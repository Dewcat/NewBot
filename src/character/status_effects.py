"""状态效果管理模块

实现角色的增益(buff)和减益(debuff)系统
包括状态效果的添加、更新、移除和回合处理
"""

import logging
import json
from typing import Dict, List, Optional, Tuple
from database.db_connection import get_db_connection
from database.queries import get_character, update_character_health

logger = logging.getLogger(__name__)

class StatusEffect:
    """状态效果类"""
    
    def __init__(self, effect_type: str, effect_name: str, intensity: int, duration: int):
        self.effect_type = effect_type  # buff 或 debuff
        self.effect_name = effect_name  # 具体状态名称
        self.intensity = intensity      # 强度
        self.duration = duration        # 层数/持续回合
    
    def to_dict(self) -> Dict:
        return {
            'effect_type': self.effect_type,
            'effect_name': self.effect_name,
            'intensity': self.intensity,
            'duration': self.duration
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'StatusEffect':
        return cls(
            effect_type=data['effect_type'],
            effect_name=data['effect_name'],
            intensity=data['intensity'],
            duration=data['duration']
        )

def get_character_status_effects(character_id: int) -> List[StatusEffect]:
    """获取角色的所有状态效果"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            SELECT effect_type, effect_name, intensity, duration
            FROM character_status_effects 
            WHERE character_id = ?
        """, (character_id,))
        
        effects = []
        for row in cursor.fetchall():
            effects.append(StatusEffect(
                effect_type=row[0],
                effect_name=row[1],
                intensity=row[2],
                duration=row[3]
            ))
        
        return effects
    except Exception as e:
        logger.error(f"获取角色状态效果时出错: {e}")
        return []
    finally:
        conn.close()

def get_hardblood_amount(character_id: int) -> int:
    """获取角色的硬血数量"""
    try:
        status_effects = get_character_status_effects(character_id)
        for effect in status_effects:
            if effect.effect_type == 'hardblood':
                return effect.intensity
        return 0
    except Exception as e:
        logger.error(f"获取硬血数量失败: {e}")
        return 0

def reduce_paralysis_stacks(character_id: int, dice_count: int) -> bool:
    """减少麻痹层数，每个归零骰子减少1层"""
    try:
        status_effects = get_character_status_effects(character_id)
        for effect in status_effects:
            if effect.effect_name == 'paralysis':
                new_intensity = max(0, effect.intensity - dice_count)
                
                logger.info(f"角色{character_id}麻痹层数: {effect.intensity} → {new_intensity} (减少{dice_count}层)")
                
                if new_intensity <= 0:
                    # 麻痹层数用完，移除状态
                    remove_status_effect(character_id, 'paralysis')
                    logger.info(f"角色{character_id}的麻痹状态已移除")
                    return True
                else:
                    # 更新麻痹层数 - 使用effect_name作为条件
                    conn = get_db_connection()
                    cursor = conn.cursor()
                    try:
                        cursor.execute("""
                            UPDATE character_status_effects
                            SET intensity = ?
                            WHERE character_id = ? AND effect_name = ?
                        """, (new_intensity, character_id, 'paralysis'))
                        conn.commit()
                        logger.info(f"角色{character_id}麻痹层数更新为{new_intensity}")
                        return True
                    except Exception as e:
                        logger.error(f"更新麻痹层数失败: {e}")
                        conn.rollback()
                        return False
                    finally:
                        conn.close()
        return False
    except Exception as e:
        logger.error(f"减少麻痹层数失败: {e}")
        return False

def consume_hardblood(character_id: int, amount: int) -> int:
    """消耗硬血，返回实际消耗的数量"""
    try:
        current_hardblood = get_hardblood_amount(character_id)
        if current_hardblood == 0:
            return 0
        
        # 计算实际消耗量
        actual_consume = min(amount, current_hardblood)
        
        # 减少硬血数量
        new_amount = current_hardblood - actual_consume
        
        if new_amount <= 0:
            # 移除硬血状态
            remove_status_effect(character_id, '硬血')  # 使用effect_name而不是effect_type
        else:
            # 更新硬血数量
            update_status_effect_intensity(character_id, 'hardblood', new_amount)
        
        return actual_consume
    except Exception as e:
        logger.error(f"消耗硬血失败: {e}")
        return 0

