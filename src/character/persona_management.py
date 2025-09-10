"""
人格管理命令处理器 - 键盘界面版本
提供创建核心角色和切换人格的Telegram命令，使用键盘交互
"""
import json
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    CommandHandler, 
    CallbackContext, 
    ConversationHandler,
    CallbackQueryHandler
)
from character.persona import get_available_personas, switch_persona_by_id, create_core_character_if_not_exists
from database.queries import get_user_characters, get_character

logger = logging.getLogger(__name__)

# 定义会话状态
SELECTING_CHARACTER = 1
SELECTING_PERSONA = 2

async def create_core_command(update: Update, context: CallbackContext) -> None:
    """创建核心角色命令"""
    if not context.args:
        await update.message.reply_text(
            "请指定要创建的核心角色名称。\n"
            "可用角色: 珏、露、莹、笙、曦\n"
            "示例: /create_core 珏"
        )
        return
    
    character_name = context.args[0]
    core_characters = ['珏', '露', '莹', '笙', '曦']
    
    if character_name not in core_characters:
        await update.message.reply_text(
            f"未知的核心角色: {character_name}\n"
            f"可用角色: {', '.join(core_characters)}"
        )
        return
    
    result = create_core_character_if_not_exists(character_name)
    
    if result['success']:
        await update.message.reply_text(
            f"✅ 核心角色 {character_name} 创建成功！\n"
            f"默认人格: {result['default_persona']}\n"
            f"角色ID: {result['character_id']}"
        )
    else:
        await update.message.reply_text(f"❌ 创建失败: {result['message']}")

