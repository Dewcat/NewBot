"""Dewbot 本地 Web 前端：FastAPI 服务层。

权威契约：仓库根目录 ``WEB_FRONTEND_GUIDE.md``。本模块是与
``telegram_app.TelegramBattleAdapter`` 平级的第二个传输层：

- 不拥有任何战斗规则；所有裁决交给 :class:`dewbot.engine.BattleEngine`；
- 所有写操作经模块内单例 ``asyncio.Lock`` + ``asyncio.to_thread`` 串行执行，
  与 Telegram 适配器完全一致；
- 单玩家部署：只有 ``gm`` 与 ``player`` 两种角色（cookie ``dewbot_key``），
  当前选中战斗固定使用 ``user_id=0, chat_id=0`` 一条全局记录；
- 写操作成功后向 SSE（``GET /api/events``）广播该批引擎播报行。
"""

from __future__ import annotations

import asyncio
import json
import re
import logging
import secrets
import time
import weakref
from collections import deque
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from ..chat import ChatStore
from ..config import Settings
from ..content import ContentLoader
from ..db import Database
from ..engine import BattleEngine
from ..models import BattleRuleError, ContentValidationError, Faction


LOGGER = logging.getLogger(__name__)

COOKIE_NAME = "dewbot_key"
ROLE_GM = "gm"
ROLE_PLAYER = "player"
SSE_PING_SECONDS = 25
SSE_QUEUE_SIZE = 256
REPLAY_LOG_COUNT = 50

# 登录防爆破：同一来源 IP 在窗口期内失败次数达到上限后拒绝继续尝试；
# 每次失败额外附加固定延迟，压低单 IP 的穷举速度。公网部署必备。
LOGIN_MAX_FAILURES = 10
LOGIN_WINDOW_SECONDS = 600
LOGIN_FAILURE_DELAY_SECONDS = 0.3
LOGIN_TRACKED_IPS_MAX = 4096

STATIC_DIR = Path(__file__).resolve().parent / "static"

