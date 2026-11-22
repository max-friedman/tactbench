"""TactBench command line."""

from __future__ import annotations

import hashlib
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from .dataset.generate import HELD_OUT_FRAMES, generate
from .dataset.loader import load, split_path, write_jsonl
from .metrics import Scorecard, score
from .policies.base import ask
from .policies.builtin import registry
from .runner import evaluate, normalized, pair_blind_ics, silence_ics
from .schema import Decision, frame_of

app = typer.Typer(
    add_completion=False,
    help="A benchmark for whether an assistant should speak at all.",
)
console = Console()


def _fmt(v: float | None, spec: str = ".3f") -> str:
    return "--" if v is None else format(v, spec)


def _bucket(key: str) -> int:
    """Stable 0-99 bucket for a split key, independent of PYTHONHASHSEED."""
    digest = hashlib.sha256(key.encode()).digest()
    return digest[0] % 100


def _signed(x: float) -> str:
    return f"[green]+{x:.1f}[/green]" if x > 0 else f"[red]{x:.1f}[/red]" if x < 0 else "0.0"


def _table(cards: list[Scorecard], silence: float, bar: float) -> Table:
    t = Table(title="TactBench results", title_style="bold")
    t.add_column("policy", style="bold")
    t.add_column("ICS ↓", justify="right")
    t.add_column("vs silence", justify="right")
    t.add_column("vs pair-blind", justify="right")
    t.add_column("prec@int ↑", justify="right")
    t.add_column("recall-hv ↑", justify="right")
    t.add_column("intent ↑", justify="right")
    t.add_column("ECE ↓", justify="right")
    t.add_column("hard viol. ↓", justify="right")
    t.add_column("spoke", justify="right")

    for c in sorted(cards, key=lambda c: c.ics):
        viol = f"[red]{c.hard_violations}[/red]" if c.hard_violations else "0"
        t.add_row(
            c.policy,
            f"{c.ics:.1f}",
            _signed(c.ics_normalized),
            _signed(normalized(c.ics, bar)),
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
    families: int | None = typer.Option(
        None,
        help="Scenario families to include (default: the original nine; "
        "v3 10, v4 11, v5 12, v6 13, v7 14).",
    ),
) -> None:
    """Generate the synthetic dataset splits."""
    items = generate(n_pairs_per_scenario=pairs, seed=seed, families=families)
    # Split on a stable digest of the PAIR key, not Python's hash() and not the
    # item id.
    #
    # Not hash(): string hashing is salted per process, so it would reshuffle the
    # split on every run and silently leak test items into dev.
    #
    # Not the item id: that was Round 10's bug. A pair's two sides share a
    # byte-identical body, so bucketing them independently put 72 of 180 pairs on
    # opposite sides of the split -- and made 77% of the held-out set answerable
    # by looking the partner up in the published dev file and negating its label.
    # Both sides of a pair must always travel together.
    # Round 13: split on the FRAME, not on a digest of the pair.
    #
    # The pair-key digest (Round 10) fixed pairs being divided across the split,
    # but left both splits drawing from the same handful of phrasings -- so 91% of
    # held-out decider sentences were published verbatim in dev and the benchmark
    # was solvable by a surface model. Round 12 showed varying the entities does
    # not help, because the frame carries the label.
    #
    # Splitting on the frame makes the held-out phrasings disjoint *by
    # construction*: verbatim overlap is zero, not merely small. Pair-wholeness is
    # preserved for free, because a pair's two sides share a frame.
    dev = [i for i in items if frame_of(i.moment) not in HELD_OUT_FRAMES]
    test = [i for i in items if frame_of(i.moment) in HELD_OUT_FRAMES]

    for split, subset in (("dev", dev), ("test", test)):
        path = split_path(version, split)
        write_jsonl(subset, path)
        console.print(f"wrote [bold]{len(subset)}[/bold] items → {path}")


