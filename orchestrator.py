"""
Orchestrator v3 - Coeur du systeme Geo Photo.
Gere le pipeline photo, la session Frida, et la coordination ADB.
"""

import os
import sys
import shutil
import tempfile
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bluestacks_controller as bsc
from geo import modify_geolocation

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(SCRIPT_DIR, "output")
HOOKS_DIR = os.path.join(SCRIPT_DIR, "frida_hooks")


class GeoPhotoOrchestrator:
    def __init__(self):
        self.adb_path = None
        self.frida_session = None
        self.frida_script = None
        self.frida_device = None
        self._log_lines = []
        self._log_lock = threading.Lock()
        self.state = {
            "lat": 48.8566,
            "lon": 2.3522,
            "ip": "86.234.12.45",
            "altitude": 35.0,
            "certificall_package": None,
            "frida_active": False,
            "last_photo": None,
        }
        self.state_lock = threading.Lock()

    def _log(self, msg):
        """Ajoute un message au log interne."""
        line = f"[{time.strftime('%H:%M:%S')}] {msg}"
        with self._log_lock:
            self._log_lines.append(line)
            if len(self._log_lines) > 200:
                self._log_lines = self._log_lines[-100:]
        print(f"  {line}")

    def get_logs(self, since=0):
        """Retourne les logs depuis l'index donne."""
        with self._log_lock:
            return self._log_lines[since:]

    # ── Setup ──

    def setup(self):
        """Initialise ADB, verifie les prerequis. Retourne un dict de status."""
        self.adb_path = bsc.find_adb()
        status = {
            "adb_found": self.adb_path is not None,
            "connected": False,
            "pict2cam": False,
            "frida_server": False,
            "certificall_package": None,
        }
        if not self.adb_path:
            self._log("ADB non trouve")
            return status

        if not bsc.is_connected(self.adb_path):
            bsc.connect_bluestacks(self.adb_path)

        status["connected"] = bsc.is_connected(self.adb_path)
        if not status["connected"]:
            self._log("Emulateur non connecte")
            return status

        status["pict2cam"] = bsc.is_pict2cam_installed(self.adb_path)
        status["frida_server"] = bsc.is_frida_server_running(self.adb_path)

        pkg = bsc.find_certificall_package(self.adb_path)
        status["certificall_package"] = pkg
        with self.state_lock:
            self.state["certificall_package"] = pkg

        self._log(f"ADB: {self.adb_path}")
        self._log(f"pict2cam: {'OK' if status['pict2cam'] else 'MANQUANT'}")
        self._log(f"frida-server: {'OK' if status['frida_server'] else 'INACTIF'}")
        self._log(f"Certificall: {pkg or 'NON TROUVE'}")

        return status

    # ── Photo pipeline ──

    def _inject_camera_metadata(self, image_path):
        """Ajoute les metadonnees camera realistes si absentes."""
        import piexif
        import random

        try:
            exif_dict = piexif.load(image_path)
        except Exception:
            return

        ifd0 = exif_dict.setdefault("0th", {})
        exif_ifd = exif_dict.setdefault("Exif", {})

        # Make/Model Samsung Galaxy S21
        if not ifd0.get(piexif.ImageIFD.Make):
            ifd0[piexif.ImageIFD.Make] = b"samsung"
        if not ifd0.get(piexif.ImageIFD.Model):
            ifd0[piexif.ImageIFD.Model] = b"SM-G991B"
        if not ifd0.get(piexif.ImageIFD.Software):
            ifd0[piexif.ImageIFD.Software] = b"G991BXXS7DWBA"

        # Parametres camera realistes (Galaxy S21 main camera)
        if not exif_ifd.get(piexif.ExifIFD.FocalLength):
            exif_ifd[piexif.ExifIFD.FocalLength] = (6400, 1000)  # 6.4mm
        if not exif_ifd.get(piexif.ExifIFD.FocalLengthIn35mmFilm):
            exif_ifd[piexif.ExifIFD.FocalLengthIn35mmFilm] = 26
        if not exif_ifd.get(piexif.ExifIFD.FNumber):
            exif_ifd[piexif.ExifIFD.FNumber] = (180, 100)  # f/1.8
        if not exif_ifd.get(piexif.ExifIFD.ISOSpeedRatings):
            exif_ifd[piexif.ExifIFD.ISOSpeedRatings] = random.choice([50, 80, 100, 125, 160, 200, 250])
        if not exif_ifd.get(piexif.ExifIFD.ExposureTime):
            exif_ifd[piexif.ExifIFD.ExposureTime] = random.choice([
                (1, 120), (1, 100), (1, 200), (1, 250), (1, 500), (1, 60)
            ])
        if not exif_ifd.get(piexif.ExifIFD.ExposureProgram):
            exif_ifd[piexif.ExifIFD.ExposureProgram] = 2  # Normal
        if not exif_ifd.get(piexif.ExifIFD.MeteringMode):
            exif_ifd[piexif.ExifIFD.MeteringMode] = 2  # Center-weighted
        if not exif_ifd.get(piexif.ExifIFD.Flash):
            exif_ifd[piexif.ExifIFD.Flash] = 0  # No flash
        if not exif_ifd.get(piexif.ExifIFD.WhiteBalance):
            exif_ifd[piexif.ExifIFD.WhiteBalance] = 0  # Auto
        if not exif_ifd.get(piexif.ExifIFD.ColorSpace):
            exif_ifd[piexif.ExifIFD.ColorSpace] = 1  # sRGB
        if not exif_ifd.get(piexif.ExifIFD.SceneCaptureType):
            exif_ifd[piexif.ExifIFD.SceneCaptureType] = 0  # Standard
        if not exif_ifd.get(piexif.ExifIFD.ExifVersion):
            exif_ifd[piexif.ExifIFD.ExifVersion] = b"0232"

        # SubSecTime realiste
        subsec = str(random.randint(100, 999)).encode()
        for tag in [piexif.ExifIFD.SubSecTime, piexif.ExifIFD.SubSecTimeOriginal, piexif.ExifIFD.SubSecTimeDigitized]:
            if not exif_ifd.get(tag):
                exif_ifd[tag] = subsec

        # Image dimensions
        try:
            from PIL import Image
            img = Image.open(image_path)
            w, h = img.size
            ifd0[piexif.ImageIFD.ImageWidth] = w
            ifd0[piexif.ImageIFD.ImageLength] = h
            exif_ifd[piexif.ExifIFD.PixelXDimension] = w
            exif_ifd[piexif.ExifIFD.PixelYDimension] = h
        except Exception:
            pass

        # YCbCrPositioning (standard pour photos camera)
        ifd0[piexif.ImageIFD.YCbCrPositioning] = 1

        try:
            exif_bytes = piexif.dump(exif_dict)
            piexif.insert(exif_bytes, image_path)
        except Exception:
            pass

    def process_photo(self, input_path, filename):
        """Modifie EXIF + push vers BlueStacks. Retourne (success, message)."""
        os.makedirs(OUTPUT_DIR, exist_ok=True)

        with self.state_lock:
            lat = self.state["lat"]
            lon = self.state["lon"]
            alt = self.state["altitude"]

        # Injecter les metadonnees camera AVANT geo.py (pour qu'il les preserve)
        self._inject_camera_metadata(input_path)

        try:
            modify_geolocation(input_path, lat, lon, altitude=alt)
            self._log(f"EXIF modifie: {filename} ({lat}, {lon})")
        except Exception as e:
            self._log(f"Erreur geo.py: {e}")
            return False, str(e)

        # Sauvegarder dans output/
        output_path = os.path.join(OUTPUT_DIR, filename)
        shutil.copy2(input_path, output_path)

        # Push vers BlueStacks
        push_ok, push_msg = bsc.push_photo(input_path, self.adb_path)
        if push_ok:
            self._log(f"Photo push OK: {filename}")
        else:
            self._log(f"Photo push ECHEC: {push_msg}")

        with self.state_lock:
            self.state["last_photo"] = output_path

        return True, output_path

    # ── Frida ──

    def build_frida_script(self):
        """Construit le script Frida en concatenant les hooks JS."""
        js_files = [
            "config.js",
            "anti_detection.js",
            "ssl_bypass.js",
            "spoof_location.js",
            "ip_spoof.js",
            "main.js",
        ]

        parts = []
        for fname in js_files:
            fpath = os.path.join(HOOKS_DIR, fname)
            if not os.path.exists(fpath):
                self._log(f"ATTENTION: {fname} introuvable")
                continue
            with open(fpath, "r", encoding="utf-8") as f:
                content = f.read()

            # Injecter les overrides apres config.js
            if fname == "config.js":
                with self.state_lock:
                    lat = self.state["lat"]
                    lon = self.state["lon"]
                    alt = self.state["altitude"]
                    ip = self.state["ip"]
                overrides = f"""
// === CONFIG OVERRIDES (injecte par orchestrator.py) ===
CONFIG.latitude = {lat};
CONFIG.longitude = {lon};
CONFIG.altitude = {alt};
CONFIG.network.ip = "{ip}";
CONFIG.network.enabled = true;
"""
                content += overrides

            parts.append(f"// ── {fname} ──\n{content}\n")

        return "\n".join(parts)

    def _push_hooks_to_device(self):
        """Pousse le script JS concatene vers /data/local/tmp/frida_hooks.js."""
        script_content = self.build_frida_script()
        local_script = os.path.join(OUTPUT_DIR, "frida_hooks.js")
        with open(local_script, "w", encoding="utf-8") as f:
            f.write(script_content)

        # Push via sdcard puis copie (evite les problemes de path Git Bash)
        import tempfile as _tmpmod
        tmp_script = os.path.join(_tmpmod.gettempdir(), "frida_hooks.js")
        shutil.copy2(local_script, tmp_script)
        bsc.run_adb(["push", tmp_script, "/sdcard/frida_hooks.js"], self.adb_path)
        bsc.run_adb(["shell", "cp /sdcard/frida_hooks.js /data/local/tmp/frida_hooks.js"], self.adb_path)
        bsc.run_adb(["shell", "rm /sdcard/frida_hooks.js"], self.adb_path)
        self._log(f"Script hooks pousse ({len(script_content)} octets)")

    def launch_certificall(self):
        """Lance Certificall. Le proxy MITM gere les checks serveur."""
        with self.state_lock:
            package = self.state["certificall_package"]
        if not package:
            package = bsc.find_certificall_package(self.adb_path)
            if not package:
                return False, "Package Certificall non trouve sur l'appareil"
            with self.state_lock:
                self.state["certificall_package"] = package

        # 1. Desactiver mock_location
        bsc.run_adb(["shell", "settings put secure mock_location 0"], self.adb_path)

        # 2. Verifier le proxy MITM
        ok, proxy = bsc.run_adb(["shell", "settings get global http_proxy"], self.adb_path)
        if not ok or "8888" not in (proxy or ""):
            self._log("Configuration du proxy MITM...")
            bsc.run_adb(["shell", "settings put global http_proxy 10.0.2.2:8888"], self.adb_path)

        # 3. Lancer l'app
        self._log(f"Lancement {package}...")
        bsc.launch_app(package, self.adb_path)

        with self.state_lock:
            self.state["frida_active"] = True

        self._log("Certificall lance! (proxy MITM actif)")
        return True, "Certificall lance avec proxy MITM"

    def update_location(self, lat, lon):
        """Met a jour GPS (state + ADB)."""
        with self.state_lock:
            self.state["lat"] = lat
            self.state["lon"] = lon

        # ADB geo fix
        bsc.set_gps_via_geo_fix(lat, lon, self.adb_path)

    def update_ip(self, ip):
        """Met a jour l'IP spoofee."""
        with self.state_lock:
            self.state["ip"] = ip

        if self.frida_script:
            try:
                self.frida_script.exports_sync.set_ip(ip)
            except Exception as e:
                self._log(f"IP Frida echec: {e}")

        # Re-push le script hooks avec la nouvelle IP
        if self.state.get("frida_active"):
            self._push_hooks_to_device()

    def get_status(self):
        """Retourne le status complet."""
        with self.state_lock:
            data = dict(self.state)

        data["adb_connected"] = bsc.is_connected(self.adb_path)
        data["pict2cam_installed"] = bsc.is_pict2cam_installed(self.adb_path) if data["adb_connected"] else False
        data["frida_server_running"] = bsc.is_frida_server_running(self.adb_path) if data["adb_connected"] else False
        data["frida_active"] = self.frida_session is not None and self.state.get("frida_active", False)

        return data

    def stop(self):
        """Arrete la session Frida proprement."""
        if self.frida_script:
            try:
                self.frida_script.unload()
            except Exception:
                pass
            self.frida_script = None

        if self.frida_session:
            try:
                self.frida_session.detach()
            except Exception:
                pass
            self.frida_session = None

        with self.state_lock:
            self.state["frida_active"] = False

        self._log("Session Frida arretee")
        return True, "Session arretee"
