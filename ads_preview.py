from __future__ import annotations

import datetime as dt
import re
import zipfile
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

import ads_core as core

try:
    import ads_backlog as backlog
except ImportError:
    backlog = None
from ads_core import AdsError, fmt_id, get_account, load_accounts, search_raw

FOLDER = "nahledy_zmen"
BATCH_SHEET = "Dávka ze zásobníku"
BATCH_HEAD = ["Účet", "ID účtu", "Akce", "Text", "Shoda", "Úroveň", "Kampaň", "Sestava", "Důvod", "Priorita",
              "Útrata", "Zobrazení", "Pokryté dotazy", "ID položky", "Nasadit"]
PLAN_HEAD = ["Účet", "ID účtu", "Plán", "Změna", "Podrobnosti", "Chráněná", "Nasadit"]
YES = {"ano", "a", "yes", "y", "x", "1", "true"}
MATCH = {"EXACT": "přesná", "PHRASE": "frázová", "BROAD": "volná"}


def preview_dir() -> Path:
    d = core.clients_root().parent / FOLDER
    d.mkdir(parents=True, exist_ok=True)
    return d


def _col(i: int) -> str:
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def _cell(ref: str, v: Any, style: int) -> str:
    if v is None or v == "":
        return f'<c r="{ref}" s="{style}"/>'
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return f'<c r="{ref}" s="{style}"><v>{v}</v></c>'
    t = escape(str(v)).replace("\n", "&#10;")
    return f'<c r="{ref}" s="{style}" t="inlineStr"><is><t xml:space="preserve">{t}</t></is></c>'


def _sheet_xml(head: list[str], rows: list[list[Any]], widths: list[int], yes_col: int | None) -> str:
    out = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
           '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">',
           '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" '
           'state="frozen"/></sheetView></sheetViews><cols>']
    for i, w in enumerate(widths, 1):
        out.append(f'<col min="{i}" max="{i}" width="{w}" customWidth="1"/>')
    out.append("</cols><sheetData>")
    out.append('<row r="1">' + "".join(_cell(f"{_col(i)}1", h, 1) for i, h in enumerate(head)) + "</row>")
    for r, row in enumerate(rows, 2):
        cells = "".join(_cell(f"{_col(i)}{r}", v, 3 if i == yes_col else 2) for i, v in enumerate(row))
        out.append(f'<row r="{r}">{cells}</row>')
    out.append("</sheetData>")
    if rows:
        out.append(f'<autoFilter ref="A1:{_col(len(head) - 1)}{len(rows) + 1}"/>')
    out.append("</worksheet>")
    return "".join(out)


STYLES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
    '<fonts count="2"><font><sz val="10"/><name val="Arial"/></font>'
    '<font><b/><sz val="10"/><color rgb="FFFFFFFF"/><name val="Arial"/></font></fonts>'
    '<fills count="4"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill>'
    '<fill><patternFill patternType="solid"><fgColor rgb="FF1F3864"/></patternFill></fill>'
    '<fill><patternFill patternType="solid"><fgColor rgb="FFFFFF00"/></patternFill></fill></fills>'
    '<borders count="1"><border/></borders>'
    '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
    '<cellXfs count="4"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
    '<xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1" applyAlignment="1">'
    '<alignment wrapText="1" vertical="center"/></xf>'
    '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0" applyAlignment="1">'
    '<alignment wrapText="1" vertical="top"/></xf>'
    '<xf numFmtId="0" fontId="0" fillId="3" borderId="0" xfId="0" applyFill="1" applyAlignment="1">'
    '<alignment vertical="top"/></xf></cellXfs>'
    '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
    '</styleSheet>')


