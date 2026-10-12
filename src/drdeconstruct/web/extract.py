"""Estrazione strutturale deterministica da HTML, CSS e JavaScript.

Il risultato (`SiteSnapshot`) descrive la forma della pagina senza il suo
contenuto: dei testi restano solo i titoli delle sezioni (troncati), che
servono a capire l'organizzazione. Paragrafi, immagini e indirizzi delle
immagini non vengono conservati, quindi non arrivano né al modello né allo
scheletro generato.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import urlsplit

from pydantic import BaseModel

_VOID = {
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta",
    "param", "source", "track", "wbr",
}  # fmt: skip
# Elementi di cui si registra la presenza ma non il contenuto.
_OPAQUE = {"script", "style", "svg", "template", "noscript", "iframe", "canvas", "video", "picture"}
_LANDMARKS = ("header", "nav", "main", "aside", "footer", "section", "article", "form")
_MAX_NODES = 4000
_MAX_DEPTH = 9
_HEADING_CHARS = 80


# --- Modello del risultato -------------------------------------------------


class Heading(BaseModel):
    level: int
    text: str


class FormInfo(BaseModel):
    method: str
    field_types: dict[str, int]


class CssSummary(BaseModel):
    rule_count: int = 0
    custom_properties: dict[str, str] = {}
    colors: list[str] = []
    font_families: list[str] = []
    breakpoints_px: list[int] = []
    layout: dict[str, int] = {}
    keyframes: int = 0
    transitions: int = 0


class TechHit(BaseModel):
    name: str
    category: str
    evidence: str


class SiteSnapshot(BaseModel):
    url: str
    title: str = ""
    lang: str = ""
    meta: dict[str, str] = {}
    landmarks: dict[str, int] = {}
    headings: list[Heading] = []
    skeleton: str = ""
    element_counts: dict[str, int] = {}
    top_classes: list[str] = []
    forms: list[FormInfo] = []
    media: dict[str, int] = {}
    links: dict[str, int] = {}
    css: CssSummary = CssSummary()
    scripts: dict[str, int] = {}
    third_party_hosts: list[str] = []
    technologies: list[TechHit] = []
    skipped: list[str] = []


# --- Parser HTML -----------------------------------------------------------


@dataclass
class _Node:
    tag: str
    label: str
    children: list[_Node] = field(default_factory=list)


def _label(tag: str, attrs: dict[str, str]) -> str:
    out = tag
    if attrs.get("id"):
        out += f"#{attrs['id'][:30]}"
    classes = attrs.get("class", "").split()
    if classes:
        out += "".join(f".{c[:30]}" for c in classes[:3])
    if attrs.get("role"):
        out += f"[role={attrs['role']}]"
    return out


class _StructureParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _Node("document", "document")
        self.stack: list[_Node] = [self.root]
        self.nodes = 0
        self.opaque_depth = 0
        self.tags: Counter[str] = Counter()
        self.classes: Counter[str] = Counter()
        self.attr_names: set[str] = set()
        self.ids: list[str] = []
        self.headings: list[Heading] = []
        self._heading: tuple[int, list[str]] | None = None
        self.title_parts: list[str] = []
        self._in_title = False
        self.lang = ""
        self.meta: dict[str, str] = {}
        self.forms: list[FormInfo] = []
        self.inline_styles: list[str] = []
        self.inline_scripts: list[str] = []
        self.css_links: list[str] = []
        self.js_srcs: list[str] = []
        self.hrefs: list[str] = []
        self.img_total = 0
        self.img_alt = 0
        self._capture: list[str] | None = None

    # Registrazione
    def handle_starttag(self, tag, attrs_list):
        attrs = {k: (v or "") for k, v in attrs_list}
        self.tags[tag] += 1
        self.attr_names.update(attrs)
        if attrs.get("id"):
            self.ids.append(attrs["id"])
        for c in attrs.get("class", "").split():
            self.classes[c] += 1
        self._record_special(tag, attrs)

        if self.opaque_depth:
            if tag in _OPAQUE and tag not in _VOID:
                self.opaque_depth += 1
            return
        node = _Node(tag, _label(tag, attrs))
        if self.nodes < _MAX_NODES:
            self.stack[-1].children.append(node)
            self.nodes += 1
        if tag in _VOID:
            return
        if tag in _OPAQUE:
            self.opaque_depth = 1
            if tag == "style" or (tag == "script" and not attrs.get("src")):
                self._capture = []
            return
        self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in _VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6") and self._heading:
            level, parts = self._heading
            text = " ".join(" ".join(parts).split())[:_HEADING_CHARS]
            if text:
                self.headings.append(Heading(level=level, text=text))
            self._heading = None
        if tag == "title":
            self._in_title = False
        if self.opaque_depth:
            if tag in _OPAQUE:
                self.opaque_depth -= 1
                if self.opaque_depth == 0 and self._capture is not None:
                    target = self.inline_styles if tag == "style" else self.inline_scripts
                    target.append("".join(self._capture))
                    self._capture = None
            return
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        if self._capture is not None:
            self._capture.append(data)
        elif self._in_title:
            self.title_parts.append(data)
        elif self._heading is not None:
            self._heading[1].append(data)

    def _record_special(self, tag, attrs):
        if tag == "html":
            self.lang = attrs.get("lang", "")[:12]
        elif tag == "title":
            self._in_title = True
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self._heading = (int(tag[1]), [])
        elif tag == "meta":
            name = (attrs.get("name") or attrs.get("property") or "").lower()
            if name in ("generator", "viewport", "theme-color", "og:type"):
                self.meta[name] = attrs.get("content", "")[:120]
        elif tag == "link" and "stylesheet" in attrs.get("rel", "").lower() and attrs.get("href"):
            self.css_links.append(attrs["href"])
        elif tag == "script" and attrs.get("src"):
            self.js_srcs.append(attrs["src"])
        elif tag == "a" and attrs.get("href"):
            self.hrefs.append(attrs["href"])
        elif tag == "img":
            self.img_total += 1
            self.img_alt += bool(attrs.get("alt", "").strip())
        elif tag == "form":
            self.forms.append(FormInfo(method=attrs.get("method", "get").lower(), field_types={}))
        elif tag in ("input", "select", "textarea", "button") and self.forms:
            kind = attrs.get("type", "text") if tag == "input" else tag
            types = self.forms[-1].field_types
            types[kind] = types.get(kind, 0) + 1


def _parse(html: str) -> _StructureParser:
    p = _StructureParser()
    p.feed(html)
    p.close()
    return p


def linked_resources(html: str) -> tuple[list[str], list[str]]:
    """Fogli di stile e script esterni citati dalla pagina (href/src grezzi)."""
    p = _parse(html)
    return p.css_links, p.js_srcs


# --- Scheletro compatto ----------------------------------------------------


def _render(node: _Node, depth: int) -> list[str]:
    """Albero indentato; i fratelli identici consecutivi diventano una riga `×N`."""
    if depth > _MAX_DEPTH:
        return ["  " * depth + "…"] if node.children else []
    groups: list[tuple[list[str], int]] = []
    for child in node.children:
        sub = ["  " * depth + child.label] + _render(child, depth + 1)
        if groups and groups[-1][0] == sub:
            groups[-1] = (sub, groups[-1][1] + 1)
        else:
            groups.append((sub, 1))
    lines: list[str] = []
    for sub, count in groups:
        lines.append(sub[0] + (f"  ×{count}" if count > 1 else ""))
        lines.extend(sub[1:])
    return lines


def _skeleton(root: _Node) -> str:
    body = next((c for c in _walk(root) if c.tag == "body"), root)
    return "\n".join(_render(body, 0))


def _walk(node: _Node):
    for child in node.children:
        yield child
        yield from _walk(child)


# --- CSS -------------------------------------------------------------------

_CUSTOM_PROP = re.compile(r"(?:^|[{;])\s*(--[\w-]+)\s*:\s*([^;}]{1,80})", re.M)
_COLOR = re.compile(r"#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3}\b|rgba?\([^)]*\)|hsla?\([^)]*\)")
_FONT = re.compile(r"font-family\s*:\s*([^;}]+)", re.I)
_MEDIA = re.compile(r"@media[^{]*?(?:min|max)-width\s*:\s*(\d+(?:\.\d+)?)(px|em|rem)", re.I)
_LAYOUT = {
    "grid": re.compile(r"display\s*:\s*(?:inline-)?grid", re.I),
    "flex": re.compile(r"display\s*:\s*(?:inline-)?flex", re.I),
    "sticky": re.compile(r"position\s*:\s*sticky", re.I),
    "fixed": re.compile(r"position\s*:\s*fixed", re.I),
    "grid-template": re.compile(r"grid-template-(?:columns|areas)", re.I),
    "container-query": re.compile(r"@container", re.I),
}


def summarize_css(css: str) -> CssSummary:
    props: dict[str, str] = {}
    for name, value in _CUSTOM_PROP.findall(css):
        if name not in props and len(props) < 40:
            props[name] = value.strip()
    colors = [c for c, _ in Counter(m.lower() for m in _COLOR.findall(css)).most_common(12)]
    fonts = [
        f for f, _ in Counter(m.strip().strip("'\"") for m in _FONT.findall(css)).most_common(6)
    ]
    bps = set()
    for value, unit in _MEDIA.findall(css):
        px = float(value) * (16 if unit.lower() in ("em", "rem") else 1)
        bps.add(int(round(px)))
    return CssSummary(
        rule_count=css.count("{"),
        custom_properties=props,
        colors=colors,
        font_families=fonts,
        breakpoints_px=sorted(bps),
        layout={k: len(r.findall(css)) for k, r in _LAYOUT.items()},
        keyframes=len(re.findall(r"@(?:-webkit-)?keyframes", css)),
        transitions=len(re.findall(r"transition\s*:", css)),
    )


# --- Riconoscimento tecnologie ---------------------------------------------

# (nome, categoria, regex). Le regex si applicano a: URL degli script e dei
# fogli di stile, codice JS/CSS, attributi e classi dell'HTML, meta generator.
_FINGERPRINTS: list[tuple[str, str, str]] = [
    ("Next.js", "framework", r"/_next/static|__NEXT_DATA__|id=\"__next\"|#__next"),
    ("React", "libreria UI", r"react-dom|data-reactroot|_reactRootContainer|__REACT_DEVTOOLS"),
    ("Nuxt", "framework", r"/_nuxt/|__NUXT__"),
    ("Vue", "libreria UI", r"data-v-[0-9a-f]{8}|\bvue(?:\.[a-z]+)*\.js|__vue_app__"),
    ("Angular", "framework", r"ng-version|@angular/core|_nghost-|_ngcontent-"),
    ("SvelteKit", "framework", r"__sveltekit|/_app/immutable/"),
    ("Svelte", "libreria UI", r"\bsvelte-[a-z0-9]{6}\b"),
    ("Astro", "framework", r"astro-island|data-astro-cid"),
    ("Gatsby", "framework", r"___gatsby|/page-data/"),
    ("jQuery", "libreria", r"jquery[\w.-]*\.js|jQuery\.fn"),
    ("Alpine.js", "libreria", r"\bx-data\b|alpinejs"),
    ("htmx", "libreria", r"\bhx-(?:get|post|target|swap)\b|htmx(?:\.org|\.min\.js)"),
    ("GSAP", "animazioni", r"\bgsap\b|ScrollTrigger"),
    ("Three.js", "3D/WebGL", r"three(?:\.module)?(?:\.min)?\.js|THREE\.WebGLRenderer"),
    ("Swiper", "carosello", r"swiper(?:-bundle)?(?:\.min)?\.(?:js|css)|swiper-wrapper"),
    ("Tailwind CSS", "CSS", r"--tw-[a-z]|tailwindcss"),
    ("Bootstrap", "CSS", r"bootstrap(?:\.bundle)?(?:\.min)?\.(?:js|css)|--bs-[a-z]|navbar-expand-"),
    ("Bulma", "CSS", r"bulma(?:\.min)?\.css"),
    ("Font Awesome", "icone", r"font-?awesome|\bfa-solid\b|\bfa-brands\b"),
    ("WordPress", "CMS", r"/wp-content/|/wp-includes/|WordPress"),
    ("Shopify", "e-commerce", r"cdn\.shopify\.com|Shopify\.theme"),
    ("Wix", "site builder", r"static\.parastorage\.com|wixstatic\.com"),
    ("Squarespace", "site builder", r"static1\.squarespace\.com"),
    ("Webflow", "site builder", r"data-wf-page|webflow\.js"),
    ("Google Tag Manager", "analytics", r"googletagmanager\.com"),
    ("Google Analytics", "analytics", r"google-analytics\.com|gtag\("),
]  # fmt: skip
_FP = [(n, c, re.compile(p)) for n, c, p in _FINGERPRINTS]


def detect_technologies(sources: dict[str, str]) -> list[TechHit]:
    """`sources` mappa una descrizione ('html', 'script esterni', …) al testo da cercare."""
    hits: list[TechHit] = []
    for name, category, regex in _FP:
        for where, text in sources.items():
            m = regex.search(text)
            if m:
                evidence = f"{where}: {m.group(0)[:60]}"
                hits.append(TechHit(name=name, category=category, evidence=evidence))
                break
    return hits


# --- Punto d'ingresso ------------------------------------------------------


def build_snapshot(
    url: str,
    html: str,
    stylesheets: list[str] | None = None,
    scripts: list[str] | None = None,
    third_party_scripts: list[str] | None = None,
    skipped: list[str] | None = None,
) -> SiteSnapshot:
    p = _parse(html)
    css_text = "\n".join(p.inline_styles + list(stylesheets or []))
    js_text = "\n".join(p.inline_scripts + list(scripts or []))
    third = list(third_party_scripts or [])

    host = urlsplit(url).netloc
    internal = external = 0
    for href in p.hrefs:
        h = urlsplit(href).netloc
        if href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        if not h or h == host:
            internal += 1
        else:
            external += 1

    dom_markers = " ".join(
        sorted(p.attr_names)
        + [f'id="{i}"' for i in p.ids[:300]]
        + [c for c, _ in p.classes.most_common(300)]
    )
    sources = {
        "html": dom_markers + " " + " ".join(p.meta.values()),
        "risorse collegate": " ".join(p.css_links + p.js_srcs + third),
        "JavaScript": js_text[:2_000_000],
        "CSS": css_text[:2_000_000],
    }

    return SiteSnapshot(
        url=url,
        title=" ".join(" ".join(p.title_parts).split())[:120],
        lang=p.lang,
        meta=p.meta,
        landmarks={t: p.tags[t] for t in _LANDMARKS if p.tags[t]},
        headings=p.headings[:60],
        skeleton=_skeleton(p.root),
        element_counts=dict(p.tags.most_common(25)),
        top_classes=[c for c, _ in p.classes.most_common(40)],
        forms=p.forms,
        media={
            "img": p.img_total,
            "img_con_alt": p.img_alt,
            "svg": p.tags["svg"],
            "video": p.tags["video"],
            "iframe": p.tags["iframe"],
            "canvas": p.tags["canvas"],
        },
        links={"interni": internal, "esterni": external},
        css=summarize_css(css_text),
        scripts={
            "inline": len(p.inline_scripts),
            "stesso_sito": len(scripts or []),
            "terze_parti": len(third),
            "kb_analizzati": len(js_text) // 1024,
        },
        third_party_hosts=sorted({urlsplit(u).netloc for u in third if urlsplit(u).netloc}),
        technologies=detect_technologies(sources),
        skipped=list(skipped or []),
    )
