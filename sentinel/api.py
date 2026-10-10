"""Small HTTP surface: a liveness probe and an authenticated manual trigger."""

from __future__ import annotations

import hmac

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel

from sentinel.config import Settings, get_settings
from sentinel.queueing import enqueue_run

app = FastAPI(title="Compliance Sentinel", docs_url=None, redoc_url=None)


class TriggerRequest(BaseModel):
    repo: str | None = None
    full: bool = False
    simulate_amendment: bool = False


def require_token(
    authorization: str = Header(default=""), settings: Settings = Depends(get_settings)
) -> None:
    if not settings.trigger_token:
        raise HTTPException(status_code=503, detail="Manual trigger is not configured")
    supplied = authorization.removeprefix("Bearer ").strip()
    if not hmac.compare_digest(supplied, settings.trigger_token):
        raise HTTPException(status_code=401, detail="Invalid token")


@app.get("/health")
def health() -> dict:
    # Deliberately touches nothing: a probe that queried Postgres or Redis on
    # an interval would keep scale-to-zero resources awake around the clock.
    return {"status": "ok"}


@app.post("/trigger", status_code=202, dependencies=[Depends(require_token)])
async def trigger(request: TriggerRequest, settings: Settings = Depends(get_settings)) -> dict:
    data = {"trigger": "manual", **request.model_dump()}
    return {"job_id": await enqueue_run(settings, data)}
