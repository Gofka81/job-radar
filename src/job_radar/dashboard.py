"""The phone-friendly HTML dashboard served at GET /. Self-contained (inline CSS
+ JS), no build step. It loads open, then talks to the bearer-protected /api/*
endpoints using a token the user enters once (kept in localStorage).

Auto light/dark (follows the device, manual override persisted). Status lanes are
a segmented control that doubles as the funnel (live counts); advanced filters
collapse. Same API contract as before — pure UI."""

from __future__ import annotations

DASHBOARD_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light dark">
<title>job-radar</title>
<style>
  /* ---- theme: light default, dark via media query, [data-theme] overrides both ---- */
  :root {
    --bg:#f5f6f8; --card:#ffffff; --line:#e3e5ea; --fg:#1b1e26; --muted:#6b7180;
    --accent:#2f6ef7; --accent-fg:#ffffff; --pill:#eef0f4; --pill-fg:#3a4150;
    --new:#12924f; --new-fg:#ffffff; --shadow:0 1px 2px rgba(20,25,40,.06);
    --sc-hi-bg:#d8f6e4; --sc-hi-fg:#0c7a3d; --sc-mid-bg:#fbefcd; --sc-mid-fg:#8a6800;
    --sc-lo-bg:#fbdede; --sc-lo-fg:#b32424; --danger:#e23b3b;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --bg:#0f1115; --card:#181b22; --line:#282c36; --fg:#e6e8ec; --muted:#8b909c;
      --accent:#4f86f7; --accent-fg:#ffffff; --pill:#242934; --pill-fg:#c3c8d2;
      --new:#2ecc71; --new-fg:#06210f; --shadow:none;
      --sc-hi-bg:#173226; --sc-hi-fg:#7CFC9E; --sc-mid-bg:#332c18; --sc-mid-fg:#FFD479;
      --sc-lo-bg:#331a1a; --sc-lo-fg:#ff9b9b; --danger:#ff6b6b;
    }
  }
  :root[data-theme="light"] {
    --bg:#f5f6f8; --card:#ffffff; --line:#e3e5ea; --fg:#1b1e26; --muted:#6b7180;
    --accent:#2f6ef7; --accent-fg:#ffffff; --pill:#eef0f4; --pill-fg:#3a4150;
    --new:#12924f; --new-fg:#ffffff; --shadow:0 1px 2px rgba(20,25,40,.06);
    --sc-hi-bg:#d8f6e4; --sc-hi-fg:#0c7a3d; --sc-mid-bg:#fbefcd; --sc-mid-fg:#8a6800;
    --sc-lo-bg:#fbdede; --sc-lo-fg:#b32424; --danger:#e23b3b;
  }
  :root[data-theme="dark"] {
    --bg:#0f1115; --card:#181b22; --line:#282c36; --fg:#e6e8ec; --muted:#8b909c;
    --accent:#4f86f7; --accent-fg:#ffffff; --pill:#242934; --pill-fg:#c3c8d2;
    --new:#2ecc71; --new-fg:#06210f; --shadow:none;
    --sc-hi-bg:#173226; --sc-hi-fg:#7CFC9E; --sc-mid-bg:#332c18; --sc-mid-fg:#FFD479;
    --sc-lo-bg:#331a1a; --sc-lo-fg:#ff9b9b; --danger:#ff6b6b;
  }

  * { box-sizing:border-box; }
  html, body { margin:0; }
  body { background:var(--bg); color:var(--fg);
         font:15px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;
         -webkit-font-smoothing:antialiased; }
  button, select, input, textarea { font-family:inherit; }

  /* ---- app bar ---- */
  header { position:sticky; top:0; z-index:20; background:var(--bg);
           border-bottom:1px solid var(--line); }
  .bar { display:flex; align-items:center; gap:10px; padding:10px 16px;
         max-width:860px; margin:0 auto; }
  .brand { font-size:17px; font-weight:750; letter-spacing:-.01em; margin-right:2px;
           white-space:nowrap; }
  .tabs { display:flex; gap:2px; flex:1; overflow-x:auto; scrollbar-width:none; }
  .tabs::-webkit-scrollbar { display:none; }
  .tab { background:none; border:0; color:var(--muted); padding:7px 11px; border-radius:8px;
         font-size:14px; font-weight:600; cursor:pointer; white-space:nowrap; }
  .tab:hover { color:var(--fg); background:var(--pill); }
  .tab.on { color:var(--accent); background:color-mix(in srgb,var(--accent) 12%,transparent); }
  .iconbtn { background:var(--card); color:var(--fg); border:1px solid var(--line);
             border-radius:9px; width:38px; height:38px; font-size:16px; cursor:pointer;
             display:inline-flex; align-items:center; justify-content:center; flex:0 0 auto; }
  .iconbtn:hover { border-color:var(--accent); }
  .iconbtn:active { transform:translateY(1px); }

  .wrap { padding:14px 16px 40px; max-width:860px; margin:0 auto; }

  /* generic controls */
  button, select, input { color:var(--fg); }
  .btn { background:var(--card); border:1px solid var(--line); border-radius:9px;
         padding:8px 13px; font-size:14px; font-weight:600; cursor:pointer;
         min-height:38px; box-shadow:var(--shadow); }
  .btn:hover { border-color:var(--accent); }
  .btn:active { transform:translateY(1px); }
  .btn.primary { background:var(--accent); color:var(--accent-fg); border-color:var(--accent); }
  .btn.ghost { background:transparent; color:var(--muted); box-shadow:none; }
  select.btn { padding-right:8px; }
  input[type=text], input[type=number], input[type=search] {
    background:var(--card); border:1px solid var(--line); border-radius:9px;
    padding:9px 12px; font-size:14px; min-height:38px; box-shadow:var(--shadow); }
  input:focus, select:focus, textarea:focus { outline:2px solid color-mix(in srgb,var(--accent) 45%,transparent);
    outline-offset:0; border-color:var(--accent); }

  /* ---- jobs toolbar ---- */
  .toolbar { display:flex; gap:8px; align-items:center; margin-bottom:12px; flex-wrap:wrap; }
  .search { flex:1; min-width:180px; position:relative; }
  .search input { width:100%; padding-left:34px; }
  .search::before { content:"🔍"; position:absolute; left:11px; top:50%; transform:translateY(-50%);
                    font-size:13px; opacity:.7; pointer-events:none; }
  .actions { display:flex; gap:6px; flex:0 0 auto; }

  /* ---- status lanes (segmented control = funnel) ---- */
  .lanes { display:flex; gap:4px; background:var(--card); border:1px solid var(--line);
           border-radius:11px; padding:4px; overflow-x:auto; scrollbar-width:none;
           box-shadow:var(--shadow); }
  .lanes::-webkit-scrollbar { display:none; }
  .seg-opt { flex:1 0 auto; display:flex; align-items:center; justify-content:center; gap:7px;
             background:none; border:0; color:var(--muted); border-radius:8px;
             padding:8px 13px; font-size:14px; font-weight:650; cursor:pointer; white-space:nowrap; }
  .seg-opt:hover { color:var(--fg); }
  .seg-opt.on { background:var(--accent); color:var(--accent-fg); }
  .seg-n { font-size:12px; font-weight:700; background:color-mix(in srgb,var(--muted) 22%,transparent);
           color:inherit; border-radius:20px; padding:0 7px; min-width:20px; text-align:center; }
  .seg-opt.on .seg-n { background:rgba(255,255,255,.28); }

  .subbar { display:flex; align-items:center; gap:10px; margin:10px 0 4px; flex-wrap:wrap; }
  .toggle { background:none; border:1px solid var(--line); color:var(--muted); border-radius:20px;
            padding:5px 12px; font-size:13px; font-weight:600; cursor:pointer; min-height:32px; }
  .toggle.on { background:var(--accent); color:var(--accent-fg); border-color:var(--accent); }
  .spacer { flex:1; }
  .fbadge { background:var(--accent); color:var(--accent-fg); border-radius:20px; font-size:11px;
            font-weight:700; padding:0 6px; margin-left:6px; }
  #moreFilters { display:none; gap:8px; flex-wrap:wrap; align-items:center;
                 padding:11px 12px; margin:8px 0 4px; background:var(--card);
                 border:1px solid var(--line); border-radius:11px; box-shadow:var(--shadow); }
  #moreFilters.open { display:flex; }
  #moreFilters label { font-size:12px; color:var(--muted); font-weight:600; margin-right:-2px; }
  #fsalary { width:104px; }
  #floc, #fsource, #sort { min-width:120px; }

  #msg { color:var(--muted); font-size:13px; padding:8px 2px 4px; }

  /* ---- job card ---- */
  .job { background:var(--card); border:1px solid var(--line); border-left:3px solid var(--line);
         border-radius:12px; padding:12px 14px; margin-bottom:10px; box-shadow:var(--shadow); }
  .job.sb-hi  { border-left-color:var(--sc-hi-fg); }
  .job.sb-mid { border-left-color:var(--sc-mid-fg); }
  .job.sb-lo  { border-left-color:var(--sc-lo-fg); }
  .job.seen { opacity:.55; }   /* 'viewed' = a dim marker, still in the inbox */
  .jobhead { display:flex; gap:9px; align-items:flex-start; }
  .job a.joblink { color:var(--fg); text-decoration:none; font-weight:650; font-size:15.5px;
                   line-height:1.3; flex:1; }
  .job a.joblink:hover { color:var(--accent); }
  .score { font-weight:800; border-radius:7px; padding:3px 8px; font-size:12.5px; flex:0 0 auto;
           line-height:1.2; }
  .score.s-hi  { background:var(--sc-hi-bg);  color:var(--sc-hi-fg); }
  .score.s-mid { background:var(--sc-mid-bg); color:var(--sc-mid-fg); }
  .score.s-lo  { background:var(--sc-lo-bg);  color:var(--sc-lo-fg); }
  .cardacts { display:flex; gap:4px; flex:0 0 auto; }
  .mini { background:none; border:1px solid transparent; color:var(--muted); border-radius:7px;
          width:30px; height:30px; font-size:14px; cursor:pointer; line-height:1;
          display:inline-flex; align-items:center; justify-content:center; }
  .mini:hover { border-color:var(--accent); color:var(--fg); }
  .mini.dismiss:hover { border-color:var(--danger); color:var(--danger); }
  .mini.spin { color:var(--accent); cursor:default; animation:pulse 1.1s ease-in-out infinite; }
  @keyframes pulse { 0%,100%{ opacity:.35 } 50%{ opacity:1 } }
  .meta { color:var(--muted); font-size:13px; margin-top:7px; display:flex; gap:7px;
          flex-wrap:wrap; align-items:center; }
  .meta .co { font-weight:600; color:var(--fg); }
  .pill { background:var(--pill); color:var(--pill-fg); border-radius:20px; padding:1px 9px; font-size:12px; }
  .pill.new { background:var(--new); color:var(--new-fg); font-weight:700; }
  .reason { color:var(--muted); font-size:13px; margin-top:9px; line-height:1.45;
            border-top:1px solid var(--line); padding-top:8px; }
  .empty { color:var(--muted); text-align:center; padding:40px 16px; font-size:14px; }

  /* funnel micro-strip (secondary stats not covered by lanes) */
  .ministat { color:var(--muted); font-size:12px; }
  .ministat b { color:var(--fg); }

  /* ---- secondary views ---- */
  .cfgbar { display:flex; gap:8px; align-items:center; margin-bottom:12px; flex-wrap:wrap; }
  .muted { color:var(--muted); }
  #cfg, #rubric { width:100%; min-height:60vh; padding:13px; border-radius:11px;
         border:1px solid var(--line); background:var(--card); color:var(--fg);
         font:13px/1.55 ui-monospace,SFMono-Regular,Menlo,monospace; resize:vertical;
         white-space:pre; tab-size:2; box-shadow:var(--shadow); }
  .hint { color:var(--muted); font-size:12px; margin-top:8px; line-height:1.5; }
  .chips { display:flex; gap:8px; flex-wrap:wrap; margin-bottom:14px; }
  .chip { background:var(--card); border:1px solid var(--line); border-radius:11px;
          padding:9px 13px; min-width:78px; box-shadow:var(--shadow); }
  .chip b { display:block; font-size:21px; font-weight:750; }
  .chip span { color:var(--muted); font-size:11.5px; text-transform:uppercase; letter-spacing:.05em; }
  .trk-sec { font-size:13px; font-weight:700; color:var(--muted); text-transform:uppercase;
             letter-spacing:.05em; margin:16px 0 9px; }
  .trk-acts { margin-top:9px; display:flex; gap:6px; flex-wrap:wrap; }
  table.usage { width:100%; border-collapse:collapse; font-size:13px; }
  table.usage th, table.usage td { text-align:left; padding:7px 8px; border-bottom:1px solid var(--line); }
  table.usage th { color:var(--muted); font-weight:600; }
  .warn { color:var(--danger); font-weight:700; }

  /* ---- pager (windowed: « first … window … last » ) ---- */
  .pager { display:flex; align-items:center; justify-content:center; gap:6px;
           margin:16px 0 4px; flex-wrap:wrap; }
  .pg { min-width:38px; height:38px; padding:0 10px; border:1px solid var(--line);
        background:var(--card); color:var(--fg); border-radius:9px; font-size:14px;
        font-weight:600; cursor:pointer; box-shadow:var(--shadow);
        display:inline-flex; align-items:center; justify-content:center; }
  .pg:hover:not(:disabled):not(.on) { border-color:var(--accent); }
  .pg.on { background:var(--accent); color:var(--accent-fg); border-color:var(--accent); cursor:default; }
  .pg:disabled { opacity:.35; cursor:default; }
  .pg.nav { font-size:17px; line-height:1; }
  .pg.gap { border:0; background:none; box-shadow:none; cursor:default;
            min-width:16px; color:var(--muted); }

  /* ---- tracker kanban ---- */
  /* Break out of the 860px reading column so the board uses the real screen width
     (full-bleed via the centered-100vw trick). Columns then GROW to fill evenly. */
  #trackerView { width:96vw; max-width:1500px; margin-left:50%; transform:translateX(-50%); }
  .kanban { display:flex; gap:14px; overflow-x:auto; padding-bottom:10px; align-items:flex-start;
            scroll-snap-type:x proximity; -webkit-overflow-scrolling:touch; }
  .kanban::-webkit-scrollbar { height:8px; }
  .kcol { flex:1 1 300px; min-width:300px; scroll-snap-align:start; background:var(--bg);
          border:1px solid var(--line); border-radius:14px; padding:12px;
          display:flex; flex-direction:column; transition:outline-color .12s, background .12s; }
  .kcol-head { display:flex; align-items:center; gap:8px; font-weight:750; font-size:14.5px;
               padding:2px 4px 12px; }
  .kcol-head .seg-n { font-size:12px; font-weight:700;
                      background:color-mix(in srgb,var(--muted) 22%,transparent);
                      border-radius:20px; padding:0 8px; min-width:22px; text-align:center; }
  .kcol.saved   .kcol-head { color:var(--accent); }
  .kcol.applied .kcol-head { color:var(--new); }
  .kcol.rejected .kcol-head { color:var(--danger); }
  .kcol-body { display:flex; flex-direction:column; gap:10px; }
  .kcol .job { margin-bottom:0; cursor:grab; }
  .kcol .job:active { cursor:grabbing; }
  .kcol .job.dragging { opacity:.45; }
  .kcol.drop { outline:2px dashed var(--accent); outline-offset:-3px;
               background:color-mix(in srgb,var(--accent) 8%,var(--bg)); }
  .kcol-empty { color:var(--muted); font-size:13px; text-align:center; padding:22px 8px;
                border:1px dashed var(--line); border-radius:10px; }
  .drag-hint { color:var(--muted); font-size:12px; margin:2px 2px 10px; }

  /* ---- auth ---- */
  #auth { display:none; margin-bottom:14px; gap:8px; }
  #token { flex:1; min-width:160px; }

  /* ---- apply modal ---- */
  .modal { position:fixed; inset:0; background:rgba(0,0,0,.55); z-index:50;
           display:flex; align-items:center; justify-content:center; padding:16px; }
  .modal-card { background:var(--card); border:1px solid var(--line); border-radius:16px;
                padding:20px; width:100%; max-width:390px; box-shadow:0 20px 60px rgba(0,0,0,.3); }
  .modal-title { font-size:18px; font-weight:750; margin-bottom:5px; }
  .modal-actions { display:flex; flex-direction:column; gap:8px; margin-top:18px; }
  .modal-actions button { width:100%; min-height:47px; font-size:15px; }

  @media (max-width:600px) {
    .bar { padding:9px 12px; gap:8px; }
    .brand { font-size:15px; }
    .wrap { padding:12px 12px 40px; }
    .actions .btn span.lbl { display:none; }   /* icon-only actions on phones */
    /* kanban: one column at a time with a peek of the next; swipe between them */
    .kcol { flex-basis:84vw; min-width:84vw; }
    .pager .btn { flex:1; }
  }