_PLACEHOLDER_HTML = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Dewbot Web</title></head>
<body style="margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
background:#16161d;color:#d6d6e0;font-family:system-ui,'Microsoft YaHei',sans-serif">
<div style="max-width:32rem;padding:2rem;text-align:center">
<h1 style="font-size:1.4rem">Dewbot Web 服务已运行</h1>
<p>静态前端文件（<code>src/dewbot/web/static/index.html</code>）尚未就位；
API 层工作正常，可通过 <code>POST /api/login</code> 登录后调用 <code>/api/*</code> 接口。</p>
</div></body></html>
"""

_MEDIA_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".webmanifest": "application/manifest+json",
    ".woff2": "font/woff2",
}


class ApiError(Exception):
    """携带 HTTP 状态码的传输层错误；正文统一为 {"error": message}。"""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = int(status_code)
        self.message = str(message)


# ---------------------------------------------------------------------------
# 模块内单例写锁
# ---------------------------------------------------------------------------
# 所有写路由共用同一把锁（与 Telegram 适配器的 _mutation_lock 语义一致）。
# asyncio.Lock 在 Python 3.12 中绑定到首次使用它的事件循环，因此按运行中的
# 循环惰性建锁：uvicorn 进程只有一个循环，得到的就是全进程唯一写闸门；
# 测试里多个 TestClient 各自的循环互不串扰。跨进程互斥由 FrontendLock 保证。
_WRITE_LOCKS: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Lock]" = (
    weakref.WeakKeyDictionary()
)


def _write_lock() -> asyncio.Lock:
    loop = asyncio.get_running_loop()
    lock = _WRITE_LOCKS.get(loop)
    if lock is None:
        lock = asyncio.Lock()
        _WRITE_LOCKS[loop] = lock
    return lock


# ---------------------------------------------------------------------------
# 参数与负载解析（不用 pydantic，保证错误正文统一为 {"error": ...}）
# ---------------------------------------------------------------------------
async def _payload(request: Request) -> dict[str, Any]:
    raw = await request.body()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ApiError(400, "请求体必须是合法的 JSON。") from exc
    if not isinstance(data, dict):
        raise ApiError(400, "请求体必须是 JSON 对象。")
    return data


def _as_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or value is None:
        raise ApiError(400, f"{field} 必须是整数。")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ApiError(400, f"{field} 必须是整数。") from exc


def _as_str(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ApiError(400, f"{field} 必须是非空字符串。")
    return value.strip()


def _as_int_list(value: Any, field: str) -> list[int]:
    if not isinstance(value, list):
        raise ApiError(400, f"{field} 必须是整数数组。")
    return [_as_int(item, field) for item in value]


def _as_str_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list):
        raise ApiError(400, f"{field} 必须是字符串数组。")
    return [_as_str(item, field) for item in value]


def _as_choice_pairs(value: Any, field: str) -> list[tuple[int, int]]:
    if not isinstance(value, list):
        raise ApiError(400, f"{field} 必须是 [[character_id, persona_id], ...] 数组。")
    pairs: list[tuple[int, int]] = []
    for item in value:
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            raise ApiError(400, f"{field} 每一项必须是 [character_id, persona_id]。")
        pairs.append((_as_int(item[0], field), _as_int(item[1], field)))
    return pairs


_FACTION_ALIASES = {
    "friendly": Faction.FRIENDLY,
    "f": Faction.FRIENDLY,
    "我方": Faction.FRIENDLY,
    "enemy": Faction.ENEMY,
    "e": Faction.ENEMY,
    "敌方": Faction.ENEMY,
}


def _parse_faction(raw: str) -> Faction:
    faction = _FACTION_ALIASES.get(raw.strip().lower())
    if faction is None:
        raise ApiError(400, "faction 仅接受 FRIENDLY 或 ENEMY。")
    return faction


# ---------------------------------------------------------------------------
# SSE 编码
# ---------------------------------------------------------------------------
def _sse_event(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _strip_admin_hints(message: str) -> str:
    """过滤播报中的管理流程提示行（〔管理〕标记；含历史存量）。"""
    lines = [
        line for line in str(message).split("\n")
        if "〔管理〕" not in line
    ]
    rendered = "\n".join(lines).strip()
    rendered = rendered.replace("敌方指令阶段：管理员设置技能与目标后锁定，玩家再行动。", "敌方正在准备行动。")
    rendered = rendered.replace("敌方指令已锁定，玩家可查看技能与目标并发布攻击或防御指令。", "敌方行动已确定，选择你的应对。")
    rendered = re.sub(r"指令 #\d+[：:]\s*", "", rendered)
    rendered = re.sub(r"指令 #\d+", "攻击", rendered)
    return rendered


def _recent_battle_logs(engine: BattleEngine, limit: int) -> list[str]:
    rows = engine.database.fetch_all(
        """
        SELECT message FROM battle_logs
        WHERE battle_id=(SELECT id FROM battles WHERE status='ACTIVE')
        ORDER BY id DESC LIMIT ?
        """,
        (int(limit),),
    )
    return [
        _strip_admin_hints(row["message"])
        for row in reversed(rows)
        if _strip_admin_hints(row["message"])
    ]


# ---------------------------------------------------------------------------
# 静态资源
# ---------------------------------------------------------------------------
def _resolve_static_file(relative: str) -> Path | None:
    """在 static/ 内解析文件；目录可能尚不存在（前端并行开发中）。"""
    if not STATIC_DIR.is_dir():
        return None
    candidates = [relative]
    if relative.startswith("static/"):
        candidates.append(relative[len("static/"):])
    root = STATIC_DIR.resolve()
    for candidate in candidates:
        if not candidate or "\x00" in candidate:
            continue
        try:
            full = (root / candidate).resolve()
        except OSError:
            continue
        if full.is_file() and full.is_relative_to(root):
            return full
    return None


def _static_response(path: Path) -> FileResponse:
    # no-cache：每次加载都向服务器校验新鲜度，UI 更新后普通刷新即生效，
    # 避免浏览器内存缓存吃掉前端改动（2026-07-27 反馈）。
    return FileResponse(
        path,
        media_type=_MEDIA_TYPES.get(path.suffix.lower()),
        headers={"Cache-Control": "no-cache"},
    )


# ---------------------------------------------------------------------------
# 应用工厂
# ---------------------------------------------------------------------------
def create_app(
    settings: Settings,
    engine: BattleEngine | None = None,
    loader: ContentLoader | None = None,
) -> FastAPI:
    """依赖注入方式与 ``telegram_app.create_application`` 一致。

    不传 engine 时自行建库并初始化 schema；内容包加载仍由调用方（main 或
    ``POST /api/reload``）显式完成。
    """
    if not settings.web_gm_key and not settings.web_player_key:
        raise ValueError(
            "DEWBOT_WEB_GM_KEY 与 DEWBOT_WEB_PLAYER_KEY 均未配置；"
            "两种角色都无法登录，Web 前端拒绝启动。"
        )
    if (
        settings.web_gm_key
        and settings.web_player_key
        and settings.web_gm_key == settings.web_player_key
    ):
        raise ValueError(
            "DEWBOT_WEB_GM_KEY 与 DEWBOT_WEB_PLAYER_KEY 不能相同：同一把密钥"
            "会先匹配到管理人身份，玩家角色将永远无法登录。请设置两把不同的密钥。"
        )
    if engine is None:
        database = Database(settings.database_path)
        database.initialize()
        engine = BattleEngine(database)
    if loader is None:
        loader = ContentLoader(engine.database, engine.registry.keys)

    # Swagger/OpenAPI 页面依赖外链资源，离线部署直接关闭。
    app = FastAPI(title="Dewbot Web", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.settings = settings
    app.state.engine = engine
    app.state.loader = loader
    sse_clients: set[asyncio.Queue[str]] = set()
    app.state.sse_clients = sse_clients
    chat_store = ChatStore(engine.database)
    app.state.chat_store = chat_store
    from ..story import open_story_store

    story_store = open_story_store(settings)
    app.state.story_store = story_store
    from ..assistant import PrivacyStore, WritingAssistant

    writing_assistant = WritingAssistant(PrivacyStore(engine.database), story_store, settings)
    app.state.writing_assistant = writing_assistant

    # -- 错误统一整形 ----------------------------------------------------
    @app.exception_handler(ApiError)
    async def _api_error(request: Request, exc: ApiError) -> JSONResponse:
        del request
        return JSONResponse(status_code=exc.status_code, content={"error": exc.message})

    @app.exception_handler(BattleRuleError)
    async def _rule_error(request: Request, exc: BattleRuleError) -> JSONResponse:
        del request
        return JSONResponse(status_code=400, content={"error": str(exc)})

    @app.exception_handler(ContentValidationError)
    async def _content_error(
        request: Request, exc: ContentValidationError
    ) -> JSONResponse:
        del request
        return JSONResponse(status_code=400, content={"error": str(exc)})

    @app.exception_handler(ValueError)
    async def _value_error(request: Request, exc: ValueError) -> JSONResponse:
        del request
        return JSONResponse(status_code=400, content={"error": str(exc)})

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        del request
        return JSONResponse(
            status_code=exc.status_code, content={"error": str(exc.detail)}
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        del request, exc
        return JSONResponse(status_code=400, content={"error": "请求参数无效。"})

    @app.exception_handler(Exception)
    async def _server_error(request: Request, exc: Exception) -> JSONResponse:
        LOGGER.exception("未处理的服务端异常：%s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500, content={"error": f"服务器内部错误：{exc}"}
        )

    # -- 身份 ------------------------------------------------------------
    def _key_matches(candidate: str, configured: str | None) -> bool:
        if not configured:
            return False
        return secrets.compare_digest(
            candidate.encode("utf-8"), configured.encode("utf-8")
        )

    def _role_of(request: Request) -> str | None:
        key = request.cookies.get(COOKIE_NAME) or ""
        if not key:
            return None
        if _key_matches(key, settings.web_gm_key):
            return ROLE_GM
        if _key_matches(key, settings.web_player_key):
            return ROLE_PLAYER
        return None

    def _require_role(request: Request) -> str:
        role = _role_of(request)
        if role is None:
            raise ApiError(401, "未登录或访问密钥已失效，请重新登录。")
        return role

    def _require_gm(request: Request) -> str:
        role = _require_role(request)
        if role != ROLE_GM:
            raise ApiError(403, "该操作仅限管理人（GM）使用。")
        return role

    # -- 引擎调用与广播 --------------------------------------------------
    async def _read(func: Any, /, *args: Any, **kwargs: Any) -> Any:
        return await asyncio.to_thread(func, *args, **kwargs)

    async def _locked(func: Any, /, *args: Any, **kwargs: Any) -> Any:
        async with _write_lock():
            return await asyncio.to_thread(func, *args, **kwargs)

    def _broadcast(event: str, payload: dict[str, Any]) -> None:
        """向所有 SSE 连接推送单个事件（聊天/已读等）。"""
        item = _sse_event(event, payload)
        for queue in list(sse_clients):
            try:
                queue.put_nowait(item)
            except asyncio.QueueFull:
                pass

    def _notify(lines: list[str], *, paced: bool = True) -> None:
        """向所有 SSE 连接广播一批播报行，随后跟一条 refresh 提示。"""
        cleaned = [str(line) for line in lines if str(line).strip()]
        events: list[str] = []
        if cleaned:
            events.append(_sse_event("log", {"lines": cleaned, "interval_ms": 1500 if paced else 0}))
        events.append(_sse_event("refresh", {}))
        for queue in list(sse_clients):
            for item in events:
                try:
                    queue.put_nowait(item)
                except asyncio.QueueFull:
                    break  # 慢客户端丢事件；下次 refresh 会补全状态

    def _selected_setup_id() -> int:
        # Web 端全局只有一条"当前选中"记录（user_id=0, chat_id=0），见契约 §7。
        return engine.selected_battle_setup_id(0, chat_id=0)

    # -- 登录 ------------------------------------------------------------
    # 失败记录按来源 IP 存滑动窗口时间戳。经本机反向代理/隧道访问时，
    # uvicorn 默认信任 127.0.0.1 发来的 X-Forwarded-For，request.client
    # 已还原为真实来源 IP。
    login_failures: dict[str, deque[float]] = {}

    def _client_ip(request: Request) -> str:
        return request.client.host if request.client else "unknown"

    def _login_blocked(ip: str) -> bool:
        now = time.monotonic()
        window = login_failures.get(ip)
        if window is None:
            return False
        while window and now - window[0] > LOGIN_WINDOW_SECONDS:
            window.popleft()
        if not window:
            del login_failures[ip]
            return False
        return len(window) >= LOGIN_MAX_FAILURES

    def _record_login_failure(ip: str) -> None:
        if ip not in login_failures and len(login_failures) >= LOGIN_TRACKED_IPS_MAX:
            # 容量兜底：丢弃最早建档的来源，避免恶意海量 IP 撑爆内存。
            login_failures.pop(next(iter(login_failures)))
        login_failures.setdefault(ip, deque()).append(time.monotonic())

    @app.post("/api/login")
    async def login(request: Request) -> JSONResponse:
        body = await _payload(request)
        key = _as_str(body.get("key"), "key")
        ip = _client_ip(request)
        if _login_blocked(ip):
            LOGGER.warning("登录尝试过于频繁，已暂时拒绝来源 %s", ip)
            raise ApiError(
                429,
                f"登录失败次数过多，请约 {LOGIN_WINDOW_SECONDS // 60} 分钟后再试。",
            )
        role: str | None = None
        if _key_matches(key, settings.web_gm_key):
            role = ROLE_GM
        elif _key_matches(key, settings.web_player_key):
            role = ROLE_PLAYER
        if role is None:
            _record_login_failure(ip)
            LOGGER.warning("登录失败（密钥不正确），来源 %s", ip)
            await asyncio.sleep(LOGIN_FAILURE_DELAY_SECONDS)
            raise ApiError(401, "访问密钥不正确。")
        login_failures.pop(ip, None)
        response = JSONResponse({"role": role, **({"story_enabled": True} if story_store else {})})
        response.set_cookie(
            COOKIE_NAME,
            key,
            httponly=True,
            samesite="lax",
            path="/",
            secure=bool(getattr(settings, "web_secure_cookie", False)),
        )
        return response

    @app.post("/api/logout")
    async def logout(request: Request) -> JSONResponse:
        del request
        response = JSONResponse({"ok": True})
        response.delete_cookie(COOKIE_NAME, path="/")
        return response

    # -- 只读接口（契约 §5） ---------------------------------------------
    @app.get("/api/session")
    async def session(request: Request) -> dict[str, Any]:
        role = _require_role(request)

        def _state() -> dict[str, Any]:
            row = engine.database.fetch_one(
                "SELECT phase FROM battles WHERE status='ACTIVE'"
            )
            return {
                "has_active_battle": row is not None,
                "phase": row["phase"] if row is not None else None,
            }

        state = await _read(_state)
        return {"role": role, **state, **({"story_enabled": True} if story_store else {})}

    @app.get("/api/overview")
    async def overview(request: Request) -> dict[str, Any]:
        role = _require_role(request)

        def _overview() -> dict[str, Any]:
            try:
                battle = engine.battle_status()
            except BattleRuleError:
                battle = None
            try:
                setup = engine.battle_setup_status(user_id=0, chat_id=0)
            except BattleRuleError:
                setup = None
            return {
                "battle": battle,
                "setup": setup,
                "page_offers": engine.pending_page_offers(),
            }

        data = await _read(_overview)
        data["role"] = role
        return data

    @app.get("/api/roster")
    async def roster(request: Request) -> list[dict[str, Any]]:
        _require_role(request)
        raw = request.query_params.get("faction")
        faction = _parse_faction(raw) if raw else None
        return await _read(engine.list_characters, faction)

    @app.get("/api/characters/{character_id}/personas")
    async def character_personas(
        request: Request, character_id: int
    ) -> list[dict[str, Any]]:
        role = _require_role(request)
        personas = await _read(engine.list_personas, character_id)
        if role != ROLE_GM:
            # 未开放的人格对玩家不可见（当前装备中的仍显示，2026-07-27 裁定）。
            personas = [
                item for item in personas
                if item.get("opened") or item.get("is_active")
            ]
        return personas

    @app.post("/api/personas/access")
    async def persona_access(request: Request) -> dict[str, Any]:
        _require_gm(request)
        body = await _payload(request)
        keys = _as_str_list(body.get("persona_keys"), "persona_keys")
        opened = bool(body.get("opened"))
        names = await _locked(engine.set_persona_access, keys, opened)
        return {"names": names, "opened": opened}

    @app.get("/api/characters/{character_id}/skills")
    async def character_skills(
        request: Request, character_id: int
    ) -> list[dict[str, Any]]:
        role = _require_role(request)
        character = await _read(engine.get_character, character_id)
        if character["faction"] != Faction.FRIENDLY.value and role != ROLE_GM:
            raise ApiError(403, "敌方技能档案仅限管理人查阅。")
        return await _read(engine.skill_catalog, character_id)

    @app.get("/api/battle")
    async def battle(request: Request) -> dict[str, Any]:
        _require_role(request)
        return await _read(engine.battle_status)

    @app.get("/api/battles")
    async def battles(request: Request) -> list[dict[str, Any]]:
        _require_gm(request)
        return await _read(engine.list_battle_setups)

    @app.get("/api/plan")
    async def plan(request: Request) -> dict[str, Any]:
        role = _require_role(request)
        result = await _read(engine.battle_setup_status, user_id=0, chat_id=0)
        if role != ROLE_GM:
            # 裁定 §7.5-5：玩家在开战前看不到敌方阵容，只知道敌人数量。
            result["enemy_count"] = len(result.get("enemies") or [])
            result.pop("enemies", None)
        return result

    @app.get("/api/encounters")
    async def encounters(request: Request) -> list[dict[str, Any]]:
        _require_gm(request)
        return await _read(engine.list_encounters)

    @app.get("/api/templates")
    async def templates(request: Request) -> list[dict[str, Any]]:
        _require_gm(request)
        return await _read(engine.list_templates)

    @app.get("/api/abnormalities")
    async def abnormalities(request: Request) -> list[dict[str, Any]]:
        _require_gm(request)
        return await _read(engine.list_abnormalities)

    @app.get("/api/pages")
    async def pages(request: Request) -> list[dict[str, Any]]:
        _require_role(request)
        return await _read(engine.pending_page_offers)

    @app.get("/api/manager")
    async def manager(request: Request) -> list[dict[str, Any]]:
        # 干预能力（"光之树苗"）是经理＝玩家的战局手段，GM 亦可查看（2026-07-26 裁定）。
        _require_role(request)

        def _rows() -> list[dict[str, Any]]:
            # 与 Telegram `_available_manager_skills` 相同的查询。
            with engine.database.reading() as connection:
                active = connection.execute(
                    "SELECT id FROM battles WHERE status='ACTIVE'"
                ).fetchone()
                if active is None:
                    return []
                rows = connection.execute(
                    """
                    SELECT m.*,COALESCE(u.uses,0) AS uses
                    FROM manager_skills m
                    LEFT JOIN manager_unlocks unlock ON unlock.unlock_key=m.unlock_key
                    LEFT JOIN manager_skill_usage u
                        ON u.manager_skill_id=m.id AND u.battle_id=?
                    WHERE m.enabled=1 AND (
                        m.unlock_key IS NULL OR m.unlock_key=''
                        OR unlock.unlock_key IS NOT NULL
                    )
                      AND (m.allowed_phase IS NULL OR m.allowed_phase=(
                          SELECT phase FROM battles WHERE id=?
                      ))
                      AND COALESCE(u.uses,0) < m.max_uses_per_battle
                    ORDER BY m.id
                    """,
                    (active["id"], active["id"]),
                ).fetchall()
                return [dict(row) for row in rows]

        return await _read(_rows)

    @app.get("/api/battle/actors")
    async def battle_actors(request: Request) -> list[dict[str, Any]]:
        role = _require_role(request)
        side = (request.query_params.get("side") or "f").strip().lower()
        if side not in {"f", "e"}:
            raise ApiError(400, "side 仅接受 f（我方）或 e（敌方）。")
        if side == "e" and role != ROLE_GM:
            raise ApiError(403, "敌方行动名单仅限管理人查阅。")
        faction = Faction.FRIENDLY if side == "f" else Faction.ENEMY

        def _actors() -> list[dict[str, Any]]:
            status = engine.battle_status()
            rows = [
                row
                for row in status.get("participants", [])
                if row["faction"] == faction.value
                and int(row.get("active_in_stage", 0)) == 1
                and int(row["current_hp"]) > 0
                and int(row["current_actions"]) > 0
                and not int(row["is_staggered"])
            ]
            if faction == Faction.FRIENDLY:
                # 分工（2026-07-27 裁定）：玩家只操作核心；GM 只操作助战（NPC），
                # 但助战行动完/让行后 GM 也可以代操核心。
                assists_pending = any(
                    int(row.get("is_core", 0)) == 0 for row in rows
                )
                if role == ROLE_GM:
                    if assists_pending:
                        rows = [row for row in rows if int(row.get("is_core", 0)) == 0]
                else:
                    rows = [row for row in rows if int(row.get("is_core", 0)) == 1]
            return rows

        return await _read(_actors)

    async def _guard_enemy_actor(request: Request, character_id: int) -> str:
        role = _require_role(request)
        character = await _read(engine.get_character, character_id)
        if character["faction"] != Faction.FRIENDLY.value and role != ROLE_GM:
            raise ApiError(403, "敌方技能详情仅限管理人查阅。")
        return role

    @app.get("/api/actors/{character_id}/skills")
    async def actor_skills(
        request: Request, character_id: int
    ) -> list[dict[str, Any]]:
        await _guard_enemy_actor(request, character_id)
        # 返回全部技能（含冷却中的）：UI 将不可用的排到末尾置灰并标注原因。
        return await _read(engine.list_skills, character_id)

    @app.get("/api/actors/{character_id}/skills/{skill_id}/targets")
    async def actor_skill_targets(
        request: Request, character_id: int, skill_id: int
    ) -> list[dict[str, Any]]:
        await _guard_enemy_actor(request, character_id)
        return await _read(engine.legal_targets, character_id, skill_id)

    # -- 跑团聊天（契约 §7.5-3：跨战斗连续主频道） -----------------------
    def _load_channel_history(limit: int) -> list[dict[str, Any]]:
        """按时间合并最近的战斗播报与聊天消息（升序）。

        活跃战斗当前回合的播报标记 ``current=True``：刷新/重连后仍按"活跃"
        样式渲染，只有更早的内容才作为历史置灰（2026-07-26 反馈）。
        """
        active = engine.database.fetch_one(
            "SELECT id,current_turn FROM battles WHERE status='ACTIVE'"
        )
        logs = engine.database.fetch_all(
            "SELECT id,battle_id,turn_number,message,payload_json,created_at"
            " FROM battle_logs ORDER BY id DESC LIMIT ?",
            (int(limit),),
        )
        battle_ids = sorted({int(row["battle_id"]) for row in logs})
        factions_by_battle: dict[int, list[dict[str, str]]] = {
            battle_id: [] for battle_id in battle_ids
        }
        if battle_ids:
            placeholders = ",".join("?" for _ in battle_ids)
            participant_rows = engine.database.fetch_all(
                f"""
                SELECT bp.battle_id,c.name,c.faction
                FROM battle_participants bp
                JOIN characters c ON c.id=bp.character_id
                WHERE bp.battle_id IN ({placeholders})
                ORDER BY bp.battle_id,bp.character_id
                """,
                tuple(battle_ids),
            )
            for participant in participant_rows:
                factions_by_battle[int(participant["battle_id"])].append({
                    "name": str(participant["name"]),
                    "faction": str(participant["faction"]),
                })
        items: list[dict[str, Any]] = []
        for row in reversed(logs):
            message = _strip_admin_hints(row["message"])
            if message:
                payload = json.loads(str(row["payload_json"] or "{}"))
                factions = payload.get("participant_factions")
                if not isinstance(factions, list):
                    factions = factions_by_battle.get(int(row["battle_id"]), [])
                items.append({
                    "type": "log",
                    "message": message,
                    "created_at": str(row["created_at"]),
                    "factions": factions,
                    "current": bool(
                        active is not None
                        and int(row["battle_id"]) == int(active["id"])
                        and int(row["turn_number"]) == int(active["current_turn"])
                    ),
                })
        for entry in chat_store.list_recent(limit=limit):
            items.append({
                "type": "chat",
                "message": entry,
                "created_at": str(entry["created_at"]),
            })
        items.sort(key=lambda item: str(item["created_at"]))
        return items

    @app.get("/api/channel/history")
    async def channel_history(request: Request) -> dict[str, Any]:
        _require_role(request)
        return {"items": await _read(_load_channel_history, REPLAY_LOG_COUNT)}

    @app.get("/api/chat")
    async def chat_list(request: Request) -> list[dict[str, Any]]:
        _require_role(request)
        params = request.query_params
        before_raw = (params.get("before_id") or "").strip()
        before_id = int(before_raw) if before_raw.isdecimal() else None
        limit_raw = (params.get("limit") or "").strip()
        limit = int(limit_raw) if limit_raw.isdecimal() else 50
        return await _read(chat_store.list_recent, before_id=before_id, limit=limit)

    @app.get("/api/chat/search")
    async def chat_search(request: Request) -> list[dict[str, Any]]:
        _require_role(request)
        query = (request.query_params.get("q") or "").strip()
        return await _read(chat_store.search, query)

    @app.post("/api/chat")
    async def chat_post(request: Request) -> dict[str, Any]:
        role = _require_role(request)
        body = await _payload(request)
        message = await _locked(chat_store.post, role, _as_str(body.get("content"), "content"))
        _broadcast("chat", {"action": "new", "message": message})
        return message

    @app.post("/api/chat/{message_id}/edit")
    async def chat_edit(request: Request, message_id: int) -> dict[str, Any]:
        role = _require_role(request)
        body = await _payload(request)
        message = await writing_assistant.change_context(lambda: _locked(
            chat_store.edit, message_id, role, _as_str(body.get("content"), "content")
        ))
        _broadcast("chat", {"action": "edit", "message": message})
        return message

    @app.post("/api/chat/{message_id}/revoke")
    async def chat_revoke(request: Request, message_id: int) -> dict[str, Any]:
        role = _require_role(request)
        message = await writing_assistant.change_context(lambda: _locked(chat_store.revoke, message_id, role))
        _broadcast("chat", {"action": "revoke", "message": message})
        return message

    @app.post("/api/chat/read")
    async def chat_read(request: Request) -> dict[str, Any]:
        role = _require_role(request)
        body = await _payload(request)
        up_to_id = _as_int(body.get("up_to_id"), "up_to_id")
        changed = await _locked(chat_store.mark_read, role, up_to_id)
        if changed:
            _broadcast("chat_read", {"role": role, "up_to_id": up_to_id})
        return {"marked": changed}

    # -- SSE（契约 §4） ---------------------------------------------------
    @app.get("/api/events")
    async def events(request: Request) -> StreamingResponse:
        _require_role(request)
        # replay=0：客户端改用 /api/channel/history 拉合并历史，SSE 只推增量。
        skip_replay = (request.query_params.get("replay") or "").strip() == "0"
        queue: asyncio.Queue[str] = asyncio.Queue(maxsize=SSE_QUEUE_SIZE)

        async def _stream() -> Any:
            sse_clients.add(queue)
            try:
                if not skip_replay:
                    lines = await _read(_recent_battle_logs, engine, REPLAY_LOG_COUNT)
                    yield _sse_event("log", {"lines": lines, "replay": True})
                else:
                    yield ": connected\n\n"
                while True:
                    try:
                        item = await asyncio.wait_for(
                            queue.get(), timeout=SSE_PING_SECONDS
                        )
                    except asyncio.TimeoutError:
                        yield ": ping\n\n"
                        continue
                    yield item
            finally:
                sse_clients.discard(queue)

        return StreamingResponse(
            _stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-store",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    # -- 写接口：玩家可用（契约 §6） --------------------------------------
    @app.post("/api/battle/action")
    async def battle_action(request: Request) -> dict[str, Any]:
        role = _require_role(request)
        body = await _payload(request)
        actor_id = _as_int(body.get("actor_id"), "actor_id")
        skill_id = _as_int(body.get("skill_id"), "skill_id")
        target_ids = (
            _as_int_list(body.get("target_ids"), "target_ids")
            if body.get("target_ids") is not None
            else None
        )
        actor = await _read(engine.get_character, actor_id)
        if role != ROLE_GM:
            if actor["faction"] != Faction.FRIENDLY.value:
                raise ApiError(403, "玩家只能为我方单位行动；敌方行动仅限管理人。")
            if not int(actor["is_core"]):
                raise ApiError(403, "助战角色由管理人扮演操作；你只能操作核心角色。")
        elif actor["faction"] == Faction.FRIENDLY.value and int(actor["is_core"]):
            # 助战全部行动完/让行后，GM 可代操核心；此前仍归玩家。
            def _assists_pending() -> bool:
                return engine.database.fetch_one(
                    """
                    SELECT 1 FROM characters c
                    JOIN battle_participants bp ON bp.character_id=c.id
                    JOIN battles b ON b.id=bp.battle_id AND b.status='ACTIVE'
                    WHERE bp.active_in_stage=1 AND c.faction='FRIENDLY'
                      AND c.is_core=0 AND c.current_hp>0
                      AND c.is_staggered=0 AND c.current_actions>0
                    LIMIT 1
                    """
                ) is not None

            if await _read(_assists_pending):
                raise ApiError(403, "助战尚未行动完毕；先操作助战或点「助战让行」。")
        result = await _locked(engine.use_skill, actor_id, skill_id, target_ids or None)
        messages = list(result.messages)
        _notify(messages)
        return {
            "messages": messages,
            "battle_id": result.battle_id,
            "actor_id": result.actor_id,
            "skill_id": result.skill_id,
            "phase": result.phase.value,
        }

    # -- 写接口：GM 专用（契约 §6） ---------------------------------------
    @app.post("/api/setup/new")
    async def setup_new(request: Request) -> dict[str, Any]:
        _require_gm(request)
        body = await _payload(request)
        encounter_key = _as_str(body.get("encounter_key"), "encounter_key")
        name = body.get("name")
        if name is not None:
            name = _as_str(name, "name")

        def _do() -> tuple[int, list[str]]:
            setup_id = engine.prepare_encounter(
                encounter_key, name=name, created_by=0, selection_chat_id=0
            )
            status = engine.battle_setup_status(setup_id)
            return setup_id, [
                f"【已建立并选中】#{setup_id}｜{status['name']}"
                f"（关卡：{status['encounter_name']}）"
            ]

        setup_id, messages = await _locked(_do)
        _notify(messages)
        return {"messages": messages, "setup_id": setup_id}

    @app.post("/api/setup/use")
    async def setup_use(request: Request) -> dict[str, Any]:
        _require_gm(request)
        body = await _payload(request)
        setup_id = _as_int(body.get("setup_id"), "setup_id")

        def _do() -> list[str]:
            setup = engine.select_battle_setup(0, setup_id, chat_id=0)
            return [f"【已选中】#{setup['id']}｜{setup['name']}"]

        messages = await _locked(_do)
        _notify(messages)
        return {"messages": messages, "setup_id": setup_id}

    @app.post("/api/setup/discard")
    async def setup_discard(request: Request) -> dict[str, Any]:
        _require_gm(request)

        def _do() -> list[str]:
            engine.cancel_battle_setup(user_id=0)
            return ["【战斗筹备已撤销】关卡容器没有生成正式战斗。"]

        messages = await _locked(_do)
        _notify(messages)
        return {"messages": messages}

    @app.post("/api/setup/core-pool")
    async def setup_core_pool(request: Request) -> dict[str, Any]:
        _require_gm(request)
        body = await _payload(request)
        character_ids = _as_int_list(body.get("character_ids"), "character_ids")

        def _do() -> list[str]:
            names = engine.set_setup_core_pool(
                character_ids, setup_id=_selected_setup_id()
            )
            return ["【可参战核心已圈定】" + ("、".join(names) or "（已清空）")]

        messages = await _locked(_do)
        _notify(messages)
        return {"messages": messages}

    @app.post("/api/setup/core")
    async def setup_core(request: Request) -> dict[str, Any]:
        await _require_setup_participant(request)
        body = await _payload(request)
        choices = _as_choice_pairs(body.get("choices"), "choices")

        def _do() -> list[str]:
            setup_id = _selected_setup_id()
            engine.replace_core_formation(setup_id, choices)
            status = engine.battle_setup_status(setup_id)
            names = [
                str(item["name"])
                for item in status["friendlies"]
                if int(item["is_core"])
            ]
            return ["【核心编成已更新】" + ("、".join(names) or "（已清空）")]

        messages = await _locked(_do)
        _notify(messages)
        return {"messages": messages}

    @app.post("/api/setup/allies/add")
    async def setup_allies_add(request: Request) -> dict[str, Any]:
        _require_gm(request)
        body = await _payload(request)
        character_ids = _as_int_list(body.get("character_ids"), "character_ids")

        def _do() -> list[str]:
            setup_id = _selected_setup_id()
            engine.add_noncore_friendlies_to_setup(character_ids, setup_id=setup_id)
            names = [
                str(engine.get_character(character_id)["name"])
                for character_id in character_ids
            ]
            return ["【友方增援已编入】" + "、".join(names)]

        messages = await _locked(_do)
        _notify(messages)
        return {"messages": messages}

    @app.post("/api/setup/allies/remove")
    async def setup_allies_remove(request: Request) -> dict[str, Any]:
        _require_gm(request)
        body = await _payload(request)
        character_id = _as_int(body.get("character_id"), "character_id")

        def _do() -> list[str]:
            setup_id = _selected_setup_id()
            name = str(engine.get_character(character_id)["name"])
            engine.remove_noncore_friendly_from_setup(character_id, setup_id=setup_id)
            return [f"【友方增援已移出】{name}"]

        messages = await _locked(_do)
        _notify(messages)
        return {"messages": messages}

    @app.post("/api/setup/foes/add")
    async def setup_foes_add(request: Request) -> dict[str, Any]:
        _require_gm(request)
        body = await _payload(request)
        template_key = _as_str(body.get("template_key"), "template_key")
        stage_number = (
            _as_int(body.get("stage_number"), "stage_number")
            if body.get("stage_number") is not None
            else None
        )
        amount = (
            _as_int(body.get("amount"), "amount")
            if body.get("amount") is not None
            else 1
        )
        name = body.get("name")
        if name is not None:
            name = _as_str(name, "name")

        def _do() -> list[str]:
            setup_id = _selected_setup_id()
            message = engine.add_enemy_to_formation(
                template_key,
                stage=stage_number,
                amount=amount,
                name=name,
                setup_id=setup_id,
            )
            return [message]

        messages = await _locked(_do)
        _notify(messages)
        return {"messages": messages}

    @app.post("/api/setup/foes/toggle")
    async def setup_foes_toggle(request: Request) -> dict[str, Any]:
        _require_gm(request)
        body = await _payload(request)
        setup_enemy_id = _as_int(body.get("setup_enemy_id"), "setup_enemy_id")
        enabled = bool(body.get("enabled"))

        def _do() -> list[str]:
            return [engine.set_setup_enemy_enabled(
                setup_enemy_id, enabled, setup_id=_selected_setup_id()
            )]

        messages = await _locked(_do)
        _notify(messages)
        return {"messages": messages}

    @app.post("/api/setup/foes/remove")
    async def setup_foes_remove(request: Request) -> dict[str, Any]:
        _require_gm(request)
        body = await _payload(request)
        setup_enemy_id = _as_int(body.get("setup_enemy_id"), "setup_enemy_id")

        def _do() -> list[str]:
            setup_id = _selected_setup_id()
            return [
                engine.remove_manual_enemy_from_setup(
                    setup_enemy_id, setup_id=setup_id
                )
            ]

        messages = await _locked(_do)
        _notify(messages)
        return {"messages": messages}

    @app.post("/api/setup/gear")
    async def setup_gear(request: Request) -> dict[str, Any]:
        await _require_setup_participant(request)
        body = await _payload(request)
        keys = _as_str_list(body.get("abnormality_keys"), "abnormality_keys")

        def _do() -> list[str]:
            setup_id = _selected_setup_id()
            accepted = engine.set_setup_abnormalities(keys, setup_id=setup_id)
            return ["【异想体装备已更新】" + ("、".join(accepted) or "（已清空）")]

        messages = await _locked(_do)
        _notify(messages)
        return {"messages": messages}

    def _ready_checked_setup() -> dict[str, Any]:
        """触发前核对；校验口径与 Telegram ready_command 一致。"""
        setup_id = _selected_setup_id()
        setup = engine.battle_setup_status(setup_id)
        if setup["status"] != "STANDBY":
            raise BattleRuleError("这场战斗已经触发，不能再次启动。")
        cores = [item for item in setup["friendlies"] if int(item["is_core"])]
        if not cores:
            raise BattleRuleError("触发前必须先编入至少一名核心角色及其人格。")
        invalid_allies = [
            item
            for item in setup["friendlies"]
            if not int(item["is_core"])
            and (
                int(item.get("current_hp", 1)) <= 0
                or not int(item.get("template_enabled", 1))
            )
        ]
        if invalid_allies:
            names = "、".join(
                f"#{item['id']} {item['name']}" for item in invalid_allies
            )
            raise BattleRuleError(f"普通友方已无法出战：{names}。请先将其移出编成。")
        stage_one = [
            item for item in setup["enemies"]
            if int(item["stage_number"]) == 1 and int(item.get("enabled", 1)) == 1
        ]
        if not stage_one:
            raise BattleRuleError(
                "第一阶段没有携带中的敌人；请添加敌方或把预设敌人切回携带。"
            )
        return setup

    async def _require_setup_participant(request: Request) -> str:
        """GM 随时可操作编成；玩家仅在编成发布后可确认/调整（裁定 §7.5-5）。"""
        role = _require_role(request)
        if role == ROLE_GM:
            return role

        def _published() -> bool:
            try:
                setup_id = engine.selected_battle_setup_id(0, chat_id=0)
            except BattleRuleError:
                return False
            row = engine.database.fetch_one(
                "SELECT published FROM battle_setups WHERE id=?", (setup_id,)
            )
            return bool(row and int(row["published"]))

        if not await _read(_published):
            raise ApiError(403, "编成尚未发布；请等待管理人发布后再进行确认。")
        return role

    @app.post("/api/setup/publish")
    async def setup_publish(request: Request) -> dict[str, Any]:
        _require_gm(request)
        setup = await _locked(engine.publish_setup)
        _broadcast("setup_published", {
            "setup_id": int(setup["id"]),
            "name": str(setup.get("name") or ""),
        })
        _notify([f"◇ 战斗编成「{setup.get('name') or setup['id']}」已发布，等待玩家确认。"])
        return {"setup": setup}

    @app.post("/api/setup/stages/remove")
    async def setup_stage_remove(request: Request) -> dict[str, Any]:
        _require_gm(request)
        body = await _payload(request)
        stage_number = _as_int(body.get("stage_number"), "stage_number")
        message = await _locked(engine.remove_setup_stage, stage_number)
        return {"messages": [message]}

    @app.get("/api/deck")
    async def deck_get(request: Request) -> dict[str, Any]:
        role = _require_role(request)
        deck = await _read(engine.get_page_deck)
        abnormalities = await _read(engine.abnormality_catalog)
        if role != ROLE_GM:
            # 未开放的异想体对玩家完全不可见（2026-07-27 裁定）。
            abnormalities = [item for item in abnormalities if item.get("opened")]
        presets = await _read(engine.list_page_presets)
        return {"deck": deck, "abnormalities": abnormalities, "presets": presets}

    @app.post("/api/abnormalities/access")
    async def abnormality_access(request: Request) -> dict[str, Any]:
        _require_gm(request)
        body = await _payload(request)
        keys = _as_str_list(body.get("abnormality_keys"), "abnormality_keys")
        opened = bool(body.get("opened"))
        names = await _locked(engine.set_abnormality_access, keys, opened)
        return {"names": names, "opened": opened}

    @app.post("/api/deck")
    async def deck_set(request: Request) -> dict[str, Any]:
        _require_role(request)
        body = await _payload(request)
        keys = _as_str_list(body.get("abnormality_keys"), "abnormality_keys")
        saved = await _locked(engine.set_page_deck, keys)
        return {"abnormality_keys": saved}

    @app.post("/api/deck/presets")
    async def deck_preset_save(request: Request) -> dict[str, Any]:
        _require_role(request)
        body = await _payload(request)
        name = _as_str(body.get("name"), "name")
        keys = _as_str_list(body.get("abnormality_keys"), "abnormality_keys")
        return await _locked(engine.save_page_preset, name, keys)

    @app.post("/api/deck/presets/{preset_id}/delete")
    async def deck_preset_delete(request: Request, preset_id: int) -> dict[str, Any]:
        _require_role(request)
        name = await _locked(engine.delete_page_preset, preset_id)
        return {"deleted": name}

    @app.get("/api/setup/ready")
    async def setup_ready(request: Request) -> dict[str, Any]:
        await _require_setup_participant(request)
        setup = await _read(_ready_checked_setup)
        return {"setup": setup, "revision": int(setup["revision"])}

    @app.post("/api/setup/launch")
    async def setup_launch(request: Request) -> dict[str, Any]:
        await _require_setup_participant(request)
        body = await _payload(request)
        revision = _as_int(body.get("revision"), "revision")

        def _do() -> tuple[int, list[str]]:
            setup = _ready_checked_setup()
            if int(setup["revision"]) != revision:
                # 确认页取到的修订号已过期：编成发生过变化，旧确认失效。
                raise ApiError(
                    409,
                    "确认后战斗编成已经发生变化；本次没有触发，"
                    "请重新调用 /api/setup/ready 核对。",
                )
            battle_id, launch_messages = engine.launch_prepared_battle(
                int(setup["id"]), expected_revision=revision
            )
            return battle_id, [
                *launch_messages,
                f"战斗 #{battle_id} 开始！等待敌方设置指令。",
            ]

        battle_id, messages = await _locked(_do)
        _notify(messages)
        return {"messages": messages, "battle_id": battle_id}

    @app.post("/api/battle/lock-intents")
    async def lock_intents(request: Request) -> dict[str, Any]:
        _require_gm(request)
        message = await _locked(engine.finish_enemy_planning)
        _notify([message])
        return {"messages": [message]}

    @app.post("/api/battle/defend")
    async def battle_defend(request: Request) -> dict[str, Any]:
        role = _require_role(request)
        body = await _payload(request)
        actor_id = _as_int(body.get("actor_id"), "actor_id")
        actor = await _read(engine.get_character, actor_id)
        if role != ROLE_GM and (actor["faction"] != "FRIENDLY" or not int(actor["is_core"])):
            raise ApiError(403, "玩家只能操作核心角色。")
        intent_id = _as_int(body["intent_id"], "intent_id") if body.get("intent_id") is not None else None
        messages = list(await _locked(engine.declare_defense, actor_id, intent_id))
        _notify(messages)
        return {"messages": messages}

    @app.post("/api/battle/pass")
    async def battle_pass(request: Request) -> dict[str, Any]:
        # 结束回合（移交行动权）玩家也可主动发起（2026-07-26 反馈）。
        _require_role(request)
        message = await _locked(engine.end_friendly_phase)
        messages = [message]
        _notify(messages)
        return {"messages": messages}

    @app.post("/api/battle/settle")
    async def battle_settle(request: Request) -> dict[str, Any]:
        _require_gm(request)
        messages = list(await _locked(engine.end_turn))
        _notify(messages, paced=True)
        return {"messages": messages}

    @app.post("/api/battle/next")
    async def battle_next(request: Request) -> dict[str, Any]:
        _require_gm(request)
        body = await _payload(request)
        friendly_ids = (
            _as_int_list(body.get("friendly_ids"), "friendly_ids")
            if body.get("friendly_ids") is not None
            else None
        )
        messages = list(await _locked(engine.start_prepared_stage, friendly_ids))
        _notify(messages)
        return {"messages": messages}

    @app.post("/api/battle/stop")
    async def battle_stop(request: Request) -> dict[str, Any]:
        _require_gm(request)
        messages = list(await _locked(engine.end_battle, "ABORTED"))
        _notify(messages)
        return {"messages": messages}

    @app.post("/api/pages/{offer_id}/accept")
    async def page_accept(request: Request, offer_id: int) -> dict[str, Any]:
        # 书页由玩家自己挑选（2026-07-26 裁定），GM 亦可代操作。
        _require_role(request)
        message = await _locked(engine.choose_page, offer_id)
        messages = [message]
        _notify(messages)
        return {"messages": messages}

    @app.post("/api/manager/{skill_key}/use")
    async def manager_use(request: Request, skill_key: str) -> dict[str, Any]:
        _require_role(request)
        messages = list(await _locked(engine.use_manager_skill, skill_key))
        _notify(messages)
        return {"messages": messages}

    @app.post("/api/battle/forfeit-assists")
    async def forfeit_assists(request: Request) -> dict[str, Any]:
        _require_gm(request)
        messages = list(await _locked(engine.forfeit_assist_actions))
        _notify(messages)
        return {"messages": messages}

    @app.post("/api/identity")
    async def identity(request: Request) -> dict[str, Any]:
        # 玩家可为核心切换人格（阵容界面，裁定 §7.5-5/2026-07-27-4）；
        # 玩家侧仅限已开放人格，GM 不受限。
        role = _require_role(request)
        body = await _payload(request)
        character_id = _as_int(body.get("character_id"), "character_id")
        persona_key = _as_str(body.get("persona_key"), "persona_key")

        def _do() -> list[str]:
            engine.switch_persona(
                character_id, persona_key, enforce_access=(role != ROLE_GM)
            )
            character = engine.get_character(character_id)
            active = next(
                (
                    item
                    for item in engine.list_personas(character_id)
                    if int(item.get("is_active", 0))
                ),
                None,
            )
            persona_name = active["name"] if active else persona_key
            return [f"【装备完成】{character['name']}｜{persona_name}"]

        messages = await _locked(_do)
        _notify(messages)
        return {"messages": messages}

    @app.post("/api/create")
    async def create(request: Request) -> dict[str, Any]:
        _require_gm(request)
        body = await _payload(request)
        template_key = _as_str(body.get("template_key"), "template_key")
        name = body.get("name")
        if name is not None:
            name = _as_str(name, "name")

        def _do() -> tuple[int, list[str]]:
            character_id = engine.spawn_character(
                template_key, Faction.FRIENDLY, name=name
            )
            character = engine.get_character(character_id)
            return character_id, [
                f"【普通友方已建立】#{character_id}｜{character['name']}"
            ]

        character_id, messages = await _locked(_do)
        _notify(messages)
        return {"messages": messages, "character_id": character_id}

    @app.post("/api/reload")
    async def reload(request: Request) -> dict[str, Any]:
        _require_gm(request)

        def _do() -> list[str]:
            # 与 Telegram /reload 完全相同的展开与拓扑排序逻辑。
            from ..telegram_app import _expand_content_paths

            paths = _expand_content_paths(settings.content_paths)
            if not paths:
                raise BattleRuleError(
                    "Settings.content_paths 中没有可重载的 JSON 内容包。"
                )
            lines = ["【内容档案重载完成】"]
            for path in paths:
                result = loader.load_path(path)
                lines.append(
                    f"{path.name} → {result.pack_key} v{result.version}｜"
                    f"核心角色 {result.core_characters}｜生成模板 {result.characters}｜"
                    f"人格 {result.personas}｜技能 {result.skills}｜"
                    f"行为 {result.behaviors}｜书页 {result.pages}｜"
                    f"管理能力 {result.manager_skills}"
                )
            engine.validate_content_handlers()
            return lines

        messages = await _locked(_do)
        _notify(messages)
        return {"messages": messages}

    if story_store is not None:
        from .story_routes import install_story_routes

        install_story_routes(app, story_store, _require_role, _require_gm, writing_assistant)

    from .assistant_routes import install_assistant_routes

    install_assistant_routes(app, writing_assistant, _require_role, _require_gm, _broadcast)

    # -- 静态托管（GET / 与前端资源；目录可能由并行开发补齐） -------------
    @app.get("/", include_in_schema=False)
    async def index() -> Any:
        index_file = _resolve_static_file("index.html")
        if index_file is not None:
            return _static_response(index_file)
        return HTMLResponse(_PLACEHOLDER_HTML)

    @app.get("/{asset_path:path}", include_in_schema=False)
    async def static_asset(asset_path: str) -> Any:
        found = _resolve_static_file(asset_path)
        if found is None:
            raise ApiError(404, "未找到资源。")
        return _static_response(found)

    return app


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------
def main() -> None:
    """初始化数据库与内容包后，在 FrontendLock 保护下启动 uvicorn。"""
    logging.basicConfig(
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        level=logging.INFO,
    )
    settings = Settings.from_env()
    if not settings.web_gm_key and not settings.web_player_key:
        raise SystemExit(
            "DEWBOT_WEB_GM_KEY 与 DEWBOT_WEB_PLAYER_KEY 均未配置；"
            "请在 .env 中至少配置一个访问密钥后再启动 Web 前端。"
        )
    if not settings.web_gm_key:
        LOGGER.warning("DEWBOT_WEB_GM_KEY 未配置：管理人角色将无法登录。")
    if not settings.web_player_key:
        LOGGER.warning("DEWBOT_WEB_PLAYER_KEY 未配置：玩家角色将无法登录。")

    # 非回环地址意味着局域网/公网可达：密钥就是全部防线，弱密钥直接拒绝启动。
    loopback_hosts = {"127.0.0.1", "localhost", "::1"}
    if settings.web_host not in loopback_hosts:
        weak = [
            name
            for name, value in (
                ("DEWBOT_WEB_GM_KEY", settings.web_gm_key),
                ("DEWBOT_WEB_PLAYER_KEY", settings.web_player_key),
            )
            if value is not None and len(value) < 12
        ]
        if weak:
            raise SystemExit(
                f"启动中止：DEWBOT_WEB_HOST={settings.web_host} 会让服务在本机之外可达，"
                f"但 {'、'.join(weak)} 长度不足 12 个字符。"
                "对外暴露时密钥就是唯一防线，请改用足够长的随机密钥"
                "（例如 `python -c \"import secrets;print(secrets.token_urlsafe(24))\"`）。"
            )
        if not settings.web_secure_cookie:
            LOGGER.warning(
                "服务将绑定 %s 且未开启 DEWBOT_WEB_SECURE_COOKIE：请务必只经 HTTPS"
                "（反向代理或隧道）对外提供访问，并在确认全程 HTTPS 后设置"
                " DEWBOT_WEB_SECURE_COOKIE=1，防止密钥 Cookie 走明文 HTTP 泄露。",
                settings.web_host,
            )

    database = Database(settings.database_path)
    database.initialize()
    engine = BattleEngine(database)
    removed_enemies = engine.cleanup_completed_battles()
    if removed_enemies:
        LOGGER.info(
            "Cleaned up %s generated enemies from completed battles",
            removed_enemies,
        )
    loader = ContentLoader(database, engine.registry.keys)

    from ..telegram_app import _expand_content_paths

    content_files = _expand_content_paths(settings.content_paths)
    if not content_files:
        raise SystemExit("未找到可加载的 JSON 内容包，请检查 DEWBOT_CONTENT_PATHS。")
    for path in content_files:
        result = loader.load_path(path)
        LOGGER.info(
            "Loaded content pack %s v%s from %s", result.pack_key, result.version, path
        )
    engine.validate_content_handlers()

    app = create_app(settings, engine=engine, loader=loader)

    import uvicorn

    from ..runlock import FrontendLock, FrontendLockError

    # 两个前端共用一个数据库但不允许并行运行；进程内写锁只保护单进程。
    try:
        with FrontendLock(settings.database_path, "web"):
            uvicorn.run(app, host=settings.web_host, port=settings.web_port)
    except FrontendLockError as exc:
        raise SystemExit(f"启动中止：{exc}") from exc


__all__ = ["create_app", "main", "ApiError"]


if __name__ == "__main__":
    main()
