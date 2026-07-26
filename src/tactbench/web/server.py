"""Local viewer.

A benchmark that only emits a number is hard to trust and hard to improve. This
serves a single self-contained page showing the leaderboard, then every moment
with the gold label beside each policy's decision -- filterable down to just the
failures, which is where the benchmark stops being a score and starts being an
argument.

Deliberately stdlib-only, so ``tactbench serve`` works from a bare install with no
extra dependencies.
"""

from __future__ import annotations

import json
import webbrowser
from functools import partial
from http.server import BaseHTTPRequestHandler, HTTPServer

from ..dataset.loader import load
from ..metrics import Scorecard
from ..policies.builtin import registry
from ..runner import evaluate, run_policy, silence_ics
from ..schema import Item

PAGE = """<!doctype html>
<meta charset="utf-8">
<title>TactBench viewer</title>
<style>
  :root {
    --bg:#fbfbfa; --fg:#1a1a19; --muted:#6b6b66; --line:#e4e4e0;
    --card:#fff; --good:#1a7f4b; --bad:#b42318; --warn:#b25e09; --accent:#3b5bdb;
  }
  @media (prefers-color-scheme: dark) {
    :root { --bg:#16161a; --fg:#e8e8e6; --muted:#9a9a94; --line:#2c2c33;
            --card:#1e1e24; --good:#4ade80; --bad:#f87171; --warn:#fbbf24;
            --accent:#8ba3f7; }
  }
  * { box-sizing:border-box }
  body { margin:0; padding:2rem 1.25rem 4rem; background:var(--bg); color:var(--fg);
         font:15px/1.55 ui-sans-serif,-apple-system,"Segoe UI",sans-serif;
         max-width:960px; margin-inline:auto }
  h1 { font-size:1.4rem; margin:0 0 .25rem }
  .sub { color:var(--muted); margin:0 0 2rem }
  table { border-collapse:collapse; width:100%; font-variant-numeric:tabular-nums }
  th,td { text-align:right; padding:.5rem .6rem; border-bottom:1px solid var(--line) }
  th:first-child,td:first-child { text-align:left }
  th { font-weight:600; color:var(--muted); font-size:.82rem; text-transform:uppercase;
       letter-spacing:.04em }
  .good { color:var(--good) } .bad { color:var(--bad) } .warn { color:var(--warn) }
  .controls { display:flex; gap:.6rem; flex-wrap:wrap; margin:2.5rem 0 1rem;
              align-items:center }
  select,button { font:inherit; padding:.35rem .6rem; border:1px solid var(--line);
                  border-radius:6px; background:var(--card); color:var(--fg) }
  .card { background:var(--card); border:1px solid var(--line); border-radius:10px;
          padding:.9rem 1rem; margin-bottom:.7rem }
  .card.err { border-color:var(--bad) }
  .row { display:flex; justify-content:space-between; gap:1rem; align-items:baseline;
         flex-wrap:wrap }
  .id { font-family:ui-monospace,SFMono-Regular,monospace; font-size:.82rem;
        color:var(--muted) }
  .badge { display:inline-block; font-size:.72rem; padding:.1rem .45rem;
           border:1px solid var(--line); border-radius:99px; color:var(--muted);
           margin-left:.3rem }
  .sig { margin:.45rem 0 0; padding-left:.8rem; border-left:2px solid var(--line);
         font-size:.9rem }
  .sig b { color:var(--muted); font-weight:500; font-size:.78rem;
           text-transform:uppercase; letter-spacing:.03em }
  .verdict { margin-top:.6rem; font-size:.88rem }
  .why { color:var(--muted); font-size:.85rem; margin-top:.35rem; font-style:italic }
  .wrap { overflow-x:auto }
</style>
<h1>TactBench</h1>
<p class="sub">Should the assistant speak at all? — <span id="meta"></span></p>
<div class="wrap"><table id="board"></table></div>
<div class="controls">
  <select id="policy"></select>
  <select id="filter">
    <option value="errors">Failures only</option>
    <option value="all">All moments</option>
  </select>
  <select id="slice"><option value="">Every slice</option></select>
  <span id="count" class="id"></span>
</div>
<div id="list"></div>
<script>
const DATA = __DATA__;

const board = document.getElementById('board');
board.innerHTML =
  '<tr><th>policy</th><th>ICS ↓</th><th>vs silence</th><th>prec@int ↑</th>' +
  '<th>recall-hv ↑</th><th>ECE ↓</th><th>hard viol. ↓</th><th>spoke</th></tr>' +
  DATA.board.map(function (r) {
    const cls = r.normalized > 0 ? 'good' : 'bad';
    const sign = r.normalized > 0 ? '+' : '';
    const v = r.violations ? '<span class="bad">' + r.violations + '</span>' : '0';
    return '<tr><td><b>' + r.policy + '</b></td><td>' + r.ics.toFixed(1) +
      '</td><td class="' + cls + '">' + sign + r.normalized.toFixed(1) +
      '</td><td>' + fmt(r.precision) + '</td><td>' + fmt(r.recall) +
      '</td><td>' + r.ece.toFixed(3) + '</td><td>' + v +
      '</td><td>' + r.surfaced + '/' + r.n + '</td></tr>';
  }).join('');

function fmt(x) { return x === null ? '—' : x.toFixed(3); }

document.getElementById('meta').textContent =
  DATA.n + ' moments · ' + DATA.split + ' split · silence ICS ' +
  DATA.silence.toFixed(1);

const policySel = document.getElementById('policy');
DATA.board.forEach(function (r) {
  const o = document.createElement('option');
  o.value = r.policy; o.textContent = r.policy;
  policySel.appendChild(o);
});
policySel.value = DATA.board[0].policy;

const slices = new Set();
DATA.moments.forEach(function (m) { m.slices.forEach(function (s) { slices.add(s); }); });
const sliceSel = document.getElementById('slice');
Array.from(slices).sort().forEach(function (s) {
  const o = document.createElement('option');
  o.value = s; o.textContent = s;
  sliceSel.appendChild(o);
});

function render() {
  const p = policySel.value;
  const mode = document.getElementById('filter').value;
  const slice = sliceSel.value;

  const rows = DATA.moments.filter(function (m) {
    const d = m.decisions[p];
    if (slice && m.slices.indexOf(slice) === -1) return false;
    if (mode === 'errors' && d.cost === 0) return false;
    return true;
  });

  document.getElementById('count').textContent =
    rows.length + ' shown of ' + DATA.moments.length;

  document.getElementById('list').innerHTML = rows.map(function (m) {
    const d = m.decisions[p];
    const bad = d.cost > 0;
    const said = d.surface ? 'spoke' : 'stayed quiet';
    const want = m.should ? 'should have spoken' : 'should have stayed quiet';
    const cls = d.hard ? 'bad' : (bad ? 'warn' : 'good');
    return '<div class="card' + (bad ? ' err' : '') + '">' +
      '<div class="row"><span class="id">' + m.id + '</span>' +
      '<span class="id">' + m.state +
      (m.dnd ? ' · DND' : '') + ' · ' + m.hour + ':00' +
      m.slices.map(function (s) { return '<span class="badge">' + s + '</span>'; }).join('') +
      '</span></div>' +
      m.signals.map(function (s) {
        return '<div class="sig"><b>' + s.source + '</b><br>' + esc(s.content) + '</div>';
      }).join('') +
      '<div class="verdict"><span class="' + cls + '">' + said + '</span>' +
      ' · ' + want + ' · cost ' + d.cost.toFixed(1) +
      (d.hard ? ' · <span class="bad">HARD VIOLATION</span>' : '') + '</div>' +
      '<div class="why">' + esc(m.rationale) + '</div>' +
      '</div>';
  }).join('') || '<p class="sub">Nothing matches those filters.</p>';
}

function esc(s) {
  return s.replace(/[&<>]/g, function (c) {
    return { '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c];
  });
}

[policySel, document.getElementById('filter'), sliceSel].forEach(function (el) {
  el.addEventListener('change', render);
});
render();
</script>
"""


