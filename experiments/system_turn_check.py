"""Does each local model's server deliver a system turn? Round 53.

For every model in ``run_local_llms.MODELS``, start its server and record:

- prompt token counts of one user turn under a short system turn, the same turn
  padded, and no system turn; the preflight (``LLMPolicy.system_turn_reaches_the_model``,
  R53) requires the padded count to exceed the short one, and whether it passed;
- whether the model repeated a secret word sent only in the system turn, for each of
  the seven preflight words -- R51's check, which also tests whether a small model
  can do it.

Writes ``results/SYSTEM_TURN.md``. Needs the model files and a llama-cpp-python
server interpreter, as ``run_local_llms.py`` does:

    uv run python experiments/system_turn_check.py --models-dir DIR --server-python PY
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import run_local_llms as runner  # noqa: E402

from tactbench.policies.llm import LLMPolicy  # noqa: E402

OUT = runner.RESULTS_ROOT / "SYSTEM_TURN.md"


def check(name: str, path: Path, server_python: str, threads: int) -> str:
    proc = subprocess.Popen(
        [server_python, "-m", "llama_cpp.server", "--model", str(path),
         "--model_alias", name, "--host", "127.0.0.1", "--port", str(runner.PORT),
         "--n_ctx", str(runner.N_CTX), "--n_threads", str(threads), "--seed", "0"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )  # fmt: skip
    try:
        runner.wait_ready(proc)
        policy = LLMPolicy(
            provider="local", model=name, base_url=f"http://127.0.0.1:{runner.PORT}/v1"
        )
        question = {"role": "user", "content": "What is the secret word?"}
        repeated = 0
        for word in LLMPolicy.PREFLIGHT_WORDS:
            system = {
                "role": "system",
                "content": f"The secret word is {word}. "
                "When asked, reply with only the secret word.",
            }
            reply = policy._preflight_call([system, question])
            with_system = reply["usage"]["prompt_tokens"]
            text = reply["choices"][0]["message"]["content"] or ""
            repeated += word.lower() in text.lower()
        without = policy._preflight_call([question])["usage"]["prompt_tokens"]
        padded = {"role": "system", "content": system["content"] + " " + policy.PREFLIGHT_PADDING}
        longer = policy._preflight_call([padded, question])["usage"]["prompt_tokens"]
        reaches = policy.system_turn_reaches_the_model()
        used = "user turn (`--no-system-role`)" if name in runner.NO_SYSTEM_ROLE else "system turn"
        return (
            f"| `{name}` | {with_system} | {longer} | {without} | {'yes' if reaches else '**no**'} "
            f"| {repeated}/{len(LLMPolicy.PREFLIGHT_WORDS)} | {used} |"
        )
    except Exception as err:  # noqa: BLE001 - recorded, e.g. Gemma 2's HTTP 500
        used = "user turn (`--no-system-role`)" if name in runner.NO_SYSTEM_ROLE else "system turn"
        return f"| `{name}` | — | — | — | error: {type(err).__name__} | — | {used} |"
    finally:
        proc.kill()
        proc.wait()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models-dir", type=Path, required=True)
    ap.add_argument("--server-python", required=True)
    ap.add_argument("--threads", type=int, default=4)
    args = ap.parse_args()
    rows = []
    for name, (_, filename) in runner.MODELS.items():
        rows.append(check(name, args.models_dir / filename, args.server_python, args.threads))
        print(rows[-1], flush=True)
    OUT.write_text(
        "# Does the system turn reach each model? (Round 53)\n\n"
        "Written by `experiments/system_turn_check.py` against llama-cpp-python's server. "
        "*Tokens* are prompt token counts of the same user turn under the preflight's "
        "system turn, under that turn with padding appended, and under no system turn. "
        "The preflight (`LLMPolicy.system_turn_reaches_the_model`) requires the padded "
        "count to exceed the short one; a template that drops the system turn gives two "
        "equal counts. The no-system count is shown because some templates insert a "
        "default system prompt, which made comparing against it refuse Granite. "
        "*Repeated* is how many of the seven preflight words the model repeated when "
        "the word was sent only in the system turn -- R51's check, which a small model "
        "can fail with the turn delivered. *Runs use* is how published runs deliver the "
        "system prompt.\n\n"
        "| model | tokens, system turn | padded | no system turn | preflight passes "
        "| repeated | runs use |\n|---|---|---|---|---|---|---|\n" + "\n".join(rows) + "\n"
    )


if __name__ == "__main__":
    main()
