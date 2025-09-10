import random
import re
import json
from typing import List

# 导入混乱值管理器
from character.stagger_manager import stagger_manager

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
    """投掷指定数量和面数的骰子，返回总和和详细结果"""
    results = [random.randint(1, faces) for _ in range(num_dice)]
    return sum(results), results

def roll_dice_simple(num_dice, faces):
    """投掷指定数量和面数的骰子，只返回总和（向后兼容）"""
    return sum(random.randint(1, faces) for _ in range(num_dice))

def calculate_race_bonus(special_damage_tags, target_race_tags):
    """
    计算种族特攻加成
    
    Args:
        special_damage_tags (dict): 技能的特攻标签，如 {"human": 1.5, "dragon": 2.0}
        target_race_tags (list): 目标的种族标签，如 ["human", "warrior"]
        
    Returns:
        float: 特攻倍率（1.0为无加成）
    """
    if not special_damage_tags or not target_race_tags:
        return 1.0
    
    max_bonus = 1.0
    for race in target_race_tags:
        if race in special_damage_tags:
            bonus = special_damage_tags[race]
            max_bonus = max(max_bonus, bonus)
    
    return max_bonus

def calculate_resistance_reduction(damage_type, target_resistances):
    """
    计算抗性减伤
    
    Args:
        damage_type (str): 伤害类型 ('physical' 或 'magic')
        target_resistances (dict): 目标抗性，如 {"physical": 0.2, "magic": 0.1}
        
    Returns:
        float: 抗性减伤倍率（1.0为无减伤，0.5为50%减伤）
    """
    resistance = target_resistances.get(damage_type, 0.0)
    # 抗性值直接作为减伤比例，如0.3表示减伤30%
    reduction_multiplier = 1.0 - min(resistance, 0.9)  # 最多减伤90%
    return max(0.1, reduction_multiplier)  # 最少造成10%伤害

def calculate_advanced_damage(skill, attacker, target):
    """
    计算带有伤害类型、抗性和特攻的高级伤害系统
    
    Args:
        skill (dict): 技能信息，包含damage_formula, damage_type, special_damage_tags等
        attacker (dict): 攻击者信息，包含attack等属性
        target (dict): 目标信息，包含defense, physical_resistance, magic_resistance, race_tags等
        
    Returns:
        tuple: (final_damage, damage_details)
    """
    # 1. 基础伤害计算
    base_damage, dice_detail, dice_results_info = calculate_damage_from_formula(skill.get('damage_formula', '1d6'))
    
    # 2. 攻防修正
    attack_defense_modifier = calculate_attack_defense_modifier(
        attacker.get('attack', 10), 
        target.get('defense', 5)
    )
    
    # 3. 种族特攻加成
    special_tags_str = skill.get('special_damage_tags', '{}')
    # 处理空字符串的情况
    if not special_tags_str or special_tags_str.strip() == '':
        special_damage_tags = {}
    else:
        try:
            special_damage_tags = json.loads(special_tags_str)
        except json.JSONDecodeError:
            special_damage_tags = {}
    
    target_race_tags_str = target.get('race_tags', '[]')
    if not target_race_tags_str or target_race_tags_str.strip() == '':
        target_race_tags = []
    else:
        try:
            target_race_tags = json.loads(target_race_tags_str)
        except json.JSONDecodeError:
            target_race_tags = []
    
    race_bonus = calculate_race_bonus(special_damage_tags, target_race_tags)
    
    # 4. 抗性减伤
    damage_type = skill.get('damage_type', 'physical')
    target_resistances = {
        'physical': target.get('physical_resistance', 0.0),
        'magic': target.get('magic_resistance', 0.0)
    }
    resistance_reduction = calculate_resistance_reduction(damage_type, target_resistances)
    
    # 5. 混乱状态伤害加成
    stagger_multiplier = stagger_manager.get_stagger_damage_multiplier(target.get('id'))
    
    # 6. 计算最终伤害
    final_damage = int(base_damage * attack_defense_modifier * race_bonus * resistance_reduction * stagger_multiplier)
    final_damage = max(1, final_damage)  # 最少造成1点伤害
    
    # 7. 构建伤害详情文本
    damage_details = []
    damage_details.append(f"基础伤害: {dice_detail}")
    
    if attack_defense_modifier != 1.0:
        # 转换为百分比显示，如1.1显示为+10%，0.9显示为-10%
        percent_change = (attack_defense_modifier - 1.0) * 100
        if percent_change > 0:
            damage_details.append(f"攻防: +{percent_change:.0f}%")
        else:
            damage_details.append(f"攻防: {percent_change:.0f}%")
    
    if race_bonus > 1.0:
        race_name = next((race for race in target_race_tags if race in special_damage_tags), "未知")
        damage_details.append(f"特攻({race_name}): ×{race_bonus:.1f}")
    
    if resistance_reduction < 1.0:
        # 直接使用原始抗性值计算百分比，避免浮点数精度问题
        original_resistance = target_resistances.get(damage_type, 0.0)
        resistance_percent = round(original_resistance * 100)
        damage_type_name = "物理" if damage_type == "physical" else "魔法"
        damage_details.append(f"{damage_type_name}抗性: -{resistance_percent}%")
    
    if stagger_multiplier > 1.0:
        damage_details.append(f"混乱状态: ×{stagger_multiplier:.1f}")
    
    # 不再显示原始伤害
    
    return final_damage, " → ".join(damage_details), dice_results_info

def apply_damage_with_stagger(target_id: int, damage: int) -> List[str]:
    """
    应用伤害并处理混乱值
    
    Args:
        target_id: 目标角色ID
        damage: 伤害值
        
    Returns:
        List[str]: 状态消息列表
    """
    messages = []
    
    # 1. 扣除混乱值
    success, stagger_msg, enters_stagger = stagger_manager.reduce_stagger(target_id, damage)
    if success and stagger_msg:
        messages.append(stagger_msg)
    
    # 2. 如果进入混乱状态，伤害会在下次攻击时加成
    if enters_stagger:
        messages.append("⚠️ 目标进入混乱状态，下次受到的伤害将提升至200%！")
    
    return messages

def calculate_damage_from_formula(formula):
    """
    根据骰子公式计算伤害值
    
    Args:
        formula (str): 骰子公式，如 "5+2d3"
        
    Returns:
        tuple: (total_damage, detail_text, dice_results_info)
    """
    base_value, dice_rolls = parse_dice_formula(formula)
    total_damage = base_value
    detail_parts = []
    dice_results_info = []  # 存储所有骰子结果信息
    
    if base_value > 0:
        detail_parts.append(str(base_value))
    
    for num_dice, faces in dice_rolls:
        roll_total, roll_results = roll_dice(num_dice, faces)
        total_damage += roll_total
        detail_parts.append(f"{num_dice}d{faces}({roll_total})")
        
        # 记录骰子结果信息
        dice_results_info.append({
            'num_dice': num_dice,
            'faces': faces,
            'results': roll_results,
            'total': roll_total
        })
    
    detail_text = " + ".join(detail_parts) if detail_parts else "0"
    
    return total_damage, detail_text, dice_results_info

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
