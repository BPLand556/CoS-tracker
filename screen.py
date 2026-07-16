"""
LLM screening for new listings via the Claude API.

For each active job that hasn't been screened yet, sends the full job
description to Claude and stores a verdict on the job record:

    job["screen"] = {
        "verdict": "strong" | "borderline" | "weak",
        "reason":  "<one sentence>",
        "flags":   ["ea_flavored", ...],
        "remote":  "remote" | "hybrid" | "onsite" | "unclear",
        "model":   "<model id>",
        "screened_at": "<iso timestamp>",
    }

Requires ANTHROPIC_API_KEY in the environment (a GitHub Actions secret in CI).
If the key is absent, screening is skipped silently and retried next run —
the tracker works fine without it, you just don't get fit badges.
"""

import html
import json
import os
import re
import sys
from datetime import datetime, timezone

import requests

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"
MODEL = os.environ.get("SCREEN_MODEL", "claude-haiku-4-5-20251001")
MAX_PER_RUN = int(os.environ.get("SCREEN_MAX_PER_RUN", "25"))
MAX_DESC_CHARS = 6000
TIMEOUT = 60

VALID_VERDICTS = {"strong", "borderline", "weak"}

SYSTEM_PROMPT = """You screen job listings for a candidate who wants a true Chief of Staff role at a startup — a strategic right-hand-to-a-founder position (special projects, operating cadence, cross-functional leverage, board/fundraise support), NOT an executive-assistant or office-manager role wearing an inflated title.

Respond with ONLY a JSON object, no markdown fences, in exactly this shape:
{"verdict": "strong" | "borderline" | "weak",
 "reason": "<one concise sentence explaining the verdict>",
 "flags": ["<zero or more short lowercase tags, e.g. true_strategic_cos, founder_facing, ea_flavored, admin_heavy, calendar_management, big_company, unclear_scope>"],
 "remote": "remote" | "hybrid" | "onsite" | "unclear"}

Verdicts:
- "strong": genuinely strategic Chief of Staff work at a startup.
- "borderline": mixed signals, vague scope, or partly administrative.
- "weak": EA/admin/office-manager role rebranded as CoS, or clearly a poor fit."""


def strip_html(text: str) -> str:
    """Convert HTML job descriptions to readable plain text."""
    if not text:
        return ""
    text = html.unescape(text)
    text = re.sub(r"<(br|/p|/li|/h[1-6]|/div)[^>]*>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()


def call_claude(api_key: str, user_message: str) -> str:
    """One API call; returns the model's text response. Raises on HTTP errors."""
    resp = requests.post(
        API_URL,
        headers={
            "x-api-key": api_key,
            "anthropic-version": API_VERSION,
            "content-type": "application/json",
        },
        json={
            "model": MODEL,
            "max_tokens": 500,
            "system": SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": user_message}],
        },
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    return "".join(
        block.get("text", "") for block in data.get("content", [])
        if block.get("type") == "text"
    )


def parse_verdict(raw: str) -> dict | None:
    """Parse the model's JSON reply; tolerate stray markdown fences."""
    cleaned = re.sub(r"```(?:json)?", "", raw).strip()
    try:
        obj = json.loads(cleaned)
    except json.JSONDecodeError:
        return None
    verdict = obj.get("verdict")
    if verdict not in VALID_VERDICTS:
        return None
    return {
        "verdict": verdict,
        "reason": str(obj.get("reason", ""))[:300],
        "flags": [str(f)[:40] for f in obj.get("flags", [])][:8],
        "remote": obj.get("remote", "unclear"),
    }


def screen_job(api_key: str, job: dict, description: str) -> dict | None:
    description = strip_html(description)  # defensive: fetchers strip too, but never trust input
    user_message = (
        f"Company: {job.get('company', '')}\n"
        f"Title: {job.get('title', '')}\n"
        f"Location: {job.get('location', '') or 'not listed'}\n\n"
        f"Job description:\n{description[:MAX_DESC_CHARS] or '(no description available)'}"
    )
    raw = call_claude(api_key, user_message)
    verdict = parse_verdict(raw)
    if verdict is None:
        return None
    verdict["model"] = MODEL
    verdict["screened_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return verdict


def screen_new_jobs(jobs: dict, descriptions: dict) -> int:
    """Screen active jobs that lack a verdict. Mutates `jobs`. Returns count screened."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("screening: ANTHROPIC_API_KEY not set, skipping (will retry next run)")
        return 0

    pending = [
        (jid, job) for jid, job in jobs.items()
        if job.get("status") == "active" and "screen" not in job and jid in descriptions
    ]
    screened = 0
    for jid, job in pending[:MAX_PER_RUN]:
        try:
            verdict = screen_job(api_key, job, descriptions[jid])
        except Exception as exc:  # noqa: BLE001 - screening must never kill the run
            print(f"  screen error for {job['company']} — {job['title']}: {exc}", file=sys.stderr)
            continue
        if verdict is None:
            print(f"  screen: unparseable reply for {job['company']} — {job['title']}", file=sys.stderr)
            continue
        job["screen"] = verdict
        screened += 1
        print(f"SCREENED [{verdict['verdict']}] {job['company']} — {job['title']}: {verdict['reason']}")
    if len(pending) > MAX_PER_RUN:
        print(f"screening: {len(pending) - MAX_PER_RUN} jobs deferred to next run (cap {MAX_PER_RUN})")
    return screened
