"""The local viewer. Untested until Round 34, and still showing only `vs silence`
since Round 24 added the pair-blind bar everywhere else."""

from __future__ import annotations

import threading
import urllib.request
from functools import partial
from http.server import HTTPServer

import pytest

from tactbench.dataset.loader import load
from tactbench.policies.builtin import registry
from tactbench.runner import evaluate, normalized, pair_blind_ics, silence_ics
from tactbench.web.server import PAGE, _Handler, build_payload


@pytest.fixture(scope="module")
def payload():
    return build_payload(load("v1", "dev"), "dev")


def test_the_board_matches_eval(payload):
    items = load("v1", "dev")
    silence, bar = silence_ics(items), pair_blind_ics(items)
    rows = {r["policy"]: r for r in payload["board"]}
    assert set(rows) == {p.name for p in registry().values()}
    for policy in registry().values():
        card = evaluate(policy, items, reference=silence)
        row = rows[policy.name]
        assert row["ics"] == card.ics
        assert row["normalized"] == pytest.approx(card.ics_normalized)
        assert row["vs_pair_blind"] == pytest.approx(normalized(card.ics, bar))
    assert payload["pair_blind"] == bar and payload["silence"] == silence


def test_decisions_are_keyed_by_the_stored_id(payload):
    ids = {i.moment.id for i in load("v1", "dev")}
    for m in payload["moments"]:
        assert m["id"] in ids
        assert set(m["decisions"]) == {p.name for p in registry().values()}


def test_the_page_shows_the_pair_blind_column(payload):
    server = HTTPServer(("127.0.0.1", 0), partial(_Handler, payload=payload))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}/"
        html = urllib.request.urlopen(url, timeout=10).read().decode()  # noqa: S310
    finally:
        server.shutdown()
    assert "vs pair-blind" in html and "vs silence" in html
    assert "__DATA__" not in html and '"vs_pair_blind"' in html
    assert "vs pair-blind" in PAGE