@app.command(name="eval")
def evaluate_cmd(
    policy: str = typer.Option("all", "--policy", "-p", help="Policy name, or 'all'."),
    version: str = typer.Option("v1"),
    split: str = typer.Option("dev"),
    base_rate: float = typer.Option(
        1.0,
        "--base-rate",
        help="Quiet:loud ratio of the deployment. 1 = the balanced split; 100 = a "
        "realistic production prior, where false positives dominate.",
    ),
    by_family: bool = typer.Option(
        False,
        "--by-family",
        help="Break cost down per scenario family. Read this rather than trying to "
        "collapse a score into one 'comprehension' number -- ICS weights by "
        "consequence, so a single figure conflates how much a system understands "
        "with which parts it understands.",
    ),
) -> None:
    """Score one or all built-in policies against a split."""
    items = load(version, split)
    silence = silence_ics(items, base_rate=base_rate)
    reg = registry()

    chosen = list(reg.values()) if policy == "all" else [reg[policy]]
    cards = [evaluate(p, items, reference=silence, base_rate=base_rate) for p in chosen]

    bar = pair_blind_ics(items, base_rate=base_rate)
    console.print(_table(cards, silence, bar))
    console.print(
        f"\n[dim]{len(items)} moments · silence ICS = {silence:.1f} · pair-blind ICS = "
        f"{bar:.1f}. 'vs silence' above 0 means the policy is worth shipping. "
        "'vs pair-blind' above 0 means it reads the moment: no policy that answers both "
        "sides of a pair alike can get there without a hard violation.[/dim]"
    )
    if base_rate > 1.0:
        console.print(
            f"[dim]Weighted at {base_rate:g}:1 quiet:loud — every stay-quiet moment "
            f"stands in for {base_rate:g} real ones, so precision is what it would "
            "be in production.[/dim]"
        )

    if by_family:
        families = sorted({i.moment.family for i in items})
        t = Table(title="Mean cost per family (lower is better)", title_style="bold")
        t.add_column("family", style="bold")
        for c in cards:
            t.add_column(c.policy, justify="right")
        for fam in families:
            t.add_row(fam, *[f"{c.by_family.get(fam, 0.0):.2f}" for c in cards])
        console.print()
        console.print(t)
        console.print(
            "[dim]Where a system fails matters as much as how often. A policy strong "
            "on cheap families and weak on quiet_hours scores very differently from "
            "its mirror image at identical overall comprehension — see "
            "experiments/implied_comprehension_probe.py.[/dim]"
        )


#: Above this share of unreadable answers an LLM score is reported as inconclusive:
#: each non-answer is scored as silence, which is exactly the bar.
MAX_UNPARSED = 0.05


