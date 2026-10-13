#!/bin/bash
cd "$(dirname "$0")" || exit 1
clear
echo ""
echo "  Instalace Google Ads MCP"
echo "  ------------------------------"
echo ""

ok() { "$1" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; }

PY=""
for c in /Library/Frameworks/Python.framework/Versions/3.*/bin/python3 /opt/homebrew/bin/python3 /usr/local/bin/python3; do
  if [ -x "$c" ] && ok "$c"; then PY="$c"; fi
done
if [ -z "$PY" ] && xcode-select -p >/dev/null 2>&1 && ok python3; then PY="python3"; fi

if [ -z "$PY" ]; then
  echo "Potřebuješ Python 3.10 nebo novější. Otevírám stránku ke stažení."
  echo ""
  echo "1. Stáhni a nainstaluj Python pro macOS."
  echo "2. Ve složce Aplikace > Python 3.x spusť Install Certificates.command."
  echo "3. Pak znovu spusť tento soubor."
  open "https://www.python.org/downloads/macos/"
  echo ""
  read -n 1 -s -r -p "Stiskni libovolnou klávesu pro zavření..."
  exit 1
fi

"$PY" install.py
echo ""
read -n 1 -s -r -p "Hotovo. Stiskni libovolnou klávesu pro zavření..."
