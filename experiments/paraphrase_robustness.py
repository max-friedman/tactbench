"""Do model decisions survive rewording? Round 42, queue item L.

``data/v2para/dev.jsonl`` is v2 dev's frame-0 slice (36 pairs, 72 moments) with each
decider re-rendered through a paraphrase frame: same facts, same roles, same clause
order, same id. For every committed run on it this compares each decision with the
same model's decision on the original v2 moment:

- **flips**: moments whose speak/stay-quiet decision changed;
- **independent**: the flips expected if the two decisions were unrelated at the same
  speak rates, ``p_o (1 - p_p) + p_p (1 - p_o)`` per moment summed -- a model whose
  flips approach this is reacting to wording, not to the moment;
- ICS on the 72 moments, original vs reworded, against the same gold labels.

    uv run python experiments/paraphrase_robustness.py
"""

from __future__ import annotations

from tactbench.dataset.loader import load
from tactbench.metrics import score
from tactbench.results import load_results


def main() -> None:
    para = load("v2para", "dev")
    ids = {i.moment.id for i in para}
    original_items = [i for i in load("v2", "dev") if i.moment.id in ids]
    para_runs = load_results("v2para")
    v2_runs = load_results("v2")
    print(f"{'run':<26} {'flips':>6} {'indep.':>7} {'spoke o/p':>10} {'ICS o':>6} {'ICS p':>6}")
    for name in sorted(para_runs):
        orig = {d.moment_id: d for d in v2_runs[name] if d.moment_id in ids}
        new = {d.moment_id: d for d in para_runs[name]}
        flips = sum(orig[m].surface != new[m].surface for m in ids)
        p_o = sum(orig[m].surface for m in ids) / len(ids)
        p_p = sum(new[m].surface for m in ids) / len(ids)
        independent = len(ids) * (p_o * (1 - p_p) + p_p * (1 - p_o))
        ics_o = score(original_items, list(orig.values()), name).ics
        ics_p = score(para, list(new.values()), name).ics
        spoke = f"{round(p_o * len(ids))}/{round(p_p * len(ids))}"
        print(f"{name:<26} {flips:>6} {independent:>7.1f} {spoke:>10} {ics_o:>6.1f} {ics_p:>6.1f}")


if __name__ == "__main__":
    main()
