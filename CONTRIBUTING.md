# Contributing

Thanks for your interest! The workflow is simple.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,gui,smarthome]"
```

## Before opening a PR

```bash
ruff check .          # lint
ruff format .         # formatting
pytest                # tests (fake model, no network, no hardware)
```

On a machine without a display set `QT_QPA_PLATFORM=offscreen` (Linux also needs `libegl1`).

## Rules

- Add a test for every new or fixed behavior.
- No network or hardware in tests: inject fakes as the existing tests do.
- **The app is for beginners.** Every feature needs a GUI page built from the shared components
  (`gui/components.py`): numbered steps, plain-language hints, errors shown in the page banner.
  The CLI is a secondary path.
- The GUI and the model prompts are in **Italian**; identifiers are in English. Everything
  published on GitHub (README, docs, issue and PR templates, release notes) is in **English**.
- Anything that writes to memory or to a device must go through the safety checks
  (`acquisition/safety.py`, `smarthome/safety.py`): backup, explicit confirmation, read-back.
- Keep GUI tests destroying their windows on the main thread (autouse fixture in `tests/test_gui.py`),
  or Qt can segfault in CI.
- Screenshots in the README are generated: run `scripts/make_screenshots.py` instead of editing images.

## Releasing

Push a tag such as `v0.2.0`. The Release workflow builds the Windows installer and the portable exe and
publishes them with checksums (see [`packaging/README.md`](packaging/README.md)).
