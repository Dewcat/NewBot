"""
硬血效果模块
管理硬血状态和相关的伤害增强逻辑
"""

from typing import Dict, Any, List, Tuple
import sys
import os

# 添加上级目录到Python路径，使能够导入effects模块
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from effects import StatusEffect, DamageEnhancer


class HardbloodStatus(StatusEffect):
    """硬血状态效果"""
    
    def __init__(self):
        super().__init__("hardblood", "硬血状态，可用于增强技能伤害", duration=999)
    
    def apply(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """应用硬血状态"""
        character_id = context.get('character_id')
        amount = context.get('amount', 1)
        
        from character.status_effects import add_status_effect
        success = add_status_effect(character_id, 'hardblood', 'hardblood', amount, self.duration)
        
        return {
            'success': success,
            'messages': [f"🩸 获得了 {amount} 点硬血"] if success else []
        }
    
    def can_apply(self, context: Dict[str, Any]) -> bool:
        """检查是否可以应用硬血状态"""
        return context.get('character_id') is not None
    
    def has_effect(self, character_id: int) -> bool:
        """检查角色是否有硬血效果（StatusEffect抽象方法实现）"""
        from character.status_effects import get_hardblood_amount
        return get_hardblood_amount(character_id) > 0
    
    def get_effect_intensity(self, character_id: int) -> int:
        """获取硬血数量"""
        from character.status_effects import get_hardblood_amount
        return get_hardblood_amount(character_id)


class HardbloodConsumeDamage(DamageEnhancer):
    """硬血消耗伤害增强"""
    
    def __init__(self):
        super().__init__("hardblood_consume", "消耗硬血增强伤害")
    
    def apply(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """应用硬血消耗增强"""
        additional_damage, damage_detail, messages = self.calculate_additional_damage(context)
        
        return {
            'additional_damage': additional_damage,
            'damage_detail': damage_detail,
            'messages': messages
        }
    
    def can_apply(self, context: Dict[str, Any]) -> bool:
        """检查是否可以应用硬血消耗增强"""
        attacker = context.get('attacker')
        skill_effects = context.get('skill_effects', {})
        
        if not attacker or 'hardblood_consume' not in skill_effects:
            return False
        
        # 检查角色是否有硬血
        from character.status_effects import get_hardblood_amount
        return get_hardblood_amount(attacker['id']) > 0
    
    def calculate_additional_damage(self, context: Dict[str, Any]) -> Tuple[int, str, List[str]]:
        """计算硬血消耗附加伤害"""
        attacker = context.get('attacker')
        skill_effects = context.get('skill_effects', {})
        
        if not self.can_apply(context):
            return 0, "", []
        
        consume_info = skill_effects['hardblood_consume']
        max_consume = consume_info.get('max_consume', 10)
        damage_per_point = consume_info.get('damage_per_point', 1)
        
        # 获取当前硬血数量
        from character.status_effects import get_hardblood_amount, consume_hardblood
        current_hardblood = get_hardblood_amount(attacker['id'])
        actual_consume = min(current_hardblood, max_consume)
        
        if actual_consume > 0:
            # 消耗硬血并计算额外伤害
            consumed = consume_hardblood(attacker['id'], actual_consume)
            hardblood_damage = consumed * damage_per_point
            
            damage_detail = f"硬血消耗: {consumed}点×{damage_per_point} = {hardblood_damage}"
            messages = [f"🩸 {attacker['name']} 消耗了 {consumed} 点硬血"]
            
            return hardblood_damage, damage_detail, messages
        
        return 0, "", []


class HardbloodShieldEffect(DamageEnhancer):
    """硬血护盾效果"""
    
    def __init__(self):
        super().__init__("hardblood_shield", "消耗硬血获得护盾")
    
    def apply(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """应用硬血护盾效果"""
        attacker = context.get('attacker')
        skill_effects = context.get('skill_effects', {})
        
        if not self.can_apply(context):
            return {'success': False, 'messages': []}
        
        shield_info = skill_effects['hardblood_shield']
        max_consume = shield_info.get('max_consume', 30)
        shield_per_point = shield_info.get('shield_per_point', 5)
        
        # 计算要消耗的硬血数量
        from character.status_effects import get_hardblood_amount, consume_hardblood, add_status_effect
        current_hardblood = get_hardblood_amount(attacker['id'])
        actual_consume = min(current_hardblood, max_consume)
        
        if actual_consume > 0:
            # 消耗硬血
            consumed = consume_hardblood(attacker['id'], actual_consume)
            
            # 计算护盾值
            shield_value = consumed * shield_per_point
            
            # 添加护盾状态效果
            if shield_value > 0:
                add_status_effect(attacker['id'], 'buff', 'shield', shield_value, 999)
                messages = [
                    f"🩸 {attacker['name']} 消耗了 {consumed} 点硬血",
                    f"🛡️ 获得了 {shield_value} 点护盾"
                ]
                return {'success': True, 'messages': messages}
        
        return {'success': False, 'messages': []}
    
    def can_apply(self, context: Dict[str, Any]) -> bool:
        """检查是否可以应用硬血护盾"""
        attacker = context.get('attacker')
        skill_effects = context.get('skill_effects', {})
        
        if not attacker or 'hardblood_shield' not in skill_effects:
            return False
        
        # 检查角色是否有硬血
        from character.status_effects import get_hardblood_amount
        return get_hardblood_amount(attacker['id']) > 0
    
    def calculate_additional_damage(self, context: Dict[str, Any]) -> Tuple[int, str, List[str]]:
        """硬血护盾不产生额外伤害"""
        return 0, "", []


class HardbloodAOEEnhancer(DamageEnhancer):
    """硬血AOE伤害增强"""
    
    def __init__(self):
        super().__init__("hardblood_aoe_enhance", "硬血AOE伤害增强")
    
    def apply(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """应用硬血AOE增强"""
        additional_damage, damage_detail, messages = self.calculate_additional_damage(context)
        
        return {
            'additional_damage': additional_damage,
            'damage_detail': damage_detail,
            'messages': messages
        }
    
    def can_apply(self, context: Dict[str, Any]) -> bool:
        """检查是否可以应用硬血AOE增强"""
        attacker = context.get('attacker')
        skill_effects = context.get('skill_effects', {})
        
        if not attacker or 'aoe_damage_enhance' not in skill_effects:
            return False
        
        # 检查角色是否有硬血
        from character.status_effects import get_hardblood_amount
        return get_hardblood_amount(attacker['id']) > 0
    
    def calculate_additional_damage(self, context: Dict[str, Any]) -> Tuple[int, str, List[str]]:
        """计算硬血AOE增强伤害"""
        attacker = context.get('attacker')
        skill_effects = context.get('skill_effects', {})
        
        if not self.can_apply(context):
            return 0, "", []
        
        aoe_enhance = skill_effects['aoe_damage_enhance']
        hardblood_bonus = aoe_enhance.get('hardblood_damage_bonus', 0)
        max_hardblood_consume = aoe_enhance.get('max_hardblood_consume', 20)
        
        if hardblood_bonus > 0:
            from character.status_effects import get_hardblood_amount, consume_hardblood
            current_hardblood = get_hardblood_amount(attacker['id'])
            actual_consume = min(current_hardblood, max_hardblood_consume)
            
            if actual_consume > 0:
                # 消耗硬血增强AOE伤害
                consumed = consume_hardblood(attacker['id'], actual_consume)
                aoe_enhance_damage = consumed * hardblood_bonus
                
                damage_detail = f"AOE增强: {consumed}点×{hardblood_bonus} = {aoe_enhance_damage}"
                messages = [f"🩸 {attacker['name']} 消耗了 {consumed} 点硬血增强AOE伤害"]
                
                return aoe_enhance_damage, damage_detail, messages
        
        return 0, "", []