</style>
</head>
<body>
<header>
  <div class="bar">
    <span class="brand">📡 job-radar</span>
    <nav class="tabs" id="tabs">
      <button class="tab on" data-view="jobs">🧭 Jobs</button>
      <button class="tab" data-view="tracker">📌 Tracker</button>
      <button class="tab" data-view="config">⚙ Config</button>
      <button class="tab" data-view="rubric">📋 Rubric</button>
      <button class="tab" data-view="usage">📊 Usage</button>
    </nav>
    <button class="iconbtn" id="themeBtn" title="Toggle light / dark">🌓</button>
    <button class="iconbtn" id="refresh" title="Refresh">↻</button>
  </div>
</header>

<div class="wrap">
  <div id="auth">
    <input id="token" type="text" placeholder="API token" autocomplete="off">
    <button class="btn primary" id="save">Save</button>
  </div>

  <!-- ============ JOBS ============ -->
  <div id="jobsView">
    <div class="toolbar">
      <div class="search">
        <input id="q" type="search" placeholder="Search title / company / JD — e.g. spark, airflow" autocomplete="off">
      </div>
      <div class="actions">
        <button class="btn" id="scan" title="Scan now (recent window)">🛰 <span class="lbl">Scan</span></button>
        <button class="btn" id="deepscan" title="Deep scan — pull the whole window">🔭 <span class="lbl">Deep scan</span></button>
        <button class="btn" id="analyze" title="LLM triage of new jobs">✨ <span class="lbl">Analyze</span></button>
        <button class="btn" id="stopAnalyze" title="Halt the running triage" style="display:none">⏹ <span class="lbl">Stop</span></button>
      </div>
    </div>

    <div class="lanes" id="lanes"></div>

    <div class="subbar">
      <button class="toggle" id="recency">Recent 48h</button>
      <span class="ministat" id="ministat"></span>
      <span class="spacer"></span>
      <button class="btn ghost" id="filtersToggle">⚙ Filters<span class="fbadge" id="fbadge" style="display:none">0</span></button>
    </div>

    <div id="moreFilters">
      <label>Location</label><select class="btn" id="floc"><option value="">All</option></select>
      <label>Source</label><select class="btn" id="fsource"><option value="">All</option></select>
      <label>Min £</label><input id="fsalary" type="number" min="0" step="5000" placeholder="any" inputmode="numeric">
      <label>Sort</label>
      <select class="btn" id="sort">
        <option value="score" selected>Score</option>
        <option value="recent">Recent</option>
        <option value="company">Company</option>
        <option value="location">Location</option>
      </select>
    </div>

    <div id="msg"></div>
    <div id="list"></div>
    <div id="pager" class="pager" style="display:none"></div>
  </div>

  <!-- ============ TRACKER ============ -->
  <div id="trackerView" style="display:none">
    <div class="cfgbar">
      <button class="btn" id="trkReload">↻ Reload</button>
      <span id="trkMsg" class="muted"></span>
    </div>
    <div class="drag-hint">↔ Drag a card between columns to change its stage — or use the buttons on each card.</div>
    <div id="trkBox" class="kanban"></div>
    <div class="hint">
      Your pipeline board — drag stages with the buttons on each card. <b>🔖 Saved</b> =
      shortlisted to apply (from a job link, or the popup after opening one). <b>✅ Applied</b>
      and <b>🚫 Rejected</b> track the rest. Seen-but-untouched jobs stay in the 🧭 Jobs inbox
      (dimmed); hidden ones live in the Jobs “Archived” lane.
    </div>
  </div>

  <!-- ============ CONFIG ============ -->
  <div id="configView" style="display:none">
    <div class="cfgbar">
      <button class="btn primary" id="cfgSave">Save config</button>
      <button class="btn" id="cfgReload">↻ Reload</button>
      <span id="cfgMsg" class="muted"></span>
    </div>
    <textarea id="cfg" spellcheck="false" autocapitalize="off" autocomplete="off"
              placeholder="Loading config…"></textarea>
    <div class="hint">Edits save to the server’s config.yml — the next scan picks them up (no redeploy).</div>
  </div>

  <!-- ============ RUBRIC ============ -->
  <div id="rubricView" style="display:none">
    <div class="cfgbar">
      <button class="btn primary" id="rubSave">Save rubric</button>
      <button class="btn" id="rubReload">↻ Reload</button>
      <span id="rubMsg" class="muted"></span>
    </div>
    <textarea id="rubric" spellcheck="false" autocapitalize="off" autocomplete="off"
              placeholder="Loading rubric…"></textarea>
    <div class="hint">
      The 0–10 triage scoring policy (candidate profile). Saves to analysis/rubric.md —
      the next ✨ Analyze run uses it (no redeploy).
    </div>
  </div>

  <!-- ============ USAGE ============ -->
  <div id="usageView" style="display:none">
    <div class="cfgbar">
      <button class="btn" id="useReload">↻ Reload</button>
      <span id="useMsg" class="muted"></span>
    </div>
    <div id="useTotals" class="chips"></div>
    <div id="useBox"></div>
    <div class="hint">
      LLM usage (resets on deploy). <b>calls</b> = LLM invocations — for the claude-cli
      engine that’s your Pro quota (“Pro” = $0 real). <b>api $</b> appears only if the
      metered API engine was used.
    </div>
  </div>
