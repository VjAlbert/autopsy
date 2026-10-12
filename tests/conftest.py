from __future__ import annotations

import pytest
from pydantic import BaseModel


class FakeLLM:
    """Motore finto: registra le chiamate e restituisce una risposta preparata."""

    name = "fake"

    def __init__(self, payload: dict):
        self.payload = payload
        self.calls: list[tuple[str, str, type[BaseModel]]] = []

    def structured(self, system, user, schema):
        self.calls.append((system, user, schema))
        return schema.model_validate(self.payload)


@pytest.fixture
def software_payload() -> dict:
    return {
        "function_purpose": "Calcola il CRC32 di un buffer.",
        "control_flow": ["init a 0xffffffff", "loop sui byte con tabella", "complemento finale"],
        "renames": [
            {
                "original": "v1",
                "proposed": "crc",
                "kind": "variable",
                "rationale": "accumulatore del CRC",
                "confidence": "high",
            }
        ],
        "rewritten_code": "uint32_t crc32(const uint8_t *buf, int len) { ... }",
        "algorithm_notes": "CRC-32 IEEE 802.3, tabella da 256 voci.",
        "open_questions": [],
    }
