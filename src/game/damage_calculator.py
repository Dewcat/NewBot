import random
import re
import json

def parse_dice_formula(formula):
    """
    解析骰子公式，支持如下格式：
    - "5+2d3" -> 基础值5 + 2个3面骰子
    - "1d6" -> 1个6面骰子
    - "10" -> 固定值10
    - "3d4+2" -> 3个4面骰子 + 2
    
    Returns:
        tuple: (base_value, dice_rolls) 
        例如: (5, [(2, 3)]) 表示基础值5，2个3面骰子
    """
    formula = formula.strip()
    base_value = 0
    dice_rolls = []
    
    # 分割公式中的各部分（用+号分隔）
    parts = formula.split('+')
    
    for part in parts:
        part = part.strip()
        
        # 检查是否是骰子格式 (如 "2d3")
        dice_match = re.match(r'(\d+)d(\d+)', part)
        if dice_match:
            num_dice = int(dice_match.group(1))
            dice_faces = int(dice_match.group(2))
            dice_rolls.append((num_dice, dice_faces))
        else:
            # 否则当作固定数值
            try:
                base_value += int(part)
            except ValueError:
                # 如果解析失败，忽略这部分
                continue
    
    return base_value, dice_rolls

def roll_dice(num_dice, faces):
    """投掷指定数量和面数的骰子"""
    return sum(random.randint(1, faces) for _ in range(num_dice))

def calculate_damage_from_formula(formula):
    """
    根据骰子公式计算伤害值
    
    Args:
        formula (str): 骰子公式，如 "5+2d3"
        
    Returns:
        tuple: (total_damage, detail_text)
    """
    base_value, dice_rolls = parse_dice_formula(formula)
    total_damage = base_value
    detail_parts = []
    
    if base_value > 0:
        detail_parts.append(str(base_value))
    
    for num_dice, faces in dice_rolls:
        roll_result = roll_dice(num_dice, faces)
        total_damage += roll_result
        detail_parts.append(f"{num_dice}d{faces}({roll_result})")
    
    detail_text = " + ".join(detail_parts) if detail_parts else "0"
    
    return total_damage, detail_text

def calculate_attack_defense_modifier(attacker_attack, target_defense):
    """
    计算攻防差值对伤害的影响
    攻防每差1点，伤害增减2%
    
    Args:
        attacker_attack (int): 攻击者攻击力
        target_defense (int): 目标防御力
        
    Returns:
        float: 伤害倍率（1.0为基础，>1.0为增伤，<1.0为减伤）
    """
    attack_defense_diff = attacker_attack - target_defense
    # 每差1点攻防，伤害变化2%
    modifier = 1.0 + (attack_defense_diff * 0.02)
    
    # 确保倍率不会低于0.1（最少造成10%伤害）
    modifier = max(0.1, modifier)
    
    return modifier

def update_character_cooldowns(character_id, skill_id):
    """
    更新角色的技能冷却时间
    在角色的status JSON中记录各技能的冷却状态
    
    Args:
        character_id (int): 角色ID
        skill_id (int): 使用的技能ID
    """
    from database.queries import get_character, update_character_status
    
    character = get_character(character_id)
    if not character:
        return
    
    # 解析当前状态
    try:
        # character['status'] 可能已经是dict或者是JSON字符串
        status = character.get('status', {})
        if isinstance(status, str):
            status = json.loads(status)
        elif status is None:
            status = {}
    except (json.JSONDecodeError, TypeError):
        status = {}
    
    # 确保有cooldowns字段
    if 'cooldowns' not in status:
        status['cooldowns'] = {}
    
    # 减少所有技能的冷却时间
    for skill_key in list(status['cooldowns'].keys()):
        status['cooldowns'][skill_key] -= 1
        if status['cooldowns'][skill_key] <= 0:
            del status['cooldowns'][skill_key]
    
    # 从数据库获取当前技能的冷却时间
    from database.queries import get_skill
    skill = get_skill(skill_id)
    if skill and skill['cooldown'] > 0:
        status['cooldowns'][str(skill_id)] = skill['cooldown']
    
    # 更新角色状态
    update_character_status(character_id, json.dumps(status))

def is_skill_on_cooldown(character_id, skill_id):
    """
    检查技能是否在冷却中
    
    Args:
        character_id (int): 角色ID
        skill_id (int): 技能ID
        
    Returns:
        bool: True表示在冷却中，False表示可以使用
    """
    from database.queries import get_character
    
    character = get_character(character_id)
    if not character:
        return False
    
    try:
        # character['status'] 可能已经是dict或者是JSON字符串
        status = character.get('status', {})
        if isinstance(status, str):
            status = json.loads(status)
        
        cooldowns = status.get('cooldowns', {})
        return str(skill_id) in cooldowns and cooldowns[str(skill_id)] > 0
    except (json.JSONDecodeError, TypeError):
        return False

def get_skill_cooldown_remaining(character_id, skill_id):
    """
    获取技能剩余冷却时间
    
    Args:
        character_id (int): 角色ID
        skill_id (int): 技能ID
        
    Returns:
        int: 剩余冷却回合数，0表示可以使用
    """
    from database.queries import get_character
    
    character = get_character(character_id)
    if not character:
        return 0
    
    try:
        # character['status'] 可能已经是dict或者是JSON字符串
        status = character.get('status', {})
        if isinstance(status, str):
            status = json.loads(status)
        
        cooldowns = status.get('cooldowns', {})
        return cooldowns.get(str(skill_id), 0)
    except (json.JSONDecodeError, TypeError):
        return 0
