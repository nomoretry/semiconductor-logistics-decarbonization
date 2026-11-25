"""Export, submit, fetch and import verified DQ-3 Batch evidence."""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import time
from collections import defaultdict
from decimal import ROUND_CEILING, Decimal
from pathlib import Path
from uuid import uuid4

from .data import (
    LlmError,
    Record,
    Task,
    append_jsonl,
    canonical,
    digest,
    ensure_pilot_gate,
    pilot_reuse_path,
    plan,
    read_jsonl,
    response_path,
    root_lock,
    terminal_records,
)
from .transport import (
    MILLION,
    ApiError,
    Client,
    Ledger,
    Prices,
    api_error,
    decimal_amount,
    decode_response,
    redact,
)

ENDPOINT = "/v1/responses"
BATCH_FINAL = frozenset(("completed", "failed", "expired", "cancelled"))
BATCH_ACTIVE = frozenset(("validating", "in_progress", "finalizing", "cancelling"))
MAX_CHUNK = 250
MAX_FILE_BYTES = 200_000_000


def _export_line(task: Task) -> Record:
    return {"custom_id": task.custom_id, "method": "POST", "url": ENDPOINT, "body": task.body}


def _write_once(path: Path, payload: bytes) -> None:
    """Repeat an identical export without overwriting prior evidence."""
    if path.exists():
        if path.read_bytes() != payload:
            raise LlmError("Existing Batch evidence differs from the current export")
    else:
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_bytes(payload)
        temporary.replace(path)


def export_batches(config: Record, root: Path, *, phase: str, arm: str, size: str,
                   pilot_root: Path, chunk_size: int, prices: Prices) -> Record:
    if phase not in ("main", "p3") or not 1 <= chunk_size <= MAX_CHUNK:
        raise LlmError(f"Batch export requires main or p3 and a chunk size between 1 and {MAX_CHUNK}")
    tasks = plan(config, phase, arm, size)
    pilot_tasks = plan(config, "pilot", arm)
    pilot_root = pilot_root.resolve()

    with root_lock(root):
        if phase == "main":
            ensure_pilot_gate(config, pilot_root, arm)
        completed = terminal_records(root, tasks, pilot_root=pilot_root)
        if phase == "main" and pilot_root != root.resolve():
            snapshot = pilot_reuse_path(root, arm)
            prior = {(row["custom_id"], row["request_hash"]) for row in read_jsonl(snapshot)}
            for row in completed.values():
                key = (row["custom_id"], row["request_hash"])
                if row["phase"] == "pilot" and key not in prior:
                    append_jsonl(snapshot, row)
        active = active_batch_tasks(root)
        pending = [task for task in tasks if task.custom_id not in completed
                   and (task.custom_id, task.request_hash) not in active]
        pilot_rows = terminal_records(pilot_root, pilot_tasks)
        outputs = [row["usage"]["output_tokens"] for row in pilot_rows.values() if row.get("usage") is not None]
        mean_output = Decimal(sum(outputs)) / len(outputs) if outputs else None
        directory = root / "batches"
        directory.mkdir(exist_ok=True)
        chunks = []
        pilot_label = hashlib.sha256(str(pilot_root).encode("utf-8")).hexdigest()
        for start in range(0, len(pending), chunk_size):
            requests = pending[start:start + chunk_size]
            payload = b"".join(canonical(_export_line(task)) + b"\n" for task in requests)
            if len(payload) > MAX_FILE_BYTES:
                raise LlmError("Batch input exceeds 200 MB; reduce the chunk size")
            sha256 = hashlib.sha256(payload).hexdigest()
            name = f"input_{phase}_{arm}_{size}_{start // chunk_size + 1:03}_{sha256[:16]}_{pilot_label[:8]}.jsonl"
            path = directory / name
            manifest = path.with_suffix(".manifest.json")
            input_estimate = sum(task.input_tokens() for task in requests)
            maximum = sum(prices.worst(task) for task in requests)
            expected = None
            if mean_output is not None:
                expected = (input_estimate * prices.input + mean_output * len(requests) * prices.output) / MILLION
            index = {
                "phase": phase,
                "arm": arm,
                "size": size,
                "pilot_root": str(pilot_root),
                "input_file": path.name,
                "sha256": sha256,
                "requests": [{"custom_id": task.custom_id, "request_hash": task.request_hash} for task in requests],
            }
            _write_once(manifest, canonical(index) + b"\n")
            _write_once(path, payload)
            chunks.append({"file": str(path), "manifest": str(manifest), "sha256": sha256,
                           "requests": len(requests), "input_tokens_estimate": input_estimate,
                           "worst_usd": str(maximum), "expected_usd": str(expected) if expected is not None else None})
    return {"phase": phase, "arm": arm, "size": size, "planned": len(tasks),
            "reused": len(completed), "exported": len(pending), "chunks": chunks,
            "deferred_batch": len(tasks) - len(completed) - len(pending),
            "prices_usd_per_m": prices.as_dict(), "pilot_output_observations": len(outputs),
            "pilot_mean_output_tokens": str(mean_output) if mean_output is not None else None}