def build_payload(items: list[Item], split: str) -> dict:
    """Score every policy once and flatten it into what the page needs."""
    silence = silence_ics(items)
    cards: list[Scorecard] = []
    per_policy: dict[str, dict[str, dict]] = {}

    for policy in registry().values():
        card = evaluate(policy, items, reference=silence)
        cards.append(card)
        decisions = {d.moment_id: d for d in run_policy(policy, items)}
        per_policy[policy.name] = {
            o.moment_id: {
                "surface": decisions[o.moment_id].surface,
                "cost": o.cost,
                "hard": o.hard_violation,
            }
            for o in card.outcomes
        }

    cards.sort(key=lambda c: c.ics)

    board = [
        {
            "policy": c.policy,
            "ics": c.ics,
            "normalized": c.ics_normalized,
            "precision": c.precision_at_interrupt,
            "recall": c.recall_high_value,
            "ece": c.ece,
            "violations": c.hard_violations,
            "surfaced": c.surfaced,
            "n": c.n,
        }
        for c in cards
    ]

    moments = [
        {
            "id": it.moment.id,
            "state": it.moment.user_state.activity.value,
            "dnd": it.moment.user_state.dnd,
            "hour": it.moment.user_state.local_hour,
            "slices": it.moment.slices,
            "signals": [
                {"source": s.source.value, "content": s.content} for s in it.moment.signals
            ],
            "should": it.label.should_surface,
            "rationale": it.label.rationale,
            "decisions": {name: per_policy[name][it.moment.id] for name in per_policy},
        }
        for it in items
    ]

    return {
        "board": board,
        "moments": moments,
        "silence": silence,
        "n": len(items),
        "split": split,
    }


class _Handler(BaseHTTPRequestHandler):
    def __init__(self, *args, payload: dict, **kwargs):
        self._payload = payload
        super().__init__(*args, **kwargs)

    def do_GET(self):  # noqa: N802
        if self.path not in ("/", "/index.html"):
            self.send_error(404)
            return
        # json.dumps escapes nothing HTML-significant by default, so close the
        # one tag that could terminate the surrounding <script> block early.
        blob = json.dumps(self._payload).replace("</", "<\\/")
        body = PAGE.replace("__DATA__", blob).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # keep the console quiet
        pass


def serve(version: str = "v1", split: str = "dev", port: int = 8000) -> None:
    items = load(version, split)
    payload = build_payload(items, split)
    handler = partial(_Handler, payload=payload)
    url = f"http://127.0.0.1:{port}/"
    print(f"TactBench viewer — {len(items)} moments on {split} → {url}")
    print("Ctrl-C to stop.")
    webbrowser.open(url)
    try:
        HTTPServer(("127.0.0.1", port), handler).serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")
