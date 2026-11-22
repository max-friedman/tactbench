# Dataset

## Structure

Splits live in `data/<version>/<split>.jsonl`, one JSON object per line, each an
`Item` — a `Moment` paired with its `GoldLabel`.

A **moment** is everything a policy is allowed to see:

- **signals** — observations from `screen`, `calendar`, `message`, `email`,
  `location`, `app_event`, `notification`, `sensor`. Each carries `age_s` (how
  stale it is) and optional `meta` (sender, contact class, priority).
- **user_state** — `activity`, `dnd`, `device`, `last_interaction_s`, `local_hour`.
- **family** and **slices** — for stratified reporting. **`slices` is removed, and
  `id` replaced by an opaque hash, before any policy sees a moment**
  (`schema.policy_view`, via `policies.base.ask`). Both encoded the label — "no
  `near_miss` tag means speak", and `-pos-` / `-near-` in the id, are each right on
  100% of items — and until Round 26 a policy reading either scored ICS 0.0. `family`
  is passed through: both sides of a pair share it, so it carries no label. A test
  asserts that a pair's two views differ only in the decider text and the opaque id.
  The LLM prompt omits `id`, `family` and `slices`.

A **gold label** carries `should_surface`, a `value` in 0–3, `acceptable_intents`,
an optional `window_s`, a human-readable `rationale`, and `raters` / `agreement`
for labels that have been through human review.

## Why moments come in matched pairs

This is the load-bearing design decision.

A benchmark of "should the assistant speak?" is trivially gameable if the items
that warrant speech look different on the surface from the ones that don't. Any
policy could match keywords — *delayed*, *expires*, *overdue*, *failed* — and post
a strong score without having judged anything at all.

### Pairing alone was not enough

v1 emitted matched pairs and claimed they prevented keyword matching. **The claim
was false and the audit proved it:** a bag-of-words classifier that never saw user
state separated the two sides at **93.5%**. The pairs shared a *family*, but each
side was written as different sentences, so tokens like `hallway`, `inflight`, and
`closes` appeared on exactly one of them and handed over the answer.

Structural pairing is not the same as lexical pairing. The fix is a construction
rule:

> **Both sides share a byte-identical body and an identical user state. Only one
> decider signal differs, and it differs by permuting which noun plays which role
> — never by rewriting the sentence.**

| family | shared body | decider (positive → near-miss) |
|---|---|---|
| `travel` | gate moved A → B, boarding in *n* min | pass reads **B**, you're seated at **A** → pass reads **A**, you're seated at **B** |
| `deadline` | deploy failed, auto-rolled back | primary escalation goes to **you**, secondary to **Priya** → primary to **Priya**, secondary to **you** |
| `commerce` | return window closes in *n* hours | **desk** boxed, **replacement** assembled → **replacement** boxed, **desk** assembled |
| `meeting_prep` | revised contract unread, 90 min old | **review** begins in *n*, **standup** began *n* ago → **standup** begins in *n*, **review** began *n* ago |
| `driving` | flight departs in *n* hours | **your route** backed up, **alternate** clear → **alternate** backed up, **your route** clear |
| `quiet_hours` | *n*th message from Mom, **and the admission itself** | **you** are nearby / Mom is hours out → **Mom** is nearby / you are hours out |

Deciders are **prose**, and the filler always sits at the *end* of its clause:

```
positive:  Behind the screen is your prescription. Through the till is Elena's prescription.
near-miss: Behind the screen is Elena's prescription. Through the till is your prescription.
```

That position is not cosmetic. Round 15 built prose whose clauses opened with the
subject and the bigram probe read **75%** on `health` against a 60% bound, because
`item_tokens` joins signals before tokenizing: the body's last token lands against
the decider's first, and the body is shared across all eight frames, so that one
bigram transfers straight through a held-out frame. Round 16 moved the filler to
clause-final and added two properties that close the mirror trap — no clause opens
with a stopword, and both clauses of a frame put the same token before the slot.
`TestProseFrameStructure` asserts all three.

Round 21 ruled on the join itself, which Round 15 had flagged as unresolved and
load-bearing. **It stays.** A submitter picks their own representation, so the probe
takes the upper bound over representations rather than modelling one reader: a policy
serializing the moment into a single prompt genuinely sees that junction, and
tokenizing signals separately would report "clean" for a leak an LLM baseline could
take. Keeping it costs nothing, and `TestSignalJoinIsFree` asserts that the cost is
zero **exactly** — joined and per-signal bigram accuracy must be identical, with no
tolerance, because across 270 family-seed cells (at sizes 16, 20, 24, 30 and 40) the
gap is not merely small but always zero.

**What that check is and is not for.** It does *not* catch the clause-initial defect
first — `TestProseFrameStructure` already does, on all nine families, deterministically.
Round 21 initially claimed otherwise and was wrong. The three structural properties
constrain the decider's clause *openings*, which protects the junction the **body**
sits against, and that is sufficient only because the decider is currently the **last**
signal. Append one shared signal after it — leaving the frames untouched, so all three
properties still pass — and the decider's trailing filler abuts text every frame shares:
the join check then fires for **8 of 9** families while the 60% bound fires for 1. That
trailing junction is what it covers.

**It is not the only thing that would notice, and the first two drafts of this
paragraph both undercounted.** Appending that signal to every item turns the suite
red in **six** places, three of them a direct consequence of the last-signal
convention: the per-family 60% bound
(`quiet_hours`, 61.6%), the overall `< 70%` bound, three tests that fail because the
suite already hard-codes the decider as the **last** signal (`signals[-1]`,
`signals[:-1]`) — split disjointness, object identity and order balance — and dataset
reproducibility, which fails on *any* generator change and so says nothing about
signal position. A family placing a signal after the decider is not a silent hole;
it is a loud one.

What the join check adds is **localization and breadth**: it is the only assertion
that identifies the failure *as a junction leak*, and it fires on 8 of 9 families
where the bound fires on 1. No frame-shape property sees it at all.

The same round re-derived the three properties by mutating each across all nine
families, and kept all three. Three results are worth recording:

- A clause-initial filler breaches the 60% bound for **2 of 9** families on
  `seed=20260726` but **5 of 9** at its worst over eight seeds. **The bound is a
  point estimate sampled once**, so every leakage figure here carries unquantified
  spread. This limits the bound, **not the gate**: `TestProseFrameStructure` rejects
  that defect on all nine families deterministically, with no dataset and no seed,
  so `pytest -q` was never at risk of passing it.
- Violating the stopword rule moves nothing at all on `health`, and it is the only
  family where that is true: its fillers (`your prescription` / `Elena's
  prescription`) share a final token, so the internal junction bigram is identical
  whichever role each noun plays. Across all nine, the violation is worth up to
  **+16.1%** (`commerce`, 50.0% → 66.1% at its worst over eight seeds, the one cell
  that breaches the bound). Measuring it on `health` alone would have justified
  deleting a live assertion.
