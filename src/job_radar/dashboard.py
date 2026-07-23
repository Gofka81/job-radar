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
         -webkit-font-smoothing:antialiased; overflow-x:hidden; }
  /* stop horizontal swipe (kanban) rubber-banding the viewport, which drags the fixed
     bottom nav around on iOS. Contain the sideways scroll to the board itself. */
  html, body { overscroll-behavior-x:none; }
  button, select, input, textarea { font-family:inherit; }

  /* ---- app bar ---- */
  header { position:sticky; top:0; z-index:20; background:var(--bg);
           border-bottom:1px solid var(--line); }
  .bar { display:flex; align-items:center; gap:10px; padding:10px 16px;
         max-width:860px; margin:0 auto; }
  .brand { font-size:17px; font-weight:750; letter-spacing:-.01em; margin-right:2px;
           white-space:nowrap; display:inline-flex; align-items:center; gap:8px; }
  .brand-ico { width:26px; height:26px; border-radius:7px; background:var(--accent); color:#fff;
               display:inline-flex; align-items:center; justify-content:center; flex:0 0 auto; }
  /* inline Lucide SVGs render as block so they centre cleanly in their host */
  [data-icon] svg, .ico svg { display:block; }
  .iconbtn svg { width:17px; height:17px; }
  .brand-ico svg { width:16px; height:16px; }
  .set-row .ico svg { width:17px; height:17px; }
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
            scroll-snap-type:x proximity; -webkit-overflow-scrolling:touch; overscroll-behavior-x:contain; }
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

  /* ---- settings gear + iOS-style sub-pages ---- */
  .iconbtn.on { color:var(--accent); border-color:var(--accent); }
  .set-menu > .st-h { display:block; font-size:18px; font-weight:750; margin-bottom:12px; text-align:center; }
  .set-menu-card { background:var(--card); border:1px solid var(--line); border-radius:12px;
                   box-shadow:var(--shadow); overflow:hidden; }
  .set-row { display:flex; align-items:center; gap:12px; width:100%; padding:13px 14px; border:0;
             border-bottom:1px solid var(--line); background:none; cursor:pointer; text-align:left;
             color:var(--fg); font-size:15px; }
  .set-row:last-child { border-bottom:0; }
  .set-row:hover { background:var(--pill); }
  .set-row .ico { width:34px; height:34px; border-radius:9px; background:var(--pill); color:var(--pill-fg);
                  display:inline-flex; align-items:center; justify-content:center; flex:0 0 auto; font-size:16px; }
  .set-row .txt { flex:1; min-width:0; }
  .set-row .txt b { display:block; font-size:14.5px; font-weight:700; }
  .set-row .txt span { display:block; font-size:12px; color:var(--muted); }
  .set-row .chev { color:var(--muted); flex:0 0 auto; line-height:1; }
  .set-row .chev svg { width:18px; height:18px; }
  .set-head { display:flex; align-items:center; justify-content:center; position:relative;
              min-height:38px; margin-bottom:14px; }
  .set-head .st-title { font-size:18px; font-weight:750; text-align:center; }
  .set-back { position:absolute; left:0; top:50%; transform:translateY(-50%);
              display:inline-flex; align-items:center; gap:3px; background:none; border:0; cursor:pointer;
              color:var(--accent); font-size:14px; font-weight:600; padding:6px 10px 6px 4px; border-radius:8px; }
  .set-back:hover { background:var(--pill); }
  .set-block { background:var(--card); border:1px solid var(--line); border-radius:11px; padding:16px;
               box-shadow:var(--shadow); margin-bottom:12px; }
  .set-block h3 { margin:0 0 10px; font-size:14.5px; font-weight:700; }
  .seg { display:inline-flex; gap:4px; background:var(--bg); border:1px solid var(--line);
         border-radius:9px; padding:4px; }
  .seg button { border:0; background:none; color:var(--muted); border-radius:6px; padding:7px 15px;
                font-size:13px; font-weight:650; cursor:pointer; }
  .seg button.on { background:var(--accent); color:var(--accent-fg); }

  /* ---- config form (per-connector cards) ---- */
  .cfg-mode { display:flex; justify-content:center; margin-bottom:12px; }
  .cfg-label { font-size:10.5px; font-weight:700; letter-spacing:.07em; text-transform:uppercase;
               color:var(--muted); margin:16px 2px 8px; }
  .csrc { background:var(--card); border:1px solid var(--line); border-radius:11px; margin-bottom:8px;
          box-shadow:var(--shadow); overflow:hidden; }
  .csrc-head { display:flex; align-items:center; gap:11px; padding:11px 13px; cursor:pointer; }
  .csrc-head .caret { color:var(--muted); flex:0 0 auto; transition:transform .15s ease; }
  .csrc-head .caret svg { width:13px; height:13px; display:block; }
  .csrc.open .csrc-head .caret { transform:rotate(90deg); }
  .csrc-ico { width:30px; height:30px; border-radius:8px; background:var(--pill); color:var(--pill-fg);
              display:inline-flex; align-items:center; justify-content:center; flex:0 0 auto; }
  .csrc-ico svg { width:15px; height:15px; }
  .csrc-name { font-weight:700; font-size:14.5px; }
  .csrc-sub { color:var(--muted); font-size:12px; margin-top:1px; white-space:nowrap;
              overflow:hidden; text-overflow:ellipsis; }
  .csrc-badge { margin-left:auto; font-size:11px; font-weight:700; padding:2px 8px; border-radius:20px;
                background:var(--pill); color:var(--muted); flex:0 0 auto; }
  .csrc.en .csrc-badge { background:color-mix(in srgb,var(--new) 16%,transparent); color:var(--new); }
  .csrc-body { display:none; border-top:1px solid var(--line); padding:13px; flex-direction:column; gap:12px; }
  .csrc.open .csrc-body { display:flex; }
  /* iOS toggle switch */
  .sw { position:relative; width:42px; height:24px; flex:0 0 auto; }
  .sw input { position:absolute; opacity:0; width:100%; height:100%; margin:0; cursor:pointer; }
  .sw .tr { position:absolute; inset:0; background:var(--line); border-radius:20px; transition:.15s; }
  .sw .tr::after { content:""; position:absolute; top:3px; left:3px; width:18px; height:18px;
                   background:#fff; border-radius:50%; transition:.15s; box-shadow:0 1px 2px rgba(0,0,0,.3); }
  .sw input:checked + .tr { background:var(--accent); }
  .sw input:checked + .tr::after { transform:translateX(18px); }
  .sw input:focus-visible + .tr { outline:2px solid var(--accent); outline-offset:2px; }
  /* fields + chip inputs */
  .field { display:flex; flex-direction:column; gap:5px; }
  .field > label { font-size:11.5px; font-weight:650; color:var(--muted); }
  .field .help { font-size:11px; color:var(--muted); font-weight:400; }
  .fgrid { display:grid; grid-template-columns:1fr 1fr; gap:10px 12px; }
  .field input { background:var(--bg); border:1px solid var(--line); border-radius:8px;
                 padding:8px 10px; font-size:13px; min-height:36px; }
  .taginput { background:var(--bg); border:1px solid var(--line); border-radius:8px; padding:6px 7px;
              display:flex; flex-wrap:wrap; gap:5px; align-items:center; min-height:36px; }
  .tag { background:var(--pill); color:var(--pill-fg); border-radius:6px; padding:2px 4px 2px 8px;
         font-size:12px; font-weight:600; display:inline-flex; align-items:center; gap:4px; }
  .tag.neg { background:color-mix(in srgb,var(--danger) 14%,transparent); color:var(--danger); }
  .tag b { cursor:pointer; opacity:.55; font-weight:700; padding:0 2px; }
  .tag b:hover { opacity:1; }
  .taginput input { flex:1; min-width:80px; border:0; background:none; font-size:12.5px; padding:3px;
                    min-height:26px; box-shadow:none; }
  .taginput input:focus { outline:none; }
  .field select { background:var(--bg); border:1px solid var(--line); border-radius:8px;
                  padding:8px 10px; font-size:13px; min-height:36px; }
  .field.full { grid-column:1 / -1; }
  .locrow { display:flex; gap:7px; align-items:center; margin-bottom:6px; }
  .locrow .loc-where { flex:1; }
  .locrow .loc-dist { width:76px; }
  .locrow .loc-del { background:none; border:1px solid transparent; border-radius:7px; cursor:pointer;
                     width:32px; height:32px; flex:0 0 auto; color:var(--muted);
                     display:inline-flex; align-items:center; justify-content:center; }
  .locrow .loc-del:hover { border-color:var(--danger); color:var(--danger); }
  .locrow .loc-del svg { width:14px; height:14px; }
  .loc-add { background:none; border:1px dashed var(--line); color:var(--muted); border-radius:8px;
             padding:7px 11px; font-size:12.5px; font-weight:650; cursor:pointer; align-self:flex-start; }
  .loc-add:hover { border-color:var(--accent); color:var(--accent); }
  .cfg-check { display:flex; align-items:center; gap:10px; font-size:13px; font-weight:600; cursor:pointer; }
  .sched-row { display:flex; align-items:center; gap:12px; margin-bottom:9px; }
  .sched-row .cfg-check { flex:1; }
  .sched-row input { width:120px; background:var(--bg); border:1px solid var(--line); border-radius:8px;
                     padding:8px 10px; font-size:13px; min-height:36px; font-family:ui-monospace,Menlo,monospace; }
  .cfg-note { color:var(--muted); font-size:12px; }
  .savebar { position:sticky; bottom:0; z-index:10; display:flex; gap:10px; align-items:center;
             margin-top:14px; padding:12px 0 8px; flex-wrap:wrap;
             background:linear-gradient(to top, var(--bg) 66%, transparent); }

  /* ---- inline icons inside controls ---- */
  button.btn { display:inline-flex; align-items:center; justify-content:center; gap:6px; }
  .btn svg { width:15px; height:15px; }
  .btn.ghost svg { width:14px; height:14px; }
  .mini svg { width:15px; height:15px; }
  .kcol-head svg { width:16px; height:16px; }
  .modal-actions .btn svg { width:16px; height:16px; }
  .actions .btn span.lbl { line-height:1; }

  /* ---- scan split-button dropdown ---- */
  .scanwrap { position:relative; flex:none; }
  #scanBtn .caret svg { width:13px; height:13px; }
  .dropdown { position:absolute; right:0; top:calc(100% + 5px); z-index:40; background:var(--card);
              border:1px solid var(--line); border-radius:11px; box-shadow:0 8px 30px rgba(20,25,40,.16);
              min-width:214px; padding:5px; display:flex; flex-direction:column; gap:2px; }
  .dropitem { background:none; border:0; border-radius:8px; cursor:pointer; padding:9px 11px;
              font-size:14px; font-weight:600; text-align:left; color:var(--fg);
              display:flex; align-items:baseline; gap:8px; }
  .dropitem:hover { background:var(--pill); }
  .dropitem .sub { font-weight:400; color:var(--muted); font-size:12px; }

  /* ---- mobile bottom nav (shown ≤600px) ---- */
  .botnav { display:none; }

  @media (max-width:600px) {
    .bar { padding:9px 12px; gap:8px; }
    .brand { font-size:15px; }
    .wrap { padding:12px 12px 84px; }               /* room for the fixed bottom nav */
    .actions .btn span.lbl { display:none; }   /* icon-only actions on phones */
    .tabs { display:none; }                    /* primary nav moves to the bottom bar */
    #gearBtn { display:none; }                 /* Settings lives in the bottom nav on phones */
    /* kanban: one column at a time with a peek of the next; swipe between them */
    .kcol { flex-basis:84vw; min-width:84vw; }
    .pager .btn { flex:1; }
    .botnav { display:flex; position:fixed; bottom:0; left:0; right:0; z-index:40;
              background:var(--card); border-top:1px solid var(--line);
              padding:5px 8px calc(6px + env(safe-area-inset-bottom)); }
    .botnav button { flex:1; background:none; border:0; cursor:pointer; color:var(--muted);
                     font-size:11px; font-weight:650; display:flex; flex-direction:column;
                     align-items:center; gap:3px; padding:6px 0 4px; }
    .botnav button.on { color:var(--accent); }
    .botnav button .ico { font-size:19px; line-height:1; }
  }
</style>
</head>
<body>
<header>
  <div class="bar">
    <span class="brand"><span class="brand-ico" data-icon="radar"></span>job-radar</span>
    <nav class="tabs" id="tabs">
      <button class="tab on" data-view="jobs">Jobs</button>
      <button class="tab" data-view="tracker">Tracker</button>
    </nav>
    <button class="iconbtn" id="gearBtn" data-view="settings" data-icon="gear" title="Settings"></button>
  </div>
</header>

<div class="wrap">
  <div id="auth">
    <input id="token" type="password" placeholder="API token" autocomplete="off">
    <button class="btn primary" id="save">Save</button>
  </div>

  <!-- ============ JOBS ============ -->
  <div id="jobsView">
    <div class="toolbar">
      <div class="search">
        <input id="q" type="search" placeholder="Search title / company / JD — e.g. spark, airflow" autocomplete="off">
      </div>
      <div class="actions">
        <div class="scanwrap">
          <button class="btn" id="scanBtn" title="Scan for new jobs"><span data-icon="scan"></span><span class="lbl">Scan</span><span class="caret" data-icon="caret"></span></button>
          <div id="scanMenu" class="dropdown" style="display:none">
            <button class="dropitem" id="scan">Scan now<span class="sub">recent window</span></button>
            <button class="dropitem" id="deepscan">Deep scan<span class="sub">full window</span></button>
          </div>
        </div>
        <button class="btn" id="analyze" title="LLM triage of new jobs"><span data-icon="sparkles"></span><span class="lbl">Analyze</span></button>
        <button class="btn" id="stopAnalyze" title="Halt the running triage" style="display:none"><span data-icon="stop"></span><span class="lbl">Stop</span></button>
      </div>
    </div>

    <div class="lanes" id="lanes"></div>

    <div class="subbar">
      <button class="toggle" id="recency">Recent 48h</button>
      <span class="ministat" id="ministat"></span>
      <span class="spacer"></span>
      <button class="btn ghost" id="filtersToggle"><span data-icon="sliders"></span>Filters<span class="fbadge" id="fbadge" style="display:none">0</span></button>
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
      <button class="btn" id="trkReload"><span data-icon="refresh"></span>Reload</button>
      <span id="trkMsg" class="muted"></span>
    </div>
    <div class="drag-hint">↔ Drag a card between columns to change its stage — or use the buttons on each card.</div>
    <div id="trkBox" class="kanban"></div>
    <div class="hint">
      Your pipeline board — drag stages with the buttons on each card. <b>Saved</b> =
      shortlisted to apply (from a job link, or the popup after opening one). <b>Applied</b>
      and <b>Rejected</b> track the rest. Seen-but-untouched jobs stay in the Jobs inbox
      (dimmed); hidden ones live in the Jobs “Archived” lane.
    </div>
  </div>

  <!-- ============ SETTINGS ============ -->
  <div id="settingsView" style="display:none">
    <!-- menu -->
    <div id="setMenu" class="set-menu">
      <span class="st-h">Settings</span>
      <div class="set-menu-card">
        <button class="set-row" data-set="general"><span class="ico" data-icon="sliders"></span>
          <span class="txt"><b>General</b><span>Theme &amp; API token</span></span><span class="chev" data-icon="chevron"></span></button>
        <button class="set-row" data-set="config"><span class="ico" data-icon="wrench"></span>
          <span class="txt"><b>Config</b><span>Sources, filters &amp; scan settings</span></span><span class="chev" data-icon="chevron"></span></button>
        <button class="set-row" data-set="rubric"><span class="ico" data-icon="clipboard"></span>
          <span class="txt"><b>Rubric</b><span>Triage scoring policy</span></span><span class="chev" data-icon="chevron"></span></button>
        <button class="set-row" data-set="usage"><span class="ico" data-icon="chart"></span>
          <span class="txt"><b>Usage</b><span>LLM calls &amp; cost</span></span><span class="chev" data-icon="chevron"></span></button>
      </div>
    </div>

    <!-- sub-page shell -->
    <div id="setSection" style="display:none">
      <div class="set-head">
        <button class="set-back" id="setBack">‹ Settings</button>
        <span class="st-title" id="setTitle"></span>
      </div>

      <!-- General -->
      <div id="generalView" style="display:none">
        <div class="set-block">
          <h3>Appearance</h3>
          <div class="seg" id="themeSeg">
            <button data-theme="">System</button>
            <button data-theme="light">Light</button>
            <button data-theme="dark">Dark</button>
          </div>
          <div class="hint">System follows your device; Light and Dark override it.</div>
        </div>
        <div class="set-block">
          <h3>API token</h3>
          <div style="display:flex;gap:8px;align-items:center;max-width:480px">
            <input id="token2" type="password" autocomplete="off" placeholder="API token"
                   style="flex:1;background:var(--bg);border:1px solid var(--line);border-radius:9px;padding:9px 12px;min-height:38px;font-family:ui-monospace,Menlo,monospace">
            <button class="iconbtn" id="tokReveal" data-icon="eye" title="Show / hide token"></button>
            <button class="btn primary" id="save2">Save</button>
          </div>
          <div class="hint" id="tokMsg">Kept in this browser only.</div>
        </div>
        <div class="set-block">
          <h3>Scheduling</h3>
          <div class="sched-row">
            <label class="cfg-check"><span class="sw"><input type="checkbox" id="schScanEn"><span class="tr"></span></span> Scheduled crawling</label>
            <input id="schScanHours" placeholder="7-19/2">
          </div>
          <div class="sched-row">
            <label class="cfg-check"><span class="sw"><input type="checkbox" id="schTriageEn"><span class="tr"></span></span> Auto-triage (LLM)</label>
            <input id="schTriageHours" placeholder="3">
          </div>
          <div style="display:flex;gap:8px;align-items:center;margin-top:4px">
            <button class="btn primary" id="schSave">Save</button>
            <span class="hint" id="schMsg" style="margin:0"></span>
          </div>
          <div class="hint">Cron hour field — <code>7-19/2</code> = every 2h 07:00–19:00, <code>3</code> = 03:00 daily.
            Toggle off to halt. Triage spends Claude Pro quota per run — nightly (<code>3</code>) keeps it off your
            interactive hours. Seeded from env; edits apply live, no redeploy.</div>
        </div>
      </div>

      <!-- Config -->
      <div id="configView" style="display:none">
        <div class="cfg-mode">
          <div class="seg" id="cfgMode">
            <button class="on" data-mode="form">Form</button>
            <button data-mode="raw">Raw YAML</button>
          </div>
        </div>
        <!-- Form (rendered by renderCfgForm; edits line-patch the raw YAML below) -->
        <div id="cfgForm"></div>
        <!-- Raw YAML — the source of truth -->
        <div id="cfgRaw" style="display:none">
          <textarea id="cfg" spellcheck="false" autocapitalize="off" autocomplete="off"
                    placeholder="Loading config…"></textarea>
          <div class="hint">The full config.yml — the source of truth. Edits save to the server; the
            next scan picks them up (no redeploy). The Form patches values into this text.</div>
        </div>
        <div class="savebar">
          <button class="btn primary" id="cfgSave">Save config</button>
          <button class="btn" id="cfgReload"><span data-icon="refresh"></span>Reload</button>
          <span id="cfgMsg" class="muted"></span>
        </div>
      </div>

      <!-- Rubric -->
      <div id="rubricView" style="display:none">
        <div class="cfgbar">
          <button class="btn primary" id="rubSave">Save rubric</button>
          <button class="btn" id="rubReload"><span data-icon="refresh"></span>Reload</button>
          <span id="rubMsg" class="muted"></span>
        </div>
        <textarea id="rubric" spellcheck="false" autocapitalize="off" autocomplete="off"
                  placeholder="Loading rubric…"></textarea>
        <div class="hint">
          The 0–10 triage scoring policy (candidate profile). Saves to analysis/rubric.md —
          the next Analyze run uses it (no redeploy).
        </div>
      </div>

      <!-- Usage -->
      <div id="usageView" style="display:none">
        <div class="cfgbar">
          <button class="btn" id="useReload"><span data-icon="refresh"></span>Reload</button>
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
  </div>
</div>

<nav class="botnav" id="botnav">
  <button data-view="jobs" class="on"><span class="ico" data-icon="compass"></span>Jobs</button>
  <button data-view="tracker"><span class="ico" data-icon="kanban"></span>Tracker</button>
  <button data-view="settings"><span class="ico" data-icon="gear"></span>Settings</button>
</nav>

<div id="applyModal" class="modal" style="display:none">
  <div class="modal-card">
    <div class="modal-title">Did you apply?</div>
    <div id="applyJob" class="muted"></div>
    <div class="modal-actions">
      <button id="amApplied" class="btn primary"><span data-icon="check"></span>Applied</button>
      <button id="amSaved" class="btn"><span data-icon="bookmark"></span>Save for later</button>
      <button id="amArchive" class="btn"><span data-icon="ban"></span>Not interested (hide)</button>
      <button id="amDismiss" class="btn ghost">Not now</button>
    </div>
  </div>
</div>

<script>
const $ = s => document.querySelector(s);

// Inline Lucide icons (stroke, currentColor). Static chrome uses data-icon="name"
// placeholders painted by paintIcons(); dynamic markup can inject ICON.name directly.
const _svg = (p,s=16) => `<svg width="${s}" height="${s}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${p}</svg>`;
const ICON = {
  radar: _svg('<path d="M19.07 4.93A10 10 0 0 0 6.99 3.34"/><path d="M4 6h.01"/><path d="M2.29 9.62a10 10 0 1 0 19.02-1.27"/><path d="M16.24 7.76a6 6 0 1 0-8.01 8.91"/><path d="M12 18h.01"/><path d="M17.99 11.66a6 6 0 0 1-2.22 5.01"/><circle cx="12" cy="12" r="2"/><path d="m13.41 10.59 5.66-5.66"/>'),
  gear: _svg('<path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"/><circle cx="12" cy="12" r="3"/>'),
  compass: _svg('<circle cx="12" cy="12" r="10"/><polygon points="16.24 7.76 14.12 14.12 7.76 16.24 9.88 9.88 16.24 7.76"/>'),
  kanban: _svg('<path d="M6 5v11"/><path d="M10 5v6"/><path d="M14 5v14"/><path d="M18 5v9"/>'),
  sliders: _svg('<path d="M21 4h-7"/><path d="M10 4H3"/><path d="M21 12h-9"/><path d="M8 12H3"/><path d="M21 20h-5"/><path d="M12 20H3"/><path d="M14 2v4"/><path d="M8 10v4"/><path d="M16 18v4"/>'),
  wrench: _svg('<path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/>'),
  clipboard: _svg('<rect width="8" height="4" x="8" y="2" rx="1" ry="1"/><path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/><path d="M12 11h4"/><path d="M12 16h4"/><path d="M8 11h.01"/><path d="M8 16h.01"/>'),
  chart: _svg('<path d="M3 3v16a2 2 0 0 0 2 2h16"/><path d="M13 17V9"/><path d="M18 17V5"/><path d="M8 17v-3"/>'),
  chevron: _svg('<path d="m9 18 6-6-6-6"/>', 18),
  caret: _svg('<path d="m6 9 6 6 6-6"/>', 13),
  sparkles: _svg('<path d="M9.937 15.5A2 2 0 0 0 8.5 14.063l-6.135-1.582a.5.5 0 0 1 0-.962L8.5 9.936A2 2 0 0 0 9.937 8.5l1.582-6.135a.5.5 0 0 1 .963 0L14.063 8.5A2 2 0 0 0 15.5 9.937l6.135 1.581a.5.5 0 0 1 0 .964L15.5 14.063a2 2 0 0 0-1.437 1.437l-1.582 6.135a.5.5 0 0 1-.963 0z"/><path d="M20 3v4"/><path d="M22 5h-4"/>'),
  scan: _svg('<path d="M4 10a7.31 7.31 0 0 0 10 10Z"/><path d="m9 15 3-3"/><path d="M17 13a6 6 0 0 0-6-6"/><path d="M21 13A10 10 0 0 0 11 3"/>'),
  telescope: _svg('<path d="m10.065 12.493-6.18 1.318a.934.934 0 0 1-1.108-.702l-.537-2.15a1.07 1.07 0 0 1 .691-1.265l13.504-4.44"/><path d="m13.56 11.747 4.332-.924"/><path d="m16 21-3.105-6.21"/><path d="M16.485 5.94a2 2 0 0 1 1.455-2.425l1.09-.272a1 1 0 0 1 1.212.727l1.515 6.06a1 1 0 0 1-.727 1.213l-1.09.272a2 2 0 0 1-2.425-1.455z"/><path d="m6.158 8.633 1.114 4.456"/><path d="m8 21 3.105-6.21"/><circle cx="12" cy="13" r="2"/>'),
  stop: _svg('<circle cx="12" cy="12" r="10"/><rect width="6" height="6" x="9" y="9" rx="1"/>'),
  undo: _svg('<path d="M9 14 4 9l5-5"/><path d="M4 9h10.5a5.5 5.5 0 0 1 5.5 5.5a5.5 5.5 0 0 1-5.5 5.5H11"/>'),
  x: _svg('<path d="M18 6 6 18"/><path d="m6 6 12 12"/>'),
  check: _svg('<path d="M20 6 9 17l-5-5"/>'),
  bookmark: _svg('<path d="m19 21-7-4-7 4V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2v16z"/>'),
  ban: _svg('<circle cx="12" cy="12" r="10"/><path d="m4.9 4.9 14.2 14.2"/>'),
  refresh: _svg('<path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/><path d="M8 16H3v5"/>'),
  eye: _svg('<path d="M2.06 12.35a1 1 0 0 1 0-.7 10.75 10.75 0 0 1 19.88 0 1 1 0 0 1 0 .7 10.75 10.75 0 0 1-19.88 0"/><circle cx="12" cy="12" r="3"/>'),
  eyeOff: _svg('<path d="M10.73 5.08A10.74 10.74 0 0 1 21.94 11.65a1 1 0 0 1 0 .7 10.75 10.75 0 0 1-1.44 2.49"/><path d="M14.08 14.16a3 3 0 0 1-4.24-4.24"/><path d="M17.48 17.5A10.75 10.75 0 0 1 2.06 12.35a1 1 0 0 1 0-.7 10.75 10.75 0 0 1 4.45-5.14"/><path d="m2 2 20 20"/>'),
};
function paintIcons(root=document){ root.querySelectorAll("[data-icon]").forEach(e => {
  const n = e.dataset.icon; if (ICON[n]) e.innerHTML = ICON[n]; }); }
let TOKEN = localStorage.getItem("jr_token") || "";
let JOBS = [];          // last /api/jobs payload (up to 500, all statuses)
let FUNNEL = {};        // /api/funnel — TRUE per-status totals (not truncated)

// ---- theme (System / Light / Dark; persisted; set from the General settings page) ----
const THEME_KEY = "jr_theme";
function applyTheme(t){ const r=document.documentElement;
  if (t) r.dataset.theme = t; else r.removeAttribute("data-theme"); }
function setThemeSeg(t){ document.querySelectorAll("#themeSeg button")
  .forEach(b => b.classList.toggle("on", (b.dataset.theme||"") === (t||""))); }
applyTheme(localStorage.getItem(THEME_KEY) || "");

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
            ? `<button class="mini spin" disabled title="Queued for scoring…">${ICON.sparkles}</button>`
            : `<button class="mini" data-jid="${esc(j.job_id)}"
                 title="${hasScore ? "Re-score" : "Score"} this job (1 Claude call)">${ICON.sparkles}</button>`}
          ${j.status === "archived"
            ? `<button class="mini" data-restore="${esc(j.job_id)}" title="Restore to review">${ICON.undo}</button>`
            : `<button class="mini dismiss" data-dismiss="${esc(j.job_id)}" title="Not interested — hide">${ICON.x}</button>`}
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
  const msg = { inbox:"Inbox is clear — hit Scan to pull new jobs.",
    applied:"Nothing applied yet.", rejected:"Nothing rejected yet.",
    archived:"Nothing hidden.", all:"No jobs yet — hit Scan." }[LANE] || "No jobs.";
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

