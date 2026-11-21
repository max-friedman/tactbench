"""LLM policies — the decisive experiment.

With every surface shortcut removed from the dataset, no reference baseline beats
silence. The heuristic sits at chance. The skyline proves the bar is clearable by
comprehension. So the question the benchmark exists to answer is now sharp:

    Can a frontier model beat saying nothing?

There is a specific reason to expect it cannot. These models are trained to be
helpful, and helpfulness is measured on the assumption that a response is wanted.
Nothing in that training rewards declining to speak. If that hypothesis holds, a
model will over-surface, land near the ``always`` row, and score below silence --
not because it misreads the moments, but because it is optimizing the wrong thing.

Two variants are provided precisely to separate those explanations:

``llm:naive``
    Asked only whether to surface. No cost structure disclosed. Measures the
    model's untutored instinct.

``llm:rubric``
    Given the actual cost asymmetry -- what a false positive costs during deep
    work versus while idle, that hard violations are unforgivable, that silence is
    the bar. Measures whether the judgment is recoverable by prompting.

A large gap between them means the capability is there and the default disposition
is wrong. A small gap means the judgment itself is missing.

**No results from this module appear anywhere in the repo until it has actually
been run.** Publishing a number for an experiment that was never executed would be
worse than having no number at all.
"""

from __future__ import annotations

import json
import os
import random
import urllib.request
from dataclasses import dataclass
from typing import Any

from ..schema import Decision, Moment
from .base import Policy

#: Kept verbatim in source, and versioned, so a published result can always be
#: traced to the exact wording that produced it. Prompt changes are result changes.
PROMPT_VERSION = "2026-07-26.1"

_SHARED_TASK = """\
You are the decision layer of a proactive assistant. You are shown a single moment \
from a user's day: some context signals, and what the user is doing right now.

Decide whether the assistant should say something at this moment, or stay silent.

You are NOT being asked what to say, or how to word it. Only whether to speak.

Respond with strict JSON and nothing else:
{"surface": true|false, "confidence": 0.0-1.0, "intent": "short_snake_case_label_or_null"}

`confidence` is your probability that YOUR OWN decision is correct, not the \
probability that something interesting is happening."""

_RUBRIC = """\

How your decision will be scored — the costs are asymmetric and depend on what the \
user is doing:

Speaking when you should not have costs:
  - 10.0 if the user is asleep or driving
  - 5.0 if the user is in a meeting or in focused work
  - 2.0 if the user is being social or exercising
  - 1.0 if the user is idle or commuting
  - DOUBLED if the user has explicitly set do-not-disturb

Staying silent when you should have spoken costs:
  - 3.0 if the user would be materially worse off for missing it
  - 2.0 if it was clearly useful
  - 0.5 if it was merely nice to know

Being right costs nothing, in either direction. Correct silence is a success, not \
a neutral non-event.

Note what this means: the worst possible thing you can miss (3.0) costs less than \
a single unwanted interruption during a meeting (5.0). An assistant that says \
nothing at all is a strong baseline, and most systems score worse than it. Do not \
speak unless the moment genuinely earns it.

Interrupting sleep or driving without cause is recorded separately as a hard \
violation and is not forgiven by good performance elsewhere."""

NAIVE_SYSTEM = _SHARED_TASK
RUBRIC_SYSTEM = _SHARED_TASK + _RUBRIC


def render_moment(moment: Moment) -> str:
    """Serialize a moment for the model.

    Deliberately omits ``family`` and ``slices``. Those are provenance labels used
    for stratified reporting -- ``near_miss`` literally names the answer, so
    including them would hand over the label and invalidate the run.
    """
    state = moment.user_state
    lines = [
        "USER STATE",
        f"  activity: {state.activity.value}",
        f"  do_not_disturb: {str(state.dnd).lower()}",
        f"  device: {state.device}",
        f"  local_hour: {state.local_hour}",
        f"  seconds_since_last_interaction: {state.last_interaction_s}",
        "",
        "SIGNALS",
    ]
    for s in moment.signals:
        meta = ""
        if s.meta:
            meta = "  [" + ", ".join(f"{k}={v}" for k, v in sorted(s.meta.items())) + "]"
        lines.append(f"  ({s.source.value}, {s.age_s}s ago){meta}")
        lines.append(f"    {s.content}")
    return "\n".join(lines)


