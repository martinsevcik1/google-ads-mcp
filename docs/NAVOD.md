# Návod: Google Ads MCP od nuly

English: [GUIDE.md](GUIDE.md)

Tenhle návod tě provede vším, co je potřeba udělat jednou: Google účet, Google Cloud projekt, přístup
k Google Ads API, přihlášení a instalace na Windows nebo macOS. Počítej zhruba s 30-45 minutami.

Proč vlastní projekt a vlastní přihlášení: Google Ads API se od září 2026 povoluje **Google Cloud projektu**
(dřív to byl developer token v MCC). Každý, kdo MCP používá, má mít vlastní Cloud projekt, vlastního OAuth
klienta a přihlašuje se vlastním Google účtem. Nikdy nepoužívej cizí projekt ani cizí přihlášení: všechny
změny v účtech se pak zapisují pod tebe a přístup máš jen tam, kam ti ho dal klient nebo agentura.

---

## 1. Google účet

Potřebuješ Google účet, který:

- má přístup do účtů Google Ads, se kterými chceš pracovat (přímo, nebo přes MCC agentury),
- bude vlastníkem Google Cloud projektu.

Nejjednodušší je jeden účet na obojí. Možnosti:

**A) Účet, kterým už do Google Ads chodíš** (pracovní e-mail na Google Workspace nebo Gmail). Nic dalšího
nezakládáš, jen pokračuj krokem 2.

**B) Nový samostatný Gmail jen pro tuhle práci.** Hodí se, když nechceš míchat pracovní a osobní věci, nebo
když dosavadní účet patří někomu jinému (třeba firemní účet agentury).

1. Otevři https://accounts.google.com/signup a založ účet (jméno, datum narození, adresa `@gmail.com`, heslo).
2. Zapni dvoufázové ověření: https://myaccount.google.com/security > Dvoufázové ověření.
3. Nech si do Google Ads dát přístup na tenhle nový e-mail:
   - **Přes MCC agentury:** správce MCC tě přidá v MCC v Správce > Přístup a zabezpečení > Uživatelé > +.
     Úroveň přístupu Standardní (nebo Administrátor, pokud budeš měnit i nastavení účtů).
   - **Přímo do účtu klienta:** klient tě přidá ve svém účtu ve stejném menu.
   - **Vlastní MCC:** můžeš si založit vlastní manažerský účet na https://ads.google.com/home/tools/manager-accounts/
     a klienty si do něj připojit (klient žádost schválí ve svém účtu).
4. Pozvánku přijmi z e-mailu, který přijde na nový Gmail.

Ověř, že se tímto účtem dostaneš na https://ads.google.com do klientských účtů. Pokud ano, pokračuj.

---

## 2. Google Cloud projekt

Všechno v tomhle kroku dělej přihlášený účtem z kroku 1 (vpravo nahoře v Cloud Console zkontroluj, jaký účet je
aktivní, pokud máš v prohlížeči víc účtů).

