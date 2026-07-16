"""
Chief of Staff job tracker — scraper.

Pulls public job-board APIs (Greenhouse, Lever, Ashby) for the companies
listed in companies.json, keeps every listing whose title matches the
configured keywords, and maintains a persistent history in data/jobs.json.

Listings that disappear from a board are marked "closed" (kept for history),
never deleted. New listings get a first_seen timestamp, which the dashboard
uses to badge them as NEW. A board that errors out is skipped for the run and
its jobs are NOT marked closed (a network hiccup shouldn't close listings).
"""

import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import requests

from screen import screen_new_jobs, strip_html

ROOT = Path(__file__).parent
CONFIG_PATH = ROOT / "companies.json"
DATA_PATH = ROOT / "data" / "jobs.json"

TIMEOUT = 20
HEADERS = {"User-Agent": "cos-job-tracker (personal job search tool)"}


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def title_matches(title: str, keywords: list[str]) -> bool:
    t = (title or "").lower()
    return any(kw.lower() in t for kw in keywords)


def job_id(source: str, slug: str, url: str) -> str:
    return hashlib.sha1(f"{source}|{slug}|{url}".encode()).hexdigest()[:16]


def fetch_json(url: str):
    resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------- fetchers
# Each fetcher yields dicts: {slug, company, title, location, url, source}

