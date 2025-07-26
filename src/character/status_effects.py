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

def add_status_effect(character_id: int, effect_type: str, effect_name: str, 
                     intensity: int, duration: int) -> bool:
    """添加状态效果到角色
    
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

def process_turn_end_effects(character_id: int) -> List[str]:
    """处理回合结束时的状态效果
    
    Returns:
        List[str]: 效果处理的描述信息
    """
    effects = get_character_status_effects(character_id)
    messages = []
    character = get_character(character_id)
    
    if not character:
        return messages
    
    for effect in effects:
        message = process_single_effect_turn_end(character, effect)
        if message:
            messages.append(message)
        
        # 减少持续时间（除了特殊效果）
        if effect.effect_name not in ['rupture', 'bleeding', 'shield']:
            new_duration = effect.duration - 1
            if new_duration <= 0:
                # 状态效果即将结束，添加通知
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

def process_single_effect_turn_end(character: Dict, effect: StatusEffect) -> Optional[str]:
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
        # 中毒：按强度*1%体力扣血
        damage = int(character['max_health'] * effect.intensity / 100)
        new_health = max(0, character['health'] - damage)
        update_character_health(character_id, new_health)
        return f"☠️ {character_name} 受到中毒伤害 {damage} 点"
    
    return None

def process_hit_effects(character_id: int, incoming_damage: int) -> Tuple[int, List[str]]:
    """处理受击时的状态效果
    
    Args:
        character_id: 角色ID
        incoming_damage: 即将受到的伤害
    
    Returns:
        Tuple[int, List[str]]: (修改后的伤害, 效果描述信息)
    """
    effects = get_character_status_effects(character_id)
    messages = []
    final_damage = incoming_damage
    character = get_character(character_id)
    
    if not character:
        return final_damage, messages
    
    character_name = character['name']
    
    for effect in effects:
        if effect.effect_name == 'guard':
            # 守护：受到最终伤害-(层数*10%)
            damage_reduction = effect.duration * 0.1
            reduced_damage = int(final_damage * damage_reduction)
            final_damage = max(0, final_damage - reduced_damage)
            if reduced_damage > 0:
                messages.append(f"🛡️ {character_name} 的守护减免了 {reduced_damage} 点伤害")
        
        elif effect.effect_name == 'vulnerable':
            # 易伤：受到最终伤害+(层数*10%)
            damage_increase = effect.duration * 0.1
            increased_damage = int(final_damage * damage_increase)
            final_damage += increased_damage
            if increased_damage > 0:
                messages.append(f"💔 {character_name} 的易伤增加了 {increased_damage} 点伤害")
        
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
            # 强壮：攻击技能最终伤害+(层数*10%)
            damage_bonus = int(final_damage * effect.duration * 0.1)
            final_damage += damage_bonus
            if damage_bonus > 0:
                messages.append(f"💪 {character_name} 的强壮增加了 {damage_bonus} 点伤害")
        
        elif effect.effect_name == 'weak':
            # 虚弱：攻击技能最终伤害-(层数*10%)
            damage_reduction = int(final_damage * effect.duration * 0.1)
            final_damage = max(0, final_damage - damage_reduction)
            if damage_reduction > 0:
                messages.append(f"😵 {character_name} 的虚弱减少了 {damage_reduction} 点伤害")
    
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
        'shield': '🛡️'
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
        
        if effect.effect_name == 'shield':
            text = f"{icon}护盾({effect.intensity})"
        else:
            text = f"{icon}{effect.effect_name}({effect.intensity}/{effect.duration})"
        
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
