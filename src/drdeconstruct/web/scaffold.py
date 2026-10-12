"""Scheletro HTML/CSS da riempire, generato dall'analisi.

Lo scheletro contiene solo struttura e segnaposto: nessun testo, immagine o
logo del sito studiato. I colori e i font osservati compaiono solo come
commento di riferimento; le variabili partono da una palette neutra che
l'utente sostituisce con la propria identità visiva.
"""

from __future__ import annotations

import re
from html import escape
from pathlib import Path

from drdeconstruct.web.extract import SiteSnapshot
from drdeconstruct.web.schemas import UIComponent, WebAnalysis

_LANDMARK_HINTS = {
    "header": ("header", "intestazione", "testata"),
    "nav": ("nav", "menu", "navigazione"),
    "footer": ("footer", "piè di pagina", "pie di pagina"),
}


def slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:40] or "sezione"


def _landmark(name: str) -> str:
    low = name.lower()
    for tag, words in _LANDMARK_HINTS.items():
        if any(w in low for w in words):
            return "header" if tag == "nav" else tag
    return "section"


def _component_html(comp: UIComponent | None, name: str, indent: str) -> str:
    cls = f"c-{slug(name)}"
    structure = escape(comp.structure, quote=False) if comp else ""
    note = f" struttura osservata: {structure}" if structure else ""
    return (
        f'{indent}<div class="{cls}">\n'
        f"{indent}  <!-- Componente {escape(name, quote=False)}.{note} -->\n"
        f"{indent}  <h3>[Titolo]</h3>\n"
        f"{indent}  <p>[Il tuo testo]</p>\n"
        f"{indent}</div>\n"
    )


def render_html(analysis: WebAnalysis, title: str = "La mia versione") -> str:
    comps = {c.name.lower(): c for c in analysis.components}
    body = []
    has_main = False
    for section in analysis.sections:
        tag = _landmark(section.name)
        cls = f"s-{slug(section.name)}"
        inner_indent = "      " if tag == "section" else "    "
        parts = [
            f"<!-- {escape(section.role, quote=False)} | layout: "
            f"{escape(section.layout, quote=False)} -->",
            f'<{tag} class="{cls}">',
            '  <div class="container">' if tag == "section" else "",
        ]
        if tag == "section":
            parts.append(f"    <h2>[{escape(section.name, quote=False)}]</h2>")
        else:
            parts.append("  <!-- logo e voci di menu proprie -->" if tag == "header" else "")
        inner = "".join(
            _component_html(comps.get(n.lower()), n, inner_indent) for n in section.components
        )
        parts.append(inner.rstrip("\n"))
        if tag == "section":
            parts.append("  </div>")
        parts.append(f"</{tag}>")
        block = "\n".join(p for p in parts if p)
        if tag == "section":
            block = "\n".join("  " + line for line in block.splitlines())
            if not has_main:
                body.append("<main>")
                has_main = True
        elif has_main and tag == "footer":
            body.append("</main>")
            has_main = False
        body.append(block)
    if has_main:
        body.append("</main>")
    return (
        '<!doctype html>\n<html lang="it">\n<head>\n'
        '  <meta charset="utf-8">\n'
        '  <meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"  <title>{escape(title)}</title>\n"
        '  <link rel="stylesheet" href="styles.css">\n'
        "</head>\n<body>\n"
        + "\n".join(body)
        + '\n<script src="script.js"></script>\n</body>\n</html>\n'
    )


def render_css(analysis: WebAnalysis, breakpoints_px: list[int]) -> str:
    ds = analysis.design_system
    reference = "\n".join(f"   - {c}" for c in ds.colors_observed) or "   - nessuno"
    lines = [
        "/* Valori osservati nel sito studiato, SOLO come riferimento.",
        "   Sostituiscili con la tua identità visiva.",
        reference,
        f"   Tipografia: {ds.typography}",
        f"   Spaziatura e griglia: {ds.spacing_and_grid}",
        "*/",
        ":root {",
        "  --color-bg: #ffffff;",
        "  --color-text: #1f2328;",
        "  --color-muted: #6b7280;",
        "  --color-accent: #2563eb;",
        "  --font-body: system-ui, sans-serif;",
        "  --space: 1rem;",
        "  --container: 72rem;",
        "}",
        "",
        "*, *::before, *::after { box-sizing: border-box; }",
        "body { margin: 0; font-family: var(--font-body); color: var(--color-text);"
        " background: var(--color-bg); }",
        ".container { width: min(100% - 2 * var(--space), var(--container));"
        " margin-inline: auto; }",
        "header, footer { padding: var(--space); }",
        "section { padding-block: calc(var(--space) * 3); }",
        "",
    ]
    for section in analysis.sections:
        lines.append(f"/* {section.name}: {section.layout} */")
        lines.append(f".s-{slug(section.name)} {{ }}")
    lines.append("")
    for bp in breakpoints_px:
        lines.append(f"@media (min-width: {bp}px) {{\n  /* layout da {bp}px in su */\n}}")
    return "\n".join(lines).rstrip() + "\n"


