"""Database schema (PostgreSQL). Post vectors live in Chroma, keyed by content_items.id."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def _user_fk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True)


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = _uuid_pk()
    # Facebook user id used to sign in. Kept on the user (not only on the connection) so
    # disconnecting Pages never locks the person out of their account.
    facebook_id: Mapped[str | None] = mapped_column(String(64))  # unique index: common.db migrations
    google_sub: Mapped[str | None] = mapped_column(String(255), unique=True)  # legacy, unused
    email: Mapped[str] = mapped_column(String(320), index=True)
    name: Mapped[str] = mapped_column(String(255))
    picture_url: Mapped[str | None] = mapped_column(Text)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_login_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class UserSession(Base):
    __tablename__ = "user_sessions"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = _user_fk()
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    user_agent: Mapped[str | None] = mapped_column(String(512))

    user: Mapped[User] = relationship()


class PendingSignup(Base):
    """A Facebook login by someone without an account yet, waiting for the sign-up form.

    Holds the (encrypted) Facebook token for at most 30 minutes, referenced by an
    HttpOnly cookie, so the token never reaches the browser.
    """

    __tablename__ = "pending_signups"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    fb_user_id: Mapped[str] = mapped_column(String(64))
    fb_name: Mapped[str] = mapped_column(String(255))
    fb_email: Mapped[str | None] = mapped_column(String(320))
    picture_url: Mapped[str | None] = mapped_column(Text)
    access_token_enc: Mapped[str] = mapped_column(Text)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scopes: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    is_mock: Mapped[bool] = mapped_column(Boolean, default=False)
    return_to: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = _user_fk()
    title: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)

    messages: Mapped[list[ChatMessage]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan", order_by="ChatMessage.created_at"
    )


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[uuid.UUID] = _uuid_pk()
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = _user_fk()
    role: Mapped[str] = mapped_column(String(20))  # user | assistant
    mode: Mapped[str] = mapped_column(String(20), default="chat")  # chat | plan | hashtags
    content: Mapped[str] = mapped_column(Text)
    examples: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    is_error: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    conversation: Mapped[Conversation] = relationship(back_populates="messages")


class LoginState(Base):
    """Short-lived OAuth `state` for Facebook sign-in/connect (CSRF)."""

    __tablename__ = "login_states"

    state_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    provider: Mapped[str] = mapped_column(String(20))
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    code_verifier: Mapped[str | None] = mapped_column(String(128))
    return_to: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class MetaConnection(Base):
    """One Facebook login granted by one user. Tokens are Fernet-encrypted."""

    __tablename__ = "meta_connections"
    __table_args__ = (UniqueConstraint("user_id", "fb_user_id"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = _user_fk()
    fb_user_id: Mapped[str] = mapped_column(String(64))
    fb_user_name: Mapped[str] = mapped_column(String(255))
    access_token_enc: Mapped[str] = mapped_column(Text)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scopes: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    is_mock: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(20), default="active")  # active | expired | error
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    assets: Mapped[list[MetaAsset]] = relationship(back_populates="connection", cascade="all, delete-orphan")


class MetaAsset(Base):
    """A Facebook Page or an Instagram professional account reachable through a connection."""

    __tablename__ = "meta_assets"
    __table_args__ = (UniqueConstraint("user_id", "kind", "external_id"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = _user_fk()
    connection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meta_connections.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(32))  # facebook_page | instagram_account
    external_id: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(255))
    username: Mapped[str | None] = mapped_column(String(255))
    picture_url: Mapped[str | None] = mapped_column(Text)
    followers_count: Mapped[int | None] = mapped_column(Integer)
    page_external_id: Mapped[str | None] = mapped_column(String(64))  # IG account -> linked Page
    page_token_enc: Mapped[str | None] = mapped_column(Text)  # Page access token (pages only)
    is_selected: Mapped[bool] = mapped_column(Boolean, default=True)
    sync_status: Mapped[str] = mapped_column(String(20), default="never")  # never | queued | syncing | ok | error
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    connection: Mapped[MetaConnection] = relationship(back_populates="assets")


class ContentCluster(Base):
    __tablename__ = "content_clusters"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = _user_fk()
    label: Mapped[str] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text)
    keywords: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    size: Mapped[int] = mapped_column(Integer, default=0)
    avg_engagement: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ContentItem(Base):
    """A post: the user's own (Instagram/Facebook), a competitor's, or from hashtag research."""

    __tablename__ = "content_items"
    __table_args__ = (
        UniqueConstraint("user_id", "platform", "source", "external_id"),
        Index("ix_content_user_source", "user_id", "source"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = _user_fk()
    asset_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meta_assets.id", ondelete="CASCADE"), index=True
    )
    source: Mapped[str] = mapped_column(String(20))  # own | competitor | hashtag
    platform: Mapped[str] = mapped_column(String(20))  # instagram | facebook
    external_id: Mapped[str] = mapped_column(String(128))
    author: Mapped[str | None] = mapped_column(String(255))
    caption: Mapped[str] = mapped_column(Text, default="")
    hashtags: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    media_type: Mapped[str] = mapped_column(String(32), default="UNKNOWN")
    media_url: Mapped[str | None] = mapped_column(Text)
    permalink: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    like_count: Mapped[int | None] = mapped_column(Integer)
    comments_count: Mapped[int | None] = mapped_column(Integer)
    shares_count: Mapped[int | None] = mapped_column(Integer)
    insights: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    content_types: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    content_type_scores: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    cluster_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("content_clusters.id", ondelete="SET NULL")
    )
    query: Mapped[str | None] = mapped_column(String(255))  # hashtag or competitor username
    is_mock: Mapped[bool] = mapped_column(Boolean, default=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class HashtagSearch(Base):
    """Tracks Instagram's limit of 30 unique hashtags per IG account per rolling 7 days."""

    __tablename__ = "hashtag_searches"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = _user_fk()
    ig_user_id: Mapped[str] = mapped_column(String(64), index=True)
    hashtag: Mapped[str] = mapped_column(String(100))
    hashtag_external_id: Mapped[str | None] = mapped_column(String(64))
    searched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PublishedPost(Base):
    __tablename__ = "published_posts"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = _user_fk()
    asset_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("meta_assets.id", ondelete="CASCADE"))
    platform: Mapped[str] = mapped_column(String(20))
    media_type: Mapped[str] = mapped_column(String(20))  # IMAGE | REELS | TEXT
    caption: Mapped[str] = mapped_column(Text, default="")
    media_url: Mapped[str | None] = mapped_column(Text)
    link_url: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending | publishing | published | failed
    external_id: Mapped[str | None] = mapped_column(String(128))
    permalink: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    is_mock: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Job(Base):
    """Postgres-backed work queue consumed by the worker service."""

    __tablename__ = "jobs"
    __table_args__ = (Index("ix_jobs_status_created", "status", "created_at"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = _user_fk()
    kind: Mapped[str] = mapped_column(String(40))  # sync_asset | classify | publish
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="queued")  # queued | running | succeeded | failed
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# --------------------------------------------------------------- MCP OAuth server
class OAuthClient(Base):
    """MCP clients registered via RFC 7591 dynamic client registration."""

    __tablename__ = "oauth_clients"

    client_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    client_secret_hash: Mapped[str | None] = mapped_column(String(64))
    client_name: Mapped[str | None] = mapped_column(String(255))
    redirect_uris: Mapped[list[str]] = mapped_column(ARRAY(Text))
    token_endpoint_auth_method: Mapped[str] = mapped_column(String(40), default="none")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class OAuthAuthorizationCode(Base):
    __tablename__ = "oauth_codes"

    code_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    client_id: Mapped[str] = mapped_column(String(64), ForeignKey("oauth_clients.client_id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID] = _user_fk()
    redirect_uri: Mapped[str] = mapped_column(Text)
    code_challenge: Mapped[str] = mapped_column(String(128))
    scopes: Mapped[list[str]] = mapped_column(ARRAY(String))
    resource: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OAuthToken(Base):
    __tablename__ = "oauth_tokens"

    id: Mapped[uuid.UUID] = _uuid_pk()
    access_token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    refresh_token_hash: Mapped[str | None] = mapped_column(String(64), unique=True)
    client_id: Mapped[str] = mapped_column(String(64), ForeignKey("oauth_clients.client_id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID] = _user_fk()
    scopes: Mapped[list[str]] = mapped_column(ARRAY(String))
    resource: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    refresh_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
