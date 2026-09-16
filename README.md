# content-ai-generator

A multi-user service that turns a brand's Instagram and Facebook history into content strategy.
Each user signs in with **Facebook**, which also connects **their own** Facebook Pages and
Instagram professional accounts. Returning users go straight in; new users fill in a short
sign-up form (name, email). The app is a chat-first workspace: saved conversations in a sidebar,
with content plans and hashtag ideas as chat modes. The service:

- **syncs** their posts and insights in the background,
- **classifies** every post by content type (interactive, educational, party/event,
  critical/opinion, promotional, …) and **clusters** posts into topics without supervision,
- runs **hashtag research** (top/recent posts for a hashtag) and **competitor lookups**,
- **suggests hashtags** for drafts, including for past posts published without any,
- generates **content plans** and chat answers grounded in what actually performed,
- **publishes** to Instagram and Facebook Pages,
- exposes all of this as an **OAuth-protected MCP server**, so each user can connect Claude
  (or any MCP client) to their own account.

Everything runs with no credentials in **mock mode**, and each integration switches to the
real API as soon as its credential is configured.

## Architecture

```
 Browser ─┐                                     ┌──────────── docker compose ────────────────────────────┐
 Claude / │ :80   nginx                         │                                                        │
 MCP      ├──────► /            ─► frontend      │  React SPA (Facebook sign-in, chat + sidebar, Accounts,│
 clients  │        /api/, /oauth/ ─► backend ─────┼─► FastAPI  ── Content, Research, Publish, MCP access)   │
          │        /mcp, /.well-known/            │    │ imports common/ (DB, crypto, Meta Login + Graph)  │
          │          oauth-protected-resource     │    │ imports rag/    (embed, classify, cluster, generate)
          │                     ─► mcp ───────────┼─► FastMCP (streamable-HTTP, OAuth resource server)     │
          │        /media/      ─► uploaded media │    └─ validates tokens + calls backend API as the user  │
          │                                       │  worker ── Postgres job queue: sync · classify · publish│
          │                                       │  postgres ── users, sessions, ENCRYPTED Meta tokens,   │
          │                                       │              posts, clusters, jobs, OAuth clients/tokens
          │                                       │  chroma (server) ── one vector per post, tagged user_id │
          └───────────────────────────────────────┴────────────────────────────────────────────────────────┘
                     Facebook Login ◄── sign in + Graph API (per-user tokens)          Anthropic ◄── Claude
```

| Directory   | Role |
|-------------|------|
| `common/`   | Shared library: settings, SQLAlchemy models, Fernet token encryption, Facebook Login, and a Graph API client (`GraphClient`) with a same-interface `MockGraphClient`. |
| `rag/`      | Plain Python library, with no database or web framework: embeddings (OpenAI or local), user-scoped Chroma store, retrieval, content-type classification, KMeans clustering, hashtag suggestions, Claude/mock generation, and prompts. |
| `backend/`  | FastAPI app: auth, account connections, content API, research, generation, publishing, and the OAuth 2.1 authorization server for MCP clients. |
| `worker/`   | Runs from the backend image (as does the `chroma` server). Processes queued jobs (`FOR UPDATE SKIP LOCKED`), re-syncs accounts every `SYNC_INTERVAL_HOURS`, and requeues stalled jobs. |
| `mcp/`      | Lightweight MCP server. Every tool call runs as the token's user by calling the backend API with that user's token. |
| `frontend/` | React + Vite single-page app, with no router or state library. |
| `nginx/`    | The single public port. |

### How a user's data flows

1. **Continue with Facebook** (Facebook Login for Business). The code is exchanged for a
   long-lived user token (about 60 days) and the Facebook user id is looked up in `users.facebook_id`:
   - **Known user:** signed in straight away; their connection (token, Pages, Instagram) is refreshed.
   - **New user:** the token is parked encrypted in `pending_signups` for 30 minutes, referenced by an
     HttpOnly cookie, and the app shows a sign-up form (name, email). Submitting it creates the
     account and connection. Email verification is not implemented yet.

   The session is an HttpOnly, SameSite=Lax cookie; only its SHA-256 hash is stored.
2. **Accounts.** The service lists the user's Pages and linked Instagram professional accounts and
   stores the Page tokens. Page tokens derived from a long-lived user token don't expire, so syncing
   keeps working. All tokens are Fernet-encrypted in PostgreSQL. More Facebook logins can be
   connected from the Accounts page.
3. **Sync (worker).** Instagram media plus insights (reach, saves, shares, views) and Page posts
   (reactions, comments, shares) go into `content_items`. Each post is then embedded into
   Chroma with `user_id` metadata. Every query filters on `user_id`.
