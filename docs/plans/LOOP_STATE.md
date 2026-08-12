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

- **Round:** 13 complete
- **Gate:** green — **90 passed, no xfails**; the two strict xfails that recorded
  the surface-exploit defect were flipped to real assertions in R13. Ruff clean,
  **enforced by CI** on py3.11-3.13
- **Dataset:** `v1` — 360 items (**252 dev / 108 test**), 9 families × 20 pairs,
  8 decider frames per family, split **on the frame** (0-4 train, 5-7 held out) so
  held-out phrasings appear nowhere in training and no pair is divided
- **Headline:** silence (ICS 336) is unbeaten by any baseline; skyline (ICS 0)
  proves the bar is clearable. **The surface-model exploit is closed** — a
  bag-of-bigrams fit on `dev` now scores **−59.0** vs silence on held-out `test`,
  down from +99.4 (R11). The leaderboard caveat that stood for two rounds is gone.

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
| `audit.py` | **R11** | unigram + bigram probes; `verbatim_overlap`; worst-probe verdict |
| `cli.py` split | **R10** | buckets on `pair_key`; `TestSplitIntegrity` guards it |
| `schema.pair_key` | **R10** | the single definition of a pair |
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

1. **Restore prose deciders without losing the held-out guarantee (new, R13).**
   R13 bought validity with uniformity: every decider is now
   `Label: value. Label: value.`, which reads like a status line rather than
   something a person or an app would send. A benchmark about proactive assistance
   whose items do not look like real messages is measuring something adjacent to
   the thing. Needs prose frames that are still exact token permutations (English
   agreement is the trap -- "you are" vs "Dana is" breaks the multiset), with the
   audit and `test_the_two_sides_are_equal_but_not_the_same_objects` as the gate.
2. **Fatigue as decisive context** (re-specified in R6; the cost-multiplier form
   was measured and rejected — see `experiments/fatigue_multiplier_probe.py`).
   Needs a ruling first: may a pair's two sides differ in `UserState` when the
   state difference *is* the judgment under test? The invariant currently
   forbids it. Refine with a named exception, as `quiet_hours` is named in the
   audit — or reject and drop fatigue entirely. **Do not weaken it silently.**
3. **An order-sensitive shortcut probe (R10) — DONE in R11.** Kept here only as a
   pointer: the answer was that the audit had a structural blind spot.
   Superseded by item 1.
   <details><summary>original entry</summary> Every
   family now probes at exactly 50.0%, which is bag-of-words being structurally
   blind to word order rather than evidence of safety: a role permutation is a
   reordering, so the current probe *cannot* separate a well-formed pair. Add a
   bigram/positional probe. If it also lands at chance, the permutation claim is
   genuinely evidenced; if it separates families, the deciders leak in a way
   nine rounds of auditing could not see. Either result is worth the round.
   </details>
4. **More families still welcome** — nine is better than six but still one
   author's idea of a working life. Candidates: home security, commute
   disruption, pet care.
5. **Type checking** — no mypy/pyright configured; worth adding to CI once the
   schema surface settles.
6. **Human label validation** (also NEEDS-MAX) — a labelling CLI is buildable now
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

## Round 10 — the held-out split was published

**Question, arrived at sideways.** `tactbench audit` reported every family "at
chance", but `meeting_prep` sat at **32.8%** — far *below* it. Both audit
assertions were upper bounds (`< 0.70` overall, `< 0.60` per family), so that
passed with room to spare. A probe wrong 67.2% of the time is not ignorant;
negating it scores 67.2%, above the bar the audit claimed to enforce. **Is
sub-chance accuracy a real leak the one-sided audit cannot see?**

**It was a symptom. The disease was worse.** `cli.build` bucketed the split on
`moment.id`, which names an *item*. A pair's two sides were assigned
independently, so they landed on opposite sides of the split.

| | v1 as shipped for nine rounds |
|---|---|
| pairs divided across dev and test | **72 of 180** |
| held-out items whose partner was published in dev | **72 of 94 (77%)** |
| of those, answered by negating the partner's label | **72 of 72** |
| test-split accuracy by table lookup, no model | **88.3%** |

Both sides of a pair share a byte-identical body, so an orphaned test item is a
near-verbatim copy of a dev item **carrying the opposite label**. `moment.id` is
public, so the pair key is public, so the partner is findable. The held-out split
was not held out — 88.3% of it was answerable with a dictionary and no learning.

