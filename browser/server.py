"""Thin FastAPI wrapper exposing BrowserSession's tools over HTTP, so the
agent can drive the browser without embedding Playwright itself.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from pydantic import BaseModel

from browser.actions import DEFAULT_ACTION_TIMEOUT_MS, BrowserSession

session = BrowserSession()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    await session.start()
    yield
    await session.close()


app = FastAPI(lifespan=lifespan)


class NavigateRequest(BaseModel):
    url: str


class ClickRequest(BaseModel):
    selector: str | None = None
    text: str | None = None


class TypeTextRequest(BaseModel):
    selector: str
    text: str


class ExtractTextRequest(BaseModel):
    selector: str


class WaitForRequest(BaseModel):
    selector: str
    timeout_ms: int = DEFAULT_ACTION_TIMEOUT_MS


class HandleDialogRequest(BaseModel):
    action: str


@app.post("/navigate")
async def navigate(req: NavigateRequest) -> dict:
    return await session.navigate(req.url)


@app.post("/click")
async def click(req: ClickRequest) -> dict:
    return await session.click(selector=req.selector, text=req.text)


@app.post("/type_text")
async def type_text(req: TypeTextRequest) -> dict:
    return await session.type_text(req.selector, req.text)


@app.post("/extract_text")
async def extract_text(req: ExtractTextRequest) -> dict:
    return await session.extract_text(req.selector)


@app.post("/screenshot")
async def screenshot() -> dict:
    return await session.screenshot()


@app.post("/wait_for")
async def wait_for(req: WaitForRequest) -> dict:
    return await session.wait_for(req.selector, req.timeout_ms)


@app.post("/handle_dialog")
async def handle_dialog(req: HandleDialogRequest) -> dict:
    return await session.handle_dialog(req.action)


@app.get("/get_page_state")
async def get_page_state() -> dict:
    return await session.get_page_state()