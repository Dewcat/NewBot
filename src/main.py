import os
import httpx
import logging
from dotenv import load_dotenv
from telegram.ext import Application, CommandHandler, CallbackContext, ConversationHandler, MessageHandler, filters
from telegram import Update
from telegram.request import HTTPXRequest  # 使用 HTTPXRequest 替代原来的 Request
from character.character_management import get_character_management_handlers
from character.race_management import get_race_management_handlers
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
🤖 SimpleBot 命令帮助

📋 角色管理:
/create_character, /cc - 添加新友方角色
/create_enemy, /ce - 添加新敌方角色
/characters, /chars - 查看友方角色
/enemies - 查看敌方角色
/show, /panel - 查看角色详情
/race <角色名> - 管理角色种族和抗性
/health - 修改角色生命值
/reset - 重置角色状态
/reset_all - 重置所有角色状态（包括回合数）

⚔️ 战斗系统:
/attack - 友方攻击/治疗
/enemy_attack - 敌方攻击/治疗
/battle - 查看战斗状态
/battle_join, /join <角色名> - 单个角色加入战斗
/join <角色1> <角色2> ... - 批量加入多个角色
/join all [friendly|enemy] - 全部加入战斗
/battle_leave, /leave <角色名> - 角色离开战斗
/end_battle - 移除所有角色出战斗
/end_turn - 结束当前回合，处理状态效果

🎯 技能管理:
/sm <角色名> - 管理角色技能（支持批量操作）
/skills - 查看角色技能

💡 提示:
- 战斗中生命值为0的角色会自动移出战斗
- 技能选择会根据类型自动过滤目标
- ⚔️ 物理技能受物理抗性影响
- 🔮 魔法技能受魔法抗性影响
- 🏷️ 种族标签影响特攻伤害加成
- 支持批量操作：技能管理和战斗加入都支持批量处理

🎯 伤害系统说明:
- 物理/魔法伤害类型：技能有不同的伤害类型
- 抗性系统：角色可设置物理/魔法抗性减伤
- 特攻系统：某些技能对特定种族有额外伤害
- 种族标签：人类、精灵、机械、龙族等15种可选

🌟 状态效果系统:
技能分为六种类型：伤害、治疗、增益(buff)、减益(debuff)、自我(self)、AOE

📖 技能类型说明:
- 伤害技能：造成伤害，可附带状态效果
- 治疗技能：恢复生命，不受攻防影响，可附带增益效果
- 增益技能：纯buff效果，可选择友方目标
- 减益技能：纯debuff效果，可选择敌方目标
- 自我技能：只对自己生效，无需选择目标
- AOE技能：范围技能，对所有敌方或友方目标生效 🌀

🎯 状态效果目标规则:
- self_buff：施加给施法者自己的增益效果
- self_debuff：施加给施法者自己的减益效果
- buff：施加给目标的增益效果
- debuff：施加给目标的减益效果

💪 增益效果:
- 强壮：攻击伤害+(层数×10%)
- 呼吸法：暴击率+强度×1%，暴击伤害120%
- 守护：受到伤害-(层数×10%)
- 护盾：抵消护盾强度的伤害，被击破后消失

💀 减益效果:
- 烧伤：每回合结束扣强度×1点血
- 中毒：每回合结束扣强度×1%最大生命值
- 破裂：受击时扣强度×1点血并减1层
- 流血：行动后扣强度×1点血并减1层
- 虚弱：攻击伤害-(层数×10%)
- 易伤：受到伤害+(层数×10%)

🎯 技能示例:
- 强壮打击：伤害+给自己强壮(self_buff)
- 守护祝福：纯buff，给选中目标守护(buff)
- 虚弱诅咒：纯debuff，给选中目标虚弱(debuff)
- 狂怒攻击：伤害+给自己强壮(self_buff)
- 疾风步：自我技能，无需选择目标，直接为自己加速(self) 🧘
- 专注冥想：自我技能，无需选择目标，直接减少自己技能冷却(self) 🧘
- 生命献祭：强力治疗盟友，但会损耗自己的生命力 💔
- 吸血攻击：攻击敌人并从中汲取生命力回复自己 💚

💫 自我效果系统:
任何技能都可以添加自我伤害或自我治疗效果：
- self_damage：技能使用后对施法者造成伤害
- self_heal：技能使用后为施法者回复生命值
- 可与任何技能类型组合使用，增加策略深度

📝 批量加入示例:
/join 艾丽丝 鲍勃 查理 - 批量加入多个角色
/join all friendly - 加入所有友方角色
/join all enemy - 加入所有敌方角色

📋 种族管理示例:
/race 艾丽丝 - 为艾丽丝设置种族标签和抗性

🎮 其他命令:
/start - 启动机器人
/help - 显示此帮助信息
/cancel - 取消当前操作
/set_actions <角色名> <次数> - 设置角色每回合行动次数(1-5)

⚡ 行动系统:
- 每个角色每回合有固定的行动次数(默认1次)
- 使用技能会消耗1次行动
- 行动次数耗尽的角色无法被选择攻击
- 回合结束时恢复所有角色的行动次数

🕐 冷却系统:
- 技能使用后进入冷却状态
- 每次使用任意技能会减少所有技能1次行动的冷却时间
- 冷却时间以"次行动"计算，而不是回合
- 加速效果：立即在当前回合增加行动次数，后续回合继续生效
- 冷却缩减：立即减少所有技能的冷却时间
    """
    await update.message.reply_text(help_text)

async def end_turn_command(update: Update, context: CallbackContext) -> None:
    """结束当前回合，处理状态效果"""
    try:
        messages = turn_manager.end_battle_turn()
        
        # 将消息合并成一个字符串发送
        result_text = "\n".join(messages)
        
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
