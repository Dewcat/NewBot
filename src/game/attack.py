import logging
import random
import json
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    CommandHandler, 
    CallbackContext, 
    ConversationHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters
)
from database.queries import (
    get_character,
    get_user_characters,
    get_characters_by_type,
    get_character_skills,
    update_character_health,
    record_battle,
    get_skill,
    use_character_action,
    get_characters_with_actions
)
from skill.skill_effects import skill_registry
from game.damage_calculator import is_skill_on_cooldown, get_skill_cooldown_remaining
from database.db_connection import get_db_connection
from character.status_formatter import format_character_status

# 配置日志
logger = logging.getLogger(__name__)

# 定义会话状态
SELECTING_ATTACKER = 1
SELECTING_SKILL = 2
SELECTING_TARGET = 3

async def start_attack(update: Update, context: CallbackContext) -> int:
    """开始攻击流程"""
    # 获取有行动次数的友方角色
    friendly_characters = get_characters_with_actions("friendly")
    
    if not friendly_characters:
        await update.message.reply_text(
            "没有任何有行动次数的友方角色可以用来攻击。\n"
            "如果所有角色都已耗尽行动次数，请使用 /end_turn 结束回合。"
        )
        return ConversationHandler.END
    
    # 创建角色选择键盘
    keyboard = []
    for char in friendly_characters:
        keyboard.append([
            InlineKeyboardButton(f"{char['name']}", callback_data=f"attacker_{char['id']}")
        ])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("选择你要使用的角色:", reply_markup=reply_markup)
    
    return SELECTING_ATTACKER

async def select_attacker(update: Update, context: CallbackContext) -> int:
    """处理攻击者选择"""
    query = update.callback_query
    await query.answer()
    
    attacker_id = int(query.data.split('_')[1])
    context.user_data['attacker_id'] = attacker_id
    
    attacker = get_character(attacker_id)
    if not attacker:
        await query.edit_message_text("找不到该角色。请重新开始。")
        return ConversationHandler.END
    
    # 获取角色技能
    skills = get_character_skills(attacker_id)
    
    if not skills:
        # 如果没有技能，直接使用普通攻击
        context.user_data['skill_id'] = None
        context.user_data['skill_info'] = None
        return await show_target_selection(update, context, None)
    
    # 创建技能选择键盘
    keyboard = []
    for skill in skills:
        skill_info = get_skill(skill['id'])
        if skill_info:
            # 检查技能是否在冷却中
            cooldown_remaining = get_skill_cooldown_remaining(attacker_id, skill['id'])
            if cooldown_remaining > 0:
                skill_text = f"🔒 {skill['name']} (冷却中: {cooldown_remaining}次行动)"
                # 冷却中的技能不可选择
                continue
            else:
                skill_text = f"{skill['name']}"
                if skill_info.get('cooldown', 0) > 0:
                    skill_text += f" (冷却: {skill_info['cooldown']}次行动)"
                
                # 添加技能类型标识
                effects = skill_info.get('effects', '{}')
                skill_category = skill_info.get('skill_category', 'damage')
                
                try:
                    effects_dict = json.loads(effects) if isinstance(effects, str) else effects
                    if skill_category == 'healing':
                        skill_text += " 💚"  # 治疗技能标识
                    elif skill_category == 'buff':
                        skill_text += " ✨"  # buff技能标识
                    elif skill_category == 'debuff':
                        skill_text += " 💀"  # debuff技能标识
                    elif skill_category == 'self':
                        skill_text += " 🧘"  # 自我技能标识
                    else:
                        skill_text += " ⚔️"   # 伤害技能标识
                except:
                    skill_text += " ⚔️"
        else:
            skill_text = f"{skill['name']} ⚔️"
        
        keyboard.append([
            InlineKeyboardButton(skill_text, callback_data=f"skill_{skill['id']}")
        ])
    
    # 如果所有技能都在冷却中，只能使用普通攻击
    if not keyboard:
        context.user_data['skill_id'] = None
        context.user_data['skill_info'] = None
        return await show_target_selection(update, context, None)
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(f"已选择角色: {attacker['name']}\n\n选择要使用的技能:", reply_markup=reply_markup)
    
    return SELECTING_SKILL

