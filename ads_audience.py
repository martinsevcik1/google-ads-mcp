from __future__ import annotations

import re
from typing import Any

from google.ads.googleads.errors import GoogleAdsException

from ads_core import (
    AdsError, TempIds, client_for, create_custom_plan, create_plan, fmt_id, format_ads_error, gaql_str,
    get_account, new_op, num_id, search_raw,
)

KINDS = {
    "custom_segments": ("SELECT custom_audience.id, custom_audience.name, custom_audience.type, "
                        "custom_audience.description, custom_audience.status FROM custom_audience "
                        "WHERE custom_audience.status = ENABLED",
                        lambda r: (r.custom_audience.id, r.custom_audience.name,
                                   f"{r.custom_audience.type_.name}"
                                   + (f" | {r.custom_audience.description}" if r.custom_audience.description else ""))),
    "user_lists": ("SELECT user_list.id, user_list.name, user_list.type, user_list.size_for_search, "
                   "user_list.size_for_display, user_list.membership_status FROM user_list "
                   "WHERE user_list.membership_status = OPEN",
                   lambda r: (r.user_list.id, r.user_list.name,
                              f"{r.user_list.type_.name} | vyhledávání ~{r.user_list.size_for_search}, "
                              f"obsahová síť ~{r.user_list.size_for_display}")),
    "interests": ("SELECT user_interest.user_interest_id, user_interest.name, user_interest.taxonomy_type, "
                  "user_interest.user_interest_parent FROM user_interest",
                  lambda r: (r.user_interest.user_interest_id, r.user_interest.name,
                             r.user_interest.taxonomy_type.name)),
    "life_events": ("SELECT life_event.id, life_event.name, life_event.parent FROM life_event",
                    lambda r: (r.life_event.id, r.life_event.name, "")),
    "detailed_demographics": ("SELECT detailed_demographic.id, detailed_demographic.name, "
                              "detailed_demographic.parent FROM detailed_demographic",
                              lambda r: (r.detailed_demographic.id, r.detailed_demographic.name, "")),
    "audiences": ("SELECT audience.id, audience.name, audience.description, audience.status, audience.scope "
                  "FROM audience WHERE audience.status = ENABLED",
                  lambda r: (r.audience.id, r.audience.name,
                             r.audience.scope.name + (f" | {r.audience.description}" if r.audience.description else ""))),
}


def list_audience_segments(customer_id: str, kind: str, contains: str = "", limit: int = 200) -> str:
    acc = get_account(customer_id)
    if kind not in KINDS:
        raise AdsError(f"kind je jedno z: {', '.join(KINDS)}")
    query, fmt = KINDS[kind]
    out = []
    needle = contains.strip().lower()
    for r in search_raw(acc, query):
        id_, name, extra = fmt(r)
        if needle and needle not in name.lower():
            continue
        out.append(f"{id_}  {name}" + (f"  ({extra})" if extra else ""))
    total = len(out)
    out = out[:max(1, min(limit, 2000))]
    if not out:
        return "Nic nenalezeno." + (" Názvy zájmů a událostí jsou anglicky (např. 'Dating')." if needle else "")
    tail = f"\n... celkem {total}, zobrazeno {len(out)} (zúži přes contains)" if total > len(out) else ""
    return "\n".join(out) + tail


