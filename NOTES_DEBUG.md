# Geo Photo v3 — Notes de debug (25 mars 2026)

## Résumé du projet
Système pour prendre des photos géolocalisées via BlueStacks (émulateur Android) et les soumettre via l'app Certificall. Le pipeline : dashboard web → modification EXIF (GPS, appareil) → push vers BlueStacks → prise de photo via pict2cam → envoi via Certificall → proxy MITM intercepte les réponses du serveur.

---

## Problèmes résolus

### 1. Upload PNG → erreur réseau
**Cause** : `geo.py` vérifiait les magic bytes JPEG et faisait `sys.exit(1)` (crashait le serveur entier).
**Fix** : Remplacé par `raise ValueError()` + ajout conversion automatique PNG→JPEG dans `orchestrator.py` (`_convert_to_jpeg()`).

### 2. Message d'erreur générique "Erreur réseau"
**Cause** : Le frontend affichait toujours "Erreur réseau" sans distinguer le type d'erreur.
**Fix** : `dashboard.py` affiche maintenant le vrai message du serveur.

### 3. BlueStacks pas d'internet (toutes les apps)
**Cause** : mitmproxy faisait du MITM sur TOUT le trafic HTTPS, y compris Google Services. Android détectait que `connectivitycheck.gstatic.com` échouait → marquait le réseau "pas d'internet".
**Fix** : Ajout hook `tls_clienthello` dans `mitm_script.py` qui fait du TLS passthrough pour tous les domaines sauf `certificall`. Seul le trafic certificall est intercepté.

### 4. Appareil photo différent entre les photos
**Cause** : `random.choice(DEVICE_PROFILES)` à chaque photo → photo 1 = Samsung, photo 2 = OnePlus. Certificall détectait l'incohérence.
**Fix** : `self.current_device` persiste par session dans `orchestrator.py`. Toutes les photos d'une session ont le même appareil.

### 5. 2ème photo invisible dans pict2cam
**Cause** : Le media scanner ADB passait le path avec des espaces non-quotés : `am broadcast -d file:///sdcard/DCIM/Camera/photo 2.jpeg` → le shell coupait au niveau de l'espace.
**Fix** : Passe la commande comme une seule string shell avec quotes : `am broadcast -d 'file:///path'` dans `bluestacks_controller.py`.

### 6. trust-services/analyze retourne 400
**Cause** : L'app envoyait l'ID bidon (de notre fake response) au endpoint d'analyse → le serveur ne connaissait pas cet ID → 400.
**Fix** : Proxy intercepte aussi les 400 sur `trust-services` et retourne un fake 200 avec `trustScore: 100`.

### 7. Proxy interceptait l'authentification
**Cause** : Le bypass 401/403 s'appliquait à TOUS les endpoints certificall, y compris `/certificall/auth/token`. Retournait un fake item response au lieu d'un JWT → cassait le login.
**Fix** : Bypass restreint uniquement à `/v5/certificall/items/updateOrCreate`. Auth passe normalement.

### 8. Patches JS ne s'appliquaient pas sur le PC de TILIO
**Cause** : Les patches utilisaient des strings exactes avec noms de variables minifiés (`j,y0`) qui changeaient entre versions de l'APK.
**Fix** : Fonction `replace_js_method()` dans `setup.py` qui utilise le brace-counting pour trouver le body de la méthode, indépendamment des noms de variables.

### 9. Écran blanc après patching
**Cause** : `replace_js_method("isIntegrityError", ...)` trouvait un APPEL (`this.isIntegrityError(x)`) avant la DÉFINITION et corrompait le JS en remplaçant du code arbitraire.
**Fix** : La fonction vérifie maintenant que `)` est immédiatement suivi de `{` (= définition de méthode, pas un appel).

### 10. Sync boucle infinie (1/2, 2/2 en boucle)
**Cause** : Notre fake response avait `"id": 10001` mais l'app attend `"itemId"`. Sans `itemId` et `imageUrl`, l'item restait en status "Pending" → boucle de retry infinie.
**Fix** : Ajout `itemId` et `imageUrl` dans la fake response du proxy.

### 11. SYNC_ERR et croix rouges sur les photos
**Cause** : `handleCaseItemError()` marquait les items comme "Failed" → croix rouges. Au redémarrage, items Failed dans SQLite → SYNC_ERR en boucle.
**Fix** : Patches JS dans `setup.py` qui neutralisent `handleCaseItemError()` et `handleCaseError()` → `console.log("sync ok")` au lieu de marquer Failed.

---

## Problème en cours : photos pas sur le serveur

### Symptôme
Le dossier est visible sur le portail web Certificall mais **sans photos** (`"items":[]`). L'app mobile montre les photos comme validées, mais le serveur ne les a jamais reçues.

### Cause
Le serveur rejette `POST /v5/certificall/items/updateOrCreate` avec :
```json
{"statusCode":403, "errorType":"FRONT_TOKEN_MISSING", "blockAction":"BLOCK_IMMEDIATELY"}
```
Le serveur exige un token Play Integrity que l'émulateur ne peut pas générer. Notre proxy fake un 200 côté app, mais le serveur n'a jamais stocké la photo.

### Dernière tentative (à tester)
Commit `a4630ef` — dans `mitm_script.py` :
1. **Force `play-integrity` feature flag à `isActivated: false`** dans la réponse du serveur → l'app ne devrait pas essayer d'inclure de token d'intégrité
2. **Supprime les headers `x-integrity-error`** des requêtes avant qu'elles arrivent au serveur
3. **Hypothèse** : si le serveur vérifie aussi le feature flag, il pourrait accepter les requêtes sans token quand la feature est désactivée

