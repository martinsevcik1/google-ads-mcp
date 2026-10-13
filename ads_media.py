from __future__ import annotations

import hashlib
import io
import re
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image

from ads_core import Account, AdsError, TempIds, check_local_path, new_op, search_raw

IMG_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tif", ".tiff"}
MAX_BYTES = 5120 * 1024

SPECS = {
    "MARKETING_IMAGE": (1.91, 600, 314),
    "SQUARE_MARKETING_IMAGE": (1.0, 300, 300),
    "PORTRAIT_MARKETING_IMAGE": (0.8, 480, 600),
    "TALL_PORTRAIT_MARKETING_IMAGE": (9 / 16, 600, 1067),
    "LOGO": (1.0, 128, 128),
    "LANDSCAPE_LOGO": (4.0, 512, 128),
}
LABEL = {
    "MARKETING_IMAGE": "na šířku 1.91:1",
    "SQUARE_MARKETING_IMAGE": "čtverec 1:1",
    "PORTRAIT_MARKETING_IMAGE": "na výšku 4:5",
    "TALL_PORTRAIT_MARKETING_IMAGE": "na výšku 9:16",
    "LOGO": "logo 1:1",
    "LANDSCAPE_LOGO": "logo 4:1",
}
TOLERANCE = 0.01


@dataclass
class ImageItem:
    label: str
    width: int
    height: int
    data: bytes | None = None
    asset_rn: str | None = None
    note: str = ""
    sha: str = ""

    def field_type(self, logo: bool = False) -> str | None:
        r = self.width / self.height
        candidates = ("LOGO", "LANDSCAPE_LOGO") if logo else (
            "MARKETING_IMAGE", "SQUARE_MARKETING_IMAGE", "PORTRAIT_MARKETING_IMAGE", "TALL_PORTRAIT_MARKETING_IMAGE")
        for ft in candidates:
            ratio, _, _ = SPECS[ft]
            if abs(r - ratio) / ratio <= TOLERANCE:
                return ft
        return None

    def check(self, ft: str) -> str | None:
        _, mw, mh = SPECS[ft]
        if self.width < mw or self.height < mh:
            return f"{self.label}: {self.width}×{self.height} je pod minimem {mw}×{mh} pro {LABEL[ft]}"
        return None

    def describe(self, ft: str | None) -> str:
        src = "existující asset" if self.asset_rn else f"{len(self.data or b'') // 1024} kB"
        return f"{self.label} - {self.width}×{self.height}, {LABEL.get(ft or '', 'nesedí poměr')}, {src}{self.note}"


def _natural_key(s: str) -> list[Any]:
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]


def _normalize(raw: bytes, label: str) -> ImageItem:
    try:
        img = Image.open(io.BytesIO(raw))
        img.load()
    except Exception as ex:
        raise AdsError(f"{label}: nejde otevřít jako obrázek ({ex})")
    fmt = (img.format or "").upper()
    note = ""
    data = raw
    if fmt not in ("JPEG", "PNG", "GIF"):
        buf = io.BytesIO()
        if img.mode in ("RGBA", "LA", "P"):
            img.convert("RGBA").save(buf, "PNG", optimize=True)
            note = f" (převedeno z {fmt} na PNG)"
        else:
            img.convert("RGB").save(buf, "JPEG", quality=92)
            note = f" (převedeno z {fmt} na JPG)"
        data = buf.getvalue()
    if len(data) > MAX_BYTES:
        for q in (90, 85, 80):
            buf = io.BytesIO()
            base = img.convert("RGBA") if img.mode in ("RGBA", "LA", "P") else img.convert("RGB")
            if base.mode == "RGBA":
                bg = Image.new("RGB", base.size, (255, 255, 255))
                bg.paste(base, mask=base.split()[3])
                base = bg
            base.save(buf, "JPEG", quality=q)
            if buf.tell() <= MAX_BYTES:
                data = buf.getvalue()
                note += f" (zmenšeno na JPG q{q}, {len(data) // 1024} kB)"
                break
        else:
            raise AdsError(f"{label}: soubor má {len(raw) // 1024} kB a ani po kompresi se nevejde pod 5120 kB")
    return ImageItem(label, img.width, img.height, data=data, note=note, sha=hashlib.sha256(data).hexdigest())


