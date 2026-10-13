from __future__ import annotations

import datetime as dt
import importlib
import pkgutil
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import inspect

import google.ads.googleads.client as gclient
import proto

VERSION = gclient._DEFAULT_VERSION
SUNSET = {"v23": "2027-02", "v24": "2027-05", "v25": "2027-08", "v26": "2027-11"}
SUNSET_CHECKED = "2026-10-12"
GUIDES_FILE = Path(__file__).resolve().parent / "ads_guides.md"
PKGS = ("resources", "common", "enums", "services", "errors")


def _base(pkg: str) -> str:
    return f"google.ads.googleads.{VERSION}.{pkg}"


@lru_cache(maxsize=1)
def type_index() -> dict[str, Any]:
    idx: dict[str, Any] = {}
    for pkg in PKGS:
        try:
            mod = importlib.import_module(_base(pkg) + ".types")
        except ImportError:
            continue
        for m in pkgutil.iter_modules(mod.__path__):
            sub = importlib.import_module(f"{_base(pkg)}.types.{m.name}")
            for name in getattr(sub, "__all__", ()):
                obj = getattr(sub, name, None)
                if obj is not None:
                    idx.setdefault(name, obj)
                    for inner in dir(obj):
                        if not inner[:1].isupper():
                            continue
                        io = getattr(obj, inner, None)
                        if isinstance(io, type) and issubclass(io, (proto.Message, proto.Enum)):
                            idx.setdefault(f"{name}.{inner}", io)
    return idx


@lru_cache(maxsize=1)
def service_index() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    mod = importlib.import_module(_base("services") + ".services")
    for m in pkgutil.iter_modules(mod.__path__):
        cl = importlib.import_module(f"{_base('services')}.services.{m.name}.client")
        cls = next((getattr(cl, n) for n in dir(cl) if n.endswith("ServiceClient")), None)
        if cls is None:
            continue
        svc = cls.__name__[:-len("Client")]
        rpcs = [n for n, f in cls.__dict__.items() if not n.startswith("_") and callable(f)
                and "request" in inspect.signature(f).parameters]
        out[svc] = rpcs
    return out


def camel(snake: str) -> str:
    return "".join(p.capitalize() for p in snake.split("_"))


def _parse_attrs(doc: str) -> dict[str, tuple[str, str]]:
    out: dict[str, tuple[str, str]] = {}
    if "Attributes:" not in doc:
        return out
    body = doc.split("Attributes:", 1)[1]
    cur, typ, buf = None, "", []
    for line in body.splitlines():
        m = re.match(r"^    (\w+) \((.+)\):\s*$", line)
        if m:
            if cur:
                out[cur] = (typ, " ".join(buf))
            cur, typ, buf = m.group(1), m.group(2), []
        elif cur and line.strip():
            buf.append(line.strip())
    if cur:
        out[cur] = (typ, " ".join(buf))
    return out


def _short_type(t: str) -> str:
    t = t.replace("MutableSequence[", "[").replace("MutableMapping[", "map[")
    return re.sub(r"google\.ads\.googleads\.v\d+\.\w+\.types\.", "", t)


def _flags(desc: str) -> str:
    fl = [w for w in ("Output only", "Immutable", "Required") if w in desc[:200]]
    return f" [{', '.join(fl)}]" if fl else ""


def resolve(name: str) -> tuple[str, Any] | None:
    n = name.strip()
    idx = type_index()
    for cand in (n, camel(n), camel(n.replace("_operation", "")) + "Operation" if n.endswith("_operation") else None,
                 n + "Enum." + n if not n.endswith("Enum") else None):
        if cand and cand in idx:
            return cand, idx[cand]
    low = n.lower().replace("_", "")
    for k, v in idx.items():
        if k.lower().replace("_", "") == low:
            return k, v
    return None


