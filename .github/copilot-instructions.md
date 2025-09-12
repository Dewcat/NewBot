<!-- Use this file to provide workspace-specific custom instructions to Copilot. For more details, visit https://code.visualstudio.com/docs/copilot/copilot-customization#_use-a-githubcopilotinstructionsmd-file -->

# SimpleBot - Telegram RPG战斗机器人开发规范

## 项目架构概览

这是一个基于Telegram Bot的RPG战斗系统，采用模块化设计：
- `src/main.py`: Telegram Bot主入口
- `src/database/`: 数据持久化层（SQLite）
- `src/game/`: 战斗逻辑核心（伤害计算、回合管理）
- `src/character/`: 角色系统（属性、状态、种族、人格）
- `src/skill/`: 技能系统（效果处理、目标解析、特殊效果）
- `src/effects/`: 基础效果类定义

## 关键开发规范

### 技能系统规范
**CRITICAL**: 技能分类必须严格遵循以下规范：

#### skill_category字段的标准值：
- `damage`: 单体伤害技能
- `healing`: 单体治疗技能  
- `buff`: 单体增益技能
- `debuff`: 单体减益技能
- `self`: 自身效果技能
- `aoe_damage`: AOE伤害技能
- `aoe_healing`: AOE治疗技能
- `aoe_buff`: AOE增益技能
- `aoe_debuff`: AOE减益技能

**❌ 错误示例**: `skill_category='aoe'` + `effects='{"aoe_damage": {...}}'`
**✅ 正确示例**: `skill_category='aoe_damage'` + `effects='{"damage": {...}}'`

#### 技能运作机制详解：

**1. 目标选择逻辑**：
- 系统根据`skill_category`自动过滤可选目标：
  - `damage/debuff`: 只能选择敌方角色
  - `healing/buff`: 只能选择友方角色  
  - `self`: 强制目标为施法者自身
  - `aoe_*`: 无需选择目标，自动作用于对应类型的所有角色

**2. 效果执行顺序**：
```
伤害计算 → 攻击者状态修正 → 目标受击效果 → 应用伤害 → 
混乱值处理 → 技能附加状态效果 → 攻击者行动后效果 → 冷却时间更新
```

**3. effects字段结构规范**：
```json
{
  "damage": {"target": "skill_target", "percentage": 100},
  "status": [{"effect": "burn", "turns": 3, "value": 5, "target": "skill_target"}],
  "conditional_damage": {"condition": "hardblood", "multiplier": 2.0}
}
```

**4. 技能效果体系**：
- **主要效果**: 由`damage_formula`字段定义的基础伤害/治疗
- **附加效果**: 由`effects`字段定义的额外效果，包括：
  - **附加伤害**: conditional_damage、硬血消耗伤害等会加到主要效果中
  - **状态效果**: burn、heal等状态会独立计算和应用
  - **自我效果**: 对施法者的伤害/治疗（不计入主要效果）
- **伤害合并规则**: 除自我伤害外，所有附加伤害都会加到damage_formula计算结果中
- **计算顺序**: 主要效果 → 附加效果 → 攻防修正 → 抗性减免 → 状态修正

**5. 冷却系统**：
- 冷却时间以"次行动"为单位（非回合）
- 每次使用技能后立即进入冷却
- 每次任何角色行动时，所有角色的技能冷却-1
- 存储在角色status JSON的`cooldowns`字段中

**6. 状态效果时机**：
- **回合开始**: 持续伤害/治疗效果触发
- **受击时**: 护盾吸收、反击效果触发
- **行动后**: 呼吸法恢复、毒素伤害等触发
- **回合结束**: 状态持续时间-1，清理过期状态

### 状态效果系统说明

#### 强度(intensity)与层数(duration)机制：
- **强度**: 决定效果的威力大小（如伤害数值、加成百分比）
- **层数**: 决定效果的持续时间（回合数或触发次数）
- **叠加规则**: 相同状态效果可叠加层数，强度取最大值，特别地，如果增加效果层数为0，则如果原本没有此效果，将层数置为1，否则只更新强度。
- **显示格式**: `效果名(强度/层数)` 如 强壮(3/5) 表示3强度持续5层
- **特殊情况**: 护盾只显示强度(剩余护盾值)，硬血强度=数量且层数固定为1

### 完整状态效果列表

#### 增益状态 (Buff)
- **💪强壮 (strong)**: 攻击伤害+（强度×10%）| 回合结束-1层
- **🫁呼吸法 (breathing)**: 暴击率+强度% | 回合结束-1层
- **🛡️守护 (guard)**: 受伤减免（强度×10%）| 回合结束-1层  
- **🛡️护盾 (shield)**: 吸收伤害，强度=剩余护盾值 | 受击时消耗，破盾时移除
- **⚡加速 (haste)**: +1行动次数，获得时立即生效 | 回合结束-1层

