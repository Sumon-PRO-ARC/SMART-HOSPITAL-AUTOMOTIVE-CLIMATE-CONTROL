"use strict";
/* Hospital Climate Control dashboard. Plain JavaScript; talks to the JSON API in
   hospital_climate/web.py. Text from the server is always inserted as text, never as HTML. */

// ---- helpers ------------------------------------------------------------------

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") node.className = v;
    else if (k === "text") node.textContent = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat()) {
    if (c === null || c === undefined || c === false) continue;
    node.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return node;
}

const SVG_NS = "http://www.w3.org/2000/svg";
function svg(tag, attrs = {}, ...children) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "text") node.textContent = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v);
  }
  children.flat().forEach((c) => c && node.append(c));
  return node;
}

/* Two ways to reach the simulation, with the same API:
   - "server": python -m hospital_climate is running and answers /api/... over HTTP;
   - "browser": a static host such as GitHub Pages, where js/py-worker.js runs the
     same Python code in the browser with Pyodide. */
let backend = "server";
let worker = null;
let nextCall = 1;
const pending = new Map();

async function detectBackend() {
  try {
    const res = await fetch("/api/health", { cache: "no-store" });
    if (res.ok && (res.headers.get("Content-Type") || "").includes("json")) return "server";
  } catch (e) { /* no server: fall through */ }
  return "browser";
}

function startWorker() {
  return new Promise((resolve, reject) => {
    worker = new Worker("js/py-worker.js");
    worker.onmessage = (event) => {
      const m = event.data;
      if (m.type === "ready") return resolve();
      if (m.type === "failed") return reject(new Error(m.message));
      const p = pending.get(m.id);
      if (p) { pending.delete(m.id); p(m); }
    };
    worker.onerror = (e) => reject(new Error(e.message || "The simulation could not start."));
  });
}

function callWorker(path, body) {
  const [route, qs] = path.split("?");
  const query = Object.fromEntries(new URLSearchParams(qs || ""));
  const id = nextCall++;
  return new Promise((resolve) => {
    pending.set(id, resolve);
    worker.postMessage({ id, method: body === undefined ? "GET" : "POST", path: route, query, body });
  });
}

async function api(path, body) {
  if (backend === "browser") {
    const m = await callWorker(path, body);
    if (m.status !== 200) throw new Error((m.data && m.data.error) || "Request failed (" + m.status + ").");
    return m.data;
  }
  const opts = body === undefined ? {} : {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  };
  let res;
  try {
    res = await fetch(path, opts);
  } catch (e) {
    throw new Error("The server is not answering. Is python -m hospital_climate still running?");
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || "Request failed (" + res.status + ").");
  return data;
}

let toastTimer = null;
function toast(message, isError = false) {
  const t = $("#toast");
  t.textContent = message;
  t.classList.toggle("err", isError);
  t.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove("show"), isError ? 6000 : 3500);
}

/* Runs an action: locks the button while waiting, shows the server's message, refreshes. */
async function act(path, body, button) {
  if (button) button.disabled = true;
  try {
    const out = await api(path, body);
    if (out.message) toast(out.message);
    await refreshAll();
    return out;
  } catch (e) {
    toast(e.message, true);
    return null;
  } finally {
    if (button) button.disabled = false;
  }
}

function formData(form) {
  const out = {};
  new FormData(form).forEach((v, k) => { out[k] = typeof v === "string" ? v.trim() : v; });
  return out;
}

const fmt = (v, d = 1) => (v === null || v === undefined ? "–" : Number(v).toFixed(d));

// ---- state -----------------------------------------------------------------------

let state = null;
let metric = "temp";
let currentTab = "building";
let openRoom = null;

const TYPE_LABELS = {
  ICU: "Intensive care", NICU: "Neonatal ICU", OT: "Operating theatre",
  ISO: "Isolation", WARD: "General ward", WAIT: "Waiting area",
};

// ---- building: floor plan --------------------------------------------------------

/* Colour class for a room: how far its reading sits outside the safe range. */
function tileClass(room) {
  if (metric === "type") return "t-" + room.type;
  let value, lo, hi, unit;
  if (metric === "temp") { value = room.temp; [lo, hi] = room.safe.temp; unit = 1; }
  else if (metric === "humidity") { value = room.humidity; [lo, hi] = room.safe.humidity; unit = 5; }
  else { value = room.co2; lo = 0; hi = room.safe.co2; unit = 200; }
  if (value === null) return "";
  if (value > hi) {
    const d = (value - hi) / unit;
    return d > 3 ? "c-hot" : d > 1 ? "c-warm-2" : "c-warm-1";
  }
  if (value < lo) return (lo - value) / unit > 1 ? "c-cold-2" : "c-cold-1";
  return "c-ok";
}

