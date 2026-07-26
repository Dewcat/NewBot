from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class Faction(StrEnum):
    FRIENDLY = "FRIENDLY"
    ENEMY = "ENEMY"


class BattlePhase(StrEnum):
    BATTLE_START = "BATTLE_START"
    STAGE_SELECTION = "STAGE_SELECTION"
    TURN_START = "TURN_START"
    FRIENDLY_ACTION = "FRIENDLY_ACTION"
    ENEMY_ACTION = "ENEMY_ACTION"
    TURN_END = "TURN_END"
    STAGE_END = "STAGE_END"
    BATTLE_END = "BATTLE_END"


class SkillType(StrEnum):
    NORMAL = "NORMAL"
    EGO = "EGO"


class Timing(StrEnum):
    TURN_START = "TURN_START"
    PRE = "PRE"
    ON = "ON"
    POST = "POST"
    TURN_END = "TURN_END"


class BattleEvent(StrEnum):
    TURN_START = "TURN_START"
    BEFORE_DAMAGE = "ON_BEFORE_DAMAGE"
    HIT = "ON_HIT"
    CRIT = "ON_CRIT"
    AFTER_DAMAGE = "ON_AFTER_DAMAGE"
    KILL = "ON_KILL"
    ACTION_END = "ON_ACTION_END"
    TURN_END = "TURN_END"


class TriggerCondition(StrEnum):
    ALWAYS = "ALWAYS"
    ON_HIT = "ON_HIT"
    ON_CRIT_HIT = "ON_CRIT_HIT"
    ON_CRIT_TRIGGER = "ON_CRIT_TRIGGER"
    ON_KILL = "ON_KILL"
    ON_CRIT_KILL = "ON_CRIT_KILL"
    ON_KILL_SELECTED_TARGET = "ON_KILL_SELECTED_TARGET"
    ON_NO_KILL_SELECTED_TARGET = "ON_NO_KILL_SELECTED_TARGET"
    ON_KILL_ALLY = "ON_KILL_ALLY"
    ON_KILL_ENEMY = "ON_KILL_ENEMY"


class TriggerScope(StrEnum):
    PER_SKILL = "PER_SKILL"
    PER_TARGET = "PER_TARGET"
    PER_HIT = "PER_HIT"


class TargetScope(StrEnum):
    SELF = "SELF"
    FRIENDLY = "FRIENDLY"
    ENEMY = "ENEMY"
    ALL = "ALL"


class TargetMethod(StrEnum):
    SELF = "SELF"
    SELECT_TARGET = "SELECT_TARGET"
    ALL_TARGETS = "ALL_TARGETS"
    RANDOM = "RANDOM"


class TargetSource(StrEnum):
    INHERIT_SKILL = "INHERIT_SKILL"
    AUTO = "AUTO"


class EffectType(StrEnum):
    DAMAGE = "DAMAGE"
    HEAL = "HEAL"
    APPLY_EFFECT = "APPLY_EFFECT"
    SPECIAL = "SPECIAL"


class EffectCategory(StrEnum):
    REGULAR = "REGULAR"
    GENERIC = "GENERIC"
    SPECIAL = "SPECIAL"
    INSTANT = "INSTANT"


# 引擎按内置 key 硬编码结算的两类效果（todo.txt 规则B）。
# REGULAR 是封闭集合：内容包不得声明集合之外的常规效果。
GENERIC_EFFECTS = frozenset(
    {
        "status.strength",
        "status.weakness",
        "status.guard",
        "status.shield",
        "status.vulnerable",
        "status.paralysis",
    }
)
REGULAR_EFFECTS = frozenset(
    {
        "status.burn",
        "status.poison",
        "status.bleeding",
        "status.rupture",
        "status.breathing",
    }
)


@dataclass(slots=True)
class RollResult:
    total: int
    expression: str
    detail: str
    dice: list[tuple[int, int]] = field(default_factory=list)
    positive_coins: int = 0
    negative_coins: int = 0


@dataclass(slots=True)
class HitSnapshot:
    behavior_id: int | None
    hit_index: int
    target_id: int
    hit: bool = True
    critical: bool = False
    damage: int = 0
    healing: int = 0
    killed: bool = False
    target_faction: Faction | None = None
    damage_source: str = "SKILL"
    source_key: str | None = None
    source_character_id: int | None = None
    killer_id: int | None = None


@dataclass(slots=True)
class BattleEventSnapshot:
    battle_id: int
    actor_id: int | None
    skill_id: int | None
    skill_target_ids: list[int]
    hits: list[HitSnapshot] = field(default_factory=list)
    killed_character_ids: list[int] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def any_hit(self) -> bool:
        return any(hit.hit for hit in self.hits)

    @property
    def any_critical(self) -> bool:
        return any(hit.critical for hit in self.hits)

    @property
    def any_kill(self) -> bool:
        return bool(self.killed_character_ids)


@dataclass(frozen=True, slots=True)
class ActionResult:
    battle_id: int
    actor_id: int
    skill_id: int
    messages: tuple[str, ...]
    phase: BattlePhase

    @property
    def text(self) -> str:
        return "\n".join(self.messages)


class BattleRuleError(RuntimeError):
    """Raised when a requested action violates battle rules."""


class ContentValidationError(ValueError):
    """Raised when a content pack is structurally invalid."""
