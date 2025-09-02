"""
效果目标解析器
统一处理技能效果的目标选择逻辑
"""

try:
    # 尝试相对导入（在src目录下运行时）
    from database.queries import get_characters_by_type, get_character
except ImportError:
    # 尝试绝对导入（在项目根目录运行时）
    from src.database.queries import get_characters_by_type, get_character

class EffectTargetResolver:
    """效果目标解析器"""
    
    def __init__(self):
        self.target_types = {
            'self': self._resolve_self,
            'skill_target': self._resolve_skill_target,
            'all_allies': self._resolve_all_allies,
            'all_enemies': self._resolve_all_enemies,
            'all_characters': self._resolve_all_characters
        }
    
    def resolve_target(self, target_type, attacker, skill_target=None):
        """
        解析目标
        
        Args:
            target_type: 目标类型 ('self', 'skill_target', 'all_allies', 'all_enemies', 'all_characters')
            attacker: 施法者角色信息
            skill_target: 技能选择的目标角色信息
            
        Returns:
            list: 目标角色列表
        """
        if target_type in self.target_types:
            return self.target_types[target_type](attacker, skill_target)
        else:
            # 默认返回技能目标或施法者
            return self._resolve_skill_target(attacker, skill_target)
    
    def _resolve_self(self, attacker, skill_target=None):
        """解析自身目标"""
        return [attacker]
    
    def _resolve_skill_target(self, attacker, skill_target=None):
        """解析技能选择的目标"""
        return [skill_target] if skill_target else [attacker]
    
    def _resolve_all_allies(self, attacker, skill_target=None):
        """解析所有友方目标"""
        attacker_type = attacker.get('character_type', 'friendly')
        allies = get_characters_by_type(attacker_type, in_battle=True)
        return allies
    
    def _resolve_all_enemies(self, attacker, skill_target=None):
        """解析所有敌方目标"""
        attacker_type = attacker.get('character_type', 'friendly')
        enemy_type = 'enemy' if attacker_type == 'friendly' else 'friendly'
        enemies = get_characters_by_type(enemy_type, in_battle=True)
        return enemies
    
    def _resolve_all_characters(self, attacker, skill_target=None):
        """解析所有角色目标"""
        all_chars = []
        all_chars.extend(get_characters_by_type('friendly', in_battle=True))
        all_chars.extend(get_characters_by_type('enemy', in_battle=True))
        return all_chars

# 创建全局目标解析器实例
target_resolver = EffectTargetResolver()
