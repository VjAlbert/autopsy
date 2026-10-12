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
        fallback_model: str | None = None,
    ):
        self.model = model
        self.executable = executable
        self.timeout = timeout
        self._run = runner
        self.fallback_model = fallback_model
        self.last_model: str | None = None

    def _command(self, system: str, schema_json: str, model: str | None) -> list[str]:
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
        if model:
            cmd += ["--model", model]
        return cmd

    @staticmethod
    def _env() -> dict[str, str]:
        # Senza chiave API nell'ambiente la CLI usa il login dell'abbonamento.
        env = dict(os.environ)
        env.pop("ANTHROPIC_API_KEY", None)
        return env

    def structured(self, system: str, user: str, schema: type[T]) -> T:
        """Esegue la richiesta; se il modello rifiuta, riprova una volta col modello di riserva."""
        schema_json = json.dumps(schema.model_json_schema(), ensure_ascii=False)
        try:
            result = self._once(system, user, schema, schema_json, self.model)
            self.last_model = self.model
            return result
        except RefusalError as first:
            if not self.fallback_model or self.fallback_model == self.model:
                raise
            try:
                result = self._once(system, user, schema, schema_json, self.fallback_model)
            except RefusalError as second:
                raise RefusalError(f"Rifiutata anche da {self.fallback_model}: {second}") from first
            self.last_model = self.fallback_model
            return result

    def _once(
        self, system: str, user: str, schema: type[T], schema_json: str, model: str | None
    ) -> T:
        try:
            proc = self._run(
                self._command(system, schema_json, model),
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

        structured = payload.get("structured_output")
        if isinstance(structured, dict) and not payload.get("is_error"):
            return schema.model_validate(structured)
        # Nessun output utile: un rifiuto si riconosce dai campi strutturati del
        # risultato, non cercando parole nel testo.
        if payload.get("stop_reason") == "refusal" or payload.get("safety_stops", 0):
            raise RefusalError(str(payload.get("result", "")) or "richiesta rifiutata")
        if payload.get("is_error"):
            raise BackendError(f"Claude Code ha segnalato un errore: {payload.get('result', '')}")
        return parse_json_into(str(payload.get("result", "")), schema)