@app.command(name="llm")
def llm_cmd(
    provider: str = typer.Option(
        "anthropic", help="anthropic | gemini | openai | local (any OpenAI-compatible server)"
    ),
    variant: str = typer.Option("rubric", help="naive (no cost info) | rubric (cost disclosed)"),
    model: str = typer.Option(None, help="Override the provider's default model."),
    version: str = typer.Option("v1"),
    split: str = typer.Option("dev"),
    limit: int = typer.Option(0, help="Only run the first N moments. 0 runs all."),
    fresh: bool = typer.Option(False, help="Ignore cached decisions and re-query."),
    base_url: str = typer.Option(
        None, help="For --provider local. Default $TACTBENCH_BASE_URL or http://127.0.0.1:8080/v1"
    ),
    system_role: bool = typer.Option(
        True,
        help="For --provider local. --no-system-role puts the system prompt, unchanged, "
        "at the top of the user turn, for chat templates that reject a system turn.",
    ),
) -> None:
    """Score an LLM against a split. Hosted providers need an API key and cost money;
    ``--provider local`` runs open-weight models on your own server for free.

    Decisions are cached per (policy, split) so re-scoring, slicing, and viewing
    are free after the first run.
    """
    import json as _json

    from .policies.llm import (
        LLMPolicy,
        MissingCredential,
        available_providers,
        unparsed_rate,
    )

    have = available_providers()
    if not have.get(provider):
        console.print(f"[red]No API key for {provider}.[/red]")
        console.print(
            f"Providers with a key present: {[p for p, ok in have.items() if ok] or 'none'}"
        )
        raise typer.Exit(1)

    policy = LLMPolicy(
        provider=provider, model=model, variant=variant, base_url=base_url, system_role=system_role
    )
    items = load(version, split)
    if limit:
        items = items[:limit]

    # A run that moves the system prompt into the user turn is a different
    # experiment, so it gets its own cache rather than reusing the other's answers.
    suffix = "" if policy.system_role else "-nosys"
    stem = policy.name.replace(":", "_").replace("/", "_")
    # Per dataset version: v2 reuses ids like ``travel-pos-0003`` for different
    # text, so a shared cache would score v1's answers against v2's moments
    # (Round 38). v1 keeps its original name, so existing caches stay valid.
    tag = "" if version == "v1" else f"-{version}"
    cache_path = Path("runs") / f"{stem}{suffix}{tag}-{split}.jsonl"
    cached: dict[str, Decision] = {}
    if cache_path.exists() and not fresh:
        for line in cache_path.read_text().splitlines():
            if line.strip():
                d = Decision.model_validate(_json.loads(line))
                cached[d.moment_id] = d
        # A failed call is the server's answer, not the model's: ask again rather
        # than score it as silence forever. Later lines in the file supersede it.
        cached = {
            k: d for k, d in cached.items() if not (d.rationale or "").startswith("call failed")
        }

    todo = [i for i in items if i.moment.id not in cached]
    console.print(
        f"[bold]{policy.name}[/bold] on {split} — {len(items)} moments, "
        f"{len(cached)} cached, [yellow]{len(todo)} to query[/yellow]"
    )

    # Round 51: a template can drop the system turn silently (Mistral under
    # llama-cpp-python), so check it reaches the model before asking anything.
    if todo and policy.provider == "local" and policy.system_role:
        try:
            delivered = policy.system_turn_reaches_the_model()
        except (OSError, KeyError, IndexError, ValueError) as err:  # URLError is an OSError
            console.print(
                f"[red]The system-turn preflight could not get an answer[/red] ({err!r}). "
                "Check the server is up at --base-url. A template that rejects a system "
                "turn outright (Gemma 2 answers HTTP 500) needs --no-system-role."
            )
            raise typer.Exit(1) from None
        if not delivered:
            console.print(
                "[red]The server does not deliver a system turn to the model[/red]: "
                "lengthening the system turn did not lengthen the prompt (or, on a server "
                "that reports no token usage, the model could not repeat a word sent only "
                "there), so every answer would be to a prompt it never saw. Re-run with "
                "--no-system-role to put the same system prompt at the top of the user turn."
            )
            raise typer.Exit(1)

    if todo:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        with cache_path.open("a") as f, console.status("querying...") as status:
            for n, item in enumerate(todo, 1):
                try:
                    d = ask(policy, item.moment)
                except MissingCredential as e:
                    console.print(f"[red]{e}[/red]")
                    raise typer.Exit(1) from e
                except Exception as e:  # noqa: BLE001
                    # One bad call must not discard an expensive run; a failed
                    # decision scores as silence, same as unparseable output.
                    console.print(f"[yellow]{item.moment.id}: {e}[/yellow]")
                    d = Decision(
                        moment_id=item.moment.id, surface=False, rationale=f"call failed: {e}"
                    )
                f.write(d.model_dump_json() + "\n")
                f.flush()
                cached[d.moment_id] = d
                status.update(f"querying... {n}/{len(todo)}")

    decisions = [cached[i.moment.id] for i in items if i.moment.id in cached]
    silence = silence_ics(items)
    card = score(items, decisions, policy.name, reference_ics=silence)

    console.print(_table([card], silence, pair_blind_ics(items)))
    bad = unparsed_rate(decisions)
    console.print(
        f"unparsed: {bad:.1%} of decisions gave no readable answer and were scored as silence"
    )
    if bad > MAX_UNPARSED:
        # A non-answer is scored as silence, and silence is the bar. Past this rate the
        # score says more about the output format than about the judgment.
        verdict = f"[yellow]inconclusive[/yellow] — over {MAX_UNPARSED:.0%} unparsed"
    elif card.ics < silence:
        verdict = "[green]beats silence[/green]"
    else:
        verdict = "[red]worse than saying nothing[/red]"
    console.print(f"\n{policy.name} is {verdict} (silence ICS {silence:.1f}).")
    console.print(f"[dim]cached at {cache_path}[/dim]")


@app.command()
def results(
    version: str = typer.Option("v1"),
    split: str = typer.Option("dev"),
) -> None:
    """Re-score the committed LLM decisions in results/ and print README rows.

    Free: nothing is queried. The README's LLM table must equal this output, and
    a test enforces it.
    """
    from .results import markdown_row, scorecards

    cards = scorecards(version, split)
    bar = pair_blind_ics(load(version, split))
    if not cards:
        console.print(f"No committed LLM results for {version}/{split}.")
        raise typer.Exit(1)
    print(
        "| model | ICS ↓ | vs silence | vs pair-blind | prec@int ↑ | recall-hv ↑ | ECE ↓ "
        "| hard viol. ↓ | spoke | pairs ↑ | unparsed |"
    )
    print("|---|---|---|---|---|---|---|---|---|---|---|")
    for card, unparsed, pairs in cards:
        print(markdown_row(card, unparsed, pairs, bar))


