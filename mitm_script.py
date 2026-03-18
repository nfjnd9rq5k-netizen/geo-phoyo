"""
MITM Proxy Script — Intercepte UNIQUEMENT le trafic API Certificall.
Tout le reste passe sans modification.
"""

import json
from mitmproxy import http, ctx


def is_certificall_api(flow: http.HTTPFlow) -> bool:
    """Verifie si la requete est destinee a l'API Certificall."""
    host = flow.request.pretty_host.lower()
    return "certificall" in host


def tls_clienthello(data):
    """Ignore le SSL pour les domaines non-Certificall (ne pas intercepter)."""
    pass


class CertificallInterceptor:
    def request(self, flow: http.HTTPFlow):
        if not is_certificall_api(flow):
            return
        ctx.log.warn(f"[REQ] {flow.request.method} {flow.request.path}")

    def response(self, flow: http.HTTPFlow):
        if not is_certificall_api(flow):
            return

        status = flow.response.status_code
        path = flow.request.path
        method = flow.request.method

        # Log la reponse
        try:
            body = flow.response.content.decode("utf-8", errors="ignore")[:500]
        except Exception:
            body = ""

        ctx.log.warn(f"[RESP] {status} {method} {path}")

        # Intercepter 401/403 (Play Integrity rejet)
        if status in (401, 403):
            ctx.log.error(f"[BYPASS] {status} -> 200 | {method} {path}")
            ctx.log.error(f"  Original: {body[:300]}")

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


addons = [CertificallInterceptor()]
