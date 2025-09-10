# SimpleBot 系统说明书

## 系统概述

SimpleBot是一个基于Python和Telegram的角色扮演游戏战斗机器人，支持角色管理、技能系统、回合制战斗、状态效果和种族系统等功能。系统采用SQLite数据库存储数据，支持复杂的技能效果计算和状态管理。

## 系统架构

```
SimpleBot/
├── src/
│   ├── main.py                    # 主程序入口
│   ├── character/                 # 角色系统
│   │   ├── character_management.py   # 角色管理
│   │   ├── race_management.py        # 种族管理
│   │   ├── persona_management.py     # 人格系统
│   │   ├── status_effects.py         # 状态效果
│   │   └── status_formatter.py       # 状态显示格式化
│   ├── skill/                     # 技能系统
│   │   ├── skill_management.py       # 技能管理
│   │   ├── skill_effects.py          # 技能效果执行
│   │   └── effect_target_resolver.py # 目标解析
│   ├── game/                      # 游戏逻辑
│   │   ├── attack.py                 # 攻击系统
│   │   ├── damage_calculator.py      # 伤害计算
│   │   └── turn_manager.py           # 回合管理
│   └── database/                  # 数据库
│       ├── db_connection.py          # 数据库连接
│       ├── queries.py                # 查询函数
│       └── db_migration.py           # 数据库迁移
└── data/
    └── simplebot.db              # SQLite数据库文件
```

---

## 功能一览

### 🎭 角色管理系统

#### 基础功能
- **角色创建**: 创建友方角色和敌方角色
- **角色查看**: 查看角色详情、生命值、状态效果
- **生命值管理**: 修改角色当前生命值
- **状态重置**: 重置单个或所有角色状态

#### 高级功能
- **种族系统**: 15种可选种族，支持伤害抗性设置
- **人格系统**: 核心角色支持多重人格切换
- **行动系统**: 设置每回合行动次数(1-5次)

### ⚔️ 战斗系统

#### 回合制战斗
- **战斗加入/离开**: 角色可自由加入或离开战斗
- **攻击系统**: 友方和敌方分别的攻击流程
- **目标选择**: 智能目标过滤和选择
- **回合管理**: 自动处理回合结束和状态效果

#### 伤害计算
- **伤害类型**: 物理伤害、魔法伤害
- **抗性系统**: 物理抗性、魔法抗性减伤
- **特攻系统**: 对特定种族的额外伤害
- **暴击系统**: 暴击率和暴击倍率

### 🎯 技能系统

#### 技能分类
- **damage**: 伤害技能，对敌方造成伤害
- **healing**: 治疗技能，恢复友方生命值
- **buff**: 增益技能，给友方添加正面状态
- **debuff**: 减益技能，给敌方添加负面状态
- **self**: 自我技能，只对施法者生效
- **aoe_damage**: AOE伤害，对所有敌方造成伤害
- **aoe_healing**: AOE治疗，治疗所有友方
- **aoe_buff**: AOE增益，给所有友方添加增益
- **aoe_debuff**: AOE减益，给所有敌方添加减益

#### 效果系统
- **主效果**: 由skill_category决定，影响目标选择和主要效果
- **次要效果**: 在effects JSON中定义，支持复杂的组合效果
- **百分比效果**: 基于主效果数值的百分比计算次要效果
- **目标解析**: 支持多种目标类型(自己、目标、所有友方/敌方等)

#### 冷却系统
- **行动冷却**: 以"次行动"为单位的冷却时间
- **冷却缩减**: 每次使用技能会减少所有技能1次冷却
- **即时效果**: 加速效果可立即增加当前回合行动次数

### 🌟 状态效果系统

#### 增益状态(Buff)
- **强壮**: 攻击伤害 +(层数×10%)
- **呼吸法**: 暴击率 +强度×1%，暴击伤害120%
- **🔰守护**: 受到伤害 -(层数×10%)
- **护盾**: 抵消护盾强度的伤害，被击破后消失
- **加速**: 增加行动次数和冷却缩减