async def switch_persona_start(update: Update, context: CallbackContext) -> int:
    """开始人格切换流程"""
    # 获取用户的核心角色
    core_characters = ['珏', '露', '莹', '笙', '曦']
    user_characters = get_user_characters(update.effective_user.id)
    
    # 筛选出核心角色
    available_characters = [char for char in user_characters if char['name'] in core_characters]
    
    if not available_characters:
        await update.message.reply_text(
            "你还没有任何核心角色。\n"
            "使用 /create_core <角色名> 来创建角色。\n"
            "可用角色: 珏、露、莹、笙、曦"
        )
        return ConversationHandler.END
    
    # 创建角色选择键盘
    keyboard = []
    for char in available_characters:
        current_persona = char.get('current_persona', '无')
        keyboard.append([
            InlineKeyboardButton(
                f"{char['name']} (当前: {current_persona})", 
                callback_data=f"char_{char['id']}"
            )
        ])
    
    # 添加取消按钮
    keyboard.append([InlineKeyboardButton("❌ 取消", callback_data="cancel")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("选择要切换人格的角色:", reply_markup=reply_markup)
    
    return SELECTING_CHARACTER

async def select_character_for_persona(update: Update, context: CallbackContext) -> int:
    """处理角色选择"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "cancel":
        await query.edit_message_text("❌ 已取消人格切换")
        return ConversationHandler.END
    
    character_id = int(query.data.split('_')[1])
    context.user_data['selected_character_id'] = character_id
    
    character = get_character(character_id)
    if not character:
        await query.edit_message_text("❌ 找不到该角色")
        return ConversationHandler.END
    
    # 获取该角色可用的人格
    available_personas = get_available_personas(character['name'])
    
    if not available_personas:
        await query.edit_message_text(f"❌ 角色 {character['name']} 没有可用的人格")
        return ConversationHandler.END
    
    # 创建人格选择键盘
    keyboard = []
    current_persona = character.get('current_persona')
    
    for persona in available_personas:
        persona_name = persona['persona_name']
        button_text = f"🔸 {persona_name}"
        
        # 标记当前人格
        if persona_name == current_persona:
            button_text = f"✅ {persona_name} (当前)"
        
        keyboard.append([
            InlineKeyboardButton(button_text, callback_data=f"persona_{persona_name}")
        ])
    
    # 添加返回和取消按钮
    keyboard.append([
        InlineKeyboardButton("🔙 返回", callback_data="back"),
        InlineKeyboardButton("❌ 取消", callback_data="cancel")
    ])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(
        f"为角色 {character['name']} 选择人格:",
        reply_markup=reply_markup
    )
    
    return SELECTING_PERSONA

async def select_persona(update: Update, context: CallbackContext) -> int:
    """处理人格选择"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "cancel":
        await query.edit_message_text("❌ 已取消人格切换")
        return ConversationHandler.END
    
    if query.data == "back":
        # 重新显示角色选择
        return await switch_persona_start(update, context)
    
    character_id = context.user_data['selected_character_id']
    persona_name = query.data.split('_')[1]
    
    # 执行人格切换
    result = switch_persona_by_id(character_id, persona_name)
    
    if result['success']:
        await query.edit_message_text(
            f"✅ 人格切换成功！\n"
            f"角色: {result['character_name']}\n"
            f"新人格: {result['new_persona']}\n\n"
            f"属性更新:\n"
            f"生命值: {result['new_stats']['health']}/{result['new_stats']['max_health']}\n"
            f"攻击力: {result['new_stats']['attack']}\n"
            f"防御力: {result['new_stats']['defense']}\n"
            f"物理抗性: {result['new_stats']['physical_resistance']}%\n"
            f"魔法抗性: {result['new_stats']['magic_resistance']}%\n\n"
            f"技能已更新: {len(result['skills_updated'])} 个技能"
        )
    else:
        await query.edit_message_text(f"❌ 人格切换失败: {result['message']}")
    
    return ConversationHandler.END

async def list_personas_command(update: Update, context: CallbackContext) -> None:
    """查看所有可用人格"""
    core_characters = ['珏', '露', '莹', '笙', '曦']
    
    message_lines = ["📋 **可用人格列表:**\n"]
    
    for character_name in core_characters:
        personas = get_available_personas(character_name)
        if personas:
            message_lines.append(f"**{character_name}:**")
            for persona in personas:
                stats = f"生命:{persona['health']}/{persona['max_health']} 攻击:{persona['attack']} 防御:{persona['defense']}"
                message_lines.append(f"  🔸 {persona['persona_name']} - {stats}")
        else:
            message_lines.append(f"**{character_name}:** 无可用人格")
        message_lines.append("")
    
    await update.message.reply_text("\n".join(message_lines), parse_mode='Markdown')

async def core_status_command(update: Update, context: CallbackContext) -> None:
    """查看所有核心角色状态"""
    try:
        core_characters = ['珏', '露', '莹', '笙', '曦']
        user_characters = get_user_characters(update.effective_user.id)
        
        # 创建核心角色状态字典
        core_status = {}
        for char in user_characters:
            if char['name'] in core_characters:
                core_status[char['name']] = char.get('current_persona', '无')
        
        message = "🎭 核心角色状态:\n\n"
        
        for char_name in core_characters:
            if char_name in core_status:
                message += f"✅ {char_name} - 当前人格: {core_status[char_name]}\n"
            else:
                message += f"❌ {char_name} - 未创建\n"
        
        message += "\n使用 /create_core <角色名> 创建核心角色"
        message += "\n使用 /switch_persona 切换角色人格"
        
        await update.message.reply_text(message)
    except Exception as e:
        logger.error(f"获取核心角色状态时出错: {e}")
        await update.message.reply_text(f"获取状态时出错: {str(e)}")

# 创建ConversationHandler
persona_switch_handler = ConversationHandler(
    entry_points=[CommandHandler('switch_persona', switch_persona_start)],
    states={
        SELECTING_CHARACTER: [CallbackQueryHandler(select_character_for_persona)],
        SELECTING_PERSONA: [CallbackQueryHandler(select_persona)],
    },
    fallbacks=[],
    per_message=False
)

def get_persona_management_handlers():
    """获取人格管理相关的命令处理器"""
    return [
        CommandHandler("create_core", create_core_command),
        persona_switch_handler,
        CommandHandler("list_personas", list_personas_command),
        CommandHandler("core_status", core_status_command),
    ]