def propose_custom_segment(customer_id: str, name: str, segment_type: str = "AUTO",
                           keywords: list[str] | None = None, urls: list[str] | None = None,
                           apps: list[str] | None = None, description: str = "",
                           existing_id: str | None = None) -> str:
    acc = get_account(customer_id)
    client = client_for(acc)
    cid = acc.customer_id
    if segment_type not in ("AUTO", "SEARCH", "INTEREST", "PURCHASE_INTENT"):
        raise AdsError("segment_type je AUTO, SEARCH, INTEREST nebo PURCHASE_INTENT.")
    kws = list(dict.fromkeys(k.strip() for k in keywords or [] if k.strip()))
    us = list(dict.fromkeys(u.strip() for u in urls or [] if u.strip()))
    ap = list(dict.fromkeys(a.strip() for a in apps or [] if a.strip()))
    if not (kws or us or ap):
        raise AdsError("Segment potřebuje aspoň jedno klíčové slovo, URL nebo aplikaci.")
    if segment_type == "SEARCH" and (us or ap):
        raise AdsError("Segment typu SEARCH (lidé, kteří hledali na Googlu) bere jen klíčová slova.")
    bad = [u for u in us if not re.match(r"^(https?://)?[\w.-]+\.\w{2,}", u)]
    if bad:
        raise AdsError(f"Neplatné URL: {', '.join(bad)}")

    svc = client.get_service("CustomAudienceService")
    op = client.get_type("CustomAudienceOperation")
    if existing_id:
        sid = num_id(existing_id, "ID segmentu")
        rows = search_raw(acc, "SELECT custom_audience.name, custom_audience.type FROM custom_audience "
                               f"WHERE custom_audience.id = {sid}")
        if not rows:
            raise AdsError(f"Vlastní segment {sid} nenalezen.")
        ca = op.update
        ca.resource_name = f"customers/{cid}/customAudiences/{sid}"
        title = f"Upravit vlastní segment „{rows[0].custom_audience.name}“"
    else:
        dup = search_raw(acc, "SELECT custom_audience.id FROM custom_audience WHERE custom_audience.name = "
                              f"{gaql_str(name)} AND custom_audience.status = ENABLED")
        if dup:
            raise AdsError(f"Segment „{name}“ už existuje (ID {dup[0].custom_audience.id}). "
                           "Pro úpravu pošli existing_id.")
        ca = op.create
        title = f"Nový vlastní segment „{name}“"
    ca.name = name
    ca.type_ = client.enums.CustomAudienceTypeEnum[segment_type]
    if description:
        ca.description = description
    MT = client.enums.CustomAudienceMemberTypeEnum
    for k in kws:
        m = client.get_type("CustomAudienceMember")
        m.member_type = MT.KEYWORD
        m.keyword = k
        ca.members.append(m)
    for u in us:
        m = client.get_type("CustomAudienceMember")
        m.member_type = MT.URL
        m.url = u
        ca.members.append(m)
    for a in ap:
        m = client.get_type("CustomAudienceMember")
        m.member_type = MT.APP
        m.app = a
        ca.members.append(m)
    if existing_id:
        from google.api_core import protobuf_helpers
        client.copy_from(op.update_mask, protobuf_helpers.field_mask(None, ca._pb))

    try:
        svc.mutate_custom_audiences(request={"customer_id": cid, "operations": [op], "validate_only": True})
    except GoogleAdsException as ex:
        return f"Google Ads návrh ODMÍTL při kontrole nanečisto - nic se nezměnilo.\n{title}\n{format_ads_error(ex)}"

    def run() -> str:
        resp = svc.mutate_custom_audiences(customer_id=cid, operations=[op])
        return f"Segment: {resp.results[0].resource_name}"

    label = {"AUTO": "zájmy nebo nákupní záměry", "SEARCH": "lidé, kteří hledali na Googlu",
             "INTEREST": "zájmy", "PURCHASE_INTENT": "nákupní záměry"}[segment_type]
    lines = [f"Typ: {label}"]
    if kws:
        lines.append(f"Klíčová slova ({len(kws)}): " + ", ".join(kws))
    if us:
        lines.append(f"Weby ({len(us)}): " + ", ".join(us))
    if ap:
        lines.append(f"Aplikace ({len(ap)}): " + ", ".join(ap))
    warn = ["Úprava nahradí všechny členy segmentu tímto seznamem."] if existing_id else []
    return create_custom_plan(acc, title, lines, run, warn, validated=True)


AGE_RANGES = {"18-24": (18, 24), "25-34": (25, 34), "35-44": (35, 44), "45-54": (45, 54),
              "55-64": (55, 64), "65+": (65, None)}


def _names(acc: Any, query: str, idf, namef) -> dict[str, str]:
    return {str(idf(r)): namef(r) for r in search_raw(acc, query)}


