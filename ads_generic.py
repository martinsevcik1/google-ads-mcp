from __future__ import annotations

import csv
import datetime as dt
import json
import re
from typing import Any

import ads_api
import ads_core as core
import ads_privacy as privacy
from ads_core import AdsError, Account, fmt_id


BIDDING = {"bidding_strategy", "bidding_strategy_type", "manual_cpc", "manual_cpm", "manual_cpv", "manual_cpa",
           "maximize_conversions", "maximize_conversion_value", "target_cpa", "target_roas", "target_spend",
           "target_impression_share", "percent_cpc", "commission", "fixed_cpm", "target_cpm", "target_cpv",
           "cpc_bid_micros", "cpm_bid_micros", "cpv_bid_micros", "percent_cpc_bid_micros", "target_cpa_micros",
           "target_cpm_micros", "target_cpv_micros", "target_roas_override", "effective_target_roas",
           "bid_modifier", "fixed_cpm_micros", "portfolio_bidding_strategy", "target_cpc"}
BUDGET = {"campaign_budget", "amount_micros", "total_amount_micros", "period", "delivery_method"}
TARGETING = {"network_settings", "geo_target_type_setting", "targeting_setting", "local_campaign_setting",
             "audience_setting", "dynamic_search_ads_setting", "shopping_setting", "excluded_parent_asset_field_types",
             "frequency_caps", "video_brand_safety_suitability", "vanity_pharma", "selective_optimization"}
AUTOMATION = {"asset_automation_settings", "url_expansion_opt_out", "ai_max_setting", "brand_guidelines_enabled",
              "optimization_goal_setting", "keyword_match_type", "text_guidelines", "auto_apply"}
ROUTINE_FIELDS = {"name", "tracking_url_template", "final_url_suffix", "url_custom_parameters", "labels",
                  "final_urls", "final_mobile_urls", "path1", "path2", "resource_name", "ad", "description",
                  "text", "headlines", "descriptions"}
BY_OP = {
    "campaign_budget_operation": "budget", "book_campaigns_operation": "budget", "quote_campaigns_operation": "budget",
    "bidding_strategy_operation": "bidding", "bidding_seasonality_adjustment_operation": "bidding",
    "bidding_data_exclusion_operation": "bidding", "ad_group_bid_modifier_operation": "bidding",
    "campaign_bid_modifier_operation": "bidding",
    "conversion_action_operation": "conversions", "conversion_custom_variable_operation": "conversions",
    "conversion_goal_campaign_config_operation": "conversions", "conversion_value_rule_operation": "conversions",
    "conversion_value_rule_set_operation": "conversions", "custom_conversion_goal_operation": "conversions",
    "customer_conversion_goal_operation": "conversions", "campaign_conversion_goal_operation": "conversions",
    "remarketing_action_operation": "conversions",
    "customer_operation": "account",
    "experiment_operation": "experiments", "experiment_arm_operation": "experiments",
    "campaign_draft_operation": "experiments",
    "recommendation_subscription_operation": "automation",
    "smart_campaign_setting_operation": "settings", "campaign_group_operation": "settings",
    "asset_group_listing_group_filter_operation": "listing_groups",
    "customer_negative_criterion_operation": "targeting",
}
ROUTINE_OPS = {"ad_group_ad_label_operation", "ad_group_asset_operation", "ad_group_criterion_customizer_operation",
               "ad_group_criterion_label_operation", "ad_group_customizer_operation", "ad_group_label_operation",
               "ad_operation", "ad_parameter_operation", "asset_operation", "asset_group_asset_operation",
               "asset_group_signal_operation", "asset_set_asset_operation", "asset_set_operation",
               "audience_operation", "campaign_asset_operation", "campaign_asset_set_operation",
               "campaign_customizer_operation", "campaign_label_operation", "campaign_shared_set_operation",
               "customer_asset_operation", "customer_customizer_operation", "customer_label_operation",
               "customizer_attribute_operation", "keyword_plan_ad_group_operation",
               "keyword_plan_ad_group_keyword_operation", "keyword_plan_campaign_keyword_operation",
               "keyword_plan_campaign_operation", "keyword_plan_operation", "label_operation",
               "shared_criterion_operation", "shared_set_operation", "user_list_operation"}