</div>

<div id="applyModal" class="modal" style="display:none">
  <div class="modal-card">
    <div class="modal-title">Did you apply?</div>
    <div id="applyJob" class="muted"></div>
    <div class="modal-actions">
      <button id="amApplied" class="btn primary">✅ Applied</button>
      <button id="amSaved" class="btn">🔖 Save for later</button>
      <button id="amArchive" class="btn">🚫 Not interested (hide)</button>
      <button id="amDismiss" class="btn ghost">✕ Not now</button>
    </div>
  </div>
</div>

<script>
const $ = s => document.querySelector(s);
let TOKEN = localStorage.getItem("jr_token") || "";
let JOBS = [];          // last /api/jobs payload (up to 500, all statuses)
let FUNNEL = {};        // /api/funnel — TRUE per-status totals (not truncated)

// ---- theme (auto, with a persisted manual override) ----
const THEME_KEY = "jr_theme";
function applyTheme(t){ const r=document.documentElement;
  if (t) r.dataset.theme = t; else r.removeAttribute("data-theme"); }
applyTheme(localStorage.getItem(THEME_KEY) || "");
$("#themeBtn").onclick = () => {
  const sysDark = matchMedia("(prefers-color-scheme: dark)").matches;
  const cur = document.documentElement.dataset.theme || (sysDark ? "dark" : "light");
  const next = cur === "dark" ? "light" : "dark";
  localStorage.setItem(THEME_KEY, next); applyTheme(next);
};

