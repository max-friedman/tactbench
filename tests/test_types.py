"""``src/tactbench`` type-checks clean under mypy. Round 44.

Run from the test suite rather than as its own CI step: ``.github/workflows/`` is
owner-only, and the test job already runs on py3.11-3.13. Configuration is in
``pyproject.toml`` (``[tool.mypy]``); the only exemption is missing stubs for the
optional provider SDKs, which are imported lazily and not installed by default.
"""

from __future__ import annotations

import subprocess
import sys

from tactbench.results import ROOT


def test_the_package_type_checks():
    proc = subprocess.run(
        [sys.executable, "-m", "mypy"], cwd=ROOT, capture_output=True, text=True, timeout=600
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
