"use strict";

const CATEGORIES = {
  1: "Film & Animation", 2: "Autos & Vehicles", 10: "Music", 15: "Pets & Animals", 17: "Sports",
  19: "Travel & Events", 20: "Gaming", 22: "People & Blogs", 23: "Comedy", 24: "Entertainment",
  25: "News & Politics", 26: "Howto & Style", 27: "Education", 28: "Science & Technology",
};
const STATUS_LABEL = { draft: "Draft", queued: "Queued", uploading: "Uploading", done: "Uploaded", failed: "Failed" };

const $ = (sel, root = document) => root.querySelector(sel);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const enc = encodeURIComponent;

const S = { status: null, videos: [], settings: null, selected: new Set(), editing: null, uploads: null };

async function api(path, opts = {}) {
  const init = { ...opts };
  if (opts.json !== undefined) {
    init.body = JSON.stringify(opts.json);
    init.headers = { "Content-Type": "application/json" };
  }
  const r = await fetch(path, init);
  const body = r.headers.get("content-type")?.includes("json") ? await r.json() : await r.text();
  if (!r.ok) throw new Error(body?.detail || body || r.statusText);
  return body;
}

function toast(msg, ms = 3500) {
  const t = $("#toast");
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => (t.hidden = true), ms);
}

// ---------- time helpers ----------
const browserTz = Intl.DateTimeFormat().resolvedOptions().timeZone;
function fmt(iso, tz = browserTz, opts = {}) {
  if (!iso) return "";
  return new Intl.DateTimeFormat(undefined, {
    timeZone: tz, weekday: "short", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", ...opts,
  }).format(new Date(iso));
}
function toLocalInput(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
}
const fromLocalInput = (v) => (v ? new Date(v).toISOString().replace(/\.\d{3}Z$/, "Z") : null);
const chTz = () => S.settings?.channel_tz || "America/New_York";
const tzShort = (tz) => tz.split("/").pop().replace(/_/g, " ");

// ---------- routing ----------
const VIEWS = { dashboard: renderDashboard, content: renderContent, calendar: renderCalendar, insights: renderInsights, settings: renderSettings };
function route() {
  const view = (location.hash.slice(1) || "dashboard");
  const name = VIEWS[view] ? view : "dashboard";
  document.querySelectorAll(".view").forEach((v) => v.classList.toggle("active", v.id === `view-${name}`));
  document.querySelectorAll(".sidebar a").forEach((a) => a.classList.toggle("active", a.dataset.view === name));
  VIEWS[name]();
}
window.addEventListener("hashchange", route);

// ---------- data refresh ----------
async function refresh() {
  [S.status, S.videos] = await Promise.all([api("/api/status"), api("/api/videos")]);
  renderAccount();
}
let pollTimer;
function schedulePoll() {
  clearTimeout(pollTimer);
  const busy = S.videos.some((v) => ["queued", "uploading"].includes(v.status)) || S.status?.auth.state === "connecting";
  pollTimer = setTimeout(async () => {
    const wasConnecting = S.status?.auth.state === "connecting";
    await refresh().catch(() => {});
    if (wasConnecting && S.status.auth.state === "connected") toast(`Connected to ${S.status.channel?.title || "YouTube"}`);
    if (wasConnecting && S.status.auth.error) toast("Sign-in failed: " + S.status.auth.error, 6000);
    const active = location.hash.slice(1) || "dashboard";
    if (active === "content" || active === "dashboard") route();
    schedulePoll();
  }, busy ? 2000 : 15000);
}

