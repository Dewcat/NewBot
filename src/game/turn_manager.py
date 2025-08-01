"""回合管理系统

用于处理战斗中的回合管理和状态效果处理
"""

import logging
from typing import List, Dict
from database.queries import get_characters_by_type, restore_character_actions
from character.status_effects import process_end_turn_effects, clear_all_status_effects

logger = logging.getLogger(__name__)

class TurnManager:
    """回合管理器"""
    
    def __init__(self):
        self.current_turn = 0
    
    def end_turn_for_character(self, character_id: int) -> List[str]:
        """结束指定角色的回合，处理状态效果，并开始新回合"""
        # 处理回合结束效果
        end_messages = process_end_turn_effects(character_id)
        
        # 恢复行动次数（开始新回合）
        self._restore_single_character_actions(character_id)
        
        # 处理回合开始效果（如加速）
        from character.status_effects import process_start_turn_effects
        start_messages = process_start_turn_effects(character_id)
        
        # 合并所有消息
        all_messages = []
        if end_messages:
            all_messages.extend(end_messages)
        if start_messages:
            all_messages.extend(start_messages)
            
        return all_messages
    
    def _restore_single_character_actions(self, character_id: int):
        """恢复单个角色的行动次数"""
        from database.queries import get_character, update_character_actions
        
        character = get_character(character_id)
        if character:
            update_character_actions(character_id, character['actions_per_turn'])
    
    def end_battle_turn(self) -> List[str]:
        """结束整个战斗回合，处理所有在战斗中角色的状态效果"""
        self.current_turn += 1
        all_messages = []
        
        # 获取所有在战斗中的角色
        friendly_characters = get_characters_by_type("friendly", in_battle=True)
        enemy_characters = get_characters_by_type("enemy", in_battle=True)
        
        all_characters = friendly_characters + enemy_characters
        
        if not all_characters:
            return ["没有角色在战斗中"]
        
        all_messages.append(f"=== 第 {self.current_turn} 回合结束 ===")
        
        for character in all_characters:
            character_name = character.get('name', '未知角色')
            character_messages = self.end_turn_for_character(character['id'])
            
            if character_messages:
                all_messages.append(f"\n{character_name} 的状态效果:")
                all_messages.extend(character_messages)
        
        if len(all_messages) == 1:  # 只有回合标题，没有其他效果
            all_messages.append("本回合没有状态效果触发")
        
        # 恢复所有角色的行动次数
        restored_count = restore_character_actions()
        if restored_count > 0:
            all_messages.append(f"\n✨ 已恢复 {restored_count} 个角色的行动次数")
        
        # 处理回合开始时的状态效果（比如加速）
        from character.status_effects import process_start_turn_effects
        for character in all_characters:
            character_name = character.get('name', '未知角色')
            start_turn_messages = process_start_turn_effects(character['id'])
            
            if start_turn_messages:
                all_messages.append(f"\n{character_name} 的回合开始效果:")
                all_messages.extend(start_turn_messages)
        
        return all_messages
    
    def reset_battle(self):
        """重置战斗状态"""
        self.current_turn = 0
        
        # 清除所有角色的状态效果
        friendly_characters = get_characters_by_type("friendly")
        enemy_characters = get_characters_by_type("enemy")
        
        all_characters = friendly_characters + enemy_characters
        
        for character in all_characters:
            clear_all_status_effects(character['id'])
        
        logger.info("战斗状态已重置，所有状态效果已清除")
    
    def reset_turn_counter(self):
        """重置回合计数器到0"""
        self.current_turn = 0
        logger.info("回合计数器已重置到0")
    
    def get_current_turn(self) -> int:
        """获取当前回合数"""
        return self.current_turn

# 全局回合管理器实例
turn_manager = TurnManager()