def render_js(analysis: WebAnalysis) -> str:
    items = "\n".join(f"// - {i}" for i in analysis.interactions) or "// - nessuna rilevata"
    return f"// Comportamenti osservati da reimplementare a modo tuo:\n{items}\n"


def render_notes(analysis: WebAnalysis) -> str:
    def bullets(items: list[str]) -> str:
        return "\n".join(f"- {i}" for i in items) or "- nessuno"

    comps = "\n".join(f"- **{c.name}**: {c.purpose} (`{c.structure}`)" for c in analysis.components)
    return (
        "# Scheletro da reinterpretare\n\n"
        "Generato da DrDeconstruct. Contiene solo struttura e segnaposto: "
        "metti testi, immagini e marchio tuoi.\n\n"
        f"## Cosa è la pagina\n\n{analysis.page_purpose}\n\n{analysis.layout_summary}\n\n"
        f"## Componenti\n\n{comps or '- nessuno'}\n\n"
        f"## Piano di ricostruzione\n\n{bullets(analysis.rebuild_plan)}\n\n"
        f"## Da non riutilizzare\n\n{bullets(analysis.do_not_reuse)}\n\n"
        f"## Accessibilità\n\n{bullets(analysis.accessibility)}\n\n"
        f"## Domande aperte\n\n{bullets(analysis.open_questions)}\n"
    )


def render_report(snapshot: SiteSnapshot, analysis: WebAnalysis | None) -> str:
    """Resoconto leggibile (Markdown) per chi non vuole leggere JSON."""

    def bullets(items: list[str]) -> str:
        return "\n".join(f"- {i}" for i in items) or "- nessuno"

    tech = [f"{t.name} ({t.category})" for t in snapshot.technologies]
    css = snapshot.css
    parts = [f"# {snapshot.title or snapshot.url}\n\n{snapshot.url}\n"]
    if analysis is not None:
        sections = [f"**{s.name}**: {s.role}. Layout: {s.layout}" for s in analysis.sections]
        stack = [f"{t.name}: {t.role} (sicurezza {t.confidence})" for t in analysis.tech_stack]
        parts += [
            f"## Cosa è la pagina\n\n{analysis.page_purpose}\n\n{analysis.layout_summary}\n",
            f"## Sezioni, dall'alto in basso\n\n{bullets(sections)}\n",
            render_notes(analysis).split("\n## ", 2)[-1].join(["## ", ""]),
            f"## Tecnologie\n\n{bullets(stack)}\n",
            f"## Comportamenti dinamici\n\n{bullets(analysis.interactions)}\n",
        ]
    else:
        heads = [f"H{h.level} {h.text}" for h in snapshot.headings[:25]]
        parts += [
            "_Solo struttura: per la spiegazione completa togli la spunta "
            '"Solo struttura" e analizza di nuovo._\n',
            f"## Titoli delle sezioni\n\n{bullets(heads)}\n",
            f"## Tecnologie rilevate\n\n{bullets(tech)}\n",
        ]
    parts += [
        "## Stile osservato\n",
        f"- Colori principali: {', '.join(css.colors[:8]) or 'nessuno'}",
        f"- Caratteri: {', '.join(css.font_families[:4]) or 'nessuno'}",
        f"- Punti di rottura (px): {', '.join(map(str, css.breakpoints_px)) or 'nessuno'}",
        f"- Elementi grid/flex: {css.layout.get('grid', 0)}/{css.layout.get('flex', 0)}\n",
    ]
    if snapshot.skipped:
        parts.append(f"## Risorse non scaricate\n\n{bullets(snapshot.skipped[:15])}\n")
    return "\n".join(parts)


def build_scaffold(
    analysis: WebAnalysis, breakpoints_px: list[int] | None = None
) -> dict[str, str]:
    return {
        "index.html": render_html(analysis),
        "styles.css": render_css(analysis, breakpoints_px or []),
        "script.js": render_js(analysis),
        "NOTE.md": render_notes(analysis),
    }


def write_scaffold(
    analysis: WebAnalysis, out_dir: Path, breakpoints_px: list[int] | None = None
) -> list[Path]:
    """Scrive lo scheletro in `out_dir`; non sovrascrive file già esistenti."""
    out_dir = Path(out_dir)
    files = build_scaffold(analysis, breakpoints_px)
    existing = [name for name in files if (out_dir / name).exists()]
    if existing:
        raise FileExistsError(
            f"In {out_dir} esistono già {', '.join(existing)}: scegli una cartella vuota."
        )
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for name, text in files.items():
        path = out_dir / name
        path.write_text(text, encoding="utf-8")
        written.append(path)
    return written