// ---------- account ----------
function renderAccount() {
  const { auth, channel } = S.status;
  const acc = $("#account");
  const card = $("#channelCard");
  if (auth.state === "connected" && channel) {
    acc.innerHTML = `<span class="muted">${esc(channel.handle || "")}</span><img src="${esc(channel.avatar)}" alt="">`;
    card.innerHTML = `<img src="${esc(channel.avatar)}" alt=""><div class="name">Your channel</div><div class="sub">${esc(channel.title)}</div>`;
  } else {
    const label = { connecting: "Waiting for Google sign-in…", no_client_secret: "client_secret.json missing" }[auth.state];
    acc.innerHTML = label ? `<span class="muted">${label}</span>` : `<button class="primary blue" id="connectTop">Connect YouTube</button>`;
    card.innerHTML = `<div class="name">Not connected</div><div class="sub">Sign in with the channel's Google account</div>`;
    $("#connectTop")?.addEventListener("click", connect);
  }
}
async function connect() {
  try {
    await api("/api/auth/connect", { method: "POST" });
    toast("A Google sign-in tab opened. Pick the Oddtoon channel and allow access.", 6000);
    await refresh();
    schedulePoll();
  } catch (e) { toast(e.message); }
}

// ---------- dashboard ----------
async function renderDashboard() {
  const el = $("#view-dashboard");
  const { auth, channel, quota_used, quota_limit, paused } = S.status;
  const counts = S.videos.reduce((a, v) => ((a[v.status] = (a[v.status] || 0) + 1), a), {});
  const scheduled = S.videos.filter((v) => v.meta.publish_at && v.status !== "done")
    .sort((a, b) => a.meta.publish_at.localeCompare(b.meta.publish_at)).slice(0, 5);
  const pct = Math.min(100, (quota_used / quota_limit) * 100);
  const left = Math.floor((quota_limit - quota_used) / 1600);

  el.innerHTML = `
    <h1>Channel dashboard</h1>
    ${auth.state === "no_client_secret" ? `<div class="banner">Put <b>client_secret.json</b> in the <code>credentials</code> folder, then reload.</div>` : ""}
    ${auth.state === "disconnected" ? `<div class="banner">Not connected. <button class="ghost" id="dConnect">Connect YouTube</button>${auth.error ? `<br><span class="muted">Last error: ${esc(auth.error)}</span>` : ""}</div>` : ""}
    ${paused ? `<div class="banner">Uploads are paused because the daily quota ran out. <button class="ghost" id="resume">Resume</button></div>` : ""}
    <div class="grid">
      <div class="card">
        <h3>Library</h3>
        <div class="stat">${S.videos.length}</div><div class="muted">videos in the folder</div>
        <ul class="list" style="margin-top:12px">
          ${Object.keys(STATUS_LABEL).map((k) => `<li><span>${STATUS_LABEL[k]}</span><b>${counts[k] || 0}</b></li>`).join("")}
        </ul>
      </div>
      <div class="card">
        <h3>API quota today</h3>
        <div class="stat">${quota_used.toLocaleString()}<span class="muted" style="font-size:16px"> / ${quota_limit.toLocaleString()}</span></div>
        <div class="meter"><div style="width:${pct}%"></div></div>
        <div class="muted">Room for about ${left} more upload${left === 1 ? "" : "s"}. Resets at midnight Pacific. Local estimate.</div>
      </div>
      <div class="card">
        <h3>Coming up</h3>
        ${scheduled.length ? `<ul class="list">${scheduled.map((v) => `<li><span class="vtitle" style="max-width:180px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(v.meta.title)}</span><span class="muted">${fmt(v.meta.publish_at)}</span></li>`).join("")}</ul>`
          : `<p class="muted">Nothing scheduled. Pick videos in Content and press Auto-schedule.</p>`}
      </div>
      <div class="card">
        <h3>Latest on YouTube</h3>
        <div id="dUploads" class="muted">${auth.state === "connected" ? "Loading…" : "Connect to see your uploads."}</div>
      </div>
    </div>`;
  $("#dConnect")?.addEventListener("click", connect);
  $("#resume")?.addEventListener("click", async () => { await api("/api/queue/resume", { method: "POST" }); await refresh(); route(); });

  if (auth.state === "connected") {
    try {
      S.uploads = S.uploads || (await api("/api/uploads"));
      const box = $("#dUploads");
      if (!box) return;
      box.innerHTML = S.uploads.length
        ? `<ul class="list">${S.uploads.slice(0, 5).map((u) => `<li><a href="https://youtube.com/watch?v=${esc(u.id)}" target="_blank" rel="noopener" class="vtitle" style="max-width:190px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--text);text-decoration:none">${esc(u.title)}</a><span class="muted">${u.publish_at ? "⏱ " + fmt(u.publish_at, browserTz, { weekday: undefined }) : u.views.toLocaleString() + " views"}</span></li>`).join("")}</ul>`
        : "No videos yet.";
    } catch (e) { const b = $("#dUploads"); if (b) b.textContent = e.message; }
  }
}

