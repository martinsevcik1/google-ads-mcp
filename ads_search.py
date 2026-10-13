from __future__ import annotations

import datetime as dt
import re
import uuid
from typing import Any

from ads_core import (
    AdsError, TempIds, client_for, create_plan, gaql_str, get_account, new_op, num_id, search_raw,
    set_update_mask,
)
from ads_ops import _kw_label, _to_micros, kw_op, negative_kw_op, parse_keyword, rsa_lines, rsa_op, validate_rsa
from ads_pmax import resolve_languages, resolve_locations, targeting_ops

SNIPPET_HEADERS = {
    "amenities": "Amenities", "vybavení": "Amenities",
    "brands": "Brands", "značky": "Brands",
    "courses": "Courses", "kurzy": "Courses",
    "degree programs": "Degree programs",
    "destinations": "Destinations", "destinace": "Destinations",
    "featured hotels": "Featured hotels",
    "insurance coverage": "Insurance coverage",
    "models": "Models", "modely": "Models",
    "neighborhoods": "Neighborhoods", "čtvrti": "Neighborhoods",
    "service catalog": "Service catalog", "services": "Service catalog", "služby": "Service catalog",
    "shows": "Shows", "styles": "Styles", "styly": "Styles", "types": "Types", "typy": "Types",
}


def _ad_group_ops(client: Any, cid: str, tmp: TempIds, campaign_rn: str, spec: dict[str, Any],
                  cur: str) -> tuple[list[Any], list[str], list[str | None]]:
    name = (spec.get("name") or "").strip()
    if not name:
        raise AdsError("Sestava potřebuje název.")
    ag_rn = f"customers/{cid}/adGroups/{tmp.next()}"
    op = new_op(client)
    ag = op.ad_group_operation.create
    ag.resource_name = ag_rn
    ag.name = name
    ag.campaign = campaign_rn
    ag.type_ = client.enums.AdGroupTypeEnum.SEARCH_STANDARD
    ag.status = client.enums.AdGroupStatusEnum[spec.get("status", "ENABLED")]
    if spec.get("max_cpc"):
        ag.cpc_bid_micros = _to_micros(spec["max_cpc"])
    ops, labels = [op], [f"sestava {name}"]
    lines = [f"Sestava „{name}“" + (f", max CPC {spec['max_cpc']:.2f} {cur}" if spec.get("max_cpc") else "")
             + (" (pozastavená)" if spec.get("status") == "PAUSED" else "")]
    seen, kws = set(), []
    for kw in spec.get("keywords") or []:
        text, match = parse_keyword(kw)
        if (text.lower(), match) in seen:
            continue
        seen.add((text.lower(), match))
        ops.append(kw_op(client, ag_rn, text, match, "ENABLED", kw.get("max_cpc"), kw.get("final_url")))
        labels.append(None)
        kws.append(_kw_label(text, match))
    if kws:
        lines.append(f"  Klíčová slova ({len(kws)}): " + ", ".join(kws))
    for i, ad in enumerate(spec.get("ads") or []):
        validate_rsa(ad["headlines"], ad["descriptions"], ad["final_url"], ad.get("path1", ""), ad.get("path2", ""))
        ops.append(rsa_op(client, ag_rn, ad["headlines"], ad["descriptions"], ad["final_url"],
                          ad.get("path1", ""), ad.get("path2", ""), "ENABLED"))
        labels.append(f"RSA {i + 1} v {name}")
        lines.append(f"  RSA {i + 1}:")
        lines += [f"    {l}" for l in rsa_lines(ad["headlines"], ad["descriptions"], ad["final_url"],
                                                 ad.get("path1", ""), ad.get("path2", ""))]
    return ops, lines, labels


