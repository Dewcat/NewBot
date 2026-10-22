from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from dewbot.config import Settings
from dewbot.db import Database
from dewbot.engine import BattleEngine
from dewbot.story import StoryConflict, StoryError, StoryNotFound, StoryStore, open_story_store
from dewbot.story_telegram import StoryTelegramAdapter
from dewbot.web.server import create_app


def entry(**changes):
    return {"title": "测试角色的记忆", "body": "仅供测试的正文", "world": "主世界",
            "status": "draft", "visibility": "gm", **changes}


@pytest.fixture
def store(tmp_path):
    result = StoryStore(Database(tmp_path / "story.db"))
    result.initialize()
    return result


def test_private_defaults_and_worlds_are_independent(store):
    secret = store.save("gm", entry())
    public = store.save("gm", entry(status="confirmed", visibility="public", source="秘密来源"))
    mirror = store.save("gm", entry(world="镜世界·测试", status="confirmed", visibility="public"))
    assert secret["visibility"] == "gm"
    assert [x["id"] for x in store.list_entries("player", world="主世界")] == [public["id"]]
    assert [x["id"] for x in store.list_entries("player", world="镜世界·测试")] == [mirror["id"]]
    assert "秘密来源" not in json.dumps(store.export("player"), ensure_ascii=False)
    for operation in (lambda: store.get("player", secret["id"]), lambda: store.get("player", 9999)):
        with pytest.raises(StoryNotFound, match="未找到该故事条目"):
            operation()


def test_revision_conflict_preserves_newer_content_and_complete_history(store):
    old = store.save("gm", entry(body="旧提案"))
    new = store.save("gm", entry(body="作者修订", status="confirmed"),
                     entry_id=old["id"], expected_revision=1)
    with pytest.raises(StoryConflict):
        store.save("gm", entry(body="过期窗口"), entry_id=old["id"], expected_revision=1)
    assert store.get("gm", old["id"])["body"] == "作者修订"
    assert [r["body"] for r in store.history("gm", old["id"])] == ["作者修订", "旧提案"]
    assert new["revision"] == 2
    with pytest.raises(PermissionError):
        store.history("player", old["id"])


@pytest.mark.parametrize("status", ["draft", "withdrawn"])
def test_unconfirmed_cannot_be_published(store, status):
    with pytest.raises(StoryError, match="只有已确认"):
        store.save("gm", entry(status=status, visibility="public"))
    assert store.export("gm")["entries"] == []


def test_withdrawing_removes_player_access_without_deleting_history(store):
    first = store.save("gm", entry(status="confirmed", visibility="public"))
    store.save("gm", entry(status="withdrawn"), entry_id=first["id"], expected_revision=1)
    assert store.list_entries("player") == []
    assert len(store.history("gm", first["id"])) == 2


def test_search_pagination_and_restart(store):
    first = store.save("gm", entry(title="100%准确_待核"))
    second = store.save("gm", entry(title="另一个条目"))
    assert store.list_entries("gm", query="%_") == []
    assert store.list_entries("gm", query="%准确_")[0]["id"] == first["id"]
    assert store.list_entries("gm", before_id=second["id"])[0]["id"] == first["id"]
    reopened = StoryStore(Database(store.database.path)); reopened.initialize()
    assert len(reopened.export("gm")["entries"]) == 2


@pytest.mark.parametrize("role", ["player", "unknown"])
def test_store_write_role_is_checked(store, role):
    with pytest.raises(PermissionError):
        store.save(role, entry())


def settings(tmp_path, enabled=True):
    return Settings(database_path=tmp_path / "battle.db", content_paths=(),
                    telegram_token=None, telegram_proxy=None, admin_ids=frozenset({7}),
                    web_gm_key="test-gm", web_player_key="test-player", story_enabled=enabled)


def web_clients(tmp_path, enabled=True):
    config = settings(tmp_path, enabled)
    db = Database(config.database_path); db.initialize()
    app = create_app(config, engine=BattleEngine(db))
    gm, player = TestClient(app), TestClient(app)
    gm.post("/api/login", json={"key": "test-gm"})
    player.post("/api/login", json={"key": "test-player"})
    return app, gm, player


