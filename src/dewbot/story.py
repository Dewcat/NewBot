"""Optional, human-authored story archive. No battle state or model calls.

The archive owns a separate SQLite file and is initialized only when enabled.
Canon status, world and audience are independent; a confirmed secret stays
secret until the GM explicitly publishes it. Previous revisions are GM-only.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .db import Database


STATUSES = {"draft": "待定", "confirmed": "已确认", "withdrawn": "已撤回"}
KINDS = {"lore": "设定", "character": "角色", "event": "事件", "clue": "线索"}
VISIBILITIES = {"gm": "仅管理人", "public": "玩家可见"}


class StoryError(ValueError):
    pass


class StoryConflict(StoryError):
    pass


class StoryNotFound(StoryError):
    pass


def _text(value: Any, name: str, maximum: int, *, required: bool = False) -> str:
    if not isinstance(value, str):
        raise StoryError(f"{name}必须是文本。")
    text = value.strip()
    if required and not text:
        raise StoryError(f"{name}不能为空。")
    if len(text) > maximum:
        raise StoryError(f"{name}不能超过 {maximum} 字。")
    return text


def _role(role: str, *, write: bool = False) -> None:
    if role not in {"gm", "player"} or (write and role != "gm"):
        raise PermissionError("故事档案仅允许管理人修改；玩家只能查看已公开条目。")


def _validated(data: dict[str, Any]) -> dict[str, Any]:
    result = {
        "title": _text(data.get("title", ""), "标题", 120, required=True),
        "body": _text(data.get("body", ""), "正文", 20000, required=True),
        "world": _text(data.get("world", "主世界"), "世界线", 80, required=True),
        "chapter": _text(data.get("chapter", ""), "篇章", 120),
        "source": _text(data.get("source", ""), "管理人来源备注", 2000),
    }
    for key, allowed, default in (
        ("status", STATUSES, "draft"),
        ("kind", KINDS, "lore"),
        ("visibility", VISIBILITIES, "gm"),
    ):
        value = data.get(key, default)
        if not isinstance(value, str) or value not in allowed:
            raise StoryError(f"无效的 {key}。")
        result[key] = value
    if result["visibility"] == "public" and result["status"] != "confirmed":
        raise StoryError("只有已确认条目可以公开；待定和撤回条目请设为仅管理人。")
    return result


def _present(row: Any, role: str) -> dict[str, Any]:
    result = dict(row)
    if role != "gm":
        result.pop("source", None)
    return result


class StoryStore:
    def __init__(self, database: Database) -> None:
        self.database = database

    def initialize(self) -> None:
        # Deliberately do not call Database.initialize(): that initializes the
        # battle schema. This file is solely owned by the story module.
        with self.database.transaction() as con:
            con.execute("""
                CREATE TABLE IF NOT EXISTS story_entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL, body TEXT NOT NULL,
                    world TEXT NOT NULL, chapter TEXT NOT NULL DEFAULT '',
                    source TEXT NOT NULL DEFAULT '',
                    kind TEXT NOT NULL CHECK(kind IN ('lore','character','event','clue')),
                    status TEXT NOT NULL CHECK(status IN ('draft','confirmed','withdrawn')),
                    visibility TEXT NOT NULL CHECK(visibility IN ('gm','public')),
                    revision INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    CHECK(visibility='gm' OR status='confirmed')
                )
            """)
            con.execute("""
                CREATE TABLE IF NOT EXISTS story_revisions (
                    entry_id INTEGER NOT NULL REFERENCES story_entries(id),
                    revision INTEGER NOT NULL,
                    snapshot_json TEXT NOT NULL,
                    PRIMARY KEY(entry_id,revision)
                )
            """)

    def save(
        self, role: str, data: dict[str, Any], *, entry_id: int | None = None,
        expected_revision: int | None = None,
    ) -> dict[str, Any]:
        _role(role, write=True)
        fields = _validated(data)
        with self.database.transaction() as con:
            if entry_id is None:
                cursor = con.execute(
                    "INSERT INTO story_entries(title,body,world,chapter,source,kind,status,visibility)"
                    " VALUES(:title,:body,:world,:chapter,:source,:kind,:status,:visibility)",
                    fields,
                )
                entry_id = int(cursor.lastrowid)
            else:
                current = con.execute("SELECT * FROM story_entries WHERE id=?", (entry_id,)).fetchone()
                if current is None:
                    raise StoryNotFound("未找到该故事条目。")
                if type(expected_revision) is not int or expected_revision != current["revision"]:
                    raise StoryConflict("条目已更新或未提供版本号，请重新打开后再编辑；你的输入尚未保存。")
                con.execute(
                    "UPDATE story_entries SET title=:title,body=:body,world=:world,chapter=:chapter,"
                    "source=:source,kind=:kind,status=:status,visibility=:visibility,"
                    "revision=revision+1,updated_at=CURRENT_TIMESTAMP WHERE id=:id",
                    {**fields, "id": entry_id},
                )
            row = dict(con.execute("SELECT * FROM story_entries WHERE id=?", (entry_id,)).fetchone())
            con.execute("INSERT INTO story_revisions VALUES(?,?,?)", (
                entry_id, row["revision"], json.dumps(row, ensure_ascii=False),
            ))
            return row

    def list_entries(
        self, role: str, *, query: str = "", world: str = "", status: str = "",
        before_id: int | None = None, limit: int = 50,
    ) -> list[dict[str, Any]]:
        _role(role)
        query = _text(query, "搜索词", 200)
        world = _text(world, "世界线", 80)
        if status and status not in STATUSES:
            raise StoryError("无效的设定状态。")
        clauses, args = ["1=1"], []
        if role != "gm":
            clauses.append("visibility='public' AND status='confirmed'")
        if world:
            clauses.append("world=?")
            args.append(world)
        if status:
            clauses.append("status=?")
            args.append(status)
        if query:
            # instr treats '%' and '_' literally; never search GM notes for a player.
            clauses.append("(instr(title,?)>0 OR instr(body,?)>0 OR instr(chapter,?)>0)")
            args.extend([query] * 3)
        if before_id is not None:
            clauses.append("id<?")
            args.append(before_id)
        args.append(max(1, min(int(limit), 200)))
        rows = self.database.fetch_all(
            "SELECT * FROM story_entries WHERE " + " AND ".join(clauses) + " ORDER BY id DESC LIMIT ?",
            tuple(args),
        )
        return [_present(row, role) for row in rows]

    def get(self, role: str, entry_id: int) -> dict[str, Any]:
        _role(role)
        row = self.database.fetch_one("SELECT * FROM story_entries WHERE id=?", (entry_id,))
        if row is None or (role != "gm" and (row["visibility"] != "public" or row["status"] != "confirmed")):
            # Identical response for a secret ID and a missing ID.
            raise StoryNotFound("未找到该故事条目。")
        return _present(row, role)

    def history(self, role: str, entry_id: int) -> list[dict[str, Any]]:
        _role(role, write=True)
        self.get(role, entry_id)
        return [json.loads(row["snapshot_json"]) for row in self.database.fetch_all(
            "SELECT snapshot_json FROM story_revisions WHERE entry_id=? ORDER BY revision DESC",
            (entry_id,),
        )]

    def export(self, role: str) -> dict[str, Any]:
        _role(role)
        where = "" if role == "gm" else " WHERE visibility='public' AND status='confirmed'"
        entries = [_present(row, role) for row in self.database.fetch_all(
            "SELECT * FROM story_entries" + where + " ORDER BY id"
        )]
        return {"format": "dewbot.story.v1", "audience": role, "entries": entries}


def open_story_store(settings: Any) -> StoryStore | None:
    if not getattr(settings, "story_enabled", False):
        return None
    battle_path = Path(settings.database_path).resolve()
    explicit = getattr(settings, "story_database_path", None)
    path = Path(explicit).resolve() if explicit else battle_path.with_name(battle_path.stem + ".story.db")
    if path == battle_path or (path.exists() and battle_path.exists() and path.samefile(battle_path)):
        raise StoryError("故事数据库必须与战斗数据库使用不同的文件。")
    store = StoryStore(Database(path))
    store.initialize()
    return store