@app.command()
def label(
    rater: str = typer.Option(..., help="Your name or handle; one file per rater."),
    pairs: int = typer.Option(20, help="Matched pairs in the sample (2 moments each)."),
    version: str = typer.Option("v1"),
    split: str = typer.Option("dev"),
) -> None:
    """Label a sample of moments by hand: should the assistant speak? y / n / q.

    You see what a model sees -- no ids, slices or family. Answers are saved after
    each one to labels/<version>-<split>/<rater>.jsonl, and a rerun resumes.
    """
    import json as _json

    from .labeling import labels_path, load_labels, rater_order, rater_view, sample_pairs
    from .schema import opaque_id

    try:
        path = labels_path(rater, version, split)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from e
    items = rater_order(rater, sample_pairs(load(version, split), pairs))
    done = load_labels(version, split).get(rater, {})
    todo = [i for i in items if opaque_id(i.moment.id) not in done]
    console.print(f"{len(done)} answered, {len(todo)} to go. y = speak, n = stay quiet, q = quit.")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        for n, item in enumerate(todo, 1):
            console.print(f"\n[bold]{len(done) + n}/{len(items)}[/bold]")
            console.print(rater_view(item), markup=False, highlight=False)
            answer = typer.prompt("speak? [y/n/q]").strip().lower()
            while answer not in ("y", "n", "q"):
                answer = typer.prompt("y, n or q").strip().lower()
            if answer == "q":
                break
            # The opaque id: a stored id reads ``-pos-`` / ``-near-`` and would let a
            # rater read the answer out of their own file.
            row = {"item": opaque_id(item.moment.id), "rater": rater, "surface": answer == "y"}
            f.write(_json.dumps(row) + "\n")
            f.flush()


@app.command()
def agreement(version: str = typer.Option("v1"), split: str = typer.Option("dev")) -> None:
    """Agreement among human raters (Fleiss' kappa) and with the constructed labels."""
    from .labeling import MIN_ITEMS, load_labels
    from .labeling import agreement as _agreement

    labels = load_labels(version, split)
    if not labels:
        console.print(f"No labels yet in labels/{version}-{split}/. Run `tactbench label`.")
        raise typer.Exit(1)
    r = _agreement(load(version, split), labels)
    answered = ", ".join(f"{k} {v}" for k, v in sorted(r.answers.items()))
    console.print(f"{r.raters} raters; answers in this split: {answered}")
    console.print(
        f"{r.items} moments ({r.pairs} whole pairs) were answered by every rater; "
        "kappa and the majority use only those"
    )
    if r.too_few:
        console.print(f"[yellow]Fewer than {MIN_ITEMS} moments in common: kappa withheld.[/yellow]")
    console.print(f"Fleiss' kappa: {_fmt(r.kappa)}")
    console.print(f"ties (even splits, not scored): {r.ties}")
    console.print(
        f"majority agrees with the constructed label (untied): "
        f"{_fmt(r.majority_matches_construction)}"
    )
    console.print(
        f"majority gets both sides of a pair right: {_fmt(r.majority_pairs_both_right)} "
        "-- raters see both sides of each pair, so this is easier than the LLM column"
    )
    for name, acc in sorted(r.per_rater.items()):
        shown = "--" if acc is None else f"{acc:.1%}"
        console.print(f"  {name}: agrees with construction on {shown}")


