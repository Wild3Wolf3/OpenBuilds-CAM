"use strict";
// Kiln controller web UI. No build step, no external libraries: it has to
// work on a kiln-shed network with no internet access.

const MAX_STEPS = 35;
const ROOM_C = 21;
const $ = (id) => document.getElementById(id);

const S = {
  settings: { units: "F" },
  status: null,
  profiles: [],
  editing: null,      // profile being edited {id?, builtin?, name, description, steps}
  run: { run_id: null, plan: [], points: [] },
  ws: null,
};

// ---------------------------------------------------------------- units --
const isF = () => S.settings.units === "F";
const toU = (c) => (c == null ? null : isF() ? c * 9 / 5 + 32 : c);
const fromU = (u) => (isF() ? (u - 32) * 5 / 9 : u);
const dToU = (c) => (isF() ? c * 9 / 5 : c);
const dFromU = (u) => (isF() ? u * 5 / 9 : u);
const deg = () => (isF() ? "°F" : "°C");
const fmtT = (c) => (c == null ? "--" : Math.round(toU(c)) + deg());

function fmtDur(sec) {
  if (sec == null) return "—";
  sec = Math.max(0, Math.round(sec));
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60);
  return `${h}:${String(m).padStart(2, "0")}`;
}

// ------------------------------------------------------------------ api --
const PIN_TTL = 2 * 60 * 1000;  // remember an entered firing-lock PIN this long

async function api(path, opts = {}) {
  const init = { method: opts.method || "GET", headers: {} };
  if (opts.body !== undefined) {
    init.body = JSON.stringify(opts.body);
    init.headers["Content-Type"] = "application/json";
  }
  if (init.method !== "GET" && S.pin && Date.now() - S.pin.t < PIN_TTL) init.headers["X-Kiln-Pin"] = S.pin.v;
  const res = await fetch(path, init);
  if (res.status === 401) { showLogin(); throw new Error("login required"); }
  const text = await res.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = { error: text }; }
  if (data && data.pin_required) {
    // Firing lock: ask for the PIN and retry. 429 = too many wrong tries.
    S.pin = null;
    if (res.status === 429) throw new Error(data.error);
    const pin = await askPin(data.error);
    if (pin == null) throw new Error("cancelled");
    S.pin = { v: pin, t: Date.now() };
    return api(path, opts);
  }
  if (!res.ok) throw new Error((data && data.error) || text || res.statusText);
  return data;
}

function askPin(message) {
  return new Promise((resolve) => {
    const dlg = $("pin-dialog"), input = $("pin-input");
    $("pin-msg").textContent = message === "Firing lock PIN required" ? "Enter the firing lock PIN to change a running firing." : message;
    $("pin-msg").classList.toggle("error", message !== "Firing lock PIN required");
    input.value = "";
    dlg.hidden = false;
    input.focus();
    const done = (value) => { dlg.hidden = true; $("pin-form").onsubmit = $("pin-cancel").onclick = null; resolve(value); };
    $("pin-form").onsubmit = (e) => { e.preventDefault(); done(input.value); };
    $("pin-cancel").onclick = () => done(null);
  });
}

function toast(msg, ms = 3500) {
  const t = $("toast");
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => (t.hidden = true), ms);
}

async function act(fn) {
  try { return await fn(); } catch (e) { if (!["login required", "cancelled"].includes(e.message)) toast(e.message, 6000); }
}

// ----------------------------------------------------------------- tabs --
document.querySelectorAll(".tabs button").forEach((b) => b.addEventListener("click", () => showTab(b.dataset.tab)));
function showTab(name) {
  document.querySelectorAll(".tabs button").forEach((b) => b.setAttribute("aria-selected", b.dataset.tab === name));
  document.querySelectorAll(".tab").forEach((s) => (s.hidden = s.id !== "tab-" + name));
  if (name === "history") loadHistory();
  if (name === "settings") { renderSettings(); loadWifi(); }
  if (name === "profiles") drawProfileChart();
  if (name === "dash") drawLiveChart();
  try { localStorage.setItem("kiln-tab", name); } catch {}
}

// ---------------------------------------------------------------- chart --
function css(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }

