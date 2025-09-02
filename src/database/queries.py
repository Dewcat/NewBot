import logging
import json
from .db_connection import get_db_connection

logger = logging.getLogger(__name__)

# 角色相关查询

def create_character(name="", character_type="friendly", health=100, attack=10, defense=5):
    """创建一个新角色
    
    Args:
        name: 角色名称
        character_type: 角色类型，'friendly'表示友方角色，'enemy'表示敌方角色
        health: 初始生命值
        attack: 攻击力
        defense: 防御力
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute(
            "INSERT INTO characters (name, character_type, health, max_health, attack, defense) VALUES (?, ?, ?, ?, ?, ?)",
            (name, character_type, health, health, attack, defense)
        )
        conn.commit()
        character_id = cursor.lastrowid
        
        # 添加默认技能（ID为1的普通攻击）
        cursor.execute(
            "INSERT INTO character_skills (character_id, skill_id) VALUES (?, ?)",
            (character_id, 1)
        )
        conn.commit()
        return character_id
    except Exception as e:
        logger.error(f"创建角色时出错: {e}")
        conn.rollback()
        return None
    finally:
        conn.close()

def get_character(character_id):
    """获取角色信息"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("SELECT * FROM characters WHERE id = ?", (character_id,))
        character = cursor.fetchone()
        
        if not character:
            return None
        
        # 转换为字典
        character_dict = dict(character)
        
        # 解析状态JSON
        if 'status' in character_dict and character_dict['status']:
            try:
                character_dict['status'] = json.loads(character_dict['status'])
            except json.JSONDecodeError:
                character_dict['status'] = {}
        else:
            character_dict['status'] = {}
        
        return character_dict
    except Exception as e:
        logger.error(f"获取角色信息时出错: {e}")
        return None
    finally:
        conn.close()

def get_user_characters(user_id=None):
    """获取友方角色
    
    注意：此函数保留以保持兼容性，但user_id参数已不再使用
    """
    return get_characters_by_type("friendly")

def get_friendly_characters():
    """获取所有友方角色"""
    return get_characters_by_type("friendly")

def get_battle_characters():
    """获取所有正在战斗中的角色"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("SELECT * FROM characters WHERE in_battle = 1")
        characters = cursor.fetchall()
        
        if not characters:
            return []
        
        result = []
        for char in characters:
            # 转换为字典
            char_dict = dict(char)
            
            # 解析status JSON
            if 'status' in char_dict and char_dict['status']:
                try:
                    char_dict['status'] = json.loads(char_dict['status'])
                except json.JSONDecodeError:
                    char_dict['status'] = {}
            else:
                char_dict['status'] = {}
            
            result.append(char_dict)
        
        return result
    except Exception as e:
        logger.error(f"获取战斗角色时出错: {e}")
        return []
    finally:
        conn.close()

def get_characters_by_type(character_type, in_battle=None):
    """获取指定类型的所有角色
    
    Args:
        character_type: 角色类型，'friendly'或'enemy'
        in_battle: 是否在战斗中，None表示不限制，True表示在战斗中，False表示不在战斗中
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        if in_battle is None:
            cursor.execute("SELECT * FROM characters WHERE character_type = ?", (character_type,))
        else:
            in_battle_value = 1 if in_battle else 0
            cursor.execute(
                "SELECT * FROM characters WHERE character_type = ? AND in_battle = ?", 
                (character_type, in_battle_value)
            )
        
        characters = cursor.fetchall()
        
        if not characters:
            return []
        
        result = []
        for char in characters:
            # 转换为字典
            char_dict = dict(char)
            
            # 解析status JSON
            if 'status' in char_dict and char_dict['status']:
                try:
                    char_dict['status'] = json.loads(char_dict['status'])
                except json.JSONDecodeError:
                    char_dict['status'] = {}
            else:
                char_dict['status'] = {}
            
            result.append(char_dict)
        
        return result
    except Exception as e:
        logger.error(f"获取角色时出错: {e}")
        return []
    finally:
        conn.close()