def _write_xlsx(path: Path, sheets: list[tuple[str, list[str], list[list[Any]], list[int], int | None]]) -> None:
    wb = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
          '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
          'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>']
    rels = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">']
    ct = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
          '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">',
          '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>',
          '<Default Extension="xml" ContentType="application/xml"/>',
          '<Override PartName="/xl/workbook.xml" '
          'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>',
          '<Override PartName="/xl/styles.xml" '
          'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>']
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for i, (name, head, rows, widths, yes_col) in enumerate(sheets, 1):
            wb.append(f'<sheet name="{escape(name[:31])}" sheetId="{i}" r:id="rId{i}"/>')
            rels.append(f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
                        f'relationships/worksheet" Target="worksheets/sheet{i}.xml"/>')
            ct.append(f'<Override PartName="/xl/worksheets/sheet{i}.xml" '
                      'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>')
            z.writestr(f"xl/worksheets/sheet{i}.xml", _sheet_xml(head, rows, widths, yes_col))
        n = len(sheets) + 1
        rels.append(f'<Relationship Id="rId{n}" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
                    'relationships/styles" Target="styles.xml"/>')
        wb.append("</sheets></workbook>")
        rels.append("</Relationships>")
        ct.append("</Types>")
        z.writestr("[Content_Types].xml", "".join(ct))
        z.writestr("_rels/.rels",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
                   'relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        z.writestr("xl/workbook.xml", "".join(wb))
        z.writestr("xl/_rels/workbook.xml.rels", "".join(rels))
        z.writestr("xl/styles.xml", STYLES)


NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
RNS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"


def _read_sheet(path: Path, sheet_name: str) -> list[list[str]]:
    import xml.etree.ElementTree as ET
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        shared: list[str] = []
        if "xl/sharedStrings.xml" in names:
            for si in ET.fromstring(z.read("xl/sharedStrings.xml")).iter(f"{NS}si"):
                shared.append("".join(t.text or "" for t in si.iter(f"{NS}t")))
        wb = ET.fromstring(z.read("xl/workbook.xml"))
        rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        targets = {r.get("Id"): r.get("Target") for r in rels}
        target = None
        for sh in wb.iter(f"{NS}sheet"):
            if sh.get("name") == sheet_name:
                target = targets.get(sh.get(f"{RNS}id"))
        if not target:
            return []
        target = target.lstrip("/")
        if not target.startswith("xl/"):
            target = "xl/" + target
        root = ET.fromstring(z.read(target))
    out: list[list[str]] = []
    for row in root.iter(f"{NS}row"):
        vals: dict[int, str] = {}
        for c in row.iter(f"{NS}c"):
            ref = c.get("r", "")
            letters = re.match(r"[A-Z]+", ref).group(0)
            idx = 0
            for ch in letters:
                idx = idx * 26 + (ord(ch) - 64)
            t = c.get("t")
            if t == "inlineStr":
                v = "".join(x.text or "" for x in c.iter(f"{NS}t"))
            else:
                ve = c.find(f"{NS}v")
                v = ve.text if ve is not None and ve.text else ""
                if t == "s" and v:
                    v = shared[int(v)]
            vals[idx - 1] = v
        if vals:
            out.append([vals.get(i, "") for i in range(max(vals) + 1)])
    return out


def _names(acc: core.Account, camp_ids: set[str], group_ids: set[str]) -> tuple[dict[str, str], dict[str, tuple[str, str]]]:
    camps: dict[str, str] = {}
    groups: dict[str, tuple[str, str]] = {}
    if camp_ids:
        q = f"SELECT campaign.id, campaign.name FROM campaign WHERE campaign.id IN ({', '.join(sorted(camp_ids))})"
        for r in search_raw(acc, q):
            camps[str(r.campaign.id)] = r.campaign.name
    if group_ids:
        q = ("SELECT ad_group.id, ad_group.name, campaign.name FROM ad_group "
             f"WHERE ad_group.id IN ({', '.join(sorted(group_ids))})")
        for r in search_raw(acc, q):
            groups[str(r.ad_group.id)] = (r.campaign.name, r.ad_group.name)
    return camps, groups


def build_preview(customer_ids: list[str] | None = None, per_account: int = 10,
                  counts: dict[str, int] | None = None) -> str:
    if customer_ids:
        accounts = [get_account(c) for c in customer_ids]
    else:
        all_acc = list(load_accounts().values())
        accounts = [a for a in all_acc if a.active] or all_acc
    counts = {re.sub(r"\D", "", k): int(v) for k, v in (counts or {}).items()}
    batch_rows: list[list[Any]] = []
    full_rows: list[list[Any]] = []
    summary: list[list[Any]] = []
    for acc in (accounts if backlog is not None else []):
        n = counts.get(acc.customer_id, per_account)
        opened = backlog.all_open(acc)
        batch = opened[:n]
        camp_ids = {r["cil_id"] for r in opened if r["uroven"] == "campaign"}
        group_ids = {r["cil_id"] for r in opened if r["uroven"] == "ad_group"}
        try:
            camps, groups = _names(acc, camp_ids, group_ids)
        except Exception:
            camps, groups = {}, {}

        def row(r: dict[str, str], with_yes: bool) -> list[Any]:
            if r["uroven"] == "campaign":
                camp, grp = camps.get(r["cil_id"], f"ID {r['cil_id']}"), ""
            else:
                camp, grp = groups.get(r["cil_id"], ("", f"ID {r['cil_id']}"))

            def num(x: str) -> Any:
                try:
                    return float(x) if "." in x else int(x)
                except (TypeError, ValueError):
                    return ""
            base = [acc.name, fmt_id(acc.customer_id), "Vyloučit" if r["akce"] == "vyloucit" else "Přidat KW",
                    r["text"], MATCH.get(r["shoda"], r["shoda"]),
                    "kampaň" if r["uroven"] == "campaign" else "sestava", camp, grp, r["duvod"],
                    int(r.get("priorita") or 2), num(r.get("utrata", "")), num(r.get("zobrazeni", "")),
                    r.get("dotazy", ""), r["id"]]
            return base + (["ano"] if with_yes else [])

        batch_rows += [row(r, True) for r in batch]
        full_rows += [row(r, False) for r in opened]
        summary.append([acc.name, fmt_id(acc.customer_id), len(batch), len(opened) - len(batch)])

    plans = core.list_plans()
    plan_rows = [[p.account.name, fmt_id(p.account.customer_id), p.id, p.title, "\n".join(p.lines),
                  ", ".join(core.GUARD_LABELS[g] for g in p.guard) if p.guard else "", "ano"] for p in plans]

    today = dt.date.today()
    path = preview_dir() / f"nahled_{today:%Y-%m-%d}_{dt.datetime.now():%H%M}.xlsx"
    if backlog is None:
        if not plan_rows:
            return "Žádné připravené plány, náhled nevznikl."
        _write_xlsx(path, [("Další připravené změny", PLAN_HEAD, plan_rows, [22, 14, 10, 34, 60, 22, 9], 6)])
        lines = [f"Náhled uložen: {path}", f"Připravené plány: {len(plan_rows)}"]
    else:
        _write_xlsx(path, [
            ("Souhrn", ["Účet", "ID účtu", "V dávce", "Zůstane v zásobníku"], summary, [28, 14, 10, 18], None),
            (BATCH_SHEET, BATCH_HEAD, batch_rows, [22, 14, 10, 30, 10, 9, 30, 24, 28, 8, 9, 10, 40, 12, 9], 14),
            ("Další připravené změny", PLAN_HEAD, plan_rows, [22, 14, 10, 34, 60, 22, 9], 6),
            ("Celý zásobník", BATCH_HEAD[:-1], full_rows, [22, 14, 10, 30, 10, 9, 30, 24, 28, 8, 9, 10, 40, 12],
             None),
        ])
        lines = [f"Náhled uložen: {path}",
                 f"Dávka: {len(batch_rows)} položek v {sum(1 for s in summary if s[2])} účtech | další připravené "
                 f"plány: {len(plan_rows)}"]
        lines += [f"  {s[0]}: {s[2]} (zbývá {s[3]})" for s in summary]
    lines.append("Uživatel může ve sloupci Nasadit přepsat ano na ne. Nasazení až po jeho souhlasu přes "
                 "release_preview.")
    return "\n".join(lines)


def latest_preview() -> Path:
    files = sorted(preview_dir().glob("nahled_*.xlsx"))
    if not files:
        raise AdsError("Žádný náhled zatím neexistuje. Nejdřív preview_changes.")
    return files[-1]


def release_preview(path: str | None = None) -> str:
    p = Path(path) if path else latest_preview()
    if not p.exists():
        raise AdsError(f"Náhled {p} neexistuje.")
    rows = _read_sheet(p, BATCH_SHEET) if backlog is not None else []
    out: list[str] = []
    if rows:
        out += _release_batch(p, rows)
    plan_rows = _read_sheet(p, "Další připravené změny")
    if len(plan_rows) > 1:
        h = plan_rows[0]
        ok = [r[h.index("Plán")] for r in plan_rows[1:] if len(r) > h.index("Nasadit")
              and r[h.index("Nasadit")].strip().lower() in YES]
        no = [r[h.index("Plán")] for r in plan_rows[1:] if r and r[h.index("Plán")] not in ok]
        if ok:
            out.append("Připravené plány schválené v náhledu: " + ", ".join(ok))
        if no:
            out.append("Plány vyřazené v náhledu (neprovádět, případně zahodit): " + ", ".join(no))
    return "\n\n".join(out) or "V náhledu není nic ke schválení."


def _release_batch(p: Path, rows: list[list[str]]) -> list[str]:
    head = rows[0]
    i_acc, i_id, i_yes = head.index("ID účtu"), head.index("ID položky"), head.index("Nasadit")
    per_acc: dict[str, list[str]] = {}
    skipped = 0
    for r in rows[1:]:
        r = r + [""] * (len(head) - len(r))
        if r[i_yes].strip().lower() in YES:
            per_acc.setdefault(r[i_acc], []).append(r[i_id])
        elif r[i_id]:
            skipped += 1
    out = [f"Z náhledu {p.name}: k nasazení {sum(len(v) for v in per_acc.values())} položek, vyřazeno {skipped}."]
    for cid, ids in per_acc.items():
        out.append(backlog.backlog_release(cid, ids=ids))
    return out
