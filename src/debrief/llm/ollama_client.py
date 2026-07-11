"""Thin wrapper around a local Ollama server. Imported only by narrative.py
(the --no-llm path never touches this module or the `ollama` package),
and only ever talks to localhost -- see OllamaClient's docstring.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

DEFAULT_HOST = "http://127.0.0.1:11434"
DEFAULT_TIMEOUT_S = 120


class OllamaUnavailableError(RuntimeError):
    pass


@dataclass
class GenerationResult:
    text: str
    model: str
    total_duration_s: float
    eval_count: int


class OllamaClient:
    """Talks only to a local Ollama server (default 127.0.0.1:11434,
    overridable via host= for e.g. a different WSL/container address, but
    never a remote/cloud endpoint) -- this is the one module in the repo
    that makes a network call at all, and it never leaves localhost.
    """

    def __init__(self, host: str = DEFAULT_HOST):
        import ollama  # deferred: --no-llm mode must not require this package installed

        self._client = ollama.Client(host=host)
        self.host = host

    def is_available(self) -> bool:
        try:
            self._client.list()
            return True
        except Exception:
            return False

    def has_model(self, model: str) -> bool:
        try:
            names = {m.model for m in self._client.list().models}
        except Exception:
            return False
        return model in names or f"{model}:latest" in names

    def list_models(self) -> list[str]:
        """Model tags actually pulled on this machine, for populating a
        picker -- never a hardcoded guess at what's installed.
        """
        try:
            return sorted(m.model for m in self._client.list().models)
        except Exception:
            return []

    def generate_json(self, model: str, prompt: str, timeout_s: float = DEFAULT_TIMEOUT_S) -> dict:
        import time

        t0 = time.perf_counter()
        try:
            resp = self._client.generate(
                model=model,
                prompt=prompt,
                format="json",
                options={"temperature": 0.2},
            )
        except Exception as e:
            raise OllamaUnavailableError(f"Ollama generate() failed for model {model!r}: {e}") from e
        dt = time.perf_counter() - t0

        try:
            parsed = json.loads(resp.response)
        except json.JSONDecodeError as e:
            raise OllamaUnavailableError(
                f"model {model!r} did not return valid JSON (first 200 chars): {resp.response[:200]!r}"
            ) from e

        parsed["_meta"] = GenerationResult(
            text=resp.response,
            model=model,
            total_duration_s=dt,
            eval_count=getattr(resp, "eval_count", 0) or 0,
        )
        return parsed
