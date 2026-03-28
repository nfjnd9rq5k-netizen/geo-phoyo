"""
Orchestrator v3 - Coeur du systeme Geo Photo (mode telephone).
Gere le pipeline photo (EXIF + GPS) et la coordination ADB.
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


class GeoPhotoOrchestrator:
    def __init__(self):
        self.adb_path = None
        self._log_lines = []
        self._log_lock = threading.Lock()
        self.state = {
            "lat": 48.8566,
            "lon": 2.3522,
            "ip": "86.234.12.45",
            "altitude": 35.0,
            "certificall_package": None,
            "last_photo": None,
        }
        self.state_lock = threading.Lock()
        self.current_device = None  # Profil camera persistant par session

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
        # Initialiser les fichiers config pour le proxy MITM
        with self.state_lock:
            ip = self.state["ip"]
            lat = self.state["lat"]
            lon = self.state["lon"]

        ip_config = os.path.join(SCRIPT_DIR, "ip_config.txt")
        with open(ip_config, "w") as f:
            f.write(ip)

        gps_config = os.path.join(SCRIPT_DIR, "gps_config.txt")
        with open(gps_config, "w") as f:
            f.write(f"{lat},{lon}")

        self.adb_path = bsc.find_adb()
        status = {
            "adb_found": self.adb_path is not None,
            "connected": False,
            "certificall_package": None,
            "certificall_running": False,
        }
        if not self.adb_path:
            self._log("ADB non trouve")
            return status

        status["connected"] = bsc.is_connected(self.adb_path)
        if not status["connected"]:
            self._log("Telephone non connecte")
            return status

        pkg = bsc.find_certificall_package(self.adb_path)
        status["certificall_package"] = pkg
        with self.state_lock:
            self.state["certificall_package"] = pkg

        if pkg:
            pid = bsc.get_app_pid(pkg, self.adb_path)
            status["certificall_running"] = pid is not None
            if pid:
                self._log(f"Certificall deja en cours (PID {pid})")

        self._log(f"ADB: {self.adb_path}")
        self._log(f"Telephone: connecte")
        self._log(f"Certificall: {pkg or 'NON TROUVE'}{' (en cours)' if status['certificall_running'] else ''}")

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

        # Forcer profil iPhone (coherent avec le spoof iOS du proxy)
        if self.current_device is None:
            self.current_device = {"make": b"Apple", "model": b"iPhone 15 Pro", "sw": b"26.1", "focal": (5700, 1000), "focal35": 24, "fnum": (178, 100)}
        device = self.current_device
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
        """Modifie EXIF (GPS + camera) et sauvegarde dans output/. Le proxy MITM remplace la photo lors de l'upload."""
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

        # Sauvegarder dans output/ (le proxy MITM lira la derniere photo ici)
        output_path = os.path.join(OUTPUT_DIR, filename)
        shutil.copy2(input_path, output_path)
        self._log(f"Photo prete: {filename} (le proxy la remplacera lors de l'upload)")

        with self.state_lock:
            self.state["last_photo"] = output_path

        return True, output_path

    def launch_certificall(self):
        """(Re)lance Certificall sur le telephone."""
        with self.state_lock:
            package = self.state["certificall_package"]
        if not package:
            package = bsc.find_certificall_package(self.adb_path)
            if not package:
                return False, "Package Certificall non trouve sur le telephone"
            with self.state_lock:
                self.state["certificall_package"] = package

        self._log(f"Arret de {package}...")
        bsc.run_adb(["shell", "am", "force-stop", package], self.adb_path)
        time.sleep(1)

        self._log(f"Lancement {package}...")
        bsc.launch_app(package, self.adb_path)

        self._log("Certificall lance (proxy MITM actif)")
        return True, "Certificall lance"

    def update_location(self, lat, lon):
        """Met a jour GPS (state + gps_config.txt pour le proxy)."""
        with self.state_lock:
            self.state["lat"] = lat
            self.state["lon"] = lon

        # Ecrire dans gps_config.txt pour le proxy MITM
        gps_config = os.path.join(SCRIPT_DIR, "gps_config.txt")
        with open(gps_config, "w") as f:
            f.write(f"{lat},{lon}")

    def update_ip(self, ip):
        """Met a jour l'IP spoofee (ecrit dans ip_config.txt pour le proxy MITM)."""
        with self.state_lock:
            self.state["ip"] = ip

        ip_config = os.path.join(SCRIPT_DIR, "ip_config.txt")
        with open(ip_config, "w") as f:
            f.write(ip)
        self._log(f"IP mise a jour: {ip}")

    def update_device(self, device_name):
        """Met a jour le modele iPhone (ecrit dans device_config.txt pour le proxy MITM)."""
        with self.state_lock:
            self.state["device"] = device_name

        device_config = os.path.join(SCRIPT_DIR, "device_config.txt")
        with open(device_config, "w") as f:
            f.write(device_name)
        self._log(f"Device mis a jour: {device_name}")

    def get_status(self):
        """Retourne le status complet (detecte l'etat reel via ADB)."""
        with self.state_lock:
            data = dict(self.state)

        data["adb_connected"] = bsc.is_connected(self.adb_path)

        if data["adb_connected"]:
            pkg = data.get("certificall_package")
            data["certificall_running"] = False
            if pkg:
                data["certificall_running"] = bsc.get_app_pid(pkg, self.adb_path) is not None
        else:
            data["certificall_running"] = False

        return data

    def stop(self):
        """Arrete Certificall proprement."""
        with self.state_lock:
            package = self.state.get("certificall_package")

        if package:
            bsc.run_adb(["shell", "am", "force-stop", package], self.adb_path)
            self._log(f"{package} arrete")

        self._log("Session arretee")
        return True, "Session arretee"