async def select_skill(update: Update, context: CallbackContext) -> int:
    """处理技能选择"""
    query = update.callback_query
    await query.answer()
    
    skill_id = int(query.data.split('_')[1])
    
    # 先检查技能是否在冷却中
    attacker_id = context.user_data['attacker_id']
    if is_skill_on_cooldown(attacker_id, skill_id):
        cooldown_remaining = get_skill_cooldown_remaining(attacker_id, skill_id)
        await query.edit_message_text(f"技能还在冷却中，剩余 {cooldown_remaining} 次行动。")
        return ConversationHandler.END
    
    skill_info = get_skill(skill_id)
    if not skill_info:
        await query.edit_message_text("找不到指定的技能。")
        return ConversationHandler.END
    
    context.user_data['skill_id'] = skill_id
    context.user_data['skill_info'] = skill_info
    
    return await show_target_selection(update, context, skill_info)

async def show_target_selection(update: Update, context: CallbackContext, skill_info):
    """显示目标选择界面"""
    query = update.callback_query
    attacker_id = context.user_data['attacker_id']
    attacker = get_character(attacker_id)
    
    # 确定技能类型和目标选择
    is_heal_skill = False
    is_buff_skill = False
    is_debuff_skill = False
    is_self_skill = False
    skill_category = None
    
    if skill_info:
        try:
            effects = skill_info.get('effects', '{}')
            effects_dict = json.loads(effects) if isinstance(effects, str) else effects
            is_heal_skill = effects_dict.get('heal', False)
            skill_category = skill_info.get('skill_category', 'damage')
            is_buff_skill = (skill_category == 'buff')
            is_debuff_skill = (skill_category == 'debuff')
            is_self_skill = (skill_category == 'self')
        except:
            pass
    
    # 如果是self技能，直接对自己生效，跳过目标选择
    if is_self_skill:
        # 验证攻击者状态
        if not attacker.get('in_battle'):
            await query.edit_message_text("技能使用失败：施法者必须在战斗中。")
            return ConversationHandler.END
        
        if attacker.get('health', 0) <= 0:
            await query.edit_message_text("技能使用失败：施法者已经无法战斗。")
            return ConversationHandler.END
        
        # 直接对自己使用技能
        result_message = execute_skill_effect(attacker, attacker, skill_info)
        
        # 消耗攻击者的行动次数
        if not use_character_action(attacker['id']):
            result_message += "\n⚠️ 警告：消耗行动次数失败"
        
        await query.edit_message_text(result_message)
        return ConversationHandler.END
    
    # 根据技能类型选择目标
    if is_heal_skill or is_buff_skill:
        # 治疗技能和纯buff技能：选择友方角色（包括自己）
        target_characters = get_characters_by_type("friendly", in_battle=True)
        if is_heal_skill:
            target_type_text = "治疗目标"
        else:
            target_type_text = "增益目标"
        skill_name = skill_info['name'] if skill_info else ("治疗" if is_heal_skill else "增益技能")
    elif is_debuff_skill:
        # 纯debuff技能：选择敌方角色
        target_characters = get_characters_by_type("enemy", in_battle=True)
        target_type_text = "减益目标"
        skill_name = skill_info['name'] if skill_info else "减益技能"
    else:
        # 攻击技能：选择敌方角色
        target_characters = get_characters_by_type("enemy", in_battle=True)
        target_type_text = "攻击目标"
        skill_name = skill_info['name'] if skill_info else "普通攻击"
    
    if not target_characters:
        target_type = "友方" if is_heal_skill else "敌方"
        await query.edit_message_text(f"没有可选择的{target_type}目标在战斗中。")
        return ConversationHandler.END
    
    # 创建目标选择键盘
    keyboard = []
    for target in target_characters:
        # 显示角色生命值状态
        health_percent = (target['health'] / target['max_health'] * 100) if target['max_health'] > 0 else 0
        health_status = ""
        if target['health'] <= 0:
            health_status = " 💀"
        elif health_percent >= 80:
            health_status = " 💚"
        elif health_percent >= 50:
            health_status = " 💛"
        elif health_percent >= 20:
            health_status = " 🧡"
        else:
            health_status = " ❤️"
        
        target_text = f"{target['name']} ({target['health']}/{target['max_health']}){health_status}"
        keyboard.append([
            InlineKeyboardButton(target_text, callback_data=f"target_{target['id']}")
        ])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    message = f"攻击者: {attacker['name']}\n技能: {skill_name}\n\n选择{target_type_text}:"
    await query.edit_message_text(message, reply_markup=reply_markup)
    
    return SELECTING_TARGET

