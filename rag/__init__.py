"""content-ai-generator RAG library: ingestion, retrieval and grounded generation.

Plain Python package with no web-framework dependency. Typical use::

    import asyncio
    from rag.ingestion import ingest_account
    from rag.generation import generate_content_plan, chat_reply

    asyncio.run(ingest_account("somebrand", limit=25))
    print(generate_content_plan("summer launch reel", n_examples=5)["plan"])
"""

__all__ = ["config"]
