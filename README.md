# Geo Photo v3

Outil de geolocalisation de photos pour Certificall sur BlueStacks.

---

## Installation rapide (nouvel ordinateur)

### 1. Installer les logiciels

| Logiciel | Lien | Notes |
|----------|------|-------|
| **BlueStacks 5** | https://www.bluestacks.com/fr/ | Instance Pie 64-bit (Android 9) |
| **Python 3.10+** | https://www.python.org/downloads/ | Cocher "Add to PATH" |
| **Java JDK 17** | https://adoptium.net/ | Eclipse Adoptium recommande |

### 2. Cloner le repo

```bash
git clone https://github.com/nfjnd9rq5k-netizen/geo-phoyo.git
cd geo-phoyo
```

### 3. Avoir les Android Build Tools

Il faut `zipalign.exe` et `apksigner.jar`. Deux options:
- **Option A**: Installer Android Studio (les build-tools sont inclus)
- **Option B**: Telecharger le SDK command-line tools depuis https://developer.android.com/studio#command-tools

Le script `setup.py` cherche automatiquement dans les emplacements standards.

### 4. Lancer le setup automatique

```bash
python setup.py
```

Ce script fait TOUT automatiquement:
1. Verifie Java, Python, ADB, Build Tools
2. Installe les dependances Python (piexif, mitmproxy, etc.)
3. Telecharge apktool
4. Telecharge le XAPK de Certificall
5. Decompile l'APK
6. Applique tous les patches (isVirtual, devMode, integrity, SSL)
7. Ajoute le certificat CA mitmproxy
8. Recompile, aligne et signe l'APK
9. Installe pict2cam et Certificall patche sur BlueStacks

### 5. Configurer pict2cam comme camera par defaut

Dans BlueStacks:
- **Parametres Android** > **Apps et notifications** > **Apps par defaut** > **Camera** > **Pict2Cam**

### 6. C'est pret !

```bash
start.bat
```

---

## Utilisation

### Demarrage

Double-cliquer sur **`start.bat`**

Il fait automatiquement:
1. Lance le proxy MITM (intercepte les reponses serveur)
2. Configure le proxy sur BlueStacks
3. Lance Certificall
4. Lance le dashboard web

### Dashboard — http://127.0.0.1:8420

- **Carte** — Cliquer pour choisir la position GPS
- **Champ IP** — Taper une IP (appliquee immediatement au proxy)
- **Zone photo** — Glisser-deposer une photo
  - EXIF modifie auto: GPS, appareil (aleatoire parmi 12 modeles), date, timezone
- **Bouton "Lancer Certificall"** — Lance l'app avec proxy actif

### Workflow

1. Choisir la position sur la carte
2. Changer l'IP si besoin (ex: `82.67.33.100` pour Orange)
3. Glisser une photo
4. Dans Certificall: prendre photo > pict2cam > choisir la photo uploadee
5. Photo validee !

### Arret

Double-cliquer sur **`stop.bat`** (supprime le proxy, arrete tout)

---

## Comment ca marche

### Le probleme
Certificall verifie:
- **Google Play Integrity** — Le serveur valide un token cryptographique
- **isVirtual** — Detection d'emulateur via Build.FINGERPRINT/PRODUCT
- **Developer Mode** — Verifie si le mode dev est active
- **Signature APK** — Play Integrity echoue si l'APK est re-signe

### La solution

```
[Photo] --> [geo.py modifie EXIF] --> [Push vers BlueStacks]
                                           |
[Certificall] --> [Requete API + token] --> [Serveur]
                                                |
                                           [401/403 rejet]
                                                |
                                      [Proxy MITM intercepte]
                                                |
                                        [Transforme en 200 OK]
                                                |
                                      [App recoit "succes"]
```

1. **Patches APK** — isVirtual=false, devMode=false, integrity checks desactives
2. **Proxy MITM** — Intercepte les reponses 401/403 du serveur et les transforme en 200 OK
3. **geo.py** — Modifie les metadonnees EXIF (GPS, appareil, date, timezone)
4. **pict2cam** — Intercepte les demandes de camera pour choisir une photo existante

---

## Fichiers

| Fichier | Role |
|---------|------|
| `setup.py` | Installation automatique complete |
| `start.bat` | Demarrage (proxy + dashboard + Certificall) |
| `stop.bat` | Arret propre |
| `dashboard.py` | Interface web (carte, upload, controle) |
| `orchestrator.py` | Coordination + modification EXIF |
| `geo.py` | Moteur EXIF (GPS, dates, timezone, DOP) |
| `mitm_script.py` | Script proxy (intercepte 401/403) |
| `bluestacks_controller.py` | Communication ADB avec BlueStacks |
| `fix_so.py` | Corrige la compression des .so dans les APK |
| `patch_apk.py` | Outil de patching APK (ancien, remplace par setup.py) |
| `frida_hooks/` | Hooks Frida (reference, non utilises activement) |

---

## Notes importantes

- **Erreurs reseau** dans BlueStacks: normal, c'est le proxy qui intercepte le SSL des autres apps. Ca n'affecte pas Certificall. Ignorez-les.
- **Ordre de demarrage**: critique ! Toujours utiliser `start.bat` qui fait les etapes dans le bon ordre.
- **Sequence**: stop tout → supprimer proxy → force-stop app → lancer proxy → remettre proxy → lancer app
- Quand vous avez fini, lancez `stop.bat` pour retirer le proxy.

## Depannage

| Probleme | Solution |
|----------|----------|
| Photo rejetee | Relancez `start.bat` (la sequence d'ordre est importante) |
| Ecran blanc | Verifiez que les libs natives sont dans lib/arm64-v8a/ ET lib/x86_64/ |
| BlueStacks non connecte | Lancez BlueStacks et attendez le demarrage complet |
| "Erreur reseau" sur le dashboard | Le dashboard Python a plante, relancez `start.bat` |
| pict2cam ne s'ouvre pas | Verifiez qu'il est defini comme camera par defaut |