// --- views (jobs / tracker / settings) — Settings holds general/config/rubric/usage sub-pages ---
let VIEW = "jobs";
let SETTAB = "menu";   // menu | general | config | rubric | usage
const LOADERS = { jobs: load, tracker: loadTracker, config: loadConfig, rubric: loadRubric, usage: loadUsage };
function showView(v) {
  VIEW = v;
  $("#jobsView").style.display     = v==="jobs"     ? "" : "none";
  $("#trackerView").style.display  = v==="tracker"  ? "" : "none";
  $("#settingsView").style.display = v==="settings" ? "" : "none";
  document.querySelectorAll(".tab").forEach(b => b.classList.toggle("on", b.dataset.view===v));
  $("#gearBtn").classList.toggle("on", v==="settings");
  document.querySelectorAll("#botnav button").forEach(b => b.classList.toggle("on", b.dataset.view===v));
  if (v==="settings") showSetTab(SETTAB);
}
// Settings sub-page router (iOS-style: a menu, then one section with a ‹ Settings back).
function showSetTab(t) {
  SETTAB = t;
  $("#setMenu").style.display    = t==="menu" ? "" : "none";
  $("#setSection").style.display = t==="menu" ? "none" : "";
  $("#generalView").style.display = t==="general" ? "" : "none";
  $("#configView").style.display  = t==="config"  ? "" : "none";
  $("#rubricView").style.display  = t==="rubric"  ? "" : "none";
  $("#usageView").style.display   = t==="usage"   ? "" : "none";
  $("#setTitle").textContent = { general:"General", config:"Config", rubric:"Rubric", usage:"Usage" }[t] || "";
  if (t==="general") { setThemeSeg(localStorage.getItem(THEME_KEY) || ""); loadScheduler(); }
  else if (LOADERS[t]) LOADERS[t]();     // load config/rubric/usage on entry
}

