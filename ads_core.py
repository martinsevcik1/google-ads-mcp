from __future__ import annotations

import datetime as dt
import enum
import json
import os
import csv
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

import proto
import yaml
from google.ads.googleads.client import GoogleAdsClient
from google.ads.googleads.errors import GoogleAdsException
from google.api_core import protobuf_helpers

BASE_DIR = Path(__file__).resolve().parent
ACCOUNTS_FILE = Path(os.environ.get("ADS_ACCOUNTS_FILE", BASE_DIR / "accounts.yaml")).expanduser()
CREDENTIALS_FILE = Path(
    os.environ.get("GOOGLE_ADS_CONFIG", Path.home() / ".google-ads" / "google-ads.yaml")
)
LOG_DIR = Path(os.environ.get("ADS_LOG_DIR", ACCOUNTS_FILE.parent / "logs")).expanduser()
GUARDRAILS_FILE = Path(os.environ.get("ADS_GUARDRAILS_FILE", BASE_DIR / "guardrails.yaml"))

GUARD_LABELS = {
    "budget": "změna rozpočtu",
    "bidding": "nabídky nebo cíl strategie",
    "enable": "zapnutí kampaně / sestavy / reklamy / slova nebo nová kampaň rovnou zapnutá",
    "pause": "pozastavení celé kampaně nebo sestavy",
    "targeting": "lokality a cílení",
    "automation": "automatiky PMAX",
    "remove_negatives": "odebrání vylučujících slov",
    "listing_groups": "skupiny produktů",
    "remove": "odebrání nebo smazání",
    "settings": "nastavení kampaní a další zásahy mimo běžné úpravy",
    "conversions": "měření konverzí, konverzní cíle a nahrávání konverzí",
    "account": "nastavení účtu a propojení",
    "experiments": "experimenty a koncepty",
    "user_data": "osobní údaje zákazníků (Customer Match)",
    "recommendations": "použití nebo zamítnutí doporučení Googlu",
}


def guarded_categories() -> set[str]:
    cats = set(GUARD_LABELS)
    if GUARDRAILS_FILE.exists():
        data = yaml.safe_load(GUARDRAILS_FILE.read_text(encoding="utf-8")) or {}
        for k, v in (data.get("guarded") or {}).items():
            if k in GUARD_LABELS and v is False:
                cats.discard(k)
    return cats
PLAN_TTL_SECONDS = 60 * 60
MAX_OPS_PER_PLAN = 5000
MAX_PLAN_BYTES = 60 * 1024 * 1024


class AdsError(Exception):
    pass


def norm_id(value: Any) -> str:
    digits = re.sub(r"\D", "", str(value))
    if len(digits) != 10:
        raise AdsError(f"Neplatné ID účtu: {value!r} (čekám 10 číslic, např. 123-456-7890)")
    return digits


def fmt_id(digits: str) -> str:
    return f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"


def num_id(value: Any, what: str = "ID") -> str:
    s = str(value).strip()
    if not re.fullmatch(r"\d+", s):
        raise AdsError(f"Neplatné {what}: {value!r} (čekám jen číslice)")
    return s


@dataclass
class Account:
    customer_id: str
    name: str
    login_customer_id: str | None
    folder: Path | None = None
    active: bool = False
    shared_folder: bool = False


def load_accounts() -> dict[str, Account]:
    if not ACCOUNTS_FILE.exists():
        raise AdsError(f"Chybí soubor se seznamem účtů: {ACCOUNTS_FILE}")
    data = yaml.safe_load(ACCOUNTS_FILE.read_text(encoding="utf-8")) or {}
    default_login = data.get("default_login_customer_id")
    default_login = norm_id(default_login) if default_login else None
    root = _resolve(data.get("clients_root"))
    result: dict[str, Account] = {}
    for raw_id, info in (data.get("accounts") or {}).items():
        info = info or {}
        cid = norm_id(raw_id)
        if "login_customer_id" in info:
            login = norm_id(info["login_customer_id"]) if info["login_customer_id"] else None
        else:
            login = default_login
        folder = info.get("folder")
        if folder:
            folder = Path(folder).expanduser()
            folder = folder if folder.is_absolute() else (root or ACCOUNTS_FILE.parent) / folder
        result[cid] = Account(cid, str(info.get("name", fmt_id(cid))), login, folder or None,
                              bool(info.get("aktivni_sprava", False)))
    counts: dict[str, int] = {}
    for a in result.values():
        if a.folder:
            counts[_norm(a.folder)] = counts.get(_norm(a.folder), 0) + 1
    for a in result.values():
        a.shared_folder = bool(a.folder) and counts.get(_norm(a.folder), 0) > 1
    return result


