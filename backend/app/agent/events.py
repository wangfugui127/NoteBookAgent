from __future__ import annotations

import json

from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import RunEvent


class EventStore:
    def __init__(self, redis_url: str) -> None:
        self.redis = Redis.from_url(redis_url, decode_responses=True)

    async def emit(
        self, db: AsyncSession, run_id: str, event_type: str, payload: dict[str, object]
    ) -> RunEvent:
        current = await db.scalar(
            select(func.max(RunEvent.sequence)).where(RunEvent.run_id == run_id)
        )
        event = RunEvent(
            run_id=run_id,
            sequence=int(current or 0) + 1,
            event_type=event_type,
            payload=payload,
        )
        db.add(event)
        await db.flush()
        try:
            await self.redis.publish(
                f"agent-run:{run_id}",
                json.dumps(
                    {"sequence": event.sequence, "type": event_type, "payload": payload},
                    ensure_ascii=False,
                    default=str,
                ),
            )
        except Exception:
            pass
        return event

    async def close(self) -> None:
        await self.redis.aclose()
