"""Retrieval over real carrier notices: a links-and-hashes manifest, BM25 search and a download that needs consent.

The searchable text is the 24 short verbatim excerpts already held in the frozen notice datasets (listed in
THIRD_PARTY_NOTICES.md). The manifest in data_sources/ records links, dates, hashes and annotations, never notice
text. Chinese questions are expanded with an English glossary because the notices are in English. Nothing here
calls a model, and nothing goes online unless ``fetch`` is called with consent.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import time
import urllib.request
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
REAL_DATASET = "benchmarks/real_notices_v1/dataset.json"
REAL_ANNOTATIONS = "benchmarks/real_notices_v1/annotations.jsonl"
FACTS_DATASET = "benchmarks/notice_facts_v1/dataset.json"
MANIFEST = ROOT / "data_sources" / "notice_corpus.json"
RAW = ROOT / "data_sources" / "raw" / "notices"
QUERIES = ROOT / "benchmarks" / "notice_retrieval_v1" / "queries.json"
RESULTS = ROOT / "benchmark_results" / "notice_retrieval_v1"
GLOSSARY = Path(__file__).with_name("notice_glossary.json")

PUBLISHERS = {"maersk.com": "A.P. Moller - Maersk", "maersk.com.cn": "A.P. Moller - Maersk", "msc.com": "MSC",
              "hapag-lloyd.com": "Hapag-Lloyd", "cma-cgm.com": "CMA CGM", "cnc-line.com": "CNC"}
MISSING_LABELS = {
    "service_to_internal_route_mapping": "公告里的航线对应我们哪条内部线路",
    "affected_dispatch_calendar": "受影响的是计划期里哪几周的发运",
    "exact_incremental_lead_weeks": "确定增加几周运输时间（公告只给近似值、区间或没有给）",
}
STOPWORDS = frozenset((
    "a", "an", "the", "of", "to", "in", "on", "at", "for", "by", "and", "or", "is", "are", "was", "were", "be",
    "been", "will", "would", "can", "could", "has", "have", "had", "from", "with", "what", "how", "when", "where",
    "which", "who", "does", "do", "did", "its", "it", "this", "that", "these", "those", "as", "our", "we", "you",
    "your", "there", "their", "they", "any", "about", "into"))
K1, B = 1.5, 0.75
CUTOFFS = (1, 3, 5)
USER_AGENT = "semiconductor-logistics-notice-fetch/1.0 (research use; one request per page)"

Getter = Callable[[str], tuple[int, str, bytes]]


@dataclass(frozen=True)
class Notice:
    """One carrier notice excerpt with its source record and the project's annotation."""

    id: str
    publisher: str
    title: str
    url: str
    published: str | None
    accessed: str | None
    group: str
    text: str
    text_sha256: str
    dataset: str
    annotation: str
    event_kind: str | None
    summary: str | None
    quantities: tuple[str, ...]
    missing: tuple[str, ...]


@dataclass(frozen=True)
class Hit:
    notice: Notice
    score: float
    rank: int
    passage: str
    matched: tuple[str, ...]
    local: bool = False


# ---------------------------------------------------------------------------- corpus

def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _publisher(url: str) -> str:
    host = urlparse(url).netloc.lower().removeprefix("www.")
    return next((name for domain, name in PUBLISHERS.items() if host == domain or host.endswith("." + domain)), host)


def _quantity(item: dict[str, Any]) -> str:
    """A stated quantity as text, keeping its qualifier (range, approximately, average)."""
    kind = item.get("semantic_type") or item.get("metric") or "quantity"
    low, high = item.get("minimum", item.get("low")), item.get("maximum", item.get("high"))
    value = item.get("value")
    if value is None and low is not None and high is not None and low != high:
        amount = f"{low:g}–{high:g}"
    else:
        amount = f"{(value if value is not None else low):g}" if (value is not None or low is not None) else "?"
    return f"{kind}: {amount} {item.get('unit', '')} ({item.get('qualifier', 'stated')})".replace("  ", " ")


