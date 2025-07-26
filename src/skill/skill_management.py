import logging
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
    get_character_by_name,
    get_all_skills,
    get_character_skills,
    add_skill_to_character,
    remove_skill_from_character,
    get_skill_by_id
)

# 配置日志
logger = logging.getLogger(__name__)

# 定义会话状态
SELECTING_CHARACTER_FOR_SKILLS = 1
SELECTING_ACTION = 2
SELECTING_SKILL_TO_ADD = 3
SELECTING_SKILL_TO_REMOVE = 4

async def start_skill_management(update: Update, context: CallbackContext) -> int:
    """开始技能管理流程"""
    await update.message.reply_text("请输入要管理技能的角色名称：")
    return SELECTING_CHARACTER_FOR_SKILLS

async def select_character_for_skills(update: Update, context: CallbackContext) -> int:
    """选择要管理技能的角色"""
    character_name = update.message.text.strip()
    
    character = get_character_by_name(character_name)
    if not character:
        await update.message.reply_text(f"找不到名为 '{character_name}' 的角色。请重新输入角色名称：")
        return SELECTING_CHARACTER_FOR_SKILLS
    
    context.user_data['selected_character'] = character
    
    # 获取角色当前技能
    character_skills = get_character_skills(character['id'])
    
    skills_text = "当前技能：\n"
    if character_skills:
        for skill in character_skills:
            skills_text += f"• {skill['name']} - {skill['description']} (伤害倍率: {skill['damage_multiplier']}x)\n"
    else:
        skills_text += "无技能\n"
    
    # 创建操作选择键盘
    keyboard = [
        [InlineKeyboardButton("添加技能", callback_data="add_skill")],
        [InlineKeyboardButton("移除技能", callback_data="remove_skill")],
        [InlineKeyboardButton("查看所有技能", callback_data="list_all_skills")],
        [InlineKeyboardButton("取消", callback_data="cancel")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    message = f"角色：{character['name']}\n\n{skills_text}\n请选择操作："
    await update.message.reply_text(message, reply_markup=reply_markup)
    
    return SELECTING_ACTION

async def handle_action_selection(update: Update, context: CallbackContext) -> int:
    """处理操作选择"""
    query = update.callback_query
    await query.answer()
    
    action = query.data
    character = context.user_data.get('selected_character')
    
    if action == "add_skill":
        # 获取所有技能
        all_skills = get_all_skills()
        character_skills = get_character_skills(character['id'])
        character_skill_ids = {skill['id'] for skill in character_skills}
        
        # 过滤掉角色已有的技能
        available_skills = [skill for skill in all_skills if skill['id'] not in character_skill_ids]
        
        if not available_skills:
            await query.edit_message_text("该角色已拥有所有可用技能。")
            return ConversationHandler.END
        
        # 创建技能选择键盘
        keyboard = []
        for skill in available_skills:
            keyboard.append([
                InlineKeyboardButton(
                    f"{skill['name']} (伤害倍率: {skill['damage_multiplier']}x)", 
                    callback_data=f"add_{skill['id']}"
                )
            ])
        keyboard.append([InlineKeyboardButton("取消", callback_data="cancel")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("选择要添加的技能：", reply_markup=reply_markup)
        
        return SELECTING_SKILL_TO_ADD
        
    elif action == "remove_skill":
        character_skills = get_character_skills(character['id'])
        
        # 过滤掉普通攻击技能（不能移除）
        removable_skills = [skill for skill in character_skills if skill['id'] != 1]
        
        if not removable_skills:
            await query.edit_message_text("没有可移除的技能（普通攻击不能移除）。")
            return ConversationHandler.END
        
        # 创建技能选择键盘
        keyboard = []
        for skill in removable_skills:
            keyboard.append([
                InlineKeyboardButton(
                    f"{skill['name']} (伤害倍率: {skill['damage_multiplier']}x)", 
                    callback_data=f"remove_{skill['id']}"
                )
            ])
        keyboard.append([InlineKeyboardButton("取消", callback_data="cancel")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("选择要移除的技能：", reply_markup=reply_markup)
        
        return SELECTING_SKILL_TO_REMOVE
        
    elif action == "list_all_skills":
        all_skills = get_all_skills()
        
        skills_text = "所有可用技能：\n\n"
        for skill in all_skills:
            skills_text += f"🔸 {skill['name']}\n"
            skills_text += f"   描述：{skill['description']}\n"
            skills_text += f"   伤害倍率：{skill['damage_multiplier']}x\n"
            skills_text += f"   冷却时间：{skill['cooldown']}回合\n\n"
        
        await query.edit_message_text(skills_text)
        return ConversationHandler.END
        
    else:  # cancel
        await query.edit_message_text("已取消技能管理。")
        return ConversationHandler.END

async def handle_skill_addition(update: Update, context: CallbackContext) -> int:
    """处理技能添加"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "cancel":
        await query.edit_message_text("已取消技能添加。")
        return ConversationHandler.END
    
    skill_id = int(query.data.split('_')[1])
    character = context.user_data.get('selected_character')
    
    skill = get_skill_by_id(skill_id)
    if not skill:
        await query.edit_message_text("技能不存在。")
        return ConversationHandler.END
    
    if add_skill_to_character(character['id'], skill_id):
        await query.edit_message_text(
            f"成功为角色 '{character['name']}' 添加技能 '{skill['name']}'！"
        )
    else:
        await query.edit_message_text("添加技能失败，请稍后再试。")
    
    return ConversationHandler.END

async def handle_skill_removal(update: Update, context: CallbackContext) -> int:
    """处理技能移除"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "cancel":
        await query.edit_message_text("已取消技能移除。")
        return ConversationHandler.END
    
    skill_id = int(query.data.split('_')[1])
    character = context.user_data.get('selected_character')
    
    skill = get_skill_by_id(skill_id)
    if not skill:
        await query.edit_message_text("技能不存在。")
        return ConversationHandler.END
    
    if remove_skill_from_character(character['id'], skill_id):
        await query.edit_message_text(
            f"成功从角色 '{character['name']}' 移除技能 '{skill['name']}'！"
        )
    else:
        await query.edit_message_text("移除技能失败，请稍后再试。")
    
    return ConversationHandler.END

async def show_character_skills(update: Update, context: CallbackContext) -> None:
    """显示角色技能"""
    args = context.args
    
    if not args or len(args) < 1:
        await update.message.reply_text("请提供角色名称。用法: /skills <角色名称>")
        return
    
    character_name = " ".join(args)
    character = get_character_by_name(character_name)
    
    if not character:
        await update.message.reply_text(f"找不到名为 '{character_name}' 的角色。")
        return
    
    character_skills = get_character_skills(character['id'])
    
    if not character_skills:
        await update.message.reply_text(f"角色 '{character['name']}' 还没有任何技能。")
        return
    
    skills_text = f"角色 '{character['name']}' 的技能：\n\n"
    for skill in character_skills:
        skills_text += f"🔸 {skill['name']}\n"
        skills_text += f"   描述：{skill['description']}\n"
        skills_text += f"   伤害倍率：{skill['damage_multiplier']}x\n"
        skills_text += f"   冷却时间：{skill['cooldown']}回合\n\n"
    
    await update.message.reply_text(skills_text)

async def cancel_skill_management(update: Update, context: CallbackContext) -> int:
    """取消技能管理"""
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("已取消技能管理。")
    else:
        await update.message.reply_text("已取消技能管理。")
    
    return ConversationHandler.END

def get_skill_management_handlers():
    """获取所有技能管理相关的处理器"""
    
    # 技能管理会话处理器
    skill_management_conv_handler = ConversationHandler(
        entry_points=[CommandHandler(["skill_manage", "sm"], start_skill_management)],
        states={
            SELECTING_CHARACTER_FOR_SKILLS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, select_character_for_skills)
            ],
            SELECTING_ACTION: [
                CallbackQueryHandler(handle_action_selection)
            ],
            SELECTING_SKILL_TO_ADD: [
                CallbackQueryHandler(handle_skill_addition)
            ],
            SELECTING_SKILL_TO_REMOVE: [
                CallbackQueryHandler(handle_skill_removal)
            ]
        },
        fallbacks=[
            CommandHandler("cancel", cancel_skill_management),
            CallbackQueryHandler(cancel_skill_management, pattern=r"^cancel$")
        ]
    )
    
    handlers = [
        skill_management_conv_handler,
        CommandHandler("skills", show_character_skills),
    ]
    
    return handlers
