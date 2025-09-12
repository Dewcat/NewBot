# 兽之数技能黑夜领域条件判断修复

## 问题描述

在使用米拉库尔的兽之数技能时，当检查黑夜领域增伤条件时会出现 `AttributeError` 错误：

```
AttributeError: 'StatusEffect' object has no attribute 'get'
```

## 错误原因

问题出现在 `src/skill/skill_effects.py` 文件的 `_check_conditional_damage_condition` 方法中：

```python
# 错误的代码
return any(effect.get('name') == '黑夜领域' for effect in status_effects)
```

`get_character_status_effects` 函数返回的是 `StatusEffect` 对象列表，而不是字典列表。`StatusEffect` 对象没有 `get` 方法，只有直接的属性访问。

## 修复方案

将错误的 `effect.get('name')` 改为正确的 `effect.effect_name`：

```python
# 修复后的代码
return any(effect.effect_name == '黑夜领域' for effect in status_effects)
```

## 修复文件

- **文件**: `src/skill/skill_effects.py`
- **行数**: 1748
- **方法**: `_check_conditional_damage_condition`

## StatusEffect 对象结构

`StatusEffect` 类的属性：
- `effect_type`: 效果类型（buff/debuff）
- `effect_name`: 效果名称
- `intensity`: 强度
- `duration`: 持续回合数

## 测试验证

修复后的代码已通过语法检查，兽之数技能的黑夜领域条件判断现在能够正常工作：

1. ✅ 当角色没有黑夜领域状态时，条件返回 `False`
2. ✅ 当角色有黑夜领域状态时，条件返回 `True`
3. ✅ 不再出现 `AttributeError` 异常

## 相关技能

此修复影响所有使用 `self_has_dark_domain` 条件的技能，主要是：
- 米拉库尔的兽之数技能（在黑夜领域状态下增加伤害）

## 预防措施

为了避免类似问题，在使用 `get_character_status_effects` 函数时，应该记住它返回的是 `StatusEffect` 对象，需要使用点号访问属性：
- `effect.effect_name` - 效果名称
- `effect.effect_type` - 效果类型  
- `effect.intensity` - 强度
- `effect.duration` - 持续时间
