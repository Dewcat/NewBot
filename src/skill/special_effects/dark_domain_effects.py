"""
黑夜领域效果模块
管理黑夜领域状态和条件伤害逻辑
"""

from typing import Dict, Any, List, Tuple
import sys
import os

# 添加上级目录到Python路径，使能够导入effects模块
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from effects import StatusEffect, DamageEnhancer, BaseEffect


class DarkDomainStatus(StatusEffect):
    """黑夜领域状态效果"""
    
    def __init__(self):
        super().__init__("dark_domain", "黑夜领域状态，增强某些技能的伤害", duration=3)
    
    def apply(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """应用黑夜领域状态"""
        character_id = context.get('character_id')
        intensity = context.get('intensity', 1)
        duration = context.get('duration', self.duration)
        
        if character_id:
            from character.status_effects import apply_status_effect
            apply_status_effect(character_id, self.effect_name, intensity, duration)
            
            return {
                'success': True,
                'messages': [f"🌙 获得了黑夜领域效果 (强度: {intensity}, 持续: {duration}回合)"]
            }
        
        return {'success': False, 'messages': []}
    
    def can_apply(self, context: Dict[str, Any]) -> bool:
        """检查是否可以应用黑夜领域状态"""
        return context.get('character_id') is not None
    
    def has_effect(self, character_id: int) -> bool:
        """检查角色是否有黑夜领域效果（StatusEffect抽象方法实现）"""
        return self.get_effect_intensity(character_id) > 0
    
    def get_effect_intensity(self, character_id: int) -> int:
        """获取黑夜领域强度"""
        from character.status_effects import get_character_status_effects
        status_effects = get_character_status_effects(character_id)
        
        for effect in status_effects:
            if effect.effect_name == 'dark_domain':
                return effect.intensity
        return 0
    
    def has_dark_domain(self, character_id: int) -> bool:
        """检查角色是否有黑夜领域效果"""
        return self.get_effect_intensity(character_id) > 0


class DarkDomainConditionalDamage(DamageEnhancer):
    """黑夜领域条件伤害增强"""
    
    def __init__(self):
        super().__init__("dark_domain_conditional", "黑夜领域条件伤害")
    
    def apply(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """应用黑夜领域条件伤害"""
        additional_damage, damage_detail, messages = self.calculate_additional_damage(context)
        
        return {
            'additional_damage': additional_damage,
            'damage_detail': damage_detail,
            'messages': messages
        }
    
    def can_apply(self, context: Dict[str, Any]) -> bool:
        """检查是否可以应用黑夜领域条件伤害"""
        attacker = context.get('attacker')
        skill_effects = context.get('skill_effects', {})
        
        if not attacker or 'conditional_damage' not in skill_effects:
            return False
        
        conditional_damage = skill_effects['conditional_damage']
        condition = conditional_damage.get('condition')
        
        # 检查条件类型
        if condition == "self_has_dark_domain":
            dark_domain_status = DarkDomainStatus()
            return dark_domain_status.has_dark_domain(attacker['id'])
        
        return False
    
    def calculate_additional_damage(self, context: Dict[str, Any]) -> Tuple[int, str, List[str]]:
        """计算黑夜领域条件伤害"""
        attacker = context.get('attacker')
        skill_effects = context.get('skill_effects', {})
        
        if not self.can_apply(context):
            return 0, "", []
        
        conditional_damage = skill_effects['conditional_damage']
        conditional_formula = conditional_damage.get('damage_formula', '1d6')
        
        # 导入伤害计算函数
        from game.damage_calculator import calculate_damage_from_formula
        conditional_base, conditional_detail, _ = calculate_damage_from_formula(conditional_formula)
        
        return conditional_base, f"条件伤害: {conditional_detail}", []


class BeastNumberSkillEffect(BaseEffect):
    """兽之数技能效果管理器"""
    
    def __init__(self):
        super().__init__("beast_number_skill", "兽之数技能效果管理器")
        self.dark_domain_status = DarkDomainStatus()
        self.conditional_damage = DarkDomainConditionalDamage()
    
    def apply(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """应用兽之数技能的所有效果"""
        return self.apply_beast_number_effects(context)
    
    def can_apply(self, context: Dict[str, Any]) -> bool:
        """检查是否可以应用兽之数技能效果"""
        return True  # 总是可以应用
    
    def apply_beast_number_effects(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """应用兽之数技能的所有效果"""
        results = {
            'additional_damage': 0,
            'damage_details': [],
            'messages': []
        }
        
        # 1. 计算条件伤害（如果满足条件）
        if self.conditional_damage.can_apply(context):
            damage_result = self.conditional_damage.apply(context)
            results['additional_damage'] += damage_result['additional_damage']
            if damage_result['damage_detail']:
                results['damage_details'].append(damage_result['damage_detail'])
            results['messages'].extend(damage_result['messages'])
        
        # 2. 应用黑夜领域状态（如果技能包含状态效果）
        skill_effects = context.get('skill_effects', {})
        if 'status' in skill_effects:
            status_list = skill_effects['status']
            attacker = context.get('attacker')
            
            if isinstance(status_list, list) and attacker:
                for status_info in status_list:
                    if isinstance(status_info, dict) and status_info.get('effect') == 'dark_domain':
                        domain_context = {
                            'character_id': attacker['id'],
                            'intensity': status_info.get('value', 1),
                            'duration': status_info.get('turns', 3)
                        }
                        
                        domain_result = self.dark_domain_status.apply(domain_context)
                        results['messages'].extend(domain_result['messages'])
        
        return results
