"""Guida assistita dall'AI: dall'inventario a un piano di collegamento per dispositivo."""

from __future__ import annotations

import json

from drdeconstruct.llm.base import LLMBackend
from drdeconstruct.smarthome.inventory import Inventory
from drdeconstruct.smarthome.prompts import SYSTEM, build_user_message, redact
from drdeconstruct.smarthome.schemas import SmartHomeGuide


class SmartHomeAdvisor:
    def __init__(self, llm: LLMBackend):
        self.llm = llm

    def advise(self, inventory: Inventory | dict, context: str = "") -> SmartHomeGuide:
        data = inventory.to_dict() if isinstance(inventory, Inventory) else inventory
        payload = json.dumps(redact(data), indent=2, ensure_ascii=False)
        return self.llm.structured(SYSTEM, build_user_message(payload, context), SmartHomeGuide)
