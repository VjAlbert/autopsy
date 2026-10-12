# Contribuire

Grazie per l'interesse. Il progetto segue un flusso semplice.

## Ambiente

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,gui]"
```

## Prima di aprire una PR

```bash
ruff check .          # lint
ruff format .         # formattazione
pytest                # test (usano un motore finto, nessuna chiamata reale)
```

## Regole

- Aggiungi un test per ogni comportamento nuovo o corretto.
- Niente chiamate di rete o hardware nei test: inietta un finto come negli esempi.
- Mantieni i prompt e i commenti in italiano, gli identificatori in inglese.
- Le operazioni che scrivono sulla memoria devono sempre passare dai controlli in
  `acquisition/safety.py`.
