# SimpleBot API文档

## 核心模块API说明

### 1. Character Management API

#### `character/character_management.py`

##### 主要函数

```python
def get_character_by_name(name: str) -> dict:
    """根据名称获取角色信息"""
    
def create_character(name: str, character_type: str, max_health: int, 
                    attack: int, defense: int, magic_attack: int, 
                    magic_defense: int) -> bool:
    """创建新角色"""
    
def update_character_health(character_id: int, new_health: int) -> bool:
    """更新角色生命值"""
    
def reset_character_status(character_id: int) -> bool:
    """重置角色所有状态"""
    
def get_characters_by_type(character_type: str, in_battle: bool = None) -> list:
    """获取指定类型的角色列表"""
```

##### 使用示例

```python
from character.character_management import get_character_by_name

# 获取角色信息
character = get_character_by_name("艾丽丝")
if character:
    print(f"角色生命值: {character['health']}/{character['max_health']}")
```

### 2. Skill System API

#### `skill/skill_effects.py`

##### 核心类：DefaultSkillEffect

```python
class DefaultSkillEffect(SkillEffect):
    def execute(self, attacker: dict, target: dict, skill_info: dict) -> dict:
        """执行技能效果"""
        
    def apply_skill_status_effects(self, attacker: dict, target: dict, 
                                 skill_info: dict, main_effect_value: int = 0) -> list:
        """应用技能的次要状态效果"""
        
    def _calculate_effect_amount(self, effect_config: dict, 
                               main_effect_value: int, effect_type: str) -> int:
        """计算效果数值（支持百分比）"""
```

##### 技能分类执行方法

```python
def execute_aoe_damage(self, attacker: dict, target: dict, skill_info: dict) -> dict:
    """执行AOE伤害技能"""
    
def execute_aoe_healing(self, attacker: dict, target: dict, skill_info: dict) -> dict:
    """执行AOE治疗技能"""
    
def execute_aoe_buff(self, attacker: dict, target: dict, skill_info: dict) -> dict:
    """执行AOE增益技能"""
    
def execute_aoe_debuff(self, attacker: dict, target: dict, skill_info: dict) -> dict:
    """执行AOE减益技能"""
```

##### 返回值格式

所有技能执行方法返回统一格式：
```python
{
    'total_damage': int,      # 造成的总伤害（负数表示治疗）
    'result_text': str,       # 战斗结果描述文本
    'target_health': int      # 目标剩余生命值
}
```

### 3. Status Effects API

#### `character/status_effects.py`

##### StatusEffect类

```python
class StatusEffect:
    @classmethod
    def from_db_row(cls, row):
        """从数据库记录创建状态效果对象"""
        
    def apply_turn_start_effect(self, character_id: int):
        """应用回合开始时的效果"""
        
    def apply_turn_end_effect(self, character_id: int):
        """应用回合结束时的效果"""
        
    def apply_on_hit_effect(self, character_id: int, incoming_damage: int):
        """应用受击时的效果"""
```

##### 状态效果管理函数

```python
def add_status_effect(character_id: int, effect_type: str, 
                     effect_name: str, intensity: int, duration: int) -> bool:
    """添加状态效果"""
    
def remove_status_effect(character_id: int, effect_type: str, 
                        effect_name: str) -> bool:
    """移除状态效果"""
    
def get_character_status_effects(character_id: int) -> list:
    """获取角色的所有状态效果"""
    
def process_turn_end_effects(character_id: int) -> list:
    """处理回合结束时的状态效果"""
```

### 4. Database API

#### `database/queries.py`

##### 角色查询

```python
def get_character_by_id(character_id: int) -> dict:
    """根据ID获取角色"""
    
def get_character_by_name(name: str) -> dict:
    """根据名称获取角色"""
    
def get_characters_by_type(character_type: str, in_battle: bool = None) -> list:
    """获取指定类型的角色"""
    
def update_character_health(character_id: int, new_health: int) -> bool:
    """更新角色生命值"""
```

##### 技能查询

```python
def get_character_skills(character_id: int) -> list:
    """获取角色的技能列表"""
    
def get_skill_by_id(skill_id: int) -> dict:
    """根据ID获取技能"""
    
def add_skill_to_character(character_id: int, skill_id: int) -> bool:
    """为角色添加技能"""
    
def remove_skill_from_character(character_id: int, skill_id: int) -> bool:
    """移除角色技能"""
```

##### 战斗相关

```python
def set_battle_status(character_id: int, in_battle: bool) -> bool:
    """设置角色战斗状态"""
    
def get_battle_participants() -> dict:
    """获取所有战斗参与者"""
    
def record_battle(attacker_id: int, target_id: int, damage: int, skill_id: int):
    """记录战斗日志"""
```

### 5. Target Resolution API

#### `skill/effect_target_resolver.py`

##### EffectTargetResolver类

```python
class EffectTargetResolver:
    def resolve_target(self, target_type: str, attacker: dict, 
                      skill_target: dict = None) -> list:
        """解析目标类型，返回目标列表"""
        
    def get_all_allies(self, character: dict) -> list:
        """获取所有友军"""
        
    def get_all_enemies(self, character: dict) -> list:
        """获取所有敌军"""
```

##### 支持的目标类型

```python
TARGET_TYPES = {
    'self': '施法者自己',
    'skill_target': '技能选中的目标',
    'attacker': '施法者（同self）',
    'all_allies': '所有友方角色',
    'all_enemies': '所有敌方角色',
    'friendly': '所有友方角色',
    'enemy': '所有敌方角色'
}
```

