# Metrics

## Why accuracy is the wrong metric

Treat "should the assistant speak?" as binary classification and you get a number
that is actively misleading. Accuracy weights every mistake equally, and these
mistakes are not equal in any dimension that matters:

- Interrupting deep work costs more than interrupting an idle user.
- Waking someone at 3am costs more than either.
- Missing a gate change costs more than missing a price drop.
- Being wrong against an *explicitly stated* preference (DND) is a different kind
  of failure from being wrong about an *inferred* state.

An accuracy-optimizing system converges on the `always` policy, which on this
benchmark has perfect recall and is the worst policy measured. So the headline
number has to price the asymmetry directly.

## ICS — Interruption Cost Score

Total cost incurred across the split. **Lower is better.** Zero is perfect.

### False positive — spoke when it shouldn't have

Cost by user activity:

| activity | cost |
|---|---|
| `sleeping` | 10.0 |
| `driving` | 10.0 |
| `meeting` | 5.0 |
| `focused_work` | 5.0 |
| `exercising` | 2.0 |
| `social` | 2.0 |
| `commuting` | 1.0 |
| `idle` | 1.0 |

Multiplied by **2.0** when DND is set.

The ratios encode a product claim: unwanted interruptions during focus are what
make people turn proactive features off permanently, and interruptions while
asleep or driving are what make them distrust the device. An interruption while
idle is a minor annoyance and priced accordingly.

### False negative — stayed quiet when it shouldn't have

Cost by the gold `value` of the missed cue:

| value | meaning | cost |
|---|---|---|
| 0 | actively harmful to surface | 0.0 |
| 1 | mildly useful | 0.5 |
| 2 | clearly useful | 2.0 |
| 3 | user is materially worse off without it | 3.0 |

Note the ceiling: the worst possible miss (3.0) costs less than a single unwanted
interruption during a meeting (5.0). That is deliberate and is the benchmark's
strongest opinion. It reflects how proactive features actually die — not from
being insufficiently helpful, but from being annoying enough to disable.

### Correct decisions

Cost 0.0, in both directions. Correctly staying quiet is a success, not a neutral
non-event, and the scoring says so.

### Normalization

`ics_normalized` maps the silence baseline to **0** and zero cost to **100**:

```
ics_normalized = 100 × (1 − ics / ics_of_never_policy)
```

A negative value means the system is worse than shipping nothing. This is the
number to quote, because it answers the only question a PM actually has: *is this
feature worth turning on?*