def _object(path: Path) -> Record:
    try:
        value = json.loads(path.read_bytes())
    except (OSError, ValueError) as error:
        raise LlmError(f"Cannot read Batch metadata: {path.name}") from error
    if not isinstance(value, dict):
        raise LlmError("Batch metadata must be a JSON object")
    return value


def _state(root: Path) -> Record:
    path = root / "batches" / "state.json"
    return _object(path) if path.exists() else {}


def _active_tasks(state: Record) -> set[tuple[str, str]]:
    return {(proof["custom_id"], proof["request_hash"])
            for record in state.values() if record["status"] not in ("rejected", "imported")
            for proof in record.get("requests", [])}


def active_batch_tasks(root: Path) -> set[tuple[str, str]]:
    """Identify exact requests with an unresolved local Batch submission."""
    return _active_tasks(_state(root))


def _save_state(root: Path, state: Record) -> None:
    directory = root / "batches"
    directory.mkdir(exist_ok=True)
    temporary = directory / "state.json.tmp"
    with temporary.open("wb") as file:
        file.write(canonical(state) + b"\n")
        file.flush()
        os.fsync(file.fileno())
    temporary.replace(directory / "state.json")


def _chunk(config: Record, root: Path, file: Path) -> tuple[Record, list[Task]]:
    file = file.resolve()
    if file.parent != (root / "batches").resolve() or not file.is_file():
        raise LlmError("Batch input must be a saved export in the results root")
    manifest = _object(file.with_suffix(".manifest.json"))
    if manifest["phase"] not in ("main", "p3") or manifest["arm"] not in config["arms"]:
        raise LlmError("Batch input scope differs from the protocol")
    if manifest["input_file"] != file.name or manifest["sha256"] != digest(file):
        raise LlmError("Batch input SHA256 mismatch")
    by_id = {task.custom_id: task for task in plan(config, manifest["phase"], manifest["arm"], manifest["size"])}
    rows = list(read_jsonl(file))
    if not 1 <= len(rows) <= MAX_CHUNK or file.stat().st_size > MAX_FILE_BYTES:
        raise LlmError("Batch input is empty or exceeds the file limits")
    selected = []
    seen = set()
    for row in rows:
        key = row.get("custom_id")
        task = by_id.get(key) if isinstance(key, str) else None
        if task is None or key in seen or canonical(row) != canonical(_export_line(task)):
            raise LlmError("Batch input does not match unique frozen requests")
        seen.add(key)
        selected.append(task)
    if manifest["requests"] != [{"custom_id": task.custom_id, "request_hash": task.request_hash}
                                for task in selected]:
        raise LlmError("Batch input request hashes mismatch")
    return manifest, selected


def _pilot_costs(config: Record, root: Path, arm: str, prices: Prices) -> list[Decimal]:
    pilot = terminal_records(root, plan(config, "pilot", arm))
    costs = sorted(prices.actual(row["usage"]) for row in pilot.values() if row.get("usage") is not None)
    if not costs:
        raise LlmError("Batch submission requires saved pilot responses with token usage")
    return costs


def _multipart(file: Path) -> tuple[bytes, str]:
    boundary = uuid4().hex
    payload = (f'--{boundary}\r\nContent-Disposition: form-data; name="purpose"\r\n\r\nbatch\r\n'
               f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{file.name}"\r\n'
               'Content-Type: application/octet-stream\r\n\r\n').encode()
    return payload + file.read_bytes() + f"\r\n--{boundary}--\r\n".encode("ascii"), (
        f"multipart/form-data; boundary={boundary}"
    )


