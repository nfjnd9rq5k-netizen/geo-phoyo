"""
Dashboard v3 — Interface web pour Geo Photo.
Carte interactive + upload photo + controle Frida + lancement Certificall.
"""

import http.server
import json
import os
import shutil
import sys
import tempfile
import threading
import webbrowser

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from orchestrator import GeoPhotoOrchestrator

PORT = 8420
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# ── Orchestrator global ──
orch = GeoPhotoOrchestrator()

# ── HTML ──
HTML_PAGE = r"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Geo Photo v3</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #1a1a2e; color: #eee; display: flex; flex-direction: column; height: 100vh; }
#map { flex: 1; }
.panel {
    padding: 10px 20px;
    background: #16213e;
    display: flex;
    align-items: center;
    gap: 12px;
    flex-wrap: wrap;
}
.panel input[type="text"] {
    padding: 8px 12px;
    border: 1px solid #444;
    border-radius: 6px;
    background: #0f3460;
    color: #eee;
    font-size: 14px;
    outline: none;
}
.panel input[type="text"]:focus { border-color: #e94560; }
#search { flex: 1; min-width: 200px; }
#ip { width: 160px; }
.btn {
    padding: 8px 18px;
    border: none;
    border-radius: 6px;
    cursor: pointer;
    font-size: 14px;
    font-weight: 600;
    background: #0f3460;
    color: #eee;
    border: 1px solid #e94560;
    white-space: nowrap;
}
.btn:hover { background: #e94560; }
.btn-launch {
    background: #e94560;
    border-color: #e94560;
    color: #fff;
    font-size: 15px;
    padding: 10px 24px;
}
.btn-launch:hover { background: #c0392b; }
.btn-launch.active {
    background: #27ae60;
    border-color: #27ae60;
}
.btn-stop {
    background: #333;
    border-color: #e94560;
}
.coords {
    background: #0f3460;
    padding: 8px 14px;
    border-radius: 6px;
    font-family: monospace;
    font-size: 14px;
    min-width: 240px;
    text-align: center;
}
label { font-size: 13px; color: #aaa; }
.status-bar {
    padding: 6px 20px;
    background: #0f0f23;
    display: flex;
    align-items: center;
    gap: 16px;
    font-size: 12px;
    border-top: 1px solid #333;
    flex-wrap: wrap;
}
.status-dot {
    width: 10px; height: 10px;
    border-radius: 50%;
    display: inline-block;
}
.dot-ok { background: #4ecca3; }
.dot-ko { background: #e94560; }
.dot-warn { background: #f0c040; }

.drop-zone {
    border: 2px dashed #444;
    border-radius: 8px;
    padding: 12px 16px;
    text-align: center;
    color: #888;
    font-size: 13px;
    cursor: pointer;
    transition: border-color 0.2s, background 0.2s;
    min-width: 200px;
}
.drop-zone.dragover { border-color: #e94560; background: rgba(233,69,96,0.1); color: #eee; }
.drop-zone.uploading { color: #f0c040; }
.drop-zone.success { color: #4ecca3; border-color: #4ecca3; }
.drop-zone.error { color: #e94560; }

.log-panel {
    background: #0a0a1a;
    border-top: 1px solid #222;
    padding: 6px 12px;
    max-height: 120px;
    overflow-y: auto;
    font-family: monospace;
    font-size: 11px;
    color: #8a8;
}
.log-panel div { padding: 1px 0; }
.log-panel .error { color: #e94560; }
</style>
</head>
<body>

<div class="panel">
    <input type="text" id="search" placeholder="Rechercher une adresse..." />
    <button class="btn" id="searchBtn" onclick="doSearch()">Rechercher</button>
    <div class="coords" id="coordsDisplay">Cliquez sur la carte</div>
    <label>IP: <input type="text" id="ip" value="86.234.12.45" /></label>
    <div class="drop-zone" id="dropZone">Glisser une photo ici</div>
    <button class="btn btn-launch" id="launchBtn" onclick="doLaunch()">Lancer Certificall</button>
    <button class="btn btn-stop" id="stopBtn" onclick="doStop()" style="display:none;">Stop</button>
</div>

<div id="map"></div>

<div class="status-bar">
    <span>BlueStacks: <span class="status-dot" id="emuDot"></span> <span id="emuText">...</span></span>
    <span>pict2cam: <span class="status-dot" id="p2cDot"></span></span>
    <span>Frida: <span class="status-dot" id="fridaDot"></span> <span id="fridaText">inactif</span></span>
    <span>GPS: <span id="statusGps">--</span></span>
    <span>IP: <span id="statusIp">--</span></span>
    <span id="uploadStatus"></span>
</div>

<div class="log-panel" id="logPanel"></div>

<script>
// ── Carte ──
var map = L.map('map').setView([48.8566, 2.3522], 6);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '&copy; OpenStreetMap', maxZoom: 19
}).addTo(map);

var marker = null;

function setMarker(lat, lon) {
    if (marker) marker.setLatLng([lat, lon]);
    else {
        marker = L.marker([lat, lon], {draggable: true}).addTo(map);
        marker.on('dragend', function(e) {
            var p = e.target.getLatLng();
            sendGps(p.lat, p.lng);
        });
    }
    document.getElementById('coordsDisplay').textContent =
        'Lat: ' + lat.toFixed(6) + '  Lon: ' + lon.toFixed(6);
}

function sendGps(lat, lon) {
    setMarker(lat, lon);
    fetch('/api/gps', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({lat: lat, lon: lon})
    });
}

map.on('click', function(e) { sendGps(e.latlng.lat, e.latlng.lng); });

// ── Recherche ──
function doSearch() {
    var q = document.getElementById('search').value.trim();
    if (!q) return;
    document.getElementById('searchBtn').textContent = '...';
    fetch('https://nominatim.openstreetmap.org/search?format=json&limit=1&q=' + encodeURIComponent(q))
        .then(function(r) { return r.json(); })
        .then(function(data) {
            document.getElementById('searchBtn').textContent = 'Rechercher';
            if (data && data.length > 0) {
                var lat = parseFloat(data[0].lat), lon = parseFloat(data[0].lon);
                sendGps(lat, lon);
                map.setView([lat, lon], 17);
            } else alert('Adresse introuvable.');
        })
        .catch(function() {
            document.getElementById('searchBtn').textContent = 'Rechercher';
            alert('Erreur de geocodage.');
        });
}
document.getElementById('search').addEventListener('keydown', function(e) {
    if (e.key === 'Enter') doSearch();
});

// ── IP ──
var ipInput = document.getElementById('ip');
var ipTimer = null;
ipInput.addEventListener('input', function() {
    clearTimeout(ipTimer);
    ipTimer = setTimeout(function() {
        fetch('/api/ip', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ip: ipInput.value.trim()})
        });
    }, 500);
});

// ── Drop zone photo ──
var dropZone = document.getElementById('dropZone');
dropZone.addEventListener('dragover', function(e) { e.preventDefault(); dropZone.classList.add('dragover'); });
dropZone.addEventListener('dragleave', function() { dropZone.classList.remove('dragover'); });
dropZone.addEventListener('drop', function(e) {
    e.preventDefault(); dropZone.classList.remove('dragover');
    for (var i = 0; i < e.dataTransfer.files.length; i++) uploadPhoto(e.dataTransfer.files[i]);
});
dropZone.addEventListener('click', function() {
    var inp = document.createElement('input');
    inp.type = 'file'; inp.accept = 'image/jpeg,image/png,image/webp'; inp.multiple = true;
    inp.onchange = function() { for (var i = 0; i < inp.files.length; i++) uploadPhoto(inp.files[i]); };
    inp.click();
});

function uploadPhoto(file) {
    dropZone.textContent = 'Upload: ' + file.name + '...';
    dropZone.className = 'drop-zone uploading';
    fetch('/api/photo', { method: 'POST', headers: {'X-Filename': file.name}, body: file })
    .then(function(r) { return r.json().then(function(data) { return {status: r.status, data: data}; }); })
    .then(function(res) {
        if (res.data.ok) {
            dropZone.textContent = file.name + ' - OK';
            dropZone.className = 'drop-zone success';
        } else {
            dropZone.textContent = 'Erreur: ' + (res.data.error || 'erreur ' + res.status);
            dropZone.className = 'drop-zone error';
        }
        setTimeout(function() { dropZone.textContent = 'Glisser une photo ici'; dropZone.className = 'drop-zone'; }, 4000);
    })
    .catch(function(err) {
        dropZone.textContent = 'Erreur reseau: ' + (err.message || 'serveur injoignable');
        dropZone.className = 'drop-zone error';
        setTimeout(function() { dropZone.textContent = 'Glisser une photo ici'; dropZone.className = 'drop-zone'; }, 4000);
    });
}

// ── Launch / Stop ──
function doLaunch() {
    var btn = document.getElementById('launchBtn');
    btn.textContent = 'Lancement...';
    btn.disabled = true;
    fetch('/api/launch', { method: 'POST' })
    .then(function(r) { return r.json(); })
    .then(function(data) {
        btn.disabled = false;
        if (data.ok) {
            btn.textContent = 'Frida actif';
            btn.classList.add('active');
            document.getElementById('stopBtn').style.display = '';
        } else {
            btn.textContent = 'Lancer Certificall';
            alert('Erreur: ' + (data.error || 'echec'));
        }
    })
    .catch(function() { btn.disabled = false; btn.textContent = 'Lancer Certificall'; });
}

function doStop() {
    fetch('/api/stop', { method: 'POST' })
    .then(function() {
        document.getElementById('launchBtn').textContent = 'Lancer Certificall';
        document.getElementById('launchBtn').classList.remove('active');
        document.getElementById('stopBtn').style.display = 'none';
    });
}

// ── Status poll ──
function pollStatus() {
    fetch('/api/status').then(function(r) { return r.json(); }).then(function(d) {
        // BlueStacks
        var emuDot = document.getElementById('emuDot');
        var emuText = document.getElementById('emuText');
        emuDot.className = 'status-dot ' + (d.adb_connected ? 'dot-ok' : 'dot-ko');
        emuText.textContent = d.adb_connected ? 'connecte' : 'deconnecte';
        // pict2cam
        document.getElementById('p2cDot').className = 'status-dot ' + (d.pict2cam_installed ? 'dot-ok' : 'dot-ko');
        // Frida
        var fridaDot = document.getElementById('fridaDot');
        var fridaText = document.getElementById('fridaText');
        if (d.frida_active) {
            fridaDot.className = 'status-dot dot-ok';
            fridaText.textContent = 'actif';
        } else if (d.frida_server_running) {
            fridaDot.className = 'status-dot dot-warn';
            fridaText.textContent = 'server OK';
        } else {
            fridaDot.className = 'status-dot dot-ko';
            fridaText.textContent = 'inactif';
        }
        // GPS / IP
        document.getElementById('statusGps').textContent = (d.lat || 0).toFixed(4) + ', ' + (d.lon || 0).toFixed(4);
        document.getElementById('statusIp').textContent = d.ip || '--';
        // Boutons
        var btn = document.getElementById('launchBtn');
        if (d.frida_active) {
            btn.textContent = 'Frida actif';
            btn.classList.add('active');
            document.getElementById('stopBtn').style.display = '';
        } else {
            btn.textContent = 'Lancer Certificall';
            btn.classList.remove('active');
            document.getElementById('stopBtn').style.display = 'none';
        }
    }).catch(function() {});
}
setInterval(pollStatus, 5000);
pollStatus();

// ── Log poll ──
var logIndex = 0;
function pollLogs() {
    fetch('/api/logs?since=' + logIndex).then(function(r) { return r.json(); }).then(function(data) {
        var panel = document.getElementById('logPanel');
        if (data.lines && data.lines.length > 0) {
            data.lines.forEach(function(line) {
                var div = document.createElement('div');
                div.textContent = line;
                if (line.indexOf('ERROR') >= 0 || line.indexOf('ERREUR') >= 0 || line.indexOf('echec') >= 0)
                    div.className = 'error';
                panel.appendChild(div);
            });
            logIndex += data.lines.length;
            panel.scrollTop = panel.scrollHeight;
        }
    }).catch(function() {});
}
setInterval(pollLogs, 2000);
pollLogs();
</script>
</body>
</html>"""


class DashboardHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            self._serve_html()
        elif self.path == "/api/status":
            self._json_response(200, orch.get_status())
        elif self.path.startswith("/api/logs"):
            self._handle_logs()
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path == "/api/gps":
            self._handle_gps()
        elif self.path == "/api/ip":
            self._handle_ip()
        elif self.path == "/api/photo":
            self._handle_photo()
        elif self.path == "/api/launch":
            self._handle_launch()
        elif self.path == "/api/stop":
            self._handle_stop()
        else:
            self.send_error(404)

    # ── GET ──

    def _serve_html(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(HTML_PAGE.encode("utf-8"))

    def _handle_logs(self):
        since = 0
        if "?" in self.path:
            params = self.path.split("?")[1]
            for p in params.split("&"):
                if p.startswith("since="):
                    try:
                        since = int(p.split("=")[1])
                    except ValueError:
                        pass
        lines = orch.get_logs(since)
        self._json_response(200, {"lines": lines})

    # ── POST ──

    def _handle_gps(self):
        data = self._read_json()
        if data is None:
            return
        lat = data.get("lat")
        lon = data.get("lon")
        if lat is None or lon is None:
            self._json_response(400, {"ok": False, "error": "lat/lon requis"})
            return
        orch.update_location(lat, lon)
        self._json_response(200, {"ok": True})

    def _handle_ip(self):
        data = self._read_json()
        if data is None:
            return
        ip = data.get("ip", "")
        orch.update_ip(ip)
        self._json_response(200, {"ok": True})

    def _handle_photo(self):
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            self._json_response(400, {"ok": False, "error": "corps vide"})
            return
        filename = self.headers.get("X-Filename", "photo.jpg")
        raw = self.rfile.read(length)

        tmp_dir = tempfile.mkdtemp(prefix="geophoto_")
        input_path = os.path.join(tmp_dir, filename)
        with open(input_path, "wb") as f:
            f.write(raw)

        ok, result = orch.process_photo(input_path, filename)
        shutil.rmtree(tmp_dir, ignore_errors=True)

        if ok:
            self._json_response(200, {"ok": True, "output": result})
        else:
            self._json_response(500, {"ok": False, "error": result})

    def _handle_launch(self):
        ok, msg = orch.launch_certificall()
        self._json_response(200, {"ok": ok, "message": msg, "error": None if ok else msg})

    def _handle_stop(self):
        orch.stop()
        self._json_response(200, {"ok": True})

    # ── Helpers ──

    def _read_json(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        try:
            return json.loads(body)
        except (json.JSONDecodeError, ValueError):
            self._json_response(400, {"ok": False, "error": "JSON invalide"})
            return None

    def _json_response(self, code, data):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode("utf-8"))

    def log_message(self, fmt, *args):
        pass


def main():
    os.makedirs(os.path.join(SCRIPT_DIR, "output"), exist_ok=True)

    print("=" * 50)
    print("  GEO PHOTO v3 — Dashboard")
    print("=" * 50)

    # Setup initial
    status = orch.setup()

    if not status["adb_found"]:
        print("\n  ERREUR: ADB non trouve!")
        print("  Verifiez que BlueStacks est installe.")
        return

    if not status["connected"]:
        print("\n  ATTENTION: Emulateur non connecte.")
        print("  Lancez BlueStacks et reessayez.")

    if status["connected"] and not status["pict2cam"]:
        print("\n  ATTENTION: pict2cam non installe sur l'emulateur.")
        print("  Installez-le: HD-Adb.exe install pict2cam.apk")

    if status["certificall_package"]:
        print(f"\n  Certificall: {status['certificall_package']}")
    else:
        print("\n  ATTENTION: Certificall non trouve sur l'emulateur.")

    print(f"\n  Dashboard: http://127.0.0.1:{PORT}")
    print("  Ctrl+C pour arreter\n")

    # Ouvrir le navigateur
    threading.Timer(1.5, lambda: webbrowser.open(f"http://127.0.0.1:{PORT}")).start()

    server = http.server.HTTPServer(("127.0.0.1", PORT), DashboardHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nArret du dashboard.")
        orch.stop()
        server.shutdown()


if __name__ == "__main__":
    main()
