"""
角色人格（Persona）系统 - 基于数据库的实现
为特定的友方角色提供可切换的人格，每个人格有不同的属性和战斗风格
参考DewBot的设计模式：人格数据存储在独立的personas表中
"""
import json
import logging
from database.queries import (
    get_character_by_name, 
    update_character_health,
    get_db_connection
)

logger = logging.getLogger(__name__)

def get_available_personas(character_name):
    """获取指定角色的可用人格"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            SELECT character_name, name, description, health, max_health, attack, defense,
                   physical_resistance, magic_resistance, skills
            FROM personas 
            WHERE character_name = ?
            ORDER BY id
        """, (character_name,))
        
        personas_data = cursor.fetchall()
        
        if not personas_data:
            return []
        
        personas = []
        for row in personas_data:
            persona = {
                'character_name': row[0],
                'persona_name': row[1],
                'description': row[2],
                'health': row[3],
                'max_health': row[4],
                'attack': row[5],
                'defense': row[6],
                'physical_resistance': row[7],
                'magic_resistance': row[8],
                'skills': json.loads(row[9]) if row[9] else []
            }
            personas.append(persona)
        
        return personas
        
    except Exception as e:
        print(f"Error getting available personas for {character_name}: {e}")
        return []
    finally:
        conn.close()

def get_character_personas(character_name):
    """获取指定角色的所有人格"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            SELECT name, description, health, max_health, attack, defense,
                   physical_resistance, magic_resistance, skills
            FROM personas 
            WHERE character_name = ?
            ORDER BY id
        """, (character_name,))
        
        personas_data = cursor.fetchall()
        
        personas = {}
        for row in personas_data:
            import json
            skills = json.loads(row[8]) if row[8] else [1]
            personas[row[0]] = {
                'name': row[0],
                'description': row[1],
                'health': row[2],
                'max_health': row[3],
                'attack': row[4],
                'defense': row[5],
                'physical_resistance': row[6],
                'magic_resistance': row[7],
                'skills': skills
            }
        
        return personas
        
    except Exception as e:
        logger.error(f"获取角色 {character_name} 的人格数据时出错: {e}")
        return {}
    finally:
        conn.close()

def switch_persona(character_name, persona_name):
    """
    切换角色的人格
    
    Args:
        character_name: 角色名称（珏、露、莹、笙、曦）
        persona_name: 人格名称
        
    Returns:
        tuple: (success: bool, message: str)
    """
    # 首先检查人格是否存在
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # 查询人格数据
        cursor.execute("""
            SELECT name, health, max_health, attack, defense, physical_resistance, 
                   magic_resistance, race_tags, description, skills
            FROM personas 
            WHERE character_name = ? AND name = ?
        """, (character_name, persona_name))
        
        persona_data = cursor.fetchone()
        if not persona_data:
            # 获取该角色的可用人格
            cursor.execute("SELECT name FROM personas WHERE character_name = ?", (character_name,))
            available = [row[0] for row in cursor.fetchall()]
            if available:
                return False, f"人格 '{persona_name}' 不存在。{character_name} 的可用人格: {', '.join(available)}"
            else:
                return False, f"角色 '{character_name}' 没有可用的人格"
        
        # 查找角色（支持带人格后缀的角色名）
        character = get_character_by_name(character_name)
        if not character:
            # 尝试查找数据库中所有友方角色，找到名称包含该角色名的
            from database.queries import get_characters_by_type
            all_friendly = get_characters_by_type("friendly")
            for char in all_friendly:
                # 检查角色名是否以目标角色名开头（如"珏(战士)"以"珏"开头）
                if char['name'].startswith(character_name + "(") or char['name'] == character_name:
                    character = char
                    break
            
            if not character:
                return False, f"角色 '{character_name}' 不存在，请先使用 /create_core {character_name} 创建角色"
        
        # 解析人格数据
        name, health, max_health, attack, defense, phys_res, magic_res, race_tags, description, skills_json = persona_data
        
        # 解析技能列表
        import json
        skills = json.loads(skills_json) if skills_json else [1]  # 默认只有普通攻击
        
        # 更新角色属性
        cursor.execute("""
            UPDATE characters 
            SET health = ?, 
                max_health = ?, 
                attack = ?, 
                defense = ?,
                physical_resistance = ?,
                magic_resistance = ?,
                race_tags = ?,
                current_persona = ?
            WHERE id = ?
        """, (
            health,
            max_health,
            attack,
            defense,
            phys_res,
            magic_res,
            race_tags,
            name,  # 记录当前人格
            character['id']
        ))
        
        # 这里可以添加技能切换逻辑（如果需要的话）
        # 清除现有技能并添加新技能
        cursor.execute("DELETE FROM character_skills WHERE character_id = ?", (character['id'],))
        
        # 添加人格专属技能
        for skill_id in skills:
            cursor.execute(
                "INSERT INTO character_skills (character_id, skill_id) VALUES (?, ?)",
                (character['id'], skill_id)
            )
        
        conn.commit()
        
        return True, f"✨ {character_name} 成功切换为 {name} 人格！\n{description}\n🎯 获得技能: {len(skills)}个"
        
    except Exception as e:
        logger.error(f"切换人格时出错: {e}")
        conn.rollback()
        return False, f"切换人格时出错: {str(e)}"
    finally:
        conn.close()

