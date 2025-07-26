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
    create_character,
    get_character,
    get_character_by_name,
    get_user_characters,
    get_characters_by_type,
    update_character_health,
    reset_character,
    update_character_status,
    set_character_battle_status,
    reset_all_characters,
    remove_all_from_battle
)
from character.status_formatter import format_character_status, format_character_list, format_battle_participants
from game.turn_manager import turn_manager

# 配置日志
logger = logging.getLogger(__name__)

# 定义会话状态
CREATE_NAME = 1
CREATE_ENEMY_NAME = 2
CREATE_ENEMY_HEALTH = 3
CREATE_ENEMY_ATTACK = 4
CREATE_ENEMY_DEFENSE = 5

async def start_create_character(update: Update, context: CallbackContext) -> int:
    """开始创建角色的会话"""
    await update.message.reply_text("请输入你的角色名称：")
    return CREATE_NAME

async def create_character_name(update: Update, context: CallbackContext) -> int:
    """处理角色名称输入"""
    name = update.message.text.strip()
    
    if not name or len(name) > 50:
        await update.message.reply_text("无效的名称。请提供一个少于50个字符的名称。")
        return CREATE_NAME
    
    character_id = create_character(name=name, character_type="friendly")
    
    if character_id:
        await update.message.reply_text(f"友方角色 '{name}' 创建成功！\n\n使用 /join {name} 将角色加入战斗。")
    else:
        await update.message.reply_text("创建角色时出错，请稍后再试。")
    
    return ConversationHandler.END

async def start_create_enemy(update: Update, context: CallbackContext) -> int:
    """开始创建敌方角色的会话"""
    await update.message.reply_text("请输入敌方角色名称：")
    return CREATE_ENEMY_NAME

async def create_enemy_name(update: Update, context: CallbackContext) -> int:
    """处理敌方角色名称输入"""
    name = update.message.text.strip()
    
    if not name or len(name) > 50:
        await update.message.reply_text("无效的名称。请提供一个少于50个字符的名称。")
        return CREATE_ENEMY_NAME
    
    context.user_data["enemy_name"] = name
    await update.message.reply_text(f"请输入敌方角色 '{name}' 的生命值（整数）：")
    return CREATE_ENEMY_HEALTH

async def create_enemy_health(update: Update, context: CallbackContext) -> int:
    """处理敌方角色生命值输入"""
    try:
        health = int(update.message.text.strip())
        if health <= 0:
            await update.message.reply_text("生命值必须为正整数。请重新输入：")
            return CREATE_ENEMY_HEALTH
        
        context.user_data["enemy_health"] = health
        await update.message.reply_text(f"请输入敌方角色的攻击力（整数）：")
        return CREATE_ENEMY_ATTACK
    except ValueError:
        await update.message.reply_text("无效的输入。请输入一个整数：")
        return CREATE_ENEMY_HEALTH

async def create_enemy_attack(update: Update, context: CallbackContext) -> int:
    """处理敌方角色攻击力输入"""
    try:
        attack = int(update.message.text.strip())
        if attack < 0:
            await update.message.reply_text("攻击力必须为非负整数。请重新输入：")
            return CREATE_ENEMY_ATTACK
        
        context.user_data["enemy_attack"] = attack
        await update.message.reply_text(f"请输入敌方角色的防御力（整数）：")
        return CREATE_ENEMY_DEFENSE
    except ValueError:
        await update.message.reply_text("无效的输入。请输入一个整数：")
        return CREATE_ENEMY_ATTACK