function tileValue(room) {
  if (metric === "temp") return room.temp === null ? "–" : fmt(room.temp);
  if (metric === "humidity") return room.humidity === null ? "–" : room.humidity + "%";
  if (metric === "co2") return room.co2 === null ? "–" : String(room.co2);
  return room.type;
}

function tileLabel(room) {
  const parts = ["Room " + room.id, TYPE_LABELS[room.type] || room.type];
  if (room.temp !== null) parts.push(fmt(room.temp) + " °C, " + room.humidity + " % humidity, " + room.co2 + " ppm CO2");
  if (room.alert !== null) parts.push("alert, priority " + room.alert);
  if (!room.supply) parts.push("no air supply");
  return parts.join(", ");
}

let planKey = "";
function renderPlan() {
  const plan = $("#plan");
  const key = state.rooms.map((r) => r.id).join(",");
  if (key !== planKey) { // build the skeleton once; later polls only update it
    planKey = key;
    plan.replaceChildren();
    const floors = [...state.floors].sort((a, b) => b.floor - a.floor);
    for (const f of floors) {
      const wings = ["A", "B"].map((w) => {
        const rooms = state.rooms.filter((r) => r.floor === f.floor && r.wing === w);
        const first = rooms[0] ? rooms[0].id : "";
        const last = rooms.length ? rooms[rooms.length - 1].id : "";
        return el("div", { class: "wing" },
          el("p", { class: "wing-label", text: "Wing " + w + " · rooms " + first + "–" + last }),
          el("div", { class: "rooms" }, rooms.map((r) =>
            el("button", { type: "button", class: "tile", "data-room": r.id, onclick: () => openPanel(r.id) },
              el("span", { class: "num", text: r.id }), el("span", { class: "val" })))));
      });
      plan.append(el("div", { class: "floor", "data-floor": f.floor },
        el("div", { class: "floor-id" },
          el("p", { class: "floor-no", "aria-label": "Floor " + f.floor, text: String(f.floor) }),
          el("p", { class: "floor-stat" }, el("b", { class: "favg" }), el("span", { class: "fmax" })),
          el("button", { type: "button", class: "ahu", "data-ahu": f.ahu, onclick: () => location.hash = "#network" },
            f.ahu, el("small", { class: "ahu-status" }))),
        wings));
    }
  }
  const unsupplied = new Set(state.unsupplied);
  for (const room of state.rooms) {
    const tile = plan.querySelector('[data-room="' + room.id + '"]');
    const cls = tileClass(room);
    const dark = ["c-hot", "c-cold-2", "t-ICU", "t-OT", "t-ISO"].includes(cls);
    tile.className = "tile " + cls + (dark ? " dark" : "") + (room.alert !== null ? " alert" : "") +
      (unsupplied.has(room.id) ? " unsupplied" : "");
    tile.querySelector(".val").textContent = tileValue(room);
    tile.setAttribute("aria-label", tileLabel(room));
  }
  for (const f of state.floors) {
    const row = plan.querySelector('[data-floor="' + f.floor + '"]');
    const ahu = row.querySelector(".ahu");
    ahu.classList.toggle("failed", f.ahu_failed);
    ahu.querySelector(".ahu-status").textContent = f.ahu_failed ? "failed" : "running";
    row.querySelector(".favg").textContent = f.avg === null ? "–" : fmt(f.avg) + " °C";
    row.querySelector(".fmax").textContent = f.max === null ? "average" : "avg, max " + fmt(f.max);
  }
  renderLegend();
}

function renderLegend() {
  const legend = $("#legend");
  const items = [];
  if (metric === "type") {
    for (const t of state.types) items.push([("t-" + t.code), t.label]);
  } else {
    const unit = metric === "temp" ? "1 °C" : metric === "humidity" ? "5 %" : "200 ppm";
    if (metric !== "co2") {
      items.push(["c-cold-2", "Well below range"], ["c-cold-1", "Below range"]);
    }
    items.push(["c-ok", "In safe range"], ["c-warm-1", "Up to " + unit + " over"],
      ["c-warm-2", "Further over"], ["c-hot", "More than 3 × " + unit + " over"]);
  }
  items.push(["ring", "Open alert"], ["hatch", "No air supply"]);
  legend.replaceChildren(...items.map(([c, t]) => el("span", {}, el("i", { class: c }), t)));
}

// ---- building: alerts -------------------------------------------------------------

