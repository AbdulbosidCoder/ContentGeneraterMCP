from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Source = Literal["own", "competitor", "hashtag"]


class DemoFacebookLogin(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)
    return_to: str | None = Field(None, max_length=2000)


class SignupRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    email: str = Field(..., min_length=3, max_length=320)


class AssetUpdate(BaseModel):
    is_selected: bool


class ClassifyRequest(BaseModel):
    force: bool = False


class HashtagResearchRequest(BaseModel):
    hashtag: str = Field(..., min_length=1, max_length=100)
    asset_id: str | None = Field(None, description="Instagram account to search as (defaults to the first one)")
    edge: Literal["top_media", "recent_media"] = "top_media"
    limit: int = Field(25, ge=1, le=50)


class HashtagSuggestRequest(BaseModel):
    caption: str = Field(..., min_length=1, max_length=2200)
    count: int = Field(10, ge=1, le=30)


class CompetitorRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=31)
    asset_id: str | None = None
    limit: int = Field(25, ge=1, le=50)


class AdsSearchRequest(BaseModel):
    search_terms: str = Field(..., min_length=1, max_length=200)
    country: str = Field("US", pattern=r"^[A-Za-z]{2}$")
    limit: int = Field(20, ge=1, le=50)


class PlanRequest(BaseModel):
    topic: str = Field(..., min_length=1, max_length=2000)
    n_examples: int = Field(6, ge=1, le=20)
    sources: list[Source] | None = None


class ChatSendRequest(BaseModel):
    conversation_id: str | None = None
    message: str = Field(..., min_length=1, max_length=4000)
    mode: Literal["chat", "plan", "hashtags"] = "chat"
    sources: list[Source] | None = None
    n_examples: int = Field(6, ge=1, le=20)


class ConversationRename(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)


class PublishRequest(BaseModel):
    asset_id: str
    caption: str = Field("", max_length=2200)
    media_type: Literal["IMAGE", "REELS", "TEXT"] = "IMAGE"
    media_url: str | None = Field(None, max_length=2000)
    link_url: str | None = Field(None, max_length=2000)
