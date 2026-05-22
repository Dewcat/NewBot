# Dewbot 项目重新接手总览

本文档用于帮助你在很久没有碰这个仓库后，快速重新理解 Dewbot 当前开发到了哪里、每个模块现在如何设计、哪些内容已经实现、哪些内容只是最新设计草案，以及几次重要更改分别带来了什么想法。

结论先说清楚：

- 当前代码是一个基于 Telegram Bot 的跑团战斗辅助系统，已经能创建角色、加入战斗、选择攻击者/技能/目标、结算伤害/治疗/状态、处理行动次数、混乱值、技能冷却和情感等级。
- 当前代码仍然保留很多“旧设计”：攻击/防御、物理/魔法抗性、种族标签、加速、技能类别驱动、状态效果统一强度+持续时间。
- 最新设计想法主要写在 `todo.txt` 和 `REFACTOR_GUIDE.md` 中，核心方向是向《边狱公司》和《废墟图书馆》式的战斗结构靠拢：移除攻防抗性，把种族改成特性标签，技能改为“行为集合”，状态效果重新分类，引入异想体书页和 EGO 技能。
- 所以仓库目前是“旧系统可运行 + 新系统蓝图已写好但未完整落地”的状态。

---

## 1. 项目定位

Dewbot 是一个为跑团服务的 Telegram 战斗机器人。它的设计灵感明显来自《边狱公司》和《废墟图书馆》：

- 角色可以加入或离开战斗。
- 战斗以回合推进。
- 角色通过技能造成伤害、治疗、施加状态效果。
- 角色有行动次数，每次使用技能消耗行动。
- 角色有混乱值，混乱后受到更高伤害且失去行动。
- 角色有情感等级，通过战斗行为获得情感硬币并升级。
- 五名核心角色“珏、露、莹、笙、曦”拥有类似人格系统的设计。
- 最新蓝图计划加入异想体书页和 EGO 技能，使核心角色在一场战斗内有更强的成长和爆发机制。

当前入口是：

- `src/main.py`: Telegram Bot 启动和命令注册。
- `src/database/db_connection.py`: SQLite 数据库连接。
- `src/database/db_migration.py`: 启动时运行迁移。

数据库路径当前写在 `src/database/db_connection.py` 中：

```text
src/data/dewbot.db
```

仓库中还存在：

```text
src/data/simplebot.db
src/database/game.db
```

它们看起来像旧数据库或开发遗留文件，真正运行代码使用的是 `src/data/dewbot.db`。

---

## 2. 当前代码结构

当前源码主要分为六大块：

```text
src/main.py
src/database/
src/character/
src/skill/
src/game/
src/effects/
src/special_effect_integration.py
```

各目录职责如下。

### 2.1 `src/main.py`

这是 Bot 的启动入口，负责：

- 加载 `.env` 中的 `TELEGRAM_TOKEN`。
- 运行数据库迁移 `run_migrations()`。
- 创建 `python-telegram-bot` 的 `Application`。
- 注册命令处理器。
- 注册攻击流程、敌方攻击流程、角色管理、人格管理、技能管理、种族管理等模块。

目前注册的核心命令包括：

```text
/start
/help
/create_character, /cc
/create_enemy, /ce
/characters, /chars
/enemies
/show, /panel
/race
/health
/reset
/reset_all
/create_core
/persona, /switch
/personas
/attack
/enemy
/battle
/join
/leave
/end_battle
/end_turn
/set_actions
/sm
/skills
/cancel
```

注意：`/help` 中仍然保留旧概念，如“种族和抗性”“AOE技能分类”“统一百分比效果系统”等。最新设计要求移除抗性和种族战斗结算，但当前代码还没有完全移除。

---

## 3. 数据库系统

相关文件：

```text
src/database/db_connection.py
src/database/db_migration.py
src/database/queries.py
src/database/migrations/
```

### 3.1 当前数据库设计

当前基础表由 `init_db()` 创建，后续字段由 `db_migration.py` 添加。

主要表包括：

- `characters`: 角色表。
- `skills`: 技能表。
- `character_skills`: 角色和技能关联表。
- `battle_logs`: 战斗日志表。
- `character_status_effects`: 状态效果表。
- `character_emotion_effects`: 旧版情感升级效果表。
- `emotion_level_history`: 情感升级历史。
- `emotion_coin_log`: 情感硬币日志。
- `personas`: 人格表，实际由人格相关迁移或外部数据库已有结构支持。
- `migrations`: 已应用迁移记录。

### 3.2 当前 `characters` 表的核心字段

代码会使用这些字段：

```text
id
name
character_type          friendly/enemy
in_battle               是否在战斗中
health
max_health
attack
defense
status                  JSON，当前主要存技能冷却
physical_resistance
magic_resistance
race_tags               JSON
actions_per_turn
current_actions
stagger_value
max_stagger_value
stagger_status
stagger_turns_remaining
emotion_level
positive_emotion_coins
negative_emotion_coins
pending_emotion_upgrade
current_persona
```

### 3.3 当前 `skills` 表的核心字段

当前技能不是新蓝图中的“行为集合”，而是一个带 JSON 效果字段的旧式技能：

```text
id
name
description
cooldown
skill_category
damage_formula
damage_type
special_damage_tags
effects
required_emotion_level
```

其中：

