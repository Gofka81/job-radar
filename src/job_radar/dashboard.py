"""The phone-friendly HTML dashboard served at GET /. Self-contained (inline CSS
+ JS), no build step. It loads open, then talks to the bearer-protected /api/*
endpoints using a token the user enters once (kept in localStorage)."""

from __future__ import annotations

DASHBOARD_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>job-radar</title>
<style>
  :root { --bg:#0f1115; --card:#1a1d24; --line:#2a2e37; --fg:#e6e8ec; --muted:#8b909c;
          --accent:#4f86f7; --new:#2ecc71; --pill:#262b34; }
  * { box-sizing: border-box; }
  body { margin:0; background:var(--bg); color:var(--fg); font:15px/1.45 system-ui,sans-serif; }
  header { position:sticky; top:0; background:var(--bg); border-bottom:1px solid var(--line);
           padding:12px 16px; display:flex; align-items:center; gap:10px; flex-wrap:wrap; }
  h1 { font-size:18px; margin:0; flex:1; }
  button, select { background:var(--card); color:var(--fg); border:1px solid var(--line);
           border-radius:8px; padding:7px 12px; font-size:14px; cursor:pointer; }
  button:active { transform:translateY(1px); }
  .wrap { padding:14px 16px; max-width:760px; margin:0 auto; }
  .chips { display:flex; gap:8px; flex-wrap:wrap; margin-bottom:14px; }
  .chip { background:var(--card); border:1px solid var(--line); border-radius:10px;
          padding:8px 12px; min-width:74px; }
  .chip b { display:block; font-size:20px; }
  .chip span { color:var(--muted); font-size:12px; text-transform:uppercase; letter-spacing:.04em; }
  .controls { display:flex; gap:8px; align-items:center; margin-bottom:12px; flex-wrap:wrap; }
  .job { background:var(--card); border:1px solid var(--line); border-radius:10px;
         padding:11px 13px; margin-bottom:9px; }
  .job a { color:var(--fg); text-decoration:none; font-weight:600; }
  .job a:hover { color:var(--accent); }
  .meta { color:var(--muted); font-size:13px; margin-top:4px; display:flex; gap:8px; flex-wrap:wrap; }
  .pill { background:var(--pill); border-radius:20px; padding:1px 9px; font-size:12px; }
  .new { background:var(--new); color:#06210f; font-weight:700; }
  .muted { color:var(--muted); }
  #token, #q { flex:1; min-width:140px; padding:7px 10px; border-radius:8px;
           border:1px solid var(--line); background:var(--card); color:var(--fg); }
  #fsalary { width:96px; padding:7px 10px; border-radius:8px;
           border:1px solid var(--line); background:var(--card); color:var(--fg); }
  .controls select { flex:0 0 auto; }
  #recency.on { background:var(--accent); color:#fff; border-color:var(--accent); }
  #msg { color:var(--muted); font-size:13px; padding:6px 0; }
</style>
</head>
<body>
<header>
  <h1>📡 job-radar</h1>
  <select id="sort">
    <option value="recent">Recent</option>
    <option value="company">Company</option>
    <option value="location">Location</option>
    <option value="score">Score</option>
  </select>
  <button id="scan">Scan now</button>
  <button id="refresh">↻</button>
</header>
<div class="wrap">
  <div id="auth" style="display:none; margin-bottom:12px;">
    <input id="token" placeholder="API token" autocomplete="off">
    <button id="save">Save</button>
  </div>
  <div id="chips" class="chips"></div>
  <div class="controls">
    <input id="q" placeholder="Search title / company… (e.g. spark)" autocomplete="off">
    <select id="fstatus"><option value="">All statuses</option></select>
    <select id="floc"><option value="">All locations</option></select>
    <select id="fsource"><option value="">All sources</option></select>
    <input id="fsalary" type="number" min="0" step="5000" placeholder="Min £" inputmode="numeric">
    <button id="recency">Recent</button>
  </div>
  <div id="msg"></div>
  <div id="list"></div>
</div>
<script>
const $ = s => document.querySelector(s);
let TOKEN = localStorage.getItem("jr_token") || "";
let JOBS = [];

