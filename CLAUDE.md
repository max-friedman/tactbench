# Contributor & agent guide

Read this before changing anything. TactBench is a benchmark, and benchmarks fail
in a specific way: they quietly stop measuring what they claim to measure while
the numbers keep looking fine. Most of the rules below exist to prevent that.

## Layout

```
src/tactbench/
  schema.py            Moment, Signal, UserState, GoldLabel, Decision, Item
  metrics.py           ICS, hard violations, calibration, slice reporting
  runner.py            runs a policy over a split, times each decision
  cli.py               build / eval / failures / serve
  dataset/generate.py  scenario families, matched-pair generation
  dataset/loader.py    JSONL read/write, split paths
  policies/base.py     the Policy interface
  policies/builtin.py  never, always, random, heuristic
  web/server.py        stdlib-only local viewer
docs/METRICS.md        metric definitions and the reasoning behind the costs
docs/DATASET.md        construction, pairing, base rate, known weaknesses
```

## Rules that protect the benchmark's meaning

**1. The reference heuristic may not read the generator.**

`HeuristicPolicy` is restricted to structural features (user state, DND, signal
age and source, contact metadata) and generic English lexicons — words you would
have written before ever seeing this dataset. It must never match phrases lifted
from `dataset/generate.py`.

This is not hypothetical. The first draft of this repo violated it: the rules
matched strings like `"confirmed clean"` and `"started 4 minutes ago"` copied
verbatim from the generator, and scored a perfect 1.000 precision / 1.000 recall
that measured nothing except that one person wrote both files. `TestHeuristicIsHonest`
now enforces single-word lexicons with a size cap. Do not weaken it.

**2. Headroom must exist.**

If any reference baseline scores perfectly, the benchmark has stopped measuring.
`test_heuristic_does_not_solve_the_dataset` asserts this. When it fails, the fix
is harder dataset items — never a weaker assertion.

**3. Every scenario emits a matched pair.**

Positives and near-misses must share sources, vocabulary, and family, differing
only in the deciding fact. A scenario that adds a positive without its near-miss
opens a keyword-matching shortcut. Tests enforce that both halves exist per family.

**4. Hard violations are never averaged.**

Unwanted interruptions while asleep or driving, or against explicit DND, are
reported as a raw count. Do not fold them into ICS, a weighted score, or a
composite. The whole point is that they cannot be traded away.

**5. Timing and content stay separate.**

ICS scores *whether* to speak. Intent correctness is reported as its own metric
and is explicitly zero-weighted in cost (`WRONG_INTENT_COST = 0.0`). Do not merge
them — an earlier version did, and it flooded the failure viewer with correctly-
timed decisions marked as failures.

**6. Splits use `hashlib`, never `hash()`.**

Python salts string hashing per process. Using `hash()` for the dev/test split
would reshuffle it on every run and silently leak test items into dev.

**7. Labels state their provenance honestly.**

Constructed labels carry `raters: 0`. When human labels are added, record the real
rater count and agreement. Never present a constructed label as validated.

## Working on this

```bash
uv run pytest -q          # must be green before any commit
uv run ruff check .
uv run tactbench eval     # sanity-check the leaderboard still makes sense
uv run tactbench serve    # look at actual failures, not just the number
```

After changing costs, the generator, or the heuristic, **re-run `eval` and update
the results table in README.md.** A README quoting stale numbers is worse than one
quoting none.

## Priorities

In order. Each is a self-contained increment.

1. **LLM baselines** (`policies/llm.py`) — provider-agnostic, one prompt documented
   verbatim in the repo, zero-shot and cost-rubric variants. This is the result the
   project exists to produce: whether frontier models beat a few dozen lines of
   if-statements on interruption cost. Report it honestly whichever way it lands.
2. **Human-labeled subset** — a labeling CLI, multiple raters, reported κ. Measures
   how far construction drifts from what people actually want.
3. **Paraphrase expansion** — vary sentence structure, not just entities, so
   string-matching overfitting becomes genuinely impossible.
4. **Held-out test labels** — hidden behind a submission script so the leaderboard
   resists overfitting.
5. **Fatigue modeling** — session-level items where interruption cost rises with
   recent interruption frequency.

## Tone

The README's credibility rests on its limitations section. When you add a
capability, move the corresponding limitation out of that list — and when you find
a new weakness, add it. Overclaiming is the fastest way to make a benchmark
worthless.
