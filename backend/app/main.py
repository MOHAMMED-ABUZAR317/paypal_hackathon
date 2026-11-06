"""RainCheck API - application entrypoint.

Run locally:
    cd backend
    uvicorn app.main:app --reload --port 8000
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .config import REPO_ROOT, get_settings
from .db import SessionLocal, create_all
from .routers import ai, events, ledger, meta, operator, policies, pool, webhooks
from .seed import seed_if_empty
from .services.paypal import PayPalError
from .services.scheduler import scheduler_loop

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("raincheck")

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_all()
    if settings.auto_seed:
        db = SessionLocal()
        try:
            result = seed_if_empty(db)
            if result:
                logger.info("Demo pool seeded: %s members", result.get("members"))
        finally:
            db.close()

    task: asyncio.Task | None = None
    if settings.poll_interval_minutes > 0 and settings.env.lower() not in {"test", "ci"}:
        task = asyncio.create_task(scheduler_loop())
        logger.info("Live rainfall poller started")
    else:
        logger.info("Live poller disabled for this environment")

    yield

    if task is not None:
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):  # noqa: B014 - shutdown best effort
            pass


app = FastAPI(
    title="RainCheck API",
    version=__version__,
    description=(
        "Parametric income protection for gig workers. AI proposes the rule, "
        "deterministic code authorises the money, PayPal moves it.\n\n"
        "Sandbox prototype - not a licensed insurance product."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
    allow_headers=["Content-Type", "X-Operator-Key"],
)

for router in (
    meta.router,
    ai.router,
    policies.router,
    pool.router,
    events.router,
    ledger.router,
    operator.router,
    webhooks.router,
):
    app.include_router(router, prefix="/api")


@app.exception_handler(PayPalError)
async def paypal_error_handler(request: Request, exc: PayPalError) -> JSONResponse:
    return JSONResponse(
        status_code=502,
        content={"detail": f"PayPal error: {exc}", "path": str(request.url.path)},
    )


@app.exception_handler(RuntimeError)
async def runtime_error_handler(request: Request, exc: RuntimeError) -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content={
            "detail": str(exc),
            "hint": "The demo seed may not have run. Restart the API or POST /api/operator/demo/reset.",
        },
    )


@app.get("/", include_in_schema=False)
def root() -> dict:
    return {
        "app": "RainCheck",
        "version": __version__,
        "docs": "/docs",
        "health": "/api/health",
        "note": "Sandbox prototype. MOCK payout mode unless PayPal credentials are configured.",
    }


# Single-service deployment: if the React build exists, serve it from the same
# origin. API routes are registered first, so they always win.
_DIST = REPO_ROOT / "frontend" / "dist"
if _DIST.exists():
    app.mount("/", StaticFiles(directory=str(_DIST), html=True), name="ui")