**The shape of the bug is the lesson.** `audit.lexical_leakage` had always kept
pairs whole across its own folds, with a comment explaining that splitting one
"would let the probe memorize one half and trivially answer the other." The
artifact it was auditing did not. **The invariant was enforced in the checker and
violated in the thing being checked**, because each had its own private notion of
a pair. `schema.pair_key` is now the single definition.

**Shipped:** the pair-key split; `schema.pair_key`; two-sided leakage
(`leakage`, `exploitable_accuracy`, `is_leaking`, and thresholds defined once);
`TestSplitIntegrity` (5 tests); a pair-independence test; the two probes; every
published number re-run.

**Results:** partner lookup **88.3% → 50.0%**; zero orphaned items; every family
back to exactly **50.0%** — the sub-chance families were *entirely* an artifact of
the split. Qualitatively nothing moved: silence still unbeaten, skyline still
+100, every baseline still loses.

**A second bug, found by a failing test of my own.** The two sides of a pair
shared the *same* mutable `Signal` objects. A test that appended a per-label tell
to every item produced a dataset where both sides carried both tells. Nothing in
the shipped code mutates an item, so it had never bitten — but paraphrase
expansion (priority 3) is exactly an in-place rewrite. Fixed with per-side deep
copies.

**Review caught three recurrences of this round's own defect.** A fresh-context
reviewer found the two-sided threshold *still* one-sided in `tactbench audit`
(the command contributors are told to run) while METRICS.md claimed otherwise;
two tests weaker than their docstrings, one silently vacuous behind
`if len(pair) == 2`; and no assertion that the shipped `data/v1` is what
`tactbench build` writes — the same checker-vs-artifact gap, one level up. All
fixed. **The maker could not see the pattern in its own work even immediately
after naming it.**

**Recorded honestly — the audit is now weaker than it looks.** With pairs whole
and deciders written as true role permutations, every family probes at *exactly*
50.0%, and it must: bag-of-words cannot see word order, and a permutation is only
a reordering. The audit still catches deciders that are **not** permutations, but
"50.0% everywhere" is close to a tautology given the construction. An
order-sensitive probe is the next check, not a stronger claim.

---

## Round 11 — the pairing defeats vocabulary, not word order

**Question, straight off R10's queue:** every family probed at exactly 50.0%.
Is that evidence, or is it a tautology — bag-of-words cannot see word order, and
a role permutation is *only* a reordering?

**A tautology.**

| probe | overall | families ≥ 60% |
|---|---|---|
| unigram (reported for ten rounds) | 50.0% | 0 of 9 |
| **bigram** | **97.2%** | **9 of 9** |

Fit on `dev`, graded on held-out `test`: bag-of-bigrams reaches **ICS 1.0, +99.4
vs silence, 0.983 precision** — one point off the skyline.

**Review corrected the mechanism, and the correction is the better finding.**
My first draft said "one decider template per family" and called the result
generalisation to unseen pairs. Both were wrong. Each family has *two* decider
variants, and the dominant effect is not learning at all:

| | |
|---|---|
| held-out deciders published byte-identically in `dev` | **91.2%** |
| held-out items whose entire signal text is in `dev` | **49.1%** |
| **dict lookup on the decider string, no model** | **95.6%, +90.9 vs silence** |
| distinct decider sentences per family (40 items each) | as few as **4** |

So a zero-model lookup already gets +90.9 and the bigram adds the rest. This is a
**near-duplicate leak** — a *different* defect from R10's pair-key split. That one
divided pairs across the boundary; this one repeats text across it. **A split can
be perfectly pair-whole and still publish its own answers**, and R10's fix said
nothing about that.

**Shipped:** `item_bigrams`, `ngram_leakage`, `verbatim_overlap`; a bigram column
in `tactbench audit`, which now prints the verdict of whichever probe is **worse**;
`experiments/order_sensitive_probe.py`; a test pinning that pair sides are an exact
token-multiset permutation, so the 50.0% is never misread again.

**NOT shipped: a weaker threshold.** The rule that no surface policy may beat
silence is violated and stays visibly violated — two `strict=True` xfails
(verbatim overlap, ICS exploit) fail the build the moment the dataset is repaired,
forcing the assertions to be tightened rather than forgotten.

**Scope of the standing audit invariant, recorded explicitly** because it is now
*deliberately* not enforced end-to-end: the `< 70%` / `< 60%` bounds are gated on
the **unigram** probe only. The bigram probe is reported, and `tactbench audit`
prints LEAKING for all nine families, but does **not** fail CI — because gating it
would put the build red with no available fix. That is a knowing trade, not an
oversight, and it reverses when paraphrase expansion lands.

