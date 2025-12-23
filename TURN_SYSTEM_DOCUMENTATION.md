# 回合系统文档

## 概述

回合系统是Dewbot战斗系统的核心组件，负责管理战斗的回合流程、状态效果处理和角色状态更新。系统采用回合制设计，每个角色在回合内有固定数量的行动次数。

## 战斗终止概念 (Combat Termination Concepts)

为了支持连续战斗和正确的状态继承，系统定义了三种不同层级的“结束”状态：

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

## 核心类：TurnManager

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
**功能**：执行“战斗结束 (Battle End)”逻辑，完全重置战斗状态

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

**执行流程**：
1. 查询角色的 `actions_per_turn` 值
2. 更新角色当前行动次数为此值

#### 6. _process_emotion_turn_start(character_id: int) -> List[str]
**功能**：处理角色回合开始时的情感系统回合开始效果

**执行流程**：
1. 调用 `apply_emotion_effects(character_id)`
2. 返回情感效果应用结果消息

#### 7. process_all_emotion_upgrades() -> List[str]
**功能**：处理所有角色的情感升级

**执行流程**：
1. 调用情感系统的 `process_emotion_upgrades()`
2. 返回升级结果消息

## 回合流程图

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

## 状态效果处理顺序

### 单个角色回合结束顺序：
1. 回合结束效果（中毒、持续伤害等）
2. 死亡检查
3. 混乱值处理
4. 行动次数恢复
5. 情感系统效果

### 全局回合结束顺序：
1. 回合计数+1
2. 所有角色回合结束处理
3. 行动次数恢复（静默）
4. 回合开始效果（加速等）

## 相关系统集成

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

## 异常处理

系统包含完善的异常处理机制：
- 角色不存在时返回空列表
- 情感系统处理异常时记录错误日志
- 数据库操作异常时记录错误但不中断流程

## 使用示例

```python
from game.turn_manager import turn_manager

# 结束整个战斗回合
messages = turn_manager.end_battle_turn()
for message in messages:
    print(message)

# 结束单个角色回合
character_messages = turn_manager.end_turn_for_character(1)
print(f"角色1的状态变化: {character_messages}")

# 获取当前回合数
current_turn = turn_manager.get_current_turn()
print(f"当前回合: {current_turn}")
```