async def create_enemy_defense(update: Update, context: CallbackContext) -> int:
    """处理敌方角色防御力输入并创建敌方角色"""
    try:
        defense = int(update.message.text.strip())
        if defense < 0:
            await update.message.reply_text("防御力必须为非负整数。请重新输入：")
            return CREATE_ENEMY_DEFENSE
        
        name = context.user_data.get("enemy_name")
        health = context.user_data.get("enemy_health")
        attack = context.user_data.get("enemy_attack")
        
        character_id = create_character(
            name=name,
            character_type="enemy",
            health=health,
            attack=attack,
            defense=defense
        )
        
        if character_id:
            await update.message.reply_text(
                f"敌方角色 '{name}' 创建成功！\n"
                f"生命值: {health}\n"
                f"攻击力: {attack}\n"
                f"防御力: {defense}\n\n"
                f"使用 /join {name} 将角色加入战斗。"
            )
        else:
            await update.message.reply_text("创建敌方角色时出错，请稍后再试。")
        
        return ConversationHandler.END
    except ValueError:
        await update.message.reply_text("无效的输入。请输入一个整数：")
        return CREATE_ENEMY_DEFENSE

async def cancel_create(update: Update, context: CallbackContext) -> int:
    """取消创建角色"""
    await update.message.reply_text("已取消角色创建。")
    return ConversationHandler.END

async def show_characters(update: Update, context: CallbackContext) -> None:
    """显示用户的所有角色"""
    characters = get_user_characters()  # 不再需要传递user_id
    
    if not characters:
        await update.message.reply_text("你还没有创建任何角色。使用 /create_character 创建一个角色。")
        return
    
    message = "👥 你的角色列表：\n\n"
    message += format_character_list(characters, show_details=False)
    message += "\n\n📖 使用说明:"
    message += "\n• /show <角色名称> - 查看角色详情"
    message += "\n• /join <角色名称> - 将角色加入战斗"
    message += "\n• /leave <角色名称> - 将角色撤出战斗"
    
    await update.message.reply_text(message)

async def show_all_enemies(update: Update, context: CallbackContext) -> None:
    """显示所有敌方角色"""
    enemies = get_characters_by_type("enemy")
    
    if not enemies:
        await update.message.reply_text("没有任何敌方角色。使用 /create_enemy 创建一个敌方角色。")
        return
    
    message = "👹 敌方角色列表：\n\n"
    message += format_character_list(enemies, show_details=False)
    message += "\n\n📖 使用说明:"
    message += "\n• /show <角色名称> - 查看角色详情"
    message += "\n• /join <角色名称> - 将角色加入战斗"
    message += "\n• /leave <角色名称> - 将角色撤出战斗"
    
    await update.message.reply_text(message)