// series: [{pts: [[sec, degC], ...], color, dash, width}]
function drawChart(canvas, series, opts = {}) {
  const dpr = window.devicePixelRatio || 1;
  if (!canvas.dataset.h) canvas.dataset.h = canvas.getAttribute("height");
  const h = +canvas.dataset.h;
  canvas.style.height = h + "px";
  const w = canvas.clientWidth;
  if (!w) return;
  canvas.width = w * dpr; canvas.height = h * dpr;
  const g = canvas.getContext("2d");
  g.scale(dpr, dpr);
  g.clearRect(0, 0, w, h);
  const all = series.flatMap((s) => s.pts);
  const pad = { l: 46, r: 10, t: 10, b: 26 };
  let maxT = Math.max(3600, ...all.map((p) => p[0]), opts.minTime || 0);
  let maxY = Math.max(toU(100), ...all.map((p) => toU(p[1])));
  let minY = Math.min(0, ...all.map((p) => toU(p[1])));
  const ystep = niceStep(maxY - minY, 5);
  maxY = Math.ceil(maxY / ystep) * ystep;
  const hours = maxT / 3600;
  const xstep = niceStep(hours, Math.max(2, Math.floor(w / 80)));
  maxT = Math.ceil(hours / xstep) * xstep * 3600;
  const X = (t) => pad.l + (t / maxT) * (w - pad.l - pad.r);
  const Y = (u) => h - pad.b - ((u - minY) / (maxY - minY)) * (h - pad.t - pad.b);

  g.font = "11px system-ui, sans-serif";
  g.fillStyle = css("--muted");
  g.strokeStyle = css("--border");
  g.lineWidth = 1;
  g.textAlign = "right"; g.textBaseline = "middle";
  for (let v = minY; v <= maxY + 1e-6; v += ystep) {
    g.beginPath(); g.moveTo(pad.l, Y(v)); g.lineTo(w - pad.r, Y(v)); g.stroke();
    g.fillText(Math.round(v) + "°", pad.l - 6, Y(v));
  }
  g.textAlign = "center"; g.textBaseline = "top";
  for (let v = 0; v <= maxT / 3600 + 1e-6; v += xstep) {
    g.fillText(+v.toFixed(2) + "h", X(v * 3600), h - pad.b + 6);
  }
  for (const s of series) {
    if (s.pts.length < 1) continue;
    g.strokeStyle = s.color; g.lineWidth = s.width || 2; g.setLineDash(s.dash || []);
    g.lineJoin = "round";
    g.beginPath();
    s.pts.forEach((p, i) => (i ? g.lineTo(X(p[0]), Y(toU(p[1]))) : g.moveTo(X(p[0]), Y(toU(p[1])))));
    g.stroke();
    if (s.endDot) {
      const p = s.pts[s.pts.length - 1];
      g.fillStyle = s.color; g.beginPath(); g.arc(X(p[0]), Y(toU(p[1])), 4, 0, 7); g.fill();
    }
  }
  g.setLineDash([]);
}

function niceStep(range, ticks) {
  const raw = range / ticks, mag = 10 ** Math.floor(Math.log10(raw || 1));
  for (const m of [1, 2, 2.5, 5, 10]) if (raw <= m * mag) return m * mag;
  return 10 * mag;
}

window.addEventListener("resize", () => { drawLiveChart(); drawProfileChart(); });

// ----------------------------------------------------------- dashboard --
function connect() {
  const ws = new WebSocket((location.protocol === "https:" ? "wss://" : "ws://") + location.host + "/ws");
  S.ws = ws;
  ws.onopen = () => $("conn").classList.add("ok");
  ws.onmessage = (ev) => onStatus(JSON.parse(ev.data));
  ws.onclose = () => {
    $("conn").classList.remove("ok");
    setTimeout(async () => { if (await checkAuth()) connect(); }, 3000);
  };
}

async function onStatus(st) {
  const prev = S.status;
  S.status = st;
  if (st.run_id !== S.run.run_id) {
    S.run = await api("/api/run").catch(() => S.run);
  } else if (st.state === "firing" || st.state === "holding") {
    const last = S.run.points[S.run.points.length - 1];
    if (!last || st.fire_time - last[0] >= 30) S.run.points.push([st.fire_time, st.temp, st.setpoint]);
  }
  renderStatus(st, prev);
}

