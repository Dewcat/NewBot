"""跑团角色扮演聊天存储（2026-07-26 裁定 §7.5-3）。

战斗频道同时是跑团主频道：聊天记录跨战斗连续，战斗播报按时间穿插其中。
- 玩家发言固定以玩家身份（speech）。
- 管理人输入 ``角色名：“内容”``（中英文冒号、中英文引号均可）即以该 NPC
  身份发言；不符合该格式的输入一律视为旁白（narration）。
- 支持编辑、撤回（软删除）、按角色标记已读、内容搜索。

本模块只做持久化与规则校验，不做任何广播；SSE 推送由 Web 传输层负责。
"""

from __future__ import annotations

import re
from typing import Any

from .db import Database
from .models import BattleRuleError


ROLE_GM = "gm"
ROLE_PLAYER = "player"
PLAYER_SPEAKER = "经理"

MAX_CONTENT_LENGTH = 2000
MAX_SPEAKER_LENGTH = 40

# 角色名：“内容” / 角色名:"内容" —— 冒号与引号中英文混用均接受。
_SPEECH_RE = re.compile(
    r"^\s*(?P<speaker>[^：:\n]{1,40}?)\s*[：:]\s*[“\"](?P<content>.+)[”\"]\s*$",
    re.S,
)


def _row_to_dict(row: Any) -> dict[str, Any]:
    item = dict(row)
    if item.get("revoked"):
        item["content"] = ""
    return item


class ChatStore:
    def __init__(self, database: Database) -> None:
        self.database = database

    # -- 写入 ----------------------------------------------------------
    def post(self, author_role: str, raw_content: str) -> dict[str, Any]:
        if author_role not in (ROLE_GM, ROLE_PLAYER):
            raise BattleRuleError("未知的聊天身份。")
        text = str(raw_content or "").strip()
        if not text:
            raise BattleRuleError("消息内容不能为空。")
        if len(text) > MAX_CONTENT_LENGTH:
            raise BattleRuleError(f"消息过长（上限 {MAX_CONTENT_LENGTH} 字）。")

        if author_role == ROLE_PLAYER:
            kind, speaker, content = "speech", PLAYER_SPEAKER, text
        else:
            match = _SPEECH_RE.match(text)
            if match:
                kind = "speech"
                speaker = match.group("speaker").strip()
                content = match.group("content").strip()
                if not content:
                    raise BattleRuleError("发言内容不能为空。")
            else:
                kind, speaker, content = "narration", "", text

        with self.database.transaction() as connection:
            cursor = connection.execute(
                f"""
                INSERT INTO chat_messages(
                    author_role,kind,speaker,content,
                    read_by_gm,read_by_player,ai_excluded
                ) VALUES(?,?,?,?,?,?,(SELECT enabled FROM ai_privacy WHERE id=1))
                """,
                (
                    author_role, kind, speaker, content,
                    1 if author_role == ROLE_GM else 0,
                    1 if author_role == ROLE_PLAYER else 0,
                ),
            )
            row = connection.execute(
                "SELECT * FROM chat_messages WHERE id=?", (cursor.lastrowid,)
            ).fetchone()
            return _row_to_dict(row)

    def edit(self, message_id: int, author_role: str, raw_content: str) -> dict[str, Any]:
        text = str(raw_content or "").strip()
        if not text:
            raise BattleRuleError("消息内容不能为空。")
        if len(text) > MAX_CONTENT_LENGTH:
            raise BattleRuleError(f"消息过长（上限 {MAX_CONTENT_LENGTH} 字）。")
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM chat_messages WHERE id=?", (int(message_id),)
            ).fetchone()
            if row is None:
                raise BattleRuleError("该消息不存在。")
            if row["author_role"] != author_role:
                raise BattleRuleError("只能编辑自己发送的消息。")
            if row["revoked"]:
                raise BattleRuleError("该消息已撤回，无法编辑。")
            # 编辑时按原 kind 重新解析：GM 修正 NPC 台词时格式仍然生效。
            speaker, kind, content = row["speaker"], row["kind"], text
            if author_role == ROLE_GM:
                match = _SPEECH_RE.match(text)
                if match:
                    kind = "speech"
                    speaker = match.group("speaker").strip()
                    content = match.group("content").strip()
                else:
                    kind, speaker = "narration", ""
            connection.execute(
                """
                UPDATE chat_messages
                SET content=?,speaker=?,kind=?,edited_at=CURRENT_TIMESTAMP,
                    ai_excluded=MAX(ai_excluded,(SELECT enabled FROM ai_privacy WHERE id=1))
                WHERE id=?
                """,
                (content, speaker, kind, int(message_id)),
            )
            connection.execute("UPDATE ai_privacy SET epoch=epoch+1 WHERE id=1")
            updated = connection.execute(
                "SELECT * FROM chat_messages WHERE id=?", (int(message_id),)
            ).fetchone()
            return _row_to_dict(updated)

    def revoke(self, message_id: int, author_role: str) -> dict[str, Any]:
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM chat_messages WHERE id=?", (int(message_id),)
            ).fetchone()
            if row is None:
                raise BattleRuleError("该消息不存在。")
            if row["author_role"] != author_role:
                raise BattleRuleError("只能撤回自己发送的消息。")
            connection.execute(
                "UPDATE chat_messages SET revoked=1,content='' WHERE id=?",
                (int(message_id),),
            )
            connection.execute("UPDATE ai_privacy SET epoch=epoch+1 WHERE id=1")
            updated = connection.execute(
                "SELECT * FROM chat_messages WHERE id=?", (int(message_id),)
            ).fetchone()
            return _row_to_dict(updated)

    # -- 已读 ----------------------------------------------------------
    def mark_read(self, reader_role: str, up_to_id: int) -> int:
        if reader_role not in (ROLE_GM, ROLE_PLAYER):
            raise BattleRuleError("未知的聊天身份。")
        column = "read_by_gm" if reader_role == ROLE_GM else "read_by_player"
        with self.database.transaction() as connection:
            cursor = connection.execute(
                f"UPDATE chat_messages SET {column}=1 WHERE id<=? AND {column}=0",
                (int(up_to_id),),
            )
            return int(cursor.rowcount or 0)

    # -- 读取 ----------------------------------------------------------
    def list_recent(
        self, *, before_id: int | None = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        """按时间升序返回一窗消息；``before_id`` 用于向上翻页。"""
        limit = max(1, min(int(limit), 200))
        with self.database.reading() as connection:
            if before_id is None:
                rows = connection.execute(
                    "SELECT * FROM chat_messages ORDER BY id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM chat_messages WHERE id<? ORDER BY id DESC LIMIT ?",
                    (int(before_id), limit),
                ).fetchall()
            return [_row_to_dict(row) for row in reversed(rows)]

    def search(self, query: str, *, limit: int = 30) -> list[dict[str, Any]]:
        text = str(query or "").strip()
        if not text:
            return []
        pattern = "%" + text.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_") + "%"
        with self.database.reading() as connection:
            rows = connection.execute(
                r"""
                SELECT * FROM chat_messages
                WHERE revoked=0 AND (
                    content LIKE ? ESCAPE '\' OR speaker LIKE ? ESCAPE '\'
                )
                ORDER BY id DESC LIMIT ?
                """,
                (pattern, pattern, max(1, min(int(limit), 100))),
            ).fetchall()
            return [_row_to_dict(row) for row in rows]


__all__ = ["ChatStore", "ROLE_GM", "ROLE_PLAYER", "PLAYER_SPEAKER"]
