from __future__ import annotations

import hashlib
import json
import random
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .db import Database
from .dice import DiceFormulaError, roll_formula
from .models import ContentValidationError, REGULAR_EFFECTS


KEY_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_.-]{1,95}$")

SKILL_TYPES = {"NORMAL", "EGO"}
TARGET_SCOPES = {"SELF", "FRIENDLY", "ENEMY", "ALL"}
SKILL_TARGET_METHODS = {"SELF", "SELECT_TARGET", "ALL_TARGETS", "RANDOM"}
AUTO_TARGET_METHODS = {"SELF", "ALL_TARGETS", "RANDOM"}
BEHAVIOR_EFFECT_TYPES = {"DAMAGE", "HEAL", "APPLY_EFFECT", "SPECIAL"}
TRIGGER_SCOPES = {"PER_SKILL", "PER_TARGET", "PER_HIT"}
EFFECT_CATEGORIES = {"REGULAR", "GENERIC", "SPECIAL", "INSTANT"}
LIFECYCLE_SCOPES = {"TURN", "STAGE", "BATTLE"}
REGISTRATION_STARTS = {"THIS_TURN_END", "NEXT_TURN_START"}
MANAGER_ACTION_PHASES = {"FRIENDLY_ACTION", "ENEMY_ACTION", "STAGE_END"}
HOOK_EVENTS = {
    "TURN_START", "ON_BEFORE_DAMAGE", "ON_HIT", "ON_CRIT",
    "ON_AFTER_DAMAGE", "ON_KILL", "ON_ACTION_END", "TURN_END",
}
HOOK_SUBJECTS = {"OWNER_ACTOR", "OWNER_TARGET", "OWNER_INVOLVED", "ANY"}

ROOT_FIELDS = {
    "pack", "effects", "skills", "characters", "core_characters", "personas",
    "character_extensions", "abnormalities", "manager_skills", "encounters",
}
PACK_FIELDS = {"key", "name", "version", "description", "requires"}
EFFECT_FIELDS = {
    "key", "name", "description", "category", "icon", "handler",
    "default_params", "metadata",
}
SKILL_FIELDS = {
    "key", "name", "description", "type", "cooldown", "emotion",
    "target_scope", "target_method", "target_param", "max_uses_per_battle",
    "metadata", "behaviors",
}
BEHAVIOR_FIELDS = {
    "key", "timing", "trigger_condition", "trigger_scope", "target_source",
    "target_scope", "target_method", "target_param", "effect_type", "effect_key",
    "value", "params", "order",
}
TEMPLATE_FIELDS = {
    "key", "name", "description", "max_hp", "max_actions", "max_stagger",
    "tags", "skills", "ego_skill", "metadata",
}
CORE_FIELDS = {
    "name", "description", "max_hp", "max_actions", "max_stagger", "tags",
    "ego_skill", "metadata",
}
PERSONA_FIELDS = {
    "key", "character", "name", "description", "max_hp", "max_actions",
    "max_stagger", "default", "skills", "metadata",
}
EXTENSION_FIELDS = {"template_key", "skills", "ego_skills"}
ABNORMALITY_FIELDS = {"key", "name", "description", "pages", "carry_bonus"}
PAGE_FIELDS = {"key", "name", "description", "type", "level", "handler", "params"}
CARRY_BONUS_FIELDS = {"key", "name", "description", "handler", "params"}
MANAGER_FIELDS = {
    "key", "name", "description", "unlock", "handler", "max_uses",
    "allowed_phase", "params",
}
ENCOUNTER_FIELDS = {"key", "name", "description", "abnormalities", "stages"}
STAGE_FIELDS = {"name", "description", "enemies", "clear_when", "on_clear"}
ENEMY_FIELDS = {"id", "template", "count", "name"}
CLEAR_CONDITION_FIELDS = {"type", "target", "ratio"}


@dataclass(frozen=True, slots=True)
class ContentLoadResult:
    pack_key: str
    version: str
    effects: int
    skills: int
    behaviors: int
    characters: int
    core_characters: int
    personas: int
    abnormalities: int
    pages: int
    manager_skills: int
    encounters: int


def _key(value: Any, field: str) -> str:
    if not isinstance(value, str) or not KEY_PATTERN.fullmatch(value):
        raise ContentValidationError(
            f"{field} 必须是稳定键（小写字母/数字/._-，长度2-96）：{value!r}"
        )
    return value


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _required(mapping: dict[str, Any], key: str, where: str) -> Any:
    if key not in mapping:
        raise ContentValidationError(f"{where} 缺少字段 {key}")
    return mapping[key]


