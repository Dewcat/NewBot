# Dewbot Web 前端指南（架构与 API 契约）

更新时间：2026-07-26。本文件是 Web 前端（`src/dewbot/web/`）的权威契约：后端 API 与浏览器 SPA 都以此为准。游戏规则仍以 `todo.txt` > `REFACTOR_GUIDE.md` 为权威；本文件只约定传输层。

## 1. 定位与总体架构

- Dewbot 有两个可互换前端：Telegram Bot（`telegram_app.py`）与 Web UI（`web/`）。二者共用同一个 `BattleEngine`、同一个 SQLite 数据库、同一套内容包。
- **同一时间只允许运行一个前端**：启动时通过 `runlock.FrontendLock`（数据库文件旁的心跳锁文件）互斥；另一前端存活时启动会直接报错。
- 启动方式二选一：`dewbot-telegram` 或 `dewbot-web`（等价 `python -m dewbot.web.server`）。
- Web 层结构：
  - `src/dewbot/web/server.py` — FastAPI 应用工厂 `create_app(settings, engine=None, loader=None)`（依赖注入方式与 `telegram_app.create_application` 一致）与 `main()` 入口（初始化数据库/内容包/校验 handler → FrontendLock → uvicorn）。
  - `src/dewbot/web/static/` — 无构建步骤的单页应用（`index.html`、`app.js`、`style.css`），由 FastAPI 静态托管，`GET /` 返回 `index.html`。
- 单玩家部署：只有两个角色（见 §2），无注册/多租户概念。默认只监听 `127.0.0.1`。

## 2. 身份与权限

- `.env` 配置 `DEWBOT_WEB_GM_KEY`（管理人）与 `DEWBOT_WEB_PLAYER_KEY`（玩家）。未配置的角色无法登录；两者都未配置时服务拒绝启动。
- 登录：`POST /api/login {"key": "..."}` → 校验后 `Set-Cookie: dewbot_key=<key>; HttpOnly; SameSite=Lax`，响应 `{"role": "gm"|"player"}`。`POST /api/logout` 清除。
- 每个请求按 cookie 现算角色；无效/缺失 → 401 `{"error": "..."}`。
- 权限与 Telegram 对齐：玩家可用 = 只读查询 + 我方行动 + 结束回合（`/api/battle/pass`）+ 经理干预 + 书页选取 + 常备卡组 + 已发布编成的确认/调整；其余全部 GM。玩家调用 GM 接口 → 403。（2026-07-26 裁定后的口径，细节见 §7.5。）
- 敌方信息隐私与 Telegram 对齐：玩家角色永远拿不到敌方技能详情（服务端过滤，不靠前端隐藏）。
- 两把密钥不允许相同（同一把钥匙会先匹配到管理人，玩家将永远无法登录），`create_app` 直接拒绝。
- 公网加固：登录按来源 IP 限速——10 分钟窗口内失败满 10 次返回 429，每次失败附加约 0.3s 延迟；成功登录清零计数。`DEWBOT_WEB_SECURE_COOKIE=1` 时 Cookie 附加 `Secure` 标记（全程 HTTPS 部署用）。非回环 `DEWBOT_WEB_HOST` 且任一密钥短于 12 字符时 `main()` 拒绝启动。部署路线见 README「让 Web 前端可从外网访问」。

## 3. 通用约定

- 所有接口前缀 `/api`，请求/响应均 JSON（UTF-8）。
- 错误统一 `{"error": "<中文可读信息>"}`，状态码 400（规则拒绝，含 `BattleRuleError`/`ContentValidationError`）、401、403、409（前端互斥/修订号过期）。
- 所有**写操作**在服务端经全局 `asyncio.Lock` + `asyncio.to_thread` 串行执行（与 Telegram 适配器完全一致），成功响应统一含 `{"messages": [...]}`（引擎播报行）。
- 写操作成功后，服务端向 SSE 广播该批 `messages`。

## 4. SSE 实时流

