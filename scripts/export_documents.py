"""Export the delivered Markdown documents to PDF files that can be sent and opened directly.

Markdown stays the source. Needs `markdown` and `latex2mathml` (pip install markdown==3.7 latex2mathml==3.77.0) and a
Chromium-based browser for printing. Relative links are shown as repository paths, since they would not work inside a
sent file. Mermaid diagrams are replaced by the architecture figure they describe.

    python scripts/export_documents.py --output artifacts/documents
"""
from __future__ import annotations

import argparse
import base64
import html
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import latex2mathml.converter
import markdown

ROOT = Path(__file__).resolve().parents[1]
DOCUMENTS = (
    ("docs/user_guide.md", "user_guide", "使用手册 User guide"),
    ("docs/technical_overview.md", "technical_overview", "技术总览 Technical overview"),
    ("docs/results/planning_agent_v2.md", "planning_agent_v2_report", "评测 v2 报告 Evaluation v2 report"),
    ("docs/results/planning_agent_v2_followup.md", "planning_agent_v2_followup", "评测 v2 后续 Evaluation v2 follow-up"),
    ("docs/results/planning_agent_v2_scoring.md", "planning_agent_v2_scoring", "评分说明 Scoring notes"),
    ("docs/results/c03_review_case.md", "c03_review_case", "C03 复核案例 C03 review case"),
)
CSS = """
@page { size: A4; margin: 18mm 16mm; }
body { font-family: "Microsoft YaHei", "Noto Sans SC", "Noto Sans CJK SC", "Helvetica Neue", Arial, sans-serif;
       font-size: 10pt; line-height: 1.55; color: #1f1f1f; }
h1 { font-size: 19pt; margin: 0 0 8pt; } h2 { font-size: 15pt; margin: 18pt 0 6pt; border-bottom: 1px solid #bbb; }
h3 { font-size: 12pt; margin: 14pt 0 4pt; } h4 { font-size: 10.5pt; margin: 10pt 0 3pt; }
h2, h3, h4 { break-after: avoid; }
table { border-collapse: collapse; width: 100%; margin: 6pt 0 10pt; font-size: 8.8pt; }
th, td { border: 1px solid #c8c8c8; padding: 2.5pt 4pt; vertical-align: top; overflow-wrap: break-word; }
th { background: #efefef; } tr { break-inside: avoid; }
code { font-family: Consolas, "Courier New", monospace; font-size: 8.8pt; background: #f3f3f3; padding: 0 2pt;
       overflow-wrap: anywhere; }
pre { background: #f3f3f3; padding: 6pt 8pt; white-space: pre-wrap; overflow-wrap: anywhere; break-inside: avoid; }
pre code { background: none; padding: 0; }
blockquote { margin: 4pt 0 8pt; padding: 2pt 8pt; border-left: 3px solid #bbb; color: #333; }
img { max-width: 100%; } .version { color: #555; font-size: 8.5pt; margin-bottom: 10pt; }
math { font-size: 1.02em; } math[display=block] { display: block; overflow-wrap: anywhere; margin: 6pt 0; }
"""
FENCE = re.compile(r"^```.*?^```[ \t]*$", re.MULTILINE | re.DOTALL)
CODE = re.compile(r"`[^`\n]+`")
BLOCK_MATH = re.compile(r"^\$\$\n(.+?)\n\$\$[ \t]*$", re.MULTILINE | re.DOTALL)
INLINE_MATH = re.compile(r"(?<![\w$\\])\$(?=[^\s$\d])([^$\n]*?[^\s$])\$(?![\w$])")
LINK = re.compile(r"(?<!!)\[([^\]\n]+)\]\((?!https?://|#|mailto:)([^)\s]+)\)")


def code_version() -> str:
    done = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=False)
    dirty = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True, check=False)
    return done.stdout.strip() + ("+uncommitted" if dirty.stdout.strip() else "")


def find_browser() -> str:
    names = ("msedge", "chrome", "chromium", "chromium-browser", "google-chrome")
    paths = (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
             r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
             r"C:\Program Files\Google\Chrome\Application\chrome.exe")
    for name in (*[shutil.which(n) for n in names], *paths):
        if name and Path(name).exists():
            return str(name)
    raise SystemExit("no Chromium-based browser found")


