"""FastAPI entry point: ``uvicorn app.main:app`` (repo root on PYTHONPATH for ``common`` and ``rag``)."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import api_router, oauth_router
from app.services.meta_accounts import AssetNotFound
from app.services.research import QuotaExceeded
from common import config
from common.db import create_schema, wait_for_database
from common.meta import GraphAPIError, TokenExpiredError
from common.security import ConfigurationError, cipher
from rag import config as rag_config
from rag.generation import LLMError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("backend")


@asynccontextmanager
async def lifespan(_: FastAPI):
    wait_for_database()
    create_schema()
    cipher()  # fail fast if real Meta is configured without TOKEN_ENCRYPTION_KEY
    mock = config.MOCK_PREFIX
    logger.info(
        "Public URL: %s | Sign-in & Meta data: %s | LLM: %s | Embeddings: %s",
        config.public_base_url(),
        "REAL Facebook Login" if config.meta_configured() else f"{mock} demo Facebook login",
        f"Claude ({rag_config.anthropic_model()})" if rag_config.anthropic_api_key() else f"{mock} MockClient",
        f"OpenAI ({rag_config.openai_embedding_model()})" if rag_config.openai_api_key()
        else f"local ({rag_config.local_embedding_model()})",
    )
    yield


app = FastAPI(
    title="content-ai-generator",
    description="Multi-user Instagram/Facebook content intelligence: sync, classify, research, generate, publish.",
    version="2.0.0",
    lifespan=lifespan,
)
# Same-origin behind nginx; credentials are cookies, so don't allow arbitrary origins with credentials.
app.add_middleware(CORSMiddleware, allow_origins=[config.public_base_url()], allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])
app.include_router(api_router, prefix="/api")
app.include_router(oauth_router)


def _error(status: int, message: str) -> JSONResponse:
    return JSONResponse({"detail": message}, status_code=status)


@app.exception_handler(AssetNotFound)
async def _not_found(_: Request, exc: AssetNotFound) -> JSONResponse:
    return _error(404, str(exc))


@app.exception_handler(ValueError)
async def _bad_value(_: Request, exc: ValueError) -> JSONResponse:
    return _error(400, str(exc))


@app.exception_handler(QuotaExceeded)
async def _quota(_: Request, exc: QuotaExceeded) -> JSONResponse:
    return _error(429, str(exc))


@app.exception_handler(TokenExpiredError)
async def _expired(_: Request, exc: TokenExpiredError) -> JSONResponse:
    return _error(409, f"{exc} Reconnect Facebook on the Accounts tab.")


@app.exception_handler(GraphAPIError)
async def _graph(_: Request, exc: GraphAPIError) -> JSONResponse:
    return _error(502, str(exc))


@app.exception_handler(LLMError)
async def _llm(_: Request, exc: LLMError) -> JSONResponse:
    return _error(502, str(exc))


@app.exception_handler(ConfigurationError)
async def _config(_: Request, exc: ConfigurationError) -> JSONResponse:
    return _error(500, str(exc))


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
