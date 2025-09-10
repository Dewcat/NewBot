# SimpleBot - Telegram RPG战斗机器人

![Python](https://img.shields.io/badge/Python-3.8+-blue.svg)
![Telegram](https://img.shields.io/badge/Telegram-Bot-blue.svg)
![SQLite](https://img.shields.io/badge/Database-SQLite-green.svg)
![License](https://img.shields.io/badge/License-MIT-green.svg)

一个功能丰富的Telegram角色扮演游戏战斗机器人，支持角色管理、技能系统、回合制战斗、状态效果和种族系统。

## ✨ 主要特性

### 🎭 角色管理系统
- **多角色支持**: 创建和管理友方/敌方角色
- **属性系统**: 生命值、攻击力、防御力、魔法攻击、魔法防御
- **种族系统**: 15种可选种族，支持伤害抗性
- **人格系统**: 核心角色支持多重人格切换

### ⚔️ 战斗系统
- **回合制战斗**: 完整的回合管理和状态处理
- **智能目标选择**: 根据技能类型自动过滤目标
- **伤害计算**: 支持物理/魔法伤害类型和抗性系统
- **特攻机制**: 对特定种族的额外伤害加成

### 🎯 技能系统
- **9种技能分类**: damage, healing, buff, debuff, self, aoe_damage, aoe_healing, aoe_buff, aoe_debuff
- **复杂效果系统**: 主效果 + 次要效果的组合机制
- **百分比效果**: 基于主效果数值的动态百分比计算
- **冷却系统**: 以"次行动"为单位的技能冷却

### 🌟 状态效果系统
- **增益状态**: 强壮、🔰守护、呼吸法、护盾等
- **减益状态**: 烧伤、中毒、虚弱、易伤等
- **状态叠加**: 支持状态层数和持续时间管理
- **触发机制**: 回合开始/结束、受击时、行动后等触发时机

## 🚀 快速开始

### 环境要求
- Python 3.8+
- python-telegram-bot
- SQLite3

### 安装步骤

1. **克隆仓库**
```bash
git clone https://github.com/Dewcat/NewBot.git
cd NewBot
```

2. **安装依赖**
```bash
pip install -r requirements.txt
```

3. **配置环境**
创建`.env`文件并添加你的Telegram Bot Token：
```
TELEGRAM_TOKEN=your_bot_token_here
```

4. **运行机器人**
```bash
cd src
python main.py
```

### 基础使用

1. **创建角色**
```
/cc 艾丽丝 100 15 10 12 8
```

2. **加入战斗**
```
/join 艾丽丝
```

3. **使用技能**
```
/attack
```

4. **查看帮助**
```
/help
```

## 📚 文档

- **[用户手册](SIMPLEBOT_MANUAL.md)**: 完整的功能说明和使用指南
- **[API文档](SIMPLEBOT_API.md)**: 开发者API接口说明
- **[系统报告](UNIFIED_PERCENTAGE_SYSTEM_REPORT.md)**: 最新的系统更新和特性说明

## 🏗️ 系统架构

```
SimpleBot/
├── src/
│   ├── character/          # 角色管理模块
│   ├── skill/             # 技能系统模块  
│   ├── game/              # 游戏逻辑模块
│   ├── database/          # 数据库模块
│   └── main.py           # 主程序入口
├── data/
│   └── simplebot.db      # SQLite数据库
├── docs/                 # 文档目录
└── tests/               # 测试脚本
```

## 🔧 核心技术

- **Telegram Bot API**: 基于python-telegram-bot框架
- **SQLite数据库**: 轻量级数据存储
- **JSON效果系统**: 灵活的技能效果配置
- **模块化设计**: 清晰的代码组织结构

## 🆕 最新特性 (v2.0)

### 统一百分比效果系统
- ✅ AOE技能细分：aoe_damage, aoe_healing, aoe_buff, aoe_debuff
- ✅ 主次效果分离：skill_category决定主效果，effects JSON包含次要效果
- ✅ 百分比计算：支持基于主效果数值的动态百分比效果
- ✅ 目标解析优化：统一的目标类型解析系统

### 示例：百分比效果技能
```json
{
  "damage": {
    "target": "skill_target",
    "percentage": 20
  },
  "heal": {
    "target": "self", 
    "amount": 15
  }
}
```
如果主效果造成100点伤害，则次要伤害效果造成20点伤害，同时固定治疗施法者15点生命值。

## 🎮 游戏特色

### 策略深度
- **资源管理**: 生命值、行动次数、技能冷却的平衡
- **状态博弈**: 增益减益状态的互相制衡
- **种族克制**: 特攻系统增加战术选择
- **技能组合**: 主次效果的巧妙搭配

### 扩展性强
- **模块化架构**: 易于添加新功能
- **JSON配置**: 灵活的技能和效果定义
- **数据库迁移**: 自动的数据结构更新
- **API友好**: 完整的编程接口

## 📊 系统数据

- **技能总数**: 77个技能
- **AOE技能**: 11个（已细分分类）
- **状态效果**: 10+种增益减益状态
- **种族类型**: 15种可选种族
- **技能分类**: 9种技能类型

## 🤝 贡献指南

1. Fork 本仓库
2. 创建特性分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 开启 Pull Request

## 📝 更新日志

### v2.0.0 (2025-01-06)
- ✨ 新增统一百分比效果系统
- 🔄 AOE技能细分分类
- ⚡ 目标解析系统优化
- 🐛 修复"战场支配"等技能的分类问题

### v1.5.0
- ✨ 添加AOE技能系统
- 🔧 优化状态效果处理
- 📚 完善文档系统

### v1.0.0
- 🎉 初始版本发布
- ⚔️ 基础战斗系统
- 🎭 角色管理功能

## 📄 许可证

本项目采用 MIT 许可证 - 查看 [LICENSE](LICENSE) 文件了解详情

## 📞 联系方式

- GitHub Issues: [提交问题](https://github.com/Dewcat/NewBot/issues)
- 项目维护者: Dewcat

---

**SimpleBot - 让每一场战斗都充满策略与乐趣！** ⚔️✨
