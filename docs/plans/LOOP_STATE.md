# Loop state

The spine for the continuous-improvement loop. **Read this first, write it last.**
Context is lost between rounds; this file is not.

---

## Current status

- **Round:** 1 complete
- **Gate:** green — 30 tests, ruff clean
- **Dataset:** `v1` — 240 items (181 dev / 59 test), 6 families × 20 pairs
- **Headline:** silence (ICS 245) is unbeaten by any baseline; skyline (ICS 0)
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

## Coverage map

| area | last touched | probe / status |
|---|---|---|
| `dataset/generate.py` | R1 | 5/6 families at chance floor |
| `metrics.py` | R0 | untouched since design; ICS constants unvalidated by humans |
| `policies/builtin.py` | R1 | heuristic now near chance, as intended |
| `policies/skyline.py` | R1 | new; ceiling marker |
| `audit.py` | R1 | new; gates the build |
| `web/server.py` | R0 | **not re-verified since the dataset rebuild** |
| `policies/llm.py` | — | **does not exist** — blocked, see NEEDS-MAX |

---

## NEEDS-MAX

Items that cannot proceed without a human. **Noted and skipped — never a reason to
halt the loop.**

1. **LLM baselines need an API key.** No `ANTHROPIC_API_KEY` / `GEMINI_API_KEY` /
   `OPENAI_API_KEY` in the environment and no local Ollama. The provider-agnostic
   policy can be written and shipped unrun, but **no numbers may be published
   without actually running it.** This is now the decisive experiment: with every
   shortcut removed and no baseline clearing silence, "can a frontier model beat
   saying nothing?" is the question the repo exists to answer.
2. **Human label validation.** Labels remain by construction (`raters: 0`). Needs
   real raters and a reported κ.
3. **PyPI release** — deliberately held until (1) lands, so the first release ships
   with the finding that makes it worth installing.

---

## Queue — next rounds

1. **`policies/llm.py`** — provider-agnostic policy, prompt documented verbatim in
   the repo, zero-shot and cost-rubric variants. Buildable now; runnable only with
   a key. Ship it unrun and clearly marked.
2. **Re-verify the web viewer** against the rebuilt dataset. Untouched since R0 and
   the item shape changed underneath it.
3. **More scenario families.** Six is the real diversity ceiling now that phrasing
   is handled. Candidates: health/medication, childcare logistics, financial
   deadlines, home security.
4. **Base-rate reweighting** — a CLI flag to evaluate at a realistic 100:1
   quiet-to-loud prior, which makes silence far harder to beat.
5. **Fatigue modeling** — session-level items where interruption cost rises with
   recent interruption frequency. Needs a schema change.

---

## Standing invariants

Encoded as tests. Do not weaken them to make a round pass — if one fails, the
dataset or the policy is wrong, not the assertion.

- Overall lexical probe stays **< 70%**; the five permutable families **< 60%**.
- Skyline beats silence with **zero** hard violations (task stays solvable).
- Skyline never disagrees with a gold label (labels stay self-consistent).
- The heuristic stays near chance (**0.5 ± 0.15** precision) and never solves the set.
- Both sides of every pair carry an identical `UserState`.
- Heuristic lexicons stay single words, ≤ 20 entries — no phrase-lifting.
