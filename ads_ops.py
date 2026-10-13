from __future__ import annotations

import re
from typing import Any, Literal

from ads_core import (
    Account, AdsError, client_for, create_plan, gaql_str, get_account, new_op, num_id,
    search_raw, set_update_mask,
)

MatchType = Literal["EXACT", "PHRASE", "BROAD"]

ENTITY_LABEL = {"campaign": "Kampaň", "ad_group": "Sestava", "ad": "Reklama", "keyword": "Klíčové slovo"}


def _clean_keyword(text: str) -> str:
    t = re.sub(r"\s+", " ", str(text)).strip()
    t = t.strip("[]\"")
    if not t:
        raise AdsError("Prázdné klíčové slovo.")
    if len(t) > 80:
        raise AdsError(f"Klíčové slovo je delší než 80 znaků: {t!r}")
    if len(t.split(" ")) > 10:
        raise AdsError(f"Klíčové slovo má víc než 10 slov: {t!r}")
    return t


def _kw_label(text: str, match: str) -> str:
    return {"EXACT": f"[{text}]", "PHRASE": f"\"{text}\"", "BROAD": text}.get(match, text)


def _ids_in(ids: list[str]) -> str:
    return ", ".join(ids)


def _rn_in(names: list[str]) -> str:
    return ", ".join(gaql_str(n) for n in names)


def propose_status_change(customer_id: str, entity: str, ids: list[str], status: str) -> str:
    acc = get_account(customer_id)
    client = client_for(acc)
    cid = acc.customer_id
    if status not in ("ENABLED", "PAUSED"):
        raise AdsError("Povolený stav je jen ENABLED nebo PAUSED. Mazání MCP nedělá.")
    if not ids:
        raise AdsError("Chybí ID.")

    found: dict[str, tuple[str, str]] = {}
    if entity == "campaign":
        keys = [num_id(i, "ID kampaně") for i in ids]
        for r in search_raw(acc, f"SELECT campaign.id, campaign.name, campaign.status FROM campaign "
                                 f"WHERE campaign.id IN ({_ids_in(keys)})"):
            found[str(r.campaign.id)] = (f"„{r.campaign.name}“", r.campaign.status.name)
    elif entity == "ad_group":
        keys = [num_id(i, "ID sestavy") for i in ids]
        for r in search_raw(acc, f"SELECT ad_group.id, ad_group.name, ad_group.status, campaign.name "
                                 f"FROM ad_group WHERE ad_group.id IN ({_ids_in(keys)})"):
            found[str(r.ad_group.id)] = (f"„{r.ad_group.name}“ (kampaň {r.campaign.name})",
                                        r.ad_group.status.name)
    elif entity in ("ad", "keyword"):
        keys = []
        for i in ids:
            m = re.fullmatch(r"\s*(\d+)\s*~\s*(\d+)\s*", str(i))
            if not m:
                raise AdsError(f"ID pro {entity} musí mít tvar ID_sestavy~ID_{'reklamy' if entity == 'ad' else 'kritéria'}: {i!r}")
            keys.append(f"{m.group(1)}~{m.group(2)}")
        if entity == "ad":
            rns = [f"customers/{cid}/adGroupAds/{k}" for k in keys]
            q = (f"SELECT ad_group_ad.resource_name, ad_group_ad.status, ad_group_ad.ad.type, ad_group.name "
                 f"FROM ad_group_ad WHERE ad_group_ad.resource_name IN ({_rn_in(rns)})")
            for r in search_raw(acc, q):
                k = r.ad_group_ad.resource_name.split("/")[-1]
                found[k] = (f"{r.ad_group_ad.ad.type_.name} v sestavě „{r.ad_group.name}“",
                            r.ad_group_ad.status.name)
        else:
            rns = [f"customers/{cid}/adGroupCriteria/{k}" for k in keys]
            q = (f"SELECT ad_group_criterion.resource_name, ad_group_criterion.status, "
                 f"ad_group_criterion.negative, ad_group_criterion.keyword.text, "
                 f"ad_group_criterion.keyword.match_type, ad_group.name "
                 f"FROM ad_group_criterion WHERE ad_group_criterion.resource_name IN ({_rn_in(rns)})")
            for r in search_raw(acc, q):
                c = r.ad_group_criterion
                if c.negative:
                    raise AdsError(f"{c.resource_name} je vylučující slovo - na ty stav nejde, "
                                   "použij propose_remove_negative_keywords.")
                k = c.resource_name.split("/")[-1]
                found[k] = (f"{_kw_label(c.keyword.text, c.keyword.match_type.name)} v sestavě „{r.ad_group.name}“",
                            c.status.name)
    else:
        raise AdsError("entity musí být campaign, ad_group, ad nebo keyword.")

    missing = [k for k in keys if k not in found]
    if missing:
        raise AdsError(f"V účtu {acc.name} nenalezeno: {', '.join(missing)}")

    ops, lines, skipped = [], [], []
    for k in dict.fromkeys(keys):
        label, current = found[k]
        if current == "REMOVED":
            raise AdsError(f"{ENTITY_LABEL[entity]} {label} je odstraněná, stav nejde měnit.")
        if current == status:
            skipped.append(f"{ENTITY_LABEL[entity]} {label} už je {status}")
            continue
        op = new_op(client)
        if entity == "campaign":
            sub = op.campaign_operation
            res = sub.update
            res.resource_name = f"customers/{cid}/campaigns/{k}"
            res.status = client.enums.CampaignStatusEnum[status]
        elif entity == "ad_group":
            sub = op.ad_group_operation
            res = sub.update
            res.resource_name = f"customers/{cid}/adGroups/{k}"
            res.status = client.enums.AdGroupStatusEnum[status]
        elif entity == "ad":
            sub = op.ad_group_ad_operation
            res = sub.update
            res.resource_name = f"customers/{cid}/adGroupAds/{k}"
            res.status = client.enums.AdGroupAdStatusEnum[status]
        else:
            sub = op.ad_group_criterion_operation
            res = sub.update
            res.resource_name = f"customers/{cid}/adGroupCriteria/{k}"
            res.status = client.enums.AdGroupCriterionStatusEnum[status]
        set_update_mask(client, sub, res)
        ops.append(op)
        lines.append(f"{ENTITY_LABEL[entity]} {label}: {current} → {status}")
    lines += [f"(beze změny) {s}" for s in skipped]
    verb = "Pozastavit" if status == "PAUSED" else "Zapnout"
    guard = ["enable"] if status == "ENABLED" else (["pause"] if entity in ("campaign", "ad_group") else [])
    return create_plan(acc, f"{verb}: {ENTITY_LABEL[entity].lower()} ({len(ops)}×)", lines, ops, guard=guard)


