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
           border-radius:8px; padding:7px 12px; font-size:14px; cursor:pointer;
           min-height:36px; line-height:1; }
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
  .jobhead { display:flex; gap:8px; align-items:flex-start; justify-content:space-between; }
  .jobhead a { flex:1; }
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
  #nav { display:flex; gap:6px; }
  .navbtn { min-width:44px; text-align:center; }
  #refresh { min-width:44px; }
  .navbtn.on { background:var(--accent); color:#fff; border-color:var(--accent); }
  .back { background:var(--accent); color:#fff; border-color:var(--accent); font-weight:600; }
  .mini { padding:4px 10px; min-height:30px; font-size:13px; }
  #msg { color:var(--muted); font-size:13px; padding:6px 0; }
  .cfgbar { display:flex; gap:8px; align-items:center; margin-bottom:10px; flex-wrap:wrap; }
  #cfg, #rubric { width:100%; min-height:60vh; padding:12px; border-radius:8px;
         border:1px solid var(--line); background:var(--card); color:var(--fg);
         font:13px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace; resize:vertical;
         white-space:pre; tab-size:2; }
  .navbtn.on { background:var(--accent); color:#fff; border-color:var(--accent); }
  .score { background:#1d3a2a; color:#7CFC9E; font-weight:700; border-radius:20px;
           padding:1px 9px; font-size:12px; }
  .reason { color:var(--muted); font-size:13px; margin-top:5px; }
  table.usage { width:100%; border-collapse:collapse; font-size:13px; }
  table.usage th, table.usage td { text-align:left; padding:6px 8px; border-bottom:1px solid var(--line); }
  table.usage th { color:var(--muted); font-weight:600; }
  .warn { color:#ff6b6b; font-weight:700; }
</style>
</head>
<body>
<header>
  <h1>📡 job-radar</h1>
  <span id="jobsTools">
    <select id="sort">
      <option value="recent">Recent</option>
      <option value="company">Company</option>
      <option value="location">Location</option>
      <option value="score">Score</option>
    </select>
    <button id="scan">Scan now</button>
    <button id="analyze" title="LLM triage of pending jobs">✨ Analyze</button>
  </span>
  <span id="nav">
    <button class="navbtn on" data-view="jobs">Jobs</button>
    <button class="navbtn" data-view="config" title="Config">⚙</button>
    <button class="navbtn" data-view="rubric" title="Triage rubric">📋</button>
    <button class="navbtn" data-view="usage" title="LLM token usage">📊</button>
  </span>
  <button id="refresh">↻</button>
</header>
<div class="wrap">
  <div id="auth" style="display:none; margin-bottom:12px;">
    <input id="token" placeholder="API token" autocomplete="off">
    <button id="save">Save</button>
  </div>

  <div id="jobsView">
    <div id="chips" class="chips"></div>
    <div class="controls">
      <input id="q" placeholder="Search title / company / JD — e.g. spark, airflow" autocomplete="off">
      <select id="fstatus"><option value="">All statuses</option></select>
      <select id="floc"><option value="">All locations</option></select>
      <select id="fsource"><option value="">All sources</option></select>
      <input id="fsalary" type="number" min="0" step="5000" placeholder="Min £" inputmode="numeric">
      <button id="recency">Recent</button>
    </div>
    <div id="msg"></div>
    <div id="list"></div>
  </div>

  <div id="configView" style="display:none">
    <div class="cfgbar">
      <button class="back">← Jobs</button>
      <button id="cfgSave">Save config</button>
      <button id="cfgReload">Reload</button>
      <span id="cfgMsg" class="muted"></span>
    </div>
    <textarea id="cfg" spellcheck="false" autocapitalize="off" autocomplete="off"
              placeholder="Loading config…"></textarea>
    <div class="muted" style="font-size:12px;margin-top:6px;">
      Edits save to the Pi’s config.yml — the next scan picks them up (no redeploy).
    </div>
  </div>

  <div id="rubricView" style="display:none">
    <div class="cfgbar">
      <button class="back">← Jobs</button>
      <button id="rubSave">Save rubric</button>
      <button id="rubReload">Reload</button>
      <span id="rubMsg" class="muted"></span>
    </div>
    <textarea id="rubric" spellcheck="false" autocapitalize="off" autocomplete="off"
              placeholder="Loading rubric…"></textarea>
    <div class="muted" style="font-size:12px;margin-top:6px;">
      The 0–10 triage scoring policy (candidate profile). Saves to analysis/rubric.md —
      the next ✨ Analyze run uses it (no redeploy).
    </div>
  </div>

  <div id="usageView" style="display:none">
    <div class="cfgbar">
      <button class="back">← Jobs</button>
      <button id="useReload">Reload</button>
      <span id="useMsg" class="muted"></span>
    </div>
    <div id="useTotals" class="chips"></div>
    <div id="useBox"></div>
    <div class="muted" style="font-size:12px;margin-top:6px;">
      LLM usage (resets on deploy). <b>calls</b> = LLM invocations — for the claude-cli
      engine that’s your Pro quota (“Pro” = $0 real). <b>api $</b> appears only if the
      metered API engine was used.
    </div>
  </div>
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

const RECENT_MS = 48*3600*1000;   // "recent" default window
let SHOW_ALL = false;             // recency toggle (off = recent only)

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
function viewJobs() {
  // Text search (#q) is server-side (it matches the JD too) — see fetchJobs().
  // The rest filter the loaded set client-side for instant response.
  const st = $("#fstatus").value, loc = $("#floc").value, src = $("#fsource").value;
  const minSal = parseFloat($("#fsalary").value) || 0;
  const now = Date.now();
  let v = JOBS.filter(j =>
    (!st  || j.status === st) &&
    (!loc || (j.locations || []).includes(loc)) &&
    (!src || j.source === src) &&
    // min salary on salary_max; keep jobs with no salary data visible
    (!minSal || j.salary_max == null || j.salary_max >= minSal) &&
    (SHOW_ALL || !j.first_seen || (now - new Date(j.first_seen).getTime()) <= RECENT_MS));
  const k = $("#sort").value;
  const by = { recent:(a,b)=> (b.first_seen||"").localeCompare(a.first_seen||""),
               company:(a,b)=> (a.company||"").localeCompare(b.company||""),
               location:(a,b)=> primaryLoc(a).localeCompare(primaryLoc(b)),
               score:(a,b)=> (b.score||0)-(a.score||0) };
  v.sort(by[k]);
  render(v);
  const older = SHOW_ALL ? 0 : JOBS.filter(j => j.first_seen && (now - new Date(j.first_seen).getTime()) > RECENT_MS).length;
  $("#recency").textContent = SHOW_ALL ? "All" : `Recent${older?` (+${older})`:""}`;
  $("#recency").classList.toggle("on", !SHOW_ALL);
  $("#msg").textContent = `${v.length} of ${JOBS.length} jobs` + (SHOW_ALL ? "" : " · recent 48h");
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
    const hasScore = j.score != null;
    return `<div class="job">
      <div class="jobhead">
        <a href="${esc(j.url)}" target="_blank" rel="noopener">${esc(j.title)}</a>
        <button class="mini" data-jid="${esc(j.job_id)}"
          title="Triage just this job (uses 1 Claude call)">✨${hasScore ? ' re' : ''}</button>
      </div>
      <div class="meta">
        <span>${esc(j.company)}</span>
        ${hasScore ? `<span class="score">${Math.round(j.score)}/10</span>` : ''}
        <span class="pill">${esc(primaryLoc(j))}${locExtra(j)}</span>
        ${sal ? `<span class="pill">${sal}</span>` : ''}
        <span class="pill">${esc(j.source)}</span>
        <span class="pill">${esc(j.status)}</span>
        <span class="muted">${ago(j.first_seen)}</span>
        ${fresh ? '<span class="pill new">NEW</span>' : ''}
      </div>
      ${j.eval_reason ? `<div class="reason">✨ ${esc(j.eval_reason)}</div>` : ''}
    </div>`;
  }).join("") || '<div class="muted">No jobs yet — hit “Scan now”.</div>';
}

async function fetchJobs() {
  // Search (incl. JD/tech-stack) is server-side; the q is sent to /api/jobs.
  const q = $("#q").value.trim();
  const url = "/api/jobs?limit=500" + (q ? "&q=" + encodeURIComponent(q) : "");
  JOBS = (await (await api(url)).json()).jobs || [];
  fillFilter($("#fstatus"), "All statuses", JOBS.map(j => j.status));
  fillFilter($("#floc"), "All locations", JOBS.flatMap(j => j.locations || []));
  fillFilter($("#fsource"), "All sources", JOBS.map(j => j.source));
  viewJobs();
}
async function load() {
  if (!TOKEN) return showAuth("Enter your API token to view jobs.");
  $("#auth").style.display="none";
  try {
    const f = await (await api("/api/funnel")).json();
    $("#chips").innerHTML = Object.entries(f).map(([k,v]) =>
      `<div class="chip"><b>${v}</b><span>${k}</span></div>`).join("");
    await fetchJobs();
  } catch(e){ if (e.message!=="auth") $("#msg").textContent = "Error: "+e.message; }
}

// --- views (jobs / config / rubric / usage) -------------------------------
let VIEW = "jobs";
const LOADERS = { jobs: load, config: loadConfig, rubric: loadRubric, usage: loadUsage };
function showView(v) {
  VIEW = v;
  $("#jobsView").style.display   = v==="jobs"   ? "" : "none";
  $("#configView").style.display = v==="config" ? "" : "none";
  $("#rubricView").style.display = v==="rubric" ? "" : "none";
  $("#usageView").style.display  = v==="usage"  ? "" : "none";
  $("#jobsTools").style.display  = v==="jobs"   ? "" : "none";
  document.querySelectorAll(".navbtn").forEach(b => b.classList.toggle("on", b.dataset.view===v));
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

// --- usage view ---
function fmtTok(n){ n=n||0; return n>=1000 ? (n/1000).toFixed(1)+"k" : ""+n; }
async function loadUsage() {
  if (!TOKEN) return showAuth("Enter your API token to view usage.");
  $("#useMsg").textContent = "loading…";
  try {
    const u = await (await api("/api/usage")).json();
    const t = u.totals;
    // claude-cli spends Pro quota (calls), not $ — lead with calls; show api $ only if real.
    const apiCost = (u.by_engine||[]).filter(e => e.engine==="anthropic")
                      .reduce((s,e) => s+(e.cost_usd||0), 0);
    $("#useTotals").innerHTML =
      `<div class="chip"><b>${t.calls}</b><span>calls</span></div>`+
      `<div class="chip"><b>${t.runs}</b><span>runs</span></div>`+
      `<div class="chip"><b>${t.scored}</b><span>scored</span></div>`+
      `<div class="chip"><b>${fmtTok(t.input_tokens)}</b><span>in tok</span></div>`+
      `<div class="chip"><b>${fmtTok(t.output_tokens)}</b><span>out tok</span></div>`+
      (apiCost>0 ? `<div class="chip"><b>$${apiCost.toFixed(4)}</b><span>api $</span></div>` : "");
    const rows = (u.runs||[]).map(r => {
      const calls = (r.scored||0)+(r.errors||0);
      const cli = (r.engine||"").indexOf("cli") >= 0;
      const costCell = cli ? '<span class="muted">Pro</span>' : `$${(r.cost_usd||0).toFixed(4)}`;
      return `<tr>
        <td>${ago(r.started_at)||"—"}</td><td>${esc(r.engine||r.stage)}</td><td>${esc(r.model)}</td>
        <td>${calls}</td><td>${r.scored}/${r.jobs}</td>
        <td>${fmtTok(r.input_tokens)} / ${fmtTok(r.output_tokens)}</td>
        <td>${costCell}</td>
        <td>${r.budget_hit?'<span class="warn">⛔ limit</span>':(r.errors?r.errors+" err":"")}</td></tr>`;
    }).join("");
    $("#useBox").innerHTML = rows
      ? `<table class="usage"><tr><th>when</th><th>engine</th><th>model</th><th>calls</th>`
        + `<th>scored</th><th>tok in/out</th><th>cost</th><th></th></tr>${rows}</table>`
      : '<div class="muted">No LLM runs yet — hit ✨ Analyze.</div>';
    $("#useMsg").textContent = "";
  } catch(e){ if (e.message!=="auth") $("#useMsg").textContent = "Error: "+e.message; }
}

// --- triage (✨ Analyze) ---
async function triage(target) {
  try {
    const r = await api("/api/analyze", {
      method:"POST", headers:{ "content-type":"application/json" },
      body: JSON.stringify({ mode:"triage", target }) });
    if (r.status===409) { $("#msg").textContent = "Triage already running…"; return; }
    $("#msg").textContent = "✨ Triage started…";
    pollAnalyze();
  } catch(e){}
}
async function pollAnalyze() {
  try {
    const s = await (await api("/api/analyze")).json();
    if (s.running) { $("#msg").textContent = "✨ Triage running…"; setTimeout(pollAnalyze, 2000); return; }
    const last = s.last || {};
    if (last.auth_failed)
      $("#msg").innerHTML = '<span class="warn">⛔ Claude not logged in — set '
        + 'CLAUDE_CODE_OAUTH_TOKEN (claude setup-token) and redeploy.</span>';
    else if (last.budget_hit)
      $("#msg").innerHTML = '<span class="warn">⛔ Out of budget / rate limited — triage stopped.</span>';
    else if (last.totals)
      $("#msg").textContent = `✨ Triage done — scored ${last.totals.scored} (${last.totals.errors||0} err)`;
    fetchJobs();
  } catch(e){}
}

// --- wiring ---
document.querySelectorAll(".navbtn").forEach(b => b.onclick = () => { showView(b.dataset.view); refreshView(); });
document.querySelectorAll(".back").forEach(b => b.onclick = () => { showView("jobs"); load(); });
$("#save").onclick = () => { TOKEN = $("#token").value.trim(); localStorage.setItem("jr_token", TOKEN); refreshView(); };
$("#refresh").onclick = refreshView;
$("#cfgSave").onclick = saveConfig;
$("#cfgReload").onclick = loadConfig;
$("#rubSave").onclick = saveRubric;
$("#rubReload").onclick = loadRubric;
$("#useReload").onclick = loadUsage;
$("#sort").onchange = viewJobs;
let qTimer;  // debounce server-side search so we don't refetch on every keystroke
$("#q").oninput = () => { clearTimeout(qTimer); qTimer = setTimeout(fetchJobs, 300); };
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
$("#analyze").onclick = () => triage("all_pending");
// per-card ✨ button → triage just that one job (event delegation; re-scores even
// if already triaged, since the server treats an explicit job_id list as force).
$("#list").onclick = (e) => {
  const b = e.target.closest("button.mini");
  if (b && b.dataset.jid) triage([b.dataset.jid]);
};
load();
</script>
</body>
</html>
"""
