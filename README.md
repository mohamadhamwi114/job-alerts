# LinkedIn Job Alerts → Telegram + Google Sheets

Get a Telegram message within ~30 minutes of a new job being posted on LinkedIn, for the roles and countries **you**
choose. Every job is also logged in a Google Sheet so you can track what you applied to.

Out of the box it tracks **AI engineers, Python engineers, and software/backend engineers whose job description
mentions Python**, in the Middle East, UK and US. Change [`config.toml`](config.toml) to track anything else
(frontend, DevOps, data, mobile…), with no code changes. See [Configuration](#configuration-configtoml).

- **Free**: Python script + Telegram bot + Google Sheets + GitHub Actions free tier.
- **No LinkedIn login**: it uses LinkedIn's public (logged-out) job search, so your LinkedIn account is never touched.
- **Alerts only**: it never applies to anything automatically.
- **One message per country**, sent as soon as that country is searched. No waiting for the whole run.
- **Hybrid scheduling**: every 30 min on your computer when it's on, every hour on GitHub's servers when it's off,
  with automatic catch-up so nothing posted while you were offline is missed, and never the same job twice.
- **Windows, Linux and macOS.**

---

## Table of contents
1. [How it works](#1-how-it-works)
2. [What you need](#2-what-you-need)
3. [Step 1: Get the code](#step-1-get-the-code)
4. [Step 2: Create a Telegram bot](#step-2-create-a-telegram-bot-token--chat-id)
5. [Step 3: Set up the Google Sheet](#step-3-set-up-the-google-sheet-service-account--sheet-id)
6. [Step 4: Run it on your computer](#step-4-run-it-on-your-computer)
7. [Step 5: Schedule it every 30 minutes](#step-5-schedule-it-every-30-minutes)
8. [Step 6: Cloud backup with GitHub Actions](#step-6-cloud-backup-with-github-actions)
9. [Configuration (`config.toml`)](#configuration-configtoml)
10. [Common changes (recipes)](#common-changes-recipes)
11. [Environment variables & command-line options](#environment-variables--command-line-options)
12. [Troubleshooting](#troubleshooting)
13. [Security notes](#security-notes)
14. [Stopping / uninstalling](#stopping--uninstalling)

---

## 1. How it works

```
        every 30 min (your computer)            every 1 h (GitHub Actions)
                     │                                     │
                     │                 skip if your computer ran in the last 45 min
                     ▼                                     ▼
  ┌────────────────────────────────── job_alerts.py ──────────────────────────────────┐
  │ load config.toml, read already-seen job IDs from the Google Sheet                 │
  │                                                                                   │
  │ for each country in config.toml:                                                  │
  │   1. search LinkedIn (posted in the last 30 min) + a remote-only search           │
  │   2. read the job cards: id, title, company, location, link                       │
  │   3. title filter: exclude words → must-have words → first matching role group   │
  │   4. drop jobs already in the Sheet                                               │
  │   5. if the group needs it, open the job description and check for keywords       │
  │   6. send that country's jobs to Telegram  →  7. append them to the Sheet         │
  │                                                                                   │
  │ nothing new at all? → "No new jobs" message                                       │
  └───────────────────────────────────────────────────────────────────────────────────┘
```

**Searching.** For each country it requests
`https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search` with:

| Parameter | Comes from | Meaning |
|---|---|---|
| `keywords` | `[search] keywords` | what to search for |
| `geoId` | `[[locations]] geo_id` | LinkedIn's numeric country ID |
| `f_TPR=r1800` | `[window_minutes]` | posted in the last N seconds |
| `f_WT=2` | `[search] remote_pass` | remote only (second search, tags jobs 🌍) |
| `start` | `max_pages` | pagination, 10 jobs per page |

Requests are spaced a few seconds apart (`sleep_seconds`). On HTTP 429 (too many requests) it waits
(`rate_limit_backoff_seconds`) and retries once. If it's still blocked, it stops the run early instead of hammering LinkedIn.

**Parsing.** LinkedIn returns HTML. BeautifulSoup reads each `div.base-card` for the job ID, title, company,
location and date. The link is `https://www.linkedin.com/jobs/view/<id>`.

**Filtering.** LinkedIn's keyword search is loose, so every title goes through `[filters]` and `[[groups]]`
(see [Configuration](#configuration-configtoml)). A group can also require words in the full **job description**
(e.g. "Software Engineer" only if the description mentions Python). Jobs that fail that check go to the
Sheet's `rejected` tab so they're never checked again.

**Dedupe.** The Google Sheet is the shared memory. Job IDs in `jobs` or `rejected` are skipped, so your computer and
the cloud never send the same job twice. Rows are written only *after* Telegram accepts the message, so a failed send
is retried on the next run.

**Computer vs. cloud: how GitHub knows your computer is on.** GitHub can't see your computer, so they talk through
the Sheet's `meta` tab:
- Every local run writes `last_local_run` (a heartbeat).
- Every cloud run reads it first. If it's younger than `local_heartbeat_minutes` (45), your computer is on, so the
  cloud run exits in seconds. If it's older, your computer is off or asleep, so the cloud run does the full search.

**Catch-up: nothing falls through the gap.** A fixed window would miss jobs around the switch-over. Example: the computer
runs at 10:00 and is shut down, the cloud skips at 10:30 (heartbeat still fresh), and at 11:30 a 60-minute window would
only cover 10:30–11:30. So every complete run also records `last_run` in `meta`, and the next run, on either side,
searches back to that moment (+5 min overlap) if that's longer than its normal window, up to 24 h. The same applies when
you turn your computer on in the morning: its first run covers the whole night, if the cloud didn't already.

**A Telegram message looks like:**
```
🇬🇧 United Kingdom · 3 new (last 30 min)
━━━━━━━━━━━━━━━
Senior AI Engineer
Acme Ltd · London, England, United Kingdom
🌍 Remote · AI

Python Software Engineer
Foo Corp · Manchester, England, United Kingdom
🏢 On-site/Hybrid · Python
```

---

## 2. What you need

| Thing | Cost | Used for |
|---|---|---|
| Python 3.10+ | free | running the script |
| Telegram account | free | receiving alerts |
| Google account | free | the Sheet (log + dedupe memory) |
| GitHub account | free | cloud runs when your computer is off (optional) |

Where commands differ by OS, both versions are shown.

| | Windows (PowerShell) | Linux / macOS (bash/zsh) |
|---|---|---|
| Install Python | https://www.python.org/downloads/ (tick **"Add python.exe to PATH"**) | usually preinstalled; else `sudo apt install python3 python3-venv` (Debian/Ubuntu), `sudo dnf install python3` (Fedora), `brew install python` (macOS) |
| Check | `python --version` | `python3 --version` |
| Python in the venv | `.\.venv\Scripts\python.exe` | `.venv/bin/python` |
| Scheduler | Task Scheduler (`register_task.ps1`) | cron (`install_cron.sh`) |

---

## Step 1: Get the code

Download this repo as a ZIP (**Code → Download ZIP**) and unzip it, or:
```bash
git clone https://github.com/<your-username>/job-alerts.git
cd job-alerts
```

Create your secrets file from the template:
```powershell
copy .env.example .env          # Windows
```
```bash
cp .env.example .env            # Linux / macOS
```
`.env` holds 4 values. You'll fill them in the next steps:

| Variable | Where it comes from |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Step 2A |
| `TELEGRAM_CHAT_ID` | Step 2C |
| `SHEET_ID` | Step 3D |
| `GOOGLE_SA_FILE` | leave as `service_account.json` |

---

## Step 2: Create a Telegram bot (token + chat ID)

### 2A. Create the bot and get the token
1. Open Telegram (phone app, desktop app, or https://web.telegram.org).
2. Search for **@BotFather** and open it (blue verified tick).
3. Press **START**, then send `/newbot`.
4. **Name**: anything, e.g. `Job Alerts`.
5. **Username**: must be unique and end in `bot`, e.g. `my_job_alerts_4821_bot`.
   If it says *"this username is already taken"*, change the numbers and try again.
6. BotFather replies *"Done! Congratulations on your new bot…"*. The line under
   *"Use this token to access the HTTP API:"* looks like `7412345678:AAH3kd9f…`. That's your **token**.
7. Put it in `.env`:
   ```
   TELEGRAM_BOT_TOKEN=7412345678:AAH3kd9f...
   ```

### 2B. Say hi to your bot
A bot can't message you until you message it first.
1. Tap the `t.me/<your_bot_username>` link in BotFather's reply.
2. Press **START** and send `hi`.

### 2C. Get your chat ID
1. Open this in a browser (put in your token):
   `https://api.telegram.org/bot<TOKEN>/getUpdates`
2. Find `"chat":{"id":123456789,` in the result. That number is your **chat ID**.
   (If you see `"result":[]`, you haven't sent `hi` yet. Do 2B, then refresh.)
3. Put it in `.env`:
   ```
   TELEGRAM_CHAT_ID=123456789
   ```

### 2D. Test it (optional)
In a browser: `https://api.telegram.org/bot<TOKEN>/sendMessage?chat_id=<CHAT_ID>&text=hello`
You should get "hello" from your bot.

---

## Step 3: Set up the Google Sheet (service account + Sheet ID)

**Why a "service account"?** The script runs unattended, sometimes on GitHub's servers, so it can't click
"Sign in with Google". A service account is a robot Google identity with its own key file. It can only open
the Sheet you explicitly share with it. It can't see your Gmail, Drive or anything else, and the key doesn't expire.

### 3A. Create a Google Cloud project
1. Go to https://console.cloud.google.com and sign in. Accept the terms if asked (free, no card needed).
2. Click the project dropdown at the top left (next to "Google Cloud") → **NEW PROJECT**.
3. Name: `job-alerts` → **CREATE**.
4. Make sure the dropdown now shows **job-alerts**.

### 3B. Enable the two APIs
1. In the top search bar type **Google Sheets API** → open it → **ENABLE**.
2. Search **Google Drive API** → open it → **ENABLE**.

### 3C. Create the service account and download its key
1. Search **Service Accounts** → open it → **+ CREATE SERVICE ACCOUNT**.
2. Name: `job-alerts-bot` → **CREATE AND CONTINUE** → skip roles → **DONE**.
3. Click the new account. **Copy its email**. It looks like
   `job-alerts-bot@job-alerts-123456.iam.gserviceaccount.com`.
4. **KEYS** tab → **ADD KEY** → **Create new key** → **JSON** → **CREATE**. A `.json` file downloads.
5. Move it into the project folder and rename it to exactly **`service_account.json`**.

> ⚠️ This file is a password. Never share it, paste it in chats, or commit it. `.gitignore` already blocks it.

### 3D. Create the Sheet and share it with the robot
1. Go to https://sheets.new and name the sheet, e.g. `Job Alerts`.
2. **Share** (top right) → paste the service account email from 3C → **Editor** → untick *Notify people* → **Share**.
3. Copy the Sheet ID from the URL, the part between `/d/` and `/edit`:
   `https://docs.google.com/spreadsheets/d/`**`1AbCdEfGh...xyz`**`/edit`
4. Put it in `.env`:
   ```
   SHEET_ID=1AbCdEfGh...xyz
   ```

The script creates these tabs on its first run:

| Tab | Contents |
|---|---|
| **`jobs`** | one row per job sent: `job_id, title, company, location, country, work_type, keyword_group, posted, url, first_seen, found_by, status`. Use **`status`** yourself (e.g. `applied`, `skip`). |
| **`rejected`** | jobs whose description didn't contain the required words, so they're not checked again |
| **`meta`** | internal state (`last_local_run`, `last_block_alert`). Don't edit. |

The default **Sheet1** tab isn't used. You can delete it.

---

## Step 4: Run it on your computer

Create a virtual environment and install the dependencies:
```powershell
python -m venv .venv                                      # Windows
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```
```bash
python3 -m venv .venv                                     # Linux / macOS
.venv/bin/python -m pip install -r requirements.txt
```

**Dry run:** searches and prints what it would send. No Telegram, no Sheet, no secrets needed.
Use it every time you change `config.toml`:
```powershell
.\.venv\Scripts\python.exe job_alerts.py --dry-run --limit 2   # Windows: first 2 countries only
```
```bash
.venv/bin/python job_alerts.py --dry-run --limit 2              # Linux / macOS
```

**Real run:** sends to Telegram and logs to the Sheet:
```powershell
.\.venv\Scripts\python.exe job_alerts.py --runner local         # Windows
```
```bash
.venv/bin/python job_alerts.py --runner local                    # Linux / macOS
```
A full run takes about 3–6 minutes (12 countries, gentle request rate). The output looks like:
```
[13:03:12] config=config.toml runner=local window=30 min locations=12
[13:03:12] search Lebanon
[13:03:24]   2 matching, 1 new, 0 rejected by description
...
[13:08:40] done: 61 matching, 14 sent, 0/24 searches failed
```
Run it again right away and it should say `0 sent` (and you'll get "No new jobs"). That shows dedupe works.

---

## Step 5: Schedule it every 30 minutes

### Windows: Task Scheduler
```powershell
.\register_task.ps1
```
(If PowerShell says scripts are disabled: `powershell -ExecutionPolicy Bypass -File .\register_task.ps1`.)

This creates a task called **LinkedInJobAlerts** that:
- runs `run_local.ps1` every 30 minutes, starting 1 minute from now
- also runs 2 minutes after you log in (i.e. right after you turn the computer on)
- **wakes the computer from sleep** to run
- runs on battery too
- skips a run if the previous one is still going

Output goes to `logs\run_YYYY-MM-DD.log`.

**Allow wake timers.** Without this, sleep blocks the task:
Control Panel → **Power Options** → **Change plan settings** → **Change advanced power settings** →
**Sleep** → **Allow wake timers** → **Enable** (both *On battery* and *Plugged in*) → OK.

Check it in **Task Scheduler** → *Task Scheduler Library* → **LinkedInJobAlerts** (*Last Run Result* `0x0` = success),
or start it now with `Start-ScheduledTask LinkedInJobAlerts`.

### Linux / macOS: cron
```bash
chmod +x install_cron.sh run_local.sh
./install_cron.sh            # adds: */30 * * * * /path/to/job-alerts/run_local.sh
crontab -l                   # check it's there
./run_local.sh               # optional: run once now, then look in logs/
```
Remove it with `./install_cron.sh --remove`. Output goes to `logs/run_YYYY-MM-DD.log`.

- **cron doesn't wake a sleeping machine.** Runs during sleep are skipped, and the cloud runner (Step 6) covers the gap.
  On Linux, use a systemd timer with `WakeSystem=true` if you need wake-from-sleep.
- **macOS**: if logs stay empty, give `/usr/sbin/cron` **Full Disk Access** (System Settings → Privacy & Security).
- Minimal Linux installs: `sudo systemctl enable --now cron` (Debian/Ubuntu) or `crond` (Fedora).

> Sleep is fine on Windows, **shutdown is not**: a shut-down computer can't run anything. That's what Step 6 is for.

---

## Step 6: Cloud backup with GitHub Actions

`.github/workflows/job_alerts.yml` runs **every hour** (on the hour, UTC) on GitHub's servers, and on demand.
If your computer ran in the last 45 minutes it exits immediately. Otherwise it searches the last
`window_minutes.cloud` minutes (60), or further back if the catch-up says so.

### 6A. Create the repo
1. Sign up or log in at https://github.com.
2. **+** (top right) → **New repository** → name `job-alerts`.
3. **Public** = unlimited free Actions minutes. **Private** = 2,000 free minutes/month. At 24 runs/day, skipped runs
   cost ~1 min each (GitHub rounds up), full runs ~5–7 min, so a private repo will run out if your computer is off
   much of the time (then use every 3 h: `"0 */3 * * *"`). Public is recommended, and safe: your secrets live in
   GitHub Secrets, not in the code.
4. Leave *Add README / .gitignore / license* **unticked** → **Create repository**.

### 6B. Upload the code
**Option 1: git (recommended).** Install Git (Windows: https://git-scm.com/download/win · Debian/Ubuntu:
`sudo apt install git` · macOS: `xcode-select --install`), then in the project folder:
```bash
git init
git add .
git status          # check: .env, service_account.json, .venv and logs must NOT be listed
git commit -m "Job alerts"
git branch -M main
git remote add origin https://github.com/<your-username>/job-alerts.git
git push -u origin main
```
(The first push opens a browser window to sign in to GitHub.)

**Option 2: browser upload.** In the empty repo click **uploading an existing file** and drag in:
`job_alerts.py`, `config.toml`, `requirements.txt`, `README.md`, `.gitignore`, `.gitattributes`, `.env.example`,
`run_local.ps1`, `register_task.ps1`, `run_local.sh`, `install_cron.sh` and the **`.github`** folder → **Commit changes**.
⚠️ Do **not** upload `.env`, `service_account.json`, `.venv` or `logs`.

### 6C. Add the 4 secrets
Repo → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**, four times:

| Name | Value |
|---|---|
| `TELEGRAM_BOT_TOKEN` | same as in `.env` |
| `TELEGRAM_CHAT_ID` | same as in `.env` |
| `SHEET_ID` | same as in `.env` |
| `GOOGLE_SA_JSON` | open `service_account.json` in a text editor, copy **everything** from `{` to `}`, paste |

Secrets are encrypted and hidden in logs, even on a public repo.

With the GitHub CLI (https://cli.github.com, then `gh auth login`) you can set them from the terminal instead.
`gh secret set NAME` with no value prompts you to paste it, which keeps it out of your shell history:
```bash
gh secret set TELEGRAM_BOT_TOKEN
gh secret set TELEGRAM_CHAT_ID
gh secret set SHEET_ID
gh secret set GOOGLE_SA_JSON < service_account.json
```
(Windows PowerShell, last line: `Get-Content service_account.json -Raw | gh secret set GOOGLE_SA_JSON`.)

### 6D. Test the workflow
Repo → **Actions** tab → (enable workflows if asked) → **job-alerts** → **Run workflow**.
Open the run → **run** job → expand *Run python job_alerts.py*:
- `laptop ran at HH:MM UTC; skipping cloud run`: works (your computer ran recently).
- `search <country>` lines ending in `done: N matching, N sent`: works (full cloud run).
- `HTTP 429` on most countries: LinkedIn is limiting GitHub's servers. Your computer's runner still covers you.

> GitHub pauses scheduled workflows in **public** repos after 60 days without commits. You'll get an email.
> Re-enable with one click (Actions → job-alerts → Enable workflow) or make any small commit.
> Scheduled runs can also start 5–20 minutes late. The cloud window covers that.

---

## Configuration (`config.toml`)

**Everything about what gets searched, filtered and sent lives in [`config.toml`](config.toml).**
The code never needs editing. After any change, test with `--dry-run --limit 2`.

TOML basics: `key = value`, text in quotes, lists in `[ ]`, comments start with `#`.
`[section]` is a group of settings, and `[[name]]` repeated is a list of items (one block per role group / country).

### `[search]`: what to ask LinkedIn for

| Variable | Type | Default | What it does |
|---|---|---|---|
| `keywords` | text | | Sent to LinkedIn's search box as-is. Use `OR` between terms and quotes for phrases: `'AI OR python OR "software engineer"'`. **Keep it short** (a handful of words / short phrases): long lists of quoted phrases make LinkedIn return a stale, unchanging result set. Cast a wide net here; the filters below do the precise work. |
| `remote_pass` | true/false | `true` | Also run a remote-only search per country. Jobs found there are tagged **🌍 Remote**. `false` halves the number of requests. |
| `remote_only` | true/false | `false` | `true` = **only** remote jobs. Skips the normal search, so `remote_pass` is ignored. |
| `max_pages` | number | `3` | Result pages per country, 10 jobs each. Override per country in `[[locations]]`. |

### `[window_minutes]`: how far back to look

| Variable | Default | What it does |
|---|---|---|
| `local` | `30` | Search window for runs on your computer. **Match it to the schedule** (every 30 min → 30). Make it a bit bigger (e.g. 40) if you want overlap in case a run starts late; dedupe stops repeats. |
| `cloud` | `60` | Search window for GitHub Actions runs (every hour). |
| `catch_up` | `true` | If the last complete run (either side) was longer ago than the window, search back to it instead. Prevents gaps when switching between computer and cloud, or after a night off. |
| `catch_up_overlap` | `5` | Extra minutes added to the catch-up window, for late starts. |
| `max` | `1440` | Never search further back than this many minutes (24 h). |

### `[filters]`: title rules applied to every job

| Variable | Type | What it does |
|---|---|---|
| `title_exclude` | list of words | If the title contains **any** of these (whole word/phrase, case-insensitive), the job is dropped. Checked first. Example: `["intern", "sales", "manager", "java"]`. `"java"` does **not** match "JavaScript". |
| `title_require_any` | list of words | The title must contain **at least one** of these, e.g. `["engineer", "developer"]` drops "AI Specialist" and "Head of AI". Use `[]` to turn this check off. |

### `[[groups]]`: which roles you want (one block per role)

Each title is checked against the groups **top to bottom**. The **first** group with a matching `title_terms` word wins,
and its `name` appears in the Telegram message and the Sheet. Titles that match **no** group are dropped.

| Variable | Required | What it does |
|---|---|---|
| `name` | yes | Label shown in Telegram and in the Sheet's `keyword_group` column. |
| `title_terms` | yes | Words/phrases to look for in the title (whole word, case-insensitive). `"ai"` matches "AI Engineer" and "AI/ML Engineer" but not "Email" or "Maintenance". |
| `description_terms` | no | If set, a job in this group is only kept if its **full job description** contains one of these words. Use it for generic titles: "Software Engineer" → keep only if the description mentions `python`. Costs one extra LinkedIn request per job. |

Default groups:
```toml
[[groups]]
name = "AI"                         # AI Engineer, LLM Engineer, ML Engineer, Agentic...
title_terms = ["ai", "llm", "machine learning", "ml", ...]

[[groups]]
name = "Python"                     # Python Developer, Django Engineer...
title_terms = ["python", "django", "fastapi", "flask"]

[[groups]]
name = "Software/Backend + Python"  # Software/Backend Engineer, only if the description says Python
title_terms = ["software engineer", "backend", "full stack", ...]
description_terms = ["python", "django", "fastapi", "flask"]
```

### `[description_check]`

| Variable | Default | What it does |
|---|---|---|
| `limit_per_run` | `25` | Max job descriptions opened per run (all countries together). Jobs over the limit aren't lost: they're checked on the next run. Lower it if you see many `HTTP 429`. |

### `[[locations]]`: which countries (one block per country)

Countries are searched (and their Telegram messages sent) **in the order listed**.

| Variable | Required | What it does |
|---|---|---|
| `name` | yes | Shown in Telegram and in the Sheet's `country` column. Any text. |
| `geo_id` | yes | LinkedIn's numeric location ID. Text names are ambiguous ("Lebanon" also matches Lebanon, Pennsylvania), so IDs are used. [How to find one](#add-or-remove-a-country). |
| `flag` | no | Emoji shown before the country name in Telegram (default 📍). |
| `max_pages` | no | Overrides `[search] max_pages` for this country. Give big markets more (US/UK use 6). |

Included geo IDs:

| Country | geo_id | | Country | geo_id |
|---|---|---|---|---|
| Lebanon | `101834488` | | Jordan | `103710677` |
| United Arab Emirates | `104305776` | | Egypt | `106155005` |
| Qatar | `104170880` | | Turkey | `102105699` |
| Saudi Arabia | `100459316` | | United Kingdom | `101165590` |
| Kuwait | `103239229` | | United States | `103644278` |
| Bahrain | `100425729` | | Oman | `103619019` |

### `[notify]`

| Variable | Default | What it does |
|---|---|---|
| `when_empty` | `true` | Send "No new jobs" when a whole run finds nothing new. `false` = stay quiet (silence then means "nothing new" **or** "didn't run": check the logs). |

### `[runtime]`: politeness and timing

| Variable | Default | What it does |
|---|---|---|
| `sleep_seconds` | `[4, 8]` | Random pause (seconds) between LinkedIn requests. Increase it if you get `HTTP 429` often. |
| `rate_limit_backoff_seconds` | `90` | Wait after a 429 before retrying once. A second 429 ends the run early. |
| `local_heartbeat_minutes` | `45` | The cloud run skips itself if your computer ran within this many minutes. Keep it a bit above your local schedule. |
| `block_alert_cooldown_hours` | `6` | If LinkedIn blocks every search, you get a ⚠️ Telegram warning at most once per this many hours. |

---

## Common changes (recipes)

### Change the job titles / roles
Edit the `[[groups]]` blocks (and widen `[search] keywords` so LinkedIn returns those jobs at all).
For example, to track **frontend** instead:
```toml
[search]
keywords = 'frontend OR react OR "front end" OR vue OR angular OR typescript'

[filters]
title_require_any = ["engineer", "developer"]
title_exclude = ["intern", "sales", "manager", "backend", "devops", "ios", "android"]

[[groups]]
name = "React"
title_terms = ["react", "next.js"]

[[groups]]
name = "Frontend"
title_terms = ["frontend", "front-end", "front end", "vue", "angular", "web developer"]

[[groups]]
name = "Full stack + React"
title_terms = ["full stack", "software engineer"]
description_terms = ["react"]
```
Or **DevOps**:
```toml
[search]
keywords = 'devops OR SRE OR "site reliability" OR kubernetes OR "platform engineer"'

[filters]
title_require_any = ["engineer", "architect", "sre"]
title_exclude = ["intern", "sales", "manager", "frontend"]

[[groups]]
name = "DevOps / SRE"
title_terms = ["devops", "sre", "site reliability"]

[[groups]]
name = "Platform / Cloud"
title_terms = ["platform engineer", "cloud engineer", "infrastructure", "kubernetes"]
```
⚠️ Check `title_exclude` when switching roles. The default list excludes `frontend`, `devops`, `react`, etc.,
which you'd want to remove for those roles.

### Stop a type of job from appearing
Add a word to `title_exclude`, e.g. `"senior"`, `"lead"`, `"principal"` to see only junior/mid roles, or `"clearance"` to skip
US security-clearance jobs.

### Only junior / only senior
- Junior only: add `"senior", "staff", "principal", "lead", "head"` to `title_exclude`.
- Senior only: add `"senior"`, `"staff"`, `"lead"` to `title_require_any`. Note this then *replaces* the engineer/developer check.

### Add or remove a country
Remove: delete its `[[locations]]` block. Add:
1. Open https://www.linkedin.com/jobs/search, type the country (or city) into the location box, search.
2. Copy the `geoId=` number from the browser address bar.
3. Add a block:
   ```toml
   [[locations]]
   name = "Germany"
   geo_id = "101282230"   # the number you copied
   flag = "🇩🇪"
   ```
4. Test with `--dry-run`. Each country costs 1–2+ requests per run, so keep the list reasonable to avoid LinkedIn 429s.

Cities work too (e.g. the geoId for "Dubai" or "London"), as does LinkedIn's "Worldwide" location.

### Only remote jobs
```toml
[search]
remote_only = true
```
Every country is then searched with LinkedIn's "Remote" filter only. To get remote jobs from the US/UK but every kind
from the Middle East, keep `remote_only = false` and use two config files (see *Several profiles* below).

### Change how often it runs
- Windows: edit `-Minutes 30` in `register_task.ps1` and run it again.
- Linux/macOS: edit `*/30` in `install_cron.sh` and run it again.
- Cloud: edit `cron: "0 * * * *"` in `.github/workflows/job_alerts.yml` (times are UTC). Every 2 h = `"0 */2 * * *"`.
- Then update `[window_minutes]` to match.

### Several profiles (e.g. you + a friend, or backend + frontend)
Copy `config.toml` to `frontend.toml`, edit it, and run with `--config frontend.toml`. Use a different `.env`/Sheet per person,
or share one Sheet. Dedupe works across profiles either way.

---

## Environment variables & command-line options

**`.env` (local) / GitHub Secrets (cloud)**

| Variable | Required | What it is |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | yes | from @BotFather (Step 2A) |
| `TELEGRAM_CHAT_ID` | yes | your chat ID (Step 2C) |
| `SHEET_ID` | yes | from the Sheet URL (Step 3D) |
| `GOOGLE_SA_FILE` | local | path to the service-account key, default `service_account.json` |
| `GOOGLE_SA_JSON` | cloud | the key file's **contents** (used instead of `GOOGLE_SA_FILE` when set) |
| `JOB_ALERTS_CONFIG` | no | path to a config file, default `config.toml` |

**Command line**

| Option | What it does |
|---|---|
| `--runner local` / `--runner cloud` | which window to use; `cloud` also skips itself if your computer ran recently. Default `local`. |
| `--dry-run` | search and print only. No Telegram, no Sheet, no secrets needed. |
| `--limit N` | only search the first N countries (for testing). |
| `--config FILE` | use another config file. |

---

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| No Telegram messages at all | With `when_empty = true` every run sends something, so silence means it didn't run or crashed. Check `logs/`, Task Scheduler history, or the Actions run log. |
| `chat not found` from Telegram | You haven't sent `hi` to your bot, or the chat ID is wrong. Redo Step 2B–2C. |
| `401 Unauthorized` from Telegram | Wrong token. Copy it again from BotFather (`/mybots` → your bot → *API Token*). |
| `waiting for network...` then `giving up` | No internet, or Telegram unreachable. The script already falls back to Cloudflare DNS if your router's DNS fails. |
| `SpreadsheetNotFound` / `PermissionError` | The Sheet isn't shared with the service account email, or `SHEET_ID` is wrong. |
| `APIError: ... has not been used in project` | Sheets API or Drive API not enabled (Step 3B). |
| `FileNotFoundError: service_account.json` | The key file isn't in the project folder or isn't named exactly `service_account.json`. |
| `no [[locations]] defined` / TOML error | Syntax error in `config.toml`. The error shows the line. Check quotes and brackets. |
| Sheet looks empty | You're on `Sheet1`. Click the **jobs** tab at the bottom. |
| Same jobs keep showing in `--dry-run` | Normal: dry runs don't record anything. |
| `HTTP 429` in logs | LinkedIn rate limit. The script backs off automatically. If frequent: raise `sleep_seconds`, lower `max_pages` / `limit_per_run`, or remove countries. |
| ⚠️ *"LinkedIn blocked every search"* | Every search was refused this run. It usually clears on its own. Sent at most once per `block_alert_cooldown_hours`. |
| `0 matching` everywhere, all the time | Check `keywords` isn't too long. If it's short and still 0, LinkedIn may have changed its HTML (`parse_cards` in `job_alerts.py`). |
| Wanted jobs are missing | Run `--dry-run` and look at the titles. Usually a `title_exclude` word or no matching `title_terms`. |
| Wrong-country jobs | Use `geo_id`, not text locations. |
| Task never runs while asleep (Windows) | Enable wake timers (Step 5). Check Task Scheduler history. |
| `bad interpreter: /usr/bin/env: 'bash\r'` | `.sh` got Windows line endings: `sed -i 's/\r$//' *.sh` (macOS: `sed -i '' 's/\r$//' *.sh`). |
| `Permission denied: ./run_local.sh` | `chmod +x run_local.sh install_cron.sh` |
| `No module named venv` (Debian/Ubuntu) | `sudo apt install python3-venv` |

---

## Security notes
- `.env` and `service_account.json` hold your secrets. Both (and all `*.json`) are in `.gitignore`.
  Always check `git status` before committing.
- If a secret leaks:
  - Telegram: BotFather → `/revoke` → pick the bot → put the new token in `.env` and the GitHub secret.
  - Google: Cloud Console → Service Accounts → your account → **KEYS** → delete the key → create a new one.
- The service account can only access Sheets you share with it.
- Error messages never include the Telegram token.
- The script only reads LinkedIn's public search pages. No login, no cookies, no applying. Scraping is still against
  LinkedIn's terms, so keep the request rate gentle, as configured.

---

## Stopping / uninstalling
- Windows: `Unregister-ScheduledTask LinkedInJobAlerts -Confirm:$false`
- Linux/macOS: `./install_cron.sh --remove`
- Cloud: repo → **Actions** → **job-alerts** → **⋯** → **Disable workflow**
- Telegram: BotFather → `/deletebot`
- Google: delete the service account / project in the Cloud Console.