function renderAlerts() {
  const count = $("#alert-count");
  count.textContent = state.alert_count;
  count.classList.toggle("zero", state.alert_count === 0);
  const list = $("#alert-list");
  const focused = document.activeElement && document.activeElement.dataset ? document.activeElement.dataset.alertRoom : null;
  if (!state.alerts.length) {
    list.replaceChildren(el("li", { class: "empty", text: "No open alerts. Every room is inside its safe range." }));
  } else {
    list.replaceChildren(...state.alerts.map((a, i) => el("li", {},
      el("button", { type: "button", "data-alert-room": a.room, onclick: () => openPanel(a.room) },
        el("span", { class: "pos", text: String(i + 1) }),
        el("span", {}, el("span", { class: "room", text: "Room " + a.room + " · " + (TYPE_LABELS[a.type] || a.type) }),
          el("span", { class: "why", text: a.reasons.join("; ") })),
        el("span", { class: "prio" }, String(a.priority), el("small", { text: "since " + a.since.slice(3) }))))));
    if (state.alert_count > state.alerts.length) {
      list.append(el("li", { class: "empty", text: (state.alert_count - state.alerts.length) + " more, lower priority." }));
    }
  }
  if (focused) {
    const again = list.querySelector('[data-alert-room="' + focused + '"]');
    if (again) again.focus();
  }
  $("#serve").disabled = state.alert_count === 0;
  $("#stat-strip").replaceChildren(
    el("span", { text: state.processed.toLocaleString() + " sensor readings processed" + (state.dropped ? ", " + state.dropped + " dropped" : "") }),
    el("span", { text: state.unsupplied.length ? state.unsupplied.length + " rooms without air supply" : "Every room has air supply" }));
}

// ---- masthead ---------------------------------------------------------------------

function renderMasthead() {
  const [day, time] = state.clock.slice(1).split(" ");
  $("#clock").textContent = time;
  $("#clock").setAttribute("aria-label", "Simulated time: day " + day + ", " + time);
  $("#outside").textContent = "Day " + day + " · outside " + fmt(state.outside.temp) + " °C, " + state.outside.humidity + " % humidity";
  $("#label").textContent = state.label.charAt(0).toUpperCase() + state.label.slice(1) +
    (backend === "browser" ? " · running in your browser" : "");
  const run = $("#run");
  run.textContent = state.running ? "Pause clock" : "Start clock";
  run.setAttribute("aria-pressed", state.running ? "true" : "false");
  const speed = $("#speed");
  if (!speed.options.length) {
    for (const s of state.speeds) speed.append(el("option", { value: s, text: s === 60 ? "1 hour / s" : s + " min / s" }));
  }
  if (document.activeElement !== speed) speed.value = String(state.speed);
  const wf = $("#weather-form");
  if (!wf.contains(document.activeElement)) {
    wf.temp.value = state.outside.temp;
    wf.humidity.value = state.outside.humidity;
  }
}

// ---- room panel -----------------------------------------------------------------

let panelReturnFocus = null;

async function openPanel(roomId) {
  if (!openRoom) panelReturnFocus = document.activeElement;
  if (openRoom !== roomId) {
    $("#panel-title").textContent = "Room " + roomId;
    $("#panel-body").replaceChildren(el("p", { class: "hint", text: "Loading the room…" }));
  }
  openRoom = roomId;
  $("#panel").hidden = false;
  $("#scrim").hidden = false;
  await renderPanel(true);
  $("#panel-close").focus();
}

function closePanel() {
  openRoom = null;
  $("#panel").hidden = true;
  $("#scrim").hidden = true;
  if (panelReturnFocus && document.contains(panelReturnFocus)) panelReturnFocus.focus();
}

function sparkline(values, lo, hi) {
  const w = 400, h = 72;
  if (!values.length) return el("p", { class: "hint", text: "No readings yet." });
  const min = Math.min(lo - 0.5, ...values), max = Math.max(hi + 0.5, ...values);
  const y = (v) => h - 4 - ((v - min) / (max - min)) * (h - 8);
  const x = (i) => (values.length === 1 ? w / 2 : 4 + (i / (values.length - 1)) * (w - 8));
  return svg("svg", { class: "spark", viewBox: "0 0 " + w + " " + h, preserveAspectRatio: "none", role: "img",
    "aria-label": "Last " + values.length + " temperature readings, safe band shaded" },
    svg("rect", { class: "band", x: 0, y: y(hi), width: w, height: Math.max(0, y(lo) - y(hi)) }),
    svg("polyline", { class: "line", points: values.map((v, i) => x(i).toFixed(1) + "," + y(v).toFixed(1)).join(" ") }));
}