async def select_target(update: Update, context: CallbackContext) -> int:
    """处理目标选择并执行攻击"""
    query = update.callback_query
    await query.answer()
    
    target_id = int(query.data.split('_')[1])
    context.user_data['target_id'] = target_id
    
    # 直接执行攻击，因为攻击者和技能已经选择完毕
    return await execute_attack(update, context)

async def execute_attack(update: Update, context: CallbackContext) -> int:
    """执行攻击"""
    query = update.callback_query
    
    attacker_id = context.user_data['attacker_id']
    target_id = context.user_data['target_id']
    skill_id = context.user_data.get('skill_id')
    
    attacker = get_character(attacker_id)
    target = get_character(target_id)
    
    if not attacker or not target:
        await query.edit_message_text("攻击失败：找不到攻击者或目标。")
        return ConversationHandler.END
    
    # 验证攻击者和目标都在战斗中
    if not attacker.get('in_battle') or not target.get('in_battle'):
        await query.edit_message_text("攻击失败：攻击者和目标必须都在战斗中。")
        return ConversationHandler.END
    
    # 验证攻击者的生命值
    if attacker.get('health', 0) <= 0:
        await query.edit_message_text("攻击失败：攻击者已经无法战斗。")
        return ConversationHandler.END
    
    # 获取技能信息（如果有）
    skill_info = None
    if skill_id:
        # 先检查技能是否在冷却中
        if is_skill_on_cooldown(attacker_id, skill_id):
            cooldown_remaining = get_skill_cooldown_remaining(attacker_id, skill_id)
            await query.edit_message_text(f"攻击失败：技能还在冷却中，剩余 {cooldown_remaining} 次行动。")
            return ConversationHandler.END
        
        skill_info = get_skill(skill_id)
        if not skill_info:
            await query.edit_message_text("攻击失败：找不到指定的技能。")
            return ConversationHandler.END
    
    # 执行技能效果
    result_message = execute_skill_effect(attacker, target, skill_info)
    
    # 消耗攻击者的行动次数
    if not use_character_action(attacker['id']):
        result_message += "\n⚠️ 警告：消耗行动次数失败"
    
    await query.edit_message_text(result_message)
    
    return ConversationHandler.END

def execute_skill_effect(attacker, target, skill_info):
    """执行技能效果并返回结果消息"""
    skill_name = skill_info['name'] if skill_info else "普通攻击"
    
    # 判断技能类型
    is_heal_skill = False
    is_buff_skill = False
    is_debuff_skill = False
    is_self_skill = False
    skill_category = None
    
    if skill_info:
        try:
            effects = skill_info.get('effects', '{}')
            effects_dict = json.loads(effects) if isinstance(effects, str) else effects
            is_heal_skill = effects_dict.get('heal', False)
            skill_category = skill_info.get('skill_category', 'damage')
            is_buff_skill = (skill_category == 'buff')
            is_debuff_skill = (skill_category == 'debuff')
            is_self_skill = (skill_category == 'self')
        except:
            pass
    
    # 根据技能类型设置不同的描述
    if is_self_skill:
        result_message = f"🧘 自我强化结果 🧘\n\n"
        result_message += f"{attacker['name']} 使用 {skill_name} 强化了自己！\n\n"
    elif is_heal_skill:
        result_message = f"💚 治疗结果 💚\n\n"
        result_message += f"{attacker['name']} 使用 {skill_name} 治疗了 {target['name']}！\n\n"
    elif is_buff_skill:
        result_message = f"✨ 强化结果 ✨\n\n"
        result_message += f"{attacker['name']} 使用 {skill_name} 强化了 {target['name']}！\n\n"
    elif is_debuff_skill:
        result_message = f"💀 削弱结果 💀\n\n"
        result_message += f"{attacker['name']} 使用 {skill_name} 削弱了 {target['name']}！\n\n"
    else:
        result_message = f"⚔️ 战斗结果 ⚔️\n\n"
        result_message += f"{attacker['name']} 使用 {skill_name} 攻击了 {target['name']}！\n\n"
    
    # 使用技能效果系统执行攻击
    skill_result = skill_registry.execute_skill(attacker, target, skill_info)
    
    # 添加技能效果描述
    result_message += skill_result['result_text'] + "\n\n"
    
    # 根据技能类型决定是否显示生命值状态
    if not (is_self_skill or is_buff_skill or is_debuff_skill):
        # 只有攻击和治疗技能才显示生命值状态
        target = get_character(target['id'])
        
        if target['health'] <= 0:
            result_message += f"💀 {target['name']} 已被击倒！"
        else:
            result_message += f"❤️ {target['name']} 剩余生命值: {target['health']}/{target['max_health']}"
    else:
        # self技能、buff技能、debuff技能不显示生命值，只显示效果完成
        result_message += f"✅ 技能效果已生效！"
    
    return result_message

