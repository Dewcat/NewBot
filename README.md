# Dewbot v2

Dewbot v2 是一个数据驱动的回合制战斗机器人，提供两个可互换前端：**Telegram Bot** 与 **本地 Web UI**（Telegram/Discord 风格聊天界面）。二者共用同一套引擎、数据库与内容包，启动时二选一，同一时间只允许运行一个（数据库旁的心跳锁文件互斥）。新版入口位于 `src/dewbot/`；旧的 `src/character`、`src/game`、`src/skill` 等模块保留作历史参考，但启动入口已经不再导入它们。

核心回合固定为：

```text
回合开始 → 管理员设置并锁定敌方技能与目标 → 玩家攻击立即结算／防御待命 → 执行敌方指令 → 回合结束
```

详细交互规则见 [回合指令说明](TURN_COMMANDS.md)。战斗没有攻击拼点和同步行动，闪避保留点数比较及成功复用。通用效果在回合结束清空；下一回合效果先进入待生效队列；普通技能冷却只在全场 `TURN_END` 推进；EGO 每角色每战任意一个只能使用一次；情感等级 4 的额外行动在 Battle End 回收。

## 本地启动

要求 Python 3.12：

```powershell
python -m pip install -e ".[test]"
```

`.env`：

```dotenv
# —— Telegram 前端 ——
TELEGRAM_TOKEN=你的机器人令牌
DEWBOT_ADMIN_IDS=123456789,987654321
# 可选；未设置时绝不会强制使用本地代理
TELEGRAM_PROXY=socks5://127.0.0.1:7890

# —— Web 前端（两把访问密钥分别对应管理人与玩家）——
DEWBOT_WEB_GM_KEY=改成你的管理密钥
DEWBOT_WEB_PLAYER_KEY=改成玩家的密钥
# 可选；默认 127.0.0.1:8787
DEWBOT_WEB_HOST=127.0.0.1
DEWBOT_WEB_PORT=8787
# 可选；确认全程 HTTPS（隧道/反向代理）后设为 1，让密钥 Cookie 拒绝走明文 HTTP
DEWBOT_WEB_SECURE_COOKIE=0

# —— 共享 ——
# 可选；Windows 下用分号按依赖顺序列出文件/目录
DEWBOT_CONTENT_PATHS=content/base_pack.json;content/core_personas.json
DEWBOT_DB_PATH=src/data/dewbot_v2.db
```

启动时选择一个前端：

```powershell
# 方式一：Telegram Bot 前端
dewbot-telegram        # 或 $env:PYTHONPATH='src'; python -m dewbot.telegram_app

# 方式二：Web 前端（浏览器打开 http://127.0.0.1:8787，输入访问密钥登录）
dewbot-web             # 或 $env:PYTHONPATH='src'; python -m dewbot.web.server
```

两个前端功能完全对等（Telegram 命令 ↔ 网页按钮的映射见 [WEB_FRONTEND_GUIDE.md](WEB_FRONTEND_GUIDE.md)）。战斗数据存在数据库里，今天用 Telegram 打的战斗明天可以开网页端接着打。若另一前端仍在运行，启动会被互斥锁拒绝（崩溃后约 60 秒心跳过期自动解锁）。

启动时会自动迁移数据库，并依据 `pack.requires` 对本地内容包排序后加载。没有硬编码 Token、管理员或代理；模块导入也不会建立网络连接或修改数据库。

## 让 Web 前端可从外网访问

服务本身默认只监听 `127.0.0.1`。对外提供访问时**不要**直接把端口暴露成明文 HTTP——密钥 Cookie 会在网络上裸奔。推荐两条路线（都不需要改任何代码）：

1. **内网穿透隧道（推荐，无需公网 IP）**：保持 `DEWBOT_WEB_HOST=127.0.0.1` 不变，用 Cloudflare Tunnel、Tailscale Funnel 或 frp+VPS（国内更稳）把 `127.0.0.1:8787` 映射到一个 HTTPS 域名。隧道客户端在本机回环口转发，uvicorn 默认信任来自 127.0.0.1 的 `X-Forwarded-For`，登录限速看到的仍是真实访客 IP。
2. **公网 IP + 反向代理**：有公网 IP 时用 Caddy/Nginx 做 HTTPS 终端（Caddy 一行 `reverse_proxy 127.0.0.1:8787` 自动签证书），路由器只转发 443。

无论哪条路线，对外后请：把两把密钥换成长随机串（`python -c "import secrets;print(secrets.token_urlsafe(24))"`），并在确认全程 HTTPS 后设 `DEWBOT_WEB_SECURE_COOKIE=1`。内置防线：登录接口按来源 IP 限速（10 分钟内失败 10 次即暂时封禁，每次失败附加延迟），非回环监听时启动会直接拒绝长度不足 12 位的密钥。

## 管理与烟雾测试

