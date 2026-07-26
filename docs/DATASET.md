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
| `quiet_hours` | *n*th message from Mom in ten minutes | Dad is being **admitted** → Dad is being **discharged** |

The first five are token permutations: both sides contain the same words, arranged
differently. Each probes at the 50% chance floor.

`quiet_hours` is the exception and always will be. A medical emergency is not a
rearrangement of a routine check-in, so severity there is irreducibly lexical and
the family probes at **91.4%**. It is kept because the judgment it poses is real —
DND exists to be overridden by exactly this, and repetition alone must never be
enough at 3am — but any system scoring well on that family alone may just be
reading `admitting` versus `discharging`.

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

- **Six families is six degrees of freedom.** Phrasing is no longer the weak point —
  the audit confirms word statistics don't carry the answer — but the *scenarios*
  are still a small hand-authored set. Item count overstates diversity. More
  families is the highest-value expansion.
- **`quiet_hours` leaks at 91.4%** and structurally cannot be fixed by permutation.
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
