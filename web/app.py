from __future__ import annotations

"""FastAPI application for Web Connect UI."""

from fastapi import FastAPI

from web.routes import router

app = FastAPI(title="Health Bot Connect", docs_url=None, redoc_url=None)
app.include_router(router)


@app.get("/health")
async def health():
    return {"status": "ok"}
