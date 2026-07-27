# Contributor & agent guide

**Working the improvement loop? Read [`docs/plans/LOOP_STATE.md`](docs/plans/LOOP_STATE.md)
first and write it last.** It holds the queue, the coverage map, the NEEDS-MAX list,
and the standing invariants. Context is lost between rounds; that file is not.

## Where the method lives

This project is run with the **[agentic coding loop](https://github.com/max-friedman/agentic-coding-loop)**.
That repo is the source of truth for *how* to make changes here — what a round is,
how it ends, and the principles it runs on. This file covers what is specific to
TactBench; it does not restate the method.

Read before your first round:

- **[`LOOP.md`](https://github.com/max-friedman/agentic-coding-loop/blob/main/LOOP.md)**
  — self-contained: round steps, hard rules, ending states, the audit round, and
  continuous operation. Nothing else needs fetching. Raw URL for an agent:
  `https://raw.githubusercontent.com/max-friedman/agentic-coding-loop/main/LOOP.md`
- **[The principles](https://github.com/max-friedman/agentic-coding-loop/blob/main/docs/PRINCIPLES.md)**
  — the rules the loop runs on. Principles 3 and 4 are the ones this project
  breaks first if you're not careful: *build the check before the thing*, and
  *invariants may not be weakened*.

**Improvements to the method go upstream — as an issue, never as a pull request.**
If a round teaches something durable about running an agentic loop — as opposed to
something about proactive assistance — file it with the **Loop proposal** form on
`agentic-coding-loop`, or run its `loop-feedback` skill. A maintainer writes the
change; proposals themselves are inert. Do **not** open a PR editing the loop's
docs, and do **not** patch the loop's instructions locally to compensate — a local
fork is invisible to every other project running the loop and is overwritten on
the next update.

Note the candidate in `LOOP_STATE.md` under *Method findings* so it isn't lost,
then send it up. A lesson recorded only in the project that discovered it is a
lesson every other project will re-learn.

Read the rest of this file before changing anything. TactBench is a benchmark, and benchmarks fail
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

**2. Headroom must exist, and the task must stay solvable.**

Two failure directions, both fatal. If a reference baseline scores perfectly the
benchmark has stopped measuring; `test_heuristic_does_not_solve_the_dataset` catches
that. If *nothing* can beat silence the benchmark is degenerate; `test_task_is_solvable`
catches that by requiring the skyline to clear the bar. When either fails, the fix is
the dataset — never a weaker assertion.

**3. Pairs are role permutations, not just matched families.**

Both sides share a byte-identical body and an identical `UserState`. One decider
signal differs, and it differs by **swapping which noun plays which role** — never by
rewriting the sentence.

This rule was learned the hard way. v1 emitted matched pairs and claimed they stopped
keyword matching; the audit measured **93.5%** for a bag-of-words probe that never saw
user state, because each side was written as different sentences. Structural pairing
is not lexical pairing. When adding a scenario, run `tactbench audit` and confirm the
new family lands near 50% — if it doesn't, you wrote two sentences instead of one
permutation.

`quiet_hours` is the standing exception (severity isn't permutable) and is excluded
from the per-family assertion by name. Don't add more exceptions.

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