4. **Classify (worker).** Content types are assigned with Claude structured outputs when
   `ANTHROPIC_API_KEY` is set. Otherwise they come from zero-shot embedding similarity to the
   label descriptions, plus keyword cues. Clustering is KMeans over post embeddings, with k
   chosen by silhouette score. Claude names the clusters, or TF-IDF keywords are used without a
   key. Content-type and cluster performance appears on the **Content** tab.
5. **Research.** Instagram Hashtag Search is limited by Meta to 30 unique hashtags per account
   per rolling 7 days; the app tracks and shows that quota. `business_discovery` fetches public
   Business/Creator competitors. Results are classified and added to the user's library
   (`source=hashtag|competitor`).
6. **Chat.** Conversations are saved (`conversations`, `chat_messages`). Each message runs in one of
   three modes: *Chat* (multi-turn, the last 12 messages are sent as context), *Content plan* (3
   post ideas) or *Hashtags*. Every reply retrieves the user's most similar posts, selectable by
   source, and passes them to Claude with engagement, content-type and hashtag statistics. Claude is
   told never to copy captions. The posts a reply was grounded in are shown under it.
7. **Publish.** Instagram uses a media container, then `media_publish` (images and Reels).
   Pages use `/feed` or `/photos`. Publishing runs as a job, and the post is re-synced afterwards.

### MCP with per-user OAuth

The MCP server implements the MCP authorization spec as a **resource server**, and the backend
is the **authorization server**:

```
MCP client ──► POST /mcp                       ─► 401 + WWW-Authenticate: resource_metadata=…
           ──► GET /.well-known/oauth-protected-resource/mcp    (points to the authorization server)
           ──► GET /.well-known/oauth-authorization-server      (RFC 8414 metadata)
           ──► POST /oauth/register                             (RFC 7591 dynamic registration)
           ──► browser: /oauth/authorize ─► Facebook sign-in ─► consent page ─► redirect with code
           ──► POST /oauth/token (PKCE S256, resource=…/mcp)    ─► access token (1 h) + refresh token (30 d, rotated)
           ──► POST /mcp with Bearer token ─► mcp introspects via backend (internal only) ─► tools run as that user
```

Tools: `list_my_accounts`, `get_content_overview`, `list_my_content`, `search_my_content`,
`generate_content_plan`, `suggest_hashtags`, `research_hashtag`, `research_competitor`,
`search_ads_library`, `publish_instagram_post`, `publish_facebook_page_post`,
`get_publish_status`. The publish tools are annotated as destructive. Users see and revoke
authorized clients on the **MCP access** page.

```bash
claude mcp add --transport http content-ai-generator http://localhost/mcp
```

Remote clients such as Claude on the web need `PUBLIC_BASE_URL` to be a public HTTPS URL.

**Connection links (no OAuth).** On the **MCP access** page a user can create a personal token
and get a URL like `{MCP_PUBLIC_URL}/mcp?token=mcp_...`. The MCP server moves the token into the
`Authorization` header, and the backend resolves it to that user, exactly like an OAuth token.
Tokens don't expire, are stored hashed, can be revoked, and are stripped from nginx and MCP
access logs. `MCP_PUBLIC_URL` (default: `PUBLIC_BASE_URL`) lets MCP live on its own host, such as
`https://mcp.example.com`, while sign-in stays on `PUBLIC_BASE_URL`.

## Run it

Requirements: Docker with Compose v2.24 or newer.

```bash
cp .env.example .env     # optional; blank credentials = mock mode
docker compose up --build
```

Open <http://localhost>:

1. **Continue with Facebook.** In mock mode, type a "Facebook name". A new name shows the sign-up
   form (name, email); the same name later signs you straight back in. Different names are
   different users with fully separate data. Each demo account gets an Instagram account and two
   Pages, and about 300 posts sync within a minute.
2. **Chat** (the home screen): ask about your content, or switch the composer to *Content plan*
   or *Hashtags*. Conversations are saved in the sidebar.
3. **Content** shows which content types and topic clusters perform best, and your best hashtags.
4. **Research** covers hashtag research (with quota), competitor lookup, hashtag suggestions,
   and posts that were published without hashtags.
5. **Publish** posts to Instagram or a Page, with hashtag suggestions. Mock publishing posts nothing.
6. **Accounts** manages connected Pages and Instagram accounts; **MCP access** shows the server URL
   and the clients you've authorized.

The first build downloads CPU-only PyTorch and bakes the local embedding model into the image,
so it takes a few minutes. Data lives in the `postgres_data`, `chroma_data` and `media_data`
volumes (`docker compose down -v` wipes them).

## Mock mode

