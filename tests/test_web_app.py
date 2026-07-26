"""Web 前端（``src/dewbot/web/server.py``）的离线接口测试。

覆盖 WEB_FRONTEND_GUIDE.md §10：登录/401/403、玩家权限边界（GM 接口 403、
敌方技能不可见）、行动接口走通完整回合、``revision`` 过期 409、SSE 握手。
全部通过 ``create_app(settings, engine=engine, loader=loader)`` 注入内存库，
不触网、不起真实服务进程（SSE 为无限流，TestClient 会缓冲整个响应体，
因此握手改用手工 ASGI 调用验证响应头）。
"""

from __future__ import annotations

import asyncio
import json
from contextlib import suppress
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from dewbot.content import ContentLoader
from dewbot.db import Database
from dewbot.engine import BattleEngine
from dewbot.models import BattlePhase, Faction
from dewbot.web.server import create_app

from conftest import BASE_PACK, make_extension_pack


CORE_PERSONAS = BASE_PACK.with_name("core_personas.json")

GM_KEY = "unit-test-gm-key"
PLAYER_KEY = "unit-test-player-key"

# 该技能名只登记在敌方模板上，任何友方单位都不携带同名技能：
# 玩家侧任何响应里出现它即视为隐私泄漏。
SECRET_SKILL_NAME = "机密技能·网页面档案"
SECRET_ENEMY_TEMPLATE = "enemy.webtest_shadow"


def make_privacy_pack() -> dict[str, object]:
    """注册一个仅持有"机密技能"的敌方模板，用于验证玩家侧过滤。"""

    return {
        "pack": {
            "key": "test.web_privacy",
            "name": "Web Privacy Pack",
            "version": "1.0.0",
        },
        "effects": [],
        "skills": [
            {
                "key": "skill.webtest.secret",
                "name": SECRET_SKILL_NAME,
                "type": "NORMAL",
                "cooldown": 0,
                "emotion": 0,
                "target_scope": "ENEMY",
                "target_method": "SELECT_TARGET",
                "behaviors": [
                    {
                        "key": "behavior.webtest.secret.damage",
                        "timing": "ON",
                        "effect_type": "DAMAGE",
                        "value": "1",
                    }
                ],
            }
        ],
        "characters": [
            {
                "key": SECRET_ENEMY_TEMPLATE,
                "name": "隐秘个体",
                "max_hp": 400,
                "max_actions": 1,
                "max_stagger": 120,
                "tags": [],
                "skills": ["skill.webtest.secret"],
            }
        ],
        "abnormalities": [
            {
                "key": "webtest.abnormality.mirror",
                "name": "映镜",
                "description": "用于卡组/预设接口测试的最小异想体。",
                "carry_bonus": {
                    "key": "webtest.carry.mirror",
                    "name": "镜光",
                    "description": "携带生效：回合开始+1行动。",
                    "handler": "bonus_actions",
                    "params": {"amount": 1, "events": ["TURN_START"]},
                },
                "pages": [
                    {
                        "key": "webtest.page.mirror_glint",
                        "name": "镜面拂光",
                        "type": "AWAKENING",
                        "level": 1,
                        "handler": "bonus_actions",
                        "params": {"amount": 1, "events": ["TURN_START"]},
                    },
                    {
                        "key": "webtest.page.mirror_crack",
                        "name": "裂镜",
                        "type": "BREAKDOWN",
                        "level": 2,
                        "handler": "fortune_verdict",
                        "params": {"intensity": 2, "events": ["TURN_START"]},
                    },
                ],
            }
        ],
        "manager_skills": [],
    }


