from __future__ import annotations

import datetime as dt
import re
import uuid
from pathlib import Path
from typing import Any

from ads_core import (
    Account, AdsError, TempIds, check_local_path, client_for, create_custom_plan, create_plan, fmt_id, gaql_str,
    get_account, new_op, num_id, search_raw, set_update_mask,
)
from ads_media import (
    LABEL, VIDEO_EXT, ImageItem, existing_video_assets, image_asset_op, resolve_images,
    video_asset_op, youtube_id,
)
from ads_ops import _to_micros

AUTOMATION_OFF_DEFAULT = [
    "FINAL_URL_EXPANSION_TEXT_ASSET_AUTOMATION",
    "TEXT_ASSET_AUTOMATION",
    "GENERATE_IMAGE_ENHANCEMENT",
    "GENERATE_IMAGE_EXTRACTION",
    "GENERATE_ENHANCED_YOUTUBE_VIDEOS",
]
AUTOMATION_LABEL = {
    "FINAL_URL_EXPANSION_TEXT_ASSET_AUTOMATION": "rozšíření cílové adresy",
    "TEXT_ASSET_AUTOMATION": "přizpůsobení textu",
    "GENERATE_IMAGE_ENHANCEMENT": "vylepšení obrázků",
    "GENERATE_IMAGE_EXTRACTION": "obrázky z cílové stránky",
    "GENERATE_ENHANCED_YOUTUBE_VIDEOS": "vylepšení videa",
}


def _check_url(url: str, what: str = "final_url") -> str:
    if not re.match(r"^https?://\S+$", url or ""):
        raise AdsError(f"{what} musí být celá adresa začínající http(s)://")
    return url


def resolve_languages(acc: Account, codes: list[str]) -> list[tuple[str, str]]:
    if not codes:
        raise AdsError("Zadej aspoň jeden jazyk (např. cs).")
    ids = [c for c in codes if re.fullmatch(r"\d+", c.strip())]
    names = [c.strip().lower() for c in codes if c not in ids]
    out: dict[str, tuple[str, str]] = {}
    conds = []
    if names:
        conds.append("language_constant.code IN (" + ", ".join(gaql_str(n) for n in names) + ")")
    if ids:
        conds.append("language_constant.id IN (" + ", ".join(ids) + ")")
    for cond in conds:
        for r in search_raw(acc, f"SELECT language_constant.id, language_constant.code, language_constant.name "
                                 f"FROM language_constant WHERE {cond}"):
            lc = r.language_constant
            out[lc.code.lower()] = (f"languageConstants/{lc.id}", f"{lc.name} ({lc.code})")
            out[str(lc.id)] = out[lc.code.lower()]
    missing = [c for c in names + ids if c not in out]
    if missing:
        raise AdsError(f"Neznámý jazyk: {', '.join(missing)}")
    return list(dict.fromkeys(out[c] for c in names + ids))


def resolve_locations(acc: Account, items: list[str]) -> list[tuple[str, str]]:
    if not items:
        raise AdsError("Zadej aspoň jednu lokalitu (ID z find_geo_targets nebo kód země, např. CZ).")
    ids = [i.strip() for i in items if re.fullmatch(r"\s*\d+\s*", i)]
    countries = [i.strip().upper() for i in items if re.fullmatch(r"\s*[A-Za-z]{2}\s*", i)]
    bad = [i for i in items if i.strip() not in ids and i.strip().upper() not in countries]
    if bad:
        raise AdsError(f"Lokalitu zadej jako ID (find_geo_targets) nebo kód země: {', '.join(bad)}")
    out: dict[str, tuple[str, str]] = {}
    sel = ("SELECT geo_target_constant.id, geo_target_constant.canonical_name, geo_target_constant.country_code, "
           "geo_target_constant.target_type, geo_target_constant.status FROM geo_target_constant WHERE ")
    if ids:
        for r in search_raw(acc, sel + f"geo_target_constant.id IN ({', '.join(ids)})"):
            g = r.geo_target_constant
            out[str(g.id)] = (f"geoTargetConstants/{g.id}", f"{g.canonical_name} ({g.target_type})")
    if countries:
        q = sel + ("geo_target_constant.country_code IN (" + ", ".join(gaql_str(c) for c in countries) +
                   ") AND geo_target_constant.target_type = 'Country'")
        for r in search_raw(acc, q):
            g = r.geo_target_constant
            out[g.country_code.upper()] = (f"geoTargetConstants/{g.id}", g.canonical_name)
    missing = [k for k in ids + countries if k not in out]
    if missing:
        raise AdsError(f"Lokalita nenalezena: {', '.join(missing)}")
    return list(dict.fromkeys(out[k] for k in ids + countries))


def find_geo_targets(customer_id: str, names: list[str], country_code: str = "CZ") -> str:
    acc = get_account(customer_id)
    client = client_for(acc)
    svc = client.get_service("GeoTargetConstantService")
    req = client.get_type("SuggestGeoTargetConstantsRequest")
    req.locale = "cs"
    if country_code:
        req.country_code = country_code.upper()
    req.location_names.names.extend(names)
    out = []
    for s in svc.suggest_geo_target_constants(request=req).geo_target_constant_suggestions:
        g = s.geo_target_constant
        out.append(f"{g.id}  {g.canonical_name}  ({g.target_type}, dosah {s.reach:,})".replace(",", " "))
    return "\n".join(out) or "Nic nenalezeno."


