# Decider reading (Round 82)

**Question.** Fourteen open-weight models (0.5B-8B) were run on every dataset, and none
tells the two sides of a pair apart: the best pairs-both-right on any split is 14.8%,
where a coin gets about 25%. That result has two readings, which the project had never
separated:

- **(a)** the model cannot **read** the decider: it does not know which entity holds
  which role;
- **(b)** it reads the decider but does not **use** it in the decision to interrupt.

This experiment asks each model a direct factual question about the decider alone,
with no interruption decision involved. Code: `experiments/decider_reading.py`.
Results: `results/decider-reading/`. Gate: `tests/test_decider_reading.py`, written
before the probe existed (it failed at collection) and holding every figure below.

## Design

**Data.** `v9` dev: 320 pairs, 16 families x 20. **One side per pair**, so a model never
sees both halves. Within each family the pairs are split by clause order (privileged
clause first or second, 10 and 10). Within each of those, sides alternate positive /
near-miss in `hashlib.sha256` order, and option order alternates the same way, by a
separate digest. So within every family:

- exactly half the questions come from positive sides;
- the gold answer is the first option exactly half the time;
- the gold answer is the entity named first in the decider exactly half the time.

**Questions.** There is one per family. Each asks which of the two entities holds one
role the decider assigns. The two options are the two entities the pair swaps, so
swapping them in this side's decider gives the partner side's decider (tested). Thirteen
questions ask about the *privileged* role, the one whose occupant decides the label.
Three ask about the other role because it is the plainer one to word. Every question
is answerable from the decider sentence alone, without the body, the user state or
world knowledge. `river_swim` asks only "further upstream", which its decider states
directly.

<!-- decider-reading-questions:start -->
| family | role asked | question |
|---|---|---|
| `childcare` | privileged | According to the last signal, who is responsible for getting the children from school: {a} or {b}? Answer with one of the two, exactly as written, and nothing else. |
| `commerce` | privileged | According to the last signal, which item has never been taken out of its packaging: {a} or {b}? Answer with one of the two, exactly as written, and nothing else. |
| `deadline` | privileged | According to the last signal, who is the main person on call: {a} or {b}? Answer with one of the two, exactly as written, and nothing else. |
| `dinner_booking` | other | According to the last signal, which restaurant's booking is confirmed: {a} or {b}? Answer with one of the two, exactly as written, and nothing else. |
| `driving` | privileged | According to the last signal, which road has bad traffic: {a} or {b}? Answer with one of the two, exactly as written, and nothing else. |
| `finance` | privileged | According to the last signal, which account does not have enough money for the payment: {a} or {b}? Answer with one of the two, exactly as written, and nothing else. |
| `health` | privileged | According to the last signal, which prescription has not yet been collected: {a} or {b}? Answer with one of the two, exactly as written, and nothing else. |
| `home_security` | other | According to the last signal, which part of the home is the worker expected to come into: {a} or {b}? Answer with one of the two, exactly as written, and nothing else. |
| `meeting_prep` | privileged | According to the last signal, which meeting has not started yet: {a} or {b}? Answer with one of the two, exactly as written, and nothing else. |
| `pet_care` | privileged | According to the last signal, which pet has a health problem: {a} or {b}? Answer with one of the two, exactly as written, and nothing else. |
| `photo_backup` | other | According to the last signal, which album has a copy saved somewhere besides the cloud: {a} or {b}? Answer with one of the two, exactly as written, and nothing else. |
| `quiet_hours` | privileged | According to the last signal, who can get to the hospital quickly tonight: {a} or {b}? Answer with one of the two, exactly as written, and nothing else. |
| `river_swim` | privileged | According to the last signal, which place is further upstream: {a} or {b}? Answer with one of the two, exactly as written, and nothing else. |
| `street_cleaning` | privileged | According to the last signal, on which street is the car parked at the moment: {a} or {b}? Answer with one of the two, exactly as written, and nothing else. |
| `travel` | privileged | According to the last signal, at which gate is the passenger really present right now: {a} or {b}? Answer with one of the two, exactly as written, and nothing else. |
| `water_notice` | privileged | According to the last signal, in which district does the user live now: {a} or {b}? Answer with one of the two, exactly as written, and nothing else. |
<!-- decider-reading-questions:end -->

