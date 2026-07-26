"""TactBench command line."""

from __future__ import annotations

import hashlib
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from .dataset.generate import generate
from .dataset.loader import load, split_path, write_jsonl
from .metrics import Scorecard, score
from .policies.builtin import registry
from .runner import evaluate, silence_ics
from .schema import Decision

app = typer.Typer(
    add_completion=False,
    help="A benchmark for whether an assistant should speak at all.",
)
console = Console()


def _fmt(v: float | None, spec: str = ".3f") -> str:
    return "--" if v is None else format(v, spec)


def _bucket(moment_id: str) -> int:
    """Stable 0-99 bucket for a moment id, independent of PYTHONHASHSEED."""
    digest = hashlib.sha256(moment_id.encode()).digest()
    return digest[0] % 100


def _table(cards: list[Scorecard], silence: float) -> Table:
    t = Table(title="TactBench results", title_style="bold")
    t.add_column("policy", style="bold")
    t.add_column("ICS ↓", justify="right")
    t.add_column("vs silence", justify="right")
    t.add_column("prec@int ↑", justify="right")
    t.add_column("recall-hv ↑", justify="right")
    t.add_column("intent ↑", justify="right")
    t.add_column("ECE ↓", justify="right")
    t.add_column("hard viol. ↓", justify="right")
    t.add_column("spoke", justify="right")

    for c in sorted(cards, key=lambda c: c.ics):
        better = c.ics < silence
        verdict = f"[green]+{c.ics_normalized:.1f}[/green]" if better else (
            f"[red]{c.ics_normalized:.1f}[/red]"
        )
        viol = f"[red]{c.hard_violations}[/red]" if c.hard_violations else "0"
        t.add_row(
            c.policy,
            f"{c.ics:.1f}",
            verdict,
            _fmt(c.precision_at_interrupt),
            _fmt(c.recall_high_value),
            _fmt(c.intent_accuracy),
            _fmt(c.ece),
            viol,
            f"{c.surfaced}/{c.n}",
        )
    return t


@app.command()
def build(
    version: str = typer.Option("v1", help="Dataset version directory."),
    pairs: int = typer.Option(20, help="Matched pairs per scenario family."),
    seed: int = typer.Option(20260726, help="Generation seed."),
) -> None:
    """Generate the synthetic dataset splits."""
    items = generate(n_pairs_per_scenario=pairs, seed=seed)
    # Split on a stable digest of the moment id, not Python's hash() -- string
    # hashing is salted per process, so hash() would reshuffle the split on every
    # run and silently leak test items into dev.
    dev = [i for i in items if _bucket(i.moment.id) < 60]
    test = [i for i in items if _bucket(i.moment.id) >= 60]

    for split, subset in (("dev", dev), ("test", test)):
        path = split_path(version, split)
        write_jsonl(subset, path)
        console.print(f"wrote [bold]{len(subset)}[/bold] items → {path}")


@app.command(name="eval")
def evaluate_cmd(
    policy: str = typer.Option("all", "--policy", "-p", help="Policy name, or 'all'."),
    version: str = typer.Option("v1"),
    split: str = typer.Option("dev"),
) -> None:
    """Score one or all built-in policies against a split."""
    items = load(version, split)
    silence = silence_ics(items)
    reg = registry()

    chosen = list(reg.values()) if policy == "all" else [reg[policy]]
    cards = [evaluate(p, items, reference=silence) for p in chosen]

    console.print(_table(cards, silence))
    console.print(
        f"\n[dim]{len(items)} moments · silence baseline ICS = {silence:.1f}. "
        "'vs silence' above 0 means the policy is worth shipping; "
        "below 0 means it is worse than saying nothing.[/dim]"
    )


