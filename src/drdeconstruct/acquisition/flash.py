"""Backup, lettura e aggiornamento della memoria flash tramite `flashrom`.

`flashrom` è un programma esterno che parla con il chip attraverso un
programmatore USB. Qui lo pilotiamo con regole fisse: prima si fa sempre un
backup dell'originale, poi si verifica la nuova immagine, e si aggiorna solo
con la conferma esplicita dell'operatore. Niente di tutto questo scrive nulla
senza passare da `safety.WriteGuard`.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

from drdeconstruct.acquisition.models import MemoryImage
from drdeconstruct.acquisition.safety import WriteGuard, sha256, verify_readback
from drdeconstruct.config import NO_WINDOW
from drdeconstruct.core.errors import DrDeconstructError, SafetyError

Runner = Callable[..., subprocess.CompletedProcess]


class FlashTool:
    """Involucro attorno a `flashrom` con backup e verifica obbligatori."""

    def __init__(self, programmer: str, chip: str | None = None, runner: Runner = subprocess.run):
        # Es. programmer="ch341a_spi"; chip rilevato in automatico se None.
        self.programmer = programmer
        self.chip = chip
        self._run = runner

    def _base_cmd(self) -> list[str]:
        cmd = ["flashrom", "-p", self.programmer]
        if self.chip:
            cmd += ["-c", self.chip]
        return cmd

    def _exec(self, args: list[str]) -> str:
        try:
            proc = self._run(
                self._base_cmd() + args, capture_output=True, text=True, timeout=600, **NO_WINDOW
            )
        except FileNotFoundError as exc:
            raise DrDeconstructError(
                "`flashrom` non trovato: installalo (flashrom.org) e collega il programmatore."
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise DrDeconstructError("flashrom non ha risposto in tempo.") from exc
        if proc.returncode != 0:
            raise DrDeconstructError(f"flashrom ha fallito: {proc.stderr.strip()}")
        return proc.stdout

    def backup(self, path: Path) -> MemoryImage:
        """Legge l'intero contenuto e lo salva su file: è il punto di ripristino."""
        self._exec(["-r", str(path)])
        data = Path(path).read_bytes()
        if not data:
            raise DrDeconstructError("Backup vuoto: controlla il collegamento del programmatore.")
        return MemoryImage(data=data, source=str(path), sha256=sha256(data))

    def read(self, path: Path) -> MemoryImage:
        """Alias di backup, con un nome che dice solo 'leggi'."""
        return self.backup(path)

    def update(self, new_image: Path, guard: WriteGuard, readback_path: Path | None = None) -> None:
        """Aggiorna la flash solo se i controlli di sicurezza passano.

        `guard` deve avere backup_done=True e confirmed=True. Dopo la scrittura
        rilegge il chip e verifica che coincida con l'immagine scritta.
        """
        image = Path(new_image).read_bytes()
        guard.check(image)  # alza SafetyError se mancano backup o conferma

        self._exec(["-w", str(new_image)])

        if readback_path is not None:
            self._exec(["-r", str(readback_path)])
            verify_readback(image, Path(readback_path).read_bytes())
        else:
            raise SafetyError("Aggiornamento senza rilettura di verifica non consentito.")
