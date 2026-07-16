"""
Builds the static dashboard (docs/index.html) from data/jobs.json.
GitHub Pages serves the docs/ folder, so the dashboard is just a URL.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent
DATA_PATH = ROOT / "data" / "jobs.json"
OUT_PATH = ROOT / "docs" / "index.html"

TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>CoS Briefing</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Archivo:wght@500;700;800&family=IBM+Plex+Mono:wght@400;500&family=Public+Sans:ital,wght@0,400;0,600;1,400&display=swap" rel="stylesheet">
<style>
  :root {
    --paper: #F2F4F1;
    --ink: #1C2B26;
    --petrol: #175B54;
    --petrol-soft: #DCE8E5;
    --amber: #C77D1F;
    --amber-soft: #F5E7D0;
    --muted: #76837D;
    --line: #C9D2CD;
    --card: #FFFFFF;
  }
  * { box-sizing: border-box; margin: 0; }
  body {
    background: var(--paper);
    color: var(--ink);
    font-family: 'Public Sans', system-ui, sans-serif;
    font-size: 15px;
    line-height: 1.5;
  }
  a { color: var(--petrol); }
  a:focus-visible, input:focus-visible, select:focus-visible {
    outline: 2px solid var(--petrol);
    outline-offset: 2px;
  }
  .wrap { max-width: 880px; margin: 0 auto; padding: 32px 20px 64px; }

  /* Briefing header */
  header { border-bottom: 3px solid var(--ink); padding-bottom: 20px; }
  .eyebrow {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 12px;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    color: var(--petrol);
  }
  h1 {
    font-family: 'Archivo', sans-serif;
    font-weight: 800;
    font-size: clamp(28px, 5vw, 42px);
    letter-spacing: -0.01em;
    text-transform: uppercase;
    margin-top: 4px;
  }
  .stats {
    display: flex;
    gap: 28px;
    margin-top: 16px;
    font-family: 'IBM Plex Mono', monospace;
    font-size: 13px;
    flex-wrap: wrap;
  }
  .stats b { font-size: 22px; font-weight: 500; display: block; }
  .stats .new-stat b { color: var(--amber); }
  .stats .strong-stat b { color: var(--petrol); }

  /* Controls */
  .controls { display: flex; gap: 10px; margin: 24px 0 16px; flex-wrap: wrap; align-items: center; }
  input[type="search"], select {
    font: inherit;
    padding: 8px 12px;
    border: 1px solid var(--line);
    border-radius: 6px;
    background: var(--card);
    color: var(--ink);
  }
  input[type="search"] { flex: 1; min-width: 180px; }
  label.toggle { display: flex; align-items: center; gap: 6px; font-size: 13px; color: var(--muted); cursor: pointer; }

  /* Job rows */
  .job {
    display: grid;
    grid-template-columns: 1fr auto;
    gap: 4px 16px;
    background: var(--card);
    border: 1px solid var(--line);
    border-radius: 8px;
    padding: 14px 16px;
    margin-bottom: 8px;
  }
  .job.is-new { border-left: 4px solid var(--amber); }
  .job.is-closed { opacity: 0.55; }
  .job .company {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 12px;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--petrol);
  }
  .job .title { font-weight: 600; font-size: 16px; }
  .job .title a { color: inherit; text-decoration: none; }
  .job .title a:hover { color: var(--petrol); text-decoration: underline; }
  .job .meta { color: var(--muted); font-size: 13px; }
  .job .reason { color: var(--muted); font-size: 13px; font-style: italic; margin-top: 2px; }
  .job .side {
    text-align: right;
    font-family: 'IBM Plex Mono', monospace;
    font-size: 11px;
    color: var(--muted);
    display: flex;
    flex-direction: column;
    align-items: flex-end;
    gap: 4px;
  }
  .badge {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 4px;
    font-weight: 500;
    letter-spacing: 0.08em;
  }
  .badge.new { background: var(--amber); color: #fff; }
  .badge.closed { background: var(--line); color: var(--ink); }
  .badge.src { background: var(--petrol-soft); color: var(--petrol); }
  .badge.fit-strong { background: var(--petrol); color: #fff; }
  .badge.fit-borderline { background: var(--amber-soft); color: var(--amber); border: 1px solid var(--amber); }
  .badge.fit-weak { background: transparent; color: var(--muted); border: 1px solid var(--line); text-decoration: line-through; }

  .empty { text-align: center; color: var(--muted); padding: 48px 0; }
  footer {
    margin-top: 32px;
    font-family: 'IBM Plex Mono', monospace;
    font-size: 12px;
    color: var(--muted);
    border-top: 1px solid var(--line);
    padding-top: 12px;
  }
  @media (max-width: 560px) {
    .job { grid-template-columns: 1fr; }
    .job .side { align-items: flex-start; text-align: left; flex-direction: row; flex-wrap: wrap; }
  }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div class="eyebrow">Personal job desk · updated __UPDATED__</div>
    <h1>Chief of Staff — Briefing</h1>
    <div class="stats">
      <div><b id="stat-active">0</b>active roles</div>
      <div class="new-stat"><b id="stat-new">0</b>new this week</div>
      <div class="strong-stat"><b id="stat-strong">0</b>strong fits</div>
      <div><b id="stat-boards">__BOARDS__</b>boards watched</div>
    </div>
  </header>

  <div class="controls">
    <input type="search" id="q" placeholder="Filter by company, title, location…" aria-label="Filter jobs">
    <select id="source" aria-label="Filter by source">
      <option value="">All sources</option>
      <option value="greenhouse">Greenhouse</option>
      <option value="lever">Lever</option>
      <option value="ashby">Ashby</option>
      <option value="adzuna">Adzuna (catch-all)</option>
    </select>
    <label class="toggle"><input type="checkbox" id="hide-weak"> Hide weak matches</label>
    <label class="toggle"><input type="checkbox" id="show-closed"> Show closed</label>
  </div>

  <div id="list"></div>
  <div class="empty" id="empty" hidden>No listings match. New roles appear here automatically after each run.</div>

  <footer>Refreshed every 6 hours by GitHub Actions · fit verdicts by Claude · full history in data/jobs.json in this repo</footer>
</div>

<script>
const JOBS = __JOBS__;
const NEW_WINDOW_DAYS = 7;
const FIT_LABEL = { strong: 'STRONG FIT', borderline: 'BORDERLINE', weak: 'WEAK FIT' };

const list = document.getElementById('list');
const emptyEl = document.getElementById('empty');
const q = document.getElementById('q');
const sourceSel = document.getElementById('source');
const hideWeak = document.getElementById('hide-weak');
const showClosed = document.getElementById('show-closed');

function isNew(job) {
  return job.status === 'active' &&
    (Date.now() - Date.parse(job.first_seen)) < NEW_WINDOW_DAYS * 864e5;
}

function fmtDate(iso) {
  return new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

function render() {
  const term = q.value.trim().toLowerCase();
  const src = sourceSel.value;
  const rows = JOBS
    .filter(j => showClosed.checked || j.status === 'active')
    .filter(j => !hideWeak.checked || !j.screen || j.screen.verdict !== 'weak')
    .filter(j => !src || j.source === src)
    .filter(j => !term || [j.company, j.title, j.location].join(' ').toLowerCase().includes(term))
    .sort((a, b) => Date.parse(b.first_seen) - Date.parse(a.first_seen));

  list.innerHTML = rows.map(j => {
    const s = j.screen;
    return `
    <article class="job ${isNew(j) ? 'is-new' : ''} ${j.status === 'closed' ? 'is-closed' : ''}">
      <div>
        <div class="company">${esc(j.company)}</div>
        <div class="title"><a href="${esc(j.url)}" target="_blank" rel="noopener">${esc(j.title)}</a></div>
        <div class="meta">${esc(j.location || 'Location not listed')}${s && s.remote && s.remote !== 'unclear' ? ' · ' + esc(s.remote) : ''}</div>
        ${s && s.reason ? `<div class="reason">${esc(s.reason)}</div>` : ''}
      </div>
      <div class="side">
        ${isNew(j) ? '<span class="badge new">NEW</span>' : ''}
        ${j.status === 'closed' ? '<span class="badge closed">CLOSED</span>' : ''}
        ${s ? `<span class="badge fit-${esc(s.verdict)}">${FIT_LABEL[s.verdict] || esc(s.verdict)}</span>` : ''}
        <span class="badge src">${esc(j.source)}</span>
        <span>seen ${fmtDate(j.first_seen)}</span>
      </div>
    </article>`;
  }).join('');

  emptyEl.hidden = rows.length > 0;
  document.getElementById('stat-active').textContent = JOBS.filter(j => j.status === 'active').length;
  document.getElementById('stat-new').textContent = JOBS.filter(isNew).length;
  document.getElementById('stat-strong').textContent =
    JOBS.filter(j => j.status === 'active' && j.screen && j.screen.verdict === 'strong').length;
}

function esc(s) {
  return String(s).replace(/[&<>"']/g, c =>
    ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

[q, sourceSel, hideWeak, showClosed].forEach(el => el.addEventListener('input', render));
render();
</script>
</body>
</html>
"""


def main() -> int:
    store = json.loads(DATA_PATH.read_text()) if DATA_PATH.exists() else {"jobs": {}}
    jobs = list(store.get("jobs", {}).values())

    config = json.loads((ROOT / "companies.json").read_text())
    boards = sum(len(config.get(k, [])) for k in ("greenhouse", "lever", "ashby"))

    updated = store.get("last_run") or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    updated_pretty = datetime.strptime(updated, "%Y-%m-%dT%H:%M:%SZ").strftime("%b %d, %H:%M UTC")

    html = (
        TEMPLATE
        .replace("__JOBS__", json.dumps(jobs))
        .replace("__UPDATED__", updated_pretty)
        .replace("__BOARDS__", str(boards))
    )
    OUT_PATH.parent.mkdir(exist_ok=True)
    OUT_PATH.write_text(html)
    print(f"Dashboard written: {OUT_PATH} ({len(jobs)} jobs)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