1. Otevři https://console.cloud.google.com a odsouhlas podmínky (jen poprvé).
2. Nahoře klikni na výběr projektu > **Nový projekt**. Název třeba `google-ads-mcp`. Organizaci nech, jak je
   (u Gmailu „Žádná organizace"). **Vytvořit.**
3. Přepni se do nového projektu (výběr projektu nahoře).
4. **Fakturace:** Google Ads API je zdarma, ale Google odmítá přístup k API projektům na zkušební verzi
   (Free Trial) nebo bez platného fakturačního účtu. V menu **Fakturace** propoj projekt s fakturačním účtem
   (založíš ho tamtéž, chce kartu). Nic se ti strhávat nebude, pokud nezapneš placené služby.
   Pokud tě Google provede zkušební verzí, aktivuj plný účet (tlačítko Aktivovat / Upgrade).
5. **Zapni Google Ads API:** menu **APIs a služby > Knihovna**, vyhledej „Google Ads API" > **Povolit**.

---

## 3. Přihlašovací obrazovka (OAuth)

Menu **Google Auth Platform** (dřív „APIs a služby > Obrazovka pro udělení souhlasu OAuth"). Při prvním
otevření tě provede průvodcem:

1. **Informace o aplikaci:** název aplikace (třeba `Google Ads MCP`), e-mail podpory = tvůj e-mail.
2. **Okruh uživatelů (Audience):** **Externí**.
   (Interní jde jen u Google Workspace a jen pro uživatele z té samé domény.)
3. **Kontaktní údaje:** tvůj e-mail. Odsouhlas pravidla a **Vytvořit**.
4. Otevři **Okruh uživatelů (Audience)** a klikni na **Publikovat aplikaci** > potvrdit. Stav musí být
   **V produkci (In production)**.
   Proč: když aplikace zůstane ve stavu Testování, přihlášení vyprší po 7 dnech a MCP přestane fungovat
   (chyba `invalid_grant`).

Ověření aplikace Googlem (verifikaci) pro vlastní použití nepotřebuješ. Při přihlášení uvidíš varování
„Google tuto aplikaci neověřil". Je to v pořádku, je to tvoje vlastní aplikace: klikni na **Rozšířené** >
**Přejít na Google Ads MCP (nebezpečné)**.

---

## 4. OAuth klient (Desktop app)

1. **Google Auth Platform > Klienti (Clients) > Vytvořit klienta.**
2. Typ aplikace: **Aplikace pro počítač (Desktop app)**. Název třeba `google-ads-mcp`. **Vytvořit.**
3. V okně s výsledkem klikni na **Stáhnout JSON**. Soubor (`client_secret_....json`) si zatím nech ve Stažených
   souborech, instalátor si ho převezme.

Tenhle soubor nikomu neposílej a nedávej ho do gitu ani na sdílený disk.

---

## 5. Úroveň přístupu k API

Nový projekt má jen přístup **Test** (pouze testovací účty). Pro skutečné účty potřebuješ **Explorer**:

1. V Cloud Console otevři stránku **Google Ads API** (APIs a služby > Povolená rozhraní API a služby >
   Google Ads API) a v ní přehled Google Ads API (Google Ads API Overview).
2. Klikni na **Upgrade access level** a požádej o **Explorer**. Vyplň krátký formulář (k čemu API používáš:
   správa vlastních / klientských účtů). Často se schválí automaticky během pár minut.

Úrovně:

| Úroveň | Limit | Co neumí |
|---|---|---|
| Explorer | 2 880 operací denně | Plánovač klíčových slov, plánování dosahu, fakturace, správa uživatelů |
| Basic | 15 000 operací denně | nic z běžné práce, vyžaduje ověření značky (brand verification) projektu |

Operace = jeden dotaz na data, nebo jedna položka při zápisu. Pro běžnou správu několika účtů Explorer stačí.
Basic se hodí při velkém počtu účtů nebo když chceš Plánovač klíčových slov. Žádá se na stejné stránce,
předtím je potřeba ověřit značku v **Google Auth Platform > Branding** (vlastní doména, domovská stránka
a zásady ochrany soukromí).

Pozor: když přístup 90 dní nepoužiješ, Google ho může vrátit na Test.

---

## 6. Python a Claude Desktop

**Claude Desktop:** stáhni z https://claude.ai/download, nainstaluj a aspoň jednou spusť a přihlas se.

**Python 3.10 nebo novější:**

- **Windows:** https://www.python.org/downloads/ > instalátor. Na první obrazovce zaškrtni
  **Add python.exe to PATH**. Ověř v PowerShellu: `py --version`
- **macOS:** https://www.python.org/downloads/ > instalátor pro macOS. Po instalaci otevři složku
  Aplikace > Python 3.x a spusť **Install Certificates.command** (jinak mohou spojení s API padat na
  chybě SSL certifikátu). Ověř v Terminálu: `python3 --version`
  (Python předinstalovaný v macOS bývá starší než 3.10, proto ten z python.org. Jde i `brew install python`.)

**Git** (nepovinné, ale usnadní aktualizace):

- Windows: https://git-scm.com/download/win
- macOS: v Terminálu spusť `git --version`, systém sám nabídne instalaci.

Bez gitu stačí na stránce repozitáře **Code > Download ZIP** a rozbalit.

---

## 7. Stažení a instalace

Vyber si stálé místo (ne Stažené soubory), třeba složku `Dokumenty/mcp`.

Windows (PowerShell):

```
cd $HOME\Documents
mkdir mcp; cd mcp
git clone https://github.com/martinsevcik1/google-ads-mcp.git
cd google-ads-mcp
py install.py
```

macOS (Terminál):

```
mkdir -p ~/Documents/mcp && cd ~/Documents/mcp
git clone https://github.com/martinsevcik1/google-ads-mcp.git
cd google-ads-mcp
python3 install.py
```

Instalátor se postupně ptá. Každý krok jde přeskočit a později spustit `install.py` znovu.

1. **Knihovny:** vytvoří `.venv` a nainstaluje potřebné balíčky (pár minut).
2. **Kde má ležet seznam účtů:** Enter = ve složce repa. Pokud používáš víc počítačů, zadej cestu do
   složky na cloudovém disku (viz krok 9).
3. **Cesta ke staženému JSON:** přetáhni soubor z kroku 4 do okna terminálu (vloží se cesta) a Enter.
   Zkopíruje se do `~/.google-ads/client_secret.json`.
4. **Přihlášení:** otevře se prohlížeč. Přihlas se účtem z kroku 1, potvrď varování o neověřené aplikaci
   (Rozšířené > Přejít na...) a povol přístup. Výsledek se uloží do `~/.google-ads/google-ads.yaml`.
5. **Výpis účtů:** vypíše účty a MCC, ke kterým máš přístup, i s ID. Podle něj vyplníš seznam účtů.
6. **Vyplň seznam účtů:** otevři `accounts.yaml` (cestu ti instalátor vypsal) v textovém editoru:

   ```yaml
   dpa: false                                   # true jen s DPA s klientem i s poskytovatelem modelu
   default_login_customer_id: "123-456-7890"   # ID MCC z výpisu, přes které účty vidíš
   clients_root: klienti
   accounts:
     "234-567-8901": {name: klient-a.cz, folder: klient_a}
     "345-678-9012": {name: klient-b.cz, folder: klient_b}
   ```

   - Účty vidíš přes MCC: `default_login_customer_id` = ID toho MCC (výpis ho u účtu ukazuje jako
     `login_customer_id`).
   - Účty máš přímo bez MCC: `default_login_customer_id: null`.
   - Účet přes jiné MCC než ostatní: k účtu přidej `login_customer_id: "ID-toho-MCC"`.
   - `folder` je složka klienta pro exporty, náhledy a obrázky. Vytvoří se sama.
   - `dpa` viz README.cs.md, část Režim s DPA a bez DPA. Nech `false`, pokud nemáš smlouvu o zpracování
     osobních údajů s klientem i s poskytovatelem modelu (Claude Team, Enterprise nebo API, případně Claude
     přes Google Cloud nebo Amazon Bedrock).

7. **Ověření přístupu:** zkusí přečíst každý účet ze seznamu a vypíše, co funguje.
8. **Zápis do Claude Desktopu:** přidá server do konfigurace Claude Desktopu (předtím ji zazálohuje).

Pak **Claude Desktop úplně ukonči** (Windows: i ikonu u hodin, macOS: Cmd+Q) a spusť znovu. V konverzaci
napiš třeba „vypiš moje Google Ads účty". Claude by měl zavolat `list_accounts`.

Seznam účtů můžeš kdykoli upravit, změny platí hned bez restartu.

---

## 8. První kroky

- „Jak si vede účet klient-a.cz za posledních 30 dní? Kampaně, útrata, konverze, cena za konverzi."
- „Projdi vyhledávací dotazy v klient-a.cz za 30 dní a navrhni negativa."
- „Ukaž strukturu kampaní a sestav v klient-b.cz."

Claude nejdřív vždy ukáže plán změny. Běžné změny provede po tvém „ano", u chráněných (rozpočty, nabídky,
zapínání, cílení, mazání...) chce výslovný souhlas s konkrétním plánem.

---

## 9. Druhý počítač (třeba Windows + MacBook)

1. Seznam účtů dej do složky na cloudovém disku, který máš na obou počítačích (OneDrive, Google Drive,
   Dropbox, iCloud Drive), např. `.../Google Drive/mcp/accounts.yaml`. Složky klientů (`clients_root: klienti`)
   a log změn se vytvoří vedle něj, takže je uvidí oba počítače.
2. Na druhém počítači zopakuj kroky 6 a 7. Při otázce na seznam účtů zadej cestu k tomu samému souboru
   na cloudovém disku.
3. OAuth JSON z kroku 4 použij stejný (stáhneš ho znovu v Cloud Console > Google Auth Platform > Klienti),
   přihlásit se ale musíš na každém počítači zvlášť. Složku `~/.google-ads` mezi počítači nekopíruj
   a nesynchronizuj.

Cesty na cloudovém disku se na Windows a macOS liší. Proto je v `accounts.yaml` nech relativní
(`clients_root: klienti`), každý počítač si je dopočítá od místa, kde soubor leží.

---

## 10. Řešení problémů

| Chyba | Co s tím |
|---|---|
| `CLOUD_PROJECT_NOT_APPROVED_FOR_PRODUCTION` | Projekt nemá přístup Explorer (krok 5), nebo je na zkušební verzi bez fakturace (krok 2.4). Když nic nepomůže, založ nový projekt a požádej znovu. |
| `invalid_grant` | Přihlášení vypršelo. Zkontroluj, že je aplikace V produkci (krok 3.4), a spusť `install.py` znovu (přihlášení). |
| `USER_PERMISSION_DENIED` | Špatné `login_customer_id`. Spusť výpis účtů a použij MCC, pod kterým účet ve výpisu je. |
| `CUSTOMER_NOT_ENABLED` | Účet je zrušený nebo nedokončený. |
| `QuotaError.RESOURCE_EXHAUSTED` | Vyčerpaný denní limit operací (Explorer 2 880). Počkej, limit se počítá za posledních 24 hodin. |
| Claude nevidí nástroje | Claude Desktop úplně ukonči a spusť znovu. Zkontroluj, že `install_claude_config.py` vypsal „Zapsáno". |
| SSL / certifikát na macOS | Spusť Install Certificates.command ze složky Python v Aplikacích (krok 6). |
| Prohlížeč se při přihlášení neotevře | Zkopíruj adresu z terminálu do prohlížeče ručně. |

Ruční spuštění jednotlivých kroků (z kořene repa):

- Windows: `.venv\Scripts\python.exe auth_setup.py`, `check_access.py --list`, `check_access.py`,
  `install_claude_config.py`
- macOS: `.venv/bin/python auth_setup.py` atd.

Zrušení přístupu: https://myaccount.google.com/permissions (aplikace Google Ads MCP), případně smaž
složku `~/.google-ads`.
