"""Copia locale e privata di UNA pagina, da aprire offline e modificare per studio.

Scarica la pagina e ciò che serve a mostrarla (fogli di stile, script,
immagini, font) in una cartella, e riscrive i collegamenti perché funzioni
senza rete. Valgono gli stessi limiti della raccolta per l'analisi:
robots.txt rispettato per ogni dominio, nessun login o paywall aggirato, un
429 ferma tutto. Non segue i link verso altre pagine e salta i tracker.

La copia è per uso personale di studio. Testi, immagini, loghi e marchi
restano dei titolari: per pubblicare una tua versione usa lo scheletro pulito
(`scaffold`) e contenuti tuoi. Il file LEGGIMI.txt nella cartella lo ricorda.
"""

from __future__ import annotations

import hashlib
import posixpath
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from functools import partial
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from drdeconstruct.web.fetcher import Getter, HttpResponse, SiteFetcher, _decode, http_get

MAX_FILE_BYTES = 15_000_000
_TRACKERS = re.compile(
    r"googletagmanager\.com|google-analytics\.com|doubleclick\.net|facebook\.(?:net|com)"
    r"|hotjar\.com|clarity\.ms|segment\.(?:com|io)|connect\.facebook"
)
_CSS_URL = re.compile(r"""url\(\s*(["']?)([^"')]+)\1\s*\)""", re.I)
_CSS_IMPORT = re.compile(r"""@import\s+(["'])([^"']+)\1""", re.I)
_ATTR = re.compile(r"""(\s(?:src|href|poster|data-src)\s*=\s*)(["'])(.*?)\2""", re.I | re.S)
_SRCSET = re.compile(r"""(\s(?:srcset|data-srcset)\s*=\s*)(["'])(.*?)\2""", re.I | re.S)
_TAG = re.compile(r"<[a-zA-Z][^>]*>")
_DROP_ATTR = re.compile(
    r"""\s(?:integrity|crossorigin|nonce)(?:\s*=\s*(["']).*?\1)?""", re.I | re.S
)
_DROP_TAGS = re.compile(
    r"""<meta[^>]+http-equiv\s*=\s*["']?content-security-policy[^>]*>|<base\s[^>]*>""", re.I
)
_EXT_BY_TYPE = {
    "text/css": ".css",
    "javascript": ".js",
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/svg": ".svg",
    "image/avif": ".avif",
    "font/woff2": ".woff2",
    "font/woff": ".woff",
}
_ASSET_RELS = {"stylesheet", "icon", "shortcut", "apple-touch-icon", "preload", "modulepreload"}


