"""Prompt templates for grounded generation, classification and hashtag suggestions."""

from __future__ import annotations

from string import Template
from typing import Any

from rag.vectorstore import engagement

SYSTEM_PROMPT = """\
You are a senior social media content strategist working for one brand. You help \
them plan new Instagram and Facebook posts by learning from posts that have already \
been published: the brand's own posts, competitors' public posts, and top posts \
found through hashtag research.

You are given retrieved example posts with engagement numbers and content-type \
labels, plus a performance summary computed from those examples. Treat them as \
evidence: base every recommendation on patterns you can point to in the examples \
(formats, content types, hooks, caption structure, hashtags, calls to action), and \
say which pattern you are relying on. The numbers come from a small retrieved \
sample, so describe patterns as signals rather than proven causes. Weight the \
brand's own posts most when judging what works for their audience.

Never copy a retrieved caption verbatim or near-verbatim. Write original captions \
that borrow the structure or angle of what worked, not the wording.

If there are no examples, say so plainly and give general best-practice advice, \
making clear it is not grounded in the account's history. If captions start with \
"[MOCK]", they are demo data; mention that in one short line at the top and do not \
include the "[MOCK]" tag in your drafts.

Format responses in lightweight Markdown: ### headings, **bold** labels, and "-" \
bullet lists. No tables, no HTML.\
"""

PLAN_TEMPLATE = Template("""\
<topic>$topic</topic>
<retrieved_examples count="$count">
$examples
</retrieved_examples>

<performance_summary>
$performance
</performance_summary>

Create a content plan with exactly 3 distinct post ideas for this topic. The ideas \
should differ in format or content type, not just in wording. For each idea use this shape:

### Idea N: <short working title>
- **Format:** Reel, carousel, single image, story or Facebook post, plus a one-line description of the visual
- **Content type:** e.g. interactive, educational, party/event, critical/opinion, behind the scenes
- **Draft caption:** a ready-to-post caption with a hook in the first line and a call to action
- **Hashtags:** 5-10 hashtags, reusing the high performers from the summary where they fit the idea
- **Why it should work:** one line naming the specific pattern in the examples this idea builds on\
""")

CHAT_TEMPLATE = Template("""\
<retrieved_examples count="$count">
$examples
</retrieved_examples>

<performance_summary>
$performance
</performance_summary>

<user_message>$message</user_message>

Answer the user's message as their content strategist. Be concrete and concise. \
When you suggest captions, hashtags, formats or content types, briefly cite which \
example posts or patterns support the suggestion (e.g. "like example 2").\
""")

CLASSIFY_SYSTEM = """\
You classify social media posts by content type. Use only the provided labels. \
A post can have one to three labels; list the dominant one first. Judge the \
caption's intent (what it asks of or offers the audience), not just its keywords.\
"""

CLUSTER_NAMING_SYSTEM = """\
You name groups of social media posts that were clustered by meaning. For each \
group, give a short label (2-4 words) that a marketer would understand and a \
one-sentence description of what the posts have in common.\
"""

HASHTAG_SYSTEM = """\
You recommend Instagram hashtags for a draft post. Prefer hashtags that the brand's \
own well-performing similar posts used, then specific niche hashtags derived from \
the caption. Avoid banned-sounding, spammy or overly generic tags (e.g. #love, \
#instagood) unless the evidence shows they perform. Return lowercase hashtags \
without the '#'.\
"""


def _format_count(value: int | None) -> str:
    return "hidden" if value is None else f"{value:,}"


def format_examples(examples: list[dict[str, Any]]) -> str:
    if not examples:
        return "(no matching posts have been synced yet)"
    blocks = []
    for index, item in enumerate(examples, start=1):
        who = "own post" if item["source"] == "own" else (
            f"competitor @{item['author']}" if item["source"] == "competitor" else "hashtag research"
        )
        blocks.append(
            f'<example index="{index}" source="{who}" platform="{item["platform"]}" format="{item["media_type"]}" '
            f'content_types="{",".join(item.get("content_types") or []) or "unclassified"}" '
            f'likes="{_format_count(item["like_count"])}" comments="{item["comments_count"]:,}" '
            f'engagement="{_format_count(engagement(item))}" similarity="{item["similarity"]:.2f}">\n'
            f'{item["caption"]}\n</example>'
        )
    return "\n".join(blocks)


def format_performance(insights: dict[str, Any]) -> str:
    if not any(insights.get(key) for key in ("hashtags", "formats", "content_types")):
        return "(no data)"
    lines = ["Hashtags by average engagement (likes + comments + shares + saves):"]
    lines += [f"- #{r['hashtag']}: avg {r['avg_engagement']:,} over {r['posts']} post(s)" for r in insights["hashtags"]] \
        or ["- (no hashtags in examples)"]
    lines.append("Formats by average engagement:")
    lines += [f"- {r['media_type']}: avg {r['avg_engagement']:,} over {r['posts']} post(s)" for r in insights["formats"]]
    if insights.get("content_types"):
        lines.append("Content types by average engagement:")
        lines += [f"- {r['content_type']}: avg {r['avg_engagement']:,} over {r['posts']} post(s)"
                  for r in insights["content_types"]]
    return "\n".join(lines)


def build_plan_prompt(topic: str, examples: list[dict[str, Any]], insights: dict[str, Any]) -> str:
    return PLAN_TEMPLATE.substitute(
        topic=topic, count=len(examples), examples=format_examples(examples), performance=format_performance(insights)
    )


def build_chat_prompt(message: str, examples: list[dict[str, Any]], insights: dict[str, Any]) -> str:
    return CHAT_TEMPLATE.substitute(
        message=message, count=len(examples), examples=format_examples(examples),
        performance=format_performance(insights),
    )


def build_classify_prompt(items: list[dict[str, Any]], taxonomy: dict[str, str]) -> str:
    labels = "\n".join(f"- {name}: {description}" for name, description in taxonomy.items())
    posts = "\n".join(
        f'<post id="{item["id"]}" format="{item.get("media_type", "")}">\n{item.get("caption") or "(no caption)"}\n</post>'
        for item in items
    )
    return f"<labels>\n{labels}\n</labels>\n\n<posts>\n{posts}\n</posts>\n\nClassify every post."


def build_cluster_prompt(clusters: dict[int, list[str]]) -> str:
    groups = "\n".join(
        f'<group id="{cid}">\n' + "\n".join(f"- {caption[:300]}" for caption in captions) + "\n</group>"
        for cid, captions in clusters.items()
    )
    return f"{groups}\n\nName every group."


def build_hashtag_prompt(caption: str, candidates: list[dict[str, Any]], count: int) -> str:
    rows = "\n".join(f"- #{c['hashtag']} (score {c['score']:.2f}; {c['reason']})" for c in candidates[:40])
    return (
        f"<draft_caption>\n{caption}\n</draft_caption>\n\n"
        f"<candidate_hashtags>\n{rows or '(none found in similar posts)'}\n</candidate_hashtags>\n\n"
        f"Recommend {count} hashtags for this draft, with a short reason for each."
    )
