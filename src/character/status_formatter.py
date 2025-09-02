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
    
    # 获取当前人格信息
    from character.persona import get_current_persona
    current_persona = None
    try:
        # 尝试从角色名提取核心角色名（去掉括号部分）
        core_name = name.split('(')[0] if '(' in name else name
        if core_name in ["珏", "露", "莹", "笙", "曦"]:
            current_persona = get_current_persona(core_name)
    except:
        pass
    
    # 基础状态文本
    status_text = f"📋 {name}\n"
    
    # 人格信息
    if current_persona:
        status_text += f"【人格：{current_persona}】\n"
    
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
    
    status_text += f"{health_emoji} 生命值: {health}/{max_health}\n"
    
    # 添加混乱值信息
    stagger_value = character.get('stagger_value', 150)
    max_stagger = character.get('max_stagger_value', 150)
    stagger_status = character.get('stagger_status', 'normal')
    if stagger_status == 'staggered':
        status_text += f"🧠 理智值: {stagger_value}/{max_stagger} (混乱中)\n"
    else:
        status_text += f"🧠 理智值: {stagger_value}/{max_stagger}\n"
    
    # 攻击和防御
    status_text += f"⚔️ 攻击等级: {attack}\n"
    status_text += f"🛡️ 防御等级: {defense}\n"
    
    # 战斗状态
    if health <= 0:
        battle_status = "💀 已倒下"
    elif in_battle:
        battle_status = "⚔️ 战斗中"
    else:
        battle_status = "🏠 休息中"
    
    status_text += f"🎯 状态: {battle_status}\n"
    status_text += f"⚡ 行动次数: {current_actions}/{actions_per_turn}\n"
    
    # 添加状态效果信息
    character_id = character.get('id')
    if character_id:
        status_effects_text = get_status_effects_display(character_id)
        if status_effects_text != "无状态效果":
            status_text += f"\n🌟 状态效果: {status_effects_text}\n"
    
    # 处理冷却时间信息
    cooldown_info = format_cooldowns(character.get('status', {}))
    if cooldown_info and cooldown_info != "所有技能可用 ✅":
        status_text += f"\n⏰ 技能冷却状态:\n{cooldown_info}"
    
    return status_text

def format_stagger_status(character):
    """
    格式化混乱值状态信息
    
    Args:
        character (dict): 角色信息字典
        
    Returns:
        str: 格式化后的混乱值状态文本
    """
    if not character:
        return ""
    
    stagger_value = character.get('stagger_value', 100)
    max_stagger_value = character.get('max_stagger_value', 100)
    stagger_status = character.get('stagger_status', 'normal')
    stagger_turns_remaining = character.get('stagger_turns_remaining', 0)
    
    # 计算混乱值百分比
    stagger_percent = (stagger_value / max_stagger_value * 100) if max_stagger_value > 0 else 0
    
    # 选择表情符号
    if stagger_status == 'staggered':
        stagger_emoji = "💫"
        status_suffix = f" (混乱中，剩余{stagger_turns_remaining}回合)"
    elif stagger_percent >= 80:
        stagger_emoji = "🟢"
        status_suffix = ""
    elif stagger_percent >= 50:
        stagger_emoji = "🟡"
        status_suffix = ""
    elif stagger_percent >= 20:
        stagger_emoji = "🟠"
        status_suffix = ""
    else:
        stagger_emoji = "🔴"
        status_suffix = " (危险！)"
    
    return f"{stagger_emoji} 混乱值: {stagger_value}/{max_stagger_value} ({stagger_percent:.0f}%){status_suffix}"

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
