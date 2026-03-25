"""
MITM Proxy Script — Intercepte le trafic Certificall.
Bypass 403 UNIQUEMENT sur updateOrCreate (pas sur auth/login).
"""

import json
import re
import time
import hashlib
from mitmproxy import http, ctx, tls

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


def _should_bypass(path):
    """Verifie si ce path doit etre bypasse en 401/403."""
    for bp in BYPASS_PATHS:
        if bp in path:
            return True
    return False


def request(flow: http.HTTPFlow) -> None:
    global _last_case_id
    host = flow.request.pretty_host.lower()
    if "certificall" not in host:
        return

    path = flow.request.path
    method = flow.request.method
    ctx.log.warn(f"[REQ] {method} {path}")

    # Supprimer les headers d'integrite qui bloquent les requetes
    for h in ["x-integrity-error", "x-integrity-token"]:
        if h in flow.request.headers:
            del flow.request.headers[h]
            ctx.log.warn(f"[REQ] Supprime header: {h}")

    # v3 endpoint n'existe pas (404). On laisse v5 et le bypass 403->200 gere.

    if method == "POST" and flow.request.content:
        case_id = _extract_case_id(flow.request.content)
        if case_id:
            _last_case_id = case_id

        # Log le body pour les endpoints importants (pas logger/message)
        if "logger/message" not in path:
            ct = flow.request.headers.get("content-type", "")
            if "json" in ct.lower():
                try:
                    body = flow.request.content.decode("utf-8", errors="ignore")
                    if len(body) > 2000:
                        body = body[:2000] + "...[TRONQUE]"
                    ctx.log.warn(f"[REQ BODY] {body}")
                except Exception:
                    pass
            elif "multipart" in ct.lower():
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

    # Forcer play-integrity a TRUE pour declencher le fallback avec headers
    if "feature-flags/play-integrity" in path and status == 200:
        try:
            data = json.loads(flow.response.content)
            if not data.get("isActivated"):
                data["isActivated"] = True
                flow.response.content = json.dumps(data).encode()
                ctx.log.warn(f"[PATCH] play-integrity force a true (fallback mode)")
        except Exception:
            pass

    # BYPASS 401/403 UNIQUEMENT sur updateOrCreate
    if status in (401, 403) and _should_bypass(path):
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