async function renderPanel(force = false) {
  if (!openRoom) return;
  const body = $("#panel-body");
  if (!force && body.contains(document.activeElement) && document.activeElement.matches("input, select")) return;
  let r;
  try {
    r = await api("/api/room?id=" + encodeURIComponent(openRoom));
  } catch (e) {
    body.replaceChildren(el("p", { class: "result err", text: e.message }));
    return;
  }
  $("#panel-title").textContent = "Room " + r.id + " · " + r.type_label;
  const [tlo, thi] = r.safe.temp;
  const parts = [];

  if (r.alert) {
    parts.push(el("p", { class: "callout" }, el("b", { text: "Alert, priority " + r.alert.priority + ". " }), r.alert.reasons.join("; ") + "."));
  }
  parts.push(el("section", {},
    el("div", { class: "big-reading" },
      el("div", {}, el("b", { text: r.latest ? fmt(r.latest.temp) + " °C" : "–" }), el("span", { text: "safe " + tlo + "–" + thi + " °C" })),
      el("div", {}, el("b", { text: r.latest ? fmt(r.latest.humidity, 0) + " %" : "–" }), el("span", { text: "humidity, safe " + r.safe.humidity.join("–") })),
      el("div", {}, el("b", { text: r.latest ? String(r.latest.co2) : "–" }), el("span", { text: "CO₂ ppm, max " + r.safe.co2 }))),
    sparkline(r.window, tlo, thi),
    r.rolling ? el("p", { class: "hint", text: "Last " + r.rolling.n + " readings: average " + fmt(r.rolling.avg, 2) +
      ", lowest " + fmt(r.rolling.min, 2) + ", highest " + fmt(r.rolling.max, 2) + ", change " +
      (r.rolling.change >= 0 ? "+" : "") + fmt(r.rolling.change, 2) + " °C." }) : null));

  const zoneSize = r.zone.length;
  const sp = el("form", { class: "row" },
    el("label", {}, "Setpoint °C", el("input", { name: "value", type: "number", step: "0.5", min: tlo, max: thi, value: r.setpoint, required: true })),
    zoneSize > 1 ? el("label", { class: "check" }, el("span", { text: "Whole zone (" + zoneSize + " rooms)" }),
      el("select", { name: "zone" }, el("option", { value: "", text: "This room only" }), el("option", { value: "1", text: "Every room in the zone" }))) : null,
    el("button", { class: "btn", type: "submit", text: "Set setpoint" }));
  sp.addEventListener("submit", (e) => {
    e.preventDefault();
    const d = formData(sp);
    act("/api/setpoint", { room: r.id, value: Number(d.value), zone: d.zone === "1" }, sp.querySelector("button")).then(() => renderPanel(true));
  });
  const vent = el("form", { class: "row" },
    el("label", {}, "Ventilation 1–5", el("input", { name: "level", type: "number", min: 1, max: 5, value: r.ventilation, required: true })),
    el("button", { class: "btn", type: "submit", text: "Set ventilation" }));
  vent.addEventListener("submit", (e) => {
    e.preventDefault();
    act("/api/ventilation", { room: r.id, level: Number(formData(vent).level) }, vent.querySelector("button")).then(() => renderPanel(true));
  });
  const heat = el("form", { class: "row" },
    el("label", {}, "Equipment heat °C per minute", el("input", { name: "value", type: "number", step: "0.1", min: 0, max: 2, value: r.extra_heat, required: true })),
    el("button", { class: "btn btn-quiet", type: "submit", text: "Apply heat" }));
  heat.addEventListener("submit", (e) => {
    e.preventDefault();
    act("/api/heat", { room: r.id, value: Number(formData(heat).value) }, heat.querySelector("button")).then(() => renderPanel(true));
  });
  parts.push(el("section", {}, el("h3", { text: "Control" }), sp, vent,
    el("p", { class: "hint", text: "Simulate a fault: extra heat from equipment in this room." }), heat));

  parts.push(el("section", {}, el("h3", { text: "Air supply" }),
    r.supply
      ? el("p", {}, "From " + r.supply + ": " + r.route.join(" → ") + " ", el("span", { class: "hint", text: "(duct resistance " + fmt(r.route_cost) + ")" }))
      : el("p", { class: "bad", text: "No working air unit can reach this room." }),
    el("dl", { class: "facts" },
      el("dt", { text: "Floor" }), el("dd", { text: r.floor + ", wing " + r.wing }),
      el("dt", { text: "Zone" }), el("dd", { text: zoneSize > 1 ? zoneSize + " rooms: " + r.zone.join(", ") : "Own zone" }))));

  parts.push(el("section", {}, el("h3", { text: "Patients" }),
    r.patients.length
      ? el("ul", { class: "plain" }, r.patients.map((p) => el("li", {},
          el("b", { text: p.name }), " · ID " + p.id + " · prefers " + fmt(p.temp) + " °C, " + p.humidity + " % humidity, lighting " + p.lighting + "/5, under " + p.noise + " dB")))
      : el("p", { class: "hint", text: "No patients. The setpoint is the room type's default." })));

  body.replaceChildren(...parts);
}