- `health` is also the only family immune to the trailing-signal leak above. Two
  independent tests, same mechanism: the exception is the shared final token, not
  something particular to the stopword rule.

### How much do these numbers move if you change the seed?

Round 21 found that a *defect's* measured size moves with the build seed, and queued
the worry that every leakage figure here is a point estimate with unquantified
spread. Round 22 measured it on **shipped** frames over 20 seeds, through the exact
pipeline that produces the committed split — a reconstruction that reproduces
`data/v1/dev` object-for-object (`model_dump()` equal). The worry is half right, and the halves point opposite
ways:

| probe | gated? | shipped reading | range over 20 seeds | worst per-family spread |
|---|---|---|---|---|
| unigram | **yes** | 50.0% | 50.0 – 50.0% | **0.0 points** |
| bigram | **yes** | 50.0% | 50.0 – 50.0% | **0.0 points** |
| positional | no | 58.0% | 52.8 – 63.9% | **40.0 points** (`health`, 50.0–90.0%) |

**The gated figures are not point estimates at all.** They are pinned at chance by
construction — both sides of a pair carry the same token multiset, so neither a bag
of words nor a bag of bigrams can separate them whatever entities are drawn. No seed
puts any family over the 60% bound. `TestGatedProbesAreSeedStable` asserts the
stability *and* the value, because a family pinned at a constant 100% would satisfy
stability alone.

**The positional figure is, for most families, a point estimate — and a wide one.**
It is reported rather than gated because it reads arrangement, which a permutation
does not control. Per family, over the same 20 seeds
(`experiments/seed_spread_probe.py` prints this table; a test recomputes it):

<!-- seed-spread:start -->
| family | min | max | seeds > 60% | decider varies with seed |
|---|---|---|---|---|
| childcare | 50.0% | 76.7% | 6 | yes |
| commerce | 50.0% | 83.3% | 14 | yes |
| deadline | 50.0% | 80.0% | 11 | yes |
| driving | 63.3% | 63.3% | 20 | no |
| finance | 50.0% | 63.3% | 17 | no |
| health | 50.0% | 90.0% | 7 | yes |
| meeting_prep | 53.3% | 70.0% | 11 | yes |
| quiet_hours | 50.0% | 80.0% | 8 | yes |
| travel | 50.0% | 65.0% | 3 | yes |
<!-- seed-spread:end -->

**Read these counts against chance (Round 37).** At 28 items a family the positional
probe exceeds 60% in about half of family-seed cells even when labels are shuffled
within pairs, so "seeds above 60%" is mostly noise for a single family; what carries
information is a reading that does not move (`driving`) and the pooled figure. See
*Dataset v2* below.

Round 22 published "6 to 14 seeds out of 20" here; the true range is **3 to 20**, and
the correction changes the reading. For seven families the figure is a draw: read
it as a range. **For `driving` it is not a draw at all.** Its decider sentences use a
fixed condition vocabulary and no entity, so they are identical on every seed, and a
whole driving moment is always 19 or 21 tokens (fixed by frame) — position tags are
tenths of the whole moment, so the tags the probe sees on the decider are the same
on every build, and so is the reading: **63.3%,
above the 60% per-family bound the gated probes must meet**, on all 20 seeds. That
is a property of `driving`'s frames, not of a seed. `finance`'s deciders are also
seed-invariant, but a whole finance moment varies from 15 to 23 tokens, which shifts the tags; it
still exceeds 60% on 17 of 20. The two families whose deciders never vary are the
two most often above the bound. No gate fails, because the positional probe is not
gated.

### Dataset v2 — the same generator at 32 pairs (Round 37)

Round 36 traced `driving`'s fixed 63.3% to the **pair count**: clause order
alternates on `idx // 8`, so a (family, frame) cell is order-balanced only with an
even number of pairs. At the shipped 20, frames 0-3 hold three pairs (2:1) and dev
is 9:5 by order in every family; a positional probe learns the majority. `data/v2`
is `tactbench build --version v2 --pairs 32` — no code change — and every cell is
balanced (360 dev / 216 test items). `v1` is unchanged, so every published v1
figure, including the LLM results, still describes `v1`.

What it changes, measured over 20 seeds against a **label-swap null** — the same
moments with each pair's labels swapped at random, so labels carry no information:

- **Overall**, the positional leak at 20 pairs is real and at 32 it is gone. At 20
  pairs the probe's median is **59.5%** and it exceeds 60% on **9 of 20** seeds,
  against a null of 53.4% and 0 of 20. At 32 pairs it is **51.7%**, 0 of 20 —
  below the null's 53.5%.
- **`driving`** read a constant 63.3% at 20 pairs and reads exactly **50.0%** on
  every seed at 32 — a deterministic change, not a draw.
- **Per-family readings are mostly noise at this size**, with 28-40 items a family.
  With labels independent of the text, family-seed cells exceed 60% in **101 of
  180** at 20 pairs and **77 of 180** at 32; observed is 97 and 45. So a single
  family reading above 60% is not evidence of a leak. `commerce`, the family still
  most often above 60% at 32 pairs (11 of 20), matches its own null (10 of 20) —
  there is no evidence of a second cause.

`experiments/order_balance_probe.py` prints all of it; a test compares these
figures with it. (The first version of this section reported "97 → 45 of 180" as the
improvement and called commerce a second cause; review ran the null and showed both
counts are mostly chance.)

### Dataset v3 — a tenth family, `pet_care` (Round 45)

`data/v3` is `tactbench build --version v3 --pairs 32 --families 10`: v2 plus one new
family (400 dev / 240 test). A smart feeder reports that one pet left its meal and the
other ate; the decider says which pet is medically fragile — *"Mending after an operation is Mochi. Thriving in excellent health is Pepper."* Speak when the pet that skipped is the
fragile one; stay quiet when it is the healthy one. Both names appear in the shared
body and on both sides, and swap roles, so it is a role permutation like every other
family.

The family is **appended** to the generator's scenario list (`LATER_SCENARIOS`) and
its frames kept apart from `FRAMES` (`LATER_FRAMES`), so `v1` and `v2` are
byte-identical and every moment of the first nine families in v3 equals its v2
counterpart — asserted in `tests/test_dataset_v3.py`, which also holds the new
family to the unigram and bigram probes at chance (on ten seeds), the positional
probe under its label-swap null, order-balanced cells, the skyline solving it and the
heuristic not.

One limit of the positional probe shows here: `pet_care`'s marker is a drawn name, not
a constant, so a probe of token positions cannot see which clause holds it. A planted
"privileged clause always first" mutation left the positional probe at chance and was
caught only by the order-balance check. The check exists for every family; it is the
guard that matters for this one.