@app.command()
def audit(
    version: str = typer.Option("v1"),
    split: str = typer.Option("dev"),
) -> None:
    """Probe the dataset for surface shortcuts.

    Trains a bag-of-words classifier on signal text alone -- no user state, no DND,
    no slice tags -- and reports how well it separates speak from stay-quiet. Near
    50% on the UNIGRAM column means vocabulary carries no answer. It does not mean
    the text carries no answer: a role permutation is invisible to a bag of words
    by construction, so read the bigram column too. High
    means the benchmark is measuring vocabulary instead of tact.
    """
    from .audit import (
        PER_FAMILY_THRESHOLD,
        lexical_leakage,
        ngram_leakage,
        null_median,
        positional_leakage,
    )

    items = load(version, split)
    report = lexical_leakage(items)
    ngram_report = ngram_leakage(items)

    t = Table(title="Shortcut audit — text-only probes (chance = 50%)")
    t.add_column("family", style="bold")
    t.add_column("unigram", justify="right")
    # A probe that is reliably wrong is worth as much to a submitter as one that
    # is reliably right, so show what the words are actually worth once polarity
    # is chosen. Reporting only raw accuracy is how `meeting_prep` at 32.8% read
    # as "at chance" for nine rounds.
    t.add_column("exploitable", justify="right")
    # The unigram column cannot see word order, so a role permutation is invisible
    # to it by construction. Reporting it alone read as resistance for ten rounds.
    t.add_column("bigram", justify="right")
    t.add_column("positional", justify="right")
    # Round 40: the positional probe's chance level at this sample size. With labels
    # swapped at random within pairs it still exceeds 60% in about half of
    # family-seed cells (Round 37), so a positional figure means little without it.
    t.add_column("pos. null", justify="right")
    t.add_column("verdict")

    families = sorted({i.moment.family for i in items})
    for family in families:
        subset = [i for i in items if i.moment.family == family]
        uni = lexical_leakage(subset)
        big = ngram_leakage(subset)
        pos = positional_leakage(subset)
        # Gate on unigram and bigram; positional is reported only (see the audit
        # section of docs/METRICS.md for why, and the queue for when).
        worst = max(uni.exploitable_accuracy, big.exploitable_accuracy)

        def cell(r):
            return (
                f"[yellow]{r.exploitable_accuracy:.1%}[/yellow]"
                if r.is_leaking(PER_FAMILY_THRESHOLD)
                else f"{r.exploitable_accuracy:.1%}"
            )

        null = null_median(subset, positional_leakage)
        pos_cell = (
            f"[yellow]{pos.exploitable_accuracy:.1%}[/yellow]"
            if pos.is_leaking(PER_FAMILY_THRESHOLD) and pos.exploitable_accuracy > null
            else f"{pos.exploitable_accuracy:.1%}"
        )
        t.add_row(
            family,
            f"{uni.accuracy:.1%}",
            cell(uni),
            cell(big),
            pos_cell,
            f"{null:.1%}",
            "[yellow]leaks[/yellow]"
            if worst >= PER_FAMILY_THRESHOLD
            else "[green]at chance[/green]",
        )
    pos_report = positional_leakage(items)
    t.add_row(
        "[bold]overall[/bold]",
        f"[bold]{report.accuracy:.1%}[/bold]",
        f"[bold]{report.exploitable_accuracy:.1%}[/bold]",
        f"[bold]{ngram_report.exploitable_accuracy:.1%}[/bold]",
        f"[bold]{pos_report.exploitable_accuracy:.1%}[/bold]",
        f"{null_median(items, positional_leakage):.1%}",
        "",
    )
    console.print(t)
    # Report the WORST probe, not the friendliest one. Printing only the unigram
    # verdict under a table full of bigram leaks is how a benchmark keeps looking
    # fine while it has stopped measuring what it claims to.
    worst_probe = max((report, ngram_report, pos_report), key=lambda r: r.exploitable_accuracy)
    console.print(f"\n{worst_probe.verdict()}")
    if ngram_report.is_leaking(PER_FAMILY_THRESHOLD):
        console.print(
            f"\n[yellow]The unigram probe reports {report.accuracy:.1%} because it cannot "
            "see word order.[/yellow]\nA role permutation is only a reordering, so "
            "bag-of-words is structurally unable to\nseparate a pair. Bigrams reach "
            f"{ngram_report.accuracy:.1%}. Check that your family's eight frames are\n"
            "pairwise lexically disjoint and that each frame's two labels have the same\n"
            "token count — those two properties are what keep the probe at chance.\n"
            "See docs/DATASET.md and TestFrameDisjointness."
        )
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

    worst = sorted((o for o in card.outcomes if o.cost > 0), key=lambda o: -o.cost)[:limit]
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
        console.print(
            f"  state: {item.moment.user_state.activity.value}"
            f"{', DND' if item.moment.user_state.dnd else ''}"
        )
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
