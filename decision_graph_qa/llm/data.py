"""Load the frozen protocol and prompts, and plan reproducible requests."""
from __future__ import annotations

import hashlib
import json
import os
import random
import re
from collections import defaultdict
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import ROUND_CEILING, Decimal
from pathlib import Path
from typing import Any, BinaryIO

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ROOT = ROOT / "benchmark_results" / "decision_graph_qa_llm_v1"
PROTOCOL = ROOT / "docs" / "decision_graph_qa_llm_protocol.md"
TERMINAL = frozenset(("ok", "parse_failure", "truncated"))

Record = dict[str, Any]


class LlmError(RuntimeError):
    """A runner precondition or evidence check failed."""


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def digest(path: Path) -> str:
    with path.open("rb") as file:
        hash_value = hashlib.sha256()
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            hash_value.update(chunk)
    return hash_value.hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_jsonl(path: Path) -> Iterator[Record]:
    if not path.exists():
        return
    with path.open(encoding="utf-8") as file:
        for line_number, line in enumerate(file, 1):
            try:
                row = json.loads(line)
            except ValueError:
                raise LlmError(f"{path.name}:{line_number}: invalid JSON record") from None
            if not isinstance(row, dict):
                raise LlmError(f"{path.name}:{line_number}: expected a JSON object")
            yield row


def append_jsonl(path: Path, row: Record) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("ab") as file:
        file.write(canonical(row) + b"\n")
        file.flush()
        os.fsync(file.fileno())