ENTITY_OPS = {"campaign_operation", "ad_group_operation", "ad_group_ad_operation", "ad_group_criterion_operation",
              "campaign_criterion_operation", "asset_group_operation"}


def _top(paths: list[str]) -> set[str]:
    return {p.split(".")[0] for p in paths}


def classify(op: str, kind: str, res: dict[str, Any], paths: list[str]) -> list[str]:
    g: list[str] = []
    if kind == "remove":
        return ["listing_groups"] if op == "asset_group_listing_group_filter_operation" else ["remove"]
    status = res.get("status")
    if status == "REMOVED":
        g.append("remove")
    if kind == "update" and status == "ENABLED":
        g.append("enable")
    if kind == "update" and status == "PAUSED" and op in ("campaign_operation", "ad_group_operation",
                                                           "asset_group_operation"):
        g.append("pause")
    if kind == "create" and op in ("campaign_operation", "asset_group_operation") and status != "PAUSED":
        g.append("enable")
    if op in BY_OP:
        cat = BY_OP[op]
        if not (op == "campaign_budget_operation" and kind == "create"):
            g.append(cat)
        return list(dict.fromkeys(g))
    if op in ROUTINE_OPS:
        return list(dict.fromkeys(g))
    fields = _top(paths) if kind == "update" else set(res)
    if op in ("ad_group_criterion_operation", "campaign_criterion_operation"):
        if "listing_group" in res:
            g.append("listing_groups")
        elif res.get("negative"):
            pass
        elif kind == "create" and "keyword" in res and op == "ad_group_criterion_operation":
            if fields & BIDDING:
                g.append("bidding")
        elif kind == "create":
            g.append("targeting")
            if fields & BIDDING:
                g.append("bidding")
        if kind == "update":
            if fields & BIDDING:
                g.append("bidding")
            if fields - BIDDING - ROUTINE_FIELDS - {"status"}:
                g.append("targeting")
        return list(dict.fromkeys(g))
    if op in ENTITY_OPS:
        if fields & BIDDING and not (kind == "create" and op in ("campaign_operation",)):
            g.append("bidding")
        if kind == "update":
            if fields & BUDGET:
                g.append("budget")
            if fields & TARGETING:
                g.append("targeting")
            if fields & AUTOMATION:
                g.append("automation")
            rest = fields - BIDDING - BUDGET - TARGETING - AUTOMATION - ROUTINE_FIELDS - {"status"}
            if rest == {"contains_eu_political_advertising"} and \
                    res.get("contains_eu_political_advertising") == "DOES_NOT_CONTAIN_EU_POLITICAL_ADVERTISING":
                rest = set()
            if rest:
                g.append("settings")
        return list(dict.fromkeys(g))
    g.append("settings")
    return list(dict.fromkeys(g))


def snake(k: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", k).lower()


def _paths(d: Any, pre: str = "") -> list[str]:
    out: list[str] = []
    if not isinstance(d, dict):
        return [pre] if pre else []
    if not d and pre:
        return [pre]
    for k, v in d.items():
        sk = snake(k)
        if sk == "resource_name" and not pre:
            continue
        p = f"{pre}.{sk}" if pre else sk
        if isinstance(v, dict) and v:
            out += _paths(v, p)
        else:
            out.append(p)
    return out


def check_customers(acc: Account, obj: Any) -> None:
    def walk(v: Any) -> None:
        if isinstance(v, str):
            for cid in re.findall(r"customers/(\d+)", v):
                if cid != acc.customer_id:
                    raise AdsError(f"Operace odkazuje na cizí účet {cid} (pracuješ v {fmt_id(acc.customer_id)}). "
                                   "Zápis do jiného účtu z jednoho plánu MCP nepovolí.")
        elif isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)
    walk(obj)