def _resource_id(value: object) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", value) or value.startswith("sk-"):
        raise LlmError("Batch service returned an invalid resource identifier")
    return value


def _object_reply(raw: bytes) -> Record:
    try:
        reply = json.loads(raw)
    except ValueError:
        raise LlmError("Expected a Batch JSON reply") from None
    if not isinstance(reply, dict):
        raise LlmError("Expected a Batch JSON object")
    return reply


def _metadata(task: Task, prices: Prices) -> Record:
    return {"phase": task.phase, "arm": task.arm, "transport": "batch", "task_key": task.custom_id,
            "request_hash": task.request_hash, "prices": prices.as_dict()}


def _attempt(submission: str, task: Task) -> str:
    return f"batch:{submission}:{task.custom_id}"


def _recover_unsent(root: Path, state: Record, ledger: Ledger) -> None:
    interrupted = [record for record in state.values() if record["status"] == "reserving"]
    for record in interrupted:
        submission = record["submission_id"]
        for proof in record["requests"]:
            identifier = f"batch:{submission}:{proof['custom_id']}"
            if ledger.pending(identifier) is not None:
                ledger.settle(identifier, Decimal(0), {
                    "phase": record["phase"], "arm": record["arm"], "transport": "batch",
                    "task_key": proof["custom_id"], "request_hash": proof["request_hash"], "prices": record["prices"],
                    "outcome": "not_sent", "actual_usd": None, "error": "Interrupted before Batch creation",
                })
        record["status"] = "rejected"
    if interrupted:
        _save_state(root, state)


def submit_batch(config: Record, root: Path, *, file: Path, max_usd: Decimal, prices: Prices) -> Record:
    max_usd = decimal_amount(max_usd)
    with root_lock(root):
        manifest, tasks = _chunk(config, root, file)
        pilot_root = Path(manifest["pilot_root"])
        if manifest["phase"] == "main":
            ensure_pilot_gate(config, pilot_root, manifest["arm"])
        if terminal_records(root, tasks, pilot_root=pilot_root):
            raise LlmError("Batch input includes terminal responses; export the remaining requests again")
        state = _state(root)
        ledger = Ledger(root)
        _recover_unsent(root, state, ledger)
        selected = {(task.custom_id, task.request_hash) for task in tasks}
        if selected & _active_tasks(state):
            raise LlmError("Batch input overlaps a submitted or unresolved batch")
        costs = _pilot_costs(config, pilot_root, manifest["arm"], prices)
        rank = (Decimal("0.95") * len(costs)).to_integral_value(rounding=ROUND_CEILING)
        p95 = costs[int(rank) - 1]
        amount = p95 * len(tasks)
        if ledger.committed_total() + amount > max_usd:
            raise LlmError("Batch p95 reservation would exceed --max-usd")
        client = Client.from_env()
        payload, content_type = _multipart(file)
        upload = client.redact(_object_reply(client.request("POST", "files", payload, content_type)))
        input_file_id = _resource_id(upload.get("id"))
        submission = uuid4().hex
        record = {**manifest, "input_file_id": input_file_id, "prices": prices.as_dict(),
                  "status": "reserving", "submission_id": submission}
        state[submission] = record
        _save_state(root, state)
        for task in tasks:
            ledger.reserve(_attempt(submission, task), p95, _metadata(task, prices))
        record["status"] = "creating"
        _save_state(root, state)
        try:
            reply = client.redact(client.json("POST", "batches", {
                "input_file_id": input_file_id, "endpoint": ENDPOINT, "completion_window": "24h",
            }))
        except ApiError as error:
            if not error.unknown_charge:
                for task in tasks:
                    ledger.settle(_attempt(submission, task), Decimal(0), {
                        **_metadata(task, prices), "outcome": "submission_rejected", "actual_usd": None,
                        "error": str(error),
                    })
                record.update(status="rejected")
                _save_state(root, state)
            raise
        batch_id = _resource_id(reply.get("id"))
        _update_batch(record, reply, batch_id)
        _save_state(root, state)
        return {"batch_id": batch_id, "input_file_id": input_file_id, "status": record["status"],
                "requests": len(tasks), "pilot_cost_observations": len(costs),
                "pilot_p95_usd": str(p95), "reserved_usd": str(amount),
                "committed_usd": str(ledger.committed_total())}


