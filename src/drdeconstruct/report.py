"""Risultati delle analisi come testo leggibile (Markdown), non JSON.

Per l'interfaccia grafica: chi non è esperto legge titoli, elenchi e tabelle
in italiano. Le chiavi note dei moduli Software e Hardware hanno un'etichetta;
le altre vengono mostrate comunque, con un titolo ricavato dal nome.
"""

from __future__ import annotations

from typing import Any

LABELS = {
    # Software
    "function_purpose": "Cosa fa",
    "control_flow": "Come procede, passo per passo",
    "renames": "Nomi proposti",
    "rewritten_code": "Codice con nomi chiari",
    "algorithm_notes": "Algoritmi riconosciuti",
    "open_questions": "Domande ancora aperte",
    # Hardware
    "summary": "In breve",
    "protocol_or_format": "Protocollo o formato",
    "decoded_fields": "Campi decodificati",
    "structures": "Strutture trovate",
    "pin_or_register_notes": "Note su pin e registri",
    # Web
    "page_purpose": "A cosa serve la pagina",
    "layout_summary": "Com'è organizzata",
    "sections": "Sezioni",
    "components": "Componenti",
    "design_system": "Stile grafico",
    "tech_stack": "Tecnologie",
    "interactions": "Comportamenti dinamici",
    "accessibility": "Accessibilità",
    # Colonne delle tabelle
    "original": "Nome originale",
    "proposed": "Nome proposto",
    "kind": "Tipo",
    "rationale": "Perché",
    "confidence": "Sicurezza",
    "offset_or_position": "Posizione",
    "raw": "Valore grezzo",
    "meaning": "Significato",
    "name": "Nome",
    "role": "Ruolo",
    "layout": "Disposizione",
    "purpose": "Scopo",
    "structure": "Struttura",
    "variants": "Varianti",
    "evidence": "Indizi",
}

# Valori fissi tradotti nelle celle delle tabelle.
WORDS = {
    "high": "alta",
    "medium": "media",
    "low": "bassa",
    "variable": "variabile",
    "parameter": "parametro",
    "function": "funzione",
    "global": "globale",
    "field": "campo",
    "type": "tipo",
    "pointer": "puntatore",
}
CODE_KEYS = {"rewritten_code"}


def _title(key: str) -> str:
    return LABELS.get(key, key.replace("_", " ").capitalize())


def _cell(value: Any) -> str:
    text = WORDS.get(value, value) if isinstance(value, str) else value
    return str(text).replace("|", "\\|").replace("\n", " ")


def _table(rows: list[dict]) -> list[str]:
    keys = list(rows[0])
    head = [_title(k) for k in keys]
    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(keys)]
    lines += ["| " + " | ".join(_cell(r.get(k, "")) for k in keys) + " |" for r in rows]
    return lines


def _value(key: str, value: Any, level: int) -> list[str]:
    if value in (None, "", [], {}):
        return ["_nessuno_"]
    if key in CODE_KEYS and isinstance(value, str):
        return ["```c", value.rstrip(), "```"]
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        if all(isinstance(v, dict) for v in value):
            return _table(value)
        return [f"- {v}" for v in value]
    if isinstance(value, dict):
        out: list[str] = []
        for k, v in value.items():
            out += [f"{'#' * min(level + 1, 6)} {_title(k)}", "", *_value(k, v, level + 1), ""]
        return out
    return [str(value)]


def analysis_markdown(result: dict, level: int = 2) -> str:
    """Una sola analisi (Software, Hardware o Web) come Markdown."""
    if result.get("error"):
        why = "il modello si è rifiutato" if result.get("refused") else "errore"
        return f"**Non analizzata ({why}).** {result['error']}"
    lines: list[str] = []
    for key, value in result.items():
        lines += [f"{'#' * level} {_title(key)}", "", *_value(key, value, level), ""]
    return "\n".join(lines).strip() + "\n"


def to_markdown(result: dict) -> str:
    """Risultato di `orch.run` o di `analyze_functions` (più funzioni)."""
    if "functions" not in result:
        return analysis_markdown(result)
    lines: list[str] = []
    names = list(result.get("symbol_map", {}).values())
    if names:
        lines += ["## Nomi comuni a tutto il programma", ""]
        lines += _table(
            [
                {
                    "original": n["original"],
                    "proposed": n["proposed"],
                    "confidence": n["confidence"],
                }
                for n in names
            ]
        )
        lines.append("")
    for name, analysis in result["functions"].items():
        lines += [f"## Funzione {name}", "", analysis_markdown(analysis, level=3), ""]
    return "\n".join(lines).strip() + "\n"
