# 攻击逻辑文档

## 概述

攻击逻辑是Dewbot战斗系统的核心交互组件，负责处理玩家发起的攻击命令，包括友方攻击（`/attack`）和敌方攻击（`/enemy`）。系统采用对话式交互，通过Telegram的内联键盘引导用户完成攻击流程。

## 核心流程

### 友方攻击流程 (`/attack`)

#### 1. 选择攻击者 (`start_attack`)
**功能**：开始友方攻击流程，显示可用的攻击者

**执行流程**：
1. **获取有行动次数的友方角色**
   - 调用 `get_characters_with_actions("friendly")`
   - 只显示 `current_actions > 0` 的角色

2. **验证可用性**
   - 如果没有可用角色，提示用户结束回合

3. **创建选择键盘**
   - 显示角色名称
   - 格式：`[角色名]`

4. **状态转换**
   - 返回 `SELECTING_ATTACKER`

#### 2. 处理攻击者选择 (`select_attacker`)
**功能**：处理用户选择的攻击者

**执行流程**：
1. **解析选择**
   - 从回调数据提取角色ID：`attacker_{id}`

2. **验证角色**
   - 检查角色是否存在
   - 确认角色有行动次数

3. **获取技能列表**
   - 调用 `get_character_skills(attacker_id)`
   - 过滤冷却中的技能
   - 检查情感等级要求

4. **技能选择界面**
   - 如果有可用技能，显示技能选择键盘
   - 如果没有技能，使用普通攻击
   - 技能显示格式：`[技能名] ([伤害公式]) [图标]`

**技能图标说明**：
- ⚔️ 伤害技能 (Damage)
- 💚 治疗技能 (Healing)
- ✨ 增益技能 (Buff)
- 💀 减益技能 (Debuff)
- 🧘 自我技能 (Self)
- 🌀 AOE技能 (Area of Effect)

#### 3. 处理技能选择 (`select_skill`)
**功能**：处理用户选择的技能

**执行流程**：
1. **解析选择**
   - 从回调数据提取技能ID：`skill_{id}`

2. **验证技能状态**
   - 检查冷却状态
   - 检查情感等级要求
   - 获取技能详细信息

3. **存储选择**
   - 保存 `skill_id` 和 `skill_info` 到上下文

4. **进入目标选择**
   - 调用 `show_target_selection()`

#### 4. 显示目标选择 (`show_target_selection`)
**功能**：根据技能类型显示相应的目标选择界面

**技能类型判断**：
```python
skill_category = skill_info.get('skill_category', 'damage')
is_heal_skill = (skill_category == 'healing')
is_buff_skill = (skill_category == 'buff')
is_debuff_skill = (skill_category == 'debuff')
is_self_skill = (skill_category == 'self')
is_aoe_skill = skill_category.startswith('aoe_')
```

**特殊处理**：
- **自我技能**：直接对自己使用，无需目标选择
- **AOE技能**：直接执行，无需目标选择

**目标选择逻辑**：
- **治疗/增益技能**：选择友方角色
- **减益技能**：选择敌方角色
- **伤害技能**：选择敌方角色

**目标显示格式**：
```
[角色名] ([当前生命]/[最大生命]) [状态图标]
```

**状态图标**：
- 💀 已死亡 (Dead)
- 💚 80%+ 生命 (Healthy)
- 💛 50-79% 生命 (Injured)
- 🧡 20-49% 生命 (Wounded)
- ❤️ <20% 生命 (Critical)

#### 5. 处理目标选择 (`select_target`)
**功能**：处理用户选择的目标并执行攻击

**执行流程**：
1. **解析选择**
   - 从回调数据提取目标ID：`target_{id}`

2. **存储选择**
   - 保存 `target_id` 到上下文

3. **执行攻击**
   - 调用 `execute_attack()`

#### 6. 执行攻击 (`execute_attack`)
**功能**：最终执行攻击逻辑

**验证流程**：
1. **验证角色状态**
   - 检查攻击者和目标是否存在
   - 确认都在战斗中
   - 检查攻击者生命值 > 0

2. **验证技能状态**
   - 检查技能是否存在
   - 确认不在冷却中

3. **执行技能效果**
   - 调用 `execute_skill_effect()`

4. **消耗行动次数**
   - 调用 `use_character_action(attacker_id)`

5. **返回结果**
   - 显示战斗结果消息

### 敌方攻击流程 (`/enemy`)

敌方攻击流程与友方攻击类似，但有一些差异：

#### 主要差异：
1. **目标选择相反**
   - 治疗/增益技能选择敌方
   - 减益技能选择友方
   - 伤害技能选择友方

