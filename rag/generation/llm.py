"""LLM clients: Claude when ANTHROPIC_API_KEY is set, a deterministic mock otherwise."""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Literal

from rag import config
from rag.vectorstore import engagement

logger = logging.getLogger("rag.generation")

MOCK_PREFIX = config.MOCK_PREFIX
FALLBACK_BETA = "server-side-fallback-2026-07-01"
_FALLBACK_MODELS = ("claude-opus-5", "claude-fable-5-1")  # support fallbacks="default"


class LLMError(RuntimeError):
    pass


@dataclass
class GenerationRequest:
    task: Literal["plan", "chat"]
    query: str
    system: str
    prompt: str
    examples: list[dict[str, Any]] = field(default_factory=list)
    insights: dict[str, Any] = field(default_factory=lambda: {"hashtags": [], "formats": [], "content_types": []})
    # Earlier turns of the conversation: [{"role": "user"|"assistant", "content": str}]
    history: list[dict[str, str]] = field(default_factory=list)


class LLMClient(ABC):
    name: str

    @abstractmethod
    def complete(self, request: GenerationRequest) -> str: ...


class ClaudeClient(LLMClient):
    def __init__(self, api_key: str, model: str) -> None:
        import anthropic

        self._anthropic = anthropic
        # timeout x (retries + 1) stays under the nginx proxy_read_timeout (300s)
        self._client = anthropic.Anthropic(api_key=api_key, timeout=120.0, max_retries=1)
        self.model = model
        self.name = f"claude:{model}"

    def _create(self, **params: Any):
        anthropic = self._anthropic
        try:
            if self.model.startswith(_FALLBACK_MODELS):
                # On a safety-classifier decline, the API re-runs the request on
                # Anthropic's recommended fallback model instead of refusing.
                response = self._client.beta.messages.create(
                    model=self.model, betas=[FALLBACK_BETA], fallbacks="default", **params
                )
            else:
                response = self._client.messages.create(model=self.model, **params)
        except anthropic.AuthenticationError as exc:
            raise LLMError("Anthropic rejected ANTHROPIC_API_KEY (401). Check the key in .env.") from exc
        except anthropic.NotFoundError as exc:
            raise LLMError(f"Anthropic model {self.model!r} not found. Check ANTHROPIC_MODEL.") from exc
        except anthropic.RateLimitError as exc:
            raise LLMError("Anthropic rate limit reached (429). Try again shortly.") from exc
        except anthropic.APIStatusError as exc:
            raise LLMError(f"Anthropic API error ({exc.status_code}): {exc.message}") from exc
        except anthropic.APIConnectionError as exc:
            raise LLMError(f"Could not connect to the Anthropic API: {exc}") from exc

        if response.stop_reason == "refusal":
            category = getattr(getattr(response, "stop_details", None), "category", None)
            raise LLMError(f"Claude declined this request (category: {category or 'unspecified'}).")
        return response

    def complete(self, request: GenerationRequest) -> str:
        history = [
            {"role": turn["role"], "content": turn["content"]}
            for turn in request.history
            if turn.get("role") in ("user", "assistant") and turn.get("content")
        ]
        while history and history[0]["role"] != "user":  # the conversation must start with a user turn
            history.pop(0)
        response = self._create(
            max_tokens=16000, system=request.system,
            messages=[*history, {"role": "user", "content": request.prompt}],
        )
        text = "".join(block.text for block in response.content if block.type == "text").strip()
        if response.stop_reason == "max_tokens":
            text += "\n\n_(Response truncated at the output token limit.)_"
        return text

    def structured(self, system: str, prompt: str, schema: dict[str, Any], max_tokens: int = 16000) -> dict[str, Any]:
        """Return JSON that matches ``schema`` (structured outputs)."""
        response = self._create(
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": prompt}],
            output_config={"format": {"type": "json_schema", "schema": schema}},
        )
        text = next((block.text for block in response.content if block.type == "text"), "")
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise LLMError(f"Claude returned invalid JSON (stop_reason={response.stop_reason}).") from exc


