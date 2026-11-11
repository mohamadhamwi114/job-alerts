import argparse
import html
import json
import os
import random
import re
import socket
import sys
import time
from datetime import datetime, timedelta, timezone

import requests
from bs4 import BeautifulSoup

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib

HERE = os.path.dirname(os.path.abspath(__file__))
SEARCH_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
DESCRIPTION_URL = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{}"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}
JOBS_HEADER = [
    "job_id", "title", "company", "location", "country", "work_type", "keyword_group",
    "posted", "url", "first_seen", "found_by", "status",
]
TG_LIMIT = 4000


def now_utc():
    return datetime.now(timezone.utc)


def stamp():
    return now_utc().isoformat(timespec="seconds")


def log(msg):
    print(f"[{now_utc():%H:%M:%S}] {msg}", flush=True)


# ---------- config ----------

def load_config(path):
    with open(path, "rb") as f:
        cfg = tomllib.load(f)
    if not cfg.get("locations"):
        sys.exit(f"{path}: no [[locations]] defined")
    if not cfg.get("groups"):
        sys.exit(f"{path}: no [[groups]] defined")
    flt = cfg.setdefault("filters", {})
    flt["title_require_any"] = [t.lower() for t in flt.get("title_require_any", [])]
    flt["title_exclude"] = [t.lower().strip() for t in flt.get("title_exclude", [])]
    for g in cfg["groups"]:
        g["title_terms"] = [t.lower() for t in g["title_terms"]]
        g["description_terms"] = [t.lower() for t in g.get("description_terms", [])]
    return cfg


# ---------- network ----------

def _install_dns_fallback():
    """Some routers/hotspots time out resolving api.telegram.org; fall back to Cloudflare DNS-over-HTTPS by IP."""
    original = socket.getaddrinfo
    cache = {}

    def getaddrinfo(host, *args, **kwargs):
        try:
            return original(host, *args, **kwargs)
        except socket.gaierror:
            if not isinstance(host, str) or host in ("1.1.1.1", "1.0.0.1"):
                raise
            if host not in cache:
                try:
                    r = requests.get("https://1.1.1.1/dns-query", params={"name": host, "type": "A"},
                                     headers={"accept": "application/dns-json"}, timeout=10)
                    ips = [a["data"] for a in r.json().get("Answer", []) if a.get("type") == 1]
                except (requests.RequestException, ValueError):
                    ips = []
                if not ips:
                    raise
                cache[host] = ips[0]
            return original(cache[host], *args, **kwargs)

    socket.getaddrinfo = getaddrinfo


_install_dns_fallback()


def wait_for_network(timeout=120):
    """After wake-from-sleep, Wi-Fi can take a while to come back."""
    deadline = time.time() + timeout
    while True:
        try:
            socket.create_connection(("api.telegram.org", 443), timeout=5).close()
            return
        except OSError:
            if time.time() > deadline:
                log("no network after waiting; giving up this run")
                sys.exit(1)
            log("waiting for network...")
            time.sleep(10)


# ---------- LinkedIn ----------

class RateLimited(Exception):
    pass


