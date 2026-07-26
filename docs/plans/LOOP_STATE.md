# Loop state

The spine for the continuous-improvement loop. **Read this first, write it last.**
Context is lost between rounds; this file is not.

---

## Current status

- **Round:** 3 complete
- **Gate:** green — 53 tests, ruff clean
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

## Coverage map

| area | last touched | probe / status |
|---|---|---|
| `dataset/generate.py` | R3 | 8/9 families at chance floor |
| `metrics.py` | R0 | untouched since design; ICS constants unvalidated by humans |
| `policies/builtin.py` | R1 | heuristic now near chance, as intended |
| `policies/skyline.py` | R3 | handles all 9 families; ICS 0 |
| `audit.py` | R1 | new; gates the build |
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

1. **Base-rate reweighting** — a CLI flag to evaluate at a realistic 100:1
   quiet-to-loud prior, which makes silence far harder to beat and is the honest
   production intuition.
2. **Show the skyline as a fraction.** Report each policy as % of achievable
   performance now that a ceiling exists, not just raw ICS.
3. **Fatigue modeling** — session-level items where interruption cost rises with
   recent interruption frequency. Needs a schema change.
4. **More families still welcome** — nine is better than six but still one
   author's idea of a working life. Candidates: home security, commute
   disruption, pet care.
5. **Human label validation** (also NEEDS-MAX) — a labelling CLI is buildable now
   even if the raters are not.

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