@app.command(name="llm")
def llm_cmd(
    provider: str = typer.Option("anthropic", help="anthropic | gemini | openai"),
    variant: str = typer.Option("rubric", help="naive (no cost info) | rubric (cost disclosed)"),
    model: str = typer.Option(None, help="Override the provider's default model."),
    version: str = typer.Option("v1"),
    split: str = typer.Option("dev"),
    limit: int = typer.Option(0, help="Only run the first N moments. 0 runs all."),
    fresh: bool = typer.Option(False, help="Ignore cached decisions and re-query."),
) -> None:
    """Score an LLM against a split. Requires an API key and costs money.

    Decisions are cached per (policy, split) so re-scoring, slicing, and viewing
    are free after the first run.
    """
    import json as _json

    from .policies.llm import LLMPolicy, MissingCredential, available_providers

    have = available_providers()
    if not have.get(provider):
        console.print(f"[red]No API key for {provider}.[/red]")
        console.print(f"Providers with a key present: "
                      f"{[p for p, ok in have.items() if ok] or 'none'}")
        raise typer.Exit(1)

    policy = LLMPolicy(provider=provider, model=model, variant=variant)
    items = load(version, split)
    if limit:
        items = items[:limit]

    cache_path = Path("runs") / f"{policy.name.replace(':', '_').replace('/', '_')}-{split}.jsonl"
    cached: dict[str, Decision] = {}
    if cache_path.exists() and not fresh:
        for line in cache_path.read_text().splitlines():
            if line.strip():
                d = Decision.model_validate(_json.loads(line))
                cached[d.moment_id] = d

    todo = [i for i in items if i.moment.id not in cached]
    console.print(
        f"[bold]{policy.name}[/bold] on {split} — {len(items)} moments, "
        f"{len(cached)} cached, [yellow]{len(todo)} to query[/yellow]"
    )

    if todo:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        with cache_path.open("a") as f, console.status("querying...") as status:
            for n, item in enumerate(todo, 1):
                try:
                    d = policy.decide(item.moment)
                except MissingCredential as e:
                    console.print(f"[red]{e}[/red]")
                    raise typer.Exit(1) from e
                except Exception as e:  # noqa: BLE001
                    # One bad call must not discard an expensive run; a failed
                    # decision scores as silence, same as unparseable output.
                    console.print(f"[yellow]{item.moment.id}: {e}[/yellow]")
                    d = Decision(moment_id=item.moment.id, surface=False,
                                 rationale=f"call failed: {e}")
                f.write(d.model_dump_json() + "\n")
                f.flush()
                cached[d.moment_id] = d
                status.update(f"querying... {n}/{len(todo)}")

    decisions = [cached[i.moment.id] for i in items if i.moment.id in cached]
    silence = silence_ics(items)
    card = score(items, decisions, policy.name, reference_ics=silence)

    console.print(_table([card], silence))
    verdict = (
        "[green]beats silence[/green]" if card.ics < silence
        else "[red]worse than saying nothing[/red]"
    )
    console.print(f"\n{policy.name} is {verdict} (silence ICS {silence:.1f}).")
    console.print(f"[dim]cached at {cache_path}[/dim]")


@app.command()
def audit(
    version: str = typer.Option("v1"),
    split: str = typer.Option("dev"),
) -> None:
    """Probe the dataset for surface shortcuts.

    Trains a bag-of-words classifier on signal text alone -- no user state, no DND,
    no slice tags -- and reports how well it separates speak from stay-quiet. Near
    50% means the words carry no answer and a policy must actually judge. High
    means the benchmark is measuring vocabulary instead of tact.
    """
    from .audit import lexical_leakage

    items = load(version, split)
    report = lexical_leakage(items)

    t = Table(title="Shortcut audit — bag-of-words probe (chance = 50%)")
    t.add_column("family", style="bold")
    t.add_column("probe accuracy", justify="right")
    t.add_column("verdict")

    families = sorted({i.moment.family for i in items})
    for family in families:
        subset = [i for i in items if i.moment.family == family]
        acc = lexical_leakage(subset).accuracy
        ok = acc < 0.60
        t.add_row(
            family,
            f"{acc:.1%}",
            "[green]at chance[/green]" if ok else "[yellow]leaks[/yellow]",
        )
    t.add_row("[bold]overall[/bold]", f"[bold]{report.accuracy:.1%}[/bold]", "")
    console.print(t)
    console.print(f"\n{report.verdict()}")
    console.print(
        "\n[dim]Most speak-predictive tokens: "
        + ", ".join(tok for tok, _ in report.top_speak[:6])
        + "\nMost quiet-predictive tokens: "
        + ", ".join(tok for tok, _ in report.top_quiet[:6])
        + "[/dim]"
    )


@app.command()
def demo() -> None:
    """Build the dataset if needed, then score every built-in policy."""
    path = split_path("v1", "dev")
    if not path.exists():
        build(version="v1", pairs=20, seed=20260726)
    evaluate_cmd(policy="all", version="v1", split="dev")


@app.command()
def failures(
    policy: str = typer.Argument(..., help="Policy to inspect."),
    version: str = typer.Option("v1"),
    split: str = typer.Option("dev"),
    limit: int = typer.Option(5),
) -> None:
    """Show the costliest mistakes a policy made. This is where the benchmark
    stops being a number and starts being useful."""
    items = load(version, split)
    by_id = {i.moment.id: i for i in items}
    card = evaluate(registry()[policy], items)

    worst = sorted(
        (o for o in card.outcomes if o.cost > 0), key=lambda o: -o.cost
    )[:limit]
    if not worst:
        console.print(f"[green]{policy} made no scored mistakes on {split}.[/green]")
        return

    for o in worst:
        item = by_id[o.moment_id]
        head = "spoke when it should not have" if o.kind == "fp" else "stayed quiet"
        console.print(
            f"\n[bold]{o.moment_id}[/bold]  cost={o.cost:.1f}  "
            f"[{'red' if o.hard_violation else 'yellow'}]{head}"
            f"{' · HARD VIOLATION' if o.hard_violation else ''}[/]"
        )
        console.print(f"  state: {item.moment.user_state.activity.value}"
                      f"{', DND' if item.moment.user_state.dnd else ''}")
        for s in item.moment.signals:
            console.print(f"  [dim]{s.source.value}:[/dim] {s.content}")
        console.print(f"  [dim]why:[/dim] {item.label.rationale}")


@app.command()
def serve(
    version: str = typer.Option("v1"),
    split: str = typer.Option("dev"),
    port: int = typer.Option(8000),
) -> None:
    """Launch the local viewer."""
    from .web.server import serve as _serve

    _serve(version=version, split=split, port=port)


def main() -> None:  # pragma: no cover
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