**Clause length — found in review, fixed for `pet_care`, a known weakness elsewhere.**
Frames are held to equal *token* counts, not character counts. The first `pet_care`
draft had the privileged clause longer in 6 of 8 frames and never shorter, and every
body named the skipped pet first, so "speak if the clause ending in the body's first
name is the longer one" read 90% on dev and 83% on test. The frames now balance
length on dev frames and on held-out frames separately, two of four body phrasings
name the skipped pet second, and the exploit's median over 20 seeds is 50%
(`experiments/clause_length_probe.py`; both gated in `tests/test_dataset_v3.py`).

The original nine families were never held to this. Each leans on its *dev* frames —
childcare's and commerce's privileged clause is shorter in 4 of 5 — but a rule learned
on the dev frames does not transfer to the held-out frames: it reads at or below 50%
there in eight of the nine. `deadline` reads 83%, on three frames, which is too few to
call. On dev the lean is one more feature of five public frames, which a parser of the
templates already exploits fully (Round 33); changing those families would change v1
and v2, so they are left as published and the length-balance test applies to families
added from v3 on.

**Longest word — a smaller lean in `pet_care`, found in Round 47.** With the marker
located properly, "speak iff the skipped pet's clause has the shorter longest word"
reads 70% on v3 dev and 67% on test (two of three held-out frames). The other five
clause features read 50–60%. v3 is published with LLM runs against it, so this is
recorded and gated (`tests/test_dataset_v3.py`) rather than changed; `home_security`
is held to all six features from the start.

### Dataset v4 — an eleventh family, `home_security` (Round 47)

`data/v4` is `tactbench build --version v4 --pairs 32 --families 11`: v3 plus one new
family (440 dev / 264 test). The user is at work; a camera reports motion at one part
of the home while another is quiet. The decider says where a booked visitor is and is
not going — *"Roofers bypassing the shed. Roofers repairing the garage."* Speak when
the motion is where nobody is expected; stay quiet when it is where the visitor is.
Both zones appear in the shared body and on both sides, and swap roles. Zones are
drawn from a pool of 40 single words, none of which appears in a frame.

Built the way v3 was, and held to everything v3's new family is
(`tests/test_dataset_v4.py`): every moment of the first ten families equals its v3
counterpart; unigram and bigram at 50% on ten seeds; the positional probe against its
null over 20 seeds; order-balanced cells; both zones on both sides and the motion zone
named first in about half of bodies, on dev and test; the skyline solves it and the
heuristic does not.

**A morphology leak, found in review and fixed before anything ran on v4.** The first
draft named a visitor only in the non-privileged clause ("Booked for gardeners" against
"Unoccupied this evening"), six of eight times with an *-er* noun. "Find the motion
zone's clause; stay quiet if it has an -er word" read **90% dev / 83% test**, and it
transferred to held-out frames because it depends on the frame design, not on a seed.
Now both clauses of every frame name the same visitor in the same verb form, and the
gate is no longer length alone: `experiments/clause_length_probe.feature_exploit`
compares six clause features (characters, *-er*, *-s*, *-ing*, *-ed* words, longest
word) between the marker's clause and the other, and every one must read chance over
20 seeds and at most 60% on the held-out split. Three of the first draft's frames also
named times that did not fit a weekday afternoon ("this evening", "overnight"); the
body no longer names a clock time either.

The review also found that the length check shipped with the first draft **could not
fail**: it took the first zone in the body as the marker, and body order is balanced,
so its sign flipped at random against the label. It now finds the marker the way the
skyline does, and a test pads the privileged clauses and requires the reading to jump
past 90%. The same fix applies to `pet_care`'s check (whose readings are unchanged at
50%).

The overall positional probe is held both to v3's single-seed check (shipped dev 52.3%
against a null median of 52.4%) and to the same comparison over 20 seeds. An earlier
rebuild read 52.5% against 52.4% on one seed — noise, as the seed sweep showed.

A second review tried 111 cheap clause features (every letter, letter pairs, affixes,
prepositions, lengths). One rule cleared 60% on both splits: "speak iff the motion
clause has fewer *e*'s" reads 70% dev / 83% test, frame-determined. One hit in 111 is
about what chance gives, so it is stated here and pinned in a test rather than tuned
away — tuning frames against every letter would fit the probe, not fix a cue. The
same review caught frame 4's verb ("halted in the garage" can mean the carpenter is
there), now "excluded from".

What the family does not resist, and no family does: the privileged clause always
carries an ordinary word of exclusion or absence (*barred*, *skipping*, *cancelled*,
*excluded*). A reader that locates the motion zone's clause and knows those words
solves the family — that is reading the decider, which is the task.

### Dataset v5 — a twelfth family, `water_notice` (Round 52)

`data/v5` is `tactbench build --version v5 --pairs 32 --families 12`: v4 plus one new
family (480 dev / 288 test), from a domain none of the eleven touches — a public
utility notice. The user is out for the evening; the water company posts a boil-water
notice for one district and says another is unaffected. The decider, an old email,
says which district is home now and which is a former address — *"Currently renting
in Upton. Previously renting in Selby."* Speak when the notice covers home; stay quiet
when it covers the old address. Both districts appear in the shared body and on both
sides, and swap roles. Districts come from a pool of 40 single words, none of which
appears in a frame or in another family's pool.

Held to everything v4's new family is (`tests/test_dataset_v5.py`): every moment of
the first eleven families equals its v4 counterpart; unigram and bigram at 50% on ten
seeds; order-balanced cells; both districts on both sides and the notice district
named first in about half of bodies; the six clause features, and vowel and consonant
counts, at chance; the skyline solves it and the heuristic does not.

**Frames were chosen by search, and the first choice leaked on vowels.** The structural
rules (equal skeletons, a shared token before the slot, no stopword opening, vocabulary
disjoint across frames) and the gated clause features leave few hand-written sets, so
the frames were picked by searching candidate sets for ones where the privileged clause
wins each feature as often as it loses, on dev and held-out frames separately. A first
set met all of that; a scan of 139 cheap clause features then found "speak iff the
notice district's clause has more vowels" reading **80% dev / 83% test**. Vowel and
consonant counts were added to the search and gated. Review then dropped three frames
a careful reader could take the wrong way (*"Unpacked boxes"*, often meaning boxes not
yet unpacked; *"Boiler drained"*, routine maintenance; *"Sofa collected"*), and a
second review two more (*"Electricity meter read"*, which happens on moving out;
*"Spare room vacated"*). On the shipped set a 749-feature scan finds no rule at 70% or
more on both splits; the best on dev read 70% dev / 50% test.

