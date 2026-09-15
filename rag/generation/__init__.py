"""Retrieval-grounded content plans and chat replies, scoped to one user."""

from __future__ import annotations

from typing import Any

from rag.generation.insights import summarize_performance
from rag.generation.llm import ClaudeClient, GenerationRequest, LLMClient, LLMError, MockClient, get_llm_client
from rag.prompts import SYSTEM_PROMPT, build_chat_prompt, build_plan_prompt
from rag.retrieval import retrieve_for_query

MAX_HISTORY_MESSAGES = 12


def _generate(
    task: str, query: str, n_examples: int, user_id: str, sources: list[str] | None, client: LLMClient | None,
    history: list[dict[str, str]] | None = None,
) -> tuple[list[dict[str, Any]], str]:
    examples = retrieve_for_query(query, n_examples, user_id, sources)
    insights = summarize_performance(examples)
    builder = build_plan_prompt if task == "plan" else build_chat_prompt
    request = GenerationRequest(
        task=task,  # type: ignore[arg-type]
        query=query,
        system=SYSTEM_PROMPT,
        prompt=builder(query, examples, insights),
        examples=examples,
        insights=insights,
        history=(history or [])[-MAX_HISTORY_MESSAGES:],
    )
    return examples, (client or get_llm_client()).complete(request)


def generate_content_plan(
    topic: str, n_examples: int, user_id: str, sources: list[str] | None = None, client: LLMClient | None = None,
    history: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Retrieve the user's posts similar to ``topic`` and generate 3 grounded post ideas."""
    examples, plan = _generate("plan", topic, n_examples, user_id, sources, client, history)
    return {"topic": topic, "used_examples": examples, "plan": plan}


def chat_reply(
    message: str, n_examples: int, user_id: str, sources: list[str] | None = None, client: LLMClient | None = None,
    history: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Answer one chat turn, grounded in the user's posts similar to ``message``.

    ``history`` is the earlier conversation as ``[{"role": "user"|"assistant", "content": str}]``.
    """
    examples, reply = _generate("chat", message, n_examples, user_id, sources, client, history)
    return {"message": message, "used_examples": examples, "reply": reply}


__all__ = [
    "ClaudeClient", "GenerationRequest", "LLMClient", "LLMError", "MockClient",
    "chat_reply", "generate_content_plan", "get_llm_client", "summarize_performance",
]