async def cancel_attack(update: Update, context: CallbackContext) -> int:
    """取消攻击"""
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("已取消攻击。")
    else:
        await update.message.reply_text("已取消攻击。")
    
    return ConversationHandler.END

def get_attack_conv_handler():
    """获取攻击会话处理器"""
    return ConversationHandler(
        entry_points=[CommandHandler("attack", start_attack)],
        states={
            SELECTING_ATTACKER: [CallbackQueryHandler(select_attacker, pattern=r"^attacker_\d+$")],
            SELECTING_TARGET: [CallbackQueryHandler(select_target, pattern=r"^target_\d+$")],
            SELECTING_SKILL: [CallbackQueryHandler(select_skill, pattern=r"^skill_\d+$")]
        },
        fallbacks=[
            CommandHandler("cancel", cancel_attack),
            CallbackQueryHandler(cancel_attack, pattern=r"^cancel$")
        ],
        name="attack",
        per_user=False
    )

# 敌方攻击相关状态
ENEMY_SELECTING_ATTACKER, ENEMY_SELECTING_TARGET, ENEMY_SELECTING_SKILL = 3, 4, 5

async def start_enemy_attack(update: Update, context: CallbackContext) -> int:
    """开始敌方攻击流程"""
    # 获取有行动次数的敌方角色
    enemy_characters = get_characters_with_actions("enemy")
    
    if not enemy_characters:
        await update.message.reply_text(
            "没有任何有行动次数的敌方角色可以用来攻击。\n"
            "如果所有敌方角色都已耗尽行动次数，请使用 /end_turn 结束回合。"
        )
        return ConversationHandler.END
    
    # 创建攻击者选择键盘
    keyboard = []
    for enemy in enemy_characters:
        # 检查角色是否还活着
        if enemy['health'] <= 0:
            continue
            
        # 显示角色信息和行动次数
        action_info = f" ⚡{enemy['current_actions']}/{enemy['actions_per_turn']}"
        status_text = f"{enemy['name']} ({enemy['health']}/{enemy['max_health']}){action_info}"
        keyboard.append([
            InlineKeyboardButton(status_text, callback_data=f"enemy_attacker_{enemy['id']}")
        ])
    
    if not keyboard:
        await update.message.reply_text("没有存活且有行动次数的敌方角色可以发起攻击。")
        return ConversationHandler.END
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("选择发起攻击的敌方角色:", reply_markup=reply_markup)
    
    return ENEMY_SELECTING_ATTACKER

