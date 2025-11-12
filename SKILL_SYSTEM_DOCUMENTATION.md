# 技能系统文档

## 概述

技能系统是SimpleBot战斗系统的核心组件之一，负责处理各种类型的技能效果、伤害计算和状态应用。系统采用模块化设计，支持多种技能类型和复杂的伤害计算公式。

## 核心类：SkillEffect

### 类结构
```python
class SkillEffect(ABC):
    def execute(self, attacker, target, skill_info):
        # 根据技能分类选择处理方式
        skill_category = skill_info.get('skill_category', 'damage')
        
        if skill_category == 'healing':
            return self.execute_healing(attacker, target, skill_info)
        elif skill_category == 'buff':
            return self.execute_buff(attacker, target, skill_info)
        # ... 其他技能类型
```

### 技能类型分类

#### 1. 伤害技能 (damage)
**功能**：对目标造成伤害

**执行流程**：
1. **计算基础伤害**
   - 解析骰子公式（如 "5+2d3"）
   - 计算追加伤害（通过效果系统）
   - 合并基础伤害和追加伤害

2. **应用攻击者状态效果修正**
   - 调用 `calculate_damage_modifiers(attacker_id, base_damage)`
   - 处理暴击、强壮等增伤效果

3. **应用目标受击状态效果**
   - 调用 `process_hit_effects(target_id, modified_damage)`
   - 处理守护、护盾等减伤效果

4. **应用最终伤害**
   - 更新目标生命值
   - 记录战斗日志

5. **处理混乱值**
   - 伤害积累可能触发混乱状态

6. **应用技能状态效果**
   - 处理技能附加的buff/debuff

7. **处理行动后效果**
   - 触发攻击者身上的行动后状态

8. **更新冷却时间**
   - 增加技能冷却计数

**返回值**：
```python
{
    'total_damage': int,      # 总伤害值
    'result_text': str,       # 战斗结果文本
    'target_health': int      # 目标剩余生命值
}
```

#### 2. 治疗技能 (healing)
**功能**：恢复目标生命值

**特点**：
- 不受攻防和抗性影响
- 可以使用骰子公式计算治疗量
- 支持自我治疗和队友治疗

#### 3. 增益技能 (buff)
**功能**：为目标添加正面状态效果

**特点**：
- 不造成伤害
- 主要用于施加buff效果
- 支持多种buff类型（强壮、守护、护盾等）

#### 4. 减益技能 (debuff)
**功能**：为目标添加负面状态效果

**特点**：
- 不造成伤害
- 主要用于施加debuff效果
- 支持多种debuff类型（虚弱、易伤、中毒等）

#### 5. 自我技能 (self)
**功能**：只对施法者生效

**特点**：
- 目标始终是施法者自己
- 常用于自我强化或特殊效果

#### 6. 范围技能 (AOE)
**功能**：对多个目标同时生效

**子类型**：
- `aoe_damage`: 对所有敌方造成伤害
- `aoe_healing`: 对所有友方进行治疗
- `aoe_buff`: 对所有友方施加增益
- `aoe_debuff`: 对所有敌方施加减益

## 伤害计算系统

### 骰子公式解析
**支持格式**：
- `"5+2d3"` → 基础值5 + 2个3面骰子
- `"1d6"` → 1个6面骰子
- `"10"` → 固定值10
- `"3d4+2"` → 3个4面骰子 + 2

**解析函数**：`parse_dice_formula(formula)`
**投掷函数**：`roll_dice(num_dice, faces)`

### 伤害修正计算

#### 1. 攻防修正
```python
def calculate_attack_defense_modifier(attacker_attack, target_defense):
    attack_defense_diff = attacker_attack - target_defense
    modifier = 1.0 + (attack_defense_diff * 0.02)  # 每差1点攻防，伤害变化2%
    return max(0.1, modifier)  # 最少造成10%伤害
```

#### 2. 种族特攻
```python
def calculate_race_bonus(special_damage_tags, target_race_tags):
    # 技能特攻标签如 {"human": 1.5, "dragon": 2.0}
    # 目标种族标签如 ["human", "warrior"]
    max_bonus = 1.0
    for race in target_race_tags:
        if race in special_damage_tags:
            bonus = special_damage_tags[race]
            max_bonus = max(max_bonus, bonus)
    return max_bonus
```

