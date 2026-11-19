# Changelog

Notable changes to TactBench. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
0.1.0 is the first tagged release; everything before it is recorded under that heading.

## [Unreleased]

### Fixed (Round 26)

- **Policies were handed the label in `moment.slices`.** The two sides of every pair
  differ in their reporting tags, and a three-line policy speaking whenever
  `near_miss` was absent scored ICS 0.0 on dev and held-out — tying the skyline.
  `schema.policy_view` now empties `slices` on every path to `Policy.decide`
  (`runner.run_policy`, the `llm` command). No published figure changes: the
  built-in policies never read slices, and the LLM prompt already omitted them.

### Fixed (Rounds 22 and 25)

- **The positional figure's seed spread is published per family, and gated.** Round
  22 measured the leakage probes over 20 build seeds (the gated unigram and bigram
  probes do not move at all; `TestGatedProbesAreSeedStable`) and published "6 to 14
  seeds out of 20" for families above 60% on the positional probe, with no script
  behind it. The true range is 3 to 20. `experiments/seed_spread_probe.py` now
  prints the table, `docs/DATASET.md` carries it, and a test recomputes it.
  `driving` reads a constant 63.3% on every seed — its deciders contain no
  seed-drawn entity — so for that family the figure is a property of the frames,
  not a draw.

### Added (Round 24)

- **The pair-blind bar** (`runner.pair_blind_ics`), reported as a `vs pair-blind`
  column beside `vs silence` in `eval`, `llm`, `results` and both README tables.
  It is the best cost any policy reaches without telling a matched pair's sides
  apart, never paying with a hard violation. Silence stays the bar for worth
  shipping; this is the bar for reading the moment. ICS 238 on `v1/dev` against
  silence's 336. No LLM measured so far clears it. Costs are unchanged.

### Added (Round 23)

- **The first LLM results**: eleven open-weight instruction models from 0.5B to
  8B parameters, Q4_K_M, on CPU through llama.cpp at temperature 0, both prompt
  variants, on `v1/dev`. Decisions are committed in `results/v1-dev/`, weights'
  sha256 and runtime in `results/MANIFEST.json`, and the README table is gated
  against a fresh re-score by `tests/test_results.py`. No hosted frontier model
  has been run.
- **`--provider local`** for any OpenAI-compatible server, with no key and no
  default model; `--no-system-role` for chat templates that reject a system turn.
- **`tactbench results`**, which prints the README table from committed runs,
  with two new columns: `pairs` (both sides of a matched pair right — a constant
  policy scores exactly 0%) and `unparsed`.
- `experiments/run_local_llms.py`, which reproduces every row from the weights.

### Fixed (Round 23)

- **The LLM response parser scored `"false"` as speaking.** It cast the field
  with `bool()`, so a quoted `"false"`, `"no"` or `"maybe"` was an interruption;
  an answer missing the decision was silently silence; and a stray trailing brace
  made a valid answer unreadable. Four of six constructed cases were scored
  wrong. Non-answers are now counted as `unparsed` and reported.

## [0.1.0] - 2026-11-12

First tagged release: dataset `v1` (360 items, 252 dev / 108 test), the ICS metric,
the built-in policies, the shortcut audit and the provider-agnostic LLM harness.
LLM baselines have not been run. The README's *Honest limitations* section is the
current list of what this release does not measure; the dated sections below are
the history that led here.

### Added

- **`docs/leaderboard.svg`**, the README's headline chart. It is rendered from a
  fresh eval by `experiments/leaderboard_chart.py`, never from typed numbers, so it
  cannot drift from the results table that `TestReadmeResultsAreCurrent` guards.

### Changed

- **The shortcut audit reports a bigram column, and the verdict of whichever probe
  is worse.** A bag of words cannot see word order, and the matched-pair design
  makes both sides carry the same token multiset — so the unigram probe was
  *structurally incapable* of separating a pair and reported 50.0% for ten rounds.
  Bigrams reach **97.2%**. `audit.verbatim_overlap` additionally measures how much
  held-out text is published verbatim in `dev`.