#### 减益状态(Debuff)
- **烧伤**: 每回合结束扣强度×1点血
- **中毒**: 每回合结束扣强度×1%最大生命值
- **破裂**: 受击时扣强度×1点血并减1层
- **流血**: 行动后扣强度×1点血并减1层
- **虚弱**: 攻击伤害 -(层数×10%)
- **易伤**: 受到伤害 +(层数×10%)

---

## 使用方法

### 基础操作

#### 启动系统
```
/start - 启动机器人
/help - 显示帮助信息
```

#### 角色管理
```
# 创建角色
/create_character 角色名 最大生命值 攻击力 防御力 魔法攻击 魔法防御
/cc 艾丽丝 100 15 10 12 8

# 创建敌方角色
/create_enemy 敌人名 最大生命值 攻击力 防御力 魔法攻击 魔法防御
/ce 哥布林 80 12 8 5 6

# 查看角色
/characters        # 查看所有友方角色
/enemies          # 查看所有敌方角色
/show 角色名       # 查看具体角色详情

# 修改生命值
/health 角色名 新生命值

# 重置状态
/reset 角色名      # 重置单个角色
/reset_all        # 重置所有角色
```

#### 种族管理
```
/race 角色名       # 为角色设置种族和抗性
```

可选种族：人类、精灵、矮人、兽人、龙族、天使、恶魔、不死族、机械、元素、妖精、巨人、魔族、虫族、异界生物

#### 人格系统
```
/create_core 角色名    # 创建核心角色（珏、露、莹、笙、曦）
/persona 角色名 人格名  # 切换角色人格
/personas 角色名       # 查看可用人格
/core_status          # 查看所有核心角色状态
```

### 战斗操作

#### 战斗准备
```
# 加入战斗
/join 角色名               # 单个角色加入
/join 角色1 角色2 角色3      # 批量加入
/join all friendly        # 所有友方加入
/join all enemy           # 所有敌方加入

# 离开战斗
/leave 角色名             # 单个角色离开
/end_battle              # 所有角色离开战斗

# 查看战斗状态
/battle                  # 查看当前战斗状态
```

#### 战斗行动
```
/attack                  # 友方角色攻击/使用技能
/enemy_attack            # 敌方角色攻击/使用技能
/end_turn               # 结束当前回合
```

#### 行动次数设置
```
/set_actions 角色名 次数   # 设置每回合行动次数(1-5)
```

### 技能管理

```
/sm 角色名               # 管理角色技能
/skills                 # 查看角色技能列表
```

技能管理支持：
- 添加新技能
- 编辑现有技能
- 删除技能
- 批量操作

---

## 数据库结构

### characters 表（角色信息）

| 字段名 | 类型 | 说明 |
|--------|------|------|
| id | INTEGER PRIMARY KEY | 角色唯一标识符 |
| name | TEXT NOT NULL | 角色名称 |
| character_type | TEXT NOT NULL | 角色类型：'friendly'(友方) 或 'enemy'(敌方) |
| max_health | INTEGER DEFAULT 100 | 最大生命值 |
| health | INTEGER DEFAULT 100 | 当前生命值 |
| attack | INTEGER DEFAULT 10 | 物理攻击力 |
| defense | INTEGER DEFAULT 5 | 物理防御力 |
| magic_attack | INTEGER DEFAULT 10 | 魔法攻击力 |
| magic_defense | INTEGER DEFAULT 5 | 魔法防御力 |
| in_battle | INTEGER DEFAULT 0 | 是否在战斗中：0(否) 1(是) |
| actions_left | INTEGER DEFAULT 1 | 当前剩余行动次数 |
| actions_per_turn | INTEGER DEFAULT 1 | 每回合行动次数 |
| race | TEXT | 角色种族标签 |
| physical_resistance | REAL DEFAULT 0 | 物理抗性(0-1之间的小数) |
| magic_resistance | REAL DEFAULT 0 | 魔法抗性(0-1之间的小数) |

### skills 表（技能信息）

