"""Read-only story lookup; group replies always use the public view."""
from __future__ import annotations

import asyncio
from typing import Any

from .story import STATUSES, StoryError, StoryStore


class StoryTelegramAdapter:
    def __init__(self, store: StoryStore, admin_ids: frozenset[int]) -> None:
        self.store = store
        self.admin_ids = admin_ids

    async def story_command(self, update: Any, context: Any) -> None:
        message, user, chat = update.effective_message, update.effective_user, update.effective_chat
        if message is None or user is None or chat is None:
            return
        # Administrator status alone never authorizes leaking notes to a group.
        role = "gm" if user.id in self.admin_ids and getattr(chat, "type", None) == "private" else "player"
        query = " ".join(context.args or []).strip()
        try:
            if query.isdecimal():
                item = await asyncio.to_thread(self.store.get, role, int(query))
                text = f"#{item['id']} {item['title']}\n{item['world']} · {STATUSES[item['status']]}\n\n{item['body']}"
            else:
                rows = await asyncio.to_thread(self.store.list_entries, role, query=query, limit=10)
                heading = "故事档案（管理人私聊视图）" if role == "gm" else "已公开的故事档案"
                text = heading + "\n" + ("\n".join(
                    f"#{x['id']} {x['title']} · {x['world']} · {STATUSES[x['status']]}" for x in rows
                ) or "暂无匹配条目。")
                text += "\n\n/story 编号 查看正文；/story 关键词 搜索。\n每次列出最新 10 条，完整浏览与编辑请用 Web 故事档案。"
        except (StoryError, PermissionError) as exc:
            text = str(exc)
        # Plain text only. No Markdown/HTML interpretation of authored content.
        for offset in range(0, len(text), 3500):
            await message.reply_text(text[offset:offset + 3500], parse_mode=None)
