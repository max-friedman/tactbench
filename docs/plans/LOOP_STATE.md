# Loop state

The spine for the continuous-improvement loop. **Read this first, write it last.**
Context is lost between rounds; this file is not.

Method: [agentic-coding-loop](https://github.com/max-friedman/agentic-coding-loop)
([LOOP.md](https://github.com/max-friedman/agentic-coding-loop/blob/main/LOOP.md) ·
[principles](https://github.com/max-friedman/agentic-coding-loop/blob/main/docs/PRINCIPLES.md)).
Findings about the *method* go upstream **as issues, not PRs** — see **Method
findings** below.

---

## Current status

- **Round:** 9 complete
- **Gate:** green — 73 tests, ruff clean, **enforced by CI** on py3.11-3.13
- **Dataset:** `v1` — 360 items (266 dev / 94 test), 9 families × 20 pairs
- **Headline:** silence (ICS 354) is unbeaten by any baseline; skyline (ICS 0)
  proves the bar is clearable

---

## Round 1 — shortcut resistance

**Question:** does the matched-pair design actually prevent surface pattern
matching, or is that just a claim in the README?

**Method:** built `audit.py` — a dependency-free bag-of-words probe over signal
text only (no user state, no DND, no slice tags), cross-validated with pairs kept
whole across folds so neither half can leak into training.

**Finding: the claim was false.** The probe hit **93.5%** against a 50% floor.
Each scenario had one fixed phrasing per side, so tokens appearing on exactly one
side (`hallway`, `inflight`, `closes`) gave the answer away.

**Fix:** rebuilt pair construction around *role permutation* — both sides share a
byte-identical body and identical user state; one decider signal differs by
swapping which noun plays which role. Overall probe **93.5% → 57.5%**, with five
of six families at the chance floor.

**Consequences, all verified:**

| effect | detail |
|---|---|
| Heuristic collapsed | precision 0.818 → 0.560 (chance). Its old score was leakage, not skill. |
| Nothing beats silence | every baseline now scores below `never`. |
| Skyline added | proves the task is solvable (ICS 0, +100) and the benchmark isn't degenerate. |
| Label bug caught | `travel` variant 0 had **inverted labels** — the "positive" described a user already at the new gate. |

**Shipped:** `audit.py`, `policies/skyline.py`, rebuilt `dataset/generate.py`,
`tactbench audit` CLI, 5 new invariant tests, README + DATASET.md corrected.

---

## Round 2 — the decisive experiment, built but unrun

**Goal:** with every shortcut gone and no baseline clearing silence, "can a frontier
model beat saying nothing?" is the question the repo exists to answer. It is blocked
on a credential. Build everything around the block.

**Shipped:** `policies/llm.py` — provider-agnostic (Anthropic / Gemini / OpenAI),
one moment per call (no batching, which would leak the 50/50 balance and let the
model compare moments a real assistant can't), prompt kept verbatim in source and
versioned, unparseable output scored as silence. `tactbench llm` CLI with per-run
caching so a paid run is never repeated. 23 new tests, none needing a key.

**Two variants, by design:** `naive` withholds the cost structure; `rubric`
discloses it. The gap between them distinguishes *wrong disposition* (capability
present, helpfulness bias dominating) from *missing judgment*.

**Prompt-leak guard.** `render_moment` deliberately omits `family`, `slices`, and
`moment.id`. `slices` literally contains `near_miss`; shipping it would hand over
the label and silently invalidate every result. Four tests enforce this. Two of
them initially failed on legitimate collisions — the activity value `driving` and
the contact class `family` both belong in the prompt — so the assertions were
narrowed to the labelled-field form rather than the code being changed.

**Not done, deliberately:** no numbers. Nothing about LLM performance appears in
the README, and nothing may until a run actually happens.

---

## Round 3 — more degrees of freedom

**Goal:** after R1, the top weakness was that six families is six effective degrees
of freedom regardless of item count. Phrasing was no longer the weak point; scenario
count was.

**Shipped:** three new families, each built as a role permutation from the start
rather than retrofitted — `health` (whose prescription is still at the counter),
`childcare` (which parent is listed for pickup vs. travelling), `finance` (which
account autopay actually draws from). Dataset 240 -> 360 items.

**Caught by the audit before landing:** `health` probed at 82.5% on first pass. The
decider ended `your prescription` on one side and `yours` on the other -- different
tokens, so the probe latched on. Repeating the noun on both sides made it a true
permutation and it dropped to 50.0%. This is exactly the check working as intended:
the leak was invisible by eye and obvious to the probe.

**Result:** 8 of 9 families now sit at exactly 0.500. Overall 57.5% -> 55.6% (adding
clean families dilutes quiet_hours' share). Skyline still resolves all 9 families
with zero disagreements, so the new labels are self-consistent.

---

## Round 4 — the base rate

**Goal:** the balanced 50/50 split makes the near-miss contrast legible but is not
what production looks like. Every number in the repo was implicitly claiming a 1:1
prior, which no deployed assistant has ever seen.

**Shipped:** `--base-rate` on `score`, `silence_ics`, `evaluate` and `tactbench
eval`. Every stay-quiet item is importance-weighted by the quiet:loud ratio, so it
stands in for the real moments it represents. Precision is weighted too and now
reports the production figure. 7 new tests.

**Result — the most decision-relevant number in the repo:** at 100:1, precision
collapses from 0.514 to **0.010**. Ninety-nine of every hundred interruptions would
be unwanted. Silence and skyline are the only rows that don't move, because neither
produces a false positive; everything else inflates around them.

**Design calls:** hard violations are *not* reweighted — they count distinct
moments in the benchmark, not estimated production volume, and conflating those
would make the number meaningless. `base_rate < 1` raises rather than silently
inverting the intent.

**Noted, not built:** "skyline as a fraction" turned out to be redundant.
`ics_normalized` already maps silence to 0 and zero cost to 100, and skyline scores
exactly 0, so the existing column *is* percent-of-achievable. Adding a second one
would have been duplicate reporting. Revisit only if skyline stops being perfect.

---

## Round 5 — engineering hygiene

**Goal:** the repo kept claiming a green gate that only existed on one laptop, and
five rounds had gone straight to `main` with no branch or review.

**Gaps found (one self-inflicted):**

| gap | fix |
|---|---|
| No CI at all | `.github/workflows/ci.yml` — py3.11/3.12/3.13, pytest + ruff check + ruff format |
| `data/` could drift from the generator unnoticed | `dataset-is-reproducible` job regenerates and diffs; published results stay traceable |
| Audit numbers invisible outside the test suite | `shortcut-audit` job surfaces per-family leakage in the run log |
| **`docs/METRICS.md` never learned about base rate** | R4 updated README + DATASET.md and missed the canonical metrics reference. Now covers base rate, skyline, and the audit |
| README claimed CC BY 4.0 with no such file | `LICENSE-DATA` |
| No contributor guidance | `CONTRIBUTING.md` leading with the permutation rule |
| Everything committed to `main` | Branch + PR #1; formatting isolated in its own behavior-free commit |

**Also:** `CHANGELOG.md`, PR template (checklist covers the audit and the
no-unproduced-numbers rule), README badges.

**Standing practice from here:** branch off `main`, open a PR, formatting-only
changes get their own commit, and the README results table is re-run and updated
whenever costs, the generator, or a policy change.

---

## Coverage map

| area | last touched | probe / status |
|---|---|---|
| `dataset/generate.py` | R3 | 8/9 families at chance floor |
| `metrics.py` | R4 | base-rate weighting; ICS constants still unvalidated by humans |
| `policies/builtin.py` | R1 | heuristic now near chance, as intended |
| `policies/skyline.py` | R3 | handles all 9 families; ICS 0 |
| `audit.py` | R1 | gates the build; also its own CI job |
| `.github/workflows/` | R5 | CI on py3.11-3.13 + reproducibility + audit |
| `web/server.py` | R1 | re-verified against the rebuilt dataset; 5 policy columns |
| `policies/llm.py` | R2 | built and tested; **never executed** — needs a key |

---

## NEEDS-MAX

Items that cannot proceed without a human. **Noted and skipped — never a reason to
halt the loop.**

1. **Run the LLM baselines.** The harness is built, tested, and cached (R2). It has
   never been executed because no `ANTHROPIC_API_KEY` / `GEMINI_API_KEY` /
   `OPENAI_API_KEY` is present and there is no local Ollama. One command unblocks
   the headline result:

   ```
   export ANTHROPIC_API_KEY=...
   uv run tactbench llm --variant rubric --limit 20   # smoke-test the spend first
   uv run tactbench llm --variant naive
   uv run tactbench llm --variant rubric
   ```

   **No numbers may be published without actually running it.**
2. **Human label validation.** Labels remain by construction (`raters: 0`). Needs
   real raters and a reported κ.
3. **PyPI release** — deliberately held until (1) lands, so the first release ships
   with the finding that makes it worth installing.

---

## Queue — next rounds

1. **Fatigue as decisive context** (re-specified in R6; the cost-multiplier form
   was measured and rejected — see `experiments/fatigue_multiplier_probe.py`).
   Needs a ruling first: may a pair's two sides differ in `UserState` when the
   state difference *is* the judgment under test? The invariant currently
   forbids it. Refine with a named exception, as `quiet_hours` is named in the
   audit — or reject and drop fatigue entirely. **Do not weaken it silently.**
2. **More families still welcome** — nine is better than six but still one
   author's idea of a working life. Candidates: home security, commute
   disruption, pet care.
3. **Type checking** — no mypy/pyright configured; worth adding to CI once the
   schema surface settles.
4. **Human label validation** (also NEEDS-MAX) — a labelling CLI is buildable now
   even if the raters are not.

---

## Round 6 — fatigue, measured and rejected

**Question:** the queue's top item proposed scaling false-positive cost by how
recently the user was last interrupted. Framed falsifiably: *does fatigue add a
judgment this benchmark doesn't already test, or is it a rescale?*

**Check built before the thing** (`experiments/fatigue_multiplier_probe.py`) —
assigns each moment a deterministic fatigue level, rescales false-positive cost,
and compares leaderboard ordering. No feature code required to answer it.

**Finding — rejected.** The ordering is byte-identical at k=0, k=0.5 and k=2.0:

```
skyline < never < heuristic < random@0.5 < always
```

The reason is structural, not a quirk of these numbers. The multiplier only ever
*increases* false-positive cost and applies identically regardless of which
policy produced the error, so the transform is monotone in "how many false
positives, weighted per-moment" — already what the ordering is determined by.
Spreading scores apart is not new information. It would have cost a schema
change, a scoring parameter, and docs, to change no decision any policy makes.

**Shipped:** the probe, kept in-repo so the rejection carries its evidence and a
future round re-runs it instead of re-arguing it. No production code changed.

**Re-specified, not abandoned.** Fatigue is only interesting when it is
*observable context that changes the correct answer* — a real assistant knows how
often it just spoke, and the bar genuinely should rise. Two conditions make that
a real test rather than a one-line rule:

1. Fatigue must decide the label for **low-value cues only**; a family emergency
   at high fatigue still gets through. Otherwise `fatigue >= 3 → stay quiet`
   solves it outright and no judgment is exercised.
2. Fatigue varies across *all* families, so a policy applying a global threshold
   breaks the high-value ones. That is what makes it compositional: the policy
   must judge cue value **and** read fatigue.

**Blocked on an invariant decision, deliberately not made unilaterally.**
Condition 1 requires a pair whose two sides differ in `UserState` — which the
standing invariant forbids. That invariant exists to stop state being a
*shortcut*; here state would be the *substance*. That may be a refinement rather
than a weakening, but principle 4 says invariants are not weakened to let a round
land, so it goes to review rather than into this branch. See the queue.

---

## Round 7 — does the metric discriminate?

**Question:** six rounds of leaderboards show every real policy at 0.484-0.560
precision and the skyline at 1.000, with nothing measured between. ICS has been
shown to separate *no* comprehension from *perfect* comprehension. **It has never
been shown to rank the middle** — which is where every real system lands. A metric
flat across that range would be broken for exactly the systems the benchmark
exists to score, and no dataset work would fix it.

**Check built first:** `PartialSkylinePolicy(p)` resolves a deterministic fraction
`p` of moments and coin-flips on the rest, interpolating between `random@0.5` and
the skyline. The comprehending set is hash-chosen, therefore **nested** — raising
`p` only adds moments, so a non-monotonic result can't be resampling noise.

**Finding — the metric is sound, and it produced a new number.**

| p | ICS | vs silence | prec@int |
|---|---|---|---|
| 0.0 | 507.0 | −43.2 | 0.484 |
| 0.2 | 463.0 | −30.8 | 0.556 |
| 0.4 | 245.0 | +30.8 | 0.705 |
| 0.6 | 178.0 | +49.7 | 0.836 |
| 0.8 | 105.0 | +70.3 | 0.880 |
| 1.0 | 0.0 | +100.0 | 1.000 |

Monotone, anchored at both ends, smallest step 2.8% of range. **A system needs
roughly 30% comprehension before it beats silence at all** — and `p=0.2` reaches
0.556 precision, which reads as better-than-chance and is still a net loss.

**Shipped:** `PartialSkylinePolicy` (diagnostic, deliberately not in the
leaderboard registry), five invariant tests in `TestMetricDiscrimination`, the
sweep script, plus README and METRICS.md sections.

**A bug in my own probe, worth recording:** the first run crashed on
`zip(..., strict=True)` over an intentionally offset pairwise comparison. The
check was wrong, not the metric — the data underneath was already clean. Cheap
reminder that a failing check is a hypothesis about the code *and* about itself.

---

## Round 8 — implied comprehension, refuted

**Question:** R7's sweep maps ICS to a comprehension fraction. The queue proposed
applying it to the pending LLM run so a score reads as "this model comprehends
~p of these moments." Before building it: *does implied-p survive structured
errors, or does it mis-read exactly the systems it would interpret?*

The curve was built from **uniformly random** errors. Real models fail
systematically, and this dataset prices that heavily — a false positive costs
10.0 in `quiet_hours` (asleep, DND-doubled) and 1.0 in `commerce`.

**Check built first:** `FamilyPartialSkyline` comprehends whole families and
guesses elsewhere, holding the fraction of moments comprehended roughly fixed
while varying *which* moments those are.

**Finding — refuted.**

| comprehends | true fraction | ICS | implied p |
|---|---|---|---|
| cheap (`commerce`/`health`/`meeting_prep`) | 0.323 | 466.0 | 0.198 |
| mixed (`travel`/`deadline`/`finance`) | 0.338 | 367.0 | 0.303 |
| costly (`quiet_hours`/`driving`/`childcare`) | 0.338 | 199.0 | 0.495 |

True fraction varies by 0.015; implied p varies by **0.298** — twenty times the
true variation. Implied-p is not a real quantity.

**The metric is not at fault.** ICS weights by consequence, and a system handling
the expensive families really is better. The *label* was wrong: one number
conflates how much a system understands with which parts.

**Shipped the honest replacement:** `Scorecard.by_family` and
`tactbench eval --by-family`. Two policies can sit adjacent on the headline and
fail in completely different places — and for a proactive assistant, *where* it
fails is as load-bearing as how often. Four tests, plus METRICS.md.

**Consequence for the blocked LLM run:** report per-family costs, never a single
implied comprehension figure. Recorded so a future round doesn't re-propose it.

---

## Round 9 — the exemption we granted ourselves

**Question:** R8's breakdown showed `always` costing 9.71/moment in `quiet_hours`
against 0.42 in `commerce`; R1's audit showed `quiet_hours` is the only family not
at the chance floor. Together: *is the headline dominated by one family — and is
it the one a keyword matcher can already solve?*

**Measured, both parts yes.** `quiet_hours` is 13% of moments and drives **82% of
the gap** between `always` and silence. And the exploit was live: a policy matching
two substrings (`admitt` / `discharg`) and coin-flipping on the other eight
families scored **+28.0 vs silence** — while the honest structural heuristic
scored **−22.9**. Two tokens in one family beat reasoning across all nine.

**Root cause: the exemption from R1, not the family.** "Severity is irreducibly
lexical" was wrong. The decider was on the wrong *axis*. The admission now sits in
the **shared body**, identical on both sides, and the judgment is whether the user
can act:

> *"Right now I am 6 hours out; you are the one nearby."* → speak
> *"Right now you are 6 hours out; I am the one nearby."* → stay quiet

**Results:**

| | before | after |
|---|---|---|
| `quiet_hours` probe | 100.0% | **54.3%** |
| overall probe | 55.6% | **48.1%** |
| two-keyword exploit vs silence | **+28.0** | **−85.0** |
| exempt families | 1 | **0** |
| heuristic vs silence | −22.9 | −39.3 |

The heuristic got *worse*, which is the leak removal working — its severity
lexicon no longer buys anything.

**Concentration itself was left alone.** `quiet_hours` still drives 82% of the
gap, and that is correct: a false positive while asleep under DND is the most
expensive error the cost model prices. Concentration is fine; concentration in an
*exploitable* family was the bug.

**Two bugs found in my own R7 code while re-verifying:**

1. `PartialSkylinePolicy` drew guesses from a sequential RNG, so *which* moments
   consumed randomness depended on `p` — raising `p` reshuffled every remaining
   guess instead of only converting guesses to correct answers. R7's monotonicity
   held **by luck**; it reversed on the new dataset (p=0.4 → 112.0, p=0.6 → 120.0).
   Guesses are now hashed per moment, making monotonicity *structural*.
2. `digest[2] / 255.0 < p` excluded a moment whose byte was exactly 255, so p=1.0
   did not reproduce the skyline. Passed on small samples, failed on the full
   split. Now `/ 256.0`.

**Shipped:** rebuilt `quiet_hours`, skyline handler, `TestNoKeywordExploit` (4
keyword sets), the per-family audit assertion extended to **all nine** families,
the concentration probe, and corrections across README, DATASET.md, METRICS.md,
CONTRIBUTING.md and CLAUDE.md — five documents asserted the exemption.

---

## Method findings — send upstream

Durable lessons about running an agentic loop, as opposed to lessons about
proactive assistance. These belong in
[agentic-coding-loop](https://github.com/max-friedman/agentic-coding-loop), not
here. File them with the upstream **Loop proposal** issue form (or the `loop-feedback`
skill) — *not* as a pull request; proposals are inert until a maintainer writes
the change. **Check `LOOP.md` first**: three of the five below turned out to be
already covered or out of scope, and filing them would have wasted triage.

| finding | evidence from this project | disposition |
|---|---|---|
| The gate needs a home outside one machine | R5 added CI and it failed on its first run — dev tooling was an extras group `uv run` never installs, so the suite had been green on exactly one laptop for five rounds. | filed — [issue #2](https://github.com/max-friedman/agentic-coding-loop/issues/2) |
| The branch rule fires too late for attended rounds | R1–R4 went straight to `main`. The rule exists but is scoped to §D unattended runs, and even there fires after the work is already committed. | filed — [issue #3](https://github.com/max-friedman/agentic-coding-loop/issues/3) |
| Never publish a number the round didn't produce | The LLM harness has been built and unrun since R2; no figure appears anywhere. | **not filed** — already a `LOOP.md` hard rule verbatim, plus principle 5. Fully covered. |
| Mechanical churn gets its own behavior-free commit | R5 reformatted 9 files; isolating it kept the diff reviewable and `git blame` honest. | **not filed** — generic git hygiene, not a loop concern. A 300-line protocol shouldn't absorb it. |
| Docs drift — search for the concept, don't recall the filenames | R4 shipped base-rate scoring and missed `METRICS.md` entirely. | **not filed** — §5.4 covers documents *quoting a number you changed*; this was a **missing section**, so §5.4 wouldn't have caught it. Real but narrow; offered upstream, not filed, to avoid spending a triage slot on day one of the process. |

---

## Standing invariants

Encoded as tests. Do not weaken them to make a round pass — if one fails, the
dataset or the policy is wrong, not the assertion.

- Overall lexical probe stays **< 70%**; every permutable family (all but
  `quiet_hours`) **< 60%**. A new family must be added to the audit, not exempted.
- Skyline beats silence with **zero** hard violations (task stays solvable).
- Skyline never disagrees with a gold label (labels stay self-consistent).
- The heuristic stays near chance (**0.5 ± 0.15** precision) and never solves the set.
- Both sides of every pair carry an identical `UserState`.
- Heuristic lexicons stay single words, ≤ 20 entries — no phrase-lifting.
- Silence and skyline stay invariant to `base_rate` (neither can false-positive).
- Hard violations are never reweighted by `base_rate`.

- A round may reject its own queue item. The evidence stays in `experiments/`.
- **No single-number "comprehension" score.** Refuted in R8: ICS weights by
  consequence, so one figure conflates how much a system understands with which
  parts. Report `--by-family` instead.
- **No exempt families.** Every family probes under 60%. R9 showed an exemption is
  not free: the exempted family was also the highest-cost one, which made it
  exploitable by two keywords.
- **No keyword policy may beat silence** (`TestNoKeywordExploit`).
- ICS stays monotone, anchored, and responsive in comprehension — the metric must
  rank the middle, not only separate the ends.
