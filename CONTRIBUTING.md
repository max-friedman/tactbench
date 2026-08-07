# Contributing

The most valuable contribution to a benchmark is usually not a feature. It's a
**near-miss pair the author didn't think of**, or evidence that a claim in the
README doesn't hold.

## The gate

Everything must pass before a PR merges. CI runs all of it on Python 3.11–3.13.

```bash
uv run pytest -q          # 60 tests
uv run ruff check .
uv run ruff format --check .
uv run tactbench audit    # per-family shortcut probe
uv run tactbench eval     # sanity-check the leaderboard still reads sensibly
```

## Adding a scenario family

This is the highest-value contribution. Nine families is nine effective degrees of
freedom no matter how many items the generator emits.

1. Subclass `Scenario` in `src/tactbench/dataset/generate.py`, implementing
   `state()`, `body()`, `deciders()`, and `why()`. Register it in `SCENARIOS`.
2. **Build the decider as a role permutation, not two sentences.** Both sides must
   carry nearly the same token multiset, differing by which noun plays which role.
   This is the rule the whole benchmark rests on — see below.
3. Add a handler to `SkylinePolicy` so the ceiling still resolves your family.
4. Run `uv run tactbench audit` and confirm your family lands near **50% in the
   unigram column**. If it doesn't, you wrote two sentences instead of one
   permutation — fix the data, not the threshold.
   **The bigram column currently reads ~100% for every family. That is a known,
   recorded defect (Round 11), not something your family introduced** — see
   "The limit of this rule" below. Do not try to fix it in a scenario PR.
5. Run `uv run tactbench build` and commit the regenerated splits. CI verifies the
   committed data is reproducible from the generator.

### Why permutation, and not just "matched pairs"

v1 emitted matched pairs and claimed they stopped keyword matching. **The claim was
false.** A bag-of-words probe that never saw user state separated the two sides at
93.5%, because each side was written as different sentences and tokens like
`hallway` and `inflight` appeared on exactly one of them.

Structural pairing is not lexical pairing. Swap roles instead of rewriting:

```
positive:  On-call rotation — primary: you,   secondary: Priya Raman.
near-miss: On-call rotation — primary: Priya Raman, secondary: you.
```

Identical token multiset. *Vocabulary* cannot separate them; only resolving
*who holds the page* can.

### The limit of this rule

A permutation defeats a bag of words **because a bag of words cannot see
arrangement** — which also means the unigram audit is structurally unable to
score a well-formed permutation at anything but 50%. Round 11 measured what that
concealed:

| probe | overall |
|---|---|
| unigram | 50.0% |
| **bigram** | **93.5%** |

The cause is that each family has only **two structural frames**, and the frame is
what carries the label: `pickup_you` → speak, `primary_you` → speak.

Round 12 tested whether *entity* variation was enough. It is not. Varying the
counterpart per pair took every family from as few as 4 distinct decider sentences
to 24–38 and cut verbatim overlap from 91.2% to 29.8% — and moved the exploit by
1.3 points, +99.4 → +98.1.

So keep writing permutations; the rule is right, and vary your entities. But
understand that **neither fixes this**. The open work item is more *frames* per
family, with some held out of `dev` entirely, so a model must generalise across
phrasings rather than recognise one.

**There are no exempt families, and you should be very reluctant to propose one.**

`quiet_hours` used to be the exception. It was declared irreducible — a medical
emergency is not a rearrangement of a routine check-in — and excluded from the
per-family assertion by name. That exemption was wrong, and it cost something
real: two substrings captured the family, and because it carries the highest
false-positive cost, a policy matching them and coin-flipping everywhere else
**beat silence**, while the honest structural heuristic did not.

The fix was to stop making severity the decider. The emergency moved into the
shared body and the judgment became *who can actually get there tonight* — which
permutes cleanly. If a family looks irreducible, the decider is probably just the
wrong axis. Look for one that permutes before asking for an exception.

## Invariants you may not weaken

Encoded as tests. If one fails, the dataset or the policy is wrong — not the
assertion. A PR that loosens a threshold to go green will be sent back.

- Overall lexical probe **< 70%**; every permutable family **< 60%**.
- Skyline beats silence with **zero** hard violations (the task stays solvable).
- Skyline never disagrees with a gold label (labels stay self-consistent).
- The heuristic stays near chance (0.5 ± 0.15 precision) and never solves the set.
- Both sides of every pair carry an **identical** `UserState`.
- Heuristic lexicons stay single words, ≤ 20 entries — no phrase-lifting from the
  generator.
- Hard violations are never averaged into ICS or reweighted by `--base-rate`.

## Two rules about honesty

These matter more here than in most repos, because a benchmark that overclaims is
worse than no benchmark.

**Never publish a number you didn't produce.** No LLM figures appear anywhere in
this repo because none have been run. If you run them, commit the numbers *and*
say which model, which prompt version, and which split.

**When you add a capability, move its limitation out of the README's limitations
section — and when you find a new weakness, add one.** That section is the
repo's credibility.

## Commits and PRs

- Branch off `main`; don't push to it directly.
- Keep formatting-only changes in their own commit, separate from logic.
- Explain **why** in the commit body, not just what. If a change was driven by a
  measurement, quote the measurement.
- If you changed costs, the generator, or a policy, re-run `tactbench eval` and
  update the results table in README.md. A README quoting stale numbers is worse
  than one quoting none.

## Licensing

Code is MIT; dataset content is CC BY 4.0. By contributing you agree your work is
released under those terms.
