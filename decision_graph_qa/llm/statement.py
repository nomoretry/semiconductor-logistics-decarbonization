"""Self-contained statements of the dispatch question (protocol v2).

A statement is the DQ-2 prompt text with three additions: the planning rules, the demand scenarios behind
the reference answers, and a line that introduces the already answered questions.
"""
from __future__ import annotations

import gzip
import hashlib
from collections.abc import Iterable, Iterator
from pathlib import Path

from ..graph import compact, context
from ..planner import Record, scenarios
from .data import LlmError, canonical, digest
from .rules import ANSWERED, RULES, SCENARIO_LABEL

MODES = ("None", "Chain", "Graph")
STAGES = ("P3", "B")
LANGUAGE = "en"
SOURCE = "gold"


def prompt_file(mode: str) -> str:
    return f"prompts_test_{mode}_{LANGUAGE}.jsonl.gz"


def scenario_line(obs: Record) -> str:
    return f"{SCENARIO_LABEL} = {compact(scenarios(obs).tolist())}"


def statement(graph: Record, node_id: str, mode: str) -> str:
    """Wrap the frozen state, upstream answers and question with the rules and the scenarios."""
    obs = graph["observation"]
    p = obs["public"]
    if any(not float(mass * rate).is_integer() for mass in p["mass"] for rate in p["emissions"]):
        raise LlmError(f"{graph['id']}: dispatch emissions are not whole numbers")
    state = graph["state_text"][LANGUAGE]
    question = next(node["question"][LANGUAGE] for node in graph["nodes"] if node["id"] == node_id)
    text = context(graph, node_id, mode, LANGUAGE)
    if not text.startswith(f"{state}\n\n") or not text.endswith(f"\n\n{question}"):
        raise LlmError(f"{graph['id']} {node_id}: unexpected context layout")
    answered = text[len(state) + 2:-len(question)].rstrip("\n")
    parts = [RULES, state, scenario_line(obs)]
    if answered:
        parts += [ANSWERED, answered]
    return "\n\n".join([*parts, question])


def rows(graphs: Iterable[Record], mode: str) -> Iterator[Record]:
    for graph in graphs:
        for node in graph["nodes"]:
            if node["stage"] in STAGES:
                text = statement(graph, node["id"], mode)
                yield {"id": graph["id"], "node_id": node["id"], "stage": node["stage"], "mode": mode,
                       "source": SOURCE, "lang": LANGUAGE, "prompt": text, "characters": len(text)}


def payload(graphs: Iterable[Record], mode: str) -> bytes:
    return b"".join(canonical(row) + b"\n" for row in rows(graphs, mode))


def write_gzip(path: Path, data: bytes) -> None:
    with path.open("wb") as stream, gzip.GzipFile(filename="", fileobj=stream, mode="wb", mtime=0) as archive:
        archive.write(data)


def read_gzip(path: Path) -> bytes:
    with gzip.open(path, "rb") as stream:
        return stream.read()


def export(graphs: list[Record], out: Path, dataset: Record) -> Record:
    """Write the three prompt files and their manifest; the content hash survives recompression."""
    out.mkdir(parents=True, exist_ok=False)
    files, content, prompts = {}, {}, {}
    for mode in MODES:
        data = payload(graphs, mode)
        path = out / prompt_file(mode)
        write_gzip(path, data)
        files[path.name] = digest(path)
        content[path.name] = hashlib.sha256(data).hexdigest()
        prompts[mode] = data.count(b"\n")
    manifest = {"algorithm": "SHA256", "files": files, "content": content, "prompts": prompts,
                "rules": hashlib.sha256(RULES.encode("utf-8")).hexdigest(), "dataset": dataset}
    (out / "manifest.json").write_bytes(canonical(manifest) + b"\n")
    return manifest


def verify(graphs: list[Record], directory: Path, manifest: Record) -> Record:
    """Render every prompt again and compare it with the stored file."""
    if manifest["rules"] != hashlib.sha256(RULES.encode("utf-8")).hexdigest():
        raise LlmError("Planning rules differ from the exported prompts")
    if set(manifest["files"]) != {prompt_file(mode) for mode in MODES}:
        raise LlmError("Prompt manifest file set")
    for mode in MODES:
        name = prompt_file(mode)
        stored = read_gzip(directory / name)
        if digest(directory / name) != manifest["files"][name] or (
                hashlib.sha256(stored).hexdigest() != manifest["content"][name]):
            raise LlmError(f"SHA256 mismatch: {name}")
        if stored != payload(graphs, mode):
            raise LlmError(f"Rendered prompts differ from {name}")
    return {"prompts": sum(manifest["prompts"].values()), "files": len(manifest["files"])}