function authHeader(){ return { "authorization": "Bearer " + TOKEN }; }
function ago(ts){
  if (!ts) return "";
  const s = (Date.now() - new Date(ts).getTime())/1000;
  if (s < 3600) return Math.max(1,Math.round(s/60)) + "m ago";
  if (s < 86400) return Math.round(s/3600) + "h ago";
  return Math.round(s/86400) + "d ago";
}
function esc(t){ const d=document.createElement("div"); d.textContent=t==null?"":t; return d.innerHTML; }

async function api(path, opts={}) {
  const r = await fetch(path, { ...opts, headers: { ...authHeader(), ...(opts.headers||{}) } });
  if (r.status === 401 || r.status === 503) { showAuth("Enter a valid API token."); throw new Error("auth"); }
  return r;
}
function showAuth(m){ $("#auth").style.display="flex"; $("#msg").textContent=m||""; }

const RECENT_MS = 48*3600*1000;   // "recent" default window (inbox only)
let SHOW_ALL = false;             // recency toggle (off = recent only)
let LANE = "inbox";               // active status lane

// Client-side pagination over the filtered set. 25 balances a scannable page
// against too many clicks (a full scan yields 400+ across sources). PAGE resets
// to 1 whenever the filter set changes (lane/search/sort/filters); the pager
// buttons just move within the current set.
const PAGE_SIZE = 25;
let PAGE = 1;
function applyFilters(){ PAGE = 1; viewJobs(); }

// Jobs is the discovery surface, so its lanes stay minimal: the working Inbox,
// hidden Archived (restore point), and All (escape hatch). Applied/Rejected/Saved
// are pipeline states — they live on the 📌 Tracker board, not here.
const STATUS_SETS = {
  inbox:    s => s === "new" || s === "viewed",
  archived: s => s === "archived",
  all:      () => true,
};
const LANES = [
  { key:"inbox",    label:"Inbox" },
  { key:"archived", label:"Archived" },
  { key:"all",      label:"All" },
];
// Lane badge counts come from the funnel (TRUE totals, not truncated by the 500 cap).
function laneCount(key){
  const f = FUNNEL || {};
  if (key === "inbox") return (f.new||0) + (f.viewed||0);
  if (key === "all")   return f.total||0;
  return f[key]||0;
}
function renderLanes(){
  $("#lanes").innerHTML = LANES.map(l =>
    `<button class="seg-opt${l.key===LANE?" on":""}" data-lane="${l.key}">`
    + `${l.label}<span class="seg-n">${laneCount(l.key)}</span></button>`).join("");
}
$("#lanes").onclick = (e) => {
  const b = e.target.closest("[data-lane]"); if (!b) return;
  LANE = b.dataset.lane; renderLanes(); applyFilters();
};

// One posting can list several cities (locations[], stored priority-first by the
// server). Show the first as the preview chip + "+N" so Edinburgh is never hidden.
function primaryLoc(j){ const l=j.locations||[]; return l[0] || j.location || "—"; }
function locExtra(j){ const n=(j.locations||[]).length; return n>1 ? ` +${n-1}` : ""; }

