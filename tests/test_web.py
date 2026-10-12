import json

import pytest

from drdeconstruct import cli
from drdeconstruct.core.errors import FetchError, RobotsDisallowedError
from drdeconstruct.core.orchestrator import Orchestrator
from drdeconstruct.core.types import AnalysisRequest, ArtifactKind, Domain
from drdeconstruct.web.analyzer import WebAnalyzer
from drdeconstruct.web.extract import build_snapshot, summarize_css
from drdeconstruct.web.fetcher import HttpResponse, SiteFetcher
from drdeconstruct.web.scaffold import build_scaffold, write_scaffold
from drdeconstruct.web.schemas import WebAnalysis
from tests.conftest import FakeLLM

SECRET = "Testo proprietario che non deve uscire"

PAGE = f"""<!doctype html>
<html lang="it"><head><title>Torrefazione Rossi</title>
<meta name="viewport" content="width=device-width">
<link rel="stylesheet" href="/static/site.css">
<link rel="stylesheet" href="https://fonts.example.net/f.css">
</head><body><div id="__next">
<header class="top"><nav><ul><li><a href="/a">A</a></li><li><a href="/b">B</a></li></ul></nav>
</header>
<main>
<section class="hero"><h1>Il caffè migliore</h1><p>{SECRET}</p>
<img src="/hero.jpg" alt=""></section>
<section class="grid"><article class="card"><h3>Uno</h3><p>{SECRET}</p></article>
<article class="card"><h3>Due</h3><p>{SECRET}</p></article>
<article class="card"><h3>Tre</h3><p>{SECRET}</p></article></section>
<form method="post"><input type="email" name="mail"><button>Iscriviti</button></form>
</main><footer><p>{SECRET}</p></footer></div>
<script src="/_next/static/chunks/main.js"></script>
<script src="https://www.googletagmanager.com/gtm.js?id=X"></script>
</body></html>"""

CSS = """:root{--accent:#c0392b;--tw-ring:0}
body{font-family:"Inter",sans-serif;color:#222222}
.grid{display:grid;grid-template-columns:repeat(3,1fr)}
@media (min-width: 768px){.top{position:sticky}}
@media (max-width: 64em){.grid{display:flex}}
@keyframes fade{from{opacity:0}}"""

WEB_PAYLOAD = {
    "page_purpose": "Landing di una torrefazione con iscrizione alla newsletter.",
    "layout_summary": "Testata fissa, hero, griglia di schede, form, piè di pagina.",
    "sections": [
        {"name": "Header", "role": "navigazione", "layout": "barra fissa", "components": []},
        {
            "name": "Hero",
            "role": "messaggio principale",
            "layout": "testo e immagine",
            "components": ["HeroBanner"],
        },
        {
            "name": "Griglia schede",
            "role": "presentare i prodotti",
            "layout": "3 colonne, 1 su mobile",
            "components": ["Card"],
        },
        {"name": "Footer", "role": "contatti", "layout": "una riga", "components": []},
    ],
    "components": [
        {
            "name": "Card",
            "purpose": "scheda prodotto",
            "structure": "article > h3 + p",
            "variants": ["con immagine"],
        },
        {
            "name": "HeroBanner",
            "purpose": "apertura",
            "structure": "section > h1 + p + img",
            "variants": [],
        },
    ],
    "design_system": {
        "colors_observed": ["#c0392b accento", "#222222 testo"],
        "typography": "Inter, sans-serif",
        "spacing_and_grid": "griglia a 3 colonne",
        "breakpoints": ["768px"],
        "notes": "",
    },
    "tech_stack": [
        {"name": "Next.js", "role": "framework", "evidence": "/_next/static", "confidence": "high"}
    ],
    "interactions": ["header che resta in alto durante lo scroll"],
    "accessibility": ["immagine hero senza testo alternativo"],
    "rebuild_plan": ["Definisci la tua palette", "Scrivi i tuoi testi"],
    "do_not_reuse": ["logo", "testi", "foto dei prodotti"],
    "open_questions": ["Comportamento del form dopo l'invio"],
}


