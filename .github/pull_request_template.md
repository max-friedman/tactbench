<!--
Thanks for contributing. See CONTRIBUTING.md — especially the permutation rule if
you're adding a scenario family.
-->

## What and why

<!-- What changed, and what evidence drove it. If a measurement motivated this,
quote the measurement. -->

## Gate

- [ ] `uv run pytest -q`
- [ ] `uv run ruff check .` and `uv run ruff format --check .`
- [ ] `uv run tactbench audit` — new/changed families near 50%
- [ ] `uv run tactbench build` re-run and regenerated splits committed, if the
      generator changed

## Claims

- [ ] No number appears in the repo that wasn't actually produced by a run
- [ ] README results table updated, if costs / generator / policies changed
- [ ] Limitations section updated — removed a limitation this fixes, or added one
      this reveals
- [ ] No standing invariant was weakened to make the gate pass

<!-- If you did weaken an invariant or add an audit exception, say so here and
explain why — that will be the main thing reviewed. -->