- `skill_category` 决定技能的主要流程，如 `damage`、`healing`、`buff`、`debuff`、`self`、`aoe_damage`、`aoe_healing`、`aoe_buff`、`aoe_debuff`。
- `effects` 是 JSON，记录次要效果、状态效果、吸血、硬血等。
- `status` JSON 中的 `cooldowns` 记录角色当前技能冷却。

### 3.4 最新设计要求的数据库变化

`REFACTOR_GUIDE.md` 计划把数据库改成更清晰的结构：

- `characters` 去掉 `attack`、`defense`、抗性结算意义，保留 HP、行动、混乱、情感、特性标签。
- `race_tags` 改为 `tags`，只允许“人类、机械、异想体”等特性标签，暂时只存储，不参与结算。
- 新增 `skill_behaviors`，让每个技能由多条行为组成。
- 新增 `battle_skill_cooldowns`，不再把冷却塞进角色 `status` JSON。
- 新增 `battle_ego_usage`，记录每名角色本场是否已经使用过任意 EGO。
- 新增异想体相关表：`abnormalities`、`abnormality_pages`、`battle_page_pool`。

这些目前主要还是设计蓝图，当前代码尚未完整实现。

---

## 4. 角色管理系统

相关文件：

```text
src/character/character_management.py
src/character/status_formatter.py
src/database/queries.py
```

### 4.1 当前职责

角色管理负责：

- 创建友方角色。
- 创建敌方角色。
- 查看友方/敌方列表。
- 查看角色详情。
- 修改生命值。
- 重置单个角色或全部角色。
- 加入战斗、离开战斗、全部加入、全部离开。
- 展示战斗参与者。

当前有两种角色阵营：

```text
friendly
enemy
```

友方通过 `/attack` 发起行动，敌方通过 `/enemy` 发起行动。

### 4.2 当前角色创建逻辑

友方角色创建较简单：

- `/create_character` 或 `/cc`
- 只要求输入名称。
- 默认生命值 100、攻击 10、防御 5、行动次数 1。
- 创建后不会自动分配默认技能，需要手动通过 `/sm <角色名>` 管理技能。

敌方角色创建更完整：

- `/create_enemy` 或 `/ce`
- 输入名称、生命值、攻击力、防御力。

### 4.3 当前战斗加入逻辑

角色不会自动参与战斗，必须设置 `in_battle = 1`。

相关命令：

```text
/join <角色名>
/join <角色1> <角色2> ...
/join all
/join all friendly
/join all enemy
/leave <角色名>
/end_battle
```

这与最新设计里的 Stage Start 思路是接近的：每个阶段开始时，需要选择哪些角色加入战斗。但当前实现只是简单地用 `in_battle` 标记，不存在完整的 `battle_state` 或阶段状态机。

### 4.4 最新设计中的角色系统

最新设计希望角色系统变得更纯粹：

- 五名核心角色固定为“珏、露、莹、笙、曦”。
- 核心角色可切换人格。
- 人格改变普通技能和部分属性。
- EGO 技能与角色绑定，不随人格切换。
- 移除攻防等级和抗性。
- 种族改为特性标签，暂时不参与战斗结算。
- 混乱值、行动次数、情感等级仍然保留。

---

## 5. 人格系统

相关文件：

```text
src/character/persona.py
src/character/persona_management.py
```

### 5.1 当前职责

人格系统服务于五名核心角色：

```text
珏、露、莹、笙、曦
```

它让角色可以通过 `/persona` 或 `/switch` 切换人格。

人格记录在 `personas` 表中，当前包含：

```text
character_name
name
description
health
max_health
attack
defense
physical_resistance
magic_resistance
race_tags
skills
stagger_value
max_stagger_value
```

切换人格时会：

- 更新角色 HP、最大 HP、攻击、防御。
- 更新物理/魔法抗性。
- 更新种族标签。
- 更新当前人格名 `current_persona`。
- 更新混乱值。
- 清空原有技能并写入人格技能列表。

### 5.2 当前实现与最新设计的差异

当前人格仍然绑定旧属性：

- `attack`
- `defense`
- `physical_resistance`
- `magic_resistance`
- `race_tags`

最新设计要求这些战斗结算意义被移除。人格应主要决定：

- HP。
- 行动次数修正。
- 混乱值。
- 普通技能池。
- 可能的标签或特殊机制。

同时，最新设计加入 EGO：

- 每名核心角色有独立 EGO 技能。
- EGO 不会因为人格切换而增加或移除。
- EGO 需要高情感等级。
- 每名角色每场战斗只能使用一次任意 EGO。

这部分在当前代码中尚未真正落地。

---

## 6. 种族、抗性与特性标签

相关文件：

```text
src/character/race_management.py
src/game/damage_calculator.py
```

### 6.1 当前代码状态

当前系统仍然有完整的旧式种族和抗性系统：

- `/race <角色名>` 可以管理种族标签和抗性。
- 角色可拥有多个种族标签。
- 技能可通过 `special_damage_tags` 对某些种族造成特攻。
- 伤害计算会使用物理/魔法抗性减伤。

当前可选种族包括：

```text
human, elf, dwarf, orc, dragon, machine, beast, undead, demon,
angel, elemental, construct, fey, giant, goblinoid
```

### 6.2 最新设计要求

`todo.txt` 规则 A 明确要求：

- 移除攻防等级和抗性相关逻辑。
- 移除种族相关逻辑。
- 种族改为特性标签。
- 现有特性标签先只保留：

```text
人类
机械
异想体
```