def _settings(tmp_path: Path, **overrides: Any) -> SimpleNamespace:
    """与 test_telegram_app 一致的 Settings 桩：只提供 create_app 用到的字段。"""

    values: dict[str, Any] = {
        "database_path": tmp_path / "web.sqlite3",
        "content_paths": (BASE_PACK, CORE_PERSONAS),
        "telegram_token": None,
        "telegram_proxy": None,
        "admin_ids": frozenset(),
        "web_host": "127.0.0.1",
        "web_port": 8787,
        "web_gm_key": GM_KEY,
        "web_player_key": PLAYER_KEY,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.fixture
def web(tmp_path: Path) -> Any:
    """内存库 + 全量内容包 + 注入引擎的 FastAPI 应用。"""

    database = Database(":memory:")
    database.initialize()
    loader = ContentLoader(database)
    loader.load_path(BASE_PACK)
    loader.load_path(CORE_PERSONAS)
    loader.load(make_extension_pack())
    loader.load(make_privacy_pack())
    engine = BattleEngine(database)
    # 新加载的异想体默认不对玩家开放；夹具统一开放，访问控制由专项测试覆盖。
    all_keys = [
        row["abnormality_key"]
        for row in database.fetch_all(
            "SELECT abnormality_key FROM abnormalities WHERE enabled=1"
        )
    ]
    if all_keys:
        engine.set_abnormality_access(all_keys, True)
    app = create_app(_settings(tmp_path), engine=engine, loader=loader)
    yield SimpleNamespace(app=app, engine=engine, database=database)
    database.close()


def _login(client: TestClient, key: str) -> dict[str, Any]:
    response = client.post("/api/login", json={"key": key})
    assert response.status_code == 200
    return response.json()


@pytest.fixture
def gm(web: SimpleNamespace) -> TestClient:
    client = TestClient(web.app)
    assert _login(client, GM_KEY)["role"] == "gm"
    return client


@pytest.fixture
def player(web: SimpleNamespace) -> TestClient:
    client = TestClient(web.app)
    assert _login(client, PLAYER_KEY)["role"] == "player"
    return client


def _dump(response: Any) -> str:
    """以 ensure_ascii=False 序列化响应，供中文技能名泄漏检查。"""

    return json.dumps(response.json(), ensure_ascii=False)


# ---------------------------------------------------------------------------
# 登录与 401
# ---------------------------------------------------------------------------
def test_create_app_refuses_when_no_key_is_configured(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="均未配置"):
        create_app(_settings(tmp_path, web_gm_key=None, web_player_key=None))


def test_unauthenticated_requests_are_rejected_with_401(web: SimpleNamespace) -> None:
    client = TestClient(web.app)
    for path in ("/api/session", "/api/overview", "/api/battle", "/api/events"):
        response = client.get(path)
        assert response.status_code == 401
        assert "error" in response.json()
    response = client.post("/api/battle/pass")
    assert response.status_code == 401
    assert "error" in response.json()


def test_wrong_key_login_is_rejected_with_401(web: SimpleNamespace) -> None:
    client = TestClient(web.app)
    response = client.post("/api/login", json={"key": "definitely-not-a-key"})
    assert response.status_code == 401
    assert "error" in response.json()
    assert "dewbot_key" not in response.headers.get("set-cookie", "")
    # 错误 key 不建立会话。
    assert client.get("/api/session").status_code == 401


def test_login_returns_role_and_sets_httponly_cookie(web: SimpleNamespace) -> None:
    gm_client = TestClient(web.app)
    response = gm_client.post("/api/login", json={"key": GM_KEY})
    assert response.status_code == 200
    assert response.json() == {"role": "gm"}
    cookie = response.headers["set-cookie"].lower()
    assert "dewbot_key" in cookie
    assert "httponly" in cookie
    assert "samesite=lax" in cookie
    session = gm_client.get("/api/session")
    assert session.status_code == 200
    assert session.json() == {
        "role": "gm",
        "has_active_battle": False,
        "phase": None,
    }

    player_client = TestClient(web.app)
    assert player_client.post("/api/login", json={"key": PLAYER_KEY}).json() == {
        "role": "player"
    }
    assert player_client.get("/api/session").json()["role"] == "player"

    # 登出后会话失效。
    assert player_client.post("/api/logout").status_code == 200
    assert player_client.get("/api/session").status_code == 401


def test_single_key_deployment_only_admits_that_role(tmp_path: Path) -> None:
    database = Database(":memory:")
    database.initialize()
    engine = BattleEngine(database)
    try:
        app = create_app(_settings(tmp_path, web_gm_key=None), engine=engine)
        client = TestClient(app)
        assert client.post("/api/login", json={"key": GM_KEY}).status_code == 401
        assert client.post("/api/login", json={"key": PLAYER_KEY}).json() == {
            "role": "player"
        }
    finally:
        database.close()


# ---------------------------------------------------------------------------
# 玩家权限边界（GM 接口 403）
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/battles"),
        ("GET", "/api/encounters"),
        ("GET", "/api/templates"),
        ("GET", "/api/abnormalities"),
        ("GET", "/api/setup/ready"),
        ("POST", "/api/battle/settle"),
        ("POST", "/api/battle/forfeit-assists"),
        ("POST", "/api/setup/new"),
        ("POST", "/api/reload"),
    ],
)
def test_player_is_rejected_from_gm_endpoints(
    player: TestClient, method: str, path: str
) -> None:
    response = player.request(method, path)
    assert response.status_code == 403
    assert "error" in response.json()


def test_player_cannot_read_enemy_skill_catalog_outside_battle(
    web: SimpleNamespace, gm: TestClient, player: TestClient
) -> None:
    enemy_id = web.engine.spawn_character(SECRET_ENEMY_TEMPLATE, Faction.ENEMY)

    blocked = player.get(f"/api/characters/{enemy_id}/skills")
    assert blocked.status_code == 403
    assert SECRET_SKILL_NAME not in _dump(blocked)

    # 玩家可以看到敌方名册（对齐 /roster），但其中不含技能档案。
    roster = player.get("/api/roster", params={"faction": "ENEMY"})
    assert roster.status_code == 200
    assert any(int(item["id"]) == enemy_id for item in roster.json())
    assert SECRET_SKILL_NAME not in _dump(roster)

    # GM 正向对照：同一接口可见完整技能名。
    catalog = gm.get(f"/api/characters/{enemy_id}/skills")
    assert catalog.status_code == 200
    assert SECRET_SKILL_NAME in _dump(catalog)