def add_status_effect(character_id: int, effect_type: str, effect_name: str, 
                     intensity: int, duration: int, immediate_effect: bool = False) -> bool:
    """添加状态效果到角色
    
    Args:
        character_id: 角色ID
        effect_type: 效果类型
        effect_name: 效果名称
        intensity: 强度
        duration: 持续时间
        immediate_effect: 是否立即生效（用于回合中获得的效果）
    
    如果角色已有同名状态效果，则强度取较高值，层数累加
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # 检查是否已有同名状态效果
        cursor.execute("""
            SELECT intensity, duration FROM character_status_effects
            WHERE character_id = ? AND effect_name = ?
        """, (character_id, effect_name))
        
        existing = cursor.fetchone()
        
        # 特殊处理加速效果
        if effect_name == 'haste':
            return _handle_haste_effect(character_id, effect_type, intensity, duration, 
                                      immediate_effect, existing, cursor, conn)
        
        if existing:
            # 已有同名效果，强度取较高值，层数累加
            old_intensity, old_duration = existing
            new_intensity = max(old_intensity, intensity)
            new_duration = old_duration + duration
            
            cursor.execute("""
                UPDATE character_status_effects
                SET intensity = ?, duration = ?
                WHERE character_id = ? AND effect_name = ?
            """, (new_intensity, new_duration, character_id, effect_name))
        else:
            # 新增状态效果
            cursor.execute("""
                INSERT INTO character_status_effects 
                (character_id, effect_type, effect_name, intensity, duration)
                VALUES (?, ?, ?, ?, ?)
            """, (character_id, effect_type, effect_name, intensity, duration))
        
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"添加状态效果时出错: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()

def _handle_haste_effect(character_id: int, effect_type: str, intensity: int, duration: int,
                        immediate_effect: bool, existing, cursor, conn) -> bool:
    """处理加速效果的特殊逻辑
    
    新逻辑：
    - 获得时立即+1行动次数及对应上限
    - 持续期间保持+1行动次数
    - 回合结束减少1层
    - 效果消失时恢复为1行动次数
    """
    
    if existing:
        # 已有加速效果，只延长持续时间，不叠加强度
        old_intensity, old_duration = existing
        new_duration = old_duration + duration
        # 加速强度始终为1，不叠加
        
        cursor.execute("""
            UPDATE character_status_effects
            SET duration = ?
            WHERE character_id = ? AND effect_name = 'haste'
        """, (new_duration, character_id))
        
        conn.commit()
    else:
        # 新增加速效果，强度固定为1
        cursor.execute("""
            INSERT INTO character_status_effects 
            (character_id, effect_type, effect_name, intensity, duration)
            VALUES (?, ?, 'haste', 1, ?)
        """, (character_id, effect_type, duration))
        
        conn.commit()
        
        # 立即增加行动次数和行动上限
        _update_haste_actions_immediately(character_id, 1)  # +1
    
    return True

def _update_haste_actions_immediately(character_id: int, bonus_actions: int):
    """立即更新角色行动次数和行动上限（用于加速效果）
    
    Args:
        character_id: 角色ID
        bonus_actions: 额外行动次数
    """
    from database.queries import get_character
    
    # 使用独立连接避免数据库锁定
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        character = get_character(character_id)
        if character:
            # 增加当前行动次数
            current_actions = character.get('current_actions', 0)
            new_current_actions = current_actions + bonus_actions
            
            # 增加每回合行动次数上限
            actions_per_turn = character.get('actions_per_turn', 1)
            new_actions_per_turn = actions_per_turn + bonus_actions
            
            cursor.execute("""
                UPDATE characters
                SET current_actions = ?, actions_per_turn = ?
                WHERE id = ?
            """, (new_current_actions, new_actions_per_turn, character_id))
            
            conn.commit()
            logger.info(f"角色 {character_id} 获得加速：当前行动 {current_actions} → {new_current_actions}, 每回合行动 {actions_per_turn} → {new_actions_per_turn}")
    except Exception as e:
        logger.error(f"更新加速行动次数时出错: {e}")
        conn.rollback()
    finally:
        conn.close()

def _remove_haste_actions(character_id: int, bonus_actions: int):
    """移除角色的加速行动次数和行动上限（用于加速效果消失）
    
    Args:
        character_id: 角色ID
        bonus_actions: 要移除的额外行动次数
    """
    from database.queries import get_character
    
    # 使用独立连接避免数据库锁定
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        character = get_character(character_id)
        if character:
            # 减少当前行动次数（但不能低于0）
            current_actions = character.get('current_actions', 0)
            new_current_actions = max(0, current_actions - bonus_actions)
            
            # 减少每回合行动次数上限（但不能低于1）
            actions_per_turn = character.get('actions_per_turn', 1)
            new_actions_per_turn = max(1, actions_per_turn - bonus_actions)
            
            cursor.execute("""
                UPDATE characters
                SET current_actions = ?, actions_per_turn = ?
                WHERE id = ?
            """, (new_current_actions, new_actions_per_turn, character_id))
            
            conn.commit()
            logger.info(f"角色 {character_id} 失去加速：当前行动 {current_actions} → {new_current_actions}, 每回合行动 {actions_per_turn} → {new_actions_per_turn}")
    except Exception as e:
        logger.error(f"移除加速行动次数时出错: {e}")
        conn.rollback()
    finally:
        conn.close()

def _update_actions_immediately(character_id: int):
    """立即更新角色行动次数（旧版本，保留兼容性）"""
    _update_haste_actions_immediately(character_id, 1)

def add_haste_immediate(character_id: int, duration: int = 1) -> bool:
    """立即获得加速效果（新版逻辑：总是立即生效）
    
    Args:
        character_id: 角色ID
        duration: 持续回合数
    
    Returns:
        bool: 是否成功添加
    """
    return add_status_effect(character_id, 'buff', 'haste', 1, duration, immediate_effect=True)

def add_haste_next_turn(character_id: int, duration: int = 1) -> bool:
    """获得加速效果（新版逻辑：总是立即生效，此函数保留兼容性）
    
    Args:
        character_id: 角色ID  
        duration: 持续回合数
    
    Returns:
        bool: 是否成功添加
    """
    return add_status_effect(character_id, 'buff', 'haste', 1, duration, immediate_effect=True)

def remove_status_effect(character_id: int, effect_name: str) -> bool:
    """移除角色的指定状态效果"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            DELETE FROM character_status_effects
            WHERE character_id = ? AND effect_name = ?
        """, (character_id, effect_name))
        
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"移除状态效果时出错: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()

def update_status_effect_duration(character_id: int, effect_name: str, new_duration: int) -> bool:
    """更新状态效果的持续时间"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        if new_duration <= 0:
            # 持续时间为0或负数，移除效果
            cursor.execute("""
                DELETE FROM character_status_effects
                WHERE character_id = ? AND effect_name = ?
            """, (character_id, effect_name))
        else:
            cursor.execute("""
                UPDATE character_status_effects
                SET duration = ?
                WHERE character_id = ? AND effect_name = ?
            """, (new_duration, character_id, effect_name))
        
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"更新状态效果持续时间时出错: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()