def propose_search_campaign(customer_id: str, name: str, daily_budget: float, bidding: str,
                            locations: list[str], languages: list[str], max_cpc_limit: float | None = None,
                            target_cpa: float | None = None, search_partners: bool = False,
                            status: str = "PAUSED", ad_groups: list[dict[str, Any]] | None = None,
                            negative_keywords: list[dict[str, str]] | None = None) -> str:
    acc = get_account(customer_id)
    client = client_for(acc)
    cid = acc.customer_id
    if daily_budget <= 0:
        raise AdsError("Rozpočet musí být kladný.")
    if status not in ("PAUSED", "ENABLED"):
        raise AdsError("status musí být PAUSED nebo ENABLED.")
    exists = search_raw(acc, f"SELECT campaign.id FROM campaign WHERE campaign.name = {gaql_str(name)} "
                             "AND campaign.status != REMOVED")
    if exists:
        raise AdsError(f"Kampaň „{name}“ už v účtu je (ID {exists[0].campaign.id}).")
    cur = search_raw(acc, "SELECT customer.currency_code FROM customer")[0].customer.currency_code
    locs = resolve_locations(acc, locations)
    langs = resolve_languages(acc, languages)

    tmp = TempIds()
    ops: list[Any] = []
    labels: list[str | None] = []
    budget_rn = f"customers/{cid}/campaignBudgets/{tmp.next()}"
    op = new_op(client)
    b = op.campaign_budget_operation.create
    b.resource_name = budget_rn
    b.name = f"{name} | {dt.date.today():%Y-%m-%d} {uuid.uuid4().hex[:4]}"
    b.amount_micros = _to_micros(daily_budget)
    b.delivery_method = client.enums.BudgetDeliveryMethodEnum.STANDARD
    b.explicitly_shared = False
    ops.append(op)
    labels.append("rozpočet")

    camp_rn = f"customers/{cid}/campaigns/{tmp.next()}"
    op = new_op(client)
    c = op.campaign_operation.create
    c.resource_name = camp_rn
    c.name = name
    c.status = client.enums.CampaignStatusEnum[status]
    c.advertising_channel_type = client.enums.AdvertisingChannelTypeEnum.SEARCH
    c.campaign_budget = budget_rn
    c.contains_eu_political_advertising = \
        client.enums.EuPoliticalAdvertisingStatusEnum.DOES_NOT_CONTAIN_EU_POLITICAL_ADVERTISING
    c.network_settings.target_google_search = True
    c.network_settings.target_search_network = bool(search_partners)
    c.network_settings.target_content_network = False
    c.network_settings.target_partner_search_network = False
    c.geo_target_type_setting.positive_geo_target_type = client.enums.PositiveGeoTargetTypeEnum.PRESENCE
    c.geo_target_type_setting.negative_geo_target_type = client.enums.NegativeGeoTargetTypeEnum.PRESENCE
    if bidding == "MAXIMIZE_CLICKS":
        c.target_spend._pb.SetInParent()
        if max_cpc_limit:
            c.target_spend.cpc_bid_ceiling_micros = _to_micros(max_cpc_limit)
        bid_txt = "Maximalizace kliknutí" + (f", strop CPC {max_cpc_limit:.2f} {cur}" if max_cpc_limit else "")
    elif bidding == "MAXIMIZE_CONVERSIONS":
        c.maximize_conversions._pb.SetInParent()
        if target_cpa:
            c.maximize_conversions.target_cpa_micros = _to_micros(target_cpa)
        bid_txt = "Maximalizace konverzí" + (f", cílová CPA {target_cpa:.2f} {cur}" if target_cpa else "")
    elif bidding == "MANUAL_CPC":
        c.manual_cpc.enhanced_cpc_enabled = False
        c.manual_cpc._pb.SetInParent()
        bid_txt = "Ruční CPC"
    else:
        raise AdsError("bidding je MAXIMIZE_CLICKS, MAXIMIZE_CONVERSIONS nebo MANUAL_CPC.")
    ops.append(op)
    labels.append("kampaň")
    t = targeting_ops(client, camp_rn, locs, langs)
    ops += t
    labels += [None] * len(t)

    lines = [f"Kampaň „{name}“ | Vyhledávání | {status}",
             f"Rozpočet {daily_budget:.2f} {cur}/den | {bid_txt}",
             "Síť: vyhledávání Google" + (" + partneři" if search_partners else " (bez partnerů a obsahové sítě)"),
             "Lokality (přítomnost): " + ", ".join(n for _, n in locs),
             "Jazyky: " + ", ".join(n for _, n in langs)]
    negs = []
    for kw in negative_keywords or []:
        text, match = parse_keyword(kw)
        ops.append(negative_kw_op(client, camp_rn, text, match))
        labels.append(None)
        negs.append(_kw_label(text, match))
    if negs:
        lines.append(f"Vylučující slova kampaně ({len(negs)}): " + ", ".join(negs))
    for spec in ad_groups or []:
        g_ops, g_lines, g_labels = _ad_group_ops(client, cid, tmp, camp_rn, spec, cur)
        ops += g_ops
        labels += g_labels
        lines += g_lines
    return create_plan(acc, f"Nová vyhledávací kampaň „{name}“", lines, ops, labels=labels,
                       guard=["enable"] if status == "ENABLED" else [])