- `GET /api/events`（需登录）→ `text/event-stream`。
- 事件格式：`event: log`，`data: {"lines": ["...","..."]}`；另有 `event: refresh`，`data: {}`（提示前端重拉 `/api/overview`；每次广播 log 后跟一条）。
- 连接建立时先回放当前活动战斗 `battle_logs` 表最近 50 条（`data: {"lines": [...], "replay": true}`）。
- 心跳：每 25 秒发注释行 `: ping`。

## 5. 只读接口（登录即可，标注 GM 的除外）

| 接口 | 映射 | 说明 |
| --- | --- | --- |
| `GET /api/session` | — | `{role, has_active_battle, phase}` |
| `GET /api/overview` | `battle_status()` + `battle_setup_status()` + `pending_page_offers()` | 侧栏一次拉全：`{battle, setup, page_offers, role}`；无活动战斗/未选中编成时对应字段为 null（内部吞 `BattleRuleError`） |
| `GET /api/roster?faction=FRIENDLY\|ENEMY` | `list_characters(faction)` | |
| `GET /api/characters/{id}/personas` | `list_personas(id)` | |
| `GET /api/characters/{id}/skills` | `skill_catalog(id)` | 敌方角色 → 仅 GM |
| `GET /api/battle` | `battle_status()` | 含每单位 `effects`/`pending_effects` |
| `GET /api/battles` | `list_battle_setups()` | GM |
| `GET /api/plan` | `battle_setup_status(user_id=0)`… | 用 `setup_id=None` 默认路径：Web 端全局只有一个"当前选中"，见 §7 |
| `GET /api/encounters` | `list_encounters()` | GM |
| `GET /api/templates` | `list_templates()` | GM |
| `GET /api/abnormalities` | `list_abnormalities()` | GM |
| `GET /api/pages` | `pending_page_offers()` | |
| `GET /api/manager` | 同 Telegram `_available_manager_skills` 查询 | GM |
| `GET /api/battle/actors?side=f\|e` | 从 `battle_status()` 过滤可行动者 | `e` 仅 GM |
| `GET /api/actors/{id}/skills` | `list_skills(id, available_only=True)` | 敌方 actor 仅 GM |
| `GET /api/actors/{id}/skills/{skill_id}/targets` | `legal_targets(id, skill_id)` | 同上 |

## 6. 写接口

玩家可用（仅此一个，且服务端校验 actor 是我方、当前为我方行动阶段——引擎会二次裁决）：

| 接口 | 映射 |
| --- | --- |
| `POST /api/battle/action {actor_id, skill_id, target_ids?}` | `use_skill(actor_id, skill_id, target_ids or None)`；敌方 actor 时要求 GM |

GM 专用：

| 接口 | 映射 |
| --- | --- |
| `POST /api/setup/new {name, encounter_key}` | `prepare_encounter(...)` 后自动选中（等价 /new + 按钮选关卡） |
| `POST /api/setup/use {setup_id}` | `select_battle_setup(user_id=0, setup_id, chat_id=0)` |
| `POST /api/setup/discard` | `cancel_battle_setup(...)` |
| `POST /api/setup/core {choices: [[character_id, persona_id], ...]}` | `replace_core_formation(setup_id, choices)` |
| `POST /api/setup/allies/add {character_ids}` | `add_noncore_friendlies_to_setup(...)` |
| `POST /api/setup/allies/remove {character_id}` | `remove_noncore_friendly_from_setup(...)` |
| `POST /api/setup/foes/add {template_key, stage_number, name?}` | `add_enemy_to_formation(...)`（以引擎实际签名为准） |
| `POST /api/setup/foes/remove {setup_enemy_id}` | `remove_manual_enemy_from_setup(...)` |
| `POST /api/setup/gear {abnormality_keys}` | `set_setup_abnormalities(...)` |
| `GET /api/setup/ready` | 触发前核对：返回编成摘要 + `revision`（复用 `battle_setup_status`） |
| `POST /api/setup/launch {revision}` | `launch_prepared_battle(..., expected_revision=revision)`（以引擎实际签名为准；修订不符 → 409） |
| `POST /api/battle/pass` | `end_friendly_phase()` |
| `POST /api/battle/settle` | `end_turn()` |
| `POST /api/battle/next {friendly_ids}` | `start_prepared_stage(friendly_ids)` |
| `POST /api/battle/stop` | `end_battle("ABORTED")` |
| `POST /api/pages/{offer_id}/accept` | `choose_page(offer_id)` |
| `POST /api/manager/{skill_key}/use` | `use_manager_skill(skill_key)` |
| `POST /api/identity {character_id, persona_key}` | `switch_persona(...)`（战斗外人格切换） |
| `POST /api/create {template_key, name?}` | `spawn_character(template_key, FRIENDLY, name)` |
| `POST /api/reload` | 与 Telegram `/reload` 相同的加载流程（按 `settings.content_paths` 展开、拓扑序加载、`validate_content_handlers`） |