def block_math(latex: str) -> str:
    """One display line per row: the converter does not lay out `aligned`, and a long line would shrink the whole page."""
    latex = latex.replace("\\begin{aligned}", "").replace("\\end{aligned}", "").replace("&", "")
    rows = [row.replace("\n", " ").strip() for row in latex.split("\\\\")]
    return "".join(latex2mathml.converter.convert(row, display="block") for row in rows if row)


def to_html(path: Path, title: str, version: str) -> str:
    text = path.read_text(encoding="utf-8")
    stored: list[str] = []

    def keep(fragment: str) -> str:
        stored.append(fragment)
        return f"ZZKEEP{len(stored) - 1}ZZ"  # plain letters: Markdown removes control characters

    figure = base64.b64encode((ROOT / "docs/figures/system_architecture.svg").read_bytes()).decode("ascii")

    def fence(match: re.Match[str]) -> str:
        if match.group(0).startswith("```mermaid"):
            return "\n\n" + keep(f'<p><img alt="system architecture" src="data:image/svg+xml;base64,{figure}"></p>') + "\n\n"
        return match.group(0)

    text = FENCE.sub(fence, text)
    # Code stays as written, so math and links are only looked for outside it.
    protected: list[str] = []

    def protect(match: re.Match[str]) -> str:
        protected.append(match.group(0))
        return f"\x04{len(protected) - 1}\x05"

    text = FENCE.sub(protect, text)
    text = CODE.sub(protect, text)
    text = BLOCK_MATH.sub(lambda m: "\n" + keep(block_math(m.group(1))) + "\n", text)
    text = INLINE_MATH.sub(lambda m: keep(latex2mathml.converter.convert(m.group(1))), text)
    text = LINK.sub(lambda m: f"{m.group(1)}（{keep('<code>' + html.escape(_target(path, m.group(2))) + '</code>')}）",
                    text)
    while "\x04" in text:
        text = re.sub("\x04(\\d+)\x05", lambda m: protected[int(m.group(1))], text)
    body = markdown.markdown(text, extensions=["tables", "fenced_code", "sane_lists"])
    while "ZZKEEP" in body:
        body = re.sub(r"ZZKEEP(\d+)ZZ", lambda m: stored[int(m.group(1))], body)
    return (f'<!doctype html><html lang="zh"><head><meta charset="utf-8"><title>{html.escape(title)}</title>'
            f'<style>{CSS}</style></head><body><p class="version">Exported from Markdown; code version '
            f'<code>{version}</code>. Links show paths in the repository.</p>{body}</body></html>')


def _target(path: Path, link: str) -> str:
    """A repository path rather than one on this computer."""
    target, _, anchor = link.partition("#")
    resolved = (path.parent / target).resolve()
    try:
        shown = resolved.relative_to(ROOT).as_posix()
    except ValueError:
        shown = target
    return shown + (f"#{anchor}" if anchor else "")


def print_pdf(browser: str, source: Path, target: Path, profile: Path) -> None:
    target.unlink(missing_ok=True)
    subprocess.run([browser, "--headless=new", "--disable-gpu", f"--user-data-dir={profile}", "--no-pdf-header-footer",
                    f"--print-to-pdf={target}", source.as_uri()], capture_output=True, timeout=180, check=False)
    # The launcher can exit before its child process has finished writing the file.
    size, deadline = -1, time.monotonic() + 60
    while not (target.exists() and target.stat().st_size == size > 0):
        if time.monotonic() > deadline:
            raise SystemExit(f"the browser did not write {target.name}")
        size = target.stat().st_size if target.exists() else -1
        time.sleep(1)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", type=Path, default=Path("artifacts/documents"))
    parser.add_argument("--browser")
    args = parser.parse_args(argv)
    args.output.mkdir(parents=True, exist_ok=True)
    browser, version = args.browser or find_browser(), code_version()
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
        for source, stem, title in DOCUMENTS:
            page = Path(folder) / f"{stem}.html"
            page.write_text(to_html(ROOT / source, title, version), encoding="utf-8")
            target = (args.output / f"{stem}.pdf").resolve()
            print_pdf(browser, page, target, Path(folder) / "profile")
            print(f"wrote {target.name} ({target.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