```powershell
$env:PYTHONPATH='src'
python -m dewbot.cli init-db
python -m dewbot.cli load-content content/base_pack.json
python -m dewbot.cli load-content content/core_personas.json
python -m dewbot.cli simulate
```

主要 Telegram 指令：

- `/roster`、`/personas`、`/skills`：查阅角色、人格和当前我方技能；建立可命名的普通友方与战斗外切换人格分别使用 `/create [名称]`、`/identity`。
- `/new 名称`：建立一场待触发战斗，随后用中文按钮选择关卡。
- `/battles`、`/use 编号`：查看并选中待触发或正在进行的战斗；每位管理员在每个群聊/私聊中的选择独立保存。
- `/team`：勾选核心角色，再依次用按钮装备本次战斗人格。
- `/ally`、`/foe`：用按钮追加普通友方或指定阶段敌人；战前手动追加的敌人可从 `/foe` 移除。
- `/plan`、`/ready`：检查当前选中的编成、阶段条件，并在二次确认后触发战斗；确认后若任何编成发生变化，旧确认会安全失效。`/discard` 可确认撤销待触发记录。
- `/gear`：战前勾选装备的异想体，决定本场战斗的书页池；保存会推进编成修订号，需重新 `/ready` 确认。
- 日常流程不需要输入 `encounter.*`、`persona.*`、`enemy.*` 等内部内容键。
- 新建的战斗处于“待触发”（`STANDBY`）：预设敌人已经就位，选择核心角色及人格后才能开战；普通友方和额外敌人可在战前或战中增援。
- 阶段切换/胜利条件由关卡数据定义，可使用敌方全灭、首领被击败或首领生命降至阈值。
- `/enemy` 设置敌方技能与目标，`/lock` 锁定后交给玩家；`/attack` 立即行动，`/defend 角色编号 [敌方指令编号]` 发布防御，`/pass` 进入敌方攻击阶段，`/settle` 执行已锁定指令并统一清算；`/next` 勾选进入下一阶段的我方阵容（默认全选）后展开下一阶段，`/stop` 中止战斗。
- `/battle`：查看当前战斗档案，包含每个单位身上的活动效果、硬血资源与下回合待生效效果。
- `/pages`、`/manager`：异想体书页与剧情解锁的管理人能力。
- `/reload`：无活动战斗时重载配置内容包；`/whoami` 显示配置管理员所需的 Telegram 用户编号。

带“管理”性质的写操作由 `DEWBOT_ADMIN_IDS` 控制；敌方未选技能目录只向管理员提供；已发布指令的技能与目标公开显示在战斗档案中。Telegram 群组无法把同一条内联键盘真正隐藏给其他成员，因此系统同时使用匿名公共按钮、发起者校验和短期 nonce 防止旁人或旧按钮操作。

## 架构

可选的[但丁笔记](STORY_ARCHIVE_GUIDE.md)默认关闭。设置 `DEWBOT_STORY_ENABLED=1` 后，管理人可安排条目的剧情解锁进度，玩家通过 Web 或 Telegram `/notes` 查阅。初始进度为第四章第一部分结束（东柏刺伤李箱），笔记使用独立数据库，不参与战斗结算。

[AI 写作与隐私模式](AI_PRIVACY_GUIDE.md)：管理人可随时切换隐私模式，开启期间的聊天永久排除出 AI 上下文。写作需先选择并预览材料，再调用模型 API 或导出给 Codex 等工具；玩家可见范围与 AI 许可分别控制。升级前历史默认排除，未配置 API 也可导出。

- `schema.py` / `db.py`：版本化、并发安全的 SQLite 迁移和事务边界。
- `content.py`：幂等内容包、跨包依赖、所有权、反向依赖与语义校验。
- `engine.py`：阶段状态机、五段技能时机、目标解析、事件钩子、效果、情感、EGO 和日志。
- `effects.py`：以稳定 handler key 注册新机制的策略表。
- `telegram_app.py`：Telegram 前端适配层；只负责权限、交互和文案，所有规则仍由引擎事务裁决。
- `web/`：Web 前端（FastAPI JSON API + SSE 实时播报 + 无构建步骤的聊天风 SPA）；与 Telegram 适配层调用同一引擎接口，权限为管理人/玩家两级密钥。
- `runlock.py`：前端互斥锁，保证同一数据库同时只被一个前端使用。

角色、人格、技能、效果、书页和管理人能力的扩展方法见 [CONTENT_PACK_GUIDE.md](CONTENT_PACK_GUIDE.md)。示例 [content/example_extension.json](content/example_extension.json) 不会默认加载，可作为跨包追加既有角色人格的作者模板。

## 测试

```powershell
pytest -q
```

测试覆盖内容包幂等/跨包组合、迁移、阶段权限、冷却、通用/延迟/常规状态、情感 4 级、EGO、Telegram 路由与敌方技能情报隔离。数据库文件 `src/data/dewbot*.db` 属于运行态，已从版本控制中排除；旧数据库不会被新版入口自动改写。