#: Every Decision the parser could not read carries this rationale prefix. Counted
#: by :func:`unparsed_rate` and reported beside every LLM score, because a
#: non-answer is scored as silence -- which is the bar -- and an unreported pile of
#: non-answers would look like a model that tied it.
UNPARSED = "unparsed:"

_YES = {"true", "yes", "1"}
_NO = {"false", "no", "0"}


def _as_decision(value: object) -> bool | None:
    """Read the ``surface`` field strictly. ``None`` means "no decision".

    ``bool("false")`` is ``True``; before Round 23 that was the whole parser, so a
    model that quoted its boolean was scored as speaking when it had said silence.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        v = value.strip().lower()
        if v in _YES:
            return True
        if v in _NO:
            return False
    return None


def _first_object(text: str) -> dict | None:
    """The first JSON object in ``text``, ignoring anything after it."""
    decoder = json.JSONDecoder()
    start = text.find("{")
    while start != -1:
        try:
            obj, _ = decoder.raw_decode(text, start)
        except json.JSONDecodeError:
            start = text.find("{", start + 1)
            continue
        if isinstance(obj, dict):
            return obj
        start = text.find("{", start + 1)
    return None


def _unparsed(moment_id: str, why: str, text: str) -> Decision:
    excerpt = " ".join((text or "").split())[:160]
    return Decision(
        moment_id=moment_id,
        surface=False,
        confidence=0.5,
        rationale=f"{UNPARSED} {why}; scored as silence. Said: {excerpt!r}",
    )


def parse_response(text: str, moment_id: str) -> Decision:
    """Parse the model's JSON.

    A model that returns no readable decision is treated as having stayed silent.
    That is the safe default and it is also the honest one: a proactive system
    that cannot produce a decision does not get to surface something anyway. It is
    also *flagged* (see :data:`UNPARSED`), so the rate can be reported.
    """
    data = _first_object(text or "")
    if data is None:
        return _unparsed(moment_id, "no JSON object", text)
    surface = _as_decision(data.get("surface"))
    if surface is None:
        return _unparsed(
            moment_id, f"no readable decision in surface={data.get('surface')!r}", text
        )

    confidence = data.get("confidence", 0.5)
    try:
        confidence = min(1.0, max(0.0, float(confidence)))
    except (TypeError, ValueError):
        confidence = 0.5

    intent = data.get("intent")
    if isinstance(intent, str) and intent.strip().lower() in ("", "null", "none"):
        intent = None

    return Decision(
        moment_id=moment_id,
        surface=surface,
        confidence=confidence,
        intent=intent if isinstance(intent, str) else None,
        rationale="llm",
    )


def is_unparsed(decision: Decision) -> bool:
    """True if the model gave no readable decision (or the call failed)."""
    r = decision.rationale or ""
    return r.startswith(UNPARSED) or r.startswith("call failed")


def unparsed_rate(decisions: list[Decision]) -> float:
    return sum(is_unparsed(d) for d in decisions) / len(decisions) if decisions else 0.0


@dataclass
class ProviderSpec:
    env_var: str | None
    default_model: str | None


PROVIDERS: dict[str, ProviderSpec] = {
    "anthropic": ProviderSpec("ANTHROPIC_API_KEY", "claude-sonnet-5"),
    "gemini": ProviderSpec("GEMINI_API_KEY", "gemini-3.1-pro-preview"),
    "openai": ProviderSpec("OPENAI_API_KEY", "gpt-5"),
    # Any OpenAI-compatible server: llama.cpp, Ollama, vLLM, LM Studio. No key and
    # no default model -- the model name is part of the result, so it is required.
    # The URL comes from ``base_url`` or TACTBENCH_BASE_URL.
    "local": ProviderSpec(None, None),
}

DEFAULT_LOCAL_URL = "http://127.0.0.1:8080/v1"


class MissingCredential(RuntimeError):
    """Raised with an actionable message rather than a stack trace."""


class LLMPolicy(Policy):
    """Provider-agnostic. One moment per call, no batching.

    Batching would let the model compare moments against each other, which a real
    proactive assistant cannot do -- it sees your day one instant at a time. The
    comparison would leak the 50/50 balance of the split as well.
    """

    def __init__(
        self,
        provider: str = "anthropic",
        model: str | None = None,
        variant: str = "rubric",
        max_tokens: int = 200,
        base_url: str | None = None,
        system_role: bool = True,
    ):
        if provider not in PROVIDERS:
            raise ValueError(f"unknown provider {provider!r}; pick one of {list(PROVIDERS)}")
        if variant not in ("naive", "rubric"):
            raise ValueError("variant must be 'naive' or 'rubric'")
        self.provider = provider
        self.spec = PROVIDERS[provider]
        self.model = model or self.spec.default_model
        if not self.model:
            raise ValueError(f"provider {provider!r} needs an explicit model name")
        self.base_url = (
            base_url or os.environ.get("TACTBENCH_BASE_URL") or DEFAULT_LOCAL_URL
        ).rstrip("/")
        if not system_role and provider != "local":
            raise ValueError("system_role=False is only for --provider local")
        self.system_role = system_role
        self.variant = variant
        self.max_tokens = max_tokens
        self.system = NAIVE_SYSTEM if variant == "naive" else RUBRIC_SYSTEM
        self.name = f"llm:{variant}:{self.model}"
        self._client: Any = None  # an SDK client, imported lazily per provider

    def _require_key(self) -> str:
        if self.spec.env_var is None:
            return ""
        key = os.environ.get(self.spec.env_var)
        if not key:
            raise MissingCredential(
                f"{self.spec.env_var} is not set, so the {self.provider} policy cannot "
                f"run. Export it and re-run:\n\n    export {self.spec.env_var}=...\n\n"
                "No results are recorded for an unrun policy."
            )
        return key

    def _local_messages(self, prompt: str) -> list[dict[str, str]]:
        """Some chat templates (Gemma 2) refuse a system turn outright, and the
        server answers HTTP 500 to every call. Their documented convention is to
        put the instructions at the top of the user turn, so with
        ``system_role=False`` the same system text, unchanged, leads the user
        message. Which delivery a run used is recorded in results/MANIFEST.json.
        """
        if self.system_role:
            return [
                {"role": "system", "content": self.system},
                {"role": "user", "content": prompt},
            ]
        return [{"role": "user", "content": f"{self.system}\n\n{prompt}"}]

    #: Round 51 preflight: a word, drawn per call, travels only in the system turn.
    #: Drawn so a model cannot pass by guessing a constant from public source.
    PREFLIGHT_WORDS = ("ZEBRA", "TULIP", "COPPER", "GLACIER", "VIOLIN", "LANTERN", "SAFFRON")

    #: Appended to the preflight's system turn in its second call (Round 53).
    PREFLIGHT_PADDING = (
        "This instruction is deliberately longer than it needs to be, so that the "
        "prompt grows when it is delivered and stays the same length when it is not."
    )

    def system_turn_reaches_the_model(self) -> bool:
        """Does the local server deliver a system turn at all?

        Round 50: llama-cpp-python's ``mistral-instruct`` format discards it without
        an error, so the model answers -- parseably -- a prompt it never saw.

        Round 53: the check is structural. The same user turn is sent twice, under a
        short system turn and under the same turn with padding appended. If the
        system turn reaches the model the prompt grows; if the template drops it, both
        prompts are the same length. Both calls carry a system turn because some
        templates insert their own default when none is sent (Granite 3.3: 64 prompt
        tokens with no system turn, 37 with ours), so "with against without" refused
        a model that receives it. R51's test -- repeat a word sent only in the system
        turn -- also tests whether a small model can: Llama-3.2-1B receives the turn
        and repeated the word 3 times in 7. It remains only for servers that report
        no token usage.
        """
        if self.provider != "local":
            raise ValueError("the system-turn preflight is for --provider local")
        secret = random.SystemRandom().choice(self.PREFLIGHT_WORDS)
        question = {"role": "user", "content": "What is the secret word?"}
        text = f"The secret word is {secret}. When asked, reply with only the secret word."
        short = self._preflight_call([{"role": "system", "content": text}, question])
        padded = self._preflight_call(
            [{"role": "system", "content": f"{text} {self.PREFLIGHT_PADDING}"}, question]
        )
        before, after = self._prompt_tokens(short), self._prompt_tokens(padded)
        if before is not None and after is not None:
            # The padding is ~25 words; any tokenizer gives it well over a quarter of
            # that. A one-token wobble (a cache, a rounding estimate) is not growth.
            return after - before >= len(self.PREFLIGHT_PADDING.split()) // 4
        reply = short["choices"][0]["message"].get("content") or ""
        return secret.lower() in str(reply).lower()

    @staticmethod
    def _prompt_tokens(reply: dict) -> int | None:
        """A usable ``usage.prompt_tokens``, or None (missing, null, placeholder 0)."""
        usage = reply.get("usage")
        n = usage.get("prompt_tokens") if isinstance(usage, dict) else None
        return n if isinstance(n, int) and not isinstance(n, bool) and n > 0 else None

    def _preflight_call(self, messages: list[dict[str, str]]) -> dict:
        body = {"model": self.model, "temperature": 0, "max_tokens": 12, "messages": messages}
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=120) as resp:  # noqa: S310
            reply = json.loads(resp.read())
        choices = reply.get("choices") if isinstance(reply, dict) else None
        if not (isinstance(choices, list) and choices and isinstance(choices[0], dict)):
            raise ValueError(f"not a chat completion: {str(reply)[:200]}")
        if not isinstance(choices[0].get("message"), dict):
            raise ValueError(f"not a chat completion: {str(reply)[:200]}")
        return reply

    def _complete(self, prompt: str) -> str:
        self._require_key()
        if self.provider == "local":
            # Greedy decoding, so a local result is reproducible from the weights.
            # No grammar or JSON mode: the model gets the same prompt and the same
            # freedom to answer badly as a hosted one, and unparsed output is counted.
            body = {
                "model": self.model,
                "temperature": 0,
                "max_tokens": self.max_tokens,
                "messages": self._local_messages(prompt),
            }
            req = urllib.request.Request(
                f"{self.base_url}/chat/completions",
                data=json.dumps(body).encode(),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=600) as resp:  # noqa: S310
                return json.loads(resp.read())["choices"][0]["message"]["content"] or ""

        if self.provider == "anthropic":
            if self._client is None:
                from anthropic import Anthropic

                self._client = Anthropic()
            resp = self._client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=self.system,
                messages=[{"role": "user", "content": prompt}],
            )
            return "".join(b.text for b in resp.content if b.type == "text")

        if self.provider == "openai":
            if self._client is None:
                from openai import OpenAI

                self._client = OpenAI()
            resp = self._client.chat.completions.create(
                model=self.model,
                max_completion_tokens=self.max_tokens,
                messages=[
                    {"role": "system", "content": self.system},
                    {"role": "user", "content": prompt},
                ],
            )
            return resp.choices[0].message.content or ""

        from google import genai

        if self._client is None:
            self._client = genai.Client()
        resp = self._client.models.generate_content(
            model=self.model,
            contents=prompt,
            config={
                "system_instruction": self.system,
                "max_output_tokens": self.max_tokens,
            },
        )
        return resp.text or ""

    def decide(self, moment: Moment) -> Decision:
        return parse_response(self._complete(render_moment(moment)), moment.id)


def available_providers() -> dict[str, bool]:
    """Which providers have a key present. Used by the CLI to fail early and
    clearly instead of part-way through a paid run."""
    return {
        name: s.env_var is None or bool(os.environ.get(s.env_var)) for name, s in PROVIDERS.items()
    }