- 特性标签暂时只写入数据库，不参与结算，未来供技能调用。

也就是说，`race_management.py` 和 `damage_calculator.py` 的这部分是旧设计，应在重构时废弃或替换。

---

## 7. 行动次数系统

相关文件：

```text
src/database/queries.py
src/game/attack.py
src/game/turn_manager.py
src/main.py
```

### 7.1 当前职责

行动次数系统让角色每回合可以行动多次。

核心字段：

```text
actions_per_turn
current_actions
```

流程如下：

1. `/attack` 或 `/enemy` 只列出 `current_actions > 0` 且 `in_battle = 1` 的角色。
2. 成功使用技能后，调用 `use_character_action()`。
3. `current_actions -= 1`。
4. `/end_turn` 后恢复行动次数。

管理员可以通过：

```text
/set_actions <角色名> <次数>
```

设置角色每回合行动次数。

### 7.2 与最新设计的关系

最新设计决定移除“加速”机制，统一改为“额外行动点”表达。

当前代码仍然有 `haste` 状态，它会直接增加当前行动次数和行动上限。这属于旧设计，应在重构时改为更清楚的行动点修改，不再保留加速这个特殊状态。

---

## 8. 攻击逻辑系统

相关文件：

```text
src/game/attack.py
```

### 8.1 当前职责

攻击逻辑是 Telegram 交互层，负责用户点按钮完成战斗动作。

友方流程 `/attack`：

1. 选择有行动次数的友方角色。
2. 显示该角色可用技能。
3. 检查技能冷却和情感等级要求。
4. 根据 `skill_category` 判断是否需要选目标。
5. 执行技能。
6. 消耗行动次数。
7. 编辑消息显示结果。

敌方流程 `/enemy`：

1. 记录发起者 ID，只有发起者能继续操作。
2. 选择有行动次数的敌方角色。
3. 敌方技能按钮只显示编号。
4. 技能详情通过 Telegram 弹窗只显示给操作者。
5. 选择目标或直接执行 AOE/self。
6. 执行技能并消耗行动次数。

### 8.2 当前目标选择方式

当前代码主要靠 `skill_category` 判断目标：

- `damage`: 选择敌方。
- `healing`: 选择友方。
- `buff`: 选择友方。
- `debuff`: 选择敌方。
- `self`: 自动选择自己。
- `aoe_damage`: 全体敌方。
- `aoe_healing`: 全体友方。
- `aoe_buff`: 全体友方。
- `aoe_debuff`: 全体敌方。

敌方攻击时，友敌关系会反转。

### 8.3 最新设计要求

最新设计认为“靠技能类型决定目标和播报”不够灵活，要求改为：

- 技能层只指定一次目标。
- 技能目标由“范围 + 方式”组成。
- 范围：

```text
自身
友方
敌方
不限
```

- 方式：

```text
自身
选择目标
全体目标
广域乱射:X
```

- 如果需要选择目标，交互界面只选择一次。
- 行为层要么继承技能目标，要么使用自己的自动目标逻辑。
- 行为层不允许再次要求交互选择目标。
- 广域乱射 `RANDOM:X` 使用放回抽样，也就是可以重复命中同一个目标。

这个目标系统目前主要写在 `REFACTOR_GUIDE.md`，当前攻击逻辑还没有重构到这个模型。

---

## 9. 技能系统

相关文件：

```text
src/skill/skill_management.py
src/skill/skill_effects.py
src/skill/effect_target_resolver.py
src/game/damage_calculator.py
```

### 9.1 当前技能管理

`skill_management.py` 负责通过 `/sm <角色名>` 管理角色技能。

支持：

- 查看角色当前技能。
- 添加单个技能。
- 移除单个技能。
- 批量添加技能。
- 批量移除技能。
- 查看所有技能。

技能和角色的关系存在 `character_skills` 表里。

### 9.2 当前技能执行模型

当前技能执行由 `skill_registry.execute_skill(attacker, target, skill_info)` 进入。

核心类在 `skill_effects.py`：

```text
SkillEffect
```

它根据 `skill_category` 分发到：

```text
execute_damage
execute_healing
execute_buff
execute_debuff
execute_self
execute_aoe_damage
execute_aoe_healing
execute_aoe_buff
execute_aoe_debuff
```

伤害技能流程大致是：

1. 解析骰子公式。
2. 计算基础伤害。
3. 计算特殊附加伤害。
4. 应用攻防修正。
5. 应用种族特攻。
6. 应用抗性减伤。
7. 应用混乱伤害倍率。
8. 应用攻击者状态修正，如强壮、虚弱、呼吸法暴击。
9. 应用目标受击修正，如守护、易伤、护盾、破裂、黑夜领域死亡免疫。
10. 扣除 HP。
11. 扣除混乱值。
12. 应用技能附带状态效果。
13. 处理行动后效果，如流血。
14. 设置技能冷却。
15. 处理情感硬币。
16. 生成播报。

### 9.3 当前技能 JSON 效果

当前 `effects` 字段支持多种格式，历史兼容痕迹较多。

常见键包括：

```text
status
buff
debuff
damage
heal
vampiric
hardblood_shield
aoe_apply_status
apply_status
```

也支持一些新格式：

```text
[
  {"type": "aoe_apply_status", ...},
  {"type": "apply_status", ...}
]
```

`effect_target_resolver.py` 支持目标：

