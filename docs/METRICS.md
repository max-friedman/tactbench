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
