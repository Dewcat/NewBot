"""
伤害增强器模块
统一管理所有类型的伤害增强逻辑
"""

from typing import Dict, Any, List, Tuple
import sys
import os

# 添加父目录到Python路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from effects import DamageEnhancer


class StatusBasedDamageEnhancer(DamageEnhancer):
    """基于状态效果的伤害增强"""
    
    def __init__(self):
        super().__init__("status_based_damage", "基于状态效果的伤害增强")
    
    def apply(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """应用状态基础伤害增强"""
        additional_damage, damage_detail, messages = self.calculate_additional_damage(context)
        
        return {
            'additional_damage': additional_damage,
            'damage_detail': damage_detail,
            'messages': messages
        }
    
    def can_apply(self, context: Dict[str, Any]) -> bool:
        """检查是否可以应用状态基础伤害增强"""
        skill_effects = context.get('skill_effects', {})
        return 'status' in skill_effects
    
    def calculate_additional_damage(self, context: Dict[str, Any]) -> Tuple[int, str, List[str]]:
        """计算基于状态效果的附加伤害"""
        skill_effects = context.get('skill_effects', {})
        base_damage = context.get('base_damage', 0)
        
        if not self.can_apply(context):
            return 0, "", []
        
        total_additional_damage = 0
        damage_details = []
        messages = []
        
        status_effects_list = skill_effects['status']
        if isinstance(status_effects_list, list):
            for status_info in status_effects_list:
                if isinstance(status_info, dict) and 'additional_damage' in status_info:
                    # 处理基于主伤害百分比的额外伤害
                    add_damage_info = status_info['additional_damage']
                    if isinstance(add_damage_info, dict):
                        damage_percentage = add_damage_info.get('damage_percentage', 0)
                        if damage_percentage > 0:
                            # 基于基础伤害的百分比计算额外伤害
                            percentage_damage = int(base_damage * damage_percentage / 100)
                            total_additional_damage += percentage_damage
                            damage_details.append(f"状态伤害: {base_damage}×{damage_percentage}% = {percentage_damage}")
                            
                        # 处理固定数值的额外伤害
                        fixed_damage = add_damage_info.get('fixed_damage', 0)
                        if fixed_damage > 0:
                            total_additional_damage += fixed_damage
                            damage_details.append(f"固定伤害: {fixed_damage}")
        
        combined_detail = " + ".join(damage_details) if damage_details else ""
        return total_additional_damage, combined_detail, messages


class DamageEnhancerManager:
    """伤害增强器管理器"""
    
    def __init__(self):
        # 导入所有伤害增强器 - 更新导入路径
        from skill.special_effects.hardblood_effects import (
            HardbloodConsumeDamage, HardbloodAOEEnhancer
        )
        from skill.special_effects.dark_domain_effects import DarkDomainConditionalDamage
        
        # 注册所有伤害增强器
        self.enhancers = [
            HardbloodConsumeDamage(),
            HardbloodAOEEnhancer(),
            DarkDomainConditionalDamage(),
            StatusBasedDamageEnhancer()
        ]
    
    def calculate_all_additional_damage(self, context: Dict[str, Any]) -> Tuple[int, List[str], List[str]]:
        """
        计算所有类型的附加伤害
        
        Args:
            context: 伤害计算上下文
            
        Returns:
            Tuple: (总附加伤害, 伤害详情列表, 消息列表)
        """
        total_additional_damage = 0
        damage_details = []
        messages = []
        
        for enhancer in self.enhancers:
            if enhancer.can_apply(context):
                additional_damage, damage_detail, enhancer_messages = enhancer.calculate_additional_damage(context)
                
                if additional_damage > 0:
                    total_additional_damage += additional_damage
                    if damage_detail:
                        damage_details.append(damage_detail)
                    messages.extend(enhancer_messages)
        
        return total_additional_damage, damage_details, messages
    
    def get_enhancer_by_name(self, name: str) -> DamageEnhancer:
        """根据名称获取伤害增强器"""
        for enhancer in self.enhancers:
            if enhancer.name == name:
                return enhancer
        return None
    
    def apply_enhancer(self, enhancer_name: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """应用指定的伤害增强器"""
        enhancer = self.get_enhancer_by_name(enhancer_name)
        if enhancer and enhancer.can_apply(context):
            return enhancer.apply(context)
        
        return {'additional_damage': 0, 'damage_detail': '', 'messages': []}


# 全局伤害增强器管理器
damage_enhancer_manager = DamageEnhancerManager()
