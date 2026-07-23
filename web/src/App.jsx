import React, { useEffect, useState } from "react";
import Monitor from "./pages/Monitor.jsx";
import Settings from "./pages/Settings.jsx";
import Dataset from "./pages/Dataset.jsx";
import Annotate from "./pages/Annotate.jsx";
import Training from "./pages/Training.jsx";
import { subscribeStatus, estop, clearEstop, setMode } from "./api.js";

export default function App() {
  const [tab, setTab] = useState("monitor");
  const [status, setStatus] = useState(null);
  const [annotateImg, setAnnotateImg] = useState(null);

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
          <button className={tab === "dataset" ? "active" : ""} onClick={() => setTab("dataset")}>
            Dataset
          </button>
          <button className={tab === "annotate" ? "active" : ""} onClick={() => setTab("annotate")}>
            Anotasi
          </button>
          <button className={tab === "training" ? "active" : ""} onClick={() => setTab("training")}>
            Training
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

      {tab === "monitor" && <Monitor status={status} />}
      {tab === "settings" && <Settings status={status} />}
      {tab === "dataset" && (
        <Dataset
          onAnnotate={(name) => {
            setAnnotateImg(name);
            setTab("annotate");
          }}
        />
      )}
      {tab === "annotate" && <Annotate initial={annotateImg} />}
      {tab === "training" && <Training />}
    </div>
  );
}