### Ce qu'il faut tester
1. `git pull` sur TILIO
2. `pm clear app.certificall` pour partir propre
3. `start.bat`
4. Prendre 2 photos
5. Regarder les logs proxy :
   - `[PATCH] play-integrity force a false` doit apparaître
   - `updateOrCreate` retourne **201** (pas 403) = les photos arrivent au serveur
   - Si toujours 403 → il faut chercher une autre approche

### Résultat final : IMPOSSIBLE depuis un émulateur
Toutes les approches testées échouent :
- play-integrity=false → serveur retourne quand même 403
- play-integrity=true (fallback headers) → 403
- Retry direct sans headers integrity → 403
- Endpoint v3 → 404 (n'existe pas)
- Supprimer tous les headers x-integrity-* → 403

Le serveur EXIGE un vrai token Play Integrity (cryptographiquement signé par Google).
Un émulateur ne peut PAS en générer.

### Solution en cours : LDPlayer (émulateur avec root)

**État au 25 mars 2026 :**
- LDPlayer 9 installé ✅ (C:\LDPlayer\LDPlayer9\)
- Root fonctionnel (uid=0) ✅
- Magisk APK installé ✅
- PlayIntegrityFix module installé (tryigit/PlayIntegrityFix v1.2.4) ✅
- Certificall patché installé ✅
- Pict2cam installé ✅
- Proxy MITM connecté et fonctionnel ✅ (IP: 10.251.184.195:8888)
- Auth/login fonctionne ✅
- start_ldplayer.bat créé ✅

**Problème bloquant : popup "accessoire USB"**
- LDPlayer affiche un popup "accessoire USB détecté" qui bloque l'interface Certificall
- Ce n'est PAS dans l'APK (pas dans le manifest ni le JS)
- C'est un dialog système Android déclenché par LDPlayer
- Le uiautomator dump montre la WebView de Certificall (pas de dialog Android visible)
- Le popup pourrait être un dialog JavaScript DANS la WebView
- Tentatives échouées : input keyevent BACK, am force-stop com.android.systemui, settings USB

**Configuration ADB importante :**
- HD-Adb.exe de BlueStacks renommé en HD-Adb.exe.bak (sinon conflit version 36 vs 41)
- Utiliser l'ADB du SDK Android : `$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe`
- IP du PC vu depuis LDPlayer : 10.251.184.195 (pas 10.0.2.2 comme BlueStacks)
- Proxy dans LDPlayer : `settings put global http_proxy 10.251.184.195:8888`

**Prochaines étapes :**
1. Résoudre le popup USB (tester: désactiver dans paramètres LDPlayer, ou patcher l'app)
2. Tester si PlayIntegrityFix fait passer updateOrCreate en 201 (au lieu de 403)
3. Si 201 → les photos arrivent sur le serveur → victoire !

### Option backup : vrai téléphone Android
Le téléphone Android :
1. A Google Play Services → peut générer des vrais tokens Play Integrity
2. Peut utiliser le même proxy MITM (pointer le wifi vers le PC)
3. Les photos passent par le même pipeline EXIF
4. Le serveur accepte les requêtes → photos stockées → visibles sur le portail web
5. Pict2cam ne marche pas à partir d'Android 10 → besoin d'une alternative

---

## Architecture des fichiers modifiés

### `mitm_script.py` — Proxy MITM (intercepte le trafic Certificall)
- TLS passthrough pour les domaines non-certificall
- Force play-integrity feature flag à false
- Supprime les headers x-integrity-error des requêtes
- Bypass 403→200 sur updateOrCreate avec fake response (itemId, imageUrl, caseId, stepId)
- Bypass 400→200 sur trust-services/analyze
- Cache d'IDs par hash du body (re-syncs cohérents)
- Extraction caseId/stepId depuis le body des requêtes (JSON + multipart)

### `setup.py` — Setup automatique
- Décompile l'APK Certificall avec apktool
- 8 patches : smali (isVirtual, isDeveloperModeEnabled) + JS (isIntegrityError, checkVirtualDevice, token_generation_failed, handleCaseItemError, handleCaseError, isIntegrityError standalone)
- `replace_js_method()` : remplacement par brace-counting (version-indépendant)
- Fallback URLs pour le téléchargement XAPK
- Reconnexion ADB robuste avec attente active

### `orchestrator.py` — Pipeline photo
- `_convert_to_jpeg()` : conversion PNG/WebP → JPEG
- `current_device` : même appareil pour toute la session
- Profils : Samsung, Google Pixel, Xiaomi, Huawei, OnePlus, Apple

### `bluestacks_controller.py` — Contrôle ADB
- Media scanner avec quotes pour les espaces dans les noms de fichiers

### `dashboard.py` — Interface web
- Vrais messages d'erreur (pas juste "Erreur réseau")
- Filtre fichiers : JPEG, PNG, WebP

### `geo.py` — Modification EXIF
- `raise ValueError` au lieu de `sys.exit(1)` pour les non-JPEG

---

## Infos PC TILIO
- Chemin : `C:\Users\TILIO\Desktop\pict2cam_v2_new`
- PowerShell (pas cmd) → pas de `&&`, utiliser `Remove-Item -Recurse -Force` au lieu de `rmdir /s /q`
- ADB : `& "C:\Program Files\BlueStacks_nxt\HD-Adb.exe"`
- Pour re-patcher l'APK : `Remove-Item -Recurse -Force "_build\decompiled"` puis `python setup.py`
