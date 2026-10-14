# Guide: Google Ads MCP from scratch

Česky: [NAVOD.md](NAVOD.md)

This guide walks you through everything you only do once: a Google account, a Google Cloud project, access to
the Google Ads API, signing in and installing on Windows or macOS. Allow about 30-45 minutes.

Why your own project and your own sign-in: since September 2026, Google Ads API access is granted to a
**Google Cloud project** (it used to be a developer token in an MCC). Everyone who uses the MCP should have their
own Cloud project and their own OAuth client, and sign in with their own Google account. Never use someone else's
project or sign-in: all changes in the accounts are then recorded under your name, and you only have access where
a client or agency has given it to you.

---

## 1. Google account

You need a Google account that:

- has access to the Google Ads accounts you want to work with (directly or through an agency MCC),
- will own the Google Cloud project.

The simplest option is one account for both. Your choices:

**A) The account you already use for Google Ads** (a work address on Google Workspace, or Gmail). There's nothing
to set up, go straight to step 2.

**B) A new Gmail address just for this work.** Useful if you don't want to mix work and personal things, or if
your current account belongs to someone else (an agency's company account, for example).

1. Open https://accounts.google.com/signup and create the account (name, date of birth, `@gmail.com` address,
   password).
2. Turn on 2-Step Verification: https://myaccount.google.com/security > 2-Step Verification.
3. Ask for Google Ads access for the new address:
   - **Through an agency MCC:** the MCC admin adds you in the MCC under Admin > Access and security > Users > +.
     Access level Standard (or Admin if you'll also change account settings).
   - **Directly in the client's account:** the client adds you in their account in the same menu.
   - **Your own MCC:** you can create your own manager account at https://ads.google.com/home/tools/manager-accounts/
     and link clients to it (the client approves the request in their account).
4. Accept the invitation from the email that arrives at the new Gmail address.

Check that this account gets you into the client accounts at https://ads.google.com. If it does, carry on.

---

## 2. Google Cloud project

Do everything in this step signed in with the account from step 1 (if your browser has several accounts, check
which one is active in the top right corner of the Cloud Console).

1. Open https://console.cloud.google.com and accept the terms (first time only).
2. Click the project picker at the top > **New project**. Name it, for example, `google-ads-mcp`. Leave the
   organisation as it is ("No organisation" for Gmail). **Create.**
3. Switch to the new project (project picker at the top).
4. **Billing:** the Google Ads API is free, but Google refuses API access to projects on the Free Trial or
   without a valid billing account. In the **Billing** menu, link the project to a billing account (you create
   one there, it asks for a card). Nothing will be charged unless you turn on paid services.
   If Google puts you on the Free Trial, activate a full account (the Activate / Upgrade button).
5. **Turn on the Google Ads API:** menu **APIs & Services > Library**, search for "Google Ads API" > **Enable**.

---

## 3. Consent screen (OAuth)

Menu **Google Auth Platform** (formerly "APIs & Services > OAuth consent screen"). The first time, it takes you
through a wizard:

1. **App information:** app name (for example `Google Ads MCP`), support email = your email.
2. **Audience:** **External**.
   (Internal only works on Google Workspace and only for users from the same domain.)
3. **Contact information:** your email. Accept the policy and click **Create**.
4. Open **Audience** and click **Publish app** > confirm. The status must be **In production**.
   Why: if the app stays in Testing, your sign-in expires after 7 days and the MCP stops working
   (error `invalid_grant`).

You don't need Google to verify the app for your own use. When you sign in, you'll see the warning "Google
hasn't verified this app". That's fine, it's your own app: click **Advanced** > **Go to Google Ads MCP (unsafe)**.

---

## 4. OAuth client (Desktop app)

1. **Google Auth Platform > Clients > Create client.**
2. Application type: **Desktop app**. Name it, for example, `google-ads-mcp`. **Create.**
3. In the result window, click **Download JSON**. Keep the file (`client_secret_....json`) in your Downloads
   folder for now, the installer will pick it up.

Don't send this file to anyone, and don't put it in git or on a shared drive.

---

## 5. API access level

A new project only has **Test** access (test accounts only). For real accounts you need **Explorer**:

1. In the Cloud Console, open the **Google Ads API** page (APIs & Services > Enabled APIs & services >
   Google Ads API) and its Google Ads API Overview.
2. Click **Upgrade access level** and request **Explorer**. Fill in a short form (what you use the API for:
   managing your own or your clients' accounts). It's often approved automatically within a few minutes.

Levels:

| Level | Limit | What it can't do |
|---|---|---|
| Explorer | 2,880 operations per day | Keyword Planner, reach planning, billing, user management |
| Basic | 15,000 operations per day | nothing you need day to day; requires brand verification of the project |

An operation is one data query, or one item in a write. Explorer is enough for day-to-day management of a few
accounts. Basic is useful for a large number of accounts or if you want the Keyword Planner. You request it on
the same page, after verifying your brand in **Google Auth Platform > Branding** (your own domain, home page and
privacy policy).

Note: if you don't use the access for 90 days, Google may drop it back to Test.

---

## 6. Python and Claude Desktop

**Claude Desktop:** download it from https://claude.ai/download, install it, start it at least once and sign in.

**Python 3.10 or newer:**

- **Windows:** https://www.python.org/downloads/ > installer. On the first screen, tick
  **Add python.exe to PATH**. Check in PowerShell: `py --version`
- **macOS:** https://www.python.org/downloads/ > macOS installer. After installing, open Applications >
  Python 3.x and run **Install Certificates.command** (otherwise API connections can fail with an SSL certificate
  error). Check in Terminal: `python3 --version`
  (The Python that ships with macOS is often older than 3.10, hence the one from python.org. `brew install python`
  works too.)

**Git** (optional, but makes updates easier):

- Windows: https://git-scm.com/download/win
- macOS: run `git --version` in Terminal and the system offers to install it.

Without git, use **Code > Download ZIP** on the repository page and unzip it.

---

## 7. Download and install

Pick a permanent place (not Downloads), for example a `Documents/mcp` folder.

Windows (PowerShell):

```
cd $HOME\Documents
mkdir mcp; cd mcp
git clone https://github.com/martinsevcik1/google-ads-mcp.git
cd google-ads-mcp
py install.py
```

macOS (Terminal):

```
mkdir -p ~/Documents/mcp && cd ~/Documents/mcp
git clone https://github.com/martinsevcik1/google-ads-mcp.git
cd google-ads-mcp
python3 install.py
```

The installer asks step by step. You can skip any step and run `install.py` again later.

1. **Libraries:** creates `.venv` and installs the packages it needs (a few minutes).
2. **Where the account list should live:** Enter = in the repo folder. If you use more than one computer, enter
   a path to a folder on a cloud drive (see step 9).
3. **Path to the downloaded JSON:** drag the file from step 4 into the terminal window (this pastes its path) and
   press Enter. It's copied to `~/.google-ads/client_secret.json`.
4. **Sign-in:** a browser opens. Sign in with the account from step 1, confirm the unverified app warning
   (Advanced > Go to...) and allow access. The result is saved to `~/.google-ads/google-ads.yaml`.
5. **Account list:** lists the accounts and MCCs you have access to, with their IDs. Use it to fill in the
   account list.
6. **Fill in the account list:** open `accounts.yaml` (the installer prints its path) in a text editor:

   ```yaml
   dpa: false                                   # true only with a DPA with the client and the model provider
   default_login_customer_id: "123-456-7890"   # ID of the MCC you see the accounts through
   clients_root: klienti
   accounts:
     "234-567-8901": {name: client-a.com, folder: client_a}
     "345-678-9012": {name: client-b.com, folder: client_b}
   ```

   - You see the accounts through an MCC: `default_login_customer_id` = that MCC's ID (the account list shows it
     next to the account as `login_customer_id`).
   - You have the accounts directly, without an MCC: `default_login_customer_id: null`.
   - An account under a different MCC from the rest: add `login_customer_id: "ID-of-that-MCC"` to the account.
   - `folder` is the client folder for exports, previews and images. It's created automatically.
   - For `dpa`, see the README, section DPA mode. Leave it `false` unless you have a data processing agreement
     with both the client and the model provider (Claude Team, Enterprise or the API, or Claude through Google
     Cloud or Amazon Bedrock).

7. **Access check:** tries to read every account on the list and shows what works.
8. **Claude Desktop config:** adds the server to the Claude Desktop configuration (after backing it up).

Then **quit Claude Desktop completely** (Windows: including the icon next to the clock; macOS: Cmd+Q) and start
it again. In a conversation, type something like "list my Google Ads accounts". Claude should call
`list_accounts`.

You can edit the account list at any time; changes apply straight away without a restart.

---

## 8. First steps

- "How has client-a.com done over the last 30 days? Campaigns, spend, conversions, cost per conversion."
- "Go through the search terms in client-a.com for the last 30 days and suggest negatives."
- "Show me the campaign and ad group structure in client-b.com."

Claude always shows you a plan of the change first. It makes ordinary changes after your "yes"; protected ones
(budgets, bids, enabling, targeting, removals...) need explicit approval of the specific plan.

---

## 9. A second computer (say, Windows and a MacBook)

1. Put the account list in a folder on a cloud drive you have on both computers (OneDrive, Google Drive,
   Dropbox, iCloud Drive), for example `.../Google Drive/mcp/accounts.yaml`. The client folders
   (`clients_root: klienti`) and the change log are created next to it, so both computers see them.
2. On the second computer, repeat steps 6 and 7. When asked for the account list, enter the path to the same file
   on the cloud drive.
3. Use the same OAuth JSON from step 4 (you can download it again in Cloud Console > Google Auth Platform >
   Clients), but sign in on each computer separately. Don't copy or sync the `~/.google-ads` folder between
   computers.

Cloud drive paths differ between Windows and macOS. That's why you should keep them relative in `accounts.yaml`
(`clients_root: klienti`); each computer works them out from where the file is.

---

## 10. Troubleshooting

| Error | What to do |
|---|---|
| `CLOUD_PROJECT_NOT_APPROVED_FOR_PRODUCTION` | The project doesn't have Explorer access (step 5), or it's on the Free Trial without billing (step 2.4). If nothing helps, create a new project and apply again. |
| `invalid_grant` | Your sign-in has expired. Check that the app is In production (step 3.4) and run `install.py` again (sign-in). |
| `USER_PERMISSION_DENIED` | Wrong `login_customer_id`. Run the account list and use the MCC the account is listed under. |
| `CUSTOMER_NOT_ENABLED` | The account is cancelled or was never finished. |
| `QuotaError.RESOURCE_EXHAUSTED` | The daily operations limit is used up (Explorer 2,880). Wait; the limit counts the last 24 hours. |
| Claude doesn't see the tools | Quit Claude Desktop completely and start it again. Check that `install_claude_config.py` printed "Zapsáno" (written). |
| SSL / certificate error on macOS | Run Install Certificates.command from the Python folder in Applications (step 6). |
| The browser doesn't open at sign-in | Copy the address from the terminal into your browser by hand. |

Running individual steps by hand (from the repo root):

- Windows: `.venv\Scripts\python.exe auth_setup.py`, `check_access.py --list`, `check_access.py`,
  `install_claude_config.py`
- macOS: `.venv/bin/python auth_setup.py` and so on.

Revoking access: https://myaccount.google.com/permissions (the Google Ads MCP app), or delete the
`~/.google-ads` folder.