def switch_persona_by_id(character_id, persona_name):
    """
    通过角色ID切换角色的人格
    
    Args:
        character_id: 角色ID
        persona_name: 人格名称
        
    Returns:
        dict: 包含success, message, character_name, new_persona, new_stats, skills_updated等信息
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # 获取角色信息
        cursor.execute("SELECT name FROM characters WHERE id = ?", (character_id,))
        char_result = cursor.fetchone()
        if not char_result:
            return {'success': False, 'message': '找不到指定的角色'}
        
        character_name = char_result[0]
        
        # 查询人格数据
        cursor.execute("""
            SELECT name, health, max_health, attack, defense, physical_resistance, 
                   magic_resistance, description, skills, stagger_value, max_stagger_value
            FROM personas 
            WHERE character_name = ? AND name = ?
        """, (character_name, persona_name))
        
        persona_data = cursor.fetchone()
        if not persona_data:
            return {'success': False, 'message': f'找不到人格: {persona_name}'}
        
        name, health, max_health, attack, defense, phys_res, magic_res, description, skills_json, stagger_value, max_stagger_value = persona_data
        skills = json.loads(skills_json) if skills_json else []
        
        # 更新角色属性（包括混乱值）
        cursor.execute("""
            UPDATE characters SET 
                health = ?, 
                max_health = ?,
                attack = ?, 
                defense = ?,
                physical_resistance = ?,
                magic_resistance = ?,
                current_persona = ?,
                stagger_value = ?,
                max_stagger_value = ?
            WHERE id = ?
        """, (
            health,
            max_health,
            attack,
            defense,
            phys_res,
            magic_res,
            name,
            stagger_value or 100,  # 默认混乱值
            max_stagger_value or 100,  # 默认最大混乱值
            character_id
        ))
        
        # 更新技能
        cursor.execute("DELETE FROM character_skills WHERE character_id = ?", (character_id,))
        
        for skill_id in skills:
            cursor.execute(
                "INSERT INTO character_skills (character_id, skill_id) VALUES (?, ?)",
                (character_id, skill_id)
            )
        
        conn.commit()
        
        return {
            'success': True,
            'message': '人格切换成功',
            'character_name': character_name,
            'new_persona': name,
            'new_stats': {
                'health': health,
                'max_health': max_health,
                'attack': attack,
                'defense': defense,
                'physical_resistance': phys_res,
                'magic_resistance': magic_res,
                'stagger_value': stagger_value,
                'max_stagger_value': max_stagger_value
            },
            'skills_updated': skills
        }
        
    except Exception as e:
        conn.rollback()
        return {'success': False, 'message': f'切换人格时出错: {str(e)}'}
    finally:
        conn.close()

def create_core_character_if_not_exists(character_name):
    """
    如果核心角色不存在则创建它
    
    Args:
        character_name: 角色名称
        
    Returns:
        tuple: (success: bool, message: str)
    """
    # 检查是否有该角色的人格数据
    personas = get_character_personas(character_name)
    if not personas:
        return False, f"'{character_name}' 不是支持的核心角色"
    
    # 检查角色是否已存在
    character = get_character_by_name(character_name)
    if not character:
        # 尝试查找带人格后缀的角色
        from database.queries import get_characters_by_type
        all_friendly = get_characters_by_type("friendly")
        for char in all_friendly:
            if char['name'].startswith(character_name + "("):
                character = char
                break
    
    if character:
        current_persona = character.get('current_persona')
        if current_persona:
            return True, f"角色 '{character_name}' 已存在，当前人格: {current_persona}"
        else:
            return True, f"角色 '{character_name}' 已存在"
    
    # 创建角色（使用第一个人格作为默认属性）
    first_persona_name = list(personas.keys())[0]
    first_persona = personas[first_persona_name]
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 创建角色
        cursor.execute("""
            INSERT INTO characters 
            (name, character_type, health, max_health, attack, defense, 
             physical_resistance, magic_resistance, race_tags, current_persona)
            VALUES (?, 'friendly', ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            character_name,  # 使用原始角色名
            first_persona['health'],
            first_persona['max_health'],
            first_persona['attack'],
            first_persona['defense'],
            first_persona['physical_resistance'],
            first_persona['magic_resistance'],
            '[]',  # 暂时用空的race_tags
            first_persona_name
        ))
        
        character_id = cursor.lastrowid
        
        # 添加默认技能（普通攻击）
        cursor.execute(
            "INSERT INTO character_skills (character_id, skill_id) VALUES (?, ?)",
            (character_id, 1)
        )
        
        conn.commit()
        
        return True, f"✨ 创建角色 '{character_name}' 成功！默认人格: {first_persona_name}\n{first_persona['description']}"
        
    except Exception as e:
        logger.error(f"创建核心角色时出错: {e}")
        conn.rollback()
        return False, f"创建角色时出错: {str(e)}"
    finally:
        conn.close()

