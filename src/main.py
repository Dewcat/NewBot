import os
import httpx
import logging
from dotenv import load_dotenv
from telegram.ext import Application, CommandHandler, CallbackContext, ConversationHandler, MessageHandler, filters
from telegram import Update
from telegram.request import HTTPXRequest  # 使用 HTTPXRequest 替代原来的 Request
from character.character_management import get_character_management_handlers
from skill.skill_management import get_skill_management_handlers
from game.attack import get_attack_conv_handler, get_enemy_attack_conv_handler
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
🤖 SimpleBot 命令帮助

📋 角色管理:
/add_character - 添加新角色
/list_characters - 查看所有角色
/delete_character - 删除角色
/view_character - 查看角色详情
/edit_character - 编辑角色属性
/reset_all_characters - 重置所有角色状态
/remove_all_from_battle - 移除所有角色出战斗

⚔️ 战斗系统:
/attack - 友方攻击敌方
/enemy_attack - 敌方攻击友方

🎯 技能管理:
/add_skill - 添加新技能
/view_skills - 查看所有技能
/assign_skill - 为角色分配技能

💡 提示:
- 战斗中生命值为0的角色会自动移出战斗
- 技能选择会根据类型自动过滤目标
- ⚔️ 攻击技能只能选择敌方目标
- 💚 治疗技能只能选择友方目标
"""
    await update.message.reply_text(help_text)

# 添加命令处理器
application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("help", help_command))

# 添加角色管理处理器
for handler in get_character_management_handlers():
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