class ContentLoader:
    """Versioned, idempotent loader for data-only game content packs."""

    def __init__(
        self,
        database: Database,
        registered_handlers: Iterable[str] | None = None,
    ):
        self.database = database
        self._registered_handlers = (
            {str(item).strip().lower() for item in registered_handlers}
            if registered_handlers is not None
            else None
        )

    def set_registered_handlers(self, handlers: Iterable[str]) -> None:
        self._registered_handlers = {
            str(item).strip().lower() for item in handlers
        }

    def load_path(self, path: str | Path) -> ContentLoadResult:
        source = Path(path)
        try:
            data = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ContentValidationError(f"无法读取内容包 {source}: {exc}") from exc
        return self.load(data)

    def load(self, data: dict[str, Any]) -> ContentLoadResult:
        if not isinstance(data, dict):
            raise ContentValidationError("内容包根节点必须是对象")
        if "roles" in data:
            raise ContentValidationError(
                "roles/role_key 已移除；核心角色请使用 core_characters，人格使用 character"
            )
        self._reject_unknown_fields(data, ROOT_FIELDS, "内容包根节点")
        pack = _required(data, "pack", "内容包")
        if not isinstance(pack, dict):
            raise ContentValidationError("pack 必须是对象")
        self._reject_unknown_fields(pack, PACK_FIELDS, "pack")
        pack_key = _key(_required(pack, "key", "pack"), "pack.key")
        version = str(_required(pack, "version", "pack"))
        dependencies = self._dependencies(pack, pack_key)
        checksum = hashlib.sha256(_json(data).encode("utf-8")).hexdigest()

        effects = self._list(data, "effects")
        skills = self._list(data, "skills")
        characters = self._list(data, "characters")
        core_characters = self._list(data, "core_characters")
        personas = self._list(data, "personas")
        character_extensions = self._list(data, "character_extensions")
        abnormalities = self._list(data, "abnormalities")
        manager_skills = self._list(data, "manager_skills")
        encounters = self._list(data, "encounters")
        behavior_count = sum(len(self._list(skill, "behaviors")) for skill in skills)
        persona_count = len(personas)
        page_count = sum(len(self._list(item, "pages")) for item in abnormalities)

        result = ContentLoadResult(
            pack_key=pack_key,
            version=version,
            effects=len(effects),
            skills=len(skills),
            behaviors=behavior_count,
            characters=len(characters),
            core_characters=len(core_characters),
            personas=persona_count,
            abnormalities=len(abnormalities),
            pages=page_count,
            manager_skills=len(manager_skills),
            encounters=len(encounters),
        )

        self._validate_dependencies(dependencies, pack_key, version)
        self._validate(
            pack_key,
            effects,
            skills,
            characters,
            core_characters,
            personas,
            character_extensions,
            abnormalities,
            manager_skills,
            encounters,
        )

        existing_pack = self.database.fetch_one(
            "SELECT checksum FROM content_packs WHERE pack_key=?", (pack_key,)
        )
        if existing_pack is not None and existing_pack["checksum"] == checksum:
            # A true idempotent reload must not delete/recreate behavior rows:
            # active registrations reference their stable database ids.
            return result
        if self.database.fetch_one("SELECT 1 FROM battles WHERE status='ACTIVE'"):
            raise ContentValidationError(
                "战斗记录仍在展开；为避免中途改变技能定义，只能重载内容完全相同的包。"
            )

        with self.database.transaction() as connection:
            if connection.execute(
                "SELECT 1 FROM battles WHERE status='ACTIVE'"
            ).fetchone():
                raise ContentValidationError(
                    "战斗记录仍在展开；内容更新必须等待战斗结束。"
                )
            current_pack = connection.execute(
                "SELECT checksum FROM content_packs WHERE pack_key=?", (pack_key,)
            ).fetchone()
            if current_pack is not None and current_pack["checksum"] == checksum:
                return result
            observed_checksum = existing_pack["checksum"] if existing_pack is not None else None
            current_checksum = current_pack["checksum"] if current_pack is not None else None
            if current_checksum != observed_checksum:
                raise ContentValidationError(
                    f"内容包 {pack_key} 在加载期间被其他事务更新，请重新加载最新文件。"
                )
            self._validate(
                pack_key,
                effects,
                skills,
                characters,
                core_characters,
                personas,
                character_extensions,
                abnormalities,
                manager_skills,
                encounters,
                connection=connection,
            )
            self._validate_dependencies(
                dependencies, pack_key, version, connection=connection
            )
            self._validate_pack_removals(
                connection,
                pack_key,
                {item["key"] for item in effects},
                {item["key"] for item in skills},
                {item["key"] for item in characters},
                {item["name"] for item in core_characters},
                {item["key"] for item in personas},
                {item["key"] for item in abnormalities},
            )
            connection.execute(
                """
                INSERT INTO content_packs(pack_key,name,version,description,checksum,loaded_at)
                VALUES(?,?,?,?,?,CURRENT_TIMESTAMP)
                ON CONFLICT(pack_key) DO UPDATE SET
                    name=excluded.name, version=excluded.version,
                    description=excluded.description, checksum=excluded.checksum,
                    loaded_at=CURRENT_TIMESTAMP
                """,
                (
                    pack_key,
                    str(pack.get("name", pack_key)),
                    version,
                    str(pack.get("description", "")),
                    checksum,
                ),
            )
            connection.execute(
                "DELETE FROM content_pack_dependencies WHERE pack_key=?",
                (pack_key,),
            )
            for required_pack_key, minimum in dependencies:
                connection.execute(
                    """
                    INSERT INTO content_pack_dependencies(
                        pack_key,required_pack_key,min_version
                    ) VALUES(?,?,?)
                    """,
                    (pack_key, required_pack_key, minimum),
                )
            self._disable_old_pack_entries(connection, pack_key)
            self._load_effects(connection, pack_key, effects)
            self._load_skills(connection, pack_key, skills)
            skill_ids = {
                row["skill_key"]: row["id"]
                for row in connection.execute("SELECT id,skill_key FROM skills WHERE enabled=1")
            }
            self._load_characters(connection, pack_key, characters, skill_ids)
            self._load_core_characters(
                connection, pack_key, core_characters, skill_ids
            )
            self._load_personas(connection, pack_key, personas, skill_ids)
            self._load_character_extensions(
                connection, pack_key, character_extensions, skill_ids
            )
            self._load_abnormalities(connection, pack_key, abnormalities)
            self._load_manager_skills(connection, pack_key, manager_skills)
            self._load_encounters(connection, pack_key, encounters)
            self._normalize_disabled_personas(connection)
            self._assert_one_default_persona_per_core(connection)

        return result

    @staticmethod
    def _dependencies(
        pack: dict[str, Any], pack_key: str
    ) -> list[tuple[str, str | None]]:
        raw = pack.get("requires", [])
        if not isinstance(raw, list):
            raise ContentValidationError("pack.requires 必须是数组")
        result: list[tuple[str, str | None]] = []
        seen: set[str] = set()
        for item in raw:
            if isinstance(item, str):
                required_key, minimum = _key(item, "pack.requires"), None
            elif isinstance(item, dict):
                ContentLoader._reject_unknown_fields(
                    item, {"key", "min_version"}, "pack.requires"
                )
                required_key = _key(
                    _required(item, "key", "pack.requires"), "pack.requires.key"
                )
                minimum = (
                    str(item["min_version"]) if item.get("min_version") is not None else None
                )
            else:
                raise ContentValidationError("pack.requires 每项必须是包键或对象")
            if required_key == pack_key:
                raise ContentValidationError("内容包不能依赖自身")
            if required_key in seen:
                raise ContentValidationError(f"重复内容包依赖: {required_key}")
            seen.add(required_key)
            if minimum is not None:
                ContentLoader._version_key(minimum)
            result.append((required_key, minimum))
        return result

    def _validate_dependencies(
        self,
        dependencies: list[tuple[str, str | None]],
        pack_key: str,
        version: str,
        *,
        connection: Any | None = None,
    ) -> None:
        self._version_key(version)
        for required_key, minimum in dependencies:
            rows = self._fetch_all(
                "SELECT version FROM content_packs WHERE pack_key=?",
                (required_key,),
                connection,
            )
            if not rows:
                raise ContentValidationError(f"缺少依赖内容包: {required_key}")
            if minimum is not None and self._version_key(rows[0]["version"]) < self._version_key(minimum):
                raise ContentValidationError(
                    f"依赖 {required_key} 版本过低：需要 >= {minimum}，当前 {rows[0]['version']}"
                )
        consumers = self._fetch_all(
            """
            SELECT d.pack_key,d.min_version FROM content_pack_dependencies d
            WHERE d.required_pack_key=? AND d.min_version IS NOT NULL
            """,
            (pack_key,),
            connection,
        )
        for consumer in consumers:
            if self._version_key(version) < self._version_key(consumer["min_version"]):
                raise ContentValidationError(
                    f"不能把 {pack_key} 更新为 {version}；包 {consumer['pack_key']} "
                    f"要求 >= {consumer['min_version']}"
                )

    @staticmethod
    def _version_key(version: str) -> tuple[int, ...]:
        match = re.fullmatch(r"(\d+(?:\.\d+)*)(?:-([0-9A-Za-z.-]+))?", str(version))
        if match is None:
            raise ContentValidationError(f"内容包版本必须是数字点分格式: {version}")
        parts = [int(item) for item in match.group(1).split(".")]
        parts = (parts + [0, 0, 0, 0])[:4]
        # A release sorts after its prerelease with the same numeric core.
        return (*parts, 1 if match.group(2) is None else 0)

    @staticmethod
    def _list(mapping: dict[str, Any], key: str) -> list[dict[str, Any]]:
        value = mapping.get(key, [])
        if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
            raise ContentValidationError(f"{key} 必须是对象数组")
        return value

    @staticmethod
    def _unique_references(
        mapping: dict[str, Any], key: str, where: str
    ) -> list[str]:
        value = mapping.get(key, [])
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            raise ContentValidationError(f"{where}.{key} 必须是字符串数组")
        duplicates = sorted({item for item in value if value.count(item) > 1})
        if duplicates:
            raise ContentValidationError(
                f"{where}.{key} 存在重复引用：{', '.join(duplicates)}"
            )
        return value

    @staticmethod
    def _reject_unknown_fields(
        mapping: dict[str, Any], allowed: set[str], where: str
    ) -> None:
        unknown = sorted(set(mapping) - allowed)
        if unknown:
            raise ContentValidationError(
                f"{where} 包含未知字段：{', '.join(unknown)}；"
                "请检查拼写或更新内容格式"
            )

    def _validate(
        self,
        pack_key: str,
        effects: list[dict[str, Any]],
        skills: list[dict[str, Any]],
        characters: list[dict[str, Any]],
        core_characters: list[dict[str, Any]],
        personas: list[dict[str, Any]],
        character_extensions: list[dict[str, Any]],
        abnormalities: list[dict[str, Any]],
        manager_skills: list[dict[str, Any]],
        encounters: list[dict[str, Any]],
        *,
        connection: Any | None = None,
    ) -> None:
        local_effect_keys = {_key(_required(item, "key", "effect"), "effect.key") for item in effects}
        local_skill_keys = {_key(_required(item, "key", "skill"), "skill.key") for item in skills}
        if len(local_effect_keys) != len(effects) or len(local_skill_keys) != len(skills):
            raise ContentValidationError(f"内容包 {pack_key} 中存在重复 effect/skill key")
        for effect in effects:
            self._reject_unknown_fields(effect, EFFECT_FIELDS, f"effect {effect.get('key', '?')}")
            if effect.get("category") not in EFFECT_CATEGORIES:
                raise ContentValidationError(
                    f"{effect['key']}: category 必须是 {sorted(EFFECT_CATEGORIES)}"
                )
            if effect.get("handler") is not None and not str(effect["handler"]).strip():
                raise ContentValidationError(f"{effect['key']}: handler 不能为空字符串")
            self._validate_registered_handler(effect["key"], effect.get("handler"))
            if effect.get("category") == "INSTANT" and not effect.get("handler"):
                raise ContentValidationError(f"{effect['key']}: INSTANT 效果必须指定 handler")
            if effect.get("category") == "REGULAR" and effect["key"] not in REGULAR_EFFECTS:
                raise ContentValidationError(
                    f"{effect['key']}: REGULAR 仅限五种内置常规效果 "
                    f"{sorted(REGULAR_EFFECTS)}；新持续机制请使用 SPECIAL 类别并注册 handler"
                )
            self._validate_hook_params(effect["key"], effect.get("default_params", {}))
        self._assert_pack_ownership(
            "effect_definitions", "effect_key", local_effect_keys, pack_key, connection
        )
        self._assert_pack_ownership(
            "skills", "skill_key", local_skill_keys, pack_key, connection
        )
        existing_effect_keys = {
            row["effect_key"]
            for row in self._fetch_all(
                "SELECT effect_key FROM effect_definitions WHERE enabled=1 AND pack_key!=?",
                (pack_key,),
                connection,
            )
        }
        existing_skill_rows = self._fetch_all(
            "SELECT skill_key,skill_type FROM skills WHERE enabled=1 AND pack_key!=?",
            (pack_key,),
            connection,
        )
        existing_skill_keys = {row["skill_key"] for row in existing_skill_rows}
        effect_keys = local_effect_keys | existing_effect_keys
        skill_keys = local_skill_keys | existing_skill_keys
        skill_types = {row["skill_key"]: row["skill_type"] for row in existing_skill_rows}
        skill_types.update(
            {item["key"]: str(item.get("type", "NORMAL")) for item in skills}
        )
        for effect in effects:
            if effect.get("handler") in {"consume_resource", "accumulate_resource"}:
                resource_key = (effect.get("default_params") or {}).get("resource_key")
                if resource_key is not None and resource_key not in effect_keys:
                    raise ContentValidationError(
                        f"{effect['key']}: handler 引用的资源效果 "
                        f"{resource_key!r} 不存在或未启用"
                    )

        behavior_keys: set[str] = set()
        allowed_timing = {"TURN_START", "PRE", "ON", "POST", "TURN_END"}
        allowed_triggers = {
            "ALWAYS", "ON_HIT", "ON_CRIT_HIT", "ON_CRIT_TRIGGER", "ON_KILL",
            "ON_CRIT_KILL", "ON_KILL_SELECTED_TARGET", "ON_NO_KILL_SELECTED_TARGET",
            "ON_KILL_ALLY", "ON_KILL_ENEMY",
        }
        for skill in skills:
            where = f"skill {skill.get('key', '?')}"
            self._reject_unknown_fields(skill, SKILL_FIELDS, where)
            behaviors = self._list(skill, "behaviors")
            if not any(item.get("timing", "ON") == "ON" for item in behaviors):
                raise ContentValidationError(f"{where} 必须至少有一个 ON 行为")
            method = str(_required(skill, "target_method", where))
            scope = str(_required(skill, "target_scope", where))
            skill_type = str(skill.get("type", "NORMAL"))
            if skill_type not in SKILL_TYPES:
                raise ContentValidationError(f"{where}: type 必须是 NORMAL/EGO")
            if scope not in TARGET_SCOPES or method not in SKILL_TARGET_METHODS:
                raise ContentValidationError(f"{where}: 目标范围或方式非法")
            if (method == "SELF") != (scope == "SELF"):
                raise ContentValidationError(f"{where}: SELF 范围与 SELF 方式必须成对使用")
            if method == "RANDOM" and int(skill.get("target_param") or 0) <= 0:
                raise ContentValidationError(f"{where}: RANDOM 必须提供正整数 target_param")
            if method == "SELECT_TARGET" and skill.get("target_param") not in (None, 1):
                raise ContentValidationError(
                    f"{where}: 当前交互规范下 SELECT_TARGET 只能选择一个目标"
                )
            if int(skill.get("cooldown", 0)) < 0:
                raise ContentValidationError(f"{where}: cooldown 不得小于0")
            max_uses = skill.get("max_uses_per_battle")
            if max_uses is not None and int(max_uses) <= 0:
                raise ContentValidationError(
                    f"{where}: max_uses_per_battle 必须是正整数或 null"
                )
            emotion = int(skill.get("emotion", 0))
            if not 0 <= emotion <= 5:
                raise ContentValidationError(f"{where}: emotion 必须在0-5之间")
            if skill_type == "EGO" and emotion == 0:
                raise ContentValidationError(f"{where}: EGO 的 emotion 必须在1-5之间")
            if skill_type == "EGO" and int(skill.get("cooldown", 0)) != 0:
                raise ContentValidationError(
                    f"{where}: EGO 不使用普通技能冷却，cooldown 必须为0"
                )
            if skill_type == "EGO" and max_uses not in (None, 1):
                raise ContentValidationError(
                    f"{where}: 每名角色每场战斗只能使用一次 EGO；"
                    "max_uses_per_battle 只能为1或null"
                )
            for behavior in behaviors:
                self._reject_unknown_fields(
                    behavior, BEHAVIOR_FIELDS, f"{where}.behavior"
                )
                behavior_key = _key(_required(behavior, "key", where), "behavior.key")
                if behavior_key in behavior_keys:
                    raise ContentValidationError(f"重复 behavior key: {behavior_key}")
                behavior_keys.add(behavior_key)
                timing = str(behavior.get("timing", "ON"))
                trigger = str(behavior.get("trigger_condition", "ALWAYS"))
                if timing not in allowed_timing or trigger not in allowed_triggers:
                    raise ContentValidationError(f"{behavior_key}: timing/trigger_condition 非法")
                trigger_scope = str(
                    behavior.get("trigger_scope", self._default_scope(behavior))
                )
                if trigger_scope not in TRIGGER_SCOPES:
                    raise ContentValidationError(f"{behavior_key}: trigger_scope 非法")
                if timing in {"TURN_START", "TURN_END"}:
                    if trigger != "ALWAYS":
                        raise ContentValidationError(
                            f"{behavior_key}: 回合钩子当前只支持 ALWAYS 条件"
                        )
                    registration = behavior.get("params", {}).get("registration")
                    if not isinstance(registration, dict):
                        raise ContentValidationError(
                            f"{behavior_key}: 回合开始/结束行为必须在 params.registration 定义生命周期"
                        )
                    active_from = registration.get("active_from", "NEXT_TURN_START")
                    if active_from not in REGISTRATION_STARTS:
                        raise ContentValidationError(f"{behavior_key}: active_from 非法")
                    if timing == "TURN_START" and active_from == "THIS_TURN_END":
                        raise ContentValidationError(
                            f"{behavior_key}: TURN_START 行为不能从 THIS_TURN_END 激活"
                        )
                    lifecycle = registration.get("lifecycle_scope", "TURN")
                    if lifecycle not in LIFECYCLE_SCOPES:
                        raise ContentValidationError(f"{behavior_key}: lifecycle_scope 非法")
                    for field in ("remaining_turns", "remaining_triggers"):
                        value = registration.get(field, 1)
                        if value is not None and int(value) <= 0:
                            raise ContentValidationError(f"{behavior_key}: {field} 必须为正整数或 null")
                target_source = str(behavior.get("target_source", "INHERIT_SKILL"))
                if target_source not in {"INHERIT_SKILL", "AUTO"}:
                    raise ContentValidationError(f"{behavior_key}: target_source 非法")
                if target_source == "AUTO":
                    behavior_scope = behavior.get("target_scope")
                    behavior_method = behavior.get("target_method")
                    if behavior_scope not in TARGET_SCOPES or behavior_method not in AUTO_TARGET_METHODS:
                        raise ContentValidationError(
                            f"{behavior_key}: AUTO 必须指定合法范围及 SELF/ALL_TARGETS/RANDOM 方式"
                        )
                    if (behavior_method == "SELF") != (behavior_scope == "SELF"):
                        raise ContentValidationError(
                            f"{behavior_key}: AUTO 的 SELF 范围与方式必须成对使用"
                        )
                    if behavior_method == "RANDOM" and int(behavior.get("target_param") or 0) <= 0:
                        raise ContentValidationError(
                            f"{behavior_key}: AUTO RANDOM 必须提供正整数 target_param"
                        )
                effect_type = str(_required(behavior, "effect_type", behavior_key))
                if effect_type not in BEHAVIOR_EFFECT_TYPES:
                    raise ContentValidationError(f"{behavior_key}: effect_type 非法")
                if effect_type == "APPLY_EFFECT":
                    ref = _key(_required(behavior, "effect_key", behavior_key), "behavior.effect_key")
                    if ref not in effect_keys:
                        raise ContentValidationError(f"{behavior_key}: 未在本包定义效果 {ref}")
                    activation = behavior.get("params", {}).get("activation_timing")
                    if activation not in (None, "NEXT_TURN_START"):
                        raise ContentValidationError(
                            f"{behavior_key}: activation_timing 只允许 NEXT_TURN_START"
                        )
                if effect_type in {"DAMAGE", "HEAL"}:
                    try:
                        roll_formula(
                            behavior.get("value", "0"), rng=random.Random(0)
                        )
                    except DiceFormulaError as exc:
                        raise ContentValidationError(
                            f"{behavior_key}: 非法骰子公式: {exc}"
                        ) from exc
                if effect_type == "SPECIAL" and not (
                    behavior.get("value") or behavior.get("params", {}).get("handler")
                ):
                    raise ContentValidationError(f"{behavior_key}: SPECIAL 必须指定处理器键")
                if effect_type == "SPECIAL":
                    handler_key = (
                        behavior.get("value") or behavior.get("params", {}).get("handler")
                    )
                    self._validate_registered_handler(behavior_key, handler_key)
                    handler_params = behavior.get("params", {}) or {}
                    if handler_key == "invoke_skill":
                        invoked = handler_params.get("skill_key")
                        if not invoked or invoked not in skill_keys:
                            raise ContentValidationError(
                                f"{behavior_key}: invoke_skill 引用的技能 "
                                f"{invoked!r} 不存在或未启用"
                            )
                    elif handler_key in {"consume_resource", "accumulate_resource"}:
                        resource_key = handler_params.get("resource_key")
                        if resource_key is not None and resource_key not in effect_keys:
                            raise ContentValidationError(
                                f"{behavior_key}: {handler_key} 引用的资源效果 "
                                f"{resource_key!r} 不存在或未启用"
                            )

        self._assert_behavior_ownership(behavior_keys, pack_key, connection)

        template_keys = {
            _key(_required(item, "key", "character"), "character.key") for item in characters
        }
        if len(template_keys) != len(characters):
            raise ContentValidationError("角色模板 key 重复")
        self._assert_pack_ownership(
            "character_templates", "template_key", template_keys, pack_key, connection
        )
        for character in characters:
            if character.get("core"):
                raise ContentValidationError(
                    f"{character['key']}: characters 只用于生成模板；核心角色请放入 core_characters"
                )
            if character.get("personas"):
                raise ContentValidationError(
                    f"{character['key']}: 生成模板不能持有人格；人格必须直接关联核心角色"
                )
            self._reject_unknown_fields(
                character, TEMPLATE_FIELDS, f"character {character.get('key', '?')}"
            )
            # boss 是 2026-07-26 裁定的正式标记：带它的敌人在前端挂 BOSS 标签。
            unknown_tags = set(character.get("tags", [])) - {"人类", "机械", "异想体", "boss"}
            if unknown_tags:
                raise ContentValidationError(
                    f"{character['key']}: 当前只允许特性标签 人类/机械/异想体/boss，收到 {sorted(unknown_tags)}"
                )
            ego = character.get("ego_skill")
            if ego is not None and ego not in skill_keys:
                raise ContentValidationError(f"{character['key']}: EGO 技能不存在: {ego}")
            if ego is not None and skill_types.get(ego) != "EGO":
                raise ContentValidationError(f"{character['key']}: ego_skill 必须引用 EGO 类型技能")
            for skill_key in self._unique_references(
                character, "skills", str(character["key"])
            ):
                if skill_key not in skill_keys:
                    raise ContentValidationError(f"{character['key']}: 技能不存在: {skill_key}")

        for entry in [*characters, *personas]:
            defense = entry.get("metadata", {}).get("defense_skill")
            if defense is not None:
                if not isinstance(defense, dict) or str(defense.get("kind", "GUARD")).upper() not in {"GUARD", "COUNTER", "EVADE", "INTERCEPT", "MEET"}:
                    raise ContentValidationError(f"{entry.get('key')}: 防御类型无效")
                try:
                    roll_formula(str(defense.get("power", "1d6+4")), rng=random.Random(0))
                except (ValueError, TypeError) as exc:
                    raise ContentValidationError(f"{entry.get('key')}: 防御点数表达式无效") from exc

        core_names = {
            str(_required(item, "name", "core_character")).strip()
            for item in core_characters
        }
        core_specs = {
            str(item["name"]).strip(): item for item in core_characters
        }
        if "" in core_names or len(core_names) != len(core_characters):
            raise ContentValidationError("核心角色 name 不能为空或重复")
        for character in core_characters:
            name = str(character["name"]).strip()
            self._reject_unknown_fields(character, CORE_FIELDS, f"core_character {name}")
            unknown_tags = set(character.get("tags", [])) - {"人类", "机械", "异想体"}
            if unknown_tags:
                raise ContentValidationError(
                    f"{name}: 当前只允许特性标签 人类/机械/异想体，收到 {sorted(unknown_tags)}"
                )
            for field in ("max_hp", "max_actions", "max_stagger"):
                if int(character.get(field, 0)) <= 0:
                    raise ContentValidationError(f"{name}: {field} 必须是正整数")
            ego = character.get("ego_skill")
            if ego is not None:
                if ego not in skill_keys:
                    raise ContentValidationError(f"{name}: EGO 技能不存在: {ego}")
                if skill_types.get(ego) != "EGO":
                    raise ContentValidationError(f"{name}: ego_skill 必须引用 EGO 类型技能")

        existing_template_keys = {
            row["template_key"]
            for row in self._fetch_all(
                "SELECT template_key FROM character_templates WHERE enabled=1 AND pack_key!=?",
                (pack_key,),
                connection,
            )
        }
        existing_core_names = {
            row["name"]
            for row in self._fetch_all(
                "SELECT name FROM characters WHERE is_core=1 AND content_pack_key!=?",
                (pack_key,),
                connection,
            )
        }
        conflicting_core_names = core_names & existing_core_names
        if conflicting_core_names:
            raise ContentValidationError(
                "核心角色已由其他内容包拥有：" + ", ".join(sorted(conflicting_core_names))
            )
        available_template_keys = template_keys | existing_template_keys
        available_core_names = core_names | existing_core_names
        persona_keys: set[str] = set()
        defaults_by_character: dict[str, int] = {}
        for persona in personas:
            persona_key = _key(_required(persona, "key", "persona"), "persona.key")
            if persona_key in persona_keys:
                raise ContentValidationError(f"人格 key 重复: {persona_key}")
            persona_keys.add(persona_key)
            if "role_key" in persona or "template_key" in persona:
                raise ContentValidationError(
                    f"{persona_key}: role_key/template_key 已移除；请使用 character"
                )
            self._reject_unknown_fields(persona, PERSONA_FIELDS, f"persona {persona_key}")
            owner_name = str(_required(persona, "character", persona_key)).strip()
            if owner_name not in available_core_names:
                raise ContentValidationError(
                    f"{persona_key}: 核心角色不存在: {owner_name}"
                )
            if persona.get("default", False) and owner_name not in core_names:
                raise ContentValidationError(
                    f"{persona_key}: 只有拥有核心角色 {owner_name} 的内容包"
                    "才能声明其默认人格"
                )
            defaults_by_character[owner_name] = defaults_by_character.get(owner_name, 0) + int(
                bool(persona.get("default", False))
            )
            for field in ("max_hp", "max_actions", "max_stagger"):
                if int(persona.get(field, 0)) <= 0:
                    raise ContentValidationError(f"{persona_key}: {field} 必须是正整数")
                if (
                    persona.get("default", False)
                    and int(persona[field]) != int(core_specs[owner_name][field])
                ):
                    raise ContentValidationError(
                        f"{persona_key}: 默认人格的 {field} 必须与核心角色初始数据一致"
                    )
            for skill_key in self._unique_references(persona, "skills", persona_key):
                if skill_key not in skill_keys:
                    raise ContentValidationError(f"{persona_key}: 技能不存在: {skill_key}")
                if skill_types.get(skill_key) != "NORMAL":
                    raise ContentValidationError(
                        f"{persona_key}: 人格只能装配普通技能；EGO 必须绑定角色本体"
                    )
        for owner_name, defaults in defaults_by_character.items():
            if defaults > 1:
                raise ContentValidationError(f"{owner_name}: 只能有一个默认人格")
        for owner_name in core_names:
            if defaults_by_character.get(owner_name, 0) != 1:
                raise ContentValidationError(
                    f"{owner_name}: 核心角色所属包必须声明且只能声明一个默认人格"
                )

        extended_templates: set[str] = set()
        for extension in character_extensions:
            self._reject_unknown_fields(
                extension, EXTENSION_FIELDS, "character_extension"
            )
            template_key = _key(
                _required(extension, "template_key", "character_extension"),
                "character_extension.template_key",
            )
            if template_key in extended_templates:
                raise ContentValidationError(f"角色扩展重复: {template_key}")
            extended_templates.add(template_key)
            if template_key not in available_template_keys:
                raise ContentValidationError(f"角色扩展目标不存在: {template_key}")
            for skill_key in self._unique_references(
                extension, "skills", f"character_extension {template_key}"
            ):
                if skill_key not in skill_keys:
                    raise ContentValidationError(f"{template_key}: 扩展技能不存在: {skill_key}")
            for skill_key in self._unique_references(
                extension, "ego_skills", f"character_extension {template_key}"
            ):
                if skill_key not in skill_keys:
                    raise ContentValidationError(f"{template_key}: 扩展 EGO 不存在: {skill_key}")
                if skill_types.get(skill_key) != "EGO":
                    raise ContentValidationError(f"{template_key}: ego_skills 只能引用 EGO 类型")

        # 跨包重复的模板-技能关联在校验期显式拒绝，避免加载期落入
        # 裸 IntegrityError 或 DO NOTHING 静默吞行（见审计 id=23）。
        declared_pairs: list[tuple[str, str]] = []
        for character in characters:
            for skill_key in self._unique_references(
                character, "skills", f"character {character.get('key', '?')}"
            ):
                declared_pairs.append((character["key"], skill_key))
        for extension in character_extensions:
            for skill_key in self._unique_references(
                extension, "skills", f"character_extension {extension.get('template_key', '?')}"
            ):
                declared_pairs.append((extension["template_key"], skill_key))
        for template_key, skill_key in declared_pairs:
            owner_rows = self._fetch_all(
                """
                SELECT ts.pack_key FROM template_skills ts
                JOIN skills s ON s.id=ts.skill_id
                WHERE ts.template_key=? AND s.skill_key=?
                  AND ts.pack_key IS NOT NULL AND ts.pack_key!=?
                LIMIT 1
                """,
                (template_key, skill_key, pack_key),
                connection,
            )
            if owner_rows:
                raise ContentValidationError(
                    f"模板技能关联 ({template_key}, {skill_key}) 已由包 "
                    f"{owner_rows[0]['pack_key']} 拥有，不能跨包重复声明"
                )
        declared_ego_pairs: list[tuple[str, str]] = []
        for character in characters:
            if character.get("ego_skill"):
                declared_ego_pairs.append((character["key"], str(character["ego_skill"])))
        for extension in character_extensions:
            for skill_key in self._unique_references(
                extension, "ego_skills", f"character_extension {extension.get('template_key', '?')}"
            ):
                declared_ego_pairs.append((extension["template_key"], skill_key))
        for template_key, skill_key in declared_ego_pairs:
            owner_rows = self._fetch_all(
                """
                SELECT ces.pack_key FROM character_ego_skills ces
                JOIN skills s ON s.id=ces.skill_id
                WHERE ces.template_key=? AND s.skill_key=?
                  AND ces.pack_key IS NOT NULL AND ces.pack_key!=?
                LIMIT 1
                """,
                (template_key, skill_key, pack_key),
                connection,
            )
            if owner_rows:
                raise ContentValidationError(
                    f"EGO 关联 ({template_key}, {skill_key}) 已由包 "
                    f"{owner_rows[0]['pack_key']} 拥有，不能跨包重复声明"
                )

        self._assert_pack_ownership(
            "personas", "persona_key", persona_keys, pack_key, connection
        )

        abnormality_keys: set[str] = set()
        page_keys: set[str] = set()
        for abnormality in abnormalities:
            self._reject_unknown_fields(
                abnormality, ABNORMALITY_FIELDS,
                f"abnormality {abnormality.get('key', '?')}",
            )
            abnormality_key = _key(
                _required(abnormality, "key", "abnormality"), "abnormality.key"
            )
            if abnormality_key in abnormality_keys:
                raise ContentValidationError(f"异想体 key 重复: {abnormality_key}")
            abnormality_keys.add(abnormality_key)
            for page in self._list(abnormality, "pages"):
                self._reject_unknown_fields(
                    page, PAGE_FIELDS, f"abnormality {abnormality_key}.page"
                )
                page_key = _key(_required(page, "key", "page"), "page.key")
                if page_key in page_keys:
                    raise ContentValidationError(f"书页 key 重复: {page_key}")
                page_keys.add(page_key)
                if page.get("type") not in {"AWAKENING", "BREAKDOWN"}:
                    raise ContentValidationError(f"{page['key']}: type 必须是 AWAKENING/BREAKDOWN")
                level = page.get("level", 1)
                if not isinstance(level, int) or level < 1 or level > 3:
                    raise ContentValidationError(f"{page_key}: level 必须是 1-3 的整数")
                if page.get("handler") is not None and not str(page["handler"]).strip():
                    raise ContentValidationError(f"{page_key}: handler 不能为空字符串")
                self._validate_registered_handler(page_key, page.get("handler"))
                self._validate_hook_params(page_key, page.get("params", {}))
                self._validate_sequence_steps(
                    page_key, page.get("handler"), page.get("params", {})
                )
            carry = abnormality.get("carry_bonus")
            if carry is not None:
                if not isinstance(carry, dict):
                    raise ContentValidationError(
                        f"{abnormality_key}: carry_bonus 必须是对象"
                    )
                self._reject_unknown_fields(
                    carry, CARRY_BONUS_FIELDS, f"abnormality {abnormality_key}.carry_bonus"
                )
                carry_key = _key(
                    _required(carry, "key", "carry_bonus"), "carry_bonus.key"
                )
                if carry_key in page_keys:
                    raise ContentValidationError(f"书页 key 重复: {carry_key}")
                page_keys.add(carry_key)
                if not str(carry.get("handler") or "").strip():
                    raise ContentValidationError(
                        f"{carry_key}: 携带被动必须指定 handler"
                    )
                self._validate_registered_handler(carry_key, carry.get("handler"))
                self._validate_hook_params(carry_key, carry.get("params", {}))
                self._validate_sequence_steps(
                    carry_key, carry.get("handler"), carry.get("params", {})
                )
        self._assert_pack_ownership(
            "abnormalities", "abnormality_key", abnormality_keys, pack_key, connection
        )
        self._assert_page_ownership(page_keys, pack_key, connection)
        existing_abnormality_keys = {
            row["abnormality_key"]
            for row in self._fetch_all(
                "SELECT abnormality_key FROM abnormalities "
                "WHERE enabled=1 AND pack_key!=?",
                (pack_key,),
                connection,
            )
        }
        available_abnormality_keys = abnormality_keys | existing_abnormality_keys

        manager_keys: set[str] = set()
        for skill in manager_skills:
            self._reject_unknown_fields(
                skill, MANAGER_FIELDS, f"manager_skill {skill.get('key', '?')}"
            )
            manager_key = _key(
                _required(skill, "key", "manager_skill"), "manager_skill.key"
            )
            if manager_key in manager_keys:
                raise ContentValidationError(f"管理人能力 key 重复: {manager_key}")
            manager_keys.add(manager_key)
            if not str(_required(skill, "handler", manager_key)).strip():
                raise ContentValidationError(f"{manager_key}: handler 不能为空")
            self._validate_registered_handler(manager_key, skill.get("handler"))
            if int(skill.get("max_uses", 1)) < 0:
                raise ContentValidationError(f"{manager_key}: max_uses 不得小于0")
            phase = skill.get("allowed_phase")
            if phase is not None and phase not in MANAGER_ACTION_PHASES:
                raise ContentValidationError(
                    f"{manager_key}: allowed_phase 只允许 "
                    "FRIENDLY_ACTION、ENEMY_ACTION、STAGE_END 或 null"
                )
        self._assert_pack_ownership(
            "manager_skills", "manager_skill_key", manager_keys, pack_key, connection
        )

        encounter_keys: set[str] = set()
        for encounter in encounters:
            self._reject_unknown_fields(
                encounter, ENCOUNTER_FIELDS, f"encounter {encounter.get('key', '?')}"
            )
            encounter_key = _key(
                _required(encounter, "key", "encounter"), "encounter.key"
            )
            if encounter_key in encounter_keys:
                raise ContentValidationError(f"重复 encounter key: {encounter_key}")
            encounter_keys.add(encounter_key)
            for abnormality_key in self._unique_references(
                encounter, "abnormalities", encounter_key
            ):
                _key(abnormality_key, f"{encounter_key}.abnormalities")
                if abnormality_key not in available_abnormality_keys:
                    raise ContentValidationError(
                        f"{encounter_key}: 异想体不存在或已停用: {abnormality_key}"
                    )
            stages = self._list(encounter, "stages")
            if not stages:
                raise ContentValidationError(f"{encounter_key}: 至少需要一个 stage")
            for number, stage in enumerate(stages, 1):
                self._reject_unknown_fields(
                    stage, STAGE_FIELDS, f"{encounter_key}.stage{number}"
                )
                enemies = self._list(stage, "enemies")
                if not enemies:
                    raise ContentValidationError(
                        f"{encounter_key}: stage {number} 至少需要一个敌人"
                    )
                enemy_ids: set[str] = set()
                enemy_counts: dict[str, int] = {}
                for position, enemy in enumerate(enemies, 1):
                    self._reject_unknown_fields(
                        enemy, ENEMY_FIELDS,
                        f"{encounter_key}.stage{number}.enemy{position}",
                    )
                    template_key = _key(
                        _required(enemy, "template", f"{encounter_key}.stage{number}"),
                        "enemy.template",
                    )
                    if template_key not in available_template_keys:
                        raise ContentValidationError(
                            f"{encounter_key}: 敌人模板不存在: {template_key}"
                        )
                    if int(enemy.get("count", 1)) <= 0:
                        raise ContentValidationError(
                            f"{encounter_key}: enemy.count 必须大于 0"
                        )
                    enemy_id = str(enemy.get("id", f"enemy_{position}")).strip()
                    if not enemy_id or enemy_id in enemy_ids:
                        raise ContentValidationError(
                            f"{encounter_key}: stage {number} enemy.id must be unique"
                        )
                    enemy_ids.add(enemy_id)
                    enemy_counts[enemy_id] = int(enemy.get("count", 1))
                condition = stage.get(
                    "clear_when", {"type": "ALL_ENEMIES_DEFEATED"}
                )
                if not isinstance(condition, dict):
                    raise ContentValidationError(
                        f"{encounter_key}: stage {number} clear_when must be an object"
                    )
                self._reject_unknown_fields(
                    condition, CLEAR_CONDITION_FIELDS,
                    f"{encounter_key}.stage{number}.clear_when",
                )
                condition_type = str(condition.get("type", "")).upper()
                if condition_type not in {
                    "ALL_ENEMIES_DEFEATED", "TARGET_DEFEATED", "TARGET_HP_BELOW"
                }:
                    raise ContentValidationError(
                        f"{encounter_key}: unsupported clear condition {condition_type}"
                    )
                if condition_type.startswith("TARGET_") and str(
                    condition.get("target", "")
                ) not in enemy_ids:
                    raise ContentValidationError(
                        f"{encounter_key}: clear target is not in stage {number}"
                    )
                if condition_type.startswith("TARGET_"):
                    target_key = str(condition["target"])
                    if enemy_counts[target_key] != 1:
                        raise ContentValidationError(
                            f"{encounter_key}: stage {number} 的条件目标 "
                            f"{target_key} 必须且只能生成 1 名敌人"
                        )
                if condition_type == "TARGET_HP_BELOW" and not 0 < float(
                    condition.get("ratio", 0)
                ) < 1:
                    raise ContentValidationError(
                        f"{encounter_key}: TARGET_HP_BELOW ratio must be between 0 and 1"
                    )
                outcome = str(stage.get(
                    "on_clear", "VICTORY" if number == len(stages) else "NEXT_STAGE"
                )).upper()
                if outcome not in {"NEXT_STAGE", "VICTORY"}:
                    raise ContentValidationError(
                        f"{encounter_key}: on_clear must be NEXT_STAGE or VICTORY"
                    )
                if number == len(stages) and outcome == "NEXT_STAGE":
                    raise ContentValidationError(
                        f"{encounter_key}: 最后一个 stage 不能使用 NEXT_STAGE"
                    )
        self._assert_pack_ownership(
            "encounters", "encounter_key", encounter_keys, pack_key, connection
        )

    def _assert_pack_ownership(
        self,
        table: str,
        key_column: str,
        keys: set[str],
        pack_key: str,
        connection: Any | None = None,
    ) -> None:
        if not keys:
            return
        placeholders = ",".join("?" for _ in keys)
        rows = self._fetch_all(
            f"SELECT {key_column} AS item_key,pack_key FROM {table} "
            f"WHERE {key_column} IN ({placeholders})",
            tuple(sorted(keys)),
            connection,
        )
        conflicts = sorted(
            row["item_key"] for row in rows if row["pack_key"] != pack_key
        )
        if conflicts:
            raise ContentValidationError(
                f"内容键已由其他包拥有，不能覆盖：{', '.join(conflicts)}"
            )

    def _assert_behavior_ownership(
        self, keys: set[str], pack_key: str, connection: Any | None = None
    ) -> None:
        if not keys:
            return
        placeholders = ",".join("?" for _ in keys)
        rows = self._fetch_all(
            "SELECT b.behavior_key AS item_key,s.pack_key "
            "FROM skill_behaviors b JOIN skills s ON s.id=b.skill_id "
            f"WHERE b.behavior_key IN ({placeholders})",
            tuple(sorted(keys)),
            connection,
        )
        conflicts = sorted(row["item_key"] for row in rows if row["pack_key"] != pack_key)
        if conflicts:
            raise ContentValidationError(
                f"行为键已由其他包拥有，不能覆盖：{', '.join(conflicts)}"
            )

    def _assert_page_ownership(
        self, keys: set[str], pack_key: str, connection: Any | None = None
    ) -> None:
        if not keys:
            return
        placeholders = ",".join("?" for _ in keys)
        rows = self._fetch_all(
            "SELECT p.page_key AS item_key,a.pack_key "
            "FROM abnormality_pages p JOIN abnormalities a ON a.id=p.abnormality_id "
            f"WHERE p.page_key IN ({placeholders})",
            tuple(sorted(keys)),
            connection,
        )
        conflicts = sorted(row["item_key"] for row in rows if row["pack_key"] != pack_key)
        if conflicts:
            raise ContentValidationError(
                f"书页键已由其他包拥有，不能覆盖：{', '.join(conflicts)}"
            )

    def _fetch_all(
        self,
        sql: str,
        params: tuple[object, ...],
        connection: Any | None,
    ) -> list[Any]:
        if connection is not None:
            return connection.execute(sql, params).fetchall()
        return self.database.fetch_all(sql, params)

    def _validate_registered_handler(self, where: str, handler: Any) -> None:
        if handler is None or self._registered_handlers is None:
            return
        if str(handler).strip().lower() not in self._registered_handlers:
            raise ContentValidationError(
                f"{where}: 特殊处理器尚未注册: {handler}"
            )

    def _validate_sequence_steps(self, where: str, handler: Any, params: Any) -> None:
        """hook_sequence 的每个 step 也必须指向已注册的处理器（禁止嵌套）。"""
        if str(handler or "").strip() != "hook_sequence":
            return
        steps = params.get("steps") if isinstance(params, dict) else None
        if not isinstance(steps, list) or not steps:
            raise ContentValidationError(f"{where}: hook_sequence 需要非空 steps 列表")
        for index, step in enumerate(steps, 1):
            if not isinstance(step, dict) or not str(step.get("handler") or "").strip():
                raise ContentValidationError(f"{where}: steps[{index}] 缺少 handler")
            if str(step["handler"]).strip() == "hook_sequence":
                raise ContentValidationError(f"{where}: hook_sequence 不允许嵌套")
            self._validate_registered_handler(f"{where}.steps[{index}]", step["handler"])
            if step.get("params") is not None and not isinstance(step["params"], dict):
                raise ContentValidationError(f"{where}: steps[{index}].params 必须是对象")

    @staticmethod
    def _validate_hook_params(where: str, params: Any) -> None:
        if not isinstance(params, dict):
            raise ContentValidationError(f"{where}: params 必须是对象")
        configured = params.get("events", params.get("event"))
        if configured is not None:
            values = [configured] if isinstance(configured, str) else configured
            if not isinstance(values, list) or any(
                str(item).upper() not in HOOK_EVENTS for item in values
            ):
                raise ContentValidationError(f"{where}: events 包含未支持的战斗事件")
        subject = params.get("event_subject")
        if subject is not None and str(subject).upper() not in HOOK_SUBJECTS:
            raise ContentValidationError(f"{where}: event_subject 非法")
        context_targets = params.get("context_targets")
        if context_targets is not None and str(context_targets).upper() not in {
            "OWNER", "EVENT_TARGETS", "EVENT_ACTOR"
        }:
            raise ContentValidationError(f"{where}: context_targets 非法")
        lifecycle = params.get("lifecycle_scope")
        if lifecycle is not None and lifecycle not in LIFECYCLE_SCOPES:
            raise ContentValidationError(f"{where}: lifecycle_scope 非法")
        remaining_turns = params.get("remaining_turns")
        if remaining_turns is not None and int(remaining_turns) <= 0:
            raise ContentValidationError(f"{where}: remaining_turns 必须为正整数")

    @staticmethod
    def _validate_pack_removals(
        connection: Any,
        pack_key: str,
        retained_effects: set[str],
        retained_skills: set[str],
        retained_templates: set[str],
        retained_core_names: set[str],
        retained_personas: set[str],
        retained_abnormalities: set[str],
    ) -> None:
        removed_effects = {
            row["effect_key"]
            for row in connection.execute(
                "SELECT effect_key FROM effect_definitions WHERE pack_key=? AND enabled=1",
                (pack_key,),
            )
            if row["effect_key"] not in retained_effects
        }
        for effect_key in sorted(removed_effects):
            consumer = connection.execute(
                """
                SELECT s.pack_key,s.skill_key FROM skill_behaviors b
                JOIN skills s ON s.id=b.skill_id
                WHERE b.effect_key=? AND b.enabled=1 AND s.enabled=1 AND s.pack_key!=?
                LIMIT 1
                """,
                (effect_key, pack_key),
            ).fetchone()
            if consumer:
                raise ContentValidationError(
                    f"不能移除 {effect_key}；仍被包 {consumer['pack_key']} 的技能 "
                    f"{consumer['skill_key']} 引用"
                )
        if removed_effects:
            for row in connection.execute(
                """
                SELECT s.pack_key,s.skill_key,b.effect_params_json FROM skill_behaviors b
                JOIN skills s ON s.id=b.skill_id
                WHERE b.enabled=1 AND s.enabled=1 AND s.pack_key!=? AND b.effect_type='SPECIAL'
                """,
                (pack_key,),
            ):
                params = json.loads(row["effect_params_json"] or "{}")
                resource_key = params.get("resource_key")
                if resource_key in removed_effects:
                    raise ContentValidationError(
                        f"不能移除 {resource_key}；仍被包 {row['pack_key']} 的技能 "
                        f"{row['skill_key']} 的特殊行为参数引用"
                    )
            for row in connection.execute(
                """
                SELECT pack_key,effect_key,default_params_json FROM effect_definitions
                WHERE enabled=1 AND pack_key!=?
                """,
                (pack_key,),
            ):
                params = json.loads(row["default_params_json"] or "{}")
                resource_key = params.get("resource_key")
                if resource_key in removed_effects:
                    raise ContentValidationError(
                        f"不能移除 {resource_key}；仍被包 {row['pack_key']} 的效果 "
                        f"{row['effect_key']} 的默认参数引用"
                    )

        removed_skills = {
            row["id"]: row["skill_key"]
            for row in connection.execute(
                "SELECT id,skill_key FROM skills WHERE pack_key=? AND enabled=1",
                (pack_key,),
            )
            if row["skill_key"] not in retained_skills
        }
        for skill_id, skill_key in removed_skills.items():
            consumers = connection.execute(
                """
                SELECT pack_key FROM (
                    SELECT COALESCE(ts.pack_key,t.pack_key) AS pack_key
                    FROM template_skills ts
                    JOIN character_templates t ON t.template_key=ts.template_key
                    WHERE ts.skill_id=?
                    UNION ALL
                    SELECT p.pack_key FROM persona_skills ps
                    JOIN personas p ON p.id=ps.persona_id WHERE ps.skill_id=?
                    UNION ALL
                    SELECT t.pack_key FROM character_templates t WHERE t.ego_skill_id=?
                    UNION ALL
                    SELECT ces.pack_key FROM character_ego_skills ces WHERE ces.skill_id=?
                    UNION ALL
                    SELECT content_pack_key FROM characters
                    WHERE is_core=1 AND ego_skill_id=?
                ) WHERE pack_key!=? LIMIT 1
                """,
                (skill_id, skill_id, skill_id, skill_id, skill_id, pack_key),
            ).fetchone()
            if consumers:
                raise ContentValidationError(
                    f"不能移除 {skill_key}；仍被包 {consumers['pack_key']} 的角色或人格引用"
                )
        if removed_skills:
            removed_skill_keys = set(removed_skills.values())
            for row in connection.execute(
                """
                SELECT s.pack_key,s.skill_key,b.effect_params_json FROM skill_behaviors b
                JOIN skills s ON s.id=b.skill_id
                WHERE b.enabled=1 AND s.enabled=1 AND s.pack_key!=? AND b.effect_type='SPECIAL'
                """,
                (pack_key,),
            ):
                params = json.loads(row["effect_params_json"] or "{}")
                invoked = params.get("skill_key")
                if invoked in removed_skill_keys:
                    raise ContentValidationError(
                        f"不能移除 {invoked}；仍被包 {row['pack_key']} 的技能 "
                        f"{row['skill_key']} 通过 invoke_skill 引用"
                    )

        removed_templates = {
            row["template_key"]
            for row in connection.execute(
                "SELECT template_key FROM character_templates WHERE pack_key=? AND enabled=1",
                (pack_key,),
            )
            if row["template_key"] not in retained_templates
        }
        for template_key in sorted(removed_templates):
            consumer = connection.execute(
                """
                SELECT pack_key FROM (
                    SELECT pack_key FROM template_skills WHERE template_key=?
                    UNION ALL
                    SELECT pack_key FROM character_ego_skills WHERE template_key=?
                ) WHERE pack_key IS NOT NULL AND pack_key!=? LIMIT 1
                """,
                (template_key, template_key, pack_key),
            ).fetchone()
            if consumer:
                raise ContentValidationError(
                    f"不能移除角色模板 {template_key}；仍被包 {consumer['pack_key']} 扩展"
                )
            encounter_consumer = connection.execute(
                """
                SELECT e.pack_key,e.encounter_key FROM encounter_stage_enemies se
                JOIN encounter_stages s ON s.id=se.stage_id
                JOIN encounters e ON e.encounter_key=s.encounter_key
                WHERE se.template_key=? AND e.enabled=1 AND e.pack_key!=?
                LIMIT 1
                """,
                (template_key, pack_key),
            ).fetchone()
            if encounter_consumer:
                raise ContentValidationError(
                    f"不能移除角色模板 {template_key}；仍被包 "
                    f"{encounter_consumer['pack_key']} 的关卡 "
                    f"{encounter_consumer['encounter_key']} 引用"
                )
            setup_consumer = connection.execute(
                """
                SELECT bs.id,bs.name FROM battle_setup_enemies se
                JOIN battle_setups bs ON bs.id=se.setup_id
                WHERE se.template_key=? AND bs.status IN ('STANDBY','ACTIVE')
                LIMIT 1
                """,
                (template_key,),
            ).fetchone()
            if setup_consumer:
                raise ContentValidationError(
                    f"不能移除角色模板 {template_key}；待触发/进行中的战斗 "
                    f"#{setup_consumer['id']} {setup_consumer['name']} 仍在使用"
                )

        removed_abnormalities = {
            row["abnormality_key"]
            for row in connection.execute(
                "SELECT abnormality_key FROM abnormalities "
                "WHERE pack_key=? AND enabled=1",
                (pack_key,),
            )
            if row["abnormality_key"] not in retained_abnormalities
        }
        for abnormality_key in sorted(removed_abnormalities):
            encounter_rows = connection.execute(
                "SELECT encounter_key,pack_key,abnormalities_json FROM encounters "
                "WHERE enabled=1"
            ).fetchall()
            encounter_consumer = next(
                (
                    row for row in encounter_rows
                    if row["pack_key"] != pack_key
                    and abnormality_key in json.loads(row["abnormalities_json"])
                ),
                None,
            )
            if encounter_consumer:
                raise ContentValidationError(
                    f"不能移除异想体 {abnormality_key}；仍被包 "
                    f"{encounter_consumer['pack_key']} 的关卡 "
                    f"{encounter_consumer['encounter_key']} 引用"
                )
            setup_rows = connection.execute(
                """
                SELECT bs.id,bs.name,bs.abnormalities_json
                FROM battle_setups bs
                WHERE bs.status IN ('STANDBY','ACTIVE')
                """
            ).fetchall()
            setup_consumer = next(
                (
                    row for row in setup_rows
                    if abnormality_key in json.loads(row["abnormalities_json"])
                ),
                None,
            )
            if setup_consumer:
                raise ContentValidationError(
                    f"不能移除异想体 {abnormality_key}；待触发/进行中的战斗 "
                    f"#{setup_consumer['id']} {setup_consumer['name']} 仍在使用"
                )

        removed_personas = {
            row["id"]: row["persona_key"]
            for row in connection.execute(
                "SELECT id,persona_key FROM personas WHERE pack_key=? AND enabled=1",
                (pack_key,),
            )
            if row["persona_key"] not in retained_personas
        }
        for persona_id, persona_key in removed_personas.items():
            setup_consumer = connection.execute(
                """
                SELECT bs.id,bs.name FROM battle_setup_friendlies sf
                JOIN battle_setups bs ON bs.id=sf.setup_id
                WHERE sf.persona_id=? AND bs.status IN ('STANDBY','ACTIVE')
                LIMIT 1
                """,
                (persona_id,),
            ).fetchone()
            if setup_consumer:
                raise ContentValidationError(
                    f"不能移除人格 {persona_key}；待触发/进行中的战斗 "
                    f"#{setup_consumer['id']} {setup_consumer['name']} 仍在使用"
                )

        removed_core = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM characters WHERE is_core=1 AND content_pack_key=?",
                (pack_key,),
            )
            if row["name"] not in retained_core_names
        }
        if removed_core:
            raise ContentValidationError(
                "核心角色是持久实体，不能通过内容重载删除：" + ", ".join(sorted(removed_core))
            )

    @staticmethod
    def _disable_old_pack_entries(connection: Any, pack_key: str) -> None:
        connection.execute("DELETE FROM template_skills WHERE pack_key=?", (pack_key,))
        connection.execute("DELETE FROM character_ego_skills WHERE pack_key=?", (pack_key,))
        # 包级预删除全部行为行：behavior_key 全局唯一，逐技能删建会让
        # 同包内跨技能移动 key 的加载结果取决于 JSON 顺序（见审计 id=24）。
        connection.execute(
            "DELETE FROM skill_behaviors WHERE skill_id IN"
            " (SELECT id FROM skills WHERE pack_key=?)",
            (pack_key,),
        )
        for table in (
            "effect_definitions", "skills", "character_templates", "personas",
            "abnormalities", "manager_skills", "encounters",
        ):
            connection.execute(f"UPDATE {table} SET enabled=0 WHERE pack_key=?", (pack_key,))
        connection.execute(
            """
            UPDATE abnormality_pages SET enabled=0
            WHERE abnormality_id IN (SELECT id FROM abnormalities WHERE pack_key=?)
            """,
            (pack_key,),
        )

    @staticmethod
    def _load_effects(connection: Any, pack_key: str, effects: list[dict[str, Any]]) -> None:
        for effect in effects:
            connection.execute(
                """
                INSERT INTO effect_definitions(
                    effect_key,pack_key,name,category,description,icon,handler_key,
                    default_params_json,metadata_json,enabled,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,1,CURRENT_TIMESTAMP)
                ON CONFLICT(effect_key) DO UPDATE SET
                    pack_key=excluded.pack_key,name=excluded.name,category=excluded.category,
                    description=excluded.description,icon=excluded.icon,
                    handler_key=excluded.handler_key,
                    default_params_json=excluded.default_params_json,
                    metadata_json=excluded.metadata_json,enabled=1,updated_at=CURRENT_TIMESTAMP
                """,
                (
                    effect["key"], pack_key, effect.get("name", effect["key"]),
                    effect["category"], effect.get("description", ""), effect.get("icon", ""),
                    effect.get("handler"), _json(effect.get("default_params", {})),
                    _json(effect.get("metadata", {})),
                ),
            )

    def _load_skills(
        self, connection: Any, pack_key: str, skills: list[dict[str, Any]]
    ) -> dict[str, int]:
        ids: dict[str, int] = {}
        for skill in skills:
            connection.execute(
                """
                INSERT INTO skills(
                    skill_key,pack_key,name,description,skill_type,base_cooldown,
                    emotion_requirement,target_scope,target_method,target_param,
                    metadata_json,max_uses_per_battle,enabled,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,1,CURRENT_TIMESTAMP)
                ON CONFLICT(skill_key) DO UPDATE SET
                    pack_key=excluded.pack_key,name=excluded.name,description=excluded.description,
                    skill_type=excluded.skill_type,base_cooldown=excluded.base_cooldown,
                    emotion_requirement=excluded.emotion_requirement,
                    target_scope=excluded.target_scope,target_method=excluded.target_method,
                    target_param=excluded.target_param,metadata_json=excluded.metadata_json,
                    max_uses_per_battle=excluded.max_uses_per_battle,
                    enabled=1,updated_at=CURRENT_TIMESTAMP
                """,
                (
                    skill["key"], pack_key, skill.get("name", skill["key"]),
                    skill.get("description", ""), skill.get("type", "NORMAL"),
                    int(skill.get("cooldown", 0)), int(skill.get("emotion", 0)),
                    skill["target_scope"], skill["target_method"], skill.get("target_param"),
                    _json(skill.get("metadata", {})), skill.get("max_uses_per_battle"),
                ),
            )
            skill_id = connection.execute(
                "SELECT id FROM skills WHERE skill_key=?", (skill["key"],)
            ).fetchone()[0]
            ids[skill["key"]] = skill_id
            connection.execute("DELETE FROM skill_behaviors WHERE skill_id=?", (skill_id,))
            for order, behavior in enumerate(self._list(skill, "behaviors")):
                connection.execute(
                    """
                    INSERT INTO skill_behaviors(
                        behavior_key,skill_id,timing,trigger_condition,trigger_scope,
                        target_source,target_scope,target_method,target_param,effect_type,
                        effect_key,effect_value,effect_params_json,sort_order,enabled
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,1)
                    """,
                    (
                        behavior["key"], skill_id, behavior.get("timing", "ON"),
                        behavior.get("trigger_condition", "ALWAYS"),
                        behavior.get("trigger_scope", self._default_scope(behavior)),
                        behavior.get("target_source", "INHERIT_SKILL"),
                        behavior.get("target_scope"), behavior.get("target_method"),
                        behavior.get("target_param"), behavior["effect_type"],
                        behavior.get("effect_key"), behavior.get("value"),
                        _json(behavior.get("params", {})), int(behavior.get("order", order)),
                    ),
                )
        return ids

    @staticmethod
    def _default_scope(behavior: dict[str, Any]) -> str:
        trigger = behavior.get("trigger_condition", "ALWAYS")
        return "PER_HIT" if trigger in {"ON_HIT", "ON_CRIT_HIT", "ON_CRIT_TRIGGER"} else "PER_SKILL"

    def _load_characters(
        self,
        connection: Any,
        pack_key: str,
        characters: list[dict[str, Any]],
        skill_ids: dict[str, int],
    ) -> None:
        for character in characters:
            ego_id = skill_ids.get(character.get("ego_skill"))
            connection.execute(
                """
                INSERT INTO character_templates(
                    template_key,pack_key,name,description,max_hp,max_actions,
                    max_stagger,tags_json,ego_skill_id,metadata_json,enabled,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,1,CURRENT_TIMESTAMP)
                ON CONFLICT(template_key) DO UPDATE SET
                    pack_key=excluded.pack_key,name=excluded.name,description=excluded.description,
                    max_hp=excluded.max_hp,max_actions=excluded.max_actions,
                    max_stagger=excluded.max_stagger,
                    tags_json=excluded.tags_json,ego_skill_id=excluded.ego_skill_id,
                    metadata_json=excluded.metadata_json,enabled=1,updated_at=CURRENT_TIMESTAMP
                """,
                (
                    character["key"], pack_key, character.get("name", character["key"]),
                    character.get("description", ""),int(character.get("max_hp", 100)),
                    int(character.get("max_actions", 1)),
                    int(character.get("max_stagger", 50)), _json(character.get("tags", [])),
                    ego_id, _json(character.get("metadata", {})),
                ),
            )
            connection.execute(
                "DELETE FROM template_skills WHERE template_key=? AND pack_key=?",
                (character["key"], pack_key),
            )
            for slot, skill_key in enumerate(character.get("skills", [])):
                connection.execute(
                    """
                    INSERT INTO template_skills(template_key,skill_id,slot_order,pack_key)
                    VALUES(?,?,?,?)
                    """,
                    (character["key"], skill_ids[skill_key], slot, pack_key),
                )
            if ego_id is not None:
                connection.execute(
                    """
                    INSERT INTO character_ego_skills(
                        template_key,skill_id,pack_key,slot_order
                    ) VALUES(?,?,?,0)
                    ON CONFLICT(template_key,skill_id) DO UPDATE SET
                        pack_key=excluded.pack_key,slot_order=excluded.slot_order
                    """,
                    (character["key"], ego_id, pack_key),
                )

    @staticmethod
    def _load_core_characters(
        connection: Any,
        pack_key: str,
        core_characters: list[dict[str, Any]],
        skill_ids: dict[str, int],
    ) -> None:
        for character in core_characters:
            name = str(character["name"]).strip()
            ego_id = skill_ids.get(character.get("ego_skill"))
            existing = connection.execute(
                "SELECT id,active_persona_id FROM characters WHERE is_core=1 AND name=?",
                (name,),
            ).fetchone()
            if existing is None:
                connection.execute(
                    """
                    INSERT INTO characters(
                        template_key,name,description,faction,is_core,content_pack_key,
                        ego_skill_id,active_persona_id,current_hp,max_hp,current_actions,
                        max_actions,current_stagger,max_stagger,tags_json,metadata_json
                    ) VALUES(NULL,?,?, 'FRIENDLY',1,?,?,NULL,?,?,?,?,?,?,?,?)
                    """,
                    (
                        name,character.get("description", ""),pack_key,ego_id,
                        int(character["max_hp"]),int(character["max_hp"]),
                        int(character.get("max_actions", 1)),
                        int(character.get("max_actions", 1)),
                        int(character["max_stagger"]),int(character["max_stagger"]),
                        _json(character.get("tags", [])),
                        _json(character.get("metadata", {})),
                    ),
                )
            else:
                connection.execute(
                    """
                    UPDATE characters SET description=?,content_pack_key=?,ego_skill_id=?,
                        tags_json=?,metadata_json=? WHERE id=?
                    """,
                    (
                        character.get("description", ""),pack_key,ego_id,
                        _json(character.get("tags", [])),
                        _json(character.get("metadata", {})),existing["id"],
                    ),
                )

    def _load_personas(
        self,
        connection: Any,
        pack_key: str,
        personas: list[dict[str, Any]],
        skill_ids: dict[str, int],
    ) -> None:
        for persona in personas:
            owner_name = str(persona["character"]).strip()
            owner = connection.execute(
                "SELECT id,active_persona_id FROM characters WHERE is_core=1 AND name=?",
                (owner_name,),
            ).fetchone()
            if owner is None:
                raise ContentValidationError(f"核心角色不存在：{owner_name}")
            if persona.get("default", False):
                connection.execute(
                    "UPDATE personas SET is_default=0 WHERE character_id=?",
                    (owner["id"],),
                )
            self._upsert_persona(
                connection, pack_key, int(owner["id"]), persona, skill_ids
            )
            persona_id = connection.execute(
                "SELECT id FROM personas WHERE persona_key=?", (persona["key"],)
            ).fetchone()[0]
            should_apply = (
                owner["active_persona_id"] == persona_id
                or (owner["active_persona_id"] is None and persona.get("default", False))
            )
            if should_apply:
                connection.execute(
                    """
                    UPDATE characters SET active_persona_id=?,current_hp=?,max_hp=?,
                        current_actions=?,max_actions=?,current_stagger=?,max_stagger=?
                    WHERE id=?
                    """,
                    (
                        persona_id,int(persona["max_hp"]),int(persona["max_hp"]),
                        int(persona.get("max_actions", 1)),
                        int(persona.get("max_actions", 1)),
                        int(persona["max_stagger"]),int(persona["max_stagger"]),
                        owner["id"],
                    ),
                )

    @staticmethod
    def _upsert_persona(
        connection: Any,
        pack_key: str,
        character_id: int,
        persona: dict[str, Any],
        skill_ids: dict[str, int],
    ) -> None:
        existing = connection.execute(
            "SELECT character_id FROM personas WHERE persona_key=?",
            (persona["key"],),
        ).fetchone()
        if existing is not None and int(existing["character_id"]) != int(character_id):
            raise ContentValidationError(
                f"人格 {persona['key']} 已绑定其他核心角色；"
                "persona key 的角色归属一经建立便不能变更，请创建新的 key"
            )
        connection.execute(
            """
            INSERT INTO personas(
                persona_key,pack_key,character_id,name,description,max_hp,max_actions,
                max_stagger,is_default,metadata_json,enabled
            ) VALUES(?,?,?,?,?,?,?,?,?,?,1)
            ON CONFLICT(persona_key) DO UPDATE SET
                pack_key=excluded.pack_key,character_id=excluded.character_id,
                name=excluded.name,description=excluded.description,
                max_hp=excluded.max_hp,max_actions=excluded.max_actions,
                max_stagger=excluded.max_stagger,is_default=excluded.is_default,
                metadata_json=excluded.metadata_json,enabled=1
            """,
            (
                persona["key"], pack_key, character_id,
                persona.get("name", persona["key"]), persona.get("description", ""),
                int(persona["max_hp"]), int(persona.get("max_actions", 1)),
                int(persona["max_stagger"]), int(bool(persona.get("default", False))),
                _json(persona.get("metadata", {})),
            ),
        )
        persona_id = connection.execute(
            "SELECT id FROM personas WHERE persona_key=?", (persona["key"],)
        ).fetchone()[0]
        connection.execute("DELETE FROM persona_skills WHERE persona_id=?", (persona_id,))
        for slot, skill_key in enumerate(persona.get("skills", [])):
            connection.execute(
                "INSERT INTO persona_skills(persona_id,skill_id,slot_order) VALUES(?,?,?)",
                (persona_id, skill_ids[skill_key], slot),
            )

    @staticmethod
    def _load_character_extensions(
        connection: Any,
        pack_key: str,
        extensions: list[dict[str, Any]],
        skill_ids: dict[str, int],
    ) -> None:
        for extension in extensions:
            template_key = extension["template_key"]
            for slot, skill_key in enumerate(extension.get("skills", [])):
                connection.execute(
                    """
                    INSERT INTO template_skills(template_key,skill_id,slot_order,pack_key)
                    VALUES(?,?,?,?)
                    ON CONFLICT(template_key,skill_id) DO NOTHING
                    """,
                    (template_key, skill_ids[skill_key], slot, pack_key),
                )
            for slot, skill_key in enumerate(extension.get("ego_skills", [])):
                connection.execute(
                    """
                    INSERT INTO character_ego_skills(
                        template_key,skill_id,pack_key,slot_order
                    ) VALUES(?,?,?,?)
                    ON CONFLICT(template_key,skill_id) DO NOTHING
                    """,
                    (template_key, skill_ids[skill_key], pack_key, slot),
                )

    @staticmethod
    def _normalize_disabled_personas(connection: Any) -> None:
        rows = connection.execute(
            """
            SELECT c.id FROM characters c
            LEFT JOIN personas active ON active.id=c.active_persona_id
            WHERE c.is_core=1 AND (
                c.active_persona_id IS NULL OR active.enabled=0 OR active.character_id!=c.id
            )
            """
        ).fetchall()
        for row in rows:
            replacement = connection.execute(
                """
                SELECT id,max_hp,max_actions,max_stagger FROM personas
                WHERE character_id=? AND enabled=1
                ORDER BY is_default DESC,id LIMIT 1
                """,
                (row["id"],),
            ).fetchone()
            if replacement is None:
                continue
            connection.execute(
                """
                UPDATE characters SET active_persona_id=?,max_hp=?,
                    current_hp=MIN(current_hp,?),max_actions=?,
                    current_actions=MIN(current_actions,?),max_stagger=?,
                    current_stagger=MIN(current_stagger,?)
                WHERE id=?
                """,
                (
                    replacement["id"],replacement["max_hp"],replacement["max_hp"],
                    replacement["max_actions"],replacement["max_actions"],
                    replacement["max_stagger"],replacement["max_stagger"],row["id"],
                ),
            )

    @staticmethod
    def _assert_one_default_persona_per_core(connection: Any) -> None:
        invalid = connection.execute(
            """
            SELECT c.name,
                   SUM(CASE WHEN p.is_default=1 THEN 1 ELSE 0 END) AS default_count
            FROM characters c
            LEFT JOIN personas p ON p.character_id=c.id AND p.enabled=1
            WHERE c.is_core=1
            GROUP BY c.id,c.name
            HAVING COUNT(p.id)>0
               AND SUM(CASE WHEN p.is_default=1 THEN 1 ELSE 0 END)!=1
            ORDER BY c.id
            LIMIT 1
            """
        ).fetchone()
        if invalid is not None:
            raise ContentValidationError(
                f"核心角色 {invalid['name']} 必须恰有一个启用中的默认人格；"
                f"当前为 {invalid['default_count']} 个"
            )

    def _load_abnormalities(
        self, connection: Any, pack_key: str, abnormalities: list[dict[str, Any]]
    ) -> None:
        for abnormality in abnormalities:
            connection.execute(
                """
                INSERT INTO abnormalities(abnormality_key,pack_key,name,description,enabled)
                VALUES(?,?,?,?,1)
                ON CONFLICT(abnormality_key) DO UPDATE SET
                    pack_key=excluded.pack_key,name=excluded.name,
                    description=excluded.description,enabled=1
                """,
                (
                    abnormality["key"], pack_key,
                    abnormality.get("name", abnormality["key"]),
                    abnormality.get("description", ""),
                ),
            )
            abnormality_id = connection.execute(
                "SELECT id FROM abnormalities WHERE abnormality_key=?", (abnormality["key"],)
            ).fetchone()[0]
            page_rows = [
                (
                    page["key"], page.get("name", page["key"]), page["type"],
                    int(page.get("level", 1)), page.get("description", ""),
                    page.get("handler"), page.get("params", {}),
                )
                for page in self._list(abnormality, "pages")
            ]
            carry = abnormality.get("carry_bonus")
            if carry is not None:
                # 携带被动以 CARRY 页型入库：不进抽取池，开战即自动生效。
                page_rows.append((
                    carry["key"], carry.get("name", carry["key"]), "CARRY",
                    1, carry.get("description", ""),
                    carry.get("handler"), carry.get("params", {}),
                ))
            for key, name, page_type, level, description, handler, params in page_rows:
                connection.execute(
                    """
                    INSERT INTO abnormality_pages(
                        page_key,abnormality_id,name,page_type,level,description,
                        handler_key,params_json,enabled
                    ) VALUES(?,?,?,?,?,?,?,?,1)
                    ON CONFLICT(page_key) DO UPDATE SET
                        abnormality_id=excluded.abnormality_id,name=excluded.name,
                        page_type=excluded.page_type,level=excluded.level,
                        description=excluded.description,
                        handler_key=excluded.handler_key,params_json=excluded.params_json,enabled=1
                    """,
                    (key, abnormality_id, name, page_type, level, description,
                     handler, _json(params)),
                )

    @staticmethod
    def _load_manager_skills(
        connection: Any, pack_key: str, manager_skills: list[dict[str, Any]]
    ) -> None:
        for skill in manager_skills:
            connection.execute(
                """
                INSERT INTO manager_skills(
                    manager_skill_key,pack_key,name,description,unlock_key,handler_key,
                    max_uses_per_battle,allowed_phase,params_json,enabled
                ) VALUES(?,?,?,?,?,?,?,?,?,1)
                ON CONFLICT(manager_skill_key) DO UPDATE SET
                    pack_key=excluded.pack_key,name=excluded.name,
                    description=excluded.description,unlock_key=excluded.unlock_key,
                    handler_key=excluded.handler_key,
                    max_uses_per_battle=excluded.max_uses_per_battle,
                    allowed_phase=excluded.allowed_phase,params_json=excluded.params_json,enabled=1
                """,
                (
                    skill["key"], pack_key, skill.get("name", skill["key"]),
                    skill.get("description", ""), skill.get("unlock"), skill["handler"],
                    int(skill.get("max_uses", 1)), skill.get("allowed_phase"),
                    _json(skill.get("params", {})),
                ),
            )

    @staticmethod
    def _load_encounters(
        connection: Any, pack_key: str, encounters: list[dict[str, Any]]
    ) -> None:
        for encounter in encounters:
            connection.execute(
                """
                INSERT INTO encounters(
                    encounter_key,pack_key,name,description,abnormalities_json,
                    enabled,updated_at
                ) VALUES(?,?,?,?,?,1,CURRENT_TIMESTAMP)
                ON CONFLICT(encounter_key) DO UPDATE SET
                    pack_key=excluded.pack_key,name=excluded.name,
                    description=excluded.description,
                    abnormalities_json=excluded.abnormalities_json,
                    enabled=1,updated_at=CURRENT_TIMESTAMP
                """,
                (
                    encounter["key"], pack_key,
                    encounter.get("name", encounter["key"]),
                    encounter.get("description", ""),
                    _json(encounter.get("abnormalities", [])),
                ),
            )
            connection.execute(
                "DELETE FROM encounter_stages WHERE encounter_key=?",
                (encounter["key"],),
            )
            for stage_number, stage in enumerate(encounter.get("stages", []), 1):
                cursor = connection.execute(
                    """
                    INSERT INTO encounter_stages(
                        encounter_key,stage_number,name,description,
                        clear_condition_json,clear_outcome
                    ) VALUES(?,?,?,?,?,?)
                    """,
                    (
                        encounter["key"], stage_number,
                        stage.get("name", f"Stage {stage_number}"),
                        stage.get("description", ""),
                        _json(stage.get("clear_when", {"type": "ALL_ENEMIES_DEFEATED"})),
                        str(stage.get(
                            "on_clear",
                            "VICTORY" if stage_number == len(encounter.get("stages", []))
                            else "NEXT_STAGE",
                        )).upper(),
                    ),
                )
                stage_id = int(cursor.lastrowid)
                for position, enemy in enumerate(stage.get("enemies", [])):
                    connection.execute(
                        """
                        INSERT INTO encounter_stage_enemies(
                            stage_id,template_key,amount,display_name,position,enemy_key
                        ) VALUES(?,?,?,?,?,?)
                        """,
                        (
                            stage_id, enemy["template"], int(enemy.get("count", 1)),
                            enemy.get("name"), position,
                            str(enemy.get("id", f"enemy_{position + 1}")),
                        ),
                    )