class LinkedIn:
    def __init__(self, cfg):
        self.cfg = cfg
        self.session = requests.Session()
        rt = cfg.get("runtime", {})
        self.sleep_range = tuple(rt.get("sleep_seconds", [4, 8]))
        self.backoff = rt.get("rate_limit_backoff_seconds", 90)

    def _get(self, url, params=None):
        """Response on 200, None on other failures, RateLimited if 429 persists after one back-off."""
        for attempt in range(2):
            try:
                r = self.session.get(url, params=params, headers=HEADERS, timeout=30)
            except requests.RequestException as e:
                log(f"  request error: {type(e).__name__}")
                return None
            finally:
                time.sleep(random.uniform(*self.sleep_range))
            if r.status_code == 200:
                return r
            if r.status_code in (429, 999):
                if attempt == 0:
                    log(f"  HTTP {r.status_code}, backing off {self.backoff}s")
                    time.sleep(self.backoff)
                    continue
                raise RateLimited()
            log(f"  HTTP {r.status_code}")
            return None

    def search(self, location, window_s, remote):
        """Returns (cards, ok)."""
        found = []
        pages = location.get("max_pages", self.cfg["search"].get("max_pages", 3))
        if remote and not self.cfg["search"].get("remote_only", False):
            pages = 1  # the normal pass already covers these; this pass only tags remote ones
        for page in range(pages):
            params = {"keywords": self.cfg["search"]["keywords"], "geoId": location["geo_id"],
                      "f_TPR": f"r{window_s}", "start": page * 10}
            if remote:
                params["f_WT"] = "2"
            r = self._get(SEARCH_URL, params)
            if r is None:
                return found, page > 0
            cards = parse_cards(r.text)
            found.extend(cards)
            if len(cards) < 10:
                break
        return found, True

    def description(self, job_id):
        """Lower-cased description text, or None if it couldn't be fetched."""
        r = self._get(DESCRIPTION_URL.format(job_id))
        if r is None:
            return None
        soup = BeautifulSoup(r.text, "html.parser")
        d = soup.select_one("div.show-more-less-html__markup") or soup.select_one("div.description__text")
        return f" {d.get_text(' ', strip=True).lower()} " if d else None


def parse_cards(page_html):
    soup = BeautifulSoup(page_html, "html.parser")
    jobs = []
    for card in soup.select("div.base-card"):
        m = re.search(r"(\d+)$", card.get("data-entity-urn", ""))
        if not m:
            continue
        job_id = m.group(1)
        title = card.select_one("h3.base-search-card__title")
        company = card.select_one("h4.base-search-card__subtitle")
        location = card.select_one("span.job-search-card__location")
        posted = card.select_one("time")
        jobs.append({
            "job_id": job_id,
            "title": title.get_text(strip=True) if title else "",
            "company": company.get_text(strip=True) if company else "",
            "location": location.get_text(strip=True) if location else "",
            "posted": posted.get("datetime", "") if posted else "",
            "url": f"https://www.linkedin.com/jobs/view/{job_id}",
        })
    return jobs


# ---------- filtering ----------

def has_term(text, term):
    return re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", text) is not None


def match_group(cfg, title):
    t = f" {title.lower()} "
    flt = cfg["filters"]
    if any(has_term(t, x) for x in flt["title_exclude"]):
        return None
    if flt["title_require_any"] and not any(has_term(t, w) for w in flt["title_require_any"]):
        return None
    for g in cfg["groups"]:
        if any(has_term(t, term) for term in g["title_terms"]):
            return g
    return None


def search_location(li, cfg, location, window_s):
    """Normal + remote pass for one location. Returns ({job_id: job}, attempts, failures)."""
    jobs, attempts, failures = {}, 0, 0
    if cfg["search"].get("remote_only", False):
        passes = [True]
    else:
        passes = [False, True] if cfg["search"].get("remote_pass", True) else [False]
    for remote in passes:
        attempts += 1
        cards, ok = li.search(location, window_s, remote)
        failures += not ok
        for j in cards:
            if j["job_id"] in jobs:
                if remote:
                    jobs[j["job_id"]]["work_type"] = "Remote"
                continue
            group = match_group(cfg, j["title"])
            if not group:
                continue
            j["country"] = location["name"]
            j["group"] = group
            j["work_type"] = "Remote" if remote or "remote" in j["location"].lower() else "On-site/Hybrid"
            jobs[j["job_id"]] = j
    return jobs, attempts, failures


def description_filter(li, jobs, budget):
    """Applies group description_terms. Returns (kept, rejected). Jobs over budget or failing to fetch are
    left out of both, so they're retried next run. budget is a one-item list, shared across locations."""
    kept, rejected = [], []
    for j in jobs:
        terms = j["group"]["description_terms"]
        if not terms:
            kept.append(j)
            continue
        if budget[0] <= 0:
            continue
        budget[0] -= 1
        text = li.description(j["job_id"])
        if text is None:
            continue
        (kept if any(has_term(text, t) for t in terms) else rejected).append(j)
    return kept, rejected


# ---------- Google Sheet ----------