def _update_batch(record: Record, reply: Record, batch_id: str) -> None:
    status = reply.get("status")
    input_file_id = _resource_id(reply.get("input_file_id"))
    if not isinstance(status, str) or reply.get("id") != batch_id or reply.get("endpoint") != ENDPOINT or (
        record.get("input_file_id", input_file_id) != input_file_id
    ) or status not in BATCH_ACTIVE | BATCH_FINAL:
        raise LlmError("Unexpected Batch status reply")
    record.update(batch_id=batch_id, input_file_id=input_file_id, status=status,
                  output_file_id=reply.get("output_file_id"), error_file_id=reply.get("error_file_id"),
                  provider_usage=reply.get("usage"), errors=reply.get("errors"),
                  request_counts=reply.get("request_counts"))


def _download(client: Client, directory: Path, record: Record) -> list[str]:
    files = []
    for kind in ("output", "error"):
        file_id = record[f"{kind}_file_id"]
        if file_id is None:
            continue
        file_id = _resource_id(file_id)
        raw = client.request("GET", f"files/{file_id}/content")
        try:
            rows = [client.redact(json.loads(line)) for line in raw.splitlines()]
            payload = b"".join(canonical(row) + b"\n" for row in rows)
        except (ValueError, RecursionError):
            raise LlmError("Invalid Batch output JSONL") from None
        path = directory / f"{record['batch_id']}_{kind}.jsonl"
        _write_once(path, payload)
        files.append(path.name)
    return files


def _fetch_once(root: Path, client: Client, batch_id: str | None) -> list[Record]:
    directory = root / "batches"
    state = _state(root)
    if batch_id is None:
        identifiers = [row["batch_id"] for row in state.values() if "batch_id" in row]
    else:
        identifiers = [_resource_id(client.redact(batch_id))]
    results = []
    for identifier in identifiers:
        reply = client.redact(client.json("GET", f"batches/{identifier}"))
        record = next((row for row in state.values() if row.get("batch_id") == identifier), None)
        if record is None:
            record = next((row for row in state.values() if row["status"] == "creating"
                           and row.get("input_file_id") == reply.get("input_file_id")), None)
        if record is None:
            record = {}
            state[identifier] = record
        if record.get("status") != "imported":
            _update_batch(record, reply, identifier)
        files = record.get("files", [])
        import_files = record.get("import_files", files)
        if reply["status"] in BATCH_FINAL and not import_files:
            directory.mkdir(exist_ok=True)
            files = _download(client, directory, record)
            import_files = files
            if not import_files and "input_file" in record:
                marker = directory / f"{identifier}_empty.jsonl"
                _write_once(marker, b"")
                import_files = [marker.name]
            record.update(files=files, import_files=import_files)
        _save_state(root, state)
        results.append({"batch_id": identifier, "status": reply["status"], "errors": record["errors"],
                        "request_counts": record["request_counts"], "usage": record["provider_usage"],
                        "files": [str(directory / name) for name in files],
                        "import_files": [str(directory / name) for name in import_files]})
    return results


def fetch_batches(root: Path, *, batch_id: str | None = None, wait_seconds: float = 0,
                  poll_interval: float = 60) -> Record:
    if not math.isfinite(wait_seconds) or not math.isfinite(poll_interval) or wait_seconds < 0 or poll_interval <= 0:
        raise LlmError("Batch polling requires a nonnegative wait and a positive interval")
    client = Client.from_env()
    deadline = time.monotonic() + wait_seconds
    while True:
        with root_lock(root):
            batches = _fetch_once(root, client, batch_id)
        outstanding = any(row["status"] in BATCH_ACTIVE for row in batches)
        remaining = deadline - time.monotonic()
        if not outstanding or remaining <= 0:
            return {"batches": batches, "wait_expired": outstanding and wait_seconds > 0}
        time.sleep(min(poll_interval, remaining))


def _import_groups(root: Path, files: list[Path], state: Record) -> dict[str, list[Path]]:
    directory = root / "batches"
    associations = {(directory / name).resolve(): key for key, record in state.items()
                    for name in record.get("import_files", [])}
    groups: dict[str, list[Path]] = defaultdict(list)
    for file in files:
        path = file.resolve()
        if not path.is_file():
            raise LlmError("A supplied Batch result file does not exist")
        groups[associations.get(path, "")].append(path)
    for key, paths in groups.items():
        if key and set(paths) != {(directory / name).resolve() for name in state[key]["import_files"]}:
            raise LlmError("Provide all downloaded files of each Batch together")
    return groups