// --- scheduling (crawler + triage on/off + cron hours) ---
async function loadScheduler() {
  if (!TOKEN) return;
  try {
    const s = await (await api("/api/scheduler")).json();
    $("#schScanEn").checked   = !!(s.scan && s.scan.enabled);
    $("#schScanHours").value  = (s.scan && s.scan.hours) || "";
    $("#schTriageEn").checked = !!(s.triage && s.triage.enabled);
    $("#schTriageHours").value= (s.triage && s.triage.hours) || "";
    $("#schMsg").textContent  = "";
  } catch(e){ if (e.message!=="auth") $("#schMsg").textContent = "Error: "+e.message; }
}
async function saveScheduler() {
  $("#schMsg").textContent = "saving…";
  const body = {
    scan:   { enabled: $("#schScanEn").checked,   hours: $("#schScanHours").value.trim() },
    triage: { enabled: $("#schTriageEn").checked, hours: $("#schTriageHours").value.trim() },
  };
  try {
    const r = await api("/api/scheduler", {
      method:"POST", headers:{ "content-type":"application/json" }, body: JSON.stringify(body) });
    $("#schMsg").textContent = r.ok ? "Saved — applied live." : "Error: HTTP "+r.status;
  } catch(e){ if (e.message!=="auth") $("#schMsg").textContent = "Error: "+e.message; }
}
function refreshView(){
  if (VIEW==="settings") { if (SETTAB!=="menu" && SETTAB!=="general" && LOADERS[SETTAB]) LOADERS[SETTAB](); }
  else (LOADERS[VIEW] || load)();
}

