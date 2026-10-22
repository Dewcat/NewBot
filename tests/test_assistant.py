from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from dewbot.assistant import AssistantError, PrivacyStore, WritingAssistant
from dewbot.assistant_telegram import PrivacyTelegramAdapter
from dewbot.chat import ChatStore
from dewbot.config import Settings
from dewbot.db import Database
from dewbot.schema import MIGRATIONS
from dewbot.story import StoryError, StoryStore
from dewbot.web.server import create_app


@pytest.fixture
def writing(tmp_path):
    settings = Settings(database_path=tmp_path / "battle.db", content_paths=(), telegram_token=None,
                        telegram_proxy=None, admin_ids=frozenset({7}), web_gm_key="gm-test",
                        web_player_key="player-test", story_enabled=True)
    app = create_app(settings)
    return app.state.writing_assistant, app.state.chat_store, app


def test_privacy_is_sticky_across_toggles_edits_and_restart(writing):
    assistant, chat, _ = writing
    private = chat.post("gm", "PRIVATE_SENTINEL")
    assert private["ai_excluded"] == 1
    assistant.privacy.set(False)
    public = chat.post("player", "eligible")
    assert public["ai_excluded"] == 0
    assert [x["id"] for x in assistant.privacy.eligible()] == [public["id"]]
    chat.edit(private["id"], "gm", "still private after disabling")
    assert chat.list_recent()[0]["ai_excluded"] == 1
    assistant.privacy.set(True)
    chat.edit(public["id"], "player", "now private")
    assistant.privacy.set(False)
    assert assistant.privacy.eligible() == []
    restarted = PrivacyStore(Database(chat.database.path))
    assert restarted.state()["enabled"] is False
    assert restarted.eligible() == []
    # Human chat retains the content and its ordinary visibility.
    assert len(chat.search("private")) == 2


def test_upgrade_excludes_legacy_messages(tmp_path):
    db = Database(tmp_path / "legacy.db")
    with db.transaction() as con:
        # Build a genuine pre-v24 database rather than writing the new flag manually.
        con.execute("CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY,name TEXT,applied_at TEXT)")
        for version, name, sql in MIGRATIONS[:-1]:
            for statement in db._sql_statements(sql):
                con.execute(statement)
            con.execute("INSERT INTO schema_migrations VALUES(?,?,CURRENT_TIMESTAMP)", (version, name))
        con.execute("INSERT INTO chat_messages(author_role,kind,speaker,content) VALUES('gm','narration','','old secret')")
    db.initialize()
    PrivacyStore(db).set(False)
    assert PrivacyStore(db).eligible() == []
    assert ChatStore(db).list_recent()[0]["content"] == "old secret"


def test_context_uses_only_selected_eligible_current_material(writing):
    assistant, chat, _ = writing
    secret = chat.post("gm", "PRIVATE_SENTINEL")
    assistant.privacy.set(False)
    chosen = chat.post("gm", "selected line")
    chat.post("player", "UNSELECTED_SENTINEL")
    note = assistant.notebook.save("gm", {"title":"permitted", "body":"allowed note", "status":"confirmed",
        "visibility":"gm", "source":"SOURCE_SENTINEL", "ai_allowed":True, "unlock_at":300})
    data = {"instruction":"Write two alternatives", "message_ids":[chosen["id"]], "note_ids":[note["id"]]}
    result = asyncio.run(assistant.preview(data))
    assert "selected line" in result["prompt"] and "allowed note" in result["prompt"]
    for forbidden in ("PRIVATE_SENTINEL", "UNSELECTED_SENTINEL", "SOURCE_SENTINEL"):
        assert forbidden not in result["prompt"]
    with pytest.raises(AssistantError, match="不可提供"):
        asyncio.run(assistant.preview({**data, "message_ids":[secret["id"]]}))
    assistant.privacy.protect([chosen["id"]])
    with pytest.raises(AssistantError):
        asyncio.run(assistant.preview({**data, "digest":result["digest"]}, reviewed=True))


def test_preview_cannot_be_reused_after_edit_revoke_or_toggle(writing):
    assistant, chat, _ = writing
    assistant.privacy.set(False)
    message = chat.post("gm", "first")
    data = {"instruction":"continue", "message_ids":[message["id"]]}
    result = asyncio.run(assistant.preview(data))
    chat.edit(message["id"], "gm", "second")
    with pytest.raises(AssistantError, match="变化"):
        asyncio.run(assistant.preview({**data, "digest":result["digest"]}, reviewed=True))
    result = asyncio.run(assistant.preview(data))
    assistant.privacy.set(True); assistant.privacy.set(False)
    with pytest.raises(AssistantError):
        asyncio.run(assistant.preview({**data, "digest":result["digest"]}, reviewed=True))
    chat.revoke(message["id"], "gm")
    with pytest.raises(AssistantError):
        asyncio.run(assistant.preview(data))


