"""Jednorázové přihlášení k Google Ads API.

1. Stáhni z Google Cloud Console OAuth klienta typu "Desktop app" (JSON)
   a ulož ho jako  ~/.google-ads/client_secret.json  (Windows: C:\\Users\\<jméno>\\.google-ads\\client_secret.json)
2. Spusť přes install.py, nebo ručně pythonem z .venv:  auth_setup.py
3. V prohlížeči se přihlas účtem, který má přístup do Google Ads (MCC nebo přímo účty), a povol přístup.

Výsledek: ~/.google-ads/google-ads.yaml s refresh tokenem.
Token se nikam nevypisuje. Kdo ten soubor má, může zapisovat do všech účtů,
kam máš přístup - nekopíruj ho do synchronizovaných složek.
Zrušit ho jde na https://myaccount.google.com/permissions
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import yaml
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/adwords"]
DIR = Path.home() / ".google-ads"
CLIENT_FILE = Path(sys.argv[1]) if len(sys.argv) > 1 else DIR / "client_secret.json"
OUT_FILE = DIR / "google-ads.yaml"


def main() -> None:
    if not CLIENT_FILE.exists():
        sys.exit(f"Nenašel jsem {CLIENT_FILE}. Ulož tam JSON OAuth klienta (Desktop app).")
    info = json.loads(CLIENT_FILE.read_text(encoding="utf-8"))
    if "installed" not in info:
        sys.exit("Tohle není OAuth klient typu Desktop app. Vytvoř v Cloud Console klienta 'Desktop app'.")

    flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_FILE), scopes=SCOPES)
    print("Otevírám prohlížeč - přihlas se účtem s přístupem do Google Ads ...")
    creds = flow.run_local_server(port=0, access_type="offline", prompt="consent",
                                  authorization_prompt_message="", success_message=
                                  "Hotovo, okno můžeš zavřít a vrátit se do terminálu.")
    if not creds.refresh_token:
        sys.exit("Google nevrátil refresh token. Zkus to znovu (případně odeber přístup aplikace "
                 "na myaccount.google.com/permissions a opakuj).")

    DIR.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(DIR, 0o700)
    except OSError:
        pass
    cfg = {
        "client_id": info["installed"]["client_id"],
        "client_secret": info["installed"]["client_secret"],
        "refresh_token": creds.refresh_token,
        "use_proto_plus": True,
    }
    OUT_FILE.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")
    try:
        os.chmod(OUT_FILE, 0o600)
    except OSError:
        pass
    print(f"Uloženo: {OUT_FILE}")
    print("Další krok: check_access.py (install.py ho spustí sám)")


if __name__ == "__main__":
    main()
