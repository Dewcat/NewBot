# SimpleBot

一个简化版的Telegram机器人，提供基本的角色管理和单向攻击战斗系统。

## 功能

- 角色管理（创建、查看、修改）
- 状态效果系统（以JSON格式存储）
- 单向攻击系统（无回合制战斗）
- 技能系统（不同伤害倍率的技能）

## 项目结构

- `src/main.py`：机器人主入口
- `src/database/`：数据库连接和查询
- `src/game/`：游戏机制包括攻击系统
- `src/character/`：角色管理命令

## 安装

1. 克隆此仓库
2. 创建一个`.env`文件并添加你的Telegram机器人令牌：
   ```
   TELEGRAM_TOKEN=your_telegram_bot_token_here
   ```
3. 安装依赖：
   ```
   pip install -r requirements.txt
   ```
4. 运行机器人：
   ```
   python src/main.py
   ```

## 命令

- `/start`：启动机器人
- `/create_character`：创建一个新角色
- `/characters`：显示你的所有角色
- `/show_character <角色ID>`：显示角色详细信息
- `/health <角色ID> <生命值>`：修改角色生命值
- `/reset <角色ID>`：重置角色状态
- `/attack`：使用你的角色攻击其他角色
