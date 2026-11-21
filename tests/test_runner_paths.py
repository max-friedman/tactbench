"""The local runner's file names, for every version and split. Round 68.

Before R68 ``experiments/run_local_llms.py`` ran dev only: it hard-coded ``-dev`` in
the CLI cache it copies from and in the results directory it writes to, so a held-out
run could not be produced. ``runner_paths`` is now the one place those names are
built; these tests hold it to the CLI's cache name and to ``results.load_results``.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from tactbench.results import policy_name, results_dir

ROOT = Path(__file__).resolve().parents[1]


def _runner():
    path = ROOT / "experiments" / "run_local_llms.py"
    spec = importlib.util.spec_from_file_location("run_local_llms", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _cli_cache(variant: str, model: str, version: str, split: str, system_role: bool) -> Path:
    """The CLI's cache name, restated from ``cli.llm`` (tag/suffix rules, Round 38)."""
    suffix = "" if system_role else "-nosys"
    tag = "" if version == "v1" else f"-{version}"
    return Path("runs") / f"llm_{variant}_{model}{suffix}{tag}-{split}.jsonl"


@pytest.mark.parametrize("version", ["v1", "v5"])
@pytest.mark.parametrize("split", ["dev", "test"])
@pytest.mark.parametrize("model", ["qwen2.5-3b", "mistral-7b"])
def test_runner_paths_match_the_cli_and_the_loader(version, split, model):
    runner = _runner()
    nosys = model in runner.NO_SYSTEM_ROLE
    for variant in runner.VARIANTS:
        cache, result = runner.runner_paths(model, variant, version, split)
        assert cache == runner.ROOT / _cli_cache(variant, model, version, split, not nosys)
        assert result.parent == results_dir(version, split)
        assert policy_name(result, split) == f"llm:{variant}:{model}"


def test_the_cli_cache_name_is_the_one_restated_here():
    src = (ROOT / "src" / "tactbench" / "cli.py").read_text()
    assert 'cache_path = Path("runs") / f"{stem}{suffix}{tag}-{split}.jsonl"' in src
    assert 'tag = "" if version == "v1" else f"-{version}"' in src


def test_the_runner_passes_the_split_to_the_cli():
    text = (ROOT / "experiments" / "run_local_llms.py").read_text()
    assert '"--split", split' in text and '"--split"' in text
