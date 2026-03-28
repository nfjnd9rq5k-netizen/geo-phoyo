"""
Push Frida hooks vers l'appareil.
Concatene les fichiers JS et pousse vers /data/local/tmp/frida_hooks.js.
Utilise par start_ldplayer.bat avant le lancement de Certificall.
"""

import os
import sys
import shutil
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bluestacks_controller as bsc

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
HOOKS_DIR = os.path.join(SCRIPT_DIR, "frida_hooks")
OUTPUT_DIR = os.path.join(SCRIPT_DIR, "output")


def build_frida_script():
    """Concatene les fichiers JS hooks en un seul script."""
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
            print(f"  ATTENTION: {fname} introuvable")
            continue
        with open(fpath, "r", encoding="utf-8") as f:
            content = f.read()
        parts.append(f"// -- {fname} --\n{content}\n")

    return "\n".join(parts)


def push_hooks():
    """Build et pousse le script Frida hooks vers l'appareil."""
    adb_path = bsc.find_adb()
    if not adb_path:
        print("  ERREUR: ADB non trouve")
        return False

    if not bsc.is_connected(adb_path):
        print("  ERREUR: Appareil non connecte")
        return False

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Build le script
    script_content = build_frida_script()
    local_script = os.path.join(OUTPUT_DIR, "frida_hooks.js")
    with open(local_script, "w", encoding="utf-8") as f:
        f.write(script_content)

    # Push via sdcard puis copie (evite problemes de path)
    tmp_script = os.path.join(tempfile.gettempdir(), "frida_hooks.js")
    shutil.copy2(local_script, tmp_script)

    ok, out = bsc.run_adb(["push", tmp_script, "/sdcard/frida_hooks.js"], adb_path)
    if not ok:
        print(f"  ERREUR push: {out}")
        return False

    bsc.run_adb(["shell", "cp /sdcard/frida_hooks.js /data/local/tmp/frida_hooks.js"], adb_path)
    bsc.run_adb(["shell", "chmod 644 /data/local/tmp/frida_hooks.js"], adb_path)
    bsc.run_adb(["shell", "rm /sdcard/frida_hooks.js"], adb_path)

    try:
        os.remove(tmp_script)
    except OSError:
        pass

    print(f"  Frida hooks deployes ({len(script_content)} octets)")
    return True


if __name__ == "__main__":
    success = push_hooks()
    sys.exit(0 if success else 1)
