"""Scarica le risorse pubbliche di una pagina, come farebbe un browser.

Limiti voluti, non opzioni da aggirare:
- rispetta robots.txt e il suo Crawl-delay; se vieta l'accesso si ferma;
- nessun cookie, login o credenziale; 401, 403 e 429 fermano la raccolta;
- scarica solo HTML, CSS e JavaScript dello stesso sito; gli script di terzi
  (CDN, analytics) vengono solo elencati;
- tetto alla dimensione di ogni risorsa e al numero di risorse.
"""

from __future__ import annotations

import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from urllib import robotparser
from urllib.parse import urljoin, urlsplit

from drdeconstruct.core.errors import FetchError, RobotsDisallowedError
from drdeconstruct.web.extract import linked_resources

USER_AGENT = "DrDeconstruct/0.1 (+https://github.com/VjAlbert/autopsy; analisi strutturale)"
_STOP_STATUSES = {401: "richiede login", 403: "accesso negato", 429: "troppe richieste"}


@dataclass(frozen=True)
class HttpResponse:
    status: int
    url: str
    content_type: str
    body: bytes


Getter = Callable[[str], HttpResponse]


@dataclass
class Resource:
    url: str
    text: str


@dataclass
class FetchedSite:
    url: str
    html: str
    stylesheets: list[Resource] = field(default_factory=list)
    scripts: list[Resource] = field(default_factory=list)
    third_party_scripts: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


def http_get(url: str, timeout: float = 20, max_bytes: int = 2_000_000) -> HttpResponse:
    """GET senza cookie né credenziali; legge al massimo `max_bytes`."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - schema controllato
            return HttpResponse(
                resp.status, resp.url, resp.headers.get("Content-Type", ""), resp.read(max_bytes)
            )
    except urllib.error.HTTPError as exc:
        ctype = exc.headers.get("Content-Type", "") if exc.headers else ""
        return HttpResponse(exc.code, url, ctype, b"")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise FetchError(f"Impossibile raggiungere {url}: {exc}") from exc


def _decode(resp: HttpResponse) -> str:
    charset = "utf-8"
    if "charset=" in resp.content_type:
        charset = resp.content_type.split("charset=")[-1].split(";")[0].strip() or "utf-8"
    try:
        return resp.body.decode(charset, errors="replace")
    except LookupError:
        return resp.body.decode("utf-8", errors="replace")


class HttpStatusError(FetchError):
    """Il server ha risposto con uno stato che impone di fermarsi (401, 403, 429)."""

    def __init__(self, message: str, status: int):
        super().__init__(message)
        self.status = status


def _origin(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


class SiteFetcher:
    def __init__(
        self,
        getter: Getter = http_get,
        max_resources: int = 20,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self._get = getter
        self.max_resources = max_resources
        self._sleep = sleep
        self._robots: dict[str, robotparser.RobotFileParser] = {}
        self._delays: dict[str, float] = {}
        self._robots_errors: dict[str, FetchError] = {}

    def _robots_for(self, origin: str) -> robotparser.RobotFileParser:
        if origin in self._robots:
            return self._robots[origin]
        if origin in self._robots_errors:
            raise self._robots_errors[origin]
        try:
            return self._load_robots(origin)
        except FetchError as exc:
            self._robots_errors[origin] = exc
            raise

    def _load_robots(self, origin: str) -> robotparser.RobotFileParser:
        rp = robotparser.RobotFileParser()
        resp = self._get(origin + "/robots.txt")
        if resp.status == 429:
            raise HttpStatusError(f"{origin}: 429 (troppe richieste). Riprova più tardi.", 429)
        if resp.status in (401, 403):
            rp.disallow_all = True  # convenzione: robots protetto = accesso vietato
        elif resp.status >= 500:
            raise FetchError(
                f"robots.txt di {origin} non disponibile ({resp.status}): mi fermo per prudenza."
            )
        elif resp.status >= 400:
            rp.allow_all = True
        else:
            rp.parse(_decode(resp).splitlines())
        self._robots[origin] = rp
        self._delays[origin] = float(rp.crawl_delay(USER_AGENT) or 0)
        return rp

    def _allowed(self, url: str) -> bool:
        return self._robots_for(_origin(url)).can_fetch(USER_AGENT, url)

    def _fetch(self, url: str, first: bool = False) -> HttpResponse:
        delay = self._delays.get(_origin(url), 0)
        if not first and delay:
            self._sleep(delay)
        resp = self._get(url)
        if resp.status in _STOP_STATUSES:
            raise HttpStatusError(
                f"{url}: {resp.status} ({_STOP_STATUSES[resp.status]}). "
                "DrDeconstruct non aggira login, paywall o limiti anti-scraping.",
                resp.status,
            )
        return resp

    def fetch_page(self, url: str) -> tuple[str, HttpResponse]:
        """Scarica la pagina principale dopo i controlli; restituisce (URL finale, risposta)."""
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.netloc:
            raise FetchError(f"URL non valido (serve http:// o https://): {url}")
        if not parts.path:
            url += "/"
        if not self._allowed(url):
            raise RobotsDisallowedError(f"robots.txt del sito vieta l'accesso a {url}.")
        page = self._fetch(url, first=True)
        if page.status >= 400:
            raise FetchError(f"{url}: errore HTTP {page.status}.")
        final = page.url or url
        if urlsplit(final).netloc != parts.netloc:
            raise FetchError(f"{url} reindirizza a un altro sito ({final}): mi fermo.")
        return final, page

    def fetch_resource(self, url: str) -> HttpResponse | str:
        """Una risorsa secondaria: la risposta, o il motivo per cui è stata saltata.

        Un 429 ferma tutto; 401/403 o robots.txt fanno saltare solo questa risorsa.
        """
        try:
            if not self._allowed(url):
                return "vietato da robots.txt"
            resp = self._fetch(url)
        except HttpStatusError as exc:
            if exc.status == 429:
                raise
            return f"HTTP {exc.status}, protetto"
        except FetchError as exc:
            return str(exc)
        if resp.status >= 400:
            return f"HTTP {resp.status}"
        return resp

    def fetch(self, url: str) -> FetchedSite:
        final, page = self.fetch_page(url)
        host = urlsplit(final).netloc
        site = FetchedSite(url=final, html=_decode(page))

        css_hrefs, js_srcs = linked_resources(site.html)
        budget = self.max_resources
        for kind, refs in (("css", css_hrefs), ("js", js_srcs)):
            for ref in refs:
                absolute = urljoin(final, ref)
                if urlsplit(absolute).scheme not in ("http", "https"):
                    continue
                if urlsplit(absolute).netloc != host:
                    if kind == "js":
                        site.third_party_scripts.append(absolute)
                    else:
                        site.skipped.append(f"{absolute} (foglio di stile di terzi)")
                    continue
                if budget <= 0:
                    site.skipped.append(f"{absolute} (limite di {self.max_resources} risorse)")
                    continue
                resp = self.fetch_resource(absolute)
                budget -= 1
                if isinstance(resp, str):
                    site.skipped.append(f"{absolute} ({resp})")
                    continue
                target = site.stylesheets if kind == "css" else site.scripts
                target.append(Resource(absolute, _decode(resp)))
        return site