def to_plain(msg: Any) -> Any:
    return json.loads(type(msg).to_json(msg, use_integers_for_enums=False, preserving_proto_field_name=True,
                                        always_print_fields_with_no_presence=False))


def add_units(obj: Any) -> Any:
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            out[k] = add_units(v)
            if k.endswith("_micros"):
                try:
                    out[k[:-7]] = round(int(v) / 1_000_000, 2)
                except (TypeError, ValueError):
                    pass
        return out
    if isinstance(obj, list):
        return [add_units(x) for x in obj]
    return obj


def _load_list(text: str) -> list[Any]:
    try:
        data = json.loads(text)
    except ValueError as ex:
        raise AdsError(f"Neplatný JSON: {ex}") from ex
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        raise AdsError("Čekám JSON pole operací.")
    return data


def propose_mutate(customer_id: str, operations_json: str, title: str = "", reason: str = "") -> str:
    acc = core.get_account(customer_id)
    raw_ops = _load_list(operations_json)
    if not raw_ops:
        raise AdsError("Žádné operace.")
    if len(raw_ops) > core.MAX_OPS_PER_PLAN:
        raise AdsError(f"Max {core.MAX_OPS_PER_PLAN} operací v plánu.")
    client = core.client_for(acc)
    MO = type(client.get_type("MutateOperation"))
    ops, lines, labels, guard, warnings = [], [], [], [], []
    counts: dict[str, int] = {}
    for i, raw in enumerate(raw_ops, 1):
        if not isinstance(raw, dict) or len(raw) != 1:
            raise AdsError(f"Operace #{i}: čekám objekt s jedním klíčem typu operace, např. "
                           '{"campaign_operation": {...}}. Seznam typů: api_catalog("operations").')
        key = next(iter(raw))
        op_name = snake(key)
        body = dict(raw[key] or {})
        check_customers(acc, body)
        mask = body.pop("update_mask", None) or body.pop("updateMask", None)
        kinds = [k for k in ("create", "update", "remove") if k in body]
        if len(kinds) != 1:
            raise AdsError(f"Operace #{i} ({op_name}): uveď právě jedno z create / update / remove.")
        kind = kinds[0]
        try:
            op = MO.from_json(json.dumps({op_name: body}), ignore_unknown_fields=False)
        except Exception as ex:
            msg = str(ex).split("Available Fields")[0].strip()
            raise AdsError(f"Operace #{i} ({op_name}) nejde sestavit: {msg}\nNápověda: api_operation_help(\"{op_name}\")"
                           ) from ex
        paths: list[str] = []
        if kind == "update":
            paths = [snake(p.strip()) for p in (mask.split(",") if isinstance(mask, str) else (mask or []))
                     if p.strip()] if mask else _paths(body["update"])
            if not paths:
                raise AdsError(f"Operace #{i} ({op_name}): update bez měněných polí.")
            getattr(op, op_name).update_mask.paths.extend(paths)
        plain = to_plain(op).get(op_name, {})
        res = plain.get(kind) if kind != "remove" else {}
        res = res if isinstance(res, dict) else {}
        g = classify(op_name, kind, res, paths)
        guard += g
        if op_name == "campaign_operation" and kind == "create" and not res.get("contains_eu_political_advertising"):
            warnings.append(f"Operace #{i}: nová kampaň bez contains_eu_political_advertising - Google ji odmítne.")
        rn = plain.get("remove") if kind == "remove" else res.get("resource_name", "")
        detail = {k: v for k, v in res.items() if k != "resource_name"}
        dtxt = json.dumps(detail, ensure_ascii=False)
        dtxt = re.sub(r'"[A-Za-z0-9+/=]{200,}"', '"<data>"', dtxt)
        short = op_name.replace("_operation", "")
        counts[f"{short} {kind}"] = counts.get(f"{short} {kind}", 0) + 1
        if len(lines) < 60:
            lines.append(f"#{i} {short} {kind} {rn or ''}" + (f" | {', '.join(paths)}" if paths else "")
                         + (f" | {dtxt[:260]}{'...' if len(dtxt) > 260 else ''}" if detail else "")
                         + (f" [chráněné: {', '.join(g)}]" if g else ""))
        labels.append(f"{short} {kind}")
        ops.append(op)
    if len(raw_ops) > 60:
        lines.append(f"... a dalších {len(raw_ops) - 60} operací")
    lines.insert(0, "Souhrn: " + ", ".join(f"{k} {v}×" for k, v in counts.items()))
    if reason:
        lines.insert(1, f"Důvod: {reason}")
    t = title or ("Změny v účtu: " + ", ".join(f"{k} {v}×" for k, v in list(counts.items())[:4]))
    return core.create_plan(acc, t, lines, ops, warnings, labels=labels, guard=guard)