def _to_micros(amount: float) -> int:
    return int(round(float(amount) * 100)) * 10_000


def propose_budget_change(customer_id: str, campaign_id: str, daily_budget: float,
                          allow_shared: bool = False) -> str:
    acc = get_account(customer_id)
    client = client_for(acc)
    camp = num_id(campaign_id, "ID kampaně")
    if daily_budget <= 0:
        raise AdsError("Rozpočet musí být kladný.")
    rows = search_raw(acc, "SELECT campaign.name, campaign.campaign_budget, campaign_budget.amount_micros, "
                           "campaign_budget.explicitly_shared, campaign_budget.reference_count, "
                           "campaign_budget.name, customer.currency_code "
                           f"FROM campaign WHERE campaign.id = {camp}")
    if not rows:
        raise AdsError(f"Kampaň {camp} v účtu {acc.name} nenalezena.")
    r = rows[0]
    cur = r.customer.currency_code
    old = r.campaign_budget.amount_micros
    new = _to_micros(daily_budget)
    warnings = []
    if r.campaign_budget.explicitly_shared:
        msg = (f"Rozpočet „{r.campaign_budget.name}“ je sdílený mezi {r.campaign_budget.reference_count} "
               "kampaněmi - změna se projeví ve všech.")
        if not allow_shared:
            raise AdsError(msg + " Pokud to tak má být, zavolej znovu s allow_shared=true.")
        warnings.append(msg)
    if old and abs(new - old) / old > 0.5:
        warnings.append(f"Změna o {round((new - old) / old * 100)} % - velký skok.")
    if new == old:
        return create_plan(acc, "Změna denního rozpočtu", [f"Rozpočet už je {old / 1e6:.2f} {cur}"], [])

    op = new_op(client)
    sub = op.campaign_budget_operation
    res = sub.update
    res.resource_name = r.campaign.campaign_budget
    res.amount_micros = new
    set_update_mask(client, sub, res)
    line = f"Kampaň „{r.campaign.name}“: denní rozpočet {old / 1e6:,.2f} → {new / 1e6:,.2f} {cur}".replace(",", " ")
    return create_plan(acc, "Změna denního rozpočtu", [line], [op], warnings, guard=["budget"])


