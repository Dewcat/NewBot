from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from telegram.ext import CallbackQueryHandler, CommandHandler, ConversationHandler
from telegram.request import HTTPXRequest

from dewbot.models import BattlePhase
from dewbot.config import Settings
from dewbot.telegram_app import (
    SELECTING_ACTOR,
    SELECTING_SKILL,
    TelegramBattleAdapter,
    _expand_content_paths,
    _parse_positive_ids,
    create_application,
    main,
)


def test_content_paths_follow_pack_dependencies_not_file_names(tmp_path: Path) -> None:
    dependent = tmp_path / "a_dependent.json"
    base = tmp_path / "z_base.json"
    dependent.write_text(
        json.dumps({
            "pack": {
                "key": "test.dependent",
                "version": "1.0.0",
                "requires": [{"key": "test.base"}],
            }
        }),
        encoding="utf-8",
    )
    base.write_text(
        json.dumps({"pack": {"key": "test.base", "version": "1.0.0"}}),
        encoding="utf-8",
    )

    assert _expand_content_paths([tmp_path]) == [base.resolve(), dependent.resolve()]


class RecordingMessage:
    def __init__(self) -> None:
        self.replies: list[tuple[str, dict[str, Any]]] = []

    async def reply_text(self, text: str, **kwargs: Any) -> None:
        self.replies.append((text, kwargs))


class RecordingQuery:
    def __init__(self, user_id: int, data: str, message: RecordingMessage | None = None):
        self.from_user = SimpleNamespace(id=user_id)
        self.data = data
        self.message = message or RecordingMessage()
        self.answers: list[tuple[str | None, dict[str, Any]]] = []
        self.edits: list[tuple[str, dict[str, Any]]] = []

    async def answer(self, text: str | None = None, **kwargs: Any) -> None:
        self.answers.append((text, kwargs))

    async def edit_message_text(self, text: str, **kwargs: Any) -> None:
        self.edits.append((text, kwargs))


def _settings(tmp_path: Path, *, admins: set[int] | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        database_path=tmp_path / "telegram.sqlite3",
        content_paths=(),
        telegram_token="123456:OFFLINE_TEST_TOKEN",
        telegram_proxy=None,
        admin_ids=frozenset(admins or set()),
    )


def _command_update(user_id: int) -> tuple[SimpleNamespace, RecordingMessage]:
    message = RecordingMessage()
    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=user_id),
        effective_chat=SimpleNamespace(id=-100123),
        effective_message=message,
        callback_query=None,
    )
    return update, message


def _callback_update(query: RecordingQuery) -> SimpleNamespace:
    return SimpleNamespace(
        effective_user=query.from_user,
        effective_chat=SimpleNamespace(id=-100123),
        effective_message=query.message,
        callback_query=query,
    )


def _context(*args: str) -> SimpleNamespace:
    return SimpleNamespace(args=list(args), user_data={})


class MinimalEngine:
    def __init__(self) -> None:
        self.database = object()


def test_create_application_is_an_offline_factory_and_registers_routes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def network_must_not_start(_request: HTTPXRequest) -> None:
        raise AssertionError("create_application must not initialize Telegram networking")

    monkeypatch.setattr(HTTPXRequest, "initialize", network_must_not_start)
    engine = MinimalEngine()
    loader = object()

    application = create_application(_settings(tmp_path), engine, loader)  # type: ignore[arg-type]

    assert application.bot_data["battle_engine"] is engine
    assert application.bot_data["content_loader"] is loader
    assert isinstance(application.bot_data["telegram_adapter"], TelegramBattleAdapter)

    top_level_commands: set[str] = set()
    conversations: dict[str, ConversationHandler] = {}
    callback_patterns: set[str] = set()
    for handler in application.handlers[0]:
        if isinstance(handler, CommandHandler):
            top_level_commands.update(handler.commands)
        elif isinstance(handler, ConversationHandler):
            conversations[str(handler.name)] = handler
        elif isinstance(handler, CallbackQueryHandler) and handler.pattern is not None:
            callback_patterns.add(handler.pattern.pattern)

    assert {
        "start",
        "help",
        "whoami",
        "roster",
        "personas",
        "skills",
        "battle",
        "pass",
        "settle",
        "stop",
        "next",
        "pages",
        "manager",
        "reload",
        "new",
        "battles",
        "use",
        "team",
        "ally",
        "foe",
        "ready",
        "discard",
        "plan",
        "identity",
        "create",
    } <= top_level_commands
    assert {
        "templates", "spawn", "persona", "battle_start", "battle_prepare",
        "battle_core", "battle_launch", "end_friendly_phase",
    }.isdisjoint(top_level_commands)
    assert set(conversations) == {"dewbot_friendly_attack", "dewbot_enemy_attack"}
    assert {next(iter(item.commands)) for item in conversations.values() for item in item.entry_points} == {
        "attack",
        "enemy",
    }
    assert all(set(item.states) == {0, 1, 2} for item in conversations.values())
    assert {r"^dw:p:\d+$", r"^dw:m:", r"^dw:a:"} <= callback_patterns


