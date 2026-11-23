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
Three ask about the other role because it is the plainer one to word. Every answer is
in the decider sentence; none needs the body or the user state. Twelve questions restate
the decider's role directly. Four need a small inference from the decider's wording:
`quiet_hours` asks who "can get to the hospital quickly tonight" where the decider says
"Nearby right now"; `photo_backup` asks about "a copy saved somewhere besides the cloud"
where it says "archive"; `pet_care` asks which pet "has a health problem" where it says
"daily tablets"; and `childcare` asks who is "getting the children from school" where it
says "Pickup". `river_swim` asks only "further upstream", which its decider states
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

These rules were written before any model was run. They were first committed together
with the results (one commit), so the timing cannot be verified from history.

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

That rule is underpowered. At 20 questions per family a true 75% reaches the first Holm step (17 of 20) only 22.5% of the time, so the (a) labels are not evidence that a model cannot read. *Exploratory, not pre-registered:* on the moment each model was asked about, its interrupt decision in the committed v9 runs (both prompts, 28 runs) was right 42% to 57% of the time when its reading was right and 38% to 61% when it was wrong; it was higher with a right reading in 15 of 28 runs. Getting the role right did not make the decision more often right. Whether a model can join the role to the body (which restaurant is tonight's) was not tested, so "reads but cannot join" and "reads but ignores" are not separated.
<!-- decider-reading-findings:end -->

**Per model.** *Right* counts all 320 questions. *Families read* applies the
pre-registered rule. *Best pairs-both-right* is the better of the model's naive and rubric
runs in `results/v9-dev/`.

<!-- decider-reading:start -->
| model | right | accuracy | p (one-sided) | unparsed | families read | best pairs-both-right on v9 | pre-registered verdict (underpowered) |
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

**Reading against decision.** *Exploratory, not pre-registered.* For each of the 320
asked moments, the reading answer is set beside the model's interrupt decision on the
same moment in the committed v9 run, for both prompt variants. *Spoke on* counts how
many of the 320 moments that run spoke on.

<!-- decider-reading-contrast:start -->
| model | prompt | spoke on | reading right: decision right | reading wrong: decision right |
|---|---|---|---|---|
| `llama-3.1-8b` | naive | 193/320 | 128/252 (51%) | 33/68 (49%) |
| `llama-3.1-8b` | rubric | 12/320 | 123/252 (49%) | 35/68 (51%) |
| `qwen2.5-7b` | naive | 51/320 | 123/235 (52%) | 42/85 (49%) |
| `qwen2.5-7b` | rubric | 31/320 | 120/235 (51%) | 43/85 (51%) |
| `mistral-7b` | naive | 139/320 | 107/222 (48%) | 50/98 (51%) |
| `mistral-7b` | rubric | 1/320 | 118/222 (53%) | 41/98 (42%) |
| `gemma-3-4b` | naive | 163/320 | 110/228 (48%) | 49/92 (53%) |
| `gemma-3-4b` | rubric | 59/320 | 112/228 (49%) | 51/92 (55%) |
| `phi-3.5-mini` | naive | 298/320 | 113/222 (51%) | 47/98 (48%) |
| `phi-3.5-mini` | rubric | 300/320 | 112/222 (50%) | 48/98 (49%) |
| `phi-4-mini` | naive | 273/320 | 110/226 (49%) | 53/94 (56%) |
| `phi-4-mini` | rubric | 1/320 | 125/226 (55%) | 36/94 (38%) |
| `qwen2.5-3b` | naive | 235/320 | 121/215 (56%) | 42/105 (40%) |
| `qwen2.5-3b` | rubric | 1/320 | 97/215 (45%) | 64/105 (61%) |
| `llama-3.2-3b` | naive | 96/320 | 84/202 (42%) | 68/118 (58%) |
| `llama-3.2-3b` | rubric | 0/320 | 88/202 (44%) | 72/118 (61%) |
| `gemma-2-2b` | naive | 30/320 | 91/193 (47%) | 73/127 (57%) |
| `gemma-2-2b` | rubric | 34/320 | 81/193 (42%) | 77/127 (61%) |
| `granite-3.3-2b` | naive | 300/320 | 104/222 (47%) | 60/98 (61%) |
| `granite-3.3-2b` | rubric | 185/320 | 121/222 (55%) | 50/98 (51%) |
| `smollm2-1.7b` | naive | 320/320 | 87/165 (53%) | 73/155 (47%) |
| `smollm2-1.7b` | rubric | 314/320 | 88/165 (53%) | 74/155 (48%) |
| `qwen2.5-1.5b` | naive | 0/320 | 111/197 (56%) | 49/123 (40%) |
| `qwen2.5-1.5b` | rubric | 0/320 | 111/197 (56%) | 49/123 (40%) |
| `llama-3.2-1b` | naive | 320/320 | 76/165 (46%) | 84/155 (54%) |
| `llama-3.2-1b` | rubric | 320/320 | 76/165 (46%) | 84/155 (54%) |
| `qwen2.5-0.5b` | naive | 306/320 | 91/161 (57%) | 71/159 (45%) |
| `qwen2.5-0.5b` | rubric | 318/320 | 87/161 (54%) | 73/159 (46%) |
<!-- decider-reading-contrast:end -->

### What this does and does not show

- **Neither pre-registered reading holds cleanly.** Eleven models answer the reading
  question well above chance, so (a) in its strong sense, cannot read at all, does not
  describe them. None reads reliably family by family, which (b) required. The
  measured result is **partial reading**: these models get the role right roughly two
  times in three. The (a) labels in the table come from an underpowered family test
  and are not evidence that a model cannot read.
- **A right reading did not come with a right decision.** This is exploratory, not
  pre-registered. On the moment where the model answered the reading question, its
  interrupt decision was no more often right when its reading was right (table below).
  Many runs are near-constant (see *spoke on*). For those, decision accuracy is set
  by the label mix of each subset, not by anything the run read. Whether a model can
  join the role to the body (which restaurant is tonight's) was not tested. So "reads
  but cannot join" and "reads but ignores" are not separated.
- **The reading is with full context and an explicit question.** In the interruption
  task, nothing points the model at the last signal. The question here does, so these
  accuracies are, if anything, generous to the models.
- **One side per pair, 20 per family.** Small samples. A family read at 16 of 20 by one
  model and not by another is not evidence that the two differ.
- **Fourteen local models of 8B and under, Q4_K_M, greedy.** Says nothing about
  frontier models (NEEDS-MAX 1).

## Round 83: where does the chain break?

Round 82 found partial reading (60-79% on the better models) and no link between a
right reading and a right decision. The decision needs a chain of three steps:

- **R, read:** which entity holds the decider's role. This is Round 82's question.
- **J, join:** which entity the body makes relevant, e.g. that tonight's dinner is at
  Marzano.
- **C, compose:** the two together, e.g. that tonight's booking is unconfirmed.

This round asks all three on **both sides of every v9 dev pair**, 640 moments and 40 per
family. Code: `experiments/decider_chain.py`. Results: `results/decider-chain/`. Gate:
`tests/test_decider_chain.py`, written before the probe existed (it failed at collection).

### Design (Round 83)

**R.** R is Round 82's question. On the side Round 82 asked, it is Round 82's own
answer, which is not re-asked. On the other side, the same question is asked with the
partner's option order reversed.

**J.** J's options are the same two entities as R. Its gold is the family's *marker*,
the entity the body makes relevant, on both sides of a pair. In **eight families the body
names both entities**, drawn per pair from one pool. In those, J reads the body. In the
other eight, the body names one entity or none: the relevant one is the user (`you`,
`your route`, `your prescription`) or the one thing the body mentions (`checking`, the
returnable item, the contract review). It is the same kind of entity on every item, so
a constant answer can get J right there. **J high in those eight families is not
evidence of reading the body**, and the pre-registered readings use the two-entity
families only.

**C.** C restates the decision as a fact about the relevant entity, with two *role
words* as options. Example: "is the booking for tonight's dinner unconfirmed or
confirmed?" The gold is the speak-side word on the speak side and the silent-side word on
the silent side. The question names the entity only by what the body says about it, so
answering it needs J and R together.

This replaces the suggested "which entity, or 'neither'" form, for three reasons:

- It keeps two options and a 50% chance, like R and J.
- "Neither" would be the answer on every silent side. A model that hedges with "neither"
  would then look like it composes.
- Swapping the two role words exactly counterbalances position. With a third, fixed
  "neither" option, position cannot be balanced.

Both sides of a pair carry the same tokens and opposite C answers. Any rule that reads
only the prompt's words, ignoring their order, therefore gets exactly one side of every
pair right (tested). The role words appear only in the counterbalanced `{a} or {b}`
slot, never in the question's own wording (tested).

<!-- decider-chain-questions:start -->
| family | entities the body names | J (body) | C (composed) | C options: speak / silent |
|---|---|---|---|---|
| `childcare` | one or none | According to the signals, which of the two is the user: {a} or {b}? Answer with one of the two, exactly as written, and nothing else. | According to the signals, for today's school pickup, is the user {a} or {b}? Answer with one of the two, exactly as written, and nothing else. | collecting / away |
| `commerce` | one or none | According to the signals, which item's return window is closing: {a} or {b}? Answer with one of the two, exactly as written, and nothing else. | According to the signals, is the item whose return window is closing {a} or {b}? Answer with one of the two, exactly as written, and nothing else. | unopened / used |
| `deadline` | one or none | According to the signals, which of the two is the user: {a} or {b}? Answer with one of the two, exactly as written, and nothing else. | According to the signals, is the user the {a} or the {b} person on call? Answer with one of the two, exactly as written, and nothing else. | main / backup |
| `dinner_booking` | two | According to the signals, which restaurant is tonight's dinner at: {a} or {b}? Answer with one of the two, exactly as written, and nothing else. | According to the signals, is the booking for tonight's dinner {a} or {b}? Answer with one of the two, exactly as written, and nothing else. | unconfirmed / confirmed |
| `driving` | one or none | According to the signals, which road is the user's own: {a} or {b}? Answer with one of the two, exactly as written, and nothing else. | According to the signals, is the user's own route {a} or {b}? Answer with one of the two, exactly as written, and nothing else. | jammed / clear |
| `finance` | one or none | According to the signals, which account does the card autopay draw from tonight: {a} or {b}? Answer with one of the two, exactly as written, and nothing else. | According to the signals, is the account the card autopay draws from tonight {a} or {b}? Answer with one of the two, exactly as written, and nothing else. | underfunded / covered |
| `health` | one or none | According to the signals, which prescription is the user's own: {a} or {b}? Answer with one of the two, exactly as written, and nothing else. | According to the signals, is the user's own prescription {a} or {b}? Answer with one of the two, exactly as written, and nothing else. | uncollected / collected |
| `home_security` | two | According to the signals, where has the camera seen motion: {a} or {b}? Answer with one of the two, exactly as written, and nothing else. | According to the signals, at the place where the camera has seen motion, is a worker {a} or {b}? Answer with one of the two, exactly as written, and nothing else. | unexpected / expected |
| `meeting_prep` | one or none | According to the signals, which meeting is the revised vendor contract for: {a} or {b}? Answer with one of the two, exactly as written, and nothing else. | According to the signals, is the meeting the revised vendor contract is for {a} or {b}? Answer with one of the two, exactly as written, and nothing else. | upcoming / started |
| `pet_care` | two | According to the signals, which pet left its breakfast uneaten: {a} or {b}? Answer with one of the two, exactly as written, and nothing else. | According to the signals, is the pet that left its breakfast uneaten {a} or {b}? Answer with one of the two, exactly as written, and nothing else. | fragile / healthy |
| `photo_backup` | two | According to the signals, which album is deleted at midnight: {a} or {b}? Answer with one of the two, exactly as written, and nothing else. | According to the signals, when the album deleted at midnight goes, are its photos {a} or {b}? Answer with one of the two, exactly as written, and nothing else. | lost / saved |
| `quiet_hours` | one or none | According to the signals, which of the two is the user: {a} or {b}? Answer with one of the two, exactly as written, and nothing else. | According to the signals, is the user {a} or {b} from the hospital tonight? Answer with one of the two, exactly as written, and nothing else. | near / far |
| `river_swim` | two | According to the signals, where is the sewage overflow: {a} or {b}? Answer with one of the two, exactly as written, and nothing else. | According to the signals, is the sewage overflow {a} or {b} of the club's swim? Answer with one of the two, exactly as written, and nothing else. | upstream / downstream |
| `street_cleaning` | two | According to the signals, which street is swept at 7am tomorrow: {a} or {b}? Answer with one of the two, exactly as written, and nothing else. | According to the signals, is the street swept at 7am tomorrow the car's {a} or {b} spot? Answer with one of the two, exactly as written, and nothing else. | current / previous |
| `travel` | two | According to the signals, which gate did the flight's gate change move away from: {a} or {b}? Answer with one of the two, exactly as written, and nothing else. | According to the signals, is the passenger right now at the {a} or the {b} gate? Answer with one of the two, exactly as written, and nothing else. | old / new |
| `water_notice` | two | According to the signals, which district is under the boil-water notice: {a} or {b}? Answer with one of the two, exactly as written, and nothing else. | According to the signals, is the district under the boil-water notice the user's {a} or {b} home? Answer with one of the two, exactly as written, and nothing else. | current / former |
<!-- decider-chain-questions:end -->

Each question follows the moment's full rendered context and Round 82's preamble.
Decoding is the same: greedy, 16 tokens, a single user turn, and an answer that names
neither option or both is unparsed and scored wrong. Option order alternates in
`hashlib` order within each (family, clause order) stratum, and a pair's two sides take
opposite orders. So in every family the first option and the entity (or role word) named
first in the decider each answer exactly 20 of the 40 questions of each kind (tested).
*First-named in body* is not controlled. The body's own phrasings place the entities, and
`travel` always names the old gate first.

<!-- decider-chain-baselines:start -->
| question | baseline | overall | lowest family | highest family |
|---|---|---|---|---|
| R | always first option | 50.0% | 50% | 50% |
| R | first-named in decider | 50.0% | 50% | 50% |
| J | always first option | 50.0% | 50% | 50% |
| J | first-named in decider | 50.0% | 50% | 50% |
| J | first-named in body | 60.3% | 30% | 100% |
| C | always first option | 50.0% | 50% | 50% |
| C | first-named in decider | 50.0% | 50% | 50% |
| C | always the speak word | 50.0% | 50% | 50% |
<!-- decider-chain-baselines:end -->

### Pre-registration (Round 83)

These rules were written before any Round 83 model call, and this file is committed
before the runs start, so the order can be checked in history.

- **Models.** These are the six with Round 82 accuracy of at least 69%: `llama-3.1-8b`,
  `qwen2.5-7b`, `mistral-7b`, `gemma-3-4b`, `phi-4-mini` and `granite-3.3-2b`. They run
  largest first. If the timing of the first model puts the total far past about 6 hours,
  the smallest are dropped and named.
- **Power.** Each model is tested per family on each of R, J and C, with n = 40, a
  one-sided exact binomial and Holm across 16 families. The first Holm step needs
  **30 of 40** (p = 0.0011), and a family read at a true 75% reaches it
  58.4% of the time. A later step at p ≤ 0.05/8 needs **29 of 40**, which a true 75%
  reaches 71.5% of the time. Per-family counts are reported but do not decide the
  readings. The pooled figures below do.
- **Pooled accuracy.** Each model's R, J and C accuracy is pooled over the **eight
  two-entity families** (n = 320 per question). A step is *high* at **at least
  70%** and *low* **below 60%**. The readings are checked in this
  order:
  1. J low: a **break in finding the relevant entity**.
  2. Otherwise R low: a **break in reading the decider**.
  3. R and J high but C low: a **break in composition**.
  4. R, J and C all high: **no break before the decision**. The failure is in using the
     composed fact to decide.
  5. Anything else is **unresolved** and reported with its numbers.
- **Per-item chain test.** On the two-entity items, compare
  P(C right | R right and J right) against P(C right | otherwise) with a one-sided
  **Fisher** exact test, p < 0.05 per model. If composition uses the two steps, C should
  be right more often when both are right.
- **Also reported, not decisive.** R, J and C over all 16 families; per-family counts
  with the Holm marks; unparsed counts.

### Results (Round 83)

Not yet run.