## 7. 与 Telegram 的语义差异（有意为之）

- Telegram 的"当前选中战斗"按（用户,聊天）保存；Web 端单玩家部署固定用 `user_id=0, chat_id=0` 一条全局选择，两个前端互不干扰。
- Telegram 的按钮 nonce/15 分钟超时在 Web 端由登录会话 + `/api/setup/launch` 的 `revision` 参数替代：确认页取到的修订号过期即 409，语义等同"编成变化让旧确认失效"。
- 引擎播报中的 `/next`、`/pages` 等命令名提示在 Web 端原样显示（页面上有对应按钮，不致误导）；后续如需分前端文案再改。

## 7.5 身份职能与流程裁定（2026-07-26，用户逐条定调；高于本文其余描述）

1. **角色扮演分工**：管理人扮演 NPC（敌方 + 友方助战）；玩家扮演五名核心角色的经理。UI 标签：核心不挂标签，友方非核心挂「助战」，带 `boss` 标签（tags_json）的敌人挂「BOSS」。**回合行动顺序：回合开始 → 友方助战 → 友方玩家（核心）→ 敌方 → 结束**；引擎在 `_use_skill` 中强制（助战尚有行动时核心不可行动），GM 可经 `POST /api/battle/forfeit-assists`（Telegram `/yield`）"助战让行"。
2. **干预能力（原"管理人权限树"，即光之树苗）**：属于玩家（经理）的战局手段，不是 GM 工具；每场次数与合法窗口沿用 `manager_skills` 表；Web 端「干预」栏目双角色可见，播报文案为【经理干预】。
3. **战斗频道 = 跑团聊天主频道**（已实现）：聊天记录跨战斗连续存储（`chat_messages` 表，迁移 V15），战斗播报按时间穿插其中（`GET /api/channel/history` 合并回放；SSE `/api/events?replay=0` 只推增量）。玩家发言固定为「经理」身份；GM 输入 `角色名：“内容”`（中英文冒号/引号均可）即以该 NPC 发言，否则为旁白。接口：`POST /api/chat`（发送）、`POST /api/chat/{id}/edit|revoke`（仅作者，撤回为软删除）、`POST /api/chat/read {up_to_id}`（按角色已读，SSE `chat_read` 推送 ✓✓）、`GET /api/chat?before_id=&limit=`（翻页）、`GET /api/chat/search?q=`。UI：Telegram 式日期分隔线（今天/昨天/X月X日）+ 每条 HH:MM、自己消息 ✓/✓✓、气泡「···」菜单编辑/撤回、频道底部输入栏（Enter 发送 Shift+Enter 换行）、🔍 搜索弹窗。
4. **异想体书页**（已实现，2026-07-27 扩充）：每个异想体是一副小卡组——分级（1-3 级）的觉醒/崩溃页 + 一个「携带被动」（`carry_bonus`→`page_type='CARRY'` 行，迁移 V18；不进抽取池，开战即自动激活并播报，事件挂在首位友方核心名下驱动）。**分段解锁**：候选页等级只由升级者**本人**的情感等级决定，且是"解锁上限"语义（2026-07-27 裁定）——情感 1-2 可出Ⅰ级页、3-4 解锁至Ⅱ级、5 解锁至Ⅲ级；低级页始终留在候选池内。**携带上限 5 个**（`set_page_deck`/`set_setup_gear` 双端强制）；带得少候选更固定、带得多更随机但携带被动更多。每个异想体小卡组**固定 3 页**（2026-07-27 补充裁定）。**开放管理**：异想体默认不对玩家开放（`abnormality_access` 表，V19；迁移时既有条目自动视为已开放），GM 在书页页「开放管理」面板逐个开放/收回（`POST /api/abnormalities/access`）；未开放的对玩家完全不可见，也不能进卡组/预设/本场装备（引擎统一校验），发布编成带入卡组时同样过滤。内容库 `content/ruina_pages.json` 移植了废墟图书馆 28 个异想体（每组 3 页 + 携带被动，效果经本地化改良映射到 hook_apply_effect/hook_heal/hook_damage/bonus_actions/emotion_shift/fortune_verdict，多步效果用 `hook_sequence` 组合——**崩溃页一律双刃剑**：强增益+代价两步，或命运判定式赌局；2026-07-27 补充裁定）。GM 战斗编成不再有「异想体装备」栏（书页归玩家决定）；GM 书页页「当前携带」只列已开放的异想体，未开放的只在「开放管理」出现。**人格同理有开放门控**（`persona_access` 表，V20；迁移时既有人格视为已开放，新加载的默认关闭）：GM 在阵容页人格行上开放/收回（`POST /api/personas/access`）；**默认人格恒开放且不可收回**；未开放人格对玩家不可见（装备中的仍显示）、不能切换也不能编入出战（`/api/identity` 已开放给玩家为核心换人格，玩家侧带 `enforce_access`；`replace_core_formation` 同步校验，默认/当前装备豁免）。**预设编队**（`page_deck_presets`）：书页页面可保存/应用/删除预设（`POST /api/deck/presets`、`POST /api/deck/presets/{id}/delete`），玩家确认界面可一键应用预设到本场卡组。`GET /api/deck` 返回 `{deck, abnormalities(含 pages+carry_bonus), presets}`（`abnormality_catalog()`）。玩家常备卡组存于 `player_page_deck`（V16），GM「发布」时自动带入该场 `abnormalities_json` 并把出战核心人格同步为玩家阵容界面的当前配置。
5. **战斗编成单栏目**（已实现）：导航合并为「战斗编成」（战斗列表成为其中一个区块）。GM 流程：新建/选中 → **圈定可参战核心**（`POST /api/setup/core-pool`，V17 `core_pool_json`；池内核心自动以激活人格补入编成，池外移出）→ 编排助战/敌人（**预设与手动敌人均可移除或切换携带**：`POST /api/setup/foes/remove`、`POST /api/setup/foes/toggle`（V21 `battle_setup_enemies.enabled`）；「不携带」的敌人开战/进阶段时不生成，触发前置检查按携带中的敌人计算；预设阶段可删：`POST /api/setup/stages/remove`，删的是本场快照、模板本体不动，后续阶段自动前移补位）→ `POST /api/setup/publish`（`battle_setups.published=1`，revision+1，SSE `setup_published`）。玩家侧：收到横幅通知与 info 弹窗 → 编成页显示确认界面（关卡/阶段数/助战名单/敌人仅数量——`/api/plan` 对玩家剥离 `enemies` 只给 `enemy_count`）→ **从可参战池中勾选出战核心并指定人格**（`/api/setup/core`，引擎拒绝池外核心）与本场卡组（`/api/setup/gear`）→「确认并开战」（`/api/setup/ready`+`/api/setup/launch`，revision 过期即 409 需重新核对）。以上玩家侧编成接口仅在 `published=1` 时放行（`_require_setup_participant`），GM 不受限并保留「直接触发」。阵容选单玩家侧只显示五核心换人格。
6. **状态展示**：双方状态在主聊天框顶部（频道标题下方）紧凑展示，左我方右敌方，点击弹出详情；适配手机。
7. **个人 EGO**：在阵容选单角色卡内独立成 E.G.O 模块展示。

