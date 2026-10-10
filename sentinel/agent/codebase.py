"""Read-only access to the repository under audit."""

from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path

SKIP_DIRS = {
    ".git", ".hg", ".svn", "node_modules", ".venv", "venv", "__pycache__", "dist", "build",
    ".next", "target", "vendor", ".tox", ".mypy_cache", ".pytest_cache", "coverage",
}  # fmt: skip
SOURCE_EXTENSIONS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".java", ".kt", ".go", ".rb", ".php", ".cs",
    ".rs", ".sql", ".html", ".htm", ".vue", ".svelte", ".yml", ".yaml", ".toml", ".ini", ".cfg",
    ".json", ".tf", ".sh",
}  # fmt: skip
SOURCE_NAMES = {"Dockerfile", ".env.example"}
SKIP_NAMES = {"package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock", "uv.lock"}
MAX_FILE_BYTES = 200_000

RepoFiles = dict[str, list[str]]


def resolve_repo(target: str) -> Path:
    """Return a local path for the target, cloning it first when it is a git URL."""
    if re.match(r"^(https?://|git@)", target):
        destination = Path(tempfile.mkdtemp(prefix="sentinel-repo-"))
        subprocess.run(
            ["git", "clone", "--depth", "1", "--quiet", target, str(destination)],
            check=True,
            timeout=300,
        )
        return destination
    path = Path(target).resolve()
    if not path.is_dir():
        raise FileNotFoundError(f"Target repository not found: {path}")
    return path


def load_repo(root: Path) -> RepoFiles:
    """Read every source file under `root`, keyed by POSIX-style relative path."""
    files: RepoFiles = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or any(part in SKIP_DIRS for part in path.relative_to(root).parts):
            continue
        if path.name in SKIP_NAMES:
            continue
        if path.suffix.lower() not in SOURCE_EXTENSIONS and path.name not in SOURCE_NAMES:
            continue
        if path.stat().st_size > MAX_FILE_BYTES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        files[path.relative_to(root).as_posix()] = text.splitlines()
    return files


def total_chars(files: RepoFiles) -> int:
    return sum(len(line) + 1 for lines in files.values() for line in lines)


def render_lines(path: str, lines: list[str], start: int = 1, end: int | None = None) -> str:
    end = len(lines) if end is None else min(end, len(lines))
    body = "\n".join(f"{n:>5} | {lines[n - 1]}" for n in range(start, end + 1))
    return f'<file path="{path}">\n{body}\n</file>'


def render_repo(files: RepoFiles) -> str:
    return "\n\n".join(render_lines(path, lines) for path, lines in files.items())


def compile_patterns(patterns: list[str]) -> list[re.Pattern[str]]:
    compiled = []
    for pattern in patterns:
        try:
            compiled.append(re.compile(pattern, re.IGNORECASE))
        except re.error:
            continue
    return compiled


def grep(files: RepoFiles, patterns: list[str]) -> dict[str, list[int]]:
    """Return matching 1-based line numbers per file."""
    compiled = compile_patterns(patterns)
    hits: dict[str, list[int]] = {}
    for path, lines in files.items():
        matched = [
            number
            for number, line in enumerate(lines, start=1)
            if any(p.search(line) for p in compiled)
        ]
        if matched:
            hits[path] = matched
    return hits


def render_snippets(
    files: RepoFiles, hits: dict[str, list[int]], context: int = 12, char_budget: int = 40_000
) -> str:
    """Render windows around each hit, most-matched files first, within a size budget."""
    blocks: list[str] = []
    used = 0
    for path in sorted(hits, key=lambda p: len(hits[p]), reverse=True):
        lines = files[path]
        windows: list[list[int]] = []
        for number in hits[path]:
            start, end = max(1, number - context), min(len(lines), number + context)
            if windows and start <= windows[-1][1] + 1:
                windows[-1][1] = max(windows[-1][1], end)
            else:
                windows.append([start, end])
        for start, end in windows:
            block = render_lines(path, lines, start, end)
            if used + len(block) > char_budget:
                return "\n\n".join(blocks)
            blocks.append(block)
            used += len(block)
    return "\n\n".join(blocks)


def _squash(text: str) -> str:
    return re.sub(r"\s+", "", text)


def locate_quote(lines: list[str], quote: str, hint_line: int = 1) -> tuple[int, int] | None:
    """Find where `quote` occurs in the file, ignoring whitespace differences.

    Returns the 1-based inclusive line range of the occurrence nearest to
    `hint_line`, or None when the quoted code is not in the file.
    """
    quote_lines = [_squash(q) for q in quote.splitlines() if _squash(q)]
    if not quote_lines:
        return None
    squashed = [_squash(line) for line in lines]
    span = len(quote_lines)
    matches: list[tuple[int, int]] = []
    for i in range(len(squashed) - span + 1):
        window = squashed[i : i + span]
        first_ok = window[0].endswith(quote_lines[0]) or quote_lines[0] in window[0]
        last_ok = window[-1].startswith(quote_lines[-1]) or quote_lines[-1] in window[-1]
        middle_ok = window[1:-1] == quote_lines[1:-1]
        if first_ok and last_ok and middle_ok:
            matches.append((i + 1, i + span))
    if not matches:
        return None
    return min(matches, key=lambda m: abs(m[0] - hint_line))
