"""Testi semplici per l'interfaccia: cosa è un dispositivo e cosa fare dopo.

Pensato per chi non conosce i protocolli: niente JSON, frasi brevi e un'azione
chiara per ogni dispositivo. Non dipende da Qt, così si può testare.
"""

from __future__ import annotations

import ipaddress
from enum import Enum

from drdeconstruct.smarthome.models import Channel, Ecosystem, SmartDevice
from drdeconstruct.smarthome.schemas import SmartHomeGuide

ECOSYSTEM_NAMES = {
    Ecosystem.XIAOMI: "Xiaomi",
    Ecosystem.AQARA: "Aqara",
    Ecosystem.TAPO: "Tapo (TP-Link)",
    Ecosystem.VALETUDO: "Robot con Valetudo",
    Ecosystem.UNKNOWN: "Marca non riconosciuta",
}

CHANNEL_NAMES = {
    Channel.BLE: "Bluetooth",
    Channel.MDNS: "rete di casa (annuncio automatico)",
    Channel.MIIO: "WiFi, protocollo Xiaomi",
    Channel.TAPO_UDP: "WiFi, protocollo Tapo",
}

CHANNEL_ERRORS = {
    "ble": "Bluetooth non disponibile: controlla che sia acceso sul PC.",
    "mdns": "Ricerca sulla rete di casa non riuscita.",
    "miio": "Ricerca dei dispositivi Xiaomi WiFi non riuscita.",
    "tapo": "Ricerca dei dispositivi Tapo non riuscita.",
}

SMART_HOME_STEPS = (
    "1. Collega il PC alla stessa rete WiFi dei dispositivi e accendi il Bluetooth.\n"
    "2. Premi «Cerca dispositivi» e attendi qualche secondo.\n"
    "3. Clicca un dispositivo nell'elenco: sotto leggi cos'è e cosa serve.\n"
    "4. Se il pulsante «Leggi stato» è attivo, premilo: ti verrà chiesto il token o "
    "l'account solo se serve.\n"
    "5. Premi «Guida AI» per un piano passo passo su tutti i dispositivi trovati "
    "(usa il motore scelto nella scheda «Software / Hardware»)."
)


class Action(str, Enum):
    MIIO = "miio"
    TAPO = "tapo"
    VALETUDO = "valetudo"


def _channels(dev: SmartDevice) -> set[str]:
    listed = dev.details.get("channels", "")
    return {c for c in listed.split(",") if c} | {dev.channel.value}


def _is_ip(text: str) -> bool:
    try:
        ipaddress.ip_address(text)
    except ValueError:
        return False
    return True


def action_for(dev: SmartDevice) -> Action | None:
    """Quale lettura dello stato è possibile per questo dispositivo, se ce n'è una."""
    if not _is_ip(dev.address):
        return None
    channels = _channels(dev)
    if dev.ecosystem is Ecosystem.VALETUDO:
        return Action.VALETUDO
    if Channel.MIIO.value in channels or dev.details.get("service", "").startswith("_miio"):
        return Action.MIIO
    if Channel.TAPO_UDP.value in channels and dev.details.get("encrypt_type", "") == "KLAP":
        return Action.TAPO
    return None


_ACTION_HINTS = {
    Action.MIIO: (
        "Puoi leggerne lo stato con «Leggi stato». Ti servirà il token del dispositivo "
        "(32 caratteri): si ricava dal cloud Xiaomi con il tuo account, per esempio con il "
        "programma gratuito «Xiaomi Cloud Tokens Extractor»."
    ),
    Action.TAPO: (
        "Puoi leggerne lo stato con «Leggi stato» usando email e password del tuo account "
        "TP-Link (quelle dell'app Tapo). Non vengono salvate."
    ),
    Action.VALETUDO: "Puoi leggerne lo stato con «Leggi stato»: non serve nessuna password.",
}


