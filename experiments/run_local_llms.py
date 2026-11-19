"""Run open-weight models through `tactbench llm --provider local`. Round 23.

Free to run: each model is a quantized GGUF file served by llama.cpp's
OpenAI-compatible server on this machine. No API key, no spend.

    python experiments/run_local_llms.py --models-dir DIR --server-python PY [--only NAME]

``--server-python`` is an interpreter with ``llama-cpp-python[server]`` installed
(kept out of this project's dependencies; it compiles C++). For each model in
``MODELS`` whose file is present, this starts a server, runs both prompt variants
over v1/dev, stops the server by the PID it started, and copies the decisions to
``results/v1-dev/``. ``results/MANIFEST.json`` records what produced each file:
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

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results" / "v1-dev"
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
}

#: Chat templates that raise on a system turn. Their convention is instructions at
#: the top of the user turn; the run passes --no-system-role and the manifest says so.
NO_SYSTEM_ROLE = frozenset({"gemma-2-2b"})

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


def run_model(name: str, path: Path, server_python: str, threads: int) -> dict[str, float | None]:
    log = open(RESULTS.parent / f".server-{name}.log", "w")  # noqa: SIM115
    proc = subprocess.Popen(
        [server_python, "-m", "llama_cpp.server", "--model", str(path),
         "--model_alias", name, "--host", "127.0.0.1", "--port", str(PORT),
         "--n_ctx", str(N_CTX), "--n_threads", str(threads), "--seed", "0"],
        stdout=log, stderr=subprocess.STDOUT,
    )  # fmt: skip
    timings = {}
    try:
        wait_ready(proc)
        for variant in VARIANTS:
            src = ROOT / "runs" / f"llm_{variant}_{name}-dev.jsonl"
            # A run killed part-way resumes from the CLI's per-decision cache. Its
            # wall time would then cover only the remainder, so it is not recorded.
            resumed = src.exists() and src.stat().st_size > 0
            t0 = time.time()
            subprocess.run(
                ["uv", "run", "tactbench", "llm", "--provider", "local", "--model", name,
                 "--variant", variant, "--base-url", f"http://127.0.0.1:{PORT}/v1",
                 *(["--no-system-role"] if name in NO_SYSTEM_ROLE else [])],
                cwd=ROOT, check=True,
            )  # fmt: skip
            timings[variant] = None if resumed else round(time.time() - t0, 1)
            shutil.copy(src, RESULTS / src.name)
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
    args = ap.parse_args()

    RESULTS.mkdir(parents=True, exist_ok=True)
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
        timings = run_model(name, path, args.server_python, args.threads)
        manifest[name] = {
            "hf_repo": repo,
            "file": fname,
            "sha256": sha256(path),
            "bytes": path.stat().st_size,
            "quantization": "Q4_K_M",
            "runtime": f"llama-cpp-python {runtime}",
            "n_ctx": N_CTX,
            "temperature": 0,
            "system_role": name not in NO_SYSTEM_ROLE,
            "threads": args.threads,
            "wall_seconds": timings,
        }
        MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
