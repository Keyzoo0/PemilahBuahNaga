import React, { useEffect, useState } from "react";
import Monitor from "./pages/Monitor.jsx";
import Settings from "./pages/Settings.jsx";
import { subscribeStatus, estop, clearEstop, setMode } from "./api.js";

export default function App() {
  const [tab, setTab] = useState("monitor");
  const [status, setStatus] = useState(null);

  useEffect(() => subscribeStatus(setStatus), []);

  const online = !!status;
  const manual = status?.manual_mode;
  const isEstop = status?.estop;

  return (
    <div className="app">
      <div className="topbar">
        <div className="brand">
          <span className="logo">🐉</span>
          <span className="name">PemilahBuahNaga</span>
        </div>

        <div className="tabs">
          <button className={tab === "monitor" ? "active" : ""} onClick={() => setTab("monitor")}>
            Monitor
          </button>
          <button className={tab === "settings" ? "active" : ""} onClick={() => setTab("settings")}>
            Kalibrasi
          </button>
        </div>

        <div className="spacer" />

        <div className="conn">
          <span className={"dot " + (online ? "ok" : "bad")} />
          {online ? "Terhubung" : "Menghubungkan..."}
        </div>

        <button
          className="btn sm"
          onClick={() => setMode(!manual)}
          title="Mode manual menahan otomatis untuk kalibrasi"
        >
          Mode: {manual ? "MANUAL" : "AUTO"}
        </button>

        {isEstop ? (
          <button className="btn primary" onClick={clearEstop}>
            Lepas E-STOP
          </button>
        ) : (
          <button className="btn estop" onClick={estop}>
            ■ E-STOP
          </button>
        )}
      </div>

      {tab === "monitor" ? <Monitor status={status} /> : <Settings status={status} />}
    </div>
  );
}