def propose_bidding_target(customer_id: str, campaign_id: str, target_cpa: float | None = None,
                           target_roas: float | None = None) -> str:
    acc = get_account(customer_id)
    client = client_for(acc)
    camp = num_id(campaign_id, "ID kampaně")
    if (target_cpa is None) == (target_roas is None):
        raise AdsError("Zadej právě jedno: target_cpa (v měně účtu) nebo target_roas (poměr, 4.0 = 400 %).")
    rows = search_raw(acc, "SELECT campaign.name, campaign.bidding_strategy_type, campaign.bidding_strategy, "
                           "campaign.maximize_conversions.target_cpa_micros, campaign.target_cpa.target_cpa_micros, "
                           "campaign.maximize_conversion_value.target_roas, campaign.target_roas.target_roas, "
                           f"customer.currency_code FROM campaign WHERE campaign.id = {camp}")
    if not rows:
        raise AdsError(f"Kampaň {camp} v účtu {acc.name} nenalezena.")
    r = rows[0]
    c = r.campaign
    if c.bidding_strategy:
        raise AdsError("Kampaň používá portfoliovou strategii - cíl se mění na strategii, ne na kampani. "
                       "To MCP zatím neumí.")
    bst = c.bidding_strategy_type.name
    cur = r.customer.currency_code
    op = new_op(client)
    sub = op.campaign_operation
    res = sub.update
    res.resource_name = f"customers/{acc.customer_id}/campaigns/{camp}"
    warnings = []
    if target_cpa is not None:
        if target_cpa <= 0:
            raise AdsError("Cílová CPA musí být kladná. Vypnutí cíle MCP nedělá.")
        new = _to_micros(target_cpa)
        if bst == "MAXIMIZE_CONVERSIONS":
            old = c.maximize_conversions.target_cpa_micros
            res.maximize_conversions.target_cpa_micros = new
        elif bst == "TARGET_CPA":
            old = c.target_cpa.target_cpa_micros
            res.target_cpa.target_cpa_micros = new
        else:
            raise AdsError(f"Kampaň má strategii {bst}, cílová CPA na ni nejde.")
        if not old:
            warnings.append("Kampaň zatím cílovou CPA neměla - zapnutí cíle mění chování strategie.")
        line = f"Kampaň „{c.name}“ ({bst}): cílová CPA {old / 1e6:.2f} → {new / 1e6:.2f} {cur}"
        ratio = (new - old) / old if old else 0
    else:
        if target_roas <= 0:
            raise AdsError("Cílová ROAS musí být kladná. Vypnutí cíle MCP nedělá.")
        if target_roas > 50:
            raise AdsError("target_roas se zadává jako poměr (4.0 = 400 %), ne v procentech.")
        new_r = round(float(target_roas), 4)
        if bst == "MAXIMIZE_CONVERSION_VALUE":
            old = c.maximize_conversion_value.target_roas
            res.maximize_conversion_value.target_roas = new_r
        elif bst == "TARGET_ROAS":
            old = c.target_roas.target_roas
            res.target_roas.target_roas = new_r
        else:
            raise AdsError(f"Kampaň má strategii {bst}, cílová ROAS na ni nejde.")
        if not old:
            warnings.append("Kampaň zatím cílovou ROAS neměla - zapnutí cíle mění chování strategie.")
        line = f"Kampaň „{c.name}“ ({bst}): cílová ROAS {old * 100:.0f} % → {new_r * 100:.0f} %"
        ratio = (new_r - old) / old if old else 0
    if abs(ratio) > 0.3:
        warnings.append(f"Změna cíle o {round(ratio * 100)} % - Google doporučuje měnit po menších krocích.")
    set_update_mask(client, sub, res)
    return create_plan(acc, "Změna cíle nabídkové strategie", [line], [op], warnings, guard=["bidding"])