def _manual_input(root: Path, rows: list[Record]) -> Path:
    # A manual upload can only be replayed when exact IDs identify one exported chunk.
    supplied = {row["custom_id"] for row in rows if isinstance(row.get("custom_id"), str)}
    matches = []
    known = set()
    for path in sorted((root / "batches").glob("input_*.manifest.json")):
        manifest = _object(path)
        keys = {proof["custom_id"] for proof in manifest["requests"]}
        known.update(keys)
        matches.append((keys, (manifest["phase"], manifest["sha256"]), path.with_name(manifest["input_file"])))
    wanted = supplied & known
    if not wanted:
        raise LlmError("No Batch result ID belongs to a saved input chunk: " + json.dumps(sorted(supplied)))
    matched = {proof: path for keys, proof, path in matches if wanted <= keys}
    if len(matched) != 1:
        raise LlmError("Manual results must identify one saved Batch input chunk; import each output/error pair together")
    return next(iter(matched.values()))


def _decode_row(task: Task, row: Record, prices: Prices) -> Record:
    response, failure = row.get("response"), row.get("error")
    if response is None and isinstance(failure, dict):
        error = api_error(failure)
        decoded = decode_response(task, None, prices, transport="batch", error=error)
        decoded.update(error_code=error.code)
        return decoded
    if not isinstance(response, dict) or failure is not None:
        raise LlmError("Unexpected Batch result response/error envelope")
    status, body = response.get("status_code"), response.get("body")
    if type(status) is not int or not isinstance(body, dict):
        raise LlmError("Unexpected Batch result HTTP status or body")
    error = None if 200 <= status < 300 else api_error(body, status_code=status)
    decoded = decode_response(task, body, prices, transport="batch", error=error)
    decoded.update(http_status=status, request_id=response.get("request_id"))
    if error:
        decoded.update(error_code=error.code)
    return decoded


def _usage_check(record: Record, usage: list[Record], check_path: Path) -> Record | None:
    provider = record.get("provider_usage")
    if provider is None:
        return None
    from_rows = {field: sum(item[field] for item in usage)
                 for field in ("input_tokens", "cached_tokens", "output_tokens", "reasoning_tokens")}
    from_rows["total_tokens"] = from_rows["input_tokens"] + from_rows["output_tokens"]
    reported = {"input_tokens": provider.get("input_tokens"),
                "cached_tokens": (provider.get("input_tokens_details") or {}).get("cached_tokens"),
                "output_tokens": provider.get("output_tokens"),
                "reasoning_tokens": (provider.get("output_tokens_details") or {}).get("reasoning_tokens"),
                "total_tokens": provider.get("total_tokens")}
    check = {"batch_id": record["batch_id"], "phase": record["phase"], "arm": record["arm"],
             "reported": reported, "from_rows": from_rows, "matches": reported == from_rows}
    if check not in read_jsonl(check_path):
        append_jsonl(check_path, check)
    return check


def _record_import(root: Path, task: Task, row: Record, prices: Prices, ledger: Ledger,
                   attempt_id: str, row_hash: str, seen: dict[str, str]) -> bool:
    if attempt_id in seen:
        if seen[attempt_id] != row_hash:
            raise LlmError("Conflicting Batch evidence for an imported result")
        return False
    amount = Decimal(row["actual_usd"]) if row["actual_usd"] is not None else Decimal(0)
    row.update(batch_attempt_id=attempt_id, batch_result_sha256=row_hash, charged_usd=str(amount),
               usage_status="reported" if row["usage"] is not None else "service_unreported")
    ledger.settle(attempt_id, amount, {
        **_metadata(task, prices), "outcome": row["status"], "actual_usd": row["actual_usd"],
        "error": row["error"], "usage_status": row["usage_status"],
    })
    append_jsonl(response_path(root, task.phase, task.arm), row)
    seen[attempt_id] = row_hash
    return True


