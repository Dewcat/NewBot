"""
情感系统核心模块
管理角色的情感等级、情感硬币、情感效果等
"""
import logging
import random
from typing import Dict, List, Tuple, Optional
from database.queries import get_character, get_db_connection
from character.status_effects import add_status_effect

logger = logging.getLogger(__name__)

class EmotionSystem:
    """情感系统管理器"""
    
    # 情感等级升级所需硬币数
    UPGRADE_REQUIREMENTS = {
        1: 3,
        2: 3, 
        3: 5,
        4: 7,
        5: 9
    }
    
    # 正面情感升级效果池
    POSITIVE_EMOTION_EFFECTS = [
        {
            'type': 'buff',
            'name': 'strong',
            'intensity': 1,
            'description': '每回合开始时获得1级强壮'
        }
    ]
    
    # 负面情感升级效果池  
    NEGATIVE_EMOTION_EFFECTS = [
        {
            'type': 'buff',
            'name': 'guard',
            'intensity': 1,
            'description': '每回合开始时获得1级守护'
        }
    ]

    @classmethod
    def add_emotion_coins(cls, character_id: int, positive_coins: int = 0, negative_coins: int = 0, source: str = "") -> Dict:
        """
        为角色添加情感硬币
        
        Args:
            character_id: 角色ID
            positive_coins: 正面情感硬币数量
            negative_coins: 负面情感硬币数量
            source: 硬币来源描述
            
        Returns:
            dict: 包含添加结果和升级信息
        """
        character = get_character(character_id)
        if not character:
            return {'success': False, 'message': '角色不存在'}
        
        # 获取当前情感数据
        current_level = character.get('emotion_level', 0)
        current_positive = character.get('positive_emotion_coins', 0)
        current_negative = character.get('negative_emotion_coins', 0)
        pending_upgrade = character.get('pending_emotion_upgrade', 0)
        
        # 如果已达到最大等级，不再添加硬币
        if current_level >= 5:
            return {
                'success': True,
                'message': '角色已达到最大情感等级，不再获得情感硬币',
                'coins_added': False,
                'upgrade_pending': False
            }
        
        # 如果已经有待升级状态，不再添加硬币
        if pending_upgrade > 0:
            return {
                'success': True,
                'message': '角色已有待升级情感等级，本回合不再获得情感硬币',
                'coins_added': False,
                'upgrade_pending': True
            }
        
        # 添加硬币
        new_positive = current_positive + positive_coins
        new_negative = current_negative + negative_coins
        
        # 检查是否满足升级条件
        target_level = current_level + 1
        required_coins = cls.UPGRADE_REQUIREMENTS.get(target_level, float('inf'))
        
        total_coins = new_positive + new_negative
        upgrade_ready = total_coins >= required_coins
        
        # 更新数据库
        conn = get_db_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                UPDATE characters 
                SET positive_emotion_coins = ?, 
                    negative_emotion_coins = ?,
                    pending_emotion_upgrade = ?
                WHERE id = ?
            ''', (new_positive, new_negative, 1 if upgrade_ready else 0, character_id))
            
            # 记录硬币获得历史
            cursor.execute('''
                INSERT INTO emotion_coin_log (character_id, positive_coins, negative_coins, source, total_after)
                VALUES (?, ?, ?, ?, ?)
            ''', (character_id, positive_coins, negative_coins, source, total_coins))
            
            conn.commit()
            
            result = {
                'success': True,
                'coins_added': True,
                'positive_coins_added': positive_coins,
                'negative_coins_added': negative_coins,
                'total_positive': new_positive,
                'total_negative': new_negative,
                'upgrade_pending': upgrade_ready,
                'target_level': target_level if upgrade_ready else None,
                'message': f"获得了{positive_coins}个正面情感硬币，{negative_coins}个负面情感硬币"
            }
            
            if upgrade_ready:
                result['message'] += f"，准备升级到{target_level}级！"
                
            return result
            
        except Exception as e:
            conn.rollback()
            logger.error(f"添加情感硬币失败: {e}")
            return {'success': False, 'message': f'添加情感硬币失败: {e}'}
        finally:
            conn.close()

    @classmethod
    def process_turn_start_emotion_upgrades(cls) -> List[str]:
        """
        处理回合开始时的情感等级升级
        
        Returns:
            list: 升级消息列表
        """
        messages = []
        conn = get_db_connection()
        cursor = conn.cursor()
        
        try:
            # 查找所有待升级的角色
            cursor.execute('''
                SELECT id, name, emotion_level, positive_emotion_coins, 
                       negative_emotion_coins, pending_emotion_upgrade
                FROM characters 
                WHERE pending_emotion_upgrade = 1
            ''')
            
            pending_characters = cursor.fetchall()
            
            for char_data in pending_characters:
                char_id, name, current_level, pos_coins, neg_coins, _ = char_data
                
                # 执行升级
                upgrade_result = cls._execute_emotion_upgrade(
                    char_id, name, current_level, pos_coins, neg_coins
                )
                
                if upgrade_result['success']:
                    messages.append(upgrade_result['message'])
            
            return messages
            
        except Exception as e:
            logger.error(f"处理情感升级失败: {e}")
            return [f"处理情感升级时出错: {e}"]
        finally:
            conn.close()

    @classmethod
    def _execute_emotion_upgrade(cls, character_id: int, name: str, current_level: int, 
                                pos_coins: int, neg_coins: int) -> Dict:
        """执行单个角色的情感升级"""
        new_level = current_level + 1
        
        # 确定升级类型（基于硬币数量）
        upgrade_type = "positive" if pos_coins > neg_coins else "negative"
        
        # 选择升级效果
        if upgrade_type == "positive":
            effect_pool = cls.POSITIVE_EMOTION_EFFECTS
        else:
            effect_pool = cls.NEGATIVE_EMOTION_EFFECTS
        
        selected_effect = random.choice(effect_pool)
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        try:
            # 更新角色等级和清空硬币
            cursor.execute('''
                UPDATE characters 
                SET emotion_level = ?,
                    positive_emotion_coins = 0,
                    negative_emotion_coins = 0,
                    pending_emotion_upgrade = 0
                WHERE id = ?
            ''', (new_level, character_id))
            
            # 降低所有技能冷却1回合
            cls._reduce_all_skill_cooldowns(character_id)
            
            # 添加情感效果
            cls._add_emotion_effect(character_id, selected_effect)
            
            # 记录升级历史
            cursor.execute('''
                INSERT INTO emotion_level_history 
                (character_id, old_level, new_level, upgrade_type, positive_coins, negative_coins)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (character_id, current_level, new_level, upgrade_type, pos_coins, neg_coins))
            
            conn.commit()
            
            # 构建升级消息
            upgrade_msg = f"🎭 {name} 情感等级提升到 {new_level} 级！"
            upgrade_msg += f"\n✨ 获得效果：{selected_effect['description']}"
            upgrade_msg += f"\n⏰ 所有技能冷却时间-1回合"
            
            return {
                'success': True,
                'message': upgrade_msg,
                'new_level': new_level,
                'effect': selected_effect
            }
            
        except Exception as e:
            conn.rollback()
            logger.error(f"执行情感升级失败: {e}")
            return {'success': False, 'message': f'升级失败: {e}'}
        finally:
            conn.close()

    @classmethod
    def _reduce_all_skill_cooldowns(cls, character_id: int):
        """降低角色所有技能冷却时间1回合"""
        try:
            from database.queries import get_character_cooldowns, update_character_cooldowns
            
            cooldowns = get_character_cooldowns(character_id)
            for skill_id, current_cooldown in cooldowns.items():
                new_cooldown = max(0, current_cooldown - 1)
                update_character_cooldowns(character_id, {skill_id: new_cooldown})
                
        except Exception as e:
            logger.error(f"降低技能冷却失败: {e}")

    @classmethod
    def _add_emotion_effect(cls, character_id: int, effect_config: Dict):
        """添加情感升级效果"""
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO character_emotion_effects 
                (character_id, effect_type, effect_name, intensity)
                VALUES (?, ?, ?, ?)
            ''', (character_id, effect_config['type'], effect_config['name'], effect_config['intensity']))
            
            conn.commit()
            
        except Exception as e:
            logger.error(f"添加情感效果失败: {e}")
        finally:
            conn.close()

    @classmethod
    def apply_turn_start_emotion_effects(cls, character_id: int) -> List[str]:
        """应用回合开始时的情感效果"""
        messages = []
        conn = get_db_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                SELECT effect_type, effect_name, intensity
                FROM character_emotion_effects
                WHERE character_id = ?
            ''', (character_id,))
            
            effects = cursor.fetchall()
            
            for effect_type, effect_name, intensity in effects:
                if effect_type == 'buff':
                    # 添加buff状态效果
                    success = add_status_effect(character_id, 'buff', effect_name, intensity, 1)
                    if success:
                        effect_names = {
                            'strong': '强壮',
                            'guard': '守护'
                        }
                        display_name = effect_names.get(effect_name, effect_name)
                        messages.append(f"情感效果：获得{intensity}层{display_name}状态")
            
            return messages
            
        except Exception as e:
            logger.error(f"应用情感效果失败: {e}")
            return []
        finally:
            conn.close()

    @classmethod
    def check_skill_emotion_requirement(cls, character_id: int, skill_info: Dict) -> Tuple[bool, str]:
        """
        检查技能的情感等级要求
        
        Returns:
            tuple: (是否满足要求, 错误信息)
        """
        required_level = skill_info.get('required_emotion_level', 0)
        if required_level <= 0:
            return True, ""
        
        character = get_character(character_id)
        if not character:
            return False, "角色不存在"
        
        current_level = character.get('emotion_level', 0)
        
        if current_level < required_level:
            return False, f"此技能需要情感等级{required_level}级，当前等级{current_level}级"
        
        return True, ""

    @classmethod
    def get_emotion_coins_from_dice_roll(cls, dice_results: List[int], dice_sides: int) -> Tuple[int, int]:
        """
        根据骰子结果计算获得的情感硬币
        
        Args:
            dice_results: 骰子结果列表
            dice_sides: 骰子面数
            
        Returns:
            tuple: (正面硬币数, 负面硬币数)
        """
        positive_coins = sum(1 for result in dice_results if result == dice_sides)
        negative_coins = sum(1 for result in dice_results if result == 1)
        
        return positive_coins, negative_coins

# 情感系统的便捷函数
emotion_system = EmotionSystem()

def add_emotion_coins(character_id: int, positive: int = 0, negative: int = 0, source: str = "") -> Dict:
    """添加情感硬币的便捷函数"""
    return emotion_system.add_emotion_coins(character_id, positive, negative, source)

def process_emotion_upgrades() -> List[str]:
    """处理情感升级的便捷函数"""
    return emotion_system.process_turn_start_emotion_upgrades()

def apply_emotion_effects(character_id: int) -> List[str]:
    """应用情感效果的便捷函数"""
    return emotion_system.apply_turn_start_emotion_effects(character_id)

def check_skill_emotion_requirement(character_id: int, skill_info: Dict) -> Tuple[bool, str]:
    """检查技能情感要求的便捷函数"""
    return emotion_system.check_skill_emotion_requirement(character_id, skill_info)