// ---------- content ----------
function checkBadge(checks) {
  const e = checks.filter((c) => c.level === "error").length;
  const w = checks.filter((c) => c.level === "warn").length;
  if (e) return `<span class="badge error">${e} error${e > 1 ? "s" : ""}</span>`;
  if (w) return `<span class="badge warn">${w} warning${w > 1 ? "s" : ""}</span>`;
  return `<span class="badge ok">Ready</span>`;
}
function statusCell(v) {
  const st = v.state || {};
  let html = `<span class="chip ${v.status}">${STATUS_LABEL[v.status] || v.status}</span>`;
  if (v.status === "uploading") html += `<div class="bar"><div style="width:${st.progress || 0}%"></div></div><small class="muted">${st.progress || 0}%</small>`;
  if (v.status === "done" && st.youtube_id) html += `<div><a href="https://studio.youtube.com/video/${esc(st.youtube_id)}/edit" target="_blank" rel="noopener">Open in Studio</a></div>`;
  if (st.error) html += `<div class="muted" style="max-width:220px;font-size:12px">${esc(st.error)}</div>`;
  for (const w of st.warnings || []) html += `<div style="color:var(--amber);max-width:240px;font-size:12px">${esc(w)}</div>`;
  return html;
}
function whenCell(v) {
  if (v.status === "done") return v.state.result_publish_at ? fmt(v.state.result_publish_at) : `<span class="muted">${esc(v.state.result_privacy || "")}</span>`;
  if (v.meta.publish_at) return `${fmt(v.meta.publish_at)}<div class="muted" style="font-size:12px">${fmt(v.meta.publish_at, chTz(), { weekday: undefined, month: undefined, day: undefined })} ${tzShort(chTz())}</div>`;
  return `<span class="muted">${v.meta.privacy === "public" ? "Public on upload" : esc(v.meta.privacy)}</span>`;
}