function renderStatus(st, prev) {
  const active = st.state === "firing" || st.state === "holding";
  $("temp").textContent = st.temp == null ? "--" : Math.round(toU(st.temp));
  $("setpoint").textContent = active ? fmtT(st.setpoint) : "—";
  $("state").textContent = st.state;
  $("state").className = "pill " + st.state;
  $("catchup").hidden = !st.catching_up;
  $("duty").textContent = Math.round(st.duty * 100);
  $("duty-bar").style.width = st.duty * 100 + "%";
  $("heater-dot").classList.toggle("on", st.heater_on || (active && st.duty > 0));
  $("contactor").textContent = st.contactor_on ? "closed" : "open";
  $("s-profile").textContent = st.profile || "—";
  $("s-step").textContent = active ? `${st.step} / ${st.steps} · ${st.segment}` : "—";
  $("s-elapsed").textContent = st.profile ? fmtDur(st.fire_time) : "—";
  $("s-remaining").textContent = active ? "≈ " + fmtDur(st.remaining) : "—";
  $("s-energy").textContent = st.profile ? st.kwh.toFixed(1) + " kWh" : "—";
  $("s-cost").textContent = st.profile ? (S.settings.currency || "$") + st.cost.toFixed(2) : "—";
  $("sim-badge").hidden = !st.simulated;
  $("start-box").hidden = active;
  $("run-box").hidden = !active;
  $("btn-hold").textContent = st.state === "holding" ? "Resume" : "Hold";
  $("lock-note").hidden = !st.control_locked;

  let alertText = "";
  if (st.sensor_error) alertText = "Thermocouple: " + st.sensor_error;
  if (st.state === "error" || st.state === "complete" || st.state === "stopped") alertText = st.message;
  $("alert").hidden = !alertText;
  $("alert").classList.toggle("ok", st.state === "complete");
  $("alert-text").textContent = alertText;
  $("btn-ack").hidden = !["error", "complete", "stopped"].includes(st.state);
  document.title = (st.temp != null ? fmtT(st.temp) + " · " : "") + (S.settings.kiln_name || "Kiln");

  if (!prev || prev.camera !== st.camera) renderCamera(st.camera);
  if (!$("tab-dash").hidden) drawLiveChart();
}

function drawLiveChart() {
  if ($("tab-dash").hidden) return;
  const st = S.status;
  const pts = S.run.points.slice();
  if (st && st.temp != null && (st.state === "firing" || st.state === "holding")) pts.push([st.fire_time, st.temp]);
  drawChart($("chart"), [
    { pts: S.run.plan, color: css("--plan"), dash: [6, 5] },
    { pts, color: css("--actual"), width: 2.5, endDot: true },
  ]);
}

function renderCamera(on) {
  const wrap = $("cam-wrap");
  $("cam-snap").hidden = !on;
  wrap.innerHTML = "";
  if (on) {
    const img = document.createElement("img");
    img.alt = "Live kiln camera";
    img.src = "/camera/stream.mjpg?" + Date.now();
    img.onerror = () => setTimeout(() => (img.src = "/camera/stream.mjpg?" + Date.now()), 5000);
    wrap.appendChild(img);
  } else {
    wrap.innerHTML = '<span class="muted">No camera connected</span>';
  }
}

function fillStartSelect() {
  const sel = $("start-profile");
  const cur = sel.value;
  sel.innerHTML = "";
  for (const p of S.profiles) {
    const o = document.createElement("option");
    o.value = p.id;
    o.textContent = p.name + (p.builtin ? " (preset)" : "");
    sel.appendChild(o);
  }
  if (cur) sel.value = cur;
  startSummary();
}
function startSummary() {
  const p = S.profiles.find((x) => x.id === $("start-profile").value);
  $("start-summary").textContent = p
    ? `${p.steps.length} steps · peak ${fmtT(Math.max(...p.steps.map((s) => s.target)))} · ~${fmtDur(programSeconds(p.steps))} planned`
    : "";
}
$("start-profile").addEventListener("change", startSummary);

$("btn-start").onclick = () => {
  const p = S.profiles.find((x) => x.id === $("start-profile").value);
  if (!p) return;
  if (!confirm(`Start "${p.name}"?\n\nCheck the kiln is loaded, the lid is closed and nothing flammable is nearby.`)) return;
  act(() => api("/api/firing/start", { method: "POST", body: { profile_id: p.id } }));
};
$("btn-stop").onclick = () => confirm("Stop the firing? The kiln will cool naturally.") && act(() => api("/api/firing/stop", { method: "POST" }));
$("btn-estop").onclick = () => act(() => api("/api/firing/estop", { method: "POST" }));
$("btn-skip").onclick = () => confirm("Skip to the next step?") && act(() => api("/api/firing/skip", { method: "POST" }));
$("btn-hold").onclick = () => act(() => api("/api/firing/" + (S.status.state === "holding" ? "resume" : "hold"), { method: "POST" }));
$("btn-ack").onclick = () => act(() => api("/api/firing/ack", { method: "POST" }));