```text
self
skill_target
all_allies
all_enemies
all_characters
```

这已经是向“行为目标解析”靠近的一步，但还不是最新设计里的完整行为系统。

### 9.4 当前骰子系统

`game/damage_calculator.py` 支持：

```text
1d6
2d8
10
5+2d3
3d4+2
```

骰子公式解析规则：

- 用 `+` 分隔多个部分。
- `XdY` 表示 X 个 Y 面骰。
- 纯数字表示固定值。

麻痹会把部分骰子结果归零，并消耗麻痹强度。

骰子结果还会影响情感硬币：

- 投出最大值：正面情感硬币。
- 投出 1：负面情感硬币。

### 9.5 最新技能设计

最新设计的核心是：

> 一个技能不是一个类别，而是数条行为的集合。

每条行为包含：

- 作用时机。
- 作用目标。
- 效果种类。
- 效果数值。
- 执行顺序。

作用时机为：

```text
PRE   使用前
ON    使用时，必须存在
POST  使用后
```

效果类型为：

```text
DAMAGE
HEAL
APPLY_EFFECT
SPECIAL
```

一个技能可以像这样被拆开：

```text
使用前：自身获得 2 强壮
使用时：全体敌人受到 3d5 伤害
使用后：全体敌人获得 3 破裂强度
```

播报应在一个消息中按行为顺序列出：

```text
A 使用了 B：
A 获得 2 强壮
敌人1 受到 3d5=2+3+1=6 点伤害
敌人2 受到 3d5=1+4+2=7 点伤害
敌人1 增加 3 破裂强度
敌人2 增加 3 破裂强度
```

这个新系统尚未在代码中完整实现。

---

## 10. 伤害计算系统

相关文件：

```text
src/game/damage_calculator.py
src/game/damage_enhancers/damage_manager.py
src/special_effect_integration.py
```

### 10.1 当前伤害公式

当前伤害计算仍是旧系统：

```text
最终伤害 = 基础骰子伤害
        + 特殊附加伤害
        × 攻防倍率
        × 种族特攻倍率
        × 抗性倍率
        × 混乱倍率
        再经过强壮/虚弱/守护/易伤/护盾等状态修正
```

攻防倍率：

```text
攻击 - 防御 每差 1 点，伤害变化 2%
最低倍率 0.1
```

抗性：

```text
1.0 - min(resistance, 0.9)
至少造成 10% 伤害
```

混乱：

```text
处于混乱状态时受到 200% 伤害
```

### 10.2 最新设计要求

最新设计要求移除：

- 攻防等级。
- 抗性。
- 种族特攻。

保留或重做：

- 骰子公式。
- 状态修正。
- 混乱 200% 受伤。
- 常规效果的固定伤害独立结算。
- 特殊效果通过扩展系统接入。

这意味着 `damage_calculator.py` 将来要大幅简化。

---

## 11. 状态效果系统

相关文件：

```text
src/character/status_effects.py
src/character/status_formatter.py
```

### 11.1 当前状态表结构

当前状态存在 `character_status_effects` 表中：

```text
character_id
effect_type
effect_name
intensity
duration
```

当前实现把 `duration` 同时当作持续回合或层数使用。

### 11.2 当前叠加规则

当前 `add_status_effect()` 的规则是：

- 同名效果已存在时：
  - 强度取新旧最大值。
  - 如果新增 `duration = 0`，只更新强度。
  - 否则持续时间/层数相加。
- 同名效果不存在时：
  - 如果新增 `duration = 0`，设为 1。

### 11.3 当前已支持状态

常见增益：

```text
strong        强壮
breathing     呼吸法
guard         守护
shield        护盾
haste         加速
hardblood     硬血
dark_domain   黑夜领域
weaken_aura   削弱光环
```

常见减益：

```text
burn          烧伤
poison        中毒
rupture       破裂
bleeding      流血
weak          虚弱
vulnerable    易伤
paralysis     麻痹
```

### 11.4 当前效果机制

当前主要机制：

- 烧伤：回合结束造成 `强度 × 1` 固定伤害。
- 中毒：回合结束造成当前生命值 `强度%` 的伤害，至少 1。
- 流血：行动后造成 `强度 × 1` 伤害，并减少层数。
- 破裂：受击时造成 `强度 × 1` 额外伤害，并减少层数。
- 呼吸法：提供暴击率，触发时伤害变为 120%。
- 强壮：攻击最终伤害增加 `强度 × 10%`。
- 虚弱：攻击最终伤害减少 `强度 × 10%`。
- 守护：受到最终伤害减少 `强度 × 10%`。
- 易伤：受到最终伤害增加 `强度 × 10%`。
- 护盾：抵消伤害，护盾强度随抵消量减少。
- 麻痹：让若干伤害骰归零，并消耗强度。
- 加速：当前旧实现会增加当前行动次数和每回合行动上限。
- 硬血：作为资源池，可被技能消耗。
- 黑夜领域：回合结束获得强壮、易伤、加速和大量负面情感硬币；可免疫一次致死伤害。
- 削弱光环：回合结束给敌方全体施加虚弱和易伤。

### 11.5 最新状态设计

`todo.txt` 规则 B 对状态系统做了重新分类。

#### 常规效果

常规效果有强度和层数：

```text
烧伤
中毒
流血
破裂
呼吸法
```

新叠加规则：