# ---------------------------------------------------------------------------
# 编成 → revision → 触发 → 完整回合
# ---------------------------------------------------------------------------
def _prepare_full_setup(gm: TestClient) -> dict[str, int]:
    """走 GM 编成接口搭出可触发的编成，返回关键 id。"""

    created = gm.post(
        "/api/create", json={"template_key": "unit.test_hero", "name": "网页试验体"}
    )
    assert created.status_code == 200
    assert created.json()["messages"]
    helper_id = int(created.json()["character_id"])

    roster = gm.get("/api/roster", params={"faction": "FRIENDLY"})
    assert roster.status_code == 200
    core = next(item for item in roster.json() if int(item["is_core"]))
    personas = gm.get(f"/api/characters/{core['id']}/personas")
    assert personas.status_code == 200
    persona = next(item for item in personas.json() if int(item["is_default"]))

    encounters = gm.get("/api/encounters")
    assert encounters.status_code == 200
    encounter_key = encounters.json()[0]["encounter_key"]

    new = gm.post(
        "/api/setup/new", json={"name": "网页整备", "encounter_key": encounter_key}
    )
    assert new.status_code == 200
    setup_id = int(new.json()["setup_id"])

    # /api/setup/new 自动选中（user_id=0, chat_id=0），/api/plan 走默认路径。
    plan = gm.get("/api/plan")
    assert plan.status_code == 200
    assert int(plan.json()["id"]) == setup_id

    core_set = gm.post(
        "/api/setup/core",
        json={"choices": [[int(core["id"]), int(persona["id"])]]},
    )
    assert core_set.status_code == 200
    assert core_set.json()["messages"]

    allies = gm.post("/api/setup/allies/add", json={"character_ids": [helper_id]})
    assert allies.status_code == 200

    foes = gm.post(
        "/api/setup/foes/add",
        json={
            "template_key": SECRET_ENEMY_TEMPLATE,
            "stage_number": 1,
            "name": "隐秘看守",
        },
    )
    assert foes.status_code == 200
    assert foes.json()["messages"]

    return {"setup_id": setup_id, "helper_id": helper_id, "core_id": int(core["id"])}


def _launch_battle(gm: TestClient) -> dict[str, int]:
    ids = _prepare_full_setup(gm)
    revision = gm.get("/api/setup/ready").json()["revision"]
    launched = gm.post("/api/setup/launch", json={"revision": revision})
    assert launched.status_code == 200
    ids["battle_id"] = int(launched.json()["battle_id"])
    return ids


