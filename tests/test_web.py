"""The local viewer. Untested until Round 34, and still showing only `vs silence`
since Round 24 added the pair-blind bar everywhere else. Tested on `v1/dev` only until
Round 59, whose page also never said which dataset version it showed."""

from __future__ import annotations

import threading
import urllib.request
from functools import partial
from http.server import HTTPServer

import pytest

from tactbench.dataset.loader import DATA_ROOT, load
from tactbench.policies.builtin import registry
from tactbench.runner import evaluate, normalized, pair_blind_ics, silence_ics
from tactbench.web.server import PAGE, _Handler, build_payload

VERSIONS = ["v1", "v2", "v3", "v4", "v5"]
CASES = [(v, s) for v in VERSIONS for s in ("dev", "test")]


@pytest.fixture(scope="module", params=CASES, ids=lambda c: f"{c[0]}-{c[1]}")
def case(request):
    version, split = request.param
    return version, split, build_payload(load(version, split), split, version)


@pytest.fixture(scope="module")
def payload(case):
    return case[2]


def _serve_once(payload) -> str:
    server = HTTPServer(("127.0.0.1", 0), partial(_Handler, payload=payload))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}/"
        return urllib.request.urlopen(url, timeout=10).read().decode()  # noqa: S310
    finally:
        server.shutdown()


def test_every_version_is_covered():
    assert (
        sorted(
            p.name for p in DATA_ROOT.iterdir() if p.name.startswith("v") and p.name[1:].isdigit()
        )
        == VERSIONS
    )


def test_the_payload_names_its_version_and_split(case):
    version, split, payload = case
    assert payload["version"] == version and payload["split"] == split


def test_every_family_has_moments_on_the_page(case):
    version, split, payload = case
    families = {i.moment.family for i in load(version, split)}
    shown = {m["family"] for m in payload["moments"]}
    assert shown == families and len(payload["moments"]) == payload["n"]


def test_the_page_says_which_version_it_shows(case):
    version, split, payload = case
    html = _serve_once(payload)
    assert "DATA.version" in PAGE
    assert f'"version": "{version}"' in html


def test_the_board_matches_eval(case):
    version, split, payload = case
    items = load(version, split)
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


def test_decisions_are_keyed_by_the_stored_id(case):
    version, split, payload = case
    ids = {i.moment.id for i in load(version, split)}
    for m in payload["moments"]:
        assert m["id"] in ids
        assert set(m["decisions"]) == {p.name for p in registry().values()}


def test_the_page_shows_the_pair_blind_column(payload):
    html = _serve_once(payload)
    assert "vs pair-blind" in html and "vs silence" in html
    assert "__DATA__" not in html and '"vs_pair_blind"' in html
    assert "vs pair-blind" in PAGE