### Fixed (Round 14)

- **`MIN_PAIRS_FOR_BALANCED_ORDER`.** Clause order alternates on a pair's index
  within its frame, so fewer than two pairs per frame (16 per family) leaves cells
  single-order — 54 of 72 at ten pairs — and a position-tagged probe then separates
  the set at ~74%. Round 13 measured exactly that, from a test calling
  `generate(10)`, and recorded it as a dataset defect in three documents. At a legal
  size the probe reads 52%. The precondition is now stated, asserted in both
  directions, and the positional probe is gated overall alongside the other two.

### Fixed (Round 13) — the surface-model exploit is closed

- **Held-out phrasings.** Every decider is now rendered from a shared frame table
  (`FRAMES[family]`, eight `(privileged_label, other_label)` entries), and the
  dev/test split is taken **on the frame** — 0–4 train, 5–7 held out. A held-out
  item is worded in a way that appears nowhere in training, so verbatim overlap is
  **zero by construction** rather than merely small.
  A bag-of-bigrams fit on `dev` and graded on held-out `test` goes from **+99.4 to
  +0.0 versus silence, two-sided** — it ties saying nothing and never beats it,
  across 30 seeds. The dict-lookup exploit falls to chance. The two `strict=True`
  xfails that recorded this defect for two rounds are now ordinary assertions.
  Four properties were needed, and three of them were found by measurement after
  the first draft claimed a closure it had not earned: frames must be pairwise
  lexically disjoint (not merely disjoint across the split), a frame's two labels
  must carry the same token count, and clause order must alternate *within* each
  frame rather than being drawn from a digest.
- **A third, position-tagged probe** is reported by `tactbench audit`. It is not
  gated — it separates the full generated set at 74% — but a positional policy is
  held to the same "must not beat silence" standard, which it loses by 16 points.
- **`travel`'s gate pool** was ten codes, so a code landed on the "old gate" side
  more often than chance and a bigram read the bias. Now 240 codes.
- **The permutation now holds by construction.** Frames are filled with
  `(marker, counterpart)` and the pair's sides swap them, so an author cannot
  accidentally write two sentences instead of one permutation.
- **`SkylinePolicy` stopped being a lookup.** Nine hand-written matchers became one
  resolver over the generator's frame table. `_commerce` matched the literal
  `"the desk"` and `_meeting_prep` matched `"contract review"` — they resolved
  nothing and worked only because those nouns never varied. Still zero
  disagreements across all nine families.
- **Known cost:** deciders are now uniform `Label: value.` lines, which reads like
  a status line rather than a real message. Restoring prose while keeping the
  guarantee is the top queue item.

### Changed (Round 12)

