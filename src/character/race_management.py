"""
角色种族和抗性管理模块
"""
import json
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackContext, ConversationHandler, CallbackQueryHandler
from database.queries import get_character_by_name, get_db_connection

# 定义种族列表
AVAILABLE_RACES = [
    "human", "elf", "dwarf", "orc", "dragon", 
    "machine", "beast", "undead", "demon", "angel",
    "elemental", "construct", "fey", "giant", "goblinoid"
]

# 种族中文名映射
RACE_NAMES = {
    "human": "人类", "elf": "精灵", "dwarf": "矮人", "orc": "兽人", "dragon": "龙族",
    "machine": "机械", "beast": "野兽", "undead": "不死族", "demon": "恶魔", "angel": "天使",
    "elemental": "元素", "construct": "构装体", "fey": "妖精", "giant": "巨人", "goblinoid": "哥布林"
}

async def character_race_management(update: Update, context: CallbackContext):
    """角色种族管理命令 /race <角色名>"""
    args = context.args
    
    if not args:
        await update.message.reply_text(
            "请提供角色名称。\n用法: /race <角色名>\n\n"
            "此命令用于管理角色的种族标签和抗性属性。"
        )
        return
    
    character_name = " ".join(args)
    character = get_character_by_name(character_name)
    
    if not character:
        await update.message.reply_text(f"找不到角色 '{character_name}'。")
        return
    
    # 显示当前状态和操作菜单
    await show_character_attributes(update, character)