// ---- patients -------------------------------------------------------------------

function renderPatients(list, caption) {
  $("#patient-caption").textContent = caption;
  const tbody = $("#patient-table tbody");
  if (!list.length) {
    tbody.replaceChildren(el("tr", {}, el("td", { colspan: 5, class: "hint", text: "No patients found." })));
    return;
  }
  tbody.replaceChildren(...list.map((p) => el("tr", {},
    el("td", { text: String(p.id) }),
    el("td", { text: p.name }),
    el("td", {}, el("button", { type: "button", class: "linkish", text: p.room, onclick: () => openPanel(p.room) })),
    el("td", { text: fmt(p.temp) + " °C, " + p.humidity + " %" }),
    el("td", {}, el("button", { type: "button", class: "btn btn-quiet", text: "Discharge",
      onclick: (e) => act("/api/patients/discharge", { id: p.id }, e.currentTarget).then(loadPatients) })))));
}

async function loadPatients() {
  const q = $("#search-form").q.value.trim();
  try {
    if (q) {
      renderPatients(await api("/api/patients/search?q=" + encodeURIComponent(q)), "Names starting with " + q);
    } else {
      const f = $("#idrange-form");
      const lo = f.lo.value || 0, hi = f.hi.value || 999999999;
      renderPatients(await api("/api/patients?lo=" + encodeURIComponent(lo) + "&hi=" + encodeURIComponent(hi)), "Patients with IDs " + lo + " to " + hi);
    }
  } catch (e) {
    toast(e.message, true);
  }
}

// ---- air network ------------------------------------------------------------------

const ROW = 120, TOP = 52;
function nodePos(id, floors) {
  const m = /^AHU-F(\d+)$/.exec(id) || /^C(\d+)([AB])$/.exec(id);
  const f = Number(m[1]);
  const y = TOP + (floors - f) * ROW;
  if (id.startsWith("AHU")) return { x: 50, y };
  return { x: m[2] === "A" ? 170 : 430, y };
}

function ductPath(d, floors) {
  const a = nodePos(d.a, floors), b = nodePos(d.b, floors);
  const ahu = d.a.startsWith("AHU") ? d.a : d.b.startsWith("AHU") ? d.b : null;
  if (ahu) {
    const c = ahu === d.a ? b : a;
    if (c.x === 170) return "M68 " + c.y + " H135";
    return "M50 " + (c.y - 18) + " V" + (c.y - 34) + " H430 V" + (c.y - 14);
  }
  if (a.y === b.y) return "M190 " + (a.y + 14) + " V" + (a.y + 40) + " H410 V" + (a.y + 14);
  const x = a.x === 170 ? 150 : 450;
  const top = Math.min(a.y, b.y), bottom = Math.max(a.y, b.y);
  return "M" + x + " " + (top + 14) + " V" + (bottom - 14);
}

function activate(handler) {
  return (e) => {
    if (e.type === "click" || e.key === "Enter" || e.key === " ") { e.preventDefault(); handler(); }
  };
}

