"""
效果系统基础模块
提供特殊效果的基类和管理接口
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, List, Tuple, Optional


class BaseEffect(ABC):
    """特殊效果基类"""
    
    def __init__(self, name: str, description: str = ""):
        self.name = name
        self.description = description
    
    @abstractmethod
    def apply(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        应用效果
        
        Args:
            context: 效果上下文，包含角色、技能、目标等信息
            
        Returns:
            Dict: 效果结果，包含修改的数值、消息等
        """
        pass
    
    @abstractmethod
    def can_apply(self, context: Dict[str, Any]) -> bool:
        """
        检查是否可以应用此效果
        
        Args:
            context: 效果上下文
            
        Returns:
            bool: 是否可以应用
        """
        pass


class StatusEffect(BaseEffect):
    """状态效果基类"""
    
    def __init__(self, name: str, description: str = "", duration: int = 1):
        super().__init__(name, description)
        self.duration = duration
    
    @abstractmethod
    def get_effect_intensity(self, character_id: int) -> int:
        """获取效果强度"""
        pass
    
    @abstractmethod
    def has_effect(self, character_id: int) -> bool:
        """检查角色是否有此效果"""
        pass


class DamageEnhancer(BaseEffect):
    """伤害增强效果基类"""
    
    @abstractmethod
    def calculate_additional_damage(self, context: Dict[str, Any]) -> Tuple[int, str, List[str]]:
        """
        计算附加伤害
        
        Args:
            context: 伤害计算上下文
            
        Returns:
            Tuple: (附加伤害值, 伤害详情, 额外消息列表)
        """
        pass


class EffectRegistry:
    """效果注册中心"""
    
    def __init__(self):
        self._status_effects: Dict[str, StatusEffect] = {}
        self._damage_enhancers: Dict[str, DamageEnhancer] = {}
        self._special_effects: Dict[str, BaseEffect] = {}
    
    def register_status_effect(self, effect: StatusEffect):
        """注册状态效果"""
        self._status_effects[effect.name] = effect
    
    def register_damage_enhancer(self, enhancer: DamageEnhancer):
        """注册伤害增强效果"""
        self._damage_enhancers[enhancer.name] = enhancer
    
    def register_special_effect(self, effect: BaseEffect):
        """注册特殊效果"""
        self._special_effects[effect.name] = effect
    
    def get_status_effect(self, name: str) -> Optional[StatusEffect]:
        """获取状态效果"""
        return self._status_effects.get(name)
    
    def get_damage_enhancer(self, name: str) -> Optional[DamageEnhancer]:
        """获取伤害增强效果"""
        return self._damage_enhancers.get(name)
    
    def get_special_effect(self, name: str) -> Optional[BaseEffect]:
        """获取特殊效果"""
        return self._special_effects.get(name)
    
    def get_all_damage_enhancers(self) -> List[DamageEnhancer]:
        """获取所有伤害增强效果"""
        return list(self._damage_enhancers.values())
    
    def get_all_status_effects(self) -> List[StatusEffect]:
        """获取所有状态效果"""
        return list(self._status_effects.values())


# 全局效果注册中心
effect_registry = EffectRegistry()
