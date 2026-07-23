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