def update_status_effect_intensity(character_id: int, effect_type: str, new_intensity: int) -> bool:
    """更新状态效果的强度"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            UPDATE character_status_effects
            SET intensity = ?
            WHERE character_id = ? AND effect_type = ?
        """, (new_intensity, character_id, effect_type))
        
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"更新状态效果强度时出错: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()

def clear_all_status_effects(character_id: int) -> bool:
    """清除角色的所有状态效果"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            DELETE FROM character_status_effects
            WHERE character_id = ?
        """, (character_id,))
        
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"清除状态效果时出错: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()

def process_end_turn_effects(character_id: int) -> List[str]:
    """处理回合结束时的状态效果
    
    Returns:
        List[str]: 效果处理的描述信息
    """
    effects = get_character_status_effects(character_id)
    messages = []
    character = get_character(character_id)
    
    if not character:
        return messages
    
    # 记录初始生命值
    initial_health = character['health']
    character_knocked_down = False
    
    for effect in effects:
        # 如果角色已经倒下，跳过剩余效果处理
        if character_knocked_down:
            break
            
        # 获取最新的角色数据
        current_character = get_character(character_id)
        if not current_character:
            break
            
        message = process_single_effect_end_turn(current_character, effect)
        if message:
            messages.append(message)
            
            # 每次处理效果后检查角色是否倒下
            updated_character = get_character(character_id)
            if updated_character and updated_character['health'] <= 0 and initial_health > 0:
                # 角色刚刚倒下，只保留倒下信息
                character_knocked_down = True
                messages = [f"💀 {character['name']} 倒下了！"]
                break
    
    # 如果角色没有倒下，处理状态效果持续时间
    if not character_knocked_down:
        for effect in effects:
            # 减少持续时间（除了特殊效果和不会自动衰减的效果）
            if effect.effect_name not in ['rupture', 'bleeding', 'shield', 'cooldown_reduction', 'paralysis', 'hardblood', 'weaken_aura']:
                new_duration = effect.duration - 1
                if new_duration <= 0:
                    # 状态效果即将结束，添加通知
                    if effect.effect_name == 'haste':
                        # 加速效果结束时，移除额外的行动次数
                        _remove_haste_actions(character_id, 1)
                        messages.append(f"⏰ {character['name']} 的加速状态结束")
                    else:
                        effect_display_names = {
                            'strong': '强壮',
                            'breathing': '呼吸法', 
                            'guard': '守护',
                            'burn': '烧伤',
                            'poison': '中毒',
                            'weak': '虚弱',
                            'vulnerable': '易伤'
                        }
                        effect_display_name = effect_display_names.get(effect.effect_name, effect.effect_name)
                        messages.append(f"⏰ {character['name']} 的 {effect_display_name} 状态结束")
                update_status_effect_duration(character_id, effect.effect_name, new_duration)
    
    return messages

