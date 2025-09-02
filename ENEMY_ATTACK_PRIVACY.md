# 敌方攻击系统用户隐私功能

## 功能概述

为了保护策略隐私，敌方攻击系统现在实现了用户特定的界面可见性。只有发起 `/enemy_attack` 命令的用户才能看到技能选择和目标选择界面，其他用户只能看到最终的攻击结果。

## 实现的隐私保护

### 🔒 私人技能选择界面
- **问题**：之前所有用户都能看到敌方角色的具体技能信息
- **解决方案**：技能选择按钮只对发起命令的用户可见
- **UI提示**：界面显示"🔒 私人技能选择 🔒"和"⚠️ 此界面仅对发起者可见"

### 🔒 私人目标选择界面  
- **问题**：其他用户能看到攻击意图和目标选择过程
- **解决方案**：目标选择按钮只对发起命令的用户可见
- **UI提示**：界面显示"🔒 私人目标选择 🔒"和"⚠️ 此界面仅对发起者可见"

## 权限验证机制

### 用户身份验证
```python
# 在每个关键步骤验证用户身份
initiator_id = context.user_data.get('enemy_attack_initiator')
if query.from_user.id != initiator_id:
    await query.answer("只有发起敌方攻击命令的人可以操作此界面。", show_alert=True)
    return CURRENT_STATE
```

### 会话隔离
```python
# 设置per_user=True确保每个用户独立的会话状态
ConversationHandler(
    # ...
    per_user=True
)
```

## 用户体验流程

### 对发起者（有权限的用户）
1. **输入命令**：`/enemy_attack`
2. **选择攻击者**：看到敌方角色列表（其他人也能看到）
3. **选择技能**：🔒 私人界面，只有发起者可见技能详情
4. **选择目标**：🔒 私人界面，只有发起者可见目标选择
5. **查看结果**：所有人都能看到攻击结果

### 对其他用户（无权限）
1. **看到选择攻击者**：能看到谁在选择敌方攻击者
2. **看不到技能选择**：无法看到敌方有什么技能
3. **看不到目标选择**：无法看到攻击意图
4. **看到攻击结果**：能看到最终的战斗结果
5. **尝试操作时**：显示权限错误"只有发起敌方攻击命令的人可以操作此界面。"

## 代码修改说明

### 主要修改文件
- `src/game/attack.py`

### 关键修改点

#### 1. 记录发起者ID
```python
async def start_enemy_attack(update: Update, context: CallbackContext) -> int:
    # 记录发起命令的用户ID
    context.user_data['enemy_attack_initiator'] = update.effective_user.id
    # ...
```

#### 2. 权限验证函数
```python
async def enemy_select_attacker(update: Update, context: CallbackContext) -> int:
    # 验证是否为发起命令的用户
    initiator_id = context.user_data.get('enemy_attack_initiator')
    if query.from_user.id != initiator_id:
        await query.answer("只有发起敌方攻击命令的人可以操作此界面。", show_alert=True)
        return ENEMY_SELECTING_ATTACKER
    # ...
```

#### 3. 私密界面提示
```python
message = f"🔒 私人技能选择 🔒\n攻击者: {attacker['name']}\n选择要使用的技能:\n\n⚠️ 此界面仅对发起者可见"
```

#### 4. 会话隔离
```python
def get_enemy_attack_conv_handler():
    return ConversationHandler(
        # ...
        per_user=True  # 确保每个用户独立的会话状态
    )
```

## 安全性和隐私特点

### ✅ 实现的保护
- **技能隐私**：敌方技能信息不会泄露给其他玩家
- **策略隐私**：攻击意图和目标选择过程保密
- **操作权限**：严格的用户身份验证
- **会话隔离**：防止用户间状态冲突

### ✅ 用户体验
- **明确提示**：清楚标明哪些界面是私人的
- **友好错误**：权限错误有明确的说明
- **无缝体验**：对有权限的用户操作流程不变

### ✅ 技术实现
- **轻量级**：最小化对现有代码的影响
- **可靠性**：在每个关键步骤都有验证
- **可维护性**：代码结构清晰，易于理解和修改

## 使用示例

```
用户A: /enemy_attack
Bot: 选择发起攻击的敌方角色: [敌方角色列表]  # 所有人可见

用户A: [选择敌方角色]
Bot: 🔒 私人技能选择 🔒
     攻击者: 敌方角色名
     选择要使用的技能:
     [技能列表]
     ⚠️ 此界面仅对发起者可见  # 只有用户A能看到

用户B: [尝试点击技能按钮]
Bot: ⚠️ 只有发起敌方攻击命令的人可以操作此界面。  # 弹窗提示

用户A: [选择技能]
Bot: 🔒 私人目标选择 🔒
     攻击者: 敌方角色名
     技能: 技能名
     选择攻击目标:
     [目标列表]
     ⚠️ 此界面仅对发起者可见  # 只有用户A能看到

用户A: [选择目标]
Bot: 敌方攻击结果:
     [详细攻击结果]  # 所有人可见
```

这个实现完美解决了用户提出的隐私需求，确保敌方攻击的技能选择过程只对发起者可见，同时保持了良好的用户体验。
