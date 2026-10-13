"""Ověří přihlášení a přístup ke všem účtům z accounts.yaml. Nic nemění.

Spuštění: přes install.py, nebo ručně pythonem z .venv:  check_access.py
"""
from __future__ import annotations

import sys

from google.ads.googleads.errors import GoogleAdsException

import ads_core as core


def short_error(ex: GoogleAdsException) -> str:
    return core.format_ads_error(ex).splitlines()[0]


def list_accessible() -> None:
    client = core.get_client(None)
    direct = [rn.split("/")[-1] for rn in client.get_service("CustomerService").list_accessible_customers().resource_names]
    print(f"Přímo přístupné účty: {len(direct)}\n")
    for cid in direct:
        try:
            ga = core.get_client(cid).get_service("GoogleAdsService")
            rows = list(ga.search(customer_id=cid, query=(
                "SELECT customer_client.id, customer_client.descriptive_name, customer_client.manager, "
                "customer_client.level, customer_client.status FROM customer_client "
                "WHERE customer_client.level <= 2")))
        except GoogleAdsException as ex:
            print(f"{core.fmt_id(cid)}  (nejde přečíst: {short_error(ex)})")
            continue
        for r in sorted(rows, key=lambda r: r.customer_client.level):
            cc = r.customer_client
            indent = "    " * cc.level
            kind = "MCC" if cc.manager else "účet"
            via = f"  login_customer_id: {core.fmt_id(cid)}" if cc.level > 0 else ""
            print(f"{indent}{core.fmt_id(str(cc.id))}  {kind:<4} {cc.descriptive_name}  [{cc.status.name}]{via}")
        print()


def main() -> None:
    if "--list" in sys.argv:
        list_accessible()
        return
    accounts = core.load_accounts()
    print(f"Účtů v accounts.yaml: {len(accounts)}\n")

    try:
        client = core.get_client(None)
        svc = client.get_service("CustomerService")
        direct = {rn.split("/")[-1] for rn in svc.list_accessible_customers().resource_names}
        print(f"Přihlášení OK. Přímo přístupných účtů/MCC: {len(direct)}")
    except GoogleAdsException as ex:
        sys.exit("Přihlášení nebo přístup k API selhal:\n" + core.format_ads_error(ex) +
                 "\n\nČastá příčina: Cloud projekt nemá schválený přístup Explorer/Basic "
                 "(CLOUD_PROJECT_NOT_APPROVED_FOR_PRODUCTION) nebo není zapnuté Google Ads API.")
    except core.AdsError as ex:
        sys.exit(str(ex))

    logins = {a.login_customer_id for a in accounts.values() if a.login_customer_id}
    for login in logins:
        print(f"MCC {core.fmt_id(login)}: {'přímý přístup OK' if login in direct else 'NENÍ mezi přímo přístupnými účty'}")
    print()

    ok, bad = 0, []
    for acc in accounts.values():
        q = "SELECT customer.descriptive_name, customer.currency_code, customer.time_zone FROM customer"
        try:
            row = core.search_raw(acc, q)[0]
            c = row.customer
            print(f"OK    {core.fmt_id(acc.customer_id)}  {acc.name:<25} -> {c.descriptive_name} ({c.currency_code})")
            ok += 1
        except GoogleAdsException as ex:
            hint = ""
            if acc.customer_id in direct:
                hint = "  | tip: účet máš i napřímo, zkus login_customer_id: null"
            print(f"CHYBA {core.fmt_id(acc.customer_id)}  {acc.name:<25} -> {short_error(ex)}{hint}")
            bad.append(acc)
    print(f"\nHotovo: {ok} OK, {len(bad)} s chybou.")
    if bad:
        print("U chybových účtů nejspíš nesedí MCC - doplň jim v accounts.yaml správné login_customer_id.")


if __name__ == "__main__":
    main()
