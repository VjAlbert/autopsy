"""Robot aspirapolvere con firmware Valetudo: lettura dell'API REST locale.

Valetudo sostituisce il cloud Xiaomi/Roborock/Dreame dopo il rooting e offre
un'API HTTP senza autenticazione sulla rete di casa. Qui si leggono soltanto
informazioni e stato; i comandi di movimento restano fuori da questo modulo.
"""

from __future__ import annotations

import json
import urllib.request
from collections.abc import Callable

from drdeconstruct.core.errors import DrDeconstructError

Getter = Callable[[str], bytes]


def _urllib_get(url: str) -> bytes:
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:  # noqa: S310 - URL locale
            return resp.read()
    except OSError as exc:
        raise DrDeconstructError(f"Impossibile contattare {url}: {exc}") from exc


def read_robot(ip: str, getter: Getter = _urllib_get) -> dict:
    """Restituisce modello, versione di Valetudo e attributi di stato del robot."""
    base = f"http://{ip}/api/v2"
    result = {}
    for key, path in (
        ("robot", "/robot"),
        ("valetudo", "/valetudo/version"),
        ("state", "/robot/state/attributes"),
    ):
        try:
            result[key] = json.loads(getter(base + path))
        except ValueError as exc:
            raise DrDeconstructError(f"Risposta non valida da {base}{path}") from exc
    return result