**Method note.** Review caught the maker overstating its own finding in the
direction that made the round look better, and missing five files that still
asserted the falsified claim — including `audit.py`'s own module docstring and a
`CONTRIBUTING.md` step contributors could no longer follow. Second round running
that the checker found the maker repeating the exact pattern the round was about.

---

## Round 12 — entity variation was the wrong lever

**Decision recorded (taken without Max, per his instruction to decide and note).**
R11 left three candidate fixes. Chose the **phased** one — R12 does entity
variation across all nine families (cheap, no skyline changes), R13 does held-out
phrasings plus the skyline rework — because the loop's own rule is shippable
independent increments, and authoring ~72 template pairs plus nine generalised
skyline handlers in one round is where subtle leaks get introduced (R3 shipped a
template that probed at 82.5% and nearly landed).

**Question:** R11 attributed the exploit to decider scarcity — as few as **4
distinct decider sentences across a family's 40 items**. *If the scarcity is
removed, does the exploit go with it?*

**Built:** entity pools (`COLLEAGUES`, `HOUSEHOLD`, `PHARMACY_OTHERS`,
`RETURNABLES`, `MEETING_SUBJECTS`), drawn per pair. Both sides of a pair still take
the **same** entity — the permutation is which role it plays — so varying it cannot
leak. Numeric pools widened. `commerce` and `meeting_prep` vary only the
*counterpart*, leaving the noun the skyline resolves against intact, which avoided
touching the skyline at all.

**Result: the diagnosis was half right, and the fix does not work.**

| measure | before | after |
|---|---|---|
| distinct decider sentences per family | **4**–32 | **24–38** |
| held-out deciders published verbatim in `dev` | 91.2% | **29.8%** |
| held-out items wholly duplicate | 49.1% | **7.0%** |
| dict-lookup accuracy (no model) | 95.6% | **64.9%** |
| bigram probe | 97.2% | 93.5% |
| **bigram exploit vs silence** | **+99.4** | **+98.1** |

Duplication fell by two thirds. The exploit moved **1.3 points**. The reason is
structural and should have been predictable: the **frame** carries the label
(`pickup_you` → speak, `primary_you` → speak), and varying who stands in the *other*
slot leaves the frame untouched. There are still exactly **two frames per family**.

**Shipped anyway, framed as what it is.** The duplication reduction is real and
worth having, the entity pools are what R13 builds on, and a measured negative
result is the point of the check. Both strict xfails stay red. No claim of a fix
appears anywhere.

**The decisive control, added after review.** The round inferred "the frame carries
the label" from the exploit not moving. Review pointed out that is indirect and ran
the direct test: score only held-out items whose decider sentence **never** appeared
in `dev`.

| held-out subset | n | bigram accuracy |
|---|---|---|
| decider *was* published in dev | 34 | 100.0% |
| decider **never** published in dev | 80 | **97.5%** |

Near-identical. The model is not recognising strings. That converts the round's
conclusion from inference to evidence, and it is now `1c` in the probe.

**Method note.** Review also caught a base-rate figure that had been *scaled* from
the previous round's value rather than re-run (0.011 where the truth is 0.009) —
a direct breach of the repo's own "never ship a number the round didn't produce",
committed by the round whose entire subject is numbers being wrong. Third round
running that the checker caught the maker repeating the pattern under discussion.

**Consequence for R13:** the fix must vary *frames*, and hold some frames out of
`dev` entirely, so a model has to generalise across phrasings rather than recognise
one. That also forces the skyline to resolve the relation instead of matching a
constant — `_commerce` and `_meeting_prep` currently key on the literals
`"the desk"` and `"contract review"`, which is a lookup wearing a ceiling's
clothing and is its own recorded finding.

---

## Round 13 — hold the phrasings out

**Question:** R12 established that entity variation cannot fix the surface
exploit, because the frame carries the label. *Does holding frames out of the
training split close it?*

**Design.** Every decider is now rendered from a shared table,
`FRAMES[family] -> [(privileged_label, other_label)] x 8`, filled by
`fillers(rng) -> (marker, counterpart)`. The privileged role is the one whose
occupant decides the answer; the pair's two sides swap marker and counterpart, so
**the permutation holds by construction** rather than by an author remembering to
make it so. The dev/test split is taken **on the frame**: 0-4 train, 5-7 held out.

**Result — closed.**

