"""Run the preregistered evaluation through synchronous Responses calls."""
from __future__ import annotations

import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from .data import (
    TERMINAL,
    LlmError,
    Record,
    Task,
    append_jsonl,
    ensure_pilot_gate,
    load_config,
    response_path,
    root_lock,
    terminal_records,
    utc_now,
)
from .transport import (
    ApiError,
    Client,
    Ledger,
    Prices,
    api_error,
    decimal_amount,
    decode_response,
)

MAX_ATTEMPTS = 3
# Prices assume the Standard tier. A call served on another tier is booked at this multiple of its
# Standard cost, the highest multiplier in the price list, and dispatch stops (protocol amendment 1).
TIER_BOUND = 6


def run(root: Path, tasks: list[Task], prices: Prices, *, max_usd: Decimal, max_calls: int | None = None,
        workers: int = 8, timeout: float = 3600, config: Record | None = None) -> Record:
    if not 1 <= workers <= 32:
        raise LlmError("Workers must be between 1 and 32")
    if max_calls is not None and max_calls < 0:
        raise LlmError("Maximum calls must be nonnegative")
    max_usd = decimal_amount(max_usd)
    client = Client.from_env(timeout)
    with root_lock(root):
        pilot_gate = None
        if tasks and tasks[0].phase == "main":
            pilot_gate = ensure_pilot_gate(config if config is not None else load_config(), root, tasks[0].arm)
        result = _run(root, tasks, prices, max_usd, max_calls, workers, client)
        if pilot_gate is not None:
            result["pilot_gate"] = pilot_gate
        return result


def _run(root: Path, tasks: list[Task], prices: Prices, max_usd: Decimal, max_calls: int | None,
         workers: int, client: Client) -> Record:
    ledger = Ledger(root)
    completed = terminal_records(root, tasks)
    remaining = (task for task in tasks if task.custom_id not in completed)
    reused = sum(row["phase"] == "pilot" for row in completed.values()) if tasks and tasks[0].phase == "main" else 0
    counters: Counter[str] = Counter()
    stop_signal = threading.Event()
    stop_reason: str | None = None
    calls = 0

    def stop(reason: str) -> None:
        nonlocal stop_reason
        if stop_reason is None:
            stop_reason = reason
        stop_signal.set()

    def reserve(task: Task) -> tuple[str, Decimal, Record] | None:
        nonlocal calls
        if stop_signal.is_set():
            return None
        if max_calls is not None and calls >= max_calls:
            stop("max_calls")
            return None
        amount = prices.worst(task)
        if ledger.committed_total() + amount > max_usd:
            stop("max_usd")
            return None
        attempt_id = uuid4().hex
        fields: Record = {"phase": task.phase, "arm": task.arm, "transport": "sync", "task_key": task.custom_id,
                          "request_hash": task.request_hash, "prices": prices.as_dict()}
        ledger.reserve(attempt_id, amount, fields)
        calls += 1
        return attempt_id, amount, fields

    def execute(task: Task, reservation: tuple[str, Decimal, Record]) -> None:
        start = utc_now()
        started = time.perf_counter()
        charged = Decimal(0)
        result: Record = {}
        for index in range(1, MAX_ATTEMPTS + 1):
            attempt_id, reserved, metadata = reservation
            error = None
            raw = None
            try:
                raw = client.json("POST", "responses", task.body)
                if raw.get("error"):
                    error = api_error(client.redact(raw))
            except ApiError as problem:
                error = problem
            result = decode_response(task, client.redact(raw), prices, transport="sync", attempts=index,
                                     started_at=start, finished_at=utc_now(), seconds=time.perf_counter() - started,
                                     error=error)
            actual = result["actual_usd"]
            charge = Decimal(actual) if actual is not None else Decimal(0)
            if actual is None and (error is None or error.unknown_charge or (raw is not None and not error.stop)):
                charge = reserved
            tier = result["service_tier"]
            tier_mismatch = tier is not None and tier != task.body.get("service_tier", "default")
            if tier_mismatch:
                charge *= TIER_BOUND
                result.update(service_tier_mismatch=True)
            charged += charge
            if error is not None:
                result.update(http_status=error.status_code, error_code=error.code)
            with ledger.lock:
                if error is not None and error.stop:
                    stop(error.code or f"http_{error.status_code}")
                if tier_mismatch:
                    stop("service_tier")
                ledger.settle(attempt_id, charge, {**metadata, "outcome": result["status"], "actual_usd": actual,
                                                   "error": result["error"], "http_status": result.get("http_status"),
                                                   "error_code": result.get("error_code"), "service_tier": tier})
            if error is None or not error.retryable or index == MAX_ATTEMPTS:
                break
            delay = error.retry_after if error.retry_after is not None else 2 ** (index - 1)
            if stop_signal.wait(delay):
                break
            with ledger.lock:
                next_reservation = reserve(task)
            if next_reservation is None:
                break
            reservation = next_reservation
        result.update(charged_usd=str(charged), finished_at=utc_now(), seconds=time.perf_counter() - started)
        with ledger.lock:
            append_jsonl(response_path(root, task.phase, task.arm), result)
            counters[result["status"]] += 1

    def worker() -> None:
        while not stop_signal.is_set():
            with ledger.lock:
                task = next(remaining, None)
                if task is None:
                    return
                reservation = reserve(task)
            if reservation is None:
                return
            execute(task, reservation)

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(worker) for _ in range(workers)]
        try:
            for future in futures:
                future.result()
        except BaseException:
            with ledger.lock:
                stop("worker_failure")
            raise

    new_terminal = sum(counters[name] for name in TERMINAL)
    outstanding = len(tasks) - len(completed) - new_terminal
    return {"planned": len(tasks), "previous": len(completed) - reused, "reused": reused, "attempted": calls,
            "remaining": outstanding, "statuses": dict(counters), "committed_usd": str(ledger.committed_total()),
            "stop_reason": stop_reason, "status": "stopped" if stop_reason else "incomplete" if outstanding else "complete"}