- 强度相加。
- 层数相加。
- 新增层数为 0 且目标没有该效果时，层数设为 1。
- 伤害如果存在，是固定伤害，独立于伤害公式结算。
- 不受易伤、混乱等伤害修正影响。

#### 通用效果

通用效果只保留强度：

```text
强壮
虚弱
守护
护盾
易伤
麻痹
```

最新蓝图里写的是“回合内有效，回合结束清空”，但 `REFACTOR_GUIDE.md` 又对护盾和麻痹做了例外说明：

- 强壮、虚弱、守护、易伤：回合结束清空。
- 护盾：直到强度耗尽，或 Stage/Battle End 清理。
- 麻痹：直到强度归零，或 Stage/Battle End 清理。

#### 特殊效果

特殊效果不再硬塞进强度/层数体系：

```text
硬血
黑夜领域
削弱光环
```

它们用自己的参数描述：

- 硬血：只有 `amount`，是资源池。
- 黑夜领域：持续时间、死亡免疫是否使用、回合结束子效果。
- 削弱光环：持续时间、影响范围、施加效果值。

#### 即时效果

即时效果没有强度/层数，只立即生效。

例子：

- 吸血：当前最新设计更准确地说是把伤害转化为硬血，而不是直接回血。

冷却缩减被明确移出即时效果，不再作为普通技能特效，只允许情感升级触发。

---

## 12. 混乱系统

相关文件：

```text
src/character/stagger_manager.py
src/game/damage_calculator.py
```

### 12.1 当前职责

混乱值类似《边狱公司》的 Stagger。

字段：

```text
stagger_value
max_stagger_value
stagger_status
stagger_turns_remaining
```

当前流程：

1. 受到伤害时，混乱值按伤害量减少。
2. 混乱值降为 0 时进入 `staggered`。
3. 进入混乱时 `stagger_turns_remaining = 2`。
4. 当前行动次数清零。
5. 混乱期间受到伤害为 200%。
6. 每次回合处理减少剩余回合。
7. 归零后恢复正常，混乱值回满。

### 12.2 最新设计说明

`todo.txt` 规则 E 解释了为什么“持续 2 回合”：

真正想表达的是：

> 混乱条清零的当回合进入混乱，并在下一回合结束时解除混乱。

实现上设置为 2，是因为从“当回合进入混乱”到“下一回合结束”正好经历两次回合结束处理。

这个说明已经写进 `REFACTOR_GUIDE.md`，当前代码机制也基本符合。

---

## 13. 情感系统

相关文件：

```text
src/character/emotion_system.py
src/game/turn_manager.py
src/skill/skill_effects.py
```

### 13.1 当前职责

情感系统是战斗内短期成长机制。

角色字段：

```text
emotion_level
positive_emotion_coins
negative_emotion_coins
pending_emotion_upgrade
```

升级需求：

```text
0 -> 1: 3
1 -> 2: 3
2 -> 3: 5
3 -> 4: 7
4 -> 5: 9
```

当前获取硬币来源包括：

- 骰子投出最大值：正面硬币。
- 骰子投出 1：负面硬币。
- 造成伤害。
- 治疗。
- 击杀。
- 某些特殊效果，如黑夜领域。

当硬币总数达到要求：

- 设置 `pending_emotion_upgrade = 1`。
- 本回合不再继续获得硬币。
- 在回合开始/结束流程中统一处理升级。
- 升级后清空正负硬币。
- 所有技能冷却 -1。

当前旧版“升级获得被动情感效果”被代码注释禁用了：

```text
POSITIVE_EMOTION_EFFECTS = []
NEGATIVE_EMOTION_EFFECTS = []
```

所以当前情感升级主要效果是：

- 情感等级提升。
- 技能冷却减少。
- 解锁需要情感等级的技能。

### 13.2 最新设计：异想体书页

`todo.txt` 规则 F 引入异想体书页系统。

核心想法：

- 玩家战前选择装备哪些异想体。
- 每个异想体通常提供 3 张书页。
- 被装备异想体的书页进入本场战斗书页池。
- 五名核心角色“珏、露、莹、笙、曦”情感等级提升时，可以从至多 3 张书页里选 1 张。
- 书页分为：

```text
觉醒型
崩溃型
```

- 正面硬币较多时偏向觉醒型。
- 负面硬币较多时偏向崩溃型。
- 觉醒型提供强力正面效果。
- 崩溃型提供更强正面效果，但可能伴随负面代价。
- 一张书页被选择后，从本场卡池移除。
- 如果升级时没有书页，则跳过选择。
- Stage End 保留已选书页。
- Battle End 清空角色书页并重置书页池。

这部分目前还未实现，属于最新设计蓝图。

---

## 14. 回合管理系统

相关文件：

```text
src/game/turn_manager.py
```

### 14.1 当前职责

当前回合管理比较轻量，没有完整 Battle/Stage/Turn 状态机。

`/end_turn` 会：

1. 调用 `turn_manager.process_all_emotion_upgrades()` 处理情感升级。
2. 调用 `turn_manager.end_battle_turn()` 处理所有在战斗中的角色。
3. 对每个角色结算回合结束状态效果。
4. 处理混乱回合。
5. 恢复行动次数。
6. 处理回合开始状态效果。
7. 返回文本播报。

当前 `TurnManager` 有内存中的：

```text
current_turn
```

但没有持久化的 `battle_state`。

### 14.2 当前 Stage/Battle 差异

当前代码没有真正区分：