`{a}` and `{b}` are filled with the two options as they appear in the decider, for
example `you` / `Dana`, `checking` / `savings`, `your prescription` / `Sam's prescription`
or `the desk` / `the spare`.

**Prompt.** The prompt is a single user turn with no system turn, so no chat template can
drop the instructions (R50). It contains the preamble below, a blank line, the moment
exactly as every policy sees it (`render_moment` in `policies/llm.py`, with user state
and all signals), another blank line, and the question. The decider is always the last
signal. A reading that exists only with the context stripped would be a different claim,
so the context stays.

<!-- decider-reading-prompt:start -->
```
Below is a single moment from a user's day: what the user is doing right now, and some context signals. In the signals, "you" and "your" refer to the user. Read it, then answer the question after it.
```
<!-- decider-reading-prompt:end -->

**Decoding and parsing.** Decoding is greedy (temperature 0), with at most 16 new tokens,
on the same Q4_K_M weights and llama-cpp-python server as every other local run. The
answer is the option whose naming word appears in the reply: `you`, `Dana`, `your`,
`Sam`, `desk`. It is matched as a whole word, so `your` is not `you`, and a trailing `s`
is allowed. A reply that names **neither or both** options is unparsed. It is scored
wrong and counted.

**Baselines.** Cheap answer rules, scored on the same 320 questions. The first three are
exactly 50% in every family by construction, and the tests hold them there.
*Word overlap* picks the entity whose clause shares more words with the question. It
checks that the wording of a question does not hand over its answer.

<!-- decider-reading-baselines:start -->
| baseline | overall | lowest family | highest family |
|---|---|---|---|
| always first option | 50.0% | 50% | 50% |
| first-named in decider | 50.0% | 50% | 50% |
| always the marker | 50.0% | 50% | 50% |
| word overlap with question | 50.6% | 45% | 55% |
<!-- decider-reading-baselines:end -->

## Pre-registration

These rules were written, and committed to this file, before any model was run.

- **Null.** 50% per family: two options, counterbalanced.
- **Reading a family.** A model *reads* a family if its 20 answers there are
  significant by an **exact binomial**, **one-sided** (more right than chance), at
  **p < 0.05 after Holm** correction across that model's 16 families. With n = 20 the
  first Holm step needs p ≤ 0.05/16, which means **17 of 20** right. Later steps relax
  the bar: 16 of 20 (p = 0.0059) passes only once eight families have already passed,
  and 15 of 20 (p = 0.021) passes only at the last steps. 60% on a family (12 of 20,
  p = 0.25) is not reading.
- **Overall.** Each model's accuracy over all 320 questions, with an exact one-sided
  binomial p against 50%.
- **What supports (b).** The model reads *most* families (**9 or more of 16**), yet its
  best pairs-both-right in the committed v9 runs (the better of its naive and rubric
  prompts) is still **at or below a coin's 25%**. It knows which entity holds which
  role, and that knowledge does not reach the decision.
- **What supports (a).** The model reads **at most a few** families (**3 or fewer**).
  It cannot say which entity holds the role, so it cannot act on it either.
- **Anything else** (4-8 families read, or most read with pairs above a coin) is
  reported as **neither**. It supports neither reading cleanly.
- Unparsed answers count as wrong and are reported per model. A model whose replies
  are mostly unparsed is not evidence for (a). It is reported as such.

## Results

Run in Round 82: all fourteen models, largest first, one llama.cpp server per model on
4 CPU threads. The calls took 9,862 seconds in total (`call_seconds` per model in
`results/decider-reading/MANIFEST.json`); wall time was about 2 h 55 min.