def targeting_ops(client: Any, campaign_rn: str, locations: list[tuple[str, str]],
                  languages: list[tuple[str, str]]) -> list[Any]:
    ops = []
    for rn, _ in locations:
        op = new_op(client)
        c = op.campaign_criterion_operation.create
        c.campaign = campaign_rn
        c.location.geo_target_constant = rn
        ops.append(op)
    for rn, _ in languages:
        op = new_op(client)
        c = op.campaign_criterion_operation.create
        c.campaign = campaign_rn
        c.language.language_constant = rn
        ops.append(op)
    return ops


def propose_upload_images(customer_id: str, sources: list[str], logos: bool = False) -> str:
    acc = get_account(customer_id)
    client = client_for(acc)
    items = [i for i in resolve_images(acc, sources) if i.data is not None]
    if not items:
        raise AdsError("Žádné nové obrázky k nahrání (všechno jsou existující assety).")
    tmp = TempIds()
    ops, labels, lines, warn = [], [], [], []
    for it in items:
        ft = it.field_type(logo=logos)
        if ft is None:
            warn.append(f"{it.label}: poměr {it.width}×{it.height} nesedí na žádný formát "
                        f"{'loga' if logos else 'PMAX/Demand Gen'} - do knihovny ho nahraju, ale do sestavy nepůjde")
        elif (msg := it.check(ft)):
            warn.append(msg)
        op, _ = image_asset_op(client, acc.customer_id, tmp, it)
        ops.append(op)
        labels.append(it.label)
        lines.append(it.describe(ft))
    return create_plan(acc, f"Nahrát obrázky do knihovny ({len(ops)}×)", lines, ops, warn, labels=labels)


def propose_youtube_videos(customer_id: str, videos: list[str]) -> str:
    acc = get_account(customer_id)
    client = client_for(acc)
    ids = list(dict.fromkeys(youtube_id(v) for v in videos))
    existing = existing_video_assets(acc, ids)
    tmp = TempIds()
    ops, labels, lines = [], [], []
    for vid in ids:
        if vid in existing:
            lines.append(f"{vid} už v knihovně je ({existing[vid]})")
            continue
        op, _ = video_asset_op(client, acc.customer_id, tmp, vid)
        ops.append(op)
        labels.append(f"YouTube {vid}")
        lines.append(f"Přidat video https://youtu.be/{vid}")
    return create_plan(acc, f"Přidat YouTube videa do knihovny ({len(ops)}×)", lines, ops, labels=labels)


def _opravit_chyby_nahravani() -> None:
    import sys

    def kontrola(response: Any, version: str | None = None) -> None:
        if not response.ok:
            raise AdsError(f"Nahrávání videa selhalo: HTTP {response.status_code} {response.reason}\n"
                           f"{(response.text or '')[:1500]}")

    for name, mod in list(sys.modules.items()):
        if name.endswith("you_tube_video_upload_service.transports.resumable_upload"):
            mod.raise_formatted_for_status = kontrola


def propose_video_upload(customer_id: str, file_path: str, title: str, description: str = "") -> str:
    acc = get_account(customer_id)
    client = client_for(acc)
    p = Path(file_path.strip().strip('"')).expanduser()
    if not p.is_file():
        raise AdsError(f"Soubor neexistuje: {file_path}")
    check_local_path(acc, p)
    if p.suffix.lower() not in VIDEO_EXT:
        raise AdsError(f"{p.name} nevypadá jako video ({', '.join(sorted(VIDEO_EXT))}).")
    size = p.stat().st_size
    if size > 2 * 1024 ** 3:
        raise AdsError("Video je větší než 2 GB.")
    if not title.strip():
        raise AdsError("Video potřebuje název.")

    def run() -> str:
        svc = client.get_service("YouTubeVideoUploadService")
        _opravit_chyby_nahravani()
        upload = client.get_type("YouTubeVideoUpload")
        upload.video_title = title.strip()[:100]
        upload.video_description = description.strip()[:5000]
        upload.video_privacy = client.enums.YouTubeVideoPrivacyEnum.UNLISTED
        with p.open("rb") as fh:
            resp = svc.create_you_tube_video_upload(customer_id=acc.customer_id, you_tube_video_upload=upload,
                                                    stream=fh)
        if f"customers/{acc.customer_id}/" not in resp.resource_name:
            raise AdsError(f"Google vrátil nečekaný účet: {resp.resource_name} - zkontroluj to v rozhraní!")
        return (f"Video nahráno do účtu {acc.name}: {resp.resource_name}\nYouTube ho teď zpracovává. Stav a ID videa zjistíš přes "
                "video_upload_status, potom ho přidej do knihovny přes propose_youtube_videos.")

    lines = [f"Cílový účet: {acc.name} ({fmt_id(acc.customer_id)}) - kanál YouTube spravovaný Googlem pro tento účet",
             f"Soubor: {p} ({size / 1024 ** 2:.1f} MB) - ve složce klienta {acc.folder}",
             f"Název: {title.strip()[:100]}", "Viditelnost: neveřejné (UNLISTED)"]
    return create_custom_plan(acc, "Nahrát video na YouTube", lines, run)


def video_upload_status(customer_id: str) -> str:
    acc = get_account(customer_id)
    rows = search_raw(acc, "SELECT you_tube_video_upload.resource_name, you_tube_video_upload.state, "
                           "you_tube_video_upload.video_id FROM you_tube_video_upload")
    if not rows:
        return "Žádná nahraná videa."
    rows = sorted(rows, key=lambda r: int(r.you_tube_video_upload.resource_name.rsplit("/", 1)[-1]))
    radky = [f"{r.you_tube_video_upload.resource_name} | {r.you_tube_video_upload.state.name} | "
             f"video_id {r.you_tube_video_upload.video_id or '-'}" for r in rows[-20:]]
    hlava = f"Nahraných videí celkem {len(rows)}, níže posledních {len(radky)}:" if len(rows) > 20 else ""
    return "\n".join(([hlava] if hlava else []) + radky)


