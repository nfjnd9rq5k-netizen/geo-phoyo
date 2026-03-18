# Geo Photo v3

Outil de geolocalisation de photos pour Certificall sur BlueStacks.

## Prerequis

- **Windows 10/11**
- **BlueStacks 5** (instance Pie64 / Android 9)
- **Python 3.10+**
- **Java JDK 17** (Eclipse Adoptium recommande)
- **Android Build Tools** (zipalign, apksigner)

## Installation complete (premiere fois)

### 1. Installer BlueStacks 5

Telecharger et installer depuis https://www.bluestacks.com/fr/
- Creer une instance **Pie 64-bit** (Android 9)
- Laisser ADB actif (par defaut)

### 2. Installer Python et dependances

```bash
pip install piexif pytz timezonefinder frida-tools geopy Pillow mitmproxy
```

### 3. Installer Java JDK 17

Telecharger Eclipse Adoptium JDK 17 depuis https://adoptium.net/
Installer dans `C:\Program Files\Eclipse Adoptium\jdk-17.0.18.8-hotspot\`

### 4. Obtenir les Android Build Tools

Il faut `zipalign.exe` et `apksigner.jar` depuis le SDK Android.
Soit via Android Studio, soit en copiant depuis un SDK existant.

Modifier les chemins dans `patch_apk.py` si vos chemins sont differents:
```python
JAVA_HOME = r"C:\Program Files\Eclipse Adoptium\jdk-17.0.18.8-hotspot"
BUILD_TOOLS = r"chemin\vers\android-sdk\build-tools\30.0.3"
```

### 5. Installer pict2cam sur BlueStacks

```bash
# Telecharger depuis GitHub releases
curl -L -o pict2cam.apk "https://github.com/adriangl/pict2cam/releases/download/1.0.70/pict2cam-1.0.70-release.apk"

# Installer via ADB
"C:\Program Files\BlueStacks_nxt\HD-Adb.exe" install pict2cam.apk
```

Puis dans BlueStacks: **Parametres Android > Apps par defaut > Camera > Pict2Cam**

### 6. Preparer l'APK Certificall patche

#### a) Obtenir l'APK original

Telecharger le XAPK complet de Certificall (par ex. depuis apkpure.com ou apkcombo.com).

Extraire les splits du XAPK (c'est un ZIP):
```
app.certificall.apk         <- APK de base
config.arm64_v8a.apk        <- Libs natives ARM64
config.fr.apk               <- Langue francaise
config.mdpi.apk             <- Ressources ecran
```

#### b) Decompiler avec apktool

Telecharger apktool: https://github.com/iBotPeaches/Apktool/releases

```bash
java -jar apktool.jar d -f -o decompiled app.certificall.apk
```

#### c) Appliquer les patches

**Patch 1 — Libs natives ARM64:**
Extraire `libsqlcipher.so` et `libtslocationmanager.so` depuis `config.arm64_v8a.apk` et les copier dans:
- `decompiled/lib/arm64-v8a/`
- `decompiled/lib/x86_64/`

**Patch 2 — isVirtual() toujours false:**
Fichier: `decompiled/smali/com/capacitorjs/plugins/device/Device.smali`

Remplacer la methode `isVirtual()` par:
```smali
.method public isVirtual()Z
    .locals 1
    const/4 v0, 0x0
    return v0
.end method
```

**Patch 3 — isDeveloperModeEnabled() toujours false:**
Fichier: `decompiled/smali/app/certificall/plugins/devoptionschecker/DevOptionsChecker.smali`

Remplacer la methode `isDeveloperModeEnabled()` par:
```smali
.method public isDeveloperModeEnabled(Landroid/content/Context;)Z
    .locals 1
    const/4 v0, 0x0
    return v0
.end method
```

**Patch 4 — Desactiver les checks d'integrite dans le JavaScript:**
Fichier: `decompiled/assets/public/main.XXXXXXX.js` (le nom exact change selon la version)

Chercher et remplacer:

```
isIntegrityError(d){return!(!d||!d.error)&&("errorType"in d.error&&"blockAction"in d.error&&(401===d.status||403===d.status))}
```
Par:
```
isIntegrityError(d){return!1}
```

Chercher et remplacer la fonction standalone `Hs`:
```
function Hs(L){return console.log("isIntegrityError",...),L instanceof X1.yz&&(...)}
```
Par:
```
function Hs(L){return!1}
```

Chercher et remplacer:
```
if(o0.deviceInfos.isVirtual)
```
Par:
```
if(false)
```

Chercher et remplacer:
```
"x-integrity-error":"token_generation_failed"
```
Par:
```
"x-integrity-status":"ok"
```

**Patch 5 — Certificat CA mitmproxy:**
Creer `decompiled/res/xml/network_security_config.xml`:
```xml
<?xml version="1.0" encoding="utf-8"?>
<network-security-config>
    <base-config cleartextTrafficPermitted="true">
        <trust-anchors>
            <certificates src="system" />
            <certificates src="user" />
            <certificates src="@raw/mitmproxy_ca" />
        </trust-anchors>
    </base-config>
</network-security-config>
```

Copier le certificat CA de mitmproxy:
```bash
# Generer le cert (lancer mitmproxy une fois)
mitmdump --listen-port 8888
# Ctrl+C apres quelques secondes
# Le cert est dans: %USERPROFILE%\.mitmproxy\mitmproxy-ca-cert.pem

# Copier dans l'APK
copy %USERPROFILE%\.mitmproxy\mitmproxy-ca-cert.pem decompiled\res\raw\mitmproxy_ca.pem
```

Ajouter dans le `<application>` du `AndroidManifest.xml`:
```
android:networkSecurityConfig="@xml/network_security_config"
```

#### d) Recompiler, aligner, signer

```bash
# Recompiler
java -jar apktool.jar b -o unsigned.apk decompiled

