"""GM-only writing actions; privacy state is visible to everyone in the room."""
from __future__ import annotations

import asyncio
from typing import Any

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

from ..assistant import AssistantError, WritingAssistant, ids
from ..story import StoryError


def install_assistant_routes(app, assistant: WritingAssistant, require_role, require_gm, broadcast):
    def response(value):
        return JSONResponse(value, headers={"Cache-Control": "no-store"})

    async def body(request: Request) -> dict[str, Any]:
        try:
            data = await request.json()
        except ValueError:
            raise HTTPException(400, "请输入有效 JSON。") from None
        if not isinstance(data, dict):
            raise HTTPException(400, "请求必须是对象。")
        return data

    async def run(operation):
        try:
            return await operation
        except (AssistantError, StoryError) as exc:
            raise HTTPException(409, str(exc)) from None

    @app.get("/api/assistant/privacy")
    async def privacy(request: Request):
        role = require_role(request)
        state = await asyncio.to_thread(assistant.privacy.state)
        if role == "gm":
            state["api_configured"] = assistant.configured
        return response(state)

    @app.put("/api/assistant/privacy")
    async def toggle(request: Request):
        require_gm(request)
        data = await body(request)
        state = await run(assistant.set_privacy(data.get("enabled")))
        broadcast("privacy", state)
        return response(state)

    @app.get("/api/assistant/messages")
    async def messages(request: Request):
        require_gm(request)
        before = request.query_params.get("before_id")
        if before is not None and (not before.isdecimal() or not 0 < int(before) < 2**63):
            raise HTTPException(400, "分页编号必须为正整数。")
        rows = await asyncio.to_thread(assistant.privacy.eligible, int(before) if before else None)
        return response({"messages": rows, "next_before_id": rows[-1]["id"] if len(rows) == 100 else None})

    @app.post("/api/assistant/protect")
    async def protect(request: Request):
        require_gm(request)
        data = await body(request)
        try:
            selected = ids(data.get("message_ids", []))
        except AssistantError as exc:
            raise HTTPException(400, str(exc)) from None
        await run(assistant.protect(selected))
        broadcast("privacy", assistant.privacy.state())
        return response({"ok": True})

    @app.get("/api/assistant/notes")
    async def notes(request: Request):
        require_gm(request)
        before = request.query_params.get("before_id")
        if before is not None and (not before.isdecimal() or not 0 < int(before) < 2**63):
            raise HTTPException(400, "分页编号必须为正整数。")
        rows = await asyncio.to_thread(assistant.notebook.eligible_ai_entries, int(before) if before else 2**63-1) if assistant.notebook else []
        return response({"entries": rows, "next_before_id": rows[-1]["id"] if len(rows) == 100 else None})

    @app.post("/api/assistant/preview")
    async def preview(request: Request):
        require_gm(request)
        return response(await run(assistant.preview(await body(request))))

    @app.post("/api/assistant/export")
    async def export(request: Request):
        require_gm(request)
        return response(await run(assistant.preview(await body(request), reviewed=True)))

    @app.post("/api/assistant/draft")
    async def draft(request: Request):
        require_gm(request)
        return response(await run(assistant.draft(await body(request))))
