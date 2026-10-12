# Eseguibile Windows

Produce `DrDeconstruct.exe`, un singolo file che non richiede Python installato.

## Compilare in locale (Windows 10/11)

```powershell
py -3.12 -m venv .venv
.venv\Scripts\activate
pip install -e ".[full]" pyinstaller
pyinstaller packaging\drdeconstruct.spec
# risultato: dist\DrDeconstruct.exe
```

## Build automatica

A ogni tag `v*` il workflow `.github/workflows/release.yml` compila l'exe su un
runner Windows e lo allega alla Release di GitHub.

## Note

- L'exe include l'interfaccia grafica e i moduli di acquisizione (seriale, USB,
  Bluetooth). `flashrom` resta un programma esterno da installare a parte.
- Il motore `claude-code` richiede comunque Claude Code installato sul PC per il
  login; l'exe non lo incorpora.
- Firma del codice: l'exe non è firmato, quindi al primo avvio Windows
  SmartScreen può avvisare. È normale per i programmi non firmati.
