> 当前回合顺序与人格防御配置以 [回合指令规则](TURN_COMMANDS.md) 为准：敌方先设置技能与目标，玩家攻击立即结算，防御在敌方攻击阶段结算。

# Dewbot v2 内容包扩展指南

本项目把“规则执行”和“游戏内容”分开：Python 引擎负责回合、时机、目标、冷却、情感、状态生命周期和事务；JSON 内容包负责角色、人格、技能、效果、异想体书页与管理人能力。绝大多数新增内容不需要改表，也不需要复制一份战斗代码。

## 1. 内容包的基本约定

- 每项定义内容都使用稳定、小写、带命名空间的 `key`，例如 `my_pack.skill.echo_cut`。普通定义的显示名称可以修改，引用关系只使用 `key`；当前核心角色是例外，仍以名称定位，因此核心角色名称暂时不可重命名。
- `pack.version` 和内容校验和会写入数据库。同一个包可以重复加载；现有定义会更新，包内已删除的旧定义会停用。
- 包可以引用此前已加载包中的技能与效果。基础包必须先于扩展包加载。
- 跨包引用应在 `pack.requires` 声明依赖及可选的 `min_version`；加载器会检查顺序和最低版本，并阻止提供方删除仍被其他包使用的键。
- 定义数据与战斗运行态分表保存。更新内容包不会覆盖玩家角色实例、战斗日志或剧情解锁。唯一例外：重载会把装备中人格的最新数值重新应用到对应核心角色，其当前 HP/行动/混乱会随之重置为满值（与切换人格的覆盖语义一致）。
- 普通效果优先用声明式行为组合；只有无法由现有行为表达的新机制，才注册一个 Python 特殊处理器。
- 内容对象采用严格字段白名单；未知字段会在加载时直接报错，避免拼写错误被静默忽略。
- 文案规范：通用效果描述统一用『X点强度』表述，禁用『层』字。

可用命令：

```powershell
$env:PYTHONPATH='src'
python -m dewbot.cli init-db
python -m dewbot.cli load-content content/base_pack.json
python -m dewbot.cli load-content content/core_personas.json
python -m dewbot.cli load-content content/example_extension.json
```

## 2. 新增普通技能

技能由一个目标规则和一组按顺序执行的 `behaviors` 组成。行为时机严格使用：

1. `TURN_START`：回合开始
2. `PRE`：使用前
3. `ON`：使用时，包括命中、暴击命中、暴击发动
4. `POST`：使用后，包括各种击杀或未击杀条件
5. `TURN_END`：回合结束

`trigger_condition` 表达触发条件，`trigger_scope` 明确一次技能、每个目标或每次命中的结算次数。行为层若使用 `target_source: AUTO`，只能自动推导目标，不能再次要求玩家选择。

### 2.1 TURN_START / TURN_END 行为的强制要求

回合钩子行为（`timing` 为 `TURN_START` 或 `TURN_END`）有额外的加载校验：

- `trigger_condition` 只允许 `ALWAYS`。
- 必须提供 `params.registration` 对象，声明生命周期：
  - `active_from`：`"NEXT_TURN_START"`（TURN_END 行为另可用 `"THIS_TURN_END"`；TURN_START 行为不能使用 `THIS_TURN_END`）。
  - `lifecycle_scope`：`"TURN"`、`"STAGE"` 或 `"BATTLE"`（默认 `TURN`），临时行为在 Stage End 清除。
  - `remaining_turns` 与 `remaining_triggers`：正整数或 `null`（默认 1）。
- 语义：角色持有技能不会自动获得回合被动；回合钩子行为在技能使用时登记，之后按声明的生命周期在对应时机触发。

完整示例（使用技能后，本回合结束时立即生效一次的 TURN_END 行为）：

```json
{
  "key": "my_pack.behavior.ember.turn_end_burst",
  "timing": "TURN_END",
  "trigger_condition": "ALWAYS",
  "effect_type": "DAMAGE",
  "value": "1d4+2",
  "params": {
    "registration": {
      "active_from": "THIS_TURN_END",
      "lifecycle_scope": "TURN",
      "remaining_turns": 1,
      "remaining_triggers": 1
    }
  }
}
```

若示例改用 `TURN_START` 时机，`active_from` 必须是 `NEXT_TURN_START`。

普通伤害、治疗和施加效果分别使用 `DAMAGE`、`HEAL`、`APPLY_EFFECT`。延迟到下一回合生效的效果在参数中写：

```json
{"activation_timing": "NEXT_TURN_START", "intensity": 2}
```