function fillFilter(sel, label, values) {
  const cur = sel.value;
  sel.innerHTML = [`<option value="">${label}</option>`]
    .concat([...new Set(values)].filter(Boolean).sort().map(v => `<option>${esc(v)}</option>`)).join("");
  sel.value = cur;  // keep selection across reloads
}
function activeFilterCount(){
  return [$("#floc").value, $("#fsource").value, $("#fsalary").value].filter(Boolean).length;
}
function viewJobs() {
  // Text search (#q) is server-side (it matches the JD too) — see fetchJobs().
  // Status lane + the rest filter the loaded set client-side for instant response.
  const inSet = STATUS_SETS[LANE] || STATUS_SETS.inbox;
  const loc = $("#floc").value, src = $("#fsource").value;
  const minSal = parseFloat($("#fsalary").value) || 0;
  const now = Date.now();
  let v = JOBS.filter(j =>
    inSet(j.status) &&
    (!loc || (j.locations || []).includes(loc)) &&
    (!src || j.source === src) &&
    // min salary on salary_max; keep jobs with no salary data visible
    (!minSal || j.salary_max == null || j.salary_max >= minSal) &&
    // recency only narrows the inbox; curated pipeline lanes show their full set
    (LANE !== "inbox" || SHOW_ALL || !j.first_seen ||
     (now - new Date(j.first_seen).getTime()) <= RECENT_MS));
  const k = $("#sort").value;
  const recent = (a,b)=> (b.first_seen||"").localeCompare(a.first_seen||"");
  const by = { recent,
               company:(a,b)=> (a.company||"").localeCompare(b.company||""),
               location:(a,b)=> primaryLoc(a).localeCompare(primaryLoc(b)),
               // highest score first; unscored (null) sink to the bottom; ties → newest
               score:(a,b)=> ((b.score??-1)-(a.score??-1)) || recent(a,b) };
  v.sort(by[k]);

  // paginate the sorted/filtered set (PAGE clamped in case the set shrank)
  const total = v.length;
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  if (PAGE > pages) PAGE = pages;
  const start = (PAGE - 1) * PAGE_SIZE;
  const pageItems = v.slice(start, start + PAGE_SIZE);
  render(pageItems);
  renderPager(total, pages);

  // recency toggle only meaningful for the inbox
  const isInbox = LANE === "inbox";
  $("#recency").style.display = isInbox ? "" : "none";
  const older = (!isInbox || SHOW_ALL) ? 0 : JOBS.filter(j =>
    STATUS_SETS.inbox(j.status) && j.first_seen &&
    (now - new Date(j.first_seen).getTime()) > RECENT_MS).length;
  $("#recency").textContent = SHOW_ALL ? "Showing all" : `Recent 48h${older?` (+${older} older)`:""}`;
  $("#recency").classList.toggle("on", isInbox && !SHOW_ALL);

  const af = activeFilterCount();
  $("#fbadge").style.display = af ? "" : "none"; $("#fbadge").textContent = af;
  const suffix = (isInbox && !SHOW_ALL) ? " · recent 48h" : "";
  const range = total > PAGE_SIZE ? ` · ${start + 1}–${start + pageItems.length}` : "";
  $("#ministat").innerHTML = `<b>${total}</b> match${total === 1 ? "" : "es"}${range}${suffix}`;
}
// Windowed page tokens: always first + last, a window (±delta) around current,
// "…" for gaps. e.g. cur=8/20 → [1,"…",7,8,9,"…",20]; small totals show every page.
function pageTokens(cur, total, delta=1){
  const out = [1], left = Math.max(2, cur-delta), right = Math.min(total-1, cur+delta);
  // "…" only for a gap of 2+; a single hidden page is shown as its number (same width).
  if (left > 2) out.push(left === 3 ? 2 : "…");
  for (let i=left; i<=right; i++) out.push(i);
  if (right < total-1) out.push(right === total-2 ? total-1 : "…");
  if (total > 1) out.push(total);
  return out;
}
function renderPager(total, pages){
  const p = $("#pager");
  if (total <= PAGE_SIZE) { p.style.display = "none"; p.innerHTML = ""; return; }
  p.style.display = "flex";
  const nav = (lbl, to, dis, title) =>
    `<button class="pg nav" data-page="${to}" ${dis?"disabled":""} title="${title}">${lbl}</button>`;
  const nums = pageTokens(PAGE, pages).map(t =>
    t === "…" ? `<span class="pg gap">…</span>`
              : `<button class="pg${t===PAGE?" on":""}" data-page="${t}" aria-current="${t===PAGE}">${t}</button>`
  ).join("");
  p.innerHTML = nav("‹", PAGE-1, PAGE<=1, "Previous") + nums + nav("›", PAGE+1, PAGE>=pages, "Next");
}
function setPage(n){
  PAGE = n; viewJobs();  // viewJobs clamps PAGE to the valid range
  $("#list").scrollIntoView({ behavior: "smooth", block: "start" });  // start the new page at the top
}
function salaryStr(j) {
  const k = n => "£" + Math.round(n/1000) + "k";
  const lo = j.salary_min, hi = j.salary_max;
  if (lo && hi) return lo === hi ? k(lo) : `${k(lo)}–${k(hi)}`;
  if (hi) return `≤ ${k(hi)}`;
  if (lo) return `${k(lo)}+`;
  return "";
}
function scoreBand(s){ return s == null ? "" : s >= 7 ? "hi" : s >= 5 ? "mid" : "lo"; }
function render(list) {
  $("#list").innerHTML = list.map(j => {
    const sal = salaryStr(j);
    const hasScore = j.score != null;
    const band = scoreBand(j.score);
    const fresh = j.first_seen && (Date.now()-new Date(j.first_seen).getTime() < 86400000);
    const seen = j.status === "viewed" ? " seen" : "";
    return `<div class="job${band ? " sb-"+band : ""}${seen}">
      <div class="jobhead">
        ${hasScore ? `<span class="score s-${band}">${Math.round(j.score)}</span>` : ""}
        <a class="joblink" data-jid="${esc(j.job_id)}" href="${esc(j.url)}"
           target="_blank" rel="noopener">${esc(j.title)}</a>
        <span class="cardacts">
          ${SPIN.has(j.job_id)
            ? `<button class="mini spin" disabled title="Queued for scoring…">⏳</button>`
            : `<button class="mini" data-jid="${esc(j.job_id)}"
                 title="${hasScore ? "Re-score" : "Score"} this job (1 Claude call)">✨</button>`}
          ${j.status === "archived"
            ? `<button class="mini" data-restore="${esc(j.job_id)}" title="Restore to review">↩</button>`
            : `<button class="mini dismiss" data-dismiss="${esc(j.job_id)}" title="Not interested — hide">✕</button>`}
        </span>
      </div>
      <div class="meta">
        <span class="co">${esc(j.company)}</span>
        <span class="pill">${esc(primaryLoc(j))}${locExtra(j)}</span>
        ${sal ? `<span class="pill">${sal}</span>` : ""}
        <span class="pill">${esc(j.source)}</span>
        ${j.status && j.status !== "new" && j.status !== "viewed"
          ? `<span class="pill">${esc(j.status)}</span>` : ""}
        <span>${ago(j.first_seen)}</span>
        ${fresh ? '<span class="pill new">NEW</span>' : ""}
      </div>
      ${j.eval_reason ? `<div class="reason">${esc(j.eval_reason)}</div>` : ""}
    </div>`;
  }).join("") || emptyState();
}
function emptyState(){
  const msg = { inbox:"Inbox is clear — hit 🛰 Scan to pull new jobs.",
    applied:"Nothing applied yet.", rejected:"Nothing rejected yet.",
    archived:"Nothing hidden.", all:"No jobs yet — hit 🛰 Scan." }[LANE] || "No jobs.";
  return `<div class="empty">${msg}</div>`;
}

async function fetchJobs(resetPage=false) {
  // Search (incl. JD/tech-stack) is server-side; the q is sent to /api/jobs.
  // `resetPage` only from the search box — the triage poller reuses this and must
  // NOT yank a browsing user back to page 1 on every refresh.
  if (resetPage) PAGE = 1;
  const q = $("#q").value.trim();
  const url = "/api/jobs?limit=500" + (q ? "&q=" + encodeURIComponent(q) : "");
  JOBS = (await (await api(url)).json()).jobs || [];
  // a spinning single is done once its score differs from the baseline (or it's gone)
  for (const [jid, base] of SPIN) {
    const j = JOBS.find(x => x.job_id === jid);
    if (!j || j.score !== base) SPIN.delete(jid);
  }
  fillFilter($("#floc"), "All", JOBS.flatMap(j => j.locations || []));
  fillFilter($("#fsource"), "All", JOBS.map(j => j.source));
  viewJobs();
}
async function load() {
  if (!TOKEN) return showAuth("Enter your API token to view jobs.");
  $("#auth").style.display="none";
  try {
    FUNNEL = await (await api("/api/funnel")).json();
    renderLanes();
    await fetchJobs();
    syncTriage();  // restore progress line + button state if a run is in flight
  } catch(e){ if (e.message!=="auth") $("#msg").textContent = "Error: "+e.message; }
}

