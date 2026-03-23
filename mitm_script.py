"""
MITM Proxy Script — Intercepte le trafic Certificall.
Modifie les reponses 401/403 en 200 OK.
"""

import json
from mitmproxy import http, ctx, tls


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


def response(flow: http.HTTPFlow) -> None:
    host = flow.request.pretty_host.lower()
    if "certificall" not in host:
        return

    status = flow.response.status_code
    path = flow.request.path
    method = flow.request.method

    ctx.log.warn(f"[RESP] {status} {method} {path}")

    if status in (401, 403):
        try:
            body = flow.response.content.decode("utf-8", errors="ignore")[:500]
        except Exception:
            body = ""

        ctx.log.error(f"[BYPASS] {status} -> 200 | {method} {path}")

        fake_body = {
            "id": 999,
            "caseId": 1,
            "status": "COMPLETED",
            "success": True,
            "message": "OK"
        }

        flow.response.status_code = 200
        flow.response.headers["content-type"] = "application/json"
        flow.response.content = json.dumps(fake_body).encode()

    elif status >= 400:
        ctx.log.error(f"[ERROR] {status} {method} {path}")