def fetch_greenhouse(slug: str, name: str):
    data = fetch_json(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true")
    for job in data.get("jobs", []):
        yield {
            "slug": slug,
            "company": name,
            "title": job.get("title", ""),
            "location": (job.get("location") or {}).get("name", ""),
            "url": job.get("absolute_url", ""),
            "source": "greenhouse",
            "description": strip_html(job.get("content", "")),
        }


def fetch_lever(slug: str, name: str):
    data = fetch_json(f"https://api.lever.co/v0/postings/{slug}?mode=json")
    for job in data:
        yield {
            "slug": slug,
            "company": name,
            "title": job.get("text", ""),
            "location": (job.get("categories") or {}).get("location", ""),
            "url": job.get("hostedUrl", ""),
            "source": "lever",
            "description": job.get("descriptionPlain") or strip_html(job.get("description", "")),
        }


def fetch_ashby(slug: str, name: str):
    data = fetch_json(f"https://api.ashbyhq.com/posting-api/job-board/{slug}")
    for job in data.get("jobs", []):
        yield {
            "slug": slug,
            "company": name,
            "title": job.get("title", ""),
            "location": job.get("location", ""),
            "url": job.get("jobUrl", "") or job.get("applyUrl", ""),
            "source": "ashby",
            "description": job.get("descriptionPlain") or strip_html(job.get("descriptionHtml", "")),
        }


FETCHERS = {
    "greenhouse": fetch_greenhouse,
    "lever": fetch_lever,
    "ashby": fetch_ashby,
}


# ------------------------------------------------- catch-all search source

ADZUNA_COUNTRY = os.environ.get("ADZUNA_COUNTRY", "us")
ADZUNA_MAX_PAGES = 3  # up to 150 results per keyword


def fetch_adzuna(keywords: list[str]):
    """Phrase-search the whole job market via Adzuna's free API.

    Returns a list of listings, or None if API keys aren't configured
    (None tells the caller not to treat missing adzuna jobs as closed).
    """
    app_id = os.environ.get("ADZUNA_APP_ID")
    app_key = os.environ.get("ADZUNA_APP_KEY")
    if not (app_id and app_key):
        print("adzuna: ADZUNA_APP_ID/ADZUNA_APP_KEY not set, skipping catch-all search")
        return None

    results = []
    for kw in keywords:
        for page in range(1, ADZUNA_MAX_PAGES + 1):
            data = fetch_json(
                f"https://api.adzuna.com/v1/api/jobs/{ADZUNA_COUNTRY}/search/{page}"
                f"?app_id={app_id}&app_key={app_key}"
                f"&results_per_page=50&sort_by=date&what_phrase={quote(kw)}"
            )
            batch = data.get("results", [])
            for job in batch:
                results.append({
                    "slug": "adzuna",
                    "company": (job.get("company") or {}).get("display_name") or "Unknown",
                    "title": strip_html(job.get("title", "")),
                    "location": (job.get("location") or {}).get("display_name", ""),
                    "url": job.get("redirect_url", ""),
                    "source": "adzuna",
                    "description": strip_html(job.get("description", "")),
                })
            if len(batch) < 50:
                break
            time.sleep(0.5)
    return results


# ---------------------------------------------------------------- pipeline

def load_config() -> dict:
    return json.loads(CONFIG_PATH.read_text())


def load_store() -> dict:
    if DATA_PATH.exists():
        try:
            return json.loads(DATA_PATH.read_text())
        except json.JSONDecodeError:
            print("! data/jobs.json is corrupt; starting fresh", file=sys.stderr)
    return {"jobs": {}, "last_run": None}


def main() -> int:
    config = load_config()
    keywords = config.get("title_keywords", ["chief of staff"])
    store = load_store()
    jobs = store["jobs"]
    run_time = now_iso()

    seen_ids: set[str] = set()
    descriptions: dict[str, str] = {}  # held in memory for screening, never written to disk
    errors: list[str] = []
    failed_boards: set[str] = set()
    new_count = 0

    for source, fetcher in FETCHERS.items():
        for entry in config.get(source, []):
            slug = entry["slug"]
            name = entry.get("name", slug.title())
            try:
                listings = list(fetcher(slug, name))
            except Exception as exc:  # noqa: BLE001 - keep the run alive
                errors.append(f"{source}/{slug}: {exc}")
                failed_boards.add(f"{source}/{slug}")
                continue
            finally:
                time.sleep(0.5)  # be polite to the APIs

            for listing in listings:
                if not listing["url"] or not title_matches(listing["title"], keywords):
                    continue
                jid = job_id(source, slug, listing["url"])
                seen_ids.add(jid)
                descriptions[jid] = listing.pop("description", "")
                if jid in jobs:
                    jobs[jid].update(listing)   # refresh details
                    jobs[jid]["last_seen"] = run_time
                    jobs[jid]["status"] = "active"
                    jobs[jid].pop("closed_at", None)
                else:
                    jobs[jid] = {
                        **listing,
                        "first_seen": run_time,
                        "last_seen": run_time,
                        "status": "active",
                    }
                    new_count += 1
                    print(f"NEW: {name} — {listing['title']}")

    # Catch-all search via Adzuna (optional; needs ADZUNA_APP_ID/APP_KEY secrets).
    # Skip results that duplicate a job already tracked via a direct ATS board.
    direct_keys = {
        (j["company"].strip().lower(), j["title"].strip().lower())
        for jid, j in jobs.items()
        if jid in seen_ids and j["source"] != "adzuna"
    }
    try:
        adzuna_results = fetch_adzuna(keywords)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"adzuna: {exc}")
        adzuna_results = None
    if adzuna_results is None:
        failed_boards.add("adzuna/adzuna")  # don't close adzuna jobs on a skipped/failed run
    else:
        for listing in adzuna_results:
            if not listing["url"] or not title_matches(listing["title"], keywords):
                continue
            if (listing["company"].strip().lower(), listing["title"].strip().lower()) in direct_keys:
                continue  # already tracked via its own ATS board
            jid = job_id("adzuna", "adzuna", listing["url"])
            seen_ids.add(jid)
            descriptions[jid] = listing.pop("description", "")
            if jid in jobs:
                jobs[jid].update(listing)
                jobs[jid]["last_seen"] = run_time
                jobs[jid]["status"] = "active"
                jobs[jid].pop("closed_at", None)
            else:
                jobs[jid] = {
                    **listing,
                    "first_seen": run_time,
                    "last_seen": run_time,
                    "status": "active",
                }
                new_count += 1
                print(f"NEW: {listing['company']} — {listing['title']} (adzuna)")

    # Mark vanished listings closed — unless their board failed this run.
    for jid, job in jobs.items():
        board = f"{job['source']}/{job.get('slug', job['company'])}"
        if job["status"] == "active" and jid not in seen_ids and board not in failed_boards:
            job["status"] = "closed"
            job["closed_at"] = run_time

    # LLM screening: verdicts for active jobs that don't have one yet.
    # No-op without ANTHROPIC_API_KEY; errors are logged, never fatal.
    screened = screen_new_jobs(jobs, descriptions)

    store["last_run"] = run_time
    store["errors"] = errors
    DATA_PATH.parent.mkdir(exist_ok=True)
    DATA_PATH.write_text(json.dumps(store, indent=2, sort_keys=True))

    active = sum(1 for j in jobs.values() if j["status"] == "active")
    print(f"\nRun complete: {new_count} new, {screened} screened, {active} active, {len(errors)} board errors.")
    for err in errors:
        print(f"  warn: {err}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