#### 减益状态 (Debuff)
- **🔥烧伤 (burn)**: 回合结束受到（强度×1）固定伤害 | 回合结束-1层
- **☠️中毒 (poison)**: 回合结束受到（强度×1%）当前生命值伤害 | 回合结束-1层
- **💥破裂 (rupture)**: 受击时额外受到（强度×1）伤害 | 受击时-1层
- **🩸流血 (bleeding)**: 行动后受到（强度×1）伤害 | 行动后-1层
- **😵虚弱 (weak)**: 攻击伤害-（强度×10%）| 回合结束-1层
- **💔易伤 (vulnerable)**: 受伤增加（强度×10%）| 回合结束-1层
- **⚡麻痹 (paralysis)**: 阻止行动，只能通过特定技能减少层数 | 不自动减少

#### 特殊状态 (Special)
- **🩸硬血 (hardblood)**: 可被技能消耗的资源，强度=数量，层数固定为1 | 不自动减少，只能被消耗
- **🌑黑夜领域 (dark_domain)**: 回合结束获得强壮+易伤+加速+负面情感币 | 回合结束-1层
- **💜削弱光环 (weaken_aura)**: 回合结束为所有敌方施加虚弱+易伤 | 回合结束-1层

### 角色创建规范
使用`/cc <名称> <生命值> <攻击力> <防御力> <魔攻> <魔防>`创建角色。
数据库字段映射：
- `character_type`: 'friendly'/'enemy'
- `race_tags`: JSON数组，如`["human", "warrior"]`
- `physical_resistance`/`magic_resistance`: 0.0-1.0浮点数

### 状态效果目标规范
- `self`: 施法者自身
- `skill_target`: 技能选择的目标
- `all_allies`: 所有友方
- `all_enemies`: 所有敌方
- `all_characters`: 所有角色

### 技能创建完整规范

#### 伤害公式系统 (damage_formula)
**支持的格式**：
- `"1d6"`: 1个6面骰子
- `"2d8"`: 2个8面骰子  
- `"10"`: 固定值10
- `"5+2d3"`: 基础值5 + 2个3面骰子
- `"3d4+2"`: 3个4面骰子 + 2
- `"1d12+5"`: 1个12面骰子 + 5

**解析规则**：
- 使用`+`号连接多个部分
- 骰子格式: `{数量}d{面数}`（如`3d6`表示3个6面骰子）
- 固定数值直接写数字
- 执行顺序: 先投骰子，再加固定值
- 麻痹状态会让部分骰子变为0

**数据库字段要求**：
- `name`: 技能名称
- `description`: 技能描述
- `skill_category`: 必须使用标准分类值
- `damage_formula`: 伤害/治疗公式（如'1d6+5', '2d8'）
- `damage_type`: 'physical'/'magic'
- `cooldown`: 冷却时间（次行动）
- `effects`: JSON格式的效果定义
- `required_emotion_level`: 所需情感等级

**技能创建示例**：
```sql
-- 单体火球术 (中等魔法伤害)
INSERT INTO skills (name, skill_category, damage_formula, damage_type, effects, cooldown) 
VALUES ('火球术', 'damage', '2d6+3', 'magic', '{"status": [{"effect": "burn", "turns": 3, "value": 2, "target": "skill_target"}]}', 2);

-- AOE治疗技能 (低治疗量)
INSERT INTO skills (name, skill_category, damage_formula, effects, cooldown)
VALUES ('群体治疗', 'aoe_healing', '1d6+2', '{"status": [{"effect": "strong", "turns": 2, "value": 1, "target": "all_allies"}]}', 3);

-- 高伤害单体攻击 (物理伤害)
INSERT INTO skills (name, skill_category, damage_formula, damage_type, cooldown)
VALUES ('重击', 'damage', '1d12+5', 'physical', 4);

-- 固定伤害技能
INSERT INTO skills (name, skill_category, damage_formula, damage_type)
VALUES ('精准射击', 'damage', '8', 'physical');

-- 自我增益技能 (无伤害)
INSERT INTO skills (name, skill_category, effects)
VALUES ('铁壁', 'self', '{"status": [{"effect": "guard", "turns": 5, "value": 2, "target": "self"}]}');
```

#### 伤害计算流程：
1. **解析伤害公式** → 投掷骰子 + 计算固定值
2. **应用麻痹效果** → 部分骰子归零  
3. **攻防修正** → 根据角色攻击力和目标防御力调整
4. **种族特攻** → special_damage_tags对特定种族额外伤害
5. **抗性减免** → 物理/魔法抗性减少最终伤害
6. **状态修正** → 强壮/虚弱等状态影响最终伤害

### 开发工作流
1. **运行项目**: `cd src && python main.py`
2. **数据库操作**: 直接使用`sqlite3 data/simplebot.db`
3. **添加新技能**: 更新skills表 + 在skill_effects.py中处理
4. **添加新状态**: 在character/status_effects.py中定义处理逻辑

### 重要约定
- 所有数据库操作必须通过`database/queries.py`
- 技能效果处理统一在`skill/skill_effects.py`
- 特殊效果放在`skill/special_effects/`目录
- 状态效果统一使用`character/status_effects.py`处理
- 错误日志使用Python logging模块

### 调试技巧
- 查看技能数据：`sqlite3 data/simplebot.db "SELECT name, skill_category, effects FROM skills;"`
- 重置角色状态：`/reset <角色名>`
- 直接修改数据库：进入src目录后使用sqlite3命令
