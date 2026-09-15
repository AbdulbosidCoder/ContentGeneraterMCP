from fastapi import APIRouter

from app.api import accounts, auth, chat, content, generation, mcp_access, oauth, publish, research

api_router = APIRouter()
for module in (auth, accounts, content, research, generation, chat, publish, mcp_access):
    api_router.include_router(module.router)

oauth_router = oauth.router

__all__ = ["api_router", "oauth_router"]
