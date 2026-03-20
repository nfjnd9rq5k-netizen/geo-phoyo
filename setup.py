"""
Setup automatique — Geo Photo v3
Telecharge, patche et installe tout automatiquement.

Prerequis:
  - BlueStacks 5 installe et lance (instance Pie64)
  - Python 3.10+
  - Java JDK 17 (Eclipse Adoptium)
"""

import os
import sys
import json
import shutil
import subprocess
import zipfile
import tempfile
import re
import urllib.request

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
WORK_DIR = os.path.join(SCRIPT_DIR, "_build")
OUTPUT_DIR = os.path.join(SCRIPT_DIR, "output")

# ── Chemins configurables ──
# Modifier ces chemins selon votre installation
JAVA_CANDIDATES = [
    os.path.join(os.environ.get("ProgramFiles", ""), "Eclipse Adoptium", "jdk-17.0.18.8-hotspot", "bin"),
    os.path.join(os.environ.get("ProgramFiles", ""), "Eclipse Adoptium", "jdk-17.0.14.7-hotspot", "bin"),
    os.path.join(os.environ.get("ProgramFiles", ""), "Java", "jdk-17", "bin"),
    os.path.join(os.environ.get("ProgramFiles", ""), "Android", "Android Studio", "jbr", "bin"),
]

ADB_CANDIDATES = [
    os.path.join(os.environ.get("ProgramFiles", ""), "BlueStacks_nxt", "HD-Adb.exe"),
    os.path.join(os.environ.get("ProgramFiles(x86)", ""), "BlueStacks_nxt", "HD-Adb.exe"),
]

# URLs
APKTOOL_URL = "https://github.com/iBotPeaches/Apktool/releases/download/v2.9.3/apktool_2.9.3.jar"
PICT2CAM_URL = "https://github.com/adriangl/pict2cam/releases/download/1.0.70/pict2cam-1.0.70-release.apk"
CERTIFICALL_XAPK_URL = "https://d.apkpure.net/b/XAPK/app.certificall?version=latest"


def find_java():
    for base in JAVA_CANDIDATES:
        java = os.path.join(base, "java.exe")
        if os.path.exists(java):
            return base
    # Chercher dans PATH
    java = shutil.which("java")
    if java:
        return os.path.dirname(java)
    return None


def find_adb():
    for path in ADB_CANDIDATES:
        if os.path.exists(path):
            return path
    return shutil.which("adb") or shutil.which("HD-Adb")


def find_build_tools():
    """Cherche zipalign et apksigner dans les SDK Android installes."""
    search_paths = [
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Android", "Sdk", "build-tools"),
        os.path.join(os.environ.get("ProgramFiles", ""), "Android", "Android Studio", "sdk", "build-tools"),
        os.path.join(os.path.expanduser("~"), "Desktop", "geo photo", "dist", "geo-photo", "android-sdk", "build-tools"),
    ]
    for base in search_paths:
        if os.path.exists(base):
            versions = sorted(os.listdir(base), reverse=True)
            for v in versions:
                zipalign = os.path.join(base, v, "zipalign.exe")
                apksigner = os.path.join(base, v, "lib", "apksigner.jar")
                if os.path.exists(zipalign) and os.path.exists(apksigner):
                    return os.path.join(base, v)
    return None


def download(url, dest, desc=""):
    print(f"  Telechargement {desc or os.path.basename(dest)}...")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=120) as r, open(dest, 'wb') as f:
            total = int(r.headers.get('content-length', 0))
            downloaded = 0
            while True:
                chunk = r.read(8192)
                if not chunk:
                    break
                f.write(chunk)
                downloaded += len(chunk)
                if total:
                    pct = int(downloaded * 100 / total)
                    print(f"\r  {pct}%", end="", flush=True)
            print()
        return True
    except Exception as e:
        print(f"  ERREUR: {e}")
        return False


def run(cmd, timeout=120):
    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    if result.returncode != 0 and result.stderr:
        print(f"  ERREUR: {result.stderr[:200]}")
    return result.returncode == 0, result.stdout.strip()