It is also percent-of-achievable, because the `skyline` policy scores exactly 0
cost — so 100 is not a theoretical ceiling, it is a reached one. See
[The skyline](#the-skyline) below.

### Base rate

Every figure above is computed on a **balanced 50/50 split**. Production is not
balanced: a deployed assistant sees vastly more quiet moments than loud ones,
plausibly 100:1 or worse. `--base-rate` importance-weights each stay-quiet moment
by that ratio, so it stands in for the real moments it represents:

```bash
tactbench eval --base-rate 100
```

`precision_at_interrupt` is weighted too, and reports the production figure rather
than an artifact of the split. The effect is not subtle:

| policy | prec@int @ 1:1 | prec@int @ 100:1 |
|---|---|---|
| `skyline` | 1.000 | 1.000 |
| `heuristic` | 0.500 | **0.010** |
| `always` | 0.500 | **0.010** |

Two rows do not move — `never` and `skyline` — because neither produces a false
positive. Everything else inflates around them, which is the concrete reason
silence is the reference baseline rather than a curiosity.

Two deliberate choices:

- **Hard violations are never reweighted.** They count distinct moments in the
  benchmark, not estimated production volume. Blending the two would leave the
  number meaning neither.
- **`base_rate < 1` raises** rather than silently inverting the caller's intent.

## Hard violations

A raw count of unwanted interruptions that occurred while the user was asleep or
driving, or against an explicit DND.

These are **reported separately and never folded into any average.** A system with
excellent ICS and three hard violations has not made a good tradeoff — it has
broken trust three times, and averaging would hide that. Treat any non-zero count
as a blocker regardless of the headline score.

## Supporting metrics

**prec@int** — of the moments where the policy spoke, the fraction where it should
have. Undefined (`—`) for a policy that never speaks.

**recall-hv** — of the moments with gold `value ≥ 2`, the fraction the policy
caught. Restricted to high-value cues deliberately: recall over *all* positives
rewards firing on trivia.

**ECE** — expected calibration error over the policy's stated confidence, in 10
bins. Confidence is interpreted as *P(my decision is correct)*, so a policy that
doesn't model it sits at 0.5 and lands in the middle bin, which is the honest place
for it to be. Calibration matters here more than in most benchmarks: a real
deployment wants to route low-confidence moments to silence, and it cannot do that
if confidence is uninformative.

**intent** — of correctly-timed cues where the policy named an intent, the fraction
naming an acceptable one. **Excluded from ICS by design.** Deciding whether to
speak and deciding what to say are different capabilities; charging content errors
into ICS would let a policy with flawless timing look bad for emitting a generic
label, which is not the failure mode under study. Policies that name no intent are
scored `—` rather than penalized.

**timeliness** — of correctly-surfaced cues carrying a `window_s`, the fraction
delivered inside it. A reroute alert is worthless one exit later.

## The skyline

`skyline` is reported on the leaderboard but is **not a baseline**. It reads the
same signal text every other policy sees, never touches a gold label, and resolves
the semantic relation each moment turns on — which gate boarding moved away from
versus which gate you're standing at; whether the page names you as primary or as
backup.

It exists to answer an objection. Once the dataset's lexical shortcuts were
removed, every reference baseline scored *worse than silence*, which invites the
reading that "beat silence" is an impossible bar and the benchmark is degenerate.
The skyline scores ICS 0 with zero hard violations, so the headroom between
silence and solved is real and the task is solvable.

It is a template parser tuned to this generator and collapses on moments phrased
even slightly differently. **Treat a submitted policy that looks like it as
overfitting, not progress.** Its second job is as a standing label-consistency
check: if it ever disagrees with a gold label, the dataset contradicts its own
stated semantics. That check caught an inverted `travel` pair.

## Does the metric discriminate?

A metric can look healthy at its endpoints and be useless in between. ICS
separates chance-precision policies from a perfect one — but every real system
lands in the middle, so the question that matters is whether ICS *ranks* partial
comprehension.

`PartialSkylinePolicy(p)` answers it by construction: it resolves the deciding
relation on a deterministic fraction `p` of moments and coin-flips on the rest,
interpolating between `random@0.5` and the skyline. The comprehending set is
chosen by hash rather than sampled, so it is **nested** — raising `p` only adds
moments. Without that, a non-monotonic sweep could be resampling noise rather than
a property of the metric.

Three properties, all holding, all now guarded by `TestMetricDiscrimination`:

| property | meaning | why it matters |
|---|---|---|
| **Monotone** | ICS never rises as `p` rises | a reversal would mean more comprehension scoring worse |
| **Anchored** | `p=1` → exactly 0; `p=0` loses to silence | the scale means what it claims at both ends |
| **Responsive** | every step moves ICS > 2% of the range | rules out a metric that is flat through the middle while looking fine at the ends |

**The number this produced:** a system needs roughly **30% comprehension to beat
silence**. A policy at `p = 0.2` reaches 0.556 precision — which reads as
better-than-a-coin-flip — and is still a net loss against saying nothing.

`PartialSkylinePolicy` is a diagnostic, not a baseline, and is deliberately absent
from the leaderboard registry. Full sweep:
[`experiments/discrimination_sweep.py`](../experiments/discrimination_sweep.py).

## The shortcut audit

`tactbench audit` trains a bag-of-words classifier on **signal text alone** — no
user state, no DND flag, no slice tags — and reports how well it separates speak
from stay-quiet. Chance is 50%.

This is not a diagnostic; it gates the build. `test_lexical_leakage_stays_near_chance`
fails if the overall figure drifts above 70%, and **every** family must stay under
60% — there are no exemptions.

**Both bounds are on distance from chance, not on accuracy.** `LeakageReport`
exposes `leakage` (`|accuracy − 0.5|`) and `exploitable_accuracy`
(`0.5 + leakage`); the thresholds apply to the latter. A probe that is reliably
*wrong* is worth exactly as much to a submitter as one that is reliably right,
because negating a classifier is free.

Round 10: the assertions were upper bounds on raw accuracy, so `meeting_prep`
probing at **32.8%** passed with room to spare and printed as `at chance`. It was
not at chance — it was a 67.2% classifier with a minus sign, above the very bar
the audit claimed to enforce. The anti-correlation came from the dev/test split
breaking pairs apart (see [DATASET.md](DATASET.md#splitting)); a one-sided check
is structurally unable to see the kind of leak a pairing design produces.

**A caveat worth stating plainly.** With pairs whole and deciders written as true
role permutations, every family now probes at *exactly* 50.0% — and it must, since
bag-of-words cannot see word order and a permutation is only a reordering. So this
audit no longer discriminates among well-formed permutations; it catches deciders
that are **not** permutations (a one-sided token, as `quiet_hours` once had). That
is still worth gating on, but "50.0% everywhere" should not be read as stronger
evidence than it is. An order-sensitive probe is the natural next check.

The audit exists because the claim it measures was once false. v1 asserted that
matched pairs prevented keyword matching; the probe hit **93.5%**.

The exemption granted to `quiet_hours` was a second, subtler version of the same
error. It probed at 100% and was excused as irreducible. Because that family also
carries the highest false-positive cost — driving 82% of the `always`-vs-silence
gap from 13% of moments — a policy matching two substrings and coin-flipping
elsewhere beat silence while the honest heuristic did not. `TestNoKeywordExploit`
now fails the build if any keyword policy clears the bar. Full history in
[DATASET.md](DATASET.md).

## Per-family reporting, and why there is no single "comprehension" number

Round 7's sweep produces a smooth ICS curve against comprehension, which invites
an appealing shortcut: score a system, look its ICS up on the curve, report *"this
model understands about 40% of these moments."*

**That number is not real.** The curve was built from uniformly random errors;
real systems fail systematically. Three policies understanding the same share of
moments — true fractions within 0.033 of each other — land at implied fractions
spanning **0.36**, purely from *which* families they understand:

| comprehends | true fraction | ICS | implied p |
|---|---|---|---|
| cheap families (`commerce`, `health`, `meeting_prep`) | 0.350 | 382.0 | 0.163 |
| mixed (`travel`, `deadline`, `finance`) | 0.333 | 319.0 | 0.333 |
| costly (`quiet_hours`, `driving`, `childcare`) | 0.317 | 192.0 | 0.527 |

The metric is not wrong here — ICS weights by consequence, and a system that
handles `quiet_hours` correctly genuinely *is* better than one that only handles
`commerce`. What is wrong is the **label**: a single figure conflates *how much* a
system understands with *which parts*, so reporting it as a comprehension fraction
would mislead about exactly the systems it would be used on.

The honest unit is the per-family breakdown:

```bash
tactbench eval --by-family
```

`Scorecard.by_family` carries mean cost per scenario family. Read it alongside ICS:
two policies can sit adjacent on the headline and fail in completely different
places, and for a proactive assistant *where* it fails is as load-bearing as how
often. Evidence:
[`experiments/implied_comprehension_probe.py`](../experiments/implied_comprehension_probe.py).

## Slice reporting

Mean cost per moment is also reported per slice tag, so you can ask *which kind* of
judgment a system lacks rather than only *how much*. A system that scores well
overall but poorly on `near_miss` is pattern-matching surface features; one that
fails `dnd_override` doesn't understand that stated preferences have exceptions.

## What is deliberately not measured

- **Cue wording quality.** Out of scope; that is a generation problem with
  established evaluation methods.
- **Latency as a cost.** Measured and reported, but not priced into ICS — it is an
  engineering property, not a judgment property.
- **Cumulative fatigue.** Real interruption cost rises with recent interruption
  frequency. Modeling that requires session-level items rather than independent
  moments, and is left to a future version.