这会进入待生效队列，不会违反“通用效果在回合结束全部清空”的裁决。

## 3. 新增角色、人格与 EGO

- `characters[]` 只定义可重复生成的普通单位/敌人模板；`characters[].skills` 是生成单位直接拥有的技能。
- 生成模板允许 `max_actions: 0`，用于不会行动且敌方阶段自动跳过的木桩/场景单位；`core_characters[]` 与人格的 `max_actions` 仍必须为正整数。
- `core_characters[]` 会直接幂等写入 `characters` 表，不经过模板、角色本体表或 `role_key`。核心角色以名称作为内容声明中的稳定身份。
- 顶层 `personas[]` 使用 `character` 指定核心角色名称；数据库中的 `personas.character_id` 直接外键关联实际角色。
- 人格保存绝对的 `max_hp`、`max_actions`、`max_stagger` 与普通技能组。切换人格会直接覆盖角色当前战斗数据；`default: true` 表示未装备特殊人格时使用的初始人格。
- 每名核心角色必须恰有一个启用中的默认人格；只有拥有该核心角色的内容包能声明默认人格，且默认人格三项初始数值必须与 `core_characters[]` 一致。扩展包只能追加非默认人格。
- `core_characters[].ego_skill` 引用一个 `type: EGO` 的技能。EGO 外键直接保存在核心角色记录上，不随人格切换，并由引擎保证每角色每战任意 EGO 只能使用一次。
- EGO 技能的 `emotion` 必须为 1–5、`cooldown` 必须为 `0`，`max_uses_per_battle` 只能为 `1` 或 `null`；普通技能的情感要求可以为 0–5。
- 普通技能需要“每场战斗限用 N 次”时使用 `max_uses_per_battle`；它有独立的战斗使用记录，不应以超长冷却模拟。
- 模板只负责生成普通单位；五名核心角色本身就是持久记录，内容加载时直接建立或更新，不执行 `/spawn`。

## 关卡与战斗容器

`encounters` 用来声明一场战斗有哪些阶段，以及每个阶段预设生成哪些敌人：

```json
{
  "encounters": [
    {
      "key": "encounter.training_ground",
      "name": "训练场档案",
      "abnormalities": ["example.abnormality.second_hand"],
      "stages": [
        {
          "name": "第一阶段",
          "clear_when": {"type": "ALL_ENEMIES_DEFEATED"},
          "on_clear": "VICTORY",
          "enemies": [
            {"id": "guard", "template": "enemy.training_shell", "count": 2}
          ]
        }
      ]
    }
  ]
}
```

`encounters[].abnormalities` 声明该关卡战斗的书页池来源，元素必须引用已加载且启用的异想体键；建立待触发战斗时快照进战斗，之后重载关卡不漂移。

核心角色和人格不写进关卡：管理员在战斗筹备时选择参战核心角色，再为每名角色选择人格。普通友方可以按持久角色编号追加；临时敌人可以用模板追加到指定阶段。正式开战时才会生成第一阶段敌人并创建战斗记录。

内容键只用于 JSON、数据库和扩展开发。Telegram 日常操作以战斗名称、中文按钮和短编号为准：`/new 名称` 创建多场待触发战斗，`/battles` 查看，`/use 编号` 选中，然后通过 `/team` 选择触发战斗的核心角色；`/ally`、`/foe` 用于随时增援。同一管理人在不同聊天中的当前选择彼此独立。

战斗实例建立后处于 `STANDBY`（界面显示“待触发”）：关卡和预设敌人已经确定，但核心友方尚未进入。选择至少一名核心角色及人格后才能触发战斗。普通友方和额外敌人属于增援，可在触发前或战斗中加入，不构成触发流程。

建立 `STANDBY` 记录时会快照阶段名称、敌人编成、结束条件和异想体池，之后重载关卡不会让既有记录漂移。敌人模板数值、人格数值和技能定义仍在正式触发时读取当前启用版本；需要完全锁定平衡版本的长期活动应在触发前避免更新相关内容包。

每个阶段通过 `clear_when` 声明结算条件，通过 `on_clear` 声明满足条件后的结果：

- `ALL_ENEMIES_DEFEATED`：所有当前阶段敌人被击败。
- `TARGET_DEFEATED`：指定 `enemy.id` 的首领被击败。
- `TARGET_HP_BELOW`：指定首领生命比例不高于 `ratio`，例如 `0.5`。
- `NEXT_STAGE`：条件满足后进入阶段结束，等待展开下一阶段。
- `VICTORY`：条件满足后直接以胜利结束战斗。

