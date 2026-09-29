"use strict";
const provider = document.getElementById("expression.provider");
if (provider) {
  const update = () => {
    for (const name of ["local", "aws"]) {
      for (const section of document.querySelectorAll(`[data-provider="${name}"]`)) {
        section.hidden = provider.value !== name;
      }
    }
  };
  provider.addEventListener("change", update);
  // Show both provider sections after validation errors so inactive settings
  // can also be corrected without losing the selected provider.
  if (!document.querySelector(".error")) update();
}

// The administration UI consumes only the authenticated Remote API's semantic
// models.  Waitress exposes /events as SSE; EventSource carries session cookies
// and keeps this browser tab to one low-rate connection.
(() => {
  const dashboard = document.querySelector("[data-phos-live]");
  if (!dashboard || !window.EventSource) return;
  const indicator = document.getElementById("phos-connection");
  const note = dashboard.querySelector(".live-note");
  const error = dashboard.querySelector(".live-error");
  const state = {};
  let stream, retryTimer, retries = 0, fallbackTimer, opened = false;
  const endpoint = "/api/v1";
  const setConnection = (name) => {
    indicator.className = `connection ${name}`;
    indicator.textContent = `Live: ${name}`;
  };
  const display = (key, value) => {
    for (const node of dashboard.querySelectorAll(`[data-live="${key}"]`)) {
      const text = value === null || value === undefined || value === "" ? "Unavailable" : String(value);
      if (node.textContent !== text) node.textContent = text;
    }
  };
  const status = (item) => item && (item.status || item.state) || "unavailable";
  const age = (item) => item && Number.isFinite(item.age_seconds) ? `${item.age_seconds.toFixed(1)} seconds old` : "Unavailable";
  const reading = (item, field, suffix) => item && item.available && item.measurements && item.measurements[field] !== null ? `${item.measurements[field]} ${suffix}` : "Unavailable";
  const render = () => {
    const visual = state.visual || {};
    const environment = state.environment || {};
    const motion = state.motion || {};
    const ccs811 = state.ccs811 || (state.sensors || {}).ccs811 || {};
    const overlay = (state.overlay || {}).resolved || {};
    display("robot.state", (state.robot || {}).state);
    display("visual.expression", visual.expression);
    display("visual.source", state.active_visual_source || visual.source);
    display("motion.motion_state", motion.motion_state || visual.motion_state);
    display("environment.state", environment.state || ((state.sensors || {}).environmental_behavior || {}).state);
    display("environment.status", status(environment)); display("environment.temperature", reading(environment, "temperature_c", "°C"));
    display("environment.pressure", reading(environment, "pressure_hpa", "hPa")); display("environment.age", age(environment));
    display("ccs811.status", status(ccs811)); display("ccs811.eco2", reading(ccs811, "eco2_ppm", "ppm"));
    display("ccs811.tvoc", reading(ccs811, "tvoc_ppb", "ppb")); display("ccs811.age", age(ccs811));
    display("motion.status", status(motion)); display("motion.age", age(motion));
    display("overlay.resolved", `${overlay.temperature || "none"} / ${overlay.air_quality || "none"}`);
    const subsystems = ((state.health || {}).subsystems) || {};
    display("health", Object.entries(subsystems).map(([name, item]) => `${name}: ${item.state}`).join(", "));
    if (note) note.textContent = "Semantic runtime state; retained while reconnecting.";
  };
  const fetchJson = async (path) => {
    const response = await fetch(endpoint + path, {credentials: "same-origin", headers: {Accept: "application/json"}});
    if (!response.ok) throw new Error(`Snapshot unavailable (${response.status})`);
    return response.json();
  };
  const snapshot = async () => {
    try {
      const [current, overlay, capabilities] = await Promise.all([fetchJson("/status"), fetchJson("/overlay"), fetchJson("/capabilities")]);
      Object.assign(state, current, {overlay}); render(); configure(capabilities);
      if (error) error.hidden = true;
    } catch (problem) {
      if (error) { error.textContent = problem.message; error.hidden = false; }
    }
  };
  const configure = (capabilities) => {
    const controls = dashboard.querySelector("[data-live-controls]");
    if (!capabilities || !controls || controls.dataset.ready) return;
    const commands = capabilities.commands || {};
    for (const node of controls.querySelectorAll("[data-command]")) {
      const command = commands[node.dataset.command]; if (!command) { node.disabled = true; continue; }
      for (const value of command.allowed_values || []) node.add(new Option(value, value));
      node.addEventListener("change", async () => { await commandRequest(command.endpoint, {[command.field]: node.value}); });
    }
    const overlay = commands.set_overlay && commands.set_overlay.fields;
    for (const node of controls.querySelectorAll("select[data-overlay]")) {
      const field = overlay && overlay[node.dataset.overlay]; if (!field) { node.disabled = true; continue; }
      for (const value of field.allowed_values || []) node.add(new Option(value, value));
    }
    controls.querySelector("[data-overlay-submit]").addEventListener("click", async () => {
      const payload = {}; for (const node of controls.querySelectorAll("[data-overlay]")) payload[node.dataset.overlay] = node.type === "number" ? Number(node.value) : node.value;
      await commandRequest("/overlay", payload);
    });
    controls.querySelector("[data-overlay-clear]").addEventListener("click", async () => { await commandRequest("/overlay", undefined, "DELETE"); });
    controls.hidden = false; controls.dataset.ready = "true";
  };
  const commandRequest = async (path, payload, method = "POST") => {
    try { const response = await fetch(endpoint + path, {method, credentials: "same-origin", headers: {"Content-Type": "application/json", Accept: "application/json"}, body: payload ? JSON.stringify(payload) : undefined}); if (!response.ok) throw new Error((await response.json()).error.message); await snapshot(); }
    catch (problem) { error.textContent = problem.message; error.hidden = false; }
  };
  const applyEvent = (event) => {
    const payload = event.payload || {};
    if (event.type === "robot_state_changed") state.robot = payload;
    else if (event.type === "expression_changed") state.visual = {...(state.visual || {}), ...payload};
    else if (event.type === "visual_state_changed") state.visual = {...(state.visual || {}), ...payload};
    else if (event.type === "environmental_state_changed") state.environment = payload;
    else if (event.type === "motion_state_changed") state.motion = payload;
    else if (event.type === "health_changed") state.health = payload;
    else if (event.type === "overlay_changed" || event.type === "environmental_overlay_changed") state.overlay = payload;
    else return;
    render();
  };
  const fallback = () => { if (!fallbackTimer) fallbackTimer = window.setInterval(snapshot, 30000); };
  const connect = () => {
    window.clearTimeout(retryTimer); stream = new EventSource(endpoint + "/events", {withCredentials: true});
    stream.onopen = async () => { const reconnect = opened; opened = true; retries = 0; setConnection("connected"); window.clearInterval(fallbackTimer); fallbackTimer = undefined; if (reconnect) await snapshot(); };
    // The SSE adapter uses named semantic events, so listen explicitly rather
    // than relying on EventSource's unnamed-message default.
    for (const type of ["robot_state_changed", "expression_changed", "visual_state_changed", "environmental_state_changed", "environmental_overlay_changed", "motion_state_changed", "health_changed", "presence_changed", "overlay_changed"]) {
      stream.addEventListener(type, (message) => { try { applyEvent(JSON.parse(message.data)); } catch (_) {} });
    }
    stream.onerror = () => { stream.close(); setConnection("reconnecting"); fallback(); const delay = Math.min(30000, 1000 * 2 ** Math.min(retries++, 5)); retryTimer = window.setTimeout(connect, delay); };
  };
  snapshot().then(connect); setConnection("reconnecting");
})();
