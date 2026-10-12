# Autopsy (DrDeconstruct)

![CI](https://github.com/VjAlbert/autopsy/actions/workflows/ci.yml/badge.svg) ![Python](https://img.shields.io/badge/python-3.10%2B-blue) ![License](https://img.shields.io/badge/license-MIT-green)

Piattaforma assistita da AI per il reverse engineering, software e hardware.
DrDeconstruct non sostituisce Ghidra, IDA o binwalk: prende il loro output
testuale e lo spiega con un modello linguistico.

## Moduli

| Modulo | Input | Output |
|---|---|---|
| Software | Pseudocodice C (Ghidra/IDA) o assembly | Scopo della funzione, flusso di controllo, variabili rinominate, codice riscritto, note sull'algoritmo |
| Hardware | Estratti esadecimali di dump, mappe di registri, log UART/SPI/I2C/CAN | Formato riconosciuto, campi decodificati, strutture, ipotesi su pin e registri |
| Web | URL di una pagina pubblica o file HTML salvato | Sezioni, componenti, design system, librerie usate, piano di ricostruzione, scheletro HTML/CSS da riempire |

### Dispositivi collegati

Il modulo `acquisition` elenca i dispositivi USB e le porte seriali, scansiona i
dispositivi Bluetooth LE vicini, cattura il log di avvio via seriale (UART) e,
con un programmatore e `flashrom`, fa il backup e l'aggiornamento della memoria
flash. Ogni scrittura passa dai controlli di `acquisition/safety.py`: backup
dell'originale obbligatorio, conferma esplicita dell'operatore e rilettura di
verifica. Richiede l'extra `hardware`.

Con `drdec decompile` dai direttamente un file binario: DrDeconstruct avvia Ghidra in modalità headless (gratuito, serve Java 21 e `GHIDRA_INSTALL_DIR`), ne estrae lo pseudocodice e, con `--analyze`, lo manda al modello.

### Siti web: studio e reinterpretazione, non clonazione

`drdec web URL` scarica solo ciò che il browser riceve già (HTML, CSS e
JavaScript pubblici dello stesso sito), ne ricava una mappa strutturale e la fa
spiegare al modello. Con `--scaffold CARTELLA` scrive uno scheletro
`index.html` + `styles.css` + `script.js` + `NOTE.md` con testi e immagini
segnaposto e una palette neutra, da riempire con i tuoi contenuti.

Con `--mirror CARTELLA` (o il pulsante "Salva copia sul PC" nella GUI) salvi
invece una **copia privata di una sola pagina**: HTML, fogli di stile, script,
immagini e caratteri, con i collegamenti riscritti perché si apra col browser
anche senza rete. Serve a studiarla e modificarla sul tuo PC; i link verso
altre pagine restano online e i tracker vengono saltati. Nella cartella un
file `LEGGIMI.txt` elenca cosa è stato saltato e ricorda che la copia non va
ripubblicata.

Limiti voluti:

- rispetta `robots.txt` e il suo `Crawl-delay`; non aggira login, paywall o
  misure anti-scraping (401, 403 e 429 fermano la raccolta);
- non scarica immagini, font o video, né script di terzi (vengono solo elencati);
- testi, immagini, loghi e marchi del sito non arrivano né al modello né allo
  scheletro: dei testi restano solo i titoli delle sezioni, per capirne l'ordine.

Anche l'aspetto grafico di un sito può essere tutelato (diritto d'autore,
marchi, concorrenza sleale): lo scheletro è un punto di partenza da
reinterpretare, non una copia da ripubblicare. Prima di analizzare un sito
controlla anche i suoi termini d'uso: alcuni vietano la raccolta automatica.

L'orchestratore usa il tipo dichiarato dall'operatore (`--kind`). Il
riconoscimento automatico è solo un ripiego: se è incerto, il programma si
ferma e chiede di specificare.

## Motori LLM (nessuna chiave API obbligatoria)

