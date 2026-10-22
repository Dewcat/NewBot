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
    unlock_at = data.get("unlock_at", 0)
    if type(unlock_at) is not int or not 0 <= unlock_at <= 99999:
        raise StoryError("解锁进度必须是 0–99999 的整数。")
    if type(data.get("ai_allowed", False)) is not bool:
        raise StoryError("AI 许可必须为布尔值。")
    result.update(unlock_at=unlock_at, ai_allowed=int(data.get("ai_allowed", False)))
    return result


def _present(row: Any, role: str) -> dict[str, Any]:
    result = dict(row)
    result["ai_allowed"] = bool(result.get("ai_allowed", False))
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
            columns = {x["name"] for x in con.execute("PRAGMA table_info(story_entries)")}
            if "unlock_at" not in columns:
                con.execute("ALTER TABLE story_entries ADD COLUMN unlock_at INTEGER NOT NULL DEFAULT 0")
            if "ai_allowed" not in columns:
                con.execute("ALTER TABLE story_entries ADD COLUMN ai_allowed INTEGER NOT NULL DEFAULT 0")
            con.execute("""CREATE TABLE IF NOT EXISTS story_progress (
                id INTEGER PRIMARY KEY CHECK(id=1), checkpoint INTEGER NOT NULL,
                label TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1
            )""")
            con.execute("INSERT OR IGNORE INTO story_progress(id,checkpoint,label) VALUES(1,410,?)",
                        ("第四章·第一部分结束（东柏刺伤李箱）",))
            con.execute("CREATE TABLE IF NOT EXISTS story_seed_packs (key TEXT PRIMARY KEY)")

    def save(
        self, role: str, data: dict[str, Any], *, entry_id: int | None = None,
        expected_revision: int | None = None,
    ) -> dict[str, Any]:
        _role(role, write=True)
        fields = _validated(data)
        with self.database.transaction() as con:
            if entry_id is None:
                cursor = con.execute(
                    "INSERT INTO story_entries(title,body,world,chapter,source,kind,status,visibility,unlock_at,ai_allowed)"
                    " VALUES(:title,:body,:world,:chapter,:source,:kind,:status,:visibility,:unlock_at,:ai_allowed)",
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
                    "unlock_at=:unlock_at,ai_allowed=:ai_allowed,"
                    "revision=revision+1,updated_at=CURRENT_TIMESTAMP WHERE id=:id",
                    {**fields, "id": entry_id},
                )
            row = dict(con.execute("SELECT * FROM story_entries WHERE id=?", (entry_id,)).fetchone())
            con.execute("INSERT INTO story_revisions VALUES(?,?,?)", (
                entry_id, row["revision"], json.dumps(row, ensure_ascii=False),
            ))
            return _present(row, role)

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
            clauses.append("unlock_at<=(SELECT checkpoint FROM story_progress WHERE id=1)")
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
        visible = "" if role == "gm" else (
            " AND visibility='public' AND status='confirmed'"
            " AND unlock_at<=(SELECT checkpoint FROM story_progress WHERE id=1)"
        )
        row = self.database.fetch_one("SELECT * FROM story_entries WHERE id=?" + visible, (entry_id,))
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
        where = "" if role == "gm" else (
            " WHERE visibility='public' AND status='confirmed'"
            " AND unlock_at<=(SELECT checkpoint FROM story_progress WHERE id=1)"
        )
        entries = [_present(row, role) for row in self.database.fetch_all(
            "SELECT * FROM story_entries" + where + " ORDER BY id"
        )]
        return {"format": "dewbot.story.v1", "audience": role, "entries": entries}

    def progress(self) -> dict[str, Any]:
        return dict(self.database.fetch_one("SELECT checkpoint,label,revision FROM story_progress WHERE id=1"))

    def set_progress(self, role: str, checkpoint: int, label: str, revision: int) -> dict[str, Any]:
        _role(role, write=True)
        if type(checkpoint) is not int or not 0 <= checkpoint <= 99999:
            raise StoryError("进度必须是 0–99999 的整数。")
        label = _text(label, "进度名称", 120, required=True)
        with self.database.transaction() as con:
            current = con.execute("SELECT revision FROM story_progress WHERE id=1").fetchone()
            if type(revision) is not int or revision != current["revision"]:
                raise StoryConflict("进度已变化，请刷新后重试。")
            con.execute("UPDATE story_progress SET checkpoint=?,label=?,revision=revision+1 WHERE id=1", (checkpoint, label))
        return self.progress()

    def ai_entries(self, selected: list[int]) -> list[dict[str, Any]]:
        # Explicit AI permission is independent of player visibility. Source notes
        # and old revisions are never included, even for GM-only AI-approved notes.
        with self.database.reading() as con:
            con.execute("BEGIN")
            rows = []
            for entry_id in selected:
                row = con.execute(
                    "SELECT id,title,body,world,chapter FROM story_entries WHERE id=?"
                    " AND ai_allowed=1 AND status='confirmed'"
                    " AND unlock_at<=(SELECT checkpoint FROM story_progress WHERE id=1)", (entry_id,),
                ).fetchone()
                if row is None:
                    raise StoryError("所选笔记尚未解锁或未获准提供给 AI，请重新选择。")
                rows.append(dict(row))
            return rows

    def eligible_ai_entries(self, before_id: int = 2**63-1) -> list[dict[str, Any]]:
        return [dict(x) for x in self.database.fetch_all(
            "SELECT id,title,body,world,chapter FROM story_entries WHERE ai_allowed=1"
            " AND status='confirmed' AND unlock_at<=(SELECT checkpoint FROM story_progress WHERE id=1)"
            " AND id<? ORDER BY id DESC LIMIT 100", (before_id,),
        )]

    def seed_notebook(self) -> None:
        from .notebook_seed import STARTER_NOTES

        with self.database.transaction() as con:
            if con.execute("SELECT 1 FROM story_seed_packs WHERE key='starter.v1'").fetchone():
                return
            for item in STARTER_NOTES:
                fields = _validated({"world": "都市·共通知识", "kind": "lore", "status": "confirmed",
                                     "visibility": "public", "ai_allowed": False, **item})
                cur = con.execute(
                    "INSERT INTO story_entries(title,body,world,chapter,source,kind,status,visibility,unlock_at,ai_allowed)"
                    " VALUES(:title,:body,:world,:chapter,:source,:kind,:status,:visibility,:unlock_at,:ai_allowed)", fields,
                )
                row = dict(con.execute("SELECT * FROM story_entries WHERE id=?", (cur.lastrowid,)).fetchone())
                con.execute("INSERT INTO story_revisions VALUES(?,?,?)", (row["id"], 1, json.dumps(row, ensure_ascii=False)))
            con.execute("INSERT INTO story_seed_packs VALUES('starter.v1')")


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
    store.seed_notebook()
    return store