def open_sheet():
    import gspread

    raw = os.environ.get("GOOGLE_SA_JSON")
    if raw:
        gc = gspread.service_account_from_dict(json.loads(raw))
    else:
        key = os.environ.get("GOOGLE_SA_FILE", "service_account.json")
        gc = gspread.service_account(filename=key if os.path.isabs(key) else os.path.join(HERE, key))
    sh = gc.open_by_key(os.environ["SHEET_ID"])
    titles = [w.title for w in sh.worksheets()]
    if "jobs" not in titles:
        sh.add_worksheet("jobs", rows=1000, cols=len(JOBS_HEADER)).append_row(JOBS_HEADER)
    if "meta" not in titles:
        sh.add_worksheet("meta", rows=20, cols=2)
    if "rejected" not in titles:
        sh.add_worksheet("rejected", rows=1000, cols=3).append_row(["job_id", "title", "checked_at"])
    return sh


def meta_get(sh, key):
    for row in sh.worksheet("meta").get_all_values():
        if row and row[0] == key:
            return row[1] if len(row) > 1 else ""
    return ""


def meta_set(sh, key, value):
    ws = sh.worksheet("meta")
    for i, row in enumerate(ws.get_all_values(), start=1):
        if row and row[0] == key:
            ws.update_cell(i, 2, value)
            return
    ws.append_row([key, value])


def parse_iso(s):
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


# ---------- Telegram ----------

class TelegramError(Exception):
    pass