CUSTOM_LABEL_RE = re.compile(r"custom_label_([0-4])")


def _set_dimension(client: Any, cv: Any, dimension: str, value: str | None, depth: int) -> None:
    m = CUSTOM_LABEL_RE.fullmatch(dimension)
    if m:
        cv.product_custom_attribute.index = client.enums.ListingGroupFilterCustomAttributeIndexEnum[f"INDEX{m.group(1)}"]
        if value is not None:
            cv.product_custom_attribute.value = value
    elif dimension == "product_type":
        cv.product_type.level = client.enums.ListingGroupFilterProductTypeLevelEnum[f"LEVEL{depth}"]
        if value is not None:
            cv.product_type.value = value
    elif dimension == "brand":
        if value is None:
            cv.product_brand._pb.SetInParent()
        else:
            cv.product_brand.value = value
    elif dimension == "item_id":
        if value is None:
            cv.product_item_id._pb.SetInParent()
        else:
            cv.product_item_id.value = value
    else:
        raise AdsError("dimension musí být custom_label_0 až custom_label_4, product_type, brand nebo item_id.")


def listing_tree_ops(client: Any, cid: str, ag_id: str, spec: dict[str, Any] | None,
                     tmp: TempIds) -> tuple[list[Any], list[str]]:
    ops: list[Any] = []

    def node(parent_rn: str | None, ftype: str, dim: str | None = None, value: str | None = None,
             depth: int = 1, other: bool = False) -> str:
        rn = f"customers/{cid}/assetGroupListingGroupFilters/{ag_id}~{tmp.next()}"
        op = new_op(client)
        f = op.asset_group_listing_group_filter_operation.create
        f.resource_name = rn
        f.asset_group = f"customers/{cid}/assetGroups/{ag_id}"
        f.type_ = client.enums.ListingGroupFilterTypeEnum[ftype]
        f.listing_source = client.enums.ListingGroupFilterListingSourceEnum.SHOPPING
        if parent_rn:
            f.parent_listing_group_filter = parent_rn
            _set_dimension(client, f.case_value, dim, None if other else value, depth)
        ops.append(op)
        return rn

    if not spec or not spec.get("values"):
        node(None, "UNIT_INCLUDED")
        return ops, ["Skupiny produktů: všechny produkty"]

    dim = spec["dimension"]
    mode = spec.get("mode", "include")
    if mode not in ("include", "exclude"):
        raise AdsError("listing_groups.mode musí být include nebo exclude.")
    unit = "UNIT_INCLUDED" if mode == "include" else "UNIT_EXCLUDED"
    rest = "UNIT_EXCLUDED" if mode == "include" else "UNIT_INCLUDED"
    sep = " > " if dim == "product_type" else None
    paths = [[p.strip() for p in (v.split(">") if sep else [v])] for v in spec["values"]]
    if dim != "product_type" and any(len(p) > 1 for p in paths):
        raise AdsError("Vnořené cesty (A > B) jdou jen u product_type.")

    def build(parent_rn: str, group: list[list[str]], depth: int) -> None:
        if depth > 5:
            raise AdsError("product_type má max 5 úrovní.")
        heads: dict[str, list[list[str]]] = {}
        for p in group:
            heads.setdefault(p[0], []).append(p[1:])
        for head, tails in heads.items():
            leaf = any(not t for t in tails)
            deeper = [t for t in tails if t]
            if leaf and deeper:
                raise AdsError(f"„{head}“ je zároveň celá skupina i nadřazená úroveň - vyber jedno.")
            if leaf:
                node(parent_rn, unit, dim, head, depth)
            else:
                sub = node(parent_rn, "SUBDIVISION", dim, head, depth)
                build(sub, deeper, depth + 1)
        node(parent_rn, rest, dim, None, depth, other=True)

    root = node(None, "SUBDIVISION")
    build(root, paths, 1)
    verb = "jen" if mode == "include" else "vše kromě"
    return ops, [f"Skupiny produktů: {verb} {dim} = " + ", ".join(spec["values"])]


def _remove_listing_tree_ops(acc: Account, client: Any, ag_id: str) -> list[Any]:
    rows = search_raw(acc, "SELECT asset_group_listing_group_filter.resource_name, "
                           "asset_group_listing_group_filter.parent_listing_group_filter "
                           f"FROM asset_group_listing_group_filter WHERE asset_group.id = {ag_id}")
    parent = {r.asset_group_listing_group_filter.resource_name:
              r.asset_group_listing_group_filter.parent_listing_group_filter for r in rows}

    def depth(rn: str) -> int:
        d = 0
        while parent.get(rn):
            rn = parent[rn]
            d += 1
        return d

    ops = []
    for rn in sorted(parent, key=depth, reverse=True):
        op = new_op(client)
        op.asset_group_listing_group_filter_operation.remove = rn
        ops.append(op)
    return ops


