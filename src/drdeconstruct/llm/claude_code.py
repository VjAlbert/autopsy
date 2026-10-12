"""Motore Claude Code: usa la CLI `claude` con il login claude.ai dell'utente.

Nessuna chiave API: la CLI viene lanciata in modalità headless (`-p`) con
tutti gli strumenti disattivati, così il codice analizzato (non fidato) non
può far eseguire nulla al modello. Consuma i limiti dell'abbonamento.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections.abc import Callable
from typing import Any

from drdeconstruct.core.errors import BackendError, RefusalError
from drdeconstruct.llm.base import T, parse_json_into

Runner = Callable[..., subprocess.CompletedProcess]


class ClaudeCodeBackend:
    name = "claude-code"

    def __init__(
        self,
        model: str | None = None,
        executable: str = "claude",
        timeout: float = 600,
        runner: Runner = subprocess.run,
    ):
        self.model = model
        self.executable = executable
        self.timeout = timeout
        self._run = runner

    def _command(self, system: str, schema_json: str) -> list[str]:
        exe = shutil.which(self.executable) or self.executable
        cmd = [
            exe,
            "-p",
            "--output-format",
            "json",
            "--json-schema",
            schema_json,
            "--system-prompt",
            system,
            "--tools",
            "",
            "--strict-mcp-config",
            "--no-session-persistence",
        ]
        if self.model:
            cmd += ["--model", self.model]
        return cmd

    @staticmethod
    def _env() -> dict[str, str]:
        # Senza chiave API nell'ambiente la CLI usa il login dell'abbonamento.
        env = dict(os.environ)
        env.pop("ANTHROPIC_API_KEY", None)
        return env

    def structured(self, system: str, user: str, schema: type[T]) -> T:
        schema_json = json.dumps(schema.model_json_schema(), ensure_ascii=False)
        try:
            proc = self._run(
                self._command(system, schema_json),
                input=user,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                env=self._env(),
            )
        except FileNotFoundError as exc:
            raise BackendError(
                "CLI `claude` non trovata: installa Claude Code ed esegui `claude` una volta "
                "per fare il login."
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise BackendError(f"Claude Code non ha risposto entro {self.timeout}s.") from exc

        if proc.returncode != 0:
            raise BackendError(f"Claude Code è uscito con codice {proc.returncode}: {proc.stderr}")

        try:
            payload: dict[str, Any] = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            raise BackendError(f"Output di Claude Code non è JSON: {proc.stdout[:500]}") from exc

        if payload.get("is_error"):
            text = str(payload.get("result", ""))
            if "refus" in text.lower():
                raise RefusalError(text)
            raise BackendError(f"Claude Code ha segnalato un errore: {text}")

        structured = payload.get("structured_output")
        if isinstance(structured, dict):
            return schema.model_validate(structured)
        return parse_json_into(str(payload.get("result", "")), schema)