def _lock_file(file: BinaryIO) -> None:
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl

        fcntl.flock(file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


@contextmanager
def root_lock(root: Path) -> Iterator[None]:
    """Serialize writers to a result root, releasing the lock on process exit."""
    root.mkdir(parents=True, exist_ok=True)
    with (root / ".lock").open("a+b") as file:
        file.seek(0)
        try:
            _lock_file(file)
        except OSError:
            raise LlmError("The results root is already in use or cannot be locked") from None
        yield


def load_config() -> Record:
    path = DEFAULT_ROOT / "protocol_config.json"
    payload = path.read_bytes()
    found = re.findall(r"^Protocol config SHA256: ([a-f0-9]{64})$", PROTOCOL.read_text(encoding="utf-8"),
                       re.MULTILINE)
    if len(found) != 1 or found[0] != hashlib.sha256(payload).hexdigest():
        raise LlmError("Protocol config SHA256 mismatch")
    config = json.loads(payload)
    if config["schema_version"] != 1:
        raise LlmError("Unsupported protocol config version")
    return config


def verified_manifest(config: Record, source: str) -> tuple[Path, Record]:
    path = ROOT / config["sources"][f"{source}_manifest"]
    payload = path.read_bytes()
    if hashlib.sha256(payload).hexdigest() != config["sources"][f"{source}_sha256"]:
        raise LlmError(f"{source} manifest SHA256 mismatch")
    manifest = json.loads(payload)
    if manifest["algorithm"] != "SHA256":
        raise LlmError(f"{source} manifest algorithm mismatch")
    return path.parent, manifest["files"]


def verify_file(directory: Path, manifest_files: Record, filename: str) -> Path:
    path = directory / filename
    if filename not in manifest_files or digest(path) != manifest_files[filename]:
        raise LlmError(f"SHA256 mismatch: {filename}")
    return path


@dataclass(frozen=True)
class Task:
    phase: str
    arm: str
    context: str
    graph: str
    question: str
    body: Record

    @property
    def custom_id(self) -> str:
        return f"{self.arm}|{self.context}|{self.graph}|{self.question}"

    @property
    def request_hash(self) -> str:
        return hashlib.sha256(canonical(self.body)).hexdigest()

    @property
    def input_characters(self) -> int:
        return len(self.body["input"])

    @property
    def system_characters(self) -> int:
        return len(self.body["instructions"])

    def input_tokens(self, divisor: float = 3) -> int:
        chars = Decimal(self.input_characters + self.system_characters)
        return int((chars / Decimal(str(divisor))).to_integral_value(rounding=ROUND_CEILING))


def _prompts(config: Record, contexts: list[str]) -> dict[str, dict[str, dict[str, str]]]:
    directory, manifest_files = verified_manifest(config, "evaluation")
    scope = config["scope"]
    paths = {mode: verify_file(directory, manifest_files, config["sources"]["prompt_files"][mode])
             for mode in contexts}
    result: dict[str, dict[str, dict[str, str]]] = {}
    for mode, path in paths.items():
        by_graph: dict[str, dict[str, str]] = {}
        for row in read_jsonl(path):
            if row["lang"] != scope["language"] or row["source"] != scope["source"] or row["mode"] != mode:
                raise LlmError(f"Prompt scope mismatch in {path.name}")
            if row["stage"] not in ("P3", "B"):
                continue
            prompt = row["prompt"]
            questions = by_graph.setdefault(row["id"], {})
            if not isinstance(prompt, str) or len(prompt) != row["characters"] or row["node_id"] in questions:
                raise LlmError(f"Invalid prompt in {path.name}")
            questions[row["node_id"]] = prompt
        result[mode] = by_graph
    return result


def _sample(config: Record, graph_order: list[str], phase: str, size: str) -> list[str]:
    sampling = config["sampling"]
    seeds = config["seeds"]
    groups: dict[str, list[str]] = defaultdict(list)
    for graph in graph_order:
        group, period = graph.rsplit("/", 1)
        if not graph.startswith(config["scope"]["split"] + "-") or not period.isdecimal():
            raise LlmError("Prompt graph identifier differs from the frozen dataset")
        groups[group].append(graph)
    pilot_rng = random.Random(seeds["pilot"])
    pilot = [graph for group in groups.values() for graph in pilot_rng.sample(group, sampling["pilot_per_group"])]
    if len(graph_order) != sampling["full_graphs"] or len(pilot) != sampling["pilot_graphs"]:
        raise LlmError("Frozen graph counts differ from the protocol")
    if phase == "smoke":
        return pilot[:1]
    if phase in ("pilot", "p3"):
        return pilot
    selected = graph_order.copy()
    if size == "half":
        half_rng = random.Random(seeds["half"])
        keep = set(pilot)
        for group in groups.values():
            keep.update(half_rng.sample([graph for graph in group if graph not in keep],
                                        sampling["half_additional_per_group"]))
        selected = [graph for graph in graph_order if graph in keep]
        if len(selected) != sampling["half_graphs"]:
            raise LlmError("Half-sample graph count differs from the protocol")
    random.Random(seeds["main"]).shuffle(selected)
    return selected


def plan(config: Record, phase: str, arm: str, size: str = "full") -> list[Task]:
    if phase not in ("smoke", "pilot", "main", "p3") or size not in ("full", "half"):
        raise LlmError("Unsupported phase or main sample size")
    if phase != "main" and size != "full":
        raise LlmError("The half sample is available for main only")
    if arm == "A" and phase in ("smoke", "p3"):
        raise LlmError("Configuration A is registered for dispatch questions only")
    contexts = config["scope"]["contexts"]
    if phase == "smoke":
        contexts = ["None"]
    prompts = _prompts(config, contexts)
    anchor = prompts["None"]
    for mode, by_graph in prompts.items():
        if anchor.keys() != by_graph.keys() or any(anchor[g].keys() != by_graph[g].keys() for g in anchor):
            raise LlmError(f"Prompt key mismatch in {mode}")
    selected = _sample(config, list(anchor), phase, size)
    rng = random.Random(config["seeds"]["within_graph"])
    template = config["arms"][arm]["request"]
    tasks = []
    for graph in selected:
        questions = list(anchor[graph])
        if len(questions) != 7 or "B" not in questions:
            raise LlmError("Expected six P3 prompts and one B prompt per graph")
        if phase == "p3":
            questions.remove("B")
        elif phase in ("pilot", "main"):
            questions = ["B"]
        combinations = [(mode, question) for mode in contexts for question in questions]
        rng.shuffle(combinations)
        for mode, question in combinations:
            body = {**template, "input": prompts[mode][graph][question]}
            tasks.append(Task(phase, arm, mode, graph, question, body))
    return tasks


def response_path(root: Path, phase: str, arm: str) -> Path:
    return root / f"{phase}_{arm}" / "responses.jsonl"


def pilot_reuse_path(root: Path, arm: str) -> Path:
    return response_path(root, "main", arm).with_name("pilot_reuse.jsonl")


def records_for_tasks(root: Path, tasks: list[Task], *, pilot_root: Path | None = None,
                      include_pilot: bool = True) -> dict[str, Record]:
    if not tasks:
        return {}
    phase, arm = tasks[0].phase, tasks[0].arm
    expected = {task.custom_id: task.request_hash for task in tasks}
    selected: dict[str, Record] = {}
    sources = [(response_path(root, phase, arm), phase)]
    if phase == "main" and include_pilot:
        source_root = pilot_root if pilot_root is not None else root
        sources.extend(((response_path(source_root, "pilot", arm), "pilot"), (pilot_reuse_path(root, arm), "pilot")))
    for path, source_phase in sources:
        for row in read_jsonl(path):
            key = row["custom_id"]
            if key not in expected or row["request_hash"] != expected[key]:
                continue
            if row["phase"] != source_phase or row["arm"] != arm or row["status"] not in TERMINAL | {"error"}:
                raise LlmError("Invalid saved response metadata")
            if source_phase != phase and row["status"] not in TERMINAL:
                continue
            current = selected.get(key)
            if current is None or current["status"] not in TERMINAL:
                selected[key] = row
    return selected


def terminal_records(root: Path, tasks: list[Task], *, pilot_root: Path | None = None,
                     include_pilot: bool = True) -> dict[str, Record]:
    return {key: row for key, row in records_for_tasks(root, tasks, pilot_root=pilot_root,
                                                      include_pilot=include_pilot).items()
            if row["status"] in TERMINAL}


def ensure_pilot_gate(config: Record, root: Path, arm: str) -> Record:
    tasks = plan(config, "pilot", arm)
    records = terminal_records(root, tasks)
    total = len(records)
    result: Record = {"expected": len(tasks), "terminal": total}
    for status in ("truncated", "parse_failure"):
        field = "truncation_rate" if status == "truncated" else "parse_failure_rate"
        rate = sum(row["status"] == status for row in records.values()) / total if total else None
        threshold = config["gates"][field]
        if rate is not None and rate > threshold:
            raise LlmError(f"Pilot {field} {rate:.1%} exceeds {threshold:.1%}; a protocol amendment is required")
        result[field] = rate
    return result
