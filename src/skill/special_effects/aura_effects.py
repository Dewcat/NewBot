"""
削弱光环效果模块
管理削弱光环状态和相关的AOE减益逻辑
"""

from typing import Dict, Any, List, Tuple
import sys
import os

# 添加上级目录到Python路径，使能够导入effects模块
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from effects import StatusEffect, BaseEffect


class WeakenAuraStatus(StatusEffect):
    """削弱光环状态效果"""
    
    def __init__(self):
        super().__init__("weaken_aura", "削弱光环，对所有敌方目标施加削弱效果", duration=5)
    
    def apply(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """应用削弱光环状态"""
        character_id = context.get('character_id')
        intensity = context.get('intensity', 1)
        duration = context.get('duration', self.duration)
        
        from character.status_effects import add_status_effect
        success = add_status_effect(character_id, 'special', 'weaken_aura', intensity, duration)
        
        return {
            'success': success,
            'messages': [f"💜 释放了削弱光环，持续 {duration} 回合"] if success else []
        }
    
    def can_apply(self, context: Dict[str, Any]) -> bool:
        """检查是否可以应用削弱光环状态"""
        return context.get('character_id') is not None
    
    def get_effect_intensity(self, character_id: int) -> int:
        """获取削弱光环强度"""
        from character.status_effects import get_character_status_effects
        status_effects = get_character_status_effects(character_id)
        
        for effect in status_effects:
            if effect.effect_name == 'weaken_aura':
                return effect.intensity
        return 0
    
    def has_effect(self, character_id: int) -> bool:
        """检查角色是否有削弱光环效果"""
        return self.get_effect_intensity(character_id) > 0


class AOEStatusApplicator(BaseEffect):
    """AOE状态效果施加器"""
    
    def __init__(self):
        super().__init__("aoe_status_applicator", "对所有目标施加状态效果")
    
    def apply(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """应用AOE状态效果"""
        attacker = context.get('attacker')
        skill_effects = context.get('skill_effects', {})
        
        if not self.can_apply(context):
            return {'success': False, 'messages': []}
        
        messages = []
        
        # 处理新的削弱光环技能格式
        if isinstance(skill_effects, list):
            for effect_info in skill_effects:
                if not isinstance(effect_info, dict):
                    continue
                
                effect_type = effect_info.get('type', '')
                
                if effect_type == 'aoe_apply_status':
                    result = self._apply_aoe_status(attacker, effect_info)
                    messages.extend(result['messages'])
                elif effect_type == 'apply_status':
                    result = self._apply_single_status(attacker, effect_info)
                    messages.extend(result['messages'])
        
        return {'success': len(messages) > 0, 'messages': messages}
    
    def can_apply(self, context: Dict[str, Any]) -> bool:
        """检查是否可以应用AOE状态效果"""
        attacker = context.get('attacker')
        skill_effects = context.get('skill_effects', {})
        
        return attacker is not None and skill_effects is not None
    
    def _apply_aoe_status(self, attacker: Dict[str, Any], effect_info: Dict[str, Any]) -> Dict[str, Any]:
        """应用AOE状态效果到所有敌方目标"""
        target_type = effect_info.get('target_type', 'enemy')
        effect_name = effect_info.get('effect_name', '')
        intensity = effect_info.get('intensity', 1)
        duration = effect_info.get('duration', 1)
        
        messages = []
        
        # 获取所有目标类型的角色
        from database.queries import get_characters_by_type
        if target_type == 'enemy':
            attacker_type = attacker.get('character_type', 'friendly')
            enemy_type = 'enemy' if attacker_type == 'friendly' else 'friendly'
            targets = get_characters_by_type(enemy_type, in_battle=True)
        else:
            targets = [attacker]  # 默认自身
        
        # 对所有目标施加状态效果
        for target_char in targets:
            if not target_char:
                continue
            
            # 确定效果类型
            if effect_name in ['weak', 'vulnerable', 'burn', 'poison', 'rupture', 'bleeding', 'paralysis']:
                status_type = 'debuff'
            elif effect_name in ['strong', 'breathing', 'guard', 'shield', 'haste']:
                status_type = 'buff'
            else:
                status_type = effect_info.get('effect_type', 'debuff')
            
            from character.status_effects import add_status_effect
            success = add_status_effect(
                target_char['id'],
                status_type,
                effect_name,
                intensity,
                duration
            )
            
            if success:
                effect_display_names = {
                    'weak': '虚弱',
                    'vulnerable': '易伤', 
                    'burn': '烧伤',
                    'poison': '中毒',
                    'rupture': '破裂',
                    'bleeding': '流血',
                    'paralysis': '麻痹',
                    'strong': '强壮',
                    'breathing': '呼吸法',
                    'guard': '守护',
                    'shield': '护盾',
                    'haste': '加速'
                }
                
                effect_display_name = effect_display_names.get(effect_name, effect_name)
                
                if status_type == 'buff':
                    messages.append(f"✨ {target_char['name']} 获得了 {effect_display_name}({intensity}) 效果，持续 {duration} 回合")
                else:
                    messages.append(f"💀 {target_char['name']} 受到了 {effect_display_name}({intensity}) 效果，持续 {duration} 回合")
        
        return {'messages': messages}
    
    def _apply_single_status(self, attacker: Dict[str, Any], effect_info: Dict[str, Any]) -> Dict[str, Any]:
        """应用单体状态效果"""
        target_type = effect_info.get('target_type', 'self')
        effect_name = effect_info.get('effect_name', '')
        intensity = effect_info.get('intensity', 1)
        duration = effect_info.get('duration', 1)
        
        messages = []
        
        # 确定目标
        if target_type == 'self':
            apply_target = attacker
        else:
            return {'messages': []}  # 暂时只支持自身目标
        
        if apply_target:
            # 确定效果类型
            if effect_name in ['weak', 'vulnerable', 'burn', 'poison', 'rupture', 'bleeding', 'paralysis']:
                status_type = 'debuff'
            elif effect_name in ['strong', 'breathing', 'guard', 'shield', 'haste']:
                status_type = 'buff'
            elif effect_name == 'weaken_aura':
                status_type = 'special'
            else:
                status_type = effect_info.get('effect_type', 'buff')
            
            from character.status_effects import add_status_effect
            success = add_status_effect(
                apply_target['id'],
                status_type,
                effect_name,
                intensity,
                duration
            )
            
            if success:
                effect_display_names = {
                    'weak': '虚弱',
                    'vulnerable': '易伤',
                    'burn': '烧伤',
                    'poison': '中毒',
                    'rupture': '破裂',
                    'bleeding': '流血',
                    'paralysis': '麻痹',
                    'strong': '强壮',
                    'breathing': '呼吸法',
                    'guard': '守护',
                    'shield': '护盾',
                    'haste': '加速',
                    'weaken_aura': '削弱光环'
                }
                
                effect_display_name = effect_display_names.get(effect_name, effect_name)
                
                if effect_name == 'weaken_aura':
                    messages.append(f"💜 {apply_target['name']} 释放了{effect_display_name}，持续 {duration} 回合")
                elif status_type == 'buff':
                    messages.append(f"✨ {apply_target['name']} 获得了 {effect_display_name}({intensity}) 效果，持续 {duration} 回合")
                else:
                    messages.append(f"💀 {apply_target['name']} 受到了 {effect_display_name}({intensity}) 效果，持续 {duration} 回合")
        
        return {'messages': messages}
