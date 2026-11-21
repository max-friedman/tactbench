"""The local viewer. Untested until Round 34, and still showing only `vs silence`
since Round 24 added the pair-blind bar everywhere else. Tested on `v1/dev` only until
Round 59, whose page also never said which dataset version it showed."""

from __future__ import annotations

import json
import re
import threading
import urllib.request
from functools import partial
from http.server import HTTPServer

import pytest

from tactbench.dataset.loader import DATA_ROOT, load
from tactbench.policies.builtin import registry
from tactbench.runner import evaluate, normalized, pair_blind_ics, silence_ics
from tactbench.web.server import PAGE, _Handler, build_payload

#: Every dataset on disk and its splits. v2para (R42) is a reworded dev slice only.
CASES = [(v, s) for v in ("v1", "v2", "v3", "v4", "v5") for s in ("dev", "test")]
CASES.append(("v2para", "dev"))


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


def test_every_dataset_on_disk_is_covered():
    on_disk = {
        (d.name, f.stem) for d in DATA_ROOT.iterdir() if d.is_dir() for f in d.glob("*.jsonl")
    }
    assert on_disk == set(CASES)


def test_the_payload_names_its_version_and_split(case):
    version, split, payload = case
    assert payload["version"] == version and payload["split"] == split


def test_the_payload_carries_every_family(case):
    """The payload, not the page: no element renders ``family`` yet (the id's prefix
    shows it)."""
    version, split, payload = case
    families = {i.moment.family for i in load(version, split)}
    shown = {m["family"] for m in payload["moments"]}
    assert shown == families and len(payload["moments"]) == payload["n"]


def test_the_served_header_names_the_dataset(case):
    """The exact line a person reads, recomputed from ``eval``'s own numbers, in the
    served page; and the page's script sets the header from that field and nothing
    else."""
    version, split, payload = case
    items = load(version, split)
    expected = (
        f"dataset {version} · {len(items)} moments · {split} split · "
        f"silence ICS {silence_ics(items):.1f} · pair-blind ICS {pair_blind_ics(items):.1f}"
    )
    assert payload["header"] == expected
    html = _serve_once(payload)
    assert json.dumps(expected) in html
    assert "document.getElementById('meta').textContent = DATA.header;" in PAGE
    assert PAGE.count("getElementById('meta')") == 1


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


#: The payload's text fields (everything else on the page is a number or a boolean).
TEXT_FIELDS = ("policy", "id", "state", "source", "content", "rationale")
#: The only places a text field may appear outside ``esc(...)``: DOM properties that
#: never parse HTML, and lookups.
SAFE_USES = (
    "o.value = r.policy",
    "o.textContent = r.policy",
    "DATA.board[0].policy",
)


def _unescaped_text_uses(page: str) -> list[str]:
    """Every ``x.<text field>`` in the page's script that is neither wrapped in
    ``esc(...)`` nor a known safe use. Slices are iterated as bare ``s`` in a map, so
    the badge's concatenation is checked separately."""
    script = page.split("<script>")[1].split("</script>")[0]
    bad = []
    for match in re.finditer(r"\b(\w+)\.(" + "|".join(TEXT_FIELDS) + r")\b", script):
        start = match.start()
        if script[start - 4 : start] == "esc(":
            continue
        line = script[script.rfind("\n", 0, start) + 1 : script.find("\n", start)]
        if any(use in line for use in SAFE_USES) and match.group(0) in "".join(SAFE_USES):
            continue
        bad.append(line.strip())
    if "'<span class=\"badge\">' + esc(s) +" not in script:
        bad.append("slice badge")
    return bad


def test_every_text_field_is_escaped_before_innerHTML():
    """R60: five text fields (policy, id, state, slice, source) went into innerHTML
    raw, and planted markup in any of them ran in Chromium. Browser-free: the script
    may use a text field only through ``esc`` or a property that never parses HTML."""
    assert _unescaped_text_uses(PAGE) == []
    assert '"' in PAGE.split("function esc")[1].split("}")[0]  # quotes escaped too


@pytest.mark.parametrize("field", ["r.policy", "m.id", "m.state", "s.source", "m.rationale"])
def test_the_escape_check_catches_a_raw_field(field):
    assert _unescaped_text_uses(PAGE.replace(f"esc({field})", field, 1)), field


def test_the_escape_check_catches_a_raw_slice():
    assert _unescaped_text_uses(PAGE.replace("esc(s) +", "s +", 1))