def propose_ad_group(customer_id: str, campaign_id: str, spec: dict[str, Any]) -> str:
    acc = get_account(customer_id)
    client = client_for(acc)
    camp = num_id(campaign_id, "ID kampaně")
    rows = search_raw(acc, "SELECT campaign.name, campaign.advertising_channel_type, customer.currency_code "
                           f"FROM campaign WHERE campaign.id = {camp}")
    if not rows:
        raise AdsError(f"Kampaň {camp} nenalezena.")
    if rows[0].campaign.advertising_channel_type.name != "SEARCH":
        raise AdsError("Sestavy s klíčovými slovy jdou jen do vyhledávací kampaně.")
    ex = search_raw(acc, f"SELECT ad_group.id FROM ad_group WHERE campaign.id = {camp} AND "
                         f"ad_group.name = {gaql_str(spec.get('name', ''))} AND ad_group.status != REMOVED")
    if ex:
        raise AdsError(f"Sestava „{spec.get('name')}“ v kampani už je (ID {ex[0].ad_group.id}).")
    tmp = TempIds()
    ops, lines, labels = _ad_group_ops(client, acc.customer_id, tmp, f"customers/{acc.customer_id}/campaigns/{camp}",
                                       spec, rows[0].customer.currency_code)
    lines.insert(0, f"Kampaň „{rows[0].campaign.name}“")
    bids = spec.get("max_cpc") or any(k.get("max_cpc") for k in spec.get("keywords") or [])
    guard = ["bidding"] if bids else []
    return create_plan(acc, f"Nová sestava „{spec.get('name')}“", lines, ops, labels=labels, guard=guard)


def propose_campaign_assets(customer_id: str, campaign_ids: list[str], sitelinks: list[dict[str, str]] | None = None,
                            callouts: list[str] | None = None, snippet: dict[str, Any] | None = None) -> str:
    acc = get_account(customer_id)
    client = client_for(acc)
    cid = acc.customer_id
    ids = [num_id(i, "ID kampaně") for i in campaign_ids]
    rows = search_raw(acc, f"SELECT campaign.id, campaign.name FROM campaign WHERE campaign.id IN ({', '.join(ids)})")
    names = {str(r.campaign.id): r.campaign.name for r in rows}
    if missing := [i for i in ids if i not in names]:
        raise AdsError(f"Kampaň nenalezena: {', '.join(missing)}")
    errs = []
    for s in sitelinks or []:
        if len(s.get("text", "")) > 25:
            errs.append(f"odkaz „{s['text']}“ má víc než 25 znaků")
        for k in ("description1", "description2"):
            if s.get(k) and len(s[k]) > 35:
                errs.append(f"popis odkazu „{s[k]}“ má víc než 35 znaků")
        if bool(s.get("description1")) != bool(s.get("description2")):
            errs.append(f"odkaz „{s.get('text')}“: popisy buď oba, nebo žádný")
        if not re.match(r"^https?://", s.get("url", "")):
            errs.append(f"odkaz „{s.get('text')}“ nemá platnou URL")
    errs += [f"heslo „{c}“ má víc než 25 znaků" for c in callouts or [] if len(c) > 25]
    header = None
    if snippet:
        header = SNIPPET_HEADERS.get(str(snippet.get("header", "")).strip().lower())
        if not header:
            errs.append(f"neznámá hlavička přehledu: {snippet.get('header')!r} "
                        f"(povolené: {', '.join(sorted(set(SNIPPET_HEADERS.values())))})")
        vals = snippet.get("values") or []
        if not 3 <= len(vals) <= 10:
            errs.append("přehled potřebuje 3-10 hodnot")
        errs += [f"hodnota „{v}“ má víc než 25 znaků" for v in vals if len(v) > 25]
    if errs:
        raise AdsError("Rozšíření neprošla kontrolou:\n- " + "\n- ".join(errs))

    tmp = TempIds()
    ops: list[Any] = []
    links: list[tuple[str, str]] = []
    lines = ["Kampaně: " + ", ".join(f"„{names[i]}“" for i in ids)]
    for s in sitelinks or []:
        rn = f"customers/{cid}/assets/{tmp.next()}"
        o = new_op(client)
        a = o.asset_operation.create
        a.resource_name = rn
        a.final_urls.append(s["url"])
        a.sitelink_asset.link_text = s["text"]
        if s.get("description1"):
            a.sitelink_asset.description1 = s["description1"]
            a.sitelink_asset.description2 = s["description2"]
        ops.append(o)
        links.append((rn, "SITELINK"))
        lines.append(f"Odkaz: {s['text']} → {s['url']}" +
                     (f" ({s['description1']} / {s['description2']})" if s.get("description1") else ""))
    for t in callouts or []:
        rn = f"customers/{cid}/assets/{tmp.next()}"
        o = new_op(client)
        o.asset_operation.create.resource_name = rn
        o.asset_operation.create.callout_asset.callout_text = t
        ops.append(o)
        links.append((rn, "CALLOUT"))
    if callouts:
        lines.append("Hesla: " + " | ".join(callouts))
    if snippet:
        rn = f"customers/{cid}/assets/{tmp.next()}"
        o = new_op(client)
        a = o.asset_operation.create
        a.resource_name = rn
        a.structured_snippet_asset.header = header
        a.structured_snippet_asset.values.extend(snippet["values"])
        ops.append(o)
        links.append((rn, "STRUCTURED_SNIPPET"))
        lines.append(f"Přehled ({header}): " + "; ".join(snippet["values"]))
    for i in ids:
        for rn, ft in links:
            o = new_op(client)
            l = o.campaign_asset_operation.create
            l.campaign = f"customers/{cid}/campaigns/{i}"
            l.asset = rn
            l.field_type = client.enums.AssetFieldTypeEnum[ft]
            ops.append(o)
    return create_plan(acc, "Rozšíření kampaní", lines, ops)


