# TactBench

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

Built-in baselines on `v1/dev` (171 moments):

| policy | ICS ↓ | vs silence | prec@int ↑ | recall-hv ↑ | ECE ↓ | hard viol. ↓ | spoke |
|---|---|---|---|---|---|---|---|
| `heuristic` | **55.0** | **+75.4** | 0.818 | 0.847 | 0.139 | 0 | 88/171 |
| `never` | 224.0 | 0.0 | — | 0.000 | 0.497 | 0 | 0/171 |
| `random@0.5` | 469.0 | −109.4 | 0.515 | 0.588 | 0.020 | 19 | 97/171 |
| `always` | 595.0 | −165.6 | 0.497 | 1.000 | 0.503 | 29 | 171/171 |

Read the `always` row carefully. It has **perfect recall** — it never misses a
single cue worth surfacing — and it is the worst policy on the board by a wide
margin, scoring 165 points *below saying nothing at all*. That gap is the entire
argument for this benchmark. Optimize for helpfulness and you land on that row.

`never` is the bar. **A proactive feature that scores worse than silence is a
feature that should not ship.**

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

## The dataset

Every moment is a frozen context slice — signals from screen, calendar, messages,
email, location, app events, sensors — plus a user-state snapshot (activity, DND,
local hour, time since last interaction).

**Moments are generated in matched pairs.** This is the central design decision.
A benchmark of "should you speak?" is trivially gameable if the items warranting
speech look different on the surface from the ones that don't — any policy could
match keywords like *delayed*, *expires*, *overdue* and score well without having
judged anything. So each scenario emits a positive **and** a near-miss sharing the
same sources, the same vocabulary, and the same family, differing only in the fact
that actually settles it:

> **Positive** — gate changed to B31, boarding in 35 minutes, user is reading news,
> 8 minute walk away. → **Speak.**
>
> **Near-miss** — same gate change, same 35 minutes, but the user is already seated
> at B31 with the updated boarding pass on screen. → **Say nothing.**

Six scenario families: `travel`, `deadline`, `commerce`, `quiet_hours`, `driving`,
`meeting_prep`. Slice tags (`near_miss`, `already_handled`, `not_yours`,
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
uv run tactbench failures heuristic   # inspect the costliest mistakes
uv run tactbench serve                # local viewer at :8000
```

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
- **Moments are synthetic and template-generated.** Phrasing diversity is low
  enough that a sufficiently determined string matcher could still overfit,
  despite the paired design. Paraphrase variation is the first planned expansion.
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

1. LLM baselines across providers, zero-shot and with an explicit cost rubric.
2. Human-labeled subset with reported agreement.
3. Paraphrase and distractor expansion.
4. Held-out test split with hidden labels behind a submission script.

## License

MIT for the code, CC BY 4.0 for the dataset.