def test_notebook_permission_and_progress_are_checked_again(writing):
    assistant, _, _ = writing
    assistant.privacy.set(False)
    note = assistant.notebook.save("gm", {"title":"note", "body":"first", "status":"confirmed",
        "visibility":"public", "ai_allowed":True, "unlock_at":410})
    data = {"instruction":"continue", "note_ids":[note["id"]]}
    result = asyncio.run(assistant.preview(data))
    assistant.notebook.save("gm", {**note,"ai_allowed":False}, entry_id=note["id"], expected_revision=1)
    with pytest.raises(StoryError):
        asyncio.run(assistant.preview({**data,"digest":result["digest"]}, reviewed=True))
    assistant.notebook.save("gm", {**note,"ai_allowed":True}, entry_id=note["id"], expected_revision=2)
    progress = assistant.notebook.progress()
    assistant.notebook.set_progress("gm",300,"第三章",progress["revision"])
    with pytest.raises(StoryError):
        asyncio.run(assistant.preview(data))


def test_privacy_blocks_all_outgoing_paths_and_player_controls(writing, monkeypatch):
    assistant, _, app = writing
    calls = []
    async def model(prompt): calls.append(prompt); return "draft"
    monkeypatch.setattr(assistant, "_request_model", model)
    gm, player = TestClient(app), TestClient(app)
    gm.post("/api/login",json={"key":"gm-test"}); player.post("/api/login",json={"key":"player-test"})
    for endpoint in ("preview","export","draft"):
        assert gm.post("/api/assistant/"+endpoint,json={"instruction":"continue"}).status_code == 409
        assert player.post("/api/assistant/"+endpoint,json={"instruction":"continue"}).status_code == 403
    assert player.put("/api/assistant/privacy",json={"enabled":False}).status_code == 403
    assert player.post("/api/assistant/protect",json={"message_ids":[]}).status_code == 403
    assert player.get("/api/assistant/messages").status_code == 403
    assert player.get("/api/assistant/notes").status_code == 403
    assert TestClient(app).get("/api/assistant/privacy").status_code == 401
    assert calls == []
    assert gm.put("/api/assistant/privacy",json={"enabled":False}).status_code == 200
    data = {"instruction":"continue"}
    preview = gm.post("/api/assistant/preview",json=data)
    assert preview.headers["cache-control"] == "no-store"
    data["digest"] = preview.json()["digest"]
    exported = gm.post("/api/assistant/export",json=data)
    assert exported.status_code == 200 and calls == []
    assert gm.post("/api/assistant/draft",json=data).json() == {"draft":"draft"}
    assert len(calls) == 1
    assert assistant.privacy.database.fetch_all("SELECT * FROM chat_messages") == []


def test_toggle_cancels_inflight_generation_without_waiting(writing, monkeypatch):
    assistant, _, _ = writing
    async def scenario():
        started, cancelled = asyncio.Event(), asyncio.Event()
        async def model(prompt):
            started.set()
            try: await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                # Simulate a provider which returns despite cancellation.
                return "LATE_DRAFT_SENTINEL"
        monkeypatch.setattr(assistant,"_request_model",model)
        await assistant.set_privacy(False)
        data = {"instruction":"continue"}
        data["digest"] = (await assistant.preview(data))["digest"]
        request = asyncio.create_task(assistant.draft(data))
        await asyncio.wait_for(started.wait(),1)
        await asyncio.wait_for(assistant.set_privacy(True),1)
        await asyncio.wait_for(cancelled.wait(),1)
        with pytest.raises(AssistantError): await request
        assert not assistant._pending
    asyncio.run(scenario())


def test_provider_payload_and_failures_do_not_expose_keys(writing, monkeypatch):
    assistant, _, _ = writing
    assistant.settings = replace(assistant.settings, ai_api_base="https://model.example/v1", ai_model="test-model", ai_api_key="KEY_SENTINEL")
    original_client = httpx.AsyncClient
    sent = []
    def transport(request):
        sent.append(json.loads(request.content))
        assert request.headers["authorization"] == "Bearer KEY_SENTINEL"
        return httpx.Response(200,json={"choices":[{"message":{"content":"candidate"}}]})
    monkeypatch.setattr(httpx,"AsyncClient",lambda **kwargs: original_client(transport=httpx.MockTransport(transport),**kwargs))
    assert asyncio.run(assistant._request_model("only selected material")) == "candidate"
    assert sent[0]["messages"] == [{"role":"user","content":"only selected material"}]
    assert sent[0]["store"] is False
    assert "KEY_SENTINEL" not in json.dumps(sent)
    monkeypatch.setattr(httpx,"AsyncClient",lambda **kwargs: original_client(transport=httpx.MockTransport(
        lambda request:httpx.Response(400,text="KEY_SENTINEL private body")),**kwargs))
    with pytest.raises(AssistantError) as error:
        asyncio.run(assistant._request_model("prompt"))
    assert "SENTINEL" not in str(error.value)


def test_telegram_privacy_permissions(writing):
    assistant, _, _ = writing
    adapter = PrivacyTelegramAdapter(assistant.privacy,frozenset({7}))
    replies = []
    async def reply(text): replies.append(text)
    update = SimpleNamespace(effective_message=SimpleNamespace(reply_text=reply),effective_user=SimpleNamespace(id=8))
    asyncio.run(adapter.privacy_command(update,SimpleNamespace(args=["off"])))
    assert assistant.privacy.state()["enabled"] is True
    update.effective_user.id = 7
    asyncio.run(adapter.privacy_command(update,SimpleNamespace(args=["off"])))
    assert assistant.privacy.state()["enabled"] is False
