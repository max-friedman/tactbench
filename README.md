# TactBench

[![CI](https://github.com/max-friedman/tactbench/actions/workflows/ci.yml/badge.svg)](https://github.com/max-friedman/tactbench/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/code-MIT-blue.svg)](LICENSE)
[![Dataset: CC BY 4.0](https://img.shields.io/badge/dataset-CC%20BY%204.0-lightgrey.svg)](LICENSE-DATA)

**A benchmark for whether an assistant should speak at all.**

Nearly every LLM evaluation asks *how good is the answer*. Proactive assistants —
the notification that surfaces itself, the suggestion chip, the ambient agent —
face a prior question that no common benchmark scores: **should you have said
anything?**

That question is not accuracy. Its costs are asymmetric and state-dependent.
Interrupting someone mid-meeting is not the same mistake as interrupting them
while they wait for coffee, and neither is the same as waking them at 3am. A
system optimized for helpfulness will fail it in a specific, predictable way: it
will be helpful too often.

TactBench scores that judgment.

```bash
git clone https://github.com/max-friedman/tactbench && cd tactbench
uv run tactbench demo
```

## Results

Built-in policies on `v1/dev` (266 moments, 9 scenario families):

| policy | ICS ↓ | vs silence | prec@int ↑ | recall-hv ↑ | ECE ↓ | hard viol. ↓ | spoke |
|---|---|---|---|---|---|---|---|
| `skyline` *(ceiling, not a baseline)* | **0.0** | **+100.0** | 1.000 | 1.000 | 0.075 | 0 | 132/266 |
| `never` *(the bar)* | 354.0 | 0.0 | — | 0.000 | 0.496 | 0 | 0/266 |
| `heuristic` | 493.0 | −39.3 | 0.542 | 0.197 | 0.186 | 10 | 48/266 |
| `random@0.5` | 543.0 | −53.4 | 0.496 | 0.530 | 0.000 | 17 | 141/266 |
| `always` | 704.0 | −98.9 | 0.496 | 1.000 | 0.504 | 32 | 266/266 |

Read the `always` row carefully. It has **perfect recall** — it never misses a
single cue worth surfacing — and it is the worst policy on the board, scoring 146
points *below saying nothing at all*. That gap is the argument for this benchmark.
Optimize for helpfulness and you land on that row.

Then read the `heuristic` row. A hand-written rule set with no comprehension lands
at **0.542 precision — barely above a coin flip** — and also loses to silence. That
is by design: every surface shortcut it used to exploit has been removed from the
dataset (see [Shortcut resistance](#shortcut-resistance) below). Pattern matching
gets no traction here.

`skyline` proves the bar is clearable. It reads the same text, never sees a label,
and resolves what each moment actually turns on — which gate you're standing at,
whether the page names you or your colleague. It scores perfectly, so the headroom
between silence and solved is real. It is **not** a baseline: it's a template
parser tuned to this generator, included only to mark the ceiling.

So the standing result is: **`never` is the bar, and nothing short of genuine
comprehension has cleared it.** A proactive feature that scores worse than silence
is a feature that should not ship.

### How good does a system have to be?

The leaderboard shows chance-precision policies losing to silence and a perfect
one winning. That leaves the question every real system actually faces: *how much
comprehension is enough?*

Sweeping a policy that resolves a controlled fraction `p` of moments correctly and
guesses on the rest:

| comprehension `p` | ICS ↓ | vs silence | prec@int |
|---|---|---|---|
| 0.0 | 507.0 | −43.2 | 0.484 |
| 0.2 | 463.0 | −30.8 | 0.556 |
| **0.4** | **245.0** | **+30.8** | 0.705 |
| 0.6 | 178.0 | +49.7 | 0.836 |
| 0.8 | 105.0 | +70.3 | 0.880 |
| 1.0 | 0.0 | +100.0 | 1.000 |

**A system needs roughly 30% comprehension before it beats silence at all.** Below
that it is worse than shipping nothing, however well-intentioned — and note that
`p = 0.2` still reaches 0.556 precision, which reads as "better than a coin flip"
and is still a net loss.

The sweep also establishes that ICS is **monotone, anchored, and responsive across
the whole range** — it ranks partial comprehension rather than merely separating
none from perfect. That matters because the middle is where every real system
lands. Guarded by `TestMetricDiscrimination`; full sweep in
[`experiments/discrimination_sweep.py`](experiments/discrimination_sweep.py).

## Shortcut resistance

The claim that matched pairs prevent keyword matching is worth exactly its
evidence, so the benchmark measures it rather than asserting it:

```bash
uv run tactbench audit
```

This trains a bag-of-words classifier on **signal text alone** — no user state, no
DND flag, no slice tags — and reports how well it separates *speak* from *stay
quiet*. Chance is 50%.

**v1 failed this badly: the probe hit 93.5%.** Each scenario had one fixed phrasing
per side, so whole sentences differed and tokens like `hallway`, `inflight`, and
`closes` appeared on exactly one side. The pairing was real in structure and
useless in practice.

The fix was a construction principle: **make each pair as close to a token
permutation as the scenario allows.** Swap roles instead of rewriting sentences —
primary and secondary on-call trade places, the two boxes trade which one is still
sealed, the two meetings trade which is ahead and which has passed. Both sides then
carry nearly the same token multiset, so word statistics cannot separate them.

**All nine families sit at the chance floor. Overall: 48.1%.**

That was not always true, and the exception is worth the telling. `quiet_hours`
originally probed at **100%** and was declared irreducible — a medical emergency
is not a rearrangement of a routine check-in, so severity had to be lexical.

It wasn't. The mistake was making *severity* the decider. The emergency now sits
in the **shared body**, identical on both sides, and the judgment is whether the
user can actually do anything:

> **Positive** — *"Right now I am 6 hours out; you are the one nearby."* → **Speak.**
>
> **Near-miss** — *"Right now you are 6 hours out; I am the one nearby."* → **Say nothing.**

Waking someone at 3am about a crisis they can't reach before morning isn't help.
Waking the one person who can be there in fifteen minutes is. Same tokens, swapped
roles — and a harder judgment than spotting the word *admitted*.

**Why it mattered.** `quiet_hours` carries the highest false-positive cost in the
benchmark (asleep, DND-doubled), so it drove **82% of the gap** between `always`
and silence from 13% of the moments. Concentration plus exploitability meant a
policy matching two substrings — `admitt` / `discharg` — and coin-flipping on the
other eight families **beat silence at +28.0**, while the honest structural
heuristic scored −22.9. After the rebuild that same policy scores **−85.0**.

There is no exempt family now. `TestNoKeywordExploit` fails the build if any
keyword policy beats silence, and every family must probe under 60%.

## The metric

**ICS (Interruption Cost Score)** — total cost incurred, lower is better. Cost is
charged asymmetrically:

- **Speaking when you shouldn't** costs by what the user was doing: 1.0 idle,
  2.0 social or exercising, 5.0 in a meeting or deep work, 10.0 asleep or
  driving. Explicit DND doubles it, because ignoring a stated preference is a
  different failure from misjudging an inferred state.
- **Staying quiet when you shouldn't have** costs by what was missed: 0.5 for a
  minor cue, 3.0 for one the user is materially worse off without.
- **Being right costs nothing**, in either direction.

Reported alongside, never averaged in:

- **Hard violations** — raw count of unwanted interruptions while asleep or
  driving, or against an explicit DND. These are trust-destroying rather than
  merely annoying, so they are never allowed to disappear into an average.
- **prec@int** — of the times it spoke, how often it should have.
- **recall-hv** — of the genuinely valuable cues, how many it caught.
- **ECE** — calibration of the policy's stated confidence.
- **intent** — of correctly-timed cues, how often it said the right *thing*.
  Tracked separately and deliberately kept out of ICS: deciding *whether* to
  speak and deciding *what* to say are different capabilities, and this benchmark
  is about the first.

Full definitions in [docs/METRICS.md](docs/METRICS.md).

### Base rate — the number that decides whether to ship

The dataset is balanced 50/50 so the near-miss contrast is legible. **Production is
nothing like balanced.** A deployed assistant sees vastly more quiet moments than
loud ones — plausibly 100:1 or worse. `--base-rate` importance-weights every
stay-quiet moment accordingly:

```bash
uv run tactbench eval --base-rate 100
```

| policy | prec@int @ 1:1 | prec@int @ 100:1 |
|---|---|---|
| `skyline` | 1.000 | 1.000 |
| `heuristic` | 0.514 | **0.010** |
| `random@0.5` | 0.560 | **0.013** |
| `always` | 0.496 | **0.010** |

Precision collapses to roughly **1%** — ninety-nine of every hundred interruptions
would be unwanted. Silence and the skyline are the only rows that don't move,
because neither produces a false positive; everything else inflates around them.

This is why `never` is the reference baseline rather than a curiosity. A policy
that looks respectable on balanced data can be completely unshippable, and the
balanced number will never tell you.

## The dataset

Every moment is a frozen context slice — signals from screen, calendar, messages,
email, location, app events, sensors — plus a user-state snapshot (activity, DND,
local hour, time since last interaction).

**Moments are generated in matched pairs, built as role permutations.** Each
scenario emits a positive and a near-miss that share a byte-identical body and an
identical user state; only one *decider* signal differs, and it differs by swapping
which noun plays which role rather than by rewriting the sentence:

> **Positive** — gate moved B12 → B31, boarding in 35 minutes. *Boarding pass reads
> B31; you are seated at B12.* → **Speak** — you're at the old gate.
>
> **Near-miss** — same gate change, same 35 minutes. *Boarding pass reads B12; you
> are seated at B31.* → **Say nothing** — you're already there.

Same words, swapped positions. A classifier counting tokens sees the same evidence
in both and has to actually resolve *which gate boarding moved away from* against
*which gate you're standing at*.

User state is held identical across a pair on purpose. If the positive were set
during deep work and the near-miss while idle, the state alone would give the
answer away as surely as vocabulary did. State determines the **cost** of speaking;
the signals determine **whether**.

Nine scenario families: `travel`, `deadline`, `commerce`, `quiet_hours`, `driving`,
`meeting_prep`, `health`, `childcare`, `finance`. Slice tags (`near_miss`, `already_handled`, `not_yours`,
`too_late`, `protected_state`, `dnd_override`, `wrong_moment`) support stratified
reporting, so you can ask *which kind* of judgment a system lacks.

The hardest slice is `quiet_hours`, where value and timing point in opposite
directions:

> A starred family contact messages three times at 3am while the user is asleep
> with DND on. If it's *"Dad's in the ER, he's stable"* — **speak**; DND exists to
> be overridden by exactly this. If it's *"Are you awake? Call me when you get a
> chance"* — **stay quiet**. Same contact, same repetition, same hour. Repetition
> alone must never be enough to break DND at 3am.

Construction details and limitations in [docs/DATASET.md](docs/DATASET.md).

## Usage

```bash
uv run tactbench build                # generate the dataset splits
uv run tactbench eval                 # score every built-in policy
uv run tactbench audit                # probe the dataset for surface shortcuts
uv run tactbench failures heuristic   # inspect the costliest mistakes
uv run tactbench serve                # local viewer at :8000
```

### Running an LLM

```bash
export ANTHROPIC_API_KEY=...          # or GEMINI_API_KEY / OPENAI_API_KEY
uv run tactbench llm --variant rubric --limit 20
```

Two variants exist to separate two different explanations for failure. `naive` is
asked only whether to surface, with no cost structure disclosed — it measures the
model's untutored instinct. `rubric` is given the actual asymmetry, including that
silence is a strong baseline. A large gap between them means the capability is
there and the default disposition is wrong; a small gap means the judgment itself
is missing.

Decisions are cached per policy and split, so a paid run is never repeated. The
prompt is kept verbatim in `policies/llm.py` and versioned, so any published number
traces to the exact wording that produced it.

**No LLM numbers appear in this README, because none have been run yet.** Publishing
a figure for an experiment that was never executed would be worse than having none.

Not yet on PyPI — the name is reserved and publishing waits until LLM baselines
land, so the first release has the result that makes it worth installing.

The viewer shows the leaderboard, then every moment with gold label beside each
policy's decision — filterable to failures only, and sliceable. A benchmark that
emits only a number is hard to trust and harder to improve.

### Scoring your own system

Implement one method. Policies see moments one at a time and never see labels —
proactive assistance is an online decision, so batching would leak information a
real system wouldn't have.

```python
from tactbench.policies.base import Policy
from tactbench.schema import Decision, Moment
from tactbench.dataset.loader import load
from tactbench.runner import evaluate


class MyPolicy(Policy):
    name = "mine"

    def decide(self, moment: Moment) -> Decision:
        return Decision(moment_id=moment.id, surface=..., confidence=...)


print(evaluate(MyPolicy(), load("v1", "dev")))
```

## Honest limitations

This is v1. The things that would make it stronger are not done yet, and pretending
otherwise would defeat the purpose of building a benchmark:

- **Labels are by construction.** Each item was built around a known answer rather
  than labeled by humans afterward. That makes them internally consistent but
  unvalidated against what people actually want. A human-agreement subset with
  reported inter-rater κ is the next priority.
- **Moments are synthetic and template-generated.** Each family has 2–3 phrasings
  per side. The permutation construction means low diversity no longer implies
  guessability (the audit measures this directly), but the scenarios remain a small,
  hand-authored set — nine families is nine effective degrees of freedom, whatever
  the item count.
- **Cost is concentrated in `quiet_hours`** — 82% of the `always`-versus-silence
  gap from 13% of the moments, because a false positive while asleep under DND is
  the most expensive error the model prices. That concentration is deliberate, and
  it means the headline is sensitive to how that one family is written. It is no
  longer *exploitable* (see above), but it is still load-bearing.
- **All nine families are one author's idea of a working life** — knowledge work,
  a car, a pharmacy, school pickup. Interruption norms are culturally specific and
  this captures one culture's.
- **The 50/50 base rate is unrealistic.** Real deployments see far more quiet
  moments than loud ones. Balance makes the near-miss contrast legible; see
  [docs/DATASET.md](docs/DATASET.md) for reweighting to a realistic prior.
- **No LLM baselines yet.** The interesting result — whether frontier models beat
  a few dozen lines of if-statements on interruption cost — is the whole point and
  is not yet measured. The harness is provider-agnostic and ready for it.

The reference `heuristic` is restricted to structural features (user state, DND,
signal age and source, contact metadata) and generic English lexicons. It may not
match phrases copied from the generator, and a test enforces that — an earlier
draft violated it and scored a meaningless perfect 1.000/1.000.

## Roadmap

1. **LLM baselines** across providers, zero-shot and with an explicit cost rubric.
   With every shortcut removed and no baseline clearing silence, this is now the
   decisive experiment: can a frontier model beat saying nothing?
2. Human-labeled subset with reported agreement.
3. More scenario families — six is the real ceiling on dataset diversity now that
   phrasing has stopped being the weak point.
4. Held-out test split with hidden labels behind a submission script.

## Contributing

The most valuable contribution is usually a **near-miss pair nobody thought of**,
or evidence that a claim in this README doesn't hold. See
[CONTRIBUTING.md](CONTRIBUTING.md) — particularly the permutation rule for new
scenario families, and the invariants that may not be weakened to make the gate
pass.

Change history is in [CHANGELOG.md](CHANGELOG.md).

## License

Code is [MIT](LICENSE). Dataset content is [CC BY 4.0](LICENSE-DATA).
