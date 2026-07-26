# Dataset

## Structure

Splits live in `data/<version>/<split>.jsonl`, one JSON object per line, each an
`Item` — a `Moment` paired with its `GoldLabel`.

A **moment** is everything a policy is allowed to see:

- **signals** — observations from `screen`, `calendar`, `message`, `email`,
  `location`, `app_event`, `notification`, `sensor`. Each carries `age_s` (how
  stale it is) and optional `meta` (sender, contact class, priority).
- **user_state** — `activity`, `dnd`, `device`, `last_interaction_s`, `local_hour`.
- **family** and **slices** — for stratified reporting. Not visible to policies in
  any meaningful sense (they describe provenance, not content), but excluded from
  prompts by convention.

A **gold label** carries `should_surface`, a `value` in 0–3, `acceptable_intents`,
an optional `window_s`, a human-readable `rationale`, and `raters` / `agreement`
for labels that have been through human review.

## Why moments come in matched pairs

This is the load-bearing design decision.

A benchmark of "should the assistant speak?" is trivially gameable if the items
that warrant speech look different on the surface from the ones that don't. Any
policy could match keywords — *delayed*, *expires*, *overdue*, *failed* — and post
a strong score without having judged anything at all.

So every scenario emits a **matched pair**. The positive and the near-miss share
signal sources, vocabulary, scenario family, and usually user state. They differ
only in the fact that actually settles the question:

| family | positive | near-miss | what differs |
|---|---|---|---|
| `travel` | gate changed, user reading news, 8 min walk away | gate changed, user already seated at the new gate with updated pass on screen | already handled |
| `deadline` | prod deploy failed, **you** are on-call, others blocked | prod deploy failed, **Priya** is on-call and has confirmed it clean | not yours, resolved |
| `commerce` | return window closes tomorrow, user idle, signalled intent to return | price dropped 12%, user is mid-quarterly-review | value vs. moment cost |
| `quiet_hours` | 3am, starred contact, *"Dad's in the ER, he's stable"* | 3am, starred contact, *"Are you awake? Call me sometime"* | severity |
| `driving` | route delayed 40 min, alternate saves 25, flight in 2h | route clear, inflight menu available to pre-order | actionability |
| `meeting_prep` | contract review in 12 min, revised terms unread | contract review started 4 min ago, revised terms unread | lead time |

The `quiet_hours` pair is the sharpest. Same contact, same repetition, same hour,
same DND state — and opposite correct answers. Repetition alone must never be
enough to break DND at 3am, but a medical emergency from a starred contact must
get through. A policy that keys on "starred contact messaged repeatedly" gets one
of the two right and pays full price for the other.

## How labels are assigned

**v1 labels are by construction.** Each item was built around a known answer rather
than shown to raters afterward. This is a genuine limitation:

- Labels are internally consistent and the rationale is always available.
- They are *unvalidated against what people actually want*. If the author's
  intuitions about interruption cost are wrong, the benchmark encodes those wrong
  intuitions with total confidence.

Items carry `raters: 0` and `agreement: 1.0` to mark this honestly. A
human-labeled subset with reported inter-rater κ is the top roadmap item, and
`raters` / `agreement` exist so that constructed and human-validated items can
coexist in one file and be filtered apart.

## Base rate

Generation is **50/50** speak / stay-quiet by construction.

This is not realistic. A deployed assistant sees vastly more quiet moments than
loud ones — plausibly 100:1 or worse. Balance is chosen so the near-miss contrast
is legible and so slice-level numbers aren't computed over a handful of items.

To evaluate against a realistic prior, reweight false-positive cost by the ratio
you expect. At a 100:1 quiet-to-loud base rate, multiply every false-positive cost
by 100 before aggregating; the ordering of policies changes sharply, and `never`
becomes much harder to beat. That is the correct intuition for production, and the
reason `never` is the reference baseline rather than a curiosity.

## Splitting

`dev` / `test` are split on `sha256(moment_id)[0] % 100 < 60`.

Deliberately **not** Python's `hash()` — string hashing is salted per process, so
`hash()` would reshuffle the split on every run and silently leak test items into
dev. The digest is stable across processes, machines, and Python versions.

Regeneration with the same seed reproduces both splits exactly.

## Extending it

Add a `Scenario` subclass in `src/tactbench/dataset/generate.py` implementing
`positive()` and `near_miss()`, and register it in `SCENARIOS`. The test suite
enforces the invariants that make the benchmark meaningful:

- every family contributes both a positive and a near-miss
- every near-miss is tagged `near_miss` for slicing
- every positive names at least one acceptable intent
- generation is deterministic under a fixed seed
- the reference heuristic does not score perfectly (headroom must exist)

## Known weaknesses

- **Low phrasing diversity.** Templates vary entities (gate numbers, hours) but not
  sentence structure. A determined string matcher could still overfit despite the
  paired design. Paraphrase expansion is planned.
- **Independent moments.** Real interruption cost depends on how recently the user
  was last interrupted. Modeling fatigue requires session-level items.
- **Western, knowledge-worker, English-only.** The scenarios assume a particular
  working life. Interruption norms are culturally specific and this captures one
  culture's.
- **No adversarial authorship.** Every item was written by the same person who
  wrote the baselines. External contributions of near-miss pairs are the highest-
  value thing an outside contributor can add.

## License

Dataset content is CC BY 4.0. Code is MIT.