// ------------------------------------------------------------- profiles --
function programSeconds(steps) {
  return steps.reduce((a, s) => a + (+s.minutes || 0) * 60 + (+s.hold || 0) * 60, 0);
}

async function loadProfiles(selectId) {
  S.profiles = await api("/api/profiles");
  fillStartSelect();
  renderProfileList();
  const pick = S.profiles.find((p) => p.id === (selectId || (S.editing && S.editing.id)));
  if (pick) editProfile(pick);
  else if (!S.editing) newProfile();
}

function renderProfileList() {
  const ul = $("profile-list");
  ul.innerHTML = "";
  for (const p of S.profiles) {
    const li = document.createElement("li");
    li.className = S.editing && S.editing.id === p.id ? "active" : "";
    li.innerHTML = `<span></span><span class="tag">${p.builtin ? "preset" : "custom"}</span>`;
    li.firstChild.textContent = p.name;
    li.onclick = () => editProfile(p);
    ul.appendChild(li);
  }
}

function editProfile(p) {
  S.editing = JSON.parse(JSON.stringify(p));
  $("p-name").value = p.name;
  $("p-desc").value = p.description || "";
  renderSteps();
  renderProfileList();
  $("btn-save").textContent = p.builtin ? "Save (preset - use Save as new)" : "Save";
  $("btn-save").disabled = !!p.builtin;
  $("btn-delete").hidden = !p.id || p.builtin;
  $("p-error").hidden = true;
}

function newProfile() {
  editProfile({ name: "", description: "", steps: [{ target: 100, minutes: 60, hold: 0 }] });
}
$("btn-new").onclick = newProfile;

function stepStart(i) { return i === 0 ? ROOM_C : S.editing.steps[i - 1].target; }

function renderSteps() {
  const tb = $("steps");
  tb.innerHTML = "";
  S.editing.steps.forEach((s, i) => {
    const tr = document.createElement("tr");
    const rm = Math.round(s.minutes), hm = Math.round(s.hold);
    tr.innerHTML = `
      <td class="num">${i + 1}</td>
      <td class="tgt"><input type="number" inputmode="decimal" step="1" data-f="target" aria-label="Step ${i + 1} target temperature"></td>
      <td><div class="hm"><input type="number" min="0" data-f="rh" value="${Math.floor(rm / 60)}" aria-label="ramp hours">:<input type="number" min="0" max="59" data-f="rm" value="${rm % 60}" aria-label="ramp minutes"></div></td>
      <td class="rate"><input type="number" min="0" data-f="rate" aria-label="ramp rate per hour" placeholder="max"></td>
      <td><div class="hm"><input type="number" min="0" data-f="hh" value="${Math.floor(hm / 60)}" aria-label="hold hours">:<input type="number" min="0" max="59" data-f="hm" value="${hm % 60}" aria-label="hold minutes"></div></td>
      <td class="del"><button title="Remove step" aria-label="Remove step ${i + 1}">×</button></td>`;
    tr.querySelector('[data-f="target"]').value = Math.round(toU(s.target));
    tr.querySelectorAll("input").forEach((inp) => inp.addEventListener("input", () => onStepInput(i, inp.dataset.f, tr)));
    tr.querySelector(".del button").onclick = () => {
      if (S.editing.steps.length === 1) return toast("A profile needs at least one step");
      S.editing.steps.splice(i, 1);
      renderSteps();
    };
    tb.appendChild(tr);
    updateRate(i, tr);
  });
  $("step-count").textContent = `${S.editing.steps.length} / ${MAX_STEPS}`;
  $("btn-add-step").disabled = S.editing.steps.length >= MAX_STEPS;
  updateTotals();
}

function rowVal(tr, f) { const v = parseFloat(tr.querySelector(`[data-f="${f}"]`).value); return isNaN(v) ? 0 : v; }

function onStepInput(i, field, tr) {
  const s = S.editing.steps[i];
  if (field === "target") s.target = fromU(rowVal(tr, "target"));
  if (field === "rh" || field === "rm") s.minutes = rowVal(tr, "rh") * 60 + rowVal(tr, "rm");
  if (field === "hh" || field === "hm") s.hold = rowVal(tr, "hh") * 60 + rowVal(tr, "hm");
  if (field === "rate") {
    // Typing a rate fills in the ramp time.
    const rate = dFromU(rowVal(tr, "rate"));
    s.minutes = rate > 0 ? Math.round(Math.abs(s.target - stepStart(i)) / rate * 60) : 0;
    tr.querySelector('[data-f="rh"]').value = Math.floor(s.minutes / 60);
    tr.querySelector('[data-f="rm"]').value = s.minutes % 60;
  } else {
    updateRate(i, tr);
  }
  if (field === "target" && tr.nextElementSibling) updateRate(i + 1, tr.nextElementSibling);
  updateTotals();
}

