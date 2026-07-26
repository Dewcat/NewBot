from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from .models import BattleEventSnapshot, BattleRuleError


@dataclass(slots=True)
class EffectExecutionContext:
    engine: Any
    connection: Any
    battle_id: int
    actor_id: int | None
    target_ids: list[int]
    params: dict[str, Any]
    snapshot: BattleEventSnapshot | None
    messages: list[str]
    recursion_depth: int = 0
    event: str | None = None
    hook_owner_id: int | None = None


class SpecialEffectHandler(Protocol):
    def __call__(self, context: EffectExecutionContext) -> None: ...


class SpecialEffectRegistry:
    """Named strategy registry used by skills, pages and manager abilities."""

    def __init__(self) -> None:
        self._handlers: dict[str, SpecialEffectHandler] = {}

    def register(
        self, key: str, handler: SpecialEffectHandler | None = None
    ) -> SpecialEffectHandler | Callable[[SpecialEffectHandler], SpecialEffectHandler]:
        normalized = key.strip().lower()

        def decorator(candidate: SpecialEffectHandler) -> SpecialEffectHandler:
            if normalized in self._handlers:
                raise ValueError(f"特殊效果处理器重复注册: {normalized}")
            self._handlers[normalized] = candidate
            return candidate

        return decorator(handler) if handler is not None else decorator

    def execute(self, key: str, context: EffectExecutionContext) -> None:
        handler = self._handlers.get(key.strip().lower())
        if handler is None:
            raise BattleRuleError(f"未登记的特殊机制：{key}")
        handler(context)

    def contains(self, key: str) -> bool:
        return key.strip().lower() in self._handlers

    @property
    def keys(self) -> tuple[str, ...]:
        return tuple(sorted(self._handlers))