async function loadNetwork() {
  let net;
  try { net = await api("/api/network"); } catch (e) { toast(e.message, true); return; }
  const floors = Math.max(...net.nodes.filter((n) => n.kind === "ahu").map((n) => Number(n.id.slice(5))));
  const unsupplied = new Set(net.unsupplied);
  const roomsByWing = {};
  for (const r of state.rooms) (roomsByWing[r.floor + r.wing] ||= []).push(r.id);

  const g = svg("svg", { viewBox: "0 0 620 " + (TOP + floors * ROW - 40), role: "group", "aria-label": "Duct diagram, top floor first" });
  for (const d of net.ducts) {
    const label = "Duct " + d.a + " to " + d.b + (d.failed ? ", failed. Press to repair." : ", working. Press to break.");
    const toggle = () => act(d.failed ? "/api/repair" : "/api/fail", { a: d.a, b: d.b }).then(loadNetwork);
    const p = ductPath(d, floors);
    g.append(svg("g", { tabindex: 0, role: "button", "aria-label": label, onclick: activate(toggle), onkeydown: activate(toggle) },
      svg("title", { text: label }),
      svg("path", { class: "duct-hit", d: p, fill: "none" }),
      svg("path", { class: "duct" + (d.failed ? " failed" : ""), d: p, fill: "none" })));
  }
  for (let f = floors; f >= 1; f--) {
    for (const w of ["A", "B"]) {
      const c = nodePos("C" + f + w, floors);
      const ids = roomsByWing[f + w] || [];
      const dead = ids.filter((id) => unsupplied.has(id)).length;
      const x = w === "A" ? 215 : 475;
      g.append(svg("rect", { class: "rw" + (dead ? " unsupplied" : ""), x, y: c.y - 14, width: 120, height: 28, rx: 3 }),
        svg("text", { x: x + 8, y: c.y + 5, text: (ids[0] || "") + "–" + (ids[ids.length - 1] || "") + (dead ? "  no air" : "") }));
    }
  }
  for (const n of net.nodes) {
    const pos = nodePos(n.id, floors);
    if (n.kind === "ahu") {
      const label = n.id + (n.failed ? ", failed. Press to repair." : ", running. Press to break.");
      const toggle = () => act(n.failed ? "/api/repair" : "/api/fail", { a: n.id }).then(loadNetwork);
      g.append(svg("g", { class: "node ahu" + (n.failed ? " failed" : ""), tabindex: 0, role: "button", "aria-label": label,
        onclick: activate(toggle), onkeydown: activate(toggle) },
        svg("title", { text: label }),
        svg("circle", { cx: pos.x, cy: pos.y, r: 18 }),
        svg("text", { x: pos.x, y: pos.y + 5, "text-anchor": "middle", text: "F" + n.id.slice(5) })));
    } else {
      g.append(svg("g", { class: "node" },
        svg("rect", { x: pos.x - 35, y: pos.y - 14, width: 70, height: 28, rx: 3 }),
        svg("text", { x: pos.x, y: pos.y + 5, "text-anchor": "middle", text: n.id })));
    }
  }
  $("#diagram").replaceChildren(g, el("p", { class: "hint", text: "Circles are air units (F = floor), boxes are corridors, shaded boxes are the rooms they feed. Dashed red = broken." }));

  $("#parts").replaceChildren(...net.parts.filter((p) => p.rooms.length).map((p) => el("li", {},
    el("b", { text: p.units.length ? "Fed by " + p.units.join(", ") : "No air unit" }),
    " · " + p.rooms.length + " rooms",
    p.units.length ? null : el("span", { class: "bad", text: " (no air supply)" }))));

  const from = $("#route-from");
  const keep = from.value;
  from.replaceChildren(...net.nodes.filter((n) => n.kind === "ahu").map((n) => el("option", { value: n.id, text: n.id + (n.failed ? " (failed)" : "") })));
  if (keep) from.value = keep;
}

// ---- zones, maintenance, log ---------------------------------------------------------

async function loadZones() {
  let z;
  try { z = await api("/api/zones"); } catch (e) { toast(e.message, true); return; }
  if (!$("#zone-types").children.length) {
    $("#zone-types").replaceChildren(...state.types.map((t) => el("button", { type: "button", class: "btn btn-quiet", text: t.label,
      onclick: (e) => act("/api/zones/type", { type: t.code }, e.currentTarget).then(loadZones) })));
  }
  $("#zone-heading").textContent = z.groups.length ? z.groups.length + " shared zones" : "No shared zones";
  $("#zone-list").replaceChildren(...(z.groups.length ? z.groups.map((g) => el("li", {},
    el("b", { text: g.rooms.length + " rooms" }), el("span", { class: "rooms-line", text: g.rooms.join(", ") })))
    : [el("li", { class: "hint", text: "Every room is in its own zone. Group rooms of a type, or join two rooms." })]));
}

async function loadTasks() {
  let tasks;
  try { tasks = await api("/api/tasks"); } catch (e) { toast(e.message, true); return; }
  $("#task-list").replaceChildren(...(tasks.length ? tasks.map((t) => el("li", {},
    el("span", { class: "due" + (t.overdue ? " overdue" : ""), text: t.due.slice(3) + (t.overdue ? " late" : "") }),
    el("span", { class: "prio-pill p" + t.priority, text: "P" + t.priority }),
    el("span", {}, t.title, t.room ? el("span", { class: "hint", text: " · room " + t.room }) : null),
    el("button", { type: "button", class: "btn btn-quiet", text: "Mark done",
      onclick: (e) => act("/api/tasks/done", { id: t.id }, e.currentTarget).then(loadTasks) })))
    : [el("li", { class: "hint", text: "No open tasks. Breaking an air unit or duct adds a repair task." })]));
}

async function loadLog() {
  let log;
  try { log = await api("/api/history?n=100"); } catch (e) { toast(e.message, true); return; }
  $("#log-list").replaceChildren(...log.map((e) => el("li", {},
    el("span", { class: "when", text: e.time.slice(3) }), el("span", { class: "who", text: e.actor }), el("span", { text: e.text }))));
  $("#undo").disabled = state.undo_depth === 0;
  $("#undo-next").textContent = state.undo_next ? "Undo will revert: " + state.undo_next + "." : "Nothing to undo. Setpoint and ventilation changes can be undone.";
}