function updateRate(i, tr) {
  const s = S.editing.steps[i];
  const inp = tr.querySelector('[data-f="rate"]');
  inp.value = s.minutes > 0 ? Math.round(dToU(Math.abs(s.target - stepStart(i)) / (s.minutes / 60))) : "";
  inp.title = i === 0 ? "Estimated from room temperature" : "";
}

function updateTotals() {
  const steps = S.editing.steps;
  $("p-total").textContent = fmtDur(programSeconds(steps)) + (steps.some((s) => !s.minutes) ? " + max-rate steps" : "");
  $("p-peak").textContent = steps.length ? fmtT(Math.max(...steps.map((s) => s.target))) : "—";
  drawProfileChart();
}

function planPoints(steps, start = ROOM_C) {
  // Max-rate steps are drawn at an assumed 300 C/hr so the preview stays readable.
  const pts = [[0, start]];
  let t = 0, temp = start;
  for (const s of steps) {
    t += s.minutes > 0 ? s.minutes * 60 : Math.abs(s.target - temp) / 300 * 3600;
    pts.push([t, s.target]);
    temp = s.target;
    if (s.hold > 0) { t += s.hold * 60; pts.push([t, temp]); }
  }
  return pts;
}

function drawProfileChart() {
  if ($("tab-profiles").hidden || !S.editing) return;
  drawChart($("p-chart"), [{ pts: planPoints(S.editing.steps), color: css("--actual"), width: 2.5 }]);
}

$("btn-add-step").onclick = () => {
  const steps = S.editing.steps;
  if (steps.length >= MAX_STEPS) return;
  const last = steps[steps.length - 1];
  steps.push({ target: last ? last.target : 100, minutes: 60, hold: 0 });
  renderSteps();
  const inputs = $("steps").querySelectorAll('[data-f="target"]');
  inputs[inputs.length - 1].focus();
};

function editorPayload() {
  return {
    name: $("p-name").value.trim(),
    description: $("p-desc").value,
    steps: S.editing.steps.map((s) => ({ target: +(+s.target).toFixed(2), minutes: +s.minutes || 0, hold: +s.hold || 0 })),
  };
}

async function saveProfile(asNew) {
  $("p-error").hidden = true;
  try {
    const body = editorPayload();
    const saved = asNew || !S.editing.id
      ? await api("/api/profiles", { method: "POST", body })
      : await api("/api/profiles/" + S.editing.id, { method: "PUT", body });
    toast("Saved " + saved.name);
    S.editing.id = saved.id;
    await loadProfiles(saved.id);
  } catch (e) {
    $("p-error").textContent = e.message;
    $("p-error").hidden = false;
  }
}
$("btn-save").onclick = () => saveProfile(false);
$("btn-saveas").onclick = () => {
  if (S.editing.id && $("p-name").value.trim() === S.editing.name) $("p-name").value += " (copy)";
  saveProfile(true);
};
$("btn-delete").onclick = async () => {
  if (!S.editing.id || !confirm(`Delete "${S.editing.name}"?`)) return;
  await act(() => api("/api/profiles/" + S.editing.id, { method: "DELETE" }));
  S.editing = null;
  loadProfiles();
};
$("btn-fire").onclick = async () => {
  const body = editorPayload();
  if (!confirm(`Start firing "${body.name || "unsaved profile"}" now?`)) return;
  const ok = await act(() => api("/api/firing/start", { method: "POST", body: { profile: { ...body, name: body.name || "Unsaved profile" } } }));
  if (ok) showTab("dash");
};
$("btn-export").onclick = () => {
  const body = editorPayload();
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([JSON.stringify(body, null, 2)], { type: "application/json" }));
  a.download = (body.name || "profile").replace(/[^\w-]+/g, "_") + ".json";
  a.click();
};
$("p-import").onchange = async (e) => {
  const f = e.target.files[0];
  if (!f) return;
  try {
    const p = JSON.parse(await f.text());
    if (!Array.isArray(p.steps)) throw new Error("no steps in file");
    editProfile({ name: p.name || "Imported", description: p.description || "", steps: p.steps.slice(0, MAX_STEPS) });
    toast("Imported - review and Save");
  } catch (err) { toast("Import failed: " + err.message); }
  e.target.value = "";
};

