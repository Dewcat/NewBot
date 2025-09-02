"""
混乱值（Stagger）状态管理模块
处理角色的混乱值扣除、混乱状态进入/解除、回合管理等
"""
import logging
from typing import Dict, List, Tuple, Optional
from database.db_connection import get_db_connection
from database.queries import get_character

logger = logging.getLogger(__name__)

class StaggerManager:
    """混乱值管理器"""
    
    @staticmethod
    def get_character_stagger_info(character_id: int) -> Optional[Dict]:
        """获取角色的混乱值信息"""
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT stagger_value, max_stagger_value, stagger_status, stagger_turns_remaining
                FROM characters WHERE id = ?
            """, (character_id,))
            
            result = cursor.fetchone()
            if result:
                return {
                    'stagger_value': result[0],
                    'max_stagger_value': result[1],
                    'stagger_status': result[2],
                    'stagger_turns_remaining': result[3]
                }
            return None
        except Exception as e:
            logger.error(f"获取角色混乱值信息失败: {e}")
            return None
        finally:
            conn.close()
    
    @staticmethod
    def reduce_stagger(character_id: int, damage: int) -> Tuple[bool, str, bool]:
        """
        扣除角色混乱值
        
        Args:
            character_id: 角色ID
            damage: 造成的伤害值（等于扣除的混乱值）
            
        Returns:
            tuple: (是否成功, 状态信息, 是否进入混乱状态)
        """
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            
            # 获取当前状态
            stagger_info = StaggerManager.get_character_stagger_info(character_id)
            if not stagger_info:
                return False, "找不到角色混乱值信息", False
            
            # 如果已经在混乱状态，不再扣除混乱值
            if stagger_info['stagger_status'] == 'staggered':
                return True, "角色已处于混乱状态，不再扣除混乱值", False
            
            # 扣除混乱值
            new_stagger = max(0, stagger_info['stagger_value'] - damage)
            
            # 检查是否进入混乱状态
            enters_stagger = (new_stagger == 0 and stagger_info['stagger_value'] > 0)
            
            if enters_stagger:
                # 进入混乱状态，设置持续时间为2回合
                cursor.execute("""
                    UPDATE characters 
                    SET stagger_value = 0, stagger_status = 'staggered', stagger_turns_remaining = 2
                    WHERE id = ?
                """, (character_id,))
                
                # 清空当前行动次数
                cursor.execute("""
                    UPDATE characters 
                    SET current_actions = 0
                    WHERE id = ?
                """, (character_id,))
                
                conn.commit()
                
                character = get_character(character_id)
                char_name = character.get('name', '未知角色') if character else '未知角色'
                
                return True, f"💫 {char_name} 进入混乱状态！", True
            else:
                # 正常扣除混乱值
                cursor.execute("""
                    UPDATE characters 
                    SET stagger_value = ?
                    WHERE id = ?
                """, (new_stagger, character_id))
                
                conn.commit()
                
                character = get_character(character_id)
                char_name = character.get('name', '未知角色') if character else '未知角色'
                
                return True, f"🔸 {char_name} 的混乱值: {stagger_info['stagger_value']} → {new_stagger}", False
            
        except Exception as e:
            logger.error(f"扣除混乱值失败: {e}")
            return False, f"扣除混乱值时出错: {str(e)}", False
        finally:
            conn.close()
    
    @staticmethod
    def process_stagger_turn(character_id: int) -> Tuple[bool, str]:
        """
        处理混乱状态的回合进程
        
        Returns:
            tuple: (是否成功, 状态信息)
        """
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            
            stagger_info = StaggerManager.get_character_stagger_info(character_id)
            if not stagger_info or stagger_info['stagger_status'] != 'staggered':
                return True, ""  # 不在混乱状态，无需处理
            
            character = get_character(character_id)
            char_name = character.get('name', '未知角色') if character else '未知角色'
            
            # 减少剩余回合数
            remaining_turns = stagger_info['stagger_turns_remaining'] - 1
            
            if remaining_turns <= 0:
                # 恢复正常状态，回满混乱值
                cursor.execute("""
                    UPDATE characters 
                    SET stagger_value = max_stagger_value, stagger_status = 'normal', stagger_turns_remaining = 0
                    WHERE id = ?
                """, (character_id,))
                
                conn.commit()
                return True, f"✨ {char_name} 从混乱状态中恢复，混乱值已回满！"
            else:
                # 继续混乱状态，清空行动次数
                cursor.execute("""
                    UPDATE characters 
                    SET stagger_turns_remaining = ?, current_actions = 0
                    WHERE id = ?
                """, (remaining_turns, character_id))
                
                conn.commit()
                return True, f"😵‍💫 {char_name} 仍处于混乱状态，行动次数已清零（剩余 {remaining_turns} 回合）"
            
        except Exception as e:
            logger.error(f"处理混乱状态回合失败: {e}")
            return False, f"处理混乱状态时出错: {str(e)}"
        finally:
            conn.close()
    
    @staticmethod
    def is_staggered(character_id: int) -> bool:
        """检查角色是否处于混乱状态"""
        stagger_info = StaggerManager.get_character_stagger_info(character_id)
        return stagger_info and stagger_info['stagger_status'] == 'staggered'
    
    @staticmethod
    def get_stagger_damage_multiplier(character_id: int) -> float:
        """获取混乱状态的伤害倍率"""
        if StaggerManager.is_staggered(character_id):
            return 2.0  # 混乱状态下受到200%伤害
        return 1.0
    
    @staticmethod
    def reset_character_stagger(character_id: int) -> bool:
        """重置角色的混乱状态"""
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            
            cursor.execute("""
                UPDATE characters 
                SET stagger_value = max_stagger_value, stagger_status = 'normal', stagger_turns_remaining = 0
                WHERE id = ?
            """, (character_id,))
            
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"重置角色混乱状态失败: {e}")
            return False
        finally:
            conn.close()
    
    @staticmethod
    def update_persona_stagger(character_id: int, persona_name: str, character_name: str) -> bool:
        """根据人格更新角色的混乱值"""
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            
            # 获取人格的混乱值配置
            cursor.execute("""
                SELECT stagger_value, max_stagger_value
                FROM personas 
                WHERE character_name = ? AND name = ?
            """, (character_name, persona_name))
            
            result = cursor.fetchone()
            if result:
                stagger_value, max_stagger_value = result
                
                # 更新角色的混乱值
                cursor.execute("""
                    UPDATE characters 
                    SET stagger_value = ?, max_stagger_value = ?
                    WHERE id = ?
                """, (stagger_value, max_stagger_value, character_id))
                
                conn.commit()
                return True
            
            return False
        except Exception as e:
            logger.error(f"更新人格混乱值失败: {e}")
            return False
        finally:
            conn.close()

# 全局混乱值管理器实例
stagger_manager = StaggerManager()