def _negative_target(acc: Account, level: str, target_id: str) -> tuple[str, set[tuple[str, str]]]:
    tid = num_id(target_id, "ID cíle")
    existing: set[tuple[str, str]] = set()
    if level == "campaign":
        rows = search_raw(acc, f"SELECT campaign.name FROM campaign WHERE campaign.id = {tid}")
        if not rows:
            raise AdsError(f"Kampaň {tid} nenalezena.")
        label = f"kampaň „{rows[0].campaign.name}“"
        q = ("SELECT campaign_criterion.keyword.text, campaign_criterion.keyword.match_type "
             f"FROM campaign_criterion WHERE campaign.id = {tid} AND campaign_criterion.type = KEYWORD "
             "AND campaign_criterion.negative = TRUE")
        for r in search_raw(acc, q):
            existing.add((r.campaign_criterion.keyword.text.lower(), r.campaign_criterion.keyword.match_type.name))
    elif level == "ad_group":
        rows = search_raw(acc, f"SELECT ad_group.name, campaign.name FROM ad_group WHERE ad_group.id = {tid}")
        if not rows:
            raise AdsError(f"Sestava {tid} nenalezena.")
        label = f"sestava „{rows[0].ad_group.name}“ (kampaň {rows[0].campaign.name})"
        q = ("SELECT ad_group_criterion.keyword.text, ad_group_criterion.keyword.match_type "
             f"FROM ad_group_criterion WHERE ad_group.id = {tid} AND ad_group_criterion.type = KEYWORD "
             "AND ad_group_criterion.negative = TRUE")
        for r in search_raw(acc, q):
            existing.add((r.ad_group_criterion.keyword.text.lower(), r.ad_group_criterion.keyword.match_type.name))
    elif level == "shared_list":
        rows = search_raw(acc, f"SELECT shared_set.name, shared_set.type, shared_set.status FROM shared_set "
                               f"WHERE shared_set.id = {tid}")
        if not rows:
            raise AdsError(f"Sdílený seznam {tid} nenalezen.")
        if rows[0].shared_set.type_.name not in ("NEGATIVE_KEYWORDS", "ACCOUNT_LEVEL_NEGATIVE_KEYWORDS"):
            raise AdsError(f"Seznam „{rows[0].shared_set.name}“ není seznam vylučujících slov.")
        label = f"sdílený seznam „{rows[0].shared_set.name}“"
        q = ("SELECT shared_criterion.keyword.text, shared_criterion.keyword.match_type "
             f"FROM shared_criterion WHERE shared_set.id = {tid} AND shared_criterion.type = KEYWORD")
        for r in search_raw(acc, q):
            existing.add((r.shared_criterion.keyword.text.lower(), r.shared_criterion.keyword.match_type.name))
    else:
        raise AdsError("level musí být campaign, ad_group nebo shared_list.")
    return label, existing


def propose_negative_keywords(customer_id: str, level: str, target_id: str,
                              keywords: list[dict[str, str]]) -> str:
    acc = get_account(customer_id)
    client = client_for(acc)
    tid = num_id(target_id, "ID cíle")
    label, existing = _negative_target(acc, level, tid)
    ops, added, skipped = [], [], []
    seen: set[tuple[str, str]] = set()
    for kw in keywords:
        text = _clean_keyword(kw["text"])
        match = kw["match_type"].upper()
        if match not in ("EXACT", "PHRASE", "BROAD"):
            raise AdsError(f"Neplatná shoda {match!r} u {text!r}")
        key = (text.lower(), match)
        if key in existing:
            skipped.append(f"{_kw_label(text, match)} už tam je")
            continue
        if key in seen:
            continue
        seen.add(key)
        op = new_op(client)
        if level == "campaign":
            res = op.campaign_criterion_operation.create
            res.campaign = f"customers/{acc.customer_id}/campaigns/{tid}"
            res.negative = True
        elif level == "ad_group":
            res = op.ad_group_criterion_operation.create
            res.ad_group = f"customers/{acc.customer_id}/adGroups/{tid}"
            res.negative = True
        else:
            res = op.shared_criterion_operation.create
            res.shared_set = f"customers/{acc.customer_id}/sharedSets/{tid}"
        res.keyword.text = text
        res.keyword.match_type = client.enums.KeywordMatchTypeEnum[match]
        ops.append(op)
        added.append(_kw_label(text, match))
    lines = [f"Cíl: {label}", f"Přidat vylučující ({len(added)}): " + ", ".join(added)]
    if skipped:
        lines.append(f"Vynecháno ({len(skipped)}): " + ", ".join(skipped))
    return create_plan(acc, f"Přidat vylučující slova ({len(added)}×)", lines, ops)


