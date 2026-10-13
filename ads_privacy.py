from __future__ import annotations

import re
from typing import Any

import ads_core as core

EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
PHONE = re.compile(r"(?<![\w])(?:\+|00)?\d(?:[ \-/.]?\d){8,14}(?![\w])")

BLOCKED_RESOURCES = {
    "lead_form_submission_data": "odpovědi z formulářů pro potenciální zákazníky",
    "local_services_lead": "poptávky z místních služeb",
    "local_services_lead_conversation": "konverzace s poptávkami z místních služeb",
    "local_services_verification_artifact": "ověřovací doklady místních služeb",
    "customer_user_access": "uživatelé účtu a jejich e-maily",
    "customer_user_access_invitation": "pozvánky uživatelů a jejich e-maily",
}
BLOCKED_FIELDS = {
    "change_event.user_email": "e-mail autora změny",
    "change_status.user_email": "e-mail autora změny",
}
BLOCKED_SERVICES = {
    "OfflineUserDataJobService": "nahrávání seznamů zákazníků (Customer Match)",
    "UserDataService": "nahrávání seznamů zákazníků (Customer Match)",
    "ConversionUploadService": "nahrávání offline konverzí s identifikátory a kontaktními údaji",
    "ConversionAdjustmentUploadService": "úpravy konverzí s kontaktními údaji",
    "LocalServicesLeadService": "poptávky z místních služeb",
}
HOW = ("Režim bez DPA (dpa: false v accounts.yaml) - do konverzace s Claudem nesmí jít osobní údaje. "
       "Udělej to ručně v rozhraní Google Ads. Pokud máš plán Claude s DPA (Team, Enterprise, API), "
       "nastav v accounts.yaml dpa: true.")


def enabled() -> bool:
    return not core.dpa_enabled()


def mode_line() -> str:
    return ("Režim: s DPA (osobní údaje povolené)" if core.dpa_enabled()
            else "Režim: bez DPA (osobní údaje se do konverzace neposílají)")


def _is_phone(s: str) -> bool:
    return not (s.isdigit() and len(s) == 13)


def has_pii(text: str) -> bool:
    t = text or ""
    return bool(EMAIL.search(t)) or any(_is_phone(m.group(0)) for m in PHONE.finditer(t))


def redact(text: str) -> str:
    t = EMAIL.sub("[e-mail]", text or "")
    return PHONE.sub(lambda m: "[telefon]" if _is_phone(m.group(0)) else m.group(0), t)


def mask_email(email: str) -> str:
    if not email or "@" not in email:
        return email
    local, dom = email.split("@", 1)
    return f"{local[:2]}***@{dom}"


def check_gaql(query: str) -> None:
    if not enabled():
        return
    q = query.lower()
    m = re.search(r"\bfrom\s+([a-z_]+)", q)
    if m and m.group(1) in BLOCKED_RESOURCES:
        raise core.AdsError(f"{m.group(1)}: {BLOCKED_RESOURCES[m.group(1)]}. {HOW}")
    for f, why in BLOCKED_FIELDS.items():
        if re.search(rf"\b{re.escape(f)}\b", q):
            raise core.AdsError(f"{f}: {why}. Pole z dotazu vynech. {HOW}")


def check_service(service: str) -> None:
    if enabled() and service in BLOCKED_SERVICES:
        raise core.AdsError(f"{service}: {BLOCKED_SERVICES[service]}. {HOW}")


def clean_rows(rows: list[dict[str, Any]]) -> int:
    if not enabled():
        return 0
    n = 0
    for r in rows:
        for k, v in r.items():
            if "search_term" in k and isinstance(v, str) and has_pii(v):
                r[k] = redact(v)
                n += 1
    return n