// -------------------------------------------------------------- history --
async function loadHistory() {
  const runs = await act(() => api("/api/history"));
  if (!runs) return;
  const tb = $("history");
  tb.innerHTML = runs.length ? "" : '<tr><td colspan="6" class="muted">No firings yet</td></tr>';
  for (const r of runs) {
    const tr = document.createElement("tr");
    const res = r.outcome === "complete" ? "complete" : r.outcome === "running" ? "running" : r.outcome;
    tr.innerHTML = `<td>${fmtRunId(r.run_id)}</td><td></td><td class="res-${res}">${res}</td>
      <td>${fmtDur(r.duration_s)}</td><td>${fmtT(r.peak_c)}</td><td>${r.kwh} kWh · ${(S.settings.currency || "$") + r.cost.toFixed(2)}</td>`;
    tr.children[1].textContent = r.profile_name || "—";
    tr.onclick = () => showRun(r.run_id);
    tb.appendChild(tr);
  }
}

function fmtRunId(id) {
  const m = id.match(/^(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})/);
  return m ? `${m[1]}-${m[2]}-${m[3]} ${m[4]}:${m[5]}` : id;
}

async function showRun(id) {
  const r = await act(() => api("/api/history/" + id));
  if (!r) return;
  $("run-detail").hidden = false;
  $("rd-title").textContent = `${(r.profile && r.profile.name) || "Firing"} · ${fmtRunId(id)}`;
  $("rd-msg").textContent = r.message || "";
  $("rd-csv").href = `/api/history/${id}/log.csv`;
  $("rd-delete").onclick = async () => {
    if (!confirm("Delete this firing log?")) return;
    await act(() => api("/api/history/" + id, { method: "DELETE" }));
    $("run-detail").hidden = true;
    loadHistory();
  };
  const plan = r.profile ? planPoints(r.profile.steps, r.start_temp ?? ROOM_C) : [];
  drawChart($("rd-chart"), [
    { pts: plan, color: css("--plan"), dash: [6, 5] },
    { pts: r.points, color: css("--actual"), width: 2.5 },
  ]);
  const snaps = $("rd-snaps");
  snaps.innerHTML = "";
  for (const s of r.snapshots) {
    const a = document.createElement("a");
    a.href = `/api/history/${id}/snapshots/${s}`;
    a.target = "_blank";
    a.innerHTML = `<img loading="lazy" alt="Snapshot at ${fmtDur(+s.slice(0, 7))}" src="${a.href}">`;
    snaps.appendChild(a);
  }
  $("run-detail").scrollIntoView({ behavior: "smooth" });
}