def test_disabled_has_no_sidecar_routes_or_schema_changes(tmp_path):
    app, gm, player = web_clients(tmp_path, False)
    assert app.state.story_store is None
    assert not (tmp_path / "battle.story.db").exists()
    assert gm.get("/api/story/entries").status_code == 404
    assert "story_enabled" not in player.get("/api/session").json()
    assert not app.state.engine.database.fetch_all("SELECT name FROM sqlite_master WHERE name LIKE 'story_%'")


def test_enabled_does_not_write_battle_database(tmp_path):
    app, gm, player = web_clients(tmp_path)
    with app.state.engine.database.reading() as con:
        before = '\n'.join(con.iterdump())
    assert gm.post("/api/story/entries", json=entry()).status_code == 200
    with app.state.engine.database.reading() as con:
        assert '\n'.join(con.iterdump()) == before


def test_api_hides_secrets_notes_and_history_and_checks_permissions(tmp_path):
    app, gm, player = web_clients(tmp_path)
    secret = gm.post("/api/story/entries", json=entry(title="尚未揭晓的秘密")).json()
    public = gm.post("/api/story/entries", json=entry(status="confirmed", visibility="public", source="机密出处")).json()
    unauthenticated = TestClient(app)
    for path in ("/api/story/entries", "/api/story/export", f"/api/story/entries/{secret['id']}"):
        assert unauthenticated.get(path).status_code == 401
        result = player.get(path)
        assert "尚未揭晓的秘密" not in result.text and "机密出处" not in result.text
    assert player.get(f"/api/story/entries/{secret['id']}").status_code == 404
    assert player.get(f"/api/story/entries/{public['id']}/history").status_code == 403
    assert player.post("/api/story/entries", json=entry()).status_code == 403
    assert player.put(f"/api/story/entries/{public['id']}", json=entry()).status_code == 403
    assert player.get("/api/story/entries").headers["cache-control"] == "no-store"
    assert gm.get("/api/session").json()["story_enabled"] is True


def test_api_edit_conflict_is_409_and_does_not_overwrite(tmp_path):
    app, gm, _ = web_clients(tmp_path)
    original = gm.post("/api/story/entries", json=entry()).json()
    url = f"/api/story/entries/{original['id']}"
    assert gm.put(url, json=entry(body="新文本", revision=1)).status_code == 200
    assert gm.put(url, json=entry(body="冲突文本", revision=1)).status_code == 409
    assert gm.get(url).json()["body"] == "新文本"
    assert gm.post("/api/story/entries", json=[]).status_code == 400
    assert gm.post("/api/story/entries", json=entry(status=[])).status_code == 400
    assert gm.get("/api/story/entries?before_id=-1").status_code == 400


def test_sidecar_cannot_alias_battle_database(tmp_path):
    config = settings(tmp_path)
    from dataclasses import replace
    with pytest.raises(StoryError, match="不同的文件"):
        open_story_store(replace(config, story_database_path=config.database_path))
    config.database_path.touch()
    alias = tmp_path / "alias.db"; alias.symlink_to(config.database_path)
    with pytest.raises(StoryError):
        open_story_store(replace(config, story_database_path=alias))


def test_telegram_admin_group_is_public_and_private_admin_is_private(store):
    secret = store.save("gm", entry(title="未公开身份"))
    adapter = StoryTelegramAdapter(store, frozenset({7}))
    replies = []
    async def reply(text, **kwargs): replies.append(text)
    update = SimpleNamespace(effective_message=SimpleNamespace(reply_text=reply),
                             effective_user=SimpleNamespace(id=7),
                             effective_chat=SimpleNamespace(type="group"))
    asyncio.run(adapter.story_command(update, SimpleNamespace(args=[str(secret['id'])])))
    assert "未公开身份" not in '\n'.join(replies)
    update.effective_chat.type = "private"; replies.clear()
    asyncio.run(adapter.story_command(update, SimpleNamespace(args=[str(secret['id'])])))
    assert "未公开身份" in '\n'.join(replies)
    update.effective_user.id = 8; replies.clear()
    asyncio.run(adapter.story_command(update, SimpleNamespace(args=[])))
    assert "未公开身份" not in '\n'.join(replies)