def propose_audience(customer_id: str, name: str, description: str = "",
                     custom_segment_ids: list[str] | None = None, user_list_ids: list[str] | None = None,
                     interest_ids: list[str] | None = None, life_event_ids: list[str] | None = None,
                     detailed_demographic_ids: list[str] | None = None, ages: list[str] | None = None,
                     genders: list[str] | None = None, parental_statuses: list[str] | None = None,
                     exclude_user_list_ids: list[str] | None = None,
                     attach_to_asset_group_ids: list[str] | None = None) -> str:
    acc = get_account(customer_id)
    client = client_for(acc)
    cid = acc.customer_id
    if not name.strip():
        raise AdsError("Publikum potřebuje název.")
    dup = search_raw(acc, f"SELECT audience.id FROM audience WHERE audience.name = {gaql_str(name)} "
                          "AND audience.status = ENABLED")
    if dup:
        raise AdsError(f"Publikum „{name}“ už existuje (ID {dup[0].audience.id}).")

    def ids(v: list[str] | None, what: str) -> list[str]:
        return list(dict.fromkeys(num_id(x, what) for x in v or []))

    cs, ul, ui = ids(custom_segment_ids, "ID segmentu"), ids(user_list_ids, "ID seznamu"), ids(interest_ids, "ID zájmu")
    le, dd = ids(life_event_ids, "ID události"), ids(detailed_demographic_ids, "ID demografie")
    ex = ids(exclude_user_list_ids, "ID seznamu")
    names: dict[str, dict[str, str]] = {}
    if cs:
        names["cs"] = _names(acc, f"SELECT custom_audience.id, custom_audience.name FROM custom_audience "
                                  f"WHERE custom_audience.id IN ({', '.join(cs)})",
                             lambda r: r.custom_audience.id, lambda r: r.custom_audience.name)
    if ul or ex:
        names["ul"] = _names(acc, f"SELECT user_list.id, user_list.name FROM user_list "
                                  f"WHERE user_list.id IN ({', '.join(ul + ex)})",
                             lambda r: r.user_list.id, lambda r: r.user_list.name)
    if ui:
        names["ui"] = _names(acc, "SELECT user_interest.user_interest_id, user_interest.name FROM user_interest "
                                  f"WHERE user_interest.user_interest_id IN ({', '.join(ui)})",
                             lambda r: r.user_interest.user_interest_id, lambda r: r.user_interest.name)
    if le:
        names["le"] = _names(acc, f"SELECT life_event.id, life_event.name FROM life_event "
                                  f"WHERE life_event.id IN ({', '.join(le)})",
                             lambda r: r.life_event.id, lambda r: r.life_event.name)
    if dd:
        names["dd"] = _names(acc, f"SELECT detailed_demographic.id, detailed_demographic.name FROM detailed_demographic "
                                  f"WHERE detailed_demographic.id IN ({', '.join(dd)})",
                             lambda r: r.detailed_demographic.id, lambda r: r.detailed_demographic.name)
    missing = [f"{k}:{i}" for k, lst in (("cs", cs), ("ul", ul + ex), ("ui", ui), ("le", le), ("dd", dd))
               for i in lst if i not in names.get(k, {})]
    if missing:
        raise AdsError("Nenalezeno (cs=vlastní segment, ul=seznam, ui=zájem, le=událost, dd=demografie): "
                       + ", ".join(missing))
    if not (cs or ul or ui or le or dd or ages or genders or parental_statuses):
        raise AdsError("Publikum potřebuje aspoň jeden segment nebo demografii.")

    tmp = TempIds()
    aud_rn = f"customers/{cid}/audiences/{tmp.next()}"
    op = new_op(client)
    a = op.audience_operation.create
    a.resource_name = aud_rn
    a.name = name.strip()
    if description:
        a.description = description
    a.scope = client.enums.AudienceScopeEnum.CUSTOMER
    lines = [f"Publikum „{name.strip()}“ (opakovaně použitelné v účtu)"]

    segs = []
    for i in cs:
        segs.append(("custom_audience", "custom_audience", f"customers/{cid}/customAudiences/{i}", f"vlastní: {names['cs'][i]}"))
    for i in ul:
        segs.append(("user_list", "user_list", f"customers/{cid}/userLists/{i}", f"seznam: {names['ul'][i]}"))
    for i in ui:
        segs.append(("user_interest", "user_interest_category", f"customers/{cid}/userInterests/{i}", f"zájem: {names['ui'][i]}"))
    for i in le:
        segs.append(("life_event", "life_event", f"customers/{cid}/lifeEvents/{i}", f"událost: {names['le'][i]}"))
    for i in dd:
        segs.append(("detailed_demographic", "detailed_demographic", f"customers/{cid}/detailedDemographics/{i}",
                     f"demografie: {names['dd'][i]}"))
    if segs:
        dim = client.get_type("AudienceDimension")
        for kind, field, rn, _ in segs:
            seg = client.get_type("AudienceSegment")
            setattr(getattr(seg, kind), field, rn)
            dim.audience_segments.segments.append(seg)
        a.dimensions.append(dim)
        lines.append("Segmenty (stačí splnit kterýkoli): " + "; ".join(s[3] for s in segs))
    if ages:
        dim = client.get_type("AudienceDimension")
        for ag in ages:
            if ag not in AGE_RANGES:
                raise AdsError(f"Věk {ag!r} - povolené: {', '.join(AGE_RANGES)}")
            lo, hi = AGE_RANGES[ag]
            s = client.get_type("AgeSegment")
            s.min_age = lo
            if hi:
                s.max_age = hi
            dim.age.age_ranges.append(s)
        a.dimensions.append(dim)
        lines.append("Věk: " + ", ".join(ages))
    if genders:
        dim = client.get_type("AudienceDimension")
        for g in genders:
            dim.gender.genders.append(client.enums.GenderTypeEnum[g])
        a.dimensions.append(dim)
        lines.append("Pohlaví: " + ", ".join(genders))
    if parental_statuses:
        dim = client.get_type("AudienceDimension")
        for p in parental_statuses:
            dim.parental_status.parental_statuses.append(client.enums.ParentalStatusTypeEnum[p])
        a.dimensions.append(dim)
        lines.append("Rodičovství: " + ", ".join(parental_statuses))
    for i in ex:
        seg = client.get_type("ExclusionSegment")
        seg.user_list.user_list = f"customers/{cid}/userLists/{i}"
        a.exclusion_dimension.exclusions.append(seg)
    if ex:
        lines.append("Vyloučit seznamy: " + ", ".join(names["ul"][i] for i in ex))
    if len(a.dimensions) > 1:
        lines.append("Mezi skupinami platí A ZÁROVEŇ (např. segment a zároveň věk).")
    ops = [op]

    for ag in attach_to_asset_group_ids or []:
        ops += _signal_ops(acc, client, num_id(ag, "ID sestavy podkladů"), aud_rn, lines)
    return create_plan(acc, f"Nové publikum „{name.strip()}“", lines, ops, labels=["publikum"] + [None] * (len(ops) - 1))