def propose_remove_negative_keywords(customer_id: str, resource_names: list[str]) -> str:
    acc = get_account(customer_id)
    client = client_for(acc)
    cid = acc.customer_id
    groups: dict[str, list[str]] = {"campaignCriteria": [], "adGroupCriteria": [], "sharedCriteria": []}
    for rn in dict.fromkeys(n.strip() for n in resource_names):
        m = re.fullmatch(r"customers/(\d+)/(campaignCriteria|adGroupCriteria|sharedCriteria)/\d+~\d+", rn)
        if not m:
            raise AdsError(f"Nerozpoznaný resource_name: {rn!r}")
        if m.group(1) != cid:
            raise AdsError(f"{rn} nepatří do účtu {acc.name}.")
        groups[m.group(2)].append(rn)

    ops, lines, found = [], [], set()
    if groups["campaignCriteria"]:
        q = ("SELECT campaign_criterion.resource_name, campaign_criterion.negative, campaign_criterion.type, "
             "campaign_criterion.keyword.text, campaign_criterion.keyword.match_type, campaign.name "
             f"FROM campaign_criterion WHERE campaign_criterion.resource_name IN ({_rn_in(groups['campaignCriteria'])})")
        for r in search_raw(acc, q):
            c = r.campaign_criterion
            if not c.negative or c.type_.name != "KEYWORD":
                raise AdsError(f"{c.resource_name} není vylučující klíčové slovo - MCP maže jen ta.")
            found.add(c.resource_name)
            op = new_op(client)
            op.campaign_criterion_operation.remove = c.resource_name
            ops.append(op)
            lines.append(f"Kampaň „{r.campaign.name}“: odebrat {_kw_label(c.keyword.text, c.keyword.match_type.name)}")
    if groups["adGroupCriteria"]:
        q = ("SELECT ad_group_criterion.resource_name, ad_group_criterion.negative, ad_group_criterion.type, "
             "ad_group_criterion.keyword.text, ad_group_criterion.keyword.match_type, ad_group.name "
             f"FROM ad_group_criterion WHERE ad_group_criterion.resource_name IN ({_rn_in(groups['adGroupCriteria'])})")
        for r in search_raw(acc, q):
            c = r.ad_group_criterion
            if not c.negative or c.type_.name != "KEYWORD":
                raise AdsError(f"{c.resource_name} není vylučující klíčové slovo - MCP maže jen ta.")
            found.add(c.resource_name)
            op = new_op(client)
            op.ad_group_criterion_operation.remove = c.resource_name
            ops.append(op)
            lines.append(f"Sestava „{r.ad_group.name}“: odebrat {_kw_label(c.keyword.text, c.keyword.match_type.name)}")
    if groups["sharedCriteria"]:
        q = ("SELECT shared_criterion.resource_name, shared_criterion.type, shared_criterion.keyword.text, "
             "shared_criterion.keyword.match_type, shared_set.name, shared_set.type "
             f"FROM shared_criterion WHERE shared_criterion.resource_name IN ({_rn_in(groups['sharedCriteria'])})")
        for r in search_raw(acc, q):
            c = r.shared_criterion
            if (r.shared_set.type_.name not in ("NEGATIVE_KEYWORDS", "ACCOUNT_LEVEL_NEGATIVE_KEYWORDS")
                    or c.type_.name != "KEYWORD"):
                raise AdsError(f"{c.resource_name} není vylučující slovo ve sdíleném seznamu.")
            found.add(c.resource_name)
            op = new_op(client)
            op.shared_criterion_operation.remove = c.resource_name
            ops.append(op)
            lines.append(f"Seznam „{r.shared_set.name}“: odebrat {_kw_label(c.keyword.text, c.keyword.match_type.name)}")
    missing = [rn for g in groups.values() for rn in g if rn not in found]
    if missing:
        raise AdsError("Nenalezeno: " + ", ".join(missing))
    return create_plan(acc, f"Odebrat vylučující slova ({len(ops)}×)", lines, ops, guard=["remove_negatives"])


def parse_keyword(kw: dict[str, Any]) -> tuple[str, str]:
    text = _clean_keyword(kw["text"])
    match = str(kw["match_type"]).upper()
    if match not in ("EXACT", "PHRASE", "BROAD"):
        raise AdsError(f"Neplatná shoda {match!r} u {text!r}")
    return text, match


