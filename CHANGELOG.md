# Changelog

Notable changes to TactBench. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
this project has not yet cut a release, so everything sits under Unreleased.

## [Unreleased]

### Added

- **Engineering hygiene.** CI on Python 3.11–3.13 (tests, lint, format check, a
  dataset-reproducibility job that fails if `data/` drifts from the generator, and
  a visible shortcut-audit run). `CONTRIBUTING.md`, this changelog, a PR template,
  and `LICENSE-DATA` for the CC BY 4.0 dataset terms the README already claimed.
- **Base-rate reweighting** (`--base-rate`). Scores against a realistic
  quiet-to-loud prior instead of the balanced split. At 100:1, heuristic precision
  falls from 0.514 to **0.010** — ninety-nine of every hundred interruptions would
  be unwanted. Silence and skyline are the only rows that don't move.
- **Three scenario families**: `health`, `childcare`, `finance`. Dataset grew from
  240 to 360 items across 9 families.
- **`policies/llm.py`** — provider-agnostic LLM policy (Anthropic / Gemini /
  OpenAI), one moment per call, versioned prompt kept verbatim in source, two
  variants (`naive` withholds the cost structure, `rubric` discloses it). Plus
  `tactbench llm` with per-run caching. **Never executed** — no API key available,
  and no numbers are published for an unrun experiment.
- **`audit.py`** and `tactbench audit` — a dependency-free bag-of-words probe that
  measures whether signal text alone can answer the benchmark.
- **`policies/skyline.py`** — the achievable ceiling, and a standing
  label-consistency check.

### Changed

- **Pair construction rebuilt around role permutation.** Both sides of a pair now
  share a byte-identical body and an identical `UserState`; only one decider signal
  differs, by swapping which noun plays which role. Shortcut probe: **93.5% →
  55.6%**, with 8 of 9 families at the 0.500 chance floor.
- **Timing and content scored separately.** ICS measures *whether* to speak;
  intent correctness is reported alongside at zero weight. Previously a correctly
  timed decision was charged as a failure for emitting a generic intent, which
  flooded the failure viewer.
- The reference `heuristic` was rebuilt on structural features and generic English
  lexicons only. Its precision fell 0.818 → 0.514 — the old score was measuring
  dataset leakage, not judgment.

### Fixed

- **Inverted labels in a `travel` pair** — the "positive" described a user already
  seated at the new gate, which is the near-miss condition. Caught by the skyline
  consistency check.
- **Dev/test split used Python's `hash()`**, which is salted per process, so the
  split reshuffled on every run and silently leaked test items into dev. Now a
  stable SHA-256 digest.
- `docs/METRICS.md` documented neither base rate, the skyline, nor the audit.

### Known limitations

Tracked deliberately; see the README's limitations section.

- No LLM baselines have been run.
- Labels are by construction (`raters: 0`); no human validation or inter-rater κ.
- `quiet_hours` leaks at 100% and structurally cannot be permuted.
- Nine families is nine degrees of freedom, whatever the item count.