最后一个阶段必须使用 `VICTORY`；使用目标条件时，对应 `enemy.id` 的 `count` 必须为 1，避免“首领”实际生成多份时语义不确定。

例如首领半血时切换阶段：

```json
{
  "clear_when": {"type": "TARGET_HP_BELOW", "target": "boss", "ratio": 0.5},
  "on_clear": "NEXT_STAGE",
  "enemies": [
    {"id": "boss", "template": "enemy.example_boss", "count": 1}
  ]
}
```
- `character_extensions[]` 可向既有模板附加模板技能或 `ego_skills`。这些关联由扩展包拥有，重载/移除包时不会改写原角色定义。
- 新的小怪只需追加模板定义；生成实例时数据库会快照当前模板数值。

[`content/example_extension.json`](content/example_extension.json) 演示了如何给既有核心角色追加人格，并让该人格同时引用基础包技能和扩展包新技能。

## 4. 新增效果与特殊机制

效果定义分为：

- `GENERIC`：强壮、虚弱、护盾等；回合结束统一清空。
- `REGULAR`：烧伤、中毒、流血、破裂、呼吸法等；按各自固定规则结算与衰减。
- `SPECIAL`：跨回合资源或角色专属状态，由处理器和参数决定生命周期。
- `INSTANT`：不进入状态表的即时效果，例如增加行动次数。

已有行为无法表达的新机制，通过稳定的处理器键接入：

```python
def my_handler(context):
    context.messages.append("└ 新机制完成结算。")

registry.register("my_pack.my_handler", my_handler)
engine = BattleEngine(database, registry=registry)
```

内容包中相应行为使用 `effect_type: SPECIAL`，并把处理器键写入 `value`。处理器通过 `EffectExecutionContext` 获得事务连接、战斗、行动者、目标、参数和本次技能快照，因此新机制不会绕开统一的事务与日志边界。

基础运行时已经登记 `bonus_actions`、`summon_unit`、`invoke_skill`、`accumulate_resource`、`consume_resource`、`require_effect_from_actor`、`fortune_verdict` 和 `emotion_shift`。硬血使用 `params.amount` 作为独立资源池，不占用强度/层数；`consume_resource` 可在技能行为中原子扣除，并把实际消耗量写入结算快照，供后续伤害行为读取。

后三个处理器的参数说明：

- `require_effect_from_actor`：`params.effect_key` 必填。要求每个目标身上存在由行动者本人施加的该效果；不满足时抛出 `params.error` 自定义文案（缺省为通用提示）。典型用于 `PRE` 时机做技能使用条件。
- `fortune_verdict`：`params.intensity` 默认 `2`。50% 概率给行动者施加 `status.strength` 或 `status.weakness`，并把结果记入对应的正面/负面情感硬币。
- `emotion_shift`：`params.polarity` 取 `POSITIVE`/`NEGATIVE`，默认 `NEGATIVE`；`params.amount` 默认 `1`。为各目标——无目标时为行动者——累积情感硬币，达到阈值时标记待升级。

## 5. 异想体书页与管理人能力

- `abnormalities[].pages[]` 定义觉醒/崩溃书页。核心角色情感升级时，由战斗池生成候选；选择后按 `params.events` 订阅统一战斗事件。默认事件为 `TURN_START`，还可订阅 `ON_BEFORE_DAMAGE`、`ON_HIT`、`ON_CRIT`、`ON_AFTER_DAMAGE`、`ON_KILL`、`ON_ACTION_END`、`TURN_END`。
- `pages[].level`（1-3，默认 1）：书页按团队情感等级分段解锁——1级页在团队情感 1-2 级出现，2级页在 3-4 级，3级页仅在 5 级。每个异想体应尽量在各等级都配觉醒与崩溃页，形成完整小卡组。
- `abnormalities[].carry_bonus`（可选）：`{key, name, description, handler, params}` 定义"携带即生效"的被动增益；入库为 `page_type='CARRY'` 的书页行，不进抽取池，开战自动激活并播报。玩家最多同时携带 5 个异想体。
- `manager_skills[]` 定义全局能力、剧情 `unlock` 键、合法阶段、每战次数和处理器。手动干预窗口只允许 `FRIENDLY_ACTION`、`ENEMY_ACTION`、`STAGE_END` 或 `null`；剧情系统只需调用 `unlock_manager_feature()` 登记解锁，不需要改能力表结构。

内容发生变化时只能在没有活动战斗的窗口加载；战斗中仅允许 checksum 完全相同的幂等 no-op。示例包故意不在默认配置中自动加载，便于把它当作作者模板。正式内容应使用自己的包命名空间，并为规则边界补充测试。