def test_full_round_flow_over_the_api(
    web: SimpleNamespace, gm: TestClient, player: TestClient
) -> None:
    ids = _prepare_full_setup(gm)

    # 触发前没有活动战斗：/api/battle 是规则拒绝（400），不是 500。
    no_battle = gm.get("/api/battle")
    assert no_battle.status_code == 400
    assert "error" in no_battle.json()

    ready = gm.get("/api/setup/ready")
    assert ready.status_code == 200
    payload = ready.json()
    assert isinstance(payload["revision"], int)
    assert int(payload["setup"]["id"]) == ids["setup_id"]
    assert payload["revision"] == int(payload["setup"]["revision"])
    stale_revision = payload["revision"]

    # 任意一次编成修改都会推进 revision，使旧确认失效。
    bump = gm.post(
        "/api/setup/foes/add",
        json={
            "template_key": SECRET_ENEMY_TEMPLATE,
            "stage_number": 2,
            "name": "增援看守",
        },
    )
    assert bump.status_code == 200

    stale = gm.post("/api/setup/launch", json={"revision": stale_revision})
    assert stale.status_code == 409
    assert "error" in stale.json()
    # 409 之后战斗没有被触发，编成仍是待命状态。
    assert gm.get("/api/battle").status_code == 400
    assert gm.get("/api/plan").json()["status"] == "STANDBY"

    fresh_revision = gm.get("/api/setup/ready").json()["revision"]
    assert fresh_revision != stale_revision
    launched = gm.post("/api/setup/launch", json={"revision": fresh_revision})
    assert launched.status_code == 200
    body = launched.json()
    assert body["messages"]
    battle_id = int(body["battle_id"])

    battle = gm.get("/api/battle").json()
    assert int(battle["id"]) == battle_id
    assert battle["phase"] == BattlePhase.FRIENDLY_ACTION.value
    assert int(battle["current_turn"]) == 1

    # 玩家的行动名单只含核心；助战由 GM 扮演（2026-07-27 裁定）。
    actors = player.get("/api/battle/actors", params={"side": "f"})
    assert actors.status_code == 200
    actor_ids = {int(item["id"]) for item in actors.json()}
    assert ids["helper_id"] not in actor_ids
    assert ids["core_id"] in actor_ids
    gm_actor_ids = {
        int(item["id"])
        for item in gm.get("/api/battle/actors", params={"side": "f"}).json()
    }
    assert ids["helper_id"] in gm_actor_ids

    # GM 先操作助战（助战 → 玩家 → 敌方的回合顺序）。
    skills = gm.get(f"/api/actors/{ids['helper_id']}/skills")
    assert skills.status_code == 200
    assert skills.json()
    skill = next(
        item for item in skills.json() if item["target_scope"] == "ENEMY"
    )

    targets = gm.get(
        f"/api/actors/{ids['helper_id']}/skills/{skill['id']}/targets"
    )
    assert targets.status_code == 200
    assert targets.json()

    action = gm.post(
        "/api/battle/action",
        json={
            "actor_id": ids["helper_id"],
            "skill_id": int(skill["id"]),
            "target_ids": [int(targets.json()[0]["id"])],
        },
    )
    assert action.status_code == 200
    result = action.json()
    assert result["messages"]
    assert result["phase"] == BattlePhase.FRIENDLY_ACTION.value
    assert int(result["actor_id"]) == ids["helper_id"]

    # GM 收尾本回合：/pass → 敌方阶段，/settle → 第 2 回合我方阶段。
    passed = gm.post("/api/battle/pass")
    assert passed.status_code == 200
    assert passed.json()["messages"]
    assert gm.get("/api/battle").json()["phase"] == BattlePhase.ENEMY_ACTION.value

    settled = gm.post("/api/battle/settle")
    assert settled.status_code == 200
    assert settled.json()["messages"]

    after = gm.get("/api/battle").json()
    assert after["phase"] == BattlePhase.FRIENDLY_ACTION.value
    assert int(after["current_turn"]) == 2

    session = player.get("/api/session").json()
    assert session["has_active_battle"] is True
    assert session["phase"] == BattlePhase.FRIENDLY_ACTION.value


# ---------------------------------------------------------------------------
# 敌方技能隐私（战斗内）
# ---------------------------------------------------------------------------
def test_player_side_battle_responses_hide_enemy_skills(
    web: SimpleNamespace, gm: TestClient, player: TestClient
) -> None:
    ids = _launch_battle(gm)
    battle = gm.get("/api/battle").json()
    enemy = next(
        item
        for item in battle["participants"]
        if item["faction"] == Faction.ENEMY.value
        and item["template_key"] == SECRET_ENEMY_TEMPLATE
        and int(item["active_in_stage"])
    )
    enemy_id = int(enemy["id"])

    # 玩家角色对敌方技能的所有入口都被服务端拒绝。
    assert player.get("/api/battle/actors", params={"side": "e"}).status_code == 403
    assert player.get(f"/api/actors/{enemy_id}/skills").status_code == 403
    assert player.get(f"/api/actors/{enemy_id}/skills/1/targets").status_code == 403
    assert player.get(f"/api/characters/{enemy_id}/skills").status_code == 403
    blocked_action = player.post(
        "/api/battle/action", json={"actor_id": enemy_id, "skill_id": 1}
    )
    assert blocked_action.status_code == 403
    assert "error" in blocked_action.json()

    # 玩家可见的每一个只读响应都不包含敌方技能名。
    helper_skills = player.get(f"/api/actors/{ids['helper_id']}/skills")
    assert helper_skills.status_code == 200
    first_skill_id = int(helper_skills.json()[0]["id"])
    readable: list[tuple[str, dict[str, str] | None]] = [
        ("/api/session", None),
        ("/api/overview", None),
        ("/api/battle", None),
        ("/api/pages", None),
        ("/api/roster", {"faction": "ENEMY"}),
        ("/api/battle/actors", {"side": "f"}),
        (f"/api/actors/{ids['helper_id']}/skills", None),
        (f"/api/actors/{ids['helper_id']}/skills/{first_skill_id}/targets", None),
        (f"/api/characters/{ids['helper_id']}/skills", None),
        (f"/api/characters/{ids['core_id']}/personas", None),
    ]
    for path, params in readable:
        response = player.get(path, params=params)
        assert response.status_code == 200, (path, response.status_code)
        assert SECRET_SKILL_NAME not in _dump(response), path

    # GM 正向对照：同一战斗内可以取到敌方技能详情。
    gm_view = gm.get(f"/api/actors/{enemy_id}/skills")
    assert gm_view.status_code == 200
    assert SECRET_SKILL_NAME in _dump(gm_view)