def set_character_battle_status(character_id, in_battle):
    """设置角色战斗状态
    
    Args:
        character_id: 角色ID
        in_battle: 是否在战斗中，True表示在战斗中，False表示不在战斗中
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        in_battle_value = 1 if in_battle else 0
        cursor.execute(
            "UPDATE characters SET in_battle = ? WHERE id = ?",
            (in_battle_value, character_id)
        )
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"设置角色战斗状态时出错: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()

def update_character_health(character_id, health):
    """更新角色健康值"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # 首先获取角色的最大健康值
        cursor.execute("SELECT max_health FROM characters WHERE id = ?", (character_id,))
        result = cursor.fetchone()
        if not result:
            return False
        
        max_health = result[0]
        
        # 确保健康值不超过最大值
        if health > max_health:
            health = max_health
        
        # 确保健康值不小于0
        if health < 0:
            health = 0
        
        cursor.execute(
            "UPDATE characters SET health = ? WHERE id = ?",
            (health, character_id)
        )
        
        # 如果生命值归0，自动移出战斗
        if health <= 0:
            cursor.execute("UPDATE characters SET in_battle = 0 WHERE id = ?", (character_id,))
            logger.info(f"角色 {character_id} 生命值归0，已自动移出战斗")
        
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"更新角色健康值时出错: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()

def get_character_by_name(name, character_type=None):
    """通过名称获取角色信息
    
    Args:
        name: 角色名称
        character_type: 角色类型，可选参数，用于进一步筛选
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        if character_type:
            cursor.execute("SELECT * FROM characters WHERE name = ? AND character_type = ?", (name, character_type))
        else:
            cursor.execute("SELECT * FROM characters WHERE name = ?", (name,))
        
        character = cursor.fetchone()
        
        if not character:
            return None
        
        # 转换为字典
        character_dict = dict(character)
        
        # 解析状态JSON
        if 'status' in character_dict and character_dict['status']:
            try:
                character_dict['status'] = json.loads(character_dict['status'])
            except json.JSONDecodeError:
                character_dict['status'] = {}
        else:
            character_dict['status'] = {}
        
        return character_dict
    except Exception as e:
        logger.error(f"通过名称获取角色信息时出错: {e}")
        return None
    finally:
        conn.close()

def update_character_status(character_id, status_key, status_value):
    """更新角色状态"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # 获取当前状态
        cursor.execute("SELECT status FROM characters WHERE id = ?", (character_id,))
        result = cursor.fetchone()
        if not result:
            return False
        
        # 解析当前状态JSON
        try:
            current_status = json.loads(result[0]) if result[0] else {}
        except json.JSONDecodeError:
            current_status = {}
        
        # 更新状态
        current_status[status_key] = status_value
        
        # 保存更新后的状态
        cursor.execute(
            "UPDATE characters SET status = ? WHERE id = ?",
            (json.dumps(current_status), character_id)
        )
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"更新角色状态时出错: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()

def reset_character(character_id):
    """重置角色状态"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # 获取角色的最大健康值和每回合行动次数
        cursor.execute("SELECT max_health, actions_per_turn FROM characters WHERE id = ?", (character_id,))
        result = cursor.fetchone()
        if not result:
            return False
        
        max_health, actions_per_turn = result
        
        # 重置角色状态：恢复满血、清空status字段、恢复行动次数、重置混乱值
        cursor.execute(
            "UPDATE characters SET health = ?, status = '{}', current_actions = ?, stagger_value = max_stagger_value, stagger_status = 'normal', stagger_turns_remaining = 0 WHERE id = ?",
            (max_health, actions_per_turn, character_id)
        )
        
        # 清除状态效果表中的所有buff/debuff
        cursor.execute("""
            DELETE FROM character_status_effects
            WHERE character_id = ?
        """, (character_id,))
        
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"重置角色状态时出错: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()

# 技能相关查询

def get_character_skills(character_id):
    """获取角色的所有技能"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            SELECT s.id, s.name, s.description, s.cooldown,
                   s.damage_formula, s.effects
            FROM skills s
            JOIN character_skills cs ON s.id = cs.skill_id
            WHERE cs.character_id = ?
        """, (character_id,))
        
        skills = cursor.fetchall()
        
        if not skills:
            return []
        
        result = []
        for skill in skills:
            skill_dict = {
                "id": skill[0],
                "name": skill[1],
                "description": skill[2],
                "cooldown": skill[3],
                "damage_formula": skill[4] if skill[4] else '1d6',
                "effects": skill[5] if skill[5] else '{}'
            }
            result.append(skill_dict)
        
        return result
    except Exception as e:
        logger.error(f"获取角色技能时出错: {e}")
        return []
    finally:
        conn.close()

def add_skill_to_character(character_id, skill_id):
    """为角色添加技能"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # 检查技能是否存在
        cursor.execute("SELECT id FROM skills WHERE id = ?", (skill_id,))
        if not cursor.fetchone():
            return False
        
        # 检查角色是否已有此技能
        cursor.execute(
            "SELECT 1 FROM character_skills WHERE character_id = ? AND skill_id = ?", 
            (character_id, skill_id)
        )
        if cursor.fetchone():
            return True  # 已有此技能
        
        # 添加技能
        cursor.execute(
            "INSERT INTO character_skills (character_id, skill_id) VALUES (?, ?)",
            (character_id, skill_id)
        )
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"为角色添加技能时出错: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()