#### 3. 抗性减伤
```python
def calculate_resistance_reduction(damage_type, target_resistances):
    resistance = target_resistances.get(damage_type, 0.0)
    reduction_multiplier = 1.0 - min(resistance, 0.9)  # 最多减伤90%
    return max(0.1, reduction_multiplier)  # 最少造成10%伤害
```

#### 4. 混乱状态加成
- 混乱状态下伤害提升至200%
- 通过 `stagger_manager.get_stagger_damage_multiplier()` 计算

### 最终伤害公式
```
最终伤害 = 基础伤害 × 攻防修正 × 种族特攻 × 抗性减伤 × 混乱加成
```

### 麻痹状态处理
- 麻痹状态下骰子结果归零
- 每个麻痹层数可使一个骰子归零
- 投骰后自动减少麻痹层数

## 状态效果应用

### 技能状态效果
**函数**：`apply_skill_status_effects(attacker, target, skill_info, main_effect_value)`

**支持效果类型**：
- **buff**: 强壮、呼吸法、守护、护盾、加速等
- **debuff**: 虚弱、易伤、烧伤、中毒、破裂、流血、麻痹等
- **special**: 硬血、黑夜领域、削弱光环等

**效果配置格式**：
```json
{
  "buff": {
    "type": "strong",
    "intensity": 1,
    "duration": 3
  },
  "debuff": {
    "type": "poison",
    "intensity": 2,
    "duration": 2
  }
}
```

### AOE状态效果
**函数**：`apply_aoe_status_effects(attacker, targets, skill_info, is_friendly_skill)`

- 对所有目标统一施加状态效果
- 支持友方/敌方区分

## 自我效果处理

### 自我伤害/治疗
**函数**：`apply_self_effects(attacker, skill_info, effect_value, skill_type)`

- 基于技能效果值计算自我影响
- 支持百分比计算（如伤害的10%作为自我伤害）

## 冷却系统

### 冷却时间管理
**更新函数**：`update_character_cooldowns(character_id, skill_id)`
- 技能使用后增加冷却计数
- 每回合结束减少所有技能冷却时间

**检查函数**：
- `is_skill_on_cooldown(character_id, skill_id)`
- `get_skill_cooldown_remaining(character_id, skill_id)`

## 情感硬币系统集成

### 骰子情感硬币
- 投掷结果为1：获得负面情感硬币
- 投掷结果为最大值：获得正面情感硬币

### 伤害相关情感硬币
- 造成伤害时获得情感硬币
- 击杀目标时获得额外情感硬币

### 治疗相关情感硬币
- 进行治疗时获得情感硬币

## 特殊效果集成

### 效果管理器
- `effect_integration_manager.calculate_unified_damage()`
- 处理复杂的技能追加伤害和特殊效果

### 目标解析器
- `target_resolver.resolve_target()`
- 支持多种目标选择逻辑（自身、技能目标、友方等）

## 使用示例

```python
from skill.skill_effects import skill_registry

# 执行伤害技能
result = skill_registry.execute(attacker, target, skill_info)
print(f"造成 {result['total_damage']} 点伤害")
print(result['result_text'])

# 计算伤害（不执行效果）
damage = calculate_advanced_damage(skill, attacker, target)
print(f"预估伤害: {damage[0]}")
```

## 扩展性设计

### 新技能类型添加
1. 在 `SkillEffect.execute()` 中添加新的 `elif` 分支
2. 实现对应的 `execute_new_type()` 方法
3. 更新技能数据库中的 `skill_category` 字段

### 新状态效果添加
1. 在 `status_effects.py` 中添加效果处理逻辑
2. 在技能效果配置中添加新的效果类型
3. 更新显示名称映射

### 新伤害修正添加
1. 在 `damage_calculator.py` 中添加新的修正函数
2. 在 `calculate_advanced_damage_modular()` 中集成新的修正
3. 更新伤害详情显示逻辑</content>
<parameter name="filePath">e:\PythonWorkspace\NewBot\SKILL_SYSTEM_DOCUMENTATION.md