def describe_device(dev: SmartDevice) -> str:
    """Scheda leggibile del dispositivo selezionato."""
    title = dev.name or dev.model or "Dispositivo senza nome"
    lines = [title, ""]
    lines.append(f"Marca: {ECOSYSTEM_NAMES[dev.ecosystem]}")
    if dev.model and dev.model != title:
        lines.append(f"Modello: {dev.model}")
    seen_on = ", ".join(CHANNEL_NAMES[Channel(c)] for c in sorted(_channels(dev)))
    lines.append(f"Visto tramite: {seen_on}")
    if dev.address:
        lines.append(f"Indirizzo: {dev.address}")

    readings = {
        "temperature_c": "Temperatura: {} °C",
        "humidity_pct": "Umidità: {} %",
        "battery_pct": "Batteria: {} %",
        "illuminance_lux": "Luce: {} lux",
        "moisture_pct": "Umidità del terreno: {} %",
    }
    values = [fmt.format(dev.details[k]) for k, fmt in readings.items() if k in dev.details]
    if values:
        lines += ["", "Valori letti dal Bluetooth:", *values]

    lines += ["", "Cosa fare:"]
    action = action_for(dev)
    if action is not None:
        lines.append(_ACTION_HINTS[action])
    elif dev.channel is Channel.BLE:
        lines.append(
            "Questo dispositivo è visto solo via Bluetooth. Se è un sensore, i valori sopra "
            "sono già tutto ciò che trasmette. Se è un robot o una presa, il Bluetooth serve "
            "solo all'abbinamento: per leggerlo serve che sia sulla stessa rete WiFi del PC."
        )
    else:
        lines.append("Per ora non c'è una lettura diretta: chiedi alla «Guida AI» come procedere.")
    if dev.needs:
        lines += ["", "Ti serve:", *[f"• {n}" for n in dev.needs]]
    return "\n".join(lines)


def describe_errors(errors: dict[str, str]) -> str:
    if not errors:
        return ""
    lines = ["Alcune ricerche non sono riuscite:"]
    for channel, detail in errors.items():
        lines.append(f"• {CHANNEL_ERRORS.get(channel, channel)} ({detail})")
    return "\n".join(lines)


def format_guide(guide: SmartHomeGuide) -> str:
    """La guida AI come testo da leggere, non come JSON."""
    confidence = {"high": "sicuro", "medium": "abbastanza sicuro", "low": "da verificare"}
    lines = [guide.summary, ""]
    for advice in guide.devices:
        state = "si può leggere subito" if advice.reachable_now else "serve preparazione"
        lines.append(f"■ {advice.device} ({advice.ecosystem}): {state}")
        lines.append(f"  Come collegarsi: {advice.connection_path}")
        for req in advice.requirements:
            lines.append(f"  • Ti serve: {req}")
        if advice.firmware_path:
            lines.append(f"  Firmware: {advice.firmware_path}")
        for risk in advice.risks:
            lines.append(f"  ⚠ {risk}")
        lines.append(f"  Affidabilità: {confidence[advice.confidence]}")
        lines.append("")
    if guide.not_reachable:
        lines.append("Non raggiungibili dal PC:")
        lines += [f"• {item}" for item in guide.not_reachable]
        lines.append("")
    if guide.next_steps:
        lines.append("Prossimi passi:")
        lines += [f"{i}. {step}" for i, step in enumerate(guide.next_steps, 1)]
    return "\n".join(lines).rstrip()


def format_state(data: object, indent: int = 0) -> str:
    """Rende leggibile lo stato restituito da un dispositivo (dizionari annidati)."""
    pad = "  " * indent
    if isinstance(data, dict):
        out = []
        for key, value in data.items():
            if isinstance(value, dict | list):
                out.append(f"{pad}{key}:")
                out.append(format_state(value, indent + 1))
            else:
                out.append(f"{pad}{key}: {value}")
        return "\n".join(out)
    if isinstance(data, list):
        return "\n".join(
            format_state(item, indent) if isinstance(item, dict | list) else f"{pad}• {item}"
            for item in data
        )
    return f"{pad}{data}"