8.（2026-07-27 补充）**行动权双向分工**：我方阵营内玩家只操作核心、GM 只操作助战（NPC）——`/api/battle/actors?side=f` 按角色分别只返回核心/助战，`/api/battle/action` 越界即 403（玩家动助战、GM 动核心都被拒）；敌方仍全归 GM。回合内顺序为 助战（GM）→ 玩家核心 → 敌方；助战未行动完时玩家操作条是与敌方阶段一致的「助战行动中……」纯等待态。**GM 战斗中实时增援**：操作条「增援」按钮（我方/敌方行动阶段可用）弹实时面板——敌方按模板即时生成并在当前阶段入场（`/api/setup/foes/add` 不带 stage 即当前阶段），助战勾选既有角色立即加入战场（`/api/setup/allies/add`，战斗 ACTIVE 时直接进 participants）。

另：诸如"情感升级派发候选、由管理人接纳"之类的**流程性描述不写进系统 UI 文案**，只进说明书。

## 8. 功能对等表（Telegram 命令 → Web UI）

/roster→阵容页；/personas /skills→角色卡展开；/battle→右侧状态栏+日志流；/plan /ready→编成页+触发确认弹窗；/new /battles /use /discard→战斗列表页;/team→核心编成向导；/ally /foe /gear→编成页分区；/create /identity→阵容页操作；/attack /enemy→行动向导（选人→选技能→选目标→确认）；/pass /settle /next /stop→阶段控制条按钮（/next 弹阵容勾选）；/pages→书页面板；/manager→管理人面板；/reload→设置区按钮；/whoami /help→登录角色标识+帮助弹窗。

