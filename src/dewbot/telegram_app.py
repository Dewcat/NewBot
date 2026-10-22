from __future__ import annotations

import asyncio
import json
import logging
import re
import secrets
import time
import warnings
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any, Protocol

from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
)
from telegram.request import HTTPXRequest
from telegram.warnings import PTBUserWarning

from .content import ContentLoader
from .db import Database
from .engine import BattleEngine
from .models import BattlePhase, BattleRuleError, ContentValidationError, Faction


LOGGER = logging.getLogger(__name__)

SELECTING_ACTOR, SELECTING_SKILL, SELECTING_TARGET = range(3)

_ATTACK_PREFIX = "dw:a"
_FRIENDLY_FLOW = "friendly_attack"
_ENEMY_FLOW = "enemy_attack"
_CORE_FORMATION_FLOW = "core_formation"
_BATTLE_LIST_FLOW = "battle_list"
_NEW_BATTLE_FLOW = "new_battle"
_ALLY_FLOW = "ally_reinforcement"
_FOE_FLOW = "foe_reinforcement"
_READY_FLOW = "ready_battle"
_DISCARD_FLOW = "discard_battle"
_STOP_FLOW = "stop_battle"
_HUMAN_CONTENT_FLOW = "human_content"
_MANAGER_FLOW = "manager_skill"
_STAGE_FLOW = "stage_selection"
_GEAR_FLOW = "gear_abnormalities"
_TELEGRAM_TEXT_LIMIT = 3900
_CALLBACK_ALERT_LIMIT = 195
_MENU_PAGE_SIZE = 8
_FLOW_TTL_SECONDS = 15 * 60


class StaleFlowError(BattleRuleError):
    """A callback belongs to an expired, foreign, or superseded UI flow."""


class SettingsLike(Protocol):
    database_path: Path
    content_paths: tuple[Path, ...]
    telegram_token: str | None
    telegram_proxy: str | None
    admin_ids: frozenset[int]


PHASE_LABELS: dict[str, str] = {
    BattlePhase.BATTLE_START.value: "战斗开始",
    BattlePhase.STAGE_SELECTION.value: "阶段编成",
    BattlePhase.TURN_START.value: "回合开始",
    BattlePhase.ENEMY_PLANNING.value: "敌方设置指令",
    BattlePhase.FRIENDLY_ACTION.value: "我方行动",
    BattlePhase.ENEMY_ACTION.value: "敌方行动",
    BattlePhase.TURN_END.value: "回合清算",
    BattlePhase.STAGE_END.value: "阶段结束",
    BattlePhase.BATTLE_END.value: "战斗结束",
}

SETUP_STATUS_LABELS = {
    "STANDBY": "等待触发",
    "ACTIVE": "战斗中",
    "COMPLETE": "已结束",
    "CANCELLED": "已撤销",
}

CLEAR_CONDITION_LABELS = {
    "ALL_ENEMIES_DEFEATED": "击败全部敌人",
    "TARGET_DEFEATED": "击败指定目标",
    "TARGET_HP_BELOW": "将指定目标生命降至阈值",
}


def _chunks(text: str, limit: int = _TELEGRAM_TEXT_LIMIT) -> list[str]:
    """Split long plain-text reports without cutting a line when possible."""
    text = text.strip() or "（无可记录内容）"
    result: list[str] = []
    while len(text) > limit:
        cut = text.rfind("\n", 0, limit)
        if cut < limit // 2:
            cut = limit
        result.append(text[:cut].rstrip())
        text = text[cut:].lstrip("\n")
    result.append(text)
    return result


def _compact(text: object, limit: int) -> str:
    value = " ".join(str(text or "").split())
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 1)].rstrip() + "…"


def _parse_positive_ids(tokens: Iterable[str]) -> list[int]:
    values: list[int] = []
    for token in tokens:
        for raw in re.split(r"[,，;；]", token):
            raw = raw.strip()
            if not raw:
                continue
            try:
                value = int(raw)
            except ValueError as exc:
                raise ValueError(f"角色编号必须是整数：{raw}") from exc
            if value <= 0:
                raise ValueError(f"角色编号必须大于 0：{raw}")
            if value not in values:
                values.append(value)
    return values


def _expand_content_paths(configured_paths: Iterable[Path]) -> list[Path]:
    """Expand configured files/directories and order local pack dependencies."""
    result: list[Path] = []
    for configured in configured_paths:
        path = Path(configured)
        if path.is_dir():
            candidates = sorted(path.glob("*.json"))
        elif path.suffix.lower() == ".json":
            candidates = [path]
        else:
            candidates = []
        for candidate in candidates:
            resolved = candidate.resolve()
            if resolved not in result:
                result.append(resolved)
    metadata: dict[str, tuple[Path, set[str]]] = {}
    unresolved: list[Path] = []
    for path in result:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            pack = data["pack"]
            pack_key = str(pack["key"])
            required = {
                str(item["key"] if isinstance(item, dict) else item)
                for item in pack.get("requires", [])
            }
        except (OSError, json.JSONDecodeError, KeyError, TypeError):
            # Preserve the path so ContentLoader can provide its richer error.
            unresolved.append(path)
            continue
        if pack_key in metadata:
            raise ContentValidationError(
                f"配置中存在重复内容包 key：{pack_key}"
            )
        metadata[pack_key] = (path, required)

    ordered: list[Path] = []
    remaining = dict(metadata)
    while remaining:
        ready = [
            key for key, (_path, required) in remaining.items()
            if not (required & remaining.keys())
        ]
        if not ready:
            raise ContentValidationError(
                "已配置内容包之间存在循环依赖：" + "、".join(sorted(remaining))
            )
        for key in ready:
            ordered.append(remaining.pop(key)[0])
    # Invalid/unreadable files remain visible to the authoritative loader.
    return ordered + unresolved


def _flow_key(side: str) -> str:
    return _FRIENDLY_FLOW if side == "f" else _ENEMY_FLOW


def _expected_phase(side: str) -> BattlePhase:
    return BattlePhase.FRIENDLY_ACTION if side == "f" else BattlePhase.ENEMY_PLANNING


def _side_faction(side: str) -> Faction:
    return Faction.FRIENDLY if side == "f" else Faction.ENEMY