// ------------------------------------------------------------- settings --
// [key, label, type, hint]; type: text|num|temp|delta|bool|select:a,b|pin|password
const SETTINGS = [
  ["General", [
    ["kiln_name", "Kiln name", "text"],
    ["units", "Temperature units", "select:F,C"],
    ["notify_url", "Notification URL", "text", "e.g. https://ntfy.sh/your-secret-topic - alerts on start, finish, errors and when cool"],
  ]],
  ["Passcodes", [
    ["new_password", "Interface passcode (login)", "password", "Needed to open the controller on any device. Use digits only (4 or more) to get a keypad on the touchscreen. Leave blank to keep the current one; enter a single space to remove it."],
    ["kiosk_lock_minutes", "Touchscreen auto-lock after idle (minutes)", "num", "0 = never. Needs an interface passcode. EMERGENCY STOP still works on a locked screen."],
    ["new_control_pin", "Firing lock PIN (4–8 digits)", "pin", "When set, holding, skipping, stopping or changing settings during a firing asks for this PIN. EMERGENCY STOP never does. Leave blank to keep; enter a single space to remove."],
  ]],
  ["Firing control", [
    ["pid_kp", "PID Kp (power per °C error)", "num"],
    ["pid_ki", "PID Ki", "num"],
    ["pid_kd", "PID Kd", "num"],
    ["cycle_seconds", "SSR cycle (seconds)", "num"],
    ["catch_up", "Wait for kiln when it lags behind schedule", "bool"],
    ["catch_up_delta", "Catch-up threshold", "delta"],
    ["tc_offset", "Thermocouple calibration offset", "delta", "Adjust after comparing with witness cones"],
  ]],
  ["Safety limits", [
    ["max_temp", "Absolute max temperature", "temp", "Never exceeded - firing aborts and the contactor opens"],
    ["overshoot_abort", "Abort if above setpoint by", "delta"],
    ["stall_minutes", "Stall detect: minutes at full power", "num"],
    ["stall_min_rise", "…must rise at least", "delta"],
    ["runaway_minutes", "Stuck relay: minutes with heater off", "num"],
    ["runaway_rise", "…yet temperature rose by", "delta"],
    ["max_firing_hours", "Maximum firing length (hours)", "num"],
    ["auto_resume_minutes", "Resume after power loss up to (minutes)", "num", "0 = never resume automatically"],
    ["safe_open_temp", "Notify 'safe to open' below", "temp"],
  ]],
  ["Energy cost", [
    ["element_watts", "Element power (watts)", "num", "Kiln nameplate: volts × amps"],
    ["price_per_kwh", "Electricity price per kWh", "num"],
    ["currency", "Currency symbol", "text"],
  ]],
  ["Camera", [
    ["camera_enabled", "Enable camera", "bool"],
    ["camera_fps", "Frames per second", "num"],
    ["timelapse_minutes", "Time-lapse snapshot every (minutes)", "num", "0 = off"],
  ]],
  ["Hardware (restart required)", [
    ["simulate", "Simulation mode (no hardware)", "bool"],
    ["sim_speed", "Simulation speed multiplier", "num"],
    ["sensor", "Thermocouple amplifier", "select:max31856,max31855"],
    ["thermocouple_type", "Thermocouple type (MAX31856)", "select:K,N,S,R,B,J,E,T"],
    ["mains_hz", "Mains frequency (noise filter)", "select:60,50"],
    ["heater_pin", "SSR GPIO (BCM)", "pin"],
    ["heater_active_high", "SSR active high", "bool"],
    ["contactor_pin", "Safety contactor relay GPIO", "pin"],
    ["contactor_active_high", "Contactor relay active high", "bool"],
    ["estop_pin", "E-stop button GPIO (blank = none)", "pin"],
    ["buzzer_pin", "Alarm buzzer GPIO (blank = none)", "pin"],
    ["http_port", "Web port", "num"],
  ]],
];

function renderSettings() {
  const form = $("settings-form");
  form.innerHTML = "";
  const v = S.settings;
  for (const [title, fields] of SETTINGS) {
    const fs = document.createElement("fieldset");
    fs.innerHTML = `<legend>${title}</legend>`;
    for (const [key, label, type, hint] of fields) {
      const id = "set-" + key;
      const wrap = document.createElement("div");
      let input;
      if (type === "bool") {
        wrap.innerHTML = `<label class="check"><input type="checkbox" id="${id}"> <span></span></label>`;
        wrap.querySelector("span").textContent = label;
        input = wrap.querySelector("input");
        input.checked = !!v[key];
      } else {
        wrap.innerHTML = `<label for="${id}"></label>`;
        wrap.firstChild.textContent = label + (type === "temp" || type === "delta" ? ` (${deg()})` : "");
        if (type.startsWith("select:")) {
          input = document.createElement("select");
          for (const o of type.slice(7).split(",")) input.add(new Option(o, o));
          input.value = String(v[key]);
        } else {
          input = document.createElement("input");
          const secret = type === "password" || type === "pin";
          input.type = secret ? "password" : type === "text" ? "text" : "number";
          if (!secret && type !== "text") input.step = "any";
          if (secret) input.autocomplete = "new-password";
          if (type === "pin") { input.inputMode = "numeric"; input.dataset.osk = "pin"; input.maxLength = 8; }
          const val = type === "temp" ? toU(v[key]) : type === "delta" ? dToU(v[key]) : v[key];
          input.value = val == null ? "" : type === "temp" || type === "delta" ? +(+val).toFixed(2) : val;
          if (type === "password") input.placeholder = v.password_set ? "•••• (set)" : "not set - anyone on the network can open the controller";
          if (type === "pin") input.placeholder = v.control_pin_set ? "•••• (set)" : "not set - running firings are unlocked";
        }
        input.id = id;
        wrap.appendChild(input);
      }
      input.dataset.key = key;
      input.dataset.type = type;
      if (hint) { const h = document.createElement("div"); h.className = "hint"; h.textContent = hint; wrap.appendChild(h); }
      fs.appendChild(wrap);
    }
    form.appendChild(fs);
  }
}

