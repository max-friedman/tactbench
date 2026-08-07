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

### Pairing alone was not enough

v1 emitted matched pairs and claimed they prevented keyword matching. **The claim
was false and the audit proved it:** a bag-of-words classifier that never saw user
state separated the two sides at **93.5%**. The pairs shared a *family*, but each
side was written as different sentences, so tokens like `hallway`, `inflight`, and
`closes` appeared on exactly one of them and handed over the answer.

Structural pairing is not the same as lexical pairing. The fix is a construction
rule:

> **Both sides share a byte-identical body and an identical user state. Only one
> decider signal differs, and it differs by permuting which noun plays which role
> — never by rewriting the sentence.**

| family | shared body | decider (positive → near-miss) |
|---|---|---|
| `travel` | gate moved A → B, boarding in *n* min | pass reads **B**, you're seated at **A** → pass reads **A**, you're seated at **B** |
| `deadline` | deploy failed, auto-rolled back | primary: **you**, backup: **Priya** → primary: **Priya**, backup: **you** |
| `commerce` | return window closes in *n* hours | **desk** boxed, **replacement** assembled → **replacement** boxed, **desk** assembled |
| `meeting_prep` | revised contract unread, 90 min old | **review** begins in *n*, **standup** began *n* ago → **standup** begins in *n*, **review** began *n* ago |
| `driving` | flight departs in *n* hours | **your route** backed up, **alternate** clear → **alternate** backed up, **your route** clear |
| `quiet_hours` | *n*th message from Mom, **and the admission itself** | **you** are nearby / Mom is hours out → **Mom** is nearby / you are hours out |

All nine are token permutations: both sides contain the same words, arranged
differently. Every family probes at the 50% chance floor.

`quiet_hours` was not always in that list. It originally turned on severity —
*admitted* versus *discharged* — and was declared irreducible on the reasoning
that a medical emergency is not a rearrangement of a routine check-in. It probed
at 100% and was exempted from the per-family assertion by name.

**The exemption was the error, not the family.** Because `quiet_hours` carries the
highest false-positive cost in the benchmark, it drove 87% of the gap between
`always` and silence from 11% of the moments — so a policy matching `admitt` /
`discharg` and coin-flipping on the other eight families beat silence, while the
honest structural heuristic did not.

The decider was simply on the wrong axis. Moving the admission into the shared
body and asking *who can actually get there tonight* permutes cleanly and poses a
harder question. If a family looks irreducible, look for a different decider
before granting an exception.

### User state is held constant across a pair

If the positive were set during deep work and its near-miss while idle, state would
give the answer away as surely as vocabulary did. So both sides of a pair carry the
identical `UserState`.

This has a consequence worth stating plainly: **state carries no information about
`should_surface`.** It determines the *cost* of being wrong, not the answer. A
policy that reasons only about activity and DND can avoid hard violations but
cannot do better than chance on whether to speak — which is why every non-skyline
baseline now scores worse than silence.

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

To evaluate against a realistic prior, pass `--base-rate`:

```bash
tactbench eval --base-rate 100
```

Every stay-quiet item is importance-weighted by the ratio, so it stands in for the
hundred real quiet moments it represents. Precision is weighted too, and reports
what it would be in production rather than in the artificial split — it collapses
from roughly 0.5 to roughly 0.01.

Silence and the skyline are unaffected, because neither produces a false positive.
Everything else inflates around them, which is exactly why `never` is the reference
baseline and not a curiosity.

Hard violations are deliberately **not** reweighted: they count distinct moments in
the benchmark, not an estimate of production volume, and conflating the two would
make the number mean nothing.

## Splitting

`dev` / `test` are split on `sha256(pair_key(moment_id))[0] % 100 < 60` — **246
dev / 114 test**.

Two things about that expression are load-bearing, and each was learned by getting
it wrong.

**Not Python's `hash()`.** String hashing is salted per process, so `hash()` would
reshuffle the split on every run and silently leak test items into dev. The digest
is stable across processes, machines, and Python versions.

**Not the moment id — the *pair* key.** A pair's two sides must always travel
together into the same split. This is not tidiness; it is the difference between
a held-out set and a published one. Both sides share a byte-identical body and an
identical `UserState`, differing only in which noun plays which role, so an
orphaned test item is a near-verbatim copy of a dev item **carrying the opposite
label**.

Round 10 found the split bucketing on `moment.id`, which names an item rather than
a pair. The two halves were therefore assigned independently, and:

| | |
|---|---|
| pairs divided across dev and test | **72 of 180** |
| held-out items whose partner was published in dev | **72 of 94 (77%)** |
| of those, answered by negating the partner's label | **72 of 72** |
| test-split accuracy by table lookup, no model | **88.3%** |

`moment.id` is public, so the pair key is public, so the partner is findable. A
pair has exactly one speak side and one stay-quiet side — reading the partner's
label out of `dev.jsonl` and negating it gave the answer outright. No learning, no
text analysis, nothing that isn't shipped in the repo.

The audit had always kept pairs whole across its own cross-validation folds, with
a comment explaining that splitting one "would let the probe memorize one half and
trivially answer the other." The artifact it was auditing did not. `pair_key` in
`schema.py` is now the single definition, used by both.

`TestSplitIntegrity` enforces this on the generator *and* on the shipped `.jsonl`
files, and asserts that partner-lookup recovers nothing.

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

- **Nine families is nine degrees of freedom.** Phrasing is no longer the weak point —
  the audit confirms word statistics don't carry the answer — but the *scenarios*
  are still a small hand-authored set. Item count overstates diversity. More
  families is the highest-value expansion.
- **Cost is concentrated in `quiet_hours`** — 87% of the `always`-vs-silence gap
  from 11% of moments, because a false positive while asleep under DND is the most
  expensive error priced. Deliberate, but it makes the headline sensitive to how
  that one family is written.
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