def kw_op(client: Any, ad_group_rn: str, text: str, match: str, status: str = "ENABLED",
          max_cpc: float | None = None, final_url: str | None = None) -> Any:
    op = new_op(client)
    res = op.ad_group_criterion_operation.create
    res.ad_group = ad_group_rn
    res.status = client.enums.AdGroupCriterionStatusEnum[status]
    res.keyword.text = text
    res.keyword.match_type = client.enums.KeywordMatchTypeEnum[match]
    if max_cpc:
        res.cpc_bid_micros = _to_micros(max_cpc)
    if final_url:
        res.final_urls.append(final_url)
    return op


def negative_kw_op(client: Any, campaign_rn: str, text: str, match: str) -> Any:
    op = new_op(client)
    res = op.campaign_criterion_operation.create
    res.campaign = campaign_rn
    res.negative = True
    res.keyword.text = text
    res.keyword.match_type = client.enums.KeywordMatchTypeEnum[match]
    return op

def propose_keywords(customer_id: str, ad_group_id: str, keywords: list[dict[str, Any]],
                     status: str = "ENABLED", final_url: str | None = None) -> str:
    acc = get_account(customer_id)
    client = client_for(acc)
    ag = num_id(ad_group_id, "ID sestavy")
    if status not in ("ENABLED", "PAUSED"):
        raise AdsError("status musí být ENABLED nebo PAUSED.")
    rows = search_raw(acc, f"SELECT ad_group.name, campaign.name, customer.currency_code FROM ad_group "
                           f"WHERE ad_group.id = {ag}")
    if not rows:
        raise AdsError(f"Sestava {ag} nenalezena.")
    cur = rows[0].customer.currency_code
    label = f"sestava „{rows[0].ad_group.name}“ (kampaň {rows[0].campaign.name})"
    existing = {
        (r.ad_group_criterion.keyword.text.lower(), r.ad_group_criterion.keyword.match_type.name)
        for r in search_raw(acc, "SELECT ad_group_criterion.keyword.text, ad_group_criterion.keyword.match_type "
                                 f"FROM ad_group_criterion WHERE ad_group.id = {ag} AND ad_group_criterion.type = KEYWORD "
                                 "AND ad_group_criterion.negative = FALSE AND ad_group_criterion.status != REMOVED")
    }
    ops, added, skipped, seen = [], [], [], set()
    for kw in keywords:
        text = _clean_keyword(kw["text"])
        match = str(kw["match_type"]).upper()
        if match not in ("EXACT", "PHRASE", "BROAD"):
            raise AdsError(f"Neplatná shoda {match!r} u {text!r}")
        key = (text.lower(), match)
        if key in existing:
            skipped.append(_kw_label(text, match))
            continue
        if key in seen:
            continue
        seen.add(key)
        op = kw_op(client, f"customers/{acc.customer_id}/adGroups/{ag}", text, match, status,
                   kw.get("max_cpc"), final_url)
        desc = _kw_label(text, match)
        if kw.get("max_cpc"):
            desc += f" (max CPC {float(kw['max_cpc']):.2f} {cur})"
        ops.append(op)
        added.append(desc)
    lines = [f"Cíl: {label}", f"Stav nových slov: {status}", f"Přidat ({len(added)}): " + ", ".join(added)]
    if final_url:
        lines.append(f"Vlastní cílová URL: {final_url}")
    if skipped:
        lines.append(f"Vynecháno, už existuje ({len(skipped)}): " + ", ".join(skipped))
    guard = ["bidding"] if any(kw.get("max_cpc") for kw in keywords) else []
    return create_plan(acc, f"Přidat klíčová slova ({len(added)}×)", lines, ops, guard=guard)


HEADLINE_PINS = {"HEADLINE_1", "HEADLINE_2", "HEADLINE_3"}
DESC_PINS = {"DESCRIPTION_1", "DESCRIPTION_2"}