async def enemy_select_attacker(update: Update, context: CallbackContext) -> int:
    """处理敌方攻击者选择"""
    query = update.callback_query
    await query.answer()
    
    attacker_id = int(query.data.split('_')[2])
    attacker = get_character(attacker_id)
    
    if not attacker:
        await query.edit_message_text("找不到指定的角色。")
        return ConversationHandler.END
    
    if attacker['health'] <= 0:
        await query.edit_message_text("该角色已经无法战斗。")
        return ConversationHandler.END
    
    context.user_data['enemy_attacker_id'] = attacker_id
    
    # 获取攻击者的技能
    skills = get_character_skills(attacker_id)
    
    if not skills:
        await query.edit_message_text("该角色没有可用的技能。")
        return ConversationHandler.END
    
    # 创建技能选择键盘
    keyboard = []
    for skill in skills:
        # 检查技能是否在冷却中
        if is_skill_on_cooldown(attacker_id, skill['id']):
            cooldown_remaining = get_skill_cooldown_remaining(attacker_id, skill['id'])
            skill_text = f"{skill['name']} (冷却中: {cooldown_remaining}次行动)"
            # 冷却中的技能不可选择
            continue
        else:
            # 判断技能类型并添加图标
            skill_info = get_skill(skill['id'])
            try:
                effects = skill.get('effects', '{}')
                effects_dict = json.loads(effects) if isinstance(effects, str) else effects
                skill_category = skill_info.get('skill_category', 'damage') if skill_info else 'damage'
                
                if effects_dict.get('heal', False):
                    skill_type_icon = "💚"  # 治疗技能
                elif skill_category == 'buff':
                    skill_type_icon = "✨"  # buff技能
                elif skill_category == 'debuff':
                    skill_type_icon = "💀"  # debuff技能
                else:
                    skill_type_icon = "⚔️"  # 伤害技能
            except:
                skill_type_icon = "⚔️"
            
            skill_text = f"{skill_type_icon} {skill['name']}"
        
        keyboard.append([
            InlineKeyboardButton(skill_text, callback_data=f"enemy_skill_{skill['id']}")
        ])
    
    if not keyboard:
        await query.edit_message_text("该角色没有可用的技能（全部在冷却中）。")
        return ConversationHandler.END
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    message = f"攻击者: {attacker['name']}\n选择要使用的技能:"
    await query.edit_message_text(message, reply_markup=reply_markup)
    
    return ENEMY_SELECTING_SKILL

async def enemy_select_skill(update: Update, context: CallbackContext) -> int:
    """处理敌方技能选择"""
    query = update.callback_query
    await query.answer()
    
    skill_id = int(query.data.split('_')[2])
    
    # 先检查技能是否在冷却中
    attacker_id = context.user_data['enemy_attacker_id']
    if is_skill_on_cooldown(attacker_id, skill_id):
        cooldown_remaining = get_skill_cooldown_remaining(attacker_id, skill_id)
        await query.edit_message_text(f"技能还在冷却中，剩余 {cooldown_remaining} 次行动。")
        return ConversationHandler.END
    
    skill_info = get_skill(skill_id)
    if not skill_info:
        await query.edit_message_text("找不到指定的技能。")
        return ConversationHandler.END
    
    context.user_data['enemy_skill_id'] = skill_id
    context.user_data['enemy_skill_info'] = skill_info
    
    return await enemy_show_target_selection(update, context, skill_info)

async def enemy_show_target_selection(update: Update, context: CallbackContext, skill_info):
    """显示敌方攻击目标选择界面"""
    query = update.callback_query
    attacker_id = context.user_data['enemy_attacker_id']
    attacker = get_character(attacker_id)
    
    # 确定技能类型和目标选择
    is_heal_skill = False
    is_buff_skill = False
    is_debuff_skill = False
    is_self_skill = False
    skill_category = None
    
    if skill_info:
        try:
            effects = skill_info.get('effects', '{}')
            effects_dict = json.loads(effects) if isinstance(effects, str) else effects
            is_heal_skill = effects_dict.get('heal', False)
            skill_category = skill_info.get('skill_category', 'damage')
            is_buff_skill = (skill_category == 'buff')
            is_debuff_skill = (skill_category == 'debuff')
            is_self_skill = (skill_category == 'self')
        except:
            pass
    
    # 如果是self技能，直接对自己生效，跳过目标选择
    if is_self_skill:
        # 验证攻击者状态
        if not attacker.get('in_battle'):
            await query.edit_message_text("技能使用失败：施法者必须在战斗中。")
            return ConversationHandler.END
        
        if attacker.get('health', 0) <= 0:
            await query.edit_message_text("技能使用失败：施法者已经无法战斗。")
            return ConversationHandler.END
        
        # 直接对自己使用技能
        result_message = execute_skill_effect(attacker, attacker, skill_info)
        
        # 消耗攻击者的行动次数
        if not use_character_action(attacker['id']):
            result_message += "\n⚠️ 警告：消耗行动次数失败"
        
        result_message = f"敌方技能使用结果:\n{result_message}"
        await query.edit_message_text(result_message)
        return ConversationHandler.END
    
    # 根据技能类型选择目标
    if is_heal_skill or is_buff_skill:
        # 治疗技能和纯buff技能：选择敌方角色（包括自己）
        target_characters = get_characters_by_type("enemy", in_battle=True)
        if is_heal_skill:
            target_type_text = "治疗目标"
        else:
            target_type_text = "增益目标"
        skill_name = skill_info['name'] if skill_info else ("治疗" if is_heal_skill else "增益技能")
    elif is_debuff_skill:
        # 纯debuff技能：选择友方角色
        target_characters = get_characters_by_type("friendly", in_battle=True)
        target_type_text = "减益目标"
        skill_name = skill_info['name'] if skill_info else "减益技能"
    else:
        # 攻击技能：选择友方角色
        target_characters = get_characters_by_type("friendly", in_battle=True)
        target_type_text = "攻击目标"
        skill_name = skill_info['name'] if skill_info else "普通攻击"
    
    if not target_characters:
        target_type = "敌方" if is_heal_skill else "友方"
        await query.edit_message_text(f"没有可选择的{target_type}目标在战斗中。")
        return ConversationHandler.END
    
    # 创建目标选择键盘
    keyboard = []
    for target in target_characters:
        # 显示角色生命值状态
        health_percent = (target['health'] / target['max_health'] * 100) if target['max_health'] > 0 else 0
        health_status = ""
        if target['health'] <= 0:
            health_status = " 💀"
        elif health_percent >= 80:
            health_status = " 💚"
        elif health_percent >= 50:
            health_status = " 💛"
        elif health_percent >= 20:
            health_status = " 🧡"
        else:
            health_status = " ❤️"
        
        target_text = f"{target['name']} ({target['health']}/{target['max_health']}){health_status}"
        keyboard.append([
            InlineKeyboardButton(target_text, callback_data=f"enemy_target_{target['id']}")
        ])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    message = f"攻击者: {attacker['name']}\n技能: {skill_name}\n\n选择{target_type_text}:"
    await query.edit_message_text(message, reply_markup=reply_markup)
    
    return ENEMY_SELECTING_TARGET