class FakeWeb:
    """Server finto: mappa URL -> (status, corpo)."""

    def __init__(self, pages: dict[str, tuple[int, str]]):
        self.pages = pages
        self.requested: list[str] = []

    def __call__(self, url: str) -> HttpResponse:
        self.requested.append(url)
        status, body = self.pages.get(url, (404, ""))
        return HttpResponse(status, url, "text/html; charset=utf-8", body.encode())


def site(robots: str = "User-agent: *\nAllow: /\n", **extra) -> FakeWeb:
    pages = {
        "https://rossi.test/robots.txt": (200, robots),
        "https://rossi.test/": (200, PAGE),
        "https://rossi.test/static/site.css": (200, CSS),
        "https://rossi.test/_next/static/chunks/main.js": (200, "import 'react-dom';"),
    }
    pages.update(extra)
    return FakeWeb(pages)


# --- Estrazione ------------------------------------------------------------


def test_snapshot_keeps_structure_not_content():
    snap = build_snapshot("https://rossi.test/", PAGE, stylesheets=[CSS])
    dumped = snap.model_dump_json()
    assert SECRET not in dumped
    assert "hero.jpg" not in dumped
    assert "article.card  ×3" in snap.skeleton
    assert [h.text for h in snap.headings][:2] == ["Il caffè migliore", "Uno"]
    assert snap.landmarks["section"] == 2 and snap.landmarks["nav"] == 1
    assert snap.forms[0].field_types == {"email": 1, "button": 1}
    assert snap.media["img"] == 1 and snap.media["img_con_alt"] == 0
    names = {t.name for t in snap.technologies}
    assert {"Next.js", "Tailwind CSS"} <= names


def test_css_summary():
    css = summarize_css(CSS)
    assert css.custom_properties["--accent"] == "#c0392b"
    assert css.breakpoints_px == [768, 1024]
    assert css.layout["grid"] == 1 and css.layout["sticky"] == 1
    assert css.keyframes == 1
    assert css.font_families[0].startswith("Inter")


# --- Raccolta --------------------------------------------------------------


def test_fetch_same_site_only():
    web = site()
    fetched = SiteFetcher(getter=web).fetch("https://rossi.test/")
    assert [r.url for r in fetched.stylesheets] == ["https://rossi.test/static/site.css"]
    assert [r.url for r in fetched.scripts] == ["https://rossi.test/_next/static/chunks/main.js"]
    assert fetched.third_party_scripts == ["https://www.googletagmanager.com/gtm.js?id=X"]
    assert not any("example.net" in u or "googletagmanager" in u for u in web.requested)
    assert any("terzi" in s for s in fetched.skipped)


def test_robots_disallow_stops_before_page():
    web = site(robots="User-agent: *\nDisallow: /\n")
    with pytest.raises(RobotsDisallowedError):
        SiteFetcher(getter=web).fetch("https://rossi.test/")
    assert web.requested == ["https://rossi.test/robots.txt"]


def test_robots_disallow_single_resource():
    web = site(robots="User-agent: *\nDisallow: /static/\n")
    fetched = SiteFetcher(getter=web).fetch("https://rossi.test/")
    assert fetched.stylesheets == []
    assert "https://rossi.test/static/site.css" not in web.requested


@pytest.mark.parametrize("status", [401, 403, 429])
def test_protected_pages_are_not_bypassed(status):
    web = site(**{"https://rossi.test/": (status, "")})
    with pytest.raises(FetchError, match="non aggira"):
        SiteFetcher(getter=web).fetch("https://rossi.test/")