def process_start_turn_effects(character_id: int) -> List[str]:
    """处理回合开始时的状态效果
    
    新版加速逻辑：加速效果在获得时就立即生效，回合开始不需要特殊处理
    
    Returns:
        List[str]: 效果处理的描述信息
    """
    effects = get_character_status_effects(character_id)
    messages = []
    character = get_character(character_id)
    
    if not character:
        return messages
    
    character_name = character['name']
    
    # 新版加速逻辑：不在回合开始时处理加速
    # 加速效果在获得时就立即增加行动次数和上限
    # 在回合结束时减少持续时间，消失时恢复行动次数
    
    # 这里可以处理其他需要在回合开始时触发的状态效果
    # 目前暂时保留空函数，以便未来扩展
    
    return messages

def process_single_effect_end_turn(character: Dict, effect: StatusEffect) -> Optional[str]:
    """处理单个状态效果的回合结束效果"""
    character_id = character['id']
    character_name = character['name']
    
    if effect.effect_name == 'burn':
        # 烧伤：按强度*1点扣血
        damage = effect.intensity * 1
        new_health = max(0, character['health'] - damage)
        update_character_health(character_id, new_health)
        return f"🔥 {character_name} 受到烧伤伤害 {damage} 点"
    
    elif effect.effect_name == 'poison':
        # 中毒：按强度*1%当前生命值扣血
        damage = int(character['health'] * effect.intensity / 100)
        damage = max(1, damage)  # 至少造成1点伤害
        new_health = max(0, character['health'] - damage)
        update_character_health(character_id, new_health)
        return f"☠️ {character_name} 受到中毒伤害 {damage} 点"
    
    elif effect.effect_name == 'haste':
        # 加速效果在回合开始时处理，这里什么都不做
        return None
    
    elif effect.effect_name == 'dark_domain':
        # 黑夜领域：回合结束时触发复杂效果
        return process_dark_domain_end_turn(character_id, character_name, effect.intensity, effect.duration)
    
    elif effect.effect_name == 'weaken_aura':
        # 削弱光环：回合结束时为敌方全体增加虚弱和易伤
        return process_weaken_aura_end_turn(character_id, character_name, effect.intensity, effect.duration)
    
    elif effect.effect_name == 'paralysis':
        # 麻痹：不会自动衰减，只在受到技能影响时减少层数
        return None
    
    elif effect.effect_name == 'hardblood':
        # 硬血：不会自动衰减，只能被技能消耗
        return None
    
    return None