function renderContent() {
  const el = $("#view-content");
  const keep = el.querySelector("#search")?.value || "";
  S.selected = new Set([...S.selected].filter((n) => S.videos.some((v) => v.name === n)));
  const sel = [...S.selected];
  el.innerHTML = `
    <h1>Channel content</h1>
    <div class="drop" id="drop">Drag video files here, or <label class="link" style="cursor:pointer">browse<input type="file" id="pick" accept="video/*" multiple hidden></label></div>
    <div class="toolbar">
      <input type="text" id="search" placeholder="Filter by title" value="${esc(keep)}">
      <span class="spacer"></span>
      <span class="muted">${sel.length ? sel.length + " selected" : ""}</span>
      <button class="ghost" id="autoSched" ${sel.length ? "" : "disabled"}>Auto-schedule</button>
      <button class="ghost" id="retry" ${sel.length ? "" : "disabled"}>Retry failed</button>
      <button class="primary blue" id="upSel" ${sel.length ? "" : "disabled"}>Upload selected</button>
    </div>
    ${S.videos.length ? `<table>
      <thead><tr><th style="width:32px"><input type="checkbox" id="all"></th><th>Video</th><th>Status</th><th>Schedule</th><th>Checks</th></tr></thead>
      <tbody>${S.videos.filter((v) => v.meta.title.toLowerCase().includes(keep.toLowerCase())).map((v) => `
        <tr class="row" data-name="${esc(v.name)}">
          <td><input type="checkbox" class="pick" ${S.selected.has(v.name) ? "checked" : ""} ${["uploading", "done"].includes(v.status) ? "disabled" : ""}></td>
          <td><div style="display:flex;gap:16px;align-items:center">
            ${v.has_thumbnail ? `<img class="vthumb" src="/api/videos/${enc(v.name)}/thumbnail" alt="">` : `<video class="vthumb" src="/api/videos/${enc(v.name)}/file#t=1" preload="metadata" muted></video>`}
            <div><div class="vtitle">${esc(v.meta.title)}</div><div class="vdesc">${esc(v.meta.description.split("\n")[0] || v.name)}</div></div>
          </div></td>
          <td>${statusCell(v)}</td>
          <td>${whenCell(v)}</td>
          <td>${checkBadge(v.checks)}</td>
        </tr>`).join("")}</tbody></table>`
      : `<div class="empty">No videos yet. Drop rendered MP4s above, or copy them into the <code>videos</code> folder.</div>`}`;

  const drop = $("#drop");
  ["dragenter", "dragover"].forEach((t) => drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.add("over"); }));
  ["dragleave", "drop"].forEach((t) => drop.addEventListener(t, () => drop.classList.remove("over")));
  drop.addEventListener("drop", (e) => { e.preventDefault(); addFiles(e.dataTransfer.files); });
  $("#pick").addEventListener("change", (e) => addFiles(e.target.files));
  $("#search").addEventListener("input", () => { renderContent(); const s = $("#search"); s.focus(); s.setSelectionRange(s.value.length, s.value.length); });

  el.querySelectorAll("tr.row").forEach((tr) => tr.addEventListener("click", (e) => {
    if (e.target.closest("input,a")) return;
    openDetails(tr.dataset.name);
  }));
  el.querySelectorAll(".pick").forEach((cb) => cb.addEventListener("change", () => {
    const n = cb.closest("tr").dataset.name;
    cb.checked ? S.selected.add(n) : S.selected.delete(n);
    renderContent();
  }));
  $("#all")?.addEventListener("change", (e) => {
    S.videos.forEach((v) => { if (!["uploading", "done"].includes(v.status)) e.target.checked ? S.selected.add(v.name) : S.selected.delete(v.name); });
    renderContent();
  });
  $("#autoSched").addEventListener("click", async () => {
    const r = await api("/api/schedule/auto", { method: "POST", json: { names: sel } });
    toast(`Scheduled ${Object.keys(r).length} video(s), one per slot.`);
    await refresh(); renderContent();
  });
  $("#upSel").addEventListener("click", () => queue(sel));
  $("#retry").addEventListener("click", async () => {
    await api("/api/queue/retry", { method: "POST", json: { names: sel } });
    await refresh(); renderContent(); schedulePoll();
  });
}

async function addFiles(files) {
  for (const f of files) {
    const fd = new FormData();
    fd.append("file", f);
    toast(`Adding ${f.name}…`, 60000);
    try { await api("/api/videos", { method: "POST", body: fd }); }
    catch (e) { toast(`${f.name}: ${e.message}`, 6000); return; }
  }
  toast(`Added ${files.length} file(s).`);
  await refresh(); renderContent();
}

async function queue(names) {
  const blocked = S.videos.filter((v) => names.includes(v.name) && v.checks.some((c) => c.level === "error"));
  if (blocked.length) { toast(`${blocked.length} video(s) have errors. Open them and fix the red checks first.`, 6000); return; }
  if (S.status.auth.state !== "connected") { toast("Connect YouTube first."); return; }
  await api("/api/queue", { method: "POST", json: { names } });
  S.selected.clear();
  toast(`Queued ${names.length} upload(s).`);
  await refresh(); route(); schedulePoll();
}

