"""
效果集成模块
整合所有效果系统，提供统一的接口
"""

from typing import Dict, Any, List, Tuple
from effects import EffectRegistry
from skill.special_effects.hardblood_effects import (
    HardbloodStatus, HardbloodConsumeDamage, HardbloodShieldEffect, HardbloodAOEEnhancer
)
from skill.special_effects.dark_domain_effects import (
    DarkDomainStatus, DarkDomainConditionalDamage, BeastNumberSkillEffect
)
from skill.special_effects.aura_effects import (
    WeakenAuraStatus, AOEStatusApplicator
)
from game.damage_enhancers.damage_manager import DamageEnhancerManager


class EffectIntegrationManager:
    """效果集成管理器"""
    
    def __init__(self):
        self.registry = EffectRegistry()
        self.damage_manager = DamageEnhancerManager()
        self._register_all_effects()
    
    def _register_all_effects(self):
        """注册所有效果"""
        # 注册硬血效果
        self.registry.register_status_effect(HardbloodStatus())
        self.registry.register_damage_enhancer(HardbloodConsumeDamage())
        self.registry.register_special_effect(HardbloodShieldEffect())
        self.registry.register_damage_enhancer(HardbloodAOEEnhancer())
        
        # 注册黑夜领域效果
        self.registry.register_status_effect(DarkDomainStatus())
        self.registry.register_damage_enhancer(DarkDomainConditionalDamage())
        self.registry.register_special_effect(BeastNumberSkillEffect())
        
        # 注册光环效果
        self.registry.register_status_effect(WeakenAuraStatus())
        self.registry.register_special_effect(AOEStatusApplicator())
    
    def calculate_unified_damage(self, context: Dict[str, Any]) -> Tuple[int, int, str, List[str]]:
        """
        统一计算伤害（基础伤害 + 所有附加伤害）
        
        Args:
            context: 伤害计算上下文，包含技能信息、目标信息等
            
        Returns:
            Tuple: (基础伤害, 附加伤害, 伤害详情, 消息列表)
        """
        base_damage = context.get('base_damage', 0)
        
        # 计算所有附加伤害
        additional_damage, damage_details, messages = self.damage_manager.calculate_all_additional_damage(context)
        
        # 构建详细信息
        detail_parts = []
        if base_damage > 0:
            detail_parts.append(f"基础伤害: {base_damage}")
        
        if damage_details:
            detail_parts.extend(damage_details)
        
        combined_detail = " + ".join(detail_parts) if detail_parts else ""
        
        return base_damage, additional_damage, combined_detail, messages
    
    def apply_status_effects(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        应用状态效果
        
        Args:
            context: 效果应用上下文
            
        Returns:
            Dict: 应用结果，包含状态变化、消息等
        """
        results = {
            'applied_effects': [],
            'messages': [],
            'status_changes': {}
        }
        
        skill_effects = context.get('skill_effects', {})
        
        # 应用硬血效果
        if self._should_apply_hardblood(skill_effects):
            hardblood_effect = self.registry.get_status_effect("hardblood_status")
            if hardblood_effect and hardblood_effect.can_apply(context):
                effect_result = hardblood_effect.apply(context)
                results['applied_effects'].append("hardblood_status")
                results['messages'].extend(effect_result.get('messages', []))
        
        # 应用黑夜领域效果
        if self._should_apply_dark_domain(skill_effects):
            dark_domain_effect = self.registry.get_status_effect("dark_domain")
            if dark_domain_effect and dark_domain_effect.can_apply(context):
                effect_result = dark_domain_effect.apply(context)
                results['applied_effects'].append("dark_domain_status")
                results['messages'].extend(effect_result.get('messages', []))
        
        # 应用削弱光环效果
        if self._should_apply_aoe_status(skill_effects):
            aoe_effect = self.registry.get_special_effect("aoe_status_applicator")
            if aoe_effect and aoe_effect.can_apply(context):
                effect_result = aoe_effect.apply(context)
                results['applied_effects'].append("aoe_status_applicator")
                results['messages'].extend(effect_result.get('messages', []))
        
        return results
    
    def _should_apply_hardblood(self, skill_effects: Dict[str, Any]) -> bool:
        """检查是否应该应用硬血效果"""
        return 'hardblood' in skill_effects
    
    def _should_apply_dark_domain(self, skill_effects: Dict[str, Any]) -> bool:
        """检查是否应该应用黑夜领域效果"""
        return 'conditional_damage' in skill_effects
    
    def _should_apply_aoe_status(self, skill_effects: Dict[str, Any]) -> bool:
        """检查是否应该应用AOE状态效果"""
        return 'aoe_status' in skill_effects
    
    def process_skill_effects(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        处理技能的所有效果
        
        Args:
            context: 技能效果上下文
            
        Returns:
            Dict: 处理结果，包含伤害、状态变化、消息等
        """
        results = {
            'base_damage': 0,
            'additional_damage': 0,
            'total_damage': 0,
            'damage_detail': '',
            'applied_effects': [],
            'messages': []
        }
        
        # 计算伤害
        base_damage, additional_damage, damage_detail, damage_messages = self.calculate_unified_damage(context)
        results['base_damage'] = base_damage
        results['additional_damage'] = additional_damage
        results['total_damage'] = base_damage + additional_damage
        results['damage_detail'] = damage_detail
        results['messages'].extend(damage_messages)
        
        # 应用状态效果
        status_results = self.apply_status_effects(context)
        results['applied_effects'].extend(status_results['applied_effects'])
        results['messages'].extend(status_results['messages'])
        
        return results


# 全局效果集成管理器
effect_integration_manager = EffectIntegrationManager()