- **Decider entities are drawn per pair** instead of baked into the template. Four
  families hardcoded a single counterpart ("Priya Raman", "Sam", "Dana", "the
  desk") and so emitted only **4 distinct decider sentences** however many pairs
  were generated; every family now yields 24–38. Both sides of a pair still take
  the same entity — the permutation is which role it plays — so this cannot leak.
  Verbatim decider overlap between the splits falls **91.2% → 29.8%** and wholly
  duplicate held-out items **49.1% → 7.0%**.
  **This did not fix the exploit** (+99.4 → +98.1 versus silence). The frame
  carries the label, not the entity, and there are still two frames per family.
  Recorded as a measured negative result; see the known defect below.

### Known defect (open, recorded, not worked around)

- **The dataset is currently solvable by surface pattern matching.** A
  bag-of-bigrams fit on `dev` scores **+98.1** versus silence on held-out `test`
  (ICS 3.0 against a skyline of 0.0), at 0.982 precision. Each family has only
  **two structural frames**, and the frame carries the label. Round 12 removed most
  of the duplicate text that Round 11 blamed and the exploit barely moved, which
  localises the cause: it is frame scarcity, not entity scarcity. This is a near-duplicate leak, distinct from the pair-key split fixed
  above: a split can be perfectly pair-whole and still publish its own answers.
  Pinned by two `strict=True` xfails so repairing the dataset fails the build and
  forces the assertions to be tightened. **The fix is paraphrase expansion, not a
  weaker bound.** Until it lands, read every leaderboard number as measuring a task
  a lookup table can mostly solve.

### Fixed

- **The held-out split was published.** `tactbench build` bucketed dev/test on
  `moment.id`, which names an item rather than a pair, so 72 of 180 matched pairs
  were divided across the split. Because a pair's two sides share a byte-identical
  body and differ only in which noun plays which role, 77% of the test split was a
  near-verbatim copy of a dev item under the opposite label — and **88.3% of it was
  answerable by table lookup against the published `dev.jsonl`, with no model**.
  The split now buckets on `schema.pair_key`, the single definition of a pair, used
  by the audit and the splitter alike. Dev/test moves 266/94 → **246/114** and every
  published number has been re-run. `TestSplitIntegrity` guards it, including that
  the shipped `data/v1` still equals what the generator produces.
- **The shortcut audit was one-sided.** Both thresholds bounded raw accuracy, so a
  family probing at 32.8% passed and printed "at chance" — while negating that
  probe scores 67.2%, above the bar. Leakage is now `|accuracy − 0.5|` and the
  bounds apply to `exploitable_accuracy`, in the tests *and* in `tactbench audit`.
- **Pair sides shared mutable state.** Both halves referenced the same `Signal`
  and `UserState` objects, so editing one item's text edited its partner's. Latent
  until anything mutates items in place — which paraphrase expansion will.

### Added

- **Engineering hygiene.** CI on Python 3.11–3.13 (tests, lint, format check, a
  dataset-reproducibility job that fails if `data/` drifts from the generator, and
  a visible shortcut-audit run; the audit job reports but does not yet gate on the
  bigram probe — see the known defect above). `CONTRIBUTING.md`, this changelog, a PR template,
  and `LICENSE-DATA` for the CC BY 4.0 dataset terms the README already claimed.
- **Base-rate reweighting** (`--base-rate`). Scores against a realistic
  quiet-to-loud prior instead of the balanced split. At 100:1, heuristic precision
  falls from 0.500 to **0.010** — ninety-nine of every hundred interruptions would
  be unwanted. Silence and skyline are the only rows that don't move.
- **Three scenario families**: `health`, `childcare`, `finance`. Dataset grew from
  240 to 360 items across 9 families.
- **`policies/llm.py`** — provider-agnostic LLM policy (Anthropic / Gemini /
  OpenAI), one moment per call, versioned prompt kept verbatim in source, two
  variants (`naive` withholds the cost structure, `rubric` discloses it). Plus
  `tactbench llm` with per-run caching. **Never executed** — no API key available,
  and no numbers are published for an unrun experiment.
- **`audit.py`** and `tactbench audit` — a dependency-free bag-of-words probe (joined in Round 11 by a bigram probe) that
  measures whether signal text alone can answer the benchmark.
- **`policies/skyline.py`** — the achievable ceiling, and a standing
  label-consistency check.

### Changed

- **Pair construction rebuilt around role permutation.** Both sides of a pair now
  share a byte-identical body and an identical `UserState`; only one decider signal
  differs, by swapping which noun plays which role. Shortcut probe: **93.5% →
  55.6%**, with 8 of 9 families at the 0.500 chance floor. (Superseded: after
  the Round 10 split fix every family probes at exactly 50.0%.)
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
- ~~`quiet_hours` leaks at 100% and structurally cannot be permuted.~~ Since fixed:
  the family is now a role permutation and probes at chance (see the README).
- Nine families is nine degrees of freedom, whatever the item count.
