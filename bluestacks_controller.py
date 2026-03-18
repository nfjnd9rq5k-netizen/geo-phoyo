"""
BlueStacks Controller v3 - Controle BlueStacks via ADB.
Gere GPS, photos, proxy, connexion, et frida-server.
"""

import subprocess
import os
import shutil
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def find_adb():
    """Trouve le chemin ADB (BlueStacks ou standard)."""
    candidates = [
        os.path.join(os.environ.get("ProgramFiles", ""), "BlueStacks_nxt", "HD-Adb.exe"),
        os.path.join(os.environ.get("ProgramFiles(x86)", ""), "BlueStacks_nxt", "HD-Adb.exe"),
        os.path.join(os.environ.get("ProgramFiles", ""), "Genymotion", "tools", "adb.exe"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Android", "Sdk", "platform-tools", "adb.exe"),
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return shutil.which("adb") or shutil.which("HD-Adb")


def run_adb(args, adb_path=None, timeout=30):
    """Execute une commande ADB et retourne (success, output)."""
    if adb_path is None:
        adb_path = find_adb()
    if adb_path is None:
        return False, "ADB non trouve"
    cmd = [adb_path] + args
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        output = result.stdout.strip()
        if result.returncode != 0:
            output = result.stderr.strip() or output
        return result.returncode == 0, output
    except subprocess.TimeoutExpired:
        return False, "Timeout"
    except FileNotFoundError:
        return False, f"ADB introuvable: {adb_path}"
    except Exception as e:
        return False, str(e)


def is_connected(adb_path=None):
    """Verifie si un appareil est connecte via ADB."""
    success, output = run_adb(["devices"], adb_path)
    if not success:
        return False
    for line in output.strip().split("\n")[1:]:
        if "\tdevice" in line:
            return True
    return False


def connect_bluestacks(adb_path=None, port=5555):
    """Tente de se connecter a BlueStacks via ADB TCP."""
    run_adb(["connect", f"127.0.0.1:{port}"], adb_path)
    return is_connected(adb_path)


def get_device_info(adb_path=None):
    """Retourne des infos sur l'appareil connecte."""
    info = {}
    for prop in ["ro.product.model", "ro.product.brand", "ro.build.version.release"]:
        success, output = run_adb(["shell", "getprop", prop], adb_path)
        if success:
            info[prop] = output
    return info


def set_gps_via_broadcast(lat, lon, adb_path=None):
    """Envoie les coordonnees GPS via broadcast ADB."""
    success, output = run_adb([
        "shell", "am", "broadcast",
        "-a", "com.geophoto.SET_LOCATION",
        "--ef", "lat", str(lat),
        "--ef", "lng", str(lon),
    ], adb_path)
    if success:
        return True, "GPS mis a jour via broadcast"
    return True, f"GPS broadcast envoye: {lat}, {lon}"


def set_gps_via_geo_fix(lat, lon, adb_path=None):
    """Tente geo fix via la console emulateur, fallback au broadcast."""
    success, output = run_adb(["emu", "geo", "fix", str(lon), str(lat)], adb_path)
    if success and "OK" in output:
        return True, "GPS mis a jour via geo fix"
    return set_gps_via_broadcast(lat, lon, adb_path)


def push_photo(local_path, adb_path=None):
    """Pousse une photo vers /sdcard/DCIM/Camera/ et lance le media scanner."""
    filename = os.path.basename(local_path)
    remote_path = f"/sdcard/DCIM/Camera/{filename}"
    success, output = run_adb(["push", local_path, remote_path], adb_path)
    if not success:
        return False, f"Echec push: {output}"
    run_adb([
        "shell", "am", "broadcast",
        "-a", "android.intent.action.MEDIA_SCANNER_SCAN_FILE",
        "-d", f"file://{remote_path}",
    ], adb_path)
    return True, f"Photo poussee: {remote_path}"


def set_proxy(ip, port, adb_path=None):
    """Configure le proxy HTTP global."""
    proxy_str = f"{ip}:{port}"
    success, output = run_adb([
        "shell", "settings", "put", "global", "http_proxy", proxy_str,
    ], adb_path)
    return success, f"Proxy configure: {proxy_str}" if success else f"Echec: {output}"


def clear_proxy(adb_path=None):
    """Supprime la configuration proxy."""
    run_adb(["shell", "settings", "put", "global", "http_proxy", ":0"], adb_path)
    return True, "Proxy supprime"


def install_apk(apk_path, adb_path=None):
    """Installe un APK sur l'appareil."""
    return run_adb(["install", "-r", apk_path], adb_path, timeout=120)


# ── Frida server management ──

def is_frida_server_running(adb_path=None):
    """Verifie si frida-server tourne sur l'appareil."""
    success, output = run_adb(["shell", "pidof", "frida-server"], adb_path)
    return success and output.strip() != ""


def ensure_frida_server(adb_path=None):
    """Push + demarre frida-server sur BlueStacks. Retourne (success, message)."""
    if is_frida_server_running(adb_path):
        return True, "frida-server deja en cours"

    # Verifier si le binaire est present sur l'appareil
    success, _ = run_adb(["shell", "ls /data/local/tmp/frida-server"], adb_path)
    if not success:
        # Chercher le binaire local
        local_frida = os.path.join(SCRIPT_DIR, "frida-server-x86_64")
        if not os.path.exists(local_frida):
            return False, "frida-server-x86_64 introuvable dans le dossier du projet"
        # Push via /sdcard/ (contourne les problemes de permission)
        # D'abord copier le fichier dans un chemin sans espaces
        import tempfile
        tmp_path = os.path.join(tempfile.gettempdir(), "frida-server")
        import shutil as _shutil
        _shutil.copy2(local_frida, tmp_path)
        ok, out = run_adb(["push", tmp_path, "/sdcard/frida-server"], adb_path, timeout=180)
        if not ok:
            return False, f"Echec push frida-server: {out}"
        # Deplacer de /sdcard/ vers /data/local/tmp/
        run_adb(["shell", "cp /sdcard/frida-server /data/local/tmp/frida-server"], adb_path, timeout=60)
        run_adb(["shell", "rm /sdcard/frida-server"], adb_path)
        try:
            os.remove(tmp_path)
        except OSError:
            pass

    # Rendre executable
    run_adb(["shell", "chmod 755 /data/local/tmp/frida-server"], adb_path)

    # Demarrer frida-server (shell user suffit sur BlueStacks)
    run_adb(["shell", "nohup /data/local/tmp/frida-server -D > /dev/null 2>&1 &"], adb_path, timeout=5)
    time.sleep(3)

    if is_frida_server_running(adb_path):
        return True, "frida-server demarre"

    return False, "Impossible de demarrer frida-server"


def kill_frida_server(adb_path=None):
    """Arrete frida-server."""
    run_adb(["shell", "su -c 'killall frida-server'"], adb_path)
    run_adb(["shell", "killall frida-server"], adb_path)
    return True, "frida-server arrete"


# ── App management ──

def find_certificall_package(adb_path=None):
    """Recherche le package Certificall."""
    success, output = run_adb(["shell", "pm", "list", "packages"], adb_path)
    if not success:
        return None
    for line in output.split("\n"):
        pkg = line.replace("package:", "").strip()
        if "certificall" in pkg.lower() or "certif" in pkg.lower():
            return pkg
    return None


def is_pict2cam_installed(adb_path=None):
    """Verifie si pict2cam est installe."""
    success, output = run_adb(["shell", "pm", "list", "packages", "com.adriangl.pict2cam"], adb_path)
    return success and "pict2cam" in output


def launch_app(package, adb_path=None):
    """Force-stop puis lance une app via monkey."""
    run_adb(["shell", "am", "force-stop", package], adb_path)
    time.sleep(0.5)
    success, output = run_adb([
        "shell", "monkey", "-p", package,
        "-c", "android.intent.category.LAUNCHER", "1",
    ], adb_path)
    return success, output


def get_app_pid(package, adb_path=None):
    """Retourne le PID d'une app en cours d'execution."""
    success, output = run_adb(["shell", "pidof", package], adb_path)
    if success and output.strip():
        try:
            return int(output.strip().split()[0])
        except ValueError:
            pass
    return None


if __name__ == "__main__":
    adb = find_adb()
    print(f"ADB: {adb}")
    print(f"Connecte: {is_connected(adb)}")
    if is_connected(adb):
        info = get_device_info(adb)
        print(f"Appareil: {info}")
        print(f"pict2cam: {'installe' if is_pict2cam_installed(adb) else 'non installe'}")
        print(f"frida-server: {'actif' if is_frida_server_running(adb) else 'inactif'}")
        pkg = find_certificall_package(adb)
        print(f"Certificall: {pkg or 'non trouve'}")