// ---------- details dialog ----------
const D = {};
function openDetails(name) {
  const v = S.videos.find((x) => x.name === name);
  if (!v) return;
  S.editing = name;
  const m = structuredClone(v.meta);
  D.meta = m;
  D.locked = ["uploading", "done"].includes(v.status);
  $("#dTitle").textContent = D.locked ? "Video details (uploaded — edit in YouTube Studio)" : "Video details";
  $("#fTitle").value = m.title;
  $("#fDesc").value = m.description;
  document.querySelector(`input[name=kids][value=${m.made_for_kids ? "yes" : "no"}]`).checked = true;
  document.querySelector(`input[name=synth][value=${m.synthetic_media ? "yes" : "no"}]`).checked = true;
  $("#fCat").innerHTML = Object.entries(CATEGORIES).map(([id, n]) => `<option value="${id}" ${String(m.category_id) === id ? "selected" : ""}>${n}</option>`).join("");
  document.querySelector(`input[name=vis][value=${m.publish_at ? "schedule" : m.privacy}]`).checked = true;
  $("#fWhen").value = toLocalInput(m.publish_at);
  $("#fNotify").checked = m.notify_subscribers;
  renderTags();
  $("#pv").src = `/api/videos/${enc(name)}/file`;
  $("#pvName").textContent = name;
  const p = v.probe;
  $("#pvFmt").textContent = p ? `${p.width}×${p.height} · ${p.duration ? p.duration.toFixed(1) + "s" : "?"}${p.height >= p.width ? " · vertical" : ""}` : "ffprobe not found";
  const tp = $("#thumbPreview");
  tp.hidden = !v.has_thumbnail;
  if (v.has_thumbnail) tp.src = `/api/videos/${enc(name)}/thumbnail?${Date.now()}`;
  document.querySelectorAll("#details textarea, #details input, #details select, #saveBtn, #saveUpload").forEach((x) => (x.disabled = D.locked));
  $("#saveState").textContent = "";
  updateCounts();
  updateSchedUi();
  renderChecks(v.checks);
  $("#details").hidden = false;
}
function closeDetails() {
  $("#details").hidden = true;
  $("#pv").pause();
  $("#pv").removeAttribute("src");
  S.editing = null;
}
document.querySelectorAll("[data-close]").forEach((b) => b.addEventListener("click", closeDetails));
$("#details").addEventListener("click", (e) => { if (e.target.id === "details") closeDetails(); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !$("#details").hidden) closeDetails(); });

function collect() {
  const m = D.meta;
  m.title = $("#fTitle").value;
  m.description = $("#fDesc").value;
  m.made_for_kids = document.querySelector("input[name=kids]:checked")?.value === "yes";
  m.synthetic_media = document.querySelector("input[name=synth]:checked")?.value === "yes";
  m.category_id = $("#fCat").value;
  const vis = document.querySelector("input[name=vis]:checked")?.value || "public";
  m.publish_at = vis === "schedule" ? fromLocalInput($("#fWhen").value) : null;
  m.privacy = vis === "schedule" ? "private" : vis;
  m.notify_subscribers = $("#fNotify").checked;
  return m;
}

function tagChars(tags) { return tags.reduce((n, t) => n + t.length + (t.includes(" ") ? 2 : 0), 0) + Math.max(tags.length - 1, 0); }
function updateCounts() {
  const set = (id, n, max) => { const c = $(id); c.textContent = `${n}/${max}`; c.classList.toggle("over", n > max); };
  set("#cTitle", $("#fTitle").value.length, 100);
  set("#cDesc", $("#fDesc").value.length, 5000);
  set("#cTags", tagChars(D.meta.tags), 500);
}
function renderTags() {
  const box = $("#tagBox");
  box.querySelectorAll(".tag").forEach((t) => t.remove());
  D.meta.tags.forEach((t, i) => {
    const s = document.createElement("span");
    s.className = "tag";
    s.innerHTML = `${esc(t)}<button type="button" aria-label="Remove ${esc(t)}">✕</button>`;
    s.querySelector("button").addEventListener("click", () => { if (D.locked) return; D.meta.tags.splice(i, 1); renderTags(); liveCheck(); });
    box.insertBefore(s, $("#fTag"));
  });
  updateCounts();
}
$("#fTag").addEventListener("keydown", (e) => {
  const input = e.target;
  if (e.key === "Enter" || e.key === ",") {
    e.preventDefault();
    input.value.split(",").map((t) => t.trim()).filter(Boolean).forEach((t) => { if (!D.meta.tags.includes(t)) D.meta.tags.push(t); });
    input.value = "";
    renderTags(); liveCheck();
  } else if (e.key === "Backspace" && !input.value && D.meta.tags.length) {
    D.meta.tags.pop(); renderTags(); liveCheck();
  }
});
$("#tagBox").addEventListener("click", () => $("#fTag").focus());