def load_notices(root: Path = ROOT) -> list[Notice]:
    """The 24 distinct excerpts: real_notices_v1 plus the notice_facts_v1 items that do not repeat it."""
    real = _read_json(root / REAL_DATASET)
    notes = {}
    for line in (root / REAL_ANNOTATIONS).read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            notes[row["source_id"]] = row["annotation"]
    notices = []
    for source in real["sources"]:
        note = notes.get(source["source_id"], {})
        broad = note.get("broad_reference", {})
        reviewed = "human review pending" if note.get("human_review_pending", True) else "human reviewed"
        notices.append(Notice(
            id=source["source_id"], publisher=source["publisher"], title=source["title"], url=source["url"],
            published=source.get("published_date"), accessed=source.get("accessed_date"),
            group=source["event_group_id"], text=source["text"], text_sha256=source["text_sha256"],
            dataset=f"{REAL_DATASET}#{source['source_id']}",
            annotation=f"{note.get('annotator_type', 'no')} annotation, {reviewed}",
            event_kind=broad.get("event_kind"), summary=broad.get("factual_summary"),
            quantities=tuple(_quantity(q) for q in broad.get("quantities", [])),
            missing=tuple(note.get("missing_information", []))))
    seen = {n.text_sha256 for n in notices}
    facts = _read_json(root / FACTS_DATASET)
    for items in facts["splits"].values():
        for item in items:
            if item["text_sha256"] in seen:  # the development split repeats real_notices_v1
                continue
            seen.add(item["text_sha256"])
            reference = item.get("reference", {}).get("facts", [])
            notices.append(Notice(
                id=item["id"], publisher=_publisher(item["source_url"]), title=item["source_title"],
                url=item["source_url"], published=None, accessed=facts.get("source_access_date"),
                group=item["group"], text=item["text"], text_sha256=item["text_sha256"],
                dataset=f"{FACTS_DATASET}#{item['id']}",
                annotation=f"curated by the implementer, human review {item.get('human_review', 'pending')}",
                event_kind=reference[0]["metric"] if reference else None, summary=None,
                quantities=tuple(_quantity(q) for q in reference), missing=()))
    return notices


def build_manifest(notices: Sequence[Notice]) -> dict[str, Any]:
    return {
        "corpus": "notice_corpus_v1",
        "text_policy": ("No notice text is stored here. Excerpts stay in the frozen datasets named by `dataset`; "
                        "full pages are downloaded locally by `python -m planning_agent corpus fetch --yes` "
                        "into data_sources/raw/notices/ and never committed."),
        "rights": "Notice text belongs to the respective carriers; see THIRD_PARTY_NOTICES.md.",
        "documents": [{
            "id": n.id, "publisher": n.publisher, "title": n.title, "url": n.url, "published_date": n.published,
            "accessed_date": n.accessed, "event_group": n.group, "dataset": n.dataset,
            "excerpt_sha256": n.text_sha256, "event_kind": n.event_kind, "annotation": n.annotation,
            "stated_quantities": list(n.quantities), "missing_information": list(n.missing),
        } for n in notices],
    }


def manifest_text(notices: Sequence[Notice]) -> str:
    return json.dumps(build_manifest(notices), indent=2, ensure_ascii=False) + "\n"