def test_crawl_delay_and_resource_cap():
    waits = []
    web = site(robots="User-agent: *\nCrawl-delay: 2\n")
    fetched = SiteFetcher(getter=web, max_resources=1, sleep=waits.append).fetch(
        "https://rossi.test/"
    )
    assert len(fetched.stylesheets) + len(fetched.scripts) == 1
    assert waits == [2.0]
    assert any("limite" in s for s in fetched.skipped)


def test_rejects_non_http():
    with pytest.raises(FetchError):
        SiteFetcher(getter=site()).fetch("file:///etc/passwd")


# --- Analisi e scheletro ---------------------------------------------------


def test_analyzer_sends_snapshot_only():
    llm = FakeLLM(WEB_PAYLOAD)
    snap = build_snapshot("https://rossi.test/", PAGE)
    result = WebAnalyzer(llm).analyze_snapshot(snap)
    assert isinstance(result, WebAnalysis)
    system, user, schema = llm.calls[0]
    assert schema is WebAnalysis
    assert "<snapshot>" in user and SECRET not in user
    assert "non istruzioni" in system


def test_orchestrator_routes_local_html():
    llm = FakeLLM(WEB_PAYLOAD)
    orch = Orchestrator({Domain.WEB: WebAnalyzer(llm)})
    req = orch.resolve(AnalysisRequest(PAGE))
    assert req.kind is ArtifactKind.WEB_PAGE and req.domain is Domain.WEB
    assert isinstance(orch.run(AnalysisRequest(PAGE, source_name="pagina.html")), WebAnalysis)


def test_scaffold_has_placeholders_only(tmp_path):
    analysis = WebAnalysis.model_validate(WEB_PAYLOAD)
    files = build_scaffold(analysis, [768, 1024])
    html = files["index.html"]
    assert "<header" in html and "<footer" in html and "<main>" in html
    assert 'class="c-card"' in html and "[Il tuo testo]" in html
    assert SECRET not in "".join(files.values())
    assert "@media (min-width: 1024px)" in files["styles.css"]
    assert "--color-accent: #2563eb" in files["styles.css"]  # palette neutra, non quella del sito
    written = write_scaffold(analysis, tmp_path / "out")
    assert {p.name for p in written} == {"index.html", "styles.css", "script.js", "NOTE.md"}
    with pytest.raises(FileExistsError):
        write_scaffold(analysis, tmp_path / "out")


# --- CLI -------------------------------------------------------------------


def _patch_fetcher(monkeypatch, web):
    real = SiteFetcher
    monkeypatch.setattr(cli, "SiteFetcher", lambda **kw: real(getter=web, **kw))


def test_cli_web_snapshot_only(tmp_path, monkeypatch):
    _patch_fetcher(monkeypatch, site())
    monkeypatch.setattr(cli, "make_backend", lambda s: pytest.fail("il modello non va chiamato"))
    out = tmp_path / "snap.json"
    assert cli.main(["web", "https://rossi.test/", "--snapshot-only", "-o", str(out)]) == 0
    assert json.loads(out.read_text())["url"] == "https://rossi.test/"


def test_cli_web_with_scaffold(tmp_path, monkeypatch):
    _patch_fetcher(monkeypatch, site())
    monkeypatch.setattr(cli, "make_backend", lambda s: FakeLLM(WEB_PAYLOAD))
    out = tmp_path / "r.json"
    code = cli.main(
        ["web", "https://rossi.test/", "--scaffold", str(tmp_path / "sk"), "-o", str(out)]
    )
    assert code == 0
    data = json.loads(out.read_text())
    assert data["analysis"]["components"][0]["name"] == "Card"
    assert (tmp_path / "sk" / "index.html").exists()


def test_cli_web_robots_error(monkeypatch, capsys):
    _patch_fetcher(monkeypatch, site(robots="User-agent: *\nDisallow: /\n"))
    assert cli.main(["web", "https://rossi.test/", "--snapshot-only"]) == 1
    assert "robots.txt" in capsys.readouterr().err