def tg_send(text, attempts=3):
    url = f"https://api.telegram.org/bot{os.environ['TELEGRAM_BOT_TOKEN']}/sendMessage"
    payload = {
        "chat_id": os.environ["TELEGRAM_CHAT_ID"],
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    # Errors are re-raised without the URL, which contains the bot token.
    for i in range(attempts):
        try:
            r = requests.post(url, json=payload, timeout=30)
        except requests.RequestException as e:
            err = f"network error ({type(e).__name__})"
        else:
            if r.ok:
                return
            err = f"HTTP {r.status_code}: {r.text[:200]}"
            if r.status_code < 500 and r.status_code != 429:
                break
        log(f"  telegram {err}; attempt {i + 1}/{attempts}")
        if i < attempts - 1:
            time.sleep(15)
    raise TelegramError(err) from None


def country_messages(location, jobs, window_min):
    e = html.escape
    head = f"{location.get('flag', '📍')} <b>{e(location['name'])}</b> · {len(jobs)} new (last {window_min} min)"
    blocks = [head + "\n━━━━━━━━━━━━━━━"]
    for j in sorted(jobs, key=lambda x: (x["work_type"] != "Remote", x["group"]["name"])):
        tag = "🌍 Remote" if j["work_type"] == "Remote" else "🏢 On-site/Hybrid"
        blocks.append(
            f"<a href=\"{j['url']}\">{e(j['title'])}</a>\n"
            f"{e(j['company'])} · {e(j['location'])}\n"
            f"{tag} · {e(j['group']['name'])}"
        )
    messages, buf = [], ""
    for b in blocks:
        if buf and len(buf) + len(b) + 2 > TG_LIMIT:
            messages.append(buf)
            buf = ""
        buf += b + "\n\n"
    if buf:
        messages.append(buf)
    return messages


# ---------- main ----------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runner", choices=["local", "cloud"], default="local")
    ap.add_argument("--config", default=os.environ.get("JOB_ALERTS_CONFIG", os.path.join(HERE, "config.toml")))
    ap.add_argument("--dry-run", action="store_true", help="search and print only; no Sheet, no Telegram")
    ap.add_argument("--limit", type=int, help="only search the first N locations (testing)")
    args = ap.parse_args()

    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(HERE, ".env"))
    except ImportError:
        pass

    cfg = load_config(args.config)
    run_start = now_utc()
    wcfg = cfg.get("window_minutes", {})
    window_min = wcfg.get(args.runner, 30 if args.runner == "local" else 90)
    locations = cfg["locations"][: args.limit] if args.limit else cfg["locations"]
    rt = cfg.get("runtime", {})

    sh = jobs_ws = rejected_ws = None
    seen = set()
    if not args.dry_run:
        wait_for_network()
        sh = open_sheet()
        if args.runner == "cloud":
            last_local = parse_iso(meta_get(sh, "last_local_run"))
            if last_local and now_utc() - last_local < timedelta(minutes=rt.get("local_heartbeat_minutes", 45)):
                log(f"laptop ran at {last_local:%H:%M} UTC; skipping cloud run")
                return
        else:
            meta_set(sh, "last_local_run", stamp())
        jobs_ws, rejected_ws = sh.worksheet("jobs"), sh.worksheet("rejected")
        seen = set(jobs_ws.col_values(1)[1:]) | set(rejected_ws.col_values(1)[1:])

        # Catch-up: cover everything since the last complete run by either runner.
        last_run = parse_iso(meta_get(sh, "last_run")) if wcfg.get("catch_up", True) else None
        if last_run:
            gap = int((run_start - last_run).total_seconds() // 60) + wcfg.get("catch_up_overlap", 5)
            if gap > window_min:
                window_min = min(gap, wcfg.get("max", 1440))
                log(f"last complete run {last_run:%Y-%m-%d %H:%M} UTC; catching up {window_min} min")

    window_s = window_min * 60
    log(f"config={os.path.basename(args.config)} runner={args.runner} window={window_min} min "
        f"locations={len(locations)}")
    li = LinkedIn(cfg)
    budget = [cfg.get("description_check", {}).get("limit_per_run", 25)]
    attempts = failures = total_matched = total_sent = 0
    complete = True

    for idx, loc in enumerate(locations):
        log(f"search {loc['name']}")
        try:
            found, a, f = search_location(li, cfg, loc, window_s)
        except RateLimited:
            log("  rate-limited twice; stopping this run early")
            remaining = len(locations) - idx
            attempts += remaining
            failures += remaining
            complete = False
            break
        attempts += a
        failures += f
        total_matched += len(found)
        new = [j for j in found.values() if j["job_id"] not in seen]
        try:
            new, rejected = description_filter(li, new, budget)
        except RateLimited:
            log("  rate-limited during description checks; sending what's confirmed")
            new, rejected = [j for j in new if not j["group"]["description_terms"]], []
        seen.update(j["job_id"] for j in new + rejected)
        log(f"  {len(found)} matching, {len(new)} new, {len(rejected)} rejected by description")

        if args.dry_run:
            for j in rejected:
                print(f"    x {j['title']} | {j['company']}")
            for j in new:
                print(f"    + [{j['work_type']}] [{j['group']['name']}] {j['title']} | {j['company']} | {j['url']}")
            continue

        if rejected:
            rejected_ws.append_rows([[j["job_id"], j["title"], stamp()] for j in rejected], value_input_option="RAW")
        if new:
            for msg in country_messages(loc, new, window_min):
                tg_send(msg)
            jobs_ws.append_rows(
                [[j["job_id"], j["title"], j["company"], j["location"], j["country"], j["work_type"],
                  j["group"]["name"], j["posted"], j["url"], stamp(), args.runner, ""] for j in new],
                value_input_option="RAW",
            )
            total_sent += len(new)

    log(f"done: {total_matched} matching, {total_sent} sent, {failures}/{attempts} searches failed")
    if args.dry_run:
        return

    # Only a complete run moves the catch-up point; otherwise the next run re-covers this window.
    if complete and failures < attempts:
        meta_set(sh, "last_run", run_start.isoformat(timespec="seconds"))

    if attempts and failures == attempts:
        last_alert = parse_iso(meta_get(sh, "last_block_alert"))
        if not last_alert or now_utc() - last_alert > timedelta(hours=rt.get("block_alert_cooldown_hours", 6)):
            tg_send(f"⚠️ LinkedIn blocked every search in the {args.runner} run.")
            meta_set(sh, "last_block_alert", stamp())
        sys.exit(1)

    if total_sent == 0 and cfg.get("notify", {}).get("when_empty", True):
        tg_send(f"No new jobs ({args.runner}, last {window_min} min, {total_matched} matching already seen).")


if __name__ == "__main__":
    main()