def validate_rsa(headlines: list[dict[str, Any]], descriptions: list[dict[str, Any]], final_url: str,
                 path1: str = "", path2: str = "") -> None:
    if not 3 <= len(headlines) <= 15:
        raise AdsError(f"Nadpisů musí být 3-15, je jich {len(headlines)}.")
    if not 2 <= len(descriptions) <= 4:
        raise AdsError(f"Popisků musí být 2-4, je jich {len(descriptions)}.")
    if not re.match(r"^https?://", final_url or ""):
        raise AdsError("final_url musí začínat http:// nebo https://")
    problems = []
    for h in headlines:
        if len(h["text"]) > 30:
            problems.append(f"nadpis má {len(h['text'])} znaků (max 30): {h['text']!r}")
        if h.get("pin") and h["pin"] not in HEADLINE_PINS:
            problems.append(f"neplatné připnutí nadpisu {h['pin']!r}")
    for d in descriptions:
        if len(d["text"]) > 90:
            problems.append(f"popisek má {len(d['text'])} znaků (max 90): {d['text']!r}")
        if d.get("pin") and d["pin"] not in DESC_PINS:
            problems.append(f"neplatné připnutí popisku {d['pin']!r}")
    for p in (path1, path2):
        if p and len(p) > 15:
            problems.append(f"cesta {p!r} má víc než 15 znaků")
    if path2 and not path1:
        problems.append("path2 nejde bez path1")
    texts = [h["text"].strip().lower() for h in headlines]
    if len(set(texts)) != len(texts):
        problems.append("nadpisy obsahují duplicity")
    if problems:
        raise AdsError("RSA neprošla kontrolou:\n- " + "\n- ".join(problems))


def rsa_op(client: Any, ad_group_rn: str, headlines: list[dict[str, Any]], descriptions: list[dict[str, Any]],
           final_url: str, path1: str = "", path2: str = "", status: str = "PAUSED") -> Any:
    op = new_op(client)
    res = op.ad_group_ad_operation.create
    res.ad_group = ad_group_rn
    res.status = client.enums.AdGroupAdStatusEnum[status]
    ad = res.ad
    ad.final_urls.append(final_url)
    rsa = ad.responsive_search_ad
    for items, target in ((headlines, rsa.headlines), (descriptions, rsa.descriptions)):
        for item in items:
            asset = client.get_type("AdTextAsset")
            asset.text = item["text"].strip()
            if item.get("pin"):
                asset.pinned_field = client.enums.ServedAssetFieldTypeEnum[item["pin"]]
            target.append(asset)
    if path1:
        rsa.path1 = path1
    if path2:
        rsa.path2 = path2
    return op


def rsa_lines(headlines: list[dict[str, Any]], descriptions: list[dict[str, Any]], final_url: str,
              path1: str = "", path2: str = "") -> list[str]:
    lines = [f"URL: {final_url}" + (f" | cesta: /{path1}" + (f"/{path2}" if path2 else "") if path1 else "")]
    lines += [f"N{i + 1} ({len(h['text'])}): {h['text']}" + (f" [📌 {h['pin']}]" if h.get("pin") else "")
              for i, h in enumerate(headlines)]
    lines += [f"P{i + 1} ({len(d['text'])}): {d['text']}" + (f" [📌 {d['pin']}]" if d.get("pin") else "")
              for i, d in enumerate(descriptions)]
    return lines


def propose_rsa(customer_id: str, ad_group_id: str, headlines: list[dict[str, Any]],
                descriptions: list[dict[str, Any]], final_url: str, path1: str = "", path2: str = "",
                status: str = "PAUSED") -> str:
    acc = get_account(customer_id)
    client = client_for(acc)
    ag = num_id(ad_group_id, "ID sestavy")
    if status not in ("ENABLED", "PAUSED"):
        raise AdsError("status musí být ENABLED nebo PAUSED.")
    validate_rsa(headlines, descriptions, final_url, path1, path2)
    rows = search_raw(acc, f"SELECT ad_group.name, campaign.name FROM ad_group WHERE ad_group.id = {ag}")
    if not rows:
        raise AdsError(f"Sestava {ag} nenalezena.")
    op = rsa_op(client, f"customers/{acc.customer_id}/adGroups/{ag}", headlines, descriptions,
                final_url, path1, path2, status)
    lines = [f"Sestava „{rows[0].ad_group.name}“ (kampaň {rows[0].campaign.name}), stav {status}"]
    lines += rsa_lines(headlines, descriptions, final_url, path1, path2)
    return create_plan(acc, "Nová RSA reklama", lines, [op])