class TelegramBattleAdapter:
    """Thin Telegram UI over the transactional battle engine.

    The adapter owns no battle rules. It revalidates phase and selections before
    every callback, then lets :class:`BattleEngine` make the authoritative
    decision. Mutations are serialized to keep two Telegram callbacks from
    racing over the same global battle record.
    """

    def __init__(
        self,
        settings: SettingsLike,
        engine: BattleEngine,
        loader: ContentLoader,
    ) -> None:
        self.settings = settings
        self.engine = engine
        self.loader = loader
        self._mutation_lock = asyncio.Lock()

    @staticmethod
    def _remember_flow(
        context: ContextTypes.DEFAULT_TYPE,
        key: str,
        *,
        initiator_id: int,
        chat_id: int,
        **payload: Any,
    ) -> str:
        """Store one short-lived button flow and return its compact nonce.

        Telegram limits callback payloads to 64 bytes.  Database/content keys
        therefore stay server-side and buttons carry only a nonce plus a small
        numeric choice.  Replacing the stored value also expires older buttons.
        """
        nonce = secrets.token_urlsafe(4)
        context.user_data[key] = {
            "nonce": nonce,
            "initiator_id": int(initiator_id),
            "chat_id": int(chat_id),
            "created_at": time.time(),
            **payload,
        }
        return nonce

    @staticmethod
    def _owned_flow(
        context: ContextTypes.DEFAULT_TYPE,
        key: str,
        *,
        nonce: str,
        user_id: int,
        chat_id: int,
    ) -> dict[str, Any]:
        flow = context.user_data.get(key)
        if (
            not isinstance(flow, dict)
            or flow.get("nonce") != nonce
            or int(flow.get("initiator_id", 0)) != int(user_id)
            or int(flow.get("chat_id", 0)) != int(chat_id)
            or time.time() - float(flow.get("created_at", 0)) > _FLOW_TTL_SECONDS
        ):
            raise StaleFlowError("这组按钮已经失效，或不属于当前操作者；请重新输入对应指令。")
        return flow

    @staticmethod
    def _chat_id(update: Update) -> int:
        chat = update.effective_chat
        if chat is not None:
            return int(chat.id)
        message = update.effective_message
        return int(getattr(message, "chat_id", 0) or 0)

    @staticmethod
    def _setup_signature(setup: dict[str, Any]) -> tuple[tuple[Any, ...], ...]:
        """Fingerprint the exact formation shown by /ready."""
        friendlies = tuple(sorted(
            (
                "F",
                int(item["id"]),
                str(item.get("persona_key") or ""),
            )
            for item in setup.get("friendlies", [])
        ))
        stage_one = tuple(sorted(
            (
                "E",
                int(item["id"]),
                str(item["template_key"]),
                int(item["amount"]),
                str(item.get("display_name") or ""),
            )
            for item in setup.get("enemies", [])
            if int(item["stage_number"]) == 1
        ))
        return friendlies + stage_one

    @staticmethod
    def _setup_label(setup: dict[str, Any]) -> str:
        status = SETUP_STATUS_LABELS.get(str(setup.get("status")), str(setup.get("status")))
        return f"#{setup['id']}｜{setup['name']}｜{status}"

    @staticmethod
    def _condition_label(
        stage: dict[str, Any], target_names: dict[str, str] | None = None
    ) -> str:
        condition = stage.get("clear_condition_json", {})
        if isinstance(condition, str):
            try:
                condition = json.loads(condition)
            except json.JSONDecodeError:
                condition = {}
        kind = str(condition.get("type", "ALL_ENEMIES_DEFEATED")).upper()
        label = CLEAR_CONDITION_LABELS.get(kind, kind)
        if kind.startswith("TARGET_") and condition.get("target"):
            target_key = str(condition["target"])
            label += f"〔{(target_names or {}).get(target_key, '指定目标')}〕"
        if kind == "TARGET_HP_BELOW" and condition.get("ratio") is not None:
            label += f"至 {float(condition['ratio']) * 100:g}%"
        outcome = "进入下一阶段" if stage.get("clear_outcome") == "NEXT_STAGE" else "结束战斗"
        return f"{label} → {outcome}"

    @staticmethod
    def _battle_list_page(
        rows: list[dict[str, Any]], nonce: str, page: int
    ) -> tuple[str, InlineKeyboardMarkup]:
        page_count = max(1, (len(rows) + _MENU_PAGE_SIZE - 1) // _MENU_PAGE_SIZE)
        page = min(max(0, int(page)), page_count - 1)
        start = page * _MENU_PAGE_SIZE
        visible = rows[start:start + _MENU_PAGE_SIZE]
        lines = [f"【战斗容器｜{page + 1}/{page_count}】"]
        keyboard: list[list[InlineKeyboardButton]] = []
        for offset, item in enumerate(visible, start=start):
            progress = ""
            if item.get("status") == "ACTIVE":
                stage = item.get("current_stage") or "?"
                phase = PHASE_LABELS.get(str(item.get("phase")), str(item.get("phase") or ""))
                progress = f"｜阶段 {stage}｜{phase}"
            lines.append(
                f"#{item['id']}｜{item['name']}\n"
                f"  状态：{SETUP_STATUS_LABELS.get(item['status'], item['status'])}｜"
                f"关卡：{item['encounter_name']}｜{item['total_stages']} 阶段｜"
                f"友方 {item['friendly_count']}{progress}"
            )
            keyboard.append([InlineKeyboardButton(
                f"选中 #{item['id']}｜{item['name']}",
                callback_data=f"dw:b:use:{nonce}.{offset}",
            )])
        navigation: list[InlineKeyboardButton] = []
        if page > 0:
            navigation.append(InlineKeyboardButton(
                "‹ 上一页", callback_data=f"dw:b:list:{nonce}.{page - 1}"
            ))
        if page + 1 < page_count:
            navigation.append(InlineKeyboardButton(
                "下一页 ›", callback_data=f"dw:b:list:{nonce}.{page + 1}"
            ))
        if navigation:
            keyboard.append(navigation)
        return "\n".join(lines), InlineKeyboardMarkup(keyboard)

    @staticmethod
    def _choice_page(
        options: list[dict[str, Any]],
        *,
        nonce: str,
        page: int,
        select_prefix: str,
        page_prefix: str,
        title: str,
        instruction: str,
    ) -> tuple[str, InlineKeyboardMarkup]:
        page_count = max(1, (len(options) + _MENU_PAGE_SIZE - 1) // _MENU_PAGE_SIZE)
        page = min(max(0, int(page)), page_count - 1)
        start = page * _MENU_PAGE_SIZE
        keyboard = [[InlineKeyboardButton(
            str(item["label"]), callback_data=f"{select_prefix}:{nonce}.{index}"
        )] for index, item in enumerate(
            options[start:start + _MENU_PAGE_SIZE], start=start
        )]
        navigation: list[InlineKeyboardButton] = []
        if page > 0:
            navigation.append(InlineKeyboardButton(
                "‹ 上一页", callback_data=f"{page_prefix}:{nonce}.{page - 1}"
            ))
        if page + 1 < page_count:
            navigation.append(InlineKeyboardButton(
                "下一页 ›", callback_data=f"{page_prefix}:{nonce}.{page + 1}"
            ))
        if navigation:
            keyboard.append(navigation)
        return (
            f"【{title}｜{page + 1}/{page_count}】\n{instruction}",
            InlineKeyboardMarkup(keyboard),
        )

    # ------------------------------------------------------------------
    # Telegram primitives and permissions
    # ------------------------------------------------------------------
    async def _reply(self, update: Update, text: str, **kwargs: Any) -> None:
        message = update.effective_message
        if message is None:
            return
        parts = _chunks(text)
        for index, part in enumerate(parts):
            await message.reply_text(part, **(kwargs if index == 0 else {}))

    async def _edit_and_follow_up(self, query: Any, text: str) -> None:
        parts = _chunks(text)
        try:
            await query.edit_message_text(parts[0])
        except BadRequest as exc:
            if "message is not modified" not in str(exc).lower():
                raise
        if len(parts) > 1 and query.message is not None:
            for part in parts[1:]:
                await query.message.reply_text(part)

    def _is_admin(self, update: Update) -> bool:
        user = update.effective_user
        return user is not None and int(user.id) in self.settings.admin_ids

    async def _require_admin(self, update: Update) -> bool:
        if self._is_admin(update):
            return True
        if update.callback_query is not None:
            await update.callback_query.answer(
                "该操作需要管理人权限。", show_alert=True
            )
        else:
            user_id = int(update.effective_user.id) if update.effective_user else 0
            await self._reply(
                update,
                "【权限核验失败】\n"
                f"你的 Telegram 用户编号是 {user_id}。\n"
                "请将它加入 DEWBOT_ADMIN_IDS 后重启系统。",
            )
        return False

    async def _command_error(self, update: Update, exc: Exception) -> None:
        if isinstance(exc, (BattleRuleError, ContentValidationError, ValueError)):
            await self._reply(update, f"【记录拒绝】\n{exc}")
            return
        LOGGER.exception("Unhandled Telegram command failure", exc_info=exc)
        await self._reply(update, "【记录中断】\n系统未能完成本次请求，请查阅后台日志。")

    async def _callback_error(self, query: Any, exc: Exception) -> int:
        if isinstance(exc, StaleFlowError):
            # A foreign or stale click must never overwrite the shared message
            # that still belongs to another valid flow.
            await query.answer(_compact(exc, _CALLBACK_ALERT_LIMIT), show_alert=True)
            return ConversationHandler.END
        if isinstance(exc, (BattleRuleError, ContentValidationError, ValueError)):
            await query.answer(_compact(exc, _CALLBACK_ALERT_LIMIT), show_alert=True)
            await self._edit_and_follow_up(query, f"【行动拒绝】\n{exc}")
        else:
            LOGGER.exception("Unhandled Telegram callback failure", exc_info=exc)
            await query.answer("行动记录发生异常。", show_alert=True)
            await self._edit_and_follow_up(
                query, "【记录中断】\n系统未能完成本次行动，请查阅后台日志。"
            )
        return ConversationHandler.END

    async def error_handler(
        self, update: object, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Log transport/update failures and give users a bounded response."""
        error = context.error
        LOGGER.error("Unhandled Telegram update failure", exc_info=error)
        if isinstance(update, Update) and update.effective_message is not None:
            await self._reply(
                update,
                "【记录中断】\n本次更新未能完成；战斗事务已回滚，请稍后重试。",
            )

    # ------------------------------------------------------------------
    # Read-only commands
    # ------------------------------------------------------------------
    async def start_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        del context
        await self._reply(
            update,
            "【Dewbot｜接收端已启动】\n"
            "战斗记录采用顺序回合：我方行动完成后，才会移交敌方。\n"
            "输入 /help 查阅完整指令索引。",
        )

    async def whoami_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        del context
        if update.effective_user is None:
            return
        user_id = int(update.effective_user.id)
        permission = "已登记为管理人" if user_id in self.settings.admin_ids else "尚未登记为管理人"
        await self._reply(
            update,
            f"【用户编号】\n{user_id}\n状态：{permission}\n"
            "配置方式：将编号写入 DEWBOT_ADMIN_IDS；多个编号用英文逗号分隔。",
        )

    async def _legacy_help_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        del context
        await self._reply(
            update,
            """【Dewbot｜接收指令索引】

/templates — 查阅可生成小怪/单位的模板
/spawn <模板键> <friendly|enemy> [名称] — 登记角色〔管理〕
/roster [我方|敌方] — 查阅现有角色
/personas <角色编号> — 查阅可用人格
/skills <角色编号> — 查阅当前人格的技能
/persona <角色编号> <人格键> — 切换人格〔管理；仅战斗外〕
/battle_start <我方编号…> -- <敌方编号…> [stages=N] [abnormalities=键,…] — 开战〔管理〕
/start_stage <我方编号…> -- <敌方编号…> — 编成下一阶段〔管理；/stage_start 同义〕
/battle — 查阅当前战斗档案
/attack — 展开我方行动
/lock — 锁定敌方指令并交给玩家〔管理〕
/defend 角色编号 [指令编号] — 发布人格防御指令
/enemy — 设置敌方技能与目标〔管理；技能情报仅操作者可见〕
/end_friendly_phase — 移交敌方行动权〔管理〕
/end_turn — 完成敌方阶段并统一清算〔管理〕
/end_battle — 中止当前战斗〔管理；/battle_abort 同义〕
/pages [书页报价编号] — 查阅或接纳异想体书页〔接纳需管理〕
/manager [能力键] — 查阅或发动管理人能力〔管理〕
/reload_content — 重载已配置内容包〔管理〕
/cancel — 撤销当前内联行动流程

回合顺序固定为：回合开始 → 我方全部行动 → 敌方全部行动 → 回合结束。""",
        )

    async def encounters_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        del context
        encounters = await asyncio.to_thread(self.engine.list_encounters)
        if not encounters:
            await self._reply(update, "【关卡档案】\n当前没有可用关卡。")
            return
        lines = ["【关卡档案】"]
        for item in encounters:
            lines.append(
                f"\n〔{item['name']}〕{item['encounter_key']}\n"
                f"阶段数：{item['total_stages']}\n{item['description']}"
            )
        await self._reply(update, "\n".join(lines))

    async def battle_prepare_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        if not await self._require_admin(update):
            return
        try:
            if len(context.args) != 1:
                raise ValueError("用法：/battle_prepare <关卡键>")
            user_id = int(update.effective_user.id) if update.effective_user else None
            async with self._mutation_lock:
                setup_id = await asyncio.to_thread(
                    self.engine.prepare_encounter, context.args[0], created_by=user_id
                )
            await self._reply(
                update,
                f"【战斗筹备 #{setup_id}】\n关卡容器已经展开。\n"
                "使用 /battle_core 选择核心角色及人格；普通友方使用 /battle_friendly。",
            )
        except Exception as exc:
            await self._command_error(update, exc)

    async def battle_setup_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        del context
        try:
            user_id = int(update.effective_user.id) if update.effective_user else None
            setup = await asyncio.to_thread(
                self.engine.battle_setup_status,
                user_id=user_id,
                chat_id=self._chat_id(update),
            )
            lines = [
                f"【战斗编成｜{setup['name']}】",
                f"编号：#{setup['id']}｜状态：{SETUP_STATUS_LABELS.get(setup['status'], setup['status'])}",
                f"基础关卡：{setup['encounter_name']}｜共 {setup['total_stages']} 阶段",
            ]
            gear_keys = [
                str(key)
                for key in json.loads(setup.get("abnormalities_json") or "[]")
            ]
            if gear_keys:
                gear_names = {
                    str(item["abnormality_key"]): str(item["name"])
                    for item in await asyncio.to_thread(self.engine.list_abnormalities)
                }
                lines.append(
                    "装备异想体："
                    + "、".join(gear_names.get(key, key) for key in gear_keys)
                    + "（/gear 可调整）"
                )
            else:
                lines.append("装备异想体：无（/gear 可装备，决定本场书页池）")
            lines.append("\n〔友方编成〕")
            if setup["friendlies"]:
                for item in setup["friendlies"]:
                    persona = f"｜人格：{item['persona_name']}" if item["persona_name"] else ""
                    lines.append(f"#{item['id']} {item['name']}{persona}")
            else:
                lines.append("尚未编入")
            enemies_by_stage: dict[int, list[str]] = {}
            targets_by_stage: dict[int, dict[str, str]] = {}
            for item in setup["enemies"]:
                label = item["display_name"] or item["template_name"]
                stage_number = int(item["stage_number"])
                enemies_by_stage.setdefault(stage_number, []).append(
                    f"{label} ×{item['amount']}"
                )
                if item.get("enemy_key"):
                    targets_by_stage.setdefault(stage_number, {})[
                        str(item["enemy_key"])
                    ] = str(label)
            lines.append("\n〔阶段记录〕")
            for stage in setup.get("stages", []):
                number = int(stage["stage_number"])
                lines.append(f"阶段 {number}｜{stage['name']}")
                lines.append("  敌方：" + "、".join(enemies_by_stage.get(number, ["尚未编入"])))
                lines.append(
                    "  结束条件："
                    + self._condition_label(stage, targets_by_stage.get(number, {}))
                )
            if not setup.get("stages"):
                for number in range(1, int(setup["total_stages"]) + 1):
                    lines.append(
                        f"阶段 {number}｜" + "、".join(enemies_by_stage.get(number, ["尚未编入"]))
                    )
            await self._reply(update, "\n".join(lines))
        except Exception as exc:
            await self._command_error(update, exc)

    async def _legacy_battle_core_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        if not await self._require_admin(update):
            return
        del context
        try:
            await asyncio.to_thread(self.engine.battle_setup_status)
            characters = await asyncio.to_thread(self.engine.list_characters, Faction.FRIENDLY)
            cores = [item for item in characters if int(item["is_core"])]
            if not cores:
                raise BattleRuleError("没有可编入的核心角色。")
            context_key = _CORE_FORMATION_FLOW
            # user_data is supplied by PTB; keep ownership explicit for forged callbacks.
            update_context = getattr(update, "_dewbot_context", None)
            del update_context
            keyboard = [
                [InlineKeyboardButton(item["name"], callback_data=f"dw:c:r:{item['id']}")]
                for item in cores
            ]
            keyboard.append([InlineKeyboardButton("完成编成", callback_data="dw:c:x")])
            await self._reply(
                update, "【核心角色编成】\n先选择参战角色，再为该角色选择本次装备的人格。",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
        except Exception as exc:
            await self._command_error(update, exc)

    async def _legacy_core_formation_callback(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        query = update.callback_query
        if query is None or not await self._require_admin(update):
            return
        try:
            data = str(query.data or "")
            if data == "dw:c:x":
                await query.answer("核心角色编成已记录。")
                await query.edit_message_text("【核心角色编成】\n选择完成，可继续追加单位或启动战斗。")
                return
            parts = data.split(":")
            if len(parts) != 4:
                raise ValueError("无效的编成回调。")
            kind, raw_id = parts[2], parts[3]
            if kind == "r":
                character_id = int(raw_id)
                character = await asyncio.to_thread(self.engine.get_character, character_id)
                personas = await asyncio.to_thread(self.engine.list_personas, character_id)
                keyboard = [
                    [InlineKeyboardButton(
                        f"{item['name']}｜HP {item['max_hp']}｜行动 {item['max_actions']}",
                        callback_data=f"dw:c:p:{character_id}.{item['id']}",
                    )] for item in personas
                ]
                await query.answer()
                await query.edit_message_text(
                    f"【{character['name']}｜人格装备】\n选择本次战斗采用的人格。",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                )
                return
            if kind == "p":
                character_raw, persona_raw = raw_id.split(".", 1)
                character_id, persona_id = int(character_raw), int(persona_raw)
                async with self._mutation_lock:
                    await asyncio.to_thread(
                        self.engine.add_core_to_setup, character_id, persona_id
                    )
                character = await asyncio.to_thread(self.engine.get_character, character_id)
                personas = await asyncio.to_thread(self.engine.list_personas, character_id)
                chosen = next(item for item in personas if int(item["id"]) == persona_id)
                await query.answer("已写入战斗编成。", show_alert=True)
                await query.edit_message_text(
                    f"【编成已记录】\n{character['name']}｜{chosen['name']}\n"
                    "继续输入 /battle_core 可添加或调整其他核心角色。"
                )
                return
            raise ValueError("无效的编成回调。")
        except Exception as exc:
            await self._callback_error(query, exc)

    async def battle_friendly_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        if not await self._require_admin(update):
            return
        try:
            ids = _parse_positive_ids(context.args)
            async with self._mutation_lock:
                await asyncio.to_thread(self.engine.add_noncore_friendlies_to_setup, ids)
            await self._reply(update, "【普通友方已编入】\n" + "、".join(f"#{item}" for item in ids))
        except Exception as exc:
            await self._command_error(update, exc)

    async def battle_enemy_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        if not await self._require_admin(update):
            return
        try:
            if not context.args:
                raise ValueError(
                    "用法：/battle_enemy <模板键> [stage=N] [count=N] [name=名称]"
                )
            template_key = context.args[0]
            options = dict(
                token.split("=", 1) for token in context.args[1:] if "=" in token
            )
            unknown = set(options) - {"stage", "count", "name"}
            if unknown:
                raise ValueError("未知参数：" + ", ".join(sorted(unknown)))
            async with self._mutation_lock:
                message = await asyncio.to_thread(
                    self.engine.add_enemy_to_formation,
                    template_key,
                    stage=int(options["stage"]) if "stage" in options else None,
                    amount=int(options.get("count", "1")),
                    name=options.get("name"),
                )
            await self._reply(update, "【敌方记录已追加】\n" + message)
        except Exception as exc:
            await self._command_error(update, exc)

    async def battle_launch_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        if not await self._require_admin(update):
            return
        del context
        try:
            async with self._mutation_lock:
                battle_id, messages = await asyncio.to_thread(
                    self.engine.launch_prepared_battle
                )
            await self._reply(
                update, "\n".join(messages) + f"\n\n战斗 #{battle_id} 开始！\n行动权在我方。"
            )
        except Exception as exc:
            await self._command_error(update, exc)

    async def battle_cancel_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        if not await self._require_admin(update):
            return
        del context
        try:
            async with self._mutation_lock:
                await asyncio.to_thread(self.engine.cancel_battle_setup)
            await self._reply(update, "【战斗筹备已撤销】\n关卡容器没有生成正式战斗。")
        except Exception as exc:
            await self._command_error(update, exc)

    async def battle_core_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        if not await self._require_admin(update) or update.effective_user is None:
            return
        try:
            user_id = int(update.effective_user.id)
            setup_id = await asyncio.to_thread(
                self.engine.selected_battle_setup_id,
                user_id,
                chat_id=self._chat_id(update),
            )
            setup = await asyncio.to_thread(self.engine.battle_setup_status, setup_id)
            if setup["status"] != "STANDBY":
                raise BattleRuleError("核心编成只能在战斗触发前调整。")
            characters = await asyncio.to_thread(
                self.engine.list_characters, Faction.FRIENDLY
            )
            cores = [item for item in characters if int(item["is_core"])]
            if not cores:
                raise BattleRuleError("没有可编入的核心角色。")
            existing = {
                int(item["id"]): item.get("persona_key")
                for item in setup["friendlies"] if int(item["is_core"])
            }
            nonce = self._remember_flow(
                context,
                _CORE_FORMATION_FLOW,
                initiator_id=user_id,
                chat_id=self._chat_id(update),
                setup_id=setup_id,
                setup_name=setup["name"],
                selected=list(existing),
                existing_personas=existing,
                choices={},
                core_ids=[int(item["id"]) for item in cores],
            )
            keyboard = [[InlineKeyboardButton(
                f"{'☑' if int(item['id']) in existing else '□'} {item['name']}",
                callback_data=f"dw:c:t:{nonce}.{item['id']}"
            )] for item in cores]
            keyboard.append([InlineKeyboardButton(
                "下一步：选择人格" if existing else "清空核心编成（再次确认）",
                callback_data=f"dw:c:n:{nonce}"
            )])
            await self._reply(
                update,
                f"【核心角色编成｜{self._setup_label(setup)}】\n"
                "勾选本次参战角色；取消勾选会在最终确认时移出编成。",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
        except Exception as exc:
            await self._command_error(update, exc)

    async def core_formation_callback(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        query = update.callback_query
        if query is None or not await self._require_admin(update):
            return
        try:
            user_id = int(update.effective_user.id) if update.effective_user else 0
            parts = str(query.data or "").split(":")
            if len(parts) != 4:
                raise ValueError("无效的编成回调。")
            kind, raw_id = parts[2], parts[3]
            nonce = raw_id.split(".", 1)[0]
            flow = self._owned_flow(
                context, _CORE_FORMATION_FLOW, nonce=nonce, user_id=user_id,
                chat_id=self._chat_id(update),
            )
            if kind == "t":
                character_id = int(raw_id.split(".", 1)[1])
                if character_id not in flow["core_ids"]:
                    raise BattleRuleError("该角色不在可选核心角色名单中。")
                selected = flow["selected"]
                selected.remove(character_id) if character_id in selected else selected.append(character_id)
                characters = [
                    await asyncio.to_thread(self.engine.get_character, item)
                    for item in flow["core_ids"]
                ]
                keyboard = [[InlineKeyboardButton(
                    f"{'☑' if int(item['id']) in selected else '□'} {item['name']}",
                    callback_data=f"dw:c:t:{nonce}.{item['id']}",
                )] for item in characters]
                keyboard.append([InlineKeyboardButton(
                    "下一步：选择人格" if selected else "清空核心编成（再次确认）",
                    callback_data=f"dw:c:n:{nonce}"
                )])
                await query.answer("已更新参战名单。")
                await query.edit_message_text(
                    "【核心角色编成｜第一步】\n先勾选所有参战角色，完成后再逐一选择人格。",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                )
                return
            if kind == "n":
                if not flow["selected"]:
                    await query.answer("请再次确认。")
                    await query.edit_message_text(
                        f"【清空核心编成确认｜{flow['setup_name']}】\n"
                        "清空后战斗将不能触发，直到重新编入核心角色。",
                        reply_markup=InlineKeyboardMarkup([[
                            InlineKeyboardButton(
                                "确认清空", callback_data=f"dw:c:z:{nonce}"
                            ),
                            InlineKeyboardButton(
                                "返回选择", callback_data=f"dw:c:r:{nonce}"
                            ),
                        ]]),
                    )
                    return
                flow["remaining"] = list(flow["selected"])
                await self._show_next_persona_choice(query, flow)
                return
            if kind == "z":
                if flow["selected"]:
                    raise StaleFlowError("参战名单已经变化，请重新确认。")
                async with self._mutation_lock:
                    await asyncio.to_thread(
                        self.engine.replace_core_formation,
                        int(flow["setup_id"]),
                        [],
                    )
                context.user_data.pop(_CORE_FORMATION_FLOW, None)
                await query.answer("核心编成已清空。")
                await query.edit_message_text(
                    f"【核心编成已清空｜{flow['setup_name']}】\n"
                    "触发战斗前必须重新使用 /team 编入至少一名核心角色。"
                )
                return
            if kind == "r":
                characters = [
                    await asyncio.to_thread(self.engine.get_character, item)
                    for item in flow["core_ids"]
                ]
                keyboard = [[InlineKeyboardButton(
                    f"{'☑' if int(item['id']) in flow['selected'] else '□'} {item['name']}",
                    callback_data=f"dw:c:t:{nonce}.{item['id']}",
                )] for item in characters]
                keyboard.append([InlineKeyboardButton(
                    "下一步：选择人格" if flow["selected"] else "清空核心编成（再次确认）",
                    callback_data=f"dw:c:n:{nonce}",
                )])
                await query.answer("已返回。")
                await query.edit_message_text(
                    "【核心角色编成｜第一步】\n勾选所有参战角色，完成后再选择人格。",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                )
                return
            if kind == "q":
                _nonce, page_raw = raw_id.split(".", 1)
                await self._show_next_persona_choice(query, flow, page=int(page_raw))
                return
            if kind == "p":
                _nonce, character_raw, persona_raw = raw_id.split(".", 2)
                character_id, persona_id = int(character_raw), int(persona_raw)
                remaining = flow.get("remaining", [])
                if not remaining or int(remaining[0]) != character_id:
                    raise BattleRuleError("人格选择顺序已经失效，请重新编成。")
                if persona_id not in flow.get("persona_ids", []):
                    raise BattleRuleError("该人格不在当前可选列表中。")
                flow["choices"][character_id] = persona_id
                remaining.pop(0)
                await query.answer("人格选择已记录。")
                if remaining:
                    await self._show_next_persona_choice(query, flow)
                else:
                    choices = [
                        (int(item), int(flow["choices"][item]))
                        for item in flow["selected"]
                    ]
                    async with self._mutation_lock:
                        await asyncio.to_thread(
                            self.engine.replace_core_formation,
                            int(flow["setup_id"]),
                            choices,
                        )
                    context.user_data.pop(_CORE_FORMATION_FLOW, None)
                    await query.edit_message_text(
                        f"【核心角色编成完成｜{flow['setup_name']}】\n"
                        "已按最终勾选名单整体替换，不会残留上一次的角色。\n"
                        "可使用 /plan 检查，或继续追加普通友方与敌人。"
                    )
                return
            raise ValueError("无效的编成回调。")
        except Exception as exc:
            await self._callback_error(query, exc)

    async def _show_next_persona_choice(
        self, query: Any, flow: dict[str, Any], *, page: int = 0
    ) -> None:
        character_id = int(flow["remaining"][0])
        character = await asyncio.to_thread(self.engine.get_character, character_id)
        personas = await asyncio.to_thread(self.engine.list_personas, character_id)
        flow["persona_ids"] = [int(item["id"]) for item in personas]
        page_count = max(1, (len(personas) + _MENU_PAGE_SIZE - 1) // _MENU_PAGE_SIZE)
        page = min(max(0, int(page)), page_count - 1)
        start = page * _MENU_PAGE_SIZE
        keyboard = [[InlineKeyboardButton(
            f"{'▣ 当前｜' if item['persona_key'] == flow.get('existing_personas', {}).get(character_id) else ''}"
            f"{item['name']}｜HP {item['max_hp']}｜行动 {item['max_actions']}",
            callback_data=f"dw:c:p:{flow['nonce']}.{character_id}.{item['id']}",
        )] for item in personas[start:start + _MENU_PAGE_SIZE]]
        navigation: list[InlineKeyboardButton] = []
        if page > 0:
            navigation.append(InlineKeyboardButton(
                "‹ 上一页", callback_data=f"dw:c:q:{flow['nonce']}.{page - 1}"
            ))
        if page + 1 < page_count:
            navigation.append(InlineKeyboardButton(
                "下一页 ›", callback_data=f"dw:c:q:{flow['nonce']}.{page + 1}"
            ))
        if navigation:
            keyboard.append(navigation)
        await query.edit_message_text(
            f"【核心角色编成｜第二步｜{page + 1}/{page_count}】\n"
            f"为 {character['name']} 选择本次装备的人格。",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    async def new_battle_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        if not await self._require_admin(update):
            return
        name = " ".join(context.args).strip()
        if not name:
            await self._reply(update, "用法：/new <战斗名称>\n例如：/new 人格测试战")
            return
        encounters = await asyncio.to_thread(self.engine.list_encounters)
        if not encounters:
            await self._reply(update, "【没有可用关卡】")
            return
        user_id = int(update.effective_user.id) if update.effective_user else 0
        choices = {str(index): item["encounter_key"] for index, item in enumerate(encounters)}
        options = [
            {
                "label": f"{item['name']}｜{item['total_stages']} 阶段",
                "value": item["encounter_key"],
            }
            for item in encounters
        ]
        nonce = self._remember_flow(
            context,
            _NEW_BATTLE_FLOW,
            initiator_id=user_id,
            chat_id=self._chat_id(update),
            name=name,
            choices=choices,
            options=options,
        )
        text, markup = self._choice_page(
            options,
            nonce=nonce,
            page=0,
            select_prefix="dw:b:new",
            page_prefix="dw:b:newpage",
            title=f"建立待触发战斗｜{name}",
            instruction="请选择作为基础的关卡。",
        )
        await self._reply(update, text, reply_markup=markup)

    async def battles_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        if not await self._require_admin(update) or update.effective_user is None:
            return
        rows = await asyncio.to_thread(self.engine.list_battle_setups)
        if not rows:
            await self._reply(update, "【战斗容器】\n当前没有等待触发或正在进行的战斗。使用 /new 名称 创建。")
            return
        nonce = self._remember_flow(
            context,
            _BATTLE_LIST_FLOW,
            initiator_id=int(update.effective_user.id),
            chat_id=self._chat_id(update),
            rows=rows,
        )
        text, markup = self._battle_list_page(rows, nonce, 0)
        await self._reply(update, text, reply_markup=markup)

    async def use_battle_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        if not await self._require_admin(update):
            return
        try:
            if len(context.args) != 1 or not context.args[0].lstrip("#").isdecimal():
                raise ValueError("用法：/use <战斗编号>（编号可从 /battles 查看）")
            context.args[0] = context.args[0].lstrip("#")
            user_id = int(update.effective_user.id)
            setup = await asyncio.to_thread(
                self.engine.select_battle_setup,
                user_id,
                int(context.args[0]),
                chat_id=self._chat_id(update),
            )
            await self._reply(update, f"【已选中】\n#{setup['id']}｜{setup['name']}")
        except Exception as exc:
            await self._command_error(update, exc)

    async def team_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        await self.battle_core_command(update, context)

    async def ally_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        if not await self._require_admin(update) or update.effective_user is None:
            return
        try:
            user_id = int(update.effective_user.id)
            setup_id = await asyncio.to_thread(
                self.engine.selected_battle_setup_id,
                user_id,
                chat_id=self._chat_id(update),
            )
            setup = await asyncio.to_thread(self.engine.battle_setup_status, setup_id)
            already_added = {int(item["id"]) for item in setup["friendlies"]}
            rows = await asyncio.to_thread(self.engine.list_characters, Faction.FRIENDLY)
            rows = [item for item in rows if not int(item["is_core"])]
            if setup["status"] == "ACTIVE":
                rows = [
                    item for item in rows
                    if int(item["id"]) not in already_added
                    and int(item["current_hp"]) > 0
                    and int(item.get("template_enabled", 1))
                ]
            else:
                # Keep already-added invalid units visible so the administrator
                # can remove them; do not offer dead/disabled new additions.
                rows = [
                    item for item in rows
                    if int(item["id"]) in already_added
                    or (
                        int(item["current_hp"]) > 0
                        and int(item.get("template_enabled", 1))
                    )
                ]
            if not rows:
                raise BattleRuleError("当前没有可选择的普通友方。")
            options = [
                {
                    "label": (
                        f"{'☑' if int(item['id']) in already_added else '□'} "
                        f"#{item['id']} {item['name']}"
                        + (
                            "（不可出战，点击移除）"
                            if int(item['id']) in already_added
                            and (
                                int(item["current_hp"]) <= 0
                                or not int(item.get("template_enabled", 1))
                            )
                            else ""
                        )
                        if setup["status"] == "STANDBY" else f"#{item['id']} {item['name']}"
                    ),
                    "name": item["name"],
                    "value": int(item["id"]),
                    "can_add": (
                        int(item["current_hp"]) > 0
                        and int(item.get("template_enabled", 1)) == 1
                    ),
                }
                for item in rows
            ]
            choices = {str(index): item["value"] for index, item in enumerate(options)}
            nonce = self._remember_flow(
                context,
                _ALLY_FLOW,
                initiator_id=user_id,
                chat_id=self._chat_id(update),
                setup_id=setup_id,
                setup_name=setup["name"],
                status=setup["status"],
                choices=choices,
                options=options,
                used=[],
                added=list(already_added),
            )
            text, markup = self._choice_page(
                options,
                nonce=nonce,
                page=0,
                select_prefix="dw:b:ally",
                page_prefix="dw:b:allypage",
                title=f"友方增援｜{self._setup_label(setup)}",
                instruction=(
                    "点击可勾选或取消普通友方。"
                    if setup["status"] == "STANDBY"
                    else "点选要加入的普通角色；将立即进入当前阶段。"
                ),
            )
            await self._reply(
                update,
                text,
                reply_markup=markup,
            )
        except Exception as exc:
            await self._command_error(update, exc)

    async def foe_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        if not await self._require_admin(update) or update.effective_user is None:
            return
        try:
            user_id = int(update.effective_user.id)
            setup_id = await asyncio.to_thread(
                self.engine.selected_battle_setup_id,
                user_id,
                chat_id=self._chat_id(update),
            )
            setup = await asyncio.to_thread(self.engine.battle_setup_status, setup_id)
            templates = await asyncio.to_thread(self.engine.list_templates)
            options = [
                {
                    "label": f"＋ 编入 {item['name']}",
                    "value": {"action": "add", "template_key": item["template_key"]},
                }
                for item in templates
            ]
            if setup["status"] == "STANDBY":
                options.extend(
                    {
                        "label": (
                            f"✕ 移除｜阶段 {item['stage_number']}｜"
                            f"{item['display_name'] or item['template_name']} ×{item['amount']}"
                        ),
                        "value": {"action": "remove", "setup_enemy_id": int(item["id"])},
                    }
                    for item in setup["enemies"]
                    if item.get("source") == "MANUAL"
                )
            if not options:
                raise BattleRuleError("当前没有可编入的敌人种类，也没有可移除的手动敌人。")
            choices = {str(index): item["value"] for index, item in enumerate(options)}
            nonce = self._remember_flow(
                context,
                _FOE_FLOW,
                initiator_id=user_id,
                chat_id=self._chat_id(update),
                setup_id=setup_id,
                setup_name=setup["name"],
                total_stages=int(setup["total_stages"]),
                current_stage=int(setup.get("current_stage") or 0),
                status=setup["status"],
                choices=choices,
                options=options,
            )
            text, markup = self._choice_page(
                options,
                nonce=nonce,
                page=0,
                select_prefix="dw:b:foe",
                page_prefix="dw:b:foepage",
                title=f"追加敌人｜{self._setup_label(setup)}",
                instruction="选择要编入的敌人；战前手动追加项也可在这里移除。",
            )
            await self._reply(
                update, text, reply_markup=markup,
            )
        except Exception as exc:
            await self._command_error(update, exc)

    async def ready_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        if not await self._require_admin(update) or update.effective_user is None:
            return
        try:
            user_id = int(update.effective_user.id)
            setup_id = await asyncio.to_thread(
                self.engine.selected_battle_setup_id,
                user_id,
                chat_id=self._chat_id(update),
            )
            setup = await asyncio.to_thread(self.engine.battle_setup_status, setup_id)
            if setup["status"] != "STANDBY":
                raise BattleRuleError("这场战斗已经触发，不能再次启动。")
            cores = [item for item in setup["friendlies"] if int(item["is_core"])]
            if not cores:
                raise BattleRuleError("触发前必须先使用 /team 编入至少一名核心角色。")
            invalid_allies = [
                item for item in setup["friendlies"]
                if not int(item["is_core"])
                and (
                    int(item.get("current_hp", 1)) <= 0
                    or not int(item.get("template_enabled", 1))
                )
            ]
            if invalid_allies:
                names = "、".join(f"#{item['id']} {item['name']}" for item in invalid_allies)
                raise BattleRuleError(
                    f"普通友方已无法出战：{names}。请使用 /ally 将其移出编成。"
                )
            stage_one = [item for item in setup["enemies"] if int(item["stage_number"]) == 1]
            if not stage_one:
                raise BattleRuleError(
                    "第一阶段尚未编入敌人；请先使用 /foe 添加，或更换带预设敌人的关卡。"
                )
            nonce = self._remember_flow(
                context,
                _READY_FLOW,
                initiator_id=user_id,
                chat_id=self._chat_id(update),
                setup_id=setup_id,
                setup_revision=int(setup.get("revision", 0)),
                setup_signature=self._setup_signature(setup),
            )
            friendly_names = "、".join(item["name"] for item in setup["friendlies"])
            enemy_names = "、".join(
                f"{item['display_name'] or item['template_name']}×{item['amount']}"
                for item in stage_one
            ) or "无"
            keyboard = [[
                InlineKeyboardButton("确认触发", callback_data=f"dw:b:ready:{nonce}"),
                InlineKeyboardButton("返回", callback_data=f"dw:b:no:{nonce}"),
            ]]
            await self._reply(
                update,
                f"【触发确认｜{self._setup_label(setup)}】\n"
                f"友方：{friendly_names}\n第一阶段敌方：{enemy_names}\n"
                "确认后将建立正式战斗记录。",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
        except Exception as exc:
            await self._command_error(update, exc)

    async def discard_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        if not await self._require_admin(update) or update.effective_user is None:
            return
        try:
            user_id = int(update.effective_user.id)
            setup_id = await asyncio.to_thread(
                self.engine.selected_battle_setup_id,
                user_id,
                chat_id=self._chat_id(update),
            )
            setup = await asyncio.to_thread(self.engine.battle_setup_status, setup_id)
            if setup["status"] != "STANDBY":
                raise BattleRuleError("进行中的战斗请使用 /stop；/discard 只撤销等待触发的战斗。")
            nonce = self._remember_flow(
                context,
                _DISCARD_FLOW,
                initiator_id=user_id,
                chat_id=self._chat_id(update),
                setup_id=setup_id,
                setup_name=setup["name"],
            )
            await self._reply(
                update,
                f"【撤销确认｜{self._setup_label(setup)}】\n撤销后该记录将不再出现在可选列表中。",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("确认撤销", callback_data=f"dw:b:discard:{nonce}"),
                    InlineKeyboardButton("返回", callback_data=f"dw:b:keep:{nonce}"),
                ]]),
            )
        except Exception as exc:
            await self._command_error(update, exc)

    async def battle_formation_callback(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        query = update.callback_query
        if query is None or not await self._require_admin(update) or update.effective_user is None:
            return
        try:
            parts = str(query.data or "").split(":", 3)
            if len(parts) != 4:
                raise ValueError("无效的战斗编成回调。")
            action, value = parts[2], parts[3]
            user_id = int(update.effective_user.id)
            if action == "newpage":
                nonce, page_raw = value.split(".", 1)
                flow = self._owned_flow(
                    context, _NEW_BATTLE_FLOW, nonce=nonce, user_id=user_id,
                    chat_id=self._chat_id(update),
                )
                text, markup = self._choice_page(
                    flow["options"],
                    nonce=nonce,
                    page=int(page_raw),
                    select_prefix="dw:b:new",
                    page_prefix="dw:b:newpage",
                    title=f"建立待触发战斗｜{flow['name']}",
                    instruction="请选择作为基础的关卡。",
                )
                await query.answer()
                await query.edit_message_text(text, reply_markup=markup)
                return
            if action == "new":
                nonce, choice = value.split(".", 1)
                flow = self._owned_flow(
                    context, _NEW_BATTLE_FLOW, nonce=nonce, user_id=user_id,
                    chat_id=self._chat_id(update),
                )
                encounter_key = flow["choices"].get(choice)
                if encounter_key is None:
                    raise BattleRuleError("该关卡选项已经失效。")
                name = str(flow["name"]).strip()
                async with self._mutation_lock:
                    setup_id = await asyncio.to_thread(
                        self.engine.prepare_encounter,
                        encounter_key,
                        name=name,
                        created_by=user_id,
                        selection_chat_id=self._chat_id(update),
                    )
                context.user_data.pop(_NEW_BATTLE_FLOW, None)
                await query.answer("待触发战斗已建立。")
                await query.edit_message_text(
                    f"【已建立并选中】\n#{setup_id}｜{name}\n接下来使用 /team 选择核心角色。"
                )
                return
            if action == "use":
                nonce, choice = value.split(".", 1)
                flow = self._owned_flow(
                    context, _BATTLE_LIST_FLOW, nonce=nonce, user_id=user_id,
                    chat_id=self._chat_id(update),
                )
                try:
                    setup_id = int(flow["rows"][int(choice)]["id"])
                except (IndexError, KeyError, TypeError, ValueError) as exc:
                    raise StaleFlowError("该战斗选项已经失效，请重新使用 /battles。") from exc
                async with self._mutation_lock:
                    setup = await asyncio.to_thread(
                        self.engine.select_battle_setup,
                        user_id,
                        setup_id,
                        chat_id=self._chat_id(update),
                    )
                await query.answer("已选中。")
                await query.edit_message_text(f"【已选中】\n#{setup['id']}｜{setup['name']}")
                return
            if action == "list":
                nonce, page_raw = value.split(".", 1)
                flow = self._owned_flow(
                    context, _BATTLE_LIST_FLOW, nonce=nonce, user_id=user_id,
                    chat_id=self._chat_id(update),
                )
                text, markup = self._battle_list_page(
                    flow["rows"], nonce, int(page_raw)
                )
                await query.answer()
                await query.edit_message_text(text, reply_markup=markup)
                return
            if action in {"allypage", "foepage"}:
                nonce, page_raw = value.split(".", 1)
                flow_key = _ALLY_FLOW if action == "allypage" else _FOE_FLOW
                flow = self._owned_flow(
                    context, flow_key, nonce=nonce, user_id=user_id,
                    chat_id=self._chat_id(update),
                )
                is_ally = action == "allypage"
                title = (
                    f"友方增援｜#{flow['setup_id']}｜{flow['setup_name']}"
                    if is_ally
                    else f"追加敌人｜#{flow['setup_id']}｜{flow['setup_name']}"
                )
                text, markup = self._choice_page(
                    flow["options"],
                    nonce=nonce,
                    page=int(page_raw),
                    select_prefix="dw:b:ally" if is_ally else "dw:b:foe",
                    page_prefix="dw:b:allypage" if is_ally else "dw:b:foepage",
                    title=title,
                    instruction=(
                        (
                            "点击可勾选或取消普通友方。"
                            if flow.get("status") == "STANDBY"
                            else "点选要加入的普通角色；将立即进入当前阶段。"
                        )
                        if is_ally else "选择要编入的敌人；战前手动追加项也可在这里移除。"
                    ),
                )
                await query.answer()
                await query.edit_message_text(text, reply_markup=markup)
                return
            if action == "ally":
                nonce, choice = value.split(".", 1)
                flow = self._owned_flow(
                    context, _ALLY_FLOW, nonce=nonce, user_id=user_id,
                    chat_id=self._chat_id(update),
                )
                character_id = flow["choices"].get(choice)
                if character_id is None:
                    raise BattleRuleError("该友方选项已经失效。")
                if flow.get("status") == "STANDBY":
                    added = flow["added"]
                    option = flow["options"][int(choice)]
                    if int(character_id) not in added and not option.get("can_add", True):
                        await query.answer(
                            "该角色已经无法出战；只能从旧编成移除，不能重新加入。",
                            show_alert=True,
                        )
                        return
                    async with self._mutation_lock:
                        if int(character_id) in added:
                            await asyncio.to_thread(
                                self.engine.remove_noncore_friendly_from_setup,
                                int(character_id),
                                setup_id=int(flow["setup_id"]),
                            )
                            added.remove(int(character_id))
                            message = "普通友方已移出编成。"
                        else:
                            await asyncio.to_thread(
                                self.engine.add_noncore_friendlies_to_setup,
                                [int(character_id)], setup_id=int(flow["setup_id"]),
                            )
                            added.append(int(character_id))
                            message = "普通友方已加入编成。"
                    option["label"] = (
                        f"{'☑' if int(character_id) in added else '□'} "
                        f"#{character_id} {option['name']}"
                        + ("（不可出战）" if not option.get("can_add", True) else "")
                    )
                    text, markup = self._choice_page(
                        flow["options"],
                        nonce=nonce,
                        page=int(choice) // _MENU_PAGE_SIZE,
                        select_prefix="dw:b:ally",
                        page_prefix="dw:b:allypage",
                        title=f"友方增援｜#{flow['setup_id']}｜{flow['setup_name']}",
                        instruction="点击可勾选或取消普通友方。",
                    )
                    await query.answer(message)
                    await query.edit_message_text(text, reply_markup=markup)
                    return
                if choice in flow["used"]:
                    raise BattleRuleError("该角色已经通过这组按钮加入。")
                async with self._mutation_lock:
                    await asyncio.to_thread(
                        self.engine.add_noncore_friendlies_to_setup,
                        [int(character_id)], setup_id=int(flow["setup_id"]),
                    )
                flow["used"].append(choice)
                await query.answer("普通友方已加入当前阶段。", show_alert=True)
                return
            if action == "foe":
                nonce, choice = value.split(".", 1)
                flow = self._owned_flow(
                    context, _FOE_FLOW, nonce=nonce, user_id=user_id,
                    chat_id=self._chat_id(update),
                )
                selection = flow["choices"].get(choice)
                if not isinstance(selection, dict):
                    raise BattleRuleError("该敌人选项已经失效。")
                if selection.get("action") == "remove":
                    async with self._mutation_lock:
                        message = await asyncio.to_thread(
                            self.engine.remove_manual_enemy_from_setup,
                            int(selection["setup_enemy_id"]),
                            setup_id=int(flow["setup_id"]),
                        )
                    context.user_data.pop(_FOE_FLOW, None)
                    await query.answer("敌方编成已移除。")
                    await query.edit_message_text(
                        f"【敌方编成已更新】\n{message}\n如需继续调整，请再次使用 /foe。"
                    )
                    return
                template_key = selection.get("template_key")
                if selection.get("action") != "add" or not template_key:
                    raise BattleRuleError("该敌人选项已经失效。")
                flow["template_key"] = str(template_key)
                setup = await asyncio.to_thread(
                    self.engine.battle_setup_status, int(flow["setup_id"])
                )
                total_stages = int(setup["total_stages"])
                if setup["status"] == "STANDBY":
                    legal_stages = range(1, total_stages + 1)
                else:
                    current = int(setup.get("current_stage") or 1)
                    phase = str(setup.get("phase") or "")
                    first = current if phase in {
                        BattlePhase.FRIENDLY_ACTION.value,
                        BattlePhase.ENEMY_ACTION.value,
                    } else current + 1
                    legal_stages = range(first, total_stages + 1)
                legal_stages = list(legal_stages)
                if not legal_stages:
                    raise BattleRuleError("当前没有仍可接受敌方增援的阶段。")
                keyboard = [[InlineKeyboardButton(
                    f"确认加入阶段 {stage}",
                    callback_data=f"dw:b:add:{nonce}.{stage}",
                )] for stage in legal_stages]
                await query.answer()
                await query.edit_message_text(
                    "【追加敌人｜最终确认】\n每次流程只加入一名，避免重复点击造成误编。",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                )
                return
            if action == "add":
                nonce, stage_raw = value.split(".", 1)
                flow = self._owned_flow(
                    context, _FOE_FLOW, nonce=nonce, user_id=user_id,
                    chat_id=self._chat_id(update),
                )
                template_key = flow.get("template_key")
                if not template_key:
                    raise BattleRuleError("请先重新选择敌人种类。")
                async with self._mutation_lock:
                    message = await asyncio.to_thread(
                        self.engine.add_enemy_to_formation, template_key,
                        stage=int(stage_raw), setup_id=int(flow["setup_id"]),
                    )
                context.user_data.pop(_FOE_FLOW, None)
                await query.answer("敌方已编入。")
                await query.edit_message_text(
                    f"【敌方编成已更新】\n{message}\n如需继续追加，请再次使用 /foe。"
                )
                return
            if action in {"ready", "no"}:
                flow = self._owned_flow(
                    context, _READY_FLOW, nonce=value, user_id=user_id,
                    chat_id=self._chat_id(update),
                )
                if action == "no":
                    context.user_data.pop(_READY_FLOW, None)
                    await query.answer("已返回。")
                    await query.edit_message_text("【未触发】\n战斗仍在等待，可继续调整编成。")
                    return
                async with self._mutation_lock:
                    current = await asyncio.to_thread(
                        self.engine.battle_setup_status, int(flow["setup_id"])
                    )
                    if (
                        current["status"] != "STANDBY"
                        or self._setup_signature(current) != flow["setup_signature"]
                    ):
                        raise BattleRuleError(
                            "确认页面出现后，友方或第一阶段敌方编成已经变化；"
                            "本次没有触发，请重新使用 /ready 核对。"
                        )
                    battle_id, messages = await asyncio.to_thread(
                        self.engine.launch_prepared_battle,
                        int(flow["setup_id"]),
                        expected_revision=int(flow["setup_revision"]),
                    )
                context.user_data.pop(_READY_FLOW, None)
                await query.answer("战斗已触发。")
                await self._edit_and_follow_up(
                    query, "\n".join(messages) + f"\n\n战斗档案：#{battle_id}"
                )
                return
            if action in {"discard", "keep"}:
                flow = self._owned_flow(
                    context, _DISCARD_FLOW, nonce=value, user_id=user_id,
                    chat_id=self._chat_id(update),
                )
                context.user_data.pop(_DISCARD_FLOW, None)
                if action == "keep":
                    await query.answer("已返回。")
                    await query.edit_message_text("【保留记录】\n战斗仍在等待触发。")
                    return
                async with self._mutation_lock:
                    await asyncio.to_thread(
                        self.engine.cancel_battle_setup, int(flow["setup_id"])
                    )
                await query.answer("记录已撤销。")
                await query.edit_message_text(
                    f"【已撤销】\n{flow['setup_name']} 不再等待触发。"
                )
                return
            if action in {"stop", "continue"}:
                flow = self._owned_flow(
                    context, _STOP_FLOW, nonce=value, user_id=user_id,
                    chat_id=self._chat_id(update),
                )
                context.user_data.pop(_STOP_FLOW, None)
                if action == "continue":
                    await query.answer("继续战斗。")
                    await query.edit_message_text("【中止已取消】\n战斗记录保持展开。")
                    return
                status = await asyncio.to_thread(self.engine.battle_status)
                if int(status["id"]) != int(flow["battle_id"]):
                    raise BattleRuleError("活动战斗已经更替，旧确认按钮不能中止新战斗。")
                async with self._mutation_lock:
                    messages = await asyncio.to_thread(
                        self.engine.end_battle, "ABORTED"
                    )
                await query.answer("战斗已中止。")
                await self._edit_and_follow_up(query, "\n".join(messages))
                return
            raise ValueError("无效的战斗编成操作。")
        except Exception as exc:
            await self._callback_error(query, exc)

    async def identity_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        if not await self._require_admin(update) or update.effective_user is None:
            return
        cores = [
            item for item in await asyncio.to_thread(
                self.engine.list_characters, Faction.FRIENDLY
            ) if int(item["is_core"])
        ]
        if not cores:
            await self._reply(update, "【战斗外人格装备】\n当前没有可切换人格的核心角色。")
            return
        options = [
            {"label": item["name"], "value": int(item["id"])} for item in cores
        ]
        choices = {str(index): item["value"] for index, item in enumerate(options)}
        nonce = self._remember_flow(
            context,
            _HUMAN_CONTENT_FLOW,
            initiator_id=int(update.effective_user.id),
            chat_id=self._chat_id(update),
            mode="identity",
            choices=choices,
            options=options,
        )
        text, markup = self._choice_page(
            options,
            nonce=nonce,
            page=0,
            select_prefix="dw:h:id",
            page_prefix="dw:h:idpage",
            title="战斗外人格装备",
            instruction="请选择核心角色。",
        )
        await self._reply(
            update, text, reply_markup=markup,
        )

    async def create_unit_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        if not await self._require_admin(update) or update.effective_user is None:
            return
        templates = await asyncio.to_thread(self.engine.list_templates)
        if not templates:
            await self._reply(update, "【建立普通友方】\n当前没有可用的单位种类。")
            return
        requested_name = " ".join(context.args).strip() or None
        options = [
            {"label": item["name"], "value": item["template_key"]}
            for item in templates
        ]
        choices = {str(index): item["value"] for index, item in enumerate(options)}
        nonce = self._remember_flow(
            context,
            _HUMAN_CONTENT_FLOW,
            initiator_id=int(update.effective_user.id),
            chat_id=self._chat_id(update),
            mode="create",
            requested_name=requested_name,
            choices=choices,
            options=options,
        )
        text, markup = self._choice_page(
            options,
            nonce=nonce,
            page=0,
            select_prefix="dw:h:ct",
            page_prefix="dw:h:ctpage",
            title="建立普通友方",
            instruction=(
                f"角色名称将登记为「{requested_name}」；请选择单位种类。"
                if requested_name else "请选择单位种类；不另填名称时沿用种类名称。"
            ),
        )
        await self._reply(
            update, text, reply_markup=markup,
        )

    async def human_content_callback(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        query = update.callback_query
        if query is None or not await self._require_admin(update) or update.effective_user is None:
            return
        try:
            parts = str(query.data or "").split(":", 3)
            if len(parts) != 4:
                raise ValueError("无效的选择回调。")
            action, value = parts[2], parts[3]
            nonce = value.split(".", 1)[0]
            user_id = int(update.effective_user.id)
            flow = self._owned_flow(
                context, _HUMAN_CONTENT_FLOW, nonce=nonce, user_id=user_id,
                chat_id=self._chat_id(update),
            )
            if action in {"idpage", "ctpage"}:
                expected_mode = "identity" if action == "idpage" else "create"
                if flow.get("mode") != expected_mode:
                    raise BattleRuleError("这组选择按钮已经失效。")
                _nonce, page_raw = value.split(".", 1)
                is_identity = action == "idpage"
                text, markup = self._choice_page(
                    flow["options"],
                    nonce=nonce,
                    page=int(page_raw),
                    select_prefix="dw:h:id" if is_identity else "dw:h:ct",
                    page_prefix="dw:h:idpage" if is_identity else "dw:h:ctpage",
                    title="战斗外人格装备" if is_identity else "建立普通友方",
                    instruction=(
                        "请选择核心角色。"
                        if is_identity else (
                            f"角色名称将登记为「{flow['requested_name']}」；请选择单位种类。"
                            if flow.get("requested_name") else "请选择单位种类。"
                        )
                    ),
                )
                await query.answer()
                await query.edit_message_text(text, reply_markup=markup)
                return
            if action == "ippage":
                if flow.get("mode") != "identity" or not flow.get("persona_options"):
                    raise BattleRuleError("人格选择流程已经失效。")
                _nonce, page_raw = value.split(".", 1)
                text, markup = self._choice_page(
                    flow["persona_options"],
                    nonce=nonce,
                    page=int(page_raw),
                    select_prefix="dw:h:ip",
                    page_prefix="dw:h:ippage",
                    title=f"{flow['character_name']}｜人格装备",
                    instruction="请选择人格。",
                )
                await query.answer()
                await query.edit_message_text(text, reply_markup=markup)
                return
            if action == "id":
                if flow.get("mode") != "identity":
                    raise BattleRuleError("人格选择流程已经失效。")
                _nonce, choice = value.split(".", 1)
                character_id = flow["choices"].get(choice)
                if character_id is None:
                    raise BattleRuleError("该角色选项已经失效。")
                character = await asyncio.to_thread(self.engine.get_character, character_id)
                personas = await asyncio.to_thread(self.engine.list_personas, character_id)
                flow["character_id"] = int(character_id)
                flow["character_name"] = character["name"]
                flow["persona_ids"] = [int(item["id"]) for item in personas]
                flow["persona_options"] = [
                    {
                        "label": f"{'▣ 当前｜' if item['is_active'] else ''}{item['name']}",
                        "value": int(item["id"]),
                    }
                    for item in personas
                ]
                flow["persona_choices"] = {
                    str(index): item["value"]
                    for index, item in enumerate(flow["persona_options"])
                }
                text, markup = self._choice_page(
                    flow["persona_options"],
                    nonce=nonce,
                    page=0,
                    select_prefix="dw:h:ip",
                    page_prefix="dw:h:ippage",
                    title=f"{character['name']}｜人格装备",
                    instruction="请选择人格。",
                )
                await query.answer()
                await query.edit_message_text(
                    text,
                    reply_markup=markup,
                )
                return
            if action == "ip":
                _nonce, choice = value.split(".", 1)
                persona_id = flow.get("persona_choices", {}).get(choice)
                if persona_id is None:
                    raise BattleRuleError("该人格选项已经失效。")
                character_id, persona_id = int(flow["character_id"]), int(persona_id)
                if persona_id not in flow.get("persona_ids", []):
                    raise BattleRuleError("该人格选项已经失效。")
                persona = next(
                    item for item in await asyncio.to_thread(
                        self.engine.list_personas, character_id
                    ) if int(item["id"]) == persona_id
                )
                if int(persona.get("is_active", 0)):
                    await query.answer("该人格已经装备；角色状态没有被重置。", show_alert=True)
                    return
                async with self._mutation_lock:
                    await asyncio.to_thread(
                        self.engine.switch_persona, character_id, persona["persona_key"]
                    )
                context.user_data.pop(_HUMAN_CONTENT_FLOW, None)
                await query.answer("人格已经装备。")
                await query.edit_message_text(f"【装备完成】\n{persona['name']}")
                return
            if action == "ct":
                if flow.get("mode") != "create":
                    raise BattleRuleError("角色建立流程已经失效。")
                _nonce, choice = value.split(".", 1)
                template_key = flow["choices"].get(choice)
                if template_key is None:
                    raise BattleRuleError("该单位种类已经失效。")
                async with self._mutation_lock:
                    character_id = await asyncio.to_thread(
                        self.engine.spawn_character,
                        template_key,
                        Faction.FRIENDLY,
                        name=flow.get("requested_name"),
                    )
                character = await asyncio.to_thread(self.engine.get_character, character_id)
                context.user_data.pop(_HUMAN_CONTENT_FLOW, None)
                await query.answer("角色已经建立。")
                await query.edit_message_text(
                    f"【普通友方已建立】\n#{character_id}｜{character['name']}\n"
                    "可使用 /ally 将其编入当前战斗。"
                )
                return
            raise ValueError("无效的选择操作。")
        except Exception as exc:
            await self._callback_error(query, exc)

    async def templates_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        del context
        try:
            templates = await asyncio.to_thread(self.engine.list_templates)
            if not templates:
                await self._reply(update, "【单位模板档案】\n当前没有可用于生成普通单位的模板。核心角色请查阅 /roster。")
                return
            lines = ["【单位模板档案】"]
            for item in templates:
                lines.append(
                    f"\n〔生成模板〕{item['name']}  ·  {item['template_key']}\n"
                    f"HP {item['max_hp']}｜行动 {item['max_actions']}｜混乱 {item['max_stagger']}"
                )
                if item.get("description"):
                    lines.append(f"  {_compact(item['description'], 180)}")
            await self._reply(update, "\n".join(lines))
        except Exception as exc:  # pragma: no cover - defensive Telegram boundary
            await self._command_error(update, exc)

    async def roster_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        try:
            faction: Faction | None = None
            if context.args:
                raw = context.args[0].lower()
                aliases = {
                    "friendly": Faction.FRIENDLY,
                    "f": Faction.FRIENDLY,
                    "我方": Faction.FRIENDLY,
                    "enemy": Faction.ENEMY,
                    "e": Faction.ENEMY,
                    "敌方": Faction.ENEMY,
                }
                if raw not in aliases:
                    raise ValueError("阵营仅接受 friendly 或 enemy。")
                faction = aliases[raw]
            characters = await asyncio.to_thread(self.engine.list_characters, faction)
            if not characters:
                await self._reply(update, "【角色名册】\n没有符合条件的记录。")
                return
            sections: list[str] = ["【角色名册】"]
            for wanted, title in (
                (Faction.FRIENDLY.value, "我方"),
                (Faction.ENEMY.value, "敌方"),
            ):
                rows = [row for row in characters if row["faction"] == wanted]
                if not rows:
                    continue
                sections.append(f"\n▣ {title}")
                sections.extend(self._character_line(row, include_template=True) for row in rows)
            await self._reply(update, "\n".join(sections))
        except Exception as exc:
            await self._command_error(update, exc)

    async def personas_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        try:
            if len(context.args) != 1:
                raise ValueError("用法：/personas <核心角色名称或角色编号>，例如 /personas 珏")
            raw = context.args[0].strip()
            if raw.isdecimal():
                character = await asyncio.to_thread(self.engine.get_character, int(raw))
            else:
                character = await asyncio.to_thread(self.engine.get_core_character, raw)
            if character["faction"] == Faction.ENEMY.value:
                raise BattleRuleError(
                    "敌方不具备可公开切换的人格档案。"
                )
            character_id = int(character["id"])
            personas = await asyncio.to_thread(self.engine.list_personas, character_id)
            if not personas:
                await self._reply(
                    update,
                    f"【人格档案｜{character['name']}】\n该角色没有可切换人格。",
                )
                return
            lines = [f"【人格档案｜{character['name']}】"]
            for persona in personas:
                mark = "▣ 当前" if persona["is_active"] else "□ 可用"
                lines.append(
                    f"\n{mark}「{persona['name']}」\n"
                    f"HP {int(persona['max_hp'])}｜"
                    f"行动 {int(persona['max_actions'])}｜"
                    f"混乱 {int(persona['max_stagger'])}"
                )
                if persona.get("description"):
                    lines.append(f"  {_compact(persona['description'], 180)}")
            await self._reply(update, "\n".join(lines))
        except Exception as exc:
            await self._command_error(update, exc)

    async def skills_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        try:
            if len(context.args) != 1:
                raise ValueError("用法：/skills <核心角色名称或角色编号>，例如 /skills 珏")
            raw = context.args[0].strip()
            if raw.isdecimal():
                character = await asyncio.to_thread(self.engine.get_character, int(raw))
            else:
                character = await asyncio.to_thread(self.engine.get_core_character, raw)
            if character["faction"] == Faction.ENEMY.value:
                raise BattleRuleError(
                    "敌方技能档案只在 /enemy 行动流程的私密弹窗中提供。"
                )
            character_id = int(character["id"])
            skills = await asyncio.to_thread(self.engine.skill_catalog, character_id)
            lines = [f"【技能档案｜{character['name']}】"]
            if not skills:
                lines.append("当前人格没有已登记技能。")
            for skill in skills:
                kind = "E.G.O" if skill["skill_type"] == "EGO" else "普通"
                limits = (
                    ["每场战斗一次"]
                    if skill["skill_type"] == "EGO"
                    else [f"CD {skill['base_cooldown']}"]
                )
                if int(skill["emotion_requirement"]):
                    limits.append(f"情感 {skill['emotion_requirement']}")
                if (
                    skill["skill_type"] != "EGO"
                    and skill.get("max_uses_per_battle") is not None
                ):
                    limits.append(f"每战 {skill['max_uses_per_battle']} 次")
                lines.append(
                    f"\n〔{kind}〕「{skill['name']}」\n"
                    f"  {'｜'.join(limits)}\n  {_compact(skill.get('description', ''), 300)}"
                )
            await self._reply(update, "\n".join(lines))
        except Exception as exc:
            await self._command_error(update, exc)

    async def battle_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        del context
        try:
            status = await asyncio.to_thread(self.engine.battle_status)
            await self._reply(update, self._format_battle(status))
        except Exception as exc:
            await self._command_error(update, exc)

    # ------------------------------------------------------------------
    # Roster and battle lifecycle commands
    # ------------------------------------------------------------------
    async def persona_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        if not await self._require_admin(update):
            return
        try:
            if len(context.args) != 2:
                raise ValueError("用法：/persona <角色编号> <人格键>")
            character_id = int(context.args[0])
            persona_key = context.args[1]
            async with self._mutation_lock:
                await asyncio.to_thread(
                    self.engine.switch_persona, character_id, persona_key
                )
                character = await asyncio.to_thread(
                    self.engine.get_character, character_id
                )
            await self._reply(
                update,
                "【人格覆写完成】\n"
                + self._character_line(character, include_template=True),
            )
        except Exception as exc:
            await self._command_error(update, exc)

    async def spawn_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        if not await self._require_admin(update):
            return
        try:
            if len(context.args) < 2:
                raise ValueError(
                    "用法：/spawn <单位模板键> <friendly|enemy> [角色显示名]"
                )
            template_key, raw_faction = context.args[:2]
            aliases = {
                "friendly": Faction.FRIENDLY,
                "f": Faction.FRIENDLY,
                "我方": Faction.FRIENDLY,
                "enemy": Faction.ENEMY,
                "e": Faction.ENEMY,
                "敌方": Faction.ENEMY,
            }
            faction = aliases.get(raw_faction.lower())
            if faction is None:
                raise ValueError("阵营仅接受 friendly 或 enemy。")
            name = " ".join(context.args[2:]).strip() or None
            async with self._mutation_lock:
                character_id = await asyncio.to_thread(
                    self.engine.spawn_character,
                    template_key,
                    faction,
                    name=name,
                )
                character = await asyncio.to_thread(self.engine.get_character, character_id)
            await self._reply(
                update,
                "【角色记录已建立】\n" + self._character_line(character, include_template=True),
            )
        except Exception as exc:
            await self._command_error(update, exc)

    async def _legacy_stage_start_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        if not await self._require_admin(update):
            return
        try:
            if "--" not in context.args:
                raise ValueError(
                    "用法：/start_stage <我方编号…> -- <敌方编号…>"
                )
            separator = context.args.index("--")
            friendly_ids = _parse_positive_ids(context.args[:separator])
            enemy_ids = _parse_positive_ids(context.args[separator + 1 :])
            if not friendly_ids or not enemy_ids:
                raise ValueError("我方与敌方都至少需要一个角色编号。")
            async with self._mutation_lock:
                messages = await asyncio.to_thread(
                    self.engine.start_stage, friendly_ids, enemy_ids
                )
            await self._reply(update, "\n".join(messages))
        except Exception as exc:
            await self._command_error(update, exc)

    async def _legacy_battle_start_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        if not await self._require_admin(update):
            return
        try:
            if "--" not in context.args:
                raise ValueError(
                    "用法：/battle_start <我方编号…> -- <敌方编号…> "
                    "[stages=N] [abnormalities=键,键]"
                )
            separator = context.args.index("--")
            friendly_ids = _parse_positive_ids(context.args[:separator])
            right = list(context.args[separator + 1 :])
            options: dict[str, str] = {}
            enemy_tokens: list[str] = []
            for token in right:
                if "=" in token:
                    key, value = token.split("=", 1)
                    options[key.lower()] = value
                else:
                    enemy_tokens.append(token)
            enemy_ids = _parse_positive_ids(enemy_tokens)
            if not friendly_ids or not enemy_ids:
                raise ValueError("我方与敌方都至少需要一个角色编号。")
            total_stages = int(options.get("stages", "1"))
            abnormality_raw = options.get(
                "abnormalities", options.get("abnos", "")
            )
            abnormality_keys = [
                item.strip()
                for item in re.split(r"[,，]", abnormality_raw)
                if item.strip()
            ]
            unknown = set(options) - {"stages", "abnormalities", "abnos"}
            if unknown:
                raise ValueError(f"未知开战参数：{', '.join(sorted(unknown))}")
            async with self._mutation_lock:
                battle_id, messages = await asyncio.to_thread(
                    self.engine.start_battle,
                    friendly_ids,
                    enemy_ids,
                    total_stages=total_stages,
                    abnormality_keys=abnormality_keys,
                )
            await self._reply(
                update,
                "\n".join(messages)
                + f"\n\n战斗 #{battle_id} 开始！\n行动权在我方。",
            )
        except Exception as exc:
            await self._command_error(update, exc)

    async def lock_intents_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._require_admin(update):
            return
        try:
            async with self._mutation_lock:
                message = await asyncio.to_thread(self.engine.finish_enemy_planning)
            await self._reply(update, message)
        except Exception as exc:
            await self._command_error(update, exc)

    async def defend_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        try:
            if not context.args or len(context.args) > 2:
                raise BattleRuleError("用法：/defend 角色编号 [敌方指令编号]；拦截与迎击需要指令编号。")
            actor_id = int(context.args[0])
            actor = await asyncio.to_thread(self.engine.get_character, actor_id)
            if not int(actor["is_core"]) and not await self._require_admin(update):
                return
            intent_id = int(context.args[1]) if len(context.args) == 2 else None
            async with self._mutation_lock:
                messages = await asyncio.to_thread(self.engine.declare_defense, actor_id, intent_id)
            await self._reply(update, "\n".join(messages))
        except Exception as exc:
            await self._command_error(update, exc)

    async def end_friendly_phase_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """/pass —— 结束回合（移交行动权）；玩家也可主动发起（2026-07-26 反馈）。"""
        del context
        try:
            async with self._mutation_lock:
                message = await asyncio.to_thread(self.engine.end_friendly_phase)
            await self._reply(update, message)
        except Exception as exc:
            await self._command_error(update, exc)

    async def yield_assists_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """/yield —— 助战让行：放弃助战单位剩余行动，让玩家核心开始行动。"""
        del context
        if not await self._require_admin(update):
            return
        try:
            async with self._mutation_lock:
                messages = await asyncio.to_thread(self.engine.forfeit_assist_actions)
            await self._reply(update, "\n".join(messages))
        except Exception as exc:
            await self._command_error(update, exc)

    async def end_turn_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        del context
        if not await self._require_admin(update):
            return
        try:
            async with self._mutation_lock:
                messages = await asyncio.to_thread(self.engine.end_turn)
            await self._reply(update, "\n".join(messages))
        except Exception as exc:
            await self._command_error(update, exc)

    async def battle_abort_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        if not await self._require_admin(update) or update.effective_user is None:
            return
        try:
            status = await asyncio.to_thread(self.engine.battle_status)
            nonce = self._remember_flow(
                context,
                _STOP_FLOW,
                initiator_id=int(update.effective_user.id),
                chat_id=self._chat_id(update),
                battle_id=int(status["id"]),
            )
            await self._reply(
                update,
                f"【中止确认｜战斗 #{status['id']}】\n"
                "确认后本场战斗会以“记录中止”结束，不能继续行动。",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("确认中止", callback_data=f"dw:b:stop:{nonce}"),
                    InlineKeyboardButton("继续战斗", callback_data=f"dw:b:continue:{nonce}"),
                ]]),
            )
        except Exception as exc:
            await self._command_error(update, exc)

    # New encounter workflow overrides the legacy roster-in-arguments entry points.
    async def battle_start_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        if not await self._require_admin(update):
            return
        del context
        await self._reply(
            update,
            "【旧开战入口已停用】\n战斗现在由关卡容器承载。请依次使用：\n"
            "/encounters → /battle_prepare → /battle_core → /battle_launch",
        )

    async def stage_start_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        if not await self._require_admin(update) or update.effective_user is None:
            return
        try:
            if context.args:
                raise ValueError(
                    "/next 不接收参数；敌人由关卡阶段预设，"
                    "我方阵容请在弹出的按钮中勾选。"
                )
            status = await asyncio.to_thread(self.engine.battle_status)
            candidates = {
                int(row["id"]): str(row["name"])
                for row in status.get("participants", [])
                if row["faction"] == Faction.FRIENDLY.value
                and int(row["current_hp"]) > 0
            }
            if not candidates:
                raise ValueError("没有仍存活的友方角色，无法进入下一阶段。")
            nonce = self._remember_flow(
                context,
                _STAGE_FLOW,
                initiator_id=int(update.effective_user.id),
                chat_id=self._chat_id(update),
                battle_id=int(status["id"]),
                candidates=candidates,
                selected=list(candidates),
            )
            await self._reply(
                update,
                "【下一阶段｜入战选择】\n勾选进入下一阶段的友方（默认全选），"
                "然后点击“进入下一阶段”。",
                reply_markup=self._stage_selection_keyboard(
                    nonce, candidates, list(candidates)
                ),
            )
        except Exception as exc:
            await self._command_error(update, exc)

    @staticmethod
    def _stage_selection_keyboard(
        nonce: str, candidates: dict[int, str], selected: list[int]
    ) -> InlineKeyboardMarkup:
        keyboard = [
            [
                InlineKeyboardButton(
                    f"{'☑' if character_id in selected else '☐'} "
                    f"{name} (#{character_id})",
                    callback_data=f"dw:s:t:{character_id}:{nonce}",
                )
            ]
            for character_id, name in candidates.items()
        ]
        keyboard.append(
            [
                InlineKeyboardButton("进入下一阶段", callback_data=f"dw:s:go:{nonce}"),
                InlineKeyboardButton("取消", callback_data=f"dw:s:x:{nonce}"),
            ]
        )
        return InlineKeyboardMarkup(keyboard)

    async def stage_formation_callback(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        query = update.callback_query
        if query is None or update.effective_user is None:
            return
        if not await self._require_admin(update):
            return
        try:
            parts = str(query.data).split(":")
            action = parts[2]
            nonce = parts[-1]
            flow = self._owned_flow(
                context,
                _STAGE_FLOW,
                nonce=nonce,
                user_id=int(update.effective_user.id),
                chat_id=self._chat_id(update),
            )
            candidates: dict[int, str] = flow["candidates"]
            selected: list[int] = flow["selected"]
            if action == "t":
                character_id = int(parts[3])
                if character_id not in candidates:
                    raise ValueError("该角色不在候选名单中。")
                if character_id in selected:
                    selected.remove(character_id)
                else:
                    selected.append(character_id)
                await query.answer()
                await query.edit_message_reply_markup(
                    reply_markup=self._stage_selection_keyboard(
                        nonce, candidates, selected
                    )
                )
                return
            if action == "x":
                context.user_data.pop(_STAGE_FLOW, None)
                await query.answer("已取消。")
                await self._edit_and_follow_up(
                    query, "【下一阶段】入战选择已取消；再次输入 /next 可重新开始。"
                )
                return
            if not selected:
                await query.answer("至少勾选一名友方才能进入下一阶段。", show_alert=True)
                return
            context.user_data.pop(_STAGE_FLOW, None)
            async with self._mutation_lock:
                messages = await asyncio.to_thread(
                    self.engine.start_prepared_stage, list(selected)
                )
            await query.answer()
            await self._edit_and_follow_up(query, "\n".join(messages))
        except Exception as exc:
            await self._callback_error(query, exc)

    async def gear_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        if not await self._require_admin(update) or update.effective_user is None:
            return
        try:
            if context.args:
                raise ValueError("/gear 不接收参数；请在弹出的按钮中勾选异想体。")
            user_id = int(update.effective_user.id)
            chat_id = self._chat_id(update)
            setup = await asyncio.to_thread(
                self.engine.battle_setup_status, user_id=user_id, chat_id=chat_id
            )
            if setup.get("status") != "STANDBY":
                raise ValueError("只能在战斗触发前装备异想体。")
            abnormalities = await asyncio.to_thread(self.engine.list_abnormalities)
            if not abnormalities:
                await self._reply(
                    update, "【异想体装备】\n当前没有已加载且启用的异想体内容。"
                )
                return
            keys = [str(item["abnormality_key"]) for item in abnormalities]
            labels = {
                str(item["abnormality_key"]): f"{item['name']}（{item['page_count']}页）"
                for item in abnormalities
            }
            equipped = {
                str(key) for key in json.loads(setup.get("abnormalities_json") or "[]")
            }
            selected = [key for key in keys if key in equipped]
            nonce = self._remember_flow(
                context,
                _GEAR_FLOW,
                initiator_id=user_id,
                chat_id=chat_id,
                setup_id=int(setup["id"]),
                keys=keys,
                labels=labels,
                selected=selected,
            )
            await self._reply(
                update,
                f"【异想体装备｜{setup['name']}】\n"
                "勾选本场战斗的异想体；它们的书页会进入战斗书页池，"
                "情感升级时供核心角色 3 选 1。保存后 /ready 需要重新确认。",
                reply_markup=self._gear_keyboard(nonce, keys, labels, selected),
            )
        except Exception as exc:
            await self._command_error(update, exc)

    @staticmethod
    def _gear_keyboard(
        nonce: str, keys: list[str], labels: dict[str, str], selected: list[str]
    ) -> InlineKeyboardMarkup:
        keyboard = [
            [
                InlineKeyboardButton(
                    f"{'☑' if key in selected else '☐'} {labels.get(key, key)}",
                    callback_data=f"dw:g:t:{index}:{nonce}",
                )
            ]
            for index, key in enumerate(keys)
        ]
        keyboard.append(
            [
                InlineKeyboardButton("保存装备", callback_data=f"dw:g:go:{nonce}"),
                InlineKeyboardButton("取消", callback_data=f"dw:g:x:{nonce}"),
            ]
        )
        return InlineKeyboardMarkup(keyboard)

    async def gear_callback(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        query = update.callback_query
        if query is None or update.effective_user is None:
            return
        if not await self._require_admin(update):
            return
        try:
            parts = str(query.data).split(":")
            action = parts[2]
            nonce = parts[-1]
            flow = self._owned_flow(
                context,
                _GEAR_FLOW,
                nonce=nonce,
                user_id=int(update.effective_user.id),
                chat_id=self._chat_id(update),
            )
            keys: list[str] = flow["keys"]
            labels: dict[str, str] = flow["labels"]
            selected: list[str] = flow["selected"]
            if action == "t":
                index = int(parts[3])
                if not 0 <= index < len(keys):
                    raise ValueError("该异想体不在候选列表中。")
                key = keys[index]
                if key in selected:
                    selected.remove(key)
                else:
                    selected.append(key)
                await query.answer()
                await query.edit_message_reply_markup(
                    reply_markup=self._gear_keyboard(nonce, keys, labels, selected)
                )
                return
            if action == "x":
                context.user_data.pop(_GEAR_FLOW, None)
                await query.answer("已取消。")
                await self._edit_and_follow_up(
                    query, "【异想体装备】操作已取消；再次输入 /gear 可重新开始。"
                )
                return
            context.user_data.pop(_GEAR_FLOW, None)
            async with self._mutation_lock:
                saved = await asyncio.to_thread(
                    self.engine.set_setup_abnormalities,
                    list(selected),
                    setup_id=int(flow["setup_id"]),
                )
            await query.answer()
            names = "、".join(labels.get(key, key) for key in saved) or "（无）"
            await self._edit_and_follow_up(
                query,
                f"【异想体装备已保存】\n本场书页池来源：{names}\n"
                "编成已变更，触发战斗前请重新 /ready 确认。",
            )
        except Exception as exc:
            await self._callback_error(query, exc)

    async def help_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        del context
        await self._reply(
            update,
            """【Dewbot｜常用指令】
〔公共指令〕
/roster [friendly|enemy] — 查阅现有角色
/personas <核心角色名或编号> — 查阅人格
/skills <核心角色名或编号> — 查阅技能
/battle — 查阅当前战斗（含各单位状态效果）
/plan — 查看当前选中的战斗编成和阶段结束条件
/attack — 展开我方行动
/pages — 查阅异想体书页（接纳需管理权限）
/whoami — 显示你的 Telegram 用户编号与管理权限状态

〔管理指令〕（需要管理员权限）
/new <名称> — 建立待触发战斗，然后用按钮选择关卡
/battles — 查看等待触发/正在进行的战斗并点选
/use <编号> — 选中一场战斗作为后续操作目标
/team — 勾选核心角色并逐一装备人格
/ally — 用按钮追加普通友方
/foe — 用按钮追加敌人并选择阶段
/gear — 战前装备异想体，决定本场书页池
/ready — 核对阵容后确认触发当前战斗
/discard — 撤销当前选中的待触发战斗（会再次确认）
/identity — 用按钮为核心角色切换战斗外人格
/create [名称] — 用按钮建立可加入编成的普通友方
/next — 勾选我方阵容后进入下一阶段
/lock — 锁定敌方指令并交给玩家〔管理〕
/defend 角色编号 [指令编号] — 发布人格防御指令
/enemy — 设置敌方技能与目标（技能信息仅操作者可见）
/yield — 助战让行（放弃助战剩余行动，轮到玩家核心）〔管理〕
/pass — 结束回合，行动权移交敌方（玩家可用）
/settle — 进行回合结束结算
/stop — 中止当前战斗
/manager — 用按钮查阅并发动经理干预能力
/reload — 重载内容包

日常战斗流程不需要输入 encounter.*、persona.* 或 enemy.* 等内容键。""",
        )

    # ------------------------------------------------------------------
    # Abnormality pages, manager abilities, and content reload
    # ------------------------------------------------------------------
    async def pages_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        try:
            if context.args:
                if not await self._require_admin(update):
                    return
                if not context.args[0].lstrip("#").isdecimal():
                    raise ValueError(
                        "用法：/pages 查看待接纳书页，或 /pages <报价编号> 接纳指定书页。"
                    )
                offer_id = int(context.args[0].lstrip("#"))
                async with self._mutation_lock:
                    message = await asyncio.to_thread(self.engine.choose_page, offer_id)
                await self._reply(update, message)
                return
            offers = await asyncio.to_thread(self.engine.pending_page_offers)
            if not offers:
                await self._reply(
                    update,
                    "【异想体书页】\n当前没有等待处理的书页报价。",
                )
                return
            lines = ["【异想体书页｜待接纳记录】"]
            keyboard: list[list[InlineKeyboardButton]] = []
            for offer in offers:
                page_type = "觉醒" if offer["page_type"] == "AWAKENING" else "崩溃"
                lines.append(
                    f"\n#{offer['id']}  {offer['character_name']}\n"
                    f"〔{page_type}〕「{offer['name']}」\n"
                    f"  {_compact(offer.get('description', ''), 220)}"
                )
                keyboard.append(
                    [
                        InlineKeyboardButton(
                            f"#{offer['id']} · {offer['character_name']} · {offer['name']}",
                            callback_data=f"dw:p:{offer['id']}",
                        )
                    ]
                )
            await self._reply(
                update,
                "\n".join(lines),
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
        except Exception as exc:
            await self._command_error(update, exc)

    async def page_callback(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        del context
        query = update.callback_query
        if query is None:
            return
        if not await self._require_admin(update):
            return
        try:
            offer_id = int(str(query.data).rsplit(":", 1)[1])
            async with self._mutation_lock:
                message = await asyncio.to_thread(self.engine.choose_page, offer_id)
            await query.answer("书页已接纳。")
            await self._edit_and_follow_up(query, message)
        except Exception as exc:
            await self._callback_error(query, exc)

    async def manager_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        if not await self._require_admin(update) or update.effective_user is None:
            return
        try:
            if context.args:
                raise ValueError("/manager 不再需要能力键；请直接点击能力按钮。")
            skills = await asyncio.to_thread(self._available_manager_skills)
            if not skills:
                await self._reply(
                    update,
                    "【管理人权限树】\n没有已解锁的干预能力，或当前尚无战斗记录。",
                )
                return
            choices = {
                str(index): skill["manager_skill_key"]
                for index, skill in enumerate(skills)
            }
            nonce = self._remember_flow(
                context,
                _MANAGER_FLOW,
                initiator_id=int(update.effective_user.id),
                chat_id=self._chat_id(update),
                choices=choices,
            )
            lines = ["【管理人权限树｜可发动记录】"]
            keyboard: list[list[InlineKeyboardButton]] = []
            for index, skill in enumerate(skills):
                phase = (
                    PHASE_LABELS.get(skill["allowed_phase"], skill["allowed_phase"])
                    if skill.get("allowed_phase")
                    else "任意合法窗口"
                )
                remain = max(
                    0,
                    int(skill["max_uses_per_battle"])
                    - int(skill.get("uses", 0)),
                )
                lines.append(
                    f"\n「{skill['name']}」\n"
                    f"窗口：{phase}｜剩余额度：{remain}\n"
                    f"  {_compact(skill.get('description', ''), 180)}"
                )
                keyboard.append([InlineKeyboardButton(
                    f"发动｜{skill['name']}", callback_data=f"dw:m:{nonce}.{index}"
                )])
            await self._reply(
                update, "\n".join(lines), reply_markup=InlineKeyboardMarkup(keyboard)
            )
        except Exception as exc:
            await self._command_error(update, exc)

    async def manager_callback(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        query = update.callback_query
        if query is None or not await self._require_admin(update) or update.effective_user is None:
            return
        try:
            value = str(query.data or "").removeprefix("dw:m:")
            nonce, choice = value.split(".", 1)
            flow = self._owned_flow(
                context,
                _MANAGER_FLOW,
                nonce=nonce,
                user_id=int(update.effective_user.id),
                chat_id=self._chat_id(update),
            )
            manager_key = flow["choices"].get(choice)
            if manager_key is None:
                raise BattleRuleError("该管理人能力选项已经失效。")
            async with self._mutation_lock:
                messages = await asyncio.to_thread(
                    self.engine.use_manager_skill, manager_key
                )
            context.user_data.pop(_MANAGER_FLOW, None)
            await query.answer("能力已发动。")
            await self._edit_and_follow_up(query, "\n".join(messages))
        except Exception as exc:
            await self._callback_error(query, exc)

    async def reload_content_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        del context
        if not await self._require_admin(update):
            return
        try:
            paths = self._content_files()
            if not paths:
                raise ValueError("Settings.content_paths 中没有可重载的 JSON 内容包。")
            results: list[tuple[Path, Any]] = []
            async with self._mutation_lock:
                for path in paths:
                    result = await asyncio.to_thread(self.loader.load_path, path)
                    results.append((path, result))
                await asyncio.to_thread(self.engine.validate_content_handlers)
            lines = ["【内容档案重载完成】"]
            for path, result in results:
                lines.append(
                    f"\n{path.name} → {result.pack_key} v{result.version}\n"
                    f"核心角色 {result.core_characters}｜生成模板 {result.characters}｜"
                    f"人格 {result.personas}｜技能 {result.skills}｜"
                    f"行为 {result.behaviors}｜书页 {result.pages}｜管理能力 {result.manager_skills}"
                )
            await self._reply(update, "\n".join(lines))
        except Exception as exc:
            await self._command_error(update, exc)

    # ------------------------------------------------------------------
    # Inline attack flow
    # ------------------------------------------------------------------
    async def attack_start(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> int:
        return await self._attack_start(update, context, "f")

    async def enemy_start(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> int:
        if not await self._require_admin(update):
            return ConversationHandler.END
        return await self._attack_start(update, context, "e")

    async def _attack_start(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        side: str,
    ) -> int:
        try:
            status = await asyncio.to_thread(self.engine.battle_status)
            expected = _expected_phase(side)
            if status["phase"] != expected.value:
                stage_end_hint = (
                    "\n请管理员使用 /next 进入下一阶段。"
                    if status["phase"] == BattlePhase.STAGE_END.value
                    else ""
                )
                raise BattleRuleError(
                    f"当前阶段为{PHASE_LABELS.get(status['phase'], status['phase'])}；"
                    f"该流程只在{PHASE_LABELS[expected.value]}开放。{stage_end_hint}"
                )
            actors = self._actionable_participants(status, _side_faction(side))
            if not actors:
                next_hint = (
                    "使用 /pass 移交行动权。"
                    if side == "f"
                    else "使用 /settle 进入统一清算。"
                )
                await self._reply(
                    update,
                    f"【行动记录】\n当前没有可行动的{'我方' if side == 'f' else '敌方'}单位。\n{next_hint}",
                )
                return ConversationHandler.END
            flow = {
                "side": side,
                "nonce": secrets.token_urlsafe(4),
                "initiator_id": int(update.effective_user.id),
                "chat_id": self._chat_id(update),
                "created_at": time.time(),
                "battle_id": int(status["id"]),
                "state": SELECTING_ACTOR,
                "actor_id": None,
                "skill_id": None,
                "skill_number": None,
                "skill_ids": [],
            }
            context.user_data[_flow_key(side)] = flow
            keyboard = [
                [
                    InlineKeyboardButton(
                        f"#{row['id']} {row['name']} · HP {row['current_hp']}/{row['max_hp']} · "
                        f"行动 {row['current_actions']}/{row['max_actions']}",
                        callback_data=f"{_ATTACK_PREFIX}:{side}:a:{flow['nonce']}.{row['id']}",
                    )
                ]
                for row in actors
            ]
            keyboard.append([self._cancel_button(side, flow["nonce"])])
            title = "我方行动档案" if side == "f" else "敌方行动档案｜受限操作"
            await self._reply(
                update,
                f"【{title}】\n选择本次行动的执行者。",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
            return SELECTING_ACTOR
        except Exception as exc:
            await self._command_error(update, exc)
            return ConversationHandler.END

    async def friendly_actor_callback(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> int:
        return await self._actor_callback(update, context, "f")

    async def enemy_actor_callback(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> int:
        return await self._actor_callback(update, context, "e")

    async def _actor_callback(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, side: str
    ) -> int:
        query = update.callback_query
        if query is None:
            return ConversationHandler.END
        try:
            flow, status = await self._validated_flow(update, context, side)
            actor_id = int(str(query.data).rsplit(".", 1)[1])
            actors = self._actionable_participants(status, _side_faction(side))
            actor = next((row for row in actors if int(row["id"]) == actor_id), None)
            if actor is None:
                raise BattleRuleError("该执行者已不具备行动资格。")
            skills = await asyncio.to_thread(
                self.engine.list_skills, actor_id, available_only=True
            )
            if not skills:
                raise BattleRuleError("该执行者当前没有可用技能。")
            flow["actor_id"] = actor_id
            flow["skill_ids"] = [int(skill["id"]) for skill in skills]
            flow["state"] = SELECTING_SKILL
            keyboard: list[list[InlineKeyboardButton]] = []
            if side == "e":
                private_catalog = self._enemy_private_catalog(skills)
                await query.answer(private_catalog, show_alert=True)
                for index, skill in enumerate(skills, start=1):
                    keyboard.append(
                        [
                            InlineKeyboardButton(
                                f"技能 {index:02d}",
                                callback_data=f"{_ATTACK_PREFIX}:{side}:s:{flow['nonce']}.{skill['id']}",
                            )
                        ]
                    )
                prompt = (
                    f"【敌方行动档案｜技能情报封锁】\n执行者：{actor['name']}\n"
                    "技能摘要已通过私密弹窗交付操作者。公共记录仅保留技能编号。"
                )
            else:
                await query.answer()
                for skill in skills:
                    kind = "E.G.O" if skill["skill_type"] == "EGO" else "技能"
                    keyboard.append(
                        [
                            InlineKeyboardButton(
                                f"〔{kind}〕{skill['name']}",
                                callback_data=f"{_ATTACK_PREFIX}:{side}:s:{flow['nonce']}.{skill['id']}",
                            )
                        ]
                    )
                prompt = f"【我方行动档案】\n执行者：{actor['name']}\n选择展开的技能。"
            keyboard.append([self._cancel_button(side, flow["nonce"])])
            await query.edit_message_text(prompt, reply_markup=InlineKeyboardMarkup(keyboard))
            return SELECTING_SKILL
        except StaleFlowError as exc:
            await query.answer(_compact(exc, _CALLBACK_ALERT_LIMIT), show_alert=True)
            return self._attack_flow_state(context, side)
        except Exception as exc:
            return await self._callback_error(query, exc)

    async def friendly_skill_callback(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> int:
        return await self._skill_callback(update, context, "f")

    async def enemy_skill_callback(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> int:
        return await self._skill_callback(update, context, "e")

    async def _skill_callback(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, side: str
    ) -> int:
        query = update.callback_query
        if query is None:
            return ConversationHandler.END
        try:
            flow, _ = await self._validated_flow(update, context, side)
            actor_id = int(flow["actor_id"])
            skill_id = int(str(query.data).rsplit(".", 1)[1])
            skills = await asyncio.to_thread(
                self.engine.list_skills, actor_id, available_only=True
            )
            available = {int(skill["id"]): skill for skill in skills}
            if skill_id not in available or skill_id not in flow["skill_ids"]:
                raise BattleRuleError("该技能已不可用，请重新发起行动流程。")
            skill = available[skill_id]
            flow["skill_id"] = skill_id
            skill_number = flow["skill_ids"].index(skill_id) + 1
            flow["skill_number"] = skill_number
            if side == "e":
                await query.answer(
                    _compact(
                        f"技能 {skill_number:02d}｜{skill['name']}\n"
                        f"{skill.get('description', '')}",
                        _CALLBACK_ALERT_LIMIT,
                    ),
                    show_alert=True,
                )
            else:
                await query.answer()
            flow["state"] = SELECTING_TARGET
            if skill["target_method"] != "SELECT_TARGET":
                label = "确认展开 E.G.O" if skill["skill_type"] == "EGO" else "确认使用技能"
                keyboard = [
                    [InlineKeyboardButton(
                        label,
                        callback_data=f"{_ATTACK_PREFIX}:{side}:t:{flow['nonce']}.0",
                    )],
                    [self._cancel_button(side, flow["nonce"])],
                ]
                public_name = (
                    f"技能 {skill_number:02d}" if side == "e" else f"「{skill['name']}」"
                )
                await query.edit_message_text(
                    f"【行动确认】\n{public_name} 将立即结算。确认后无法撤回。",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                )
                return SELECTING_TARGET
            targets = await asyncio.to_thread(
                self.engine.legal_targets, actor_id, skill_id
            )
            if not targets:
                raise BattleRuleError("该技能当前没有合法接收对象。")
            keyboard = [
                [
                    InlineKeyboardButton(
                        f"#{target['id']} {target['name']} · HP {target['current_hp']}/{target['max_hp']}",
                        callback_data=f"{_ATTACK_PREFIX}:{side}:t:{flow['nonce']}.{target['id']}",
                    )
                ]
                for target in targets
            ]
            keyboard.append([self._cancel_button(side, flow["nonce"])])
            if side == "e":
                prompt = (
                    f"【敌方行动档案】\n执行者："
                    f"{self._participant_name(await asyncio.to_thread(self.engine.battle_status), actor_id)}\n"
                    f"已指定技能 {skill_number:02d}。选择接收对象。"
                )
            else:
                prompt = f"【目标指定】\n「{skill['name']}」将由下列对象之一接收。"
            await query.edit_message_text(prompt, reply_markup=InlineKeyboardMarkup(keyboard))
            return SELECTING_TARGET
        except StaleFlowError as exc:
            await query.answer(_compact(exc, _CALLBACK_ALERT_LIMIT), show_alert=True)
            return self._attack_flow_state(context, side)
        except Exception as exc:
            return await self._callback_error(query, exc)

    async def friendly_target_callback(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> int:
        return await self._target_callback(update, context, "f")

    async def enemy_target_callback(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> int:
        return await self._target_callback(update, context, "e")

    async def _target_callback(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, side: str
    ) -> int:
        query = update.callback_query
        if query is None:
            return ConversationHandler.END
        try:
            flow, _ = await self._validated_flow(update, context, side)
            target_id = int(str(query.data).rsplit(".", 1)[1])
            if target_id == 0:
                skills = await asyncio.to_thread(
                    self.engine.list_skills, int(flow["actor_id"]), available_only=True
                )
                selected = next(
                    (item for item in skills if int(item["id"]) == int(flow["skill_id"])),
                    None,
                )
                if selected is None or selected["target_method"] == "SELECT_TARGET":
                    raise BattleRuleError("该技能确认记录已经失效，请重新发起行动流程。")
                await query.answer("行动已确认。")
                return await self._execute_selected(update, context, side, [])
            legal = await asyncio.to_thread(
                self.engine.legal_targets,
                int(flow["actor_id"]),
                int(flow["skill_id"]),
            )
            if target_id not in {int(row["id"]) for row in legal}:
                raise BattleRuleError("目标状态已经变化，请重新发起行动流程。")
            await query.answer()
            return await self._execute_selected(update, context, side, [target_id])
        except StaleFlowError as exc:
            await query.answer(_compact(exc, _CALLBACK_ALERT_LIMIT), show_alert=True)
            return self._attack_flow_state(context, side)
        except Exception as exc:
            return await self._callback_error(query, exc)

    async def _execute_selected(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        side: str,
        target_ids: list[int],
    ) -> int:
        query = update.callback_query
        if query is None:
            return ConversationHandler.END
        try:
            flow, _ = await self._validated_flow(update, context, side)
            async with self._mutation_lock:
                # The phase may have changed while this callback waited for a
                # concurrent write. Revalidate under the adapter mutation lock.
                await self._validated_flow(update, context, side)
                result = await asyncio.to_thread(
                    self.engine.use_skill,
                    int(flow["actor_id"]),
                    int(flow["skill_id"]),
                    target_ids,
                )
            context.user_data.pop(_flow_key(side), None)
            await self._edit_and_follow_up(query, result.text)
            return ConversationHandler.END
        except StaleFlowError as exc:
            await query.answer(_compact(exc, _CALLBACK_ALERT_LIMIT), show_alert=True)
            return self._attack_flow_state(context, side)
        except Exception as exc:
            context.user_data.pop(_flow_key(side), None)
            return await self._callback_error(query, exc)

    async def cancel_friendly(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> int:
        return await self._cancel_flow(update, context, "f")

    async def cancel_enemy(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> int:
        return await self._cancel_flow(update, context, "e")

    async def _cancel_flow(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, side: str
    ) -> int:
        query = update.callback_query
        flow = context.user_data.get(_flow_key(side))
        if query is not None and flow is not None:
            current_state = self._attack_flow_state(context, side)
            if (
                int(query.from_user.id) != int(flow.get("initiator_id", -1))
                or self._chat_id(update) != int(flow.get("chat_id", 0))
            ):
                await query.answer("该界面不属于当前操作者。", show_alert=True)
                return current_state
            callback_nonce = str(query.data or "").rsplit(":", 1)[-1]
            if (
                callback_nonce != str(flow.get("nonce", ""))
                or time.time() - float(flow.get("created_at", 0)) > _FLOW_TTL_SECONDS
            ):
                await query.answer("这组按钮已经失效。", show_alert=True)
                return current_state
            await query.answer("行动流程已撤销。")
            await self._edit_and_follow_up(query, "【行动撤销】\n本次选择未写入战斗记录。")
        elif update.effective_message is not None:
            await self._reply(update, "【行动撤销】\n本次选择未写入战斗记录。")
        context.user_data.pop(_flow_key(side), None)
        return ConversationHandler.END

    @staticmethod
    def _attack_flow_state(
        context: ContextTypes.DEFAULT_TYPE, side: str
    ) -> int:
        flow = context.user_data.get(_flow_key(side))
        if isinstance(flow, dict):
            state = int(flow.get("state", SELECTING_ACTOR))
            if state in {SELECTING_ACTOR, SELECTING_SKILL, SELECTING_TARGET}:
                return state
        return SELECTING_ACTOR

    async def stale_attack_callback(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        del context
        query = update.callback_query
        if query is not None:
            await query.answer(
                "该行动界面已失效，或不属于当前操作者。", show_alert=True
            )

    async def _validated_flow(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        side: str,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        flow = context.user_data.get(_flow_key(side))
        if not isinstance(flow, dict):
            raise StaleFlowError("行动界面已经失效。")
        user = update.effective_user
        if user is None or int(user.id) != int(flow.get("initiator_id", -1)):
            raise StaleFlowError("该行动界面不属于当前操作者。")
        if self._chat_id(update) != int(flow.get("chat_id", 0)):
            raise StaleFlowError("该行动界面属于另一段会话。")
        if time.time() - float(flow.get("created_at", 0)) > _FLOW_TTL_SECONDS:
            raise StaleFlowError("该行动界面已经超时，请重新发起行动流程。")
        if update.callback_query is not None:
            callback_value = str(update.callback_query.data or "").rsplit(":", 1)[-1]
            callback_nonce = callback_value.split(".", 1)[0]
            if callback_nonce != str(flow.get("nonce", "")):
                raise StaleFlowError("这组行动按钮已经失效，请重新发起行动流程。")
        if side == "e" and not self._is_admin(update):
            raise BattleRuleError("敌方行动需要管理人权限。")
        status = await asyncio.to_thread(self.engine.battle_status)
        if int(status["id"]) != int(flow.get("battle_id", -1)):
            raise StaleFlowError("战斗档案已经更替，请重新发起行动流程。")
        expected = _expected_phase(side)
        if status["phase"] != expected.value:
            raise BattleRuleError(
                f"行动阶段已经变更为{PHASE_LABELS.get(status['phase'], status['phase'])}。"
            )
        return flow, status

    # ------------------------------------------------------------------
    # Formatting and database-backed adapter queries
    # ------------------------------------------------------------------
    @staticmethod
    def _actionable_participants(
        status: dict[str, Any], faction: Faction
    ) -> list[dict[str, Any]]:
        return [
            row
            for row in status.get("participants", [])
            if row["faction"] == faction.value
            and int(row.get("active_in_stage", 0)) == 1
            and int(row["current_hp"]) > 0
            and int(row["current_actions"]) > 0
            and not int(row["is_staggered"])
        ]

    @staticmethod
    def _participant_name(status: dict[str, Any], character_id: int) -> str:
        for row in status.get("participants", []):
            if int(row["id"]) == int(character_id):
                return str(row["name"])
        return f"#{character_id}"

    @staticmethod
    def _cancel_button(side: str, nonce: str) -> InlineKeyboardButton:
        return InlineKeyboardButton(
            "撤销本次行动", callback_data=f"{_ATTACK_PREFIX}:{side}:x:{nonce}"
        )

    @staticmethod
    def _enemy_private_catalog(skills: Sequence[dict[str, Any]]) -> str:
        lines = ["受限技能摘要"]
        for index, skill in enumerate(skills, start=1):
            kind = "E.G.O" if skill["skill_type"] == "EGO" else "技能"
            description = _compact(skill.get("description", ""), 55)
            line = f"{index:02d}. [{kind}] {skill['name']}"
            if description:
                line += f"｜{description}"
            lines.append(line)
        return _compact("\n".join(lines), _CALLBACK_ALERT_LIMIT)

    @staticmethod
    def _character_line(
        character: dict[str, Any], *, include_template: bool = False
    ) -> str:
        if int(character["current_hp"]) <= 0:
            mark = "×"
        elif int(character.get("is_staggered", 0)):
            mark = "◇"
        else:
            mark = "□"
        if include_template:
            if character.get("is_core"):
                suffix = " · 核心角色"
            else:
                suffix = " · 普通角色"
        else:
            suffix = ""
        return (
            f"{mark} #{character['id']} {character['name']}{suffix}\n"
            f"  HP {character['current_hp']}/{character['max_hp']}｜"
            f"行动 {character['current_actions']}/{character['max_actions']}｜"
            f"混乱 {character['current_stagger']}/{character['max_stagger']}｜"
            f"情感 {character['emotion_level']}"
        )

    def _format_battle(self, status: dict[str, Any]) -> str:
        phase = PHASE_LABELS.get(status["phase"], status["phase"])
        battle_name = str(status.get("name") or "").strip()
        title = f"【{battle_name}｜战斗档案 #{status['id']}】" if battle_name else f"【战斗档案 #{status['id']}】"
        lines = [
            title,
            f"阶段 {status['current_stage']}/{status['total_stages']}｜"
            f"回合 {status['current_turn']}｜当前：{phase}",
        ]
        for intent in status.get("enemy_intents", []):
            lines.append(f"{intent['actor_name']} · {intent['skill_name']} → " + "、".join(intent.get("effective_target_names", intent["target_names"])) + (f"（被{intent['redirect']['actor_name']}{intent['redirect']['label']}）" if intent.get("redirect") else "") + ("〔已混乱或倒下，将取消〕" if intent["disabled"] else ""))
            if intent.get("additional_target_names"):
                lines.append("  附加目标：" + "、".join(intent["additional_target_names"]))
        for defense in status.get("defenses", []):
            lines.append(f"防御：角色 #{defense['actor_id']} · {defense['kind']}" + (f" → 指令 #{defense['intent_id']}" if defense['intent_id'] else ""))
        for faction, title in (
            (Faction.FRIENDLY.value, "我方记录"),
            (Faction.ENEMY.value, "敌方记录"),
        ):
            rows = [
                row
                for row in status.get("participants", [])
                if row["faction"] == faction and int(row.get("active_in_stage", 0)) == 1
            ]
            lines.append(f"\n▣ {title}")
            if rows:
                for row in rows:
                    lines.append(self._character_line(row))
                    lines.extend(self._effect_summary(row))
            else:
                lines.append("（当前阶段无单位）")
        return "\n".join(lines)

    @staticmethod
    def _effect_summary(character: dict[str, Any]) -> list[str]:
        """Render a participant's live effects for /battle (audit id=8)."""
        lines: list[str] = []
        parts: list[str] = []
        for effect in character.get("effects") or []:
            name = str(
                effect.get("effect_name") or effect.get("effect_key") or "?"
            ).strip()
            params = effect.get("params") or {}
            if effect.get("category") == "SPECIAL" and "amount" in params:
                parts.append(f"{name}{params['amount']}")
                continue
            text = name
            intensity = int(effect.get("intensity") or 0)
            stacks = int(effect.get("stacks") or 0)
            if intensity:
                text += str(intensity)
            if stacks:
                text += f"×{stacks}"
            remaining = effect.get("remaining_turns")
            if remaining is not None:
                text += f"〔余{remaining}回合〕"
            parts.append(text)
        if parts:
            lines.append("  效果：" + "｜".join(parts))
        pending = [
            str(effect.get("effect_name") or effect.get("effect_key") or "?").strip()
            + (str(effect["intensity"]) if int(effect.get("intensity") or 0) else "")
            for effect in character.get("pending_effects") or []
        ]
        if pending:
            lines.append("  下回合：" + "｜".join(pending))
        return lines

    def _available_manager_skills(self) -> list[dict[str, Any]]:
        with self.engine.database.reading() as connection:
            battle = connection.execute(
                "SELECT id FROM battles WHERE status='ACTIVE'"
            ).fetchone()
            if battle is None:
                return []
            rows = connection.execute(
                """
                SELECT m.*,COALESCE(u.uses,0) AS uses
                FROM manager_skills m
                LEFT JOIN manager_unlocks unlock ON unlock.unlock_key=m.unlock_key
                LEFT JOIN manager_skill_usage u
                    ON u.manager_skill_id=m.id AND u.battle_id=?
                WHERE m.enabled=1 AND (m.unlock_key IS NULL OR m.unlock_key='' OR unlock.unlock_key IS NOT NULL)
                  AND (m.allowed_phase IS NULL OR m.allowed_phase=(
                      SELECT phase FROM battles WHERE id=?
                  ))
                  AND COALESCE(u.uses,0) < m.max_uses_per_battle
                ORDER BY m.id
                """,
                (battle["id"], battle["id"]),
            ).fetchall()
            return [dict(row) for row in rows]

    def _content_files(self) -> list[Path]:
        return _expand_content_paths(self.settings.content_paths)


def _attack_conversation(
    adapter: TelegramBattleAdapter,
    side: str,
) -> ConversationHandler:
    if side == "f":
        entry = adapter.attack_start
        actor = adapter.friendly_actor_callback
        skill = adapter.friendly_skill_callback
        target = adapter.friendly_target_callback
        cancel = adapter.cancel_friendly
        command = "attack"
        name = "dewbot_friendly_attack"
    else:
        entry = adapter.enemy_start
        actor = adapter.enemy_actor_callback
        skill = adapter.enemy_skill_callback
        target = adapter.enemy_target_callback
        cancel = adapter.cancel_enemy
        command = "enemy"
        name = "dewbot_enemy_attack"
    prefix = re.escape(f"{_ATTACK_PREFIX}:{side}")
    # The flow deliberately follows a user across the command message and its
    # callback message, so per_message=False is required. PTB emits a generic
    # advisory for this valid shape; ownership is independently revalidated on
    # every callback by _validated_flow.
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message=r"If 'per_message=False'.*",
            category=PTBUserWarning,
        )
        return ConversationHandler(
            entry_points=[CommandHandler(command, entry)],
            states={
                SELECTING_ACTOR: [
                    CallbackQueryHandler(
                        actor, pattern=rf"^{prefix}:a:[A-Za-z0-9_-]+\.\d+$"
                    )
                ],
                SELECTING_SKILL: [
                    CallbackQueryHandler(
                        skill, pattern=rf"^{prefix}:s:[A-Za-z0-9_-]+\.\d+$"
                    )
                ],
                SELECTING_TARGET: [
                    CallbackQueryHandler(
                        target, pattern=rf"^{prefix}:t:[A-Za-z0-9_-]+\.\d+$"
                    )
                ],
            },
            fallbacks=[
                CommandHandler("cancel", cancel),
                CallbackQueryHandler(
                    cancel, pattern=rf"^{prefix}:x:[A-Za-z0-9_-]+$"
                ),
            ],
            allow_reentry=True,
            name=name,
            per_chat=True,
            per_user=True,
            per_message=False,
        )


async def _register_bot_commands(application: Application) -> None:
    """Publish the short, human-facing command menu after Telegram connects."""
    commands = [
        BotCommand("start", "显示系统状态与入门提示"),
        BotCommand("help", "查看指令与战斗流程"),
        BotCommand("whoami", "显示用户编号与管理权限"),
        BotCommand("roster", "查看现有角色"),
        BotCommand("personas", "查看核心角色人格"),
        BotCommand("skills", "查看我方技能档案"),
        BotCommand("new", "建立一场等待触发的战斗"),
        BotCommand("battles", "查看并选择战斗"),
        BotCommand("use", "按编号选中战斗"),
        BotCommand("plan", "查看当前战斗编成"),
        BotCommand("team", "选择核心角色与人格"),
        BotCommand("ally", "追加普通友方"),
        BotCommand("foe", "追加或移除敌方编成"),
        BotCommand("gear", "战前装备异想体"),
        BotCommand("ready", "确认触发战斗"),
        BotCommand("discard", "撤销待触发战斗"),
        BotCommand("identity", "切换战斗外人格"),
        BotCommand("create", "建立普通友方"),
        BotCommand("attack", "展开我方行动"),
        BotCommand("enemy", "展开敌方行动"),
        BotCommand("pass", "移交敌方行动权"),
        BotCommand("settle", "执行回合结束结算"),
        BotCommand("next", "进入下一阶段"),
        BotCommand("battle", "查看当前战斗"),
        BotCommand("pages", "查看异想体书页"),
        BotCommand("manager", "查看管理人能力"),
        BotCommand("stop", "确认中止当前战斗"),
        BotCommand("reload", "重新载入内容包"),
        BotCommand("privacy", "查看或切换 AI 隐私模式"),
    ]
    if application.bot_data.get("story_store") is not None:
        commands.append(BotCommand("notes", "查看已解锁的但丁笔记"))
    await application.bot.set_my_commands(commands)


def create_application(
    settings: SettingsLike,
    engine: BattleEngine | None = None,
    loader: ContentLoader | None = None,
) -> Application:
    """Build a configured Telegram application without module-import effects.

    Dependency injection keeps the transport independently testable. If no
    engine is supplied, the factory initializes the configured SQLite schema;
    loading content remains explicit through the caller or ``/reload_content``.
    """
    token = (settings.telegram_token or "").strip()
    if not token:
        raise ValueError("TELEGRAM_TOKEN 未配置，无法建立 Telegram Application。")

    if engine is None:
        database = Database(settings.database_path)
        database.initialize()
        engine = BattleEngine(database)
    if loader is None:
        loader = ContentLoader(engine.database, engine.registry.keys)

    builder = Application.builder().token(token).post_init(_register_bot_commands)
    if settings.telegram_proxy:
        request = HTTPXRequest(
            connection_pool_size=16,
            connect_timeout=20,
            read_timeout=30,
            write_timeout=30,
            pool_timeout=10,
            proxy=settings.telegram_proxy,
        )
        polling_request = HTTPXRequest(
            connection_pool_size=4,
            connect_timeout=20,
            read_timeout=40,
            write_timeout=30,
            pool_timeout=10,
            proxy=settings.telegram_proxy,
        )
        builder = builder.request(request).get_updates_request(polling_request)
    application = builder.build()
    adapter = TelegramBattleAdapter(settings, engine, loader)

    application.bot_data["settings"] = settings
    application.bot_data["battle_engine"] = engine
    application.bot_data["content_loader"] = loader
    application.bot_data["telegram_adapter"] = adapter

    from .assistant import PrivacyStore
    from .assistant_telegram import PrivacyTelegramAdapter

    privacy_adapter = PrivacyTelegramAdapter(PrivacyStore(engine.database), settings.admin_ids)
    application.add_handler(CommandHandler("privacy", privacy_adapter.privacy_command))

    from .story import open_story_store

    story_store = open_story_store(settings)
    if story_store is not None:
        from .story_telegram import StoryTelegramAdapter

        story_adapter = StoryTelegramAdapter(story_store, settings.admin_ids)
        application.bot_data["story_store"] = story_store
        application.add_handler(CommandHandler("story", story_adapter.story_command))
        application.add_handler(CommandHandler("notes", story_adapter.story_command))

    application.add_handler(CommandHandler("start", adapter.start_command))
    application.add_handler(CommandHandler("help", adapter.help_command))
    application.add_handler(CommandHandler("whoami", adapter.whoami_command))
    application.add_handler(CommandHandler("roster", adapter.roster_command))
    application.add_handler(CommandHandler("personas", adapter.personas_command))
    application.add_handler(CommandHandler("skills", adapter.skills_command))
    application.add_handler(CommandHandler("new", adapter.new_battle_command))
    application.add_handler(CommandHandler("battles", adapter.battles_command))
    application.add_handler(CommandHandler("use", adapter.use_battle_command))
    application.add_handler(CommandHandler("team", adapter.team_command))
    application.add_handler(CommandHandler("ally", adapter.ally_command))
    application.add_handler(CommandHandler("foe", adapter.foe_command))
    application.add_handler(CommandHandler("ready", adapter.ready_command))
    application.add_handler(CommandHandler("discard", adapter.discard_command))
    application.add_handler(CommandHandler("identity", adapter.identity_command))
    application.add_handler(CommandHandler("create", adapter.create_unit_command))
    application.add_handler(
        CallbackQueryHandler(adapter.battle_formation_callback, pattern=r"^dw:b:")
    )
    application.add_handler(
        CallbackQueryHandler(adapter.human_content_callback, pattern=r"^dw:h:")
    )
    application.add_handler(CommandHandler("plan", adapter.battle_setup_command))
    application.add_handler(
        CallbackQueryHandler(adapter.core_formation_callback, pattern=r"^dw:c:")
    )
    application.add_handler(CommandHandler("next", adapter.stage_start_command))
    application.add_handler(
        CallbackQueryHandler(adapter.stage_formation_callback, pattern=r"^dw:s:")
    )
    application.add_handler(CommandHandler("gear", adapter.gear_command))
    application.add_handler(
        CallbackQueryHandler(adapter.gear_callback, pattern=r"^dw:g:")
    )
    application.add_handler(CommandHandler("battle", adapter.battle_command))
    application.add_handler(CommandHandler("lock", adapter.lock_intents_command))
    application.add_handler(CommandHandler("defend", adapter.defend_command))
    application.add_handler(_attack_conversation(adapter, "f"))
    application.add_handler(_attack_conversation(adapter, "e"))
    application.add_handler(
        CommandHandler("pass", adapter.end_friendly_phase_command)
    )
    application.add_handler(
        CommandHandler("yield", adapter.yield_assists_command)
    )
    # Keep /end_turn as a compatibility alias because todo.txt names this
    # authoritative transition explicitly; /settle is the human-facing menu entry.
    application.add_handler(
        CommandHandler(["settle", "end_turn"], adapter.end_turn_command)
    )
    application.add_handler(
        CommandHandler("stop", adapter.battle_abort_command)
    )
    application.add_handler(CommandHandler("pages", adapter.pages_command))
    application.add_handler(
        CallbackQueryHandler(adapter.page_callback, pattern=r"^dw:p:\d+$")
    )
    application.add_handler(CommandHandler("manager", adapter.manager_command))
    application.add_handler(
        CallbackQueryHandler(adapter.manager_callback, pattern=r"^dw:m:")
    )
    application.add_handler(
        CommandHandler("reload", adapter.reload_content_command)
    )
    application.add_handler(
        CallbackQueryHandler(adapter.stale_attack_callback, pattern=r"^dw:a:")
    )
    application.add_error_handler(adapter.error_handler)
    return application


def main() -> None:
    """Initialize content and start long polling; safe to import without effects."""
    from .config import Settings

    logging.basicConfig(
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        level=logging.INFO,
    )
    # HTTP request URLs can contain the bot token; keep transport logs out of
    # normal INFO output even when third-party logging defaults change.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("telegram.request").setLevel(logging.WARNING)
    settings = Settings.from_env()
    if not settings.admin_ids:
        LOGGER.warning(
            "DEWBOT_ADMIN_IDS is empty. The bot will start in read-only mode; "
            "use /whoami to obtain a Telegram user id, configure it, then restart."
        )
    database = Database(settings.database_path)
    database.initialize()
    engine = BattleEngine(database)
    loader = ContentLoader(database, engine.registry.keys)
    content_files = _expand_content_paths(settings.content_paths)
    if not content_files:
        raise RuntimeError("未找到可加载的 JSON 内容包，请检查 DEWBOT_CONTENT_PATHS。")
    for path in content_files:
        result = loader.load_path(path)
        LOGGER.info("Loaded content pack %s v%s from %s", result.pack_key, result.version, path)
    engine.validate_content_handlers()
    application = create_application(settings, engine=engine, loader=loader)
    from .runlock import FrontendLock, FrontendLockError

    # Two frontends share one database but must not run concurrently: the
    # adapter's mutation lock only serializes writes inside a single process.
    try:
        with FrontendLock(settings.database_path, "telegram"):
            application.run_polling(allowed_updates=Update.ALL_TYPES)
    except FrontendLockError as exc:
        raise SystemExit(f"启动中止：{exc}") from exc


__all__ = ["TelegramBattleAdapter", "create_application", "main"]


if __name__ == "__main__":
    main()
