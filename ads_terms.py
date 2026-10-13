from __future__ import annotations

import csv
import re
import shutil
import unicodedata
import datetime as dt
from pathlib import Path
from typing import Any

from google.ads.googleads.errors import GoogleAdsException

import ads_privacy as privacy
from ads_core import BASE_DIR, Account, AdsError, SafeCsv, fmt_id, get_account, search_raw, state_dir

THRESHOLD = {"CZK": 20.0, "EUR": 1.0, "GBP": 1.0, "USD": 1.0, "PLN": 4.0, "HUF": 400.0}
DECISIONS_FILE = "rozhodnuti.csv"


def _state_dir(acc: Account) -> Path:
    d = state_dir(acc, "rutina_dotazy")
    if acc.shared_folder and not (d / DECISIONS_FILE).exists():
        legacy = d.parent / DECISIONS_FILE
        if legacy.exists():
            shutil.copyfile(legacy, d / DECISIONS_FILE)
    return d


def _load_decisions(acc: Account) -> dict[str, dict[str, str]]:
    path = _state_dir(acc) / DECISIONS_FILE
    out: dict[str, dict[str, str]] = {}
    if path.exists():
        with path.open(encoding="utf-8-sig", newline="") as fh:
            for row in csv.DictReader(fh, delimiter=";"):
                out[row["dotaz"].strip().lower()] = row
    return out


def mark_search_terms(customer_id: str, terms: list[str], decision: str, note: str = "") -> str:
    acc = get_account(customer_id)
    if decision not in ("ponechat", "vyloucit", "pridat", "zasobnik"):
        raise AdsError("decision je ponechat, vyloucit, pridat nebo zasobnik.")
    path = _state_dir(acc) / DECISIONS_FILE
    new = not path.exists()
    today = dt.date.today().isoformat()
    with path.open("a", encoding="utf-8-sig" if new else "utf-8", newline="") as fh:
        w = csv.writer(fh, delimiter=";")
        if new:
            w.writerow(["datum", "dotaz", "rozhodnuti", "poznamka"])
        for t in dict.fromkeys(x.strip() for x in terms if x.strip()):
            w.writerow([today, t, decision, note])
    return f"Uloženo {len(terms)} dotazů jako „{decision}“ pro {acc.name}."


def _covered(words: list[str], negs: list[tuple[list[str], str]]) -> bool:
    ws = set(words)
    n = len(words)
    for nw, match in negs:
        if not nw:
            continue
        if match == "EXACT":
            if nw == words:
                return True
        elif match == "PHRASE":
            k = len(nw)
            if any(words[i:i + k] == nw for i in range(n - k + 1)):
                return True
        elif set(nw) <= ws:
            return True
    return False


STOP = {"pro", "na", "do", "se", "ze", "od", "po", "jak", "co", "je", "cz", "sk", "com", "www", "the", "and",
        "for", "with", "nebo", "který", "ktery", "kde", "kolik", "pri", "při", "bez", "nad", "pod", "mezi"}


def _fold(t: str) -> str:
    return unicodedata.normalize("NFKD", t.lower()).encode("ascii", "ignore").decode()


def _tokens(t: str) -> list[str]:
    return [w for w in re.findall(r"[\w-]+", t.lower()) if len(w) >= 3 and not w.isdigit() and w not in STOP]


def _watchlist(acc: Account) -> list[str]:
    p = _state_dir(acc) / "sledovat.txt"
    if not p.exists():
        return []
    return [l.strip().lower() for l in p.read_text(encoding="utf-8-sig").splitlines()
            if l.strip() and not l.strip().startswith("#")]