def _text_checks(spec: dict[str, Any], need_assets: bool) -> list[str]:
    errs = []
    h, lh, d = spec.get("headlines") or [], spec.get("long_headlines") or [], spec.get("descriptions") or []
    if need_assets:
        if not 3 <= len(h) <= 15:
            errs.append(f"nadpisů musí být 3-15 (je {len(h)})")
        if not 1 <= len(lh) <= 5:
            errs.append(f"dlouhých nadpisů musí být 1-5 (je {len(lh)})")
        if not 2 <= len(d) <= 5:
            errs.append(f"popisků musí být 2-5 (je {len(d)})")
        if d and min(len(x) for x in d) > 60:
            errs.append("aspoň jeden popisek musí mít max 60 znaků")
    errs += [f"nadpis {len(x)} znaků (max 30): {x!r}" for x in h if len(x) > 30]
    errs += [f"dlouhý nadpis {len(x)} znaků (max 90): {x!r}" for x in lh if len(x) > 90]
    errs += [f"popisek {len(x)} znaků (max 90): {x!r}" for x in d if len(x) > 90]
    if len({x.strip().lower() for x in h}) != len(h):
        errs.append("nadpisy obsahují duplicity")
    for p in ("path1", "path2"):
        if spec.get(p) and len(spec[p]) > 15:
            errs.append(f"{p} má víc než 15 znaků")
    if spec.get("business_name") and len(spec["business_name"]) > 25:
        errs.append("název firmy má víc než 25 znaků")
    themes = spec.get("search_themes") or []
    if len(themes) > 50:
        errs.append(f"témat vyhledávání je {len(themes)}, max 50")
    return errs


def asset_group_ops(acc: Account, client: Any, tmp: TempIds, campaign_rn: str, spec: dict[str, Any],
                    retail: bool, brand_guidelines: bool) -> tuple[list[Any], list[str], list[str | None], list[str], int]:
    cid = acc.customer_id
    name = (spec.get("name") or "").strip()
    if not name:
        raise AdsError("Sestava podkladů potřebuje název.")
    final_url = _check_url(spec.get("final_url", ""))
    has_assets = any(spec.get(k) for k in ("headlines", "long_headlines", "descriptions", "images", "videos", "logos"))
    if not retail and not has_assets:
        raise AdsError("Sestava v kampani bez Merchant Center musí mít podklady.")
    errs = _text_checks(spec, need_assets=has_assets)

    images = resolve_images(acc, spec.get("images") or [])
    logos = resolve_images(acc, spec.get("logos") or [])
    typed: list[tuple[ImageItem, str]] = []
    for it in images:
        ft = it.field_type()
        if ft is None or ft == "TALL_PORTRAIT_MARKETING_IMAGE":
            errs.append(f"{it.label}: {it.width}×{it.height} nesedí na 1.91:1, 1:1 ani 4:5")
            continue
        if (m := it.check(ft)):
            errs.append(m)
        typed.append((it, ft))
    for it in logos:
        ft = it.field_type(logo=True)
        if ft is None:
            errs.append(f"logo {it.label}: {it.width}×{it.height} nesedí na 1:1 ani 4:1")
            continue
        if (m := it.check(ft)):
            errs.append(m)
        typed.append((it, ft))
    counts: dict[str, int] = {}
    for _, ft in typed:
        counts[ft] = counts.get(ft, 0) + 1
    if has_assets:
        if not counts.get("MARKETING_IMAGE"):
            errs.append("chybí obrázek na šířku 1.91:1")
        if not counts.get("SQUARE_MARKETING_IMAGE"):
            errs.append("chybí čtvercový obrázek 1:1")
        if sum(counts.get(k, 0) for k in ("MARKETING_IMAGE", "SQUARE_MARKETING_IMAGE", "PORTRAIT_MARKETING_IMAGE")) > 20:
            errs.append("obrázků je víc než 20")
        if not brand_guidelines:
            if not spec.get("business_name"):
                errs.append("kampaň nemá brand guidelines - sestava potřebuje business_name")
            if not counts.get("LOGO"):
                errs.append("kampaň nemá brand guidelines - sestava potřebuje logo 1:1")
    if brand_guidelines and (logos or spec.get("business_name")):
        errs.append("kampaň má brand guidelines - název firmy a loga patří ke kampani, ne do sestavy")
    videos = [youtube_id(v) for v in spec.get("videos") or []]
    if len(videos) > 15:
        errs.append("videí je víc než 15")
    if errs:
        raise AdsError(f"Sestava „{name}“ neprošla kontrolou:\n- " + "\n- ".join(errs))

    ag_tmp = tmp.next()
    ag_rn = f"customers/{cid}/assetGroups/{ag_tmp}"
    ops: list[Any] = []
    labels: list[str | None] = []
    op = new_op(client)
    ag = op.asset_group_operation.create
    ag.resource_name = ag_rn
    ag.name = name
    ag.campaign = campaign_rn
    ag.final_urls.append(final_url)
    ag.status = client.enums.AssetGroupStatusEnum[spec.get("status", "ENABLED")]
    if spec.get("path1"):
        ag.path1 = spec["path1"]
    if spec.get("path2"):
        ag.path2 = spec["path2"]
    ops.append(op)
    labels.append(f"sestava {name}")

    links: list[tuple[str, str]] = []

    def text_asset(text: str, ft: str) -> None:
        rn = f"customers/{cid}/assets/{tmp.next()}"
        o = new_op(client)
        a = o.asset_operation.create
        a.resource_name = rn
        a.text_asset.text = text.strip()
        ops.append(o)
        labels.append(None)
        links.append((rn, ft))

    for t in spec.get("headlines") or []:
        text_asset(t, "HEADLINE")
    for t in spec.get("long_headlines") or []:
        text_asset(t, "LONG_HEADLINE")
    for t in spec.get("descriptions") or []:
        text_asset(t, "DESCRIPTION")
    if spec.get("business_name"):
        text_asset(spec["business_name"], "BUSINESS_NAME")
    for it, ft in typed:
        if it.asset_rn:
            links.append((it.asset_rn, ft))
        else:
            o, rn = image_asset_op(client, cid, tmp, it)
            ops.append(o)
            labels.append(f"obrázek {it.label}")
            links.append((rn, ft))
    existing_v = existing_video_assets(acc, videos)
    for vid in dict.fromkeys(videos):
        if vid in existing_v:
            links.append((existing_v[vid], "YOUTUBE_VIDEO"))
        else:
            o, rn = video_asset_op(client, cid, tmp, vid)
            ops.append(o)
            labels.append(f"video {vid}")
            links.append((rn, "YOUTUBE_VIDEO"))
    if spec.get("call_to_action"):
        rn = f"customers/{cid}/assets/{tmp.next()}"
        o = new_op(client)
        a = o.asset_operation.create
        a.resource_name = rn
        a.call_to_action_asset.call_to_action = client.enums.CallToActionTypeEnum[spec["call_to_action"]]
        ops.append(o)
        labels.append(None)
        links.append((rn, "CALL_TO_ACTION_SELECTION"))
    for rn, ft in links:
        o = new_op(client)
        l = o.asset_group_asset_operation.create
        l.asset_group = ag_rn
        l.asset = rn
        l.field_type = client.enums.AssetFieldTypeEnum[ft]
        ops.append(o)
        labels.append(None)

    for theme in dict.fromkeys(t.strip() for t in spec.get("search_themes") or [] if t.strip()):
        o = new_op(client)
        s = o.asset_group_signal_operation.create
        s.asset_group = ag_rn
        s.search_theme.text = theme
        ops.append(o)
        labels.append(None)
    if spec.get("audience_id"):
        o = new_op(client)
        s = o.asset_group_signal_operation.create
        s.asset_group = ag_rn
        s.audience.audience = f"customers/{cid}/audiences/{num_id(spec['audience_id'], 'ID publika')}"
        ops.append(o)
        labels.append(None)

    tree_lines: list[str] = []
    if retail:
        tops, tree_lines = listing_tree_ops(client, cid, str(ag_tmp), spec.get("listing_groups"), tmp)
        ops += tops
        labels += [None] * len(tops)
    elif spec.get("listing_groups"):
        raise AdsError("Skupiny produktů jdou jen v kampani napojené na Merchant Center.")

    lines = [f"Sestava „{name}“ → {final_url}" + (f" (/{spec.get('path1')}" + (f"/{spec['path2']}" if spec.get('path2') else "") + ")" if spec.get("path1") else "")]
    if spec.get("headlines"):
        lines.append(f"  Nadpisy ({len(spec['headlines'])}): " + " | ".join(spec["headlines"]))
    if spec.get("long_headlines"):
        lines.append(f"  Dlouhé nadpisy ({len(spec['long_headlines'])}): " + " | ".join(spec["long_headlines"]))
    if spec.get("descriptions"):
        lines.append(f"  Popisky ({len(spec['descriptions'])}): " + " | ".join(spec["descriptions"]))
    if spec.get("business_name"):
        lines.append(f"  Název firmy: {spec['business_name']}")
    if typed:
        lines.append(f"  Obrázky ({len(typed)}): " + ", ".join(f"{LABEL[k]} {v}×" for k, v in counts.items()))
        lines += [f"    {i + 1}. {it.describe(ft)}" for i, (it, ft) in enumerate(typed)]
    if videos:
        lines.append(f"  Videa ({len(videos)}): " + ", ".join(videos))
    if spec.get("call_to_action"):
        lines.append(f"  Výzva k akci: {spec['call_to_action']}")
    if spec.get("search_themes"):
        lines.append(f"  Témata vyhledávání ({len(spec['search_themes'])}): " + ", ".join(spec["search_themes"]))
    if spec.get("audience_id"):
        lines.append(f"  Signál publika: audience {spec['audience_id']}")
    lines += [f"  {l}" for l in tree_lines]
    if not has_assets:
        lines.append("  Bez podkladů (jen produkty z feedu)")
    return ops, lines, labels, [], ag_tmp


