"""Background worker: consumes the Postgres job queue and schedules periodic re-syncs.

Runs from the backend image (it shares the app services, ``common`` and ``rag``):
    python /code/worker/worker.py
"""

from __future__ import annotations

import logging
import signal
import time
import traceback
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, text, update

from app.services.jobs import enqueue
from app.services.tasks import HANDLERS
from common import config
from common.db import create_schema, session_factory, wait_for_database
from common.models import Job, MetaAsset, MetaConnection

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)  # its INFO lines include Graph URLs with access tokens
logger = logging.getLogger("worker")

POLL_SECONDS = 2
STALE_AFTER = timedelta(minutes=30)
MAX_ATTEMPTS = 3
_running = True


def _stop(*_):
    global _running
    _running = False


def claim_job() -> uuid.UUID | None:
    """Atomically take the oldest queued job (safe with several worker replicas)."""
    with session_factory()() as db:
        job_id = db.execute(text("""
            UPDATE jobs SET status = 'running', started_at = now(), attempts = attempts + 1
            WHERE id = (
                SELECT id FROM jobs WHERE status = 'queued' ORDER BY created_at
                FOR UPDATE SKIP LOCKED LIMIT 1
            )
            RETURNING id
        """)).scalar()
        db.commit()
        return job_id


def run_job(job_id: uuid.UUID) -> None:
    with session_factory()() as db:
        job = db.get(Job, job_id)
        handler = HANDLERS.get(job.kind)
        logger.info("Running %s job %s for user %s", job.kind, job.id, job.user_id)
        try:
            if handler is None:
                raise RuntimeError(f"Unknown job kind {job.kind!r}")
            result = handler(db, job.user_id, dict(job.payload or {}))
            db.commit()
            job = db.get(Job, job_id)
            job.status, job.result, job.error = "succeeded", result, None
        except Exception as exc:  # noqa: BLE001
            logger.error("Job %s failed: %s\n%s", job_id, exc, traceback.format_exc())
            db.rollback()
            job = db.get(Job, job_id)
            job.status, job.error = "failed", f"{type(exc).__name__}: {exc}"[:2000]
        job.finished_at = datetime.now(timezone.utc)
        db.commit()


def housekeeping() -> None:
    """Requeue jobs orphaned by a crashed worker and schedule periodic re-syncs."""
    now = datetime.now(timezone.utc)
    with session_factory()() as db:
        db.execute(update(Job).where(Job.status == "running", Job.started_at < now - STALE_AFTER,
                                     Job.attempts < MAX_ATTEMPTS).values(status="queued"))
        db.execute(update(Job).where(Job.status == "running", Job.started_at < now - STALE_AFTER)
                   .values(status="failed", error="Timed out", finished_at=now))
        due = now - timedelta(hours=config.sync_interval_hours())
        assets = db.scalars(
            select(MetaAsset).join(MetaConnection)
            .where(MetaAsset.is_selected.is_(True), MetaConnection.status == "active",
                   MetaAsset.sync_status.in_(("ok", "error")), MetaAsset.last_synced_at < due)
        ).all()
        for asset in assets:
            asset.sync_status = "queued"
            enqueue(db, asset.user_id, "sync_asset", {"asset_id": str(asset.id)})
        if assets:
            logger.info("Scheduled periodic re-sync for %d assets", len(assets))
        db.commit()


def main() -> None:
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    wait_for_database()
    create_schema()
    logger.info("Worker started (Meta: %s)", "REAL" if config.meta_configured() else f"{config.MOCK_PREFIX} demo")
    last_housekeeping = 0.0
    while _running:
        if time.monotonic() - last_housekeeping > 60:
            try:
                housekeeping()
            except Exception:  # noqa: BLE001
                logger.exception("Housekeeping failed")
            last_housekeeping = time.monotonic()
        job_id = claim_job()
        if job_id is None:
            time.sleep(POLL_SECONDS)
            continue
        run_job(job_id)
    logger.info("Worker stopped")


if __name__ == "__main__":
    main()
