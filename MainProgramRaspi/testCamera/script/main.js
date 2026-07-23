/* ========================================
   PemilahBuahNaga — Camera Monitor JS
   ======================================== */

(function () {
    "use strict";

    const statusText = document.getElementById("status-text");
    const statusDot = document.querySelector(".dot");
    const infoCam1 = document.getElementById("info-cam1");
    const infoCam2 = document.getElementById("info-cam2");
    const stream1 = document.getElementById("stream1");
    const stream2 = document.getElementById("stream2");

    // Check status periodically
    async function checkStatus() {
        try {
            const res = await fetch("/status");
            const data = await res.json();

            statusDot.className = "dot dot-green";
            statusText.textContent = "Connected";

            const keys = Object.keys(data);
            if (keys.length >= 1) {
                const c1 = data[keys[0]];
                infoCam1.textContent = `${c1.device} — ${c1.fps} FPS`;
            }
            if (keys.length >= 2) {
                const c2 = data[keys[1]];
                infoCam2.textContent = `${c2.device} — ${c2.fps} FPS`;
            }
        } catch {
            statusDot.className = "dot dot-red";
            statusText.textContent = "Disconnected";
            infoCam1.textContent = "--";
            infoCam2.textContent = "--";
        }
    }

    // Handle image load errors — reload stream
    function setupStreamReload(img, url) {
        img.addEventListener("error", function () {
            setTimeout(() => {
                img.src = url + "?t=" + Date.now();
            }, 2000);
        });
    }

    setupStreamReload(stream1, "/video_feed_1");
    setupStreamReload(stream2, "/video_feed_2");

    // Initial check + interval
    checkStatus();
    setInterval(checkStatus, 2000);
})();