function authHeader() { return { "authorization": "Bearer " + TOKEN }; }
function ago(ts) {
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

const RECENT_MS = 72*3600*1000;   // "recent" default window
let SHOW_ALL = false;             // recency toggle (off = recent only)

function fillFilter(sel, label, values) {
  const cur = sel.value;
  sel.innerHTML = [`<option value="">${label}</option>`]
    .concat([...new Set(values)].filter(Boolean).sort().map(v => `<option>${esc(v)}</option>`)).join("");
  sel.value = cur;  // keep selection across reloads
}
function viewJobs() {
  const q = $("#q").value.trim().toLowerCase();
  const st = $("#fstatus").value, loc = $("#floc").value, src = $("#fsource").value;
  const minSal = parseFloat($("#fsalary").value) || 0;
  const now = Date.now();
  let v = JOBS.filter(j =>
    (!st  || j.status === st) &&
    (!loc || (j.location_cleaned || "") === loc) &&
    (!src || j.source === src) &&
    // min salary on salary_max; keep jobs with no salary data visible
    (!minSal || j.salary_max == null || j.salary_max >= minSal) &&
    (!q || (`${j.title||""} ${j.company||""}`).toLowerCase().includes(q)) &&
    (SHOW_ALL || !j.first_seen || (now - new Date(j.first_seen).getTime()) <= RECENT_MS));
  const k = $("#sort").value;
  const by = { recent:(a,b)=> (b.first_seen||"").localeCompare(a.first_seen||""),
               company:(a,b)=> (a.company||"").localeCompare(b.company||""),
               location:(a,b)=> (a.location_cleaned||"").localeCompare(b.location_cleaned||""),
               score:(a,b)=> (b.score||0)-(a.score||0) };
  v.sort(by[k]);
  render(v);
  const older = SHOW_ALL ? 0 : JOBS.filter(j => j.first_seen && (now - new Date(j.first_seen).getTime()) > RECENT_MS).length;
  $("#recency").textContent = SHOW_ALL ? "All" : `Recent${older?` (+${older})`:""}`;
  $("#recency").classList.toggle("on", !SHOW_ALL);
  $("#msg").textContent = `${v.length} of ${JOBS.length} jobs` + (SHOW_ALL ? "" : " · recent 72h");
}
function salaryStr(j) {
  const k = n => "£" + Math.round(n/1000) + "k";
  const lo = j.salary_min, hi = j.salary_max;
  if (lo && hi) return lo === hi ? k(lo) : `${k(lo)}–${k(hi)}`;
  if (hi) return `≤ ${k(hi)}`;
  if (lo) return `${k(lo)}+`;
  return "";
}
function render(list) {
  $("#list").innerHTML = list.map(j => {
    const fresh = j.first_seen && (Date.now()-new Date(j.first_seen).getTime() < 86400000);
    const sal = salaryStr(j);
    return `<div class="job">
      <a href="${esc(j.url)}" target="_blank" rel="noopener">${esc(j.title)}</a>
      <div class="meta">
        <span>${esc(j.company)}</span>
        <span class="pill">${esc(j.location_cleaned || j.location || "—")}</span>
        ${sal ? `<span class="pill">${sal}</span>` : ''}
        <span class="pill">${esc(j.source)}</span>
        <span class="pill">${esc(j.status)}</span>
        <span class="muted">${ago(j.first_seen)}</span>
        ${fresh ? '<span class="pill new">NEW</span>' : ''}
      </div></div>`;
  }).join("") || '<div class="muted">No jobs yet — hit “Scan now”.</div>';
}

async function load() {
  if (!TOKEN) return showAuth("Enter your API token to view jobs.");
  $("#auth").style.display="none";
  try {
    const f = await (await api("/api/funnel")).json();
    $("#chips").innerHTML = Object.entries(f).map(([k,v]) =>
      `<div class="chip"><b>${v}</b><span>${k}</span></div>`).join("");
    JOBS = (await (await api("/api/jobs?limit=500")).json()).jobs || [];
    fillFilter($("#fstatus"), "All statuses", JOBS.map(j => j.status));
    fillFilter($("#floc"), "All locations", JOBS.map(j => j.location_cleaned));
    fillFilter($("#fsource"), "All sources", JOBS.map(j => j.source));
    viewJobs();
  } catch(e){ if (e.message!=="auth") $("#msg").textContent = "Error: "+e.message; }
}

$("#save").onclick = () => { TOKEN = $("#token").value.trim(); localStorage.setItem("jr_token", TOKEN); load(); };
$("#refresh").onclick = load;
$("#sort").onchange = viewJobs;
$("#q").oninput = viewJobs;
$("#fstatus").onchange = viewJobs;
$("#floc").onchange = viewJobs;
$("#fsource").onchange = viewJobs;
$("#fsalary").oninput = viewJobs;
$("#recency").onclick = () => { SHOW_ALL = !SHOW_ALL; viewJobs(); };
$("#scan").onclick = async () => {
  try {
    const r = await api("/api/scan", { method:"POST" });
    $("#msg").textContent = r.status===409 ? "A scan is already running…" : "Scan started — refresh in a bit.";
  } catch(e){}
};
load();
</script>
</body>
</html>
"""
