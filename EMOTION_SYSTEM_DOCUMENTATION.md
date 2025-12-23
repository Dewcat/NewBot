# 情感系统文档

## 概述

情感系统是Dewbot战斗中的**短期成长机制**，属于**战斗会话（Battle Session）**属性。角色通过在战斗中的表现获得情感硬币，提升情感等级，解锁更强大的技能和获得特殊效果。情感等级仅在当前战斗会话中有效，战斗结束后将重置，并非长期的RPG角色成长属性。

## 核心类：EmotionSystem

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

## 情感硬币系统

### 硬币保留与重置规则
*   **战斗结束 (Battle End)**：所有的情感硬币和情感等级都会**重置为 0**。
*   **阶段结束 (Stage End)**：情感硬币和情感等级会被**保留**，延续到下一阶段的战斗中。

### 硬币获取来源

#### 1. 骰子投掷结果
**函数**：`get_emotion_coins_from_dice_roll(dice_results, dice_sides)`

**规则**：
- **正面硬币**：投掷结果等于骰子最大值时获得
- **负面硬币**：投掷结果等于1时获得

**示例**：
- 投掷3d6得到[1,3,6] → 获得1个负面硬币 + 1个正面硬币
- 投掷2d4得到[2,4] → 获得1个正面硬币

#### 2. 伤害相关
- 造成伤害时获得情感硬币
- 击杀目标时获得额外情感硬币

#### 3. 治疗相关
- 进行治疗时获得情感硬币

### 硬币添加流程

#### 函数：`add_emotion_coins(character_id, positive_coins, negative_coins, source)`

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

## 情感等级升级

### 升级触发时机
- 在回合开始时自动处理
- 通过 `process_turn_start_emotion_upgrades()` 函数执行

### 升级流程

#### 函数：`_execute_emotion_upgrade(character_id, name, current_level, pos_coins, neg_coins)`

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

## 情感效果应用

### 回合开始效果
**函数**：`apply_turn_start_emotion_effects(character_id)`

**执行流程**：
1. 查询角色的情感效果（从 `character_emotion_effects` 表）
2. 为每个效果添加对应的状态效果
3. 持续时间为1回合（每回合刷新）

**支持效果**：
- `strong`: 强壮状态 (获得 `intensity` 层)
- `guard`: 守护状态 (获得 `intensity` 层)

### 效果存储
- 存储在 `character_emotion_effects` 表中
- 包含效果类型、名称、强度

## 技能等级要求

### 检查函数：`check_skill_emotion_requirement(character_id, skill_info)`

**逻辑**：
1. 检查技能是否设置了 `required_emotion_level`
2. 比较角色当前情感等级
3. 返回是否满足要求及错误信息

**使用场景**：
- 技能选择时检查
- 防止低等级角色使用高级技能

## 数据库表结构

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

## 情感等级详情

| 等级 | 升级所需硬币 | 累计硬币需求 | 解锁内容 |
|------|-------------|-------------|----------|
| 1 | 3 | 3 | 基础技能解锁 |
| 2 | 3 | 6 | 中级技能解锁 |
| 3 | 5 | 11 | 高级技能解锁 |
| 4 | 7 | 18 | 专家技能解锁 |
| 5 | 9 | 27 | 顶级技能解锁 |

## 便捷函数

系统提供了一系列便捷函数用于外部调用：

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

## 扩展性设计

### 添加新升级效果
1. 在 `POSITIVE_EMOTION_EFFECTS` 或 `NEGATIVE_EMOTION_EFFECTS` 中添加效果配置
2. 效果配置格式：
```python
{
    'type': 'buff',
    'name': 'strong',
    'intensity': 1,
    'description': '每回合开始时获得1级强壮'
}
```

### 修改升级需求
- 在 `UPGRADE_REQUIREMENTS` 字典中调整各等级所需硬币数

### 添加新情感效果类型
1. 在 `apply_turn_start_emotion_effects()` 中添加新的效果处理逻辑
2. 更新效果名称映射字典

## 异常处理

系统包含完善的异常处理机制：
- 数据库操作异常时记录错误日志
- 角色不存在时返回失败状态
- 硬币添加失败时回滚事务
- 效果应用失败时跳过继续执行

## 调试和监控

### 日志记录
- 硬币添加操作记录
- 升级过程记录
- 效果应用记录
- 异常情况记录

### 数据验证
- 硬币数量非负数检查
- 等级范围验证（0-5级）
- 效果配置有效性检查</content>
<parameter name="filePath">e:\PythonWorkspace\NewBot\EMOTION_SYSTEM_DOCUMENTATION.md