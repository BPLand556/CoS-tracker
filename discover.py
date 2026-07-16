"""
Self-expanding watch list: board discovery via Claude web search.

Once per interval (default ~daily), asks the Claude API — with its web search
tool restricted to the three ATS job-board domains — to find current postings
matching the title keywords. Company slugs are extracted from the result URLs
and merged into store["discovered"], which scrape.py folds into the watch
list every run. Discovered boards are then fetched through the proper ATS
APIs like any hand-added company, so bad slugs simply 404 and get dropped.

Uses the same ANTHROPIC_API_KEY as screening. If it's absent, discovery is
skipped and the tracker runs on the configured + previously discovered list.
"""

import json
import os
import re
import sys
from datetime import datetime, timezone

import requests

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"
DISCOVERY_MODEL = os.environ.get("DISCOVERY_MODEL", "claude-haiku-4-5-20251001")
DISCOVERY_INTERVAL_HOURS = float(os.environ.get("DISCOVERY_INTERVAL_HOURS", "20"))
DISCOVERY_MAX_SEARCHES = int(os.environ.get("DISCOVERY_MAX_SEARCHES", "6"))
TIMEOUT = 180

ATS_DOMAINS = [
    "jobs.ashbyhq.com",
    "jobs.lever.co",
    "boards.greenhouse.io",
    "job-boards.greenhouse.io",
]

SLUG_PATTERNS = [
    ("ashby", re.compile(r"https?://jobs\.ashbyhq\.com/([A-Za-z0-9._%\-]+)")),
    ("lever", re.compile(r"https?://jobs\.lever\.co/([A-Za-z0-9._\-]+)")),
    ("greenhouse", re.compile(r"https?://(?:boards|job-boards)\.greenhouse\.io/([A-Za-z0-9._\-]+)")),
]

BANNED_SLUGS = {"embed", "api", "jobs", "boards", ""}


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def call_discovery(api_key: str, keywords: list[str]) -> str:
    """One Claude API call with domain-restricted web search. Returns response text."""
    prompt = (
        "Find as many CURRENT job postings as you can whose titles match any of these "
        f"phrases: {', '.join(repr(k) for k in keywords)}. Only postings hosted on Ashby "
        "(jobs.ashbyhq.com), Lever (jobs.lever.co), or Greenhouse (boards.greenhouse.io or "
        "job-boards.greenhouse.io) count. Run several different searches to maximize coverage. "
        "Then output ONLY a JSON array of the posting URLs you found — no commentary."
    )
    resp = requests.post(
        API_URL,
        headers={
            "x-api-key": api_key,
            "anthropic-version": API_VERSION,
            "content-type": "application/json",
        },
        json={
            "model": DISCOVERY_MODEL,
            "max_tokens": 4000,
            "messages": [{"role": "user", "content": prompt}],
            "tools": [{
                "type": "web_search_20250305",
                "name": "web_search",
                "max_uses": DISCOVERY_MAX_SEARCHES,
                "allowed_domains": ATS_DOMAINS,
            }],
        },
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    return "".join(
        block.get("text", "") for block in data.get("content", [])
        if block.get("type") == "text"
    )


def extract_boards(text: str) -> dict[str, set[str]]:
    """Pull company slugs out of any ATS URLs in the text (JSON or prose)."""
    found: dict[str, set[str]] = {}
    for source, pattern in SLUG_PATTERNS:
        for slug in pattern.findall(text or ""):
            slug = slug.strip().strip(".,)\"'")
            if slug and slug.lower() not in BANNED_SLUGS:
                found.setdefault(source, set()).add(slug)
    return found


def run_discovery(store: dict, keywords: list[str]) -> int:
    """Discover new boards and merge into store['discovered']. Returns count added."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("discovery: ANTHROPIC_API_KEY not set, skipping board discovery")
        return 0

    last = store.get("last_discovery")
    if last:
        age_h = (
            datetime.now(timezone.utc)
            - datetime.strptime(last, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        ).total_seconds() / 3600
        if age_h < DISCOVERY_INTERVAL_HOURS:
            print(f"discovery: ran {age_h:.0f}h ago, skipping (interval {DISCOVERY_INTERVAL_HOURS:.0f}h)")
            return 0

    text = call_discovery(api_key, keywords)
    found = extract_boards(text)

    disc = store.setdefault("discovered", {})
    added_total = 0
    for source, slugs in found.items():
        current = set(disc.get(source, []))
        added = slugs - current
        for slug in sorted(added):
            print(f"DISCOVERED new {source} board: {slug}")
        disc[source] = sorted(current | slugs)
        added_total += len(added)

    store["last_discovery"] = now_iso()
    print(f"discovery: complete, {added_total} new boards adopted")
    return added_total
