# Build context is the repository root (see docker-compose.yaml): the image gets
# backend/, worker/ and the shared common/ and rag/ packages. Used by both the
# `backend` and `worker` services.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/code:/code/backend \
    HF_HOME=/opt/hf-cache \
    ANONYMIZED_TELEMETRY=False

WORKDIR /code

# CPU-only torch keeps the image far smaller than the default CUDA build.
RUN pip install torch --index-url https://download.pytorch.org/whl/cpu

COPY rag/requirements.txt rag/requirements.txt
COPY common/requirements.txt common/requirements.txt
COPY backend/requirements.txt backend/requirements.txt
RUN pip install -r rag/requirements.txt -r common/requirements.txt -r backend/requirements.txt

# Bake the local embedding model into the image so mock mode works offline.
ARG LOCAL_EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2
RUN python -c "import sys; from sentence_transformers import SentenceTransformer; SentenceTransformer(sys.argv[1])" "${LOCAL_EMBEDDING_MODEL}"
# Use the baked-in model without contacting the Hugging Face Hub at runtime.
ENV HF_HUB_OFFLINE=1

COPY common common
COPY rag rag
COPY backend backend
COPY worker worker

WORKDIR /code/backend
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=30s --retries=10 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