That scan is not an independent check: the search also ranked candidate sets by letter
balance. The character 3-8-gram probe (Round 49) did not inform the search; on v5 it
fits dev at 90.2% and reads 51.0% on held-out test (`water_notice` 50.0% of 24), and
its verdict holds.

**The token-positional probe cannot see this family's clause order.** Its features are
tokens tagged with their position; here the marker is a random district, so nothing it
can learn says where the marker sits. Review forced the privileged clause first in
every pair — a rule "speak iff the notice district is in the first clause" then reads
100% — and the positional test still passed. Order is guarded instead by a
marker-aware check: within each label, the notice district leads the decider exactly
half the time (and a mutation test forces the order and requires 100%). `pet_care` and
`home_security` have the same kind of marker, and so do `travel` (the gate boarding
moved away from) and `commerce` (the item whose return window closes). Since Round 55 the
same check (`tests/test_marker_order.py`) covers all five, on every version that carries
them, and is tied to the skyline's list of body-read markers so a new one cannot be
missed. On the committed builds the marker leads in exactly half of each label, so the
order rule reads 50.0%; forcing the order for any one family in a fresh build makes it
read 100%. The exception is v1 dev for `travel` and `commerce`, which fails it for the
same reason v1 fails cell balance (Round 36): 20 pairs over 8 frames. It is a strict
xfail. The check is the privileged-first fraction read through the marker, so it holds
only for builds whose pair count is a multiple of 16, as the committed v2-v7 builds' 32 is.

The token-positional reading itself: on the shipped seed the family reads 57.5%
positional against a label-swap null of 57.5%. Over the first 20 seeds 10 read above
60% against 25% of null draws, past the test's slack; over 60 seeds the rate is 30%
against 31%, and over 200 it is 35.5% against 32.6% (medians 60.0% against 57.5%, one
item in 40), with blocks of 20 seeds ranging from 2 to 10 above. The family's test
compares over 60 seeds with the same thresholds; that choice was made after the
20-seed reading failed. Overall, the shipped seed reads 53.1% against 51.7%, and the
20-seed medians 51.9% against 52.1%; v5 keeps the seed-robust comparison and the
single-seed 60% bound, not v4's single-seed comparison with the null. Positional is
reported, not gated.

What the family does not resist, as for `home_security`: the former-address clause
always carries an ordinary word of ending or reversal (*previously*, *formerly*, *old*,
*returned*, *unscrewed*, *cancelled*, *unmounted*; in one frame the reversal sits on
the home side instead, *unloaded*). A reader that locates the
notice district's clause and knows those words solves the family — that is reading the
decider. No LLM has been run on v5.

### Dataset v6 — a thirteenth family, `street_cleaning`

`data/v6` is `tactbench build --version v6 --pairs 32 --families 13`: v5 plus one new
family (520 dev / 312 test), from municipal parking, which none of the twelve touches.
The user is at the gym in the evening; a city notice says one street is swept at 7am
tomorrow and parked cars there will be towed, and that another street is not swept.
The decider, a location signal from an hour earlier, says which street the car is
parked on now and which it was on before — *"Parking session started on Kendal.
Parking session ended on Ashford."* Speak when the car is on the swept street; stay
quiet when the swept street is where it used to be. Both streets appear in the shared
body and on both sides, and swap roles. Streets come from a pool of 40 single words,
none of which appears in a frame, a body template, or another family's pool.

**It adds a domain, not a new decision shape.** Structurally it is `water_notice`
again: a notice names one of two places, and the decider says which is current and
which is former. It widens what the moments are about; it does not test a different
kind of reasoning.

Held to everything v5's new family is (`tests/test_dataset_v6.py`): every moment of
the first twelve families equals its v5 counterpart; unigram and bigram at 50% on ten
seeds; order-balanced cells; both streets on both sides and the swept street named
first in about half of bodies; the six clause features, and vowel and consonant
counts, at chance; the marker-aware order check; the skyline solves it and the
heuristic does not. One check is new: no single letter's count may read 70% or more
in the same direction on dev and on test.

**Frames were chosen by search from the start**, as `water_notice`'s were in the end:
51 candidate frames that meet the structural rules and read clearly as now against
before, searched for a dev set (frames 0-4) and a held-out set (5-7) on which all
eight gated clause features balance exactly, then ranked by the strongest of 936 cheap
clause features (letters, letter pairs and triples, affixes, word lengths) reading the
same way on both splits. Excluded before the search: frames naming only an absence
(*"Kerb vacant tonight on"*, which says where the car is not, not where it was) and a
"stop logged" pair (a logged stop can be brief). On the shipped splits a scan of the
412 such features present finds no rule at 70% on both; the best reads 60% dev / 83%
test (count of the letter *s*), and the best on dev alone 70% dev / 50% test. As for
v5, that scan informed the search and is not an independent check. The character
3-8-gram probe (Round 49) did not inform it; on v6 it fits dev at 89.2% and reads 52.2%
on held-out test (`street_cleaning` 54.2% of 24), and its verdict holds.

