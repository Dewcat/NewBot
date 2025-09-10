# SimpleBot 角色系统完整指南

## 📋 目录
- [系统概述](#系统概述)
- [角色管理基础](#角色管理基础)
- [人格系统详解](#人格系统详解)
- [情感系统机制](#情感系统机制)
- [状态效果系统](#状态效果系统)
- [混乱值系统](#混乱值系统)
- [种族抗性系统](#种族抗性系统)
- [命令参考手册](#命令参考手册)
- [高级管理功能](#高级管理功能)

---

## 🏗️ 系统概述

SimpleBot角色系统是一个**多层次、高度集成**的角色管理框架，支持：

### 核心架构

```
角色系统
├── 基础角色管理 (character_management.py)
├── 人格切换系统 (persona.py, persona_management.py)
├── 情感等级系统 (emotion_system.py)
├── 状态效果管理 (status_effects.py)
├── 混乱值机制 (stagger_manager.py)
├── 种族抗性系统 (race_management.py)
└── 状态格式化 (status_formatter.py)
```

### 设计理念

1. **角色多态性**：支持友方角色和敌方角色的不同管理方式
2. **人格切换**：核心角色可以切换不同人格，获得不同属性和技能
3. **情感成长**：通过战斗和行动积累情感硬币，提升情感等级
4. **动态状态**：丰富的状态效果系统和混乱值机制
5. **种族特性**：基于种族标签的抗性和特攻系统

---

## 👤 角色管理基础

### 角色类型

| 角色类型 | 代码 | 特点 | 管理方式 |
|---------|------|------|---------|
| 🛡️ **友方角色** | `friendly` | 玩家控制的角色 | 完整管理功能 |
| ⚔️ **敌方角色** | `enemy` | 对战的敌人 | 基础属性管理 |

### 基础属性系统

#### 生命值系统
```python
health          # 当前生命值
max_health      # 最大生命值
```

#### 战斗属性
```python
attack          # 攻击等级（影响伤害计算）
defense         # 防御等级（影响伤害减免）
physical_resistance  # 物理抗性（0.0-0.9）
magic_resistance     # 魔法抗性（0.0-0.9）
```

#### 行动系统
```python
actions_per_turn    # 每回合行动次数
current_actions     # 当前剩余行动次数
in_battle          # 是否在战斗中
```

### 创建角色

#### 创建友方角色
```
/create_character
# 系统会引导你输入角色名称
```

#### 创建敌方角色
```
/create_enemy
# 系统会引导你设置：
# 1. 角色名称
# 2. 生命值
# 3. 攻击力  
# 4. 防御力
```

### 角色信息查看

#### 查看所有角色
```
/characters     # 查看所有友方角色
/enemies       # 查看所有敌方角色
```

#### 查看角色详情
```
/show <角色名称>
/show <角色ID>
```

**显示内容包括**：
- 基础属性（生命值、攻击、防御）
- 当前人格信息（如果是核心角色）
- 混乱值状态
- 战斗状态和行动次数
- 状态效果列表
- 技能冷却状态

---

## 🎭 人格系统详解

### 支持的核心角色

| 角色名 | 可用人格数量 | 特色 |
|--------|-------------|------|
| **珏** | 多个人格 | 平衡型战士 |
| **露** | 多个人格 | 法师类型 |
| **莹** | 多个人格 | 敏捷刺客 |
| **笙** | 多个人格 | 治疗支援 |
| **曦** | 多个人格 | 坦克守护 |

### 人格系统机制

#### 人格数据结构
```python
{
    "character_name": "珏",           # 核心角色名
    "name": "剑圣",                  # 人格名称
    "description": "专精剑术的战士",   # 人格描述
    "health": 120,                   # 人格生命值
    "max_health": 120,               # 人格最大生命值
    "attack": 15,                    # 人格攻击力
    "defense": 10,                   # 人格防御力
    "physical_resistance": 0.1,       # 物理抗性
    "magic_resistance": 0.0,          # 魔法抗性
    "skills": [1, 5, 8],             # 人格专属技能
    "stagger_value": 150,            # 混乱值
    "max_stagger_value": 150         # 最大混乱值
}
```

### 人格管理命令

#### 创建核心角色
```
/create_core <角色名>
# 示例: /create_core 珏
```

#### 切换人格
```
/switch_persona
# 系统会显示交互式键盘界面：
# 1. 选择要切换人格的角色
# 2. 选择目标人格
# 3. 确认切换
```

#### 查看人格信息
```
/list_personas      # 查看所有可用人格
/core_status       # 查看所有核心角色状态
```

### 人格切换效果

人格切换时会：
1. **属性完全替换**：生命值、攻击、防御、抗性等
2. **技能组合更新**：替换为人格专属技能
3. **混乱值重置**：使用人格的混乱值配置
4. **保留情感等级**：情感系统数据不变

---

## 🎭 情感系统机制

### 情感等级系统

| 等级 | 升级所需硬币 | 解锁内容 |
|------|-------------|---------|
| **0级** | - | 基础状态 |
| **1级** | 3个硬币 | 解锁低级技能 |
| **2级** | 3个硬币 | 解锁中级技能 |
| **3级** | 5个硬币 | 解锁高级技能 |
| **4级** | 7个硬币 | 解锁大师技能 |
| **5级** | 9个硬币 | 最高等级，解锁终极技能 |

### 情感硬币获取

#### 战斗相关
```python
# 造成伤害
positive_coins = 1              # 基础奖励
if target_died:
    positive_coins += 2         # 击杀奖励

# 受到伤害  
negative_coins = 1              # 基础获得

# 治疗行为
healer_positive = 1             # 治疗者获得
target_positive = 1             # 被治疗者获得（非自愈）
```

#### 骰子相关
```python
# 大成功（骰子最大值）
positive_coins += 1

# 大失败（骰子为1）
negative_coins += 1
```

### 情感升级机制

#### 升级条件
```python
total_coins = positive_coins + negative_coins
if total_coins >= UPGRADE_REQUIREMENTS[next_level]:
    # 触发升级
    upgrade_type = "positive" if positive_coins > negative_coins else "negative"
```

#### 升级效果

**正面情感升级**：
- 获得增益类状态效果
- 强化战斗能力
- 技能冷却时间减少

**负面情感升级**：
- 获得防御类状态效果
- 提升生存能力
- 抗性增强

### 情感技能限制

某些高级技能需要特定情感等级：
```python
# 技能配置示例
{
    "required_emotion_level": 3,    # 需要3级情感等级
    # ... 其他技能属性
}
```

---

## 🌟 状态效果系统

### 增益状态 (Buffs)

| 状态 | 代码 | 效果机制 | 计算公式 |
|------|------|---------|---------|
| 💪 **强壮** | `strong` | 攻击伤害增加 | 伤害 × (1 + 层数×0.1) |
| 🫁 **呼吸法** | `breathing` | 暴击率提升 | 暴击率 + 层数×1% |
| 🛡️ **守护** | `guard` | 受到伤害减少 | 伤害 × (1 - 层数×0.1) |
| 🛡️ **护盾** | `shield` | 优先抵消护盾值 | 先扣除护盾值再扣生命值 |
| ⚡ **加速** | `haste` | 增加行动次数 | 立即获得额外行动 |
| ❄️ **冷却缩减** | `cooldown_reduction` | 技能冷却时间减少 | 所有技能冷却-强度值 |

### 减益状态 (Debuffs)

| 状态 | 代码 | 效果机制 | 计算公式 |
|------|------|---------|---------|
| 🔥 **烧伤** | `burn` | 回合结束持续伤害 | 每回合扣除强度×1点生命值 |
| ☠️ **中毒** | `poison` | 回合结束百分比伤害 | 每回合扣除强度×1%最大生命值 |
| 💥 **破裂** | `rupture` | 受到伤害增加 | 伤害 × (1 + 强度×0.1) |
| 🩸 **流血** | `bleeding` | 行动时触发伤害 | 行动时扣除强度×2点生命值 |
| 😵 **虚弱** | `weak` | 攻击伤害减少 | 伤害 × (1 - 强度×0.1) |
| 💔 **易伤** | `vulnerable` | 受到伤害大幅增加 | 伤害 × (1 + 强度×0.15) |

### 状态效果机制

#### 状态叠加规则
```python
# 相同状态效果叠加
if existing_effect:
    new_intensity = max(existing.intensity, new.intensity)  # 强度取最大值
    new_duration = existing.duration + new.duration         # 持续时间累加
    new_duration = min(new_duration, 99)                   # 最大99层
```

#### 状态处理时机

**回合开始时**：
- 处理加速效果
- 应用持续增益效果

**造成伤害时**：
- 计算强壮、虚弱等攻击修正
- 检查呼吸法暴击

**受到伤害时**：
- 应用守护、易伤等防御修正
- 处理护盾抵消

**回合结束时**：
- 处理烧伤、中毒等持续伤害
- 减少状态效果持续时间

---

## 🧠 混乱值系统

### 混乱值机制

#### 基础概念
```python
stagger_value           # 当前混乱值
max_stagger_value      # 最大混乱值  
stagger_status         # 混乱状态：'normal' 或 'staggered'
stagger_turns_remaining # 混乱剩余回合数
```

#### 混乱值扣除
```python
# 受到伤害时同时扣除等量混乱值
damage_taken = 50
stagger_reduced = 50    # 混乱值减少50点
```

#### 混乱状态触发
```python
if stagger_value <= 0 and previous_stagger > 0:
    # 进入混乱状态
    stagger_status = 'staggered'
    stagger_turns_remaining = 2     # 持续2回合
    current_actions = 0             # 清空当前行动次数
```

### 混乱状态效果

#### 混乱状态中
- **无法行动**：每回合行动次数清零
- **受伤加重**：受到200%伤害
- **持续时间**：2回合

#### 混乱恢复
```python
# 混乱状态结束时
stagger_value = max_stagger_value   # 混乱值回满
stagger_status = 'normal'           # 恢复正常状态
```

### 混乱值显示

```python
# 混乱值状态显示
def format_stagger_status():
    if stagger_status == 'staggered':
        return f"🧠 理智值: {stagger_value}/{max_stagger} (混乱中)"
    else:
        percent = stagger_value / max_stagger * 100
        if percent >= 80:
            return f"🟢 理智值: {stagger_value}/{max_stagger}"
        elif percent >= 20:
            return f"🟡 理智值: {stagger_value}/{max_stagger}"
        else:
            return f"🔴 理智值: {stagger_value}/{max_stagger} (危险！)"
```

---

## 🏷️ 种族抗性系统

### 可用种族标签

| 种族类型 | 代码 | 中文名 | 特点 |
|---------|------|--------|------|
| 🧑 **人类** | `human` | 人类 | 平衡型，无特殊抗性 |
| 🧝 **精灵** | `elf` | 精灵 | 魔法亲和，自然系 |
| ⛏️ **矮人** | `dwarf` | 矮人 | 物理抗性，工匠系 |
| 👹 **兽人** | `orc` | 兽人 | 高攻击，野蛮系 |
| 🐲 **龙族** | `dragon` | 龙族 | 高抗性，元素系 |
| 🤖 **机械** | `machine` | 机械 | 免疫某些状态 |
| 🐺 **野兽** | `beast` | 野兽 | 敏捷型，本能系 |
| 💀 **不死族** | `undead` | 不死族 | 免疫中毒等 |
| 😈 **恶魔** | `demon` | 恶魔 | 黑暗系，火焰系 |
| 👼 **天使** | `angel` | 天使 | 光明系，神圣系 |

### 抗性系统

#### 物理抗性
```python
physical_resistance = 0.3  # 物理伤害减少30%
final_damage = physical_damage * (1 - physical_resistance)
```

#### 魔法抗性
```python
magic_resistance = 0.5     # 魔法伤害减少50%
final_damage = magic_damage * (1 - magic_resistance)
```

#### 抗性设置范围
- **最小值**：0.0（无抗性）
- **最大值**：0.9（减伤90%）
- **推荐范围**：0.1-0.7

### 种族管理命令

#### 种族属性管理
```
/race <角色名>
# 交互式界面包括：
# 1. 管理种族标签（多选）
# 2. 设置物理抗性
# 3. 设置魔法抗性
```

#### 种族标签操作
- **添加种族**：点击种族名称添加到角色
- **移除种族**：再次点击已有种族进行移除
- **多种族**：角色可以拥有多个种族标签
- **种族效果**：影响特殊伤害计算和技能效果

---

## 📖 命令参考手册

### 角色创建和基础管理

| 命令 | 格式 | 功能 | 示例 |
|------|------|------|------|
| `/create_character` | `/create_character` | 创建友方角色 | 引导式创建 |
| `/create_enemy` | `/create_enemy` | 创建敌方角色 | 引导式创建 |
| `/characters` | `/characters` | 查看所有友方角色 | 简要列表 |
| `/enemies` | `/enemies` | 查看所有敌方角色 | 简要列表 |
| `/show` | `/show <角色名/ID>` | 查看角色详情 | `/show 珏` |

### 战斗状态管理

| 命令 | 格式 | 功能 | 示例 |
|------|------|------|------|
| `/join` | `/join <角色名/ID>` | 角色加入战斗 | `/join 珏` |
| `/join` | `/join all` | 所有角色加入战斗 | 批量操作 |
| `/leave` | `/leave <角色名/ID>` | 角色离开战斗 | `/leave 珏` |
| `/battle_status` | `/battle_status` | 查看战斗参与者 | 当前战况 |

### 角色属性修改

| 命令 | 格式 | 功能 | 示例 |
|------|------|------|------|
| `/health` | `/health <角色名> <数值>` | 修改生命值 | `/health 珏 100` |
| `/reset` | `/reset <角色名>` | 重置角色状态 | `/reset 珏` |
| `/reset_all` | `/reset_all` | 重置所有角色 | 批量重置 |
| `/race` | `/race <角色名>` | 种族属性管理 | `/race 珏` |

### 人格系统命令

| 命令 | 格式 | 功能 | 示例 |
|------|------|------|------|
| `/create_core` | `/create_core <角色名>` | 创建核心角色 | `/create_core 珏` |
| `/switch_persona` | `/switch_persona` | 切换人格界面 | 交互式操作 |
| `/list_personas` | `/list_personas` | 查看所有人格 | 人格列表 |
| `/core_status` | `/core_status` | 核心角色状态 | 当前人格信息 |

### 战斗辅助命令

| 命令 | 格式 | 功能 | 示例 |
|------|------|------|------|
| `/remove_all_battle` | `/remove_all_battle` | 所有角色离开战斗 | 清空战场 |
| `/help_character` | `/help_character` | 角色系统帮助 | 命令说明 |

---

## 🔧 高级管理功能

### 批量操作

#### 批量战斗管理
```python
# 所有角色加入战斗
/join all

# 清空战场
/remove_all_battle

# 批量重置
/reset_all
```

#### 角色状态批量查看
```python
# 战斗参与者总览
/battle_status

# 核心角色总览  
/core_status
```

### 状态效果高级管理

#### 自动状态处理
```python
# 回合开始时自动处理
- 情感升级检查
- 状态效果持续时间更新
- 混乱状态恢复检查
- 加速效果应用

# 回合结束时自动处理  
- 持续伤害计算
- 状态效果自然消退
- 混乱值状态更新
```

#### 状态效果显示
```python
# 完整状态显示格式
def format_character_status():
    """
    📋 珏
    【人格：剑圣】
    💚 生命值: 120/120
    🧠 理智值: 150/150
    ⚔️ 攻击等级: 15
    🛡️ 防御等级: 10
    🎯 状态: ⚔️ 战斗中
    ⚡ 行动次数: 2/2
    
    🌟 状态效果:
    💪 强壮(2) 剩余3回合
    🛡️ 守护(1) 剩余2回合
    
    ⏰ 技能冷却状态:
    所有技能可用 ✅
    """
```

### 数据持久化

#### 角色数据保存
```sql
-- 角色基础表
CREATE TABLE characters (
    id INTEGER PRIMARY KEY,
    name TEXT UNIQUE,
    health INTEGER,
    max_health INTEGER,
    attack INTEGER,
    defense INTEGER,
    character_type TEXT,
    in_battle INTEGER,
    physical_resistance REAL,
    magic_resistance REAL,
    race_tags TEXT,              -- JSON格式种族标签
    current_persona TEXT,        -- 当前人格
    emotion_level INTEGER,       -- 情感等级
    positive_emotion_coins INTEGER,
    negative_emotion_coins INTEGER,
    stagger_value INTEGER,       -- 混乱值
    max_stagger_value INTEGER,
    stagger_status TEXT,         -- 混乱状态
    status TEXT                  -- JSON格式状态数据
);

-- 状态效果表
CREATE TABLE character_status_effects (
    id INTEGER PRIMARY KEY,
    character_id INTEGER,
    effect_type TEXT,            -- buff/debuff
    effect_name TEXT,            -- 状态名称
    intensity INTEGER,           -- 强度
    duration INTEGER,            -- 持续时间
    FOREIGN KEY (character_id) REFERENCES characters(id)
);

-- 人格数据表
CREATE TABLE personas (
    id INTEGER PRIMARY KEY,
    character_name TEXT,         -- 核心角色名
    name TEXT,                   -- 人格名称
    description TEXT,
    health INTEGER,
    max_health INTEGER,
    attack INTEGER,
    defense INTEGER,
    physical_resistance REAL,
    magic_resistance REAL,
    skills TEXT,                 -- JSON格式技能列表
    stagger_value INTEGER,
    max_stagger_value INTEGER
);
```

### 错误处理和日志

#### 常见错误处理
```python
# 角色不存在
if not character:
    return "找不到指定角色"

# 数值超出范围
if health < 0:
    health = 0
elif health > max_health:
    health = max_health

# 状态冲突检查
if character['health'] <= 0 and in_battle:
    return "已倒下的角色无法加入战斗"
```

#### 系统日志
```python
logger.info(f"角色 {name} 切换人格: {old_persona} -> {new_persona}")
logger.warning(f"角色 {name} 进入混乱状态")
logger.error(f"状态效果处理失败: {error}")
```

---

## 🎮 实战使用建议

### 新手入门流程

1. **创建角色**：使用`/create_character`创建第一个角色
2. **查看状态**：使用`/show <角色名>`熟悉角色界面
3. **加入战斗**：使用`/join <角色名>`让角色参与战斗
4. **学习技能**：通过技能系统为角色添加技能
5. **进阶管理**：学习人格切换和情感系统

### 核心角色推荐

1. **选择核心角色**：推荐从珏开始，平衡的属性适合新手
2. **创建核心角色**：`/create_core 珏`
3. **切换人格**：`/switch_persona`体验不同战斗风格
4. **提升情感等级**：通过战斗积累情感硬币

### 战斗队伍配置

#### 平衡队伍
- **坦克**：曦（守护人格）+ 高防御装备
- **输出**：珏（剑圣人格）+ 攻击型技能
- **治疗**：笙（治疗人格）+ 治疗技能  
- **辅助**：露（法师人格）+ 控制技能

#### 种族配置建议
- **物理队伍**：人类、兽人、矮人组合
- **魔法队伍**：精灵、天使、恶魔组合
- **混合队伍**：龙族作为核心，搭配其他种族

### 状态效果运用

#### 增益链
1. **开局增益**：强壮 + 守护
2. **爆发期**：加速 + 呼吸法
3. **持续战**：护盾 + 冷却缩减

#### 减益控制
1. **降低输出**：虚弱 + 流血
2. **增加脆性**：易伤 + 破裂
3. **持续消耗**：烧伤 + 中毒

---

## 📚 相关文档

- **技能系统指南**：`SKILL_SYSTEM_COMPLETE_GUIDE.md`
- **战斗系统文档**：`BATTLE_SYSTEM_GUIDE.md`
- **API接口文档**：`SIMPLEBOT_API.md`
- **系统架构文档**：`SYSTEM_DOCUMENTATION.md`

---

*文档版本: v2.0*  
*最后更新: 2025年9月10日*  
*适用于: SimpleBot v2.0+*  
*作者: 系统开发团队*