def _signal_ops(acc: Any, client: Any, ag: str, audience_rn: str, lines: list[str]) -> list[Any]:
    rows = search_raw(acc, "SELECT asset_group.name, campaign.name FROM asset_group "
                           f"WHERE asset_group.id = {ag}")
    if not rows:
        raise AdsError(f"Sestava podkladů {ag} nenalezena.")
    current = search_raw(acc, "SELECT asset_group_signal.resource_name, asset_group_signal.audience.audience "
                              f"FROM asset_group_signal WHERE asset_group.id = {ag}")
    ops = []
    replaced = 0
    for r in current:
        if r.asset_group_signal.audience.audience:
            o = new_op(client)
            o.asset_group_signal_operation.remove = r.asset_group_signal.resource_name
            ops.append(o)
            replaced += 1
    o = new_op(client)
    s = o.asset_group_signal_operation.create
    s.asset_group = f"customers/{acc.customer_id}/assetGroups/{ag}"
    s.audience.audience = audience_rn
    ops.append(o)
    lines.append(f"Signál pro sestavu „{rows[0].asset_group.name}“ (kampaň {rows[0].campaign.name})"
                 + (" - nahradí stávající signál publika" if replaced else ""))
    return ops


def propose_audience_signal(customer_id: str, asset_group_ids: list[str], audience_id: str) -> str:
    acc = get_account(customer_id)
    client = client_for(acc)
    aid = num_id(audience_id, "ID publika")
    rows = search_raw(acc, f"SELECT audience.name FROM audience WHERE audience.id = {aid}")
    if not rows:
        raise AdsError(f"Publikum {aid} nenalezeno.")
    lines = [f"Publikum „{rows[0].audience.name}“"]
    ops = []
    for ag in asset_group_ids:
        ops += _signal_ops(acc, client, num_id(ag, "ID sestavy podkladů"),
                           f"customers/{acc.customer_id}/audiences/{aid}", lines)
    return create_plan(acc, "Signál publika", lines, ops)