$("btn-save-settings").onclick = async () => {
  const body = {};
  for (const el of $("settings-form").querySelectorAll("[data-key]")) {
    const { key, type } = el.dataset;
    if (type === "bool") body[key] = el.checked;
    else if (type === "password" || type === "pin") { if (el.value) body[key] = el.value.trim(); }
    else if (type === "text") body[key] = el.value;
    else if (type === "pin") body[key] = el.value === "" ? null : parseInt(el.value, 10);
    else if (type.startsWith("select:")) body[key] = /^\d+$/.test(el.value) ? +el.value : el.value;
    else if (type === "temp") body[key] = fromU(parseFloat(el.value));
    else if (type === "delta") body[key] = dFromU(parseFloat(el.value));
    else body[key] = parseFloat(el.value);
  }
  const res = await act(() => api("/api/settings", { method: "PUT", body }));
  if (res) {
    S.settings = res;
    $("settings-msg").textContent = "Saved. Hardware changes apply after a restart.";
    applySettings();
    renderSettings();
  }
};
$("btn-restart").onclick = () => confirm("Restart the controller service?") &&
  act(async () => { await api("/api/system/restart", { method: "POST" }); toast("Restarting…"); });

function applySettings() {
  document.querySelectorAll(".u-deg").forEach((e) => (e.textContent = deg()));
  $("kiln-name").textContent = S.settings.kiln_name || "Kiln";
  $("btn-lock").hidden = !S.settings.password_set;
  fillStartSelect();
  if (S.editing) renderSteps();
  if (S.status) renderStatus(S.status, S.status);
}

// ----------------------------------------------------------------- wifi --
async function loadWifi() {
  try {
    const w = await api("/api/wifi");
    $("wifi-status").textContent = w.connected ? `Connected to ${w.ssid} (signal ${w.signal}%)` : "Not connected to Wi-Fi";
  } catch (e) { $("wifi-status").textContent = e.message; }
}
$("btn-scan").onclick = async () => {
  $("wifi-msg").textContent = "Scanning…";
  const nets = await act(() => api("/api/wifi/scan"));
  $("wifi-msg").textContent = "";
  const ul = $("wifi-list");
  ul.innerHTML = "";
  for (const n of nets || []) {
    const li = document.createElement("li");
    li.innerHTML = `<span></span><span class="tag">${n.signal}% ${n.secure ? "🔒" : ""}</span>`;
    li.firstChild.textContent = n.ssid;
    li.onclick = () => { $("wifi-join").hidden = false; $("wifi-ssid").value = n.ssid; $("wifi-pass").focus(); };
    ul.appendChild(li);
  }
  $("wifi-join").hidden = false;
};
$("btn-join").onclick = async () => {
  const r = await act(() => api("/api/wifi/connect", { method: "POST", body: { ssid: $("wifi-ssid").value, password: $("wifi-pass").value } }));
  if (r) $("wifi-msg").textContent = r.message;
};

// ---------------------------------------------------------------- login --
function showLogin() {
  if (!$("login").hidden) return;
  $("login-pass").value = "";
  $("login-err").hidden = true;
  $("login").hidden = false;
  $("login-pass").focus();
}
async function checkAuth() {
  const a = await fetch("/api/auth").then((r) => r.json()).catch(() => null);
  if (a) {
    // Digits-only passcode: number keypad on phones and the touchscreen.
    $("login-pass").inputMode = a.numeric ? "numeric" : "text";
    if (a.numeric) $("login-pass").dataset.osk = "pin"; else delete $("login-pass").dataset.osk;
  }
  if (a && a.required && !a.authed) { showLogin(); return false; }
  return !!a;
}
async function lockNow() {
  await fetch("/api/logout", { method: "POST" }).catch(() => {});
  await checkAuth();
}
$("btn-lock").onclick = lockNow;
$("login-form").onsubmit = async (e) => {
  e.preventDefault();
  const res = await fetch("/api/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ password: $("login-pass").value }) });
  if (!res.ok) { $("login-err").hidden = false; return; }
  $("login").hidden = true;
  boot();
};

// ----------------------------------------------------------------- boot --
async function boot() {
  if (!(await checkAuth())) return;
  S.settings = await api("/api/settings");
  applySettings();
  await loadProfiles();
  if (!S.ws || S.ws.readyState > 1) connect();
  let tab = "dash";
  try { tab = localStorage.getItem("kiln-tab") || "dash"; } catch {}
  showTab(tab);
}
boot();
