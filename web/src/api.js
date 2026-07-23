// Helper API ke core FastAPI (same-origin di produksi).

export async function getStatus() {
  const r = await fetch("/api/status");
  return r.json();
}

export async function getConfig() {
  const r = await fetch("/api/config");
  return r.json();
}

export async function saveConfig(data) {
  const r = await fetch("/api/config", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  return r.json();
}

export async function getClasses() {
  const r = await fetch("/api/classes");
  return r.json();
}

export async function getHistory(limit = 50) {
  const r = await fetch(`/api/history?limit=${limit}`);
  return r.json();
}

export async function post(path, body) {
  const r = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  return r.json();
}

export const estop = () => post("/api/estop");
export const clearEstop = () => post("/api/estop/clear");
export const setMode = (manual) => post("/api/mode", { manual });
export const manualCmd = (cmd) => post("/api/manual", { cmd });
export const calibrateEmpty = () => post("/api/calibrate/empty");

async function del(path) {
  const r = await fetch(path, { method: "DELETE" });
  return r.json();
}

// riwayat
export const deleteHistory = (id) => del(`/api/history/${id}`);
export const clearHistory = () => del("/api/history");

// dataset
export async function dsList() {
  const r = await fetch("/api/dataset/list");
  return r.json();
}
export const dsCapture = () => post("/api/dataset/capture");
export const dsDelete = (name) => del(`/api/dataset/image/${encodeURIComponent(name)}`);
export async function dsGetLabel(name) {
  const r = await fetch(`/api/dataset/label/${encodeURIComponent(name)}`);
  return r.json();
}
export const dsSaveLabel = (name, boxes) =>
  post(`/api/dataset/label/${encodeURIComponent(name)}`, { boxes });

// training
export const trainStart = (params) => post("/api/train/start", params);
export const trainStop = () => post("/api/train/stop");
export async function trainStatus() {
  const r = await fetch("/api/train/status");
  return r.json();
}
export async function listModels() {
  const r = await fetch("/api/models");
  return r.json();
}
export const activateModel = (path) => post("/api/models/activate", { path });

// WebSocket status dengan auto-reconnect + fallback polling.
export function subscribeStatus(onData) {
  let ws,
    alive = true,
    poll;
  function connect() {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    ws = new WebSocket(`${proto}://${location.host}/ws`);
    ws.onmessage = (e) => onData(JSON.parse(e.data));
    ws.onclose = () => {
      if (!alive) return;
      startPolling();
      setTimeout(connect, 2000);
    };
    ws.onopen = () => stopPolling();
  }
  function startPolling() {
    if (poll) return;
    poll = setInterval(async () => {
      try {
        onData(await getStatus());
      } catch (_) {}
    }, 1000);
  }
  function stopPolling() {
    if (poll) {
      clearInterval(poll);
      poll = null;
    }
  }
  connect();
  return () => {
    alive = false;
    stopPolling();
    if (ws) ws.close();
  };
}
