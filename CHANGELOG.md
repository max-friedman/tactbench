# Changelog

Notable changes to TactBench. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
0.1.0 is the first tagged release; everything before it is recorded under that heading.

## [Unreleased]

### Fixed (Round 60)

- **The viewer escapes every text field.** Policy names, moment ids, states, slices and
  signal sources went into `innerHTML` raw, so markup planted in the payload ran in five
  of seven fields (two, `id` and `slices`, reachable from a dataset file).
  `experiments/viewer_injection_probe.py` shows it in a browser; a static allowlist
  check, with a mutation test per known bypass, gates the page script.
- **No field can end the viewer's script block.** The payload was embedded with only
  `</` rewritten; a field containing `<!--<script>` blanked the board. Every `<`, `>`, `&`
  is now a JSON escape.

### Fixed (Round 59)

- **The viewer names its dataset version** (`dataset v5 · 480 moments · …`); it never
  did, so a v2 page looked like v1's. `tests/test_web.py` now runs on every dataset on
  disk (v1-v5 and `v2para`) and asserts the exact header in the served page.

### Added (Round 55)

- **`tests/test_marker_order.py`**: the marker-aware clause-order check now covers
  `travel`, `commerce`, `pet_care` and `home_security` as well as `water_notice`, on
  every version that carries them, each with a mutation test. v2-v5 read exactly 50%;
  v1 dev fails for `travel` and `commerce` (R36's known imbalance, strict xfail). No
  data changed.

### Added (Round 54)

- **LLM results on `v5`**: all 28 runs (14 open-weight models, naive and rubric), README
  table and claims gated in `tests/test_results_v5.py`. On `water_notice` no run reads
  the decider measurably better than a coin; no verdict changes from v4.

### Fixed (Round 53)

- **The system-turn preflight measures the prompt, not the model.** It compares a short
  and a padded system turn's prompt token counts; asking the model to repeat a word
  (Llama-3.2-1B receives the turn but failed that) is now only the fallback for servers
  that report no usage. `results/SYSTEM_TURN.md`,
  written by `experiments/system_turn_check.py`, records every local model.

### Added (Round 52)

- **Dataset `v5`**: v4 plus a twelfth family, `water_notice` (480 dev / 288 test).
  Built with `tactbench build --version v5 --pairs 32 --families 12`. v1-v4 are
  unchanged and v5's first eleven families equal v4's — asserted in
  `tests/test_dataset_v5.py`. Frames chosen by search to balance eight clause
  features; unigram and bigram 50.0%; the R49 character n-gram audit holds on v5. No
  LLM has been run on v5.

### Added (Round 51)

- **`tactbench llm --provider local` checks the system turn reaches the model** before
  asking about any moment, and exits with the `--no-system-role` fix named if it
  doesn't. `LLMPolicy.system_turn_reaches_the_model()` is the one implementation;
  `experiments/run_local_llms.py` calls it. Tested against a fake server that drops
  the system turn.

### Added (Round 50)

- **Three more models on `v4`**: Granite-3.3-2B, Phi-4-mini and Mistral-7B, 6 runs
  (28 in all), with a claims block gated by `TestTheReadmeV4AddedClaims`. None beats
  silence by more than +0.7; two rubric runs speak on 1-2 of 440 moments.
- **System-turn preflight** in `experiments/run_local_llms.py`: llama-cpp-python's
  `mistral-instruct` format drops a system turn silently, so each run first checks
  the model can repeat a secret word sent there. Mistral-7B uses `--no-system-role`.

### Added (Round 49)

- **§A audit: character n-grams.** `experiments/char_ngram_audit.py` (imports nothing
  from `tactbench`) fits a 3-8-gram averaged perceptron on dev: 51.5% accuracy and 12.1%
  pairs-both-right on held-out `v4/test`; a planted mid-word suffix reads 98.5% (word
  unigrams 53.4%). A pair-aware variant picks the right side 53.3% of the time and
  never beats silence. Verdict `holds`; gated by `test_the_char_ngram_audit_holds`.

### Added (Round 48)

- **LLM results on `v4`**: the 22 open-weight runs, decisions in `results/v4-dev/`, a
  v4 README table and a claims block, each figure gated by `tests/test_results_v4.py`.
  No run gets `home_security`'s decider right (best 1 of 20 pairs); of 15 pairs
  answered differently on their two sides, 13 are backwards. Qwen2.5-0.5B naive
  becomes inconclusive (5.7% unparsed).

### Added (Round 47)

- **Dataset `v4`**: v3 plus an eleventh family, `home_security` (440 dev / 264 test).
  Built with `tactbench build --version v4 --pairs 32 --families 11`. v1-v3 are
  unchanged and v4's first ten families equal v3's — asserted in
  `tests/test_dataset_v4.py`. The skyline resolves the new family; no LLM has been run
  on v4. `experiments/clause_length_probe.feature_exploit` compares six clause
  features between the marker's clause and the other, locating the marker as the
  skyline does; the R45 length check could not fail once body order was balanced.
- `pet_care` (v3) reads 70% dev / 67% test on a longest-word rule — recorded in
  DATASET.md as a known weakness, not changed.

### Added (Round 46)

- **LLM results on `v3`**: all 22 runs, in `results/v3-dev/`. Old-family decisions are
  reused from v2 and checked equal one by one; only the 40 `pet_care` moments were
  queried. README v3 table and claims, gated by `tests/test_results_v3.py`. Qwen2.5-3B
  naive is over 5% unparsed on v3 (6.2%) and reported as inconclusive.

### Added (Round 45)

- **Dataset `v3`**: v2 plus a tenth family, `pet_care` (400 dev / 240 test). Built with
  `tactbench build --version v3 --pairs 32 --families 10`; `generate(families=)`.
  The family is appended (`LATER_SCENARIOS`, `LATER_FRAMES`), so v1 and v2 are
  unchanged and v3's first nine families equal v2's — asserted in
  `tests/test_dataset_v3.py`. The skyline resolves the new family; LLM runs on v3 are in Round 46.

### Added (Round 44)

- **mypy** over `src/tactbench` (`[tool.mypy]` in `pyproject.toml`,
  `check_untyped_defs`), run by `tests/test_types.py` so CI's test job enforces it.
  Fixed the 8 errors it found; none changed behaviour.

### Fixed (Round 43)

- Two paraphrase frames that read badly (travel's counterpart, quiet_hours'
  ungrammatical one) rewritten; `v2para` rebuilt and the 16 affected moments re-run
  for all 22 runs. The informative runs now flip 79 moments against 262 expected.

### Added (Round 42)

- **A reworded slice of v2** (`data/v2para/dev.jsonl`, `dataset/paraphrase.py`): v2
  dev's frame-0 moments with each decider re-rendered through a new frame — same
  facts, roles and ids. All 22 open-weight runs repeated on it (`results/v2para-dev/`).
- `results.paraphrase_robustness` and `experiments/paraphrase_robustness.py`: flips
  against the independence level, pairs-both-right and ICS on both wordings. The
  12 informative runs flip 78 moments against 264 expected under independence (79
  against 262 after Round 43's frame repair), but
  no run gets more than 4 of 36 pairs both right on either wording, and every run
  answers at least 27 of 36 pairs alike on both sides (`results.same_answer_pairs`):
  the stable decisions mostly do not depend on the decider. Gated in
  `tests/test_results_v2para.py`.

### Changed (Round 40)

- **`tactbench audit` prints a chance reference for the positional probe**
  (`pos. null`: median over 20 draws with each pair's labels swapped at random),
  and highlights a per-family positional figure only when it is at or above 60%
  *and* above that null. `audit.label_swap_null`, `null_readings`, `null_median`.

### Added (Round 39)

- **All 22 open-weight LLM runs re-run on dataset `v2`** (360 dev moments),
  committed in `results/v2-dev/` and published as a second README table gated
  exactly as v1's (`tests/test_results_v2.py`). The ordering, silence and pairs
  conclusions replicate: no pair of runs is reversed by ICS (5 tie on one version
  only), the median run moves 0.2 points against silence (largest 5.8) and none
  crosses it, the same six runs beat silence with zero hard violations, and the best
  pairs-both-right is 8.9%. Three details differ: 7 constant runs (v1: 8), Phi-3.5's
  prompts differ on 3 decisions, losing runs have 18-40 hard violations (v1: 11-28).
- `tactbench llm` caches per dataset version (Round 38), and README tables are read
  per version between their own markers.

### Added (Round 37)

- **Dataset `v2`**: the same generator and seed at 32 pairs per family (360 dev /
  216 test), so every (family, frame) cell is order-balanced. Against a label-swap
  null over 20 seeds, the overall positional probe exceeds 60% on 9 of 20 at 20
  pairs (null: 0) and on 0 of 20 at 32; `driving` reads exactly 50.0% on every
  seed. Per-family positional readings at this size are mostly noise (the null
  exceeds 60% in 77-101 of 180 cells), so no family's residual is evidence of a
  leak. `v1` is unchanged. `tests/test_dataset_v2.py` asserts
  the standing invariants on `v2` and its reproducibility (CI rebuilds only `v1`).

### Known defect (Round 36, open, recorded)

- **At 20 pairs per family the positional probe reads above 60% for structural
  reasons.** Clause order alternates on `idx // 8`, so a (family, frame) cell is
  balanced only with an even number of pairs; the shipped 20 leaves frames 0-3 at
  2:1 and dev 9:5 by order in every family. `driving`'s fixed 63.3% is this. At 16
  or 32 pairs every cell balances and driving reads exactly 50.0% on all 20 seeds.
  Pinned by a strict xfail; `experiments/order_balance_probe.py` prints the sweep.
  The positional probe is reported, not gated, so no published figure is wrong.

### Changed (Round 34)

- **The local viewer shows `vs pair-blind`** beside `vs silence`, and the pair-blind
  ICS beside silence's in its header — the last surface still showing only the
  shipping bar since Round 24. The viewer had no tests; `tests/test_web.py` checks
  its board against `eval`, its decisions against stored ids, and the served page.

### Measured (Round 33)

- **Hiding test labels needs private frames, not a hidden file or seed.**
  `tactbench build` regenerates `data/v1/test.jsonl` byte-for-byte (108 of 108
  labels), and the skyline — a parser of the public decider templates — scores ICS
  0.0 on held-out frames from five unseen seeds, so neither hiding the file nor a
  secret seed helps. Given only the public frames, the same parser scores exactly
  silence (144.0) on the held-out frames: private held-out frames would work. That
  needs someone to hold them and host scoring. `experiments/hidden_labels_probe.py`
  prints all three; `TestTheHeldOutSplitIsNotSecret` pins them.

### Added (Round 31)

- **`tactbench label` and `tactbench agreement`** — collect human yes/no judgments
  on a sample of whole pairs and report Fleiss' κ plus agreement with the
  constructed labels. Raters see exactly the model's view of a moment, in a
  per-rater order. κ is checked against Fleiss (1971)'s worked example (0.210). No
  human labels have been collected; every item remains `raters: 0`.

### Changed (Round 27)

- **"How much comprehension beats silence" is a range, not a number.** Two random
  choices feed the sweep, now separate knobs on `PartialSkylinePolicy`: `draw`
  (which moments are comprehended; draw 0 is unchanged) and `seed` (coin flips on
  the rest). Over 20 values of each, break-even runs 0.22–0.43 from the set alone,
  0.13–0.38 from the coin flips alone, and 0.10–0.53 from both; the published draw
  is the most favourable of 20 at `p = 0.4`. The metric's properties — monotone,
  anchored, every step above 2% of the range — hold on every draw and are asserted
  per draw. `experiments/sweep_draws.py` prints the table.

### Fixed (Round 26)

- **Policies were handed the label, twice.** The two sides of every pair differ in
  their `slices` tags and in their `id` (`travel-pos-0003` / `travel-near-0003`); a
  one-line policy reading either scored ICS 0.0 on dev and held-out — tying the
  skyline. `policies.base.ask` is now the one path to `Policy.decide` (runner, `llm`
  command, `Policy.run`): the policy sees `schema.policy_view` — no `slices`, an
  opaque `id` — and its decision is mapped back to the stored id. A test asserts a
  pair's two views differ only in the decider text and the opaque id. Leaderboard and
  LLM table unchanged. Three figures moved because they hash the id: the Round 9
  keyword policy (−89.3 → −78.0 vs silence); the comprehension sweep, whose
  break-even moved 0.29 → 0.23; and METRICS.md's implied-comprehension span, 0.36 →
  0.274. The sweep is therefore one draw; it and the implied table are now gated
  and labelled as such. A test scans `src/` and `experiments/` for any call to
  `decide` that bypasses `ask`.

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
  Bigrams **reached 97.2% in Round 11**; every family has read 50.0% on both columns
  since Round 13 held decider phrasings out of the training split, and Round 16's
  prose deciders kept it there. (This entry said "reach 97.2%" in the present tense
  until Round 32.) `audit.verbatim_overlap` additionally measures how much held-out
  text is published verbatim in `dev`.

### Changed (Round 21)

- **The shortcut probe's signal join is kept, and its cost is pinned at zero.**
  `audit.item_tokens` joins every signal before tokenizing, so bigrams cross the
  body/decider junction. Kept deliberately: a submitter chooses their own
  serialization, so the probe takes the upper bound. `TestSignalJoinIsFree` asserts
  joined and per-signal bigram accuracy are exactly equal, with no tolerance.

### Fixed (Rounds 19 and 20)

- **An order-balance invariant had been hollow since Round 16.**
  `TestOrderBalancePrecondition` tagged clause order by the text before a colon;
  Round 16's prose deciders have no colon, so the tag became the whole sentence and
  the test silently measured entity variety instead. Collapsing one family's clause
  order passed the suite for 3 of 9 families. The tag now reads clause order
  directly. Round 19 first reported "5 of 9" from three measurements; Round 20
  measured all nine and corrected it to 6 of 9 enforced.

### Added (Rounds 17 and 18)

- **`TestReadmeResultsAreCurrent`** fails the build when the README's results table
  disagrees with a fresh `eval` (Round 17, after the table went stale twice), and
  `test_prose_figures_match_a_fresh_eval` extends it to figures quoted in prose
  (Round 18, after the first version covered only the table rows while the README
  sentence beside it claimed more).

### Changed (Rounds 15 and 16)

- **Deciders are prose again.** Round 13's `Label: value` frames closed the surface
  exploit but read like status lines. Round 15 rebuilt them as prose, found the
  leak returned, and rejected the attempt with a rule (the filler may not be
  clause-initial). Round 16 found that rule necessary but not sufficient and
  restored prose under three structural properties, asserted in
  `TestProseFrameStructure`; all nine families read 50.0% on the unigram and bigram
  probes.

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
- **Known cost (resolved in Round 16):** deciders are now uniform `Label: value.`
  lines, which reads like a status line rather than a real message. Restoring prose
  while keeping the guarantee is the top queue item. *Round 16 did; see above.*

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