function updateSchedUi() {
  const on = document.querySelector("input[name=vis]:checked")?.value === "schedule";
  $("#schedBox").classList.toggle("on", on);
  const iso = fromLocalInput($("#fWhen").value);
  $("#whenHint").textContent = on && iso
    ? `Your time (${tzShort(browserTz)}): ${fmt(iso)} · Audience (${tzShort(chTz())}): ${fmt(iso, chTz())} · UTC: ${fmt(iso, "UTC")}`
    : on ? "Pick a date and time. Goes public automatically at that moment." : "";
}
document.querySelectorAll("input[name=vis]").forEach((r) => r.addEventListener("change", () => { updateSchedUi(); liveCheck(); }));
$("#fWhen").addEventListener("input", () => { updateSchedUi(); liveCheck(); });
$("#nextSlot").addEventListener("click", async () => {
  const slots = await api("/api/schedule/next?count=1");
  $("#fWhen").value = toLocalInput(slots[0]);
  updateSchedUi(); liveCheck();
});
["#fTitle", "#fDesc"].forEach((id) => $(id).addEventListener("input", () => { updateCounts(); liveCheck(); }));
document.querySelectorAll("input[name=kids], input[name=synth], #fCat, #fNotify").forEach((x) => x.addEventListener("change", liveCheck));
$("#useTemplate").addEventListener("click", () => {
  const d = $("#fDesc");
  const tpl = (S.settings?.description_template || "").replace("{hook}", "One line that makes people stay.").replace("{summary}", "Two or three sentences on what really happened.");
  d.value = d.value ? d.value + "\n\n" + tpl : tpl;
  updateCounts(); liveCheck();
});
$("#fThumb").addEventListener("change", async (e) => {
  const f = e.target.files[0];
  if (!f) return;
  const fd = new FormData();
  fd.append("file", f);
  try {
    await api(`/api/videos/${enc(S.editing)}/thumbnail`, { method: "POST", body: fd });
    const tp = $("#thumbPreview");
    tp.src = `/api/videos/${enc(S.editing)}/thumbnail?${Date.now()}`;
    tp.hidden = false;
    toast("Thumbnail saved.");
  } catch (err) { toast(err.message); }
  e.target.value = "";
});

let checkTimer;
function liveCheck() {
  if (D.locked) return;
  $("#saveState").textContent = "Unsaved changes";
  clearTimeout(checkTimer);
  checkTimer = setTimeout(async () => {
    try { renderChecks(await api(`/api/videos/${enc(S.editing)}/check`, { method: "POST", json: collect() })); } catch {}
  }, 350);
}
function renderChecks(checks) {
  const ul = $("#checkList");
  const order = { error: 0, warn: 1, info: 2 };
  const sorted = [...checks].sort((a, b) => order[a.level] - order[b.level]);
  ul.innerHTML = sorted.length
    ? sorted.map((c) => `<li class="${c.level}"><span><b>${esc(c.field.replace("_", " "))}:</b> ${esc(c.msg)}</span></li>`).join("")
    : `<li class="ok">No problems found. Ready to upload.</li>`;
  $("#saveUpload").disabled = D.locked || checks.some((c) => c.level === "error");
}

async function save() {
  const r = await api(`/api/videos/${enc(S.editing)}/meta`, { method: "PUT", json: collect() });
  renderChecks(r.checks);
  $("#saveState").textContent = "Saved";
  await refresh();
  return r;
}
$("#saveBtn").addEventListener("click", async () => { try { await save(); route(); } catch (e) { toast(e.message); } });
$("#saveUpload").addEventListener("click", async () => {
  try {
    const r = await save();
    if (r.checks.some((c) => c.level === "error")) return;
    const name = S.editing;
    closeDetails();
    await queue([name]);
  } catch (e) { toast(e.message); }
});

