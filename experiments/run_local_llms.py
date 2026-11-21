"""Run open-weight models through `tactbench llm --provider local`. Round 23.

Free to run: each model is a quantized GGUF file served by llama.cpp's
OpenAI-compatible server on this machine. No API key, no spend.

    uv run python experiments/run_local_llms.py --models-dir DIR --server-python PY [--only NAME]

``--server-python`` is an interpreter with ``llama-cpp-python[server]`` installed
(kept out of this project's dependencies; it compiles C++). For each model in
``MODELS`` whose file is present, this starts a server, runs both prompt variants
over ``<version>/dev`` (``--version``, default v1), stops the server by the PID it
started, and copies the decisions to ``results/<version>-dev/``.
``results/MANIFEST.json`` records what produced each file:
the weights' sha256, the quantization, the runtime version, the context size and
the wall time -- everything needed to rerun it, because a local result is only as
reproducible as its recorded weights.

Decoding is greedy (temperature 0, set in ``policies/llm.py``). The prompt is the
one every provider gets, with no grammar or JSON mode; output that is not a
readable decision is scored as silence *and counted* (see ``unparsed_rate``).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from tactbench.policies.llm import LLMPolicy

ROOT = Path(__file__).resolve().parents[1]
RESULTS_ROOT = ROOT / "results"
MANIFEST = ROOT / "results" / "MANIFEST.json"
PORT = 8765

#: name used in results -> (Hugging Face repo, file). All Q4_K_M, all instruction-tuned.
MODELS: dict[str, tuple[str, str]] = {
    "qwen2.5-0.5b": ("Qwen/Qwen2.5-0.5B-Instruct-GGUF", "qwen2.5-0.5b-instruct-q4_k_m.gguf"),
    "llama-3.2-1b": ("bartowski/Llama-3.2-1B-Instruct-GGUF", "Llama-3.2-1B-Instruct-Q4_K_M.gguf"),
    "qwen2.5-1.5b": ("Qwen/Qwen2.5-1.5B-Instruct-GGUF", "qwen2.5-1.5b-instruct-q4_k_m.gguf"),
    "smollm2-1.7b": ("bartowski/SmolLM2-1.7B-Instruct-GGUF", "SmolLM2-1.7B-Instruct-Q4_K_M.gguf"),
    "gemma-2-2b": ("bartowski/gemma-2-2b-it-GGUF", "gemma-2-2b-it-Q4_K_M.gguf"),
    "qwen2.5-3b": ("Qwen/Qwen2.5-3B-Instruct-GGUF", "qwen2.5-3b-instruct-q4_k_m.gguf"),
    "llama-3.2-3b": ("bartowski/Llama-3.2-3B-Instruct-GGUF", "Llama-3.2-3B-Instruct-Q4_K_M.gguf"),
    "phi-3.5-mini": ("bartowski/Phi-3.5-mini-instruct-GGUF", "Phi-3.5-mini-instruct-Q4_K_M.gguf"),
    "gemma-3-4b": ("bartowski/google_gemma-3-4b-it-GGUF", "google_gemma-3-4b-it-Q4_K_M.gguf"),
    "qwen2.5-7b": ("bartowski/Qwen2.5-7B-Instruct-GGUF", "Qwen2.5-7B-Instruct-Q4_K_M.gguf"),
    "llama-3.1-8b": (
        "bartowski/Meta-Llama-3.1-8B-Instruct-GGUF",
        "Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf",
    ),
    # Round 50: two families not yet in the pool, and a newer Phi. Run on v4 only.
    "granite-3.3-2b": (
        "bartowski/ibm-granite_granite-3.3-2b-instruct-GGUF",
        "ibm-granite_granite-3.3-2b-instruct-Q4_K_M.gguf",
    ),
    "phi-4-mini": (
        "bartowski/microsoft_Phi-4-mini-instruct-GGUF",
        "microsoft_Phi-4-mini-instruct-Q4_K_M.gguf",
    ),
    "mistral-7b": (
        "bartowski/Mistral-7B-Instruct-v0.3-GGUF",
        "Mistral-7B-Instruct-v0.3-Q4_K_M.gguf",
    ),
}

#: Chat templates that raise on a system turn. Their convention is instructions at
#: the top of the user turn; the run passes --no-system-role and the manifest says so.
#
#: Round 50 found a worse case: a template that *accepts* a system turn and drops it.
#: llama-cpp-python guesses ``mistral-instruct`` for Mistral-7B-v0.3, and that format
#: emits only user turns -- the prompt is 10 tokens with or without a system message,
#: and a secret word placed there is unknown to the model. Nothing errors. The
#: preflight below now catches this before a single call is made.
NO_SYSTEM_ROLE = frozenset({"gemma-2-2b", "mistral-7b"})

VARIANTS = ("naive", "rubric")
N_CTX = 2048


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def wait_ready(proc: subprocess.Popen, timeout: float = 300) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"server exited with {proc.returncode}")
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{PORT}/v1/models", timeout=5)
            return
        except OSError:
            time.sleep(2)
    raise TimeoutError("server never became ready")


def run_model(
    name: str, path: Path, server_python: str, threads: int, version: str = "v1"
) -> dict[str, float | None]:
    results = RESULTS_ROOT / f"{version}-dev"
    results.mkdir(parents=True, exist_ok=True)
    log = open(RESULTS_ROOT / f".server-{name}.log", "w")  # noqa: SIM115
    proc = subprocess.Popen(
        [server_python, "-m", "llama_cpp.server", "--model", str(path),
         "--model_alias", name, "--host", "127.0.0.1", "--port", str(PORT),
         "--n_ctx", str(N_CTX), "--n_threads", str(threads), "--seed", "0"],
        stdout=log, stderr=subprocess.STDOUT,
    )  # fmt: skip
    timings = {}
    try:
        wait_ready(proc)
        # The CLI checks this too (Round 51); failing here names the fix.
        local = LLMPolicy(provider="local", model=name, base_url=f"http://127.0.0.1:{PORT}/v1")
        if name not in NO_SYSTEM_ROLE and not local.system_turn_reaches_the_model():
            raise SystemExit(
                f"{name}: the server drops the system turn (the system-turn preflight"
                " failed; see results/SYSTEM_TURN.md)."
                " Add it to NO_SYSTEM_ROLE so the prompt goes in the user turn."
            )
        for variant in VARIANTS:
            suffix = "-nosys" if name in NO_SYSTEM_ROLE else ""
            tag = "" if version == "v1" else f"-{version}"  # matches the CLI's cache name
            src = ROOT / "runs" / f"llm_{variant}_{name}{suffix}{tag}-dev.jsonl"
            # A run killed part-way resumes from the CLI's per-decision cache. Its
            # wall time would then cover only the remainder, so it is not recorded.
            resumed = src.exists() and src.stat().st_size > 0
            t0 = time.time()
            subprocess.run(
                ["uv", "run", "tactbench", "llm", "--provider", "local", "--model", name,
                 "--variant", variant, "--base-url", f"http://127.0.0.1:{PORT}/v1",
                 "--version", version,
                 *(["--no-system-role"] if name in NO_SYSTEM_ROLE else [])],
                cwd=ROOT, check=True,
            )  # fmt: skip
            timings[variant] = None if resumed else round(time.time() - t0, 1)
            shutil.copy(src, results / f"llm_{variant}_{name}-dev.jsonl")
    finally:
        proc.terminate()  # by the PID we started, never by name
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        log.close()
    return timings


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models-dir", type=Path, required=True)
    ap.add_argument("--server-python", required=True)
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--only", action="append")
    ap.add_argument(
        "--version",
        default="v1",
        help="dataset version (v1-v4); the Round 50 models are published on v4 only",
    )
    args = ap.parse_args()

    manifest = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {}
    runtime = subprocess.run(
        [args.server_python, "-c", "import llama_cpp; print(llama_cpp.__version__)"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()  # fmt: skip

    for name, (repo, fname) in MODELS.items():
        if args.only and name not in args.only:
            continue
        path = args.models_dir / fname
        if not path.exists():
            print(f"skip {name}: {path} not present", file=sys.stderr)
            continue
        timings = run_model(name, path, args.server_python, args.threads, args.version)
        entry = manifest.get(name, {})
        digest = sha256(path)
        if entry.get("sha256") not in (None, digest):
            raise SystemExit(f"{name}: weights differ from the manifest's -- not the same model")
        entry.update(
            {
                "hf_repo": repo,
                "file": fname,
                "sha256": digest,
                "bytes": path.stat().st_size,
                "quantization": "Q4_K_M",
                "runtime": f"llama-cpp-python {runtime}",
                "n_ctx": N_CTX,
                "temperature": 0,
                "system_role": name not in NO_SYSTEM_ROLE,
                "threads": args.threads,
            }
        )
        # v1's timings stay where they were; other versions are recorded beside them.
        if args.version == "v1":
            entry["wall_seconds"] = timings
        else:
            entry.setdefault("wall_seconds_by_version", {})[args.version] = timings
        manifest[name] = entry
        MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