async def enemy_select_target(update: Update, context: CallbackContext) -> int:
    """处理敌方目标选择并执行攻击"""
    query = update.callback_query
    await query.answer()
    
    target_id = int(query.data.split('_')[2])
    attacker_id = context.user_data['enemy_attacker_id']
    skill_id = context.user_data['enemy_skill_id']
    skill_info = context.user_data['enemy_skill_info']
    
    attacker = get_character(attacker_id)
    target = get_character(target_id)
    
    if not attacker or not target:
        await query.edit_message_text("找不到指定的角色。")
        return ConversationHandler.END
    
    if attacker['health'] <= 0:
        await query.edit_message_text("攻击者已经无法战斗。")
        return ConversationHandler.END
    
    if target['health'] <= 0:
        await query.edit_message_text("目标已经无法战斗。")
        return ConversationHandler.END
    
    # 执行攻击
    result = execute_skill_effect(attacker, target, skill_info)
    
    # 消耗攻击者的行动次数
    if not use_character_action(attacker['id']):
        result += "\n⚠️ 警告：消耗行动次数失败"
    
    # 显示战斗结果
    result_message = f"敌方攻击结果:\n{result}"
    await query.edit_message_text(result_message)
    
    return ConversationHandler.END

async def cancel_enemy_attack(update: Update, context: CallbackContext) -> int:
    """取消敌方攻击"""
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("已取消敌方攻击。")
    else:
        await update.message.reply_text("已取消敌方攻击。")
    
    return ConversationHandler.END

def get_enemy_attack_conv_handler():
    """获取敌方攻击会话处理器"""
    return ConversationHandler(
        entry_points=[CommandHandler("enemy_attack", start_enemy_attack)],
        states={
            ENEMY_SELECTING_ATTACKER: [CallbackQueryHandler(enemy_select_attacker, pattern=r"^enemy_attacker_\d+$")],
            ENEMY_SELECTING_TARGET: [CallbackQueryHandler(enemy_select_target, pattern=r"^enemy_target_\d+$")],
            ENEMY_SELECTING_SKILL: [CallbackQueryHandler(enemy_select_skill, pattern=r"^enemy_skill_\d+$")]
        },
        fallbacks=[
            CommandHandler("cancel", cancel_enemy_attack),
            CallbackQueryHandler(cancel_enemy_attack, pattern=r"^cancel$")
        ],
        name="enemy_attack",
        per_user=False
    )