- Turn End
- Stage End
- Battle End

`/end_battle` 只是把所有角色移出战斗。

`reset_all` 则会恢复满血、重置行动、混乱、情感、状态等。

### 14.3 最新设计：三层战斗流程

`REFACTOR_GUIDE.md` 计划建立明确的三层流程：

#### Turn End

- 结算状态效果。
- 处理混乱倒计时。
- 恢复行动力。
- 推进冷却。
- 保留战斗状态、混乱值、情感等级。

#### Stage End

用于连续战斗中的波次过渡：

- 清除所有临时效果，包括临时特殊效果。
- 重置混乱值。
- 保留 HP、情感等级、情感硬币、已选书页。
- 将所有角色设为 `in_battle = False`。
- 下一阶段必须重新选择角色加入战斗。

#### Battle End

整场战斗结束：

- 清除所有状态效果。
- 重置混乱。
- 重置情感等级和硬币。
- 清空异想体书页。
- 清空技能冷却和 EGO 使用记录。
- 所有角色离开战斗。

---

## 15. 特殊效果扩展系统

相关文件：

```text
src/effects/__init__.py
src/special_effect_integration.py
src/skill/special_effects/hardblood_effects.py
src/skill/special_effects/dark_domain_effects.py
src/skill/special_effects/aura_effects.py
src/game/damage_enhancers/damage_manager.py
```

### 15.1 当前职责

当前代码已经有一套初步的扩展框架：

- `EffectRegistry`: 注册状态效果、伤害增强器、特殊效果。
- `DamageEnhancerManager`: 统一计算附加伤害。
- `EffectIntegrationManager`: 把特殊效果整合进技能计算。

当前已接入的特殊方向：

- 硬血。
- 黑夜领域。
- 削弱光环。
- 兽数/666 相关特殊技能。
- AOE 状态施加。

### 15.2 当前实现状态

这套系统是介于旧技能 JSON 和新特殊效果设计之间的过渡实现。

它已经做到：

- 特殊伤害可以从主伤害计算中统一加入。
- 硬血等复杂机制可以独立写在 `skill/special_effects/`。
- `special_effect_integration.py` 统一注册它们。

但它还没有完全变成 `REFACTOR_GUIDE.md` 里的策略模式接口：

```text
SpecialEffectInterface.execute(user, targets, params, battle_context)
SpecialEffectManager.register_effect(...)
SpecialEffectManager.execute(...)
```

### 15.3 最新设计方向

最新设计希望特殊效果成为所有非标准技能机制的统一入口。

未来特殊效果可以包括：

- 召唤单位。
- 调用其他技能。
- 创建场地效果。
- 复杂被动。
- 异想体书页效果。
- EGO 特殊机制。

技能系统不需要知道特殊效果内部逻辑，只要调用：

```text
SPECIAL + effect_value + effect_params
```

由特殊效果管理器负责执行。

---

## 16. EGO 技能系统

相关来源：

```text
todo.txt
REFACTOR_GUIDE.md
git commit 12cdb88
```

### 16.1 最新设计

EGO 是为五名核心角色准备的独立技能系统。

核心规则：

- 每名核心角色都有自己的 EGO 技能。
- EGO 与角色绑定。
- EGO 不随人格变化而增加或移除。
- EGO 比普通技能强大得多。
- EGO 需要很高情感等级。
- 每名角色每场战斗只能施放一次任意 EGO。

注意最后一条不是“每个 EGO 各一次”，而是：

> 每角色每战任意 EGO 仅可施放一次。

### 16.2 当前实现状态

当前代码还没有真正实现：

- `skill_type = EGO`
- `battle_ego_usage`
- EGO 使用检查
- EGO 不随人格切换保留
- EGO 在技能选择界面中特殊显示

这部分是明确的待实现接口。

---

## 17. 模块依赖关系

当前系统大致依赖如下：

```text
main.py
  -> database/db_migration.py
  -> character/character_management.py
  -> character/race_management.py
  -> character/persona_management.py
  -> skill/skill_management.py
  -> game/attack.py
  -> game/turn_manager.py

game/attack.py
  -> database/queries.py
  -> skill/skill_effects.py
  -> game/damage_calculator.py
  -> character/emotion_system.py

skill/skill_effects.py
  -> game/damage_calculator.py
  -> character/status_effects.py
  -> character/emotion_system.py
  -> skill/effect_target_resolver.py

game/damage_calculator.py
  -> character/stagger_manager.py
  -> character/status_effects.py
  -> special_effect_integration.py

special_effect_integration.py
  -> effects/EffectRegistry
  -> skill/special_effects/*
  -> game/damage_enhancers/damage_manager.py
```

最新重构后理想依赖应更像：

```text
Database
  -> CharacterManager
  -> StatusEffectManager
  -> SkillManager
  -> EmotionManager
  -> TurnManager
  -> SpecialEffectManager
  -> Telegram Interaction Layer
```

攻击逻辑应该只负责交互，不再自己理解技能类型细节。

---

## 18. 几次重要更改分别贡献了什么 idea

下面根据 git 历史和当前文档还原项目演化。

### 18.1 初始提交：基础 Bot 与战斗雏形

提交：

```text
fd2ba69 2025-07-26 first commit
```

主要 idea：

- 建立 Telegram Bot 项目。
- 引入角色、技能、战斗日志、SQLite 数据库。
- 形成最基本的“角色使用技能攻击目标”的结构。

