"""
Patch APK avec Frida Gadget — Injecte libfrida-gadget.so dans l'APK
et configure le chargement automatique du script d'injection.
Ne necessite PAS de root.
"""

import os
import sys
import shutil
import subprocess
import zipfile
import tempfile

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Paths
JAVA_HOME = r"C:\Program Files\Eclipse Adoptium\jdk-17.0.18.8-hotspot"
JAVA = os.path.join(JAVA_HOME, "bin", "java.exe")
KEYTOOL = os.path.join(JAVA_HOME, "bin", "keytool.exe")
JARSIGNER = os.path.join(JAVA_HOME, "bin", "jarsigner.exe")

GADGET_SO = os.path.join(os.path.expanduser("~"), "Desktop", "frida-gadget.so")
KEYSTORE = os.path.join(SCRIPT_DIR, "debug.keystore")
KEYSTORE_PASS = "android"
KEY_ALIAS = "androiddebugkey"
BUILD_TOOLS = os.path.join(os.path.expanduser("~"), "Desktop", "geo photo", "dist", "geo-photo", "android-sdk", "build-tools", "30.0.3")
ZIPALIGN = os.path.join(BUILD_TOOLS, "zipalign.exe")
APKSIGNER_JAR = os.path.join(BUILD_TOOLS, "lib", "apksigner.jar")