def test_create_application_rejects_a_missing_token(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    settings.telegram_token = "  "

    with pytest.raises(ValueError, match="TELEGRAM_TOKEN"):
        create_application(settings, MinimalEngine(), object())  # type: ignore[arg-type]


def test_main_initializes_and_loads_content_before_polling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = Path(__file__).resolve().parents[1]
    settings = Settings(
        database_path=tmp_path / "main.sqlite3",
        content_paths=(
            root / "content" / "base_pack.json",
            root / "content" / "core_personas.json",
        ),
        telegram_token="123456:OFFLINE_TEST_TOKEN",
        telegram_proxy=None,
        admin_ids=frozenset({1}),
    )
    monkeypatch.setattr(
        Settings, "from_env", classmethod(lambda cls: settings)
    )
    captured: dict[str, Any] = {}

    class FakeApplication:
        def run_polling(self, **kwargs: Any) -> None:
            captured["polling"] = kwargs

    def fake_create_application(
        supplied_settings: Settings, *, engine: Any, loader: Any
    ) -> FakeApplication:
        captured["settings"] = supplied_settings
        captured["templates"] = engine.list_templates()
        captured["roster"] = engine.list_characters()
        captured["loader"] = loader
        return FakeApplication()

    monkeypatch.setattr(
        "dewbot.telegram_app.create_application", fake_create_application
    )
    main()

    assert captured["settings"] is settings
    assert {item["template_key"] for item in captured["templates"]} == {
        "unit.training_assistant", "enemy.training_shell"
    }
    assert any(item["name"] == "珏" and item["template_key"] is None for item in captured["roster"])
    assert "polling" in captured


@pytest.mark.parametrize(
    ("tokens", "expected"),
    [
        (["1,2", "2", "3"], [1, 2, 3]),
        (["4，5；6;7"], [4, 5, 6, 7]),
        ([], []),
    ],
)
def test_positive_id_parser_accepts_command_delimiters_and_deduplicates(
    tokens: list[str], expected: list[int]
) -> None:
    assert _parse_positive_ids(tokens) == expected


@pytest.mark.parametrize("token", ["0", "-1", "not-an-id"])
def test_positive_id_parser_rejects_invalid_ids(token: str) -> None:
    with pytest.raises(ValueError):
        _parse_positive_ids([token])


def _legacy_battle_start_parses_ids_stages_and_abnormalities(tmp_path: Path) -> None:
    class CapturingEngine(MinimalEngine):
        def __init__(self) -> None:
            super().__init__()
            self.call: tuple[list[int], list[int], dict[str, Any]] | None = None

        def start_battle(
            self, friendly_ids: list[int], enemy_ids: list[int], **kwargs: Any
        ) -> tuple[int, list[str]]:
            self.call = (friendly_ids, enemy_ids, kwargs)
            return 91, ["战斗档案已建立。"]

    engine = CapturingEngine()
    adapter = TelegramBattleAdapter(_settings(tmp_path, admins={10}), engine, object())  # type: ignore[arg-type]
    update, message = _command_update(10)
    context = _context(
        "1,2",
        "2",
        "--",
        "3；4",
        "stages=2",
        "abnos=abno.one,abno.two",
    )

    asyncio.run(adapter.battle_start_command(update, context))

    assert engine.call == (
        [1, 2],
        [3, 4],
        {
            "total_stages": 2,
            "abnormality_keys": ["abno.one", "abno.two"],
        },
    )
    assert "91" in message.replies[-1][0]


def test_legacy_battle_start_directs_admin_to_encounter_workflow(tmp_path: Path) -> None:
    adapter = TelegramBattleAdapter(
        _settings(tmp_path, admins={10}), MinimalEngine(), object()  # type: ignore[arg-type]
    )
    update, message = _command_update(10)

    asyncio.run(adapter.battle_start_command(update, _context("1,2", "--", "3,4")))

    reply = message.replies[-1][0]
    assert "/battle_prepare" in reply
    assert "/battle_core" in reply
    assert "/battle_launch" in reply


def test_non_admin_callback_is_rejected_before_engine_mutation(tmp_path: Path) -> None:
    class GuardedEngine(MinimalEngine):
        def choose_page(self, _offer_id: int) -> str:
            raise AssertionError("an unauthorized callback reached the engine")

    adapter = TelegramBattleAdapter(
        _settings(tmp_path, admins={1}), GuardedEngine(), object()  # type: ignore[arg-type]
    )
    query = RecordingQuery(2, "dw:p:17")

    asyncio.run(adapter.page_callback(_callback_update(query), _context()))

    assert query.answers
    assert query.answers[-1][1]["show_alert"] is True
    assert not query.edits


def test_foreign_cancel_callback_cannot_clear_the_owners_flow(tmp_path: Path) -> None:
    adapter = TelegramBattleAdapter(
        _settings(tmp_path), MinimalEngine(), object()  # type: ignore[arg-type]
    )
    flow = {"initiator_id": 41, "nonce": "fresh"}
    context = _context()
    context.user_data["friendly_attack"] = flow
    query = RecordingQuery(99, "dw:a:f:x:fresh")

    state = asyncio.run(adapter.cancel_friendly(_callback_update(query), context))

    assert state == SELECTING_ACTOR
    assert context.user_data["friendly_attack"] is flow
    assert query.answers[-1][1]["show_alert"] is True
    assert not query.edits


def test_old_attack_button_does_not_end_or_edit_the_new_attack_flow(
    tmp_path: Path,
) -> None:
    class FriendlyFlowEngine(MinimalEngine):
        def battle_status(self) -> dict[str, Any]:
            return {
                "id": 12,
                "phase": BattlePhase.FRIENDLY_ACTION.value,
                "participants": [
                    {
                        "id": 22,
                        "name": "测试执行者",
                        "faction": "FRIENDLY",
                        "active_in_stage": 1,
                        "current_hp": 50,
                        "max_hp": 50,
                        "current_actions": 1,
                        "max_actions": 1,
                        "is_staggered": 0,
                    }
                ],
            }

    adapter = TelegramBattleAdapter(
        _settings(tmp_path), FriendlyFlowEngine(), object()  # type: ignore[arg-type]
    )
    context = _context()
    first_update, _ = _command_update(41)
    assert asyncio.run(adapter.attack_start(first_update, context)) == SELECTING_ACTOR
    old_nonce = context.user_data["friendly_attack"]["nonce"]

    second_update, _ = _command_update(41)
    assert asyncio.run(adapter.attack_start(second_update, context)) == SELECTING_ACTOR
    current_flow = context.user_data["friendly_attack"]
    assert current_flow["nonce"] != old_nonce

    query = RecordingQuery(41, f"dw:a:f:a:{old_nonce}.22")
    state = asyncio.run(
        adapter.friendly_actor_callback(_callback_update(query), context)
    )

    assert state == SELECTING_ACTOR
    assert context.user_data["friendly_attack"] is current_flow
    assert query.answers[-1][1]["show_alert"] is True
    assert not query.edits


def test_enemy_skill_names_are_private_to_the_admin_callback(tmp_path: Path) -> None:
    class EnemyFlowEngine(MinimalEngine):
        def battle_status(self) -> dict[str, Any]:
            return {
                "id": 7,
                "phase": BattlePhase.ENEMY_ACTION.value,
                "participants": [
                    {
                        "id": 22,
                        "name": "受限个体",
                        "faction": "ENEMY",
                        "active_in_stage": 1,
                        "current_hp": 50,
                        "max_hp": 50,
                        "current_actions": 1,
                        "max_actions": 1,
                        "is_staggered": 0,
                    }
                ],
            }

        def list_skills(self, _actor_id: int, *, available_only: bool) -> list[dict[str, Any]]:
            assert available_only is True
            return [
                {
                    "id": 31,
                    "name": "机密技能·甲",
                    "skill_type": "NORMAL",
                    "description": "不可公开的甲档案",
                },
                {
                    "id": 32,
                    "name": "机密技能·乙",
                    "skill_type": "EGO",
                    "description": "不可公开的乙档案",
                },
            ]

    adapter = TelegramBattleAdapter(
        _settings(tmp_path, admins={8}), EnemyFlowEngine(), object()  # type: ignore[arg-type]
    )
    context = _context()
    command_update, _message = _command_update(8)
    assert asyncio.run(adapter.enemy_start(command_update, context)) == SELECTING_ACTOR

    nonce = context.user_data["enemy_attack"]["nonce"]
    query = RecordingQuery(8, f"dw:a:e:a:{nonce}.22")
    state = asyncio.run(adapter.enemy_actor_callback(_callback_update(query), context))

    assert state == SELECTING_SKILL
    private_text, private_options = query.answers[-1]
    assert private_options["show_alert"] is True
    assert "机密技能·甲" in str(private_text)
    assert "机密技能·乙" in str(private_text)

    public_text, public_options = query.edits[-1]
    public_markup = public_options["reply_markup"]
    public_button_text = " ".join(
        button.text for row in public_markup.inline_keyboard for button in row
    )
    assert "机密技能" not in public_text
    assert "机密技能" not in public_button_text
    assert "技能 01" in public_button_text
    assert "技能 02" in public_button_text


def test_team_flow_replaces_the_core_formation_only_after_final_confirmation(
    tmp_path: Path,
) -> None:
    class FormationEngine(MinimalEngine):
        def __init__(self) -> None:
            super().__init__()
            self.replacements: list[tuple[int, list[tuple[int, int]]]] = []

        def selected_battle_setup_id(self, _user_id: int, *, chat_id: int = 0) -> int:
            return 5

        def battle_setup_status(self, _setup_id: int) -> dict[str, Any]:
            return {
                "id": 5,
                "name": "人格测试战",
                "status": "STANDBY",
                "friendlies": [{
                    "id": 1,
                    "name": "珏",
                    "is_core": 1,
                    "persona_key": "persona.jue.initial",
                }],
            }

        def list_characters(self, _faction: Any) -> list[dict[str, Any]]:
            return [
                {"id": 1, "name": "珏", "is_core": 1},
                {"id": 2, "name": "露", "is_core": 1},
            ]

        def get_character(self, character_id: int) -> dict[str, Any]:
            return {"id": character_id, "name": "珏" if character_id == 1 else "露"}

        def list_personas(self, character_id: int) -> list[dict[str, Any]]:
            return [{
                "id": character_id * 10,
                "name": "初始人格",
                "max_hp": 100,
                "max_actions": 1,
            }]

        def replace_core_formation(
            self, setup_id: int, choices: list[tuple[int, int]]
        ) -> None:
            self.replacements.append((setup_id, list(choices)))

    engine = FormationEngine()
    adapter = TelegramBattleAdapter(
        _settings(tmp_path, admins={7}), engine, object()  # type: ignore[arg-type]
    )
    context = _context()
    command, _message = _command_update(7)
    asyncio.run(adapter.team_command(command, context))
    nonce = context.user_data["core_formation"]["nonce"]

    for data in (f"dw:c:t:{nonce}.1", f"dw:c:t:{nonce}.2", f"dw:c:n:{nonce}"):
        query = RecordingQuery(7, data)
        asyncio.run(adapter.core_formation_callback(_callback_update(query), context))
    assert engine.replacements == []

    query = RecordingQuery(7, f"dw:c:p:{nonce}.2.20")
    asyncio.run(adapter.core_formation_callback(_callback_update(query), context))
    assert engine.replacements == [(5, [(2, 20)])]


def test_ready_requires_a_second_click_before_launching(tmp_path: Path) -> None:
    class ReadyEngine(MinimalEngine):
        def __init__(self) -> None:
            super().__init__()
            self.launches: list[int] = []

        def selected_battle_setup_id(self, _user_id: int, *, chat_id: int = 0) -> int:
            return 9

        def battle_setup_status(self, _setup_id: int) -> dict[str, Any]:
            return {
                "id": 9,
                "name": "确认测试",
                "status": "STANDBY",
                "friendlies": [{"id": 1, "name": "珏", "is_core": 1}],
                "enemies": [{
                    "id": 101,
                    "stage_number": 1,
                    "display_name": None,
                    "template_name": "训练假人",
                    "template_key": "enemy.training_shell",
                    "amount": 2,
                }],
            }

        def launch_prepared_battle(
            self, setup_id: int, *, expected_revision: int | None = None
        ) -> tuple[int, list[str]]:
            assert expected_revision == 0
            self.launches.append(setup_id)
            return 88, ["战斗开始"]

    engine = ReadyEngine()
    adapter = TelegramBattleAdapter(
        _settings(tmp_path, admins={7}), engine, object()  # type: ignore[arg-type]
    )
    context = _context()
    command, message = _command_update(7)

    asyncio.run(adapter.ready_command(command, context))
    assert engine.launches == []
    markup = message.replies[-1][1]["reply_markup"]
    confirm_data = markup.inline_keyboard[0][0].callback_data

    query = RecordingQuery(7, str(confirm_data))
    asyncio.run(adapter.battle_formation_callback(_callback_update(query), context))
    assert engine.launches == [9]
    assert "#88" in query.edits[-1][0]


def test_old_and_foreign_ready_buttons_only_show_a_private_alert(
    tmp_path: Path,
) -> None:
    class ReadyEngine(MinimalEngine):
        def __init__(self) -> None:
            super().__init__()
            self.launches: list[int] = []

        def selected_battle_setup_id(self, _user_id: int, *, chat_id: int = 0) -> int:
            return 9

        def battle_setup_status(self, _setup_id: int) -> dict[str, Any]:
            return {
                "id": 9,
                "name": "权限测试",
                "status": "STANDBY",
                "friendlies": [
                    {
                        "id": 1,
                        "name": "珏",
                        "is_core": 1,
                        "persona_id": 10,
                        "persona_key": "persona.jue.initial",
                    }
                ],
                "enemies": [
                    {
                        "id": 101,
                        "stage_number": 1,
                        "display_name": None,
                        "template_name": "训练假人",
                        "template_key": "enemy.training_shell",
                        "amount": 2,
                    }
                ],
            }

        def launch_prepared_battle(
            self, setup_id: int, *, expected_revision: int | None = None
        ) -> tuple[int, list[str]]:
            self.launches.append(setup_id)
            return 88, ["战斗开始"]

    engine = ReadyEngine()
    adapter = TelegramBattleAdapter(
        _settings(tmp_path, admins={7, 8}), engine, object()  # type: ignore[arg-type]
    )
    context = _context()
    first_update, first_message = _command_update(7)
    asyncio.run(adapter.ready_command(first_update, context))
    old_data = str(
        first_message.replies[-1][1]["reply_markup"].inline_keyboard[0][0].callback_data
    )

    second_update, _ = _command_update(7)
    asyncio.run(adapter.ready_command(second_update, context))
    current_flow = context.user_data["ready_battle"]

    stale_query = RecordingQuery(7, old_data)
    asyncio.run(
        adapter.battle_formation_callback(_callback_update(stale_query), context)
    )
    assert stale_query.answers[-1][1]["show_alert"] is True
    assert not stale_query.edits
    assert context.user_data["ready_battle"] is current_flow

    foreign_query = RecordingQuery(
        8, f"dw:b:ready:{current_flow['nonce']}"
    )
    asyncio.run(
        adapter.battle_formation_callback(_callback_update(foreign_query), context)
    )
    assert foreign_query.answers[-1][1]["show_alert"] is True
    assert not foreign_query.edits
    assert context.user_data["ready_battle"] is current_flow
    assert engine.launches == []


def test_ready_rejects_confirmation_if_the_formation_changed(
    tmp_path: Path,
) -> None:
    class ChangingReadyEngine(MinimalEngine):
        def __init__(self) -> None:
            super().__init__()
            self.friendlies: list[dict[str, Any]] = [
                {
                    "id": 1,
                    "name": "珏",
                    "is_core": 1,
                    "persona_id": 10,
                    "persona_key": "persona.jue.initial",
                }
            ]
            self.launches: list[int] = []

        def selected_battle_setup_id(self, _user_id: int, *, chat_id: int = 0) -> int:
            return 9

        def battle_setup_status(self, _setup_id: int) -> dict[str, Any]:
            return {
                "id": 9,
                "name": "变更测试",
                "status": "STANDBY",
                "friendlies": [dict(item) for item in self.friendlies],
                "enemies": [
                    {
                        "id": 101,
                        "stage_number": 1,
                        "display_name": None,
                        "template_name": "训练假人",
                        "template_key": "enemy.training_shell",
                        "amount": 2,
                    }
                ],
            }

        def launch_prepared_battle(
            self, setup_id: int, *, expected_revision: int | None = None
        ) -> tuple[int, list[str]]:
            self.launches.append(setup_id)
            return 88, ["战斗开始"]

    engine = ChangingReadyEngine()
    adapter = TelegramBattleAdapter(
        _settings(tmp_path, admins={7}), engine, object()  # type: ignore[arg-type]
    )
    context = _context()
    command, message = _command_update(7)
    asyncio.run(adapter.ready_command(command, context))
    confirm_data = str(
        message.replies[-1][1]["reply_markup"].inline_keyboard[0][0].callback_data
    )
    engine.friendlies.append(
        {
            "id": 2,
            "name": "临时友军",
            "is_core": 0,
            "persona_id": None,
            "persona_key": None,
        }
    )

    query = RecordingQuery(7, confirm_data)
    asyncio.run(adapter.battle_formation_callback(_callback_update(query), context))

    assert engine.launches == []
    assert query.answers[-1][1]["show_alert"] is True
    assert "/ready" in query.edits[-1][0]


def test_skills_command_refuses_to_publish_enemy_skill_catalog(
    tmp_path: Path,
) -> None:
    class EnemyCatalogEngine(MinimalEngine):
        def __init__(self) -> None:
            super().__init__()
            self.catalog_reads = 0

        def get_character(self, character_id: int) -> dict[str, Any]:
            return {"id": character_id, "name": "敌方档案", "faction": "ENEMY"}

        def skill_catalog(self, _character_id: int) -> list[dict[str, Any]]:
            self.catalog_reads += 1
            return [
                {
                    "name": "不应公开的技能名",
                    "skill_type": "NORMAL",
                    "base_cooldown": 0,
                    "emotion_requirement": 0,
                    "max_uses_per_battle": None,
                    "description": "不应公开的说明",
                }
            ]

    engine = EnemyCatalogEngine()
    adapter = TelegramBattleAdapter(
        _settings(tmp_path), engine, object()  # type: ignore[arg-type]
    )
    update, message = _command_update(5)

    asyncio.run(adapter.skills_command(update, _context("22")))

    assert engine.catalog_reads == 0
    response = message.replies[-1][0]
    assert "敌方技能" in response
    assert "不应公开" not in response


def test_long_content_keys_never_enter_telegram_callback_payloads(tmp_path: Path) -> None:
    long_key = "encounter." + "x" * 80

    class LongKeyEngine(MinimalEngine):
        def __init__(self) -> None:
            super().__init__()
            self.prepared: list[str] = []

        def list_encounters(self) -> list[dict[str, Any]]:
            return [{"encounter_key": long_key, "name": "长键关卡", "total_stages": 1}]

        def prepare_encounter(
            self, encounter_key: str, *, name: str, created_by: int,
            selection_chat_id: int = 0,
        ) -> int:
            self.prepared.append(encounter_key)
            return 3

    engine = LongKeyEngine()
    adapter = TelegramBattleAdapter(
        _settings(tmp_path, admins={7}), engine, object()  # type: ignore[arg-type]
    )
    context = _context("长键测试")
    command, message = _command_update(7)
    asyncio.run(adapter.new_battle_command(command, context))
    callback_data = message.replies[-1][1]["reply_markup"].inline_keyboard[0][0].callback_data

    assert len(str(callback_data).encode("utf-8")) <= 64
    assert long_key not in str(callback_data)
    query = RecordingQuery(7, str(callback_data))
    asyncio.run(adapter.battle_formation_callback(_callback_update(query), context))
    assert engine.prepared == [long_key]


def test_battle_list_is_paginated_for_a_growing_setup_archive(tmp_path: Path) -> None:
    class ManyBattlesEngine(MinimalEngine):
        def list_battle_setups(self) -> list[dict[str, Any]]:
            return [{
                "id": index,
                "name": f"测试战 {index}",
                "status": "STANDBY",
                "encounter_name": "训练场",
                "total_stages": 1,
                "friendly_count": 0,
            } for index in range(1, 11)]

    adapter = TelegramBattleAdapter(
        _settings(tmp_path, admins={7}), ManyBattlesEngine(), object()  # type: ignore[arg-type]
    )
    context = _context()
    command, message = _command_update(7)
    asyncio.run(adapter.battles_command(command, context))

    first_text, options = message.replies[-1]
    assert "1/2" in first_text
    assert "测试战 8" in first_text
    assert "测试战 9" not in first_text
    next_data = options["reply_markup"].inline_keyboard[-1][-1].callback_data

    query = RecordingQuery(7, str(next_data))
    asyncio.run(adapter.battle_formation_callback(_callback_update(query), context))
    assert "2/2" in query.edits[-1][0]
    assert "测试战 9" in query.edits[-1][0]
