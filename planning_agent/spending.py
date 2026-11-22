"""Hard limits on model spending, enforced before a request is sent.

Comparing usage with a budget after the reply arrives cannot stop anything: the money is already spent. Here each
request first reserves its worst case, an upper bound on its input plus the output cap sent with it, and is refused
if that could pass a limit. The reported usage replaces the reservation when the reply comes. If the reply never
says (timeout, server error, no usage field, crash) the reservation stays charged.

Limits come only from the environment or the caller; there are no built-in defaults, so a missing budget means no
call. The ledger file holds counts and prices, never prompts, replies or credentials.
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class LLMError(RuntimeError):
    pass


class BudgetExceeded(LLMError):
    """A limit would be passed; the request was not sent."""


def input_bound(payload: bytes) -> int:
    """Upper bound on the input tokens of a request body: a token covers at least one byte, plus message framing."""
    return len(payload) + 64


@dataclass(frozen=True)
class Limits:
    max_requests: int  # HTTP requests sent, retries and fallbacks included
    max_total_tokens: int  # input + output, over everything this meter counts
    max_output_tokens: int  # per request; sent to the provider as its output cap
    max_input_tokens: int | None = None  # per request, against the upper bound
    max_usd: float | None = None
    input_usd_per_m: float | None = None
    output_usd_per_m: float | None = None

    def __post_init__(self) -> None:
        for name in ("max_requests", "max_total_tokens", "max_output_tokens"):
            if getattr(self, name) <= 0:
                raise LLMError(f"{name} must be positive")
        if self.max_usd is not None and (self.input_usd_per_m is None or self.output_usd_per_m is None):
            raise LLMError("a USD limit needs LLM_INPUT_USD_PER_M and LLM_OUTPUT_USD_PER_M")

    def cost(self, input_tokens: int, output_tokens: int) -> float:
        if self.input_usd_per_m is None or self.output_usd_per_m is None:
            return 0.0
        return (input_tokens * self.input_usd_per_m + output_tokens * self.output_usd_per_m) / 1_000_000


REQUIRED_LIMITS = {"max_requests": "MAX_REQUESTS", "max_total_tokens": "MAX_TOTAL_TOKENS",
                   "max_output_tokens": "MAX_OUTPUT_TOKENS"}


def limits_from_env(prefix: str = "LLM_", **overrides: Any) -> Limits:
    """Read limits from the environment; raise LLMError naming whatever is missing or not a number."""
    def read(name: str, kind: type, *, shared: bool = False) -> Any:
        variable = f"{'LLM_' if shared else prefix}{name}"
        raw = os.getenv(variable)
        if raw in (None, ""):
            return None
        try:
            return kind(raw)
        except ValueError:
            raise LLMError(f"{variable} must be a number") from None

    values: dict[str, Any] = {field: read(name, int) for field, name in REQUIRED_LIMITS.items()}
    values.update(max_input_tokens=read("MAX_INPUT_TOKENS", int), max_usd=read("MAX_USD", float),
                  input_usd_per_m=read("INPUT_USD_PER_M", float, shared=True),
                  output_usd_per_m=read("OUTPUT_USD_PER_M", float, shared=True))
    values.update({k: v for k, v in overrides.items() if v is not None})
    missing = [f"{prefix}{name}" for field, name in REQUIRED_LIMITS.items() if values[field] is None]
    if missing:
        raise LLMError("no spending limit configured: set " + ", ".join(missing))
    return Limits(**values)


class Meter:
    """Running totals against one set of limits, shared by every client that holds this object.

    With a path the totals live in a JSON-lines ledger, so they survive a restart and carry over to later runs; the
    file is read again before each reservation. A reservation is written before the request goes out, so a crash
    leaves it charged. An unreadable ledger refuses further calls. Two processes writing at the same moment can pass
    a limit by one reservation; a single web process or sequential command-line runs cannot.
    """

    def __init__(self, limits: Limits, path: Path | str | None = None, *, daily: bool = False,
                 clock: Callable[[], float] = time.time) -> None:
        self.limits, self.path, self.daily, self.clock = limits, Path(path) if path else None, daily, clock
        self.stopped: str | None = None
        self._entries: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def _today(self) -> str:
        return datetime.fromtimestamp(self.clock(), UTC).date().isoformat()

    def _load(self) -> None:
        if not self.path or not self.path.exists():
            return
        entries: dict[str, dict[str, Any]] = {}
        for number, line in enumerate(self.path.read_text(encoding="utf-8").splitlines(), 1):
            try:
                row = json.loads(line)
                entries[row["id"]] = row
            except (ValueError, KeyError, TypeError):
                raise LLMError(f"spending ledger {self.path.name} line {number} is unreadable; "
                               "refusing to call the model") from None
        self._entries = {k: v for k, v in entries.items() if not v.get("cancelled")}

    def _record(self, row: dict[str, Any]) -> None:
        if row.get("cancelled"):
            self._entries.pop(row["id"], None)
        else:
            self._entries[row["id"]] = row
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(row) + "\n")

    def _counted(self) -> list[dict[str, Any]]:
        today = self._today()
        return [e for e in self._entries.values() if not self.daily or e["day"] == today]

    def reserve(self, input_tokens: int, output_cap: int | None = None) -> str:
        """Hold the worst case of one request, or raise BudgetExceeded so that it is never sent."""
        limits = self.limits
        output_cap = limits.max_output_tokens if output_cap is None else output_cap
        with self._lock:
            self._load()
            counted = self._counted()
            tokens = sum(e["tokens"] for e in counted)
            usd = sum(e["usd"] for e in counted)
            need, price = input_tokens + output_cap, limits.cost(input_tokens, output_cap)
            if limits.max_input_tokens and input_tokens > limits.max_input_tokens:
                raise BudgetExceeded(f"request input bound {input_tokens:,} is above the per-request limit "
                                     f"{limits.max_input_tokens:,}; not sent")
            problem = None
            if len(counted) >= limits.max_requests:
                problem = f"request limit {limits.max_requests:,} reached"
            elif tokens + need > limits.max_total_tokens:
                problem = (f"token limit {limits.max_total_tokens:,}: {tokens:,} used and this request "
                           f"could use {need:,} more")
            elif limits.max_usd is not None and usd + price > limits.max_usd:
                problem = f"USD limit {limits.max_usd}: {usd:.4f} used and this request could cost {price:.4f} more"
            if problem:
                self.stopped = problem
                raise BudgetExceeded(f"{problem}; not sent")
            hold = uuid.uuid4().hex
            self._record({"id": hold, "day": self._today(), "time": round(self.clock(), 3), "state": "reserved",
                          "reserved": need, "tokens": need, "usd": price})
            return hold

    def settle(self, hold: str, input_tokens: int, output_tokens: int) -> None:
        """Replace a reservation with what the provider reported."""
        with self._lock:
            row = {**self._entries[hold], "state": "settled", "input": input_tokens, "output": output_tokens,
                   "tokens": input_tokens + output_tokens, "usd": self.limits.cost(input_tokens, output_tokens)}
            self._record(row)

    def cancel(self, hold: str) -> None:
        """Forget a reservation whose request was never sent."""
        with self._lock:
            self._record({"id": hold, "cancelled": True})

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            self._load()
            counted = self._counted()
        return {"requests": len(counted), "tokens": sum(e["tokens"] for e in counted),
                "usd": round(sum(e["usd"] for e in counted), 6),
                "unconfirmed_requests": sum(e["state"] == "reserved" for e in counted),
                "overrun_tokens": sum(max(0, e["tokens"] - e["reserved"]) for e in counted),
                "limit_requests": self.limits.max_requests, "limit_tokens": self.limits.max_total_tokens,
                "limit_usd": self.limits.max_usd, "window": "today (UTC)" if self.daily else "all"}


def reserve_all(meters: Sequence[Meter], input_tokens: int, output_cap: int) -> list[tuple[Meter, str]]:
    """Reserve on every meter or on none."""
    held: list[tuple[Meter, str]] = []
    try:
        for meter in meters:
            held.append((meter, meter.reserve(input_tokens, output_cap)))
    except LLMError:
        for meter, hold in held:
            meter.cancel(hold)
        raise
    return held
