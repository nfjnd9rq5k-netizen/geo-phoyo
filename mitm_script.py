"""
MITM Proxy Script — Intercepte le trafic Certificall.
Modifie les reponses 401/403 en 200 OK.
"""

import json
import random
from mitmproxy import http, ctx, tls

# Compteur unique pour chaque item cree
_item_counter = random.randint(10000, 99999)


def tls_clienthello(data: tls.ClientHelloData):
    """Ignore (passthrough) les connexions TLS non-certificall pour ne pas bloquer internet."""
    host = data.context.server.address[0] if data.context.server.address else ""
    if "certificall" not in host.lower():
        data.ignore_connection = True


def request(flow: http.HTTPFlow) -> None:
    host = flow.request.pretty_host.lower()
    if "certificall" not in host:
        return
    ctx.log.warn(f"[REQ] {flow.request.method} {flow.request.path}")

    # Logger les bodies des requetes importantes
    if flow.request.method == "POST" and flow.request.content:
        try:
            req_body = flow.request.content.decode("utf-8", errors="ignore")
            # Tronquer si trop long (base64 des photos)
            if len(req_body) > 2000:
                req_body = req_body[:2000] + "... [TRONQUE]"
            ctx.log.warn(f"[REQ BODY] {req_body}")
        except Exception:
            ctx.log.warn(f"[REQ BODY] (binaire, {len(flow.request.content)} bytes)")


def response(flow: http.HTTPFlow) -> None:
    host = flow.request.pretty_host.lower()
    if "certificall" not in host:
        return

    status = flow.response.status_code
    path = flow.request.path
    method = flow.request.method

    ctx.log.warn(f"[RESP] {status} {method} {path}")

    # Logger les bodies des reponses pour debug
    if flow.response.content and path not in ("/certificall/logger/message",):
        try:
            resp_body = flow.response.content.decode("utf-8", errors="ignore")
            if len(resp_body) > 2000:
                resp_body = resp_body[:2000] + "... [TRONQUE]"
            ctx.log.warn(f"[RESP BODY] {resp_body}")
        except Exception:
            pass

    if status in (401, 403):
        try:
            body = flow.response.content.decode("utf-8", errors="ignore")[:500]
        except Exception:
            body = ""

        global _item_counter
        _item_counter += 1

        ctx.log.error(f"[BYPASS] {status} -> 200 | {method} {path} (id={_item_counter})")

        fake_body = {
            "id": _item_counter,
            "caseId": 1,
            "status": "COMPLETED",
            "success": True,
            "message": "OK"
        }

        flow.response.status_code = 200
        flow.response.headers["content-type"] = "application/json"
        flow.response.content = json.dumps(fake_body).encode()

    elif "trust-services" in path and status >= 400:
        ctx.log.error(f"[BYPASS] {status} -> 200 | {method} {path} (trust-services)")

        fake_analysis = {
            "success": True,
            "status": "COMPLETED",
            "trustScore": 100,
            "message": "OK"
        }

        flow.response.status_code = 200
        flow.response.headers["content-type"] = "application/json"
        flow.response.content = json.dumps(fake_analysis).encode()

    elif status >= 400:
        ctx.log.error(f"[ERROR] {status} {method} {path}")
