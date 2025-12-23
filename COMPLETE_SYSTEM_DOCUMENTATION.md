# Dewbot 战斗系统完整文档

## 目录

1. [系统概述](#系统概述)
2. [角色系统](#角色系统)
3. [战斗与攻击逻辑](#战斗与攻击逻辑)
4. [技能系统](#技能系统)
5. [情感系统](#情感系统)
6. [回合系统](#回合系统)
7. [数据库系统](#数据库系统)
8. [主程序与效果集成](#主程序与效果集成)

---

# 系统概述

Dewbot 是一个基于 Telegram 平台的模块化角色扮演（RPG）机器人。它围绕一个复杂的回合制战斗系统构建，该系统支持详细的角色定制、动态的技能效果和深入的情感养成机制。本文档旨在全面概述其核心系统，包括角色管理、战斗逻辑、技能效果、回合流程和数据库结构。

---

# 角色系统

角色系统是管理游戏中所有可操作实体的核心，包括玩家角色和敌人。它支持丰富的角色定制，包括独特的"人格"系统、种族属性和动态的状态管理。

## 2.1. 核心角色与人格系统

系统预设了五个"核心角色"：**珏、露、莹、笙、曦**。这些角色拥有独特的**人格（Persona）**系统，允许他们在不同的战斗形态之间切换。

*   **人格（Persona）**：每个人格代表角色的一套特定属性、技能和战斗风格。切换人格会改变角色的生命值、攻击力、防御力以及可用的技能组合。
*   **切换机制**：玩家可以通过 `/switch` 或 `/persona` 命令为核心角色切换人格，以适应不同的战斗需求。

## 2.2. 角色属性

每个角色都有一系列基础属性，定义了其在战斗中的能力：

*   **核心属性**：生命值（Health）、攻击力（Attack）、防御力（Defense）。
*   **战斗属性**：
    *   `in_battle`：标记角色是否在战斗中。
    *   `actions_per_turn`：每回合的行动次数。
    *   `current_actions`：当前剩余的行动次数。
*   **种族与抗性**：
    *   `race_tags`：角色的种族标签，用于触发特定的技能效果。
        *   **支持的种族**：human (人类), elf (精灵), dwarf (矮人), orc (兽人), dragon (龙), demon (恶魔), angel (天使), beast (野兽), undead (亡灵), machine (机械), elemental (元素), construct (构装体), fey (妖精), giant (巨人), goblinoid (哥布林)。
    *   `physical_resistance` / `magic_resistance`：物理和魔法抗性，用于减免相应类型的伤害。
        *   **计算公式**：`减伤倍率 = 1.0 - min(resistance, 0.9)`（最多减伤 90%）。
*   **情感系统属性**：详见[情感系统](#情感系统)章节。
*   **混乱值（Stagger）**：
    *   每个角色拥有 `stagger_value` (当前混乱值) 和 `max_stagger_value` (最大混乱值)。
    *   受到伤害时，混乱值会相应扣除。
    *   当混乱值归零时，角色进入**混乱状态 (Staggered)**：
        *   持续 **2 回合**。
        *   行动次数清零（无法行动）。
        *   受到的伤害提升至 **200%**。
        *   状态结束后，混乱值回满。

## 2.3. 状态效果详解

状态效果（Buffs/Debuffs）是战斗系统的关键变量，遵循以下核心规则：

*   **叠加规则**：
    *   **强度 (Intensity)**：取新旧效果中的最大值 (`max(old, new)`)。
    *   **层数/持续时间 (Duration)**：新旧效果层数相加 (`old + new`)。
    *   **特殊情况**：如果新增效果的 `duration` 为 0：
        *   若已有该效果，只更新强度，不增加层数。
        *   若无该效果，层数默认设为 1。

*   **特殊状态机制**：
    *   **加速 (Haste)**：
        *   获得时**立即**增加当前行动次数和每回合行动上限。
        *   强度固定为 1，持续期间保持 +1 行动次数。
        *   回合结束时层数 -1。
    *   **麻痹 (Paralysis)**：
        *   在伤害计算时，每个麻痹层数会使一个伤害骰子的结果归零。
        *   每归零一个骰子，消耗 1 层麻痹。
    *   **硬血 (Hardblood)**：
        *   一种特殊的资源型状态，强度代表数量，层数固定。
        *   可被特定技能消耗以造成额外伤害 (`HardbloodConsumeDamage`)。
    *   **黑夜领域 (Dark Domain)**：
        *   持续 3 回合。
        *   **回合结束效果**：获得 6级强壮(1回合)、6级易伤(1回合)、1级加速(下回合)、666点负面情感硬币。
        *   **特殊效果**：免疫一次致死伤害（触发后移除领域，HP变为1）。
    *   **削弱光环 (Weaken Aura)**：
        *   持续 5 回合。
        *   **回合结束效果**：对所有敌方施加 5级虚弱(1回合) 和 5级易伤(1回合)。

## 2.4. 角色管理命令

系统提供了一系列 Telegram 命令来管理角色：

| 命令 | 别名 | 功能描述 |
| :--- | :--- | :--- |
| `/create_character` | `/cc` | 创建一个新的友方角色。 |
| `/create_enemy` | `/ce` | 创建一个新的敌方角色。 |
| `/characters` | `/chars` | 显示所有友方角色列表。 |
| `/enemies` | | 显示所有敌方角色列表。 |
| `/show` | `/panel` | 显示指定角色的详细状态面板。 |
| `/race <角色名>` | | 管理角色的种族标签和抗性。 |
| `/health <角色名> <值>`| | 直接修改角色的当前生命值。 |
| `/reset <角色名>` | | 重置单个角色的状态，包括生命、行动次数和情感。 |
| `/reset_all` | | 重置所有角色的状态。 |
| `/create_core <角色名>`| | 创建一个核心角色（珏、露、莹、笙、曦）。 |
| `/switch <角色名> <人格>`| `/persona` | 切换核心角色的人格。 |
| `/personas <角色名>` | | 查看指定核心角色的可用人格列表。 |

---

# 战斗与攻击逻辑

攻击逻辑是战斗系统的核心交互，通过对话式界面引导用户完成攻击、治疗和使用技能的完整流程。

## 3.1. 攻击流程

系统支持对友方 (`/attack`) 和敌方 (`/enemy`) 的攻击，流程相似但目标相反。

### 友方攻击流程 (`/attack`)

**1. 选择攻击者** (`start_attack`)
- 获取有行动次数的友方角色
- 显示角色选择键盘
- 返回 `SELECTING_ATTACKER` 状态

**2. 处理攻击者选择** (`select_attacker`)
- 解析选择并获取角色信息
- 获取技能列表（过滤冷却和情感等级）
- 显示技能选择界面或使用普通攻击
- 返回 `SELECTING_SKILL` 状态

**技能图标说明**：
- ⚔️ 伤害技能
- 💚 治疗技能
- ✨ 增益技能
- 💀 减益技能
- 🧘 自我技能
- 🌀 AOE技能

**3. 处理技能选择** (`select_skill`)
- 验证技能状态（冷却、情感等级）
- 进入目标选择流程

**4. 显示目标选择** (`show_target_selection`)
- 根据技能类型确定目标：
  - **治疗/增益技能**：选择友方角色
  - **减益技能**：选择敌方角色
  - **伤害技能**：选择敌方角色
  - **自我技能**：直接执行，无需选择
  - **AOE技能**：直接执行，无需选择

**目标显示格式**：
```
[角色名] ([当前生命]/[最大生命]) [状态图标]
```

**状态图标**：
- 💀 已死亡
- 💚 80%+ 生命
- 💛 50-79% 生命
- 🧡 20-49% 生命
- ❤️ <20% 生命

**5. 处理目标选择** (`select_target`)
- 解析目标ID
- 调用 `execute_attack()` 执行攻击

**6. 执行攻击** (`execute_attack`)
- 验证角色和技能状态
- 执行技能效果
- 消耗行动次数
- 返回战斗结果

### 敌方攻击流程 (`/enemy`)

敌方攻击流程与友方类似，主要差异：
- **权限控制**：只有发起命令的用户可操作
- **技能显示**：技能按钮只显示编号，详情通过弹窗显示
- **目标相反**：选择友方目标

### 技能效果执行

**函数**：`execute_skill_effect(attacker, target, skill_info)`

**消息格式化**：
```python
{
    'aoe_damage': '💥 群体攻击结果 💥',
    'aoe_healing': '💚 群体治疗结果 💚',
    'aoe_buff': '✨ 群体强化结果 ✨',
    'aoe_debuff': '💀 群体削弱结果 💀',
    'self': '🧘 自我强化结果 🧘',
    'healing': '💚 治疗结果 💚',
    'buff': '✨ 强化结果 ✨',
    'debuff': '💀 削弱结果 💀',
    'damage': '⚔️ 战斗结果 ⚔️'
}
```

**状态显示逻辑**：
- **AOE技能**：显示所有相关目标的状态
- **单体技能**：显示目标的生命值状态
- **特殊技能**：只显示效果完成信息

## 3.2. 会话处理器

### 友方攻击处理器 (`get_attack_conv_handler()`)
```python
ConversationHandler(
    entry_points=[CommandHandler("attack", start_attack)],
    states={
        SELECTING_ATTACKER: [CallbackQueryHandler(select_attacker, pattern=r"^attacker_\d+$")],
        SELECTING_TARGET: [CallbackQueryHandler(select_target, pattern=r"^target_\d+$")],
        SELECTING_SKILL: [CallbackQueryHandler(select_skill, pattern=r"^skill_\d+$")]
    },
    fallbacks=[CommandHandler("cancel", cancel_attack)],
    name="attack",
    per_user=False
)
```

### 敌方攻击处理器 (`get_enemy_attack_conv_handler()`)
```python
ConversationHandler(
    entry_points=[CommandHandler("enemy", start_enemy_attack)],
    states={
        ENEMY_SELECTING_ATTACKER: [CallbackQueryHandler(enemy_select_attacker, pattern=r"^enemy_attacker_\d+$")],
        ENEMY_SELECTING_TARGET: [CallbackQueryHandler(enemy_select_target, pattern=r"^enemy_target_\d+$")],
        ENEMY_SELECTING_SKILL: [CallbackQueryHandler(enemy_select_skill, pattern=r"^enemy_skill_\d+$")]
    },
    fallbacks=[CommandHandler("cancel", cancel_enemy_attack)],
    name="enemy_attack",
    per_user=True  # 每个用户独立会话
)
```

## 3.3. 回调数据格式

### 友方攻击
- `attacker_{角色ID}`：选择攻击者
- `skill_{技能ID}`：选择技能
- `target_{角色ID}`：选择目标

### 敌方攻击
- `enemy_attacker_{角色ID}`：选择敌方攻击者
- `enemy_skill_{技能ID}`：选择敌方技能
- `enemy_target_{角色ID}`：选择敌方目标

## 3.4. 验证机制

### 角色状态验证
- **存在性检查**：确保角色在数据库中存在
- **战斗状态**：`in_battle = True`
- **生命值**：`health > 0`
- **行动次数**：`current_actions > 0`

### 技能状态验证
- **冷却检查**：通过 `is_skill_on_cooldown()`
- **情感等级**：通过 `check_skill_emotion_requirement()`
- **存在性**：确保技能在数据库中存在

---

# 技能系统

技能系统负责定义和执行所有战斗动作的效果，包括伤害计算、状态应用和资源管理。系统采用模块化设计，支持多种技能类型和复杂的伤害计算公式。

## 4.1. 核心类：SkillEffect

### 类结构
```python
class SkillEffect(ABC):
    def execute(self, attacker, target, skill_info):
        # 根据技能分类选择处理方式
        skill_category = skill_info.get('skill_category', 'damage')
        
        if skill_category == 'healing':
            return self.execute_healing(attacker, target, skill_info)
        elif skill_category == 'buff':
            return self.execute_buff(attacker, target, skill_info)
        # ... 其他技能类型
```

## 4.2. 技能类型分类

| 类别 | 英文标识 | 描述 |
| :--- | :--- | :--- |
| 伤害技能 | `damage` | 对目标造成直接伤害。 |
| 治疗技能 | `healing` | 恢复目标的生命值。 |
| 增益技能 | `buff` | 为目标施加正面状态效果。 |
| 减益技能 | `debuff` | 为目标施加负面状态效果。 |
| 自我技能 | `self` | 仅对施法者自身生效。 |
| 范围技能 | `aoe_*` | 对多个目标（所有友方或所有敌方）同时生效。 |

### 伤害技能 (damage)

**详细计算公式**：

最终伤害计算遵循以下流水线：

1.  **基础伤害 (Base Damage)**:
    *   `Dice Roll` (骰子结果) + `Fixed Value` (固定值)
    *   **注意**：若攻击者处于麻痹状态，每个麻痹层数会使一个骰子结果归零。

2.  **追加伤害 (Additional Damage)**:
    *   来自技能特效（如硬血消耗、条件增伤）。
    *   `Total Base Damage` = `Base Damage` + `Additional Damage`

3.  **攻防修正 (Attack/Defense Modifier)**:
    *   `Modifier` = `Attacker.Attack` / `Target.Defense`

4.  **种族特攻 (Race Bonus)**:
    *   若技能有 `special_damage_tags` 且命中对应种族。
    *   `Bonus` = `Tag Multiplier` (例如 1.5 或 2.0)

5.  **抗性减免 (Resistance Reduction)**:
    *   根据伤害类型 ('physical'/'magic') 读取目标抗性。
    *   `Reduction` = `1.0 - min(Target.Resistance, 0.9)`
    *   **即最多减伤 90%，最少造成 10% 伤害。**

6.  **混乱加成 (Stagger Multiplier)**:
    *   若目标处于混乱状态。
    *   `Multiplier` = `2.0`

**最终公式**:
$$
FinalDamage = TotalBase \times \frac{Atk}{Def} \times RaceBonus \times ResistanceReduction \times StaggerMultiplier
$$
*(结果向下取整，且最小为 1)*

**执行流程**：
1. 计算基础伤害（骰子公式+固定值）
2. 计算追加伤害（通过效果系统）
3. 合并伤害值
4. 应用攻击者状态效果修正（暴击等）
5. 应用目标受击状态效果（护盾等）
6. 应用最终伤害
7. 处理混乱值
8. 应用技能状态效果
9. 处理行动后效果
10. 更新冷却时间

**返回值**：
```python
{
    'total_damage': int,      # 总伤害值
    'result_text': str,       # 战斗结果文本
    'target_health': int      # 目标剩余生命值
}
```

### 治疗技能 (healing)
- 不受攻防和抗性影响
- 可以使用骰子公式计算治疗量
- 支持自我治疗和队友治疗

### 增益技能 (buff)
- 不造成伤害
- 主要用于施加buff效果
- 支持多种buff类型

### 减益技能 (debuff)
- 不造成伤害
- 主要用于施加debuff效果
- 支持多种debuff类型

### 自我技能 (self)
- 目标始终是施法者自己
- 常用于自我强化

### 范围技能 (AOE)
**子类型**：
- `aoe_damage`: 对所有敌方造成伤害
- `aoe_healing`: 对所有友方进行治疗
- `aoe_buff`: 对所有友方施加增益
- `aoe_debuff`: 对所有敌方施加减益

## 4.3. 伤害计算系统

### 骰子公式解析

**支持格式**：
- `"5+2d3"` → 基础值5 + 2个3面骰子
- `"1d6"` → 1个6面骰子
- `"10"` → 固定值10
- `"3d4+2"` → 3个4面骰子 + 2

**解析函数**：`parse_dice_formula(formula)`
**投掷函数**：`roll_dice(num_dice, faces)`

### 伤害修正计算

#### 1. 攻防修正
```python
def calculate_attack_defense_modifier(attacker_attack, target_defense):
    attack_defense_diff = attacker_attack - target_defense
    modifier = 1.0 + (attack_defense_diff * 0.02)  # 每差1点攻防，伤害变化2%
    return max(0.1, modifier)  # 最少造成10%伤害
```

#### 2. 种族特攻
```python
def calculate_race_bonus(special_damage_tags, target_race_tags):
    # 技能特攻标签如 {"human": 1.5, "dragon": 2.0}
    # 目标种族标签如 ["human", "warrior"]
    max_bonus = 1.0
    for race in target_race_tags:
        if race in special_damage_tags:
            bonus = special_damage_tags[race]
            max_bonus = max(max_bonus, bonus)
    return max_bonus
```

#### 3. 抗性减伤
```python
def calculate_resistance_reduction(damage_type, target_resistances):
    resistance = target_resistances.get(damage_type, 0.0)
    reduction_multiplier = 1.0 - min(resistance, 0.9)  # 最多减伤90%
    return max(0.1, reduction_multiplier)  # 最少造成10%伤害
```

#### 4. 混乱状态加成
- 混乱状态下伤害提升至200%
- 通过 `stagger_manager.get_stagger_damage_multiplier()` 计算
- **重置规则**：混乱值和混乱状态会在"阶段结束 (Stage End)"和"战斗结束 (Battle End)"时重置。

## 4.4. 状态效果应用详解

**函数**：`apply_skill_status_effects(attacker, target, skill_info, main_effect_value)`

### 1. 增益效果 (Buffs)

| 效果名称 | 代码标识 | 图标 | 效果描述 | 持续/衰减机制 |
| :--- | :--- | :--- | :--- | :--- |
| **强壮** | `strong` | 💪 | 攻击造成的最终伤害增加 `强度 × 10%`。 | 回合结束时持续时间 -1。 |
| **呼吸法** | `breathing` | 🫁 | 暴击率增加 `强度%`。若因此触发暴击，造成 120% 伤害。 | 回合结束时持续时间 -1。 |
| **守护** | `guard` | ☂ | 受到的最终伤害减少 `强度 × 10%`。 | 回合结束时持续时间 -1。 |
| **护盾** | `shield` | 🛡️ | 抵挡等同于强度的伤害。抵挡后强度减少。 | 持续时间不随回合减少，直到强度耗尽或被驱散。 |
| **加速** | `haste` | 🚀 | 立即增加 1 点当前行动次数和每回合行动上限。 | 回合结束时持续时间 -1。效果结束时扣除增加的上限。 |

### 2. 减益效果 (Debuffs)

| 效果名称 | 代码标识 | 图标 | 效果描述 | 持续/衰减机制 |
| :--- | :--- | :--- | :--- | :--- |
| **烧伤** | `burn` | 🔥 | 回合结束时受到 `强度 × 1` 点伤害。 | 回合结束时持续时间 -1。 |
| **中毒** | `poison` | ☠️ | 回合结束时受到 `当前生命值 × 强度%` 点伤害 (最少1点)。 | 回合结束时持续时间 -1。 |
| **破裂** | `rupture` | 💥 | 受到攻击时，额外受到 `强度 × 1` 点伤害。 | 每次触发后持续时间 -1 (不随回合自动减少)。 |
| **流血** | `bleeding` | 🩸 | 每次行动后，受到 `强度 × 1` 点伤害。 | 每次触发后持续时间 -1 (不随回合自动减少)。 |
| **虚弱** | `weak` | 😵 | 攻击造成的最终伤害减少 `强度 × 10%`。 | 回合结束时持续时间 -1。 |
| **易伤** | `vulnerable` | 💔 | 受到的最终伤害增加 `强度 × 10%`。 | 回合结束时持续时间 -1。 |
| **麻痹** | `paralysis` | ⚡ | 投掷伤害骰子时，`min(骰子数, 麻痹层数)` 个骰子结果归零。 | 每次归零骰子后，层数(强度)相应减少 (不随回合自动减少)。 |

### 3. 其他效果 (Other Effects)

| 效果名称 | 代码标识 | 效果描述 |
| :--- | :--- | :--- |
| **冷却缩减** | `cooldown_reduction` | **立即**减少所有处于冷却中技能的冷却时间 `intensity` 回合。若冷却归零，技能立即可用。 |
| **吸血** | `vampiric` | 将造成伤害的 `percentage`% 转化为**硬血** (Hardblood) 而非直接治疗。 |
| **自我伤害** | `self_damage` | 施法者受到 `amount` 或 `percentage`% 效果值的反噬伤害。 |
| **自我治疗** | `self_heal` | 施法者恢复 `amount` 或 `percentage`% 效果值的生命值。 |

### 4. 特殊效果 (Special Effects)

| 效果名称 | 代码标识 | 图标 | 效果描述 | 机制 |
| :--- | :--- | :--- | :--- | :--- |
| **硬血** | `hardblood` | 🩸 | 特殊资源池，可被特定技能消耗以增强伤害、获得护盾或增强AOE。 | 持续时间无限，仅通过消耗减少。 |
| **黑夜领域** | `dark_domain` | 🌑 | 1. **回合结束时**：获得 6级强壮(1回合)、6级易伤(1回合)、1级加速(下回合)、666点负面情感硬币。<br>2. **死亡免疫**：免疫一次致死伤害（触发后移除领域，HP变为1）。<br>3. **条件增伤**：增强特定技能伤害。 | 持续 3 回合，回合结束时持续时间 -1。 |
| **削弱光环** | `weaken_aura` | 💜 | **回合结束时**：对所有敌方施加 5级虚弱(1回合) 和 5级易伤(1回合)。 | 持续 5 回合 (注: 当前代码实现中暂无自动衰减)。 |

**效果配置格式**：
```json
{
  "buff": {
    "type": "strong",
    "intensity": 1,
    "duration": 3
  },
  "debuff": {
    "type": "poison",
    "intensity": 2,
    "duration": 2
  },
  "vampiric": {
    "percentage": 50
  },
  "self_damage": {
    "percentage": 10
  }
}
```

## 4.5. 冷却系统

### 冷却时间管理
**更新函数**：`update_character_cooldowns(character_id, skill_id)`
- 技能使用后增加冷却计数
- 每次任何角色行动时，所有角色的技能冷却-1

**检查函数**：
- `is_skill_on_cooldown(character_id, skill_id)`
- `get_skill_cooldown_remaining(character_id, skill_id)`

**存储位置**：`character.status` JSON 的 `cooldowns` 字段

## 4.6. 情感硬币系统集成

### 骰子情感硬币
- 投掷结果为1：获得负面情感硬币
- 投掷结果为最大值：获得正面情感硬币

### 伤害相关情感硬币
- 造成伤害时获得情感硬币
- 击杀目标时获得额外情感硬币

### 治疗相关情感硬币
- 进行治疗时获得情感硬币

## 4.7. AOE状态效果

**函数**：`apply_aoe_status_effects(attacker, targets, skill_info, is_friendly_skill)`

- 对所有目标统一施加状态效果
- 支持友方/敌方区分

## 4.8. 自我效果处理

**函数**：`apply_self_effects(attacker, skill_info, effect_value, skill_type)`

- 基于技能效果值计算自我影响
- 支持百分比计算（如伤害的10%作为自我伤害）

---

# 情感系统

情感系统是角色在**战斗会话（Battle Session）**中的短期成长机制，而非长期的RPG属性。角色通过在战斗中的表现获得情感硬币，提升情感等级，解锁更强大的技能和获得特殊效果。

## 5.1. 核心类：EmotionSystem

### 类结构
```python
class EmotionSystem:
    # 情感等级升级所需硬币数
    UPGRADE_REQUIREMENTS = {
        1: 3,  # 0→1级需要3个硬币
        2: 3,  # 1→2级需要3个硬币
        3: 5,  # 2→3级需要5个硬币
        4: 7,  # 3→4级需要7个硬币
        5: 9   # 4→5级需要9个硬币
    }
    
    # 正面情感升级效果池 (暂时禁用)
    POSITIVE_EMOTION_EFFECTS = []
    
    # 负面情感升级效果池 (暂时禁用)
    NEGATIVE_EMOTION_EFFECTS = []
```

## 5.2. 情感硬币与重置

### 生命周期
*   **战斗结束 (Battle End)**：情感等级和硬币**重置为 0**。
*   **阶段结束 (Stage End)**：情感等级和硬币**保留**，延续到下一阶段的战斗中。

## 5.3. 硬币获取来源

### 1. 骰子投掷结果
**函数**：`get_emotion_coins_from_dice_roll(dice_results, dice_sides)`

**规则**：
- **正面硬币**：投掷结果等于骰子最大值时获得
- **负面硬币**：投掷结果等于1时获得

**示例**：
- 投掷3d6得到[1,3,6] → 获得1个负面硬币 + 1个正面硬币
- 投掷2d4得到[2,4] → 获得1个正面硬币

### 2. 伤害相关
- 造成伤害时获得情感硬币
- 击杀目标时获得额外情感硬币

### 3. 治疗相关
- 进行治疗时获得情感硬币

## 5.4. 硬币添加流程

**函数**：`add_emotion_coins(character_id, positive_coins, negative_coins, source)`

**执行流程**：
1. **检查角色状态**
   - 验证角色是否存在
   - 检查是否已达到最大等级（5级）
   - 检查是否已有待升级状态

2. **添加硬币**
   - 累加正面和负面硬币数量
   - 计算总硬币数

3. **检查升级条件**
   - 根据当前等级计算目标等级
   - 检查总硬币是否满足升级要求
   - 设置 `pending_emotion_upgrade` 标志

4. **更新数据库**
   - 更新角色硬币数量
   - 记录硬币获得历史

**返回值**：
```python
{
    'success': bool,
    'coins_added': bool,
    'positive_coins_added': int,
    'negative_coins_added': int,
    'total_positive': int,
    'total_negative': int,
    'upgrade_pending': bool,
    'target_level': int or None,
    'message': str
}
```

## 5.5. 情感等级升级

### 升级触发时机
- 在回合开始时自动处理
- 通过 `process_turn_start_emotion_upgrades()` 函数执行

### 升级流程

**函数**：`_execute_emotion_upgrade(character_id, name, current_level, pos_coins, neg_coins)`

**执行步骤**：
1. **确定升级类型**
   - 正面升级：正面硬币 > 负面硬币
   - 负面升级：负面硬币 ≥ 正面硬币

2. **选择升级效果**
   - 从对应的效果池中随机选择
   - 当前效果池为空（暂时禁用增益效果）

3. **执行升级**
   - 提升情感等级
   - 清空所有硬币
   - 重置待升级标志

4. **应用升级奖励**
   - 降低所有技能冷却时间1回合
   - 添加情感效果（如果有）

5. **记录升级历史**
   - 保存到 `emotion_level_history` 表

### 升级奖励

#### 1. 技能冷却减少
- 所有技能冷却时间 -1 回合
- 通过 `_reduce_all_skill_cooldowns()` 实现

#### 2. 情感效果（暂时禁用）
- 从效果池中随机获得永久效果
- 效果类型包括强壮、守护等
- **注意**：当前代码中 `POSITIVE_EMOTION_EFFECTS` 和 `NEGATIVE_EMOTION_EFFECTS` 列表为空，因此升级时不会获得额外效果，仅获得冷却缩减。

## 5.6. 情感效果应用

### 回合开始效果
**函数**：`apply_turn_start_emotion_effects(character_id)`

**执行流程**：
1. 查询角色的情感效果（从 `character_emotion_effects` 表）
2. 为每个效果添加对应的状态效果
3. 持续时间为1回合（每回合刷新）

**支持效果**：
- `strong`: 强壮状态 (获得 `intensity` 层)
- `guard`: 守护状态 (获得 `intensity` 层)

## 5.7. 技能等级要求

**检查函数**：`check_skill_emotion_requirement(character_id, skill_info)`

**逻辑**：
1. 检查技能是否设置了 `required_emotion_level`
2. 比较角色当前情感等级
3. 返回是否满足要求及错误信息

**使用场景**：
- 技能选择时检查
- 防止低等级角色使用高级技能

## 5.8. 数据库表结构

### characters 表扩展字段
```sql
emotion_level INTEGER DEFAULT 0,              -- 当前情感等级
positive_emotion_coins INTEGER DEFAULT 0,     -- 正面情感硬币
negative_emotion_coins INTEGER DEFAULT 0,     -- 负面情感硬币
pending_emotion_upgrade INTEGER DEFAULT 0     -- 待升级标志
```

### emotion_coin_log 表
```sql
character_id INTEGER,
positive_coins INTEGER,
negative_coins INTEGER,
source TEXT,              -- 硬币来源
total_after INTEGER,      -- 添加后的总硬币数
timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
```

### emotion_level_history 表
```sql
character_id INTEGER,
old_level INTEGER,
new_level INTEGER,
upgrade_type TEXT,        -- 'positive' 或 'negative'
positive_coins INTEGER,
negative_coins INTEGER,
timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
```

### character_emotion_effects 表
```sql
character_id INTEGER,
effect_type TEXT,         -- 'buff' 或 'debuff'
effect_name TEXT,         -- 效果名称
intensity INTEGER         -- 效果强度
```

## 5.9. 情感等级详情

| 等级 | 升级所需硬币 | 累计硬币需求 | 解锁内容 |
|------|-------------|-------------|----------|
| 1 | 3 | 3 | 基础技能解锁 |
| 2 | 3 | 6 | 中级技能解锁 |
| 3 | 5 | 11 | 高级技能解锁 |
| 4 | 7 | 18 | 专家技能解锁 |
| 5 | 9 | 27 | 顶级技能解锁 |

## 5.10. 便捷函数

```python
from character.emotion_system import (
    add_emotion_coins,
    process_emotion_upgrades,
    apply_emotion_effects,
    check_skill_emotion_requirement
)

# 添加情感硬币
result = add_emotion_coins(1, 1, 0, "伤害目标")

# 处理升级
messages = process_emotion_upgrades()

# 应用效果
effects = apply_emotion_effects(1)

# 检查技能要求
can_use, error = check_skill_emotion_requirement(1, skill_info)
```

---

# 回合系统

回合系统负责驱动战斗流程，管理所有角色的行动顺序、状态更新和资源恢复。为了支持连续战斗，系统区分了三种结束状态。

## 6.1. 战斗终止概念 (Combat Termination Concepts)

### 1. 回合结束 (Turn End)
*   **定义**：当前战斗回合的自然结束。
*   **行为**：
    *   恢复所有角色的行动次数。
    *   (注意：技能冷却时间是基于**行动**减少的，而非回合结束时统一减少。)
    *   结算持续性伤害和治疗（HOT/DOT）。
    *   触发回合结束相关的状态效果。
*   **保留**：所有战斗状态、Status Effect、混乱值、情感等级/硬币。

### 2. 阶段结束 (Stage End)
*   **定义**：连续战斗中某一波次（Wave）的结束。
*   **行为**：
    *   **清除** 所有临时状态效果 (Buff/Debuff)。
    *   **重置** 混乱值 (Stagger) 为 0。
    *   **移除** 角色的战斗状态 (`in_battle = False`)。
    *   **保留** 当前生命值 (HP)。
    *   **保留** 情感等级和情感硬币（继承到下一阶段）。

### 3. 战斗结束 (Battle End)
*   **定义**：整个战斗会话的彻底结束（胜利、失败或手动停止）。
*   **行为**：
    *   **清除** 所有临时状态效果 (Buff/Debuff)。
    *   **重置** 混乱值 (Stagger) 为 0。
    *   **移除** 角色的战斗状态 (`in_battle = False`)。
    *   **重置** 情感等级和情感硬币为 0。
    *   **保留** 当前生命值 (HP)。

## 6.2. 核心类：TurnManager

### 类结构
```python
class TurnManager:
    def __init__(self):
        self.current_turn = 0
```

### 主要方法

#### 1. end_turn_for_character(character_id: int) -> List[str]
**功能**：结束指定角色的回合，处理状态效果，并开始新回合

**执行流程**：
1. **获取角色初始状态**
   - 查询角色当前生命值
   - 记录初始健康状态

2. **处理回合结束效果**
   - 调用 `process_end_turn_effects(character_id)`
   - 处理所有在回合结束时触发的状态效果（如中毒伤害、持续伤害等）

3. **检查角色死亡**
   - 如果角色在回合结束效果中生命值降至0或以下
   - 且初始生命值大于0（刚刚倒下）
   - 则停止后续处理，直接返回倒下信息

4. **处理混乱值状态**
   - 调用 `stagger_manager.process_stagger_turn(character_id)`
   - 处理混乱值积累和骰子数量减少

5. **恢复行动次数**
   - 调用 `_restore_single_character_actions(character_id)`
   - 将角色行动次数重置为每回合基础值

6. **处理情感系统回合开始效果**
   - 调用 `_process_emotion_turn_start(character_id)`
   - 应用情感系统产生的状态效果（如强壮、守护等）

**返回值**：包含所有状态效果处理结果的消息列表

#### 2. end_battle_turn() -> List[str]
**功能**：结束整个战斗回合，处理所有在战斗中角色的状态效果

**执行流程**：
1. **增加回合计数**
   - `self.current_turn += 1`

2. **获取战斗中角色**
   - 查询所有 `in_battle=True` 的友方和敌方角色

3. **处理每个角色的回合结束**
   - 对每个战斗中角色调用 `end_turn_for_character()`
   - 收集所有状态效果消息

4. **恢复所有角色行动次数**
   - 调用 `restore_character_actions()`
   - 静默恢复，不产生消息

5. **处理回合开始状态效果**
   - 对每个角色调用 `process_start_turn_effects()`
   - *当前代码实现中，加速(Haste)效果为获取时立即生效，此步骤目前保留作为扩展点。*

**返回值**：完整的回合结束报告，包括所有角色的状态变化

#### 3. reset_battle()
**功能**：执行"战斗结束 (Battle End)"逻辑，完全重置战斗状态

**执行流程**：
1. 重置回合计数器为0
2. 清除所有角色的状态效果
3. 重置混乱值 (Stagger)
4. 重置情感等级和硬币 (Battle End 特有)
5. 移除所有角色的战斗状态 (`in_battle = False`)
6. 记录重置操作日志

#### 4. reset_turn_counter()
**功能**：仅重置回合计数器到0

#### 5. _restore_single_character_actions(character_id: int)
**功能**：恢复单个角色的行动次数

#### 6. _process_emotion_turn_start(character_id: int) -> List[str]
**功能**：处理角色回合开始时的情感系统回合开始效果

#### 7. process_all_emotion_upgrades() -> List[str]
**功能**：处理所有角色的情感升级

## 6.3. 回合流程

1.  **行动阶段**：玩家或 AI 控制角色执行行动（攻击、使用技能等），消耗行动次数。
2.  **回合结束 (`/end_turn`)**：当所有角色行动完毕后，由玩家手动触发回合结束。
3.  **效果处理**：
    *   **情感升级**：首先处理所有待升级角色的情感等级提升。
    *   **回合结束效果**：结算所有持续性伤害（如"中毒"、"烧伤"）和持续性治疗效果。
    *   **混乱值处理**：更新角色的混乱值状态。
4.  **资源恢复**：
    *   **行动次数**：恢复所有角色的行动次数至其最大值。
    *   **技能冷却**：所有处于冷却中的技能倒计时减 1。
5.  **新回合开始**：
    *   **回合开始效果**：触发"加速"等在回合开始时生效的状态。
    *   **情感效果**：应用由情感系统提供的被动增益。

## 6.4. 相关系统集成

### 状态效果系统
- `process_end_turn_effects()`: 处理回合结束效果
- `process_start_turn_effects()`: 处理回合开始效果
- `clear_all_status_effects()`: 清除所有状态

### 混乱值系统
- `stagger_manager.process_stagger_turn()`: 处理混乱值回合逻辑

### 情感系统
- `apply_emotion_effects()`: 应用情感产生的状态效果
- `process_emotion_upgrades()`: 处理情感等级升级

### 数据库操作
- `get_characters_by_type()`: 获取指定类型的角色
- `restore_character_actions()`: 恢复所有角色行动次数
- `get_character()`: 获取角色信息
- `update_character_actions()`: 更新角色行动次数

---

# 数据库系统

系统使用 SQLite 数据库来持久化所有游戏数据。核心数据表结构如下：

## 7.1. `characters` 表

存储所有角色的核心数据。

| 字段 | 类型 | 描述 |
| :--- | :--- | :--- |
| `id` | INTEGER | 唯一标识符，主键。 |
| `name` | TEXT | 角色名称。 |
| `character_type` | TEXT | 角色类型（`friendly` 或 `enemy`）。 |
| `in_battle` | INTEGER | 是否在战斗中（0 或 1）。 |
| `health` / `max_health` | INTEGER | 当前/最大生命值。 |
| `attack` / `defense` | INTEGER | 攻击力/防御力。 |
| `current_persona` | TEXT | 核心角色当前的人格名称。 |
| `emotion_level` | INTEGER | 当前情感等级（0-5级）。 |
| `positive_emotion_coins` | INTEGER | 正面情感硬币数量。 |
| `negative_emotion_coins` | INTEGER | 负面情感硬币数量。 |
| `pending_emotion_upgrade` | INTEGER | 待升级标志（0 或 1）。 |
| ... | ... | 其他与行动次数、混乱值等相关的字段。 |

## 7.2. `skills` 表

存储所有可用技能的定义。

| 字段 | 类型 | 描述 |
| :--- | :--- | :--- |
| `id` | INTEGER | 唯一标识符，主键。 |
| `name` | TEXT | 技能名称。 |
| `description` | TEXT | 技能效果的详细描述。 |
| `skill_category` | TEXT | 技能类型（`damage`, `healing`, `buff`, `debuff`, `self`, `aoe_*`）。 |
| `damage_formula`| TEXT | 伤害/治疗量的骰子公式（如 `2d6+5`）。 |
| `damage_type` | TEXT | 伤害类型（`physical` 或 `magic`）。 |
| `cooldown` | INTEGER | 技能的冷却回合数。 |
| `effects` | TEXT | 附加状态效果的 JSON 定义。 |
|`required_emotion_level`|INTEGER | 使用此技能所需的情感等级。|

## 7.3. 关联表

*   **`character_skills`**: 将角色和技能关联起来，定义了每个角色当前拥有的技能。
*   **`character_status_effects`**: 存储角色当前承受的所有临时状态效果及其持续时间。
*   **`emotion_coin_log`**: 记录角色获得情感硬币的历史。
*   **`emotion_level_history`**: 记录角色情感等级提升的历史。
*   **`character_emotion_effects`**: 存储由情感升级获得的永久效果。

---

# 主程序与效果集成

## 8.1. 主程序 (`main.py`)

这是机器人的主入口，负责：
*   **初始化**：加载配置，连接 Telegram API。
*   **数据库迁移**：在启动时自动运行 `run_migrations()`，确保数据库结构与代码同步。
*   **命令注册**：将所有模块（角色、技能、攻击等）的 Telegram 命令处理器注册到应用中。
*   **启动轮询**：启动机器人，开始监听和响应用户消息。

## 8.2. 特殊效果集成 (`special_effect_integration.py`)

该模块为复杂的、跨系统的特殊技能效果（如"硬血"、"黑夜领域"）提供了一个统一的管理和计算框架。

*   **`EffectIntegrationManager`**: 这是一个全局管理器，它注册了所有特殊效果，并提供统一的接口（如 `calculate_unified_damage`）供技能系统调用。这使得基础技能系统无需关心复杂效果的具体实现，实现了高度的解耦和可扩展性。

---

## 流程图总览

### 攻击流程
```
友方攻击 (/attack)
    ↓
选择攻击者 (有行动次数的友方)
    ↓
选择技能 (检查冷却和情感等级)
    ↓
根据技能类型选择目标
    ↓
执行技能效果
    ↓
消耗行动次数
    ↓
显示结果
```

### 回合流程
```
战斗开始
    ↓
角色加入战斗 (in_battle = True)
    ↓
玩家执行行动 (/attack, /enemy)
    ↓
行动完成后，检查是否需要结束回合
    ↓
调用 end_battle_turn()
    ↓
处理所有角色状态效果
    ↓
恢复所有角色行动次数
    ↓
开始新回合
```

---

## 总结

Dewbot 的战斗系统通过模块化设计、严格的状态管理和详细的效果系统，提供了一个复杂而灵活的RPG战斗框架。核心组件包括：

1. **角色系统**：支持丰富的属性定制、人格切换和状态管理
2. **攻击逻辑**：通过对话式界面提供直观的战斗交互
3. **技能系统**：支持多种技能类型和复杂的伤害计算
4. **情感系统**：提供战斗会话内的短期养成机制
5. **回合系统**：驱动整个战斗流程并管理资源恢复
6. **数据库系统**：持久化所有游戏数据

通过良好的模块化设计，系统具有高度的可扩展性和可维护性，支持未来的功能扩展和系统优化。