def adb_install(adb, apk_path, timeout=180, retries=3):
    """Install APK via ADB with retries and server restart on failure."""
    import time
    for attempt in range(retries):
        if attempt > 0:
            print(f"  Tentative {attempt + 1}/{retries}...")
            # Restart ADB server to fix broken connections
            run([adb, "kill-server"], timeout=10)
            time.sleep(2)
            run([adb, "start-server"], timeout=10)
            time.sleep(3)
            # Wait for device to reconnect
            for _ in range(10):
                ok, out = run([adb, "devices"], timeout=10)
                if ok and "device" in out and "emulator" in out:
                    break
                time.sleep(1)
        ok, out = run([adb, "install", apk_path], timeout=timeout)
        if ok:
            return True, out
        if "closed" not in (out or "") and "closed" not in str(ok):
            # Real error, not a connection issue
            return False, out
    return False, out


def main():
    print("=" * 55)
    print("  GEO PHOTO v3 — Setup automatique")
    print("=" * 55)
    print()

    os.makedirs(WORK_DIR, exist_ok=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # ── 1. Verifier les prerequis ──
    print("[1/10] Verification des prerequis...")

    java_bin = find_java()
    if not java_bin:
        print("  ERREUR: Java JDK 17 non trouve!")
        print("  Installez: https://adoptium.net/")
        return False
    java = os.path.join(java_bin, "java.exe")
    keytool = os.path.join(java_bin, "keytool.exe")
    print(f"  Java: {java_bin}")

    adb = find_adb()
    if not adb:
        print("  ERREUR: ADB/BlueStacks non trouve!")
        return False
    print(f"  ADB: {adb}")

    build_tools = find_build_tools()
    if not build_tools:
        print("  ERREUR: Android Build Tools non trouves!")
        print("  Installez Android Studio ou le SDK Android.")
        return False
    zipalign = os.path.join(build_tools, "zipalign.exe")
    apksigner_jar = os.path.join(build_tools, "lib", "apksigner.jar")
    print(f"  Build Tools: {build_tools}")

    # ── 2. Dependances Python ──
    print("\n[2/10] Installation des dependances Python...")
    subprocess.run([sys.executable, "-m", "pip", "install", "-q",
                    "piexif", "pytz", "timezonefinder", "geopy", "Pillow", "mitmproxy"],
                   capture_output=True)
    print("  OK")

    # ── 3. Telecharger apktool ──
    apktool = os.path.join(WORK_DIR, "apktool.jar")
    if not os.path.exists(apktool):
        print("\n[3/10] Telechargement apktool...")
        if not download(APKTOOL_URL, apktool, "apktool"):
            return False
    else:
        print("\n[3/10] apktool deja present")

    # ── 4. Telecharger Certificall XAPK ──
    xapk_path = os.path.join(WORK_DIR, "certificall.xapk")
    if not os.path.exists(xapk_path):
        print("\n[4/10] Telechargement Certificall XAPK...")
        if not download(CERTIFICALL_XAPK_URL, xapk_path, "Certificall XAPK"):
            print("  Telechargement auto echoue.")
            print("  Telechargez manuellement depuis apkpure.com ou apkcombo.com")
            print(f"  et placez le fichier dans: {xapk_path}")
            return False
    else:
        print("\n[4/10] XAPK deja present")

    # ── 5. Extraire et decompiler ──
    decompiled = os.path.join(WORK_DIR, "decompiled")
    if not os.path.exists(decompiled):
        print("\n[5/10] Extraction et decompilation...")

        # Extraire les APK du XAPK
        xapk = zipfile.ZipFile(xapk_path)
        splits_dir = os.path.join(WORK_DIR, "splits")
        os.makedirs(splits_dir, exist_ok=True)

        base_apk = None
        arm64_apk = None
        for name in xapk.namelist():
            if name.endswith('.apk'):
                data = xapk.read(name)
                out_name = name
                out_path = os.path.join(splits_dir, out_name)
                with open(out_path, 'wb') as f:
                    f.write(data)
                if 'certificall' in name.lower() and 'config' not in name.lower():
                    base_apk = out_path
                if 'arm64' in name.lower():
                    arm64_apk = out_path

        if not base_apk:
            print("  ERREUR: APK de base non trouve dans le XAPK")
            return False

        # Decompiler
        ok, _ = run([java, "-jar", apktool, "d", "-f", "-o", decompiled, base_apk], timeout=300)
        if not ok:
            print("  ERREUR: Decompilation echouee")
            return False

        # Extraire les libs natives ARM64
        if arm64_apk:
            arm64_zip = zipfile.ZipFile(arm64_apk)
            for name in arm64_zip.namelist():
                if name.endswith('.so'):
                    data = arm64_zip.read(name)
                    fname = os.path.basename(name)
                    # Copier dans arm64-v8a ET x86_64
                    for arch in ["arm64-v8a", "x86_64"]:
                        dest_dir = os.path.join(decompiled, "lib", arch)
                        os.makedirs(dest_dir, exist_ok=True)
                        with open(os.path.join(dest_dir, fname), 'wb') as f:
                            f.write(data)
            print(f"  Libs natives extraites")

        print("  Decompilation OK")
    else:
        print("\n[5/10] Decompilation deja faite")

    # ── 6. Appliquer les patches ──
    print("\n[6/10] Application des patches...")
    patches_applied = 0

    # Patch smali: isVirtual() -> false
    device_smali = os.path.join(decompiled, "smali", "com", "capacitorjs", "plugins", "device", "Device.smali")
    if os.path.exists(device_smali):
        with open(device_smali, 'r') as f:
            content = f.read()
        old = '.method public isVirtual()Z\n    .locals 2'
        if old in content:
            # Find and replace the entire method
            pattern = r'\.method public isVirtual\(\)Z.*?\.end method'
            replacement = '.method public isVirtual()Z\n    .locals 1\n    const/4 v0, 0x0\n    return v0\n.end method'
            content = re.sub(pattern, replacement, content, flags=re.DOTALL)
            with open(device_smali, 'w') as f:
                f.write(content)
            patches_applied += 1
            print("  Patch: isVirtual() -> false")

    # Patch smali: isDeveloperModeEnabled() -> false
    devcheck_smali = os.path.join(decompiled, "smali", "app", "certificall", "plugins",
                                   "devoptionschecker", "DevOptionsChecker.smali")
    if os.path.exists(devcheck_smali):
        with open(devcheck_smali, 'r') as f:
            content = f.read()
        pattern = r'\.method public isDeveloperModeEnabled\(Landroid/content/Context;\)Z.*?\.end method'
        replacement = ('.method public isDeveloperModeEnabled(Landroid/content/Context;)Z\n'
                      '    .locals 1\n    const/4 v0, 0x0\n    return v0\n.end method')
        new_content = re.sub(pattern, replacement, content, flags=re.DOTALL)
        if new_content != content:
            with open(devcheck_smali, 'w') as f:
                f.write(new_content)
            patches_applied += 1
            print("  Patch: isDeveloperModeEnabled() -> false")

    # Patch JS: integrity checks
    js_dir = os.path.join(decompiled, "assets", "public")
    main_js = None
    for f in os.listdir(js_dir):
        if f.startswith("main.") and f.endswith(".js") and not f.endswith(".map"):
            main_js = os.path.join(js_dir, f)
            break

    if main_js:
        with open(main_js, 'r', encoding='utf-8', errors='ignore') as f:
            js = f.read()

        # Patch: isIntegrityError -> false
        old = 'isIntegrityError(d){return!(!d||!d.error)&&("errorType"in d.error&&"blockAction"in d.error&&(401===d.status||403===d.status))}'
        if old in js:
            js = js.replace(old, 'isIntegrityError(d){return!1}')
            patches_applied += 1
            print("  Patch JS: isIntegrityError -> false")

        # Patch: standalone Hs() -> false
        hs_pattern = re.compile(r'function Hs\(L\)\{return console\.log\("isIntegrityError"[^}]+\}')
        if hs_pattern.search(js):
            js = hs_pattern.sub('function Hs(L){return!1}', js)
            patches_applied += 1
            print("  Patch JS: Hs() -> false")

        # Patch: checkVirtualDevice
        if 'if(o0.deviceInfos.isVirtual)' in js:
            js = js.replace('if(o0.deviceInfos.isVirtual)', 'if(false)')
            patches_applied += 1
            print("  Patch JS: checkVirtualDevice -> disabled")

        # Patch: token_generation_failed
        if '"x-integrity-error":"token_generation_failed"' in js:
            js = js.replace('"x-integrity-error":"token_generation_failed"',
                           '"x-integrity-status":"ok"')
            patches_applied += 1
            print("  Patch JS: token_generation_failed -> ok")

        with open(main_js, 'w', encoding='utf-8') as f:
            f.write(js)

    # Patch: network_security_config.xml (pour le proxy MITM)
    print("\n[7/10] Configuration reseau + certificat CA...")

    # Generer le cert mitmproxy si necessaire
    mitmdump = shutil.which("mitmdump")
    if not mitmdump:
        mitmdump = os.path.join(os.environ.get("LOCALAPPDATA", ""),
                                "Python", "pythoncore-3.14-64", "Scripts", "mitmdump.exe")
    mitmproxy_cert = os.path.join(os.path.expanduser("~"), ".mitmproxy", "mitmproxy-ca-cert.pem")
    if not os.path.exists(mitmproxy_cert):
        print("  Generation du certificat mitmproxy...")
        try:
            proc = subprocess.Popen([mitmdump, "--listen-port", "18888"],
                                     capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
            import time
            time.sleep(3)
            proc.terminate()
        except Exception:
            pass

    # Copier le cert dans l'APK
    res_raw = os.path.join(decompiled, "res", "raw")
    res_xml = os.path.join(decompiled, "res", "xml")
    os.makedirs(res_raw, exist_ok=True)
    os.makedirs(res_xml, exist_ok=True)

    if os.path.exists(mitmproxy_cert):
        shutil.copy2(mitmproxy_cert, os.path.join(res_raw, "mitmproxy_ca.pem"))
        print("  Certificat CA copie")

    # Creer network_security_config.xml
    nsc = """<?xml version="1.0" encoding="utf-8"?>
<network-security-config>
    <base-config cleartextTrafficPermitted="true">
        <trust-anchors>
            <certificates src="system" />
            <certificates src="user" />
            <certificates src="@raw/mitmproxy_ca" />
        </trust-anchors>
    </base-config>
</network-security-config>"""
    with open(os.path.join(res_xml, "network_security_config.xml"), 'w') as f:
        f.write(nsc)

    # Ajouter networkSecurityConfig au manifest
    manifest = os.path.join(decompiled, "AndroidManifest.xml")
    with open(manifest, 'r') as f:
        manifest_content = f.read()
    if 'networkSecurityConfig' not in manifest_content:
        manifest_content = manifest_content.replace(
            'android:usesCleartextTraffic="true"',
            'android:usesCleartextTraffic="true" android:networkSecurityConfig="@xml/network_security_config"'
        )
        with open(manifest, 'w') as f:
            f.write(manifest_content)
        print("  Manifest modifie")

    print(f"  Total patches: {patches_applied}")

    # ── 8. Rebuild APK ──
    print("\n[8/10] Reconstruction de l'APK...")

    unsigned = os.path.join(WORK_DIR, "unsigned.apk")
    fixed = os.path.join(WORK_DIR, "fixed.apk")
    aligned = os.path.join(WORK_DIR, "aligned.apk")
    output = os.path.join(OUTPUT_DIR, "certificall_patched.apk")
    keystore = os.path.join(SCRIPT_DIR, "debug.keystore")

    # Build
    ok, _ = run([java, "-jar", apktool, "b", "-o", unsigned, decompiled], timeout=300)
    if not ok:
        print("  ERREUR: Build echoue")
        return False
    print("  Build OK")

    # Fix .so compression
    with zipfile.ZipFile(unsigned, 'r') as zin, zipfile.ZipFile(fixed, 'w') as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename.endswith('.so'):
                item.compress_type = zipfile.ZIP_STORED
            zout.writestr(item, data)
    print("  Fix .so OK")

    # Zipalign
    run([zipalign, "-p", "-f", "4", fixed, aligned])
    print("  Zipalign OK")

    # Keystore
    if not os.path.exists(keystore):
        run([keytool, "-genkeypair", "-keystore", keystore,
             "-storepass", "android", "-keypass", "android",
             "-alias", "androiddebugkey", "-keyalg", "RSA", "-keysize", "2048",
             "-validity", "10000", "-dname", "CN=Debug,OU=Debug,O=Debug,L=Debug,ST=Debug,C=US"])
        print("  Keystore cree")

    # Sign
    run([java, "-jar", apksigner_jar, "sign",
         "--ks", keystore, "--ks-pass", "pass:android",
         "--ks-key-alias", "androiddebugkey", "--key-pass", "pass:android",
         "--out", output, aligned])
    print(f"  APK signe: {output}")

    # ── 9. Installer sur BlueStacks ──
    print("\n[9/10] Installation sur BlueStacks...")

    # Restart ADB server pour eviter les "error: closed"
    import time
    print("  Redemarrage ADB...")
    run([adb, "kill-server"], timeout=10)
    time.sleep(2)
    run([adb, "start-server"], timeout=10)
    time.sleep(3)

    # Verifier connexion
    ok, out = run([adb, "devices"])
    if "device" not in out:
        print("  ERREUR: BlueStacks non connecte!")
        print("  Lancez BlueStacks et reessayez.")
        return False
    print("  BlueStacks connecte")

    # Installer pict2cam
    ok, out = run([adb, "shell", "pm", "list", "packages", "com.adriangl.pict2cam"])
    if "pict2cam" not in (out or ""):
        pict2cam_apk = os.path.join(WORK_DIR, "pict2cam.apk")
        if not os.path.exists(pict2cam_apk):
            download(PICT2CAM_URL, pict2cam_apk, "pict2cam")
        ok, _ = adb_install(adb, pict2cam_apk, timeout=60)
        if ok:
            print("  pict2cam installe")
        else:
            print("  ERREUR: pict2cam install echoue, continuons quand meme...")
        print("  >>> IMPORTANT: Allez dans Parametres Android > Apps par defaut > Camera > Pict2Cam")
    else:
        print("  pict2cam deja installe")

    # Desinstaller ancien Certificall
    run([adb, "shell", "pm", "uninstall", "app.certificall"])

    # Installer le patche
    ok, out = adb_install(adb, output, timeout=180)
    if ok:
        print("  Certificall patche installe!")
    else:
        print(f"  ERREUR installation: {out[:200]}")
        return False

    # ── 10. Termine ──
    print("\n[10/10] Configuration finale...")
    run([adb, "shell", "settings put secure mock_location 0"])
    print("  mock_location: OFF")

    print()
    print("=" * 55)
    print("  SETUP TERMINE !")
    print()
    print("  Pour utiliser:")
    print("    1. Lancez start.bat")
    print("    2. Dashboard: http://127.0.0.1:8420")
    print("    3. Cliquez la carte, uploadez une photo")
    print("    4. Dans Certificall: photo via pict2cam")
    print()
    print("  N'oubliez pas:")
    print("    - Definir pict2cam comme camera par defaut")
    print("      (Parametres > Apps > Apps par defaut > Camera)")
    print("=" * 55)
    return True


if __name__ == "__main__":
    success = main()
    if not success:
        print("\nSetup echoue. Corrigez les erreurs ci-dessus et relancez.")
    input("\nAppuyez sur Entree pour fermer...")