def _expand(source: str, acc: Account) -> list[tuple[str, bytes]]:
    s = source.strip().strip('"')
    if re.match(r"^https?://", s):
        req = urllib.request.Request(s, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            return [(s.rsplit("/", 1)[-1] or s, resp.read())]
    p = Path(s).expanduser()
    if not p.exists():
        raise AdsError(f"Soubor nebo složka neexistuje: {s}")
    check_local_path(acc, p)
    if p.is_dir():
        files = sorted([f for f in p.rglob("*") if f.suffix.lower() in IMG_EXT],
                       key=lambda f: _natural_key(str(f.relative_to(p))))
        if not files:
            raise AdsError(f"Ve složce {s} nejsou žádné obrázky.")
        return [(f.name, f.read_bytes()) for f in files]
    if p.suffix.lower() == ".zip":
        out = []
        with zipfile.ZipFile(p) as z:
            names = sorted([n for n in z.namelist() if Path(n).suffix.lower() in IMG_EXT
                            and not n.startswith("__MACOSX")], key=_natural_key)
            for n in names:
                out.append((f"{p.name}:{n}", z.read(n)))
        if not out:
            raise AdsError(f"V archivu {s} nejsou žádné obrázky.")
        return out
    if p.suffix.lower() not in IMG_EXT:
        raise AdsError(f"{s} není obrázek (podporuji {', '.join(sorted(IMG_EXT))}).")
    return [(p.name, p.read_bytes())]


def resolve_images(acc: Account, sources: list[str]) -> list[ImageItem]:
    items: list[ImageItem] = []
    asset_ids = [s.strip() for s in sources if re.fullmatch(r"\s*\d+\s*", s)]
    existing: dict[str, ImageItem] = {}
    if asset_ids:
        q = ("SELECT asset.id, asset.name, asset.type, asset.image_asset.full_size.width_pixels, "
             "asset.image_asset.full_size.height_pixels FROM asset "
             f"WHERE asset.id IN ({', '.join(asset_ids)})")
        for r in search_raw(acc, q):
            a = r.asset
            if a.type_.name != "IMAGE":
                raise AdsError(f"Asset {a.id} není obrázek ({a.type_.name}).")
            existing[str(a.id)] = ImageItem(f"asset {a.id} „{a.name}“", a.image_asset.full_size.width_pixels,
                                            a.image_asset.full_size.height_pixels,
                                            asset_rn=f"customers/{acc.customer_id}/assets/{a.id}")
        missing = [i for i in asset_ids if i not in existing]
        if missing:
            raise AdsError(f"Image asset nenalezen: {', '.join(missing)}")
    for s in sources:
        key = s.strip()
        if key in existing:
            items.append(existing[key])
            continue
        for label, raw in _expand(s, acc):
            items.append(_normalize(raw, label))
    seen: set[str] = set()
    unique = []
    for it in items:
        k = it.asset_rn or it.sha
        if k in seen:
            continue
        seen.add(k)
        unique.append(it)
    return unique


def image_asset_op(client: Any, cid: str, tmp: TempIds, item: ImageItem) -> tuple[Any, str]:
    rn = f"customers/{cid}/assets/{tmp.next()}"
    op = new_op(client)
    a = op.asset_operation.create
    a.resource_name = rn
    stem = Path(item.label.split(":")[-1]).stem[:80] or "obrazek"
    a.name = f"{stem} [{item.sha[:6]}]"
    a.type_ = client.enums.AssetTypeEnum.IMAGE
    a.image_asset.data = item.data
    return op, rn


def youtube_id(value: str) -> str:
    v = value.strip()
    m = re.search(r"(?:v=|youtu\.be/|shorts/|embed/)([A-Za-z0-9_-]{11})", v)
    if m:
        return m.group(1)
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", v):
        return v
    raise AdsError(f"Nerozpoznané YouTube video: {value!r} (čekám ID nebo odkaz)")


def existing_video_assets(acc: Account, ids: list[str]) -> dict[str, str]:
    if not ids:
        return {}
    q = ("SELECT asset.resource_name, asset.youtube_video_asset.youtube_video_id FROM asset "
         "WHERE asset.type = YOUTUBE_VIDEO AND asset.youtube_video_asset.youtube_video_id IN ("
         + ", ".join(f"'{i}'" for i in ids) + ")")
    return {r.asset.youtube_video_asset.youtube_video_id: r.asset.resource_name for r in search_raw(acc, q)}


def video_asset_op(client: Any, cid: str, tmp: TempIds, video_id: str, name: str = "") -> tuple[Any, str]:
    rn = f"customers/{cid}/assets/{tmp.next()}"
    op = new_op(client)
    a = op.asset_operation.create
    a.resource_name = rn
    a.name = name or f"YouTube {video_id}"
    a.type_ = client.enums.AssetTypeEnum.YOUTUBE_VIDEO
    a.youtube_video_asset.youtube_video_id = video_id
    return op, rn


VIDEO_EXT = {".mp4", ".mov", ".avi", ".wmv", ".mpeg", ".mpg", ".m4v", ".webm", ".flv", ".3gp"}
