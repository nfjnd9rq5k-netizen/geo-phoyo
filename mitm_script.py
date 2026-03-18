"""
MITM Proxy Script — Intercepte le trafic Certificall.
Phase 1: LOG tout pour comprendre les requetes/reponses.
Phase 2: Modifier les reponses 401/403 en 200 OK.
"""

import json
from mitmproxy import http, ctx


def request(flow: http.HTTPFlow) -> None:
    """Log les requetes sortantes."""
    host = flow.request.pretty_host.lower()
    if "certificall" not in host and "google" not in host:
        return

    ctx.log.warn(f"[REQ] {flow.request.method} {flow.request.url}")

    # Log integrity headers
    for h in ["x-play-integrity-token", "x-integrity-action", "x-integrity-timestamp",
              "x-integrity-error", "x-installation-id", "x-session-id", "authorization"]:
        val = flow.request.headers.get(h, "")
        if val:
            ctx.log.warn(f"  [{h}] = {val[:80]}...")


def response(flow: http.HTTPFlow) -> None:
    """Intercepte et modifie les reponses."""
    host = flow.request.pretty_host.lower()
    if "certificall" not in host:
        return

    status = flow.response.status_code
    path = flow.request.path
    method = flow.request.method

    # Log TOUTES les reponses
    try:
        body = flow.response.content.decode("utf-8", errors="ignore")[:1000]
    except Exception:
        body = "(binary)"

    ctx.log.warn(f"[RESP] {status} {method} {path}")
    ctx.log.warn(f"  Body: {body[:500]}")

    # MODIFIER les reponses 401/403 (integrity errors) en 200
    if status in (401, 403):
        ctx.log.error(f"[INTERCEPT] {status} -> 200 on {method} {path}")
        ctx.log.error(f"  Original body: {body[:500]}")

        # Construire une fausse reponse de succes
        fake_body = {}

        # Pour les endpoints de photo/items, retourner un faux succes
        if "items" in path or "photo" in path or "case" in path:
            fake_body = {
                "id": 999,
                "caseId": 1,
                "status": "COMPLETED",
                "success": True,
                "message": "OK"
            }
        else:
            fake_body = {"success": True, "message": "OK"}

        flow.response.status_code = 200
        flow.response.headers["content-type"] = "application/json"
        flow.response.content = json.dumps(fake_body).encode()
        ctx.log.error(f"  Fake response: {json.dumps(fake_body)}")

    # Log aussi les erreurs 4xx/5xx
    elif status >= 400:
        ctx.log.error(f"[ERROR] {status} {method} {path}: {body[:300]}")
