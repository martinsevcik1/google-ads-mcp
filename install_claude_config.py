"""Přidá tento MCP server do konfigurace Claude Desktopu (Windows i macOS). Předtím udělá zálohu.

Spuštění: přes install.py, nebo ručně pythonem z .venv:
    install_claude_config.py [--accounts CESTA] [--logs CESTA] [--extras CESTA]

--accounts  kde leží seznam účtů (výchozí accounts.yaml v této složce)
--logs      kam ukládat log změn (výchozí složka logs vedle seznamu účtů)
--extras    volitelná složka s vlastním rozšířením (moduly s funkcí register)
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import os
import platform
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SERVER_NAME = "google-ads"
ENV_PREFIX = "ADS"
SERVER = HERE / "server.py"


def venv_python() -> Path:
    win = HERE / ".venv" / "Scripts" / "python.exe"
    nix = HERE / ".venv" / "bin" / "python"
    return win if platform.system() == "Windows" else nix


def candidates() -> list[Path]:
    system = platform.system()
    out: list[Path] = []
    if system == "Windows":
        appdata = os.environ.get("APPDATA")
        if appdata:
            out.append(Path(appdata) / "Claude" / "claude_desktop_config.json")
        local = os.environ.get("LOCALAPPDATA")
        if local:
            for p in glob.glob(str(Path(local) / "Packages" / "Claude_*" / "LocalCache" / "Roaming" / "Claude")):
                out.append(Path(p) / "claude_desktop_config.json")
    elif system == "Darwin":
        out.append(Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json")
    else:
        out.append(Path.home() / ".config" / "Claude" / "claude_desktop_config.json")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--accounts", help="cesta k seznamu účtů (yaml)")
    ap.add_argument("--logs", help="složka pro log změn")
    ap.add_argument("--extras", help="složka s rozšířením")
    args = ap.parse_args()

    py = venv_python()
    if not py.exists():
        sys.exit(f"Nenašel jsem {py}. Nejdřív spusť install.py.")
    env: dict[str, str] = {}
    if args.accounts:
        env[f"{ENV_PREFIX}_ACCOUNTS_FILE"] = str(Path(args.accounts).expanduser().resolve())
    if args.logs:
        env[f"{ENV_PREFIX}_LOG_DIR"] = str(Path(args.logs).expanduser().resolve())
    if args.extras:
        env[f"{ENV_PREFIX}_EXTRAS_DIR"] = str(Path(args.extras).expanduser().resolve())
    entry: dict = {"command": str(py), "args": [str(SERVER)]}
    if env:
        entry["env"] = env

    paths = candidates()
    existing = [p for p in paths if p.exists()] or [p for p in paths if p.parent.exists()]
    if not existing:
        print("Nenašel jsem složku Claude Desktopu (je nainstalovaný a aspoň jednou spuštěný?).")
        print("Přidej ručně do claude_desktop_config.json:\n")
        print(json.dumps({"mcpServers": {SERVER_NAME: entry}}, indent=2, ensure_ascii=False))
        sys.exit(1)
    for cfg_path in existing:
        data: dict = {}
        if cfg_path.exists():
            text = cfg_path.read_text(encoding="utf-8").strip()
            data = json.loads(text) if text else {}
            backup = cfg_path.with_name(f"claude_desktop_config.backup-{dt.datetime.now():%Y%m%d-%H%M%S}.json")
            shutil.copy2(cfg_path, backup)
            print(f"Záloha: {backup}")
        data.setdefault("mcpServers", {})[SERVER_NAME] = entry
        cfg_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Zapsáno: {cfg_path}")
    if platform.system() == "Darwin":
        print("\nTeď Claude Desktop úplně ukonči (Cmd+Q) a spusť znovu.")
    else:
        print("\nTeď Claude Desktop úplně ukonči (i z lišty u hodin) a spusť znovu.")


if __name__ == "__main__":
    main()