## 9. UI 风格基线

Telegram/Discord 式三栏聊天布局：左侧导航/战斗列表，中间战斗日志流（气泡样式，系统播报与行动播报区分），右侧当前战斗状态（单位卡片：HP/行动/混乱条 + 效果 chips + 下回合待生效），底部按阶段显示的操作条；向导类操作用模态框分步完成，均有"上一步/取消"。暗色主题为默认，中文字体优先，禁外链资源（离线可用）。配色基线（2026-07-26 定）：Discord 式暗灰底（经用户裁定保持灰黑，不做暖色化）+ 废墟图书馆式**古金**交互点缀（`--accent` #c79b3b 系：按钮/导航高亮/GM 徽章/我方气泡）；标题类文字用衬线字 `--font-display` 增加典籍感；情感等级标签用更亮的金（`--gold` 系）；HP 条为红（低血量亮红脉动）；黄色保留给混乱语义（混乱条/混乱标签/混乱单位边框）；友方核心左边框绿、友方助战蓝紫、敌方红；增益 chip 绿、减益 chip 红；情感硬币在单位卡内渲染为发光小方块序列——正面鲜绿、负面玫红。播报流强调片段（`decorateLine`/`fragSpan`，2026-07-26 反馈修订）：伤害数字按数值分四档颜色（<10 暖橙 / 10-19 橙 / 20-34 红橙 / ≥35 亮红发光），仅 ≥35 档逐字抖动；〔暴击〕金色抖动（呼吸法触发，原「临界」表述已废；伤害行括注实际生效的修正成因：消耗资源/强壮/易伤/混乱×2/暴击×1.2/护盾吸收等）；战斗频道更名「故事」；效果名只上色不抖，配色按边狱公司式效果色板（`EFFECT_COLORS`：烧伤红/流血橙/震颤黄/破裂绿/沉沦青/呼吸法蓝/充能紫；强壮红/虚弱橙/护盾浅蓝/守护青蓝/易伤玫红/麻痹淡金/中毒毒紫/硬血深红），状态栏效果 chips 同色；混乱黄抖、退场红抖；历史回放与 `prefers-reduced-motion` 下静止。GM 与玩家共用同一页面，按角色隐藏无权元素（服务端仍兜底鉴权）。

## 10. 测试

`tests/test_web_app.py` 用 `fastapi.testclient.TestClient`（离线）：登录/401/403、玩家权限边界（敌方技能不可见、GM 接口 403）、行动接口走通完整回合、`revision` 过期 409、SSE 握手。测试通过 `create_app(settings, engine=engine, loader=loader)` 注入内存库，复用 `tests/conftest.py` 的 world fixture 模式。