def _campaign_info(acc: Account, campaign_id: str) -> Any:
    rows = search_raw(acc, "SELECT campaign.id, campaign.name, campaign.advertising_channel_type, "
                           "campaign.shopping_setting.merchant_id, campaign.brand_guidelines_enabled "
                           f"FROM campaign WHERE campaign.id = {campaign_id}")
    if not rows:
        raise AdsError(f"Kampaň {campaign_id} v účtu {acc.name} nenalezena.")
    c = rows[0].campaign
    if c.advertising_channel_type.name != "PERFORMANCE_MAX":
        raise AdsError(f"Kampaň „{c.name}“ není Performance Max.")
    return c


def propose_asset_group(customer_id: str, campaign_id: str, spec: dict[str, Any]) -> str:
    acc = get_account(customer_id)
    client = client_for(acc)
    camp = num_id(campaign_id, "ID kampaně")
    c = _campaign_info(acc, camp)
    retail = bool(c.shopping_setting.merchant_id)
    tmp = TempIds()
    ops, lines, labels, warn, _ = asset_group_ops(acc, client, tmp, f"customers/{acc.customer_id}/campaigns/{camp}",
                                                  spec, retail, bool(c.brand_guidelines_enabled))
    lines.insert(0, f"Kampaň „{c.name}“" + (" (Merchant Center)" if retail else ""))
    return create_plan(acc, f"Nová sestava podkladů „{spec.get('name')}“", lines, ops, warn, labels=labels)


def _automation_settings(client: Any, campaign: Any, opt_out: list[str]) -> None:
    S = type(campaign).AssetAutomationSetting
    for t in opt_out:
        try:
            atype = client.enums.AssetAutomationTypeEnum[t]
        except KeyError:
            raise AdsError(f"Neznámý typ automatiky {t!r}.")
        campaign.asset_automation_settings.append(
            S(asset_automation_type=atype, asset_automation_status=client.enums.AssetAutomationStatusEnum.OPTED_OUT))