def type_help(name: str, field: str = "", full: bool = False, max_enum: int = 60) -> str:
    if "." in name and not resolve(name):
        name, field = name.split(".", 1)
    hit = resolve(name)
    if not hit:
        near = search_types(name, 20)
        return f"Typ {name!r} ve verzi {VERSION} neexistuje." + (f" Podobné: {', '.join(near)}" if near else "")
    key, cls = hit
    if hasattr(cls, "__members__"):
        vals = [v for v in cls.__members__ if v not in ("UNSPECIFIED", "UNKNOWN")]
        return f"ENUM {key} ({VERSION}): " + ", ".join(vals)
    doc = cls.__doc__ or ""
    attrs = _parse_attrs(doc)
    head = doc.split("Attributes:", 1)[0]
    head = re.sub(r"This message has `oneof`_.*?#oneofs-mutually-exclusive-fields\s*", "", head, flags=re.S).strip()
    if field:
        f = attrs.get(field)
        if not f:
            return f"{key} nemá pole {field}. Pole: {', '.join(attrs)}"
        t, d = f
        out = [f"{key}.{field}: {_short_type(t)}", d]
        enum_hit = re.search(r"(\w+Enum)\.(\w+)", t)
        if enum_hit:
            out.append(type_help(f"{enum_hit.group(1)}.{enum_hit.group(2)}"))
        else:
            mh = re.search(r"([A-Z]\w+(?:\.[A-Z]\w+)?)\]?$", _short_type(t).split(".")[-1])
            if mh and resolve(mh.group(1)):
                out.append(f"(podrobnosti: api_type_help(\"{mh.group(1)}\"))")
        return "\n".join(out)
    out = [f"{key} ({VERSION}) - {head[:600]}", "Pole (typ, příznaky; Output only = jen ke čtení):"]
    for fname, (t, d) in attrs.items():
        st = _short_type(t)
        line = f"- {fname}: {st}{_flags(d)}"
        if full:
            line += f" - {d[:400]}"
        else:
            dd = d
            for w in ("Output only.", "Immutable.", "Required."):
                dd = dd.replace(w, "").strip()
            line += f" - {dd.split('. ')[0][:160]}"
        em = re.search(r"(\w+Enum)\.(\w+)", t)
        if em:
            ec = type_index().get(f"{em.group(1)}.{em.group(2)}")
            if ec is not None and hasattr(ec, "__members__"):
                vals = [v for v in ec.__members__ if v not in ("UNSPECIFIED", "UNKNOWN")]
                line += f" | hodnoty: {', '.join(vals[:max_enum])}{' ...' if len(vals) > max_enum else ''}"
        out.append(line)
    if "oneof" in doc:
        groups: dict[str, list[str]] = {}
        for fname, (t, d) in attrs.items():
            m = re.search(r"member of `oneof`_ ``(\w+)``", d)
            if m and not m.group(1).startswith("_"):
                groups.setdefault(m.group(1), []).append(fname)
        for g, fs in groups.items():
            out.append(f"oneof {g} (jen jedno z): {', '.join(fs)}")
    return "\n".join(out)


def search_types(q: str, limit: int = 40) -> list[str]:
    ql = q.lower().replace("_", "")
    return [k for k in sorted(type_index()) if ql in k.lower().replace("_", "")][:limit]


def mutate_operations() -> list[tuple[str, str]]:
    cls = type_index()["MutateOperation"]
    attrs = _parse_attrs(cls.__doc__ or "")
    return [(f, _short_type(t)) for f, (t, _) in attrs.items()]


def operation_help(op_name: str) -> str:
    ops = dict(mutate_operations())
    if op_name not in ops:
        near = [o for o in ops if op_name.replace("_operation", "") in o]
        return f"MutateOperation nemá {op_name}. " + (f"Podobné: {', '.join(near)}" if near else
                                                      "Seznam: api_catalog(\"operations\")")
    opcls_name = ops[op_name].split(".")[-1]
    hit = resolve(opcls_name)
    ocls = hit[1] if hit else None
    attrs = _parse_attrs((ocls.__doc__ or "") if ocls else "")
    res_t = next((_short_type(t) for f, (t, _) in attrs.items() if f in ("create", "update")), "")
    res_name = res_t.split(".")[-1]
    kinds = [k for k in ("create", "update", "remove") if k in attrs]
    extra = [k for k in attrs if k not in ("create", "update", "remove", "update_mask")]
    rpath = re.sub(r"(?<!^)(?=[A-Z])", "_", res_name).lower()
    plural = {"customer": None}.get(rpath, "")
    ex_create = {op_name: {"create": {"resource_name": f"customers/1234567890/{_collection(res_name)}/-1", "...": "..."}}}
    ex_update = {op_name: {"update": {"resource_name": f"customers/1234567890/{_collection(res_name)}/<id>",
                                      "<pole>": "<hodnota>"}, "update_mask": "<pole>"}}
    ex_remove = {op_name: {"remove": f"customers/1234567890/{_collection(res_name)}/<id>"}}
    out = [f"{op_name} -> zdroj {res_name} | akce: {', '.join(kinds)}" + (f" | další pole: {', '.join(extra)}"
                                                                         if extra else "")]
    import json
    if "create" in kinds:
        out.append("create: " + json.dumps(ex_create, ensure_ascii=False))
    if "update" in kinds:
        out.append("update: " + json.dumps(ex_update, ensure_ascii=False) + "  (update_mask doplní MCP sám z polí)")
    if "remove" in kinds:
        out.append("remove: " + json.dumps(ex_remove, ensure_ascii=False))
    out.append(f"Pole zdroje: api_type_help(\"{res_name}\")")
    _ = plural
    return "\n".join(out)


def _collection(res: str) -> str:
    special = {"Customer": "", "AdGroupAd": "adGroupAds", "AdGroupCriterion": "adGroupCriteria",
               "CampaignCriterion": "campaignCriteria", "CustomerNegativeCriterion": "customerNegativeCriteria",
               "SharedCriterion": "sharedCriteria", "AdGroupBidModifier": "adGroupBidModifiers"}
    if res in special:
        return special[res]
    s = res[0].lower() + res[1:]
    return s + ("es" if s.endswith("s") else "s")


