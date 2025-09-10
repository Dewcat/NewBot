import os
import httpx
import logging
from dotenv import load_dotenv
from telegram.ext import Application, CommandHandler, CallbackContext, ConversationHandler, MessageHandler, filters
from telegram import Update
from telegram.request import HTTPXRequest  # 使用 HTTPXRequest 替代原来的 Request
from character.character_management import get_character_management_handlers
from character.race_management import get_race_management_handlers
from character.persona_management import get_persona_management_handlers
from skill.skill_management import get_skill_management_handlers
from game.attack import get_attack_conv_handler, get_enemy_attack_conv_handler
from game.turn_manager import turn_manager
from database.queries import get_character_by_name, set_character_actions_per_turn
from database.db_migration import run_migrations

# 配置日志
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# 加载环境变量
load_dotenv()

token = os.getenv("TELEGRAM_TOKEN")

# 运行数据库迁移
logging.info("开始运行数据库迁移...")
run_migrations()
logging.info("数据库迁移完成")

# 创建HTTP请求处理器
request = HTTPXRequest(connection_pool_size=50000, 
                       connect_timeout=60, 
                       pool_timeout=60, 
                       proxy="socks5://127.0.0.1:7890")  # 根据需要配置代理

# 创建应用
application = Application.builder()\
    .token(token)\
    .request(request)\
    .build()

async def start(update: Update, context: CallbackContext) -> None:
    """机器人启动命令处理函数"""
    await update.message.reply_text(
        'SimpleBot已启动，这是一个简化版的角色管理和战斗机器人。\n\n'
        '输入 /help 查看所有可用命令。'
    )

async def help_command(update: Update, context: CallbackContext) -> None:
    """显示帮助信息"""
    help_text = """
🤖 SimpleBot 快速帮助

📋 角色管理:
/create_character, /cc - 添加新友方角色
/create_enemy, /ce - 添加新敌方角色
/characters, /chars - 查看友方角色
/enemies - 查看敌方角色
/show, /panel - 查看角色详情
/race <角色名> - 管理角色种族和抗性
/health - 修改角色生命值
/reset - 重置角色状态
/reset_all - 重置所有角色状态

🎭 人格系统:
/create_core <角色名> - 创建核心角色（珏、露、莹、笙、曦）
/persona <角色名> <人格名> - 切换角色人格
/personas <角色名> - 查看角色的可用人格

⚔️ 战斗系统:
/attack - 友方攻击/治疗
/enemy_attack - 敌方攻击/治疗
/battle - 查看战斗状态
/join <角色名> - 角色加入战斗
/join <角色1> <角色2> ... - 批量加入多个角色
/join all [friendly|enemy] - 全部加入战斗
/leave <角色名> - 角色离开战斗
/end_battle - 移除所有角色出战斗
/end_turn - 结束当前回合

🎯 技能管理:
/sm <角色名> - 管理角色技能
/skills - 查看角色技能

🎮 其他命令:
/start - 启动机器人
/help - 显示此帮助信息
/cancel - 取消当前操作
/set_actions <角色名> <次数> - 设置角色每回合行动次数

📖 技能系统说明:
- 🔥 伤害技能: 对敌方造成伤害
- 💚 治疗技能: 恢复友方生命值  
- ✨ 增益技能: 给友方添加正面状态
- 💀 减益技能: 给敌方添加负面状态
- 🧘 自我技能: 只对施法者生效，无需选择目标
- 🌀 AOE技能: 范围技能，对所有目标生效

🔰 新特性 - AOE技能分类:
- aoe_damage: 对所有敌方造成伤害 🔥
- aoe_healing: 治疗所有友方 💚  
- aoe_buff: 给所有友方添加增益 ✨
- aoe_debuff: 给所有敌方添加减益 🔰

🔰 统一百分比效果系统:
- 次要效果支持percentage字段
- 基于主效果数值计算百分比效果
- 例: 造成100伤害，次要治疗20% = 20点治疗

🔰 完整功能说明请查看: SIMPLEBOT_MANUAL.md
包含详细的系统架构、数据库结构、高级功能等说明
    """
    await update.message.reply_text(help_text)

async def end_turn_command(update: Update, context: CallbackContext) -> None:
    """结束当前回合，处理状态效果"""
    try:
        # 首先处理情感升级（回合开始时）
        emotion_upgrade_messages = turn_manager.process_all_emotion_upgrades()
        
        # 然后处理其他回合结束效果
        turn_messages = turn_manager.end_battle_turn()
        
        # 合并所有消息
        all_messages = []
        if emotion_upgrade_messages:
            all_messages.extend(emotion_upgrade_messages)
        all_messages.extend(turn_messages)
        
        # 将消息合并成一个字符串发送
        result_text = "\n".join(all_messages)
        
        # 限制消息长度，防止太长
        if len(result_text) > 4000:
            result_text = result_text[:4000] + "\n...(消息过长已截断)"
        
        await update.message.reply_text(result_text)
    except Exception as e:
        await update.message.reply_text(f"处理回合结束时出错: {str(e)}")

async def set_actions_command(update: Update, context: CallbackContext) -> None:
    """设置角色每回合行动次数"""
    args = context.args
    
    if not args or len(args) < 2:
        await update.message.reply_text(
            "用法: /set_actions <角色名称> <行动次数>\n"
            "例如: /set_actions 艾丽丝 2"
        )
        return
    
    try:
        character_name = " ".join(args[:-1])
        actions_per_turn = int(args[-1])
        
        if actions_per_turn < 1 or actions_per_turn > 5:
            await update.message.reply_text("行动次数必须在1-5之间。")
            return
        
        character = get_character_by_name(character_name)
        if not character:
            await update.message.reply_text(f"找不到名为 '{character_name}' 的角色。")
            return
        
        if set_character_actions_per_turn(character['id'], actions_per_turn):
            await update.message.reply_text(
                f"✅ 已设置角色 '{character_name}' 的每回合行动次数为 {actions_per_turn}。"
            )
        else:
            await update.message.reply_text("设置失败，请稍后再试。")
    
    except ValueError:
        await update.message.reply_text("行动次数必须是一个有效的数字。")
    except Exception as e:
        await update.message.reply_text(f"设置时出错: {str(e)}")

# 添加命令处理器
application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("help", help_command))
application.add_handler(CommandHandler("end_turn", end_turn_command))
application.add_handler(CommandHandler("set_actions", set_actions_command))

# 添加角色管理处理器
for handler in get_character_management_handlers():
    application.add_handler(handler)

# 添加种族管理处理器
for handler in get_race_management_handlers():
    application.add_handler(handler)

# 添加人格管理处理器
for handler in get_persona_management_handlers():
    application.add_handler(handler)

# 添加技能管理处理器
for handler in get_skill_management_handlers():
    application.add_handler(handler)

# 添加攻击处理器
application.add_handler(get_attack_conv_handler())

# 添加敌方攻击处理器
application.add_handler(get_enemy_attack_conv_handler())

# 启动Bot
if __name__ == '__main__':
    application.run_polling()