async def show_character_attributes(update, character):
    """显示角色的种族和抗性属性"""
    # 解析当前属性
    race_tags = json.loads(character.get('race_tags', '[]'))
    physical_resistance = character.get('physical_resistance', 0.0)
    magic_resistance = character.get('magic_resistance', 0.0)
    
    # 构建显示文本
    message = f"🧬 {character['name']} 的属性管理\n\n"
    
    # 种族标签
    if race_tags:
        race_display = [RACE_NAMES.get(race, race) for race in race_tags]
        message += f"🏷️ 种族标签: {', '.join(race_display)}\n"
    else:
        message += f"🏷️ 种族标签: 无\n"
    
    # 抗性
    message += f"🛡️ 物理抗性: {physical_resistance:.1%}\n"
    message += f"🔮 魔法抗性: {magic_resistance:.1%}\n\n"
    
    message += "选择要修改的属性："
    
    # 创建操作按钮
    keyboard = [
        [InlineKeyboardButton("🏷️ 管理种族标签", callback_data=f"race_tags_{character['id']}")],
        [InlineKeyboardButton("🛡️ 设置物理抗性", callback_data=f"phys_res_{character['id']}")],
        [InlineKeyboardButton("🔮 设置魔法抗性", callback_data=f"magic_res_{character['id']}")],
        [InlineKeyboardButton("❌ 取消", callback_data="cancel_attr")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(message, reply_markup=reply_markup)

async def handle_race_tags_selection(update: Update, context: CallbackContext):
    """处理种族标签选择"""
    query = update.callback_query
    await query.answer()
    
    character_id = int(query.data.split('_')[2])
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM characters WHERE id = ?", (character_id,))
    character = dict(zip([col[0] for col in cursor.description], cursor.fetchone()))
    conn.close()
    
    current_races = json.loads(character.get('race_tags', '[]'))
    
    message = f"🏷️ {character['name']} 的种族标签管理\n\n"
    message += "当前种族: " + (", ".join([RACE_NAMES.get(race, race) for race in current_races]) if current_races else "无") + "\n\n"
    message += "点击种族来添加/移除："
    
    # 创建种族选择按钮
    keyboard = []
    for i in range(0, len(AVAILABLE_RACES), 2):
        row = []
        for j in range(2):
            if i + j < len(AVAILABLE_RACES):
                race = AVAILABLE_RACES[i + j]
                is_selected = race in current_races
                icon = "✅" if is_selected else "⭕"
                text = f"{icon} {RACE_NAMES[race]}"
                row.append(InlineKeyboardButton(text, callback_data=f"toggle_race_{character_id}_{race}"))
        keyboard.append(row)
    
    keyboard.append([InlineKeyboardButton("✅ 完成", callback_data=f"finish_race_{character_id}")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(message, reply_markup=reply_markup)

async def toggle_race_tag(update: Update, context: CallbackContext):
    """切换种族标签"""
    query = update.callback_query
    await query.answer()
    
    parts = query.data.split('_')
    character_id = int(parts[2])
    race = parts[3]
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT race_tags FROM characters WHERE id = ?", (character_id,))
    result = cursor.fetchone()
    
    current_races = json.loads(result[0] if result[0] else '[]')
    
    if race in current_races:
        current_races.remove(race)
    else:
        current_races.append(race)
    
    cursor.execute("UPDATE characters SET race_tags = ? WHERE id = ?", 
                   (json.dumps(current_races), character_id))
    conn.commit()
    conn.close()
    
    # 重新显示种族选择界面
    context.user_data['character_id'] = character_id
    await handle_race_tags_selection(update, context)

async def finish_race_selection(update: Update, context: CallbackContext):
    """完成种族标签选择"""
    query = update.callback_query
    await query.answer()
    
    character_id = int(query.data.split('_')[2])
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT name, race_tags FROM characters WHERE id = ?", (character_id,))
    result = cursor.fetchone()
    character_name, race_tags_json = result
    conn.close()
    
    current_races = json.loads(race_tags_json if race_tags_json else '[]')
    
    if current_races:
        race_display = [RACE_NAMES.get(race, race) for race in current_races]
        message = f"✅ {character_name} 的种族标签设置完成！\n\n"
        message += f"🏷️ 当前种族: {', '.join(race_display)}"
    else:
        message = f"✅ {character_name} 的种族标签设置完成！\n\n"
        message += f"🏷️ 当前种族: 无"
    
    await query.edit_message_text(message)

async def cancel_attribute_management(update: Update, context: CallbackContext):
    """取消属性管理"""
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text("❌ 已取消属性管理。")

async def set_resistance(update: Update, context: CallbackContext):
    """设置抗性值"""
    query = update.callback_query
    await query.answer()
    
    parts = query.data.split('_')
    resistance_type = parts[0] + "_" + parts[1]  # phys_res 或 magic_res
    character_id = int(parts[2])
    
    resistance_name = "物理抗性" if resistance_type == "phys_res" else "魔法抗性"
    
    message = f"🔧 设置{resistance_name}\n\n"
    message += "请输入抗性值 (0.0-0.9):\n"
    message += "• 0.0 = 无抗性 (0%)\n"
    message += "• 0.3 = 减伤30%\n"
    message += "• 0.5 = 减伤50%\n"
    message += "• 0.9 = 减伤90% (最大)\n\n"
    message += "输入数值或点击预设值："
    
    keyboard = [
        [InlineKeyboardButton("0% (无抗性)", callback_data=f"set_{resistance_type}_{character_id}_0.0")],
        [InlineKeyboardButton("20%", callback_data=f"set_{resistance_type}_{character_id}_0.2"),
         InlineKeyboardButton("30%", callback_data=f"set_{resistance_type}_{character_id}_0.3")],
        [InlineKeyboardButton("50%", callback_data=f"set_{resistance_type}_{character_id}_0.5"),
         InlineKeyboardButton("70%", callback_data=f"set_{resistance_type}_{character_id}_0.7")],
        [InlineKeyboardButton("❌ 取消", callback_data="cancel_attr")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(message, reply_markup=reply_markup)

async def apply_resistance_value(update: Update, context: CallbackContext):
    """应用抗性数值"""
    query = update.callback_query
    await query.answer()
    
    parts = query.data.split('_')
    resistance_type = parts[1] + "_" + parts[2]  # phys_res 或 magic_res
    character_id = int(parts[3])
    value = float(parts[4])
    
    column_name = "physical_resistance" if resistance_type == "phys_res" else "magic_resistance"
    resistance_name = "物理抗性" if resistance_type == "phys_res" else "魔法抗性"
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(f"UPDATE characters SET {column_name} = ? WHERE id = ?", (value, character_id))
    conn.commit()
    
    cursor.execute("SELECT name FROM characters WHERE id = ?", (character_id,))
    character_name = cursor.fetchone()[0]
    conn.close()
    
    await query.edit_message_text(
        f"✅ 成功设置 {character_name} 的{resistance_name}为 {value:.1%}"
    )

# 导出处理器
def get_race_management_handlers():
    """获取种族管理相关的处理器"""
    from telegram.ext import CommandHandler
    
    handlers = [
        CommandHandler("race", character_race_management),
        CallbackQueryHandler(handle_race_tags_selection, pattern=r"^race_tags_\d+$"),
        CallbackQueryHandler(toggle_race_tag, pattern=r"^toggle_race_\d+_\w+$"),
        CallbackQueryHandler(finish_race_selection, pattern=r"^finish_race_\d+$"),
        CallbackQueryHandler(set_resistance, pattern=r"^(phys_res|magic_res)_\d+$"),
        CallbackQueryHandler(apply_resistance_value, pattern=r"^set_(phys_res|magic_res)_\d+_\d+\.\d+$"),
        CallbackQueryHandler(cancel_attribute_management, pattern=r"^cancel_attr$"),
    ]
    
    return handlers
