"""Which README figures can change without a test failing? Round 65.

For every number in the README's *ungated* prose (outside ``<!-- x:start/end -->``
blocks and code fences), bump its last digit, run every test function whose body
reads the README, and record whether anything failed. Restores the README at the
end (and on error). The two character n-gram audit tests are skipped for speed;
they pin their figures by regex against the probe's output.

R65: 85 of 145 unpinned before ``tests/test_readme_prose.py``, 75 of 146 after (this
script; the first count came from a scratch run of the same method). Most of the rest
are history and definitions.

    uv run python experiments/readme_figure_sweep.py     # ~40 minutes
"""

from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIGURE = re.compile(r"[−+]\d+\.\d|\d+\.\d+%|\d+(?:\.\d)?%|\b\d+\.\d\b")


def readme_tests() -> list[str]:
    nodes = []
    for path in sorted((ROOT / "tests").glob("test_*.py")):
        src = path.read_text()
        tree = ast.parse(src)

        def reads(node, src: str = src) -> bool:
            body = ast.get_source_segment(src, node) or ""
            return any(k in body for k in ("README", "readme", "_block", "_limitations"))

        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                helpers = any(
                    reads(m) for m in node.body if isinstance(m, ast.FunctionDef)
                    and not m.name.startswith("test_")
                )  # fmt: skip
                for m in node.body:
                    if isinstance(m, ast.FunctionDef) and m.name.startswith("test_"):
                        if reads(m) or helpers:
                            nodes.append(f"{path}::{node.name}::{m.name}")
            elif isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
                if reads(node) and "char_ngram" not in node.name:
                    nodes.append(f"{path}::{node.name}")
    return nodes


def main() -> None:
    readme = ROOT / "README.md"
    original = readme.read_text()
    lines = original.splitlines(keepends=True)
    nodes = readme_tests()
    block, unpinned, total = None, [], 0
    try:
        for i, line in enumerate(lines):
            marker = re.search(r"<!-- ([\w-]+):(start|end) -->", line)
            if marker:
                block = marker.group(1) if marker.group(2) == "start" else None
                continue
            if block or line.startswith("```"):
                continue
            for m in FIGURE.finditer(line):
                s = m.group(0)
                k = max(j for j, c in enumerate(s) if c.isdigit())
                bumped = s[:k] + str((int(s[k]) + 1) % 10) + s[k + 1 :]
                readme.write_text(
                    "".join(
                        lines[:i] + [line[: m.start()] + bumped + line[m.end() :]] + lines[i + 1 :]
                    )
                )
                r = subprocess.run(
                    ["uv", "run", "pytest", "-q", "-x", "-p", "no:cacheprovider", *nodes],
                    capture_output=True, cwd=ROOT,
                )  # fmt: skip
                total += 1
                if r.returncode == 0:
                    unpinned.append((i + 1, s))
                    print(f"line {i + 1}: {s} UNPINNED", flush=True)
    finally:
        readme.write_text(original)
    print(f"{len(unpinned)} of {total} figures unpinned")


if __name__ == "__main__":
    main()
