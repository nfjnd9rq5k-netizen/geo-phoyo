"""
MITM Proxy Script — Intercepte le trafic Certificall.
- Modifie les reponses 401/403 en 200 OK
- Lit l'IP depuis ip_config.txt (mis a jour par le dashboard)
"""

import json
import os
from mitmproxy import http, ctx

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ip_config.txt")


def _get_ip():
    """Lit l'IP depuis le fichier de config."""
    try:
        with open(CONFIG_FILE, "r") as f:
            ip = f.read().strip()
            if ip:
                return ip
    except FileNotFoundError:
        pass
    return "86.234.12.45"


def request(flow: http.HTTPFlow) -> None:
    host = flow.request.pretty_host.lower()
    if "certificall" not in host:
        return

    ip = _get_ip()
    flow.request.headers["X-Forwarded-For"] = ip
    ctx.log.warn(f"[REQ] {flow.request.method} {flow.request.path} (IP: {ip})")


def response(flow: http.HTTPFlow) -> None:
    host = flow.request.pretty_host.lower()
    if "certificall" not in host:
        return

    status = flow.response.status_code
    path = flow.request.path
    method = flow.request.method

    ctx.log.warn(f"[RESP] {status} {method} {path}")

    if status in (401, 403):
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