def _import_group(config: Record, root: Path, paths: list[Path], prices: Prices, ledger: Ledger,
                  record: Record) -> Record:
    rows = [redact(row) for path in dict.fromkeys(paths) for row in read_jsonl(path)]
    file = root / "batches" / record["input_file"] if "input_file" in record else _manual_input(root, rows)
    manifest, tasks = _chunk(config, root, file)
    if record.get("prices") is not None and any(
            Decimal(rate) != Decimal(record["prices"][field]) for field, rate in prices.as_dict().items()):
        raise LlmError("Batch import rates differ from the submitted rates")
    scope = response_path(root, manifest["phase"], manifest["arm"])
    saved_rows = [row for row in read_jsonl(scope) if "batch_attempt_id" in row]
    saved = {row["batch_attempt_id"]: row["batch_result_sha256"] for row in saved_rows}
    prior_results = {row["batch_result_id"]: row for row in saved_rows if row["batch_result_id"] is not None}
    by_id = {task.custom_id: task for task in tasks}
    received = set()
    unknown = []
    duplicates = []
    usage = []
    imported = already_imported = 0
    submission = record.get("submission_id")
    identity = record.get("batch_id")
    for row in rows:
        key = row.get("custom_id")
        if not isinstance(key, str):
            raise LlmError("Batch result row has no valid custom_id")
        if key not in by_id:
            unknown.append(key)
            continue
        if key in received:
            duplicates.append(key)
            continue
        received.add(key)
        result_id = _resource_id(row.get("id"))
        task = by_id[key]
        attempt = _attempt(submission, task) if submission else f"batch-result:{result_id}"
        decoded = _decode_row(task, row, prices)
        decoded.update(batch_id=identity, batch_result_id=result_id)
        if decoded["usage"] is not None:
            usage.append(decoded["usage"])
        row_hash = hashlib.sha256(canonical(row)).hexdigest()
        prior = prior_results.get(result_id)
        if prior is not None and prior["batch_attempt_id"] != attempt:
            if prior["batch_result_sha256"] != row_hash or prior["request_hash"] != task.request_hash:
                raise LlmError("Conflicting Batch evidence for an imported result")
            if ledger.pending(attempt) is not None:
                ledger.settle(attempt, Decimal(0), {
                    **_metadata(task, prices), "outcome": "already_imported", "actual_usd": None,
                    "error": None, "usage_status": "previously_settled",
                })
            already_imported += 1
            continue
        added = _record_import(root, task, decoded, prices, ledger, attempt, row_hash, saved)
        imported += added
        already_imported += not added
    missing = [key for key in by_id if key not in received]
    for key in missing:
        task = by_id[key]
        reason = "Batch input request is absent from the supplied output and error files"
        decoded = decode_response(task, None, prices, transport="batch", attempts=0, error=reason)
        decoded.update(batch_id=identity, batch_result_id=None)
        attempt = _attempt(submission, task) if submission else f"batch-missing:{manifest['sha256']}:{key}"
        proof = hashlib.sha256(canonical({"missing": key, "input": manifest["sha256"]})).hexdigest()
        added = _record_import(root, task, decoded, prices, ledger, attempt, proof, saved)
        imported += added
        already_imported += not added
    check_record = {**record, "phase": manifest["phase"], "arm": manifest["arm"]}
    comparison = _usage_check(check_record, usage, root / "batches" / "usage_checks.jsonl")
    return {"imported": imported, "already_imported": already_imported, "unknown": unknown,
            "duplicates": duplicates, "missing": missing, "usage_comparison": comparison}


def import_batches(config: Record, root: Path, *, files: list[Path], prices: Prices) -> Record:
    if not files:
        raise LlmError("Supply at least one Batch result file")
    with root_lock(root):
        state = _state(root)
        groups = _import_groups(root, files, state)
        ledger = Ledger(root)
        results = []
        for key, paths in groups.items():
            record = state.get(key, {})
            results.append(_import_group(config, root, paths, prices, ledger, record))
            if key:
                record["status"] = "imported"
                _save_state(root, state)
    return {"imported": sum(row["imported"] for row in results),
            "already_imported": sum(row["already_imported"] for row in results),
            "unknown": [key for row in results for key in row["unknown"]],
            "duplicates": [key for row in results for key in row["duplicates"]],
            "missing": [key for row in results for key in row["missing"]],
            "usage_comparisons": [row["usage_comparison"] for row in results if row["usage_comparison"] is not None],
            "committed_usd": str(ledger.committed_total())}