def get_all_skills():
    """获取所有可用技能"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("SELECT id, name, description, cooldown FROM skills ORDER BY id")
        skills = cursor.fetchall()
        
        result = []
        for skill in skills:
            result.append({
                "id": skill[0],
                "name": skill[1],
                "description": skill[2],
                "cooldown": skill[3]
            })
        
        return result
    except Exception as e:
        logger.error(f"获取所有技能时出错: {e}")
        return []
    finally:
        conn.close()

def remove_skill_from_character(character_id, skill_id):
    """从角色移除技能"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # 检查是否是普通攻击技能（ID为1），不能移除
        if skill_id == 1:
            return False
        
        cursor.execute(
            "DELETE FROM character_skills WHERE character_id = ? AND skill_id = ?",
            (character_id, skill_id)
        )
        conn.commit()
        return cursor.rowcount > 0
    except Exception as e:
        logger.error(f"移除角色技能时出错: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()

def get_skill_by_id(skill_id):
    """根据ID获取技能信息"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("SELECT id, name, description, cooldown FROM skills WHERE id = ?", (skill_id,))
        skill = cursor.fetchone()
        
        if not skill:
            return None
        
        return {
            "id": skill[0],
            "name": skill[1],
            "description": skill[2],
            "cooldown": skill[3]
        }
    except Exception as e:
        logger.error(f"获取技能信息时出错: {e}")
        return None
    finally:
        conn.close()

# 战斗相关查询

def record_battle(attacker_id, defender_id, damage, skill_used=None):
    """记录战斗结果"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute(
            "INSERT INTO battle_logs (attacker_id, defender_id, damage, skill_used) VALUES (?, ?, ?, ?)",
            (attacker_id, defender_id, damage, skill_used)
        )
        conn.commit()
        return cursor.lastrowid
    except Exception as e:
        logger.error(f"记录战斗结果时出错: {e}")
        conn.rollback()
        return None
    finally:
        conn.close()

def get_battle_logs(character_id, limit=10):
    """获取角色的战斗记录"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            SELECT 
                bl.id, 
                a.name as attacker_name, 
                d.name as defender_name, 
                bl.damage, 
                s.name as skill_name,
                bl.timestamp
            FROM battle_logs bl
            JOIN characters a ON bl.attacker_id = a.id
            JOIN characters d ON bl.defender_id = d.id
            LEFT JOIN skills s ON bl.skill_used = s.id
            WHERE bl.attacker_id = ? OR bl.defender_id = ?
            ORDER BY bl.timestamp DESC
            LIMIT ?
        """, (character_id, character_id, limit))
        
        logs = cursor.fetchall()
        
        if not logs:
            return []
        
        result = []
        for log in logs:
            result.append({
                "id": log[0],
                "attacker": log[1],
                "defender": log[2],
                "damage": log[3],
                "skill": log[4] if log[4] else "普通攻击",
                "timestamp": log[5]
            })
        
        return result
    except Exception as e:
        logger.error(f"获取战斗记录时出错: {e}")
        return []
    finally:
        conn.close()

def update_character_status(character_id, status_json):
    """更新角色状态JSON"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("UPDATE characters SET status = ? WHERE id = ?", (status_json, character_id))
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"更新角色状态时出错: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()

def get_skill(skill_id):
    """获取技能信息"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("SELECT * FROM skills WHERE id = ?", (skill_id,))
        skill = cursor.fetchone()
        
        if skill:
            skill_dict = dict(skill)
            
            # 确保新字段有默认值
            if 'damage_formula' not in skill_dict:
                skill_dict['damage_formula'] = '1d6'
            if 'cooldown' not in skill_dict:
                skill_dict['cooldown'] = 0
            if 'effects' not in skill_dict:
                skill_dict['effects'] = '{}'
            
            return skill_dict
        return None
    except Exception as e:
        logger.error(f"获取技能信息时出错: {e}")
        return None
    finally:
        conn.close()