| Integration | Real when set | Without it |
|---|---|---|
| Facebook sign-in + Facebook/Instagram data | `META_APP_ID`, `META_APP_SECRET` (+ `TOKEN_ENCRYPTION_KEY`) | A demo Facebook login by name (disabled once a Meta app is configured) creates demo connections. `MockGraphClient` returns seeded, realistic posts that mix content styles, with engagement driven by hidden style, format and hashtag weights, plus mock insights, hashtag search, competitors, ads and publishing. Everything is labelled `[MOCK]` / `is_mock`. |
| Claude | `ANTHROPIC_API_KEY` | Templated plans and replies built from real retrieval statistics, embedding-based classification, and keyword cluster names. |
| Embeddings | `OPENAI_API_KEY` | Local sentence-transformers model. |

Connections remember whether they were created in mock mode, so adding Meta credentials
later doesn't break existing demo accounts.

## Going live

1. **Meta:** create a Business app, add *Facebook Login for Business*, and register **both** redirect
   URIs: `{PUBLIC_BASE_URL}/api/auth/facebook/callback` (sign-in) and
   `{PUBLIC_BASE_URL}/api/connections/meta/callback` (connecting more logins). Optionally create a
   Login configuration and set `META_LOGIN_CONFIG_ID`; include `email` if you want the sign-up
   form pre-filled.
2. Set `TOKEN_ENCRYPTION_KEY` (a Fernet key) and `INTERNAL_SERVICE_TOKEN`. The backend refuses
   to start with Meta configured but no encryption key.
3. Set `PUBLIC_BASE_URL` to your HTTPS domain and put TLS in front of nginx. Meta must be able
   to download media you publish, and remote MCP clients require HTTPS.
4. `docker compose up -d`.
5. Before production, add email verification to sign-up (not implemented yet).

**Meta restrictions to plan for:**
- Until Meta approves your app through **App Review** (Advanced Access for each permission) and
  **Business Verification**, only people with a role on the app (admins, developers, testers)
  can connect. Permissions requested: `pages_show_list`, `pages_read_engagement`,
  `pages_manage_posts`, `read_insights`, `business_management`, `instagram_basic`,
  `instagram_manage_insights`, `instagram_content_publish`. Remove any you don't need.
- Instagram must be a **Business or Creator** account linked to a Facebook Page. Competitor
  lookups only work for public Business/Creator accounts; private and personal accounts can't
  be read.
- Hashtag Search: 30 unique hashtags per account per 7 days, and results don't include author
  usernames. Instagram publishing has a daily quota (shown via
  `/api/assets/{id}/publishing-limit`).
- Insight metric names change between Graph API versions. The client falls back to a minimal
  metric set and skips insights it can't read.
- Outside the EU/UK the Ads Library API only returns social issue, electoral and political ads.

## API overview

All endpoints under `/api` require a session cookie or an MCP bearer token, and always act on
that user's data only.

| Area | Endpoints |
|---|---|
| Auth | `GET /auth/config`, `GET /auth/facebook/login`, `GET /auth/facebook/callback`, `POST /auth/demo-facebook`, `GET /auth/signup`, `POST /auth/signup`, `POST /auth/logout`, `GET /auth/me` |
| Chat | `GET /conversations`, `GET /conversations/{id}`, `PATCH /conversations/{id}`, `DELETE /conversations/{id}`, `POST /chat` (`mode`: chat, plan or hashtags) |
| Accounts | `GET /connections`, `GET /connections/meta/login`, `GET /connections/meta/callback`, `DELETE /connections/{id}`, `PATCH /assets/{id}`, `POST /assets/{id}/sync`, `POST /sync`, `GET /jobs` |
| Content | `GET /content`, `GET /content/overview`, `GET /content/search`, `POST /content/classify` |
| Research | `GET /hashtags/quota`, `POST /hashtags/research`, `POST /hashtags/suggest`, `GET /hashtags/missing`, `POST /competitors/research`, `POST /ads/search` |
| Generation | `POST /plan` (one-off plan, used by the MCP server) |
| Publishing | `POST /media`, `POST /posts`, `GET /posts`, `GET /assets/{id}/publishing-limit` |
| MCP | `GET /mcp`, `DELETE /mcp/grants/{client_id}`, `POST /mcp/tokens`, `DELETE /mcp/tokens/{id}` |
| OAuth (root) | `/.well-known/oauth-authorization-server`, `/oauth/register`, `/oauth/authorize`, `/oauth/token`, `/oauth/revoke` |

## Notes

- Chroma runs as a **server** (`chroma` service). The backend and worker are separate processes
  that both write vectors, and embedded Chroma is not safe to open from two processes at once.
  Using `rag` as a single-process library without `CHROMA_HOST` falls back to embedded mode.
- The schema is created at startup (`create_all` under an advisory lock). Add Alembic migrations
  before changing models in production.
- Vectors of different embedding models can't share a collection, so the collection name
  includes the model. After adding or removing `OPENAI_API_KEY`, re-sync and re-classify.
- `rag` stays framework-free and database-free. It receives plain dicts, so it can be reused in
  notebooks or other services.