def propose_update_rsa(customer_id: str, ad_id: str, headlines: list[dict[str, Any]] | None = None,
                       descriptions: list[dict[str, Any]] | None = None, final_url: str | None = None,
                       path1: str | None = None, path2: str | None = None) -> str:
    acc = get_account(customer_id)
    client = client_for(acc)
    aid = num_id(ad_id, "ID reklamy")
    rows = search_raw(acc, "SELECT ad_group_ad.ad.id, ad_group_ad.ad.type, ad_group_ad.status, "
                           "ad_group_ad.ad.responsive_search_ad.headlines, "
                           "ad_group_ad.ad.responsive_search_ad.descriptions, "
                           "ad_group_ad.ad.responsive_search_ad.path1, ad_group_ad.ad.responsive_search_ad.path2, "
                           "ad_group_ad.ad.final_urls, ad_group.name, campaign.name "
                           f"FROM ad_group_ad WHERE ad_group_ad.ad.id = {aid}")
    if not rows:
        raise AdsError(f"Reklama {aid} v účtu {acc.name} nenalezena.")
    r = rows[0]
    ad = r.ad_group_ad.ad
    if ad.type_.name != "RESPONSIVE_SEARCH_AD":
        raise AdsError(f"Reklama {aid} je {ad.type_.name}, upravit jde jen RSA.")
    rsa = ad.responsive_search_ad

    def to_items(assets: Any) -> list[dict[str, Any]]:
        out = []
        for a in assets:
            pin = a.pinned_field.name if a.pinned_field.name not in ("UNSPECIFIED", "UNKNOWN") else None
            out.append({"text": a.text, "pin": pin})
        return out

    old_h, old_d = to_items(rsa.headlines), to_items(rsa.descriptions)
    old_url = ad.final_urls[0] if ad.final_urls else ""
    new_h = headlines if headlines is not None else old_h
    new_d = descriptions if descriptions is not None else old_d
    new_url = final_url if final_url is not None else old_url
    new_p1 = path1 if path1 is not None else rsa.path1
    new_p2 = path2 if path2 is not None else rsa.path2
    validate_rsa(new_h, new_d, new_url, new_p1, new_p2)

    op = new_op(client)
    sub = op.ad_operation
    res = sub.update
    res.resource_name = f"customers/{acc.customer_id}/ads/{aid}"
    changed = []
    for items, old, target, label in ((headlines, old_h, res.responsive_search_ad.headlines, "Nadpisy"),
                                      (descriptions, old_d, res.responsive_search_ad.descriptions, "Popisky")):
        if items is None or items == old:
            continue
        for item in items:
            asset = client.get_type("AdTextAsset")
            asset.text = item["text"].strip()
            if item.get("pin"):
                asset.pinned_field = client.enums.ServedAssetFieldTypeEnum[item["pin"]]
            target.append(asset)
        old_set = {(o["text"], o.get("pin")) for o in old}
        new_set = {(n["text"].strip(), n.get("pin")) for n in items}
        gone = [t for t, _ in sorted(old_set - new_set)]
        added = [t for t, _ in sorted(new_set - old_set)]
        changed.append(f"{label}: {len(old)} → {len(items)}")
        changed += [f"  - {t}" for t in gone] + [f"  + {t}" for t in added]
    if final_url is not None and final_url != old_url:
        res.final_urls.append(final_url)
        changed.append(f"URL: {old_url} → {final_url}")
    for name, new, old in (("path1", path1, rsa.path1), ("path2", path2, rsa.path2)):
        if new is not None and new != old:
            setattr(res.responsive_search_ad, name, new)
            changed.append(f"{name}: „{old}“ → „{new}“")
    if not changed:
        return create_plan(acc, "Úprava RSA", ["Beze změny - zadané texty odpovídají současným."], [])
    set_update_mask(client, sub, res)
    for name, new in (("path1", path1), ("path2", path2)):
        if new == "" and getattr(rsa, name):
            op.ad_operation.update_mask.paths.append(f"responsive_search_ad.{name}")
    lines = [f"RSA {aid} v sestavě „{r.ad_group.name}“ (kampaň {r.campaign.name}), stav {r.ad_group_ad.status.name}"]
    lines += changed
    lines.append("Výsledná podoba:")
    lines += [f"  {l}" for l in rsa_lines(new_h, new_d, new_url, new_p1, new_p2)]
    return create_plan(acc, "Úprava RSA", lines, [op],
                       ["Google reklamu po úpravě znovu schvaluje. ID reklamy zůstává stejné."])
