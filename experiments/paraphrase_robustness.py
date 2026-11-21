"""Do model decisions survive rewording? Round 42, queue item L.

``data/v2para/dev.jsonl`` is v2 dev's frame-0 slice (36 pairs, 72 moments) with each
decider re-rendered through a paraphrase frame: same facts, same roles, same clause
order, same id. For every committed run on it this compares each decision with the
same model's decision on the original v2 moment (``results.paraphrase_robustness``):

- **flips**: moments whose speak/stay-quiet decision changed;
- **indep.**: the flips expected if the two decisions were unrelated at the same
  speak rates -- a model whose flips approach this is reacting to wording;
- **pairs o/p**: pairs answered right on both sides, original vs reworded -- the
  check that consistency is not just ignoring the decider (a constant policy flips
  nothing and scores 0 here);
- **same o/p**: pairs given the same decision on both sides -- the decider did not
  move the decision;
- ICS on the 72 moments, original vs reworded, against the same gold labels.

    uv run python experiments/paraphrase_robustness.py
"""

from __future__ import annotations

from tactbench.results import paraphrase_robustness


def main() -> None:
    rows = paraphrase_robustness()
    print(
        f"{'run':<26} {'flips':>6} {'indep.':>7} {'spoke o/p':>10} "
        f"{'pairs o/p':>10} {'same o/p':>9} {'ICS o':>6} {'ICS p':>6}"
    )
    for r in rows:
        spoke = f"{r.spoke_original}/{r.spoke_reworded}"
        pairs = f"{round(r.pairs_original * 36)}/{round(r.pairs_reworded * 36)}"
        same = f"{r.same_original}/{r.same_reworded}"
        tag = "  constant" if r.constant else ""
        print(
            f"{r.policy:<26} {r.flips:>6} {r.independent:>7.1f} {spoke:>10} "
            f"{pairs:>10} {same:>9} {r.ics_original:>6.1f} {r.ics_reworded:>6.1f}{tag}"
        )


if __name__ == "__main__":
    main()
