"""Can held-out test labels be hidden? Round 33 (CLAUDE.md priority 4).

Priority 4 asked for "held-out test labels hidden behind a submission script so the
leaderboard resists overfitting". Two measurements say hiding the label file cannot
do that while the generator is public:

1. **The file is reproducible.** ``tactbench build`` regenerates ``data/v1/test.jsonl``
   byte-for-byte from public code and seed (CI's "dataset is reproducible" job
   already asserts it), so every hidden label is recoverable.
2. **A secret seed does not help either.** The labels follow from the decider
   *templates*, which are public. ``SkylinePolicy`` -- a parser built only from those
   templates, never shown a label -- scores ICS 0.0 on the held-out frames of splits
   built from seeds it has never seen.

3. **Private held-out templates would work.** Simulated by giving the same parser
   only the public frames (0-4): on the held-out frames it scores exactly what
   silence scores -- it parses nothing -- on every seed tried. Review of Round 33
   ran this first; the round had dismissed the design without measuring it.

So a held-out set resists a template parser if its *frames* are private -- written
fresh (frames 5-7 are already in git history) and kept with whoever hosts scoring.
That is a custody decision for the owner, not code.

    uv run python experiments/hidden_labels_probe.py
"""

from __future__ import annotations

import tactbench.policies.skyline as skyline
from tactbench.dataset.generate import FRAMES, HELD_OUT_FRAMES, generate
from tactbench.dataset.loader import load
from tactbench.policies.builtin import NeverPolicy
from tactbench.policies.skyline import SkylinePolicy
from tactbench.runner import evaluate
from tactbench.schema import frame_of

SHIPPED_SEED = 20260726
UNSEEN_SEEDS = (1, 42, 777, 123456, 99999999)


def held_out(seed: int):
    items = generate(n_pairs_per_scenario=20, seed=seed)
    return [i for i in items if frame_of(i.moment) in HELD_OUT_FRAMES]


def public_frames_only() -> dict:
    """The parser's view if the held-out frames were private."""
    return {
        family: [t for k, t in enumerate(frames) if k not in HELD_OUT_FRAMES]
        for family, frames in FRAMES.items()
    }


def main() -> None:
    committed = load("v1", "test")
    rebuilt = held_out(SHIPPED_SEED)
    same = [i.model_dump() for i in committed] == [i.model_dump() for i in rebuilt]
    print(f"test split rebuilt from public code: {len(rebuilt)} items, identical: {same}")
    for seed in UNSEEN_SEEDS:
        card = evaluate(SkylinePolicy(), held_out(seed))
        hv = card.hard_violations
        print(f"unseen seed {seed:>9}: template parser ICS {card.ics:.1f}, hard viol. {hv}")
    skyline.FRAMES = public_frames_only()
    try:
        for seed in (SHIPPED_SEED, *UNSEEN_SEEDS[:2]):
            items = held_out(seed)
            card = evaluate(SkylinePolicy(), items)
            never = evaluate(NeverPolicy(), items).ics
            print(
                f"private frames, seed {seed:>9}: parser ICS {card.ics:.1f} (silence {never:.1f})"
            )
    finally:
        skyline.FRAMES = FRAMES


if __name__ == "__main__":
    main()