### 6. Battle System API

#### `game/attack.py`

##### 主要函数

```python
def show_target_selection(update, context, attacker, available_skills):
    """显示目标选择界面"""
    
def execute_skill_effect(update, context, attacker, target, skill_info):
    """执行技能效果"""
    
def get_attack_conv_handler():
    """获取攻击对话处理器"""
    
def get_enemy_attack_conv_handler():
    """获取敌方攻击对话处理器"""
```

#### `game/damage_calculator.py`

##### 伤害计算函数

```python
def calculate_damage(attacker: dict, target: dict, skill_info: dict) -> dict:
    """计算技能伤害"""
    
def calculate_healing(attacker: dict, skill_info: dict) -> int:
    """计算治疗量"""
    
def apply_resistance(damage: int, resistance: float) -> int:
    """应用抗性减伤"""
```

### 7. 扩展开发指南

#### 添加新的技能分类

1. 在`skill_effects.py`中添加新的执行方法：
```python
def execute_new_skill_type(self, attacker, target, skill_info):
    # 实现新技能类型的逻辑
    return {
        'total_damage': 0,
        'result_text': '技能效果描述',
        'target_health': target['health']
    }
```

2. 在`execute`方法中添加分支：
```python
elif skill_category == 'new_skill_type':
    return self.execute_new_skill_type(attacker, target, skill_info)
```

#### 添加新的状态效果

1. 在`status_effects.py`中添加效果处理：
```python
def apply_new_effect_turn_end(character_id, intensity):
    """新状态效果的回合结束处理"""
    # 实现具体逻辑
    pass
```

2. 在相应的处理函数中添加分支：
```python
elif effect_name == 'new_effect':
    return apply_new_effect_turn_end(character_id, intensity)
```

#### 添加新的目标类型

在`effect_target_resolver.py`中的`resolve_target`方法添加新的目标类型：
```python
elif target_type == 'new_target_type':
    return self.get_new_target_type(character)
```

### 8. 数据结构说明

#### 角色对象结构

```python
character = {
    'id': int,                    # 角色ID
    'name': str,                  # 角色名称
    'character_type': str,        # 'friendly' 或 'enemy'
    'health': int,                # 当前生命值
    'max_health': int,            # 最大生命值
    'attack': int,                # 物理攻击力
    'defense': int,               # 物理防御力
    'magic_attack': int,          # 魔法攻击力
    'magic_defense': int,         # 魔法防御力
    'in_battle': int,             # 是否在战斗中 (0/1)
    'actions_left': int,          # 剩余行动次数
    'actions_per_turn': int,      # 每回合行动次数
    'race': str,                  # 种族标签
    'physical_resistance': float, # 物理抗性 (0-1)
    'magic_resistance': float     # 魔法抗性 (0-1)
}
```

#### 技能对象结构

```python
skill = {
    'id': int,                    # 技能ID
    'name': str,                  # 技能名称
    'skill_category': str,        # 技能分类
    'description': str,           # 技能描述
    'damage_formula': str,        # 伤害公式
    'damage_type': str,           # 伤害类型
    'effects': str,               # 次要效果JSON
    'target_races': str,          # 特攻种族JSON
    'cooldown': int               # 冷却时间
}
```

#### 状态效果对象结构

```python
status_effect = {
    'id': int,                    # 状态效果ID
    'character_id': int,          # 角色ID
    'effect_type': str,           # 'buff' 或 'debuff'
    'effect_name': str,           # 效果名称
    'intensity': int,             # 效果强度
    'duration': int               # 持续时间
}
```

### 9. 错误处理最佳实践

#### 异常类型

```python
# 自定义异常
class SkillExecutionError(Exception):
    """技能执行错误"""
    pass

class CharacterNotFoundError(Exception):
    """角色不存在错误"""
    pass

class InsufficientActionsError(Exception):
    """行动次数不足错误"""
    pass
```

#### 错误处理示例

```python
try:
    result = execute_skill(attacker, target, skill)
except SkillExecutionError as e:
    await update.message.reply_text(f"技能执行失败: {str(e)}")
except CharacterNotFoundError:
    await update.message.reply_text("找不到指定的角色")
except Exception as e:
    logging.error(f"未知错误: {str(e)}")
    await update.message.reply_text("系统发生错误，请稍后再试")
```

### 10. 测试工具

#### 单元测试示例

```python
import unittest
from skill.skill_effects import DefaultSkillEffect

class TestSkillEffects(unittest.TestCase):
    def setUp(self):
        self.skill_effect = DefaultSkillEffect()
    
    def test_calculate_effect_amount(self):
        # 测试固定数值
        result = self.skill_effect._calculate_effect_amount(
            {'amount': 50}, 100, 'damage'
        )
        self.assertEqual(result, 50)
        
        # 测试百分比
        result = self.skill_effect._calculate_effect_amount(
            {'percentage': 25}, 100, 'damage'
        )
        self.assertEqual(result, 25)
```

#### 集成测试工具

使用系统提供的测试脚本：
- `test_percentage_calculation.py`: 测试百分比计算
- `test_aoe_system.py`: 测试AOE系统
- `test_battle_system.py`: 测试战斗系统

---

本API文档提供了SimpleBot系统的完整编程接口说明。开发者可以基于这些API扩展系统功能或集成到其他应用中。
