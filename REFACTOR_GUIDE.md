# Dewbot 重构技术指南

## 引言

本文档是 Dewbot 重构项目的核心技术指南，旨在为开发人员提供一份清晰、完整的设计蓝图。基于《综合分析报告：Dewbot 重构设计规范》，本指南将详细阐述重构后系统的七个核心模块，确保各模块在设计和实现上的一致性、可扩展性和可维护性。

重构的核心目标是：
- **简化逻辑**：移除冗余的攻防、抗性及种族系统，使战斗机制更纯粹。
- **架构升级**：引入行为驱动的技能系统，实现高度灵活的技能配置。
- **系统解耦**：明确各模块职责，降低系统复杂度。
- **面向未来**：为新的特殊效果和游戏机制提供清晰的扩展框架。

本指南将作为后续代码实现的直接依据。开发人员应严格遵循本文档中的设计规范，以确保重构工作的顺利进行和最终产出的高质量。

---

## 目录

1.  [角色管理系统 (Character Management System)](#1-角色管理系统-character-management-system)
2.  [技能系统 (Skill System)](#2-技能系统-skill-system)
3.  [状态效果系统 (Status Effect System)](#3-状态效果系统-status-effect-system)
4.  [情感系统 (Emotion System)](#4-情感系统-emotion-system)
5.  [回合管理系统 (Turn Management System)](#5-回合管理系统-turn-management-system)
6.  [攻击逻辑系统 (Attack Logic System)](#6-攻击逻辑系统-attack-logic-system)
7.  [特殊效果扩展系统 (Special Effect Extension System)](#7-特殊效果扩展系统-special-effect-extension-system)

---

## 1. 角色管理系统 (Character Management System)

### 1.1 模块职责

角色管理系统是整个战斗机器人的核心基础。它负责定义、创建、存储和管理所有参与战斗的角色实体，包括玩家控制的核心角色、友方单位以及敌方单位。

#### 核心角色列表

系统预设了五个核心角色，它们拥有独特的人格系统：
- **珏 (Jue)**: 核心角色之一
- **露 (Lu)**: 核心角色之一
- **莹 (Ying)**: 核心角色之一
- **笙 (Sheng)**: 核心角色之一
- **曦 (Xi)**: 核心角色之一

核心角色可以通过 `/switch` 或 `/persona` 命令切换人格，每个人格代表不同的战斗形态，拥有独特的属性和技能组合。

> 注：以下为设计期命令名，v2 实际注册命令以第10节映射为准。

#### 主要职责

- **角色生命周期管理**：处理角色的创建、初始化、状态查询和数据持久化。
- **属性管理**：维护角色的所有基础属性和战斗属性，如生命值 (HP)、行动次数 (Actions)、混乱值 (Stagger) 等。
- **人格系统**：为核心角色提供人格切换机制，管理不同人格下的属性和技能配置。
- **特性标签**：管理角色的特性标签（如人类、机械、异想体），当前仅存储在数据库中，不直接参与战斗结算，供后续机制调用。
- **状态维护**：跟踪角色的战斗状态，如是否存活、是否处于混乱状态等。

### 1.2 数据结构 / 数据库设计

建议采用 SQLite 数据库进行数据持久化，并使用数据类 ( dataclass 或 SQLAlchemy Model ) 在代码中表示角色实体。

#### 1.2.1 `characters` 表

存储所有角色的基础和战斗数据。

| 字段名 | 类型 | 描述 | 示例 |
| :--- | :--- | :--- | :--- |
| `id` | INTEGER | 主键，唯一标识符 | 1 |
| `name` | TEXT | 角色名称 | "珏" |
| `is_enemy` | BOOLEAN | 是否为敌方单位 | `False` |
| `is_core` | BOOLEAN | 是否为核心角色 | `True` |
| `active_persona_id`| INTEGER | (核心角色)当前激活的人格ID, 外键关联`personas`表 | 101 |
| `max_hp` | INTEGER | 最大生命值 | 100 |
| `current_hp` | INTEGER | 当前生命值 | 85 |
| `max_actions` | INTEGER | 每回合最大行动次数 | 2 |
| `current_actions`| INTEGER | 当前剩余行动次数 | 1 |
| `max_stagger` | INTEGER | 最大混乱值 | 50 |
| `current_stagger`| INTEGER | 当前混乱值 | 50 |
| `is_staggered` | BOOLEAN | 是否处于混乱状态 | `False` |
| `stagger_turns` | INTEGER | 混乱状态剩余回合数（初始为2，实现"当回合进入混乱，下回合结束解除"的逻辑） | 0 |
| `emotion_level` | INTEGER | 当前情感等级 (由情感系统管理) | 0 |
| `positive_emotion_coins` | INTEGER | 正面情感硬币 | 0 |
| `negative_emotion_coins` | INTEGER | 负面情感硬币 | 0 |
| `tags` | TEXT | 特性标签, JSON 数组格式 (目前主要标签: "人类", "机械", "异想体"；当前仅存储，不参与结算) | `["人类", "异想体"]` |
| `ego_skill_id` | INTEGER | (核心角色专属)绑定的EGO技能ID | 301 |
| `is_in_battle` | BOOLEAN | 是否在战斗中 | `True` |

#### 1.2.2 `personas` 表

存储核心角色的人格信息。

| 字段名 | 类型 | 描述 | 示例 |
| :--- | :--- | :--- | :--- |
| `id` | INTEGER | 主键，人格唯一标识符 | 101 |
| `character_id`| INTEGER | 所属核心角色的ID, 外键关联`characters`表 | 1 |
| `persona_name` | TEXT | 人格名称 | "初始人格" |
| `max_hp` | INTEGER | 装备该人格后的绝对最大生命值 | 100 |
| `max_actions`| INTEGER | 装备该人格后的绝对行动次数 | 1 |
| `max_stagger`| INTEGER | 装备该人格后的绝对混乱值 | 45 |
| `skill_ids` | TEXT | 该人格下可用的技能ID, JSON 数组格式 | `[201, 202, 203]` |

### 1.3 核心函数 / API 设计

#### `CharacterManager` 类

```python
class CharacterManager:
    def __init__(self, db_connection):
        self.db = db_connection

    def create_character(self, name: str, max_hp: int, max_actions: int, max_stagger: int, tags: list, is_enemy: bool, is_core: bool = False) -> Character:
        """
        创建一个新的角色并存入数据库。
        - 伪代码:
          1. 构造角色数据字典。
          2. 将数据插入 `characters` 表。
          3. 返回一个代表该角色的 Character 对象实例。
        """
        pass

    def get_character(self, character_id: int) -> Character:
        """
        根据 ID 获取角色对象。
        - 伪代码:
          1. 从 `characters` 表查询数据。
          2. 如果是核心角色，额外查询 `personas` 表获取当前人格信息，并将当前人格的普通技能与该角色绑定的 EGO 技能合并。
          3. 将数据库行数据转换为 Character 对象。
        """
        pass

    def switch_persona(self, core_character_id: int, new_persona_id: int) -> bool:
        """
        切换核心角色的人格。
        - 伪代码:
          1. 验证角色ID和人格ID的有效性。
          2. 更新 `characters` 表中的 `active_persona_id` 字段。
          3. （可选）触发一个事件，通知其他系统（如技能系统）更新角色状态。
        """
        pass

    def apply_damage(self, character_id: int, damage: int, is_fixed: bool = False):
        """
        对角色造成最终的生命值变化，处理混乱值和混乱状态。(注意：真正的伤害公式、强壮虚弱等应该在 SkillManager 或独立的战斗环境模块完成计算，本函数仅接收计算后的最终削减值)
        - 伪代码:
          1. 获取角色对象。
          2. 如果 `not is_fixed`:
             - 如果角色 `is_staggered`，伤害乘以 2。
          3. 如果 `not is_fixed`:
             - 检查并触发破裂效果（如有）：
               - 计算破裂附加伤害 (强度 × 1)。
               - 注意：为了架构清晰，此步骤实际应当通过 `battle_context.trigger_event('on_hit', target)` 在外界执行，但基础伤害若要立刻结算，可直接在最终传值里预先加好，或在这里同步触发破裂衰减。
          4. `current_hp` 减去最终合并伤害。
          5. 如果 `not is_fixed`:
             - `current_stagger` 减去原始伤害（不包括破裂/受击附加伤害）。
             - 检查 `current_stagger` 是否小于等于 0:
               - 如果是，设置 `is_staggered = True`, `stagger_turns = 2`, `current_actions = 0`。
               - 将 `current_stagger` 重置为 `max_stagger`。
          6. 检查 `current_hp` 是否小于等于 0，标记为死亡状态。
          7. 更新数据库。
        """
        pass
    
    def reset_for_turn_end(self, character_id: int):
        """
        为回合结束重置角色状态。
        - 伪代码:
          1. 获取角色对象。
          2. 处理混乱状态: 如果 `is_staggered`，则 `stagger_turns -= 1`。
          3. 如果 `stagger_turns` 变为 0，解除混乱状态: `is_staggered = False`。
          4. 检查是否可以恢复行动力：如果解除后或本身没有混乱 (`not is_staggered`)，恢复 `current_actions = max_actions`。否则保持为 0（死锁行动力）。
          5. 更新数据库。
        """
        pass
```

### 1.4 模块交互

- **与技能系统 (Skill System)**:
  - 技能系统在执行技能前，需要向角色管理系统查询攻击者的属性（如情感等级）和可用技能。
  - 技能系统在计算效果时，需要调用角色管理系统的 `apply_damage()` 或 `apply_heal()` 等方法来更新目标角色的状态。

- **与回合管理系统 (Turn Management System)**:
  - 回合结束时，回合管理系统会调用角色管理系统的 `reset_for_turn_end()` 方法来为每个角色恢复行动次数和处理混乱状态倒计时。
  - 场景结束 (Stage End) 或战斗结束 (Battle End) 时，会调用相应的重置方法清除角色状态。

- **与情感系统 (Emotion System)**:
  - 角色管理系统存储角色的 `emotion_level`、`positive_emotion_coins`、`negative_emotion_coins`，但具体逻辑由情感系统处理。
  - 情感系统升级时，可能会通过角色管理系统查询或更新角色的状态。

### 1.5 用户接口 (Telegram 命令)

> 注：以下为设计期命令名，v2 实际注册命令以第10节映射为准。

- `/create_character <name> <max_hp> <max_actions> <max_stagger> [tags...]`: 创建一个非核心友方角色。
- `/create_enemy <name> <max_hp> <max_actions> <max_stagger> [tags...]`: 创建一个敌方角色。
- `/create_core <name> <max_hp> ...`: 创建一个核心角色（可能需要更复杂的参数来定义初始人格）。
- `/switch <core_character_name> <persona_name>`: 切换指定核心角色的人格。
- `/characters`: 显示所有友方角色的简要状态。
- `/enemies`: 显示所有敌方角色的简要状态。
- `/show <character_name>`: 显示指定角色的详细状态，包括HP、行动次数、混乱值、情感等级和当前状态效果。
- `/reset battle`: (管理命令) 重置整个战斗状态，将所有角色恢复到初始状态。

---
## 2. 技能系统 (Skill System)

### 2.1 模块职责

技能系统是战斗的核心驱动力，负责定义、解析和执行角色在战斗中使用的所有技能。重构后的技能系统将采用“行为驱动”架构，将每个技能分解为一系列原子化的行为，从而实现高度的灵活性和可扩展性。

其主要职责包括：
- **技能定义与管理**：提供创建和存储技能的机制，每个技能包含基础信息和一系列行为。
- **行为执行引擎**：按照统一回合生命周期解析行为；主动技能按“使用前 -> 使用时 -> 使用后”结算，自动触发行为还可挂在回合开始和回合结束。
- **目标解析**：技能层只进行一次目标指定（如需交互），行为层可“继承技能目标”或使用“自动目标逻辑”。
- **伤害/治疗计算**：集成骰子公式解析器，计算基础伤害/治疗值。
- **冷却管理**：跟踪技能冷却；普通技能在回合结束时统一自然推进，情感升级可对该角色的普通技能额外缩减1回合。
- **条件检查**：在技能执行前，检查使用者是否满足情感等级等前置条件。

#### 统一回合与行为时机

一个完整回合严格定义为：

```text
回合开始 -> 我方全部行动 -> 敌方全部行动 -> 回合结束
```

我方与敌方不进行拼点，也不是同步行动；双方在各自阶段直接执行技能。死亡、混乱或其他原因导致无法行动的单位不会在所属行动阶段行动。

行为使用五段主时机：

| 时机 | 含义 |
| :--- | :--- |
| `TURN_START` | 回合开始。处理情感升级、异想体书页回合开始被动、待生效效果及其他回合开始钩子。 |
| `PRE` | 使用前。处理技能主效果前的强化、弱化、条件检查与技能改写。 |
| `ON` | 使用时。主动技能必须至少有一个 `ON` 行为；主伤害、治疗、施加效果及命中/暴击条件都在这里结算。 |
| `POST` | 使用后。主效果全部完成后，处理击杀、未击杀、阵营和目标身份等条件。 |
| `TURN_END` | 回合结束。处理回合结束行为、持续效果、通用效果清理、混乱倒计时和自然冷却推进。 |

`timing` 只描述这五段生命周期；更细的条件使用独立的 `trigger_condition`。首批条件包括：

```text
ALWAYS
ON_HIT
ON_CRIT_HIT
ON_CRIT_TRIGGER
ON_KILL
ON_CRIT_KILL
ON_KILL_SELECTED_TARGET
ON_NO_KILL_SELECTED_TARGET
ON_KILL_ALLY
ON_KILL_ENEMY
```

同一时机内按 `order` 执行。条件判断必须读取本次结算快照，不能在事后重新猜测命中、暴击、死亡或击杀归属。快照至少保存技能使用者、技能层目标、实际目标、行为与命中序号、逐次命中/暴击结果、伤害来源、死亡单位、击杀者和死亡单位阵营。

`TURN_START`/`TURN_END` 行为只有在来源已激活或注册时触发。角色仅仅持有某个技能，不代表该技能的回合开始/结束行为永久生效：主动技能可在使用时登记后续时机行为；异想体书页、状态和管理人效果按自身生命周期登记。

条件还必须指定 `trigger_scope`：`PER_SKILL` 表示整次技能一次，`PER_TARGET` 表示每个目标一次，`PER_HIT` 表示每次独立命中一次。命中/暴击命中类默认 `PER_HIT`；击杀类默认 `PER_SKILL`，需要按每个目标分别结算时显式使用 `PER_TARGET`。`ON_KILL_ALLY/ON_KILL_ENEMY` 的阵营以技能使用者为参照，目标身份以本次技能目标快照为准。

对于技能层目标快照：`ON_KILL_SELECTED_TARGET + PER_SKILL` 在至少一个目标被本技能击杀时成立；`ON_NO_KILL_SELECTED_TARGET + PER_SKILL` 只有在没有任何目标被本技能击杀时成立。改用 `PER_TARGET` 后，则分别对每个死亡或存活目标结算。

`POST` 击杀条件只读取本次技能的即时结算快照。技能施加的烧伤、中毒等效果在未来回合造成死亡时会产生独立的状态伤害事件，不会追溯触发原技能的 `POST`。

### 2.2 数据结构 / 数据库设计

技能及其行为数据可以存储在数据库中，也可以作为配置文件（如 JSON或YAML）加载，后者更便于迭代和版本控制。此处我们以数据库表结构为例。

值得注意的是，针对5名核心角色（珏、露、莹、笙、曦），我们引入了 **EGO技能** 概念。

#### 2.2.1 `skills` 表

存储技能的基础信息。

| 字段名 | 类型 | 描述 | 示例 |
| :--- | :--- | :--- | :--- |
| `id` | INTEGER | 主键，技能唯一标识符 | 201 |
| `name` | TEXT | 技能名称 | "火焰斩" |
| `description`| TEXT | 技能描述 | "对单个敌人造成火焰伤害" |
| `base_cooldown`| INTEGER | 基础冷却回合数 | 3 |
| `emotion_req`| INTEGER | 情感等级要求 | 1 |
| `skill_type` | TEXT | 技能类型: `NORMAL` 或 `EGO` | "NORMAL" |
| `skill_target_scope` | TEXT | 技能目标范围 (`SELF`, `FRIENDLY`, `ENEMY`, `ALL`) | "ENEMY" |
| `skill_target_method` | TEXT | 技能目标方式 (`SELF`, `SELECT_TARGET`, `ALL_TARGETS`, `RANDOM`) | "SELECT_TARGET" |
| `skill_target_param` | INTEGER | 目标方式附加参数（如 `RANDOM` 的 X） | null |

**关于 EGO 技能 (`skill_type` = 'EGO')**:
1. EGO技能完全与角色绑定，不会根据角色人格(Persona)变化而被增加或移除。
2. 相比普通技能，EGO技能异常强大，因此具备极高的情感等级要求 (`emotion_req`)。
3. **重要限制**：每名角色每场战斗至多施放一次 EGO 技能。一旦使用，角色会被标记为“本场已使用EGO”，直到下一次战斗开始重置。
4. EGO 是主动的角色终极能力，可以是一次性高伤害技能，也可以通过 `SPECIAL` 行为让角色进入持续若干时间的强化形态；无论采用哪种内容形态，仍共用行为、事件和播报框架。

#### 2.2.2 `skill_behaviors` 表

存储构成技能的具体行为，是新架构的核心。

| 字段名 | 类型 | 描述 | 示例 |
| :--- | :--- | :--- | :--- |
| `id` | INTEGER | 主键，行为唯一标识符 | 301 |
| `skill_id` | INTEGER | 所属技能ID, 外键关联 `skills` 表 | 201 |
| `timing` | TEXT | 主时机 (`TURN_START`, `PRE`, `ON`, `POST`, `TURN_END`) | "ON" |
| `trigger_condition` | TEXT | 触发条件；默认 `ALWAYS`，也可为命中、暴击、击杀等条件 | "ON_CRIT_HIT" |
| `trigger_scope` | TEXT | 条件结算范围 (`PER_SKILL`, `PER_TARGET`, `PER_HIT`) | "PER_HIT" |
| `target_source` | TEXT | 目标来源 (`INHERIT_SKILL` 或 `AUTO`) | "INHERIT_SKILL" |
| `target_scope`| TEXT | 自动目标范围 (`SELF`, `FRIENDLY`, `ENEMY`, `ALL`)，仅 `AUTO` 时生效 | "ENEMY" |
| `target_method`| TEXT | 自动目标方式 (`SELF`, `ALL_TARGETS`, `RANDOM`)，仅 `AUTO` 时生效 | "ALL_TARGETS" |
| `target_param`| INTEGER | 自动方式附加参数 (如 `RANDOM` 的 X)，仅 `AUTO` 时生效 | null |
| `effect_type`| TEXT | 效果种类 (`DAMAGE`, `HEAL`, `APPLY_EFFECT`, `SPECIAL`) | "DAMAGE" |
| `effect_value`| TEXT | 效果数值 (骰子公式, 状态效果名称等) | "2d6+3" |
| `effect_params`| TEXT | 效果额外参数 (JSON格式), 如状态效果强度/层数 | `{"type": "BURN", "intensity": 2, "stacks": 1}` |
| `order` | INTEGER | 同一时机下的执行顺序 | 1 |

#### `battle_registered_behaviors` 表

保存已经激活、等待 `TURN_START` 或 `TURN_END` 的行为，避免把角色持有的全部技能误当成被动：

| 字段名 | 类型 | 描述 |
| :--- | :--- | :--- |
| `behavior_id` | INTEGER | 对应行为定义 |
| `owner_character_id` | INTEGER | 行为归属者；管理人行为可为空 |
| `source_type` | TEXT | `SKILL`, `PAGE`, `STATUS`, `MANAGER` |
| `source_id` | TEXT | 来源技能、书页、状态或管理人技能 |
| `active_from` | TEXT | 例如 `NEXT_TURN_START` |
| `remaining_turns` | INTEGER | 剩余有效回合；一次性行为可为1 |
| `remaining_triggers` | INTEGER | 剩余触发次数；为空表示只受持续时间控制 |
| `lifecycle_scope` | TEXT | `TURN`, `STAGE`, `BATTLE`；临时行为在 Stage End 清除 |
| `status` | TEXT | `PENDING`, `ACTIVE`, `EXHAUSTED` |

#### 2.2.3 `battle_skill_cooldowns` 表

在战斗中动态跟踪每个角色技能的冷却状态及EGO技能的使用情况。

| 字段名 | 类型 | 描述 | 示例 |
| :--- | :--- | :--- | :--- |
| `character_id`| INTEGER | 角色ID | 1 |
| `skill_id` | INTEGER | 技能ID | 201 |
| `cooldown` | INTEGER | 剩余冷却回合 | 2 |

#### 2.2.4 `battle_ego_usage` 表

记录每个角色在本场战斗中是否已施放过任意 EGO 技能。

| 字段名 | 类型 | 描述 | 示例 |
| :--- | :--- | :--- | :--- |
| `character_id` | INTEGER | 角色ID | 1 |
| `ego_used` | INTEGER | 本场是否已用EGO (0/1) | 1 |

#### 2.2.5 骰子公式系统

技能的伤害/治疗值通过骰子公式定义，提供随机性和可预测性的平衡。

**支持的格式**：

| 公式格式 | 说明 | 示例结果 |
| :--- | :--- | :--- |
| `"1d6"` | 1个6面骰子 | 1-6 |
| `"2d8"` | 2个8面骰子 | 2-16 |
| `"10"` | 固定值10 | 10 |
| `"5+2d3"` | 基础值5 + 2个3面骰子 | 7-11 |
| `"3d4+2"` | 3个4面骰子 + 2 | 5-14 |
| `"1d12+5"` | 1个12面骰子 + 5 | 6-17 |

**解析规则**：
- 使用 `+` 号连接多个部分
- 骰子格式: `{数量}d{面数}`（如 `3d6` 表示3个6面骰子）
- 固定数值直接写数字
- 执行顺序: 先投骰子，再加固定值
- 麻痹状态会让部分骰子变为0

**情感硬币触发**：
- 投掷结果为1 → 获得1个负面情感硬币
- 投掷结果为最大值 → 获得1个正面情感硬币

### 2.3 核心函数 / API 设计

#### `SkillManager` 类

```python
from enum import Enum

class EffectTiming(Enum):
    TURN_START = "TURN_START"
    PRE = "PRE"
    ON = "ON"
    POST = "POST"
    TURN_END = "TURN_END"

class TriggerCondition(Enum):
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

class SkillManager:
    def __init__(self, db_connection, character_manager, status_effect_manager):
        self.db = db_connection
        self.char_manager = character_manager
        self.effect_manager = status_effect_manager

    def get_skill(self, skill_id: int) -> Skill:
        """
        获取技能及其所有行为的完整定义。
        - 伪代码:
          1. 从 `skills` 表获取技能基础信息。
          2. 从 `skill_behaviors` 表获取所有关联的行为，并按 `timing` 和 `order` 排序。
          3. 组装成一个 Skill 对象返回。
        """
        pass

    def execute_skill(self, user_id: int, skill_id: int, selected_skill_targets: list[int] | None = None):
        """
        执行一个完整的技能流程。
        - 伪代码:
          1. 获取技能的完整定义。
          2. 根据技能层目标合同 (`skill_target_scope` + `skill_target_method`) 解析本次技能目标快照。
          3. 检查技能是否为 EGO 技能 (`skill_type` == 'EGO'):
             a. 检查该角色在本场战斗中是否已经使用过任意 EGO 技能。
             b. 检查情感等级要求。
          4. 否则检查普通技能冷却和情感等级要求。
          5. 初始化战斗播报构建器 (ReportBuilder) 与事件环境 `battle_context`。
          6. 按顺序执行 PRE-timing 行为。
          7. 按顺序执行 ON-timing 行为 (主动技能必须存在)，在命中和暴击结果产生后立即评估对应 `trigger_condition`。
          8. 汇总本技能造成的死亡与击杀快照，再按顺序执行 POST-timing 行为及其击杀/未击杀条件。
          9. 如果是普通技能，设置攻击者技能冷却；如果是 EGO，不进入普通冷却表，只标记角色本场 `ego_used = 1`。
          10. 消耗使用者行动次数。
          11. 触发使用者的行动后效果（如流血状态，或者通过 `battle_context.trigger_event('on_action_end', snapshot)` 激活相关异想体被动）。
          12. 返回构建好的单一战斗播报文本。

          注意：这里不推进自然冷却。全场普通技能 CD -1 只在整个“我方行动阶段 + 敌方行动阶段”结束后的 TURN_END 统一执行。
        """
        pass

    def _execute_behaviors_for_timing(self, user: Character, behaviors: list[Behavior], skill_target_snapshot: list[Character], report_builder):
        """
        私有辅助函数，执行特定时机下的所有行为。
        - 伪代码:
           1. 遍历行为列表。
           2. 使用当前事件快照检查 `trigger_condition`；条件不满足则跳过。
           3. 对每个行为调用 `_resolve_targets()` 确定目标列表：
             - `target_source = INHERIT_SKILL`：继承本次技能目标快照。
             - `target_source = AUTO`：使用行为自己的自动目标逻辑。
           4. 遍历目标列表，对每个目标应用效果 (`_apply_effect()`)。
           5. 将每个行为的执行结果添加到 report_builder，并更新命中、暴击、死亡和击杀快照。
        - 播报格式示例:
          [角色名] 使用了 [技能名]：
          [角色名] 获得 2级 强壮
          [目标1] 受到 3d5=2+3+1=6点伤害
          [目标1] 受到 3 破裂伤害 (常规效果独立结算)
          [目标2] 受到 3d5=1+4+2=7点伤害
          [目标1] 增加 3 破裂强度
          [目标2] 增加 3 破裂强度
        """
        pass

    def _resolve_targets(self, user: Character, behavior: Behavior, skill_target_snapshot: list[Character]) -> list[Character]:
        """
        根据目标范围和方式解析出所有受影响的角色。
        - 伪代码:
          1. 如果 `behavior.target_source == 'INHERIT_SKILL'`，直接返回 `skill_target_snapshot`。
          2. 否则按自动目标逻辑处理 (`behavior.target_source == 'AUTO'`)。
          3. 确定自动目标池 (`target_scope`):
             - 'SELF': [user]
             - 'FRIENDLY': 所有存活的友方角色
             - 'ENEMY': 所有存活的敌方角色
             - 'ALL': 所有存活的友方和敌方角色
          4. 从目标池中按方式 (`target_method`) 选择:
             - 'SELF': 从'自身'池中选择自己（仅对'自身'范围有效）。
             - 'ALL_TARGETS': 返回池中所有角色。
             - 'RANDOM': 从池中随机选择 `target_param` (X) 个目标（可重复命中，放回抽样，即广域乱射:X）。
        """
        pass

    def _resolve_skill_targets(self, user: Character, skill: Skill, selected_skill_targets: list[int] | None) -> list[Character]:
        """
        解析技能层的唯一目标指定。
        - 伪代码:
          1. 读取技能的 `skill_target_scope`、`skill_target_method`、`skill_target_param`。
          2. 如果 `skill_target_method == 'SELECT_TARGET'`，使用交互阶段只选择一次的目标。
          3. 如果 `skill_target_method` 为 `SELF/ALL_TARGETS/RANDOM`，按自动逻辑解析。
          4. 返回技能目标快照，供所有 `INHERIT_SKILL` 行为复用。
        """
        pass

    def _apply_effect(self, user: Character, target: Character, effect_type: str, value: str, params: dict):
        """
        对单个目标应用单个效果。
        - 伪代码:
          1. 'DAMAGE': 
             a. 解析骰子公式 `value` 获得基础伤害数值。
             b. 触发 `battle_context.trigger_event('on_before_damage', snapshot)` 轮询异想体书页效果（如“造成伤害前提升...”）。
             c. 结合攻击者自身的 Buff（强壮/虚弱）、目标受击修正（护盾/守护/易伤）与混乱状态，通过统一战斗计算器计算最终伤害，并加入受击相关效果。
             d. 向 `char_manager.apply_damage()` 传递最终结算数值扣减。
             e. 写入是否命中、是否暴击、目标是否死亡及击杀归属，再触发 `battle_context.trigger_event('on_after_damage', snapshot)` 轮询后置被动（如火柴“造成伤害后附加烧伤”）。
          2. 'HEAL': 解析骰子公式 `value`，结合生命恢复类修饰，调用 `char_manager.apply_heal()`。
          3. 'APPLY_EFFECT': 调用 `effect_manager.apply_effect()`，参数来自 `params`。
          4. 'SPECIAL': 调用特殊效果扩展系统的接口。
        """
        pass

    def reduce_cooldown(self, character_id: int, skill_id: int, amount: int):
        """
        减少指定技能的冷却时间。
        - 伪代码:
          1. 检查技能是否为 EGO 技能 (`skill_type` == 'EGO')。
          2. 如果是 EGO 技能，忽略冷却缩减 (EGO 技能冷却不受普通缩减影响)。
          3. 如果为普通技能，正常减少冷却时间并在 0 处截断。
        """
        pass

    def process_registered_timing_event(self, timing: EffectTiming, battle_snapshot):
        """
        处理已经登记且仍在生命周期内的 TURN_START/TURN_END 行为。
        仅遍历活动书页、状态、管理人效果或主动技能使用后登记的行为，不能遍历角色持有的全部技能后无条件触发。
        """
        pass

    def advance_all_normal_cooldowns_at_turn_end(self):
        """
        仅在 TURN_END 调用。遍历全场普通技能，将 CD -1 并在0截断。
        EGO 不进入普通技能冷却推进，也不受情感升级的额外冷却缩减影响。
        """
        pass
```

### 2.4 模块交互

- **与角色管理系统 (Character Management System)**:
  - 强依赖关系。执行技能时需要频繁查询和更新角色属性，如HP、情感等级、行动次数等。

- **与状态效果系统 (Status Effect System)**:
  - 当行为的 `effect_type` 为 `APPLY_EFFECT` 时，技能系统会将效果定义（名称与参数）传递给状态效果系统进行处理。

- **与攻击逻辑系统 (Attack Logic System)**:
  - 攻击逻辑系统作为用户交互的前端，负责收集用户输入的攻击者、技能和目标，然后调用本系统的 `execute_skill()` 方法来启动技能执行流程。

- **与特殊效果扩展系统 (Special Effect Extension System)**:
  - 当行为的 `effect_type` 为 `SPECIAL` 时，技能系统会调用扩展系统提供的接口，处理复杂的、非标准化的技能效果。

### 2.5 用户接口 (Telegram 命令)

> 注：以下为设计期命令名，v2 实际注册命令以第10节映射为准。

该模块主要由其他系统在后端调用，不直接面向用户提供命令。但可以提供一些管理和查询命令：

- `/skill <skill_name>`: (管理命令) 查询并显示一个技能的详细信息，包括其所有行为。
- `/skills <character_name>`: (管理命令) 列出指定角色当前可用（满足等级要求且不在冷却中）的所有技能。

---
## 3. 状态效果系统 (Status Effect System)

### 3.1 模块职责

状态效果系统（也称 Buff/Debuff 系统）负责管理施加在角色身上的所有临时性状态。它根据效果的类型，处理其应用、叠加、持续时间、结算和移除的逻辑。

其主要职责包括：
- **效果分类管理**：根据规则，将效果分为常规效果、通用效果、特殊效果和即时效果，并应用不同的处理逻辑。
- **效果应用与叠加**：实现不同效果的叠加规则（如常规效果强度/层数相加，通用效果取最高强度等）。
- **周期性结算**：在回合结束时，结算“烧伤”、“中毒”等持续伤害/治疗效果。
- **持续时间管理**：管理效果的持续回合，并在到期时自动移除。
- **状态查询**：提供接口供其他系统（如伤害计算、UI显示）查询角色当前承受的所有效果及其影响。
- **效果清理**：在 Stage End 和 Battle End 时，根据规则清除相应的状态效果。

### 3.2 数据结构 / 数据库设计

状态效果是战斗中的临时数据，可以存储在内存中，也可以持久化到数据库以支持长时间的战斗或断线重连。

#### 3.2.1 `active_status_effects` 表

存储当前战斗中所有角色身上的状态效果。

| 字段名 | 类型 | 描述 | 示例 |
| :--- | :--- | :--- | :--- |
| `id` | INTEGER | 主键 | 401 |
| `character_id`| INTEGER | 效果作用的角色ID | 1 |
| `effect_name`| TEXT | 效果名称 (e.g., "BURN", "STRENGTH") | "BURN" |
| `effect_category`| TEXT | 效果分类 (`REGULAR`, `GENERIC`, `SPECIAL`, `INSTANT`) | "REGULAR" |
| `intensity` | INTEGER | 效果强度 | 2 |
| `stacks` | INTEGER | 效果层数 | 1 |
| `duration` | INTEGER | 剩余持续回合数 | 3 |
| `custom_params`| TEXT | 特殊效果的自定义参数（JSON格式）；旧 `stage_persistent` 不得让临时效果跨过 Stage End | `{"amount": 5}` |

#### 3.2.2 状态效果详细列表

根据todo.txt的要求B，状态效果分为四大类：

##### 常规效果 (REGULAR)

具有强度和层数，叠加规则为新旧效果相加。伤害计算独立于伤害公式，为固定伤害，不受易伤、混乱等效果影响，也不削减混乱值。

| 效果名称 | 英文标识 | 图标 | 效果描述 | 触发时机 | 层数衰减 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **烧伤** | `BURN` | 🔥 | 回合结束时受到 `强度 × 1` 点固定伤害 | 回合结束 | 回合结束 -1 |
| **中毒** | `POISON` | ☠️ | 回合结束时受到 `当前生命值 × 强度%` 点固定伤害（最少1点） | 回合结束 | 回合结束 -1 |
| **流血** | `BLEEDING` | 🩸 | 每次行动后受到 `强度 × 1` 点固定伤害 | 行动后 | 触发时 -1 |
| **破裂** | `RUPTURE` | 💥 | 受击时额外受到 `强度 × 1` 点固定伤害 | 受击时 | 触发时 -1 |
| **呼吸法** | `BREATHING` | 🫁 | 暴击率增加 `强度%`，触发暴击时造成120%伤害 | 攻击时 | 回合结束 -1 |

##### 通用效果 (GENERIC)

仅保留强度，强度叠加规则为取最大值。六种通用效果全部只在其实际生效的当前回合有效，并在该回合的 `TURN_END` 清空；护盾与麻痹不再设置跨回合例外。

| 效果名称 | 英文标识 | 图标 | 效果描述 | 持续时间 |
| :--- | :--- | :--- | :--- | :--- |
| **强壮** | `STRENGTH` | 💪 | 攻击造成的最终伤害增加 `强度 × 10%` | 回合结束清除 |
| **虚弱** | `WEAKNESS` | 😵 | 攻击造成的最终伤害减少 `强度 × 10%` | 回合结束清除 |
| **守护** | `GUARD` | ☂️ | 受到的最终伤害减少 `强度 × 10%` | 回合结束清除 |
| **护盾** | `SHIELD` | 🛡️ | 抵挡等同于强度的伤害，抵挡后强度减少 | 强度耗尽或回合结束清除 |
| **易伤** | `VULNERABLE` | 💔 | 受到的最终伤害增加 `强度 × 10%` | 回合结束清除 |
| **麻痹** | `PARALYSIS` | ⚡ | 投掷伤害骰子时，`min(骰子数, 麻痹强度)` 个骰子结果归零 | 强度归零或回合结束清除 |

如果一个通用效果要影响下一回合，不得依赖“本回合不清除”的例外，而应写入待生效队列，在下一次 `TURN_START` 激活。例如：

- 敌方在敌方行动阶段施加“下回合虚弱/麻痹”，实际进入 `battle_pending_effects`，下一回合开始时再生效。
- 我方可以通过异想体书页、被动或其他 `TURN_START` 行为，在回合开始为自身施加护盾。
- 待生效效果激活后与普通通用效果完全相同，并在该回合结束时清空。

##### `battle_pending_effects` 表（待生效效果）

| 字段名 | 类型 | 描述 |
| :--- | :--- | :--- |
| `id` | INTEGER | 主键 |
| `character_id` | INTEGER | 将要受到效果的角色 |
| `effect_name` | TEXT | 效果名称 |
| `effect_category` | TEXT | 激活时按 `GENERIC`、`INSTANT` 或其他已登记类别执行 |
| `intensity` | INTEGER | 生效时的强度 |
| `effect_params` | TEXT | 额外参数 JSON，例如一次性额外行动点数量 |
| `activate_at` | TEXT | 当前先支持 `NEXT_TURN_START` |
| `source_snapshot` | TEXT | 来源技能、施加者和目标关系等 JSON 快照 |

##### 特殊效果 (SPECIAL)

不按照强度层数体系，参数根据各自设计而定。

| 效果名称 | 英文标识 | 图标 | 效果描述 | 参数说明 |
| :--- | :--- | :--- | :--- | :--- |
| **硬血** | `HARDBLOOD` | 🩸 | 特殊资源池，可被特定技能消耗以增强伤害 | 仅存在数量参数 `amount`，与强度/层数体系解耦 |
| **黑夜领域** | `DARK_DOMAIN` | 🌑 | 回合结束时结算666负面情感币，并安排下回合开始获得6级强壮、6级易伤和1点额外行动点；免疫一次致死伤害（规范占位，v2 尚未落地） | 持续3回合，有特殊死亡免疫机制 |
| **削弱光环** | `WEAKEN_AURA` | 💜 | 回合结束时为所有敌方安排下回合开始生效的5级虚弱和5级易伤（规范占位，v2 尚未落地） | 持续5回合 |

##### 即时效果 (INSTANT)

没有强度层数概念，根据特殊参数立即生效，不写入数据库。

| 效果名称 | 英文标识 | 效果描述 |
| :--- | :--- | :--- |
| **吸血** | `VAMPIRIC` | 将造成伤害的百分比转化为硬血（非直接治疗）（规范占位，v2 尚未落地） |

**注意**：根据todo.txt的要求A，冷却缩减不作为即时效果存在，只通过情感系统升级触发。

### 3.3 核心函数 / API 设计

#### `StatusEffectManager` 类

```python
class StatusEffectManager:
    def __init__(self, db_connection, character_manager):
        self.db = db_connection
        self.char_manager = character_manager

    def apply_effect(self, target_id: int, effect_name: str, category: str, intensity: int = 0, stacks: int = 0, duration: int = 0, params: dict = None):
        """
        向目标角色应用一个状态效果。
        - 伪代码:
          1. 检查目标身上是否已有同名效果。
          2. 根据效果 `category` 和叠加规则处理:
             - 'REGULAR' (烧伤, 中毒, 流血, 破裂, 呼吸法): 
               - 强度 = 旧强度 + 新强度。
               - 层数 = 旧层数 + 新层数。 (如果新层数为0，且无旧效果，则层数设为1)
               - 伤害计算独立于公式，为固定伤害，不受普通伤害倍率影响且不削减混乱值。
               - 注意：破裂在受击时触发并减少层数，流血在行动后触发并减少层数，不随回合自动减少。
             - 'GENERIC' (强壮, 虚弱, 守护, 护盾, 易伤, 麻痹): 
               - 仅保留强度。强度 = max(旧强度, 新强度)。
               - 默认持续时间为本回合 (duration=1)，六种通用效果全部在回合结束清除。
               - 护盾可能在回合内因吸收伤害提前耗尽，麻痹可能在回合内因触发提前归零；即使仍有剩余，也不能跨过本回合结束。
               - 如果 `params.activation_timing == 'NEXT_TURN_START'`，不立即写入活动效果，而是写入 `battle_pending_effects`，等下一次回合开始激活。
               - 麻痹特殊机制：在伤害计算时，min(骰子数, 麻痹强度) 个骰子结果归零，每归零一个骰子，麻痹强度-1。
             - 'SPECIAL' (硬血, 黑夜领域, 削弱光环): 
               - 根据 `params` 中的自定义逻辑处理 (如硬血仅维护 `amount`)。
               - 特殊效果不使用强度/层数体系。
               - Stage End 时清除全部临时特殊效果。只有被规则明确声明为“战斗级永久效果”而非临时效果的内容才可跨阶段保留。
             - 'INSTANT' (吸血): 
               - 立即执行效果，不写入数据库。
               - 注意：技能冷却缩减只通过情感系统升级触发，不作为即时效果存在。
          3. 将效果数据存入或更新 `active_status_effects` 表。
        """
        pass

    def process_turn_end_effects(self, character_id: int):
        """
        在回合结束时，处理指定角色的所有持续效果。
        - 伪代码:
          1. 查询该角色所有 `active_status_effects`。
          2. 遍历效果列表:
             - 如果是 'GENERIC' 效果:
               - 此方法不立即移除；在全部 `TURN_END` 行为和特殊效果结算完成后，由 `clear_generic_effects_at_turn_end()` 统一清空。
             - 如果是 'REGULAR' 效果:
               - 烧伤、中毒：根据 `intensity` 和 `stacks` 计算固定伤害，调用 `char_manager.apply_damage()`，层数-1。
               - 呼吸法：应用暴击率加成，层数-1。
               - 破裂、流血：仅在触发时减少层数（受击/行动后），回合结束不处理。
             - 如果是 'SPECIAL' 效果，执行其特定的回合结束逻辑 (如黑夜领域持续时间-1)。
          3. 更新数据库。
        """
        pass

    def get_character_effects(self, character_id: int) -> list[StatusEffect]:
        """
        获取一个角色当前所有的状态效果。
        """
        pass

    def get_stat_modification(self, character_id: int, stat_name: str) -> float:
        """
        查询状态效果对特定属性（如造成伤害、受到伤害）的总修正。
        - 伪代码:
          1. 获取角色所有效果。
          2. 遍历效果，累加对 `stat_name` 的影响。
          3. 例如，'STRENGTH' 增加伤害，'WEAKNESS' 减少伤害。
          4. 返回最终的修正系数（如 1.2 表示增加 20%）。
        """
        pass

    def clear_effects_on_stage_end(self):
        """
        在 Stage End 清除所有临时效果：
        - 全部通用效果 (GENERIC)
        - 全部常规效果 (REGULAR)
        - 全部临时特殊效果
        - 全部尚未激活的待生效效果
        """
        pass

    def clear_generic_effects_at_turn_end(self, character_id: int):
        """
        在该角色全部 TURN_END 行为、常规效果和特殊效果结算完毕后，
        清除强壮、虚弱、守护、护盾、易伤、麻痹六种通用效果。
        TURN_END 中希望影响下一回合的通用效果必须写入 battle_pending_effects，不能写入活动效果表。
        """
        pass

    def clear_all_effects_on_battle_end(self):
        """
        在 Battle End 清除所有角色的所有效果，并清空全部待生效效果与已注册时机行为。
        """
        pass
```

### 3.4 模块交互

- **与技能系统 (Skill System)**:
  - 技能系统是状态效果的主要来源。它会调用 `apply_effect()` 将 Buff/Debuff 施加给目标。

- **与回合管理系统 (Turn Management System)**:
  - 回合结束时，回合管理系统会为每个角色调用本系统的 `process_turn_end_effects()` 方法来结算持续伤害/治疗和减少持续时间。
  - Stage End 和 Battle End 时，会调用相应的清理方法。

- **与角色管理系统 (Character Management System)**:
  - 本系统在结算效果伤害/治疗时，需要调用角色管理系统的接口来更新角色的 HP。
  - 角色管理系统在显示角色状态时，需要调用本系统查询角色当前的效果列表。

### 3.5 用户接口 (Telegram 命令)

> 注：以下为设计期命令名，v2 实际注册命令以第10节映射为准。

该模块在后端运行，通常不直接暴露给用户。其效果通过 `/show <character_name>` 命令在角色状态中展示。

---
## 4. 情感系统 (Emotion System)

### 4.1 模块职责

情感系统为战斗引入了动态的短期成长机制。角色通过在战斗中的特定行为获取“情感硬币”，累积硬币可提升“情感等级”，从而解锁更强大的技能或获得增益。

新版不再保留独立的理智机制。情感数值本身不直接修改基础伤害；它通过情感等级、等级4的临时额外行动次数、异想体书页选择和 EGO 解锁间接改变战局。这样可以避免“同一个资源既直接加伤害、又增加行动、又提供被动”造成不可控的复合倍率。

#### 情感硬币获取规则

| 事件类型 | 硬币类型 | 获取数量 | 触发条件 |
| :--- | :--- | :--- | :--- |
| **骰子投掷** | 正面 | 1 | 骰子结果为最大值（如6面骰投出6） |
| **骰子投掷** | 负面 | 1 | 骰子结果为1 |
| **造成伤害** | 正面/负面 | 根据伤害值 | 技能造成伤害后 |
| **进行治疗** | 正面 | 根据治疗量 | 技能治疗友方后 |
| **击杀敌人** | 正面 | 额外奖励 | 攻击导致敌人死亡 |

#### 情感等级阈值

| 等级 | 所需总硬币数 | 基础升级奖励 | 额外收益 (核心角色限定) |
| :--- | :--- | :--- | :--- |
| 0→1 | 3 | 所有普通技能冷却-1 | 抽取异想体书页 |
| 1→2 | 3 | 所有普通技能冷却-1 | 抽取异想体书页 |
| 2→3 | 5 | 所有普通技能冷却-1 | 抽取异想体书页 |
| 3→4 | 7 | 所有普通技能冷却-1 + 本场战斗最高行动力+1（临时）| 抽取异想体书页 |
| 4→5 | 9 | 所有普通技能冷却-1 | 抽取异想体书页 |

**注意**：
- 等级4的额外行动次数是临时的，会在战斗结束时移除
- Stage End 保留情感等级和硬币以及已选的异想体书页
- Battle End 重置情感等级和硬币为0，并彻底重置所有的书页状态
- 旧版“情感被动常驻增益”（如固定强壮/守护）不再使用；回合开始被动统一由异想体书页触发

#### 主要职责

- **硬币管理**：根据战斗事件（如骰子结果、造成伤害、击杀敌人）为角色增减情感硬币。
- **等级提升**：当硬币达到升级阈值时，自动提升角色的情感等级。
- **异想体书页抽取**：当核心角色升级时，根据正/负硬币的占比，从书页池中抽取“觉醒型”或“崩溃型”书页供玩家3选1。
- **升级效果处理**：执行升级带来的效果，主要是为角色的所有技能缩减冷却时间，以及应用书页效果。
- **回合开始书页被动触发**：在每回合开始时触发角色已激活异想体书页的被动效果。
- **状态重置**：在 Stage End 和 Battle End 时，根据规则保留或重置角色的情感等级、硬币及书页。
- **日志记录**：记录所有硬币获取和等级提升的事件，便于调试和追溯。

异想体书页的设计目标不仅是随机奖励，也是本场战斗的被动构筑。书页应能与人格技能组形成搭配；随着战斗持续和情感等级提高，角色持有的书页逐步增多，从而形成单场战斗内的成长曲线。

### 4.2 数据结构 / 数据库设计

情感系统的核心数据（等级和硬币）已包含在 `characters` 表中。我们还需要一个表来记录情感事件日志。升级所需的硬币数量可以作为配置常量。

#### `characters` 表扩展字段

| 字段名 | 类型 | 描述 | 示例 |
| :--- | :--- | :--- | :--- |
| `emotion_level` | INTEGER | 当前情感等级 (0-5) | 2 |
| `positive_emotion_coins` | INTEGER | 正面情感硬币数量 | 5 |
| `negative_emotion_coins` | INTEGER | 负面情感硬币数量 | 2 |
| `pending_emotion_upgrade` | INTEGER | 待升级标志 (0/1) | 0 |
| `emotion_bonus_actions` | INTEGER | 情感系统提供的临时额外行动次数 (战斗结束重置) | 1 |
| `active_abnormality_pages`| TEXT | 角色当前激活的异想体书页ID列表 (JSON) | `[101, 105]` |

#### 4.2.1 `emotion_log` 表

记录情感相关的事件。

| 字段名 | 类型 | 描述 | 示例 |
| :--- | :--- | :--- | :--- |
| `id` | INTEGER | 主键 | 501 |
| `character_id`| INTEGER | 关联的角色ID | 1 |
| `event_type` | TEXT | 事件类型 (`COIN_GAIN`, `LEVEL_UP`) | "COIN_GAIN" |
| `positive_coins` | INTEGER | 正面硬币变化量 | 2 |
| `negative_coins` | INTEGER | 负面硬币变化量 | 1 |
| `reason` | TEXT | 事件原因 (e.g., "DICE_MAX", "DICE_MIN", "DEAL_DAMAGE") | "DICE_MAX" |
| `timestamp` | DATETIME | 事件发生时间 | `2023-10-27 10:00:00` |

#### 4.2.2 异想体书页池相关表 (Abnormality Pages)

支持玩家“战前配置异想体，战斗中抽取书页”的核心系统表。

##### `abnormalities` 表 (异想体定义)
| 字段名 | 类型 | 描述 |
| :--- | :--- | :--- |
| `id` | INTEGER | 主键 |
| `name` | TEXT | 异想体名称 (例如: "焦化少女") |

##### `abnormality_pages` 表 (书页定义)
| 字段名 | 类型 | 描述 | 示例 |
| :--- | :--- | :--- | :--- |
| `id` | INTEGER | 主键 | 101 |
| `abnormality_id` | INTEGER | 外键，关联 `abnormalities` | 1 |
| `name` | TEXT | 书页名称 | "火柴" |
| `type` | TEXT | 书页类型: `AWAKENING` (觉醒) / `BREAKDOWN` (崩溃) | "AWAKENING" |
| `effect_description` | TEXT | 效果描述文本 | "造成伤害时附加1层烧伤" |
| `special_effect_id` | TEXT | 关联到特殊效果扩展系统的处理标识 | "AB_PAGE_MATCHBOX" |

##### `battle_page_pool` 表 (当前战斗的书页抽卡池)
| 字段名 | 类型 | 描述 |
| :--- | :--- | :--- |
| `id` | INTEGER | 主键 |
| `page_id` | INTEGER | 外键，关联 `abnormality_pages` |
| `status` | TEXT | 状态: `AVAILABLE` (在池中), `USED` (已被选取) |

### 4.3 核心函数 / API 设计

#### `EmotionManager` 类

```python
# 配置常量
EMOTION_LEVEL_THRESHOLDS = {1: 3, 2: 3, 3: 5, 4: 7, 5: 9}

# 情感升级奖励配置
EMOTION_LEVEL_BONUSES = {
    4: {'bonus_actions': 1}  # 达到4级时获得1点额外行动次数
}

class EmotionManager:
    def __init__(self, db_connection, character_manager, skill_manager):
        self.db = db_connection
        self.char_manager = character_manager
        self.skill_manager = skill_manager

    def add_coins(self, character_id: int, positive_coins: int, negative_coins: int, reason: str):
        """
        为角色增加情感硬币（正面和负面），并检查是否升级。
        - 伪代码:
          1. 获取角色当前的正面/负面硬币数和情感等级。
          2. 累加正面和负面硬币数量。
          3. 计算总硬币数 (positive + negative)。
          4. 记录硬币获取日志到 `emotion_log` 表。
          5. 调用 `_check_for_level_up()`。
          6. 更新 `characters` 表中的硬币数量。
        - 硬币来源示例:
          - 骰子最大值: positive_coins += 1
          - 骰子值为1: negative_coins += 1
          - 造成伤害/治疗: 根据数值获得硬币
        """
        pass

    def _check_for_level_up(self, character_id: int):
        """
        检查角色是否满足升级条件，如果满足则设置待升级标记。
        - 伪代码:
          1. 获取角色当前等级和正面/负面硬币。
          2. 计算总硬币数 (positive + negative)。
          3. 确定下一级所需硬币 `required_coins = EMOTION_LEVEL_THRESHOLDS[current_level + 1]`。
          4. 如果 `total_coins >= required_coins`:
             a. 设置 `pending_emotion_upgrade = 1`。
          5. 更新 `characters` 表。
        """
        pass

    def _execute_emotion_upgrade(self, character_id: int):
        """
        执行实际的情感升级逻辑。
        - 伪代码:
          1. 获取角色当前等级和正面/负面硬币。
          2. 确定升级类型 (正面升级: positive >= negative, 否则为负面升级；平局判正面，与书页抽取及 src/dewbot/engine.py 实现一致)。
          3. `emotion_level += 1`。
          4. 清空所有硬币 (positive = 0, negative = 0)。
          5. 重置 `pending_emotion_upgrade = 0`。
          6. 调用 `_apply_level_up_bonus()`。
          7. 记录升级日志。
        """
        pass

    def _draw_abnormality_pages(self, character_id: int, positive_coins: int, negative_coins: int):
        """
        （核心角色专属）从战斗卡池中抽取异想体书页，触发抽取界面。
        - 伪代码:
          1. 查询角色是否为核心角色 (is_core == True)，若否，则跳过。
          2. 从 `battle_page_pool` 表中获取状态为 `AVAILABLE` 的书页。
          3. 如果可用书页为空，通知跳过抽取。
          4. 根据硬币比例决定抽取类型: 
             如果 positive_coins >= negative_coins，优先抽取 `AWAKENING` (觉醒型)；否则优先抽取 `BREAKDOWN` (崩溃型)。
          5. 随机抽取至多 3 张符合条件的书页。
          6. 将抽取结果打包并触发 UI 交互 (如通过 Bot 发送书页选择键盘)。
        """
        pass

    def apply_abnormality_page(self, character_id: int, page_id: int):
        """
        处理玩家在 UI 中选定的异想体书页。
        - 伪代码:
          1. 验证目标书页确实在当前待选的列表中。
          2. 将 `battle_page_pool` 中该书页的 `status` 标记为 `USED`。
          3. 将 `page_id` 添加到角色的 `active_abnormality_pages` 列表中。
          4. 执行书页的即时/被动效果 (通过对接 `SpecialEffectManager`)。
        """
        pass

    def _apply_level_up_bonus(self, character_id: int, new_level: int, positive_coins: int, negative_coins: int):
        """
        应用升级后的奖励。
        - 伪代码:
          1. 【通用奖励】对该角色所有普通技能减少1回合冷却时间（EGO不参与）。
          2. 【等级特定奖励】检查 EMOTION_LEVEL_BONUSES[new_level]:
             - 如果包含 'bonus_actions'，则:
               a. 增加角色的 `emotion_bonus_actions` 字段。
               b. 同时增加角色的 `current_actions` 和 `max_actions`。
               c. 这个临时额外行动次数会在战斗结束时移除。
          3. 【核心角色独立奖励】调用 `_draw_abnormality_pages` 进行异想体书页抽取。
        """
        pass
    
    def process_turn_start_emotions(self, character_id: int):
        """
        在回合开始时处理情感相关逻辑。
        - 伪代码:
          1. 检查角色是否有 `pending_emotion_upgrade = 1`。
          2. 如果有，则调用 `_execute_emotion_upgrade()`。
          3. 调用 `_trigger_abnormality_pages_on_turn_start(character_id)` 触发该角色已激活书页的回合开始被动。
          4. 返回回合开始结算消息列表。
        """
        pass

    def _trigger_abnormality_pages_on_turn_start(self, character_id: int):
        """
        触发异想体书页的回合开始被动。
        - 伪代码:
          1. 读取角色 `active_abnormality_pages`。
          2. 遍历每张书页，调用 `SpecialEffectManager` 执行其 `on_turn_start` 钩子。
          3. 收集并返回所有被动触发播报。
        """
        pass

    def reset_for_battle_end(self):
        """
        战斗结束时重置所有角色的情感状态及异想体书页系统。
        - 伪代码:
          1. 对所有角色:
             a. 将 `emotion_level`, `positive_emotion_coins`, `negative_emotion_coins` 更新为 0。
             b. 将 `pending_emotion_upgrade` 更新为 0。
             c. 将 `emotion_bonus_actions` 产生的额外行动次数从 `max_actions` 中扣除。
             d. 将 `emotion_bonus_actions` 更新为 0。
             e. 清空 `active_abnormality_pages` 列表。
          2. 重置 `battle_page_pool` (清空该表)。
        """
        pass
```

### 4.4 模块交互

- **与角色管理系统 (Character Management System)**:
  - 情感系统的所有操作都围绕着更新 `characters` 表中的 `emotion_level`、`positive_emotion_coins`、`negative_emotion_coins` 字段。

- **与技能系统 (Skill System)**:
  - 技能系统中的某些行为（如造成伤害、治疗）会触发本系统的 `add_coins()` 方法。
  - 情感系统升级时，会调用 `skill_manager.reduce_cooldown()` 来缩减技能冷却。

- **与回合管理系统 (Turn Management System)**:
  - 回合管理系统在 `Stage End` 时会保留情感数据，但在 `Battle End` 时会调用本系统的 `reset_for_battle_end()` 进行重置。
  - 回合开始时，可以调用 `process_turn_start_emotions` 来统一处理升级与异想体书页被动触发。

### 4.5 用户接口 (Telegram 命令)

> 注：以下为设计期命令名，v2 实际注册命令以第10节映射为准。

情感系统是自动运行的，没有直接的用户命令。其状态通过 `/show <character_name>` 命令展示。书页的选择界面会在情感升级时由机器人以交互式选项（如 Inline Keyboard）自动弹出。

- `/emotion_log <character_name>`: (管理命令) 显示指定角色的情感事件历史记录。
- `/equip_abnormality <character_name> <abnormality_id>`: (战前命令) 为核心角色配备一个异想体（将其书页洗入备用池中）。

---
## 5. 回合管理系统 (Turn Management System)

### 5.1 模块职责

回合管理系统是战斗流程的“心脏”，负责协调和驱动整个战斗的进行。它定义了战斗的各个阶段（回合、场景、战斗），并按照正确的顺序调用其他模块，处理状态的结算和重置。

一个回合固定为：

```text
TURN_START -> FRIENDLY_ACTION -> ENEMY_ACTION -> TURN_END
```

只有我方全部行动完成后才进入敌方行动阶段；敌方全部行动完成后才进入回合结束。系统不执行拼点或双方同时行动。

其主要职责包括：
- **战斗状态机管理**：维护当前战斗的全局状态，如当前回合数、当前阶段与当前流程相位（Battle/Stage/Turn 的 Start/End）。
- **回合开始处理 (Turn Start)**：处理回合开始逻辑（如情感升级结算、异想体书页回合开始被动触发），并开启本回合行动窗口。
- **我方行动阶段 (Friendly Action)**：允许所有具备行动次数且能够行动的我方角色依次使用技能。
- **敌方行动阶段 (Enemy Action)**：我方阶段结束后，允许所有具备行动次数且能够行动的敌方角色依次使用技能。
- **回合结束处理 (Turn End)**：触发所有角色的回合结束逻辑，包括状态效果结算、行动次数恢复等。
- **战斗开始处理 (Battle Start)**：初始化战斗级状态与临时数据，并进入阶段开始流程。
- **阶段开始处理 (Stage Start)**：每个新阶段开始时，根据选择结果将角色加入战斗。
- **场景结束处理 (Stage End)**：当当前波次敌人被全部击败且仍有后续阶段时，执行场景结束逻辑，清理临时状态并准备下一波。
- **战斗结束处理 (Battle End)**：当所有友方被击败、最终阶段被完成或管理人手动终止时，执行战斗结束逻辑，完全重置战斗状态。
- **流程协调**：作为协调者，按预定顺序调用角色管理、状态效果和情感等系统接口，采用“解耦但连续执行”的链路（如 `end_turn()` 后进入 `start_turn()`）。

### 5.2 数据结构 / 数据库设计

回合管理主要依赖一个全局的战斗状态对象，该对象可以在内存中管理，也可以持久化以备不时之需。

#### 5.2.1 `battle_state` 表 (或内存对象)

存储当前战斗的全局信息。

| 字段名 | 类型 | 描述 | 示例 |
| :--- | :--- | :--- | :--- |
| `id` | INTEGER | 主键, 通常只有一行数据 | 1 |
| `current_turn`| INTEGER | 当前战斗的回合数 | 3 |
| `current_stage` | INTEGER | 当前阶段序号 | 2 |
| `battle_phase`| TEXT | 当前流程相位 (`BATTLE_START`, `STAGE_START`, `TURN_START`, `FRIENDLY_ACTION`, `ENEMY_ACTION`, `TURN_END`, `STAGE_END`, `BATTLE_END`) | "FRIENDLY_ACTION" |
| `pending_stage_selection` | INTEGER | 是否等待阶段入战选择 (0/1) | 0 |
| `active_character_id`| INTEGER | 当前行动的角色ID (为未来扩展，当前系统为统一回合) | 2 |

### 5.3 核心函数 / API 设计

#### `TurnManager` 类

```python
class TurnManager:
    def __init__(self, db_connection, char_manager, effect_manager, emotion_manager, skill_manager):
        self.db = db_connection
        self.char_manager = char_manager
        self.effect_manager = effect_manager
        self.emotion_manager = emotion_manager
        self.skill_manager = skill_manager

    def start_turn(self):
        """
        处理一个标准的回合开始 (Turn Start)。
        - 伪代码:
          1. 更新 `battle_state` 的 `battle_phase` 为 'TURN_START'。
          2. 如果 `pending_stage_selection == 1`，则等待 `start_stage()` 选人，不进入行动阶段。
          3. 增加 `battle_state.current_turn` 计数。
          4. 获取所有在战斗中的存活角色列表。
          5. 对每个角色调用 `emotion_manager.process_turn_start_emotions(char_id)`：
             - 处理待升级情感。
             - 触发异想体书页的回合开始被动。
          6. 激活 `battle_pending_effects` 中 `activate_at = NEXT_TURN_START` 的待生效效果。
          7. 触发全场 `TURN_START` 行为；例如我方回合开始获得护盾、敌方此前安排的下回合虚弱/麻痹生效。
          8. 初始化本回合行动窗口（如当前可行动角色）。
          9. 将 `battle_phase` 切换为 'FRIENDLY_ACTION'。
         """
         pass

    def end_friendly_action_phase(self):
        """
        我方全部行动完成后调用，将 `battle_phase` 切换为 `ENEMY_ACTION`。
        不在此时结算回合结束效果、清除通用效果或推进自然冷却。
        """
        pass

    def end_enemy_action_phase(self):
        """
        敌方全部行动完成后调用，进入统一的 `end_turn()`。
        """
        pass

    def end_turn(self):
        """
        处理一个标准的回合结束 (Turn End)。
        - 伪代码:
          1. 仅允许从 `ENEMY_ACTION` 结束后进入，并更新 `battle_state.battle_phase = 'TURN_END'`。
          2. 获取所有在战斗中的角色列表，触发全场 `TURN_END` 行为。
          3. 对每个角色，按顺序执行:
             a. 调用 `effect_manager.process_turn_end_effects(char_id)` 结算 DoT/HoT。
             b. 检查死亡状态。
             c. 调用 `effect_manager.clear_generic_effects_at_turn_end(char_id)`，清除六种通用效果。
             d. 调用 `char_manager.reset_for_turn_end(char_id)`:
                - 处理混乱状态: 如果 `is_staggered == True`，则 `stagger_turns -= 1`。
                - 如果 `stagger_turns` 归零，解除混乱状态: `is_staggered = False`。
                - 如果解除后或原本并未混乱 (`is_staggered == False`)，才恢复行动力: `current_actions = max_actions`。否则 `current_actions = 0`。
                - (混乱逻辑说明：混乱条清零时进入混乱状态，`stagger_turns` 初始为2，经过两次回合结束后归零并解除，实现"当回合进入混乱，下回合结束解除")。
          4. 调用 `skill_manager.advance_all_normal_cooldowns_at_turn_end()`，令全场普通技能 CD -1；EGO 不参与。
          5. 如果所有友方阵亡，调用 `end_battle(result='DEFEAT')`。
          6. 如果当前波次敌人全部阵亡：
             - 仍有下一阶段：调用 `end_stage()`。
             - 已是最终阶段：调用 `end_battle(result='VICTORY')`。
          7. 其他情况下调用 `start_turn()` 进入下一回合（调用链连续执行，但回合开始逻辑与回合结束逻辑保持解耦）。
        """
        pass

    def start_stage(self, stage_index: int, friendly_ids: list[int], enemy_ids: list[int]):
        """
        处理一个场景/波次开始 (Stage Start)。
        - 伪代码:
          1. 更新 `battle_state.current_stage = stage_index`，并将 `battle_phase` 置为 `STAGE_START`。
          2. 将所有角色先设为 `is_in_battle = False`。
          3. 将被选中的友方 `friendly_ids` 和敌方 `enemy_ids` 设为 `is_in_battle = True`。
          4. 初始化本阶段临时数据（如阶段内统计、阶段事件快照）。
          5. 清空 `pending_stage_selection`。
          6. 调用 `start_turn()` 开启该阶段首回合。
        """
        pass

    def end_stage(self):
        """
        处理一个场景/波次结束 (Stage End)。
        - 伪代码:
          1. 更新 `battle_state` 的 `battle_phase` 为 'STAGE_END'。
          2. 调用 `effect_manager.clear_effects_on_stage_end()` 清除全部临时效果（含临时特殊效果）。
          3. 清除 `battle_registered_behaviors` 中全部临时行为和 `battle_pending_effects`。
          4. 对所有角色:
             a. 重置混乱值 `current_stagger = max_stagger`。
             b. 设置 `is_in_battle = False`。
          5. 设置 `pending_stage_selection = 1`，进入下一阶段的入战选择流程。
          6. 若没有下一阶段，改由 `end_battle()` 收尾。
        """
        pass

    def end_battle(self, result: str | None = None):
        """
        处理整个战斗结束 (Battle End)。
        - 伪代码:
          1. 更新 `battle_state` 的 `battle_phase` 为 'BATTLE_END'。
          2. 执行最终清理：`effect_manager.clear_all_effects_on_battle_end()`。
          3. 调用 `emotion_manager.reset_for_battle_end()`。
          4. 将所有角色的 `is_in_battle` 设为 `False`。
          5. 清理战斗相关临时数据（包括清空 `battle_skill_cooldowns`、`battle_ego_usage`、`battle_pending_effects` 与 `battle_registered_behaviors`）。
          6. 重置 `pending_stage_selection = 0`。
        """
        pass

    def start_battle(self, characters: list, enemies: list):
        """
        初始化一场新的战斗。
        - 伪代码:
          1. 重置或创建 `battle_state`，并将 `battle_phase` 置为 `BATTLE_START`。
          2. 初始化战斗级临时数据（冷却表、EGO使用表、待生效效果表、已注册行为表和管理人资源状态）。
          3. 将所有角色 `is_in_battle = False`，并设置 `pending_stage_selection = 1`。
          4. 按第一阶段选择结果调用 `start_stage(stage_index=1, friendly_ids, enemy_ids)`。
        """
        pass
```

### 5.4 模块交互

- **与角色管理系统 (Character Management System)**:
  - 频繁交互。在回合、场景、战斗的开始与结束流程中，都需要调用角色管理系统的方法来重置或更新角色状态（行动力、混乱值、在战斗标记等）。

- **与状态效果系统 (Status Effect System)**:
  - 在回合结束时调用状态效果系统来结算持续效果，在场景/战斗结束时调用其清理接口。

- **与技能和事件系统 (Skill/Event System)**:
  - 在 `TURN_START`/`TURN_END` 触发已注册行为；在 `TURN_END` 调用技能系统统一推进全场普通技能冷却。

- **与情感系统 (Emotion System)**:
  - 在回合开始时调用 `process_turn_start_emotions` 处理升级与书页被动。
  - 在战斗结束时，调用情感系统接口重置所有角色的情感等级和硬币。

### 5.5 用户接口 (Telegram 命令)

> 注：以下为设计期命令名，v2 实际注册命令以第10节映射为准。

- `/start_turn`: (管理命令) 手动触发回合开始逻辑（通常由 `end_turn` 后自动串接执行）。
- `/end_friendly_phase`: 我方行动完成后，将阶段从 `FRIENDLY_ACTION` 切换到 `ENEMY_ACTION`。
- `/end_turn`: 仅在敌方行动阶段完成后触发 `TURN_END`；拒绝从我方阶段直接调用。
- `/start_battle`: (管理命令) 手动开始一场战斗，需要指定参战的友方和敌方单位。
- `/start_stage`: (管理命令) 在 Stage End 后为下一阶段选择入战角色并开始新阶段。
- `/reset_battle`: (管理命令) 强制结束并重置当前战斗，调用 `end_battle()`。

---
## 6. 攻击逻辑系统 (Attack Logic System)

### 6.1 模块职责

攻击逻辑系统是用户与战斗系统交互的核心入口。它负责处理玩家通过 Telegram 界面发起的攻击指令，引导用户完成“选择攻击者 -> 选择技能 -> 选择目标”的完整流程，并最终触发技能的执行。

其主要职责包括：
- **会话状态管理**：使用 `ConversationHandler` (或类似机制) 管理多步骤的用户交互流程，保存每一步的选择。
- **用户输入引导**：通过内联键盘 (Inline Keyboard) 向用户展示可选的角色、技能和目标，并接收用户的选择。
- **输入验证**：在流程的每一步验证用户的选择是否合法。例如，检查所选角色是否有行动次数，所选技能是否可用（冷却、情感等级），所选目标是否符合技能要求。
- **行动阶段验证**：`/attack` 只允许在 `FRIENDLY_ACTION` 使用，`/enemy` 只允许在 `ENEMY_ACTION` 使用；任何攻击流程都不能越过当前回合阶段。
- **流程控制**：根据用户的选择，动态生成下一步的选项。例如，选择一个 AOE 技能后，跳过目标选择步骤。
- **触发执行**：在收集完所有必要信息后，调用技能系统的 `execute_skill` 方法，并将结果播报给用户。

### 6.2 数据结构 / 数据库设计

该系统主要是流程控制和用户交互，不产生需要持久化的核心数据。其状态主要通过 `ConversationHandler` 的 `context.user_data` 在内存中临时管理。

#### `context.user_data` 结构示例

```json
{"attack_flow": {"state": "SELECTING_SKILL", "attacker_id": 1, "skill_id": null, "selected_skill_targets": []}}
```

### 6.3 核心函数 / API 设计

该模块的核心是 `python-telegram-bot` 库的 `ConversationHandler`，它由一系列回调函数组成。

#### `AttackConversation` 类/模块

```python
# Conversation states
SELECTING_ATTACKER, SELECTING_SKILL, SELECTING_TARGET = range(3)

class AttackConversation:
    def __init__(self, skill_manager, char_manager):
        self.skill_manager = skill_manager
        self.char_manager = char_manager

    def start(self, update, context) -> int:
        """
        处理 /attack 命令，开始攻击流程。
        - 伪代码:
          1. 查找所有有行动次数的友方角色。
          2. 验证 `battle_phase == 'FRIENDLY_ACTION'`；如果不是，提示当前阶段并结束会话。
          3. 如果没有可行动角色，回复提示并结束会话；管理人可确认结束我方行动阶段。
          4. 生成角色选择的内联键盘。
          5. 回复消息，要求用户选择攻击者。
          6. 设置会话状态为 SELECTING_SKILL。
        """
        pass

    def select_skill(self, update, context) -> int:
        """
        处理用户选择攻击者的回调。
        - 伪代码:
          1. 从回调数据中获取 `attacker_id` 并存入 `context.user_data`。
          2. 根据角色的人格(如果有)获取其普通技能，并无视人格获取其专属EGO技能，合并作为技能池。
          3. 查询该角色所有可用的技能（满足情感要求、不在冷却中，若为EGO技能则检查本场是否已使用）。
          4. 如果没有可用技能，提示用户并结束会话。
          5. 生成技能选择的内联键盘。
          6. 编辑原消息，要求用户选择技能。
          7. 设置会话状态为 SELECTING_TARGET。
        """
        pass

    def select_target(self, update, context) -> int:
        """
        处理用户选择技能的回调。
        - 伪代码:
          1. 从回调数据中获取 `skill_id` 并存入 `context.user_data`。
          2. 获取技能定义，读取技能层目标合同 `skill_target_scope` + `skill_target_method`。
          3. 如果技能层目标方式不是 `SELECT_TARGET`（例如 `SELF/ALL_TARGETS/RANDOM`）:
             a. 调用 `_execute_and_report()` 执行技能（`selected_skill_targets` 为空，由技能层自动解析）。
             b. 结束会话 (ConversationHandler.END)。
          4. 如果技能层目标方式为 `SELECT_TARGET`:
             a. 按技能层 `skill_target_scope` 查询合法目标。
             b. 生成目标选择的内联键盘。
             c. 编辑原消息，要求用户选择目标。
             d. 返回当前状态，等待目标选择。
        """
        pass

    def execute_and_report(self, update, context) -> int:
        """
        处理用户选择目标的回调，并执行最终的攻击。
        - 伪代码:
          1. 从回调数据中获取并写入 `selected_skill_targets`（仅技能层选择一次）。
          2. 从 `context.user_data` 中集齐 `attacker_id`, `skill_id`, `selected_skill_targets`。
          3. 调用 `skill_manager.execute_skill(attacker_id, skill_id, selected_skill_targets=selected_skill_targets)`。
             - 注意：行为目标要么继承技能层目标，要么使用行为自带的自动目标逻辑（不再二次交互）。
          4. 获取技能执行结果的单一播报文本。
          5. 编辑原消息，显示战斗结果。
          6. 结束会话 (ConversationHandler.END)。
        """
        pass

    def cancel(self, update, context) -> int:
        """
        处理用户取消操作。
        """
        pass

class EnemyAttackConversation:
    def __init__(self, skill_manager, char_manager):
        self.skill_manager = skill_manager
        self.char_manager = char_manager

    # 敌方攻击流程与友方类似，但有以下关键区别：
    # 0. 阶段验证：仅 `battle_phase == 'ENEMY_ACTION'` 时允许开始或继续敌方攻击。
    # 1. 权限控制：只有发起命令的用户可以操作界面 (通过 context.user_data['enemy_attack_initiator'] 验证)。
    # 2. 角色池倒置：选择攻击者时从有行动次数的敌方角色中选择；目标选择池 (FRIENDLY/ENEMY) 的实际对象也会反转。
    # 3. 技能匿踪机制：为了防止玩家直接看到敌方的详细技能名称和数值，在 select_skill 步骤生成技能键盘时：
    #    - 按钮上的文本只显示“技能编号”（如“技能 1”、“技能 2”）。
    #    - 技能的真实详情（名称、伤害公式等）仅在使用回调查询(CallbackQuery)的弹窗 (`answer_callback_query(text=..., show_alert=True)`) 中显示给发起者。

# ConversationHandler setup
# conv_handler = ConversationHandler(
#     entry_points=[CommandHandler('attack', start)],
#     states={
#         SELECTING_SKILL: [CallbackQueryHandler(select_skill)],
#         SELECTING_TARGET: [CallbackQueryHandler(select_target)],
#         # ... and so on
#     },
#     fallbacks=[CommandHandler('cancel', cancel)]
# )
#
# enemy_conv_handler = ConversationHandler(
#     entry_points=[CommandHandler('enemy', enemy_start)],
#     states={ ... },
#     fallbacks=[CommandHandler('cancel', enemy_cancel)],
#     per_user=True  # 敌方攻击使用 per_user=True 保证会话隔离
# )
```

### 6.4 模块交互

- **与技能系统 (Skill System)**:
  - 这是攻击逻辑的最终执行者。本系统在收集完所有参数后，调用 `skill_manager.execute_skill()`。
  - 在生成选项时，需要查询技能系统获取技能层目标合同（如 `skill_target_scope` 和 `skill_target_method`）与行为目标来源（`target_source`）。

- **与角色管理系统 (Character Management System)**:
  - 在流程的每一步都需要查询角色数据，例如：获取可选的攻击者列表、获取目标的存活状态等。

- **与 Telegram API**:
  - 深度集成。通过 `CommandHandler` 和 `CallbackQueryHandler` 接收用户输入，通过 `update.message.reply_text` 和 `update.callback_query.edit_message_text` 发送反馈。

### 6.5 用户接口 (Telegram 命令)

> 注：以下为设计期命令名，v2 实际注册命令以第10节映射为准。

- `/attack`: 启动友方角色的攻击流程。
- `/enemy`: 启动敌方角色的攻击流程。敌方攻击必须在 `ConversationHandler` 层面使用 `per_user=True` 并包含发起者验证。选择敌方技能时只显示技能编号，通过弹窗机制让管理员/执行者查看详细技能。
- `/end_friendly_phase`: 我方全部行动完成后，由管理人确认进入 `ENEMY_ACTION`；也可以在所有我方角色都无可用行动时自动提示转换。
- `/end_turn`: 只允许在敌方行动阶段完成后调用，进入统一 `TURN_END`；不能从我方行动阶段直接跳过敌方阶段。
- `/cancel`: 在攻击流程中随时取消当前操作。

---
## 7. 特殊效果扩展系统 (Special Effect Extension System)

### 7.1 模块职责

特殊效果扩展系统是为保证 Dewbot 未来可扩展性而设计的关键模块。它提供了一个统一的框架，用于实现和管理那些无法通过标准行为（伤害、治疗、施加效果）来定义的复杂、独特的技能效果。例如：召唤单位、地形效果（黑夜领域）、被动光环等。

其主要职责包括：
- **效果注册与发现**：提供一个中心化的管理器，用于注册所有自定义的特殊效果处理器。
- **统一接口**：定义一个所有特殊效果都必须遵守的执行接口（例如，一个 `execute` 方法）。
- **解耦设计**：使技能系统无需了解任何特殊效果的具体实现细节。技能系统只需知道效果的名称和所需参数，然后将执行请求转发给本系统即可。
- **生命周期管理**：为有持续时间或需要周期性触发的特殊效果（如光环）提供必要的钩子（Hooks），使其能与回合管理系统协同工作。

### 7.2 数据结构 / 数据库设计

该系统以代码设计为主，数据库需求较少。主要是技能系统的 `skill_behaviors` 表中 `effect_type` 为 `SPECIAL` 的记录，其 `effect_value` 会是特殊效果的唯一名称，`effect_params` 会包含其执行所需的参数。

#### `skill_behaviors` 表示例

| `effect_type` | `effect_value` | `effect_params` |
| :--- | :--- | :--- |
| `SPECIAL` | `SUMMON_UNIT` | `{"unit_name": "机械警卫", "count": 2}` |
| `SPECIAL` | `WEAKEN_AURA` | `{"effect_value": 5, "duration": 5}` |

### 7.3 核心函数 / API 设计

该模块的设计核心是**策略模式 (Strategy Pattern)**。

#### `SpecialEffectInterface` (ABC)

```python
from abc import ABC, abstractmethod

class SpecialEffectInterface(ABC):
    @abstractmethod
    def execute(self, user, targets, params, battle_context):
        """
        执行特殊效果的接口。
        - user: 施法者 Character 对象
        - targets: 目标 Character 对象列表
        - params: 来自 skill_behaviors 表的 effect_params
        - battle_context: 包含所有管理器实例的上下文对象，用于与系统其他部分交互
        - 返回值: 一个描述效果结果的字符串，用于战斗播报
        """
        pass
```

#### 具体效果实现

```python
class SummonUnitEffect(SpecialEffectInterface):
    def execute(self, user, targets, params, battle_context):
        unit_name = params.get("unit_name")
        count = params.get("count")
        # 调用 character_manager 创建新单位
        battle_context.char_manager.create_character(name=unit_name, ...)
        return f"{user.name} 召唤了 {count} 个 {unit_name}！"

class AuraWeakenEffect(SpecialEffectInterface):
    def execute(self, user, targets, params, battle_context):
        # 特殊效果不走强度/层数体系，全部状态由自定义参数管理
        duration = params.get("duration")
        effect_value = params.get("effect_value")
        battle_context.effect_manager.apply_effect(
            target_id=user.id,
            effect_name="WEAKEN_AURA",
            category="SPECIAL",
            params={
                "remaining_turns": duration,
                "effect_value": effect_value
            }
        )
        return f"{user.name} 展开了削弱光环！"
```

#### `SpecialEffectManager`

```python
class SpecialEffectManager:
    def __init__(self):
        self._effects = {}

    def register_effect(self, name: str, handler: SpecialEffectInterface):
        """
        注册一个特殊效果处理器。
        """
        self._effects[name] = handler

    def execute(self, name: str, user, targets, params, battle_context):
        """
        查找并执行一个特殊效果。
        - 伪代码:
          1. 检查 `name` 是否已注册。
          2. 如果是，调用 `handler.execute(...)`。
          3. 如果否，记录错误并返回。
        """
        handler = self._effects.get(name)
        if handler:
            return handler.execute(user, targets, params, battle_context)
        else:
            # Log error
            return f"错误：未知的特殊效果 '{name}'。"

# 初始化时注册所有效果
# spec_manager = SpecialEffectManager()
# spec_manager.register_effect("SUMMON_UNIT", SummonUnitEffect())
# spec_manager.register_effect("WEAKEN_AURA", AuraWeakenEffect())
```

### 7.4 模块交互

- **与技能系统 (Skill System)**:
  - 当技能行为的 `effect_type` 是 `SPECIAL` 时，技能系统的 `_apply_effect` 方法会调用本系统的 `execute()` 方法，并将效果名称 (`effect_value`) 和参数 (`effect_params`) 传递过来。

- **与其他所有系统**:
  - 特殊效果的实现类可以通过传入的 `battle_context` 对象，自由地与任何其他系统（角色管理、状态效果、回合管理等）进行交互，赋予其极高的灵活性。

### 7.5 常见特殊效果实现示例

**注意**: 特殊效果不使用强度/层数体系，而是使用自定义参数来管理状态。

#### 硬血 (Hardblood) 效果

硬血是一个特殊的资源池系统，可被技能消耗以增强效果。

```python
class HardbloodEffect(SpecialEffectInterface):
    def execute(self, user, targets, params, battle_context):
        amount = params.get("amount", 0)
        current_hardblood = battle_context.effect_manager.get_effect(user.id, "HARDBLOOD")
        if current_hardblood:
            # 累加硬血数量
            new_amount = current_hardblood.custom_params.get("amount", 0) + amount
            battle_context.effect_manager.update_effect_params(
                user.id, "HARDBLOOD", {"amount": new_amount}
            )
        else:
            # 首次获得硬血
            battle_context.effect_manager.apply_effect(
                target_id=user.id,
                effect_name="HARDBLOOD",
                category="SPECIAL",
                params={"amount": amount, "stage_persistent": False}
            )
        return f"{user.name} 获得了 {amount} 点硬血！"

class HardbloodConsumeEffect(SpecialEffectInterface):
    def execute(self, user, targets, params, battle_context):
        consume_amount = params.get("consume", 0)
        damage_multiplier = params.get("damage_multiplier", 1.5)
        
        # 获取当前硬血数量
        hardblood = battle_context.effect_manager.get_effect(user.id, "HARDBLOOD")
        current_amount = hardblood.custom_params.get("amount", 0) if hardblood else 0
        
        # 计算实际消耗的硬血数量(不超过拥有的数量)
        actual_consume = min(consume_amount, current_amount)
        
        if actual_consume > 0:
            # 消耗硬血
            new_amount = current_amount - actual_consume
            if new_amount > 0:
                battle_context.effect_manager.update_effect_params(
                    user.id, "HARDBLOOD", {"amount": new_amount}
                )
            else:
                battle_context.effect_manager.remove_effect(user.id, "HARDBLOOD")
            
            # 根据消耗的硬血增强伤害
            return {
                "damage_multiplier": 1 + (actual_consume / consume_amount) * (damage_multiplier - 1),
                "message": f"{user.name} 消耗了 {actual_consume} 点硬血，伤害增强！"
            }
        else:
            # 没有硬血可消耗，技能仍然可以使用，只是没有增强效果
            return {
                "damage_multiplier": 1.0,
                "message": f"{user.name} 硬血不足，技能未获得增强。"
            }
```

#### 黑夜领域 (Dark Domain) 效果

黑夜领域是一个复合特殊效果，包含多种子效果和死亡免疫。

```python
class DarkDomainEffect(SpecialEffectInterface):
    def execute(self, user, targets, params, battle_context):
        duration = params.get("duration", 3)
        
        # 应用黑夜领域状态(使用自定义参数，不使用强度/层数)
        battle_context.effect_manager.apply_effect(
            target_id=user.id,
            effect_name="DARK_DOMAIN",
            category="SPECIAL",
            params={
                "remaining_turns": duration,
                "stage_persistent": False,
                "death_immunity_used": False,  # 死亡免疫是否已使用
                "turn_end_effects": {
                    "STRENGTH": {"value": 6},
                    "VULNERABLE": {"value": 6},
                    "BONUS_ACTIONS": {"value": 1},  # 1额外行动点
                    "emotion_coins": {"negative": 666}
                }
            }
        )
        return f"{user.name} 展开了黑夜领域！"

# 在回合结束时处理黑夜领域效果
def process_dark_domain_turn_end(character_id, effect, battle_context):
    """在状态效果系统的 process_turn_end_effects 中调用"""
    params = effect.custom_params
    turn_effects = params.get("turn_end_effects", {})
    
    # TURN_END 不能留下通用效果；强壮安排到下一回合开始生效
    if "STRENGTH" in turn_effects:
        value = turn_effects["STRENGTH"]["value"]
        battle_context.effect_manager.queue_pending_effect(
            character_id, "STRENGTH", "GENERIC", intensity=value,
            activate_at="NEXT_TURN_START", source="DARK_DOMAIN"
        )
    
    # 易伤同样在下一回合开始生效，并在该回合结束清空
    if "VULNERABLE" in turn_effects:
        value = turn_effects["VULNERABLE"]["value"]
        battle_context.effect_manager.queue_pending_effect(
            character_id, "VULNERABLE", "GENERIC", intensity=value,
            activate_at="NEXT_TURN_START", source="DARK_DOMAIN"
        )
    
    # 额外行动点在下一回合开始一次性生效
    if "BONUS_ACTIONS" in turn_effects:
        value = turn_effects["BONUS_ACTIONS"]["value"]
        battle_context.effect_manager.queue_pending_effect(
            character_id, "BONUS_ACTIONS", "INSTANT",
            activate_at="NEXT_TURN_START", params={"amount": value},
            source="DARK_DOMAIN"
        )
    
    # 添加负面情感币
    if "emotion_coins" in turn_effects:
        coins = turn_effects["emotion_coins"]
        battle_context.emotion_manager.add_coins(
            character_id, 
            positive_coins=0,
            negative_coins=coins.get("negative", 0),
            reason="DARK_DOMAIN_TURN_END"
        )
    
    # 减少剩余回合数
    params["remaining_turns"] -= 1
    if params["remaining_turns"] <= 0:
        battle_context.effect_manager.remove_effect(character_id, "DARK_DOMAIN")
```

#### 削弱光环 (Weaken Aura) 效果

削弱光环是一个持续性的范围减益效果。

```python
class WeakenAuraEffect(SpecialEffectInterface):
    def execute(self, user, targets, params, battle_context):
        duration = params.get("duration", 5)
        effect_value = params.get("effect_value", 5)
        
        # 应用削弱光环(使用自定义参数，不使用强度/层数)
        battle_context.effect_manager.apply_effect(
            target_id=user.id,
            effect_name="WEAKEN_AURA",
            category="SPECIAL",
            params={
                "remaining_turns": duration,
                "stage_persistent": False,
                "effect_value": effect_value,
                "aura_range": "all_enemies"
            }
        )
        return f"{user.name} 展开了削弱光环！"

# 在回合结束时处理削弱光环效果
def process_weaken_aura_turn_end(character_id, effect, battle_context):
    """在状态效果系统的 process_turn_end_effects 中调用"""
    params = effect.custom_params
    effect_value = params.get("effect_value", 5)
    
    # 获取所有敌方角色
    if battle_context.char_manager.is_enemy(character_id):
        enemies = battle_context.char_manager.get_all_friends()
    else:
        enemies = battle_context.char_manager.get_all_enemies()
    
    # TURN_END 产生的通用减益排入下一回合开始队列
    for enemy in enemies:
        if enemy.current_hp > 0:  # 只对存活角色生效
            battle_context.effect_manager.queue_pending_effect(
                enemy.id, "WEAKNESS", "GENERIC", intensity=effect_value,
                activate_at="NEXT_TURN_START", source="WEAKEN_AURA"
            )
            battle_context.effect_manager.queue_pending_effect(
                enemy.id, "VULNERABLE", "GENERIC", intensity=effect_value,
                activate_at="NEXT_TURN_START", source="WEAKEN_AURA"
            )
    
    # 减少剩余回合数
    params["remaining_turns"] -= 1
    if params["remaining_turns"] <= 0:
        battle_context.effect_manager.remove_effect(character_id, "WEAKEN_AURA")
```

### 7.6 用户接口 (Telegram 命令)

此系统完全在后端运行，没有直接的用户接口。

### 7.7 管理人全局技能接口

管理人可以随剧情解锁队伍级全局技能，定位类似“光之树苗”式战场干预。它们不属于任何角色、人格、异想体书页或 EGO，不消耗角色行动次数，也不进入角色普通技能冷却表。

当前先预留统一接口，不提前规定具体技能内容：

```python
class ManagerGlobalSkillInterface(ABC):
    @abstractmethod
    def execute(self, manager_state, battle_context, params):
        pass
```

接口至少需要支持：

- 剧情解锁条件与可用性检查。
- 战斗级有限资源或使用次数，避免成为无限制兜底按钮。
- 明确的可用窗口，例如 `TURN_START` 或行动阶段中的管理人干预窗口。
- 通过 `BattleContext` 和统一事件/播报系统执行，不绕过状态、死亡、Stage/Battle End 清理规则。

系统边界固定为：角色本体是职业；人格是主手武器与普通技能组；异想体书页是本场战斗的饰品和被动构筑；EGO 是角色绑定的主动终极技能或强化形态；管理人技能是队伍级全局干预。

---

## 8. 实现指南 (Implementation Guide)

### 8.1 模块实现优先级

为了确保系统能够逐步构建并持续可测试，建议按以下顺序实现各模块：

#### 第一阶段：核心基础 (Core Foundation)

1. **数据库层 (Database Layer)**
   - 实现 `db_connection.py` - 数据库连接管理
   - 创建所有表结构（characters, skills, skill_behaviors, active_status_effects 等）
   - 实现基础的 CRUD 操作 (`queries.py`)
   - **验证方法**：能够创建、读取、更新和删除角色数据

2. **角色管理系统 (Character Management)**
   - 实现 `CharacterManager` 类的基础方法
   - 创建角色、查询角色、更新角色属性
   - 实现混乱值系统
   - 创建核心角色（珏、露、莹、笙、曦）的数据
   - **验证方法**：能够通过命令创建和查询角色

3. **骰子系统 (Dice System)**
   - 实现骰子公式解析器 (`parse_dice_formula`)
   - 实现骰子投掷函数 (`roll_dice`)
   - **验证方法**：能够正确解析和计算各种骰子公式

#### 第二阶段：战斗基础 (Combat Foundation)

4. **状态效果系统 (Status Effect System)**
   - 实现常规效果（烧伤、中毒、流血、破裂、呼吸法）
   - 实现通用效果（强壮、虚弱、守护、护盾、易伤、麻痹）
   - 实现效果叠加和衰减逻辑
   - **验证方法**：能够应用、查询和结算状态效果

5. **技能系统基础 (Basic Skill System)**
   - 实现 `SkillManager` 的基础框架
   - 实现目标解析 (`_resolve_targets`)
   - 实现简单的伤害/治疗行为
   - 创建几个测试技能
   - **验证方法**：能够执行简单的单体伤害技能

6. **回合管理系统 (Turn Management)**
   - 实现 `TurnManager` 类
   - 实现 `TURN_START -> FRIENDLY_ACTION -> ENEMY_ACTION -> TURN_END` 回合状态机
   - 实现回合结束逻辑 (`end_turn`) 与全场普通技能自然冷却推进
   - 实现场景结束和战斗结束逻辑
   - **验证方法**：能够正确处理回合流转和状态重置

#### 第三阶段：进阶功能 (Advanced Features)

7. **情感系统 (Emotion System)**
   - 实现硬币获取和管理
   - 实现等级提升逻辑
   - 实现冷却缩减
   - 实现等级4的额外行动次数
   - **验证方法**：能够通过战斗行为获得硬币并升级

8. **技能系统完整实现 (Complete Skill System)**
   - 实现行为驱动架构（TURN_START/PRE/ON/POST/TURN_END timing）
   - 实现命中、暴击、击杀、未击杀、目标身份和阵营等 `trigger_condition`
   - 实现统一结算快照与事件钩子
   - 实现所有目标类型（SELF, SELECT_*, ALL_*, RANDOM_*）
   - 实现复杂的效果组合
   - **验证方法**：能够执行复杂的多阶段技能

9. **特殊效果扩展系统 (Special Effect System)**
   - 实现 `SpecialEffectManager` 框架
   - 实现硬血效果
   - 实现黑夜领域效果（规范占位，v2 尚未落地）
   - 实现削弱光环效果（规范占位，v2 尚未落地）
   - 预留管理人全局技能接口
   - **验证方法**：特殊效果能够正确触发和生效

#### 第四阶段：用户交互 (User Interface)

10. **攻击逻辑系统 (Attack Logic System)**
    - 实现友方攻击流程 (`/attack`)
    - 实现敌方攻击流程 (`/enemy`)
    - 实现会话管理和错误处理
    - **验证方法**：用户能够通过命令完成完整的攻击流程

11. **人格系统 (Persona System)**
    - 实现人格切换逻辑
    - 为核心角色创建初始人格
    - **验证方法**：核心角色能够切换人格并改变属性

12. **用户命令集成 (Command Integration)**
    - 实现所有用户命令
    - 实现状态显示 (`/show`)
    - 实现角色管理命令
    - **验证方法**：所有命令能够正常工作

### 8.2 模块依赖关系图

```
数据库层 (Database)
    ↓
角色管理 (Character) ← 骰子系统 (Dice)
    ↓                      ↓
状态效果 (Status) ← 技能系统 (Skill)
    ↓                      ↓
情感系统 (Emotion) → 回合管理 (Turn)
    ↓                      ↓
特殊效果 (Special) ← 攻击逻辑 (Attack)
    ↓
人格系统 (Persona)
```

### 8.3 关键实现注意事项

#### 数据一致性
- 所有状态变更必须原子化，使用数据库事务
- 角色生命值、混乱值等关键属性变更需要立即同步到数据库
- 状态效果的添加和移除要确保数据库与内存状态一致

#### 性能优化
- 批量查询角色数据，减少数据库往返
- 缓存技能定义，避免重复查询
- 对频繁访问的角色状态使用内存缓存

#### 错误处理
- 所有数据库操作都要有异常捕获
- 用户输入验证要全面
- 战斗流程中的错误要能够优雅降级

#### 测试策略
- 单元测试：每个管理器类的独立方法
- 集成测试：模拟完整的战斗流程
- 边界测试：极端情况（如生命值为0、混乱值为负等）

### 8.4 配置管理

建议将以下内容作为配置文件管理：

**config/constants.py**:
```python
# 情感等级阈值
EMOTION_LEVEL_THRESHOLDS = {1: 3, 2: 3, 3: 5, 4: 7, 5: 9}

# 情感升级奖励
EMOTION_LEVEL_BONUSES = {
    4: {'bonus_actions': 1}
}

# 核心角色列表
CORE_CHARACTERS = ["珏", "露", "莹", "笙", "曦"]

# 特性标签
AVAILABLE_TAGS = ["人类", "机械", "异想体"]

# 状态效果图标映射
STATUS_ICONS = {
    "BURN": "🔥",
    "POISON": "☠️",
    "BLEEDING": "🩸",
    "RUPTURE": "💥",
    "BREATHING": "🫁",
    # ... 其他状态
}
```

### 8.5 文档维护

在实现过程中，请维护以下文档：

1. **API 文档**：每个公共方法的详细说明
2. **数据库Schema文档**：表结构和字段说明
3. **状态效果手册**：所有状态效果的详细机制
4. **技能配置指南**：如何创建和配置新技能
5. **测试用例文档**：记录所有测试场景

---

## 9. 结语

本重构指南为 Dewbot 系统提供了完整的技术规范和实现路径。通过遵循本指南，开发团队可以：

- 构建一个清晰、模块化的战斗系统
- 确保各模块之间的松耦合和高内聚
- 为未来的功能扩展提供坚实的基础
- 维护代码的可读性和可维护性

重构的核心原则是**简化、解耦和扩展性**。每个系统模块都应该专注于自己的职责，通过明确的接口与其他模块交互。特殊效果扩展系统确保了未来可以轻松添加新的游戏机制，而不会破坏现有的代码结构。

祝开发顺利！

---

## 10. v2 实现映射（2026-07-10）

本指南的规范实现位于 `src/dewbot/`。旧目录保留作历史参考，新入口 `src/main.py` 只调用 `dewbot.telegram_app.main()`。

| 规范职责 | v2 实现 |
| :--- | :--- |
| 数据库迁移与事务 | `schema.py`, `db.py` |
| 角色/人格/技能/效果/书页/管理能力定义 | `content.py`, `content/*.json` |
| 回合、阶段、冷却、情感、EGO | `engine.py` |
| 特殊机制注册与统一上下文 | `effects.py`, `BattleEngine._dispatch_hooks()` |
| 玩家可见战斗记录 | `narration.py` |
| Telegram 权限与交互 | `telegram_app.py` |
| 内容作者合同 | `CONTENT_PACK_GUIDE.md` |
| 回归验收 | `tests/` |

内容定义使用稳定 key 和显式包所有权。跨包内容通过 `pack.requires`、顶层 `personas[]` 与 `character_extensions[]` 组合；加载更新必须在无活动战斗时完成，checksum 完全相同的加载除外。特殊机制若不能由 `DAMAGE/HEAL/APPLY_EFFECT` 表达，使用注册 handler；handler 必须在内容提交前通过完整性检查。

### 设计命令 → v2 实际命令对照

前文各“x.5 用户接口”小节使用的是设计期命令名；v2 实际注册命令对照如下：

| 设计命令 | v2 实际命令 |
| :--- | :--- |
| `/switch`、`/persona` | `/identity`（战斗外） |
| `/create_character` | `/create` |
| `/start_battle` | `/team` + `/ready` |
| `/start_stage` | `/next` |
| `/end_friendly_phase` | `/pass` |
| `/end_turn` | `/settle`（保留 `/end_turn` 别名） |
| `/reset_battle` | `/stop` |
| `/equip_abnormality` | 关卡异想体池 + `/pages` |

`/attack`、`/enemy`、`/cancel` 保留原名。