// --- views (jobs / tracker / config / rubric / usage) ---
let VIEW = "jobs";
const LOADERS = { jobs: load, tracker: loadTracker, config: loadConfig, rubric: loadRubric, usage: loadUsage };
function showView(v) {
  VIEW = v;
  $("#jobsView").style.display    = v==="jobs"    ? "" : "none";
  $("#trackerView").style.display = v==="tracker" ? "" : "none";
  $("#configView").style.display  = v==="config"  ? "" : "none";
  $("#rubricView").style.display  = v==="rubric"  ? "" : "none";
  $("#usageView").style.display   = v==="usage"   ? "" : "none";
  document.querySelectorAll(".tab").forEach(b => b.classList.toggle("on", b.dataset.view===v));
}
function refreshView(){ (LOADERS[VIEW] || load)(); }

// --- config editor ---
async function loadConfig() {
  if (!TOKEN) return showAuth("Enter your API token to edit config.");
  $("#cfgMsg").textContent = "loading…";
  try {
    $("#cfg").value = await (await api("/api/config")).text();
    $("#cfgMsg").textContent = "";
  } catch(e){ if (e.message!=="auth") $("#cfgMsg").textContent = "Error: "+e.message; }
}
async function saveConfig() {
  $("#cfgMsg").textContent = "saving…";
  try {
    const r = await api("/api/config", {
      method:"POST", headers:{ "content-type":"text/plain" }, body: $("#cfg").value });
    const data = await r.json().catch(()=>({}));
    if (r.ok) $("#cfgMsg").textContent = "✅ saved — applies on next scan ("+(data.sources||[]).join(", ")+")";
    else $("#cfgMsg").textContent = "❌ " + (data.detail || ("HTTP "+r.status));  // 400 = invalid YAML
  } catch(e){ if (e.message!=="auth") $("#cfgMsg").textContent = "Error: "+e.message; }
}

// --- rubric editor ---
async function loadRubric() {
  if (!TOKEN) return showAuth("Enter your API token to edit the rubric.");
  $("#rubMsg").textContent = "loading…";
  try {
    $("#rubric").value = await (await api("/api/rubric")).text();
    $("#rubMsg").textContent = "";
  } catch(e){ if (e.message!=="auth") $("#rubMsg").textContent = "Error: "+e.message; }
}
async function saveRubric() {
  $("#rubMsg").textContent = "saving…";
  try {
    const r = await api("/api/rubric", {
      method:"POST", headers:{ "content-type":"text/plain" }, body: $("#rubric").value });
    $("#rubMsg").textContent = r.ok ? "✅ saved — used by the next ✨ Analyze run" : "❌ HTTP "+r.status;
  } catch(e){ if (e.message!=="auth") $("#rubMsg").textContent = "Error: "+e.message; }
}

// --- tracker view: horizontal kanban board (Saved → Applied → Rejected) ---
const STAGES = [
  { key: "saved",    label: "🔖 Saved",    cls: "saved",
    moves: [["applied","✅ Applied"], ["rejected","🚫 Reject"], ["new","↩ Inbox"]] },
  { key: "applied",  label: "✅ Applied",  cls: "applied",
    moves: [["rejected","🚫 Rejected"], ["new","↩ Inbox"]] },
  { key: "rejected", label: "🚫 Rejected", cls: "rejected",
    moves: [["saved","🔖 Save"], ["new","↩ Inbox"]] },
];
function trackerCard(j, moves) {
  const band = scoreBand(j.score);
  const sc = j.score != null ? `<span class="score s-${band}">${Math.round(j.score)}</span> ` : "";
  const btns = moves.map(([st, lbl]) =>
    `<button class="btn ghost" data-trk="${esc(j.job_id)}" data-st="${st}">${lbl}</button>`).join("");
  return `<div class="job${band ? " sb-"+band : ""}" draggable="true" data-card="${esc(j.job_id)}">
    <div class="jobhead">${sc}
      <a class="joblink" draggable="false" data-jid="${esc(j.job_id)}" href="${esc(j.url)}"
         target="_blank" rel="noopener">${esc(j.title)}</a></div>
    <div class="meta"><span class="co">${esc(j.company)}</span>
      <span class="pill">${esc(primaryLoc(j))}${locExtra(j)}</span>
      <span>${ago(j.first_seen)}</span></div>
    <div class="trk-acts">${btns}</div>
  </div>`;
}
async function loadTracker() {
  if (!TOKEN) return showAuth("Enter your API token to view the tracker.");
  $("#trkMsg").textContent = "loading…";
  try {
    JOBS = (await (await api("/api/jobs?limit=500")).json()).jobs || [];  // keep cache fresh
    const recent = (a,b) => (b.first_seen||"").localeCompare(a.first_seen||"");
    $("#trkBox").innerHTML = STAGES.map(s => {
      const items = JOBS.filter(j => j.status === s.key).sort(recent);
      const body = items.length
        ? items.map(j => trackerCard(j, s.moves)).join("")
        : `<div class="kcol-empty">Nothing here yet.</div>`;
      return `<div class="kcol ${s.cls}" data-status="${s.key}">
        <div class="kcol-head">${s.label}<span class="seg-n">${items.length}</span></div>
        <div class="kcol-body">${body}</div>
      </div>`;
    }).join("");
    $("#trkMsg").textContent = "";
  } catch(e){ if (e.message!=="auth") $("#trkMsg").textContent = "Error: "+e.message; }
}
$("#trkBox").onclick = (e) => {
  const b = e.target.closest("button[data-trk]");
  if (b) markStatus(b.dataset.trk, b.dataset.st);  // refreshView re-renders the tracker
};

// Drag a card between columns (desktop/mouse). The move buttons stay as the touch
// fallback (HTML5 DnD doesn't fire on most mobile browsers). Delegated on #trkBox.
let DRAG_JID = null;
const clearDrop = () => document.querySelectorAll(".kcol.drop").forEach(c => c.classList.remove("drop"));
$("#trkBox").addEventListener("dragstart", (e) => {
  const card = e.target.closest("[data-card]"); if (!card) return;
  DRAG_JID = card.dataset.card;
  e.dataTransfer.effectAllowed = "move";
  try { e.dataTransfer.setData("text/plain", DRAG_JID); } catch(_){}  // Firefox needs a payload
  card.classList.add("dragging");
});
$("#trkBox").addEventListener("dragend", (e) => {
  const card = e.target.closest("[data-card]"); if (card) card.classList.remove("dragging");
  DRAG_JID = null; clearDrop();
});
$("#trkBox").addEventListener("dragover", (e) => {
  const col = e.target.closest(".kcol"); if (!col || !DRAG_JID) return;
  e.preventDefault(); e.dataTransfer.dropEffect = "move";   // allow the drop
  if (!col.classList.contains("drop")) { clearDrop(); col.classList.add("drop"); }
});
$("#trkBox").addEventListener("drop", (e) => {
  const col = e.target.closest(".kcol"); if (!col || !DRAG_JID) return;
  e.preventDefault();
  const jid = DRAG_JID, target = col.dataset.status;
  DRAG_JID = null; clearDrop();
  const j = JOBS.find(x => x.job_id === jid);
  if (j && j.status !== target) markStatus(jid, target);   // no-op if dropped on its own column
});