def write_manifest(path: Path = MANIFEST, notices: Sequence[Notice] | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(manifest_text(notices or load_notices()), encoding="utf-8", newline="\n")
    return path


def manifest_matches(path: Path = MANIFEST, notices: Sequence[Notice] | None = None) -> bool:
    return path.exists() and path.read_text(encoding="utf-8") == manifest_text(notices or load_notices())


# ---------------------------------------------------------------------------- tokens and glossary

WORD = re.compile(r"[a-z0-9]+")
CJK = re.compile(r"[㐀-鿿]+")


def _stem(word: str) -> str:
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    return word


def tokenize(text: str) -> list[str]:
    """English words (lower case, plural s removed, stopwords dropped) and Chinese character bigrams."""
    lowered = text.lower()
    tokens = [_stem(w) for w in WORD.findall(lowered) if w not in STOPWORDS and (len(w) > 1 or w.isdigit())]
    for run in CJK.findall(lowered):
        tokens += [run] if len(run) == 1 else [run[i:i + 2] for i in range(len(run) - 1)]
    return tokens


def load_glossary(path: Path = GLOSSARY) -> dict[str, tuple[str, ...]]:
    return {term: tuple(words) for term, words in _read_json(path)["terms"].items()}


def expand(query: str, glossary: dict[str, tuple[str, ...]]) -> tuple[list[str], list[str]]:
    """Query tokens plus the English words of every glossary term found in the query; also returns those terms."""
    tokens = tokenize(query)
    used = [term for term in sorted(glossary, key=len, reverse=True) if term in query]
    for term in used:
        tokens += tokenize(" ".join(glossary[term]))
    return tokens, used


# ---------------------------------------------------------------------------- BM25

class Index:
    """BM25 over publisher, title and excerpt of each notice, plus optional passages from locally fetched pages."""

    def __init__(self, notices: Sequence[Notice], glossary: dict[str, tuple[str, ...]] | None = None,
                 extra: Sequence[tuple[Notice, str]] = (), k1: float = K1, b: float = B):
        self.notices = list(notices)
        self.glossary = load_glossary() if glossary is None else glossary
        self.k1, self.b = k1, b
        self.docs: list[tuple[Notice, str, bool]] = [(n, n.text, False) for n in self.notices]
        self.docs += [(n, passage, True) for n, passage in extra]
        self.terms = [Counter(tokenize(f"{n.publisher} {n.title} {passage}" if not local else passage))
                      for n, passage, local in self.docs]
        self.lengths = [sum(t.values()) for t in self.terms]
        self.average = sum(self.lengths) / len(self.lengths) if self.lengths else 0.0
        frequency: Counter[str] = Counter()
        for terms in self.terms:
            frequency.update(terms.keys())
        n_docs = len(self.docs)
        self.idf = {t: math.log(1 + (n_docs - df + 0.5) / (df + 0.5)) for t, df in frequency.items()}

    def query_tokens(self, query: str, *, use_glossary: bool = True) -> list[str]:
        return expand(query, self.glossary)[0] if use_glossary else tokenize(query)

    def search(self, query: str, k: int = 5, *, use_glossary: bool = True) -> list[Hit]:
        """Notices with a positive score, best first; ties keep corpus order. One hit per notice."""
        tokens = self.query_tokens(query, use_glossary=use_glossary)
        best: dict[str, tuple[float, int]] = {}
        for i, (terms, length) in enumerate(zip(self.terms, self.lengths, strict=True)):
            score = 0.0
            for token in set(tokens):
                tf = terms.get(token, 0)
                if tf:
                    norm = self.k1 * (1 - self.b + self.b * length / self.average)
                    score += self.idf[token] * tf * (self.k1 + 1) / (tf + norm) * tokens.count(token)
            notice_id = self.docs[i][0].id
            if score > 0 and (notice_id not in best or score > best[notice_id][0]):
                best[notice_id] = (score, i)
        ranked = sorted(best.values(), key=lambda pair: (-pair[0], pair[1]))[:k]
        hits = []
        for rank, (score, i) in enumerate(ranked, 1):
            notice, passage, local = self.docs[i]
            matched = tuple(sorted(t for t in set(tokens) if t in self.terms[i]))
            hits.append(Hit(notice, round(score, 4), rank, passage, matched, local))
        return hits


def default_index(full_text: bool = False, root: Path = ROOT) -> Index:
    notices = load_notices(root)
    extra = local_passages(notices) if full_text else []
    return Index(notices, extra=extra)


def reference(hit: Hit) -> dict[str, Any]:
    """What the workflow shows and cites for a retrieved notice."""
    n = hit.notice
    return {"id": n.id, "publisher": n.publisher, "title": n.title, "date": n.published or "", "url": n.url,
            "group": n.group, "score": hit.score, "passage": hit.passage, "local_full_text": hit.local,
            "annotation": n.annotation, "summary": n.summary or "", "quantities": list(n.quantities),
            "missing": list(n.missing)}


# ---------------------------------------------------------------------------- evaluation

def load_queries(path: Path = QUERIES) -> list[dict[str, str]]:
    return list(_read_json(path)["queries"])


def random_expectation(n: int, relevant: int, k: int) -> dict[str, float]:
    """Exact expected recall@k, hit@k and reciprocal rank when n documents are ranked uniformly at random."""
    k = min(k, n)
    hit = 1 - math.comb(n - relevant, k) / math.comb(n, k)
    mrr = sum(math.comb(n - i, relevant - 1) / math.comb(n, relevant) / i for i in range(1, n - relevant + 2))
    return {"recall": k / n, "hit": hit, "mrr": mrr}


def _metrics(ranks: list[int | None], relevant: int) -> dict[str, float]:
    found = [r for r in ranks if r is not None]
    out: dict[str, float] = {}
    for k in CUTOFFS:
        out[f"recall@{k}"] = sum(r <= k for r in found) / relevant
        out[f"hit@{k}"] = float(any(r <= k for r in found))
    out["mrr"] = 1 / min(found) if found else 0.0
    return out


def _mean(rows: list[dict[str, float]]) -> dict[str, float]:
    return {key: round(sum(r[key] for r in rows) / len(rows), 4) for key in rows[0]} if rows else {}


def _sha256(path: Path) -> str:
    """Hash of the text with LF line ends, so a checkout that converts line ends gives the same value."""
    return hashlib.sha256(path.read_text(encoding="utf-8").encode("utf-8")).hexdigest()


def evaluate(notices: Sequence[Notice] | None = None, queries: Sequence[dict[str, str]] | None = None,
             glossary: dict[str, tuple[str, ...]] | None = None) -> dict[str, Any]:
    """Rank every notice for every question, with and without the glossary, and compare with random ranking."""
    notices = list(notices or load_notices())
    queries = list(queries or load_queries())
    index = Index(notices, glossary=glossary)
    groups: dict[str, list[str]] = {}
    for n in notices:
        groups.setdefault(n.group, []).append(n.id)
    configs = {"bm25_glossary": True, "bm25_plain": False}
    cases: list[dict[str, Any]] = []
    per: dict[str, dict[str, list[dict[str, float]]]] = {name: {} for name in (*configs, "random")}
    for query in queries:
        relevant = groups[query["group"]]
        case: dict[str, Any] = {"id": query["id"], "lang": query["lang"], "group": query["group"],
                                "relevant": relevant}
        for name, use_glossary in configs.items():
            hits = index.search(query["text"], k=len(notices), use_glossary=use_glossary)
            rank_of = {h.notice.id: h.rank for h in hits}
            ranks = [rank_of.get(r) for r in relevant]
            case[name] = {"top5": [h.notice.id for h in hits[:5]], "relevant_ranks": ranks,
                          **{key: round(value, 4) for key, value in _metrics(ranks, len(relevant)).items()}}
            per[name].setdefault(query["lang"], []).append(_metrics(ranks, len(relevant)))
        expected = {f"{m}@{k}": random_expectation(len(notices), len(relevant), k)[m]
                    for k in CUTOFFS for m in ("recall", "hit")}
        expected["mrr"] = random_expectation(len(notices), len(relevant), 1)["mrr"]
        case["random_expected"] = {key: round(value, 4) for key, value in expected.items()}
        per["random"].setdefault(query["lang"], []).append(expected)
        cases.append(case)
    summary: dict[str, Any] = {
        "benchmark": "notice_retrieval_v1",
        "status": "development check: one author wrote the questions and the glossary after reading the corpus",
        "corpus_documents": len(notices), "event_groups": len(groups),
        "queries": {lang: sum(q["lang"] == lang for q in queries) for lang in sorted({q["lang"] for q in queries})},
        "independent_cases": len({q["group"] for q in queries}),
        "method": {"bm25_k1": K1, "bm25_b": B, "fields": "publisher, title, excerpt",
                   "tokens": "English words with plural s removed; Chinese character bigrams",
                   "ties": "corpus order", "unscored_documents": "not retrieved (rank none)"},
        "inputs": {"queries_sha256": _sha256(QUERIES), "glossary_sha256": _sha256(GLOSSARY),
                   "manifest_sha256": _sha256(MANIFEST) if MANIFEST.exists() else None},
        "results": {name: {**{lang: _mean(rows) for lang, rows in sorted(by_lang.items())},
                           "all": _mean([r for rows in by_lang.values() for r in rows])}
                    for name, by_lang in per.items()},
    }
    return {"summary": summary, "cases": cases}


def results_text(result: dict[str, Any]) -> tuple[str, str]:
    summary = json.dumps(result["summary"], indent=2, ensure_ascii=False) + "\n"
    cases = "".join(json.dumps(c, ensure_ascii=False) + "\n" for c in result["cases"])
    return summary, cases


def write_results(result: dict[str, Any], out: Path = RESULTS) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    summary, cases = results_text(result)
    (out / "summary.json").write_text(summary, encoding="utf-8", newline="\n")
    (out / "cases.jsonl").write_text(cases, encoding="utf-8", newline="\n")
    return out


def results_match(result: dict[str, Any], out: Path = RESULTS) -> bool:
    summary, cases = results_text(result)
    return ((out / "summary.json").exists() and (out / "summary.json").read_text(encoding="utf-8") == summary
            and (out / "cases.jsonl").read_text(encoding="utf-8") == cases)


# ---------------------------------------------------------------------------- local full text (needs consent)

class _PageText(HTMLParser):
    SKIP = frozenset({"script", "style", "noscript", "svg", "template", "head"})
    BLOCK = frozenset({"p", "div", "li", "br", "tr", "td", "section", "article", "h1", "h2", "h3", "h4", "h5", "h6"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skipping = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self.SKIP:
            self.skipping += 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.SKIP:
            self.skipping = max(0, self.skipping - 1)
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.skipping:
            self.parts.append(data)


def page_text(html: str) -> str:
    parser = _PageText()
    parser.feed(html)
    parser.close()
    lines = (re.sub(r"[\s​]+", " ", line).strip() for line in "".join(parser.parts).split("\n"))
    return "\n".join(line for line in lines if line)


def passages(text: str, min_chars: int = 60, max_chars: int = 600) -> list[str]:
    """Paragraphs long enough to carry a fact; long paragraphs are cut at sentence ends."""
    out = []
    for paragraph in text.split("\n"):
        if len(paragraph) < min_chars:
            continue
        chunk = ""
        for sentence in re.split(r"(?<=[.!?])\s+", paragraph):
            if chunk and len(chunk) + len(sentence) > max_chars:
                out.append(chunk)
                chunk = ""
            chunk = f"{chunk} {sentence}".strip()
        if len(chunk) >= min_chars:
            out.append(chunk)
    return out


def _normalized(text: str) -> str:
    return re.sub(r"[\s​]+", " ", text).strip().lower()


def local_passages(notices: Sequence[Notice], raw: Path = RAW) -> list[tuple[Notice, str]]:
    out = []
    for notice in notices:
        path = raw / f"{notice.id}.html"
        if path.exists():
            text = page_text(path.read_bytes().decode("utf-8", errors="replace"))
            out += [(notice, p) for p in passages(text)]
    return out


def _http_get(url: str) -> tuple[int, str, bytes]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        return int(response.status), str(response.headers.get("Content-Type", "")), bytes(response.read())


def fetch(notices: Sequence[Notice], raw: Path = RAW, *, consent: bool, get: Getter | None = None,
          pause: float = 1.0) -> list[dict[str, Any]]:
    """Download each notice page into the git-ignored raw folder and log its hash; refuses without consent."""
    if not consent:
        raise PermissionError("downloading carrier pages needs explicit consent (pass --yes)")
    get = get or _http_get
    raw.mkdir(parents=True, exist_ok=True)
    records = []
    for i, notice in enumerate(notices):
        if i and pause:
            time.sleep(pause)
        record: dict[str, Any] = {"id": notice.id, "url": notice.url,
                                  "fetched_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")}
        try:
            status, content_type, body = get(notice.url)
        except (OSError, ValueError) as error:
            record.update(status=None, error=f"{type(error).__name__}: {error}")
        else:
            path = raw / f"{notice.id}.html"
            path.write_bytes(body)
            text = page_text(body.decode("utf-8", errors="replace"))
            record.update(status=status, content_type=content_type, bytes=len(body),
                          sha256=hashlib.sha256(body).hexdigest(), file=path.name,
                          excerpt_found=_normalized(notice.text) in _normalized(text))
        records.append(record)
    (raw / "fetch_log.json").write_text(json.dumps(records, indent=2, ensure_ascii=False) + "\n",
                                        encoding="utf-8", newline="\n")
    return records
