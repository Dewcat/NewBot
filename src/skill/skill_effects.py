import random
import json
from abc import ABC, abstractmethod
from database.queries import update_character_health, record_battle, get_character
from game.damage_calculator import (
    calculate_damage_from_formula, 
    calculate_attack_defense_modifier,
    update_character_cooldowns
)

class SkillEffect(ABC):
    """技能效果的抽象基类"""
    
    def execute(self, attacker, target, skill_info):
        """
        执行技能效果
        
        Args:
            attacker: 攻击者角色信息
            target: 目标角色信息  
            skill_info: 技能信息
            
        Returns:
            dict: {
                'total_damage': int,  # 总伤害
                'result_text': str,   # 战斗结果文本
                'target_health': int  # 目标剩余生命值
            }
        """
        # 处理通用的伤害计算和冷却时间
        damage_result = self.calculate_skill_damage(attacker, target, skill_info)
        
        # 处理特殊效果
        special_result = self.apply_special_effects(attacker, target, skill_info, damage_result)
        
        # 更新冷却时间
        update_character_cooldowns(attacker['id'], skill_info['id'] if skill_info else 1)
        
        return special_result
    
    def calculate_skill_damage(self, attacker, target, skill_info):
        """计算技能的基础伤害"""
        if not skill_info:
            # 无技能时使用基础攻击公式
            formula = "1d6"
        else:
            formula = skill_info.get('damage_formula', '1d6')
        
        # 计算骰子伤害
        base_damage, damage_detail = calculate_damage_from_formula(formula)
        
        # 计算攻防差值修正
        modifier = calculate_attack_defense_modifier(attacker['attack'], target['defense'])
        
        # 应用修正
        final_damage = int(base_damage * modifier)
        
        # 确保至少造成1点伤害
        final_damage = max(1, final_damage)
        
        return {
            'damage': final_damage,
            'base_damage': base_damage,
            'damage_detail': damage_detail,
            'modifier': modifier,
            'formula': formula
        }
    
    @abstractmethod
    def apply_special_effects(self, attacker, target, skill_info, damage_result):
        """应用技能的特殊效果"""
        pass

class NormalAttackEffect(SkillEffect):
    """普通攻击效果"""
    
    def apply_special_effects(self, attacker, target, skill_info, damage_result):
        damage = damage_result['damage']
        new_health = target['health'] - damage
        update_character_health(target['id'], new_health)
        record_battle(attacker['id'], target['id'], damage, skill_info['id'] if skill_info else None)
        
        result_text = f"使用{skill_info.get('name', '普通攻击')}：{damage_result['damage_detail']} = {damage} 点伤害"
        if damage_result['modifier'] != 1.0:
            result_text += f"（攻防修正: ×{damage_result['modifier']:.2f}）"
        
        return {
            'total_damage': damage,
            'result_text': result_text,
            'target_health': new_health
        }

class HealingEffect(SkillEffect):
    """治疗效果"""
    
    def apply_special_effects(self, attacker, target, skill_info, damage_result):
        # 对于治疗技能，"伤害"实际是治疗量
        heal_amount = damage_result['damage']
        
        # 治疗目标是攻击者自己
        healer = attacker
        new_health = min(healer['health'] + heal_amount, healer['max_health'])
        actual_heal = new_health - healer['health']
        
        update_character_health(healer['id'], new_health)
        record_battle(healer['id'], healer['id'], -actual_heal, skill_info['id'])  # 负伤害表示治疗
        
        result_text = f"使用{skill_info.get('name', '治疗')}：{damage_result['damage_detail']} = 恢复了 {actual_heal} 点生命值"
        if actual_heal < heal_amount:
            result_text += f"（生命值已满，实际恢复{actual_heal}点）"
        
        return {
            'total_damage': -actual_heal,  # 负数表示治疗
            'result_text': result_text,
            'target_health': target['health']  # 目标生命值不变
        }

class DefaultSkillEffect(SkillEffect):
    """默认技能效果（根据技能的effects JSON处理）"""
    
    def apply_special_effects(self, attacker, target, skill_info, damage_result):
        try:
            effects = json.loads(skill_info.get('effects', '{}'))
        except (json.JSONDecodeError, TypeError):
            effects = {}
        
        # 检查是否是治疗技能
        if effects.get('heal'):
            return HealingEffect().apply_special_effects(attacker, target, skill_info, damage_result)
        
        # 默认伤害处理
        damage = damage_result['damage']
        new_health = target['health'] - damage
        update_character_health(target['id'], new_health)
        record_battle(attacker['id'], target['id'], damage, skill_info['id'])
        
        result_text = f"使用{skill_info.get('name', '技能')}：{damage_result['damage_detail']} = {damage} 点伤害"
        if damage_result['modifier'] != 1.0:
            result_text += f"（攻防修正: ×{damage_result['modifier']:.2f}）"
        
        # 处理其他特殊效果
        special_effects = []
        if effects.get('stun'):
            special_effects.append("💫 目标被眩晕")
        if effects.get('poison'):
            special_effects.append("☠️ 目标中毒")
        if effects.get('burn'):
            special_effects.append("🔥 目标燃烧")
        
        if special_effects:
            result_text += "\n" + "\n".join(special_effects)
        
        return {
            'total_damage': damage,
            'result_text': result_text,
            'target_health': new_health
        }

class SkillEffectRegistry:
    """技能效果注册表"""
    
    def __init__(self):
        self.effects = {}
        self._register_default_effects()
    
    def _register_default_effects(self):
        """注册默认技能效果"""
        # 只为特殊技能注册专门的效果类
        self.register_effect(1, NormalAttackEffect())  # 普通攻击
        self.register_effect(7, HealingEffect())       # 净化（治疗技能）
    
    def register_effect(self, skill_id, effect):
        """注册技能效果"""
        self.effects[skill_id] = effect
    
    def get_effect(self, skill_id):
        """获取技能效果"""
        return self.effects.get(skill_id, DefaultSkillEffect())
    
    def execute_skill(self, attacker, target, skill_info):
        """执行技能"""
        if not skill_info:
            # 无技能时使用普通攻击
            effect = self.get_effect(1)
        else:
            effect = self.get_effect(skill_info['id'])
        
        return effect.execute(attacker, target, skill_info)

# 创建全局技能效果注册表实例
skill_registry = SkillEffectRegistry()
