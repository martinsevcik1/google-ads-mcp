# Google Ads MCP

**English** | [Čeština](README.cs.md)

A local MCP server that lets Claude (Claude Desktop) read and manage Google Ads accounts directly through the
Google Ads API. The idea is to do as much of the work as possible from the conversation: reports, search term
reviews, negatives, new campaigns, RSAs, Performance Max, audiences, assets, settings and anything else the API
can do, without the web interface or Google Ads Editor.

- It runs on your computer, under your own Google Cloud project and your own Google login. Data from the
  accounts Claude works with does go through your conversation with Claude, though (see
  [Where your data goes](#where-your-data-goes)).
- It only touches accounts you allow in `accounts.yaml`. Anything else is refused, even reads.
- Every write takes two steps: Claude prepares the change and Google validates it as a dry run (nothing changes),
  and it only goes live after you approve it.
- Sensitive changes (budgets, bids, enabling things, targeting, removals, conversions, account settings) are
  **guarded**: only a separate tool can apply them, and only after you explicitly approve that specific plan.
- Works on Windows and macOS.

> [!WARNING]
> **Vibe-coded.** I'm not a developer, I'm a marketer. I built this with Claude: most of the code was written by
> AI from my instructions, and I keep refining it in my own work. It works for me, but
> expect bugs, inefficient code and possibly security issues I haven't spotted. Before you point it at accounts
> that matter, read through the code (or have someone who understands it do that), start with one account and
> read every change before you approve it. Use it at your own risk.

The tool descriptions are in Czech. Claude reads them fine and will talk to you in any
language. The step-by-step setup guide is [docs/GUIDE.md](docs/GUIDE.md) ([Czech version](docs/NAVOD.md)); the short version is below.

## What you need

- Claude Desktop (Windows or macOS)
- Python 3.10 or newer
- A Google account with access to Google Ads accounts (directly or through an MCC)
- Your own Google Cloud project with the Google Ads API enabled and an OAuth client of type Desktop app

## Quick install

**Without git:** at the top of this page click **Code > Download ZIP**, unzip it (for example to
`Documents/mcp/google-ads-mcp`) and double-click `instalovat-windows.bat` (Windows) or
`instalovat-mac.command` (macOS). The launcher finds Python, and offers to install it if it's missing.

**With git:**

```
git clone https://github.com/martinsevcik1/google-ads-mcp.git
cd google-ads-mcp
```

Windows: `py install.py`, macOS: `python3 install.py`

The installer walks you through everything: virtual environment and libraries, where to keep the account list,
Google login, a list of the accounts you can access, an access check, and adding the server to Claude Desktop.
Create the Google Cloud project and the OAuth client first (Google Cloud Console: link a billing account, the
API itself is free but Google won't grant access without one; then APIs & Services: enable Google Ads API, set up
the OAuth consent screen, create an OAuth client ID of type Desktop app and download the JSON). Then quit Claude Desktop completely and start it again.

## Tools

**Reading and reports**
- `list_accounts` - allowed accounts
- `run_gaql` - any GAQL query (money already converted to the account currency)
- `export_gaql` - the full query result as CSV in the client's folder
- `get_resource_fields` - which fields a GAQL query can select
- `search_terms_review`, `mark_search_terms` - search term review (Search and PMAX), filtered locally to save
  context, remembers which terms you've already reviewed
- `list_audience_segments`, `find_geo_targets` - lookups for audiences and locations

**Specialised change proposals**
- Search: `propose_search_campaign`, `propose_ad_group`, `propose_keywords`, `propose_negative_keywords`,
  `propose_remove_negative_keywords`, `propose_rsa`, `propose_update_rsa`, `propose_campaign_assets`
- Performance Max: `propose_pmax_campaign`, `propose_asset_group`, `propose_asset_group_assets`,
  `propose_listing_groups`, `propose_search_themes`, `propose_pmax_automation`, `propose_audience_signal`
- Audiences: `propose_custom_segment`, `propose_audience`
- Media: `propose_upload_images`, `propose_youtube_videos`, `propose_video_upload`, `video_upload_status`
- Management: `propose_status_change`, `propose_budget_change`, `propose_bidding_target`,
  `propose_campaign_locations`, `propose_rename`

**The whole API**
- `propose_mutate` - any change through MutateOperation (all 64 types); the MCP fills in the update_mask and
  works out whether the change is guarded
- `call_service` - read-only services (Keyword Planner, recommendations, previews, generators...)
- `propose_service_call` - actions outside regular mutates (recommendations, conversion uploads, Customer Match,
  experiments)
- `api_catalog`, `api_type_help`, `api_operation_help`, `api_guide` - API help straight from the client library
  plus a digest of the official docs, so Claude builds operations correctly
- `api_status` - API version in use and its sunset date

**Applying changes**
- `preview_changes`, `release_preview` - an Excel preview of all prepared plans; tick what to apply in the
  Nasadit column
- `list_pending_changes`, `discard_change`
- `apply_change` - regular change
- `apply_guarded_change` - guarded change, only after explicit approval

What it deliberately doesn't do: billing, user management, MCC links and creating accounts.

## How to use it

Claude bundles related changes in one account into a single plan, so you approve few steps. Example prompts:

- **Search terms:** "Go through search terms in account X for the last 30 days, suggest negatives and new
  keywords as one plan."
- **Audit:** "Audit account X: structure, conversion tracking, impression share, budget and rank losses, asset
  quality. Finish with the 5 most important next steps."
- **New campaign:** "Create a Search campaign for service Y: 3 ad groups, exact and phrase keywords, RSAs,
  negatives, budget 500." The campaign is created paused, enabling it is a guarded change.
- **Performance Max:** "Create a PMAX campaign with the images in the client's folder, write the copy based on
  the website."
- **Bulk edits across accounts:** have the plans prepared, then "make a preview" and tick in Excel what to apply.
- **Anything from the UI or Editor:** describe what you want. If there's no dedicated tool, Claude reads the API
  help and builds the change through `propose_mutate`.

## Account list and client folders

`accounts.yaml` (template in `accounts.example.yaml`):

```yaml
dpa: false                                   # see "DPA mode" below
default_login_customer_id: "123-456-7890"   # the MCC you access accounts through (or null)
clients_root: klienti                         # relative to the folder with accounts.yaml
accounts:
  "234-567-8901": {name: example-shop.com, folder: example_shop}
```

The MCP saves exports, previews and search term review state in the client's folder. It only uploads images and
videos from disk if they sit in that account's folder, so assets can't end up in the wrong client's account.

## More than one computer

Put the account list in a synced folder (OneDrive, Google Drive, Dropbox, iCloud). Client folders and the change
log are resolved relative to it, so all computers share the same data. On each computer, clone the repo, run
`install.py`, point it to the same `accounts.yaml` and log in. Login credentials (`~/.google-ads/`) are never
synced, each computer has its own.

## Extensions

You can add your own rules and tools without touching this repo: create an `ads_extras.py` module in any folder
with an `INSTRUCTIONS` variable (text appended to Claude's instructions) and a `register(mcp, safe)` function
that registers extra tools. Pass the folder to the installer (`install_claude_config.py --extras PATH`), which
stores it in the `ADS_EXTRAS_DIR` variable.

## Updating

```
git pull
```

then run `install.py` again (it installs any new libraries), or just
`.venv/bin/python -m pip install -r requirements.txt` (Windows: `.venv\Scripts\python.exe -m pip install -r requirements.txt`).
Restart Claude Desktop afterwards.

Google releases new API versions several times a year and switches old ones off. `list_accounts` and
`api_status` warn you when the version this MCP uses is approaching its sunset.

## Where your data goes

- **The server itself** runs on your computer and only talks to the Google Ads API. There's no other server in
  between.
- **Credentials** (the refresh token in `~/.google-ads`) stay on your computer. The server reads them locally and
  never returns them to the conversation.
- **Tool results go into your conversation with Claude**, i.e. to Anthropic: campaign names, report numbers, search
  terms, ad copy and anything else Claude reads. Anthropic processes them in the US or elsewhere in the world, with
  help from subprocessors ([list](https://www.anthropic.com/subprocessors)). What it may do with them depends on
  the terms of your Claude plan.

### Before you use it on a client account

1. **May the client's data go to Anthropic?** Campaign performance, budgets and revenue aren't personal data, but
   an NDA or your client contract often protects them. Check that it lets you pass the data to an AI provider in
   the US or elsewhere outside the EU, including its subprocessors (and check your agency contract too if you work
   through one). If the contract doesn't cover this or forbids it, you need the client's consent.
2. **Are you on a plan with commercial terms?** Claude Team (from two seats), Enterprise and the API include a data
   processing agreement (DPA), and Anthropic doesn't train on your data. Free, Pro and Max are consumer plans
   without a DPA, where only a toggle in your settings switches training off. Don't use them for client data.
3. **Is personal data involved?** Keep the default `dpa: false` (see below). Only switch to `dpa: true` once you
   have a DPA with both the client and the model provider.
4. **Does the data have to stay in the EU?** Claude straight from Anthropic can't guarantee EU-only processing. Use
   Claude Code with a model from Google Cloud (Agent Platform, region `eu`) or Amazon Bedrock (an EU inference
   profile). Your DPA is then with Google or Amazon, and you pay for actual usage. Step-by-step Google Cloud setup
   by MeasureDesign (in Czech): [Jak používat Claude Code pro práci s firemními a zákaznickými
   daty](https://www.measuredesign.cz/blog/jak-pouzivat-claude-code-pro-praci-s-firemnimi-a-zakaznickymi-daty). Add
   the MCP to Claude Code like this:

   ```
   claude mcp add --scope user google-ads -- <folder>/.venv/bin/python <folder>/server.py
   ```

   On Windows, Python is in `<folder>\.venv\Scripts\python.exe`. If your account list lives outside the MCP folder,
   add `--env ADS_ACCOUNTS_FILE=<path to accounts.yaml>` after `--scope user`.

This isn't legal advice. Have your contracts checked by whoever drafts them.

### DPA mode

Personal data should only go into the conversation if you have a data processing agreement (DPA) with both the
client and the model provider. With Anthropic, it's part of the commercial terms for Claude Team, Enterprise and
the API. With Claude through Google Cloud or Amazon Bedrock, you have it with them. Free, Pro and Max don't have
one. That's why `accounts.yaml` has a switch:

```yaml
dpa: false   # default
```

- **`dpa: false` (default):** the MCP keeps personal data out of the conversation. It refuses
  - Customer Match list uploads and offline or enhanced conversion uploads with contact details,
  - GAQL over lead form data, Local Services leads, account users and the user email in change history,
  - and in search term reviews it leaves out terms containing an email or phone number (they stay in the local
    CSV only) and masks them in other outputs.
- **`dpa: true`:** everything is allowed. Guarded changes and approval before every write work the same in both
  modes.

The current mode is shown in the account list. Limitation: names and addresses people type into search can't be
detected reliably, so the filter won't catch them. Google Ads only shows search terms that enough people searched
for, though, so private email addresses, phone numbers and names hardly ever make it into the report.

## Security

- `~/.google-ads/google-ads.yaml` holds the refresh token. Whoever has it can work in every account you have
  access to. Don't copy it anywhere, don't share it, and keep it out of synced folders and git.
- You can revoke the app's access at any time at https://myaccount.google.com/permissions
- Images and videos from disk are only uploaded from the folder of the client whose account they go to.
- Every user should have their own Google Cloud project and their own login. Don't use someone else's OAuth
  client or login.
- The change log is in the `logs` folder next to `accounts.yaml`.
- This MCP is meant to run on your own computer for accounts you have access to. Don't run it as a service for
  other people, let everyone install it themselves. The Google Ads API terms explicitly prohibit an MCP server
  acting as a middle layer for third-party access.

### How keys are stored

Keys and tokens are plain files in your home folder (`~/.google-ads/`), readable only by your user. They're not
encrypted in the system keychain (Credential Manager on Windows, Keychain on macOS). Anyone with access to your
user account or its backups can read them, so don't back this folder up to the cloud, don't sync it and don't
send it to anyone. It's the same approach the official Google Ads client library and most command-line tools use.

### Prompt injection

Text written by other people goes into the conversation: search terms, campaign names, ad copy, error messages.
Someone could hide an "instruction" for Claude in there. No AI tool can fully prevent that, but the MCP limits
the risk:

- Claude's instructions say that text from the accounts is data, not commands.
- Nothing changes without a plan. Guarded changes need a separate tool and your explicit approval.
- The MCP only touches allowed accounts and has no tool that reads arbitrary files or sends data anywhere but
  the API.
- **Recommendation:** in Claude Desktop, keep the tools that apply changes (`apply_change`, `apply_guarded_change`) on
  approval every time, don't allow them permanently. Then nothing changes without your click, even if something
  confuses Claude.

CSV exports prefix values starting with `=`, `+`, `-` or `@` with an apostrophe so Excel doesn't run them as
formulas. Excel previews write everything as text.

## Found a problem?

Let me know and I'll fix it. Every report helps, since nobody but me and Claude has looked at this code.

- **Bugs, unclear docs, ideas:** open an [issue](https://github.com/martinsevcik1/google-ads-mcp/issues).
- **Security issues** (a leaked key or token, a way around the safeguards, a write without approval, access to
  an account that isn't allowed): please don't open a public issue. Email me at
  [martin@sevcikmarketing.com](mailto:martin@sevcikmarketing.com).
- **Pull requests** are welcome. I read them after work, so it may take a while.

## Did it help?

The tool is free. If it saved you time and you'd like to give something back, a review on Google Maps or
Firmy.cz helps me the most. A couple of sentences about how it works for you is plenty.
A star here on GitHub is nice too.

<table>
  <tr>
    <td align="center"><a href="https://search.google.com/local/writereview?placeid=ChIJ-XMER96VEkcRXoq1r8WHRhk"><img src="docs/img/qr-google-review.png" width="160" alt="QR code: review on Google Maps"></a><br><a href="https://search.google.com/local/writereview?placeid=ChIJ-XMER96VEkcRXoq1r8WHRhk"><b>Review on Google</b></a></td>
    <td align="center"><a href="https://www.firmy.cz/detail/13441299-mgr-martin-sevcik-sevcikmarketing-com-brno-stare-brno.html"><img src="docs/img/qr-firmy-cz.png" width="160" alt="QR code: profile on Firmy.cz"></a><br><a href="https://www.firmy.cz/detail/13441299-mgr-martin-sevcik-sevcikmarketing-com-brno-stare-brno.html"><b>Review on Firmy.cz</b></a></td>
  </tr>
</table>

Thanks!

## Author and licence

[Martin Ševčík](https://sevcikmarketing.com). The code is under the [MIT](LICENSE) licence: you can use, modify
and redistribute it, commercially too, with no warranty.
