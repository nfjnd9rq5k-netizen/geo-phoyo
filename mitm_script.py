"""
MITM Proxy Script — Intercepte le trafic Certificall.
Modifie les reponses 401/403 en 200 OK avec des donnees coherentes.
VERSION DEBUG: logging complet de toutes les requetes/reponses.
"""

import json
import re
import time
import hashlib
from mitmproxy import http, ctx, tls

# Cache des items crees: cle = hash du body -> response coherente
_item_cache = {}
_item_counter = 10000
_last_case_id = None
_request_count = 0


def tls_clienthello(data: tls.ClientHelloData):
    """Ignore (passthrough) les connexions TLS non-certificall pour ne pas bloquer internet."""
    host = data.context.server.address[0] if data.context.server.address else ""
    if "certificall" not in host.lower():
        data.ignore_connection = True


def _extract_case_id(content):
    """Essaie d'extraire le caseId du body (JSON ou multipart binaire)."""
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
        match = re.search(r'caseId[=:]\s*(\d+)', text)
        if match:
            return int(match.group(1))
    except Exception:
        pass
    return None


def _extract_all_fields(content):
    """Extrait tous les champs reconnaissables du body."""
    fields = {}
    if not content:
        return fields
    try:
        text = content.decode("utf-8", errors="ignore")
        for field in ["caseId", "stepId", "itemId", "multiStepPos", "position", "type", "status"]:
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
    """Genere une cle stable pour le cache basee sur le contenu."""
    if not content:
        return "empty"
    return hashlib.md5(content[:1024]).hexdigest()


def _log_headers(prefix, headers):
    """Log les headers importants."""
    important = ["content-type", "authorization", "x-integrity-error", "x-integrity-status",
                 "x-request-id", "x-case-id", "x-item-id"]
    for key in important:
        val = headers.get(key)
        if val:
            ctx.log.warn(f"{prefix} Header {key}: {val}")


def request(flow: http.HTTPFlow) -> None:
    global _last_case_id, _request_count
    host = flow.request.pretty_host.lower()
    if "certificall" not in host:
        return

    _request_count += 1
    path = flow.request.path
    method = flow.request.method

    ctx.log.warn(f"[REQ #{_request_count}] {method} {path}")

    # Log headers
    _log_headers(f"[REQ #{_request_count}]", flow.request.headers)

    # Log content-type
    ct = flow.request.headers.get("content-type", "")
    ctx.log.warn(f"[REQ #{_request_count}] Content-Type: {ct}")

    if method == "POST" and flow.request.content:
        content_len = len(flow.request.content)
        ctx.log.warn(f"[REQ #{_request_count}] Body size: {content_len} bytes")

        # Extraire caseId
        case_id = _extract_case_id(flow.request.content)
        if case_id:
            _last_case_id = case_id
            ctx.log.warn(f"[REQ #{_request_count}] caseId extrait: {case_id}")

        # Extraire tous les champs
        fields = _extract_all_fields(flow.request.content)
        if fields:
            ctx.log.warn(f"[REQ #{_request_count}] Champs: {json.dumps(fields)}")

        # Logger le body (JSON seulement, pas les binaires)
        if "json" in ct.lower() or "text" in ct.lower():
            try:
                body_text = flow.request.content.decode("utf-8", errors="ignore")
                if len(body_text) > 3000:
                    body_text = body_text[:3000] + "... [TRONQUE]"
                ctx.log.warn(f"[REQ #{_request_count}] BODY: {body_text}")
            except Exception:
                pass
        elif "multipart" in ct.lower():
            # Logger les parties texte du multipart
            try:
                text = flow.request.content.decode("utf-8", errors="ignore")
                # Extraire les noms de champs multipart
                field_names = re.findall(r'name="([^"]+)"', text)
                ctx.log.warn(f"[REQ #{_request_count}] Multipart fields: {field_names}")
            except Exception:
                pass


def response(flow: http.HTTPFlow) -> None:
    global _item_counter, _last_case_id
    host = flow.request.pretty_host.lower()
    if "certificall" not in host:
        return

    status = flow.response.status_code
    path = flow.request.path
    method = flow.request.method

    ctx.log.warn(f"[RESP] {status} {method} {path}")

    # Log response headers
    _log_headers("[RESP]", flow.response.headers)

    # Log TOUTES les reponses (sauf logger/message pour reduire le bruit)
    if flow.response.content and "logger/message" not in path:
        try:
            resp_body = flow.response.content.decode("utf-8", errors="ignore")
            if len(resp_body) > 3000:
                resp_body = resp_body[:3000] + "... [TRONQUE]"
            ctx.log.warn(f"[RESP BODY] {resp_body}")
        except Exception:
            ctx.log.warn(f"[RESP BODY] (binaire, {len(flow.response.content)} bytes)")

    if status in (401, 403):
        # Generer un ID stable: si meme requete, meme ID
        body_key = _get_body_key(flow.request.content)
        if body_key in _item_cache:
            item_id = _item_cache[body_key]
            ctx.log.error(f"[BYPASS] {status} -> 200 | {method} {path} (cached id={item_id})")
        else:
            _item_counter += 1
            item_id = _item_counter
            _item_cache[body_key] = item_id
            ctx.log.error(f"[BYPASS] {status} -> 200 | {method} {path} (new id={item_id})")

        # Extraire les champs de la requete pour une reponse coherente
        fields = _extract_all_fields(flow.request.content)
        case_id = fields.get("caseId", _last_case_id) or 1
        now = int(time.time() * 1000)

        fake_body = {
            "id": item_id,
            "caseId": case_id,
            "status": "COMPLETED",
            "success": True,
            "message": "OK",
            "createdAt": now,
            "updatedAt": now,
        }

        # Ajouter les champs extraits de la requete
        for key in ["stepId", "multiStepPos", "position", "type"]:
            if key in fields:
                fake_body[key] = fields[key]

        ctx.log.error(f"[BYPASS] Fake response: {json.dumps(fake_body)}")

        flow.response.status_code = 200
        flow.response.headers["content-type"] = "application/json"
        flow.response.content = json.dumps(fake_body).encode()

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
