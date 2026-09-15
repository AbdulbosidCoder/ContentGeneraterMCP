"""Saved conversations. Each message can be a chat turn, a content plan, or hashtag ideas,
always grounded in the user's own synced content."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.deps import current_user, get_db
from app.models import ChatSendRequest, ConversationRename
from common.models import ChatMessage, Conversation, User
from rag.generation import chat_reply, generate_content_plan
from rag.hashtags import suggest_hashtags

logger = logging.getLogger("backend.chat")
router = APIRouter(tags=["chat"])
DB = Depends(get_db, scope="function")


def conversation_dict(conversation: Conversation) -> dict[str, Any]:
    return {"id": str(conversation.id), "title": conversation.title,
            "created_at": conversation.created_at, "updated_at": conversation.updated_at}


def message_dict(message: ChatMessage) -> dict[str, Any]:
    return {"id": str(message.id), "role": message.role, "mode": message.mode, "content": message.content,
            "examples": message.examples or [], "is_error": message.is_error, "created_at": message.created_at}


def _get_conversation(db: Session, user: User, conversation_id: str) -> Conversation:
    try:
        conversation = db.get(Conversation, uuid.UUID(conversation_id))
    except ValueError:
        conversation = None
    if conversation is None or conversation.user_id != user.id:
        raise HTTPException(404, "Conversation not found.")
    return conversation


def _title_from(message: str) -> str:
    title = " ".join(message.split())
    return title if len(title) <= 60 else title[:57].rstrip() + "…"


def _hashtag_markdown(result: dict[str, Any]) -> str:
    suggestions = result["suggestions"]
    if not suggestions:
        return "I couldn't find hashtag ideas yet. Connect and sync your accounts so I can learn from your posts."
    lines = ["### Hashtag ideas", ""]
    lines += [f"- **#{s['hashtag']}**: {s['reason']}" for s in suggestions]
    lines += ["", f"Copy all: {' '.join('#' + s['hashtag'] for s in suggestions)}",
              "", f"_Based on {result['similar_posts_used']} similar posts ({result['method']})._"]
    return "\n".join(lines)


@router.get("/conversations")
def list_conversations(user: User = Depends(current_user), db: Session = DB) -> dict:
    rows = db.scalars(select(Conversation).where(Conversation.user_id == user.id)
                      .order_by(Conversation.updated_at.desc()).limit(100)).all()
    return {"conversations": [conversation_dict(c) for c in rows]}


@router.get("/conversations/{conversation_id}")
def get_conversation(conversation_id: str, user: User = Depends(current_user), db: Session = DB) -> dict:
    conversation = _get_conversation(db, user, conversation_id)
    return {**conversation_dict(conversation), "messages": [message_dict(m) for m in conversation.messages]}


@router.patch("/conversations/{conversation_id}")
def rename_conversation(conversation_id: str, body: ConversationRename, user: User = Depends(current_user),
                        db: Session = DB) -> dict:
    conversation = _get_conversation(db, user, conversation_id)
    conversation.title = body.title.strip()
    return conversation_dict(conversation)


@router.delete("/conversations/{conversation_id}")
def delete_conversation(conversation_id: str, user: User = Depends(current_user), db: Session = DB) -> dict:
    db.delete(_get_conversation(db, user, conversation_id))
    return {"deleted": True}


@router.post("/chat")
def send_message(body: ChatSendRequest, user: User = Depends(current_user), db: Session = DB) -> dict:
    if body.conversation_id:
        conversation = _get_conversation(db, user, body.conversation_id)
    else:
        conversation = Conversation(user_id=user.id, title=_title_from(body.message))
        db.add(conversation)
        db.flush()

    history = [{"role": m.role, "content": m.content} for m in conversation.messages if not m.is_error]
    user_message = ChatMessage(conversation_id=conversation.id, user_id=user.id, role="user", mode=body.mode,
                               content=body.message)
    db.add(user_message)
    conversation.updated_at = datetime.now(timezone.utc)
    db.commit()  # keep the user's message even if generation fails

    uid = str(user.id)
    try:
        if body.mode == "plan":
            result = generate_content_plan(body.message, body.n_examples, uid, body.sources, history=history)
            content, examples, is_error = result["plan"], result["used_examples"], False
        elif body.mode == "hashtags":
            content, examples, is_error = _hashtag_markdown(suggest_hashtags(body.message, uid, 12)), [], False
        else:
            result = chat_reply(body.message, body.n_examples, uid, body.sources, history=history)
            content, examples, is_error = result["reply"], result["used_examples"], False
    except Exception as exc:  # noqa: BLE001 - shown in the conversation instead of failing the request
        logger.exception("Generation failed")
        content, examples, is_error = f"Something went wrong: {exc}", [], True

    assistant_message = ChatMessage(conversation_id=conversation.id, user_id=user.id, role="assistant",
                                    mode=body.mode, content=content, examples=examples, is_error=is_error)
    db.add(assistant_message)
    conversation.updated_at = datetime.now(timezone.utc)
    db.flush()
    return {"conversation": conversation_dict(conversation), "user_message": message_dict(user_message),
            "assistant_message": message_dict(assistant_message)}