BLOCKED_SERVICES = {
    "AccountBudgetProposalService": "fakturace a rozpočty účtu", "AccountLinkService": "propojení účtů",
    "BillingSetupService": "fakturace", "CustomerClientLinkService": "vazby MCC",
    "CustomerManagerLinkService": "vazby MCC", "CustomerUserAccessService": "uživatelské přístupy",
    "CustomerUserAccessInvitationService": "pozvánky uživatelů", "MultiPartyAuthReviewService": "schvalování přístupů",
    "IncentiveService": "promo kredity", "ProductLinkInvitationService": "pozvánky k propojení",
    "DataLinkService": "datová propojení", "ThirdPartyAppAnalyticsLinkService": "propojení analytiky",
    "CustomerSkAdNetworkConversionValueSchemaService": "SKAdNetwork", "ReservationService": "rezervace kampaní",
    "LocalServicesLeadService": "místní služby", "BatchJobService": "dávkové úlohy",
    "YouTubeVideoUploadService": "nahrávání videí má vlastní nástroj propose_video_upload",
    "IdentityVerificationService": "ověření identity inzerenta", "PaymentsAccountService": "platební účty",
}
BLOCKED_METHODS = {"CustomerService.create_customer_client": "zakládání nových účtů",
                   "GoogleAdsService.mutate": "zápis přes propose_mutate",
                   "GoogleAdsService.search": "čtení přes run_gaql / export_gaql",
                   "GoogleAdsService.search_stream": "čtení přes run_gaql / export_gaql"}
READ_PREFIX = ("generate_", "list_", "suggest_", "get_", "search")
READ_EXCEPT = {"BlockedNothing"}
SERVICE_GUARD = {"RecommendationService": "recommendations", "ConversionUploadService": "conversions",
                 "ConversionAdjustmentUploadService": "conversions", "OfflineUserDataJobService": "user_data",
                 "UserDataService": "user_data", "ExperimentService": "experiments",
                 "CampaignDraftService": "experiments", "AutomaticallyCreatedAssetRemovalService": "remove",
                 "ProductLinkService": "account", "CustomerService": "account"}
METHOD_GUARD = {"AdGroupAdService.remove_automatically_created_assets": "remove"}
READ_ONLY_EXTRA = {"ShareablePreviewService.generate_shareable_previews", "AssetGenerationService.generate_text",
                   "AssetGenerationService.generate_images"}