def propose_rename(customer_id: str, entity: str, entity_id: str, new_name: str) -> str:
    acc = get_account(customer_id)
    client = client_for(acc)
    eid = num_id(entity_id)
    new_name = new_name.strip()
    if not new_name:
        raise AdsError("Prázdný název.")
    table = {"campaign": ("campaign", "campaigns", "campaign_operation"),
             "ad_group": ("ad_group", "adGroups", "ad_group_operation"),
             "asset_group": ("asset_group", "assetGroups", "asset_group_operation")}
    if entity not in table:
        raise AdsError("entity je campaign, ad_group nebo asset_group.")
    res_name, path, op_field = table[entity]
    rows = search_raw(acc, f"SELECT {res_name}.name FROM {res_name} WHERE {res_name}.id = {eid}")
    if not rows:
        raise AdsError(f"{entity} {eid} nenalezeno.")
    old = getattr(rows[0], res_name).name
    op = new_op(client)
    sub = getattr(op, op_field)
    res = sub.update
    res.resource_name = f"customers/{acc.customer_id}/{path}/{eid}"
    res.name = new_name
    set_update_mask(client, sub, res)
    return create_plan(acc, "Přejmenování", [f"„{old}“ → „{new_name}“"], [op])


def propose_campaign_locations(customer_id: str, campaign_id: str, add: list[str] | None = None,
                               remove: list[str] | None = None, presence_only: bool | None = None) -> str:
    acc = get_account(customer_id)
    client = client_for(acc)
    camp = num_id(campaign_id, "ID kampaně")
    rows = search_raw(acc, "SELECT campaign_criterion.resource_name, campaign_criterion.location.geo_target_constant, "
                           "campaign_criterion.negative, campaign.name FROM campaign_criterion "
                           f"WHERE campaign.id = {camp} AND campaign_criterion.type = LOCATION")
    current = {r.campaign_criterion.location.geo_target_constant: r.campaign_criterion.resource_name
               for r in rows if not r.campaign_criterion.negative}
    cname = rows[0].campaign.name if rows else search_raw(
        acc, f"SELECT campaign.name FROM campaign WHERE campaign.id = {camp}")[0].campaign.name
    ops, lines = [], [f"Kampaň „{cname}“"]
    camp_rn = f"customers/{acc.customer_id}/campaigns/{camp}"
    if add:
        for rn, label in resolve_locations(acc, add):
            if rn in current:
                lines.append(f"= {label} už je")
                continue
            o = new_op(client)
            c = o.campaign_criterion_operation.create
            c.campaign = camp_rn
            c.location.geo_target_constant = rn
            ops.append(o)
            lines.append(f"+ {label}")
    if remove:
        for rn, label in resolve_locations(acc, remove):
            if rn not in current:
                lines.append(f"? {label} v kampani není")
                continue
            o = new_op(client)
            o.campaign_criterion_operation.remove = current[rn]
            ops.append(o)
            lines.append(f"- {label}")
    if presence_only is not None:
        o = new_op(client)
        sub = o.campaign_operation
        res = sub.update
        res.resource_name = camp_rn
        t = "PRESENCE" if presence_only else "PRESENCE_OR_INTEREST"
        res.geo_target_type_setting.positive_geo_target_type = client.enums.PositiveGeoTargetTypeEnum[t]
        set_update_mask(client, sub, res)
        ops.append(o)
        lines.append("Cílení: jen lidé v lokalitě" if presence_only else "Cílení: v lokalitě nebo se o ni zajímají")
    return create_plan(acc, "Lokality kampaně", lines, ops, guard=["targeting"])