def get_persona_info(character_name, persona_name=None):
    """
    获取人格信息
    
    Args:
        character_name: 角色名称
        persona_name: 人格名称，如果为None则返回所有人格
        
    Returns:
        dict or None: 人格信息
    """
    if persona_name is None:
        return get_character_personas(character_name)
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            SELECT name, description, health, max_health, attack, defense,
                   physical_resistance, magic_resistance, race_tags
            FROM personas 
            WHERE character_name = ? AND name = ?
        """, (character_name, persona_name))
        
        row = cursor.fetchone()
        if not row:
            return None
        
        return {
            'name': row[0],
            'description': row[1],
            'health': row[2],
            'max_health': row[3],
            'attack': row[4],
            'defense': row[5],
            'physical_resistance': row[6],
            'magic_resistance': row[7],
            'race_tags': row[8] if row[8] else '[]'
        }
        
    except Exception as e:
        logger.error(f"获取人格信息时出错: {e}")
        return None
    finally:
        conn.close()

def is_core_character(character_name):
    """检查是否为核心角色"""
    personas = get_character_personas(character_name)
    return len(personas) > 0

def get_current_persona(character_name):
    """
    获取角色当前的人格
    
    Args:
        character_name: 原始角色名称（珏、露、莹、笙、曦）
        
    Returns:
        str or None: 当前人格名称
    """
    # 首先尝试用原始名称查找
    character = get_character_by_name(character_name)
    if not character:
        # 尝试查找数据库中所有友方角色，找到名称包含该角色名的
        from database.queries import get_characters_by_type
        all_friendly = get_characters_by_type("friendly")
        for char in all_friendly:
            # 检查角色名是否以目标角色名开头（如"珏(战士)"以"珏"开头）
            if char['name'].startswith(character_name + "("):
                character = char
                break
        
        if not character:
            return None
    
    # 直接从数据库字段获取当前人格
    return character.get('current_persona')

def get_supported_characters():
    """获取支持persona系统的角色列表"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("SELECT DISTINCT character_name FROM personas ORDER BY character_name")
        return [row[0] for row in cursor.fetchall()]
    except Exception as e:
        logger.error(f"获取支持的角色列表时出错: {e}")
        return []
    finally:
        conn.close()