// --- config editor: Raw YAML is the source of truth (#cfg); the Form line-patches
//     specific keys into that text so comments/structure survive. ---
const CONNECTORS = [
  {id:"adzuna", name:"Adzuna", desc:"UK aggregator · API key", icon:"scan", locs:true,
   lists:[{key:"queries", label:"Search queries", ph:"add query…"}],
   scalars:[["country","Country"],["max_pages","Max pages / location"],["max_days_old","Max days old"],
            ["sort_by","Sort by"],["category","Category"],["results_per_page","Results / page"],
            ["what_exclude","Exclude terms",true]]},
  {id:"reed", name:"Reed", desc:"UK aggregator · API key", icon:"scan", locs:true,
   lists:[{key:"queries", label:"Search queries", ph:"add query…"}],
   scalars:[["results_to_take","Results to take"]]},
  {id:"indeed", name:"Indeed", desc:"Mobile API · covers Glassdoor", icon:"compass", locs:true,
   lists:[{key:"queries", label:"Search queries", ph:"add query…"}],
   scalars:[["max_pages","Max pages / location"],["hours_old","Hours old"],["results_per_page","Results / page"]]},
  {id:"linkedin", name:"LinkedIn", desc:"Guest endpoint · deep-scan only", icon:"compass", locs:true,
   lists:[{key:"queries", label:"Search queries (OR-joined per location)", ph:"add query…"},
          {key:"proxies", label:"Proxies (host:port or user:pass@host:port; blank = direct)", ph:"add proxy…"}],
   scalars:[["max_pages","Max pages / location"],["hours_old","Hours old"],["request_delay","Request delay (s)"]]},
  {id:"greenhouse", name:"Greenhouse", desc:"ATS boards · company slugs", icon:"wrench",
   lists:[{key:"companies", label:"Company board slugs", ph:"e.g. monzo, wise…"}], scalars:[]},
  {id:"lever", name:"Lever", desc:"ATS boards · company slugs", icon:"wrench",
   lists:[{key:"companies", label:"Company board slugs", ph:"e.g. spotify…"}], scalars:[]},
  {id:"ashby", name:"Ashby", desc:"ATS boards · company slugs", icon:"wrench",
   lists:[{key:"companies", label:"Company board slugs", ph:"add slug…"}], scalars:[]},
  {id:"workday", name:"Workday", desc:"Self-hosted · host + site", icon:"wrench", companiesRaw:true,
   lists:[{key:"queries", label:"Queries (narrow server-side)", ph:"add query…"}], scalars:[["max_pages","Max pages"]]},
  {id:"oracle", name:"Oracle ORC", desc:"Oracle Cloud Recruiting · per tenant", icon:"wrench", companiesRaw:true,
   lists:[{key:"queries", label:"Queries (searches full JD)", ph:"add query…"}], scalars:[["max_pages","Max pages"]]},
];
let CFG_MODE = "form";
const CFG_OPEN = new Set();     // expanded connector card ids