**The overall positional comparison fails on 20 seeds, and the cause is not this
family's frames.** v5's test asked that the 20-seed median of the overall positional
reading be at or under its label-swap null's. On v6 it reads 20-seed medians 51.9%
against 51.7% — 0.2 points over, where one item in 520 is 0.19. Putting
`water_notice`'s shipped frames in the thirteenth slot instead fails the same way
(51.8% against 51.7%), as do `home_security`'s (52.0% against 51.7%) and every one of
the four frame sets tied in the search; `pet_care`'s frames there pass (51.5% against
51.9%), so it is not every thirteenth family. Over 60 seeds it reads 60-seed medians 52.12%
against 52.31%. The 20-seed form is kept as a strict xfail; the 60-seed form, chosen
after the 20-seed one failed (as R52 chose 60 seeds for `water_notice`'s family test),
is the gated one. On the shipped seed the overall reading is 52.7% against 51.5%, under
the 60% bound. Positional is reported, not gated, so no invariant moved. The family
itself reads 52.5% positional on the shipped seed against a null of 58.7%; over 60
seeds its median is 57.5% against 57.5%, and 33% of seeds read above 60% against 36% of
null draws.

What the family does not resist, as for `water_notice`: the former-position clause
always carries an ordinary word of the past or of leaving (*old*, *ended*, *origin*,
*surrendered*, *was*, *formerly*, *prior*, *until*). A reader that locates the swept
street's clause and knows those words solves the family — that is reading the
decider. All 28 LLM runs are on v6 (Round 72; README, *On dataset v6*).

**A combination of letter counts reads the held-out frames, and the per-letter gate
cannot see it** (found in the R71 review; `experiments/letter_bag_probe.py`). Weight
each letter by how its count difference between the two clauses correlates with the
label on dev, and the weighted sum reads `street_cleaning`'s held-out test at
**100.0%**. That is three frames, so three frame-level coin flips; leaving one frame
out at a time over all eight reads **62.5%** (5 of 8 frames above half). The class is
not new: on v4 `home_security` the same probe reads **83.3%** dev→test and **87.5%**
leaving one frame out (7 of 8), and that family is published with runs. On v5
`water_notice` it reads **33.3%** and **12.5%**.

**Against an exact null, none of it is distinguishable from chance** (Round 73,
`tests/test_letter_bag_null.py`). Readings are fixed by the frames, so the right null
swaps which clause of each frame is the privileged one: that negates every letter
difference in the frame and leaves the label alone, and the 2**8 orientations of
eight frames are an exhaustive null. Pre-registered: a family fails if under 5% of
orientations read at least its shipped leave-one-frame-out figure. All 93
family-version cells pass (64 when Round 73 measured them; v7 and v8 each add one per
family), covering all fifteen families on every version that carries them. `street_cleaning`'s 62.5% has p=0.430. The lowest is `home_security`
at p=0.070 (87.5% leaving one frame out). At 5% each, thirteen families give about
0.65 expected false alarms (fifteen, since v8, about 0.75), so a future failure is a reason to look at the frames, not
a verdict. Adding a *z* to every privileged clause drives p to 0.016, so the gate can
fail.

### Dataset v7 — a fourteenth family, `river_swim`

`data/v7` is `tactbench build --version v7 --pairs 32 --families 14`: v6 plus one new
family (560 dev / 336 test). The user is on the train home in the late afternoon. One
shared body signal says a sewage overflow is discharging into a river at one place and
that the user's club swims in the same river at another place tonight. The decider, a
river map, says only which of the two places lies upstream of the other — *"Water
flows first past Copley. Water flows later past Dunholt."* Speak when the overflow is
upstream of the swim, because the river carries it there; stay quiet when the overflow
is downstream, because the river carries it away. Both places appear in the shared
body and on both sides, and swap roles. Places come from a pool of 40 invented single
words (so no model can know a real river's order), none of which appears in a frame,
a body template, or another family's pool.

**What is new is narrower than a new decision shape** (corrected in the R74 review).
Logically the family reduces to the old form: there are two places, the swim is always
the other one, so "the overflow is upstream of the swim" is the same as "the overflow's
place carries the label *upstream*". The decider labels one entity and, given the body,
that label settles it, as in all thirteen earlier families. The skyline handles it with
the same branch as `water_notice`. Three things do differ:

- the user's location is in the shared body, not in the decider, so the deciding word
  is about the two places rather than about the user (*upstream*, not *home* or
  *yours*);
- the deciding word names a relation between the two places, so "upstream" means
  nothing about one place on its own;
- turning it into the answer takes one step of world knowledge: a river carries a
  spill downstream.

The construction is the same template as every family's, because rule 3 requires two
nouns swapping roles in one frame. A reader that locates the overflow site's clause
and knows which words mean upstream (*upper*, *climb*, *headwater*, *first*, *above*,
*set off*, *against the current*, *tops out*) solves the family; that is reading the
decider.

Held to everything v6's new family is (`tests/test_dataset_v7.py`): every moment of
the first thirteen families equals its v6 counterpart; unigram and bigram at 50% on
ten seeds; order-balanced cells; both places on both sides and the overflow site named
first in about half of bodies; the six clause features, and vowel and consonant
counts, at chance; the marker-aware order check; the single-letter gate; the skyline
solves it and the heuristic does not. One check is new: no frame says either place is
the user's (no *you*, *your* or *home*).

**Frames were chosen by search**, as v6's were. The search script was not committed, so
its counts below are the builder's record and cannot be re-run; the scan figures after
them were reproduced in review. 44 candidate frames that meet the
structural rules and read clearly as upstream against downstream of the other place,
searched for a dev set (frames 0-4) and a held-out set (5-7) on which all eight gated
clause features balance exactly (1,740 such sets), then ranked by the strongest of
about 440 cheap clause features (letters, letter pairs and triples, affixes, word
lengths) reading the same way on both splits. Excluded before the search as readable
backwards or unclear: *"Higher ground surrounds"* (a valley village is surrounded by
higher ground), *"Climbing the towpath leads to"* (towpaths are flat), *"Silt settles
later near"*, *"Rainwater drains first past"* and *"Rowing upstream from one finds"*.
On the shipped splits a scan of the 437 such features present finds no rule at 70% on
both; the best reads 60% dev / 83% test (words ending in *t*), and the best on dev
alone 70% dev / 50% test (the letters *low*). As for v5 and v6, that scan informed the
search and is not an independent check. Three further checks were run on the six
top-ranked sets before one was chosen; all six passed them, and the shipped set is the
top-ranked one, so they did not decide the choice. The character 3-8-gram probe (Round
49): on v7 it fits dev at 87.1% and reads 50.6% on held-out test (`river_swim` 50.0%
of 24), and its verdict holds. The letter-count bag (Round 73) reads 66.7% dev→test,
and `river_swim` (v7) reads 43.8% leaving one frame out, p=0.695 against the exact
orientation null. The positional comparisons are below.

**Positional.** The overall 20-seed form that v6 fails passes on v7: 20-seed medians
51.4% against 52.9%, and 60-seed medians 51.96% against 52.32%. On the shipped seed
the overall reading is 53.8% against 52.4%, under the 60% bound. The family itself
reads 72.5% positional on the shipped seed against a null of 57.5% — above 60% on this
seed. Over 60 seeds its median is 57.5% against 57.5%, and 25% of seeds read above 60%
against 25% of null draws, so the shipped seed is one of the quarter that do, at the
null's own rate. The family test compares over 60 seeds, as v5's and v6's do.
Positional is reported, not gated.

**A character naive Bayes reads the held-out frames, at chance against the null**
(R74 review; `experiments/char_nb_probe.py`). The audit's own naive Bayes, fed the
letters of the overflow site's clause and of the other clause, tagged by clause, and fit
on dev, reads `river_swim`'s held-out test at **100.0%** (24 of 24). That is three
frames, and against the exact orientation null it has p=**0.125**, which is the floor
for three frames. Leaving one frame out it reads **62.5%** (p=**0.398**). Trained on
the other thirteen families only, it reads **87.5%** of `river_swim`'s frames
(p=**0.035**). That is the strongest transfer of the fourteen families, and the only one
of the probe's 84 family, representation and reading cells under 0.05; chance alone
gives about four. So `river_swim`'s upstream clauses share letters with other
families' privileged clauses. It is disclosed, not gated; the probe takes minutes per
run.

**Two frames are weaker than the rest.** *"Situated above / below the other on the
river"*: on a map, *above* can mean north. *"Mapped elevation tops out / bottoms out
at"*: the idiom usually takes a quantity, and it works here only because there are two
places. Staying quiet when the overflow is downstream is defensible but not unanimous:
near a river mouth a tide can carry a discharge upstream. Labels are constructed
(`raters: 0`).

All 28 LLM runs are on v7 (Round 75; README, *On dataset v7*).

### Dataset v8 — a fifteenth family, `photo_backup`

`data/v8` is `tactbench build --version v8 --pairs 32 --families 15`: v7 plus one new
family (600 dev / 360 test), from personal data, which none of the fourteen touches.
The user is out for the evening. One shared body signal says a free cloud photo plan
ends at midnight and one of two albums will be deleted, and that the other album is
kept. The decider, a backup report from that morning, says which of the two albums
has a copy somewhere other than the cloud and which does not — *"Retrievable by no
other means is Lisbon. Retrievable by some other means is Kyoto."* Speak when the album
being deleted has no other copy, because midnight loses it for good; stay quiet when it
has one, because nothing is lost. Both albums appear in the shared body and on both
sides, and swap roles. Albums are named after cities, as trip albums usually are, from
a pool of 40 single words, none of which appears in a frame, a body template, or
another family's pool.

**The logical form is the same as every family's.** The decider labels one album, and
given the body that label settles it — the form the R74 review found in all fourteen
earlier families, which rule 3 (two nouns swapping roles in one frame) forces. The
skyline reads it the way it reads `water_notice`: the marker from the body, then the
filling of the privileged template. What the family adds is a domain and a deciding
predicate: whether *any* second copy of the album exists. It is not where something is
now or was (`water_notice`, `street_cleaning`), which way something flows
(`river_swim`), who holds a duty, or what is fragile, congested or unused. Every frame
states it of the album as a whole, not of one device (R76 review, below). No frame says
anything about the deletion, and no frame shares a content word with the body
(`test_the_decider_says_nothing_about_deletion`).

**What the frames test, after the R76 review.** The predicate is stated in several
ways, so a reader has to work out which clause *means* "no other copy": as an absence
(*"Retrievable by no other means"*, *"Lacking any duplicate"*), as a dependence
(*"Restoring needs the online original"*, *"Dependent on a single instance"*), as a
count (*"Copies total one"*), as a consequence (*"Closing the account forfeits all
of"*), and as membership in every backup or none (*"Missing from every backup"* against
*"Missing from no backup"*). A negation word sits on the no-copy side in two frames, on
the copy side in three, and on both or neither in three. So polarity alone reads
exactly half on dev and on held-out frames (gated below). It is still one predicate,
read through ordinary English; no reasoning step beyond "one copy of two lost loses
nothing" is required.

**The first v8 frames were replaced after review.** The adversarial review of the first
build found two defects, and both were fixed rather than disclosed:

- *Polarity decided the family.* Every privileged clause carried a negation (*nowhere*,
  *zero*, *no*, *lacks*, *absent*, *excluded*) and no other clause did. A policy legal
  under rule 1 — generic negation and deletion lexicons, capitalisation, no generator
  phrase (`experiments/negation_probe.py`) — read the family 100% on dev and 24 of 24
  on held-out test, and grafted onto the heuristic moved its test ICS from 612.0 to
  588.0. On the shipped frames it reads 50.0% on both and leaves the ICS at 612.0.
  `test_polarity_does_not_decide_the_family` gates it, and putting the first frames
  back fails it (`test_the_polarity_gate_would_catch_the_first_v8_frames`).
- *Four clauses reported absence at one place only* (*"Office workstation lacks a copy
  of"*, *"Memory stick contains no images from"*, *"Excluded from the weekly snapshot"*,
  *"Server replica absent for"*, and the cloud is itself a server), which does not mean
  no copy exists elsewhere. Every such candidate, 21 in all, was dropped.

**The same probe on the published families** (not gated; the counts are the same on
every version that carries a family). Of each family's eight frames, the number where
"speak iff the marker's clause alone carries a negation" is right, and wrong; the rest
tie: `commerce` 3 right / 0 wrong (70% dev, 67% held-out test; 71% on v1 dev),
`finance` 3/0 (70%, 67%), `health` 2/0 (60%, 67%), `meeting_prep` 2/1 (50%, 67%),
`home_security` 1/0 (60%, 50%), `quiet_hours` 1/0 (50%, 67%), `water_notice` 1/2 (40%,
50%), `deadline` and `driving` 0/2 (40%, 33%: the negated rule reads 60% and 67%),
`pet_care` and `childcare` 0/1, and `travel`, `street_cleaning` and `river_swim` 0/0. No
published family has more than three frames on one side; the first v8 frames had all
eight.

Held to everything v7's new family is (`tests/test_dataset_v8.py`): every moment of
the first fourteen families equals its v7 counterpart; unigram and bigram at 50% on ten
seeds; order-balanced cells; both albums on both sides and the deleted album named
first in about half of bodies; the six clause features, and vowel and consonant counts,
at chance; the marker-aware order check; the single-letter gate; the skyline solves it
and the heuristic does not. New: polarity balances, as above; and the R74 review's
character naive Bayes readings are gated at p ≥ 0.05, one- and two-sided, before
shipping (below).

**Frames were chosen by a committed search**, `experiments/frame_search_v8.py`, so the
counts here re-run (`test_the_frame_search_is_committed_and_reproduces_the_shipped_frames`
asserts that the script still picks the shipped frames and prints these counts). 41
candidate frames that meet the structural rules and state copy status for the album as
a whole, searched for a dev set (frames 0-4) and a held-out set (5-7), lexically
disjoint, on which the eight gated clause features and negation all balance exactly (2
such sets), then ranked by the strongest of 904 cheap clause features (letters, letter
pairs and triples, word prefixes and suffixes, word lengths, word count) reading the
same way on both splits, then on dev alone; the two sets tie, and the order of the
candidate list breaks it. Twelve frames were excluded before the search for clarity,
each with its reason in the script: two about a *sync* (a phone's sync to the cloud
would leave a copy on the phone, so a failed one reads backwards), *"Kept only on the
phone"* (a copy on the phone is a copy), *"Archived once"* (one copy elsewhere is the
other label), four idioms (*"Copies held number one"*, *"Spare drive full of"*, *"all
there is"*, *"short of"*), a colour-coded status light, *"belongs to"*, *"Exposed to
permanent loss"* (states the conclusion, not the fact), and one addressed to *you*,
which is the marker in three other families. On the shipped splits, of the 115 such
features that differ between a frame's clauses, the best reading the same way on both
is the letter *o*: "speak iff the deleted album's clause has fewer" reads 70% dev / 67%
test, just under the single-letter gate's 70%-on-both line. The best on dev alone, the
letter *n*, reads 70% dev and reverses on test. As for v5-v7, that scan informed the
search and is not an independent check. The character 3-8-gram probe (Round 49) did not
inform it; on v8 it fits dev at 87.3% and reads 50.0% on held-out test (`photo_backup`
54.2% of 24), and its verdict holds. The letter-count bag (Round 73) reads 33.3%
dev→test, and `photo_backup` (v8) reads 43.8% leaving one frame out, p=0.688 against
the exact orientation null.

What the family does not resist, as for every family: a reader that locates the
deleted album's clause and knows which of the eight phrasings mean "no other copy"
solves the family — that is reading the decider.

**Character naive Bayes, measured before shipping** (`experiments/char_nb_probe.py`,
the R74 review's probe), fed the characters of the deleted album's clause and of the
other clause, tagged by clause. Two-sided p counts readings as far under a half as over
it, since negating a learner is free; it is the one to read. The one-sided p is R74's
form.

- letters, dev→test: **33.3%** (two-sided p=0.969; one-sided p=0.867)
- letters, leaving one frame out: **37.5%** (two-sided p=0.781; one-sided p=0.738)
- letters, trained on the other fourteen families: **62.5%** (two-sided p=0.727; one-sided p=0.363)
- pairs, dev→test: **50.0%** (two-sided p=1.000; one-sided p=0.750)
- pairs, leaving one frame out: **37.5%** (two-sided p=0.727; one-sided p=0.719)
- pairs, trained on the other fourteen families: **37.5%** (two-sided p=0.727; one-sided p=0.855)

None is under 0.05; dev→test, on three frames, cannot go under 0.125. Transfer now
trains on every other family the version carries, which leaves every v7 reading
unchanged.

**Positional.** The overall 20-seed form passes on v8, as on v7: 20-seed medians 51.4%
against 52.4%, and 60-seed medians 51.83% against 52.33%. On the shipped seed the
overall reading is 52.7% against 52.2%, under the 60% bound. The family itself reads
62.5% positional on the shipped seed against a null of 57.5% — above 60% on this seed.
Over 60 seeds its median is 58.8% against 57.5%, and 37% of seeds read above 60%
against 38% of null draws. The family test compares over 60 seeds, as v5's-v7's do.
Positional is reported, not gated.

**Body order against decider order, on the shipped seed.** "Speak iff the body's first
album is the decider's first album" reads 60.0% on dev and 75.0% on held-out test. Both
orders are drawn independently per pair, so this is chance: over 60 seeds the median is
50% on each split, and 8% of seeds read held-out test at 75% or more either way. The
marker-aware order check (exactly 50% within each label) is unaffected. Disclosed, not
fixed: balancing it needs a change to how the body is drawn.

**Weaker points.** *"Dependent on a single instance"* and *"Restoring needs the online
original"* say the cloud copy is the only one by implication, not in so many words.
Staying quiet when the deleted album has a copy is defensible but not unanimous:
someone might still want to know that the cloud copy is going. The user is at a social
evening (false-positive cost 2.0) and the positive is priced at value 2. Labels are
constructed (`raters: 0`).

All 28 LLM runs are on v8 (Round 77; README, *On dataset v8*).

### Token permutations and the bigram probe

All nine are token permutations: both sides contain the same words, arranged
differently. Every family probes at the 50% chance floor **for the bag-of-words
audit** — which is exactly what a token permutation guarantees, since that probe
cannot see arrangement. An order-aware probe reached **97.2%** in Round 11, and a bag-of-bigrams fit on
`dev` scored **+99.4 versus silence on held-out `test`** — the benchmark was
solvable by surface statistics.

Round 12 blamed decider scarcity and removed it (entities drawn per pair, 4 → 24–38
distinct decider sentences per family). Verbatim overlap fell 91.2% → 29.8% and the
exploit moved **1.3 points**. The frame carries the label, not the entity.

Round 13 held the phrasings out instead. Each family has **eight** decider frames,
and the split is taken **on the frame**:

| | R11 | R12 | **R13** |
|---|---|---|---|
| bigram probe (dev) | 97.2% | 93.5% | **48.9%** |
| held-out deciders published verbatim | 91.2% | 29.8% | **0.0%** |
| dict lookup, no model | 95.6% | 64.9% | **50.0%** |
| bigram on held-out phrasings | 97.5% | 97.5% | **50.9%** |
| **bag-of-bigrams vs silence** (two-sided) | **+99.4** | **+98.1** | **+0.0** |

That was a **near-duplicate leak**, a *different* defect from the pair-key split
fixed in Round 10: that one divided pairs across the boundary, this one repeated
text across it. A split can be perfectly pair-whole and still publish its own
answers. Holding frames out closes it by construction rather than probabilistically.
See `experiments/order_sensitive_probe.py`.

`quiet_hours` was not always in that list. It originally turned on severity —
*admitted* versus *discharged* — and was declared irreducible on the reasoning
that a medical emergency is not a rearrangement of a routine check-in. It probed
at 100% and was exempted from the per-family assertion by name.

**The exemption was the error, not the family.** Because `quiet_hours` carries the
highest false-positive cost in the benchmark, it drove 87% of the gap between
`always` and silence from 11% of the moments (as recorded in Round 9; 81% on `v1` today) — so a policy matching `admitt` /
`discharg` and coin-flipping on the other eight families beat silence, while the
honest structural heuristic did not.

The decider was simply on the wrong axis. Moving the admission into the shared
body and asking *who can actually get there tonight* permutes cleanly and poses a
harder question. If a family looks irreducible, look for a different decider
before granting an exception.

### User state is held constant across a pair

If the positive were set during deep work and its near-miss while idle, state would
give the answer away as surely as vocabulary did. So both sides of a pair carry the
identical `UserState`.

This has a consequence worth stating plainly: **state carries no information about
`should_surface`.** It determines the *cost* of being wrong, not the answer. A
policy that reasons only about activity and DND can avoid hard violations but
cannot do better than chance on whether to speak — which is why every non-skyline
baseline now scores worse than silence.

## How labels are assigned

**v1 labels are by construction.** Each item was built around a known answer rather
than shown to raters afterward. This is a genuine limitation:

- Labels are internally consistent and the rationale is always available.
- They are *unvalidated against what people actually want*. If the author's
  intuitions about interruption cost are wrong, the benchmark encodes those wrong
  intuitions with total confidence.

Items carry `raters: 0` and `agreement: 1.0` to mark this honestly. A
human-labeled subset with reported inter-rater κ is the top roadmap item, and
`raters` / `agreement` exist so that constructed and human-validated items can
coexist in one file and be filtered apart. Since Round 31 `tactbench label` collects
answers (to `labels/<version>-<split>/<rater>.jsonl`) and `tactbench agreement`
reports Fleiss' κ and agreement with construction. None have been collected, so
every item is still `raters: 0`; writing human results back into those fields is
not built yet.

## Base rate

Generation is **50/50** speak / stay-quiet by construction.

This is not realistic. A deployed assistant sees vastly more quiet moments than
loud ones — plausibly 100:1 or worse. Balance is chosen so the near-miss contrast
is legible and so slice-level numbers aren't computed over a handful of items.

To evaluate against a realistic prior, pass `--base-rate`:

```bash
tactbench eval --base-rate 100
```

Every stay-quiet item is importance-weighted by the ratio, so it stands in for the
hundred real quiet moments it represents. Precision is weighted too, and reports
what it would be in production rather than in the artificial split — it collapses
from roughly 0.5 to roughly 0.01.

Silence and the skyline are unaffected, because neither produces a false positive.
Everything else inflates around them, which is exactly why `never` is the reference
baseline and not a curiosity.

Hard violations are deliberately **not** reweighted: they count distinct moments in
the benchmark, not an estimate of production volume, and conflating the two would
make the number mean nothing.

## Splitting

`dev` / `test` are split on the **decider frame** — frames 0–4 train, 5–7 are
held out — giving **252 dev / 108 test**.

Two things about that expression are load-bearing, and each was learned by getting
it wrong.

**Not Python's `hash()`.** String hashing is salted per process, so `hash()` would
reshuffle the split on every run and silently leak test items into dev. The digest
is stable across processes, machines, and Python versions.

**Not the moment id — the *pair* key.** A pair's two sides must always travel
together into the same split. This is not tidiness; it is the difference between
a held-out set and a published one. Both sides share a byte-identical body and an
identical `UserState`, differing only in which noun plays which role, so an
orphaned test item is a near-verbatim copy of a dev item **carrying the opposite
label**.

Round 10 found the split bucketing on `moment.id`, which names an item rather than
a pair. The two halves were therefore assigned independently, and:

| | |
|---|---|
| pairs divided across dev and test | **72 of 180** |
| held-out items whose partner was published in dev | **72 of 94 (77%)** |
| of those, answered by negating the partner's label | **72 of 72** |
| test-split accuracy by table lookup, no model | **88.3%** |

`moment.id` is public, so the pair key is public, so the partner is findable. A
pair has exactly one speak side and one stay-quiet side — reading the partner's
label out of `dev.jsonl` and negating it gave the answer outright. No learning, no
text analysis, nothing that isn't shipped in the repo.

The audit had always kept pairs whole across its own cross-validation folds, with
a comment explaining that splitting one "would let the probe memorize one half and
trivially answer the other." The artifact it was auditing did not. `pair_key` in
`schema.py` is now the single definition, used by both.

`TestSplitIntegrity` enforces this on the generator *and* on the shipped `.jsonl`
files, and asserts that partner-lookup recovers nothing.

`n_pairs_per_scenario` must be at least **16** (`MIN_PAIRS_FOR_BALANCED_ORDER`,
two per frame) for clause order to balance. Below it, 54 of 72 (family, frame)
cells carry a single order and a position-tagged probe separates the set at ~74%.
Small sizes remain useful for structural tests; they are not valid for measuring
leakage.

Regeneration with the same seed reproduces both splits exactly.

## Extending it

Add a `Scenario` subclass in `src/tactbench/dataset/generate.py` (a `state`, a
shared `body`, `fillers` and `why`; frames under its family name). **Append** it to
`LATER_SCENARIOS` with its frames in `LATER_FRAMES`, and build a new dataset version
with `--families`; never insert into `SCENARIOS`, which would change every published
version. `pet_care` (Round 45) is the worked example. The test suite
enforces the invariants that make the benchmark meaningful:

- every family contributes both a positive and a near-miss
- every near-miss is tagged `near_miss` for slicing
- every positive names at least one acceptable intent
- generation is deterministic under a fixed seed
- the reference heuristic does not score perfectly (headroom must exist)

## Known weaknesses

- **Nine families is nine degrees of freedom (ten in `v3`, eleven in `v4`, twelve in `v5`, thirteen in `v6`, fourteen in `v7`, fifteen in `v8`).** Every family has the same logical form (see the v7 and v8 sections); more families add domains and deciding predicates, not decision shapes. Phrasing is no longer the weak point —
  the unigram audit confirms *vocabulary* doesn't carry the answer, though word
  **order** does (see above) — but the *scenarios*
  are still a small hand-authored set. Item count overstates diversity. More
  families is the highest-value expansion.
- **Cost is concentrated in `quiet_hours`** — 81% of the `always`-vs-silence gap
  from 11% of moments on `v1`, 68% from 8% on `v5` (87% as recorded in Round 9), because a false positive while asleep under DND is the most
  expensive error priced. Deliberate, but it makes the headline sensitive to how
  that one family is written.
- **Character features transfer into `river_swim`.** A character naive Bayes trained on
  the other thirteen families reads 87.5% of its frames (p=0.035 against the exact
  null, the only one of 84 cells under 0.05; see the v7 section).
- **Negation polarity leans in five published families, none beyond chance.** "Speak
  iff the marker's clause alone carries a negation word" (`experiments/negation_probe.py`)
  reads each frame right, wrong or tied. `commerce` and `finance` lean three frames to
  none (p=0.250 each); `health` two to none and `deadline` and `driving` none to two
  (p=0.500). Swapping which clause of a frame is privileged swaps right and wrong, so
  the exact null is a fair coin over the untied frames, two-sided (Round 78,
  `tests/test_polarity_null.py`). All 93 family-version cells pass at 5%, and the
  lowest p is 0.25: with only three untied frames, even three to none cannot go lower.
  So the leans are recorded, not regenerated. Eight to none, as v8's first
  `photo_backup` frames had, gives p=1/128; v8 also gates that family to balance
  exactly.
- **Letter-count combinations sit near the gate's line in one family.** A weighted bag
  of letter counts fit on dev reads held-out `home_security` (v4) at 83.3% and
  `street_cleaning` (v6) at 100.0%. Against the exact orientation null (Round 73)
  neither is significant: p=0.070 and p=0.430. `home_security` is the closest of the
  fifteen families to the 5% line (`photo_backup`, v8: p=0.688).
- **Independent moments.** Real interruption cost depends on how recently the user
  was last interrupted. Modeling fatigue requires session-level items.
- **Western, knowledge-worker, English-only.** The scenarios assume a particular
  working life. Interruption norms are culturally specific and this captures one
  culture's.
- **No adversarial authorship.** Every item was written by the same person who
  wrote the baselines. External contributions of near-miss pairs are the highest-
  value thing an outside contributor can add.

## License

Dataset content is CC BY 4.0. Code is MIT.