<!-- decider-reading-findings:start -->
**11 of 14** models answer above chance overall (exact one-sided binomial p < 0.05), at **60.3% to 78.8%**; the other 3 sit at 50.3% to 51.6%. No model reads the 9 or more families (b) needed: the most is **7 of 16** (`llama-3.1-8b`). By the pre-registered rule, **10** models support (a), **4** support neither, and **0** support (b).

That verdict is weaker than it looks. The family test misses partial reading: its first Holm step needs 17 of 20, which a family read at a true 75% reaches only 22.5% of the time. *Exploratory, not pre-registered:* if a model's decisions followed its reading (and it read the body right), with errors independent across a pair's two sides, it would get both sides right about accuracy² of the time. For the 11 above-chance models that is 36.4% to 62.0%; their best pairs-both-right on v9 is 0.3% to 9.4%.
<!-- decider-reading-findings:end -->

**Per model.** *Right* counts all 320 questions. *Families read* applies the
pre-registered rule. *Best pairs-both-right* is the better of the model's naive and rubric
runs in `results/v9-dev/`.

<!-- decider-reading:start -->
| model | right | accuracy | p (one-sided) | unparsed | families read | best pairs-both-right on v9 | verdict |
|---|---|---|---|---|---|---|---|
| `llama-3.1-8b` | 252/320 | 78.8% | <0.0001 | 0 | 7 of 16 | 9.4% | neither |
| `qwen2.5-7b` | 235/320 | 73.4% | <0.0001 | 0 | 4 of 16 | 2.8% | neither |
| `mistral-7b` | 222/320 | 69.4% | <0.0001 | 1 | 1 of 16 | 4.4% | (a) |
| `gemma-3-4b` | 228/320 | 71.2% | <0.0001 | 1 | 4 of 16 | 4.7% | neither |
| `phi-3.5-mini` | 222/320 | 69.4% | <0.0001 | 3 | 1 of 16 | 0.3% | (a) |
| `phi-4-mini` | 226/320 | 70.6% | <0.0001 | 0 | 4 of 16 | 1.9% | neither |
| `qwen2.5-3b` | 215/320 | 67.2% | <0.0001 | 0 | 2 of 16 | 4.1% | (a) |
| `llama-3.2-3b` | 202/320 | 63.1% | <0.0001 | 6 | 1 of 16 | 1.9% | (a) |
| `gemma-2-2b` | 193/320 | 60.3% | 0.0001 | 10 | 1 of 16 | 3.1% | (a) |
| `granite-3.3-2b` | 222/320 | 69.4% | <0.0001 | 0 | 1 of 16 | 8.1% | (a) |
| `smollm2-1.7b` | 165/320 | 51.6% | 0.3075 | 1 | 0 of 16 | 3.1% | (a) |
| `qwen2.5-1.5b` | 197/320 | 61.6% | <0.0001 | 0 | 1 of 16 | 0.3% | (a) |
| `llama-3.2-1b` | 165/320 | 51.6% | 0.3075 | 1 | 0 of 16 | 0.0% | (a) |
| `qwen2.5-0.5b` | 161/320 | 50.3% | 0.4777 | 0 | 0 of 16 | 0.3% | (a) |
<!-- decider-reading:end -->

**Per family.** Each cell is the number right out of 20. **Bold** means the family is read
(Holm-corrected one-sided exact binomial, p < 0.05). Column heads: `child` childcare,
`comm` commerce, `dead` deadline, `dine` dinner_booking, `drive` driving, `fin` finance,
`hlth` health, `home` home_security, `meet` meeting_prep, `pet` pet_care, `photo`
photo_backup, `quiet` quiet_hours, `river` river_swim, `street` street_cleaning, `trav`
travel, `water` water_notice.