class _ResourceCollector(HTMLParser):
    """Raccoglie solo le risorse necessarie a mostrare la pagina, non i link."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.refs: list[str] = []

    def handle_starttag(self, tag, attrs_list):
        a = {k: (v or "") for k, v in attrs_list}
        if tag == "link" and set(a.get("rel", "").lower().split()) & _ASSET_RELS:
            self.refs.append(a.get("href", ""))
        elif tag in ("script", "img", "source", "video", "audio", "track", "embed"):
            self.refs += [a.get("src", ""), a.get("data-src", ""), a.get("poster", "")]
        elif tag == "input" and a.get("type", "").lower() == "image":
            self.refs.append(a.get("src", ""))
        for key in ("srcset", "data-srcset"):
            if a.get(key):
                self.refs += _srcset_urls(a[key])


def _srcset_urls(value: str) -> list[str]:
    return [part.strip().split()[0] for part in value.split(",") if part.strip()]


def _safe(segment: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", segment)[:80] or "_"


def local_path(url: str, content_type: str = "") -> str:
    """Percorso locale stabile e sicuro: assets/<dominio>/<percorso>[-hash].<ext>."""
    parts = urlsplit(url)
    segments = [_safe(s) for s in parts.path.split("/") if s not in ("", ".", "..")]
    name = segments.pop() if segments else "index"
    stem, dot, ext = name.rpartition(".")
    if not dot:
        stem, ext = name, ""
    if parts.query:
        stem += "-" + hashlib.sha1(parts.query.encode()).hexdigest()[:8]
    if not ext:
        ctype = content_type.lower()
        ext = next((e for k, e in _EXT_BY_TYPE.items() if k in ctype), ".bin").lstrip(".")
    return "/".join(["assets", _safe(parts.netloc), *segments[:8], f"{stem}.{ext}"])


@dataclass
class MirrorResult:
    folder: Path
    index: Path
    saved: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


class PageMirror:
    def __init__(
        self,
        getter: Getter | None = None,
        max_resources: int = 150,
        max_total_bytes: int = 60_000_000,
        sleep: Callable[[float], None] = time.sleep,
        progress: Callable[[str], None] | None = None,
    ):
        getter = getter or partial(http_get, max_bytes=MAX_FILE_BYTES)
        self._fetcher = SiteFetcher(getter=getter, sleep=sleep)
        self.max_resources = max_resources
        self.max_total_bytes = max_total_bytes
        self._progress = progress or (lambda msg: None)

    def save(self, url: str, folder: Path) -> MirrorResult:
        folder = Path(folder)
        if (folder / "index.html").exists():
            raise FileExistsError(f"In {folder} c'è già una copia: scegli una cartella vuota.")
        self._progress("Scarico la pagina…")
        final, page = self._fetcher.fetch_page(url)
        url = url if urlsplit(url).path else url + "/"
        html = _decode(page)

        self._files: dict[str, bytes] = {}
        self._map: dict[str, str] = {final: "index.html", url: "index.html"}
        self._failed: set[str] = set()
        self._result = MirrorResult(folder, folder / "index.html")
        self._budget = self.max_resources
        self._bytes = 0

        collector = _ResourceCollector()
        collector.feed(html)
        refs = collector.refs + [m.group(2) for m in _CSS_URL.finditer(html)]
        for ref in refs:
            self._download(urljoin(final, ref.strip()))

        html = self._rewrite_html(html, final)
        folder.mkdir(parents=True, exist_ok=True)
        for rel, data in self._files.items():
            path = folder / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        self._result.index.write_text(html, encoding="utf-8")
        (folder / "LEGGIMI.txt").write_text(self._notice(final), encoding="utf-8")
        return self._result

    # --- Download ----------------------------------------------------------
    def _download(self, url: str, depth: int = 0) -> str | None:
        """Scarica `url` (una volta sola) e restituisce il suo percorso locale."""
        if url in self._map:
            return self._map[url]
        if url in self._failed or urlsplit(url).scheme not in ("http", "https"):
            return None
        if _TRACKERS.search(urlsplit(url).netloc):
            return self._skip(url, "tracker, non serve offline")
        if self._budget <= 0:
            return self._skip(url, f"limite di {self.max_resources} file")
        self._budget -= 1
        self._progress(f"Scarico {url[:90]}")
        resp = self._fetcher.fetch_resource(url)
        if isinstance(resp, str):
            return self._skip(url, resp)
        if len(resp.body) >= MAX_FILE_BYTES:
            return self._skip(url, "file troppo grande")
        if self._bytes + len(resp.body) > self.max_total_bytes:
            return self._skip(url, "superato il limite di spazio")
        self._bytes += len(resp.body)

        rel = local_path(url, resp.content_type)
        self._map[url] = rel
        body = resp.body
        if rel.endswith(".css") or "text/css" in resp.content_type.lower():
            body = self._rewrite_css(_decode(resp), url, rel, depth).encode("utf-8")
        self._files[rel] = body
        self._result.saved.append(rel)
        return rel

    def _skip(self, url: str, reason: str) -> None:
        self._failed.add(url)
        short = url if len(url) <= 100 else url[:97] + "…"
        self._result.skipped.append(f"{short} ({reason[:160]})")
        return None

    # --- Riscrittura -------------------------------------------------------
    def _rewrite_css(self, css: str, css_url: str, css_rel: str, depth: int) -> str:
        here = posixpath.dirname(css_rel)

        def local(ref: str) -> str | None:
            if ref.startswith(("data:", "#")):
                return None
            if ref.split("?")[0].endswith(".css") and depth >= 2:
                return None  # @import annidati troppo in profondità
            rel = self._download(urljoin(css_url, ref), depth + 1)
            return posixpath.relpath(rel, here) if rel else None

        def sub_url(m: re.Match) -> str:
            target = local(m.group(2).strip())
            return f'url("{target}")' if target else m.group(0)

        def sub_import(m: re.Match) -> str:
            target = local(m.group(2).strip())
            return f'@import "{target}"' if target else m.group(0)

        return _CSS_URL.sub(sub_url, _CSS_IMPORT.sub(sub_import, css))

    def _rewrite_html(self, html: str, base: str) -> str:
        def resolve(ref: str) -> str:
            ref = ref.strip()
            if not ref or ref.startswith(("#", "data:", "mailto:", "tel:", "javascript:")):
                return ref
            absolute = urljoin(base, ref)
            return self._map.get(absolute, absolute)

        def sub_attr(m: re.Match) -> str:
            return f"{m.group(1)}{m.group(2)}{resolve(m.group(3))}{m.group(2)}"

        def sub_srcset(m: re.Match) -> str:
            items = []
            for part in m.group(3).split(","):
                bits = part.strip().split(maxsplit=1)
                if bits:
                    items.append(" ".join([resolve(bits[0]), *bits[1:]]))
            return f"{m.group(1)}{m.group(2)}{', '.join(items)}{m.group(2)}"

        def sub_css_url(m: re.Match) -> str:
            ref = m.group(2).strip()
            if ref.startswith("data:"):
                return m.group(0)
            return f'url("{resolve(ref)}")'

        def sub_tag(m: re.Match) -> str:
            tag = _DROP_ATTR.sub("", m.group(0))
            return _SRCSET.sub(sub_srcset, _ATTR.sub(sub_attr, tag))

        html = _TAG.sub(sub_tag, _DROP_TAGS.sub("", html))
        return _CSS_URL.sub(sub_css_url, html)

    def _notice(self, url: str) -> str:
        skipped = "\n".join(f"  - {s}" for s in self._result.skipped) or "  - nessuna"
        return (
            "COPIA PRIVATA PER STUDIO\n"
            "========================\n\n"
            f"Pagina originale: {url}\n"
            f"Salvata il: {datetime.now():%d/%m/%Y %H:%M}\n\n"
            "Apri index.html con il browser per vederla senza rete e modificala come vuoi\n"
            "per capire come è fatta.\n\n"
            "NON ripubblicarla: testi, immagini, loghi e marchi appartengono ai titolari,\n"
            "anche dopo le tue modifiche. Per pubblicare una tua versione usa lo scheletro\n"
            "pulito di DrDeconstruct e metti contenuti tuoi.\n\n"
            "I contenuti caricati dopo dal JavaScript (o dietro login) non sono inclusi.\n\n"
            f"File salvati: {len(self._result.saved)}\n"
            f"Risorse saltate:\n{skipped}\n"
        )


def mirror_page(url: str, folder: Path, **kwargs) -> MirrorResult:
    return PageMirror(**kwargs).save(url, folder)


__all__ = ["HttpResponse", "MirrorResult", "PageMirror", "local_path", "mirror_page"]
