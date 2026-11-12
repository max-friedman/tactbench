"""Render the README's headline chart from a fresh eval, never from typed numbers.

The chart shows one thing: each built-in policy's ICS against silence on
``v1/dev``. Silence is the zero line. Bars to the right are worth shipping; bars
to the left are worse than saying nothing.

Every value is computed here, so the picture cannot drift from the table that
``TestReadmeResultsAreCurrent`` guards. Re-run after any change to costs, the
generator or a policy, and commit the result:

    uv run python experiments/leaderboard_chart.py

Stdlib only: the SVG is written by hand so the chart adds no dependency.
"""

from __future__ import annotations

from html import escape
from pathlib import Path

from tactbench.dataset.loader import load
from tactbench.policies.builtin import registry
from tactbench.runner import evaluate, silence_ics

OUT = Path(__file__).resolve().parents[1] / "docs" / "leaderboard.svg"

#: Display order, best to worst once evaluated. Notes are facts about the policy,
#: not about its score, so they cannot go stale.
NOTES = {
    "skyline": "ceiling, not a baseline",
    "never": "the bar",
    "always": "perfect recall",
}

WIDTH, ROW, TOP, LEFT, RIGHT = 720, 44, 92, 150, 40


def main() -> None:
    items = load("v1", "dev")
    silence = silence_ics(items)
    rows = []
    for name, policy in registry().items():
        result = evaluate(policy, items, reference=silence)
        rows.append((name, result.ics_normalized))
    rows.sort(key=lambda r: r[1], reverse=True)

    lo = min(-100.0, min(v for _, v in rows))
    hi = max(100.0, max(v for _, v in rows))
    plot_w = WIDTH - LEFT - RIGHT

    def x(v: float) -> float:
        return LEFT + (v - lo) / (hi - lo) * plot_w

    height = TOP + ROW * len(rows) + 48
    zero = x(0.0)
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WIDTH} {height}" '
        f'width="{WIDTH}" height="{height}" font-family="-apple-system, Segoe UI, '
        'Helvetica, Arial, sans-serif">',
        f'<rect width="{WIDTH}" height="{height}" rx="10" fill="#ffffff" stroke="#d0d7de"/>',
        '<text x="24" y="38" font-size="18" font-weight="600" fill="#1f2328">'
        "Nothing short of comprehension beats saying nothing</text>",
        f'<text x="24" y="62" font-size="13" fill="#59636e">ICS vs silence on v1/dev '
        f"({len(items)} moments). Right of the line is worth shipping.</text>",
        f'<line x1="{zero:.1f}" y1="{TOP - 10}" x2="{zero:.1f}" '
        f'y2="{TOP + ROW * len(rows)}" stroke="#1f2328" stroke-width="1.5"/>',
        f'<text x="{zero:.1f}" y="{TOP + ROW * len(rows) + 22}" font-size="12" '
        'text-anchor="middle" fill="#59636e">silence</text>',
    ]
    for i, (name, value) in enumerate(rows):
        cy = TOP + ROW * i + ROW / 2
        x0, x1 = sorted((zero, x(value)))
        fill = "#1a7f37" if value > 0 else "#cf222e" if value < 0 else "#59636e"
        out.append(
            f'<text x="{LEFT - 12}" y="{cy + 5:.1f}" font-size="14" text-anchor="end" '
            f'fill="#1f2328">{escape(name)}</text>'
        )
        if x1 - x0 > 0.5:
            out.append(
                f'<rect x="{x0:.1f}" y="{cy - 13:.1f}" width="{x1 - x0:.1f}" '
                f'height="26" rx="3" fill="{fill}"/>'
            )
        label = f"{value:+.1f}" if value else "0.0"
        note = NOTES.get(name)
        if note:
            label += f"  ({note})"
        # Labels sit just right of the silence line. On a positive bar that is
        # inside the bar, so the text turns white; on a negative bar it is clear
        # space, and the name column stays free.
        ink = "#ffffff" if value > 0 else "#1f2328"
        out.append(
            f'<text x="{zero + 8:.1f}" y="{cy + 5:.1f}" font-size="13" '
            f'fill="{ink}">{escape(label)}</text>'
        )
    out.append("</svg>")
    OUT.write_text("\n".join(out) + "\n")
    print(f"wrote {OUT.relative_to(OUT.parents[1])}")
    for name, value in rows:
        print(f"  {name:<12} {value:+7.1f}")


if __name__ == "__main__":
    main()