def process_dark_domain_end_turn(character_id: int, character_name: str, intensity: int, duration: int) -> Optional[str]:
    """处理黑夜领域的回合结束效果"""
    messages = []
    
    try:
        # 添加6级1层强壮
        add_status_effect(character_id, 'buff', 'strong', 6, 1)
        messages.append(f"🌑 {character_name} 的黑夜领域赋予了 6级强壮")
        
        # 添加6级1层易伤
        add_status_effect(character_id, 'debuff', 'vulnerable', 6, 1)  
        messages.append(f"🌑 {character_name} 的黑夜领域也带来了 6级易伤")
        
        # 添加1级1层加速（回合结束获得，下回合开始生效）
        add_status_effect(character_id, 'buff', 'haste', 1, 1, immediate_effect=False)
        messages.append(f"🌑 {character_name} 的黑夜领域提供了 1级加速")
        
        # 添加666枚负面情感硬币
        from character.emotion_system import add_emotion_coins
        coin_result = add_emotion_coins(character_id, 0, 666, "黑夜领域效果")
        if coin_result.get('success'):
            messages.append(f"🌑 {character_name} 从黑夜领域获得了 666枚负面情感硬币")
            
        return " → ".join(messages)
        
    except Exception as e:
        logger.error(f"处理黑夜领域效果时出错: {e}")
        return f"🌑 {character_name} 的黑夜领域效果触发"

def process_weaken_aura_end_turn(character_id: int, character_name: str, intensity: int, duration: int) -> Optional[str]:
    """处理削弱光环的回合结束效果"""
    messages = []
    
    try:
        # 获取角色信息以确定敌方类型
        from database.queries import get_character, get_characters_by_type
        character = get_character(character_id)
        if not character:
            return None
        
        # 确定敌方类型（与光环拥有者相反）
        owner_type = character['character_type']
        enemy_type = "enemy" if owner_type == "friendly" else "friendly"
        
        # 获取战斗中的敌方角色
        enemy_characters = get_characters_by_type(enemy_type, in_battle=True)
        
        if not enemy_characters:
            return f"💜 {character_name} 的削弱光环未找到目标"
        
        # 为每个敌方角色添加5级1层虚弱和5级1层易伤
        affected_enemies = []
        for enemy in enemy_characters:
            if enemy['health'] > 0:  # 只影响存活的敌人
                # 添加5级1层虚弱
                add_status_effect(enemy['id'], 'debuff', 'weak', 5, 1)
                # 添加5级1层易伤
                add_status_effect(enemy['id'], 'debuff', 'vulnerable', 5, 1)
                affected_enemies.append(enemy['name'])
        
        if affected_enemies:
            enemy_list = "、".join(affected_enemies)
            return f"💜 {character_name} 的削弱光环影响了 {enemy_list}，施加了 5级虚弱 和 5级易伤"
        else:
            return f"💜 {character_name} 的削弱光环未找到有效目标"
        
    except Exception as e:
        logger.error(f"处理削弱光环效果时出错: {e}")
        return f"💜 {character_name} 的削弱光环效果触发"

def check_dark_domain_death_immunity(character_id: int, incoming_damage: int) -> Tuple[bool, int, List[str]]:
    """检查黑夜领域的死亡免疫效果
    
    Returns:
        Tuple[bool, int, List[str]]: (是否免疫死亡, 修改后的伤害, 效果消息)
    """
    effects = get_character_status_effects(character_id)
    messages = []
    character = get_character(character_id)
    
    if not character:
        return False, incoming_damage, messages
    
    character_name = character['name']
    current_health = character['health']
    
    # 检查是否有黑夜领域效果且即将死亡
    for effect in effects:
        if effect.effect_name == 'dark_domain' and effect.duration > 0:
            if current_health - incoming_damage <= 0:
                # 触发死亡免疫
                messages.append(f"🛡️ {character_name} 的黑夜领域保护生效！免疫致命伤害")
                
                # 将生命值设为1
                update_character_health(character_id, 1)
                
                # 清空所有黑夜领域层数
                remove_status_effect(character_id, 'dark_domain')
                messages.append(f"🌑 {character_name} 的黑夜领域消散了...")
                
                return True, 0, messages  # 免疫所有伤害
    
    return False, incoming_damage, messages

