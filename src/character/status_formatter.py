"""
角色状态格式化工具
用于将角色数据转换为用户友好的显示格式
"""

import json
from database.queries import get_skill
from character.status_effects import get_status_effects_display

def format_character_status(character):
    """
    格式化角色状态信息，将内部数据转换为用户友好的显示格式
    
    Args:
        character (dict): 角色信息字典
        
    Returns:
        str: 格式化后的状态文本
    """
    if not character:
        return "角色信息不存在"
    
    # 基础信息
    name = character.get('name', '未知')
    health = character.get('health', 0)
    max_health = character.get('max_health', 100)
    attack = character.get('attack', 0)
    defense = character.get('defense', 0)
    char_type = character.get('character_type', 'unknown')
    in_battle = character.get('in_battle', 0)
    actions_per_turn = character.get('actions_per_turn', 1)
    current_actions = character.get('current_actions', 1)
    
    # 角色类型显示
    type_text = "友方角色" if char_type == "friendly" else "敌方角色"
    
    # 战斗状态
    if health <= 0:
        battle_status = "💀 已倒下（无法战斗）"
    elif in_battle:
        battle_status = "⚔️ 战斗中"
    else:
        battle_status = "🏠 休息中"
    
    # 生命值状态
    health_percent = (health / max_health * 100) if max_health > 0 else 0
    if health <= 0:
        health_emoji = "💀"
    elif health_percent >= 80:
        health_emoji = "💚"
    elif health_percent >= 50:
        health_emoji = "💛"
    elif health_percent >= 20:
        health_emoji = "🧡"
    else:
        health_emoji = "❤️"
    
    # 基础状态文本
    status_text = f"""📋 {name} ({type_text})
{health_emoji} 生命值: {health}/{max_health} ({health_percent:.0f}%)
⚔️ 攻击力: {attack}
🛡️ 防御力: {defense}
🎯 状态: {battle_status}
⚡ 行动次数: {current_actions}/{actions_per_turn}"""
    
    # 添加状态效果信息
    character_id = character.get('id')
    if character_id:
        status_effects_text = get_status_effects_display(character_id)
        status_text += f"\n🌟 状态效果: {status_effects_text}"
    
    # 处理冷却时间信息
    cooldown_info = format_cooldowns(character.get('status', {}))
    if cooldown_info:
        status_text += f"\n\n⏰ 技能冷却状态:\n{cooldown_info}"
    
    return status_text

def format_cooldowns(status):
    """
    格式化冷却时间信息
    
    Args:
        status (dict or str): 角色状态信息
        
    Returns:
        str: 格式化后的冷却时间文本
    """
    try:
        # 处理状态数据
        if isinstance(status, str):
            status = json.loads(status) if status else {}
        elif status is None:
            status = {}
        
        cooldowns = status.get('cooldowns', {})
        
        if not cooldowns:
            return "所有技能可用 ✅"
        
        cooldown_lines = []
        for skill_id_str, remaining_turns in cooldowns.items():
            if remaining_turns > 0:
                # 获取技能名称
                skill = get_skill(int(skill_id_str))
                skill_name = skill['name'] if skill else f"技能{skill_id_str}"
                
                cooldown_lines.append(f"  🔒 {skill_name}: 冷却中，还需 {remaining_turns} 次行动")
        
        if not cooldown_lines:
            return "所有技能可用 ✅"
        
        return "\n".join(cooldown_lines)
        
    except (json.JSONDecodeError, TypeError, ValueError):
        return "状态信息解析失败"

def format_character_list(characters, show_details=False):
    """
    格式化角色列表
    
    Args:
        characters (list): 角色列表
        show_details (bool): 是否显示详细信息
        
    Returns:
        str: 格式化后的角色列表文本
    """
    if not characters:
        return "没有找到任何角色。"
    
    if show_details:
        # 显示详细信息
        character_texts = []
        for char in characters:
            character_texts.append(format_character_status(char))
        return "\n\n" + "="*40 + "\n\n".join(character_texts)
    else:
        # 显示简要列表
        lines = []
        for char in characters:
            name = char.get('name', '未知')
            health = char.get('health', 0)
            max_health = char.get('max_health', 100)
            in_battle = char.get('in_battle', 0)
            
            # 状态图标
            if health <= 0:
                status_icon = "💀"
                status_text = "已倒下"
            elif in_battle:
                status_icon = "⚔️"
                status_text = "战斗中"
            else:
                status_icon = "🏠"
                status_text = "休息中"
            
            lines.append(f"{status_icon} {name} ({health}/{max_health} HP) - {status_text}")
        
        return "\n".join(lines)

def format_battle_participants():
    """格式化当前战斗参与者信息"""
    from database.queries import get_characters_by_type
    
    friendly_chars = get_characters_by_type("friendly", in_battle=True)
    enemy_chars = get_characters_by_type("enemy", in_battle=True)
    
    if not friendly_chars and not enemy_chars:
        return "当前没有角色在战斗中。"
    
    text = "⚔️ 当前战斗参与者:\n\n"
    
    if friendly_chars:
        text += "👥 友方角色:\n"
        for char in friendly_chars:
            name = char.get('name', '未知')
            health = char.get('health', 0)
            max_health = char.get('max_health', 100)
            health_percent = (health / max_health * 100) if max_health > 0 else 0
            
            if health <= 0:
                text += f"  💀 {name} (已倒下)\n"
            else:
                text += f"  💚 {name} ({health}/{max_health} HP - {health_percent:.0f}%)\n"
    
    if enemy_chars:
        text += "\n👹 敌方角色:\n"
        for char in enemy_chars:
            name = char.get('name', '未知')
            health = char.get('health', 0)
            max_health = char.get('max_health', 100)
            health_percent = (health / max_health * 100) if max_health > 0 else 0
            
            if health <= 0:
                text += f"  💀 {name} (已倒下)\n"
            else:
                text += f"  💀 {name} ({health}/{max_health} HP - {health_percent:.0f}%)\n"
    
    return text