def propose_pmax_campaign(customer_id: str, name: str, daily_budget: float, bidding: str,
                          locations: list[str], languages: list[str], target_roas: float | None = None,
                          target_cpa: float | None = None, merchant_id: str | None = None,
                          feed_label: str | None = None, business_name: str | None = None,
                          logos: list[str] | None = None, automation_opt_out: list[str] | None = None,
                          end_date: str | None = None, status: str = "PAUSED",
                          asset_groups: list[dict[str, Any]] | None = None) -> str:
    acc = get_account(customer_id)
    client = client_for(acc)
    cid = acc.customer_id
    if daily_budget <= 0:
        raise AdsError("Rozpočet musí být kladný.")
    if status not in ("PAUSED", "ENABLED"):
        raise AdsError("status musí být PAUSED nebo ENABLED.")
    retail = bool(merchant_id)
    asset_groups = asset_groups or []
    if not asset_groups:
        raise AdsError("PMAX kampaň se zakládá rovnou s aspoň jednou sestavou podkladů (asset_groups).")
    exists = search_raw(acc, f"SELECT campaign.id FROM campaign WHERE campaign.name = {gaql_str(name)} "
                             "AND campaign.status != REMOVED")
    if exists:
        raise AdsError(f"Kampaň „{name}“ už v účtu je (ID {exists[0].campaign.id}).")
    brand_guidelines = bool(business_name)
    if brand_guidelines and len(business_name) > 25:
        raise AdsError("Název firmy má max 25 znaků.")
    logo_items = resolve_images(acc, logos or [])
    if brand_guidelines and not logo_items:
        raise AdsError("S názvem firmy na úrovni kampaně (brand guidelines) je potřeba i logo 1:1.")
    if logo_items and not brand_guidelines:
        raise AdsError("Loga na úrovni kampaně jdou jen s business_name. Jinak je dej do sestavy.")
    locs = resolve_locations(acc, locations)
    langs = resolve_languages(acc, languages)
    opt_out = AUTOMATION_OFF_DEFAULT if automation_opt_out is None else automation_opt_out

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
    c.advertising_channel_type = client.enums.AdvertisingChannelTypeEnum.PERFORMANCE_MAX
    c.campaign_budget = budget_rn
    c.contains_eu_political_advertising = \
        client.enums.EuPoliticalAdvertisingStatusEnum.DOES_NOT_CONTAIN_EU_POLITICAL_ADVERTISING
    c.geo_target_type_setting.positive_geo_target_type = client.enums.PositiveGeoTargetTypeEnum.PRESENCE
    c.geo_target_type_setting.negative_geo_target_type = client.enums.NegativeGeoTargetTypeEnum.PRESENCE
    c.brand_guidelines_enabled = brand_guidelines
    if bidding == "MAXIMIZE_CONVERSION_VALUE":
        c.maximize_conversion_value._pb.SetInParent()
        if target_roas:
            if target_roas > 50:
                raise AdsError("target_roas je poměr (4.0 = 400 %).")
            c.maximize_conversion_value.target_roas = float(target_roas)
        bid_txt = "Maximalizace hodnoty konv." + (f", cílová ROAS {target_roas * 100:.0f} %" if target_roas else "")
    elif bidding == "MAXIMIZE_CONVERSIONS":
        c.maximize_conversions._pb.SetInParent()
        if target_cpa:
            c.maximize_conversions.target_cpa_micros = _to_micros(target_cpa)
        bid_txt = "Maximalizace konverzí" + (f", cílová CPA {target_cpa:.2f}" if target_cpa else "")
    else:
        raise AdsError("bidding je MAXIMIZE_CONVERSION_VALUE nebo MAXIMIZE_CONVERSIONS.")
    if retail:
        c.shopping_setting.merchant_id = int(num_id(merchant_id, "Merchant ID"))
        if feed_label:
            c.shopping_setting.feed_label = feed_label
    if end_date:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", end_date):
            raise AdsError("end_date ve tvaru RRRR-MM-DD.")
        c.end_date_time = f"{end_date} 23:59:59"
    _automation_settings(client, c, opt_out)
    ops.append(op)
    labels.append("kampaň")

    t_ops = targeting_ops(client, camp_rn, locs, langs)
    ops += t_ops
    labels += [None] * len(t_ops)

    if brand_guidelines:
        rn = f"customers/{cid}/assets/{tmp.next()}"
        o = new_op(client)
        a = o.asset_operation.create
        a.resource_name = rn
        a.text_asset.text = business_name
        ops.append(o)
        labels.append(None)
        brand_links = [(rn, "BUSINESS_NAME")]
        for it in logo_items:
            ft = it.field_type(logo=True)
            if ft is None:
                raise AdsError(f"logo {it.label}: {it.width}×{it.height} nesedí na 1:1 ani 4:1")
            if (m := it.check(ft)):
                raise AdsError(m)
            if it.asset_rn:
                brand_links.append((it.asset_rn, ft))
            else:
                o, lrn = image_asset_op(client, cid, tmp, it)
                ops.append(o)
                labels.append(f"logo {it.label}")
                brand_links.append((lrn, ft))
        for arn, ft in brand_links:
            o = new_op(client)
            l = o.campaign_asset_operation.create
            l.campaign = camp_rn
            l.asset = arn
            l.field_type = client.enums.AssetFieldTypeEnum[ft]
            ops.append(o)
            labels.append(None)

    lines = [f"Kampaň „{name}“ | Performance Max | {status}",
             f"Rozpočet {daily_budget:.2f}/den | {bid_txt}",
             "Lokality (přítomnost): " + ", ".join(n for _, n in locs),
             "Jazyky: " + ", ".join(n for _, n in langs),
             "Vypnuté automatiky: " + (", ".join(AUTOMATION_LABEL.get(t, t) for t in opt_out) or "žádné")]
    if retail:
        lines.append(f"Merchant Center {merchant_id}" + (f", feed label {feed_label}" if feed_label else ""))
    if brand_guidelines:
        lines.append(f"Brand guidelines: název „{business_name}“, loga {len(logo_items)}×")
    if end_date:
        lines.append(f"Konec: {end_date}")
    for spec in asset_groups:
        g_ops, g_lines, g_labels, _, _ = asset_group_ops(acc, client, tmp, camp_rn, spec, retail, brand_guidelines)
        ops += g_ops
        labels += g_labels
        lines += g_lines
    return create_plan(acc, f"Nová PMAX kampaň „{name}“", lines, ops, labels=labels,
                       guard=["enable"] if status == "ENABLED" else [])