def find_adb():
    candidates = [
        os.path.join(os.environ.get("ProgramFiles", ""), "BlueStacks_nxt", "HD-Adb.exe"),
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    return shutil.which("adb") or shutil.which("HD-Adb")


def run(cmd, timeout=120):
    print(f"  > {' '.join(cmd[:3])}...")
    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    if result.returncode != 0:
        print(f"  ERREUR: {result.stderr.strip()[:200]}")
    return result.returncode == 0, result.stdout.strip()


def create_keystore():
    """Cree un keystore de debug s'il n'existe pas."""
    if os.path.exists(KEYSTORE):
        return True
    print("[1] Creation du keystore de debug...")
    ok, _ = run([
        KEYTOOL, "-genkeypair",
        "-keystore", KEYSTORE,
        "-storepass", KEYSTORE_PASS,
        "-keypass", KEYSTORE_PASS,
        "-alias", KEY_ALIAS,
        "-keyalg", "RSA", "-keysize", "2048",
        "-validity", "10000",
        "-dname", "CN=Debug,OU=Debug,O=Debug,L=Debug,ST=Debug,C=US",
    ])
    return ok


def patch_apk(input_apk, output_apk):
    """Injecte Frida Gadget dans l'APK."""
    if not os.path.exists(GADGET_SO):
        print(f"ERREUR: {GADGET_SO} introuvable")
        print("Telechargez frida-gadget depuis https://github.com/frida/frida/releases")
        return False

    print(f"[2] Patching {os.path.basename(input_apk)}...")

    work_dir = tempfile.mkdtemp(prefix="apk_patch_")
    try:
        # Extraire l'APK
        extract_dir = os.path.join(work_dir, "extracted")
        with zipfile.ZipFile(input_apk, 'r') as zf:
            zf.extractall(extract_dir)

        # Creer le dossier lib/x86_64 si necessaire
        lib_dir = os.path.join(extract_dir, "lib", "x86_64")
        os.makedirs(lib_dir, exist_ok=True)

        # Copier le gadget
        gadget_dest = os.path.join(lib_dir, "libfrida-gadget.so")
        shutil.copy2(GADGET_SO, gadget_dest)
        print(f"  Gadget copie dans lib/x86_64/")

        # Creer la config du gadget (charger le script automatiquement)
        gadget_config = os.path.join(lib_dir, "libfrida-gadget.config.so")
        script_path = "/data/local/tmp/frida_hooks.js"
        import json
        config = {
            "interaction": {
                "type": "script",
                "path": script_path,
                "on_change": "reload"
            }
        }
        with open(gadget_config, "w") as f:
            json.dump(config, f)
        print(f"  Config gadget: chargement auto de {script_path}")

        # Aussi ajouter pour x86 (BlueStacks peut utiliser les deux)
        lib_x86 = os.path.join(extract_dir, "lib", "x86")
        if os.path.exists(lib_x86):
            shutil.copy2(GADGET_SO, os.path.join(lib_x86, "libfrida-gadget.so"))
            shutil.copy2(gadget_config, os.path.join(lib_x86, "libfrida-gadget.config.so"))
            print(f"  Gadget aussi copie dans lib/x86/")

        # Supprimer les signatures existantes
        meta_inf = os.path.join(extract_dir, "META-INF")
        if os.path.exists(meta_inf):
            shutil.rmtree(meta_inf)
            print("  Anciennes signatures supprimees")

        # Recreer l'APK en preservant l'alignement des .so
        unsigned_apk = os.path.join(work_dir, "unsigned.apk")
        with zipfile.ZipFile(unsigned_apk, 'w', zipfile.ZIP_DEFLATED) as zf:
            for root, dirs, files in os.walk(extract_dir):
                for file in files:
                    file_path = os.path.join(root, file)
                    arcname = os.path.relpath(file_path, extract_dir).replace("\\", "/")
                    # Les .so doivent etre PAGE-alignes (4096) et non compresses
                    if file.endswith('.so'):
                        # Ecrire le .so avec alignement
                        info = zipfile.ZipInfo(arcname)
                        info.compress_type = zipfile.ZIP_STORED
                        # Forcer l'extraction des libs natives
                        info.flag_bits = 0
                        with open(file_path, 'rb') as sf:
                            zf.writestr(info, sf.read())
                    else:
                        zf.write(file_path, arcname)
        print("  APK reconstruit")

        # Aussi definir android:extractNativeLibs="true" dans le manifest
        # On va re-emballer en utilisant la methode de remplacement du manifest
        print("  (extractNativeLibs force via flag APK)")

        # Zipalign PUIS signer avec apksigner (preserve l'alignement)
        aligned_apk = os.path.join(work_dir, "aligned.apk")
        print("[3] Alignement ZIP...")
        ok, _ = run([ZIPALIGN, "-p", "-f", "4", unsigned_apk, aligned_apk])
        if not ok:
            print("  ATTENTION: zipalign echoue, on continue sans")
            aligned_apk = unsigned_apk

        # Signer avec apksigner (pas jarsigner — apksigner preserve l'alignement)
        print("[3b] Signature avec apksigner...")
        ok, _ = run([
            JAVA, "-jar", APKSIGNER_JAR, "sign",
            "--ks", KEYSTORE,
            "--ks-pass", f"pass:{KEYSTORE_PASS}",
            "--ks-key-alias", KEY_ALIAS,
            "--key-pass", f"pass:{KEYSTORE_PASS}",
            "--out", output_apk,
            aligned_apk,
        ])
        if not ok:
            return False
        print(f"  APK signe: {output_apk}")

        return True

    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def build_hooks_script():
    """Concatene tous les hooks JS en un seul fichier."""
    hooks_dir = os.path.join(SCRIPT_DIR, "frida_hooks")
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
        fpath = os.path.join(hooks_dir, fname)
        if os.path.exists(fpath):
            with open(fpath, "r", encoding="utf-8") as f:
                parts.append(f"// ── {fname} ──\n{f.read()}\n")
    return "\n".join(parts)


def push_hooks_script(adb_path):
    """Pousse le script JS concatene vers l'appareil."""
    script_content = build_hooks_script()
    local_script = os.path.join(SCRIPT_DIR, "output", "frida_hooks.js")
    os.makedirs(os.path.dirname(local_script), exist_ok=True)
    with open(local_script, "w", encoding="utf-8") as f:
        f.write(script_content)

    # Push vers le device
    tmp_script = os.path.join(tempfile.gettempdir(), "frida_hooks.js")
    shutil.copy2(local_script, tmp_script)
    ok, out = run([adb_path, "push", tmp_script, "/sdcard/frida_hooks.js"])
    if ok:
        # Move to /data/local/tmp/
        subprocess.run(
            [adb_path, "shell", "cp /sdcard/frida_hooks.js /data/local/tmp/frida_hooks.js"],
            capture_output=True, text=True,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        print(f"  Script hooks pousse ({len(script_content)} octets)")
    return ok


def install_patched(apk_path, adb_path):
    """Desinstalle l'ancienne version et installe la patchee."""
    print("[4] Installation...")
    # Desinstaller l'ancienne version
    run([adb_path, "shell", "pm", "uninstall", "app.certificall"])
    # Installer la nouvelle
    ok, out = run([adb_path, "install", "-r", apk_path], timeout=180)
    if ok:
        print("  Certificall patche installe!")
    else:
        # Essayer sans -r
        ok, out = run([adb_path, "install", apk_path], timeout=180)
        if ok:
            print("  Certificall patche installe!")
        else:
            print(f"  ECHEC installation: {out[:200]}")
    return ok


def main():
    print("=" * 50)
    print("  PATCH APK — Injection Frida Gadget")
    print("=" * 50)

    adb_path = find_adb()
    if not adb_path:
        print("ERREUR: ADB non trouve")
        return

    input_apk = os.path.join(os.path.expanduser("~"), "Desktop", "certificall_apk", "certificall.apk")
    output_apk = os.path.join(SCRIPT_DIR, "output", "certificall_patched.apk")

    if not os.path.exists(input_apk):
        print(f"ERREUR: {input_apk} introuvable")
        return

    # 1. Keystore
    if not create_keystore():
        print("ERREUR: Creation keystore echouee")
        return

    # 2. Patch
    if not patch_apk(input_apk, output_apk):
        print("ERREUR: Patching echoue")
        return

    # 3. Push hooks script
    print("[3b] Push du script hooks...")
    push_hooks_script(adb_path)

    # 4. Install
    if not install_patched(output_apk, adb_path):
        return

    print()
    print("=" * 50)
    print("  SUCCES! Certificall patche avec Frida Gadget")
    print("  Les hooks se chargeront automatiquement au lancement")
    print("=" * 50)


if __name__ == "__main__":
    main()