# IMPORTANT: les .so doivent etre non-compresses (ZIP_STORED)
python fix_so.py unsigned.apk fixed.apk

# Aligner (page-align les .so)
zipalign -p -f 4 fixed.apk aligned.apk

# Creer un keystore de debug (une seule fois)
keytool -genkeypair -keystore debug.keystore -storepass android -keypass android -alias androiddebugkey -keyalg RSA -keysize 2048 -validity 10000 -dname "CN=Debug"

# Signer avec apksigner (PAS jarsigner!)
java -jar apksigner.jar sign --ks debug.keystore --ks-pass pass:android --ks-key-alias androiddebugkey --key-pass pass:android --out certificall_patched.apk aligned.apk
```

#### e) Installer l'APK patche

```bash
"C:\Program Files\BlueStacks_nxt\HD-Adb.exe" install certificall_patched.apk
```

### 7. Script de correction des .so

Creer `fix_so.py`:
```python
import zipfile, sys
with zipfile.ZipFile(sys.argv[1], 'r') as zin, zipfile.ZipFile(sys.argv[2], 'w') as zout:
    for item in zin.infolist():
        data = zin.read(item.filename)
        if item.filename.endswith('.so'):
            item.compress_type = zipfile.ZIP_STORED
        zout.writestr(item, data)
```

---

## Utilisation quotidienne

### Demarrage

Double-cliquer sur **`start.bat`**

Cela fait automatiquement:
1. Verifie BlueStacks et les apps
2. Configure le proxy MITM sur BlueStacks (10.0.2.2:8888)
3. Lance le proxy qui intercepte les reponses serveur
4. Lance le dashboard web sur http://127.0.0.1:8420

### Workflow

1. **Carte** — Cliquer pour choisir la localisation GPS
2. **Photo** — Glisser-deposer une photo dans la zone d'upload
   - Les metadonnees EXIF sont modifiees automatiquement (GPS, appareil, date, timezone)
3. **Lancer Certificall** — Cliquer le bouton dans le dashboard
4. **Dans Certificall** — Quand l'app demande une photo, pict2cam s'ouvre
   - Choisir la photo qui a ete uploadee (dans DCIM/Camera)
5. **Photo validee** !

### Arret

Double-cliquer sur **`stop.bat`**
- Arrete le proxy et le dashboard
- Supprime la config proxy de BlueStacks

---

## Architecture

```
start.bat                     <- Point d'entree
  |
  +-- mitmproxy (port 8888)   <- Intercepte les reponses serveur 401/403 -> 200
  |
  +-- dashboard.py (port 8420) <- Interface web (carte + upload + controle)
       |
       +-- geo.py              <- Modification EXIF des photos
       +-- orchestrator.py     <- Coordination ADB / Frida
       +-- bluestacks_controller.py <- Communication ADB avec BlueStacks
       +-- mitm_script.py      <- Script d'interception mitmproxy

BlueStacks (Android 9)
  +-- Certificall (APK patche)
  |     +-- isVirtual() = false
  |     +-- isDeveloperModeEnabled() = false
  |     +-- Play Integrity checks desactives (JS)
  |     +-- CA cert mitmproxy integre
  |
  +-- pict2cam (camera virtuelle)
```

## Comment ca marche

### Le probleme
Certificall utilise **Google Play Integrity API** pour verifier que:
- L'app tourne sur un vrai telephone (pas un emulateur)
- L'APK n'a pas ete modifie (signature originale)
- Le telephone n'est pas roote

Sur BlueStacks, ces checks echouent systematiquement.

### La solution
1. **Patches client** — Desactiver les verifications cote app (isVirtual, devMode, integrite JS)
2. **Proxy MITM** — Intercepter les reponses du serveur au niveau reseau:
   - Quand le serveur renvoie 401/403 (integrite echouee), le proxy transforme la reponse en 200 OK
   - L'app recoit une reponse de succes et accepte la photo
3. **EXIF** — geo.py modifie les metadonnees de la photo pour correspondre a la localisation choisie
4. **pict2cam** — Intercepte les demandes de camera et permet de choisir une photo existante

## Fichiers importants

| Fichier | Role |
|---------|------|
| `start.bat` | Lancement automatique complet |
| `stop.bat` | Arret propre |
| `dashboard.py` | Interface web (carte, upload, controle) |
| `geo.py` | Moteur de modification EXIF |
| `mitm_script.py` | Script d'interception proxy |
| `orchestrator.py` | Coordination generale |
| `bluestacks_controller.py` | Communication ADB |
| `patch_apk.py` | Outil de patching APK |
| `frida_hooks/` | Hooks Frida (anti-detection, SSL, GPS, IP) |

## Depannage

### BlueStacks non connecte
- Verifier que BlueStacks est lance
- Verifier ADB: `"C:\Program Files\BlueStacks_nxt\HD-Adb.exe" devices`

### L'app affiche un ecran blanc
- L'APK patche a un probleme. Reinstaller avec les splits originaux d'abord.
- Verifier que les libs natives (libsqlcipher.so, libtslocationmanager.so) sont presentes dans lib/arm64-v8a/ ET lib/x86_64/

### La photo est rejetee
- Verifier que mitmproxy tourne: `netstat -ano | findstr 8888`
- Verifier le proxy BlueStacks: `HD-Adb.exe shell "settings get global http_proxy"` doit retourner `10.0.2.2:8888`
- Relancer `start.bat`

### Internet ne marche plus dans BlueStacks
- Le proxy est peut-etre mal configure. Lancer `stop.bat` pour le supprimer.