def _asset_group_info(acc: Account, ag_id: str) -> Any:
    rows = search_raw(acc, "SELECT asset_group.id, asset_group.name, campaign.id, campaign.name, "
                           "campaign.shopping_setting.merchant_id, campaign.brand_guidelines_enabled "
                           f"FROM asset_group WHERE asset_group.id = {ag_id}")
    if not rows:
        raise AdsError(f"Sestava podkladů {ag_id} nenalezena.")
    return rows[0]


def propose_listing_groups(customer_id: str, asset_group_id: str, spec: dict[str, Any] | None) -> str:
    acc = get_account(customer_id)
    client = client_for(acc)
    ag = num_id(asset_group_id, "ID sestavy podkladů")
    r = _asset_group_info(acc, ag)
    if not r.campaign.shopping_setting.merchant_id:
        raise AdsError("Kampaň není napojená na Merchant Center, skupiny produktů nemá.")
    remove = _remove_listing_tree_ops(acc, client, ag)
    tmp = TempIds()
    create, tl = listing_tree_ops(client, acc.customer_id, ag, spec, tmp)
    lines = [f"Sestava „{r.asset_group.name}“ (kampaň {r.campaign.name})",
             f"Odebrat stávající strom: {len(remove)} uzlů"] + tl
    return create_plan(acc, "Nastavit skupiny produktů", lines, remove + create, guard=["listing_groups"])


def propose_search_themes(customer_id: str, asset_group_id: str, add: list[str] | None = None,
                          remove: list[str] | None = None) -> str:
    acc = get_account(customer_id)
    client = client_for(acc)
    ag = num_id(asset_group_id, "ID sestavy podkladů")
    r = _asset_group_info(acc, ag)
    rows = search_raw(acc, "SELECT asset_group_signal.resource_name, asset_group_signal.search_theme.text "
                           f"FROM asset_group_signal WHERE asset_group.id = {ag}")
    current = {x.asset_group_signal.search_theme.text.lower(): x.asset_group_signal.resource_name
               for x in rows if x.asset_group_signal.search_theme.text}
    ops, lines = [], [f"Sestava „{r.asset_group.name}“ (kampaň {r.campaign.name}), dnes témat: {len(current)}"]
    removed = []
    for t in remove or []:
        rn = current.pop(t.strip().lower(), None)
        if rn:
            o = new_op(client)
            o.asset_group_signal_operation.remove = rn
            ops.append(o)
            removed.append(t.strip())
    added, skipped = [], []
    for t in dict.fromkeys(x.strip() for x in add or [] if x.strip()):
        if t.lower() in current:
            skipped.append(t)
            continue
        o = new_op(client)
        s = o.asset_group_signal_operation.create
        s.asset_group = f"customers/{acc.customer_id}/assetGroups/{ag}"
        s.search_theme.text = t
        ops.append(o)
        added.append(t)
    if len(current) + len(added) > 50:
        raise AdsError(f"Témat by bylo {len(current) + len(added)}, max 50.")
    if added:
        lines.append(f"Přidat ({len(added)}): " + ", ".join(added))
    if removed:
        lines.append(f"Odebrat ({len(removed)}): " + ", ".join(removed))
    if skipped:
        lines.append(f"Už existuje ({len(skipped)}): " + ", ".join(skipped))
    return create_plan(acc, "Témata vyhledávání", lines, ops)