def process_hit_effects(character_id: int, incoming_damage: int) -> Tuple[int, List[str]]:
    """处理受击时的状态效果
    
    Args:
        character_id: 角色ID
        incoming_damage: 即将受到的伤害
    
    Returns:
        Tuple[int, List[str]]: (修改后的伤害, 效果描述信息)
    """
    # 首先检查黑夜领域的死亡免疫
    immune, immune_damage, immune_messages = check_dark_domain_death_immunity(character_id, incoming_damage)
    if immune:
        return immune_damage, immune_messages
    
    effects = get_character_status_effects(character_id)
    messages = []
    final_damage = incoming_damage
    character = get_character(character_id)
    
    if not character:
        return final_damage, messages
    
    character_name = character['name']
    
    for effect in effects:
        if effect.effect_name == 'guard':
            # 守护：受到最终伤害-(强度*10%)
            damage_reduction = effect.intensity * 0.1
            reduced_damage = int(final_damage * damage_reduction)
            final_damage = max(0, final_damage - reduced_damage)
            if reduced_damage > 0:
                percent = int(effect.intensity * 10)
                messages.append(f"守护减伤: -{percent}%")
        
        elif effect.effect_name == 'vulnerable':
            # 易伤：受到最终伤害+(强度*10%)
            damage_increase = effect.intensity * 0.1
            increased_damage = int(final_damage * damage_increase)
            final_damage += increased_damage
            if increased_damage > 0:
                percent = int(effect.intensity * 10)
                messages.append(f"易伤增伤: +{percent}%")
        
        elif effect.effect_name == 'shield':
            # 护盾：受到最终伤害-护盾强度，伤害结算后护盾强度会减少
            shield_block = min(final_damage, effect.intensity)
            final_damage = max(0, final_damage - shield_block)
            new_shield = effect.intensity - shield_block
            
            if shield_block > 0:
                messages.append(f"🛡️ {character_name} 的护盾抵消了 {shield_block} 点伤害")
            
            if new_shield <= 0:
                remove_status_effect(character_id, 'shield')
                messages.append(f"💥 {character_name} 的护盾被击破")
            else:
                # 更新护盾强度
                conn = get_db_connection()
                cursor = conn.cursor()
                try:
                    cursor.execute("""
                        UPDATE character_status_effects
                        SET intensity = ?
                        WHERE character_id = ? AND effect_name = 'shield'
                    """, (new_shield, character_id))
                    conn.commit()
                except Exception as e:
                    logger.error(f"更新护盾强度时出错: {e}")
                finally:
                    conn.close()
        
        elif effect.effect_name == 'rupture':
            # 破裂：在受击时按强度*1点扣血，并减少1层数
            rupture_damage = effect.intensity * 1
            new_health = max(0, character['health'] - rupture_damage)
            update_character_health(character_id, new_health)
            messages.append(f"💥 {character_name} 受到破裂伤害 {rupture_damage} 点")
            
            # 减少层数
            new_duration = effect.duration - 1
            if new_duration <= 0:
                messages.append(f"⏰ {character_name} 的破裂状态结束")
            update_status_effect_duration(character_id, 'rupture', new_duration)
    
    return final_damage, messages

def process_action_effects(character_id: int) -> List[str]:
    """处理行动后的状态效果"""
    effects = get_character_status_effects(character_id)
    messages = []
    character = get_character(character_id)
    
    if not character:
        return messages
    
    character_name = character['name']
    
    for effect in effects:
        if effect.effect_name == 'bleeding':
            # 流血：在行动后按强度*1点扣血，并减少1层数
            bleeding_damage = effect.intensity * 1
            new_health = max(0, character['health'] - bleeding_damage)
            update_character_health(character_id, new_health)
            messages.append(f"🩸 {character_name} 受到流血伤害 {bleeding_damage} 点")
            
            # 减少层数
            new_duration = effect.duration - 1
            if new_duration <= 0:
                messages.append(f"⏰ {character_name} 的流血状态结束")
            update_status_effect_duration(character_id, 'bleeding', new_duration)
    
    return messages