# ---------------------------------------------------------------------------
# SSE 握手
# ---------------------------------------------------------------------------
def test_sse_handshake_advertises_an_event_stream(web: SimpleNamespace) -> None:
    """`GET /api/events` 是无限流：TestClient 会缓冲整个响应体，因此改为
    直接以 ASGI 协议调用应用，拿到响应头（与首个回放事件）后取消任务。"""

    messages: list[dict[str, Any]] = []

    async def _handshake() -> None:
        started = asyncio.Event()
        first_chunk = asyncio.Event()
        request_messages: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        await request_messages.put(
            {"type": "http.request", "body": b"", "more_body": False}
        )

        async def receive() -> dict[str, Any]:
            # 首次返回空请求体，此后阻塞（不发送 http.disconnect）。
            return await request_messages.get()

        async def send(message: dict[str, Any]) -> None:
            messages.append(message)
            if message["type"] == "http.response.start":
                started.set()
            if message["type"] == "http.response.body" and message.get("body"):
                first_chunk.set()

        scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/api/events",
            "raw_path": b"/api/events",
            "query_string": b"",
            "root_path": "",
            "headers": [(b"cookie", f"dewbot_key={GM_KEY}".encode("utf-8"))],
            "client": ("127.0.0.1", 50000),
            "server": ("127.0.0.1", 8787),
            "extensions": {},
            "state": {},
        }
        task = asyncio.ensure_future(web.app(scope, receive, send))
        try:
            await asyncio.wait_for(started.wait(), timeout=10)
            await asyncio.wait_for(first_chunk.wait(), timeout=10)
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    asyncio.run(_handshake())

    start = next(item for item in messages if item["type"] == "http.response.start")
    assert start["status"] == 200
    headers = {
        key.decode("latin-1").lower(): value.decode("latin-1")
        for key, value in start["headers"]
    }
    assert headers["content-type"].startswith("text/event-stream")
    # 连接建立即收到回放事件（此时无活动战斗，行列表为空但事件必达）。
    body = next(
        item["body"]
        for item in messages
        if item["type"] == "http.response.body" and item.get("body")
    )
    assert b"event: log" in body
    assert b'"replay": true' in body