2. **权限控制**
   - 只有发起命令的用户可以操作界面
   - 使用 `context.user_data['enemy_attack_initiator']` 验证

3. **技能显示方式**
   - 技能按钮只显示编号
   - 技能详细信息通过弹窗显示

## 技能效果执行

### 函数：`execute_skill_effect(attacker, target, skill_info)`

**功能**：执行技能效果并生成结果消息

**消息格式化**：
- 根据技能类型显示不同标题和图标
- 显示攻击者、技能名、目标
- 调用技能效果系统执行具体逻辑
- 显示战斗结果和状态变化

**技能类型标题映射**：
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

## 会话处理器

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

## 验证机制

### 角色状态验证
- **存在性检查**：确保角色在数据库中存在
- **战斗状态**：`in_battle = True`
- **生命值**：`health > 0`
- **行动次数**：`current_actions > 0`

### 技能状态验证
- **冷却检查**：通过 `is_skill_on_cooldown()`
- **情感等级**：通过 `check_skill_emotion_requirement()`
- **存在性**：确保技能在数据库中存在

### 用户权限验证（敌方攻击）
- **发起者检查**：只有命令发起者可以操作
- **会话隔离**：`per_user=True` 确保用户间独立

## 错误处理

### 常见错误场景
1. **无可用角色**：提示结束回合
2. **技能冷却中**：显示剩余冷却时间
3. **情感等级不足**：显示等级要求
4. **无有效目标**：根据技能类型提示
5. **角色死亡**：阻止死亡角色行动

### 错误消息格式
- 清晰描述问题
- 提供解决建议
- 保持用户友好

## 回调数据格式

### 友方攻击
- `attacker_{角色ID}`：选择攻击者
- `skill_{技能ID}`：选择技能
- `target_{角色ID}`：选择目标

### 敌方攻击
- `enemy_attacker_{角色ID}`：选择敌方攻击者
- `enemy_skill_{技能ID}`：选择敌方技能
- `enemy_target_{角色ID}`：选择敌方目标

## 上下文数据管理

### 存储的数据
```python
context.user_data = {
    # 友方攻击
    'attacker_id': int,
    'skill_id': int or None,
    'skill_info': dict or None,
    'target_id': int,
    
    # 敌方攻击
    'enemy_attack_initiator': int,  # 用户ID
    'original_chat_id': int,        # 群组ID
    'enemy_attacker_id': int,
    'enemy_skill_id': int,
    'enemy_skill_info': dict,
    'available_skills': list        # 技能列表
}
```

## 流程图

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

```
敌方攻击 (/enemy)
    ↓
选择攻击者 (有行动次数的敌方)
    ↓
选择技能 (编号显示，弹窗详情)
    ↓
根据技能类型选择目标 (友方)
    ↓
执行技能效果
    ↓
消耗行动次数
    ↓
显示结果
```

## 扩展性设计

### 添加新技能类型
1. 在 `show_target_selection()` 中添加类型判断
2. 更新目标选择逻辑
3. 在 `execute_skill_effect()` 中添加消息格式
4. 更新技能图标映射

### 添加新验证逻辑
1. 在相关函数中添加验证步骤
2. 更新错误消息
3. 保持向后兼容

### 自定义UI显示
1. 修改键盘创建逻辑
2. 更新消息格式化
3. 保持数据结构一致

## 性能考虑

### 数据库查询优化
- 批量获取角色信息
- 缓存技能数据
- 减少重复查询

### 会话管理
- 合理的超时设置
- 及时清理上下文数据
- 防止内存泄漏

### 用户体验
- 清晰的状态反馈
- 直观的操作流程
- 详细的错误提示

## 战斗结束交互 (Combat Termination Interaction)

虽然攻击逻辑主要处理单次行动，但攻击结果（如击杀最后一个敌人）可能触发战斗结束流程。

*   **检查时机**：通常在 `execute_attack` 完成后，或者在回合结束检查时。
*   **状态处理**：如果触发 **Stage End** 或 **Battle End**，系统将根据 `TURN_SYSTEM_DOCUMENTATION.md` 中定义的规则处理状态重置（如情感系统、混乱值等）。
    *   **Stage End**：保留情感等级/硬币，移除所有战斗状态 (`in_battle = False`)，清除所有状态效果 (Buff/Debuff)，重置混乱值 (Stagger)。
    *   **Battle End**：重置情感等级/硬币，移除所有战斗状态 (`in_battle = False`)，清除所有状态效果 (Buff/Debuff)，重置混乱值 (Stagger)。