// --- usage view ---
function fmtTok(n){ n=n||0; return n>=1000 ? (n/1000).toFixed(1)+"k" : ""+n; }
async function loadUsage() {
  if (!TOKEN) return showAuth("Enter your API token to view usage.");
  $("#useMsg").textContent = "loading…";
  try {
    const u = await (await api("/api/usage")).json();
    const t = u.totals;
    // claude-cli spends Pro quota (CALLS), not tokens/$ — calls is the real meter.
    const apiCost = (u.by_engine||[]).filter(e => e.engine==="anthropic")
                      .reduce((s,e) => s+(e.cost_usd||0), 0);
    $("#useTotals").innerHTML =
      `<div class="chip"><b>${t.calls}</b><span>calls</span></div>`+
      `<div class="chip"><b>${t.runs}</b><span>runs</span></div>`+
      `<div class="chip"><b>${t.scored}</b><span>scored</span></div>`+
      (apiCost>0 ? `<div class="chip"><b>$${apiCost.toFixed(4)}</b><span>api $</span></div>` : "");
    const rows = (u.runs||[]).map(r => {
      const calls = (r.scored||0)+(r.errors||0);
      const cli = (r.engine||"").indexOf("cli") >= 0;
      const inTok = (r.input_tokens||0)+(r.cache_read_tokens||0)+(r.cache_write_tokens||0);
      const meter = cli ? '<span class="muted">Pro</span>' : `$${(r.cost_usd||0).toFixed(4)}`;
      const flag = r.note==="auth failed" ? '<span class="warn">⛔ not logged in</span>'
                 : r.budget_hit ? '<span class="warn">⛔ limit</span>'
                 : (r.errors ? r.errors+" err" : "");
      return `<tr>
        <td>${ago(r.started_at)||"—"}</td><td>${esc(r.engine||r.stage)}</td>
        <td>${calls}</td><td>${r.scored}/${r.jobs}</td>
        <td>${fmtTok(inTok)} / ${fmtTok(r.output_tokens)}</td>
        <td>${meter}</td><td>${flag}</td></tr>`;
    }).join("");
    $("#useBox").innerHTML = rows
      ? `<table class="usage"><tr><th>when</th><th>engine</th><th>calls</th>`
        + `<th>scored</th><th>tok in/out</th><th>cost</th><th></th></tr>${rows}</table>`
      : '<div class="empty">No LLM runs yet — hit ✨ Analyze.</div>';
    $("#useMsg").textContent = "";
  } catch(e){ if (e.message!=="auth") $("#useMsg").textContent = "Error: "+e.message; }
}

// --- triage queue (✨ Analyze) ---
// Batch (Analyze button) and per-card ✨ both POST here; the server QUEUES them
// (one worker, one at a time). SPIN tracks which single job_ids are in flight so
// their card ✨ shows a spinner; the batch button is disabled while a batch is queued.
const SPIN = new Map();     // job_id -> baseline score; cleared when a new score lands
let POLL = null;            // active status poller (null when idle)
async function enqueueTriage(target) {
  try {
    const r = await api("/api/analyze", {
      method:"POST", headers:{ "content-type":"application/json" },
      body: JSON.stringify({ mode:"triage", target }) });
    if (r.status===409) { $("#msg").textContent = "Triage queue is full — try again shortly."; return null; }
    return await r.json().catch(()=>({}));
  } catch(e){ return null; }
}
function startPoll(){ if (!POLL) pollAnalyze(); }
async function syncTriage() {  // on load: reflect any in-flight run without an extra jobs fetch when idle
  try {
    const s = await (await api("/api/analyze")).json();
    setBatchBusy(!!s.batch_active);
    setStopVisible(s.running || (s.queued||0) > 0);
    if (s.running || s.queued) startPoll();
  } catch(e){}
}
function setBatchBusy(busy){
  const b = $("#analyze");
  b.disabled = busy; b.style.opacity = busy ? .55 : "";
  b.style.cursor = busy ? "default" : "";
}
function setStopVisible(show){ $("#stopAnalyze").style.display = show ? "" : "none"; }
async function pollAnalyze() {
  POLL = true;
  try {
    const s = await (await api("/api/analyze")).json();
    const c = s.current, q = s.queued||0;
    setBatchBusy(!!s.batch_active);
    setStopVisible(s.running || q > 0);   // something to halt
    // live progress line
    if (s.stopping) {
      $("#msg").textContent = "⏹ Halting after the current job…";
    } else if (s.running && c) {
      const what = c.kind==="batch" ? "Triaging" : "Scoring";
      const tot = c.total==null ? "…" : c.total;
      $("#msg").textContent = `✨ ${what} ${c.scored||0}/${tot}`
        + (c.errors ? ` (${c.errors} err)` : "") + (q ? ` · ${q} queued` : "");
    } else if (q) {
      $("#msg").textContent = `✨ ${q} queued…`;
    }
    await fetchJobs();  // reflect new scores + clear finished spinners (see render/SPIN)
    if (s.running || q) { POLL = setTimeout(pollAnalyze, 1500); return; }
    // idle: queue drained — settle the message from the last run
    POLL = null; setBatchBusy(false); setStopVisible(false);
    const last = s.last || {};
    if (last.auth_failed)
      $("#msg").innerHTML = '<span class="warn">⛔ Claude not logged in — set '
        + 'CLAUDE_CODE_OAUTH_TOKEN (claude setup-token) and redeploy.</span>';
    else if (last.budget_hit)
      $("#msg").innerHTML = '<span class="warn">⛔ Out of budget / rate limited — triage stopped.</span>';
    else if (last.cancelled)
      $("#msg").textContent = `⏹ Halted — scored ${last.totals.scored} before stopping.`;
    else if (last.totals)
      $("#msg").textContent = `✨ Done — scored ${last.totals.scored} (${last.totals.errors||0} err)`;
  } catch(e){ POLL = null; }
}

