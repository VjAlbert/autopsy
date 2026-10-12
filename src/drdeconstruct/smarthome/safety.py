"""Regole per i comandi inviati ai dispositivi smart home.

I metodi in sola lettura passano sempre; tutto il resto (accendere, spegnere,
cambiare impostazioni, avviare il robot) richiede la conferma esplicita
dell'operatore, data da un flag in CLI o da un pulsante, mai in automatico.
"""

from __future__ import annotations

from dataclasses import dataclass

from drdeconstruct.core.errors import SafetyError

MIIO_READ_ONLY = frozenset(
    {
        "miIO.info",
        "get_status",
        "get_prop",
        "get_properties",
        "get_consumable",
        "get_clean_summary",
        "get_clean_record",
        "get_timer",
        "get_dnd_timer",
        "get_map_v1",
        "get_serial_number",
        "get_current_sound",
        "get_network_info",
        "get_fw_features",
    }
)

TAPO_READ_ONLY = frozenset(
    {
        "get_device_info",
        "get_device_usage",
        "get_energy_usage",
        "get_current_power",
        "get_device_time",
        "get_child_device_list",
        "get_child_device_component_list",
        "component_nego",
    }
)


@dataclass(frozen=True)
class CommandGuard:
    """Blocca i comandi che modificano il dispositivo senza conferma."""

    confirmed: bool = False

    def check(self, method: str, read_only: frozenset[str]) -> None:
        if method in read_only:
            return
        if not self.confirmed:
            raise SafetyError(
                f"Comando '{method}' bloccato: può modificare il dispositivo. "
                "Ripeti con la conferma esplicita (--confirm) se sei sicuro."
            )