# ---------------------------------------------------------------------------
# 公网加固：登录限速与 Secure Cookie
# ---------------------------------------------------------------------------
def test_login_is_rate_limited_after_repeated_failures(
    web: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    import dewbot.web.server as web_server

    monkeypatch.setattr(web_server, "LOGIN_FAILURE_DELAY_SECONDS", 0)
    client = TestClient(web.app)
    for _ in range(web_server.LOGIN_MAX_FAILURES):
        response = client.post("/api/login", json={"key": "wrong-key"})
        assert response.status_code == 401
    # 达到上限后：即使密钥正确也被 429 拒绝（同一来源已被暂时封禁）。
    response = client.post("/api/login", json={"key": GM_KEY})
    assert response.status_code == 429
    assert "登录失败次数过多" in response.json()["error"]


def test_successful_login_clears_failure_record(
    web: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    import dewbot.web.server as web_server

    monkeypatch.setattr(web_server, "LOGIN_FAILURE_DELAY_SECONDS", 0)
    client = TestClient(web.app)
    for _ in range(web_server.LOGIN_MAX_FAILURES - 1):
        assert client.post("/api/login", json={"key": "wrong-key"}).status_code == 401
    assert client.post("/api/login", json={"key": GM_KEY}).status_code == 200
    # 成功登录清零计数：之后再失败一次不会立刻触发封禁。
    assert client.post("/api/login", json={"key": "wrong-key"}).status_code == 401
    assert client.post("/api/login", json={"key": GM_KEY}).status_code == 200


def test_secure_cookie_flag_follows_settings(tmp_path: Path) -> None:
    database = Database(":memory:")
    database.initialize()
    loader = ContentLoader(database)
    loader.load_path(BASE_PACK)
    loader.load_path(CORE_PERSONAS)
    engine = BattleEngine(database)
    app = create_app(
        _settings(tmp_path, web_secure_cookie=True), engine=engine, loader=loader
    )
    client = TestClient(app)
    response = client.post("/api/login", json={"key": GM_KEY})
    assert response.status_code == 200
    assert "secure" in response.headers["set-cookie"].lower()
    database.close()


# ---------------------------------------------------------------------------
# 跑团聊天（2026-07-26 裁定 §7.5-3）
# ---------------------------------------------------------------------------
def test_chat_roles_speaker_parsing(gm: TestClient, player: TestClient) -> None:
    mine = player.post("/api/chat", json={"content": "我们进去看看。"}).json()
    assert (mine["author_role"], mine["kind"], mine["speaker"]) == ("player", "speech", "经理")

    npc = gm.post("/api/chat", json={"content": "薇薇安：“欢迎来到档案馆。”"}).json()
    assert (npc["kind"], npc["speaker"], npc["content"]) == ("speech", "薇薇安", "欢迎来到档案馆。")

    narration = gm.post("/api/chat", json={"content": "走廊尽头传来翻书声。"}).json()
    assert (narration["kind"], narration["speaker"]) == ("narration", "")


def test_chat_edit_and_revoke_are_author_only(gm: TestClient, player: TestClient) -> None:
    message = gm.post("/api/chat", json={"content": "旁白初稿"}).json()
    denied = player.post("/api/chat/" + str(message["id"]) + "/edit", json={"content": "篡改"})
    assert denied.status_code == 400
    assert "自己发送" in denied.json()["error"]

    edited = gm.post(
        "/api/chat/" + str(message["id"]) + "/edit",
        json={"content": "薇薇安：“改口了。”"},
    ).json()
    assert (edited["kind"], edited["speaker"], edited["content"]) == ("speech", "薇薇安", "改口了。")
    assert edited["edited_at"]

    assert player.post("/api/chat/" + str(message["id"]) + "/revoke").status_code == 400
    revoked = gm.post("/api/chat/" + str(message["id"]) + "/revoke").json()
    assert revoked["revoked"] == 1 and revoked["content"] == ""


def test_chat_read_receipts_and_search(gm: TestClient, player: TestClient) -> None:
    message = player.post("/api/chat", json={"content": "有人在吗？"}).json()
    assert message["read_by_player"] == 1 and message["read_by_gm"] == 0

    marked = gm.post("/api/chat/read", json={"up_to_id": message["id"]}).json()
    assert marked["marked"] >= 1
    latest = gm.get("/api/chat").json()[-1]
    assert latest["read_by_gm"] == 1

    hits = player.get("/api/chat/search", params={"q": "有人"}).json()
    assert any(item["id"] == message["id"] for item in hits)


def test_channel_history_merges_chat_messages(gm: TestClient) -> None:
    gm.post("/api/chat", json={"content": "序幕开始。"})
    items = gm.get("/api/channel/history").json()["items"]
    assert any(
        item["type"] == "chat" and item["message"]["content"] == "序幕开始。"
        for item in items
    )


# ---------------------------------------------------------------------------
# 发布-确认握手与常备卡组（2026-07-26 裁定 §7.5-4/5）
# ---------------------------------------------------------------------------
def test_publish_flow_deck_and_player_confirm(gm: TestClient, player: TestClient) -> None:
    _prepare_full_setup(gm)

    # 发布前：玩家不能确认/调整编成。
    assert player.get("/api/setup/ready").status_code == 403
    assert player.post("/api/setup/core", json={"choices": []}).status_code == 403

    # 玩家配置常备卡组（非法键被拒绝）。
    assert player.post("/api/deck", json={"abnormality_keys": ["no.such.key"]}).status_code == 400
    abnormalities = player.get("/api/deck").json()["abnormalities"]
    keys = [abnormalities[0]["abnormality_key"]] if abnormalities else []
    if keys:
        assert player.post("/api/deck", json={"abnormality_keys": keys}).json()[
            "abnormality_keys"
        ] == keys

    # GM 发布：published=1，常备卡组自动带入本场书页池。
    published = gm.post("/api/setup/publish").json()["setup"]
    assert int(published["published"]) == 1
    if keys:
        assert json.loads(published["abnormalities_json"]) == keys

    # 玩家侧 plan 不含敌方阵容，只有数量；确认后开战。
    plan = player.get("/api/plan").json()
    assert "enemies" not in plan
    assert int(plan["enemy_count"]) >= 1
    revision = player.get("/api/setup/ready").json()["revision"]
    launched = player.post("/api/setup/launch", json={"revision": revision})
    assert launched.status_code == 200
    assert int(launched.json()["battle_id"]) > 0


def test_setup_stage_removal_keeps_numbering(gm: TestClient) -> None:
    _prepare_full_setup(gm)
    stages = gm.get("/api/plan").json()["stages"]
    if len(stages) > 1:
        removed = gm.post(
            "/api/setup/stages/remove",
            json={"stage_number": stages[-1]["stage_number"]},
        )
        assert removed.status_code == 200
        after = gm.get("/api/plan").json()["stages"]
        assert len(after) == len(stages) - 1
        assert [int(s["stage_number"]) for s in after] == list(range(1, len(after) + 1))
    else:
        refused = gm.post("/api/setup/stages/remove", json={"stage_number": 1})
        assert refused.status_code == 400
        assert "至少" in refused.json()["error"]


def test_core_pool_limits_player_choices(gm: TestClient, player: TestClient) -> None:
    """GM 圈定可参战核心；玩家只能从池内选出战角色（2026-07-26 裁定）。"""
    _prepare_full_setup(gm)
    roster = gm.get("/api/roster", params={"faction": "FRIENDLY"}).json()
    cores = [item for item in roster if int(item["is_core"])]
    allowed, banned = cores[0], cores[1]

    pooled = gm.post(
        "/api/setup/core-pool", json={"character_ids": [int(allowed["id"])]}
    )
    assert pooled.status_code == 200
    # 圈定后池内核心自动以激活人格补入编成。
    plan = gm.get("/api/plan").json()
    plan_cores = [f for f in plan["friendlies"] if int(f["is_core"])]
    assert [int(f["id"]) for f in plan_cores] == [int(allowed["id"])]

    gm.post("/api/setup/publish")
    banned_personas = player.get(f"/api/characters/{banned['id']}/personas").json()
    refused = player.post(
        "/api/setup/core",
        json={"choices": [[int(banned["id"]), int(banned_personas[0]["id"])]]},
    )
    assert refused.status_code == 400
    assert "不在本场可参战核心之列" in refused.json()["error"]

    allowed_personas = player.get(f"/api/characters/{allowed['id']}/personas").json()
    accepted = player.post(
        "/api/setup/core",
        json={"choices": [[int(allowed["id"]), int(allowed_personas[0]["id"])]]},
    )
    assert accepted.status_code == 200


# ---------------------------------------------------------------------------
# 书页体系（2026-07-27 裁定 2）：分级解锁 / 携带上限 / 预设
# ---------------------------------------------------------------------------
def test_deck_cap_and_presets(gm: TestClient, player: TestClient) -> None:
    catalog = player.get("/api/deck").json()
    keys = [item["abnormality_key"] for item in catalog["abnormalities"]]
    if len(keys) < 1:
        pytest.skip("测试内容包没有异想体")

    # 上限 5：超出直接拒绝（用重复补齐至 6 个不同键时才触发，键不足则跳过该断言）。
    if len(keys) >= 6:
        refused = player.post("/api/deck", json={"abnormality_keys": keys[:6]})
        assert refused.status_code == 400
        assert "最多携带" in refused.json()["error"]

    # 预设保存/列出/应用/删除。
    saved = player.post(
        "/api/deck/presets", json={"name": "演练编队", "abnormality_keys": keys[:1]}
    )
    assert saved.status_code == 200
    preset_id = int(saved.json()["id"])
    listed = player.get("/api/deck").json()["presets"]
    assert any(int(item["id"]) == preset_id for item in listed)

    applied = player.post("/api/deck", json={"abnormality_keys": keys[:1]})
    assert applied.status_code == 200

    deleted = player.post(f"/api/deck/presets/{preset_id}/delete")
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] == "演练编队"


def test_locked_abnormalities_hidden_from_player(gm: TestClient, player: TestClient) -> None:
    """2026-07-27 裁定：未开放的异想体对玩家不可见、不可携带；GM 可随时开放/收回。"""
    key = "webtest.abnormality.mirror"
    closed = gm.post(
        "/api/abnormalities/access", json={"abnormality_keys": [key], "opened": False}
    )
    assert closed.status_code == 200

    catalog = player.get("/api/deck").json()["abnormalities"]
    assert all(item["abnormality_key"] != key for item in catalog)
    refused = player.post("/api/deck", json={"abnormality_keys": [key]})
    assert refused.status_code == 400
    assert "尚未对玩家开放" in refused.json()["error"]

    gm_catalog = gm.get("/api/deck").json()["abnormalities"]
    assert any(
        item["abnormality_key"] == key and item["opened"] is False
        for item in gm_catalog
    )

    gm.post("/api/abnormalities/access", json={"abnormality_keys": [key], "opened": True})
    assert player.post("/api/deck", json={"abnormality_keys": [key]}).status_code == 200


def test_persona_access_controls_player(gm: TestClient, player: TestClient) -> None:
    """2026-07-27 裁定：人格默认不对玩家开放；默认人格恒开放且不可收回。"""
    roster = player.get("/api/roster", params={"faction": "FRIENDLY"}).json()
    target = None
    for core in (item for item in roster if int(item["is_core"])):
        personas = gm.get(f"/api/characters/{core['id']}/personas").json()
        non_default = next((p for p in personas if not int(p["is_default"])), None)
        if non_default is not None:
            target = (core, personas, non_default)
            break
    if target is None:
        pytest.skip("没有携带非默认人格的核心角色")
    core, personas, non_default = target

    # 新库中非默认人格默认未开放：玩家列表不可见、切换被拒。
    listed = player.get(f"/api/characters/{core['id']}/personas").json()
    assert all(p["persona_key"] != non_default["persona_key"] for p in listed)
    refused = player.post(
        "/api/identity",
        json={"character_id": core["id"], "persona_key": non_default["persona_key"]},
    )
    assert refused.status_code == 400
    assert "尚未对玩家开放" in refused.json()["error"]

    # 默认人格不能被收回。
    default = next(p for p in personas if int(p["is_default"]))
    cannot = gm.post(
        "/api/personas/access",
        json={"persona_keys": [default["persona_key"]], "opened": False},
    )
    assert cannot.status_code == 400
    assert "默认人格" in cannot.json()["error"]

    # 开放后玩家可见、可切换。
    opened = gm.post(
        "/api/personas/access",
        json={"persona_keys": [non_default["persona_key"]], "opened": True},
    )
    assert opened.status_code == 200
    listed = player.get(f"/api/characters/{core['id']}/personas").json()
    assert any(p["persona_key"] == non_default["persona_key"] for p in listed)
    switched = player.post(
        "/api/identity",
        json={"character_id": core["id"], "persona_key": non_default["persona_key"]},
    )
    assert switched.status_code == 200


def test_preset_enemies_can_be_toggled_and_removed(gm: TestClient) -> None:
    """2026-07-27 裁定：关卡预设敌人可切换携带/移除（只影响本场副本）。"""
    _prepare_full_setup(gm)
    plan = gm.get("/api/plan").json()
    preset = next(e for e in plan["enemies"] if e["source"] != "MANUAL")

    toggled = gm.post(
        "/api/setup/foes/toggle",
        json={"setup_enemy_id": preset["id"], "enabled": False},
    )
    assert toggled.status_code == 200
    assert "不携带" in toggled.json()["messages"][0]
    updated = next(
        e for e in gm.get("/api/plan").json()["enemies"] if e["id"] == preset["id"]
    )
    assert int(updated["enabled"]) == 0

    back = gm.post(
        "/api/setup/foes/toggle",
        json={"setup_enemy_id": preset["id"], "enabled": True},
    )
    assert back.status_code == 200

    removed = gm.post(
        "/api/setup/foes/remove", json={"setup_enemy_id": preset["id"]}
    )
    assert removed.status_code == 200
    assert all(
        e["id"] != preset["id"] for e in gm.get("/api/plan").json()["enemies"]
    )


def test_player_cannot_operate_assist_characters(
    gm: TestClient, player: TestClient
) -> None:
    """2026-07-27 裁定：助战是 GM 扮演的 NPC，玩家只能操作核心。"""
    ids = _launch_battle(gm)

    actors = player.get("/api/battle/actors", params={"side": "f"}).json()
    assert all(int(actor["is_core"]) == 1 for actor in actors)
    gm_actors = gm.get("/api/battle/actors", params={"side": "f"}).json()
    assert any(int(actor["id"]) == ids["helper_id"] for actor in gm_actors)

    refused = player.post(
        "/api/battle/action",
        json={"actor_id": ids["helper_id"], "skill_id": 1},
    )
    assert refused.status_code == 403
    assert "助战角色由管理人扮演" in refused.json()["error"]

    # 反向同样成立：GM 不能操作玩家的核心。
    refused_gm = gm.post(
        "/api/battle/action",
        json={"actor_id": ids["core_id"], "skill_id": 1},
    )
    assert refused_gm.status_code == 403
    assert "助战尚未行动完毕" in refused_gm.json()["error"]

    # 助战让行（静默）之后，GM 可以代操核心（不再 403）。
    forfeited = gm.post("/api/battle/forfeit-assists")
    assert forfeited.status_code == 200
    retry = gm.post(
        "/api/battle/action",
        json={"actor_id": ids["core_id"], "skill_id": 1},
    )
    assert retry.status_code != 403
    # 让行后助战出局、核心进入 GM 的行动名单（代操权已开启）。
    gm_actor_ids = {
        int(item["id"])
        for item in gm.get("/api/battle/actors", params={"side": "f"}).json()
    }
    assert ids["core_id"] in gm_actor_ids
    assert ids["helper_id"] not in gm_actor_ids


def test_mid_battle_reinforcements_join_immediately(gm: TestClient) -> None:
    """2026-07-27 裁定：GM 可在战斗中实时加入敌方与助战我方。"""
    _launch_battle(gm)
    before = gm.get("/api/battle").json()
    before_enemy = sum(
        1 for p in before["participants"]
        if p["faction"] == "ENEMY" and int(p["active_in_stage"])
    )

    # 敌方增援：不带 stage_number → 默认当前阶段，立即生成入场。
    joined = gm.post(
        "/api/setup/foes/add",
        json={"template_key": SECRET_ENEMY_TEMPLATE, "amount": 1, "name": "战地增援"},
    )
    assert joined.status_code == 200
    assert "追加" in joined.json()["messages"][0]
    after = gm.get("/api/battle").json()
    after_enemy = sum(
        1 for p in after["participants"]
        if p["faction"] == "ENEMY" and int(p["active_in_stage"])
    )
    assert after_enemy == before_enemy + 1

    # 助战增援：新建一名普通友方，战斗中加入立即成为参战者。
    create = gm.post("/api/create", json={"template_key": "unit.training_assistant", "name": "驰援人偶"})
    assert create.status_code == 200
    helper_id = int(create.json()["character_id"])
    allies = gm.post("/api/setup/allies/add", json={"character_ids": [helper_id]})
    assert allies.status_code == 200
    participants = gm.get("/api/battle").json()["participants"]
    assert any(
        int(p["id"]) == helper_id and int(p["active_in_stage"]) == 1
        for p in participants
    )