| | R11 | R12 | **R13** |
|---|---|---|---|
| bigram probe (dev) | 97.2% | 93.5% | **47.0%** |
| held-out deciders published verbatim | 91.2% | 29.8% | **0.0%** |
| dict lookup, no model | 95.6% | 64.9% | **50.0%** |
| bigram on held-out phrasings | 97.5% | 97.5% | **50.9%** |
| **bag-of-bigrams vs silence** | **+99.4** | **+98.1** | **-88.2** |

Both strict xfails flipped to ordinary assertions. Verbatim overlap is **zero by
construction**, not merely small -- the difference between a guarantee and a large
enough entity pool.

**Two details are load-bearing, and one was found by measurement rather than
foresight.** The label vocabulary must genuinely change across frames, so a bigram
learned on `listed_you` does not fire on *"At the school gate"*. And **clause order
must vary per pair, independently of the frame**: tying order to frame parity left
the two splits with different order mixes, and a *positional* probe scored 34.7% on
held-out frames -- 65.3% once negated. Order now comes from a stable digest of the
pair id. The first design would have passed every bigram check and shipped a
positional leak.

**The frame-folded audit found two leaks that predate this round.** Folding the
probe by *frame* rather than by pair -- which matches how the benchmark is
actually graded -- exposed:

1. **`travel`'s gate pools were disjoint** (old gates always `{B12,C4,A21,D7}`,
   new always `{B31,C19,A2,D22}`), so a gate's identity revealed which it was and
   a bigram read `at_b12` -> speak. **Live since Round 1**, invisible to the
   unigram probe because both gates appear on both sides of a pair. One pool now,
   sampled without replacement.
2. **Frames sharing content words leak through the fold.** `collected` was the
   *other* label in `health` frames 0 and 2 -- both training frames -- so a bigram
   learned on one answered the other. The rule is stronger than "held-out frames
   differ from training frames": **all eight frames must be pairwise lexically
   disjoint**, on stems. `TestFrameDisjointness` enforces it per family.

The first draft of the frames failed this in 7 of 9 families. The check caught
what authorship could not.

**Margin to watch.** Worst per-family exploitable accuracy across six seeds is
**58.9%** (`travel`, bigram) against a 60% bound. That is thinner than it looks
comfortable being; if a future round pushes it over, the answer is more frame
vocabulary, not a wider bound.

**The skyline stopped being a lookup.** Nine hand-written matchers became one
resolver over `FRAMES`. `_commerce` matched the literal `"the desk"` and
`_meeting_prep` matched `"contract review"` -- they *resolved nothing*, and worked
only because those nouns never varied. `commerce` now varies its returnable item
too, and the skyline reads it out of the body, which is what resolving a relation
means. A ceiling that is secretly a lookup
overstates the headroom it exists to measure. It still resolves all nine families
with zero disagreements.

**The cost, recorded.** Deciders are now uniform `Label: value. Label: value.`
lines. That bought validity at a real price in naturalness -- a decider reads like
a status line, not like something a person or an app would send. Restoring prose
while keeping the held-out guarantee is now the top queue item.

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

- Overall lexical probe stays **< 70%**; every family **< 60%** — measured as
  **exploitable accuracy** (`0.5 + |acc − 0.5|`), never raw accuracy, because
  negating a classifier is free. A new family must be added to the audit, not
  exempted. **Scoped to the unigram probe** as of R11: the bigram probe is
  reported and currently reads 100% for eight of nine families (commerce fell to
  66.7% after R12's entity variation), and gating on it is deliberately deferred
  until frame expansion gives it a fix. Recorded so
  this reads as a knowing trade rather than an unenforced rule.
- **A clean audit bounds only the shortcuts you thought to test.** A probe scoring
  at chance means *that probe* found nothing — not that the dataset forces a
  judgment. R11: ten rounds of 50.0% were a bag of words being unable to see
  arrangement. Report the worst probe, never the friendliest.
- **The held-out split must not be published verbatim.** Pair-wholeness is not
  sufficient: text can repeat across the boundary even when no pair does.
  `verbatim_overlap` must stay under 10% (currently **29.8%** after R12 — open defect).
- **No pair may be divided by the dev/test split**, and every split must contain
  whole pairs only. Partner lookup against the published dev file must recover
  nothing. Anything partitioning items uses `schema.pair_key` — one definition.
- **The shipped `data/v1` must equal what `tactbench build` produces.** A
  checker that validates a stale artifact is validating nothing.
- The two sides of a pair are **equal but not identical objects** — no shared
  mutable `Signal` or `UserState`.
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