| 字段名 | 类型 | 说明 |
|--------|------|------|
| id | INTEGER PRIMARY KEY | 技能唯一标识符 |
| name | TEXT NOT NULL | 技能名称 |
| skill_category | TEXT NOT NULL | 技能分类：damage/healing/buff/debuff/self/aoe_* |
| description | TEXT | 技能描述 |
| damage_formula | TEXT | 伤害计算公式，如"10+1d6" |
| damage_type | TEXT DEFAULT 'physical' | 伤害类型：'physical'(物理) 或 'magical'(魔法) |
| effects | TEXT | 次要效果的JSON字符串 |
| target_races | TEXT | 特攻种族列表，JSON格式 |
| cooldown | INTEGER DEFAULT 0 | 冷却时间（次行动） |

### character_skills 表（角色技能关联）

| 字段名 | 类型 | 说明 |
|--------|------|------|
| id | INTEGER PRIMARY KEY | 关联记录ID |
| character_id | INTEGER | 角色ID，外键关联characters.id |
| skill_id | INTEGER | 技能ID，外键关联skills.id |

### character_status_effects 表（角色状态效果）

| 字段名 | 类型 | 说明 |
|--------|------|------|
| id | INTEGER PRIMARY KEY | 状态效果记录ID |
| character_id | INTEGER | 角色ID |
| effect_type | TEXT NOT NULL | 效果类型：'buff' 或 'debuff' |
| effect_name | TEXT NOT NULL | 效果名称：如'strong'、'burn'等 |
| intensity | INTEGER DEFAULT 1 | 效果强度/层数 |
| duration | INTEGER NOT NULL | 持续时间（回合数） |

### character_cooldowns 表（角色技能冷却）

| 字段名 | 类型 | 说明 |
|--------|------|------|
| id | INTEGER PRIMARY KEY | 冷却记录ID |
| character_id | INTEGER | 角色ID |
| skill_id | INTEGER | 技能ID |
| remaining_cooldown | INTEGER DEFAULT 0 | 剩余冷却时间（次行动） |

### personas 表（人格信息）

| 字段名 | 类型 | 说明 |
|--------|------|------|
| id | INTEGER PRIMARY KEY | 人格记录ID |
| character_id | INTEGER | 角色ID |
| persona_name | TEXT NOT NULL | 人格名称 |
| is_active | INTEGER DEFAULT 0 | 是否激活：0(否) 1(是) |
| max_health | INTEGER | 人格专属最大生命值 |
| attack | INTEGER | 人格专属攻击力 |
| defense | INTEGER | 人格专属防御力 |
| magic_attack | INTEGER | 人格专属魔法攻击 |
| magic_defense | INTEGER | 人格专属魔法防御 |

### battle_log 表（战斗日志）

| 字段名 | 类型 | 说明 |
|--------|------|------|
| id | INTEGER PRIMARY KEY | 日志记录ID |
| attacker_id | INTEGER | 攻击者角色ID |
| target_id | INTEGER | 目标角色ID |
| damage | INTEGER | 造成的伤害值 |
| skill_id | INTEGER | 使用的技能ID |
| timestamp | TEXT DEFAULT CURRENT_TIMESTAMP | 记录时间戳 |

---

## 技能效果系统详解

### Effects JSON格式

技能的次要效果使用JSON格式存储在skills表的effects字段中：

```json
{
  "status": [
    {
      "effect": "strong",
      "turns": 3,
      "value": 2,
      "target": "self"
    }
  ],
  "damage": {
    "target": "skill_target",
    "percentage": 20
  },
  "heal": {
    "target": "attacker",
    "amount": 25
  }
}
```

#### 状态效果 (status)
```json
{
  "effect": "效果名称",    // strong, burn, weak等
  "turns": 持续回合数,
  "value": 效果强度,
  "target": "目标类型"    // self, skill_target, attacker等
}
```

#### 伤害效果 (damage)
```json
{
  "target": "目标类型",
  "amount": 固定伤害值,     // 固定数值
  "percentage": 百分比      // 基于主效果的百分比
}
```