def _resolve(p: Any) -> Path | None:
    if not p:
        return None
    path = Path(str(p)).expanduser()
    return path if path.is_absolute() else ACCOUNTS_FILE.parent / path


def dpa_enabled() -> bool:
    if not ACCOUNTS_FILE.exists():
        return False
    data = yaml.safe_load(ACCOUNTS_FILE.read_text(encoding="utf-8")) or {}
    return data.get("dpa") is True


def clients_root() -> Path:
    data = yaml.safe_load(ACCOUNTS_FILE.read_text(encoding="utf-8")) or {}
    return _resolve(data.get("clients_root")) or BASE_DIR / "state"


def state_dir(acc: Account, routine: str) -> Path:
    base = Path(acc.folder) if acc.folder else BASE_DIR / "state" / acc.customer_id
    d = base / routine
    if acc.shared_folder:
        d = d / fmt_id(acc.customer_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _norm(p: Path) -> str:
    return os.path.normcase(os.path.realpath(str(p)))


def check_local_path(acc: Account, path: Path) -> None:
    if acc.folder is None:
        raise AdsError(
            f"Účet {acc.name} ({fmt_id(acc.customer_id)}) nemá v accounts.yaml přiřazenou složku klienta, "
            "takže do něj lokální soubory nenahraju. Doplň u účtu folder.")
    base = _norm(acc.folder)
    target = _norm(path)
    if not (target == base or target.startswith(base.rstrip(os.sep) + os.sep)):
        raise AdsError(
            f"Soubor {path} neleží ve složce klienta {acc.name} ({acc.folder}). "
            "Nahrání odmítnuto - ochrana proti nahrání podkladů do cizího účtu.")


def get_account(customer_id: Any) -> Account:
    cid = norm_id(customer_id)
    accounts = load_accounts()
    if cid not in accounts:
        raise AdsError(
            f"Účet {fmt_id(cid)} není v seznamu povolených účtů (accounts.yaml). "
            "MCP do něj nesmí sahat ani číst."
        )
    return accounts[cid]


_clients: dict[str | None, GoogleAdsClient] = {}
_clients_lock = threading.Lock()


def _load_credentials() -> dict[str, Any]:
    if not CREDENTIALS_FILE.exists():
        raise AdsError(
            f"Chybí přihlašovací soubor {CREDENTIALS_FILE}. Spusť nejdřív auth_setup.py."
        )
    cfg = yaml.safe_load(CREDENTIALS_FILE.read_text(encoding="utf-8")) or {}
    cfg["use_proto_plus"] = True
    cfg.pop("login_customer_id", None)
    return cfg


def get_client(login_customer_id: str | None) -> GoogleAdsClient:
    with _clients_lock:
        if login_customer_id not in _clients:
            cfg = _load_credentials()
            if login_customer_id:
                cfg["login_customer_id"] = login_customer_id
            _clients[login_customer_id] = GoogleAdsClient.load_from_dict(cfg)
        return _clients[login_customer_id]


def client_for(acc: Account) -> GoogleAdsClient:
    return get_client(acc.login_customer_id)


def _conv(value: Any) -> Any:
    if isinstance(value, enum.Enum):
        return value.name
    if isinstance(value, proto.Message):
        return type(value).to_dict(value, use_integers_for_enums=False)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, bytes):
        return f"<{len(value)} bajtů>"
    if hasattr(value, "items"):
        return {k: _conv(v) for k, v in value.items()}
    if hasattr(value, "__iter__"):
        return [_conv(v) for v in value]
    return str(value)


def _get_path(obj: Any, path: str) -> Any:
    for part in path.split("."):
        if hasattr(obj, part):
            obj = getattr(obj, part)
        elif hasattr(obj, part + "_"):
            obj = getattr(obj, part + "_")
        else:
            return None
    return obj


def select_fields(query: str) -> list[str]:
    m = re.search(r"^\s*SELECT\s+(.*?)\s+FROM\s+", query, re.IGNORECASE | re.DOTALL)
    if not m:
        raise AdsError("Dotaz musí mít tvar SELECT ... FROM ...")
    return [f.strip() for f in m.group(1).split(",") if f.strip()]