async def battle_join(update: Update, context: CallbackContext) -> None:
    """将角色加入战斗"""
    args = context.args
    
    if not args or len(args) < 1:
        await update.message.reply_text("请提供有效的角色名称。\n用法: \n/join <角色名称> - 单个加入\n/join <角色1> <角色2> <角色3> - 批量加入\n/join all [friendly|enemy] - 全部加入")
        return
    
    # 检查是否是批量加入所有角色
    if args[0].lower() == "all":
        character_type = args[1] if len(args) > 1 and args[1] in ["friendly", "enemy"] else None
        
        if character_type:
            # 批量加入指定类型的角色
            characters = get_characters_by_type(character_type, in_battle=False)
            
            if not characters:
                type_name = "友方" if character_type == "friendly" else "敌方"
                await update.message.reply_text(f"没有未参战的{type_name}角色。")
                return
            
            success_count = 0
            failed_characters = []
            
            for character in characters:
                if character['health'] > 0:  # 只有活着的角色才能加入战斗
                    if set_character_battle_status(character['id'], True):
                        success_count += 1
                    else:
                        failed_characters.append(character['name'])
            
            type_name = "友方" if character_type == "friendly" else "敌方"
            result_message = f"批量加入战斗完成！\n\n✅ 成功加入 {success_count} 个{type_name}角色"
            
            if failed_characters:
                result_message += f"\n❌ 加入失败的角色: {', '.join(failed_characters)}"
            
            await update.message.reply_text(result_message)
            return
        else:
            # 批量加入所有角色
            friendly_chars = get_characters_by_type("friendly", in_battle=False)
            enemy_chars = get_characters_by_type("enemy", in_battle=False)
            all_chars = friendly_chars + enemy_chars
            
            if not all_chars:
                await update.message.reply_text("没有未参战的角色。")
                return
            
            success_count = 0
            failed_characters = []
            
            for character in all_chars:
                if character['health'] > 0:  # 只有活着的角色才能加入战斗
                    if set_character_battle_status(character['id'], True):
                        success_count += 1
                    else:
                        failed_characters.append(character['name'])
            
            result_message = f"批量加入战斗完成！\n\n✅ 成功加入 {success_count} 个角色"
            
            if failed_characters:
                result_message += f"\n❌ 加入失败的角色: {', '.join(failed_characters)}"
            
            await update.message.reply_text(result_message)
            return
    
    # 多个角色批量加入（通过名称列表）
    if len(args) > 1:
        success_characters = []
        failed_characters = []
        not_found_characters = []
        dead_characters = []
        
        for character_name in args:
            # 查找角色
            character = get_character_by_name(character_name)
            
            if not character:
                not_found_characters.append(character_name)
                continue
                
            if character['health'] <= 0:
                dead_characters.append(character['name'])
                continue
                
            if set_character_battle_status(character['id'], True):
                success_characters.append(character['name'])
            else:
                failed_characters.append(character['name'])
        
        # 构建结果消息
        result_message = f"批量加入战斗完成！\n"
        
        if success_characters:
            result_message += f"\n✅ 成功加入 {len(success_characters)} 个角色:\n{', '.join(success_characters)}"
        
        if dead_characters:
            result_message += f"\n💀 无法加入（已死亡）:\n{', '.join(dead_characters)}"
            
        if not_found_characters:
            result_message += f"\n❓ 找不到的角色:\n{', '.join(not_found_characters)}"
            
        if failed_characters:
            result_message += f"\n❌ 加入失败的角色:\n{', '.join(failed_characters)}"
        
        await update.message.reply_text(result_message)
        return
    
    # 单个角色加入战斗
    character_name = args[0]
    
    # 尝试将参数解析为ID
    character = None
    if character_name.isdigit():
        character_id = int(character_name)
        character = get_character(character_id)
    else:
        # 如果不是ID，则按名称查找
        character = get_character_by_name(character_name)
    
    if not character:
        await update.message.reply_text("找不到该角色。请检查ID或名称是否正确。")
        return
    
    if character['health'] <= 0:
        await update.message.reply_text(f"角色 '{character['name']}' 已经无法战斗（生命值为0）。")
        return
    
    if set_character_battle_status(character['id'], True):
        await update.message.reply_text(f"角色 '{character['name']}' 已加入战斗！")
    else:
        await update.message.reply_text("将角色加入战斗时出错，请稍后再试。")

async def battle_leave(update: Update, context: CallbackContext) -> None:
    """将角色撤出战斗"""
    args = context.args
    
    if not args or len(args) < 1:
        await update.message.reply_text("请提供有效的角色名称。用法: /leave <角色名称>")
        return
    
    # 尝试将参数解析为ID
    character = None
    if args[0].isdigit():
        character_id = int(args[0])
        character = get_character(character_id)
    else:
        # 如果不是ID，则按名称查找
        character_name = " ".join(args)
        character = get_character_by_name(character_name)
    
    if not character:
        await update.message.reply_text("找不到该角色。请检查ID或名称是否正确。")
        return
    
    if set_character_battle_status(character['id'], False):
        await update.message.reply_text(f"角色 '{character['name']}' 已撤出战斗！")
    else:
        await update.message.reply_text("将角色撤出战斗时出错，请稍后再试。")