def search_terms_review(customer_id: str, days: int = 7, max_rows: int = 150,
                        min_clicks: int = 2, min_cost: float | None = None,
                        no_click_rows: int = 40, word_rows: int = 25) -> str:
    acc = get_account(customer_id)
    days = max(1, min(int(days), 90))
    end = dt.date.today() - dt.timedelta(days=1)
    start = end - dt.timedelta(days=days - 1)
    period = f"segments.date BETWEEN '{start:%Y-%m-%d}' AND '{end:%Y-%m-%d}'"
    cur = search_raw(acc, "SELECT customer.currency_code FROM customer")[0].customer.currency_code
    thr = THRESHOLD.get(cur, 20.0) if min_cost is None else float(min_cost)

    agg: dict[tuple[str, str, str], dict[str, float]] = {}
    status: dict[tuple[str, str, str], str] = {}
    camp_type: dict[str, str] = {}

    def add(key: tuple[str, str, str], r: Any, has_cost: bool = True) -> None:
        m = agg.setdefault(key, {"clicks": 0, "cost": 0.0, "conv": 0.0, "value": 0.0, "impr": 0})
        m["clicks"] += r.metrics.clicks
        m["impr"] += r.metrics.impressions
        if has_cost:
            m["cost"] += r.metrics.cost_micros / 1e6
        m["conv"] += r.metrics.conversions
        m["value"] += r.metrics.conversions_value

    camp_id: dict[str, str] = {}
    group_id: dict[tuple[str, str], str] = {}
    q = ("SELECT search_term_view.search_term, search_term_view.status, campaign.name, ad_group.name, "
         "campaign.id, ad_group.id, "
         "metrics.clicks, metrics.impressions, metrics.cost_micros, metrics.conversions, metrics.conversions_value "
         f"FROM search_term_view WHERE {period} AND metrics.impressions > 0")
    for r in search_raw(acc, q):
        key = (r.search_term_view.search_term.strip(), r.campaign.name, r.ad_group.name)
        camp_type[r.campaign.name] = "SRCH"
        camp_id[r.campaign.name] = str(r.campaign.id)
        group_id[(r.campaign.name, r.ad_group.name)] = str(r.ad_group.id)
        add(key, r)
        s = r.search_term_view.status.name
        if s in ("ADDED", "EXCLUDED", "ADDED_EXCLUDED"):
            status[key] = s

    pmax_cost = True
    base = ("SELECT campaign_search_term_view.search_term, campaign.name, campaign.id, metrics.clicks, "
            "metrics.impressions, "
            "{cost}metrics.conversions, metrics.conversions_value FROM campaign_search_term_view "
            f"WHERE {period} AND campaign.advertising_channel_type = PERFORMANCE_MAX AND metrics.impressions > 0")
    try:
        rows = search_raw(acc, base.format(cost="metrics.cost_micros, "))
    except GoogleAdsException:
        pmax_cost = False
        rows = search_raw(acc, base.format(cost=""))
    for r in rows:
        key = (r.campaign_search_term_view.search_term.strip(), r.campaign.name, "")
        camp_id[r.campaign.name] = str(r.campaign.id)
        camp_type[r.campaign.name] = "PMAX"
        add(key, r, pmax_cost)

    negs: list[tuple[list[str], str]] = []
    for r in search_raw(acc, "SELECT campaign_criterion.keyword.text, campaign_criterion.keyword.match_type "
                             "FROM campaign_criterion WHERE campaign_criterion.type = KEYWORD "
                             "AND campaign_criterion.negative = TRUE AND campaign.status != REMOVED"):
        negs.append((r.campaign_criterion.keyword.text.lower().split(), r.campaign_criterion.keyword.match_type.name))
    for r in search_raw(acc, "SELECT shared_criterion.keyword.text, shared_criterion.keyword.match_type "
                             "FROM shared_criterion WHERE shared_criterion.type = KEYWORD"):
        negs.append((r.shared_criterion.keyword.text.lower().split(), r.shared_criterion.keyword.match_type.name))

    keywords: set[str] = set()
    for r in search_raw(acc, "SELECT ad_group_criterion.keyword.text FROM ad_group_criterion "
                             "WHERE ad_group_criterion.type = KEYWORD AND ad_group_criterion.negative = FALSE "
                             "AND ad_group_criterion.status != REMOVED AND campaign.status != REMOVED "
                             "AND ad_group.status != REMOVED"):
        keywords.add(" ".join(r.ad_group_criterion.keyword.text.lower().split()))

    decisions = _load_decisions(acc)
    queued: list[tuple[list[str], str]] = []
    zp = _state_dir(acc) / "zasobnik.csv"
    if zp.exists():
        with zp.open(encoding="utf-8-sig", newline="") as fh:
            for r in csv.DictReader(fh, delimiter=";"):
                if r.get("akce") == "vyloucit" and not r.get("nasazeno"):
                    queued.append((r["text"].lower().split(), r["shoda"]))
    total_cost = sum(m["cost"] for m in agg.values())
    skip = {"decided": 0, "negated": 0, "queued": 0, "keyword": 0, "conv": 0, "low": 0, "pii": 0}
    skip_cost = {"conv": 0.0, "low": 0.0}
    guard_pii = privacy.enabled()
    candidates = []
    pool: list[tuple[tuple[str, str, str], dict[str, float]]] = []
    to_add: dict[str, dict[str, Any]] = {}
    for key, m in agg.items():
        term = key[0]
        if guard_pii and privacy.has_pii(term):
            skip["pii"] += 1
            continue
        lt = term.lower()
        prev = decisions.get(lt)
        resurface = (prev is not None and prev.get("rozhodnuti") == "ponechat" and m["conv"] == 0
                     and m["cost"] >= 5 * thr and prev.get("datum", "") < start.isoformat())
        if prev and not resurface:
            skip["decided"] += 1
            continue
        if status.get(key) in ("EXCLUDED", "ADDED_EXCLUDED") or _covered(lt.split(), negs):
            skip["negated"] += 1
            continue
        if queued and _covered(lt.split(), queued):
            skip["queued"] += 1
            continue
        if status.get(key) == "ADDED":
            skip["keyword"] += 1
            continue
        if m["conv"] > 0:
            skip["conv"] += 1
            skip_cost["conv"] += m["cost"]
            if not prev and " ".join(lt.split()) not in keywords:
                a = to_add.setdefault(lt, {"term": term, "conv": 0.0, "cost": 0.0, "clicks": 0, "where": []})
                a["conv"] += m["conv"]
                a["cost"] += m["cost"]
                a["clicks"] += m["clicks"]
                a["where"].append(key)
            continue
        pool.append((key, m))
        if m["clicks"] < min_clicks and m["cost"] < thr:
            skip["low"] += 1
            skip_cost["low"] += m["cost"]
            continue
        candidates.append((key, m, bool(prev)))

    candidates.sort(key=lambda x: (x[1]["cost"], x[1]["clicks"]), reverse=True)

    d = _state_dir(acc)
    export = d / f"{dt.date.today():%Y-%m-%d}_dotazy.csv"
    with export.open("w", encoding="utf-8-sig", newline="") as fh:
        w = SafeCsv(fh)
        w.writerow(["dotaz", "kampan", "typ", "sestava", "kliky", "zobrazeni", "utrata", "konverze", "hodnota", "stav"])
        for key, m in sorted(agg.items(), key=lambda x: x[1]["cost"], reverse=True):
            w.writerow([key[0], key[1], camp_type.get(key[1], ""), key[2], m["clicks"], m["impr"],
                        f"{m['cost']:.2f}".replace(".", ","), f"{m['conv']:.2f}".replace(".", ","),
                        f"{m['value']:.2f}".replace(".", ","), status.get(key, "")])

    shown = candidates[:max_rows]
    shown_keys = {k for k, _, _ in shown}
    noclick = sorted((x for x in pool if x[0] not in shown_keys and x[1]["impr"] >= 3),
                     key=lambda x: (x[1]["impr"], x[1]["clicks"]), reverse=True)[:max(0, no_click_rows)]

    vocab: set[str] = set()
    for k in keywords:
        vocab.update(_fold(w) for w in _tokens(k))
    vocab.update(_fold(w) for w in _tokens(acc.name.replace(".", " ")))
    try:
        for r in search_raw(acc, "SELECT shopping_product.title, shopping_product.brand FROM shopping_product"):
            vocab.update(_fold(w) for w in _tokens(f"{r.shopping_product.title} {r.shopping_product.brand}"))
    except Exception:
        pass
    words: dict[str, dict[str, Any]] = {}
    for key, m in pool:
        for w in set(_tokens(key[0])):
            if _fold(w) in vocab:
                continue
            a = words.setdefault(w, {"n": 0, "impr": 0, "clicks": 0, "cost": 0.0, "ex": ("", -1)})
            a["n"] += 1
            a["impr"] += m["impr"]
            a["clicks"] += m["clicks"]
            a["cost"] += m["cost"]
            if m["impr"] > a["ex"][1]:
                a["ex"] = (key[0], m["impr"])
    top_words = sorted(((w, a) for w, a in words.items() if a["n"] >= 2),
                       key=lambda x: (x[1]["impr"], x[1]["n"]), reverse=True)[:max(0, word_rows)]

    watch = _watchlist(acc)
    watch_hits: list[tuple[str, dict[str, Any]]] = []
    for wt in watch:
        a = {"n": 0, "impr": 0, "clicks": 0, "cost": 0.0, "ex": []}
        for key, m in pool:
            if wt in key[0].lower():
                a["n"] += 1
                a["impr"] += m["impr"]
                a["clicks"] += m["clicks"]
                a["cost"] += m["cost"]
                a["ex"].append((m["impr"], key))
        if a["n"]:
            a["ex"] = [k for _, k in sorted(a["ex"], key=lambda x: x[0], reverse=True)[:3]]
            watch_hits.append((wt, a))
    extra_keys = [k for k, _ in noclick] + [k for _, a in watch_hits for k in a["ex"]]

    adds = sorted(to_add.values(), key=lambda a: (a["conv"], -a["cost"]), reverse=True)[:30]
    add_keys = [k for a in adds for k in a["where"]]
    camps = list(dict.fromkeys([k[1] for k, _, _ in shown] + [k[1] for k in add_keys]
                               + [k[1] for k in extra_keys]))
    groups = list(dict.fromkeys([(k[1], k[2]) for k, _, _ in shown if k[2]]
                                + [(k[1], k[2]) for k in add_keys if k[2]]
                                + [(k[1], k[2]) for k in extra_keys if k[2]]))
    cc = {c: f"C{i + 1}" for i, c in enumerate(camps)}
    gc = {g: f"A{i + 1}" for i, g in enumerate(groups)}

    def money(x: float) -> str:
        return f"{x:,.0f}".replace(",", " ") if cur in ("CZK", "HUF") else f"{x:,.2f}".replace(",", " ")

    out = [f"{acc.name} ({fmt_id(acc.customer_id)}) | {start:%d. %m.} - {end:%d. %m. %Y} | {cur} | práh: "
           f"{min_clicks} kliky nebo {money(thr)} {cur}",
           f"Dotazů {len(agg)}, útrata {money(total_cost)}. K posouzení {len(candidates)}"
           + (f", zobrazeno top {len(shown)}" if len(shown) < len(candidates) else "") + ".",
           f"Vynecháno: posouzené dřív {skip['decided']} | už vyloučené {skip['negated']} | v zásobníku "
           f"{skip['queued']} | = klíčové slovo "
           f"{skip['keyword']} | konvertující {skip['conv']} ({money(skip_cost['conv'])}) | pod prahem "
           f"{skip['low']} ({money(skip_cost['low'])})"
           + (f" | s e-mailem nebo telefonem {skip['pii']} (režim bez DPA, jsou jen v lokálním CSV)"
              if skip["pii"] else "")]
    if not pmax_cost:
        out.append("PMAX dotazy jsou bez útraty (Google ji pro ně nevrací) - řaď podle kliků.")
    if camps:
        out.append("Kampaně: " + " | ".join(f"{cc[c]} {c} ({camp_type.get(c, '')}) [{camp_id.get(c, '')}]"
                                            for c in camps))
    if groups:
        out.append("Sestavy: " + " | ".join(f"{gc[g]} {g[1]} ({cc[g[0]]}) [{group_id.get(g, '')}]" for g in groups))
    out.append("#\tdotaz\tkde\tkl\tútrata\tzobr")
    for i, (key, m, again) in enumerate(shown, 1):
        where = cc[key[1]] + (f"/{gc[(key[1], key[2])]}" if key[2] else "")
        flag = " (!dřív ponecháno)" if again else ""
        out.append(f"{i}\t{key[0]}{flag}\t{where}\t{m['clicks']}\t{money(m['cost'])}\t{m['impr']}")
    def code(k: tuple[str, str, str]) -> str:
        return cc[k[1]] + (f"/{gc[(k[1], k[2])]}" if k[2] else "")

    if watch_hits:
        out.append("SLEDOVANÁ SLOVA (vždy, i bez prokliku):")
        for wt, a in watch_hits:
            ex = ", ".join(f"{k[0]} [{code(k)}]" for k in a["ex"])
            out.append(f"  {wt}: dotazů {a['n']}, zobr {a['impr']}, kl {a['clicks']}, {money(a['cost'])} | {ex}")
    if noclick:
        out.append(f"POD PRAHEM S NEJVÍC ZOBRAZENÍMI (top {len(noclick)}):")
        out.append("#\tdotaz\tkde\tkl\tútrata\tzobr")
        for i, (key, m) in enumerate(noclick, 1):
            out.append(f"N{i}\t{key[0]}\t{code(key)}\t{m['clicks']}\t{money(m['cost'])}\t{m['impr']}")
    if top_words:
        out.append("SLOVA MIMO KLÍČOVÁ SLOVA A PRODUKTY (napříč nekonvertujícími dotazy):")
        out.append("slovo\tdotazů\tzobr\tkl\tútrata\tpříklad")
        for w, a in top_words:
            out.append(f"{w}\t{a['n']}\t{a['impr']}\t{a['clicks']}\t{money(a['cost'])}\t{a['ex'][0]}")
    if adds:
        out.append(f"KANDIDÁTI NA PŘIDÁNÍ (konvertují a nejsou klíčovým slovem): {len(to_add)}"
                   + (f", zobrazeno top {len(adds)}" if len(adds) < len(to_add) else ""))
        out.append("#\tdotaz\tkde\tkonv\tkl\tútrata")
        for i, a in enumerate(adds, 1):
            where = ", ".join(cc[k[1]] + (f"/{gc[(k[1], k[2])]}" if k[2] else "") for k in a["where"])
            conv = f"{a['conv']:.1f}".rstrip("0").rstrip(".")
            out.append(f"P{i}\t{a['term']}\t{where}\t{conv}\t{a['clicks']}\t{money(a['cost'])}")
    out.append(f"Kompletní export: {export}")
    return "\n".join(out)