// ---------- calendar ----------
async function renderCalendar() {
  const el = $("#view-calendar");
  el.innerHTML = `<h1>Schedule</h1><p class="muted">Loading…</p>`;
  let yt = [];
  if (S.status.auth.state === "connected") {
    try { yt = (await api("/api/uploads")).filter((u) => u.publish_at); } catch {}
  }
  const free = await api("/api/schedule/next?count=14");
  const items = [
    ...S.videos.filter((v) => v.meta.publish_at && v.status !== "done").map((v) => ({ when: v.meta.publish_at, title: v.meta.title, kind: "local", name: v.name })),
    ...yt.map((u) => ({ when: u.publish_at, title: u.title, kind: "yt" })),
    ...free.map((f) => ({ when: f, title: "Free slot", kind: "free" })),
  ];
  const tz = chTz();
  const dayKey = (iso) => new Intl.DateTimeFormat("en-CA", { timeZone: tz }).format(new Date(iso));
  const today = new Date();
  const days = [...Array(14)].map((_, i) => new Date(today.getTime() + i * 864e5));
  el.innerHTML = `
    <h1>Schedule</h1>
    <p class="hint">Next two weeks in your audience's time zone (${esc(tz)}). Blue: waiting here. Red: already scheduled on YouTube. Dashed: open slot.</p>
    <div class="cal">${days.map((d, i) => {
      const k = dayKey(d.toISOString());
      const list = items.filter((x) => dayKey(x.when) === k).sort((a, b) => a.when.localeCompare(b.when));
      return `<div class="day ${i === 0 ? "today" : ""}"><div class="dname">${new Intl.DateTimeFormat(undefined, { timeZone: tz, weekday: "short", month: "short", day: "numeric" }).format(d)}</div>
        ${list.map((x) => `<div class="item ${x.kind}" ${x.name ? `data-name="${esc(x.name)}"` : ""}><b>${fmt(x.when, tz, { weekday: undefined, month: undefined, day: undefined })}</b> ${esc(x.title)}</div>`).join("")}</div>`;
    }).join("")}</div>`;
  el.querySelectorAll(".item.local").forEach((it) => it.addEventListener("click", () => openDetails(it.dataset.name)));
}

// ---------- insights ----------
async function renderInsights() {
  const el = $("#view-insights");
  if (S.status.auth.state !== "connected") {
    el.innerHTML = `<h1>Insights</h1><div class="banner">Connect YouTube to read your analytics.</div>`;
    return;
  }
  el.innerHTML = `<h1>Insights</h1><p class="muted">Reading YouTube Analytics…</p>`;
  let d;
  try { d = await api("/api/insights"); } catch (e) { el.innerHTML = `<h1>Insights</h1><div class="banner">${esc(e.message)}</div>`; return; }
  const maxWd = Math.max(1, ...d.weekdays.map((w) => w.avg_views));
  const cur = S.settings.slot_times.join(", ");
  el.innerHTML = `
    <h1>Insights</h1>
    <div class="grid">
      <div class="card">
        <h3>Best time to publish</h3>
        ${d.suggested_slot
          ? `<div class="stat">${d.suggested_slot}</div><div class="muted">${esc(d.tz)}, based on first-week views by publish hour.</div>
             <p>Current slot: <b>${esc(cur)}</b></p>${d.suggested_slot !== cur ? `<button class="primary blue" id="useSlot">Use ${d.suggested_slot}</button>` : ""}`
          : `<div class="stat">${esc(cur)}</div><div class="muted">Default slot (${esc(d.tz)}).</div>`}
        ${d.notes.map((n) => `<p class="hint">${esc(n)}</p>`).join("")}
      </div>
      <div class="card">
        <h3>Views by weekday (last 90 days)</h3>
        <div class="bars">${d.weekdays.map((w) => `<div class="b"><span>${Math.round(w.avg_views)}</span><div style="height:${(w.avg_views / maxWd) * 100}%"></div><span>${w.day}</span></div>`).join("")}</div>
      </div>
      <div class="card">
        <h3>Where viewers are</h3>
        ${d.countries.length ? `<ul class="list">${d.countries.map((c) => `<li><span>${esc(c.country)}</span><b>${c.views.toLocaleString()}</b></li>`).join("")}</ul>` : `<p class="muted">No data yet.</p>`}
        <p class="hint">If most views come from one region, set the audience time zone in Settings to match.</p>
      </div>
      <div class="card">
        <h3>Publish hour vs first-week views</h3>
        ${d.hours.length ? `<ul class="list">${d.hours.map((h) => `<li><span>${String(h.hour).padStart(2, "0")}:00</span><span class="muted">${h.videos} video${h.videos > 1 ? "s" : ""}</span><b>${h.avg_views_7d.toLocaleString()}</b></li>`).join("")}</ul>` : `<p class="muted">Not enough public videos older than a week.</p>`}
      </div>
    </div>`;
  $("#useSlot")?.addEventListener("click", async () => {
    S.settings = await api("/api/settings", { method: "PUT", json: { slot_times: [d.suggested_slot] } });
    toast(`Publish slot set to ${d.suggested_slot}.`);
    renderInsights();
  });
}