async def show_character_detail(update: Update, context: CallbackContext) -> None:
    """显示角色详细信息"""
    args = context.args
    
    if not args or len(args) < 1:
        await update.message.reply_text("请提供有效的角色名称。用法: /show <角色名称>")
        return
    
    # 尝试将参数解析为ID
    character = None
    if args[0].isdigit():
        character_id = int(args[0])
        character = get_character(character_id)
    else:
        # 如果不是ID，则按名称查找
        character_name = " ".join(args)
        character = get_character_by_name(character_name)
    
    if not character:
        await update.message.reply_text("找不到该角色。请检查ID或名称是否正确。")
        return
    
    # 使用新的格式化功能
    message = format_character_status(character)
    
    # 添加操作提示
    message += f"\n\n📖 命令提示:"
    message += f"\n• /health {character['name']} <新生命值> - 修改生命值"
    message += f"- 重置状态: /reset {character['name']}\n"
    
    if character.get('in_battle'):
        message += f"- 撤出战斗: /leave {character['name']}\n"
    else:
        message += f"- 加入战斗: /join {character['name']}\n"
    
    await update.message.reply_text(message)

async def modify_health(update: Update, context: CallbackContext) -> None:
    """修改角色的生命值"""
    args = context.args
    
    if not args or len(args) < 2:
        await update.message.reply_text("请提供有效的角色名称和健康值。用法: /health <角色名称> <健康值>")
        return
    
    # 尝试将第一个参数解析为ID
    character = None
    if args[0].isdigit():
        character_id = int(args[0])
        character = get_character(character_id)
    else:
        # 如果不是ID，则按名称查找
        character_name = args[0]
        character = get_character_by_name(character_name)
    
    if not character:
        await update.message.reply_text("找不到该角色。请检查ID或名称是否正确。")
        return
    
    try:
        health = int(args[1])
    except ValueError:
        await update.message.reply_text("生命值必须是一个整数。")
        return
    
    if update_character_health(character['id'], health):
        await update.message.reply_text(f"已将角色 '{character['name']}' 的生命值更新为 {health}。")
    else:
        await update.message.reply_text("更新角色生命值时出错，请稍后再试。")

async def reset_character_status(update: Update, context: CallbackContext) -> None:
    """重置角色状态"""
    args = context.args
    
    if not args or len(args) < 1:
        await update.message.reply_text("请提供有效的角色名称。用法: /reset <角色名称>")
        return
    
    # 尝试将参数解析为ID
    character = None
    if args[0].isdigit():
        character_id = int(args[0])
        character = get_character(character_id)
    else:
        # 如果不是ID，则按名称查找
        character_name = " ".join(args)
        character = get_character_by_name(character_name)
    
    if not character:
        await update.message.reply_text("找不到该角色。请检查ID或名称是否正确。")
        return
    
    if reset_character(character['id']):
        await update.message.reply_text(f"已重置角色 '{character['name']}' 的状态。")
    else:
        await update.message.reply_text("重置角色状态时出错，请稍后再试。")

async def reset_all_characters_command(update: Update, context: CallbackContext) -> None:
    """重置所有角色状态命令"""
    count = reset_all_characters()
    
    # 同时重置回合计数器
    turn_manager.reset_turn_counter()
    
    # 重置战斗状态（包括清除状态效果）
    turn_manager.reset_battle()
    
    if count > 0:
        await update.message.reply_text(
            f"✅ 已重置 {count} 个角色的状态：\n"
            "• 恢复满血\n"
            "• 清除技能冷却\n"
            "• 移出战斗\n"
            "• 清除状态效果\n"
            "🔄 回合计数器已重置到第1回合"
        )
    else:
        await update.message.reply_text("❌ 重置失败或没有角色需要重置。")

async def remove_all_from_battle_command(update: Update, context: CallbackContext) -> None:
    """将所有角色移出战斗命令"""
    count = remove_all_from_battle()
    if count > 0:
        await update.message.reply_text(f"✅ 已将所有角色移出战斗。")
    else:
        await update.message.reply_text("❌ 操作失败或没有角色在战斗中。")