def row_to_dict(row: Any, fields: list[str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for f in fields:
        val = _conv(_get_path(row, f))
        out[f] = val
        if f.endswith("_micros") and isinstance(val, (int, float)):
            out[f[: -len("_micros")]] = round(val / 1_000_000, 2)
    return out


def search(acc: Account, query: str, max_rows: int = 200) -> tuple[list[dict[str, Any]], bool]:
    if not re.match(r"^\s*SELECT\b", query, re.IGNORECASE):
        raise AdsError("Povolené jsou jen dotazy SELECT.")
    fields = select_fields(query)
    ga = client_for(acc).get_service("GoogleAdsService")
    rows: list[dict[str, Any]] = []
    truncated = False
    for row in ga.search(customer_id=acc.customer_id, query=query):
        if len(rows) >= max_rows:
            truncated = True
            break
        rows.append(row_to_dict(row, fields))
    return rows, truncated


def search_raw(acc: Account, query: str) -> list[Any]:
    ga = client_for(acc).get_service("GoogleAdsService")
    return list(ga.search(customer_id=acc.customer_id, query=query))


def gaql_str(value: str) -> str:
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def format_ads_error(ex: GoogleAdsException) -> str:
    lines = []
    for err in ex.failure.errors:
        code = type(err.error_code).to_dict(err.error_code, use_integers_for_enums=False)
        code_txt = ", ".join(f"{k}={v}" for k, v in code.items()) or "?"
        where = ""
        for el in err.location.field_path_elements:
            if el.field_name == "mutate_operations" and "index" in el:
                where = f" [operace #{el.index + 1}]"
                break
        detail = ""
        pf = err.details.policy_finding_details
        if pf and pf.policy_topic_entries:
            topics = ", ".join(t.topic for t in pf.policy_topic_entries)
            detail = f" | zásady: {topics}"
        pv = err.details.policy_violation_details
        if pv and pv.external_policy_name:
            detail += f" | zásada: {pv.external_policy_name} (výjimka možná: {pv.is_exemptible})"
        trig = f" | text: {err.trigger.string_value}" if err.trigger.string_value else ""
        lines.append(f"- {code_txt}{where}: {err.message}{trig}{detail}")
    lines.append(f"(request_id {ex.request_id})")
    return "\n".join(lines)


def log_event(event: dict[str, Any]) -> None:
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        event = {"ts": dt.datetime.now().isoformat(timespec="seconds"), **event}
        path = LOG_DIR / f"changes-{dt.date.today():%Y-%m}.jsonl"
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _strip_blobs(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: (f"<{len(v)} znaků base64>" if k == "data" and isinstance(v, str) and len(v) > 200
                    else _strip_blobs(v)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_strip_blobs(v) for v in obj]
    return obj


def ops_to_json(ops: Iterable[Any]) -> list[Any]:
    out = []
    for op in ops:
        try:
            out.append(_strip_blobs(json.loads(type(op).to_json(
                op, use_integers_for_enums=False, always_print_fields_with_no_presence=False))))
        except Exception:
            out.append("<operace>")
    return out


@dataclass
class Plan:
    id: str
    account: Account
    title: str
    lines: list[str]
    ops: list[Any]
    warnings: list[str] = field(default_factory=list)
    created: float = field(default_factory=time.time)
    labels: list[str | None] | None = None
    guard: list[str] = field(default_factory=list)
    executor: Callable[[], str] | None = None


class TempIds:
    def __init__(self) -> None:
        self._n = 0

    def next(self) -> int:
        self._n -= 1
        return self._n


_plans: dict[str, Plan] = {}
_plans_lock = threading.Lock()


def new_op(client: GoogleAdsClient) -> Any:
    return client.get_type("MutateOperation")


def set_update_mask(client: GoogleAdsClient, operation: Any, resource: Any) -> None:
    client.copy_from(operation.update_mask, protobuf_helpers.field_mask(None, resource._pb))


def _mutate(acc: Account, ops: list[Any], validate_only: bool) -> Any:
    client = client_for(acc)
    ga = client.get_service("GoogleAdsService")
    req = client.get_type("MutateGoogleAdsRequest")
    req.customer_id = acc.customer_id
    for op in ops:
        req.mutate_operations.append(op)
    req.validate_only = validate_only
    req.partial_failure = False
    return ga.mutate(request=req)


def _cleanup_plans() -> None:
    now = time.time()
    for pid in [p for p, plan in _plans.items() if now - plan.created > PLAN_TTL_SECONDS]:
        _plans.pop(pid, None)


def _payload_bytes(ops: list[Any]) -> int:
    total = 0
    for op in ops:
        if "asset_operation" in op and op.asset_operation.create.image_asset.data:
            total += len(op.asset_operation.create.image_asset.data)
    return total


def create_custom_plan(acc: Account, title: str, lines: list[str], executor: Callable[[], str],
                       warnings: list[str] | None = None, validated: bool = False,
                       guard: list[str] | None = None) -> str:
    plan = Plan(uuid.uuid4().hex[:8], acc, title, lines, [], list(warnings or []), executor=executor,
                guard=_active_guard(guard))
    with _plans_lock:
        _cleanup_plans()
        _plans[plan.id] = plan
    log_event({"type": "proposed", "plan_id": plan.id, "customer_id": acc.customer_id,
               "account": acc.name, "title": title, "lines": lines})
    check = ("Kontrola nanečisto v Google Ads: OK, zatím se nic nezměnilo." if validated
             else "Tuhle akci Google nanečisto ověřit neumí, zkontrolovaly se jen vstupy.")
    return render_plan(plan) + f"\n\n{check}\n{_apply_hint(plan)}"


def _active_guard(guard: list[str] | None) -> list[str]:
    active = guarded_categories()
    return [g for g in dict.fromkeys(guard or []) if g in active]


def _apply_hint(plan: "Plan") -> str:
    if plan.guard:
        why = ", ".join(GUARD_LABELS[g] for g in plan.guard)
        return (f"CHRÁNĚNÁ ZMĚNA ({why}): provést jen po výslovném souhlasu uživatele přes "
                f"apply_guarded_change(plan_id=\"{plan.id}\").")
    return (f"Běžná změna: po náhledu (preview_changes) a souhlasu uživatele přes "
            f"apply_change(plan_id=\"{plan.id}\").")


def create_plan(acc: Account, title: str, lines: list[str], ops: list[Any],
                warnings: list[str] | None = None, labels: list[str | None] | None = None,
                guard: list[str] | None = None) -> str:
    warnings = list(warnings or [])
    if not ops:
        msg = [f"Není co měnit - {title} ({acc.name})."]
        msg += [f"- {l}" for l in lines]
        msg += [f"Pozor: {w}" for w in warnings]
        return "\n".join(msg)
    if len(ops) > MAX_OPS_PER_PLAN:
        raise AdsError(f"Příliš mnoho operací v jednom plánu ({len(ops)}), max {MAX_OPS_PER_PLAN}.")
    size = _payload_bytes(ops)
    if size > MAX_PLAN_BYTES:
        raise AdsError(f"Obrázky v jednom plánu mají {size / 1e6:.0f} MB, max {MAX_PLAN_BYTES / 1e6:.0f} MB. "
                       "Rozděl je: nejdřív upload_images po částech, pak odkazuj na ID assetů.")
    try:
        _mutate(acc, ops, validate_only=True)
    except GoogleAdsException as ex:
        err = format_ads_error(ex)
        log_event({"type": "validation_failed", "customer_id": acc.customer_id,
                   "account": acc.name, "title": title, "errors": err})
        return (f"Google Ads návrh ODMÍTL při kontrole nanečisto - nic se nezměnilo.\n"
                f"{title} ({acc.name}, {fmt_id(acc.customer_id)})\n{err}")

    plan = Plan(uuid.uuid4().hex[:8], acc, title, lines, ops, warnings, labels=labels, guard=_active_guard(guard))
    with _plans_lock:
        _cleanup_plans()
        _plans[plan.id] = plan
    log_event({"type": "proposed", "plan_id": plan.id, "customer_id": acc.customer_id,
               "account": acc.name, "title": title, "lines": lines, "warnings": warnings,
               "operations": ops_to_json(ops)})
    return render_plan(plan) + ("\n\nKontrola nanečisto v Google Ads: OK, zatím se nic nezměnilo.\n"
                                + _apply_hint(plan))


def render_plan(plan: Plan) -> str:
    age = int((time.time() - plan.created) / 60)
    out = [f"PLÁN {plan.id} - {plan.account.name} ({fmt_id(plan.account.customer_id)})",
           f"{plan.title} | operací: {len(plan.ops) or 1} | vytvořen před {age} min"]
    out += [f"- {l}" for l in plan.lines]
    out += [f"POZOR: {w}" for w in plan.warnings]
    if plan.guard:
        out.append("CHRÁNĚNÁ: " + ", ".join(GUARD_LABELS[g] for g in plan.guard))
    return "\n".join(out)


def list_plans() -> list[Plan]:
    with _plans_lock:
        _cleanup_plans()
        return list(_plans.values())


def discard_plan(plan_id: str) -> bool:
    with _plans_lock:
        return _plans.pop(plan_id.strip(), None) is not None


APPLY_HOOKS: list[Callable[["Plan"], None]] = []


def _run_hooks(plan: "Plan") -> None:
    for hook in APPLY_HOOKS:
        try:
            hook(plan)
        except Exception:
            pass


def apply_plan(plan_id: str, guarded_ok: bool = False) -> str:
    with _plans_lock:
        _cleanup_plans()
        plan = _plans.get(plan_id.strip())
        if plan is None:
            raise AdsError(f"Plán {plan_id} neexistuje nebo vypršel (platí {PLAN_TTL_SECONDS // 60} min). "
                           "Vytvoř nový návrh.")
        if plan.guard and not guarded_ok:
            raise AdsError("Tohle je chráněná změna (" + ", ".join(GUARD_LABELS[g] for g in plan.guard)
                           + "). Provést ji jde jen přes apply_guarded_change po výslovném souhlasu uživatele.")
        _plans.pop(plan_id.strip(), None)
    if plan.executor is not None:
        try:
            result = plan.executor()
        except GoogleAdsException as ex:
            err = format_ads_error(ex)
            log_event({"type": "apply_failed", "plan_id": plan.id, "customer_id": plan.account.customer_id,
                       "account": plan.account.name, "title": plan.title, "errors": err})
            return f"Provedení SELHALO.\n{err}"
        log_event({"type": "applied", "plan_id": plan.id, "customer_id": plan.account.customer_id,
                   "account": plan.account.name, "title": plan.title, "lines": plan.lines, "results": result,
                   "guard": plan.guard})
        _run_hooks(plan)
        return f"PROVEDENO - {plan.title} ({plan.account.name}, {fmt_id(plan.account.customer_id)})\n{result}"
    try:
        resp = _mutate(plan.account, plan.ops, validate_only=False)
    except GoogleAdsException as ex:
        err = format_ads_error(ex)
        log_event({"type": "apply_failed", "plan_id": plan.id, "customer_id": plan.account.customer_id,
                   "account": plan.account.name, "title": plan.title, "errors": err})
        return f"Provedení SELHALO, nic se nezměnilo (požadavek je atomický).\n{err}"

    names: list[str] = []
    for r in resp.mutate_operation_responses:
        d = type(r).to_dict(r)
        name = ""
        for v in d.values():
            if isinstance(v, dict) and v.get("resource_name"):
                name = v["resource_name"]
        names.append(name)
    log_event({"type": "applied", "plan_id": plan.id, "customer_id": plan.account.customer_id,
               "account": plan.account.name, "title": plan.title, "lines": plan.lines, "guard": plan.guard,
               "operations": ops_to_json(plan.ops), "results": names})
    _run_hooks(plan)
    return render_result(plan, names)


_KEY_TYPES = ("campaigns", "campaignBudgets", "adGroups", "assetGroups", "sharedSets")


def render_result(plan: Plan, names: list[str]) -> str:
    out = [f"PROVEDENO - {plan.title} ({plan.account.name}, {fmt_id(plan.account.customer_id)})"]
    labels = plan.labels or [None] * len(names)
    counts: dict[str, int] = {}
    shown = 0
    for i, name in enumerate(names):
        if not name:
            continue
        rtype = name.split("/")[2] if name.count("/") >= 3 else "?"
        label = labels[i] if i < len(labels) else None
        if label or rtype in _KEY_TYPES:
            if shown < 80:
                out.append(f"- {label + ': ' if label else ''}{name}")
            shown += 1
        else:
            counts[rtype] = counts.get(rtype, 0) + 1
    if shown > 80:
        out.append(f"... a dalších {shown - 80} pojmenovaných")
    if counts:
        out.append("Dále: " + ", ".join(f"{k} {v}×" for k, v in sorted(counts.items())))
    return "\n".join(out)


_CSV_NUM = re.compile(r"^[-+]?\d[\d\s.,]*%?$")


def csv_safe(v: Any) -> Any:
    if isinstance(v, str) and v[:1] in ("=", "+", "-", "@", "\t", "\r") and not _CSV_NUM.match(v):
        return "'" + v
    return v


class SafeCsv:
    def __init__(self, fh: Any) -> None:
        self._w = csv.writer(fh, delimiter=";")

    def writerow(self, row: list[Any]) -> None:
        self._w.writerow([csv_safe(v) for v in row])
