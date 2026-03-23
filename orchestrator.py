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
        # Initialiser l'IP dans le fichier config pour le proxy MITM
        ip_config = os.path.join(SCRIPT_DIR, "ip_config.txt")
        with self.state_lock:
            ip = self.state["ip"]
        with open(ip_config, "w") as f:
            f.write(ip)

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

    # Pool de telephones realistes
    DEVICE_PROFILES = [
        {"make": b"samsung",  "model": b"SM-G991B",  "sw": b"G991BXXS7DWBA",   "focal": (6400, 1000), "focal35": 26, "fnum": (180, 100)},  # Galaxy S21
        {"make": b"samsung",  "model": b"SM-S908B",  "sw": b"S908BXXS4CWK1",   "focal": (6400, 1000), "focal35": 23, "fnum": (180, 100)},  # Galaxy S22 Ultra
        {"make": b"samsung",  "model": b"SM-A546B",  "sw": b"A546BXXS7CXA1",   "focal": (5400, 1000), "focal35": 26, "fnum": (180, 100)},  # Galaxy A54
        {"make": b"samsung",  "model": b"SM-G781B",  "sw": b"G781BXXS9FWK2",   "focal": (5400, 1000), "focal35": 26, "fnum": (200, 100)},  # Galaxy S20 FE
        {"make": b"Google",   "model": b"Pixel 7",   "sw": b"TQ3A.230901.001", "focal": (6810, 1000), "focal35": 25, "fnum": (189, 100)},  # Pixel 7
        {"make": b"Google",   "model": b"Pixel 8",   "sw": b"AP2A.240805.005", "focal": (6810, 1000), "focal35": 26, "fnum": (173, 100)},  # Pixel 8
        {"make": b"Xiaomi",   "model": b"2201117TG", "sw": b"V14.0.6.0.TLCMIXM","focal": (5430, 1000), "focal35": 24, "fnum": (179, 100)},  # Xiaomi 12T
        {"make": b"Xiaomi",   "model": b"23049PCD8G","sw": b"V14.0.4.0.TMFMIXM","focal": (5770, 1000), "focal35": 24, "fnum": (179, 100)},  # Redmi Note 12 Pro
        {"make": b"HUAWEI",   "model": b"VOG-L29",   "sw": b"VOG-L29 10.1.0",  "focal": (5580, 1000), "focal35": 27, "fnum": (180, 100)},  # P30 Pro
        {"make": b"OnePlus",  "model": b"CPH2451",   "sw": b"CPH2451_14.0.0.3", "focal": (5590, 1000), "focal35": 25, "fnum": (188, 100)},  # OnePlus Nord CE 3
        {"make": b"Apple",    "model": b"iPhone 14",  "sw": b"17.4",            "focal": (5700, 1000), "focal35": 26, "fnum": (156, 100)},  # iPhone 14
        {"make": b"Apple",    "model": b"iPhone 13",  "sw": b"17.3.1",          "focal": (5100, 1000), "focal35": 26, "fnum": (156, 100)},  # iPhone 13
    ]

    def _inject_camera_metadata(self, image_path):
        """Ajoute les metadonnees camera realistes avec appareil aleatoire."""
        import piexif
        import random

        try:
            exif_dict = piexif.load(image_path)
        except Exception:
            return

        ifd0 = exif_dict.setdefault("0th", {})
        exif_ifd = exif_dict.setdefault("Exif", {})

        # Choisir un appareil au hasard
        device = random.choice(self.DEVICE_PROFILES)
        self._log(f"Appareil: {device['make'].decode()} {device['model'].decode()}")

        # Make/Model/Software
        ifd0[piexif.ImageIFD.Make] = device["make"]
        ifd0[piexif.ImageIFD.Model] = device["model"]
        ifd0[piexif.ImageIFD.Software] = device["sw"]

        # Parametres camera
        exif_ifd[piexif.ExifIFD.FocalLength] = device["focal"]
        exif_ifd[piexif.ExifIFD.FocalLengthIn35mmFilm] = device["focal35"]
        exif_ifd[piexif.ExifIFD.FNumber] = device["fnum"]
        exif_ifd[piexif.ExifIFD.ISOSpeedRatings] = random.choice([50, 80, 100, 125, 160, 200, 250, 320, 400])
        exif_ifd[piexif.ExifIFD.ExposureTime] = random.choice([
            (1, 60), (1, 100), (1, 120), (1, 200), (1, 250), (1, 500), (1, 1000)
        ])
        exif_ifd[piexif.ExifIFD.ExposureProgram] = 2
        exif_ifd[piexif.ExifIFD.MeteringMode] = random.choice([1, 2, 5])  # Average, Center, Pattern
        exif_ifd[piexif.ExifIFD.Flash] = 0
        exif_ifd[piexif.ExifIFD.WhiteBalance] = 0
        exif_ifd[piexif.ExifIFD.ColorSpace] = 1
        exif_ifd[piexif.ExifIFD.SceneCaptureType] = 0
        exif_ifd[piexif.ExifIFD.ExifVersion] = b"0232"

        # SubSecTime realiste
        subsec = str(random.randint(100, 999)).encode()
        for tag in [piexif.ExifIFD.SubSecTime, piexif.ExifIFD.SubSecTimeOriginal, piexif.ExifIFD.SubSecTimeDigitized]:
            exif_ifd[tag] = subsec

        # Dimensions
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

        ifd0[piexif.ImageIFD.YCbCrPositioning] = 1

        try:
            exif_bytes = piexif.dump(exif_dict)
            piexif.insert(exif_bytes, image_path)
        except Exception:
            pass

    def _convert_to_jpeg(self, input_path, filename):
        """Convertit une image non-JPEG en JPEG. Retourne (nouveau_path, nouveau_filename) ou None si deja JPEG."""
        from PIL import Image

        with open(input_path, 'rb') as f:
            header = f.read(8)

        # Deja un JPEG
        if header[:2] == b'\xFF\xD8':
            return None

        self._log(f"Conversion en JPEG: {filename}")
        img = Image.open(input_path)
        if img.mode in ('RGBA', 'P', 'LA'):
            img = img.convert('RGB')

        # Nouveau nom avec .jpg
        base = os.path.splitext(filename)[0]
        new_filename = base + ".jpg"
        new_path = os.path.splitext(input_path)[0] + ".jpg"

        img.save(new_path, "JPEG", quality=95)
        img.close()

        # Supprimer l'original si different
        if new_path != input_path and os.path.exists(input_path):
            os.remove(input_path)

        return new_path, new_filename

    def process_photo(self, input_path, filename):
        """Modifie EXIF + push vers BlueStacks. Retourne (success, message)."""
        os.makedirs(OUTPUT_DIR, exist_ok=True)

        with self.state_lock:
            lat = self.state["lat"]
            lon = self.state["lon"]
            alt = self.state["altitude"]

        # Convertir en JPEG si necessaire (PNG, WebP, etc.)
        try:
            result = self._convert_to_jpeg(input_path, filename)
            if result:
                input_path, filename = result
        except Exception as e:
            self._log(f"Erreur conversion: {e}")
            return False, f"Format image non supporte: {e}"

        # Injecter les metadonnees camera AVANT geo.py
        self._inject_camera_metadata(input_path)

        try:
            modify_geolocation(input_path, lat, lon, altitude=alt)
            self._log(f"EXIF modifie: {filename} ({lat}, {lon})")
        except Exception as e:
            self._log(f"Erreur geo.py: {e}")
            return False, str(e)

        # Re-injecter apres geo.py (il nettoie Software)
        self._inject_camera_metadata(input_path)

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
        """Met a jour l'IP spoofee (ecrit dans ip_config.txt pour le proxy MITM)."""
        with self.state_lock:
            self.state["ip"] = ip

        # Ecrire l'IP dans le fichier que le proxy MITM lit
        ip_config = os.path.join(SCRIPT_DIR, "ip_config.txt")
        with open(ip_config, "w") as f:
            f.write(ip)
        self._log(f"IP mise a jour: {ip}")

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