// ---- scenarios and benchmarks ------------------------------------------------------

const SCENARIO_TITLES = {
  normal: "Normal day", heatwave: "Heatwave", hvac_failure: "Air unit failure", icu_flood: "ICU alert flood",
};

async function loadScenarios() {
  const list = $("#scenario-list");
  if (!list.children.length) {
    const scenarios = await api("/api/scenarios");
    list.replaceChildren(...scenarios.map((s) => el("article", { class: "scenario" },
      el("h2", { text: SCENARIO_TITLES[s.name] || s.name }),
      el("p", { class: "hint", text: s.doc.split("\n")[0] }),
      el("button", { type: "button", class: "btn", text: "Run scenario", "aria-label": "Run " + (SCENARIO_TITLES[s.name] || s.name),
        onclick: async (e) => {
          const button = e.currentTarget;
          button.textContent = "Running…";
          const out = await act("/api/scenario", { name: s.name }, button);
          button.textContent = "Run scenario";
          if (out) showReport(SCENARIO_TITLES[s.name], out.report);
        } }))));
  }
  const last = await api("/api/report");
  if (last) showReport(SCENARIO_TITLES[last.name] || last.name, last.text);
}

function showReport(title, text) {
  $("#report-title").hidden = false;
  $("#report-title").textContent = "Report: " + title;
  $("#report").hidden = false;
  $("#report").textContent = text;
}

const BENCHMARKS = [
  ["lookup", "Room lookup"], ["alerts", "Serving the most urgent alert"], ["patients", "Patient ID ranges"],
  ["prefix", "Name prefix search"], ["window", "Rolling statistics"], ["segment", "Range averages"],
  ["dijkstra", "Duct routing"], ["zones", "Zone merging"], ["sorting", "Sorting tasks"], ["quicksort", "Quick vs merge sort"],
];
function loadBenchmarks() {
  const grid = $("#bench-grid");
  if (grid.children.length) return;
  grid.replaceChildren(...BENCHMARKS.map(([name, title]) => el("figure", {},
    el("img", { src: "benchmarks/" + name + ".svg", alt: title + " benchmark chart", loading: "lazy" }))));
}

// ---- tabs and refresh ----------------------------------------------------------------

const LOADERS = {
  patients: loadPatients, network: loadNetwork, zones: loadZones, maintenance: loadTasks,
  log: loadLog, scenarios: loadScenarios, benchmarks: loadBenchmarks,
};

function showTab() {
  const name = (location.hash || "#building").slice(1);
  currentTab = $("#tab-" + name) ? name : "building";
  for (const s of $$(".tab")) s.hidden = s.id !== "tab-" + currentTab;
  for (const a of $$(".tabs a")) {
    if (a.dataset.tab === currentTab) a.setAttribute("aria-current", "page");
    else a.removeAttribute("aria-current");
  }
  if (state && LOADERS[currentTab]) LOADERS[currentTab]();
}

let inFlight = null;
/* The once-a-second poll updates the masthead, plan, alerts and open room panel.
   Lists on other tabs reload only after an action (withTab), so keyboard focus
   in them is not lost every second. An action waits for a poll in progress and
   then refreshes again, so it always sees its own change. */
async function refreshAll(withTab = true) {
  if (inFlight) {
    if (!withTab) return inFlight;
    await inFlight.catch(() => {});
  }
  inFlight = doRefresh(withTab);
  try { await inFlight; } finally { inFlight = null; }
}

async function doRefresh(withTab) {
  try {
    state = await api("/api/state");
    renderMasthead();
    renderPlan();
    renderAlerts();
    if (openRoom) await renderPanel();
    if (withTab && currentTab === "log") await loadLog();
    if (withTab && currentTab === "maintenance") await loadTasks();
    if (withTab && currentTab === "network") await loadNetwork();
  } catch (e) {
    $("#clock").textContent = "Offline";
    $("#outside").textContent = e.message;
  }
}

// ---- wiring -------------------------------------------------------------------------

