from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from common.models import Job


def enqueue(db: Session, user_id: uuid.UUID, kind: str, payload: dict[str, Any] | None = None) -> Job:
    """Queue a job, reusing an identical job that is still waiting."""
    payload = payload or {}
    existing = db.scalars(
        select(Job).where(Job.user_id == user_id, Job.kind == kind, Job.status == "queued")
    ).all()
    for job in existing:
        if job.payload == payload:
            return job
    job = Job(user_id=user_id, kind=kind, payload=payload)
    db.add(job)
    db.flush()
    return job


def job_dict(job: Job) -> dict[str, Any]:
    return {
        "id": str(job.id),
        "kind": job.kind,
        "payload": job.payload,
        "status": job.status,
        "result": job.result,
        "error": job.error,
        "created_at": job.created_at,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
    }
