"""Optional story API. All content filtering happens before serialization."""
from __future__ import annotations

import asyncio
from typing import Any, Callable

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from ..story import StoryConflict, StoryError, StoryNotFound, StoryStore


def install_story_routes(
    app: FastAPI, store: StoryStore,
    require_role: Callable[[Request], str], require_gm: Callable[[Request], str],
    assistant: Any = None,
) -> None:
    async def call(function: Any, *args: Any, **kwargs: Any) -> Any:
        try:
            return await asyncio.to_thread(function, *args, **kwargs)
        except StoryConflict as exc:
            raise HTTPException(409, str(exc)) from exc
        except StoryNotFound as exc:
            raise HTTPException(404, str(exc)) from exc
        except StoryError as exc:
            raise HTTPException(400, str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc

    def response(data: Any) -> JSONResponse:
        # A shared browser must not retrieve a previous GM response from cache.
        return JSONResponse(data, headers={"Cache-Control": "no-store"})

    async def mutate(function: Any, *args: Any, **kwargs: Any) -> Any:
        operation = lambda: call(function, *args, **kwargs)
        return await assistant.change_context(operation) if assistant else await operation()

    async def payload(request: Request) -> dict[str, Any]:
        try:
            data = await request.json()
        except ValueError as exc:
            raise HTTPException(400, "请输入有效 JSON。") from exc
        if not isinstance(data, dict):
            raise HTTPException(400, "请求必须是对象。")
        return data

    @app.get("/api/story/progress")
    async def progress(request: Request) -> JSONResponse:
        require_role(request)
        return response(await call(store.progress))

    @app.put("/api/story/progress")
    async def change_progress(request: Request) -> JSONResponse:
        role = require_gm(request)
        data = await payload(request)
        return response(await mutate(store.set_progress, role, data.get("checkpoint"), data.get("label"), data.get("revision")))

    @app.get("/api/story/entries")
    async def entries(request: Request) -> JSONResponse:
        role = require_role(request)
        before = request.query_params.get("before_id")
        if before is not None and (not before.isdecimal() or int(before) < 1):
            raise HTTPException(400, "分页编号必须是正整数。")
        rows = await call(
            store.list_entries, role, query=request.query_params.get("q", ""),
            world=request.query_params.get("world", ""),
            status=request.query_params.get("status", ""),
            before_id=int(before) if before else None,
        )
        return response({"entries": rows, "next_before_id": rows[-1]["id"] if len(rows) == 50 else None})

    @app.get("/api/story/export")
    async def export(request: Request) -> JSONResponse:
        return response(await call(store.export, require_role(request)))

    @app.get("/api/story/entries/{entry_id}")
    async def entry(request: Request, entry_id: int) -> JSONResponse:
        return response(await call(store.get, require_role(request), entry_id))

    @app.get("/api/story/entries/{entry_id}/history")
    async def history(request: Request, entry_id: int) -> JSONResponse:
        return response(await call(store.history, require_gm(request), entry_id))

    @app.post("/api/story/entries")
    async def create(request: Request) -> JSONResponse:
        role = require_gm(request)
        return response(await mutate(store.save, role, await payload(request)))

    @app.put("/api/story/entries/{entry_id}")
    async def update(request: Request, entry_id: int) -> JSONResponse:
        role = require_gm(request)
        data = await payload(request)
        return response(await mutate(
            store.save, role, data, entry_id=entry_id, expected_revision=data.get("revision"),
        ))
