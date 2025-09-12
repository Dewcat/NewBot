# 重置系统和情感升级效果更新

## 更新内容

### 1. 情感升级效果禁用
- **文件**: `src/character/emotion_system.py`
- **更改**: 
  - 禁用了正面和负面情感升级效果池（强壮和守护增益）
  - 修改了升级逻辑，当效果池为空时不添加增益效果
  - 更新了升级消息，显示"升级效果已暂时禁用"

### 2. 重置系统增强
- **文件**: `src/database/queries.py`
- **更改**:
  - `reset_character()`: 增加了情感系统重置功能
    - 重置 `emotion_level` 为 0
    - 重置 `positive_emotion_coins` 为 0  
    - 重置 `negative_emotion_coins` 为 0
    - 重置 `pending_emotion_upgrade` 为 0
    - 清除 `character_emotion_effects` 表中的所有情感效果
  
  - `reset_all_characters()`: 同样增加了情感系统重置功能
    - 批量重置所有角色的情感相关字段
    - 清除所有角色的情感效果

### 3. 帮助文档更新
- **文件**: `src/main.py`, `src/character/character_management.py`
- **更改**: 更新了reset命令的说明，明确包含情感系统重置

### 4. 数据库字段补充
- **字段**: `pending_emotion_upgrade`
- **说明**: 添加了缺失的字段来支持情感升级待处理状态

## 功能验证

✅ **情感升级效果已成功禁用**
- 正面效果池长度: 0
- 负面效果池长度: 0
- 升级时显示"升级效果已暂时禁用"消息

✅ **重置功能正常工作**
- 单个角色重置：正确重置情感等级、硬币和生命值
- 全体角色重置：正确重置所有角色状态

✅ **向后兼容性**
- 现有功能继续正常工作
- 技能冷却减少功能保持不变
- 其他系统不受影响

## 使用说明

- `/reset <角色名>` - 重置单个角色的所有状态（包括情感系统）
- `/reset_all` - 重置所有角色的状态（包括情感系统）
- 情感升级仍然会提升等级并减少技能冷却，但暂时不会添加强壮/守护增益效果

## 恢复增益效果

如需恢复情感升级的增益效果，可以在 `src/character/emotion_system.py` 中取消注释效果池中的内容：

```python
# 正面情感升级效果池
POSITIVE_EMOTION_EFFECTS = [
    {
        'type': 'buff',
        'name': 'strong',
        'intensity': 1,
        'description': '每回合开始时获得1级强壮'
    }
]

# 负面情感升级效果池  
NEGATIVE_EMOTION_EFFECTS = [
    {
        'type': 'buff',
        'name': 'guard',
        'intensity': 1,
        'description': '每回合开始时获得1级守护'
    }
]
```