// ---------- settings ----------
function renderSettings() {
  const s = S.settings;
  const el = $("#view-settings");
  el.innerHTML = `
    <h1>Settings</h1>
    <div class="settings">
      <label><span>Audience time zone</span>
        <input type="text" id="sTz" value="${esc(s.channel_tz)}" list="tzList">
        <datalist id="tzList">${["America/New_York", "America/Chicago", "America/Los_Angeles", "Europe/London", "Europe/Berlin", "Asia/Kolkata", "Asia/Tehran", "Australia/Sydney"].map((t) => `<option value="${t}">`).join("")}</datalist>
        <p class="hint">Auto-schedule plans slots in this zone. Most English-language Shorts traffic is US, so New York is the default.</p>
      </label>
      <label><span>Daily publish slots</span>
        <input type="text" id="sSlots" value="${esc(s.slot_times.join(", "))}">
        <p class="hint">24-hour times, comma separated, e.g. 15:00 or 12:00, 19:00. One video per slot.</p>
      </label>
      <label><span>Default category</span>
        <select id="sCat">${Object.entries(CATEGORIES).map(([id, n]) => `<option value="${id}" ${String(s.category_id) === id ? "selected" : ""}>${n}</option>`).join("")}</select>
      </label>
      <label><span>Default tags</span>
        <input type="text" id="sTags" value="${esc(s.default_tags.join(", "))}">
      </label>
      <label><span>Description template</span>
        <textarea id="sTpl">${esc(s.description_template)}</textarea>
        <p class="hint">{hook} and {summary} become placeholders. Keep it short: a real sentence or two and 2-3 hashtags beat a keyword list.</p>
      </label>
      <label class="check"><input type="checkbox" id="sNotify" ${s.notify_subscribers ? "checked" : ""}> Notify subscribers by default</label>
      <div><button class="primary blue" id="sSave">Save settings</button></div>
      <div class="card">
        <h3>YouTube account</h3>
        <p class="muted">${S.status.auth.state === "connected" ? `Connected as ${esc(S.status.channel?.title || "")}` : "Not connected"}</p>
        ${S.status.auth.state === "connected" ? `<button class="ghost" id="sDisc">Disconnect</button>` : `<button class="primary blue" id="sConn">Connect YouTube</button>`}
      </div>
    </div>`;
  $("#sSave").addEventListener("click", async () => {
    try {
      S.settings = await api("/api/settings", { method: "PUT", json: {
        channel_tz: $("#sTz").value.trim(),
        slot_times: $("#sSlots").value.split(",").map((x) => x.trim()).filter(Boolean),
        category_id: $("#sCat").value,
        default_tags: $("#sTags").value.split(",").map((x) => x.trim()).filter(Boolean),
        description_template: $("#sTpl").value,
        notify_subscribers: $("#sNotify").checked,
      } });
      toast("Settings saved.");
    } catch (e) { toast(e.message); }
  });
  $("#sDisc")?.addEventListener("click", async () => { await api("/api/auth/disconnect", { method: "POST" }); S.uploads = null; await refresh(); renderSettings(); });
  $("#sConn")?.addEventListener("click", connect);
}

// ---------- boot ----------
(async function boot() {
  try {
    S.settings = await api("/api/settings");
    await refresh();
  } catch (e) {
    document.body.innerHTML = `<p style="padding:40px">Can't reach the uploader server: ${esc(e.message)}</p>`;
    return;
  }
  route();
  schedulePoll();
})();