| Motore | Come funziona | Costo |
|---|---|---|
| `claude-code` (default) | Lancia la CLI `claude` in modalità headless con il tuo login claude.ai, strumenti disattivati | Consuma i limiti del tuo abbonamento |
| `ollama` | Modello locale via `ollama serve` | Gratis e offline, serve una GPU; qualità inferiore |
| `api` | SDK Anthropic con `ANTHROPIC_API_KEY` | A consumo; spento di default |

Il motore `claude-code` toglie `ANTHROPIC_API_KEY` dall'ambiente del
sottoprocesso, così la CLI usa sempre l'abbonamento.

## Installazione

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
# Motore claude-code: installa Claude Code e lancia `claude` una volta per il login.
# Motore ollama: ollama pull qwen2.5-coder:14b
```

## Uso

```bash
# Un binario intero: Ghidra lo decompila e il modello lo spiega
drdec decompile programma.exe --analyze -o risultato.json
# Un firmware grezzo (indica il processore) e tieni solo certe funzioni
drdec decompile firmware.bin --processor MIPS:LE:32:default --filter "^FUN_" --analyze

# Una funzione già esportata da Ghidra
drdec analyze funzione.c --kind pseudocode_c --arch mips32el

# Un export con molte funzioni, analizzate una alla volta
drdec analyze export_ghidra.c --kind pseudocode_c --split -o risultato.json

# Log di un bus seriale con il motore locale
drdec analyze uart.log --kind bus_log --backend ollama

# Struttura di un sito, senza modello (gratis, nessun limite consumato)
drdec web https://esempio.it --snapshot-only
# Analisi completa e scheletro da riempire
drdec web https://esempio.it --scaffold mio-sito/ -o analisi.json
# Copia privata della pagina, da aprire offline e modificare
drdec web https://esempio.it --mirror copia-studio/
# Una pagina già salvata dal browser
drdec analyze pagina.html --kind web_page
```

Variabili d'ambiente: `DRDEC_BACKEND`, `DRDEC_MODEL`, `DRDEC_OLLAMA_HOST`.

## Interfaccia grafica

```bash
pip install -e ".[gui]"
drdec-gui
```

Finestra con tema scuro: una scheda per analizzare Software/Hardware (incolli o
apri un file e ottieni il risultato), una per decompilare binari, una per
studiare un sito web (analisi, copia privata della pagina, scheletro della tua
versione: tutto con pulsanti, senza riga di comando) e una per i dispositivi
collegati. Il motore IA si sceglie una volta sola, in alto, per tutte le schede.

## Eseguibile per Windows 10/11

Non serve installare Python. Scarica `DrDeconstruct.exe` dalla pagina Releases,
oppure compilalo con PyInstaller (vedi [`packaging/`](packaging/README.md)). A
ogni tag `v*` la build Windows parte da sola e allega l'exe alla Release.

## Struttura

```
src/drdeconstruct/
├─ config.py            impostazioni da variabili d'ambiente
├─ cli.py               comando `drdec`
├─ core/                tipi, euristica di fallback, orchestratore
├─ llm/                 motori: claude_code, ollama, anthropic_api
├─ software/            schemi, prompt, analizzatore (pseudocodice/ASM)
├─ hardware/            schemi, prompt, analizzatore (dump, registri, bus)
├─ web/                 raccolta rispettosa, mappa strutturale, analisi, scheletro
├─ acquisition/         USB, seriale, Bluetooth, flash (con controlli di sicurezza)
├─ gui/                 interfaccia grafica PySide6
└─ preprocess/          Ghidra headless (binario -> pseudocodice) e divisione in funzioni
```

## Test

```bash
pytest      # usano un motore finto, nessuna chiamata reale
ruff check .
```

## Uso lecito

Pensato per interoperabilità, ricerca di sicurezza, didattica e analisi di
software o dispositivi propri. Sul software proprietario, la decompilazione è
consentita solo nei limiti di legge (in Italia art. 64-quater L. 633/1941) e
il codice decompilato non va riutilizzato: per scrivere una propria versione
si parte dalla specifica funzionale (clean room).
