"""Privacy control for Telegram; writing itself uses the Web preview flow."""
import asyncio

from .assistant import PrivacyStore


class PrivacyTelegramAdapter:
    def __init__(self, store: PrivacyStore, admin_ids: frozenset[int]):
        self.store, self.admin_ids = store, admin_ids

    async def privacy_command(self, update, context):
        message, user = update.effective_message, update.effective_user
        if message is None or user is None:
            return
        args = context.args or []
        if args:
            if user.id not in self.admin_ids:
                await message.reply_text("仅管理人可以切换隐私模式。")
                return
            if args not in (["on"], ["off"]):
                await message.reply_text("用法：/privacy 查看；/privacy on 开启；/privacy off 关闭。")
                return
            await asyncio.to_thread(self.store.set, args[0] == "on")
        state = await asyncio.to_thread(self.store.state)
        await message.reply_text(
            "隐私模式：" + ("开" if state["enabled"] else "关")
            + "。开启期间的聊天永久排除出 AI 上下文。AI 写作与材料预览请使用 Web；Telegram 群聊不会自动收集给 AI。"
        )