def catalog(what: str = "") -> str:
    w = (what or "").strip().lower()
    out = [f"Google Ads API {VERSION} (knihovna google-ads). Vypnutí verze: {SUNSET.get(VERSION, '?')}."]
    if w in ("", "operations", "operace", "mutate"):
        ops = mutate_operations()
        out.append(f"MutateOperation ({len(ops)} typů, zápis přes propose_mutate): " + ", ".join(o for o, _ in ops))
    if w in ("", "services", "sluzby", "služby"):
        si = service_index()
        out.append(f"Služby ({len(si)}), volání mimo mutate přes call_service / propose_service_call:")
        for s, rpcs in sorted(si.items()):
            out.append(f"- {s}: {', '.join(rpcs)}")
    if w and w not in ("operations", "operace", "mutate", "services", "sluzby", "služby"):
        hits = search_types(w, 80)
        out.append(f"Typy obsahující „{what}“: " + ", ".join(hits))
        ops = [o for o, _ in mutate_operations() if w.replace(" ", "_") in o]
        if ops:
            out.append("Operace: " + ", ".join(ops))
        svc = [f"{s}.{r}" for s, rs in service_index().items() for r in rs if w.replace("_", "") in (s + r).lower()]
        if svc:
            out.append("Metody služeb: " + ", ".join(svc[:60]))
    return "\n".join(out)


def guide(query: str = "", max_chars: int = 12000) -> str:
    if not GUIDES_FILE.exists():
        return "Průvodce (ads_guides.md) chybí."
    text = GUIDES_FILE.read_text(encoding="utf-8")
    blocks = re.split(r"(?m)^(?=### |## )", text)
    if not query.strip():
        heads = [b.splitlines()[0] for b in blocks if b.startswith(("## ", "### "))]
        return "Průvodce Google Ads API - kapitoly (hledej api_guide(\"slovo\")):\n" + "\n".join(heads)
    words = [w.lower() for w in re.split(r"\s+", query) if w]
    scored = []
    for b in blocks:
        bl = b.lower()
        head = b.splitlines()[0].lower() if b else ""
        s = sum(bl.count(w) + 5 * head.count(w) for w in words)
        if s:
            scored.append((s, b))
    scored.sort(key=lambda x: -x[0])
    out, size = [], 0
    for _, b in scored:
        if size + len(b) > max_chars:
            break
        out.append(b.strip())
        size += len(b)
    return "\n\n".join(out) or "Nic nenalezeno."


def version_notice() -> str:
    s = SUNSET.get(VERSION)
    if not s:
        return ""
    y, m = map(int, s.split("-"))
    months = (y - dt.date.today().year) * 12 + (m - dt.date.today().month)
    if months <= 4:
        return (f"UPOZORNĚNÍ: Google Ads API {VERSION}, které MCP používá, Google vypne v {m}/{y} "
                f"(zbývá cca {max(months, 0)} měs.). Je čas na přechod na novější verzi knihovny google-ads.")
    return ""


SUNSET_URL = "https://developers.google.com/google-ads/api/docs/sunset-dates"


def api_status() -> str:
    import html as htmlmod
    import urllib.request
    out = [f"MCP používá Google Ads API {VERSION} (knihovna google-ads), vypnutí podle tabulky z {SUNSET_CHECKED}: "
           f"{SUNSET.get(VERSION, '?')}."]
    try:
        req = urllib.request.Request(SUNSET_URL + "?hl=en", headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            page = r.read().decode("utf-8", "ignore")
        rows = re.findall(r">\s*(v\d+(?:\.\d+)?)\s*</a>\s*</td>\s*<td[^>]*>([^<]+)</td>\s*<td[^>]*>([^<]+)</td>", page)
        up = re.findall(r"<td[^>]*>\s*(v\d+(?:\.\d+)?\*?)\s*</td>\s*<td[^>]*>([^<]+)</td>\s*<td[^>]*>([^<]+)</td>", page)
        if rows or up:
            out.append("Tabulka Googlu (verze | vydání | vypnutí):")
            out += [f"- {v} | {htmlmod.unescape(a).strip()} | {htmlmod.unescape(b).strip()}" for v, a, b in rows + up]
            newest = max((v for v, _, _ in rows), key=lambda v: tuple(int(x) for x in v[1:].split(".")), default=None)
            if newest and newest.split(".")[0] != VERSION:
                out.append(f"Novější hlavní verze {newest.split('.')[0]} už vyšla - přechod naplánuj s rezervou "
                           f"před vypnutím {VERSION}.")
        else:
            out.append(f"Tabulku se nepodařilo přečíst, zkontroluj ručně: {SUNSET_URL}")
    except Exception as ex:
        out.append(f"Web Googlu nedostupný ({type(ex).__name__}). Zkontroluj ručně: {SUNSET_URL}")
    note = version_notice()
    if note:
        out.append(note)
    return "\n".join(out)
