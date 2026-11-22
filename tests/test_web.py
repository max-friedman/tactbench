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
CASES = [
    (v, s) for v in ("v1", "v2", "v3", "v4", "v5", "v6", "v7", "v8", "v9") for s in ("dev", "test")
]
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


#: Every string-valued key in the payload. Numbers and booleans are validated by the
#: schema (``local_hour: int`` rejects markup) and cannot carry a tag.
TEXT_FIELDS = (
    "policy", "id", "state", "source", "content", "rationale",
    "family", "slices", "header", "version", "split",
)  # fmt: skip
#: The only script lines that may read a text field outside ``esc(...)``, verbatim:
#: each writes through a property that never parses HTML, or only compares.
SAFE_LINES = {
    "document.getElementById('meta').textContent = DATA.header;",
    "o.value = r.policy; o.textContent = r.policy;",
    "policySel.value = DATA.board[0].policy;",
    "DATA.moments.forEach(function (m) { m.slices.forEach(function (s) { slices.add(s); }); });",
    "o.value = s; o.textContent = s;",
    "if (slice && m.slices.indexOf(slice) === -1) return false;",
    "m.slices.map(function (s) { return '<span class=\"badge\">' + esc(s) + '</span>'; })"
    ".join('') +",
}
#: The two HTML sinks the page uses, by the line that opens each; no other is allowed.
SINK_LINES = {
    "board.innerHTML =",
    "document.getElementById('list').innerHTML = rows.map(function (m) {",
}
ESC = """function esc(s) {
  return String(s).replace(/[&<>"']/g, function (c) {
    return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
  });
}"""
_FIELD = "|".join(TEXT_FIELDS)
_DOT = re.compile(r"\.\s*(" + _FIELD + r")\b")
_BRACKET = re.compile(r"\[\s*['\"`](" + _FIELD + r")['\"`]\s*\]")
_DESTRUCTURE = re.compile(r"\b(?:const|let|var)\s*\{[^}]*\b(" + _FIELD + r")\b[^}]*\}")


def _expression_start(line: str, end: int) -> int:
    """Walk back from a field access over the expression it belongs to: names, dots,
    and balanced ``[...]`` indexes, e.g. ``m.signals[0].content``."""
    i = end
    while i > 0:
        c = line[i - 1]
        if c.isalnum() or c in "_$.":
            i -= 1
        elif c == "]":
            depth = 0
            while i > 0:
                i -= 1
                depth += {"]": 1, "[": -1}.get(line[i], 0)
                if depth == 0:
                    break
        else:
            break
    return i


def _unescaped_text_uses(page: str) -> list[str]:
    """Every way the page's script could put a text field into HTML unescaped.

    An allowlist, not a pattern match on today's code: outside ``SAFE_LINES``, every
    read of a text field -- by dot, bracket, index chain, or destructuring -- must be
    the whole argument of ``esc(``; the only HTML sinks are the two known
    ``innerHTML`` writes; and ``esc`` must be exactly the function above. R60's first
    check exempted any line containing a safe use and read four characters before
    the match; review got twelve real injections past it."""
    script = page.split("<script>")[1].split("</script>")[0]
    bad = []
    if script.count(ESC) != 1:
        bad.append("esc() is not the reviewed definition")
    script = script.replace(ESC, "")
    for raw in script.splitlines():
        line = raw.strip()
        if not line or line.startswith("//"):
            continue
        for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write"):
            if sink in line and line not in SINK_LINES:
                bad.append(f"sink: {line}")
        if line in SAFE_LINES:
            continue
        if _BRACKET.search(line) or _DESTRUCTURE.search(line):
            bad.append(f"indirect: {line}")
        for match in _DOT.finditer(line):
            start = _expression_start(line, match.start())
            before = line[:start]
            ok = before.endswith("esc(") and not (
                len(before) > 4 and (before[-5].isalnum() or before[-5] in "_$")
            )
            if not ok or not line[match.end() :].startswith(")"):
                bad.append(f"raw: {line}")
    return bad


def test_every_text_field_is_escaped_before_innerHTML():
    """R60: five text fields went into innerHTML raw. Browser-free, and an
    allowlist: see ``_unescaped_text_uses``."""
    assert _unescaped_text_uses(PAGE) == []


#: Each of these reintroduces an injection (or weakens ``esc``) and must be caught.
#: The first five are R60's own un-escapings; the rest are the twelve that got past
#: R60's first check in review.
MUTATIONS = {
    "raw policy": ("esc(r.policy)", "r.policy"),
    "raw id": ("esc(m.id)", "m.id"),
    "raw state": ("esc(m.state)", "m.state"),
    "raw source": ("esc(s.source)", "s.source"),
    "raw rationale": ("esc(m.rationale)", "m.rationale"),
    "raw slice badge": ("esc(s) + '</span>'", "s + '</span>'"),
    "innerHTML on a safe line": (
        "o.value = r.policy; o.textContent = r.policy;",
        "o.value = r.policy; o.textContent = r.policy; o.innerHTML = r.policy;",
    ),
    "bracket access": ("esc(m.id)", "m['id']"),
    "indexed chain": ("esc(m.rationale)", "m.signals[0].content"),
    "destructuring": ("const d = m.decisions[p];", "const d = m.decisions[p]; const {id} = m;"),
    "raw slices join": ("esc(m.rationale)", "m.slices.join(' ')"),
    "raw family": ("esc(m.rationale)", "m.family"),
    "raw slice in the select": ("o.value = s; o.textContent = s;", "o.value = s; o.innerHTML = s;"),
    "header as innerHTML": (".textContent = DATA.header;", ".innerHTML = DATA.header;"),
    "look-alike escape": ("esc(m.id)", "noesc(m.id)"),
    "esc keeps quotes": ("'\"': '&quot;', ", ""),
    "esc returns early": ("function esc(s) {\n", 'function esc(s) {\n  return s; // "\n'),
    "insertAdjacentHTML": (
        "function fmt(x)",
        "board.insertAdjacentHTML('beforeend', DATA.moments[0].rationale);\nfunction fmt(x)",
    ),
    "escape only part": ("esc(m.id)", "esc(m.id).trim() + m.id"),
}


@pytest.mark.parametrize("name", sorted(MUTATIONS))
def test_the_escape_check_catches(name):
    old, new = MUTATIONS[name]
    assert PAGE.count(old) >= 1, f"{name}: mutation target missing"
    assert _unescaped_text_uses(PAGE.replace(old, new, 1)), name


def test_the_embedded_payload_cannot_leave_its_script_block():
    """R60 review: rewriting only ``</`` let ``<!--<script>`` in a field blank the
    viewer. Every ``<``, ``>``, ``&`` is now a JSON escape, and the value survives."""
    payload = build_payload(load("v1", "dev"), "dev", "v1")
    payload["moments"][0]["rationale"] = "<!--<script></script>-->& done"
    html = _serve_once(payload)
    blob = html.split("const DATA = ", 1)[1].split(";\n", 1)[0]
    assert not set(blob) & set("<>&")
    assert json.loads(blob) == payload
    assert html.count("<script>") == 1 and html.count("</script>") == 1