这是系统骨架。

### 18.2 状态效果、角色属性与高级伤害

提交：

```text
d7c495b 2025-07-27 增益减益，角色属性功能撰写完毕
```

主要 idea：

- 引入 buff/debuff 状态效果。
- 引入角色属性管理。
- 引入高级伤害系统。
- 加入种族标签、物理/魔法抗性、特攻等旧式 RPG 机制。
- 加入状态格式化和测试文档。

这是系统从“简单攻击”变成“有战斗变量”的关键阶段。

### 18.3 行动次数系统与自我技能

提交：

```text
9a9d643 2025-07-27 行动次数系统
```

主要 idea：

- 在 `characters` 表新增 `actions_per_turn` 和 `current_actions`。
- 技能使用后消耗行动次数。
- `/end_turn` 恢复行动次数。
- 增加 `/set_actions`。
- 引入 self 技能，不需要选择目标，直接影响施法者。

这是系统接近回合制跑团工具的关键一步。

### 18.4 AOE 技能

提交：

```text
58c9aee 2025-07-29 增加AOE技能
```

主要 idea：

- 技能不再只有单体。
- 引入群体伤害、群体治疗、群体增益、群体减益。
- 攻击流程可跳过目标选择直接执行 AOE。

这让技能表达能力变强，但也加重了 `skill_category` 分支逻辑。

### 18.5 统一百分比效果、人格、混乱、敌方隐私

提交：

```text
e23291c 2025-09-02 feat: 完成统一百分比效果系统的实现
```

主要 idea：

- 引入统一百分比次要效果。
- 技能次要效果可基于主效果数值计算，例如造成 100 伤害后治疗 20。
- 引入人格系统文档和实现。
- 引入混乱值管理器。
- 引入目标解析器。
- 改进敌方攻击隐私：敌方技能对玩家只显示编号，详情只给操作者。
- 完善 API/手册/系统文档。

这是系统复杂度快速上升的一次改动，开始接近“可配置战斗引擎”。

### 18.6 米拉库尔与具体内容扩展

提交：

```text
6e6ffa8 2025-09-10 introduce 米拉库尔
```

主要 idea：

- 看起来是一次内容侧扩展，为系统加入具体角色/技能/机制数据。
- 这类提交说明系统已经开始被用来承载具体跑团内容，而不仅是框架。

当前仓库中相关临时脚本后来被删除，具体内容需要从数据库或历史提交恢复。

### 18.7 效果管理系统与特殊效果扩展

提交：

```text
a896a43 2025-09-12 feat: Implement effect management system with status effects and damage enhancers
```

主要 idea：

- 引入 `effects` 注册框架。
- 引入 `DamageEnhancerManager`。
- 引入 `special_effect_integration.py`。
- 把硬血、黑夜领域、削弱光环拆到 `skill/special_effects/`。
- 让特殊追加伤害和复杂状态从主流程中分离出来。
- 修复情感升级待处理字段。
- 移除一些测试/清库脚本。

这是后来“特殊效果扩展系统”设计的代码基础。

### 18.8 状态叠加规则优化

提交：

```text
f701c17 2025-09-12 feat: 更新状态效果管理和技能创建规范，优化叠加规则
```

主要 idea：

- 强化状态效果叠加规范。
- 更新技能创建规范。
- 调整硬血、黑夜领域等特殊效果兼容性。

这是状态系统从临时实现向规则化过渡的一步。

### 18.9 文档整理：攻击、技能、情感、回合

提交：

```text
940b52d 2025-11-12 文本
834016b 2025-12-23 文本
```

主要 idea：

- 大量系统文档被整理或补充。
- 包括 `ATTACK_LOGIC_DOCUMENTATION.md`、`SKILL_SYSTEM_DOCUMENTATION.md`、`EMOTION_SYSTEM_DOCUMENTATION.md`、`TURN_SYSTEM_DOCUMENTATION.md` 等。
- 这些文档多数描述的是当时的旧系统或过渡系统。

它们适合了解历史，但不能当作最新目标。

### 18.10 EGO 技能架构

提交：

```text
12cdb88 2026-03-19 docs: add EGO skills architecture based on Rule G
```

主要 idea：

- 在 `REFACTOR_GUIDE.md` 中加入 EGO 技能架构。
- 明确 EGO 与核心角色绑定，不随人格变化。
- 明确 EGO 高情感等级要求。
- 明确每角色每场战斗只能使用一次任意 EGO。

这是最新大方向的一部分，但还只是文档设计。

### 18.11 `todo.txt` A-G 规则定稿

提交：

```text
ffe364f 2026-03-19 docs: finalize todo rules A-G
```

主要 idea：

把最新重构方向定成七条规则：

- A：移除攻防、抗性、种族、加速、技能冷却缩减特效；种族改特性标签。
- B：重做状态效果分类和叠加规则。
- C：技能改为多行为集合，引入 PRE/ON/POST。
- D：完善特殊效果扩展系统。
- E：明确混乱持续 2 回合的真实语义。
- F：引入异想体书页系统。
- G：为五名核心角色添加 EGO 技能接口。

这是目前最重要的设计来源。

### 18.12 2026-04-01 临时补充

提交：

```text
112456d 2026-04-01 temp
```

主要 idea：

在 `todo.txt` 和 `REFACTOR_GUIDE.md` 中补充决策：

