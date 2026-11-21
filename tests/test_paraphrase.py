"""A paraphrased slice of v2, for measuring whether decisions survive rewording.
Round 42, queue item L (CLAUDE.md priority 3, restated in R41).

Each family gets one new frame with a different sentence shape. ``reword`` keeps a
moment's body, state, label and id and re-renders only its decider through the new
frame, with the same fillers in the same clause order -- so the facts and the roles
are unchanged and a decision on the reworded moment pairs with the decision on the
original by id.
"""

from __future__ import annotations

from collections import defaultdict

import pytest
from test_metrics import TestFrameDisjointness

from tactbench.audit import lexical_leakage, ngram_leakage
from tactbench.dataset.generate import FRAMES, WHO, skeleton
from tactbench.dataset.loader import load
from tactbench.dataset.paraphrase import PARAPHRASE_FRAMES, build, reword
from tactbench.schema import pair_key

STOP = TestFrameDisjointness.STOP


def _before_slot(clause):
    head = clause.split(WHO)[0].split()
    return head[-1].lower() if head else None


@pytest.mark.parametrize("family", sorted(FRAMES))
def test_paraphrase_frames_hold_the_prose_properties(family):
    """The three R16 properties plus equal skeletons, as for the shipped frames."""
    a, b = PARAPHRASE_FRAMES[family]
    for clause in (a, b):
        assert clause.count(WHO) == 1 and _before_slot(clause) is not None
        assert skeleton(clause)[0].lower().strip(".,") not in STOP, clause
    assert len(skeleton(a)) == len(skeleton(b))
    assert _before_slot(a) == _before_slot(b)


@pytest.mark.parametrize("family", sorted(FRAMES))
def test_paraphrase_frames_are_new_wording(family):
    assert PARAPHRASE_FRAMES[family] not in FRAMES[family]


def test_reword_changes_only_the_decider():
    originals = {i.moment.id: i for i in load("v2", "dev")}
    for new in load("v2para", "dev"):
        item = originals[new.moment.id]
        assert reword(item).model_dump() == new.model_dump()
        assert new.moment.id == item.moment.id and new.label == item.label
        assert new.moment.user_state == item.moment.user_state
        assert new.moment.signals[:-1] == item.moment.signals[:-1]
        assert new.moment.signals[-1].content != item.moment.signals[-1].content


def test_reworded_pairs_are_still_permutations():
    pairs = defaultdict(list)
    for item in build():
        pairs[pair_key(item.moment.id)].append(item.moment.signals[-1].content)
    assert len(pairs) == 36
    for key, (a, b) in pairs.items():
        assert sorted(a.split()) == sorted(b.split()), key


@pytest.mark.parametrize("family", sorted(FRAMES))
def test_gated_probes_at_chance_on_the_reworded_set(family):
    sub = [i for i in build() if i.moment.family == family]
    assert lexical_leakage(sub).exploitable_accuracy == pytest.approx(0.5)
    assert ngram_leakage(sub).exploitable_accuracy == pytest.approx(0.5)


def test_the_committed_set_is_reproducible():
    assert [i.model_dump() for i in load("v2para", "dev")] == [i.model_dump() for i in build()]
