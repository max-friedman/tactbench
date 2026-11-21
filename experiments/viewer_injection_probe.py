"""Does planted markup in any viewer text field execute? Round 60.

Builds the v1/dev payload, plants an ``<img onerror>`` in each text field the page
renders (policy name, moment id, state, slice, signal source, signal content,
rationale), serves it, opens it in Chromium with every moment shown, and prints which
fields' handlers ran. Before R60: id, policy, slice, source, state. After: none.

Needs Playwright and a Chromium; not part of the gate (CI has no browser).
``tests/test_web.py::test_every_text_field_is_escaped_before_innerHTML`` is the
browser-free check, and it flags exactly these five on the pre-R60 page.

    uv run --with playwright python experiments/viewer_injection_probe.py [CHROME]
"""

import sys
import threading
from functools import partial
from http.server import HTTPServer

from playwright.sync_api import sync_playwright

from tactbench.dataset.loader import load
from tactbench.web.server import _Handler, build_payload

EVIL = (
    '<img src=x data-planted="FIELD" '
    'onerror="window.__hit=(window.__hit||[]).concat(this.dataset.planted)">'
)
p = build_payload(load("v1", "dev"), "dev", "v1")
fields = []


def plant(obj, key, name):
    obj[key] = EVIL.replace("FIELD", name)
    fields.append(name)


old = p["board"][0]["policy"]
plant(p["board"][0], "policy", "policy")
for m in p["moments"]:
    m["decisions"][p["board"][0]["policy"]] = m["decisions"].pop(old)
m = p["moments"][0]
plant(m, "id", "id")
plant(m, "state", "state")
m["slices"] = [EVIL.replace("FIELD", "slice")]
fields.append("slice")
plant(m["signals"][0], "source", "source")
plant(m["signals"][0], "content", "content")
plant(m, "rationale", "rationale")
srv = HTTPServer(("127.0.0.1", 0), partial(_Handler, payload=p))
threading.Thread(target=srv.serve_forever, daemon=True).start()
with sync_playwright() as pw:
    b = pw.chromium.launch(
        executable_path=(sys.argv[1] if len(sys.argv) > 1 else None), args=["--no-sandbox"]
    )
    pg = b.new_page()
    pg.goto(f"http://127.0.0.1:{srv.server_address[1]}/")
    pg.wait_for_timeout(500)
    pg.select_option("#filter", "all")
    pg.wait_for_timeout(500)
    print("planted:", fields)
    print("executed:", sorted(set(pg.evaluate("window.__hit||[]"))))
    b.close()
srv.shutdown()