<!-- decider-reading-families:start -->
| model | child | comm | dead | dine | drive | fin | hlth | home | meet | pet | photo | quiet | river | street | trav | water | read |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `llama-3.1-8b` | **18** | 14 | 16 | 16 | **17** | **17** | 14 | **17** | 13 | **18** | 12 | 16 | **17** | 14 | 15 | **18** | 7 |
| `qwen2.5-7b` | **17** | 12 | **18** | 15 | 12 | 13 | 13 | 14 | **17** | **20** | 13 | 13 | 13 | 13 | 16 | 16 | 4 |
| `mistral-7b` | 15 | 13 | 14 | 14 | 13 | 11 | 11 | 15 | 16 | **18** | 12 | 13 | 15 | 12 | 16 | 14 | 1 |
| `gemma-3-4b` | 13 | **18** | 13 | 15 | 15 | **19** | 10 | 12 | 12 | **18** | 13 | 13 | 13 | 13 | 14 | **17** | 4 |
| `phi-3.5-mini` | 13 | 14 | 12 | 13 | **18** | 14 | 10 | 16 | 15 | 16 | 12 | 16 | 14 | 12 | 11 | 16 | 1 |
| `phi-4-mini` | **17** | 14 | 13 | 15 | **18** | 15 | 15 | 13 | 9 | **17** | 14 | 13 | 10 | 10 | 16 | **17** | 4 |
| `qwen2.5-3b` | 10 | 11 | 12 | **17** | 16 | 13 | 16 | 14 | 15 | 15 | 13 | 11 | 11 | 9 | 15 | **17** | 2 |
| `llama-3.2-3b` | 11 | **18** | 8 | 14 | 10 | 15 | 13 | 16 | 13 | 16 | 9 | 13 | 11 | 9 | 12 | 14 | 1 |
| `gemma-2-2b` | 14 | 15 | 11 | 13 | 13 | 15 | 13 | 9 | 5 | **17** | 10 | 13 | 11 | 8 | 12 | 14 | 1 |
| `granite-3.3-2b` | 15 | 15 | 15 | 14 | 16 | 12 | 13 | 15 | 13 | **17** | 7 | 16 | 11 | 14 | 13 | 16 | 1 |
| `smollm2-1.7b` | 12 | 9 | 11 | 11 | 9 | 10 | 11 | 12 | 10 | 7 | 12 | 10 | 6 | 14 | 11 | 10 | 0 |
| `qwen2.5-1.5b` | 13 | 11 | 13 | 11 | **17** | 14 | 11 | 10 | 9 | 16 | 9 | 13 | 12 | 13 | 13 | 12 | 1 |
| `llama-3.2-1b` | 10 | 12 | 10 | 10 | 12 | 8 | 9 | 11 | 11 | 10 | 13 | 10 | 8 | 11 | 11 | 9 | 0 |
| `qwen2.5-0.5b` | 11 | 9 | 8 | 9 | 10 | 12 | 12 | 9 | 11 | 7 | 11 | 12 | 10 | 11 | 10 | 9 | 0 |
<!-- decider-reading-families:end -->

### What this does and does not show

- **Neither pre-registered reading holds cleanly.** Most of these models do not *fail*
  to read the decider, in the strong sense (a) intends: eleven answer the reading
  question well above chance. None reads it *reliably*, family by family, which is what
  (b) required. The honest summary is **partial reading**. These models get the role
  right roughly two times in three, which is far from the near-perfect reading a
  decision could rest on.
- **What they do read, they do not use.** This is exploratory, not pre-registered.
  Reading at 60-79% would allow far more than the 0-9% of pairs these models get right
  on both sides. Using the decider also needs the body (which restaurant is tonight's),
  so this is an illustration, not a prediction. Even so, the gap is wide.
- **The reading is with full context and an explicit question.** In the interruption
  task, nothing points the model at the last signal. The question here does, so these
  accuracies are, if anything, generous to the models.
- **One side per pair, 20 per family.** Small samples. A family read at 16 of 20 by one
  model and not by another is not evidence that the two differ.
- **Fourteen local models of 8B and under, Q4_K_M, greedy.** Says nothing about
  frontier models (NEEDS-MAX 1).
