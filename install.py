"""Instalace Google Ads MCP na Windows i macOS. Provede tě všemi kroky, každý jde přeskočit.

Spuštění v této složce:
    Windows:  py install.py        (nebo: python install.py)
    macOS:    python3 install.py
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CRED_DIR = Path.home() / ".google-ads"


def venv_python() -> Path:
    if platform.system() == "Windows":
        return HERE / ".venv" / "Scripts" / "python.exe"
    return HERE / ".venv" / "bin" / "python"


def ask(q: str, default: str = "") -> str:
    hint = f" [{default}]" if default else ""
    ans = input(f"{q}{hint}: ").strip().strip('"').strip("'")
    if platform.system() != "Windows":
        ans = ans.replace("\\ ", " ")
    return ans or default


def yes(q: str, default: bool = True) -> bool:
    ans = input(f"{q} [{'A/n' if default else 'a/N'}]: ").strip().lower()
    return default if not ans else ans in ("a", "ano", "y", "yes")


def run(*args: str) -> int:
    return subprocess.call([str(venv_python()), *args], cwd=HERE)


def step_venv() -> None:
    if sys.version_info < (3, 10):
        sys.exit("Potřebuješ Python 3.10 nebo novější (python.org).")
    if not venv_python().exists():
        print("Vytvářím virtuální prostředí .venv ...")
        subprocess.check_call([sys.executable, "-m", "venv", str(HERE / ".venv")])
    print("Instaluji knihovny (chvíli to trvá) ...")
    subprocess.check_call([str(venv_python()), "-m", "pip", "install", "--upgrade", "pip", "--quiet"])
    subprocess.check_call([str(venv_python()), "-m", "pip", "install", "-r", str(HERE / "requirements.txt"),
                           "--quiet"])
    print("Knihovny nainstalované.\n")


def step_accounts() -> Path:
    print("Seznam účtů (accounts.yaml) určuje, na které účty smí MCP sahat.")
    print("Používáš-li víc počítačů, dej ho do složky na cloudovém disku (OneDrive, Google Drive, Dropbox,")
    print("iCloud) - pak ho i se složkami klientů a logem sdílí všechny počítače.")
    default = HERE / "accounts.yaml"
    path = Path(ask("Kde má seznam účtů ležet (cesta k souboru)", str(default))).expanduser()
    if path.is_dir():
        path = path / "accounts.yaml"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(HERE / "accounts.example.yaml", path)
        print(f"Vytvořen ze vzoru: {path} - doplň do něj svoje účty (ID najdeš v dalším kroku).")
    else:
        print(f"Používám existující: {path}")
    print()
    return path


def step_oauth() -> None:
    target = CRED_DIR / "client_secret.json"
    if (CRED_DIR / "google-ads.yaml").exists():
        if not yes("Přihlášení už existuje (~/.google-ads/google-ads.yaml). Přihlásit znovu?", False):
            return
    if not target.exists():
        print("Potřebuji OAuth klienta typu Desktop app z Google Cloud Console (stažený JSON).")
        src = Path(ask("Cesta ke staženému JSON souboru (Enter = přeskočit)")).expanduser()
        if not src.name:
            print("Přeskočeno. Až ho budeš mít, spusť install.py znovu.\n")
            return
        if not src.exists():
            sys.exit(f"Soubor {src} neexistuje.")
        CRED_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, target)
    print("Otevře se prohlížeč. Přihlas se Google účtem, který má přístup do Google Ads.")
    run("auth_setup.py")
    print()


def main() -> None:
    print(f"Google Ads MCP - instalace ({platform.system()})\n")
    step_venv()
    accounts = step_accounts()
    step_oauth()
    if (CRED_DIR / "google-ads.yaml").exists() and yes("Vypsat účty, ke kterým máš přístup (pro accounts.yaml)?"):
        run("check_access.py", "--list")
        print()
    if (CRED_DIR / "google-ads.yaml").exists() and yes("Ověřit přístup k účtům z accounts.yaml?"):
        os.environ["ADS_ACCOUNTS_FILE"] = str(accounts)
        subprocess.call([str(venv_python()), "check_access.py"], cwd=HERE, env=os.environ.copy())
        print()
    if yes("Zapsat server do Claude Desktopu?"):
        args = ["install_claude_config.py"]
        if accounts.resolve() != (HERE / "accounts.yaml").resolve():
            args += ["--accounts", str(accounts)]
        extras = ask("Složka s vlastním rozšířením (nepovinné, Enter = žádné)")
        if extras:
            args += ["--extras", extras]
        run(*args)
    print("\nHotovo. Návod a popis nástrojů je v README.cs.md (česky), README.md (anglicky) a docs/NAVOD.md.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nPřerušeno.")