def _resolve_service(service: str, method: str) -> tuple[str, str]:
    si = ads_api.service_index()
    s = service.strip()
    cand = s if s in si else ads_api.camel(s) if ads_api.camel(s) in si else None
    if cand is None:
        low = s.lower().replace("_", "").replace("service", "")
        cand = next((k for k in si if k.lower().replace("service", "") == low), None)
    if cand is None:
        raise AdsError(f"Služba {service} neexistuje. Seznam: api_catalog(\"services\").")
    m = snake(method.strip()) if not method.islower() else method.strip()
    if m not in si[cand]:
        raise AdsError(f"{cand} nemá metodu {method}. Metody: {', '.join(si[cand])}")
    return cand, m


def _is_read(svc: str, m: str) -> bool:
    if f"{svc}.{m}" in READ_ONLY_EXTRA:
        return True
    if m.startswith("mutate"):
        return False
    return m.startswith(READ_PREFIX)


def _build_request(acc: Account, svc: str, m: str, request_json: str) -> Any:
    req_name = ads_api.camel(m) + "Request"
    cls = ads_api.type_index().get(req_name)
    if cls is None:
        raise AdsError(f"Nenašel jsem typ požadavku {req_name}.")
    data = json.loads(request_json or "{}")
    if not isinstance(data, dict):
        raise AdsError("request_json musí být JSON objekt.")
    check_customers(acc, data)
    given = data.get("customer_id") or data.get("customerId")
    if given and re.sub(r"\D", "", str(given)) != acc.customer_id:
        raise AdsError("customer_id v požadavku nesedí s účtem.")
    try:
        req = cls.from_json(json.dumps(data), ignore_unknown_fields=False)
    except Exception as ex:
        raise AdsError(f"Požadavek nejde sestavit: {str(ex).split('Available Fields')[0]}\n"
                       f"Nápověda: api_type_help(\"{req_name}\")") from ex
    if "customer_id" in cls.meta.fields:
        req.customer_id = acc.customer_id
    return req


def _response_to_obj(resp: Any, max_items: int) -> tuple[Any, bool]:
    import proto
    if isinstance(resp, proto.Message):
        return add_units(to_plain(resp)), False
    if hasattr(resp, "__iter__"):
        items, cut = [], False
        for it in resp:
            if len(items) >= max_items:
                cut = True
                break
            items.append(add_units(to_plain(it)) if isinstance(it, proto.Message) else str(it))
        return items, cut
    return str(resp), False


def _save(acc: Account, svc: str, m: str, obj: Any) -> str:
    d = core.state_dir(acc, "api_vystupy")
    p = d / f"{dt.datetime.now():%Y-%m-%d_%H%M%S}_{svc}_{m}.json"
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    return str(p)


def call_service(customer_id: str, service: str, method: str, request_json: str = "{}", max_items: int = 1000,
                 max_chars: int = 15000) -> str:
    acc = core.get_account(customer_id)
    svc, m = _resolve_service(service, method)
    key = f"{svc}.{m}"
    if key in BLOCKED_METHODS:
        raise AdsError(f"{key}: {BLOCKED_METHODS[key]}.")
    if not _is_read(svc, m):
        raise AdsError(f"{key} mění data - použij propose_service_call (nebo propose_mutate pro běžné změny).")
    privacy.check_service(svc)
    req = _build_request(acc, svc, m, request_json)
    client = core.client_for(acc)
    resp = getattr(client.get_service(svc), m)(request=req)
    obj, cut = _response_to_obj(resp, max(1, min(int(max_items), 100000)))
    path = _save(acc, svc, m, obj)
    txt = json.dumps(obj, ensure_ascii=False)
    lim = max(2000, min(int(max_chars), 80000))
    head = f"{acc.name} | {key}" + (f" | položek {len(obj)}" if isinstance(obj, list) else "") + \
        (" | zkráceno na max_items" if cut else "") + f"\nCelý výsledek: {path}\n"
    return head + txt[:lim] + ("\n... (zkráceno, celé v souboru)" if len(txt) > lim else "")