def reset_all_characters():
    """重置所有角色状态：恢复满血、清除冷却、移出战斗、清除所有buff/debuff"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # 恢复所有角色的生命值到最大值，重置行动次数，重置混乱值
        cursor.execute("UPDATE characters SET health = max_health, current_actions = actions_per_turn, stagger_value = max_stagger_value, stagger_status = 'normal', stagger_turns_remaining = 0")
        
        # 清除所有角色的状态（包括冷却时间）
        cursor.execute("UPDATE characters SET status = '{}'")
        
        # 将所有角色移出战斗
        cursor.execute("UPDATE characters SET in_battle = 0")
        
        # 清除状态效果表中的所有buff/debuff
        cursor.execute("DELETE FROM character_status_effects")
        
        conn.commit()
        
        # 获取影响的角色数量
        cursor.execute("SELECT COUNT(*) FROM characters")
        count = cursor.fetchone()[0]
        
        logger.info(f"已重置 {count} 个角色的状态，清除了所有状态效果")
        return count
    except Exception as e:
        logger.error(f"重置角色状态时出错: {e}")
        conn.rollback()
        return 0
    finally:
        conn.close()

def remove_all_from_battle():
    """将所有角色移出战斗"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("UPDATE characters SET in_battle = 0")
        conn.commit()
        
        # 获取影响的角色数量
        cursor.execute("SELECT COUNT(*) FROM characters WHERE in_battle = 0")
        count = cursor.fetchone()[0]
        
        logger.info(f"已将所有角色移出战斗")
        return count
    except Exception as e:
        logger.error(f"移出战斗时出错: {e}")
        conn.rollback()
        return 0
    finally:
        conn.close()

def use_character_action(character_id):
    """消耗角色的一次行动"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            UPDATE characters 
            SET current_actions = current_actions - 1
            WHERE id = ? AND current_actions > 0
        """, (character_id,))
        
        if cursor.rowcount > 0:
            conn.commit()
            return True
        else:
            return False
    except Exception as e:
        logger.error(f"消耗行动次数时出错: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()

def restore_character_actions():
    """恢复所有角色的行动次数"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            UPDATE characters 
            SET current_actions = actions_per_turn
        """)
        conn.commit()
        
        # 获取影响的角色数量
        affected_count = cursor.rowcount
        logger.info(f"已恢复 {affected_count} 个角色的行动次数")
        return affected_count
    except Exception as e:
        logger.error(f"恢复行动次数时出错: {e}")
        conn.rollback()
        return 0
    finally:
        conn.close()

def get_characters_with_actions(character_type=None):
    """获取还有行动次数的角色
    
    Args:
        character_type: 角色类型过滤 ('friendly', 'enemy', 或 None 表示所有)
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        if character_type:
            cursor.execute("""
                SELECT * FROM characters 
                WHERE in_battle = 1 AND current_actions > 0 AND character_type = ?
                ORDER BY name
            """, (character_type,))
        else:
            cursor.execute("""
                SELECT * FROM characters 
                WHERE in_battle = 1 AND current_actions > 0
                ORDER BY name
            """)
        
        characters = []
        for row in cursor.fetchall():
            character = dict(row)
            characters.append(character)
        
        return characters
    except Exception as e:
        logger.error(f"获取有行动次数角色时出错: {e}")
        return []
    finally:
        conn.close()

def set_character_actions_per_turn(character_id, actions_per_turn):
    """设置角色每回合行动次数"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            UPDATE characters 
            SET actions_per_turn = ?, current_actions = ?
            WHERE id = ?
        """, (actions_per_turn, actions_per_turn, character_id))
        
        if cursor.rowcount > 0:
            conn.commit()
            return True
        else:
            return False
    except Exception as e:
        logger.error(f"设置行动次数时出错: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()

def update_character_actions(character_id, current_actions):
    """更新角色当前行动次数"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            UPDATE characters 
            SET current_actions = ?
            WHERE id = ?
        """, (current_actions, character_id))
        
        if cursor.rowcount > 0:
            conn.commit()
            return True
        else:
            return False
    except Exception as e:
        logger.error(f"更新行动次数时出错: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()