#### 治疗效果 (heal)
```json
{
  "target": "目标类型",
  "amount": 固定治疗值,     // 固定数值  
  "percentage": 百分比      // 基于主效果的百分比
}
```

### 目标类型说明

| 目标类型 | 说明 |
|---------|------|
| self | 施法者自己 |
| skill_target | 技能选中的目标 |
| attacker | 施法者（同self） |
| all_allies | 所有友方角色 |
| all_enemies | 所有敌方角色 |
| friendly | 所有友方角色 |
| enemy | 所有敌方角色 |

### 百分比计算规则

- **percentage字段**: 基于当次技能主效果的百分比
- 例如：主效果造成100点伤害，次要效果设置percentage: 30，则次要效果造成30点伤害
- 适用于damage和heal效果
- 与amount字段互斥，优先使用amount

---

## 高级功能

### 批量操作

#### 批量加入战斗
```
/join 角色1 角色2 角色3        # 指定多个角色
/join all friendly           # 所有友方角色
/join all enemy             # 所有敌方角色
```

#### 技能管理批量操作
在技能管理界面中支持：
- 批量添加技能到多个角色
- 批量删除角色技能
- 技能模板复制

### 种族系统高级用法

#### 抗性设置
- 物理抗性：减少物理伤害的百分比(0-100%)
- 魔法抗性：减少魔法伤害的百分比(0-100%)
- 种族标签：影响特攻技能的额外伤害

#### 特攻系统
某些技能对特定种族有额外伤害：
```json
{
  "target_races": ["龙族", "不死族"],
  "damage_formula": "15+1d8"
}
```

### 状态效果高级机制

#### 护盾机制
- 护盾值独立于生命值
- 优先抵消护盾值，护盾破除后才扣生命值
- 护盾被完全消耗后自动移除状态

#### 层数叠加
- 同名buff/debuff可叠加层数
- 最大层数限制为99层
- 部分效果按层数计算强度

#### 状态交互
- 某些状态可以相互抵消
- 状态效果的计算顺序影响最终结果
- 支持状态免疫和抗性

---

## 故障排除

### 常见问题

1. **角色无法加入战斗**
   - 检查角色是否存在
   - 确认角色生命值是否大于0
   - 检查角色是否已在战斗中

2. **技能无法使用**
   - 检查技能冷却时间
   - 确认角色剩余行动次数
   - 验证技能是否分配给角色

3. **伤害计算异常**
   - 检查抗性设置是否正确
   - 验证伤害公式格式
   - 确认状态效果是否影响计算

### 数据库维护

#### 备份数据库
```bash
cp data/simplebot.db data/simplebot_backup_$(date +%Y%m%d).db
```

#### 重置数据库
```bash
rm data/simplebot.db
# 重启机器人会自动创建新数据库
```

#### 数据库迁移
系统启动时会自动运行数据库迁移，更新数据库结构到最新版本。

---

## 开发说明

### 添加新功能

1. **新状态效果**: 在`character/status_effects.py`中添加处理逻辑
2. **新技能类型**: 在`skill/skill_effects.py`中添加执行方法
3. **新命令**: 在对应模块中添加处理函数，并在`main.py`中注册

### 代码结构

- **模块化设计**: 每个功能模块独立，便于维护
- **数据访问层**: 所有数据库操作集中在`database/queries.py`
- **错误处理**: 完整的异常捕获和用户友好的错误提示
- **日志记录**: 详细的操作日志便于调试

### 扩展指南

系统支持轻松扩展：
- 新的角色属性
- 更多技能效果类型
- 复杂的战斗机制
- 额外的管理命令

---

## 版本历史

- **v1.0**: 基础角色和战斗系统
- **v1.1**: 添加状态效果系统
- **v1.2**: 实现技能管理和冷却系统
- **v1.3**: 加入种族和抗性系统
- **v1.4**: 人格系统和核心角色
- **v1.5**: AOE技能和百分比效果系统
- **v2.0**: 统一效果系统和目标解析

---

本说明书涵盖了SimpleBot系统的所有功能和使用方法。如需更多帮助，请使用`/help`命令查看实时帮助信息。