// ---- YAML line helpers (operate on the raw text in #cfg) ----
const _lines = () => $("#cfg").value.split("\n");
const _commit = (lines) => { $("#cfg").value = lines.join("\n"); };
const _quote = s => /^[A-Za-z0-9_][A-Za-z0-9_.\- ]*$/.test(s) && !/^\d+$/.test(s) ? '"'+s+'"' : JSON.stringify(s);
function _keyIdx(lines, s, e, ind, key){
  const re = new RegExp("^ {"+ind+"}"+key+":");
  for (let i=s; i<e; i++) if (re.test(lines[i])) return i;
  return -1;
}
function readScalar(lines, s, e, ind, key){
  const i = _keyIdx(lines, s, e, ind, key); if (i<0) return null;
  let v = lines[i].slice(lines[i].indexOf(":")+1).replace(/\s+#.*$/,"").trim();
  if ((v[0]==='"'&&v.endsWith('"'))||(v[0]==="'"&&v.endsWith("'"))) v = v.slice(1,-1);
  return v;
}
function readList(lines, s, e, ind, key){
  const i = _keyIdx(lines, s, e, ind, key); if (i<0) return null;
  let rest = lines[i].slice(lines[i].indexOf(":")+1).trim();
  if (rest.startsWith("[")) return rest.replace(/^\[/,"").replace(/\]\s*(#.*)?$/,"")
    .split(",").map(x => x.trim().replace(/^["']|["']$/g,"")).filter(Boolean);
  const out = [], ire = new RegExp("^ {"+(ind+2)+"}- (.+)$");
  for (let j=i+1; j<e; j++){ const m = lines[j].match(ire);
    if (m) out.push(m[1].trim().replace(/\s+#.*$/,"").replace(/^["']|["']$/g,""));
    else if (/^\s*#/.test(lines[j]) || !lines[j].trim()) continue;  // skip comments/blanks
    else break; }                                                    // real content/dedent → stop
  return out;
}
function patchScalar(lines, s, e, ind, key, val){
  const i = _keyIdx(lines, s, e, ind, key), line = " ".repeat(ind)+key+": "+val;
  if (i>=0) lines[i] = line; else lines.splice(s+1, 0, line);
}
function patchList(lines, s, e, ind, key, items){
  const flow = " ".repeat(ind)+key+": ["+items.map(_quote).join(", ")+"]";
  const i = _keyIdx(lines, s, e, ind, key);
  if (i<0){ lines.splice(s+1, 0, flow); return; }
  // Replace the key line + any following block-list items with one flow line. Comments
  // or blanks interleaved in the list are consumed too (the block they annotated is gone).
  const ire = new RegExp("^ {"+(ind+2)+"}- ");
  let last = i;
  for (let j=i+1; j<lines.length; j++){
    if (ire.test(lines[j])) last = j;                          // an item → extend the range
    else if (/^\s*#/.test(lines[j]) || !lines[j].trim()) continue;  // comment/blank → keep scanning
    else break;                                                // real content/dedent → stop
  }
  lines.splice(i, last-i+1, flow);
}
// source block = the lines under `sources:` for one connector (child keys at indent 4)
function srcBounds(lines, id){
  const si = lines.findIndex(l => /^sources:\s*(#.*)?$/.test(l)); if (si<0) return null;
  let start = -1;
  for (let i=si+1; i<lines.length; i++){
    const m = lines[i].match(/^( {0,2})([A-Za-z0-9_-]+):/); if (!m) continue;
    if (m[1].length<2) return start<0 ? null : {s:start, e:i};      // back to top level
    if (m[1].length===2){ if (m[2]===id) { if (start<0) start = i; } else if (start>=0) return {s:start, e:i}; }
  }
  return start<0 ? null : {s:start, e:lines.length};
}
function topBlock(lines, name){
  const si = lines.findIndex(l => new RegExp("^"+name+":\\s*(#.*)?$").test(l)); if (si<0) return null;
  for (let i=si+1; i<lines.length; i++) if (/^[A-Za-z0-9_-]+:/.test(lines[i])) return {s:si, e:i};
  return {s:si, e:lines.length};
}
// resolve a form control's scope → {s,e,ind,key} against the current text
function _ctx(lines, scope){
  const p = scope.split(":");
  if (p[0]==="src"){ const b = srcBounds(lines, p[1]); return b && {s:b.s, e:b.e, ind:4, key:p[2]}; }
  if (p[0]==="gf"){ const b = topBlock(lines, "title_filter"); return b && {s:b.s, e:b.e, ind:2, key:p[1]}; }
  if (p[0]==="lf"){ const b = topBlock(lines, "location_filter"); return b && {s:b.s, e:b.e, ind:2, key:p[1]}; }
  if (p[0]==="an"){ const b = topBlock(lines, "analysis"); return b && {s:b.s, e:b.e, ind:2, key:p[1]}; }
  if (p[0]==="tl") return {s:0, e:lines.length, ind:0, key:p[1]};   // top-level list (items at indent 2)
  if (p[0]==="top") return {s:0, e:lines.length, ind:0, key:p[1]};  // top-level scalar
  return null;
}
// locations = a block of flow maps (`- { where: "X", distance: 40 }`) under a source.
function readLocations(lines, id){
  const b = srcBounds(lines, id); if (!b) return [];
  const i = _keyIdx(lines, b.s, b.e, 4, "locations"); if (i<0) return [];
  const out = [], ire = /^ {6}- \{(.*)\}/;
  for (let j=i+1; j<b.e; j++){ const m = lines[j].match(ire);
    if (m){ const w = (m[1].match(/where:\s*"?([^",}]*)"?/)||[])[1] || "";
            const d = (m[1].match(/distance:\s*(\d+)/)||[])[1] || "";
            out.push({where:w.trim(), distance:d}); }
    else if (/^\s*#/.test(lines[j]) || !lines[j].trim()) continue;
    else break; }
  return out;
}
function patchLocations(lines, id, rows){
  const b = srcBounds(lines, id); if (!b) return;
  const i = _keyIdx(lines, b.s, b.e, 4, "locations");
  const block = rows.length
    ? ["    locations:"].concat(rows.map(r => {
        const parts = ['where: "'+(r.where||"").replace(/"/g,"")+'"'];
        if (String(r.distance||"").trim()!=="") parts.push("distance: "+r.distance);
        return "      - { "+parts.join(", ")+" }"; }))
    : ["    locations: []"];
  if (i<0){ lines.splice(b.s+1, 0, ...block); return; }
  let last = i, ire = /^ {6}- /;
  for (let j=i+1; j<lines.length; j++){
    if (ire.test(lines[j])) last = j;
    else if (/^\s*#/.test(lines[j]) || !lines[j].trim()) continue;
    else break; }
  lines.splice(i, last-i+1, ...block);
}
function cfgApplyLoc(id, mutate, noRender){
  const lines = _lines();
  patchLocations(lines, id, mutate(readLocations(lines, id).map(r => ({...r}))));
  _commit(lines); if (!noRender) renderCfgForm();
}
function cfgApplyList(scope, mutate){
  const lines = _lines(), c = _ctx(lines, scope); if (!c) return;
  const items = readList(lines, c.s, c.e, c.ind, c.key) || [];
  patchList(lines, c.s, c.e, c.ind, c.key, mutate(items.slice()));
  _commit(lines); renderCfgForm();
}
function cfgApplyScalar(scope, val){
  const lines = _lines(), c = _ctx(lines, scope); if (!c) return;
  patchScalar(lines, c.s, c.e, c.ind, c.key, val); _commit(lines);
}
function cfgSetEnabled(id, on){
  const lines = _lines(), b = srcBounds(lines, id); if (!b) return;
  patchScalar(lines, b.s, b.e, 4, "enabled", on ? "true" : "false"); _commit(lines); renderCfgForm();
}

function chipsHTML(scope, items, danger){
  return `<div class="taginput" data-add="${scope}">`
    + items.map((t,i) => `<span class="tag${danger?" neg":""}">${esc(t)}<b data-rm="${scope}" data-i="${i}">✕</b></span>`).join("")
    + `<input placeholder="add…" data-addinput="${scope}"></div>`;
}
function locRowsHTML(id, rows){
  return `<div class="field"><label>Locations <span class="help">— each is its own budgeted pull; blank <i>where</i> = nationwide/remote</span></label>`
    + rows.map((r,i) => `<div class="locrow">`
        + `<input class="loc-where" data-loc-where="${id}" data-loc-i="${i}" value="${esc(r.where)}" placeholder="(nationwide + remote)">`
        + `<input class="loc-dist" data-loc-dist="${id}" data-loc-i="${i}" value="${esc(r.distance)}" inputmode="numeric" placeholder="dist">`
        + `<button class="loc-del" data-loc-del="${id}" data-loc-i="${i}" title="Remove">${ICON.x}</button></div>`).join("")
    + `<button class="loc-add" data-loc-add="${id}">+ Add location</button></div>`;
}
function connCardHTML(m, lines){
  const b = srcBounds(lines, m.id), present = !!b;
  const en = present && (readScalar(lines, b.s, b.e, 4, "enabled")||"").toLowerCase()==="true";
  const open = CFG_OPEN.has(m.id);
  let body = "";
  if (!present) {
    body = `<div class="cfg-note">Not in config.yml yet — add a <code>${m.id}:</code> block in Raw YAML first.</div>`;
  } else {
    body += m.lists.map(L => {
      const items = readList(lines, b.s, b.e, 4, L.key) || [];
      return `<div class="field"><label>${L.label}</label>${chipsHTML("src:"+m.id+":"+L.key, items, false)}</div>`;
    }).join("");
    if (m.locs) body += locRowsHTML(m.id, readLocations(lines, m.id));
    if (m.companiesRaw) body += `<div class="cfg-note">Companies (<code>host | site | name</code>) are edited in <b>Raw YAML</b>.</div>`;
    if (m.scalars.length) body += `<div class="fgrid">` + m.scalars.map(([k,lbl,full]) => {
      const v = readScalar(lines, b.s, b.e, 4, k);
      return `<div class="field${full?" full":""}"><label>${lbl}</label><input data-scalar="src:${m.id}:${k}" value="${esc(v==null?"":v)}"></div>`;
    }).join("") + `</div>`;
  }
  return `<div class="csrc${en?" en":""}${open?" open":""}" data-card="${m.id}">
    <div class="csrc-head" data-head="${m.id}">
      <span class="caret" data-icon="chevron"></span>
      <span class="csrc-ico" data-icon="${m.icon}"></span>
      <div style="min-width:0"><div class="csrc-name">${m.name}</div><div class="csrc-sub">${m.desc}</div></div>
      <span class="csrc-badge">${present ? (en?"On":"Off") : "—"}</span>
      ${present ? `<label class="sw"><input type="checkbox" data-en="${m.id}"${en?" checked":""}><span class="tr"></span></label>` : ""}
    </div>
    <div class="csrc-body">${body}</div>
  </div>`;
}
function analysisCardHTML(lines){
  const open = CFG_OPEN.has("_an"), bd = topBlock(lines, "analysis");
  const rd = k => bd ? readScalar(lines, bd.s, bd.e, 2, k) : null;
  const engine = rd("engine") || "claude-cli", model = rd("model") || "", maxj = rd("max_jobs") || "";
  const opt = (v,l) => `<option value="${v}"${engine===v?" selected":""}>${l}</option>`;
  return `<div class="csrc${open?" open":""}" data-card="_an">
    <div class="csrc-head" data-head="_an">
      <span class="caret" data-icon="chevron"></span>
      <span class="csrc-ico" data-icon="sparkles"></span>
      <div style="min-width:0"><div class="csrc-name">LLM triage</div>
        <div class="csrc-sub">Fit-scoring engine, model &amp; limits</div></div>
    </div>
    <div class="csrc-body">
      <div class="fgrid">
        <div class="field"><label>Engine</label><select data-scalar="an:engine">
          ${opt("claude-cli","claude-cli (Pro sub · no $)")}${opt("api","api (metered)")}</select></div>
        <div class="field"><label>Max jobs / run</label><input data-scalar="an:max_jobs" value="${esc(maxj)}" inputmode="numeric"></div>
        <div class="field full"><label>Model</label>
          <input data-scalar="an:model" value="${esc(model)}" placeholder="claude-haiku-4-5" list="cfgModels"></div>
      </div>
      <div class="cfg-note">claude-cli spends your Claude Pro quota (calls, not $) — keep <b>Max jobs</b> modest.
        The candidate profile lives in <b>Settings → Rubric</b>.</div>
    </div>
  </div>`;
}
function globalCardHTML(lines){
  const open = CFG_OPEN.has("_gf");
  const tf = Object.values(topBlock(lines,"title_filter") || {s:0,e:0});
  const lf = Object.values(topBlock(lines,"location_filter") || {s:0,e:0});
  const pos = readList(lines, ...tf, 2, "positive") || [];
  const neg = readList(lines, ...tf, 2, "negative") || [];
  const allow = readList(lines, ...lf, 2, "allow") || [];
  const block = readList(lines, ...lf, 2, "block") || [];
  const prio = readList(lines, 0, lines.length, 0, "priority_locations") || [];
  const exp = readScalar(lines, 0, lines.length, 0, "expire_after_hours");
  const rec = readScalar(lines, 0, lines.length, 0, "recent_days");
  const full = (readScalar(lines, 0, lines.length, 0, "fetch_full_jd") || "true").toLowerCase()==="true";
  return `<div class="csrc${open?" open":""}" data-card="_gf">
    <div class="csrc-head" data-head="_gf">
      <span class="caret" data-icon="chevron"></span>
      <span class="csrc-ico" data-icon="sliders"></span>
      <div style="min-width:0"><div class="csrc-name">Filters &amp; lifecycle</div>
        <div class="csrc-sub">Applied to every source</div></div>
      <span class="csrc-badge" style="background:color-mix(in srgb,var(--new) 16%,transparent);color:var(--new)">Always on</span>
    </div>
    <div class="csrc-body">
      <div class="field"><label>Title must match one of</label>${chipsHTML("gf:positive", pos, false)}</div>
      <div class="field"><label>Title must NOT match</label>${chipsHTML("gf:negative", neg, true)}</div>
      <div class="field"><label>Location allow <span class="help">— city / region / "Remote" / "UK"</span></label>${chipsHTML("lf:allow", allow, false)}</div>
      <div class="field"><label>Location block <span class="help">— wins over allow</span></label>${chipsHTML("lf:block", block, true)}</div>
      <div class="field"><label>Priority cities <span class="help">— shown first on multi-city posts</span></label>${chipsHTML("tl:priority_locations", prio, false)}</div>
      <div class="fgrid">
        <div class="field"><label>Expire after (hours)</label><input data-scalar="top:expire_after_hours" value="${esc(exp==null?"":exp)}"></div>
        <div class="field"><label>Recent window (days)</label><input data-scalar="top:recent_days" value="${esc(rec==null?"":rec)}" placeholder="unset = full window"></div>
      </div>
      <label class="cfg-check"><span class="sw"><input type="checkbox" data-bool="top:fetch_full_jd"${full?" checked":""}><span class="tr"></span></span> Fetch full JD after scans (Reed)</label>
    </div>
  </div>`;
}
function renderCfgForm(){
  if (!$("#cfg").value) { $("#cfgForm").innerHTML = ""; return; }
  const lines = _lines();
  $("#cfgForm").innerHTML =
    `<datalist id="cfgModels"><option value="claude-haiku-4-5"><option value="claude-sonnet-5"><option value="claude-opus-4-8"></datalist>`
    + `<div class="cfg-label">Connectors</div>`
    + CONNECTORS.map(m => connCardHTML(m, lines)).join("")
    + `<div class="cfg-label">LLM triage</div>`
    + analysisCardHTML(lines)
    + `<div class="cfg-label">Filters &amp; lifecycle</div>`
    + globalCardHTML(lines);
  paintIcons($("#cfgForm"));
}
function setCfgMode(mode){
  CFG_MODE = mode;
  $("#cfgForm").style.display = mode==="form" ? "" : "none";
  $("#cfgRaw").style.display  = mode==="raw"  ? "" : "none";
  document.querySelectorAll("#cfgMode button").forEach(b => b.classList.toggle("on", b.dataset.mode===mode));
  if (mode==="form") renderCfgForm();   // re-sync the form from (possibly edited) raw text
}
async function loadConfig() {
  if (!TOKEN) return showAuth("Enter your API token to edit config.");
  $("#cfgMsg").textContent = "loading…";
  try {
    $("#cfg").value = await (await api("/api/config")).text();
    $("#cfgMsg").textContent = "";
    setCfgMode(CFG_MODE);
  } catch(e){ if (e.message!=="auth") $("#cfgMsg").textContent = "Error: "+e.message; }
}
async function saveConfig() {
  $("#cfgMsg").textContent = "saving…";
  try {
    const r = await api("/api/config", {
      method:"POST", headers:{ "content-type":"text/plain" }, body: $("#cfg").value });
    const data = await r.json().catch(()=>({}));
    if (r.ok) $("#cfgMsg").textContent = "Saved — applies on next scan ("+(data.sources||[]).join(", ")+")";
    else $("#cfgMsg").textContent = "Error: " + (data.detail || ("HTTP "+r.status));  // 400 = invalid YAML
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
    $("#rubMsg").textContent = r.ok ? "Saved — used by the next Analyze run" : "Error: HTTP "+r.status;
  } catch(e){ if (e.message!=="auth") $("#rubMsg").textContent = "Error: "+e.message; }
}

// --- tracker view: horizontal kanban board (Saved → Applied → Rejected) ---
const STAGES = [
  { key: "saved",    label: "Saved",    icon: "bookmark", cls: "saved",
    moves: [["applied","Applied","check"], ["rejected","Reject","ban"], ["new","Inbox","undo"]] },
  { key: "applied",  label: "Applied",  icon: "check", cls: "applied",
    moves: [["rejected","Rejected","ban"], ["new","Inbox","undo"]] },
  { key: "rejected", label: "Rejected", icon: "ban", cls: "rejected",
    moves: [["saved","Save","bookmark"], ["new","Inbox","undo"]] },
];
function trackerCard(j, moves) {
  const band = scoreBand(j.score);
  const sc = j.score != null ? `<span class="score s-${band}">${Math.round(j.score)}</span> ` : "";
  const btns = moves.map(([st, lbl, ic]) =>
    `<button class="btn ghost" data-trk="${esc(j.job_id)}" data-st="${st}">${ICON[ic]}${lbl}</button>`).join("");
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
        <div class="kcol-head">${ICON[s.icon]}${s.label}<span class="seg-n">${items.length}</span></div>
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
      const flag = r.note==="auth failed" ? '<span class="warn">not logged in</span>'
                 : r.budget_hit ? '<span class="warn">limit</span>'
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
      : '<div class="empty">No LLM runs yet — hit Analyze.</div>';
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
      $("#msg").textContent = "Halting after the current job…";
    } else if (s.running && c) {
      const what = c.kind==="batch" ? "Triaging" : "Scoring";
      const tot = c.total==null ? "…" : c.total;
      $("#msg").textContent = `${what} ${c.scored||0}/${tot}`
        + (c.errors ? ` (${c.errors} err)` : "") + (q ? ` · ${q} queued` : "");
    } else if (q) {
      $("#msg").textContent = `${q} queued…`;
    }
    await fetchJobs();  // reflect new scores + clear finished spinners (see render/SPIN)
    if (s.running || q) { POLL = setTimeout(pollAnalyze, 1500); return; }
    // idle: queue drained — settle the message from the last run
    POLL = null; setBatchBusy(false); setStopVisible(false);
    const last = s.last || {};
    if (last.auth_failed)
      $("#msg").innerHTML = '<span class="warn">Claude not logged in — set '
        + 'CLAUDE_CODE_OAUTH_TOKEN (claude setup-token) and redeploy.</span>';
    else if (last.budget_hit)
      $("#msg").innerHTML = '<span class="warn">Out of budget / rate limited — triage stopped.</span>';
    else if (last.cancelled)
      $("#msg").textContent = `Halted — scored ${last.totals.scored} before stopping.`;
    else if (last.totals)
      $("#msg").textContent = `Done — scored ${last.totals.scored} (${last.totals.errors||0} err)`;
  } catch(e){ POLL = null; }
}

// --- wiring ---
// Primary nav: top tabs (Jobs/Tracker), the gear, and the mobile bottom bar all carry data-view.
document.querySelectorAll("[data-view]").forEach(b => b.onclick = () => {
  const v = b.dataset.view;
  if (v==="settings") SETTAB = "menu";   // the gear always opens Settings on its menu
  showView(v); refreshView();
});
$("#setMenu").onclick = (e) => { const r = e.target.closest("[data-set]"); if (r) showSetTab(r.dataset.set); };
$("#setBack").onclick = () => showSetTab("menu");
document.querySelectorAll("#themeSeg button").forEach(b => b.onclick = () => {
  const t = b.dataset.theme || ""; localStorage.setItem(THEME_KEY, t); applyTheme(t); setThemeSeg(t);
});
$("#save").onclick = () => { TOKEN = $("#token").value.trim(); localStorage.setItem("jr_token", TOKEN);
  $("#token2").value = TOKEN; refreshView(); };
$("#save2").onclick = () => { TOKEN = $("#token2").value.trim(); localStorage.setItem("jr_token", TOKEN);
  $("#token").value = TOKEN; $("#tokMsg").textContent = "Saved — kept in this browser only."; refreshView(); };
$("#tokReveal").onclick = () => {   // masked by default; eye toggles reveal
  const t = $("#token2"), show = t.type === "password";
  t.type = show ? "text" : "password";
  $("#tokReveal").innerHTML = show ? ICON.eyeOff : ICON.eye;
};
$("#schSave").onclick = saveScheduler;
$("#trkReload").onclick = loadTracker;
$("#cfgSave").onclick = saveConfig;
$("#cfgReload").onclick = loadConfig;
// Config Form ⇄ Raw toggle
$("#cfgMode").onclick = (e) => { const b = e.target.closest("[data-mode]"); if (b) setCfgMode(b.dataset.mode); };
// Config form interactions (delegated): expand, enable toggle, chip add/remove, scalars
$("#cfgForm").addEventListener("click", (e) => {
  const rm = e.target.closest("[data-rm]");
  if (rm) { const i = +rm.dataset.i; cfgApplyList(rm.dataset.rm, xs => (xs.splice(i,1), xs)); return; }
  const ld = e.target.closest("[data-loc-del]");
  if (ld) { cfgApplyLoc(ld.dataset.locDel, xs => (xs.splice(+ld.dataset.locI,1), xs)); return; }
  const la = e.target.closest("[data-loc-add]");
  if (la) { cfgApplyLoc(la.dataset.locAdd, xs => (xs.push({where:"", distance:""}), xs)); return; }
  if (e.target.closest(".sw")) return;                       // toggling a switch ≠ collapsing
  const head = e.target.closest("[data-head]");
  if (head) { const id = head.dataset.head; CFG_OPEN.has(id) ? CFG_OPEN.delete(id) : CFG_OPEN.add(id); renderCfgForm(); }
});
$("#cfgForm").addEventListener("change", (e) => {
  const en = e.target.closest("[data-en]");
  if (en) { cfgSetEnabled(en.dataset.en, en.checked); return; }
  const bl = e.target.closest("[data-bool]");
  if (bl) { cfgApplyScalar(bl.dataset.bool, bl.checked ? "true" : "false"); return; }
  const lw = e.target.closest("[data-loc-where]");
  if (lw) { cfgApplyLoc(lw.dataset.locWhere, xs => (xs[+lw.dataset.locI].where = lw.value, xs), true); return; }
  const ld = e.target.closest("[data-loc-dist]");
  if (ld) { cfgApplyLoc(ld.dataset.locDist, xs => (xs[+ld.dataset.locI].distance = ld.value.trim(), xs), true); return; }
  const sc = e.target.closest("[data-scalar]");
  if (sc) cfgApplyScalar(sc.dataset.scalar, sc.value.trim());   // no re-render → keeps focus/caret
});
$("#cfgForm").addEventListener("keydown", (e) => {
  const inp = e.target.closest("[data-addinput]");
  if (inp && e.key==="Enter") { e.preventDefault(); const v = inp.value.trim();
    if (v) cfgApplyList(inp.dataset.addinput, xs => (xs.includes(v) || xs.push(v), xs)); }
});
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
// One Scan button → a menu with Scan now / Deep scan.
const closeScanMenu = () => { $("#scanMenu").style.display = "none"; };
$("#scanBtn").onclick = (e) => {
  e.stopPropagation();
  const m = $("#scanMenu"); m.style.display = m.style.display==="none" ? "" : "none";
};
document.addEventListener("click", (e) => { if (!e.target.closest(".scanwrap")) closeScanMenu(); });
$("#scan").onclick = async () => {
  closeScanMenu();
  try {
    const r = await api("/api/scan", { method:"POST" });
    $("#msg").textContent = r.status===409 ? "A scan is already running…" : "Scan started — refresh in a bit.";
  } catch(e){}
};
$("#deepscan").onclick = async () => {
  closeScanMenu();
  try {
    const r = await api("/api/scan?deep=1", { method:"POST" });
    $("#msg").textContent = r.status===409 ? "A scan is already running…"
      : "Deep scan started — pulling the full window. Refresh in a bit.";
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
const STATUS_MSG = { applied:"Applied — see the Tracker", viewed:"Marked seen — stays in your inbox, dimmed",
  saved:"Saved — see the Tracker", rejected:"Rejected",
  archived:"Hidden (open the Archived lane to find it)", new:"Back in the review list" };
async function markStatus(jid, status) {
  try {
    await api("/api/status", { method:"POST", headers:{ "content-type":"application/json" },
      body: JSON.stringify({ job_id: jid, status }) });
    $("#msg").textContent = (STATUS_MSG[status] || "Updated") + ".";
    refreshView();  // re-render the active view (Jobs inbox or Tracker)
  } catch(e){}
}
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState !== "visible") return;
  showApplyModal();
  // Auto-refresh on return replaces the old ↻ button — but only the live data views,
  // never while editing a config/rubric textarea in Settings.
  if (VIEW==="jobs" || VIEW==="tracker") refreshView();
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
      + `Pro quota (capped by analysis.max_jobs). Use a card's score button for one at a time.`)) return;
  setBatchBusy(true);                   // block the button immediately
  const d = await enqueueTriage("all_pending");
  if (d && (d.queued || d.duplicate)) { $("#msg").textContent = "Batch queued…"; setStopVisible(true); startPoll(); }
  else setBatchBusy(false);             // enqueue failed (queue full) — unblock
};
$("#stopAnalyze").onclick = async () => {
  const b = $("#stopAnalyze"); b.disabled = true;
  $("#msg").textContent = "Halting after the current job…";
  try { await api("/api/analyze/stop", { method:"POST" }); } catch(e){}
  b.disabled = false; startPoll();      // poll reflects the wind-down + final message
};
$("#token2").value = TOKEN;   // reflect the saved token in the General settings field
paintIcons();                 // fill the static data-icon chrome placeholders
renderLanes();
load();
</script>
</body>
</html>
"""