class MockClient(LLMClient):
    """Deterministic, example-grounded output so the demo works without a key."""

    name = "mock"

    def complete(self, request: GenerationRequest) -> str:
        return self._plan(request) if request.task == "plan" else self._chat(request)

    @staticmethod
    def _top_tags(request: GenerationRequest, count: int) -> list[str]:
        tags = [row["hashtag"] for row in request.insights["hashtags"]]
        return tags[:count] or ["contentideas", "instagramtips", "smallbusiness"]

    @staticmethod
    def _formats(request: GenerationRequest) -> list[dict[str, Any]]:
        formats = list(request.insights["formats"])
        for fallback in ("REELS", "CAROUSEL_ALBUM", "IMAGE"):
            if len(formats) >= 3:
                break
            if all(row["media_type"] != fallback for row in formats):
                formats.append({"media_type": fallback, "avg_engagement": None, "posts": 0})
        return formats[:3]

    def _plan(self, request: GenerationRequest) -> str:
        topic = " ".join(request.query.replace("#", " ").split()) or "this topic"
        if len(topic) > 1 and topic[0].isupper() and topic[1].islower():
            topic = topic[0].lower() + topic[1:]  # it's inserted mid-sentence
        tags = self._top_tags(request, 8)
        formats = self._formats(request)
        labels = {"REELS": "Reel", "VIDEO": "Video", "CAROUSEL_ALBUM": "Carousel", "IMAGE": "Single image", "TEXT": "Text post"}
        types = [row["content_type"] for row in request.insights.get("content_types", [])] or ["educational"]
        concepts = {
            "interactive": ("Ask your audience", f"Quick question: what's your biggest challenge with {topic}?", "Answer in the comments."),
            "educational": ("Quick-win tutorial", f"The fastest way to get {topic} right, in 3 steps.", "Save this for later."),
            "party_event": ("Community moment", f"You're invited: a live session all about {topic}.", "Tap the link in bio to join."),
            "critical_opinion": ("Hot take", f"Unpopular opinion about {topic}: most people overcomplicate it.", "Agree or disagree?"),
            "behind_the_scenes": ("Behind the scenes", f"This is what {topic} really looks like on our side.", "Want a part 2?"),
            "testimonial": ("Community proof", f"What our community says after trying {topic}.", "Share your story below."),
        }
        chosen = [t for t in types if t in concepts][:3]
        for fallback in ("educational", "interactive", "behind_the_scenes"):
            if len(chosen) < 3 and fallback not in chosen:
                chosen.append(fallback)

        lines = [f"{MOCK_PREFIX} Content plan generated without ANTHROPIC_API_KEY. "
                 "Ideas are templated from the retrieved examples' statistics.", ""]
        if not request.examples:
            lines += ["_No synced posts matched this topic, so these ideas are not grounded. "
                      "Connect and sync an account first._", ""]
        for index, (ctype, fmt) in enumerate(zip(chosen, formats), start=1):
            title, hook, cta = concepts[ctype]
            shift = (index - 1) % len(tags)
            idea_tags = tags[shift:] + tags[:shift]
            why = (f"{labels.get(fmt['media_type'], fmt['media_type'])} posts averaged {fmt['avg_engagement']:,} "
                   f"engagements across {fmt['posts']} similar example(s)." if fmt["avg_engagement"] is not None
                   else "Adds format variety; no similar examples used this format yet, so treat it as a test.")
            ctype_stats = next((r for r in request.insights.get("content_types", []) if r["content_type"] == ctype), None)
            if ctype_stats:
                why += f" '{ctype}' content averaged {ctype_stats['avg_engagement']:,} in your examples."
            lines += [
                f"### Idea {index}: {title}",
                f"- **Format:** {labels.get(fmt['media_type'], fmt['media_type'])} ({ctype.replace('_', ' ')})",
                f"- **Draft caption:** {hook} {cta}",
                f"- **Hashtags:** {' '.join('#' + tag for tag in idea_tags[:7])}",
                f"- **Why it should work:** {why}",
                "",
            ]
        return "\n".join(lines).strip()

    def _chat(self, request: GenerationRequest) -> str:
        examples = request.examples
        if not examples:
            return (f"{MOCK_PREFIX} I couldn't find any synced posts related to that. "
                    "Connect Facebook and sync your accounts first.")
        best = max(examples, key=lambda item: engagement(item) or 0)
        best_index = examples.index(best) + 1
        tags = " ".join("#" + tag for tag in self._top_tags(request, 5))
        formats = request.insights["formats"]
        format_note = (f"{formats[0]['media_type']} is the strongest format in this sample "
                       f"(avg {formats[0]['avg_engagement']:,} engagements)." if formats else "")
        best_types = ", ".join(best.get("content_types") or []) or "unclassified"
        return "\n".join([
            f"{MOCK_PREFIX} Reply generated without ANTHROPIC_API_KEY.",
            "",
            f"I found {len(examples)} related post(s). The best performer is example {best_index} "
            f"({best['media_type']}, {best_types}, {engagement(best) or 0:,} engagements). {format_note}",
            "",
            f"- **Try:** reuse example {best_index}'s structure: a specific first-line hook, "
            "one concrete detail, then a clear call to action.",
            f"- **Hashtags to reuse:** {tags}",
            "- **Next step:** add ANTHROPIC_API_KEY for genuinely creative, tailored suggestions.",
        ])


def get_llm_client() -> LLMClient:
    api_key = config.anthropic_api_key()
    if not api_key:
        return MockClient()
    return ClaudeClient(api_key, config.anthropic_model())