function wire() {
  window.addEventListener("hashchange", showTab);
  $("#run").addEventListener("click", (e) => act("/api/clock", { running: !state.running, speed: state.speed }, e.currentTarget));
  $("#speed").addEventListener("change", (e) => act("/api/clock", { running: state.running, speed: Number(e.target.value) }));
  for (const b of $$("[data-tick]")) b.addEventListener("click", (e) => act("/api/tick", { minutes: Number(b.dataset.tick) }, e.currentTarget));

  for (const b of $$("[data-metric]")) {
    b.addEventListener("click", () => {
      metric = b.dataset.metric;
      for (const o of $$("[data-metric]")) o.setAttribute("aria-checked", o === b ? "true" : "false");
      renderPlan();
    });
  }
  $("#serve").addEventListener("click", (e) => act("/api/serve", { n: 1 }, e.currentTarget));

  $("#range-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const d = formData(e.target);
    const out = $("#range-result");
    try {
      const r = await api("/api/range?first=" + encodeURIComponent(d.first) + "&last=" + encodeURIComponent(d.last) + "&metric=" + d.metric);
      const unit = d.metric === "temperature" ? " °C" : d.metric === "humidity" ? " %" : " ppm";
      out.classList.remove("err");
      out.textContent = r.count ? "Average " + fmt(r.avg) + unit + ", lowest " + fmt(r.min) + ", highest " + fmt(r.max) + " over " + r.count + " rooms." : "No readings in that range yet.";
    } catch (err) {
      out.classList.add("err");
      out.textContent = err.message;
    }
  });
  $("#weather-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const d = formData(e.target);
    act("/api/weather", { temp: Number(d.temp), humidity: Number(d.humidity) }, e.submitter);
  });

  let searchTimer = null;
  $("#search-form").addEventListener("submit", (e) => { e.preventDefault(); loadPatients(); });
  $("#search-form").q.addEventListener("input", () => { clearTimeout(searchTimer); searchTimer = setTimeout(loadPatients, 150); });
  $("#idrange-form").addEventListener("submit", (e) => { e.preventDefault(); $("#search-form").q.value = ""; loadPatients(); });
  $("#admit-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const d = formData(e.target);
    const out = await act("/api/patients/add", { id: Number(d.id), name: d.name, room: d.room, temp: Number(d.temp),
      humidity: Number(d.humidity), lighting: Number(d.lighting), noise: Number(d.noise) }, e.submitter);
    if (out) { e.target.reset(); loadPatients(); }
  });

  $("#route-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const d = formData(e.target);
    const out = $("#route-result");
    try {
      const r = await api("/api/route?from=" + encodeURIComponent(d.from) + "&to=" + encodeURIComponent(d.to));
      out.classList.toggle("err", !r.path.length);
      out.textContent = r.path.length ? r.path.join(" → ") + " (resistance " + fmt(r.cost) + ")" : "No working route from " + d.from + " to room " + d.to + ".";
    } catch (err) { out.classList.add("err"); out.textContent = err.message; }
  });
  $("#spread-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const d = formData(e.target);
    const out = $("#spread-result");
    try {
      const r = await api("/api/spread?room=" + encodeURIComponent(d.room) + "&hops=" + encodeURIComponent(d.hops));
      out.classList.remove("err");
      out.textContent = r.length + " rooms: " + r.map((x) => x.room).join(", ");
    } catch (err) { out.classList.add("err"); out.textContent = err.message; }
  });

  $("#merge-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const d = formData(e.target);
    act("/api/zones/merge", { a: d.a, b: d.b }, e.submitter).then(loadZones);
  });
  $("#zones-reset").addEventListener("click", (e) => act("/api/zones/reset", {}, e.currentTarget).then(loadZones));

  $("#task-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const d = formData(e.target);
    const out = await act("/api/tasks/add", { title: d.title, room: d.room, in_minutes: Number(d.in_minutes), priority: Number(d.priority) }, e.submitter);
    if (out) { e.target.reset(); loadTasks(); }
  });
  $("#undo").addEventListener("click", (e) => act("/api/undo", {}, e.currentTarget));
  $("#reset").addEventListener("click", async (e) => {
    const out = await act("/api/reset", {}, e.currentTarget);
    if (out) { $("#report").hidden = true; $("#report-title").hidden = true; }
  });

  $("#panel-close").addEventListener("click", closePanel);
  $("#scrim").addEventListener("click", closePanel);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && openRoom) closePanel();
    if (e.key === "Tab" && openRoom) { // keep focus inside the open panel
      const f = $$("#panel button, #panel input, #panel select").filter((x) => !x.disabled);
      if (!f.length) return;
      if (e.shiftKey && document.activeElement === f[0]) { e.preventDefault(); f[f.length - 1].focus(); }
      else if (!e.shiftKey && document.activeElement === f[f.length - 1]) { e.preventDefault(); f[0].focus(); }
    }
  });
}

async function start() {
  wire();
  backend = await detectBackend();
  if (backend === "browser") {
    const boot = $("#boot");
    boot.hidden = false;
    try {
      await startWorker();
    } catch (e) {
      boot.querySelector("p").textContent = "The simulation could not start in this browser: " + e.message +
        " Check the internet connection (the Python runtime is downloaded on first use) and reload.";
      boot.classList.add("err");
      return;
    }
    boot.hidden = true;
  }
  await refreshAll();
  showTab();
  setInterval(() => { if (!document.hidden) refreshAll(false); }, 1000);
}

start();