def calculate_damage_modifiers(character_id: int, base_damage: int, is_crit: bool = False) -> Tuple[int, bool, List[str]]:
    """计算状态效果对伤害的修正
    
    Args:
        character_id: 角色ID
        base_damage: 基础伤害
        is_crit: 是否暴击
    
    Returns:
        Tuple[int, bool, List[str]]: (修改后的伤害, 是否暴击, 效果描述信息)
    """
    effects = get_character_status_effects(character_id)
    messages = []
    final_damage = base_damage
    final_crit = is_crit
    character = get_character(character_id)
    
    if not character:
        return final_damage, final_crit, messages
    
    character_name = character['name']
    
    # 计算暴击率影响
    crit_rate_bonus = 0
    for effect in effects:
        if effect.effect_name == 'breathing':
            crit_rate_bonus += effect.intensity
    
    # 如果不是暴击，检查是否因为状态效果而暴击
    if not final_crit and crit_rate_bonus > 0:
        import random
        if random.randint(1, 100) <= crit_rate_bonus:
            final_crit = True
            crit_damage_increase = int(final_damage * 0.2)  # 计算暴击增伤
            final_damage = int(final_damage * 1.2)  # 暴击伤害120%
            messages.append(f"✨ {character_name} 的呼吸法触发暴击！增加了 {crit_damage_increase} 点伤害")
    
    # 计算伤害修正
    for effect in effects:
        if effect.effect_name == 'strong':
            # 强壮：攻击技能最终伤害+(强度*10%)
            damage_bonus = int(final_damage * effect.intensity * 0.1)
            final_damage += damage_bonus
            if damage_bonus > 0:
                percent = int(effect.intensity * 10)
                messages.append(f"强壮增伤: +{percent}%")
        
        elif effect.effect_name == 'weak':
            # 虚弱：攻击技能最终伤害-(强度*10%)
            damage_reduction = int(final_damage * effect.intensity * 0.1)
            final_damage = max(0, final_damage - damage_reduction)
            if damage_reduction > 0:
                percent = int(effect.intensity * 10)
                messages.append(f"虚弱减伤: -{percent}%")
    
    return final_damage, final_crit, messages

def get_status_effects_display(character_id: int) -> str:
    """获取角色状态效果的显示文本"""
    effects = get_character_status_effects(character_id)
    
    if not effects:
        return "无状态效果"
    
    buff_icons = {
        'strong': '💪',
        'breathing': '🫁', 
        'guard': '🛡️',
        'shield': '🛡️',
        'haste': '⚡',
        'cooldown_reduction': '❄️'
    }
    
    debuff_icons = {
        'burn': '🔥',
        'poison': '☠️',
        'rupture': '💥',
        'bleeding': '🩸',
        'weak': '😵',
        'vulnerable': '💔'
    }
    
    buff_texts = []
    debuff_texts = []
    
    for effect in effects:
        icon = buff_icons.get(effect.effect_name) if effect.effect_type == 'buff' else debuff_icons.get(effect.effect_name, '❓')
        
        # 中文名称映射
        effect_display_names = {
            'strong': '强壮',
            'breathing': '呼吸法', 
            'guard': '守护',
            'shield': '护盾',
            'haste': '加速',
            'cooldown_reduction': '冷却缩减',
            'burn': '烧伤',
            'poison': '中毒',
            'rupture': '破裂',
            'bleeding': '流血',
            'weak': '虚弱',
            'vulnerable': '易伤'
        }
        
        effect_name = effect_display_names.get(effect.effect_name, effect.effect_name)
        
        if effect.effect_name == 'shield':
            text = f"{icon}{effect_name}({effect.intensity})"
        else:
            text = f"{icon}{effect_name}({effect.intensity}/{effect.duration})"
        
        if effect.effect_type == 'buff':
            buff_texts.append(text)
        else:
            debuff_texts.append(text)
    
    result_parts = []
    if buff_texts:
        result_parts.append("增益: " + " ".join(buff_texts))
    if debuff_texts:
        result_parts.append("减益: " + " ".join(debuff_texts))
    
    return "\n".join(result_parts) if result_parts else "无状态效果"
