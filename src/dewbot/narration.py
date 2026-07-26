from __future__ import annotations

from .models import BattlePhase


EFFECT_NAMES = {
    "status.strength": "强壮",
    "status.weakness": "虚弱",
    "status.guard": "守护",
    "status.shield": "护盾",
    "status.vulnerable": "易伤",
    "status.paralysis": "麻痹",
    "status.burn": "烧伤",
    "status.poison": "中毒",
    "status.bleeding": "流血",
    "status.rupture": "破裂",
    "status.breathing": "呼吸法",
    "status.hardblood": "硬血",
}


class Narrator:
    """Compact battle prose inspired by dossier-style tactical RPG UIs."""

    @staticmethod
    def battle_started(battle_id: int, total_stages: int) -> str:
        del total_stages  # 阶段总数不播报（2026-07-27 反馈）
        return f"【战斗 #{battle_id} 开始】"

    @staticmethod
    def turn_started(turn: int) -> str:
        return f"【第 {turn} 回合】"

    @staticmethod
    def phase_changed(phase: BattlePhase) -> str:
        if phase == BattlePhase.FRIENDLY_ACTION:
            return "▣ 我方行动阶段"
        if phase == BattlePhase.ENEMY_ACTION:
            return "▣ 敌方行动阶段"
        if phase == BattlePhase.TURN_END:
            return "【回合结束】"
        if phase == BattlePhase.STAGE_END:
            return "【阶段结束】"
        if phase == BattlePhase.BATTLE_END:
            return "【战斗结束】"
        return f"【战斗阶段：{phase.value}】"

    @staticmethod
    def skill(actor: str, skill: str, ego: bool = False) -> str:
        mark = "使用 E.G.O" if ego else "使用"
        return f"{actor}｜{mark}「{skill}」"

    @staticmethod
    def damage(
        target: str, formula: str, detail: str, damage: int, critical: bool,
        modifiers: str = "",
    ) -> str:
        critical_text = "〔暴击〕" if critical else ""
        modifier_text = f"（{modifiers}）" if modifiers else ""
        return (
            f"└ {target} {critical_text}承受 {formula}={detail}"
            f"{modifier_text} → {damage} 点伤害"
        )

    @staticmethod
    def fixed_damage(target: str, effect_name: str, damage: int) -> str:
        return f"└ {target} 受到「{effect_name}」固定伤害：{damage}"

    @staticmethod
    def heal(target: str, amount: int) -> str:
        return f"└ {target} 恢复了 {amount} 点生命"

    @staticmethod
    def effect(target: str, effect_key: str, intensity: int, stacks: int = 0) -> str:
        # 表述形如「获得1层3级破裂」；无层数/强度时省略对应部分。
        name = EFFECT_NAMES.get(effect_key, effect_key)
        prefix = ""
        if stacks:
            prefix += f"{stacks}层"
        if intensity:
            prefix += f"{intensity}级"
        return f"└ {target} 获得{prefix}「{name}」"

    @staticmethod
    def stack_consumed(target: str, effect_key: str, remaining_stacks: int) -> str:
        name = EFFECT_NAMES.get(effect_key, effect_key)
        return f"└ {target} 的「{name}」减少1层，剩余 {remaining_stacks} 层"

    @staticmethod
    def pending_effect(target: str, effect_key: str, intensity: int) -> str:
        name = EFFECT_NAMES.get(effect_key, effect_key)
        prefix = f"{intensity}级" if intensity else ""
        return f"└ {target} 将在下回合开始获得{prefix}「{name}」"

    @staticmethod
    def resource(target: str, effect_key: str, amount: int) -> str:
        name = EFFECT_NAMES.get(effect_key, effect_key)
        return f"└ {target} 的「{name}」现为 {amount} 点"

    @staticmethod
    def staggered(target: str) -> str:
        return f"── {target} 的混乱条被击破，陷入混乱！"

    @staticmethod
    def defeated(target: str) -> str:
        return f"── {target} 倒下了，退出战斗。"