async def show_battle_status(update: Update, context: CallbackContext) -> None:
    """显示当前战斗状态"""
    message = format_battle_participants()
    await update.message.reply_text(message)

async def show_help(update: Update, context: CallbackContext) -> None:
    """显示所有可用命令的帮助信息"""
    help_text = "🤖 SimpleBot 命令列表:\n\n"
    
    help_text += "📝 角色管理命令:\n"
    help_text += "/cc, /create_character - 创建友方角色\n"
    help_text += "/ce, /create_enemy - 创建敌方角色\n"
    help_text += "/chars, /characters - 查看你的所有友方角色\n"
    help_text += "/enemies - 查看所有敌方角色\n"
    help_text += "/show <角色名称> - 查看角色详细信息\n"
    help_text += "/join <角色名称> - 将角色加入战斗\n"
    help_text += "/join all - 将所有角色加入战斗\n"
    help_text += "/join all friendly - 将所有友方角色加入战斗\n"
    help_text += "/join all enemy - 将所有敌方角色加入战斗\n"
    help_text += "/leave <角色名称> - 将角色撤出战斗\n"
    help_text += "/health <角色名称> <数值> - 修改角色生命值\n"
    help_text += "/reset <角色名称> - 重置单个角色状态\n"
    help_text += "/reset_all - 重置所有角色状态（满血+移出战斗+清除冷却+清除状态效果+重置回合）\n"
    help_text += "/end_battle - 将所有角色移出战斗\n"
    help_text += "/battle - 查看当前战斗参与者\n\n"
    
    help_text += "⚔️ 战斗命令:\n"
    help_text += "/attack - 发起攻击\n\n"
    
    help_text += "🎯 技能管理命令:\n"
    help_text += "/sm <角色名称> - 管理角色技能（支持批量添加/移除）\n"
    help_text += "/skills <角色名称> - 查看角色技能\n\n"
    
    help_text += "ℹ️ 其他命令:\n"
    help_text += "/help - 显示此帮助信息\n"
    
    await update.message.reply_text(help_text)

def get_character_management_handlers():
    """获取所有角色管理相关的处理器"""
    # 创建友方角色的会话处理器
    create_conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler(["create_character", "cc"], start_create_character)
        ],
        states={
            CREATE_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, create_character_name)],
        },
        fallbacks=[CommandHandler("cancel", cancel_create)]
    )
    
    # 创建敌方角色的会话处理器
    create_enemy_conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler(["create_enemy", "ce"], start_create_enemy)
        ],
        states={
            CREATE_ENEMY_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, create_enemy_name)],
            CREATE_ENEMY_HEALTH: [MessageHandler(filters.TEXT & ~filters.COMMAND, create_enemy_health)],
            CREATE_ENEMY_ATTACK: [MessageHandler(filters.TEXT & ~filters.COMMAND, create_enemy_attack)],
            CREATE_ENEMY_DEFENSE: [MessageHandler(filters.TEXT & ~filters.COMMAND, create_enemy_defense)],
        },
        fallbacks=[CommandHandler("cancel", cancel_create)]
    )
    
    # 其他命令处理器
    handlers = [
        create_conv_handler,
        create_enemy_conv_handler,
        CommandHandler(["characters", "chars"], show_characters),
        CommandHandler("enemies", show_all_enemies),
        CommandHandler(["show", "panel"], show_character_detail),
        CommandHandler("health", modify_health),
        CommandHandler("reset", reset_character_status),
        CommandHandler("reset_all", reset_all_characters_command),
        CommandHandler("end_battle", remove_all_from_battle_command),
        CommandHandler("battle", show_battle_status),
        CommandHandler(["battle_join", "join"], battle_join),
        CommandHandler(["battle_leave", "leave"], battle_leave),
        CommandHandler("help", show_help),
    ]
    
    return handlers