def propose_service_call(customer_id: str, service: str, method: str, request_json: str = "{}",
                         reason: str = "") -> str:
    acc = core.get_account(customer_id)
    svc, m = _resolve_service(service, method)
    key = f"{svc}.{m}"
    if key in BLOCKED_METHODS:
        raise AdsError(f"{key}: {BLOCKED_METHODS[key]}.")
    if svc in BLOCKED_SERVICES and not _is_read(svc, m):
        raise AdsError(f"{svc} MCP nepoužívá ({BLOCKED_SERVICES[svc]}). Tohle udělej v rozhraní Google Ads.")
    privacy.check_service(svc)
    if _is_read(svc, m):
        raise AdsError(f"{key} jen čte - použij call_service.")
    op_type = m.replace("mutate_", "") if m.startswith("mutate_") else None
    if op_type:
        singular = {"ad_group_criteria": "ad_group_criterion", "campaign_criteria": "campaign_criterion",
                    "customer_negative_criteria": "customer_negative_criterion",
                    "shared_criteria": "shared_criterion"}.get(op_type, op_type[:-1] if op_type.endswith("s") else op_type)
        if f"{singular}_operation" in dict(ads_api.mutate_operations()):
            raise AdsError(f"{key} je obyčejný zápis - použij propose_mutate s {singular}_operation "
                           "(Google ho ověří nanečisto).")
    req = _build_request(acc, svc, m, request_json)
    client = core.client_for(acc)
    fn = getattr(client.get_service(svc), m)
    validated = False
    if "validate_only" in type(req).meta.fields:
        test = type(req).from_json(type(req).to_json(req))
        test.validate_only = True
        fn(request=test)
        validated = True
    guard = METHOD_GUARD.get(key) or SERVICE_GUARD.get(svc) or "settings"
    summary = json.dumps(to_plain(req), ensure_ascii=False)
    summary = re.sub(r'"[A-Za-z0-9+/=]{200,}"', '"<data>"', summary)
    lines = [f"Volání: {key}", f"Požadavek: {summary[:1500]}{'...' if len(summary) > 1500 else ''}"]
    if reason:
        lines.insert(1, f"Důvod: {reason}")

    def run() -> str:
        resp = fn(request=req)
        obj, _ = _response_to_obj(resp, 1000)
        return "Odpověď: " + json.dumps(obj, ensure_ascii=False)[:3000]

    return core.create_custom_plan(acc, f"{key}" + (f" - {reason}" if reason else ""), lines, run,
                                   validated=validated, guard=[guard])


def export_gaql(customer_id: str, query: str, name: str = "report", max_rows: int = 200000,
                preview_rows: int = 20) -> str:
    acc = core.get_account(customer_id)
    privacy.check_gaql(query)
    rows, truncated = core.search(acc, query, max(1, min(int(max_rows), 1_000_000)))
    keys = list(dict.fromkeys(k for r in rows for k in r))
    d = core.state_dir(acc, "reporty")
    safe = re.sub(r"[^\w-]+", "_", name)[:60] or "report"
    p = d / f"{dt.datetime.now():%Y-%m-%d_%H%M}_{safe}.csv"
    with p.open("w", encoding="utf-8-sig", newline="") as fh:
        w = core.SafeCsv(fh)
        w.writerow(keys)
        for r in rows:
            vals = []
            for k in keys:
                v = r.get(k)
                if isinstance(v, float):
                    v = str(v).replace(".", ",")
                elif isinstance(v, (list, dict)):
                    v = json.dumps(v, ensure_ascii=False)
                vals.append("" if v is None else v)
            w.writerow(vals)
    out = [f"{acc.name} | řádků {len(rows)}" + (" (UŘÍZNUTO na max_rows)" if truncated else ""), f"CSV: {p}"]
    preview = [dict(r) for r in rows[:max(0, preview_rows)]]
    privacy.clean_rows(preview)
    for r in preview:
        out.append(json.dumps(r, ensure_ascii=False, default=str))
    return "\n".join(out)