- 抗性彻底不参与伤害计算。
- 加速统一改为额外行动点。
- 冷却缩减只允许情感升级触发。
- 特性标签只存库，不参与结算。
- Stage End 清理所有临时效果。
- Stage End 把所有角色设为不在战斗中。
- Stage Start 必须重新选择角色加入战斗。
- 无可用技能时攻击流程直接结束。
- 技能目标选择只在技能层做一次。
- 行为层自动目标不允许再次交互选择。
- 广域乱射可重复命中。
- 旧版情感被动移除，改由异想体书页回合开始被动触发。
- 硬血与强度/层数体系解耦。
- EGO 限制为“每角色每战任意 EGO 仅一次”。

这是当前最新的设计决策。

---

## 19. 当前已实现与待实现对照

### 已实现或基本可用

- Telegram Bot 命令注册。
- SQLite 数据持久化。
- 角色创建、查看、重置。
- 友方/敌方阵营。
- 加入/离开战斗。
- 技能管理。
- 单体攻击、治疗、增益、减益。
- self 技能。
- AOE 技能。
- 行动次数。
- 技能冷却。
- 骰子公式。
- 攻防、抗性、种族特攻。
- 状态效果。
- 混乱值。
- 情感硬币、情感等级、情感等级要求。
- 敌方攻击权限控制和技能编号隐藏。
- 初步特殊效果扩展框架。
- 人格切换。

### 部分实现但需要重构

- 状态效果：已有实现，但不符合最新四分类规则。
- 特殊效果：已有框架，但还不是统一 `SPECIAL` 行为接口。
- 技能目标解析：已有 `EffectTargetResolver`，但还不是“技能层目标合同 + 行为层继承/自动”。
- 情感系统：已有升级和冷却缩减，但异想体书页未实现。
- 回合系统：已有 `/end_turn`，但没有完整 Stage/Battle 状态机。
- 混乱系统：机制接近最新设计，但需要和新回合系统整合。

### 最新设计中尚未落地

- 移除攻防、防御、抗性、种族结算。
- 特性标签替代种族标签。
- 移除加速机制，改为额外行动点。
- 冷却缩减从技能特效中移除，只保留情感升级触发。
- `skills + skill_behaviors` 行为驱动技能系统。
- PRE/ON/POST 技能执行顺序。
- 技能层目标只选择一次。
- 广域乱射 `RANDOM:X` 放回抽样。
- 新版状态分类：常规/通用/特殊/即时。
- 常规效果强度和层数相加。
- 通用效果只保留强度。
- 硬血改为独立 `amount` 参数。
- 异想体、书页池、觉醒/崩溃书页选择。
- 回合开始触发异想体书页被动。
- EGO 技能。
- Battle/Stage/Turn 三层状态机。
- Stage End 和 Battle End 的不同清理规则。

---

## 20. 接下来如果要继续开发，建议顺序

如果要把项目推进到最新设计，建议按这个顺序：

### 第一步：冻结旧系统边界

先决定哪些旧机制彻底废弃：

- `attack/defense`
- `physical_resistance/magic_resistance`
- `race_tags`
- `special_damage_tags`
- `haste`
- 技能里的 `cooldown_reduction`

不要立刻删字段，可以先停止在计算中使用，避免数据库迁移风险。

### 第二步：重做状态效果数据模型

先实现新版状态分类：

- REGULAR。
- GENERIC。
- SPECIAL。
- INSTANT。

这是后续技能行为和特殊效果的基础。

### 第三步：实现行为驱动技能系统

新增：

```text
skill_behaviors
SkillManager.execute_skill()
ReportBuilder
BattleContext
```

先支持最小集合：

- DAMAGE。
- HEAL。
- APPLY_EFFECT。
- SELF/SELECT_TARGET/ALL_TARGETS/RANDOM。

### 第四步：把攻击交互改成技能目标合同

`attack.py` 不再根据 `skill_category` 判断技能逻辑，而是：

1. 读取技能的目标范围和目标方式。
2. 如果需要选择目标，只选择一次。
3. 把目标 ID 列表交给 `SkillManager`。
4. 接收统一播报文本。

### 第五步：整合特殊效果系统

把当前的 `special_effect_integration.py` 收敛成更明确的：

```text
SpecialEffectManager
SpecialEffectInterface
BattleContext
```

硬血、黑夜领域、削弱光环迁移为正式特殊效果。

### 第六步：重构回合系统

实现：

- `start_battle`
- `start_stage`
- `start_turn`
- `end_turn`
- `end_stage`
- `end_battle`

明确 Stage End 和 Battle End 的清理差异。

### 第七步：实现异想体书页

在情感升级后触发核心角色书页选择：

- 战前装备异想体。
- 生成书页池。
- 情感升级 3 选 1。
- 已选书页从池中移除。
- 书页效果通过特殊效果系统触发。

### 第八步：实现 EGO

最后加入 EGO：

- `skill_type = EGO`
- `battle_ego_usage`
- 每角色每场一次。
- 高情感等级要求。
- 与人格技能池分离。

---

## 21. 一句话总结

这个仓库当前不是“坏掉的旧项目”，而是一个已经有大量功能的旧版战斗 Bot，后来你又为它设计了一套更接近《边狱公司》《废墟图书馆》的新版架构。真正的下一步不是补一个小功能，而是把当前旧系统逐步迁移到 `todo.txt` A-G 和 `REFACTOR_GUIDE.md` 所描述的新战斗引擎。