def propose_asset_group_assets(customer_id: str, asset_group_id: str, headlines: list[str] | None = None,
                               long_headlines: list[str] | None = None, descriptions: list[str] | None = None,
                               images: list[str] | None = None, videos: list[str] | None = None,
                               remove_asset_ids: list[str] | None = None) -> str:
    acc = get_account(customer_id)
    client = client_for(acc)
    cid = acc.customer_id
    ag = num_id(asset_group_id, "ID sestavy podkladů")
    r = _asset_group_info(acc, ag)
    ag_rn = f"customers/{cid}/assetGroups/{ag}"
    errs = _text_checks({"headlines": headlines or [], "long_headlines": long_headlines or [],
                         "descriptions": descriptions or []}, need_assets=False)
    linked = search_raw(acc, "SELECT asset_group_asset.resource_name, asset_group_asset.field_type, asset.id, "
                             "asset.text_asset.text, asset.youtube_video_asset.youtube_video_id "
                             f"FROM asset_group_asset WHERE asset_group.id = {ag} AND asset_group_asset.status != REMOVED")
    have_text = {(x.asset_group_asset.field_type.name, x.asset.text_asset.text.strip().lower()) for x in linked
                 if x.asset.text_asset.text}
    have_ids = {str(x.asset.id) for x in linked}
    tmp = TempIds()
    ops, labels, lines, skipped = [], [], [f"Sestava „{r.asset_group.name}“ (kampaň {r.campaign.name})"], []
    links: list[tuple[str, str]] = []

    for items, ft in ((headlines, "HEADLINE"), (long_headlines, "LONG_HEADLINE"), (descriptions, "DESCRIPTION")):
        for t in items or []:
            if (ft, t.strip().lower()) in have_text:
                skipped.append(t)
                continue
            rn = f"customers/{cid}/assets/{tmp.next()}"
            o = new_op(client)
            o.asset_operation.create.resource_name = rn
            o.asset_operation.create.text_asset.text = t.strip()
            ops.append(o)
            labels.append(None)
            links.append((rn, ft))
            lines.append(f"+ {ft}: {t}")
    for it in resolve_images(acc, images or []):
        ft = it.field_type()
        if ft is None or ft == "TALL_PORTRAIT_MARKETING_IMAGE":
            errs.append(f"{it.label}: {it.width}×{it.height} nesedí na 1.91:1, 1:1 ani 4:5")
            continue
        if (m := it.check(ft)):
            errs.append(m)
            continue
        if it.asset_rn and it.asset_rn.rsplit("/", 1)[-1] in have_ids:
            skipped.append(it.label)
            continue
        if it.asset_rn:
            links.append((it.asset_rn, ft))
        else:
            o, rn = image_asset_op(client, cid, tmp, it)
            ops.append(o)
            labels.append(f"obrázek {it.label}")
            links.append((rn, ft))
        lines.append(f"+ {it.describe(ft)}")
    vids = [youtube_id(v) for v in videos or []]
    ex_v = existing_video_assets(acc, vids)
    for vid in dict.fromkeys(vids):
        if vid in ex_v:
            if ex_v[vid].rsplit("/", 1)[-1] in have_ids:
                skipped.append(vid)
                continue
            links.append((ex_v[vid], "YOUTUBE_VIDEO"))
        else:
            o, rn = video_asset_op(client, cid, tmp, vid)
            ops.append(o)
            labels.append(f"video {vid}")
            links.append((rn, "YOUTUBE_VIDEO"))
        lines.append(f"+ video {vid}")
    if errs:
        raise AdsError("Podklady neprošly kontrolou:\n- " + "\n- ".join(errs))
    for rn, ft in links:
        o = new_op(client)
        l = o.asset_group_asset_operation.create
        l.asset_group = ag_rn
        l.asset = rn
        l.field_type = client.enums.AssetFieldTypeEnum[ft]
        ops.append(o)
        labels.append(None)
    by_id = {str(x.asset.id): x for x in linked}
    for aid in remove_asset_ids or []:
        aid = num_id(aid, "ID assetu")
        x = by_id.get(aid)
        if not x:
            raise AdsError(f"Asset {aid} v sestavě není.")
        o = new_op(client)
        o.asset_group_asset_operation.remove = x.asset_group_asset.resource_name
        ops.append(o)
        labels.append(None)
        txt = x.asset.text_asset.text or x.asset.youtube_video_asset.youtube_video_id or f"asset {aid}"
        lines.append(f"- odpojit {x.asset_group_asset.field_type.name}: {txt}")
    if skipped:
        lines.append(f"Už v sestavě je ({len(skipped)}): " + ", ".join(skipped))
    return create_plan(acc, "Úprava podkladů sestavy", lines, ops, labels=labels)


def propose_pmax_automation(customer_id: str, campaign_ids: list[str], opt_out: list[str] | None = None,
                            opt_in: list[str] | None = None) -> str:
    acc = get_account(customer_id)
    client = client_for(acc)
    opt_out = AUTOMATION_OFF_DEFAULT if opt_out is None and not opt_in else (opt_out or [])
    opt_in = opt_in or []
    ids = [num_id(i, "ID kampaně") for i in campaign_ids]
    rows = search_raw(acc, "SELECT campaign.id, campaign.name, campaign.advertising_channel_type, "
                           "campaign.asset_automation_settings FROM campaign "
                           f"WHERE campaign.id IN ({', '.join(ids)})")
    found = {str(r.campaign.id): r.campaign for r in rows}
    missing = [i for i in ids if i not in found]
    if missing:
        raise AdsError(f"Kampaň nenalezena: {', '.join(missing)}")
    ops, lines = [], []
    for i in ids:
        c = found[i]
        current = {s.asset_automation_type.name: s.asset_automation_status.name for s in c.asset_automation_settings}
        wanted = dict(current)
        for t in opt_out:
            wanted[t] = "OPTED_OUT"
        for t in opt_in:
            wanted[t] = "OPTED_IN"
        changes = [f"{AUTOMATION_LABEL.get(t, t)} → {'vyp' if s == 'OPTED_OUT' else 'zap'}"
                   for t, s in wanted.items() if current.get(t) != s]
        if not changes:
            lines.append(f"„{c.name}“: beze změny")
            continue
        op = new_op(client)
        sub = op.campaign_operation
        res = sub.update
        res.resource_name = f"customers/{acc.customer_id}/campaigns/{i}"
        S = type(res).AssetAutomationSetting
        for t, s in wanted.items():
            try:
                res.asset_automation_settings.append(S(
                    asset_automation_type=client.enums.AssetAutomationTypeEnum[t],
                    asset_automation_status=client.enums.AssetAutomationStatusEnum[s]))
            except KeyError:
                raise AdsError(f"Neznámý typ automatiky {t!r}.")
        set_update_mask(client, sub, res)
        ops.append(op)
        lines.append(f"„{c.name}“: " + ", ".join(changes))
    return create_plan(acc, "Automatiky kampaní", lines, ops, guard=["automation"])