// --- wiring ---
document.querySelectorAll(".tab").forEach(b => b.onclick = () => { showView(b.dataset.view); refreshView(); });
$("#save").onclick = () => { TOKEN = $("#token").value.trim(); localStorage.setItem("jr_token", TOKEN); refreshView(); };
$("#refresh").onclick = refreshView;
$("#trkReload").onclick = loadTracker;
$("#cfgSave").onclick = saveConfig;
$("#cfgReload").onclick = loadConfig;
$("#rubSave").onclick = saveRubric;
$("#rubReload").onclick = loadRubric;
$("#useReload").onclick = loadUsage;
$("#sort").onchange = applyFilters;
$("#filtersToggle").onclick = () => $("#moreFilters").classList.toggle("open");
let qTimer;  // debounce server-side search so we don't refetch on every keystroke
$("#q").oninput = () => { clearTimeout(qTimer); qTimer = setTimeout(() => fetchJobs(true), 300); };
$("#floc").onchange = applyFilters;
$("#fsource").onchange = applyFilters;
$("#fsalary").oninput = applyFilters;
$("#recency").onclick = () => { SHOW_ALL = !SHOW_ALL; applyFilters(); };
$("#pager").onclick = (e) => {
  const b = e.target.closest("button[data-page]");
  if (b && !b.disabled) setPage(parseInt(b.dataset.page, 10));
};
$("#scan").onclick = async () => {
  try {
    const r = await api("/api/scan", { method:"POST" });
    $("#msg").textContent = r.status===409 ? "A scan is already running…" : "🛰 Scan started — refresh in a bit.";
  } catch(e){}
};
$("#deepscan").onclick = async () => {
  try {
    const r = await api("/api/scan?deep=1", { method:"POST" });
    $("#msg").textContent = r.status===409 ? "A scan is already running…"
      : "🔭 Deep scan started — pulling the full window. Refresh in a bit.";
  } catch(e){}
};

// --- apply tracking ---
// When a job link is opened, remember it; when the user returns to this tab, ask
// whether they applied. Works on PC (new tab) and mobile (app switch) via the
// visibilitychange event, with a focus fallback.
let pendingApply = null;
function setPending(p) {  // persist so a same-tab navigation (mobile) survives reload
  pendingApply = p;
  try { p ? localStorage.setItem("jr_pending", JSON.stringify({...p, ts:Date.now()}))
          : localStorage.removeItem("jr_pending"); } catch(e){}
}
(function restorePending(){
  try {
    const p = JSON.parse(localStorage.getItem("jr_pending") || "null");
    if (p && Date.now() - (p.ts||0) < 1800000) pendingApply = p;  // 30-min window
    else localStorage.removeItem("jr_pending");
  } catch(e){}
})();
$("#list").onclick = (e) => {
  const r = e.target.closest("button[data-restore]");
  if (r) { markStatus(r.dataset.restore, "new"); return; }                            // ↩ unarchive
  const d = e.target.closest("button.dismiss");
  if (d && d.dataset.dismiss) { markStatus(d.dataset.dismiss, "archived"); return; }  // ✕ hide
  const b = e.target.closest("button.mini");
  if (b && b.dataset.jid) {                                                           // ✨ score (queued)
    const jid = b.dataset.jid, j = JOBS.find(x => x.job_id === jid);
    SPIN.set(jid, j ? j.score : null);           // baseline; spinner until score changes
    viewJobs();                                   // instant spinner feedback
    enqueueTriage([jid]).then(d => { if (!d || (!d.queued && !d.duplicate)) SPIN.delete(jid); startPoll(); });
    return;
  }
  const a = e.target.closest("a.joblink");
  if (a && a.dataset.jid) {  // opening a job → mark viewed (default) + remember it
    const j = JOBS.find(x => x.job_id === a.dataset.jid);
    if (j) { setPending({ jid: j.job_id, co: j.company, ti: j.title }); markViewedSilently(j); }
    // don't preventDefault — let the link open
  }
};
// Opening a job's link IS the "viewed" signal — mark it silently (no popup button
// for it any more). Only advances untouched 'new' jobs; leaves saved/applied/etc.
function markViewedSilently(j){
  if (!j || j.status !== "new") return;
  j.status = "viewed";                          // optimistic local update (dims the card)
  api("/api/status", { method:"POST", headers:{ "content-type":"application/json" },
    body: JSON.stringify({ job_id: j.job_id, status: "viewed" }) }).catch(()=>{});
  if (VIEW === "jobs") viewJobs();
}
function showApplyModal() {
  if (!pendingApply || $("#applyModal").style.display === "flex") return;
  $("#applyJob").textContent = (pendingApply.co || "") + " — " + (pendingApply.ti || "");
  $("#applyModal").style.display = "flex";
}
function closeApplyModal() { $("#applyModal").style.display = "none"; setPending(null); }
const STATUS_MSG = { applied:"✅ Applied → see the 📌 Tracker", viewed:"👀 Marked seen — stays in your inbox, dimmed",
  saved:"🔖 Saved → see the 📌 Tracker", rejected:"🚫 Rejected",
  archived:"🚫 Hidden (open the Archived lane to find it)", new:"↩ Back in the review list" };
async function markStatus(jid, status) {
  try {
    await api("/api/status", { method:"POST", headers:{ "content-type":"application/json" },
      body: JSON.stringify({ job_id: jid, status }) });
    $("#msg").textContent = (STATUS_MSG[status] || "Updated") + ".";
    refreshView();  // re-render the active view (Jobs inbox or Tracker)
  } catch(e){}
}
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible") showApplyModal();
});
window.addEventListener("focus", showApplyModal);  // fallback for browsers that skip the above
$("#amApplied").onclick = () => { const j = pendingApply; closeApplyModal(); if (j) markStatus(j.jid, "applied"); };
$("#amSaved").onclick   = () => { const j = pendingApply; closeApplyModal(); if (j) markStatus(j.jid, "saved"); };
$("#amArchive").onclick = () => { const j = pendingApply; closeApplyModal(); if (j) markStatus(j.jid, "archived"); };
$("#amDismiss").onclick = closeApplyModal;
$("#applyModal").onclick = (e) => { if (e.target.id === "applyModal") closeApplyModal(); };  // tap backdrop

if (pendingApply) setTimeout(showApplyModal, 500);  // restored from a same-tab return
$("#analyze").onclick = async () => {
  if ($("#analyze").disabled) return;   // a batch is already queued/running
  // count untriaged new jobs so we can warn before firing a big batch (each = 1
  // Claude call against your Pro quota; the server also caps at analysis.max_jobs).
  const pending = JOBS.filter(j => j.status==="new" && j.score==null).length;
  if (!pending) { $("#msg").textContent = "Nothing new to triage."; return; }
  if (pending > 10 && !confirm(
      `Triage ${pending} new jobs? That's up to ${pending} Claude calls against your `
      + `Pro quota (capped by analysis.max_jobs). Use a card's ✨ for one at a time.`)) return;
  setBatchBusy(true);                   // block the button immediately
  const d = await enqueueTriage("all_pending");
  if (d && (d.queued || d.duplicate)) { $("#msg").textContent = "✨ Batch queued…"; setStopVisible(true); startPoll(); }
  else setBatchBusy(false);             // enqueue failed (queue full) — unblock
};
$("#stopAnalyze").onclick = async () => {
  const b = $("#stopAnalyze"); b.disabled = true;
  $("#msg").textContent = "⏹ Halting after the current job…";
  try { await api("/api/analyze/stop", { method:"POST" }); } catch(e){}
  b.disabled = false; startPoll();      // poll reflects the wind-down + final message
};
renderLanes();
load();
</script>
</body>
</html>
"""
