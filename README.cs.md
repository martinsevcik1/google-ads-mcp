# Google Ads MCP

[English](README.md) | **Čeština**

Lokální MCP server, přes který Claude (Claude Desktop) čte a spravuje účty Google Ads přímo přes Google Ads API.
Cílem je dělat co nejvíc práce z konverzace: reporty, rozbor dotazů, negativa, nové kampaně, RSA, Performance Max,
publika, podklady, nastavení i cokoli dalšího, co API umí, bez webového rozhraní a Google Ads Editoru.

- Běží na tvém počítači, pod tvým vlastním Google Cloud projektem a tvým přihlášením. Data z účtů, se kterými
  Claude pracuje, ale procházejí konverzací s Claudem (viz [Kam tečou data](#kam-tečou-data)).
- Pracuje jen s účty, které mu povolíš v `accounts.yaml`. Jiné účty odmítne, i pro čtení.
- Každý zápis má dva kroky: Claude změnu nejdřív připraví a Google ji ověří nanečisto (nic se nemění),
  provede se až po tvém souhlasu.
- Citlivé změny (rozpočty, nabídky, zapínání, cílení, mazání, konverze, nastavení účtu) jsou **chráněné**:
  provede je jen samostatný nástroj a jen po výslovném souhlasu s konkrétním plánem.
- Funguje na Windows i macOS.

> [!WARNING]
> **Vibecoděné.** Nejsem programátor, jsem marketér. Google Ads MCP jsem postavil s Claudem: kód z velké části
> napsala AI podle mých zadání a já ho ladím při vlastní práci. Mně funguje, ale můžou v něm
> být chyby, neefektivní řešení i bezpečnostní rizika, na která jsem nepřišel. Než ho pustíš na důležité účty,
> projdi si kód (nebo ho dej projít někomu, kdo mu rozumí), začni na jednom účtu a každou změnu před schválením
> čti. Používáš ho na vlastní odpovědnost.

Podrobný návod krok za krokem (Google účet, Cloud projekt, přístup k API, instalace): **[docs/NAVOD.md](docs/NAVOD.md)**

## Co potřebuješ

- Claude Desktop (Windows nebo macOS)
- Python 3.10 nebo novější
- Google účet s přístupem do účtů Google Ads (přímo nebo přes MCC)
- Vlastní Google Cloud projekt se zapnutým Google Ads API a OAuth klientem typu Desktop app
  (návod v [docs/NAVOD.md](docs/NAVOD.md))

## Rychlá instalace

**Bez gitu:** nahoře na této stránce **Code > Download ZIP**, rozbal třeba do `Dokumenty/mcp/google-ads-mcp`
a spusť `instalovat-windows.bat` (Windows), nebo `instalovat-mac.command` (macOS) dvojklikem.
Spouštěč si sám najde Python, a když chybí, nabídne jeho instalaci.

**S gitem:**

```
git clone https://github.com/martinsevcik1/google-ads-mcp.git
cd google-ads-mcp
```

Windows: `py install.py`, macOS: `python3 install.py`

Instalátor provede všechny kroky: virtuální prostředí a knihovny, umístění seznamu účtů, přihlášení přes Google,
výpis účtů, ke kterým máš přístup, kontrolu přístupu a zápis serveru do Claude Desktopu.
Google Cloud projekt a OAuth klienta si ale musíš nejdřív založit podle [docs/NAVOD.md](docs/NAVOD.md).
Pak Claude Desktop úplně ukonči a spusť znovu.

## Nástroje

**Čtení a reporty**
- `list_accounts` - povolené účty
- `run_gaql` - libovolný GAQL dotaz (peníze rovnou v měně účtu)
- `export_gaql` - celý výsledek dotazu do CSV ve složce klienta
- `get_resource_fields` - jaká pole jde v GAQL vybrat
- `search_terms_review`, `mark_search_terms` - rozbor vyhledávacích dotazů (vyhledávání i PMAX), filtruje lokálně
  a šetří kontext, posouzené dotazy si pamatuje
- `list_audience_segments`, `find_geo_targets` - podklady pro publika a lokality

**Specializované návrhy změn**
- vyhledávání: `propose_search_campaign`, `propose_ad_group`, `propose_keywords`, `propose_negative_keywords`,
  `propose_remove_negative_keywords`, `propose_rsa`, `propose_update_rsa`, `propose_campaign_assets`
- Performance Max: `propose_pmax_campaign`, `propose_asset_group`, `propose_asset_group_assets`,
  `propose_listing_groups`, `propose_search_themes`, `propose_pmax_automation`, `propose_audience_signal`
- publika: `propose_custom_segment`, `propose_audience`
- média: `propose_upload_images`, `propose_youtube_videos`, `propose_video_upload`, `video_upload_status`
- správa: `propose_status_change`, `propose_budget_change`, `propose_bidding_target`, `propose_campaign_locations`,
  `propose_rename`

**Celé API**
- `propose_mutate` - jakákoli změna přes MutateOperation (všech 64 typů), MCP sám doplní update_mask a pozná,
  jestli je změna chráněná
- `call_service` - čtecí služby (Plánovač klíčových slov, doporučení, náhledy, generování...)
- `propose_service_call` - akce mimo běžný zápis (doporučení, nahrávání konverzí, Customer Match, experimenty)
- `api_catalog`, `api_type_help`, `api_operation_help`, `api_guide` - nápověda k API přímo z knihovny
  a výtah z oficiální dokumentace, aby Claude skládal operace správně
- `api_status` - verze API a data jejich vypnutí

**Provedení**
- `preview_changes`, `release_preview` - Excel s náhledem všech připravených plánů, ve sloupci Nasadit označíš,
  co provést
- `list_pending_changes`, `discard_change`
- `apply_change` - běžná změna
- `apply_guarded_change` - chráněná změna, jen po výslovném souhlasu

Co MCP záměrně nedělá: fakturace, správa uživatelů, vazby MCC a zakládání účtů.

## Doporučené postupy

MCP je stavěný na maximální efektivitu: Claude skládá související změny v jednom účtu do jednoho plánu,
takže schvaluješ málo kroků a zbytek běží sám. Příklady zadání:

- **Rozbor dotazů:** „Projdi dotazy v účtu X za 30 dní, navrhni negativa a nová klíčová slova, připrav to
  jako jeden plán." Claude použije `search_terms_review`, ukáže návrh, po souhlasu provede.
- **Audit účtu:** „Udělej audit účtu X: struktura, měření konverzí, podíl zobrazení, ztráty na rozpočtu
  a hodnocení, kvalita podkladů. Na konci 5 nejdůležitějších kroků."
- **Nová kampaň:** „Založ vyhledávací kampaň pro službu Y: 3 sestavy, slova v přesné a frázové shodě,
  RSA, negativa, rozpočet 500 Kč." Kampaň vznikne pozastavená, zapnutí je chráněná změna.
- **Performance Max:** „Založ PMAX kampaň s obrázky ze složky klienta, texty napiš podle webu."
- **Hromadné úpravy přes víc účtů:** nech připravit plány, pak „udělej náhled" a v Excelu označ,
  co nasadit.
- **Reporty:** „Vyexportuj výkon kampaní po měsících za rok do CSV" (`export_gaql`).
- **Cokoli z rozhraní nebo Editoru:** popiš, co chceš udělat. Pokud na to není specializovaný nástroj,
  Claude si přečte nápovědu k API a sestaví změnu přes `propose_mutate`.

## Seznam účtů a složky klientů

`accounts.yaml` (vzor v `accounts.example.yaml`):

```yaml
dpa: false                                   # viz Režim s DPA a bez DPA
default_login_customer_id: "123-456-7890"   # MCC, přes které přistupuješ (nebo null)
clients_root: klienti                         # relativně ke složce s accounts.yaml
accounts:
  "234-567-8901": {name: vzorovy-eshop.cz, folder: vzorovy_eshop}
```

Do složky klienta MCP ukládá exporty, náhledy a stav rozboru dotazů. Obrázky a videa z disku nahraje
do účtu jen tehdy, když leží v jeho složce (pojistka proti záměně podkladů mezi klienty).

## Víc počítačů

Seznam účtů dej do složky na cloudovém disku (OneDrive, Google Drive, Dropbox, iCloud). Složky klientů
(`clients_root`) a log změn se pak počítají relativně k němu, takže všechny počítače sdílí stejná data.
Na každém počítači stačí naklonovat repo, spustit `install.py`, zadat cestu k tomu samému `accounts.yaml`
a přihlásit se. Přihlašovací údaje (`~/.google-ads/`) se nesynchronizují, každý počítač má vlastní.

## Rozšíření

Vlastní pravidla a nástroje jde přidat bez úprav tohoto repa: v libovolné složce vytvoř modul `ads_extras.py`
s proměnnou `INSTRUCTIONS` (text připojený k pokynům pro Clauda) a funkcí `register(mcp, safe)`, která
zaregistruje další nástroje. Cestu ke složce předej instalátoru (`install_claude_config.py --extras CESTA`),
zapíše ji do proměnné `ADS_EXTRAS_DIR`.

## Aktualizace

```
git pull
```

a pak znovu `install.py` (doinstaluje případné nové knihovny), nebo jen
`.venv/bin/python -m pip install -r requirements.txt` (Windows: `.venv\Scripts\python.exe -m pip install -r requirements.txt`).
Po aktualizaci Claude Desktop úplně ukonči a spusť znovu.

Google vydává nové verze API několikrát ročně a staré vypíná. `list_accounts` a `api_status` upozorní,
když se blíží vypnutí verze, kterou MCP používá.

## Kam tečou data

- **Server sám** běží u tebe na počítači a komunikuje jen s Google Ads API. Žádný další server mezi tím není.
- **Přihlašovací údaje** (refresh token v `~/.google-ads`) zůstávají na tvém počítači. Server je čte lokálně a do
  konverzace je nikdy nevrací.
- **Výsledky nástrojů jdou do konverzace s Claudem**, tedy k Anthropicu: názvy kampaní, čísla z reportů,
  vyhledávací dotazy, texty reklam i všechno ostatní, co si Claude přečte. Anthropic je zpracovává v USA nebo jinde
  ve světě a pomáhají mu s tím subdodavatelé ([seznam](https://www.anthropic.com/subprocessors)). Co s nimi smí
  dělat, určují podmínky tvého plánu Claude.

### Než to pustíš na klientský účet

1. **Smí data klienta k Anthropicu?** Výkon kampaní, rozpočty nebo tržby nejsou osobní údaje, ale často je chrání
   NDA nebo smlouva s klientem. Ověř si v ní (a ve smlouvě s agenturou, pokud pracuješ přes ni), že data smíš
   předat poskytovateli AI v USA nebo jinde mimo EU, včetně jeho subdodavatelů. Když to smlouva neřeší nebo
   zakazuje, potřebuješ souhlas klienta.
2. **Pracuješ v plánu s obchodními podmínkami?** Claude Team (od dvou míst), Enterprise a API mají smlouvu o
   zpracování osobních údajů (DPA) a Anthropic na datech netrénuje. Free, Pro a Max jsou spotřebitelské plány bez
   DPA a trénování v nich vypíná jen přepínač v nastavení. Na klientská data je nepoužívej.
3. **Jsou v datech osobní údaje?** Nech výchozí `dpa: false` (viz níže). `dpa: true` zapni, jen když máš DPA s
   klientem i s poskytovatelem modelu.
4. **Musí data zůstat v EU?** Claude přímo od Anthropicu zpracování jen v EU nezaručí. Použij Claude Code s modelem
   z Google Cloudu (Agent Platform, region `eu`) nebo z Amazon Bedrocku (evropský inference profil). DPA pak máš s
   Googlem nebo Amazonem a platíš za skutečnou spotřebu. Nastavení přes Google Cloud krok za krokem: [Jak používat
   Claude Code pro práci s firemními a zákaznickými
   daty](https://www.measuredesign.cz/blog/jak-pouzivat-claude-code-pro-praci-s-firemnimi-a-zakaznickymi-daty)
   (MeasureDesign). MCP do Claude Code přidáš takhle:

   ```
   claude mcp add --scope user google-ads -- <složka>/.venv/bin/python <složka>/server.py
   ```

   Na Windows je Python v `<složka>\.venv\Scripts\python.exe`. Pokud máš seznam účtů jinde než ve složce MCP,
   přidej za `--scope user` i `--env ADS_ACCOUNTS_FILE=<cesta k accounts.yaml>`.

Tohle není právní rada. Smlouvy si nech projít od toho, kdo ti je píše.

### Režim s DPA a bez DPA

Osobní údaje by do konverzace měly jít jen tehdy, když máš smlouvu o zpracování osobních údajů (DPA) s klientem i s
poskytovatelem modelu. U Anthropicu je DPA automaticky součástí obchodních podmínek plánů Claude Team, Enterprise a
API, u Clauda přes Google Cloud nebo Amazon Bedrock ji máš s nimi. Plány Free, Pro a Max DPA nemají. Proto má MCP
přepínač v `accounts.yaml`:

```yaml
dpa: false   # výchozí
```

- **`dpa: false` (výchozí):** MCP do konverzace osobní údaje nepouští. Odmítne
  - nahrávání seznamů zákazníků (Customer Match) a offline nebo vylepšených konverzí s kontaktními údaji,
  - GAQL nad daty z formulářů pro potenciální zákazníky, poptávkami z místních služeb, uživateli účtu
    a e-mailem autora změny v historii,
  - vyhledávací dotazy s e-mailem nebo telefonním číslem v rozboru dotazů vynechá (zůstanou jen v lokálním CSV)
    a v ostatních výpisech je zamaskuje.
- **`dpa: true`:** vše povolené. Ochrana chráněných změn a souhlas před zápisem platí v obou režimech.

Aktuální režim ukáže výpis účtů. Omezení: jména a adresy, které lidé píšou do vyhledávání, strojově spolehlivě
poznat nejde, takže je filtr nezachytí. Google Ads ale v přehledu ukazuje jen dotazy, které hledalo víc lidí, takže
soukromé e-maily, telefony a jména se do něj skoro nedostanou.

## Bezpečnost

- `~/.google-ads/google-ads.yaml` obsahuje refresh token. Kdo ho má, může pracovat ve všech účtech, kam máš
  přístup. Nikam ho nekopíruj, nesdílej a nedávej do synchronizovaných složek ani do gitu.
- Přístup aplikace jde kdykoli zrušit na https://myaccount.google.com/permissions
- Obrázky a videa z disku MCP nahraje jen ze složky klienta, do jehož účtu se nahrávají.
- Každý uživatel má mít vlastní Google Cloud projekt a vlastní přihlášení. Nepoužívej cizí OAuth klienta
  ani cizí přihlášení.
- Log všech provedených změn je ve složce `logs` vedle `accounts.yaml`.
- MCP je určené k běhu na tvém počítači pro účty, ke kterým máš přístup. Neprovozuj ho jako službu
  pro ostatní, ať si ho každý nainstaluje sám se svým přístupem. U Google Ads to navíc výslovně zakazují
  podmínky Google Ads API (MCP server jako mezivrstva pro cizí přístup).

### Uložení klíčů

Klíče a tokeny leží jako obyčejné soubory ve tvé domovské složce (`~/.google-ads/`), čitelné jen pro tvého uživatele.
Nejsou zašifrované v trezoru systému (Správce pověření ve Windows, Klíčenka na macOS). Kdo se dostane k tvému
uživatelskému účtu nebo k jeho zálohám, může je přečíst. Proto tuhle složku nezálohuj do cloudu, nesynchronizuj
a nikomu neposílej. Je to stejný přístup, jaký používá oficiální knihovna Google Ads i většina nástrojů
pro příkazovou řádku.

### Podstrčené pokyny (prompt injection)

Do konverzace jdou texty z účtů, které píšou cizí lidé: vyhledávací dotazy, názvy kampaní, texty reklam,
chybové hlášky. Někdo do nich může schovat „pokyn“ pro Clauda. Úplná ochrana proti tomu u AI nástrojů
neexistuje, MCP ale riziko omezuje:

- Claude má v pokynech, že texty z účtů jsou data, ne příkazy.
- Žádná změna se neprovede bez plánu. Chráněné změny jen samostatným nástrojem po výslovném souhlasu.
- MCP sahá jen na povolené účty a nemá nástroj, který by četl libovolné soubory nebo posílal data jinam
  než do API.
- **Doporučení:** v Claude Desktopu nech u nástrojů pro provedení změn (`apply_change`,
  `apply_guarded_change`) zapnuté schvalování pokaždé, nepovoluj je natrvalo. Pak se žádná změna
  neprovede bez tvého kliknutí, ani kdyby Clauda něco zmátlo.

Exporty do CSV mají hodnoty začínající `=`, `+`, `-` nebo `@` označené apostrofem, aby je Excel nespustil
jako vzorec. Náhledy v Excelu zapisují všechno jako text.

## Narazil jsi na problém?

Dej mi vědět, opravím to. Každé hlášení pomáhá, protože kód nikdo jiný než já a Claude nekontroloval.

- **Chyba, nesrozumitelný návod, nápad na vylepšení:** založ [issue](https://github.com/martinsevcik1/google-ads-mcp/issues).
- **Bezpečnostní problém** (únik klíče nebo tokenu, obejití pojistek, zápis bez souhlasu, přístup k účtu,
  který není povolený): prosím ne do veřejného issue. Napiš mi na
  [martin@sevcikmarketing.com](mailto:martin@sevcikmarketing.com).
- **Pull requesty** beru rád. Jen počítej s tím, že je čtu po práci, takže odpověď může chvíli trvat.

## Pomohlo ti to?

Nástroj je zdarma. Pokud ti ušetřil čas a chceš mi to nějak vrátit, nejvíc mi pomůže
recenze na Google Mapách nebo na Firmy.cz. Stačí pár vět o tom, jak se ti s ním pracuje.
Hvězdička tady na GitHubu taky potěší.

<table>
  <tr>
    <td align="center"><a href="https://search.google.com/local/writereview?placeid=ChIJ-XMER96VEkcRXoq1r8WHRhk"><img src="docs/img/qr-google-review.png" width="160" alt="QR kód: recenze na Google Mapách"></a><br><a href="https://search.google.com/local/writereview?placeid=ChIJ-XMER96VEkcRXoq1r8WHRhk"><b>Recenze na Google</b></a></td>
    <td align="center"><a href="https://www.firmy.cz/detail/13441299-mgr-martin-sevcik-sevcikmarketing-com-brno-stare-brno.html"><img src="docs/img/qr-firmy-cz.png" width="160" alt="QR kód: profil na Firmy.cz"></a><br><a href="https://www.firmy.cz/detail/13441299-mgr-martin-sevcik-sevcikmarketing-com-brno-stare-brno.html"><b>Recenze na Firmy.cz</b></a></td>
  </tr>
</table>

Díky!

## Autor a licence

[Martin Ševčík](https://sevcikmarketing.com). Kód je pod licencí [MIT](LICENSE):
můžeš ho používat, upravovat i dál šířit, i komerčně, bez záruky.
