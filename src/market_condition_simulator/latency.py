from __future__ import annotations

from datetime import datetime, timedelta


def compute_execution_time(submitted_at: datetime, latency_ms: int) -> datetime:
    if latency_ms < 0:
        raise ValueError("latency_ms must be non-negative")
    if submitted_at.tzinfo is None:
        raise ValueError("submitted_at must be timezone-aware")
    return submitted_at + timedelta(milliseconds=latency_ms)


def latency_elapsed_ms(submitted_at: datetime, executed_at: datetime) -> int:
    if submitted_at.tzinfo is None or executed_at.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware")
    delta = executed_at - submitted_at
    return int(delta.total_seconds() * 1000)
