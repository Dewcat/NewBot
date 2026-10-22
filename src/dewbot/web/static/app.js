/* ==========================================================================
   Dewbot Web 控制台 — 单文件前端（无框架 IIFE）
   结构：常量词典 → 工具 → 全局状态 → API 封装 → Toast → 模态框 →
         SSE → 日志流 → 总览渲染（状态栏/操作条）→ 向导 → 各页面视图 →
         导航与登录 → 初始化
   ========================================================================== */
(() => {
'use strict';

/* ================= 常量与词典 ================= */

const PHASE_LABELS = {
  BATTLE_START: '战斗开始',
  STAGE_SELECTION: '阶段编成',
  TURN_START: '回合开始',
  ENEMY_PLANNING: '敌方准备',
  FRIENDLY_ACTION: '我方行动',
  ENEMY_ACTION: '敌方行动',
  TURN_END: '回合清算',
  STAGE_END: '阶段结束',
  BATTLE_END: '战斗结束',
};

const SETUP_STATUS_LABELS = {
  STANDBY: '等待触发',
  ACTIVE: '战斗中',
  COMPLETE: '已结束',
  CANCELLED: '已撤销',
};

const CLEAR_CONDITION_LABELS = {
  ALL_ENEMIES_DEFEATED: '击败全部敌人',
  TARGET_DEFEATED: '击败指定目标',
};

const TARGET_SCOPE_LABELS = { SELF: '自身', FRIENDLY: '友方', ENEMY: '敌方', ALL: '全场' };
const TARGET_METHOD_LABELS = { SELF: '自身', SELECT_TARGET: '指定单体', ALL_TARGETS: '全体', RANDOM: '随机' };

const EFFECT_NAMES = {
  'status.strength': '强壮',
  'status.weakness': '虚弱',
  'status.guard': '守护',
  'status.shield': '护盾',
  'status.vulnerable': '易伤',
  'status.paralysis': '麻痹',
  'status.burn': '烧伤',
  'status.poison': '中毒',
  'status.bleeding': '流血',
  'status.rupture': '破裂',
  'status.breathing': '呼吸法',
  'status.hardblood': '硬血',
};
/* 效果配色（2026-07-26 反馈，参考边狱公司）：
   烧伤红、流血橙、震颤黄、破裂绿、沉沦青、呼吸法蓝、充能紫；
   强壮红、虚弱橙、护盾蓝（浅）、守护青蓝、易伤玫红、麻痹淡金、中毒毒紫、硬血深红。 */
const EFFECT_COLORS = {
  'status.burn': '#ff5d3c',
  'status.bleeding': '#ff8f3e',
  'status.tremor': '#e5c93c',
  'status.rupture': '#57d06c',
  'status.sinking': '#3fd6d6',
  'status.breathing': '#3f7ef7',
  'status.charge': '#8f7bff',
  'status.strength': '#ff6a55',
  'status.weakness': '#ffab4a',
  'status.shield': '#66b3ff',
  'status.guard': '#7ec8e3',
  'status.vulnerable': '#e85d9e',
  'status.paralysis': '#f0e35a',
  'status.poison': '#a86bdf',
  'status.hardblood': '#d1495f',
};

function tintChip(node, color) {
  if (!color) return node;
  node.style.color = color;
  node.style.borderColor = color + '66';
  node.style.background = color + '17';
  return node;
}

const BUFF_KEYS = new Set([
  'status.strength', 'status.guard', 'status.shield', 'status.breathing', 'status.hardblood',
]);
const DEBUFF_KEYS = new Set([
  'status.weakness', 'status.vulnerable', 'status.paralysis', 'status.burn',
  'status.poison', 'status.bleeding', 'status.rupture',
]);

const ACTION_LINE_RE = /^(.{1,60}?)｜使用(?: E\.G\.O)?「/;

/* ================= 小工具 ================= */

function byId(id) { return document.getElementById(id); }

function el(tag, attrs, ...children) {
  const node = document.createElement(tag);
  if (attrs) {
    for (const key of Object.keys(attrs)) {
      const value = attrs[key];
      if (value === null || value === undefined || value === false) continue;
      if (key === 'class') node.className = value;
      else if (key === 'text') node.textContent = String(value);
      else if (key.startsWith('on') && typeof value === 'function') {
        node.addEventListener(key.slice(2), value);
      } else node.setAttribute(key, String(value));
    }
  }
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    if (child instanceof Node) node.append(child);
    else node.append(document.createTextNode(String(child)));
  }
  return node;
}

function clearNode(node) {
  if (!node) return;
  while (node.firstChild) node.removeChild(node.firstChild);
}

function chip(text, extraClass, title) {
  return el('span', { class: 'chip' + (extraClass ? ' ' + extraClass : ''), title: title || null }, text);
}

function toInt(value, fallback) {
  const num = Number(value);
  return Number.isFinite(num) ? Math.trunc(num) : (fallback || 0);
}

function parseJsonArray(text) {
  try {
    const value = JSON.parse(String(text || '[]'));
    return Array.isArray(value) ? value : [];
  } catch (err) { return []; }
}

/* ================= 全局状态 ================= */

const state = {
  role: null,          // 'gm' | 'player'
  loggedIn: false,
  view: 'battle',
  viewToken: 0,
  overview: null,      // {battle, setup, page_offers, role}
  nameFaction: new Map(),
  pinned: true,
  busy: false,
  sse: null,
  sseErrors: 0,
  chatNodes: new Map(),   // id -> {node, msg}：聊天气泡的原位更新索引
  channelDateKey: null,   // 最近一次渲染的日期分隔线（Telegram 式）
  chatReadTimer: null,
};

/* ================= DOM 引用（全部判空使用） ================= */

const dom = {
  loginView: byId('login-view'),
  loginCard: byId('login-card'),
  loginKey: byId('login-key'),
  loginSubmit: byId('login-submit'),
  appView: byId('app-view'),
  navList: byId('nav-list'),
  connState: byId('conn-state'),
  roleBadge: byId('role-badge'),
  userBarText: byId('user-bar-text'),
  logoutBtn: byId('logout-btn'),
  channelName: byId('channel-name'),
  channelMeta: byId('channel-meta'),
  logView: byId('log-view'),
  logScroll: byId('log-scroll'),
  logList: byId('log-list'),
  jumpLatest: byId('jump-latest'),
  pageView: byId('page-view'),
  pageScroll: byId('page-scroll'),
  actionBar: byId('action-bar'),
  noticeBanner: byId('notice-banner'),
  battleStrip: byId('battle-strip'),
  chatBar: byId('chat-bar'),
  chatInput: byId('chat-input'),
  chatSend: byId('chat-send'),
  chatSearchBtn: byId('chat-search-btn'),
  statusList: byId('status-list'),
  modalRoot: byId('modal-root'),
  toastRoot: byId('toast-root'),
  toggleNav: byId('toggle-nav'),
  toggleStatus: byId('toggle-status'),
  sidebarBackdrop: byId('sidebar-backdrop'),
};

/* ================= API 封装 ================= */

class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

async function api(path, options) {
  const opts = options || {};
  const init = { method: opts.method || 'GET' };
  if (opts.body !== undefined) {
    init.headers = { 'Content-Type': 'application/json' };
    init.body = JSON.stringify(opts.body);
  }
  let response;
  try {
    response = await fetch(path, init);
  } catch (err) {
    throw new ApiError('无法连接服务器，请确认 dewbot-web 是否在运行。', 0);
  }
  let data = null;
  try {
    const text = await response.text();
    if (text) data = JSON.parse(text);
  } catch (err) { data = null; }
  if (response.status === 401) {
    if (state.loggedIn) {
      enterLogin();
      toast('登录已失效，请重新输入访问密钥。', 'error');
    }
    throw new ApiError((data && data.error) || '未登录或登录已失效。', 401);
  }
  if (!response.ok) {
    throw new ApiError((data && data.error) || ('请求失败（HTTP ' + response.status + '）'), response.status);
  }
  return data;
}

/* 写操作统一入口：请求期间禁用按钮防双击，失败用 toast 提示。 */
async function withBusy(button, fn) {
  if (state.busy) return;
  state.busy = true;
  const target = button instanceof HTMLElement ? button : null;
  if (target) {
    target.disabled = true;
    target.classList.add('is-busy');
  }
  try {
    await fn();
  } catch (err) {
    if (!(err instanceof ApiError && err.status === 401)) {
      toast((err && err.message) || '操作失败', 'error');
    }
  } finally {
    state.busy = false;
    if (target) {
      target.disabled = false;
      target.classList.remove('is-busy');
    }
  }
}

function writeButton(label, cls, handler) {
  const button = el('button', { class: 'btn ' + (cls || ''), type: 'button' }, label);
  button.addEventListener('click', () => withBusy(button, handler));
  return button;
}

/* ================= Toast ================= */

function toast(message, kind) {
  if (!dom.toastRoot) return;
  // 成功确认（ok）不再弹窗：操作结果已由播报流与界面刷新呈现，只提示失败。
  if (kind === 'ok') return;
  const node = el('div', { class: 'toast ' + (kind || 'info') }, String(message || ''));
  let removed = false;
  const remove = () => {
    if (removed) return;
    removed = true;
    node.classList.add('leaving');
    setTimeout(() => node.remove(), 260);
  };
  node.addEventListener('click', remove);
  dom.toastRoot.append(node);
  setTimeout(remove, kind === 'error' ? 6500 : 4200);
}

/* ================= 模态框 ================= */

function closeModal() {
  if (!dom.modalRoot) return;
  dom.modalRoot.classList.add('hidden');
  clearNode(dom.modalRoot);
}

function openModal(opts) {
  if (!dom.modalRoot) return null;
  closeModal();
  const noteEl = el('span', { class: 'modal-step-note' }, (opts && opts.note) || '');
  const body = el('div', { class: 'modal-body' });
  const footer = el('div', { class: 'modal-footer' });
  const modal = el('div', { class: 'modal' + (opts && opts.wide ? ' wide' : '') },
    el('div', { class: 'modal-header' },
      el('h3', null, (opts && opts.title) || ''),
      noteEl,
      opts && opts.locked
        ? null  // 强制弹窗（如书页选取）：不给关闭按钮，选完才继续
        : el('button', { class: 'icon-btn', type: 'button', title: '关闭', onclick: closeModal }, '✕')),
    body, footer);
  dom.modalRoot.append(modal);
  dom.modalRoot.classList.remove('hidden');
  return {
    body,
    footer,
    close: closeModal,
    setNote(text) { noteEl.textContent = text || ''; },
    setBody(node) { clearNode(body); if (node) body.append(node); },
    setFooter(...buttons) { clearNode(footer); for (const b of buttons.flat()) if (b) footer.append(b); },
  };
}

function confirmModal(opts) {
  const modal = openModal({ title: opts.title });
  if (!modal) return;
  const confirmBtn = el('button', { class: 'btn ' + (opts.danger ? 'danger' : 'primary'), type: 'button' },
    opts.confirmLabel || '确认');
  const bodyWrap = el('div', null, el('div', null, opts.message || ''));
  if (opts.requireCheck) {
    const checkbox = el('input', { type: 'checkbox' });
    confirmBtn.disabled = true;
    checkbox.addEventListener('change', () => { confirmBtn.disabled = !checkbox.checked; });
    bodyWrap.append(el('label', { class: 'check-row', style: 'margin-top:12px' },
      checkbox, el('span', { class: 'check-label' }, opts.requireCheck)));
  }
  if (opts.warn) bodyWrap.append(el('div', { class: 'confirm-warn' }, opts.warn));
  modal.setBody(bodyWrap);
  confirmBtn.addEventListener('click', () => withBusy(confirmBtn, async () => {
    await opts.onConfirm();
    closeModal();
  }));
  modal.setFooter(
    el('button', { class: 'btn ghost', type: 'button', onclick: closeModal }, '取消'),
    confirmBtn);
}

/* ================= SSE 实时流 ================= */

function createLogPlayback(emit, schedule = setTimeout, cancel = clearTimeout) {
  let queue = [], timer = null;
  const drain = () => {
    timer = null;
    const item = queue.shift();
    if (!item) return;
    emit(item.lines);
    // Keep the gap even after the last entry, so another event cannot overtake it.
    timer = schedule(() => { timer = null; if (queue.length) drain(); }, item.delay);
  };
  return {
    enqueue(lines, interval = 0) {
      const pieces = lines.flatMap(raw => String(raw).split('\n')).map(line => line.trim()).filter(Boolean);
      if (!pieces.length) return;
      if (!interval && timer === null && !queue.length) { emit(pieces); return; }
      // A trigger/action and its result details are one presentation unit.
      // Phase banners stay separate from any standalone effects that follow.
      const effects = [];
      let acceptsDetails = false;
      for (const line of pieces) {
        const detail = /^(?:[└├│]|──)/.test(line);
        if (detail && acceptsDetails && effects.length) effects[effects.length-1].push(line);
        else {
          effects.push([line]);
          acceptsDetails = !/^[【▣]/.test(line) && !detail;
        }
      }
      const delay = interval || 1500;
      queue.push(...effects.map(lines => ({ lines, delay })));
      if (timer === null) drain();
    },
    reset() { if (timer !== null) cancel(timer); timer = null; queue = []; },
  };
}

const logPlayback = createLogPlayback(lines => {
  ensureDateDivider(new Date());
  appendLogLines(lines, false);
});

function setConnState(on) {
  if (!dom.connState) return;
  dom.connState.classList.toggle('on', !!on);
  dom.connState.classList.toggle('off', !on);
  dom.connState.textContent = on ? '实时连接' : '重连中…';
}

function closeSSE() {
  logPlayback.reset();
  if (state.sse) {
    try { state.sse.close(); } catch (err) { /* 忽略 */ }
    state.sse = null;
  }
  setConnState(false);
}

function connectSSE() {
  closeSSE();
  if (typeof EventSource === 'undefined') return;
  // replay=0：历史改由 /api/channel/history 合并拉取（战斗播报+聊天按时间穿插）。
  const source = new EventSource('/api/events?replay=0');
  state.sse = source;
  source.addEventListener('open', async () => {
    state.sseErrors = 0;
    setConnState(true);
    // 先拿总览建立"名字→阵营"映射，再回放历史：否则我方播报会认不出阵营靠左。
    try { await refreshOverview(); } catch (err) { /* 401 等由 api() 统一处理 */ }
    loadChannelHistory();
  });
  source.addEventListener('log', (event) => {
    let payload = null;
    try { payload = JSON.parse(event.data); } catch (err) { return; }
    const lines = payload && Array.isArray(payload.lines) ? payload.lines : [];
    if (!lines.length) return;
    logPlayback.enqueue(lines, toInt(payload.interval_ms, 0));
  });
  source.addEventListener('chat', (event) => {
    let payload = null;
    try { payload = JSON.parse(event.data); } catch (err) { return; }
    if (payload && payload.message) appendChatMessage(payload.message);
  });
  source.addEventListener('setup_published', (event) => {
    let payload = null;
    try { payload = JSON.parse(event.data); } catch (err) { return; }
    if (state.role === 'player') {
      toast('管理人发布了战斗编成「' + ((payload && payload.name) || '') + '」，请前往确认。', 'info');
    }
    refreshOverview();
  });
  source.addEventListener('chat_read', (event) => {
    let payload = null;
    try { payload = JSON.parse(event.data); } catch (err) { return; }
    if (payload && payload.role) applyChatRead(payload.role, toInt(payload.up_to_id, 0));
  });
  source.addEventListener('refresh', () => {
    refreshOverview();
  });
  source.addEventListener('error', () => {
    setConnState(false);
    state.sseErrors += 1;
    if (state.sseErrors >= 4) {
      state.sseErrors = 0;
      /* 探测会话：401 时 api() 会切回登录页并停止重连 */
      api('/api/session').catch((err) => {
        if (err instanceof ApiError && err.status === 401) closeSSE();
      });
    }
  });
}

/* ================= 日志流 ================= */

let lastBubble = null; /* {node, replay} — 供 └ 明细行归组 */

function logEmptyNote() {
  return el('div', { class: 'log-empty', id: 'log-empty-note' },
    '暂无战斗播报。触发一场战斗后，这里会实时滚动记录。');
}

function resetLog() {
  logPlayback.reset();
  lastBubble = null;
  state.chatNodes.clear();
  state.channelDateKey = null;
  if (!dom.logList) return;
  clearNode(dom.logList);
}

function classifyLine(line) {
  if (line.startsWith('└') || line.startsWith('├')) return 'detail';
  if (line.startsWith('──')) return 'notice';
  if (line.startsWith('【') || line.startsWith('▣')) return 'banner';
  if (line.startsWith('◇') || line.startsWith('◆')) return 'system';
  const match = ACTION_LINE_RE.exec(line);
  if (match) {
    const faction = state.nameFaction.get(match[1].trim());
    if (faction === 'FRIENDLY') return 'friendly';
    if (faction === 'ENEMY') return 'enemy';
    return 'action';
  }
  return 'system';
}

/* ===== 仿废墟图书馆：局部字体抖动（伤害数字/临界/效果名/混乱・退场播报） ===== */

const EFFECT_NAME_KIND = (() => {
  const map = new Map();
  for (const key of Object.keys(EFFECT_NAMES)) {
    map.set(EFFECT_NAMES[key],
      BUFF_KEYS.has(key) ? 'fx-buff' : DEBUFF_KEYS.has(key) ? 'fx-debuff' : 'fx-neutral');
  }
  return map;
})();

const EFFECT_NAME_COLOR = (() => {
  const map = new Map();
  for (const key of Object.keys(EFFECT_NAMES)) {
    if (EFFECT_COLORS[key]) map.set(EFFECT_NAMES[key], EFFECT_COLORS[key]);
  }
  return map;
})();

function fragSpan(text, cls, shake, color) {
  /* shake=false：只上色不抖；shake=true：逐字随机相位抖动（仿 Ruina）。 */
  const wrap = el('span', { class: 'frag ' + cls });
  if (color) wrap.style.color = color;
  if (!shake) {
    wrap.append(String(text));
    return wrap;
  }
  for (const ch of Array.from(String(text))) {
    const node = el('span', { class: 'jchar' }, ch);
    node.style.animationDelay = '-' + Math.floor(Math.random() * 380) + 'ms';
    node.style.animationDuration = (240 + Math.floor(Math.random() * 140)) + 'ms';
    wrap.append(node);
  }
  return wrap;
}

/* 伤害分档：数值越大颜色越红，只有最高档才抖动。 */
function damageTier(amount) {
  if (amount >= 35) return { cls: 'dmg-4', shake: true };
  if (amount >= 20) return { cls: 'dmg-3', shake: false };
  if (amount >= 10) return { cls: 'dmg-2', shake: false };
  return { cls: 'dmg-1', shake: false };
}

/* 把一行播报里需要强调的片段换成着色/抖动 span；无匹配时原样返回字符串。 */
function decorateLine(line) {
  const ranges = [];
  const collect = (re, cls, group, shake) => {
    let m;
    while ((m = re.exec(line)) !== null) {
      const text = group ? m[group] : m[0];
      const start = group ? m.index + m[0].indexOf(text) : m.index;
      ranges.push({ start, end: start + text.length, cls, shake: !!shake });
    }
  };
  const collectDamage = (re) => {
    let m;
    while ((m = re.exec(line)) !== null) {
      const text = m[1];
      const start = m.index + m[0].indexOf(text);
      const tier = damageTier(toInt(text, 0));
      ranges.push({ start, end: start + text.length, cls: tier.cls, shake: tier.shake });
    }
  };
  collectDamage(/(\d+) 点伤害/g);
  collectDamage(/固定伤害：(\d+)/g);
  collect(/〔暴击〕/g, 'jit-crit', 0, true);
  if (/获得|固定伤害|减少1层|」现为 /.test(line)) {
    let m;
    const re = /「([^」]+)」/g;
    while ((m = re.exec(line)) !== null) {
      const firstWord = m[1].split(/[ 　]/)[0];
      const kind = EFFECT_NAME_KIND.get(firstWord) || 'fx-neutral';
      // 效果名只上色不抖；颜色按边狱公司式效果配色（EFFECT_COLORS）。
      ranges.push({
        start: m.index, end: m.index + m[0].length,
        cls: kind, shake: false, color: EFFECT_NAME_COLOR.get(firstWord) || null,
      });
    }
  }
  collect(/混乱条被击破，陷入混乱！?/g, 'jit-stagger', 0, true);
  collect(/倒下了，退出战斗。?/g, 'jit-dead', 0, true);
  if (!ranges.length) return line;
  ranges.sort((a, b) => a.start - b.start);
  const out = [];
  let pos = 0;
  for (const range of ranges) {
    if (range.start < pos) continue; // 重叠时保留先匹配的片段
    if (range.start > pos) out.push(line.slice(pos, range.start));
    out.push(fragSpan(line.slice(range.start, range.end), range.cls, range.shake, range.color));
    pos = range.end;
  }
  if (pos < line.length) out.push(line.slice(pos));
  return out;
}

/* ================= 跑团聊天（跨战斗连续主频道） ================= */

function chatDate(value) {
  if (!value) return new Date();
  const iso = String(value).includes('T') ? String(value) : String(value).replace(' ', 'T') + 'Z';
  const parsed = new Date(iso);
  return Number.isNaN(parsed.getTime()) ? new Date() : parsed;
}

function timeLabel(date) {
  return String(date.getHours()).padStart(2, '0') + ':' + String(date.getMinutes()).padStart(2, '0');
}

function dateDividerLabel(date) {
  const now = new Date();
  const startOf = (d) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  const diffDays = Math.round((startOf(now) - startOf(date)) / 86400000);
  if (diffDays === 0) return '今天';
  if (diffDays === 1) return '昨天';
  if (date.getFullYear() === now.getFullYear()) {
    return (date.getMonth() + 1) + '月' + date.getDate() + '日';
  }
  return date.getFullYear() + '年' + (date.getMonth() + 1) + '月' + date.getDate() + '日';
}

function ensureDateDivider(date) {
  if (!dom.logList) return;
  const key = date.getFullYear() + '-' + date.getMonth() + '-' + date.getDate();
  if (state.channelDateKey === key) return;
  state.channelDateKey = key;
  dom.logList.append(el('div', { class: 'date-divider' },
    el('span', null, dateDividerLabel(date))));
}

function otherRoleHasRead(msg) {
  return state.role === 'gm' ? !!toInt(msg.read_by_player, 0) : !!toInt(msg.read_by_gm, 0);
}

function buildChatBubble(msg) {
  const when = chatDate(msg.created_at);
  const time = el('span', { class: 'chat-time' }, timeLabel(when));
  const mine = msg.author_role === state.role;

  if (toInt(msg.revoked, 0)) {
    const who = msg.author_role === 'gm' ? '管理人' : (msg.speaker || '玩家');
    return el('div', { class: 'bubble chat-revoked' }, who + ' 撤回了一条消息', time);
  }

  const editedMark = msg.edited_at
    ? el('span', { class: 'chat-edited' }, '（已编辑）') : null;
  const readMark = mine
    ? el('span', { class: 'chat-read' + (otherRoleHasRead(msg) ? ' seen' : '') },
        otherRoleHasRead(msg) ? '✓✓' : '✓')
    : null;
  const menuBtn = mine ? el('button', {
    class: 'chat-menu-btn', type: 'button', title: '编辑或撤回',
    onclick: () => openChatMenu(msg),
  }, '···') : null;

  if (msg.kind === 'narration') {
    return el('div', { class: 'bubble chat-narration' },
      el('div', { class: 'chat-text' }, msg.content),
      el('div', { class: 'chat-meta' }, time, editedMark, readMark, menuBtn));
  }
  const side = mine ? 'chat-mine' : 'chat-theirs';
  return el('div', { class: 'bubble chat-speech ' + side },
    el('div', { class: 'chat-head' }, msg.speaker || (msg.author_role === 'gm' ? 'NPC' : '玩家')),
    el('div', { class: 'chat-text' }, msg.content),
    el('div', { class: 'chat-meta' }, time, editedMark, readMark, menuBtn));
}

function appendChatMessage(msg) {
  if (!dom.logList || !msg || !msg.id) return;
  const id = toInt(msg.id, 0);
  const existing = state.chatNodes.get(id);
  if (existing) {
    const fresh = buildChatBubble(msg);
    existing.node.replaceWith(fresh);
    state.chatNodes.set(id, { node: fresh, msg });
    return;
  }
  const note = byId('log-empty-note');
  if (note) note.remove();
  ensureDateDivider(chatDate(msg.created_at));
  const node = buildChatBubble(msg);
  dom.logList.append(node);
  state.chatNodes.set(id, { node, msg });
  lastBubble = null; // 聊天气泡不吸附战斗明细行
  if (msg.author_role !== state.role) scheduleChatRead();
  scrollLogToBottom(false);
}

function applyChatRead(role, upToId) {
  if (role === state.role) return; // 对方读了我的消息才需要更新 ✓✓
  for (const [id, entry] of state.chatNodes) {
    if (id > upToId || entry.msg.author_role !== state.role) continue;
    if (role === 'gm') entry.msg.read_by_gm = 1; else entry.msg.read_by_player = 1;
    const mark = entry.node.querySelector('.chat-read');
    if (mark) { mark.textContent = '✓✓'; mark.classList.add('seen'); }
  }
}

function scheduleChatRead() {
  if (state.chatReadTimer) clearTimeout(state.chatReadTimer);
  state.chatReadTimer = setTimeout(async () => {
    state.chatReadTimer = null;
    if (document.visibilityState !== 'visible' || state.view !== 'battle') return;
    let maxId = 0;
    for (const [id, entry] of state.chatNodes) {
      if (entry.msg.author_role !== state.role && id > maxId) maxId = id;
    }
    if (!maxId) return;
    try {
      await api('/api/chat/read', { method: 'POST', body: { up_to_id: maxId } });
    } catch (err) { /* 静默：下次滚动/收信重试 */ }
  }, 700);
}

function openChatMenu(msg) {
  const modal = openModal({ title: '消息操作' });
  if (!modal) return;
  const editBtn = el('button', { class: 'btn ghost block', type: 'button' }, '编辑');
  editBtn.addEventListener('click', () => openChatEdit(msg));
  const revokeBtn = el('button', { class: 'btn danger block', type: 'button', style: 'margin-top:8px' }, '撤回');
  revokeBtn.addEventListener('click', () => withBusy(revokeBtn, async () => {
    await api('/api/chat/' + msg.id + '/revoke', { method: 'POST', body: {} });
    closeModal();
  }));
  modal.setBody(el('div', null,
    el('div', { class: 'wizard-subtitle' }, '「' + String(msg.content || '').slice(0, 60) + '」'),
    editBtn, revokeBtn));
  modal.setFooter(el('button', { class: 'btn ghost', type: 'button', onclick: closeModal }, '取消'));
}

function openChatEdit(msg) {
  const modal = openModal({ title: '编辑消息' });
  if (!modal) return;
  const raw = msg.kind === 'speech' && msg.author_role === 'gm' && msg.speaker
    ? msg.speaker + '：“' + msg.content + '”'
    : msg.content;
  const input = el('textarea', { class: 'chat-edit-area', rows: '3' });
  input.value = raw;
  const saveBtn = el('button', { class: 'btn primary', type: 'button' }, '保存');
  saveBtn.addEventListener('click', () => withBusy(saveBtn, async () => {
    await api('/api/chat/' + msg.id + '/edit', { method: 'POST', body: { content: input.value } });
    closeModal();
  }));
  modal.setBody(el('div', null, input));
  modal.setFooter(el('button', { class: 'btn ghost', type: 'button', onclick: closeModal }, '取消'), saveBtn);
}

function openChatSearch() {
  const modal = openModal({ title: '搜索聊天记录' });
  if (!modal) return;
  const input = el('input', { type: 'text', placeholder: '输入关键词或角色名…' });
  const results = el('div', { class: 'chat-search-results' });
  let timer = null;
  const run = async () => {
    const query = input.value.trim();
    clearNode(results);
    if (!query) return;
    let rows;
    try { rows = await api('/api/chat/search?q=' + encodeURIComponent(query)); }
    catch (err) { results.append(el('div', { class: 'empty-note' }, err.message || '搜索失败')); return; }
    const items = Array.isArray(rows) ? rows : [];
    if (!items.length) { results.append(el('div', { class: 'empty-note' }, '没有匹配的消息。')); return; }
    for (const item of items) {
      const when = chatDate(item.created_at);
      results.append(el('div', { class: 'list-row' },
        el('div', { class: 'row-main' },
          el('div', { class: 'row-title' },
            item.kind === 'narration' ? '旁白' : (item.speaker || '玩家'),
            el('span', { class: 'check-sub', style: 'margin-left:8px' },
              dateDividerLabel(when) + ' ' + timeLabel(when))),
          el('div', { class: 'row-sub' }, item.content))));
    }
  };
  input.addEventListener('input', () => {
    if (timer) clearTimeout(timer);
    timer = setTimeout(run, 300);
  });
  modal.setBody(el('div', null, input, results));
  modal.setFooter(el('button', { class: 'btn ghost', type: 'button', onclick: closeModal }, '关闭'));
  setTimeout(() => input.focus(), 60);
}

async function sendChat() {
  const text = dom.chatInput ? dom.chatInput.value.trim() : '';
  if (!text || state.busy) return;
  try {
    const message = await api('/api/chat', { method: 'POST', body: { content: text } });
    if (dom.chatInput) dom.chatInput.value = '';
    appendChatMessage(message); // SSE 广播会按 id 去重
    scrollLogToBottom(true);
  } catch (err) {
    toast((err && err.message) || '发送失败', 'error');
  }
}

async function loadChannelHistory() {
  let payload;
  try { payload = await api('/api/channel/history'); }
  catch (err) { return; }
  const items = payload && Array.isArray(payload.items) ? payload.items : [];
  resetLog();
  if (!items.length) {
    if (dom.logList) dom.logList.append(logEmptyNote());
    return;
  }
  for (const item of items) {
    if (item.type === 'chat') {
      appendChatMessage(item.message);
    } else {
      ensureDateDivider(chatDate(item.created_at));
      // 已结束/中止的战斗在刷新后不再出现在 overview 中；历史项自带当场
      // 参战者阵营，确保行动气泡仍按玩家视角稳定分列。
      learnFactions(item.factions);
      // 活跃战斗的当前回合保持"活跃"样式，只有更早的播报置灰。
      for (const piece of String(item.message || '').split('\n')) {
        const line = piece.replace(/\s+$/, '');
        if (line.trim()) appendLine(line.trim(), !item.current);
      }
    }
  }
  scrollLogToBottom(true);
  scheduleChatRead();
}

function appendLine(line, replay) {
  if (!dom.logList) return;
  const kind = classifyLine(line);
  const replayClass = replay ? ' replay' : '';

  if (kind === 'detail') {
    if (lastBubble && lastBubble.replay === replay) {
      lastBubble.node.append(el('div', { class: 'sub' }, decorateLine(line)));
      return;
    }
    dom.logList.append(el('div', { class: 'bubble sys' + replayClass }, decorateLine(line)));
    return;
  }
  if (kind === 'banner') {
    lastBubble = null;
    dom.logList.append(el('div', { class: 'log-banner' + replayClass },
      el('span', { class: 'banner-text' }, line)));
    return;
  }
  if (kind === 'notice') {
    lastBubble = null;
    dom.logList.append(el('div', { class: 'bubble notice' + replayClass }, decorateLine(line)));
    return;
  }
  const cls = kind === 'friendly' ? 'bubble friendly'
    : kind === 'enemy' ? 'bubble enemy'
    : kind === 'action' ? 'bubble action'
    : 'bubble sys';
  const node = el('div', { class: cls + replayClass }, el('div', { class: 'head' }, decorateLine(line)));
  dom.logList.append(node);
  lastBubble = { node, replay };
}

function appendLogLines(lines, replay) {
  if (!dom.logList || !lines || !lines.length) return;
  const note = byId('log-empty-note');
  if (note) note.remove();
  if (replay) {
    dom.logList.append(el('div', { class: 'replay-divider' }, '以下为历史回放'));
  }
  for (const raw of lines) {
    for (const piece of String(raw).split('\n')) {
      const line = piece.replace(/\s+$/, '');
      if (line.trim()) appendLine(line.trim(), replay);
    }
  }
  scrollLogToBottom(false);
}

function scrollLogToBottom(force) {
  if (!dom.logScroll) return;
  if (force || state.pinned) {
    dom.logScroll.scrollTop = dom.logScroll.scrollHeight;
    state.pinned = true;
    if (dom.jumpLatest) dom.jumpLatest.classList.add('hidden');
  } else if (dom.jumpLatest) {
    dom.jumpLatest.classList.remove('hidden');
  }
}

/* ================= 总览：名称→阵营映射 ================= */

function learnFactions(rows) {
  if (!Array.isArray(rows)) return;
  for (const row of rows) {
    if (row && row.name && row.faction) {
      state.nameFaction.set(String(row.name), String(row.faction));
    }
  }
}

async function refreshOverview() {
  let data;
  try {
    data = await api('/api/overview');
  } catch (err) {
    if (!(err instanceof ApiError && (err.status === 401 || err.status === 0))) {
      toast(err.message, 'error');
    }
    return;
  }
  state.overview = data || {};
  if (data && (data.role === 'gm' || data.role === 'player')) setRole(data.role);
  const battle = data && data.battle;
  if (battle) learnFactions(battle.participants);
  renderChannelHeader();
  renderStatusColumn();
  renderBattleStrip();
  renderNoticeBanner();
  renderActionBar();
  renderNavBadges();
  maybeOpenPageOffers();
  if (state.view === 'pages') renderCurrentView();
}

/* ================= 频道头部 ================= */

function renderChannelHeader() {
  if (!dom.channelName || !dom.channelMeta) return;
  const viewDef = VIEWS[state.view];
  dom.channelName.textContent = viewDef ? viewDef.label : '故事';
  // 标题旁不再堆战斗信息（顶部状态条与操作条已足够）；只放聊天搜索入口。
  clearNode(dom.channelMeta);
  if (dom.chatSearchBtn) {
    dom.chatSearchBtn.classList.toggle('hidden', state.view !== 'battle');
  }
}

/* ================= 右侧战斗状态栏 ================= */

function unitHasTag(unit, tag) {
  try {
    const tags = Array.isArray(unit.tags) ? unit.tags : JSON.parse(unit.tags_json || '[]');
    return Array.isArray(tags) && tags.some((t) => String(t).toLowerCase() === tag);
  } catch (err) {
    return false;
  }
}

function effectDetailsChip(text, extraClass, name, description, context = '') {
  const details = String(description || '').trim() || '暂无效果说明。';
  const content = context ? context + '\n\n' + details : details;
  return el('button', {
    type:'button', class:'chip effect-details-chip' + (extraClass ? ' ' + extraClass : ''),
    title:content, 'aria-label':name + '：' + content,
    onclick:event => {
      event.stopPropagation();
      const modal = openModal({title:name});
      if (!modal) return;
      modal.setBody(el('div', {class:'effect-description'}, content));
      modal.setFooter(el('button', {class:'btn ghost', type:'button', onclick:closeModal}, '关闭'));
    }
  }, text);
}

function effectChip(effect) {
  const key = String(effect.effect_key || '');
  const name = effect.effect_name || EFFECT_NAMES[key] || key || '效果';
  let text = String(name);
  const intensity = toInt(effect.intensity, 0);
  const stacks = toInt(effect.stacks, 0);
  if (intensity) text += ' ' + intensity;
  if (stacks) text += ' ×' + stacks;
  if (effect.remaining_turns !== null && effect.remaining_turns !== undefined) {
    text += '｜' + effect.remaining_turns + '回合';
  }
  const cls = BUFF_KEYS.has(key) ? 'buff' : DEBUFF_KEYS.has(key) ? 'debuff' : '';
  return tintChip(effectDetailsChip(text, cls, name, effect.effect_description), EFFECT_COLORS[key]);
}

function pendingChip(effect) {
  const key = String(effect.effect_key || '');
  const name = effect.effect_name || EFFECT_NAMES[key] || key || '效果';
  let text = String(name);
  const intensity = toInt(effect.intensity, 0);
  const stacks = toInt(effect.stacks, 0);
  if (intensity) text += ' ' + intensity;
  if (stacks) text += ' ×' + stacks;
  return tintChip(
    effectDetailsChip(text, '', name, effect.effect_description, '第 ' + effect.activate_at + ' 回合生效'),
    EFFECT_COLORS[key]);
}

function miniBar(kind, label, current, max, extraClass) {
  const safeMax = Math.max(1, toInt(max, 1));
  const value = Math.max(0, Math.min(safeMax, toInt(current, 0)));
  const percent = Math.round((value / safeMax) * 100);
  return el('div', { class: 'bar ' + kind + (extraClass ? ' ' + extraClass : '') },
    el('div', { class: 'fill', style: 'width:' + percent + '%' }),
    el('div', { class: 'bar-label' },
      el('span', null, label),
      el('span', null, value + '/' + safeMax)));
}

function unitCard(unit) {
  const hp = toInt(unit.current_hp, 0);
  const maxHp = Math.max(1, toInt(unit.max_hp, 1));
  const dead = hp <= 0;
  const staggered = !!toInt(unit.is_staggered, 0) && !dead;
  const isEnemy = unit.faction === 'ENEMY';
  const card = el('div', {
    class: 'unit ' + (isEnemy ? 'enemy-unit' : 'friendly-unit')
      + (!isEnemy && !toInt(unit.is_core, 0) ? ' assist-unit' : '')
      + (staggered ? ' staggered' : '') + (dead ? ' dead' : ''),
  });

  const head = el('div', { class: 'unit-head' },
    el('span', { class: 'unit-name' }, unit.name || ('#' + unit.id)));
  // 2026-07-26 裁定：核心不挂标签；友方非核心标「助战」，带 boss 标签的敌人标「BOSS」。
  if (!isEnemy && !toInt(unit.is_core, 0)) head.append(el('span', { class: 'unit-tag assist' }, '助战'));
  if (isEnemy && unitHasTag(unit, 'boss')) head.append(el('span', { class: 'unit-tag boss' }, 'BOSS'));
  const emotion = toInt(unit.emotion_level, 0);
  if (emotion > 0) {
    head.append(el('span', {
      class: 'unit-tag emotion',
      title: '情感硬币 +' + toInt(unit.positive_emotion_coins, 0) + ' / -' + toInt(unit.negative_emotion_coins, 0),
    }, '情感 Lv' + emotion));
  }
  if (toInt(unit.pending_emotion_upgrade, 0)) {
    head.append(el('span', { class: 'unit-tag emotion' }, '待升级'));
  }
  if (dead) head.append(el('span', { class: 'unit-tag dead-tag' }, '阵亡'));
  else if (staggered) {
    head.append(el('span', { class: 'unit-tag stagger-tag' },
      '混乱' + (toInt(unit.stagger_turns, 0) > 0 ? '｜' + unit.stagger_turns + '回合' : '')));
  }
  card.append(head);
  if (toInt(unit.is_core, 0) && unit.persona_name) {
    card.classList.add('has-persona');
    card.append(el('div', { class: 'unit-persona-row' },
      el('span', {
        class: 'unit-tag persona',
        title: '当前人格：' + unit.persona_name,
      }, '人格 · ' + unit.persona_name)));
  }

  card.append(miniBar('hp', 'HP', hp, maxHp, hp / maxHp <= 0.3 ? 'low' : ''));
  // 混乱中显示空条（黄色轨道标识），解除混乱后回满。
  card.append(miniBar('stagger', '混乱',
    staggered ? 0 : unit.current_stagger, unit.max_stagger, staggered ? 'broken' : ''));

  const maxActions = Math.max(1, toInt(unit.max_actions, 1));
  const currentActions = Math.max(0, toInt(unit.current_actions, 0));
  const row = el('div', { class: 'unit-row' }, el('span', { class: 'row-label' }, '行动'));
  const pipTotal = Math.max(maxActions, currentActions);
  if (pipTotal <= 8) {
    for (let i = 0; i < pipTotal; i += 1) {
      row.append(el('span', { class: 'pip' + (i < currentActions ? ' on' : '') }));
    }
  } else {
    row.append(el('span', { class: 'check-sub' }, currentActions + ' / ' + maxActions));
  }
  card.append(row);
  const posCoins = toInt(unit.positive_emotion_coins, 0);
  const negCoins = toInt(unit.negative_emotion_coins, 0);
  if (posCoins || negCoins) {
    const track = el('span', {
      class: 'coin-track',
      title: '正面 ' + posCoins + '｜负面 ' + negCoins + '；攒满阈值提升情感等级',
    });
    if (posCoins + negCoins <= 24) {
      for (let i = 0; i < posCoins; i += 1) track.append(el('span', { class: 'coin pos' }));
      for (let i = 0; i < negCoins; i += 1) track.append(el('span', { class: 'coin neg' }));
    } else {
      track.append(el('span', { class: 'coin-note' }, '正 ' + posCoins + '｜负 ' + negCoins));
    }
    card.append(el('div', { class: 'unit-row' },
      el('span', { class: 'row-label' }, '情感币'), track));
  }

  const effects = Array.isArray(unit.effects) ? unit.effects : [];
  if (effects.length) {
    card.append(el('div', { class: 'chips' }, effects.map(effectChip)));
  }
  const pending = Array.isArray(unit.pending_effects) ? unit.pending_effects : [];
  if (pending.length) {
    card.append(el('div', { class: 'pending-group' },
      el('span', { class: 'pending-label' }, '下回合'),
      el('div', { class: 'chips' }, pending.map(pendingChip))));
  }
  // 该角色自己选取的书页；携带被动是全队级的，展示在「我方」区块下（不进个人卡）。
  const ownPages = (Array.isArray(unit.pages) ? unit.pages : [])
    .filter((page) => page.page_type !== 'CARRY');
  if (ownPages.length) {
    card.append(el('div', { class: 'pending-group' },
      el('span', { class: 'pending-label' }, '书页'),
      el('div', { class: 'chips' }, ownPages.map((page) => {
        const isAwakening = page.page_type === 'AWAKENING';
        return effectDetailsChip(pageLevelLabel(page.level) + ' ' + (page.name || ''),
          isAwakening ? 'type-awaken' : 'type-break',
          page.name || '书页', page.description);
      }))));
  }
  return card;
}

function teamCarryBox(friendlyUnits) {
  /* 携带被动＝全队增益：作为「我方」区块下的独立条目展示。 */
  const carry = [];
  const seen = new Set();
  for (const unit of friendlyUnits) {
    for (const page of (Array.isArray(unit.pages) ? unit.pages : [])) {
      if (page.page_type === 'CARRY' && !seen.has(page.name)) {
        seen.add(page.name);
        carry.push(page);
      }
    }
  }
  if (!carry.length) return null;
  return el('div', { class: 'carry-box' },
    el('span', { class: 'pending-label' }, '携带被动'),
    el('div', { class: 'chips' },
      carry.map((page) => effectDetailsChip(page.name || '', 'buff', page.name || '携带被动', page.description))));
}

function renderStatusColumn() {
  if (!dom.statusList) return;
  clearNode(dom.statusList);
  const overview = state.overview || {};
  const battle = overview.battle;
  if (!battle || !Array.isArray(battle.participants)) {
    const note = el('div', { class: 'status-empty' }, '当前没有进行中的战斗。');
    if (overview.setup && overview.setup.status === 'STANDBY') {
      note.append(el('div', { style: 'margin-top:8px' },
        '「' + (overview.setup.name || '') + '」正等待触发。'));
    }
    dom.statusList.append(note);
    return;
  }
  const intents = battle.phase === 'ENEMY_PLANNING' && state.role !== 'gm' ? [] : battle.enemy_intents || [];
  if (intents.length) {
    dom.statusList.append(el('div', { class: 'faction-title enemy' }, '敌方行动'));
    for (const intent of intents) {
      dom.statusList.append(el('button', { type:'button', class:'unit enemy-intent-detail', title: intent.skill_description || '点击查看技能效果', onclick:()=>openEnemyIntentDetails(intent) },
        enemyIntentLabel(intent)
        + ((intent.additional_target_names || []).length ? '；附加目标：' + intent.additional_target_names.join('、') : '')
        + (intent.disabled ? '〔已混乱或倒下，将取消〕' : '')
        + (intent.status !== 'PENDING' ? '〔已处理〕' : ''),
        el('span',{class:'intent-detail-hint'},'查看技能详情')));
    }
  }
  const active = battle.participants.filter((p) => p && toInt(p.active_in_stage, 0) === 1);
  const friendly = active.filter((p) => p.faction === 'FRIENDLY');
  const enemy = active.filter((p) => p.faction === 'ENEMY');
  if (friendly.length) {
    dom.statusList.append(el('div', { class: 'faction-title friendly' },
      '我方', el('span', { class: 'count' }, '· ' + friendly.length)));
    const carryBox = teamCarryBox(friendly);
    if (carryBox) dom.statusList.append(carryBox);
    for (const unit of friendly) dom.statusList.append(unitCard(unit));
  }
  if (enemy.length) {
    dom.statusList.append(el('div', { class: 'faction-title enemy' },
      '敌方', el('span', { class: 'count' }, '· ' + enemy.length)));
    for (const unit of enemy) dom.statusList.append(unitCard(unit));
  }
  if (!friendly.length && !enemy.length) {
    dom.statusList.append(el('div', { class: 'status-empty' }, '当前阶段没有在场单位。'));
  }
}

/* ================= 顶部紧凑状态条（2026-07-26 裁定：移动端主入口） ================= */

function stripUnit(unit) {
  const hp = toInt(unit.current_hp, 0);
  const maxHp = Math.max(1, toInt(unit.max_hp, 1));
  const sg = toInt(unit.current_stagger, 0);
  const maxSg = Math.max(1, toInt(unit.max_stagger, 1));
  const dead = hp <= 0;
  const staggered = !!toInt(unit.is_staggered, 0) && !dead;
  const btn = el('button', {
    class: 'strip-unit' + (dead ? ' dead' : staggered ? ' staggered' : ''),
    type: 'button',
    title: (unit.name || '') + '｜HP ' + hp + '/' + maxHp + '｜点按查看详情',
  },
    el('span', { class: 'strip-name' }, unit.name || ('#' + unit.id)),
    el('span', { class: 'strip-bar hp' },
      el('span', { class: 'fill', style: 'width:' + Math.round((Math.max(0, hp) / maxHp) * 100) + '%' })),
    el('span', { class: 'strip-bar sg' },
      el('span', {
        class: 'fill',
        style: 'width:' + (staggered ? 0 : Math.round((Math.max(0, sg) / maxSg) * 100)) + '%',
      })));
  btn.addEventListener('click', () => {
    const modal = openModal({ title: unit.name || '单位状态' });
    if (!modal) return;
    modal.setBody(unitCard(unit));
    modal.setFooter(el('button', { class: 'btn ghost', type: 'button', onclick: closeModal }, '关闭'));
  });
  return btn;
}

function renderNoticeBanner() {
  if (!dom.noticeBanner) return;
  clearNode(dom.noticeBanner);
  const overview = state.overview || {};
  const setup = overview.setup;
  const show = state.role === 'player' && !overview.battle && setup
    && setup.status === 'STANDBY' && toInt(setup.published, 0) === 1
    && state.view !== 'setup';
  dom.noticeBanner.classList.toggle('hidden', !show);
  if (!show) return;
  dom.noticeBanner.append(
    el('span', { class: 'banner-msg' },
      '管理人发布了战斗编成「' + (setup.name || ('#' + setup.id)) + '」，等待你确认开战。'),
    el('button', {
      class: 'btn primary small', type: 'button', onclick: () => showView('setup'),
    }, '前往确认'));
}

function renderTargetMap(battle, enemies, friendlies) {
  const svgNS = 'http://www.w3.org/2000/svg';
  const svg = (tag, attrs = {}, text = '') => {
    const node = document.createElementNS(svgNS, tag);
    for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
    if (text) node.textContent = text;
    return node;
  };
  const height = 380;
  const canvas = svg('svg', { viewBox: '0 0 900 ' + height, class: 'target-map', role: 'img', 'aria-label': '战场攻击方向：红色敌方攻击，蓝色我方已行动，黄色防御响应' });
  const defs = svg('defs');
  for (const [key, color] of Object.entries({ red: '#ff646b', blue: '#52c9ff', yellow: '#f2cd52' })) {
    const marker = svg('marker', { id: 'attack-tip-' + key, viewBox: '0 0 10 10', refX: 9, refY: 5, markerWidth: 7, markerHeight: 7, orient: 'auto-start-reverse' });
    marker.append(svg('path', { d: 'M 0 0 L 10 5 L 0 10 z', fill: color })); defs.append(marker);
  }
  const sparkTrail = svg('linearGradient', {id:'spark-trail', x1:'0%', y1:'0%', x2:'100%', y2:'0%'});
  for (const [offset, color, opacity] of [['0%','#ee7733',0], ['45%','#ffc854',.55], ['85%','#fff1ad',1], ['100%','#fffcec',1]]) {
    sparkTrail.append(svg('stop', {offset, 'stop-color':color, 'stop-opacity':opacity}));
  }
  defs.append(sparkTrail);
  canvas.append(defs);
  const unitLayer = svg('g', {class:'map-unit-layer'});
  const edgeLayer = svg('g', {class:'map-edge-layer'});
  const hoverLayer = svg('g', {class:'map-hover-layer'});
  canvas.append(unitLayer, edgeLayer, hoverLayer);
  const unitNodes = new Map();
  let lifted = null;
  const liftUnit = node => {
    if (node === lifted) return;
    if (lifted) unitLayer.append(lifted);
    lifted = node;
    if (node) hoverLayer.append(node);
  };
  const positions = new Map();
  // Both factions occupy two staggered ranks; friendly units face right.
  for (const [units, origin, reverse] of [[friendlies, 22, false], [enemies, 480, true]]) {
    const columns = Math.max(1, Math.ceil(units.length / 2));
    const step = 395 / (columns + .35);
    const width = Math.min(122, step - 10);
    units.forEach((unit, index) => {
      const rank = index % 2, column = Math.floor(index / 2);
      const x = origin + (reverse ? columns - 1 - column : column) * step + rank * step * .32;
      positions.set(unit.id, { unit, x, y: 192 + rank * 98, width });
    });
  }
  const edges = [], areas = [];
  const defended = (target, intent = null) => (battle.defenses || []).some(d => d.actor_id === target && d.active
    && (['GUARD', 'EVADE'].includes(d.kind)
      || (['INTERCEPT', 'MEET'].includes(d.kind) && intent && d.intent_id === intent.id && intent.redirect?.actor_id === target)))
    && positions.has(target) && !positions.get(target).unit.is_staggered && positions.get(target).unit.current_hp > 0;
  const addAttack = (actorId, targets, areaTargets, color, label, intent = null, resolved = false) => {
    const validTargets = [...new Set(targets)].filter(id => positions.has(id) && (resolved || positions.get(id).unit.current_hp > 0));
    const covered = [...new Set(areaTargets || [])].filter(id => validTargets.includes(id));
    let area = null;
    if (covered.length) {
      area = {targets:covered, color, label, intent, index:areas.length};
      areas.push(area);
      edges.push({from:actorId, area, summary:true, color, label, resolved});
    }
    for (const target of validTargets) {
      const responds = !resolved && defended(target,intent);
      edges.push({from:actorId, to:target, color:responds ? 'yellow' : color, label,
        forecast:responds ? (intent.response_forecasts || {})[target] : null, intent, resolved,
        area:area && covered.includes(target) ? area : null});
    }
  };
  for (const intent of battle.enemy_intents || []) {
    if (battle.phase === 'ENEMY_PLANNING') continue;
    if (intent.status !== 'PENDING' || intent.disabled) continue;
    const attacker = positions.get(intent.actor_id)?.unit;
    if (!attacker || attacker.current_hp <= 0 || attacker.is_staggered) continue;
    const targets = intent.attack_target_ids || intent.effective_target_ids || intent.target_ids;
    addAttack(intent.actor_id, targets, intent.area_target_ids, 'red', enemyIntentLabel(intent), intent);
  }
  for (const attack of battle.friendly_attacks || []) {
    addAttack(attack.actor_id, attack.target_ids, attack.area_target_ids, 'blue', attack.skill_name + ' · 已行动', null, true);
  }
  let pinnedArea = null;
  for (const area of areas) {
    const covered = area.targets.map(id=>positions.get(id));
    const left = Math.min(...covered.map(p=>p.x))-5, right = Math.max(...covered.map(p=>p.x+p.width))+5;
    const y = Math.min(...covered.map(p=>p.y))-24-(area.index%4)*27;
    const center = Math.max(95,Math.min(805,(left+right)/2));
    area.anchor = {x:center-1, y:y-24, width:2};
    const bothSides = new Set(covered.map(p=>p.unit.faction)).size>1;
    const title = (bothSides ? '无差别攻击' : '全体攻击') + ' · ' + covered.length + '人';
    area.node = svg('g', {class:'target-area '+area.color, tabindex:0, role:'button', 'aria-label':area.label+'，'+title+'，展开目标连线', 'aria-expanded':'false'});
    area.summary = svg('g',{class:'area-summary'});
    area.details = svg('g',{class:'area-target-links'});
    area.node.append(area.summary, area.details);
    const setExpanded = expanded => { area.node.classList.toggle('expanded',expanded); area.node.setAttribute('aria-expanded',String(expanded)); };
    const toggle = () => {
      const wasPinned = pinnedArea===area;
      if (pinnedArea && pinnedArea!==area) { pinnedArea.node.classList.remove('expanded'); pinnedArea.node.setAttribute('aria-expanded','false'); }
      pinnedArea = wasPinned ? null : area;
      setExpanded(!wasPinned);
    };
    area.node.addEventListener('pointerenter',()=>setExpanded(true));
    area.node.addEventListener('pointerleave',()=>setExpanded(pinnedArea===area));
    area.node.addEventListener('focus',()=>setExpanded(true));
    area.node.addEventListener('blur',event=>{if (!area.node.contains(event.relatedTarget)) setExpanded(pinnedArea===area);});
    area.node.addEventListener('keydown',event=>{
      if (event.target!==area.node) return;
      if (event.key==='Enter' || event.key===' ') {event.preventDefault();toggle();}
      if (event.key==='Escape') {pinnedArea=null;setExpanded(false);}
    });
    area.summary.addEventListener('click',toggle);
    area.toggle = toggle;
    for (const p of covered) area.summary.append(svg('rect',{x:p.x-4,y:p.y-4,width:p.width+8,height:72,rx:10,class:'area-unit-outline'}));
    area.summary.append(svg('path',{d:`M ${left} ${y+8} V ${y} H ${right} V ${y+8}`,class:'area-range'}));
    const badge = svg('g',{class:'area-badge'});
    badge.append(svg('rect',{x:center-86,y:y-29,width:172,height:25,rx:6}));
    badge.append(svg('text',{x:center-(area.intent ? 21 : 0),y:y-12,'text-anchor':'middle'},title));
    if (area.intent) {
      const detail = svg('g',{class:'area-detail-button',tabindex:0,role:'button','aria-label':'查看'+area.intent.skill_name+'详情'});
      detail.append(svg('rect',{x:center+48,y:y-27,width:35,height:21,rx:4}));
      detail.append(svg('text',{x:center+65,y:y-12,'text-anchor':'middle'},'详情'));
      detail.addEventListener('click',event=>{event.stopPropagation();openEnemyIntentDetails(area.intent);});
      detail.addEventListener('keydown',event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();event.stopPropagation();openEnemyIntentDetails(area.intent);}});
      badge.append(detail);
    }
    area.node.append(badge);
    badge.addEventListener('click',toggle);
    edgeLayer.append(area.node);
  }
  for (const [index, edge] of edges.entries()) {
    const from = positions.get(edge.from), to = edge.summary ? edge.area.anchor : positions.get(edge.to);
    if (!from || !to) continue;
    const start = {x: from.x + from.width / 2, y: from.y - 7};
    const end = {x: to.x + to.width / 2, y: to.y - 7};
    const archHeight = 72 + (index % 4) * 16;
    const control = {x: (start.x + end.x) / 2, y: 2 * archHeight - (start.y + end.y) / 2};
    const mix = (a,b,t) => ({x:a.x+(b.x-a.x)*t,y:a.y+(b.y-a.y)*t});
    const at = t => mix(mix(start,control,t),mix(control,end,t),t);
    const path = (a,c,b) => `M ${a.x} ${a.y} Q ${c.x} ${c.y} ${b.x} ${b.y}`;
    const group = svg('g', { class: 'target-edge ' + edge.color + (edge.resolved ? ' resolved' : ''), tabindex: 0, role: 'button', 'aria-label': edge.label + (edge.forecast ? '，' + edge.forecast.label : '') });
    if (edge.summary) {
      group.setAttribute('aria-label',edge.label+'，展开群体目标');
      group.addEventListener('keydown',event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();event.stopPropagation();edge.area.toggle();}});
    } else if (edge.intent) {
      group.addEventListener('click',()=>openEnemyIntentDetails(edge.intent));
      group.addEventListener('keydown',event=>{
        if (event.key==='Enter' || event.key===' ') { event.preventDefault(); openEnemyIntentDetails(edge.intent); }
      });
    }
    const whole = path(start,control,end);
    group.append(svg('path', { d:whole, class:'edge-hit' }));
    let labelPosition = at(.5);
    if (edge.color === 'yellow') {
      const tier = edge.forecast ? edge.forecast.tier : 2;
      // Parameter measured from attacker: a stronger defender reaches farther.
      const fraction = [.80,.66,.50,.34,.20][tier];
      const lengths = [0]; let previous = start;
      for (let sample=1; sample<=80; sample++) {
        const current=at(sample/80);lengths.push(lengths[sample-1]+Math.hypot(current.x-previous.x,current.y-previous.y));previous=current;
      }
      const desired=lengths[80]*fraction;
      let segment=1;while(segment<80 && lengths[segment]<desired) segment++;
      const meeting=(segment-1+(desired-lengths[segment-1])/Math.max(.001,lengths[segment]-lengths[segment-1]))/80;
      const tangent = {
        x:2*((1-meeting)*(control.x-start.x)+meeting*(end.x-control.x)),
        y:2*((1-meeting)*(control.y-start.y)+meeting*(end.y-control.y))
      };
      // Keep the visible arrow tips almost touching, independent of arc length.
      const halfGap = 2.4 / Math.max(1,Math.hypot(tangent.x,tangent.y));
      const left = meeting - halfGap, right = meeting + halfGap;
      group.append(svg('path', { d:path(start,mix(start,control,left),at(left)), class:'edge-line opposing-attacker', 'marker-end':'url(#attack-tip-yellow)' }));
      group.append(svg('path', { d:path(end,mix(end,control,1-right),at(right)), class:'edge-line opposing-defender', 'marker-end':'url(#attack-tip-yellow)' }));
      labelPosition = at(meeting);
      const spark = svg('g', {class:'meeting-spark', transform:`translate(${labelPosition.x},${labelPosition.y})`, 'aria-hidden':'true'});
      // Visual randomness only: sparse streams scatter anew on each flight.
      const normal = Math.atan2(tangent.y,tangent.x)*180/Math.PI+90;
      const scatter = direction => {
        const angle = Math.random()<.75
          ? normal+(Math.random()<.6 ? 0 : 180)+(Math.random()-.5)*105
          : Math.random()*360;
        direction.setAttribute('transform',`rotate(${angle})`);
        direction.style.setProperty('--spark-flight',`${12+Math.random()*22}px`);
        direction.style.setProperty('--ember-flight',`${24+Math.random()*24}px`);
      };
      for (let ray=0; ray<9; ray++) {
        const direction = svg('g', {style:`--spark-duration:${.45+Math.random()*.4}s;--spark-delay:-${Math.random()*2}s`});
        const shard = svg('path', {class:'spark-shard'});
        const emit = () => {
          scatter(direction);
          const length = 7+Math.random()*13, thickness = .35+Math.random()*.5;
          shard.setAttribute('d',`M 0 0 L ${length} ${-thickness} L ${length+2} 0 L ${length} ${thickness} Z`);
        };
        emit(); shard.addEventListener('animationiteration',emit);
        direction.append(shard);
        spark.append(direction);
      }
      for (let fleck=0; fleck<2; fleck++) {
        const direction = svg('g', {style:`--ember-duration:${.8+Math.random()*.5}s;--spark-delay:-${Math.random()*2}s`});
        const ember = svg('g', {class:'spark-ember'});
        ember.append(svg('ellipse', {cx:8, cy:0, rx:3.5, ry:2.6, class:'spark-ember-glow'}));
        ember.append(svg('circle', {cx:8, cy:0, r:1.25, class:'spark-ember-hot'}));
        scatter(direction);
        ember.addEventListener('animationiteration',()=>scatter(direction));
        direction.append(ember);
        spark.append(direction);
      }
      group.append(spark);
    } else {
      group.append(svg('path', { d:whole, class:'edge-line', 'marker-end':'url(#attack-tip-' + edge.color + ')' }));
    }
    const label = edge.label + (edge.forecast ? ' · ' + edge.forecast.label : '');
    group.append(svg('text', { x:Math.max(180,Math.min(720,labelPosition.x)), y:labelPosition.y-13, 'text-anchor':'middle', class:'edge-label' }, label));
    if (edge.area) (edge.summary ? edge.area.summary : edge.area.details).append(group);
    else edgeLayer.append(group);
  }
  for (const {unit, x, y, width} of positions.values()) {
    const hp = Math.max(0,unit.current_hp), maxHp=Math.max(1,unit.max_hp || 1);
    const stagger = unit.is_staggered ? 0 : Math.max(0,unit.current_stagger || 0), maxStagger=Math.max(1,unit.max_stagger || 1);
    const group = svg('g', { class:'map-unit' + (hp<=0?' fallen':'') + (unit.is_staggered?' staggered':''), transform:`translate(${x},${y})`, tabindex:0, role:'button', 'aria-label':unit.name+'，生命 '+hp+'/'+maxHp+'，混乱耐性 '+stagger+'/'+maxStagger });
    group.append(svg('rect', { width, height:64, rx:8, class:'map-body' }));
    const name=svg('text',{x:9,y:21,class:'map-name'},unit.name);
    const nameWidth = [...unit.name].reduce((size, char) => size + (char.charCodeAt(0) > 255 ? 18 : 10), 0);
    if (nameWidth>width-18) {name.setAttribute('textLength',width-18);name.setAttribute('lengthAdjust','spacingAndGlyphs');}
    group.append(name);
    const hpLabel = hp+'/'+maxHp + (unit.is_staggered?' · 混乱':'');
    const hpText = svg('text',{x:9,y:37,class:'map-hp'},hpLabel);
    const hpWidth = [...hpLabel].reduce((size, char) => size + (char.charCodeAt(0) > 255 ? 14 : 8.4), 0);
    if (hpWidth>width-18) {hpText.setAttribute('textLength',width-18);hpText.setAttribute('lengthAdjust','spacingAndGlyphs');}
    group.append(hpText);
    group.append(svg('rect',{x:9,y:43,width:width-18,height:7,rx:3,class:'map-bar-track'}));
    group.append(svg('rect',{x:9,y:43,width:(width-18)*Math.min(1,hp/maxHp),height:7,rx:3,class:'map-hp-fill'}));
    group.append(svg('rect',{x:9,y:55,width:width-18,height:5,rx:2,class:'map-bar-track'}));
    group.append(svg('rect',{x:9,y:55,width:(width-18)*Math.min(1,stagger/maxStagger),height:5,rx:2,class:'map-stagger-fill'}));
    const show=()=>{const modal=openModal({title:unit.name});if(modal)modal.setBody(unitCard(unit));};
    group.addEventListener('click',show);group.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();show();}});
    group.addEventListener('focus',()=>liftUnit(group));
    group.addEventListener('blur',()=>liftUnit(null));
    unitNodes.set(unit.id,group);unitLayer.append(group);
  }
  // Hit-test in SVG coordinates even when an arrow currently covers a panel.
  canvas.addEventListener('pointermove', event => {
    const matrix = canvas.getScreenCTM(); if (!matrix) return;
    const point = canvas.createSVGPoint(); point.x = event.clientX; point.y = event.clientY;
    const local = point.matrixTransform(matrix.inverse());
    const match = [...positions.values()].find(p => local.x >= p.x && local.x <= p.x+p.width && local.y >= p.y && local.y <= p.y+64);
    liftUnit(match ? unitNodes.get(match.unit.id) : null);
  });
  canvas.addEventListener('pointerleave', () => liftUnit(null));
  dom.battleStrip.append(el('div', { class: 'target-map-header' }, el('strong', null, '战场'), el('span', { class: 'map-legend' }, el('span', { class: 'red' }, '↗ 敌方攻击'), el('span', { class: 'blue' }, '↗ 我方已行动'), el('span', { class: 'yellow' }, '↗ 防御响应'), areas.length ? el('span',null,'范围：悬停展开 · 点击固定') : null)), canvas);
}

function renderBattleStrip() {
  if (!dom.battleStrip) return;
  clearNode(dom.battleStrip);
  const overview = state.overview || {};
  const battle = overview.battle;
  const show = state.view === 'battle' && battle && Array.isArray(battle.participants);
  dom.battleStrip.classList.toggle('hidden', !show);
  if (!show) return;
  const active = battle.participants.filter((p) => p && toInt(p.active_in_stage, 0) === 1);
  const friendly = active.filter((p) => p.faction === 'FRIENDLY');
  const enemy = active.filter((p) => p.faction === 'ENEMY');
  renderTargetMap(battle, enemy, friendly);

}

/* ================= 底部操作条 ================= */

function phasePill(phase) {
  const cls = phase === 'FRIENDLY_ACTION' ? 'friendly'
    : phase === 'ENEMY_ACTION' ? 'enemy'
    : phase === 'STAGE_END' ? 'stage' : '';
  return el('span', { class: 'phase-pill ' + cls },
    el('span', { class: 'dot' }),
    '阶段：' + (PHASE_LABELS[phase] || phase || '未知'));
}

function renderActionBar() {
  if (!dom.actionBar) return;
  clearNode(dom.actionBar);
  dom.actionBar.classList.toggle('hidden', state.view !== 'battle');
  const overview = state.overview || {};
  const battle = overview.battle;
  const isGm = state.role === 'gm';

  if (!battle) {
    const published = overview.setup && overview.setup.status === 'STANDBY'
      && toInt(overview.setup.published, 0) === 1;
    if (!isGm && !published) {
      // 玩家侧无战斗且未发布：不写等待文案，直接留空（2026-07-27 反馈）。
      dom.actionBar.classList.add('hidden');
      return;
    }
    dom.actionBar.append(el('span', { class: 'action-hint' },
      isGm ? '当前没有进行中的战斗。到战斗编成栏目编排并发布。'
        : '战斗编成已发布，等待你确认开战。'));
    dom.actionBar.append(el('span', { class: 'action-spacer' }));
    dom.actionBar.append(el('button', {
      class: 'btn primary', type: 'button', onclick: () => showView('setup'),
    }, isGm ? '战斗编成' : '前往确认'));
    return;
  }

  const phase = String(battle.phase || '');
  dom.actionBar.append(phasePill(phase));

  if (phase === 'ENEMY_PLANNING') {
    if (isGm) {
      dom.actionBar.append(el('button', { class: 'btn primary', type: 'button', onclick: () => openActionWizard('e') }, '准备敌方行动'));
      dom.actionBar.append(writeButton('开始应对', 'ghost', async () => {
        await api('/api/battle/lock-intents', { method: 'POST', body: {} });
      }));
    } else dom.actionBar.append(el('span', { class: 'action-hint' }, '敌方正在准备行动…'));
  } else if (phase === 'FRIENDLY_ACTION') {
    // 回合顺序显性化：助战（GM 扮演）行动完，玩家核心才行动。
    const assistsPending = (battle.participants || []).some((p) =>
      p.faction === 'FRIENDLY' && !toInt(p.is_core, 0)
      && toInt(p.active_in_stage, 0) === 1 && toInt(p.current_hp, 0) > 0
      && !toInt(p.is_staggered, 0) && toInt(p.current_actions, 0) > 0);
    if (!isGm && assistsPending) {
      // 与敌方阶段一致的纯等待态：不给行动/结束回合按钮，防止跳过助战回合。
      dom.actionBar.append(el('span', { class: 'action-hint' }, '助战行动中……'));
      return;
    }
    dom.actionBar.append(el('button', {
      class: 'btn primary', type: 'button', onclick: () => openActionWizard('f'),
    }, isGm && assistsPending ? '助战行动' : '展开行动'));
    if (isGm) {
      dom.actionBar.append(writeButton('助战让行', 'ghost', async () => {
        await api('/api/battle/forfeit-assists', { method: 'POST', body: {} });
      }));
    }
    dom.actionBar.append(el('button', { class: 'btn', type: 'button', onclick: openDefenseWizard }, '防御指令'));
    dom.actionBar.append(writeButton('结束我方指令', 'ghost', async () => {
      await api('/api/battle/pass', { method: 'POST', body: {} });
    }));
  } else if (phase === 'ENEMY_ACTION') {
    if (isGm) {

      dom.actionBar.append(writeButton('执行敌方指令并结算', 'ghost', async () => {
        await api('/api/battle/settle', { method: 'POST', body: {} });
        toast('回合已清算。', 'ok');
      }));
    } else {
      dom.actionBar.append(el('span', { class: 'action-hint' }, '敌方行动中……'));
    }
  } else if (phase === 'STAGE_END') {
    if (isGm) {
      dom.actionBar.append(el('button', {
        class: 'btn primary', type: 'button', onclick: () => openNextStageWizard(),
      }, '进入下一阶段'));
    }
    // 玩家侧只留阶段标签，不加流程等待文案（2026-07-27 反馈）。
  } else {
    dom.actionBar.append(el('span', { class: 'action-hint' }, '战斗流程推进中…'));
  }

  if (isGm && (phase === 'FRIENDLY_ACTION' || phase === 'ENEMY_ACTION')) {
    dom.actionBar.append(el('button', {
      class: 'btn ghost', type: 'button', onclick: () => openReinforceWizard(),
    }, '增援'));
  }

  if (isGm) {
    dom.actionBar.append(el('span', { class: 'action-spacer' }));
    dom.actionBar.append(el('button', {
      class: 'btn danger small',
      type: 'button',
      onclick: () => confirmModal({
        title: '中止战斗',
        message: '确定要立即中止当前战斗吗？战斗将以「中止」结果封存，无法恢复。',
        confirmLabel: '中止战斗',
        danger: true,
        onConfirm: async () => {
          await api('/api/battle/stop', { method: 'POST', body: {} });
          toast('战斗已中止。', 'ok');
        },
      }),
    }, '中止战斗'));
  }
}

/* ================= 技能条目渲染（阵容页 / 向导共用） ================= */

function skillChips(skill) {
  const chips = [];
  if (skill.skill_type === 'EGO') chips.push(chip('E.G.O', 'ego-chip'));
  const cooldown = toInt(skill.base_cooldown, 0);
  if (cooldown > 0) chips.push(chip('冷却 ' + cooldown));
  const remaining = toInt(skill.cooldown_remaining, 0);
  if (remaining > 0) chips.push(chip('冷却中 ' + remaining, 'debuff'));
  const emotionReq = toInt(skill.emotion_requirement, 0);
  if (emotionReq > 0) chips.push(chip('需情感 Lv' + emotionReq));
  const scope = TARGET_SCOPE_LABELS[skill.target_scope] || skill.target_scope || '';
  const method = TARGET_METHOD_LABELS[skill.target_method] || skill.target_method || '';
  let targetText = scope && skill.target_method !== 'SELF' ? scope + '·' + method : method;
  if (skill.target_method === 'RANDOM' && toInt(skill.target_param, 0) > 0) {
    targetText += '×' + toInt(skill.target_param, 0);
  }
  if (targetText) chips.push(chip(targetText));
  if (skill.max_uses_per_battle !== null && skill.max_uses_per_battle !== undefined) {
    const used = toInt(skill.uses_this_battle, 0);
    chips.push(chip('限 ' + toInt(skill.max_uses_per_battle, 0) + ' 次' + (used ? '｜已用 ' + used : '')));
  }
  return chips;
}

function skillItem(skill) {
  const item = el('div', {
    class: 'skill-item' + (skill.available === false ? ' unavailable' : ''),
  },
    el('div', { class: 'skill-head' },
      el('span', { class: 'skill-name' }, skill.name || skill.skill_key || '技能'),
      skillChips(skill)));
  if (skill.description) {
    item.append(el('div', { class: 'skill-desc' }, skill.description));
  }
  return item;
}

/* ================= 向导：展开行动 ================= */

function pickItem(titleParts, subText, onPick) {
  const button = el('button', { class: 'pick-item', type: 'button' },
    el('span', { class: 'pick-title' }, titleParts));
  if (subText) button.append(el('span', { class: 'pick-sub' }, subText));
  button.addEventListener('click', onPick);
  return button;
}

function enemyIntentLabel(intent) {
  const targets = intent.effective_target_names || intent.target_names || [];
  const redirect = intent.redirect;
  return intent.actor_name + ' · ' + intent.skill_name + ' → ' + targets.join('、')
    + (redirect ? '（被' + redirect.actor_name + redirect.label + '）' : '');
}

function openEnemyIntentDetails(intent) {
  const modal = openModal({title:intent.actor_name + ' · ' + intent.skill_name, wide:true});
  if (!modal) return;
  const body = el('div', {class:'enemy-skill-details'},
    el('p', {class:'effect-description'}, intent.skill_description || '该技能暂无额外说明。'),
    el('p', null, '目标：' + (intent.effective_target_names || intent.target_names || []).join('、')));
  if (intent.redirect) body.append(el('p', null, '被' + intent.redirect.actor_name + intent.redirect.label));
  if (intent.disabled) body.append(el('p', {class:'forecast tier-1'}, '释放者已混乱或倒下，这次行动将取消。'));
  else if (intent.status !== 'PENDING') body.append(el('p', {class:'forecast-note'}, '这次行动已处理。'));
  const timing = {PRE:'使用前', ON:'使用时', POST:'使用后', TURN_START:'回合开始', TURN_END:'回合结束'};
  const conditions = {
    ALWAYS:'直接生效', ON_HIT:'命中时', ON_CRIT_HIT:'暴击命中时', ON_CRIT_TRIGGER:'触发暴击时',
    ON_KILL:'击杀时', ON_CRIT_KILL:'暴击击杀时', ON_KILL_SELECTED_TARGET:'击杀选定目标时',
    ON_NO_KILL_SELECTED_TARGET:'未击杀选定目标时', ON_KILL_ALLY:'击杀同阵营角色时', ON_KILL_ENEMY:'击杀对立阵营角色时'
  };
  const scopes = {PER_SKILL:'每次技能', PER_TARGET:'每个符合条件的目标', PER_HIT:'每次符合条件的命中'};
  for (const effect of intent.skill_effects || []) {
    const params = effect.params || {};
    let summary;
    if (effect.effect_type === 'DAMAGE') summary = '造成 ' + (effect.value || '0') + ' 点伤害';
    else if (effect.effect_type === 'HEAL') summary = '恢复 ' + (effect.value || '0') + ' 点生命';
    else if (effect.effect_type === 'APPLY_EFFECT') {
      summary = '施加「' + (effect.effect_name || '状态效果') + '」';
      if (params.intensity) summary += ' · ' + params.intensity + '级';
      if (params.stacks) summary += ' · ' + params.stacks + '层';
      if (params.remaining_turns !== undefined && params.remaining_turns !== null) summary += ' · 持续' + params.remaining_turns + '回合';
      if (params.activation_timing === 'NEXT_TURN_START') summary += ' · 下回合开始生效';
    } else summary = params.description || '特殊效果，详见上方技能说明。';
    body.append(el('div', {class:'skill-item'},
      el('div', {class:'chips'}, chip(timing[effect.timing] || '条件触发'), chip(conditions[effect.trigger_condition] || '条件生效'),
        effect.trigger_condition !== 'ALWAYS' ? chip(scopes[effect.trigger_scope] || '满足条件时') : null),
      el('p', {class:'skill-name'}, summary),
      el('div', {class:'skill-desc'}, '作用目标：' + ((effect.target_names || []).join('、') || '无有效目标')),
      effect.description ? el('div', {class:'effect-description'}, effect.description) : null));
  }
  body.append(el('p', {class:'forecast-note'}, '伤害显示技能原始点数或公式；实际结果还受状态、混乱和防御等影响。条件效果仅在满足条件时生效。'));
  modal.setBody(body);
  modal.setFooter(el('button', {class:'btn ghost', type:'button', onclick:closeModal}, '关闭'));
}

async function openDefenseWizard() {
  const modal = openModal({ title: '发布防御指令', wide: true });
  if (!modal) return;
  let battle;
  try { battle = await api('/api/battle'); }
  catch (err) { closeModal(); toast(err.message, 'error'); return; }
  const submit = async (actor, intent) => {
    try {
      await api('/api/battle/defend', { method: 'POST', body: { actor_id: actor.id, intent_id: intent ? intent.id : null } });
      closeModal();
    } catch (err) { toast(err.message, 'error'); }
  };
  const list = el('div');
  const actors = await api('/api/battle/actors?side=f');
  for (const actor of actors) {
    const unit = battle.participants.find((p) => p.id === actor.id);
    const spec = unit && unit.defense_skill;
    if (!spec || (battle.defenses || []).some((d) => d.actor_id === actor.id)) continue;
    list.append(pickItem(actor.name + ' · ' + spec.name + ' ' + spec.power, '消耗一次行动，敌方攻击时结算', () => {
      if (spec.kind === 'COUNTER') { submit(actor); return; }
      const redirecting = ['INTERCEPT','MEET'].includes(spec.kind);
      const targets = el('div');
      for (const intent of battle.enemy_intents || []) {
        if (intent.status !== 'PENDING' || intent.disabled) continue;
        if (redirecting && intent.target_ids.length !== 1) continue;
        if (!redirecting && !(intent.attack_target_ids || []).includes(actor.id)) continue;
        const forecast = (intent.response_forecasts || {})[actor.id];
        const prediction = forecast ? el('span', {class:'forecast tier-' + forecast.tier}, forecast.label + ' · ' + (forecast.approximate ? '约 ' : '') + Math.round(forecast.probability * 100) + '%') : null;
        targets.append(pickItem([enemyIntentLabel(intent), prediction].filter(Boolean), forecast ? '首段点数：' + forecast.defense_power + ' 对 ' + forecast.attack_power : null, () => submit(actor, redirecting ? intent : null)));
      }
      targets.append(el('p',{class:'forecast-note'},'预测为首段点数不低于攻击的概率，不含条件加值；迎击仍在承伤后反击，多段攻击逐次判定。'));
      if (!redirecting) targets.append(el('button',{class:'btn',onclick:()=>submit(actor)},'准备' + spec.name));
      modal.setBody(targets);
    }));
  }
  modal.setBody(list);
  modal.setFooter(el('button', { class: 'btn ghost', onclick: closeModal }, '关闭'));
}

function openActionWizard(side) {
  const isEnemy = side === 'e';
  const modal = openModal({ title: isEnemy ? '敌方行动' : '展开行动', wide: true });
  if (!modal) return;
  const sel = { actor: null, skill: null, target: null };
  const cancelBtn = () => el('button', { class: 'btn ghost', type: 'button', onclick: closeModal }, '取消');
  const backBtn = (fn) => el('button', { class: 'btn ghost', type: 'button', onclick: fn }, '上一步');
  const showLoading = (note) => {
    modal.setNote(note);
    modal.setBody(el('div', { class: 'modal-loading' }, '读取中…'));
    modal.setFooter(cancelBtn());
  };
  const showError = (err, retry, buttons) => {
    modal.setBody(el('div', { class: 'page-error' },
      el('div', null, (err && err.message) || '读取失败'),
      el('button', { class: 'btn ghost', type: 'button', onclick: retry }, '重试')));
    modal.setFooter(buttons);
  };

  const stepActor = async () => {
    showLoading('第 1 步 / 选择行动者');
    let actors;
    try {
      actors = await api('/api/battle/actors?side=' + side);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) { closeModal(); return; }
      showError(err, stepActor, [cancelBtn()]);
      return;
    }
    const list = el('div');
    const rows = Array.isArray(actors) ? actors : [];
    if (!rows.length) {
      list.append(el('div', { class: 'empty-note' },
        isEnemy ? '当前没有可行动的敌方单位。' : '当前没有可行动的我方单位。'));
    }
    for (const actor of rows) {
      const meta = [];
      meta.push(chip('HP ' + toInt(actor.current_hp, 0) + '/' + toInt(actor.max_hp, 0)));
      meta.push(chip('行动 ' + toInt(actor.current_actions, 0) + '/' + toInt(actor.max_actions, 0)));
      const emotion = toInt(actor.emotion_level, 0);
      if (emotion > 0) meta.push(chip('情感 Lv' + emotion));
      if (toInt(actor.is_staggered, 0)) meta.push(chip('混乱', 'debuff'));
      const button = pickItem([actor.name || ('#' + actor.id), meta],
        null, () => { sel.actor = actor; stepSkill(); });
      if (toInt(actor.current_hp, 0) <= 0) button.disabled = true;
      list.append(button);
    }
    modal.setNote('第 1 步 / 选择行动者');
    modal.setBody(list);
    modal.setFooter(cancelBtn());
  };

  const stepSkill = async () => {
    showLoading('第 2 步 / 选择技能');
    let skills;
    try {
      skills = await api('/api/actors/' + sel.actor.id + '/skills');
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) { closeModal(); return; }
      showError(err, stepSkill, [cancelBtn(), backBtn(stepActor)]);
      return;
    }
    const list = el('div',
      { class: '' },
      el('div', { class: 'wizard-subtitle' }, '行动者：' + (sel.actor.name || '#' + sel.actor.id)));
    const rows = Array.isArray(skills) ? skills : [];
    const usable = rows.filter((s) => s.available !== false);
    const blocked = rows.filter((s) => s.available === false);
    if (!rows.length) {
      list.append(el('div', { class: 'empty-note' }, '该单位没有任何技能。'));
    } else if (!usable.length) {
      list.append(el('div', { class: 'empty-note' }, '当前没有可立即使用的技能。'));
    }
    for (const skill of usable) {
      const button = pickItem([skill.name || skill.skill_key || '技能', skillChips(skill)],
        skill.description || null,
        () => {
          sel.skill = skill;
          if (skill.target_method === 'SELECT_TARGET') stepTarget();
          else { sel.target = null; submitAction(); }
        });
      list.append(button);
    }
    // 不可用技能排在队列末端：变暗禁选，并标注原因（冷却剩余等）。
    for (const skill of blocked) {
      const cooldown = toInt(skill.cooldown_remaining, 0);
      const reason = cooldown > 0
        ? '冷却中｜还需 ' + cooldown + ' 回合'
        : skill.skill_type === 'EGO' && toInt(skill.ego_used, 0)
          ? '本场 E.G.O 已展开'
        : toInt(skill.emotion_requirement, 0) > 0
          ? '需情感等级 ' + toInt(skill.emotion_requirement, 0)
          : '本场使用次数已耗尽';
      const button = pickItem(
        [skill.name || skill.skill_key || '技能', skillChips(skill), chip(reason, 'debuff')],
        skill.description || null, () => {});
      button.disabled = true;
      button.classList.add('pick-disabled');
      list.append(button);
    }
    modal.setNote('第 2 步 / 选择技能');
    modal.setBody(list);
    modal.setFooter(cancelBtn(), backBtn(stepActor));
  };

  const stepTarget = async () => {
    showLoading('第 3 步 / 选择目标');
    let targets;
    try {
      targets = await api('/api/actors/' + sel.actor.id + '/skills/' + sel.skill.id + '/targets');
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) { closeModal(); return; }
      showError(err, stepTarget, [cancelBtn(), backBtn(stepSkill)]);
      return;
    }
    const list = el('div', null,
      el('div', { class: 'wizard-subtitle' },
        '技能「' + (sel.skill.name || '') + '」需要指定一个目标。'));
    const rows = Array.isArray(targets) ? targets : [];
    if (!rows.length) list.append(el('div', { class: 'empty-note' }, '没有符合技能范围的存活目标。'));
    // 状态效果取自战况总览（与右侧状态栏同源），按目标 id 对上号。
    const participants = (state.overview && state.overview.battle
      && Array.isArray(state.overview.battle.participants))
      ? state.overview.battle.participants : [];
    const unitById = new Map(participants.map((p) => [toInt(p.id, 0), p]));
    for (const target of rows) {
      const meta = [
        chip(target.faction === 'ENEMY' ? '敌方' : '我方', target.faction === 'ENEMY' ? 'debuff' : 'buff'),
        chip('HP ' + toInt(target.current_hp, 0) + '/' + toInt(target.max_hp, 0)),
      ];
      const unit = unitById.get(toInt(target.id, 0));
      const effects = (unit && Array.isArray(unit.effects)) ? unit.effects : [];
      const pending = (unit && Array.isArray(unit.pending_effects)) ? unit.pending_effects : [];
      let sub = null;
      if (effects.length || pending.length) {
        sub = el('span', { class: 'chips' }, effects.map(effectChip));
        if (pending.length) {
          sub.append(el('span', { class: 'pending-label' }, '下回合'));
          for (const item of pending) sub.append(pendingChip(item));
        }
      }
      list.append(pickItem([target.name || ('#' + target.id), meta], sub,
        () => { sel.target = target; submitAction(); }));
    }
    modal.setNote('第 3 步 / 选择目标');
    modal.setBody(list);
    modal.setFooter(cancelBtn(), backBtn(stepSkill));
  };

  // 选完目标（或无需选目标的技能选完技能）即发动，不再有确认步（2026-07-27 反馈）。
  const submitAction = async () => {
    showLoading('发动中…');
    try {
      const body = { actor_id: sel.actor.id, skill_id: sel.skill.id };
      if (sel.target) body.target_ids = [sel.target.id];
      await api('/api/battle/action', { method: 'POST', body });
      closeModal();
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) { closeModal(); return; }
      toast((err && err.message) || '行动失败', 'error');
      if (sel.skill && sel.skill.target_method === 'SELECT_TARGET') stepTarget();
      else stepSkill();
    }
  };

  stepActor();
}

/* ================= 向导：战斗中实时增援（GM，2026-07-27 裁定） ================= */

async function openReinforceWizard() {
  const modal = openModal({ title: '战场增援', wide: true });
  if (!modal) return;
  modal.setNote('实时生效：敌方立即在当前阶段登场，助战立即加入战场');
  modal.setBody(el('div', { class: 'modal-loading' }, '读取中…'));
  modal.setFooter(el('button', { class: 'btn ghost', type: 'button', onclick: closeModal }, '关闭'));

  let templates;
  let roster;
  try {
    [templates, roster] = await Promise.all([
      api('/api/templates'),
      api('/api/roster?faction=FRIENDLY'),
    ]);
  } catch (err) {
    modal.setBody(el('div', { class: 'empty-note' }, (err && err.message) || '读取失败'));
    return;
  }

  const body = el('div', null);

  /* --- 敌方增援：从模板即时生成 --- */
  const foeTemplates = (Array.isArray(templates) ? templates : [])
    .filter((t) => toInt(t.is_core, 0) === 0);
  const foeSelect = el('select', null);
  if (!foeTemplates.length) foeSelect.append(el('option', { value: '' }, '（无可用模板）'));
  for (const template of foeTemplates) {
    foeSelect.append(el('option', { value: template.template_key },
      (template.name || template.template_key) + '｜HP ' + toInt(template.max_hp, 0)));
  }
  const amountInput = el('input', { type: 'number', min: '1', max: '5', value: '1' });
  const foeNameInput = el('input', { type: 'text', placeholder: '自定义显示名（可空）', maxlength: '40' });
  body.append(el('div', { class: 'card' },
    el('div', { class: 'card-title' }, '敌方增援'),
    el('div', { class: 'card-sub' }, '立即在当前阶段生成并入场。'),
    el('div', { class: 'form-grid' },
      el('div', { class: 'form-field' }, el('label', null, '敌人模板'), foeSelect),
      el('div', { class: 'form-field' }, el('label', null, '数量'), amountInput),
      el('div', { class: 'form-field full' }, el('label', null, '显示名'), foeNameInput)),
    el('div', { class: 'card-footer' },
      writeButton('敌方入场', 'primary small', async () => {
        if (!foeSelect.value) { toast('请先选择敌人模板。', 'error'); return; }
        const payload = {
          template_key: foeSelect.value,
          amount: Math.max(1, Math.min(5, toInt(amountInput.value, 1))),
        };
        const customName = foeNameInput.value.trim();
        if (customName) payload.name = customName;
        await api('/api/setup/foes/add', { method: 'POST', body: payload });
        closeModal();
      }))));

  /* --- 友方助战增援：既有角色即刻加入战场 --- */
  const battle = state.overview && state.overview.battle;
  const inBattle = new Set(
    (battle && Array.isArray(battle.participants) ? battle.participants : [])
      .map((p) => toInt(p.id, 0)));
  const addable = (Array.isArray(roster) ? roster : []).filter((c) =>
    toInt(c.is_core, 0) === 0 && !inBattle.has(toInt(c.id, 0)) && toInt(c.current_hp, 0) > 0);
  const allyCard = el('div', { class: 'card' },
    el('div', { class: 'card-title' }, '助战增援'),
    el('div', { class: 'card-sub' }, '勾选后立即加入当前战场（由你扮演操作）。'));
  if (!addable.length) {
    allyCard.append(el('div', { class: 'empty-note' },
      '没有可加入的助战角色（都在场上，或需先在阵容页新建）。'));
  } else {
    const checked = new Set();
    for (const character of addable) {
      const box = el('input', { type: 'checkbox' });
      box.addEventListener('change', () => {
        if (box.checked) checked.add(toInt(character.id, 0));
        else checked.delete(toInt(character.id, 0));
      });
      allyCard.append(el('label', { class: 'check-row' }, box,
        el('span', { class: 'check-label' }, character.name || ('#' + character.id)),
        el('span', { class: 'check-sub' },
          'HP ' + toInt(character.current_hp, 0) + '/' + toInt(character.max_hp, 0))));
    }
    allyCard.append(el('div', { class: 'card-footer' },
      writeButton('助战入场', 'primary small', async () => {
        if (!checked.size) { toast('请先勾选要入场的助战。', 'error'); return; }
        await api('/api/setup/allies/add', {
          method: 'POST', body: { character_ids: Array.from(checked) },
        });
        closeModal();
      })));
  }
  body.append(allyCard);

  modal.setBody(body);
}

/* ================= 向导：进入下一阶段 ================= */

function openNextStageWizard() {
  const modal = openModal({ title: '进入下一阶段', note: '勾选入战友方' });
  if (!modal) return;
  modal.setBody(el('div', { class: 'modal-loading' }, '读取中…'));
  modal.setFooter(el('button', { class: 'btn ghost', type: 'button', onclick: closeModal }, '取消'));

  (async () => {
    let roster;
    try {
      roster = await api('/api/roster?faction=FRIENDLY');
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) { closeModal(); return; }
      modal.setBody(el('div', { class: 'page-error' }, (err && err.message) || '读取失败'));
      return;
    }
    const alive = (Array.isArray(roster) ? roster : []).filter((c) => toInt(c.current_hp, 0) > 0);
    const checked = new Set(alive.map((c) => toInt(c.id, 0)));
    const confirmBtn = el('button', { class: 'btn primary', type: 'button' }, '进入下一阶段');
    const syncConfirm = () => {
      confirmBtn.disabled = checked.size === 0;
      confirmBtn.textContent = checked.size === 0 ? '至少勾选一名友方' : '进入下一阶段（' + checked.size + ' 人）';
    };
    const list = el('div', null,
      el('div', { class: 'wizard-subtitle' }, '勾选进入下一阶段的友方（默认全选）；敌人由关卡阶段预设。'));
    if (!alive.length) list.append(el('div', { class: 'empty-note' }, '没有仍存活的友方角色。'));
    for (const character of alive) {
      const box = el('input', { type: 'checkbox', checked: '' });
      box.addEventListener('change', () => {
        if (box.checked) checked.add(toInt(character.id, 0));
        else checked.delete(toInt(character.id, 0));
        syncConfirm();
      });
      list.append(el('label', { class: 'check-row' }, box,
        el('span', { class: 'check-label' }, character.name || ('#' + character.id),
          toInt(character.is_core, 0) ? null : el('span', { class: 'unit-tag assist', style: 'margin-left:6px' }, '助战')),
        el('span', { class: 'check-sub' },
          'HP ' + toInt(character.current_hp, 0) + '/' + toInt(character.max_hp, 0))));
    }
    confirmBtn.addEventListener('click', () => withBusy(confirmBtn, async () => {
      await api('/api/battle/next', { method: 'POST', body: { friendly_ids: Array.from(checked) } });
      closeModal();
      toast('已进入下一阶段。', 'ok');
    }));
    syncConfirm();
    modal.setBody(list);
    modal.setFooter(
      el('button', { class: 'btn ghost', type: 'button', onclick: closeModal }, '取消'),
      confirmBtn);
  })();
}

/* ================= 页面视图：战斗列表（GM） ================= */

function pageShell(title, desc, ...children) {
  return el('div', { class: 'page-inner' },
    el('div', { class: 'page-head' },
      el('h2', null, title),
      desc ? el('span', { class: 'page-desc' }, desc) : null,
      el('span', { style: 'flex:1' }),
      el('button', { class: 'icon-btn', type: 'button', title: '刷新', onclick: () => renderCurrentView() }, '↻')),
    children);
}

async function battlesSection() {
  /* 战斗列表并入战斗编成栏目（裁定 §7.5-5），以卡片区块形式呈现。 */
  let setups;
  try { setups = await api('/api/battles'); } catch (err) { return null; }
  const rows = Array.isArray(setups) ? setups : [];
  if (!rows.length) return null;
  const selectedId = state.overview && state.overview.setup ? toInt(state.overview.setup.id, 0) : 0;
  const card = el('div', { class: 'card' },
    el('div', { class: 'card-title' }, '战斗列表'),
    el('div', { class: 'card-sub' }, '选中一场待触发战斗进行编排。'));
  for (const setup of rows) {
    const isActive = setup.status === 'ACTIVE';
    const isSelected = toInt(setup.id, 0) === selectedId;
    const subParts = [
      '关卡：' + (setup.encounter_name || setup.encounter_key || ''),
      toInt(setup.total_stages, 0) + ' 阶段',
      '友方 ' + toInt(setup.friendly_count, 0) + ' 人',
    ];
    if (isActive && setup.current_stage) {
      subParts.push('进行中：阶段 ' + setup.current_stage
        + (setup.phase ? '｜' + (PHASE_LABELS[setup.phase] || setup.phase) : ''));
    }
    const row = el('div', { class: 'list-row' },
      el('div', { class: 'row-main' },
        el('div', { class: 'row-title' },
          setup.name || ('战斗 #' + setup.id),
          el('span', { class: 'status-chip ' + (isActive ? 'active' : 'standby'), style: 'margin-left:8px' },
            SETUP_STATUS_LABELS[setup.status] || setup.status),
          isSelected ? el('span', { class: 'status-chip selected', style: 'margin-left:6px' }, '当前选中') : null),
        el('div', { class: 'row-sub' }, subParts.join('｜'))));
    if (!isSelected) {
      row.append(writeButton('选用', 'ghost small', async () => {
        await api('/api/setup/use', { method: 'POST', body: { setup_id: setup.id } });
        await refreshOverview();
        renderCurrentView();
      }));
    }
    card.append(row);
  }
  return card;
}

/* ================= 页面视图：编成（GM） ================= */

function newBattleCard(encounters) {
  const nameInput = el('input', { type: 'text', placeholder: '例如：第三次镇压行动', maxlength: '80' });
  const select = el('select', null);
  const rows = Array.isArray(encounters) ? encounters : [];
  if (!rows.length) select.append(el('option', { value: '' }, '（没有可用关卡）'));
  for (const encounter of rows) {
    select.append(el('option', { value: encounter.encounter_key },
      (encounter.name || encounter.encounter_key) + '｜' + toInt(encounter.total_stages, 0) + ' 阶段'));
  }
  const card = el('div', { class: 'card' },
    el('div', { class: 'card-title' }, '新建战斗'),
    el('div', { class: 'card-sub' }, '从关卡模板建立一场待触发战斗，创建后自动选中。'),
    el('div', { class: 'form-grid' },
      el('div', { class: 'form-field' }, el('label', null, '战斗名称（可留空沿用关卡名）'), nameInput),
      el('div', { class: 'form-field' }, el('label', null, '关卡'), select)));
  card.append(el('div', { class: 'card-footer' },
    writeButton('创建并选中', 'primary', async () => {
      const encounterKey = select.value;
      if (!encounterKey) { toast('请先选择关卡。', 'error'); return; }
      const body = { encounter_key: encounterKey, name: nameInput.value.trim() || null };
      if (!body.name) delete body.name;
      await api('/api/setup/new', { method: 'POST', body });
      toast('战斗已创建并选中。', 'ok');
      await refreshOverview();
      renderCurrentView();
    })));
  return card;
}

async function renderSetupView() {
  if (state.role !== 'gm') return renderPlayerSetupView();
  await refreshOverview();
  const setup = state.overview ? state.overview.setup : null;

  if (!setup) {
    const [encounters, listCard] = await Promise.all([api('/api/encounters'), battlesSection()]);
    const shell = pageShell('战斗编成', '当前没有选中的战斗');
    if (listCard) shell.append(listCard);
    shell.append(newBattleCard(encounters));
    return shell;
  }

  const setupId = toInt(setup.id, 0);
  const battleActive = setup.status === 'ACTIVE';
  const [encounters, templates, friendlyRoster] = await Promise.all([
    api('/api/encounters'),
    api('/api/templates'),
    api('/api/roster?faction=FRIENDLY'),
  ]);
  const roster = Array.isArray(friendlyRoster) ? friendlyRoster : [];
  learnFactions(roster);
  const cores = roster.filter((c) => toInt(c.is_core, 0) === 1);

  const planFriendlies = Array.isArray(setup.friendlies) ? setup.friendlies : [];
  const planEnemies = Array.isArray(setup.enemies) ? setup.enemies : [];
  const planStages = Array.isArray(setup.stages) ? setup.stages : [];
  const shell = pageShell('战斗编成', battleActive ? '战斗进行中（编成已锁定）' : '编排完成后发布给玩家确认');

  /* --- 概要卡 --- */
  const headCard = el('div', { class: 'card' },
    el('div', { class: 'card-title' },
      el('span', null, setup.name || ('战斗 #' + setupId)),
      el('span', { class: 'status-chip ' + (battleActive ? 'active' : 'standby') },
        SETUP_STATUS_LABELS[setup.status] || setup.status),
      !battleActive && toInt(setup.published, 0) ? el('span', { class: 'status-chip selected' }, '已发布') : null,
      el('span', { class: 'spacer' }),
      el('span', { class: 'check-sub' }, '修订 #' + toInt(setup.revision, 0))),
    el('div', { class: 'card-sub' },
      '关卡：' + (setup.encounter_name || '') + '｜共 ' + toInt(setup.total_stages, 0) + ' 阶段'));
  if (planStages.length) {
    const stageBox = el('div', { class: 'card-section' },
      el('div', { class: 'card-section-title' }, '阶段与通关条件'));
    for (const stage of planStages) {
      let conditionText = '';
      try {
        const condition = JSON.parse(String(stage.clear_condition_json || '{}'));
        const type = condition && condition.type ? String(condition.type) : '';
        conditionText = CLEAR_CONDITION_LABELS[type] || type || '';
      } catch (err) { conditionText = ''; }
      const outcome = stage.clear_outcome === 'NEXT_STAGE' ? '进入下一阶段' : '结束战斗';
      const stageRow = el('div', { class: 'list-row' },
        el('div', { class: 'row-main' },
          el('div', { class: 'row-title' }, '阶段 ' + stage.stage_number + '｜' + (stage.name || '')),
          el('div', { class: 'row-sub' },
            (conditionText ? conditionText + ' → ' : '') + outcome)));
      if (!battleActive && planStages.length > 1) {
        stageRow.append(writeButton('删除', 'danger small', async () => {
          await api('/api/setup/stages/remove', {
            method: 'POST', body: { stage_number: toInt(stage.stage_number, 0) },
          });
          await refreshOverview();
          renderCurrentView();
        }));
      }
      stageBox.append(stageRow);
    }
    headCard.append(stageBox);
  }
  if (!battleActive) {
    headCard.append(el('div', { class: 'card-footer' },
      el('button', {
        class: 'btn danger', type: 'button',
        onclick: () => confirmModal({
          title: '撤销编成',
          message: '确定撤销「' + (setup.name || '') + '」吗？该待触发战斗将被作废。',
          warn: '此操作不可恢复；编成内容（核心/友方/敌人/异想体配置）将一并丢弃。',
          requireCheck: '我确认要撤销这场战斗编成',
          confirmLabel: '撤销编成',
          danger: true,
          onConfirm: async () => {
            await api('/api/setup/discard', { method: 'POST', body: {} });
            toast('编成已撤销。', 'ok');
            await refreshOverview();
            renderCurrentView();
          },
        }),
      }, '撤销编成'),
      writeButton('发布给玩家', 'primary', async () => {
        await api('/api/setup/publish', { method: 'POST', body: {} });
        toast('已发布：玩家将收到确认横幅，确认后战斗开始。', 'info');
        await refreshOverview();
        renderCurrentView();
      })));
  }
  shell.append(headCard);

  if (battleActive) {
    shell.append(el('div', { class: 'card' },
      el('div', { class: 'card-sub', style: 'margin-bottom:0' },
        '战斗进行中，编成不可修改；进入故事频道推进流程。'),
      el('div', { class: 'card-footer' },
        el('button', { class: 'btn primary small', type: 'button', onclick: () => showView('battle') }, '进入故事频道'))));
    const activeListCard = await battlesSection();
    if (activeListCard) shell.append(activeListCard);
    shell.append(newBattleCard(encounters));
    return shell;
  }

  /* --- 可参战核心（加入/移除，交互与普通友方一致） --- */
  const poolIds = new Set(parseJsonArray(setup.core_pool_json).map((n) => toInt(n, 0)));
  const coreCard = el('div', { class: 'card' },
    el('div', { class: 'card-title' }, '可参战核心'),
    el('div', { class: 'card-sub' },
      '加入编成的核心是玩家本场【可以】选用的角色；实际出战名单与人格由玩家确认时决定。'));
  const inPool = cores.filter((c) => poolIds.has(toInt(c.id, 0)));
  const outPool = cores.filter((c) => !poolIds.has(toInt(c.id, 0)));
  if (!inPool.length) coreCard.append(el('div', { class: 'empty-note' }, '尚未加入任何核心。'));
  for (const core of inPool) {
    coreCard.append(el('div', { class: 'list-row' },
      el('div', { class: 'row-main' },
        el('div', { class: 'row-title' }, core.name || ('#' + core.id)),
        el('div', { class: 'row-sub' },
          'HP ' + toInt(core.current_hp, 0) + '/' + toInt(core.max_hp, 0))),
      writeButton('移除', 'danger small', async () => {
        const ids = Array.from(poolIds).filter((id) => id !== toInt(core.id, 0));
        await api('/api/setup/core-pool', { method: 'POST', body: { character_ids: ids } });
        await refreshOverview();
        renderCurrentView();
      })));
  }
  if (outPool.length) {
    const addChecked = new Set();
    const addSection = el('div', { class: 'card-section' },
      el('div', { class: 'card-section-title' }, '可加入的核心'));
    for (const core of outPool) {
      const box = el('input', { type: 'checkbox' });
      box.addEventListener('change', () => {
        if (box.checked) addChecked.add(toInt(core.id, 0));
        else addChecked.delete(toInt(core.id, 0));
      });
      addSection.append(el('label', { class: 'check-row' }, box,
        el('span', { class: 'check-label' }, core.name || ('#' + core.id)),
        el('span', { class: 'check-sub' },
          'HP ' + toInt(core.current_hp, 0) + '/' + toInt(core.max_hp, 0))));
    }
    addSection.append(el('div', { class: 'card-footer' },
      writeButton('加入编成', 'ghost small', async () => {
        if (!addChecked.size) { toast('请先勾选要加入的核心。', 'error'); return; }
        const ids = Array.from(new Set([...poolIds, ...addChecked]));
        await api('/api/setup/core-pool', { method: 'POST', body: { character_ids: ids } });
        await refreshOverview();
        renderCurrentView();
      })));
    coreCard.append(addSection);
  }
  shell.append(coreCard);

  /* --- 普通友方 --- */
  const allyCard = el('div', { class: 'card' },
    el('div', { class: 'card-title' }, '普通友方'),
    el('div', { class: 'card-sub' }, '从既有角色中增删非核心友方。'));
  const currentAllies = planFriendlies.filter((f) => toInt(f.is_core, 0) === 0);
  if (!currentAllies.length) allyCard.append(el('div', { class: 'empty-note' }, '尚未编入普通友方。'));
  for (const ally of currentAllies) {
    allyCard.append(el('div', { class: 'list-row' },
      el('div', { class: 'row-main' },
        el('div', { class: 'row-title' }, ally.name || ('#' + ally.id)),
        el('div', { class: 'row-sub' }, 'HP ' + toInt(ally.current_hp, 0))),
      writeButton('移除', 'danger small', async () => {
        await api('/api/setup/allies/remove', { method: 'POST', body: { character_id: ally.id } });
        toast('已移除 ' + (ally.name || '') + '。', 'ok');
        await refreshOverview();
        renderCurrentView();
      })));
  }
  const inPlanIds = new Set(planFriendlies.map((f) => toInt(f.id, 0)));
  const addable = roster.filter((c) => toInt(c.is_core, 0) === 0 && !inPlanIds.has(toInt(c.id, 0)));
  if (addable.length) {
    const addChecked = new Set();
    const addSection = el('div', { class: 'card-section' },
      el('div', { class: 'card-section-title' }, '可加入的角色'));
    for (const character of addable) {
      const box = el('input', { type: 'checkbox' });
      box.addEventListener('change', () => {
        if (box.checked) addChecked.add(toInt(character.id, 0));
        else addChecked.delete(toInt(character.id, 0));
      });
      addSection.append(el('label', { class: 'check-row' }, box,
        el('span', { class: 'check-label' }, character.name || ('#' + character.id)),
        el('span', { class: 'check-sub' }, 'HP ' + toInt(character.current_hp, 0) + '/' + toInt(character.max_hp, 0))));
    }
    addSection.append(el('div', { class: 'card-footer' },
      writeButton('加入编成', 'ghost small', async () => {
        if (!addChecked.size) { toast('请先勾选要加入的角色。', 'error'); return; }
        await api('/api/setup/allies/add', { method: 'POST', body: { character_ids: Array.from(addChecked) } });
        toast('普通友方已加入。', 'ok');
        await refreshOverview();
        renderCurrentView();
      })));
    allyCard.append(addSection);
  }
  shell.append(allyCard);

  /* --- 敌方编成 --- */
  const foeCard = el('div', { class: 'card' },
    el('div', { class: 'card-title' }, '敌方编成'),
    el('div', { class: 'card-sub' },
      '预设与手动敌人都可以切换携带或移除（只影响本场副本）；「不携带」的开战不登场。'));
  if (!planEnemies.length) foeCard.append(el('div', { class: 'empty-note' }, '尚未编入敌人。'));
  const stageNumbers = Array.from(new Set(planEnemies.map((e) => toInt(e.stage_number, 0)))).sort((a, b) => a - b);
  for (const stageNumber of stageNumbers) {
    foeCard.append(el('div', { class: 'card-section-title', style: 'margin-top:10px' }, '阶段 ' + stageNumber));
    for (const enemy of planEnemies.filter((e) => toInt(e.stage_number, 0) === stageNumber)) {
      const label = enemy.display_name || enemy.template_name || enemy.template_key || '敌人';
      const amount = toInt(enemy.amount, 1);
      const carried = toInt(enemy.enabled === undefined ? 1 : enemy.enabled, 1) === 1;
      const row = el('div', { class: 'list-row' + (carried ? '' : ' foe-off') },
        el('div', { class: 'row-main' },
          el('div', { class: 'row-title' },
            label + (amount > 1 ? ' ×' + amount : ''),
            carried ? null : el('span', { class: 'unit-tag locked', style: 'margin-left:8px' }, '不携带')),
          el('div', { class: 'row-sub' },
            (enemy.template_name || enemy.template_key || '')
            + '｜' + (enemy.source === 'MANUAL' ? '手动追加' : '关卡预设'))));
      if (!battleActive) {
        row.append(writeButton(carried ? '不携带' : '携带', 'ghost small', async () => {
          await api('/api/setup/foes/toggle', {
            method: 'POST', body: { setup_enemy_id: enemy.id, enabled: !carried },
          });
          await refreshOverview();
          renderCurrentView();
        }));
        row.append(writeButton('移除', 'danger small', async () => {
          await api('/api/setup/foes/remove', { method: 'POST', body: { setup_enemy_id: enemy.id } });
          await refreshOverview();
          renderCurrentView();
        }));
      }
      foeCard.append(row);
    }
  }
  const foeTemplates = (Array.isArray(templates) ? templates : []).filter((t) => toInt(t.is_core, 0) === 0);
  const foeSelect = el('select', null);
  if (!foeTemplates.length) foeSelect.append(el('option', { value: '' }, '（无可用模板）'));
  for (const template of foeTemplates) {
    foeSelect.append(el('option', { value: template.template_key },
      (template.name || template.template_key) + '｜HP ' + toInt(template.max_hp, 0)));
  }
  const stageInput = el('input', { type: 'number', min: '1', max: String(Math.max(1, toInt(setup.total_stages, 1))), value: '1' });
  const foeNameInput = el('input', { type: 'text', placeholder: '自定义显示名（可空）', maxlength: '40' });
  foeCard.append(el('div', { class: 'card-section' },
    el('div', { class: 'card-section-title' }, '追加敌人'),
    el('div', { class: 'form-grid' },
      el('div', { class: 'form-field' }, el('label', null, '敌人模板'), foeSelect),
      el('div', { class: 'form-field' }, el('label', null, '加入阶段'), stageInput),
      el('div', { class: 'form-field full' }, el('label', null, '显示名'), foeNameInput)),
    el('div', { class: 'card-footer' },
      writeButton('追加敌人', 'ghost small', async () => {
        if (!foeSelect.value) { toast('请先选择敌人模板。', 'error'); return; }
        const body = {
          template_key: foeSelect.value,
          stage_number: Math.max(1, toInt(stageInput.value, 1)),
        };
        const customName = foeNameInput.value.trim();
        if (customName) body.name = customName;
        await api('/api/setup/foes/add', { method: 'POST', body });
        toast('敌人已追加。', 'ok');
        await refreshOverview();
        renderCurrentView();
      }))));
  shell.append(foeCard);

  /* 异想体书页由玩家决定（发布时带入玩家携带，玩家确认时可调）——GM 编成不再设装备栏。 */

  const listCard = await battlesSection();
  if (listCard) shell.append(listCard);
  shell.append(newBattleCard(encounters));
  return shell;
}

/* ================= 页面视图：战斗编成（玩家确认，裁定 §7.5-5） ================= */

async function renderPlayerSetupView() {
  await refreshOverview();
  const overview = state.overview || {};
  const shell = pageShell('战斗编成', '确认出战配置后开战');
  if (overview.battle) {
    shell.append(el('div', { class: 'card' },
      el('div', { class: 'card-sub', style: 'margin-bottom:0' }, '战斗进行中；请到故事频道推进。'),
      el('div', { class: 'card-footer' },
        el('button', { class: 'btn primary small', type: 'button', onclick: () => showView('battle') }, '进入故事频道'))));
    return shell;
  }
  const setup = overview.setup;
  if (!setup || setup.status !== 'STANDBY' || !toInt(setup.published, 0)) {
    shell.append(el('div', { class: 'card' },
      el('div', { class: 'empty-note' },
        '管理人尚未发布战斗编成；发布后这里会出现确认界面（同时有横幅通知）。')));
    return shell;
  }

  const [plan, deckData, rosterRows] = await Promise.all([
    api('/api/plan'),
    api('/api/deck'),
    api('/api/roster?faction=FRIENDLY').catch(() => []),
  ]);
  const friendlies = Array.isArray(plan.friendlies) ? plan.friendlies : [];
  const assists = friendlies.filter((f) => toInt(f.is_core, 0) === 0);
  // 可参战池：GM 圈定的候选核心；玩家从中挑出战名单（裁定 §7.5-5）。
  const poolIds = parseJsonArray(plan.core_pool_json).map((n) => toInt(n, 0));
  const rosterCores = (Array.isArray(rosterRows) ? rosterRows : [])
    .filter((c) => toInt(c.is_core, 0) === 1);
  const cores = poolIds.length
    ? rosterCores.filter((c) => poolIds.includes(toInt(c.id, 0)))
    : rosterCores;
  const plannedCoreMap = new Map(friendlies
    .filter((f) => toInt(f.is_core, 0) === 1)
    .map((f) => [toInt(f.id, 0), f]));

  shell.append(el('div', { class: 'card' },
    el('div', { class: 'card-title' },
      el('span', null, plan.name || ('战斗 #' + plan.id)),
      el('span', { class: 'status-chip standby' }, '待确认'),
      el('span', { class: 'spacer' }),
      el('span', { class: 'check-sub' }, '修订 #' + toInt(plan.revision, 0))),
    el('div', { class: 'card-sub' },
      '关卡：' + (plan.encounter_name || '') + '｜共 ' + toInt(plan.total_stages, 0) + ' 阶段'
      + '｜敌人 ' + toInt(plan.enemy_count, 0) + ' 名（情报保密）'
      + (assists.length ? '｜助战：' + assists.map((a) => a.name || '').join('、') : ''))));

  /* 核心人格选择 */
  const personasByCore = new Map();
  await Promise.all(cores.map(async (core) => {
    try {
      const personas = await api('/api/characters/' + core.id + '/personas');
      personasByCore.set(toInt(core.id, 0), Array.isArray(personas) ? personas : []);
    } catch (err) {
      personasByCore.set(toInt(core.id, 0), []);
    }
  }));
  const coreCard = el('div', { class: 'card' },
    el('div', { class: 'card-title' }, '出战核心'),
    el('div', { class: 'card-sub' },
      '从管理人圈定的可参战核心中，勾选实际出战的角色并为每人选择本场人格。'));
  // 当前已保存的出战名单（含人格），一眼可确认。
  const savedCores = friendlies.filter((f) => toInt(f.is_core, 0) === 1);
  coreCard.append(el('div', { class: 'deck-carry', style: 'margin-left:0' },
    chip('当前出战', 'buff'),
    el('span', { class: 'deck-page-text' }, savedCores.length
      ? savedCores.map((f) => (f.name || '')
        + (f.persona_name ? '（' + f.persona_name + '）' : '')).join('、')
      : '尚未选择')));
  const controls = [];
  for (const core of cores) {
    const coreId = toInt(core.id, 0);
    const personas = personasByCore.get(coreId) || [];
    const planned = plannedCoreMap.get(coreId) || null;
    const box = el('input', { type: 'checkbox' });
    box.checked = plannedCoreMap.size ? !!planned : true;
    const select = el('select', null);
    if (!personas.length) select.append(el('option', { value: '' }, '（无可用人格）'));
    for (const persona of personas) {
      select.append(el('option', { value: String(persona.id) },
        (persona.name || persona.persona_key) + (toInt(persona.is_default, 0) ? '｜默认' : '')));
    }
    const planningPersona = planned && planned.persona_key
      ? personas.find((p) => p.persona_key === planned.persona_key) : null;
    const fallbackPersona = personas.find((p) => toInt(p.is_active, 0))
      || personas.find((p) => toInt(p.is_default, 0));
    const initial = planningPersona || fallbackPersona;
    if (initial) select.value = String(initial.id);
    select.disabled = !personas.length;
    controls.push({ core, box, select });
    coreCard.append(el('div', { class: 'list-row' },
      el('label', { class: 'check-row', style: 'flex:1;padding:0' }, box,
        el('span', { class: 'check-label' }, core.name || ('#' + coreId))),
      el('div', { style: 'width:56%' }, select)));
  }
  if (!cores.length) {
    coreCard.append(el('div', { class: 'empty-note' }, '管理人尚未圈定可参战核心，请联系管理人。'));
  } else {
    coreCard.append(el('div', { class: 'card-footer' },
      writeButton('保存出战选择', 'ghost', async () => {
        const choices = [];
        const summary = [];
        for (const control of controls) {
          if (!control.box.checked) continue;
          const personaId = toInt(control.select.value, 0);
          if (!personaId) { toast((control.core.name || '核心') + ' 没有可用人格。', 'error'); return; }
          choices.push([toInt(control.core.id, 0), personaId]);
          const option = control.select.selectedOptions && control.select.selectedOptions[0];
          summary.push((control.core.name || '')
            + '（' + ((option && option.textContent.split('｜')[0]) || '人格') + '）');
        }
        if (!choices.length) { toast('至少选择一名核心出战。', 'error'); return; }
        await api('/api/setup/core', { method: 'POST', body: { choices } });
        toast('出战已确认：' + summary.join('、'), 'info');
        renderCurrentView();
      })));
  }
  shell.append(coreCard);

  /* 本场书页卡组（发布时已带入当前携带；可应用预设或现调） */
  const gearKeys = new Set(parseJsonArray(plan.abnormalities_json).map(String));
  const abnormalities = Array.isArray(deckData.abnormalities) ? deckData.abnormalities : [];
  const gearPresets = Array.isArray(deckData.presets) ? deckData.presets : [];
  const gearCounter = el('span', { class: 'check-sub' });
  const gearCard = el('div', { class: 'card' },
    el('div', { class: 'card-title' }, '本场书页卡组',
      el('span', { class: 'spacer' }), gearCounter),
    el('div', { class: 'card-sub' },
      '发布时已带入你的当前携带；可一键应用预设，或现场调整后开战。'));
  // 当前已保存的本场卡组，一眼可确认。
  const abnormalityNames = new Map(abnormalities.map((item) =>
    [String(item.abnormality_key), item.name || item.abnormality_key]));
  const savedGear = Array.from(gearKeys).map((key) => abnormalityNames.get(key) || key);
  gearCard.append(el('div', { class: 'deck-carry', style: 'margin-left:0' },
    chip('当前卡组', 'buff'),
    el('span', { class: 'deck-page-text' },
      savedGear.length ? savedGear.join('、') + '（' + savedGear.length + '/' + DECK_LIMIT + '）'
        : '尚未携带任何异想体')));
  if (gearPresets.length) {
    const presetRow = el('div', { class: 'chips', style: 'margin-bottom:10px' });
    for (const preset of gearPresets) {
      presetRow.append(writeButton('应用：' + preset.name, 'ghost small', async () => {
        await api('/api/setup/gear', {
          method: 'POST', body: { abnormality_keys: preset.abnormality_keys },
        });
        toast('已应用预设「' + preset.name + '」到本场卡组。', 'info');
        renderCurrentView();
      }));
    }
    gearCard.append(presetRow);
  }
  const boxes = [];
  for (const abnormality of abnormalities) {
    const box = el('input', { type: 'checkbox' });
    if (gearKeys.has(String(abnormality.abnormality_key))) box.checked = true;
    boxes.push({ key: String(abnormality.abnormality_key), box });
    gearCard.append(abnormalityBlock(abnormality, box));
  }
  bindDeckLimit(boxes, gearCounter);
  if (!abnormalities.length) {
    gearCard.append(el('div', { class: 'empty-note' }, '没有可用的异想体书页。'));
  } else {
    gearCard.append(el('div', { class: 'card-footer' },
      writeButton('保存本场卡组', 'ghost', async () => {
        const chosen = boxes.filter((b) => b.box.checked).map((b) => b.key);
        await api('/api/setup/gear', {
          method: 'POST', body: { abnormality_keys: chosen },
        });
        const names = chosen.map((key) => abnormalityNames.get(key) || key);
        toast('本场卡组已确认：' + (names.join('、') || '（空）')
          + '（' + names.length + '/' + DECK_LIMIT + '）', 'info');
        renderCurrentView();
      })));
  }
  shell.append(gearCard);

  shell.append(el('div', { class: 'card' },
    el('div', { class: 'card-sub' }, '确认以上配置无误后开战；开战后编成锁定。若管理人在此期间改动编成，确认会因修订变化而失效，重新进入本页即可。'),
    el('div', { class: 'card-footer' },
      writeButton('确认并开战', 'primary', async () => {
        const ready = await api('/api/setup/ready');
        await api('/api/setup/launch', { method: 'POST', body: { revision: toInt(ready.revision, 0) } });
        showView('battle');
      }))));
  return shell;
}

/* ================= 页面视图：阵容 ================= */

function personaRow(character, persona) {
  const isGm = state.role === 'gm';
  const opened = persona.opened === undefined || !!toInt(persona.opened, 0);
  const row = el('div', { class: 'list-row' },
    el('div', { class: 'row-main' },
      el('div', { class: 'row-title' },
        persona.name || persona.persona_key,
        toInt(persona.is_active, 0) ? chip('当前', 'buff') : null,
        toInt(persona.is_default, 0) ? chip('默认') : null,
        isGm ? el('span', {
          class: 'unit-tag ' + (opened ? 'carried' : 'locked'),
          style: 'margin-left:6px',
        }, opened ? '已开放' : '未开放') : null),
      el('div', { class: 'row-sub' },
        'HP ' + toInt(persona.max_hp, 0) + '｜行动 ' + toInt(persona.max_actions, 0)
        + '｜混乱 ' + toInt(persona.max_stagger, 0)
        + (persona.description ? '｜' + persona.description : ''))));
  // 玩家可为自己的核心切换人格（仅已开放的）；GM 不受限。
  const canSwitch = !toInt(persona.is_active, 0)
    && (isGm || (character.faction !== 'ENEMY' && toInt(character.is_core, 0) && opened));
  if (canSwitch) {
    row.append(writeButton('切换', 'ghost small', async () => {
      await api('/api/identity', {
        method: 'POST',
        body: { character_id: character.id, persona_key: persona.persona_key },
      });
      renderCurrentView();
    }));
  }
  if (isGm && !toInt(persona.is_default, 0)) {
    row.append(writeButton(opened ? '收回' : '开放', opened ? 'danger small' : 'primary small',
      async () => {
        await api('/api/personas/access', {
          method: 'POST',
          body: { persona_keys: [persona.persona_key], opened: !opened },
        });
        renderCurrentView();
      }));
  }
  return row;
}

function characterCard(character) {
  const hp = toInt(character.current_hp, 0);
  const isEnemy = character.faction === 'ENEMY';
  const card = el('div', { class: 'card' });
  const detail = el('div', { class: 'card-section hidden' });
  let loaded = false;

  const headBtn = el('button', { class: 'char-head', type: 'button' },
    el('span', { class: 'pick-title' },
      character.name || ('#' + character.id),
      !isEnemy && !toInt(character.is_core, 0) ? chip('助战', 'ego-chip') : null,
      isEnemy && unitHasTag(character, 'boss') ? el('span', { class: 'unit-tag boss' }, 'BOSS') : null,
      chip(isEnemy ? '敌方' : '友方', isEnemy ? 'debuff' : 'buff'),
      hp <= 0 ? chip('倒下', 'debuff') : null),
    el('span', { class: 'pick-sub' },
      'HP ' + hp + '/' + toInt(character.max_hp, 0)
      + '｜行动上限 ' + toInt(character.max_actions, 0)
      + '｜情感 Lv' + toInt(character.emotion_level, 0)
      + (character.template_key ? '｜模板 ' + character.template_key : '')));

  headBtn.addEventListener('click', async () => {
    detail.classList.toggle('hidden');
    if (loaded || detail.classList.contains('hidden')) return;
    loaded = true;
    detail.append(el('div', { class: 'modal-loading' }, '读取详情…'));
    const secret = isEnemy && state.role !== 'gm';
    try {
      const personasPromise = api('/api/characters/' + character.id + '/personas');
      const skillsPromise = secret ? Promise.resolve(null)
        : api('/api/characters/' + character.id + '/skills');
      const personas = await personasPromise.catch(() => []);
      let skills = null;
      let skillsError = null;
      try { skills = await skillsPromise; } catch (err) { skillsError = err; }
      clearNode(detail);
      const personaRows = Array.isArray(personas) ? personas : [];
      if (personaRows.length) {
        detail.append(el('div', { class: 'card-section-title' }, '人格'));
        for (const persona of personaRows) detail.append(personaRow(character, persona));
      }
      if (secret) {
        detail.append(el('div', { class: 'card-section-title', style: 'margin-top:10px' }, '技能'));
        detail.append(el('div', { class: 'empty-note' }, '敌方技能情报对玩家保密。'));
      } else if (skillsError) {
        detail.append(el('div', { class: 'card-section-title', style: 'margin-top:10px' }, '技能'));
        detail.append(el('div', { class: 'empty-note' }, skillsError.message || '技能读取失败。'));
      } else {
        const skillRows = Array.isArray(skills) ? skills : [];
        // E.G.O 独立成模块（2026-07-26 裁定：个人 EGO 在阵容选单展示）
        const egoRows = skillRows.filter((s) => s.skill_type === 'EGO');
        const normalRows = skillRows.filter((s) => s.skill_type !== 'EGO');
        if (egoRows.length) {
          detail.append(el('div', { class: 'card-section-title ego-section', style: 'margin-top:10px' }, 'E.G.O'));
          for (const skill of egoRows) detail.append(skillItem(skill));
        }
        detail.append(el('div', { class: 'card-section-title', style: 'margin-top:10px' }, '技能'));
        if (!normalRows.length) detail.append(el('div', { class: 'empty-note' }, '暂无技能。'));
        for (const skill of normalRows) detail.append(skillItem(skill));
      }
    } catch (err) {
      clearNode(detail);
      detail.append(el('div', { class: 'empty-note' }, (err && err.message) || '读取失败。'));
    }
  });

  card.append(headBtn, detail);
  return card;
}

async function renderRosterView() {
  const promises = [api('/api/roster')];
  const isGm = state.role === 'gm';
  if (isGm) promises.push(api('/api/templates').catch(() => []));
  const [roster, templates] = await Promise.all(promises);
  const rows = Array.isArray(roster) ? roster : [];
  learnFactions(rows);
  const friendly = rows.filter((c) => c.faction === 'FRIENDLY');
  const enemy = rows.filter((c) => c.faction === 'ENEMY');
  const shell = pageShell('阵容', isGm
    ? '管理全部角色档案：新建友方、切换人格、查看敌我技能与 E.G.O'
    : '这里是你的五名核心：查看详情并切换当前人格，战前编队默认采用此处配置');

  if (isGm) {
    const templateRows = (Array.isArray(templates) ? templates : []).filter((t) => toInt(t.is_core, 0) === 0);
    const select = el('select', null);
    if (!templateRows.length) select.append(el('option', { value: '' }, '（无可用模板）'));
    for (const template of templateRows) {
      select.append(el('option', { value: template.template_key },
        (template.name || template.template_key) + '｜HP ' + toInt(template.max_hp, 0)));
    }
    const nameInput = el('input', { type: 'text', placeholder: '自定义名称（可空）', maxlength: '40' });
    shell.append(el('div', { class: 'card' },
      el('div', { class: 'card-title' }, '新建友方角色'),
      el('div', { class: 'card-sub' }, '从模板生成一名普通友方，加入常备阵容。'),
      el('div', { class: 'form-grid' },
        el('div', { class: 'form-field' }, el('label', null, '模板'), select),
        el('div', { class: 'form-field' }, el('label', null, '名称'), nameInput)),
      el('div', { class: 'card-footer' },
        writeButton('创建角色', 'primary', async () => {
          if (!select.value) { toast('请先选择模板。', 'error'); return; }
          const body = { template_key: select.value };
          const customName = nameInput.value.trim();
          if (customName) body.name = customName;
          await api('/api/create', { method: 'POST', body });
          toast('友方角色已创建。', 'ok');
          renderCurrentView();
        }))));
  }

  // 2026-07-26 裁定：玩家的阵容选单只服务"给核心角色换人格"，不见助战与敌方。
  const friendlyShown = isGm ? friendly : friendly.filter((c) => toInt(c.is_core, 0) === 1);
  shell.append(el('div', { class: 'faction-title friendly', style: 'margin:6px 4px 10px' },
    isGm ? '友方' : '核心角色', el('span', { class: 'count' }, '· ' + friendlyShown.length)));
  if (!friendlyShown.length) shell.append(el('div', { class: 'empty-note' }, '没有友方角色。'));
  for (const character of friendlyShown) shell.append(characterCard(character));

  if (isGm) {
    shell.append(el('div', { class: 'faction-title enemy', style: 'margin:18px 4px 10px' },
      '敌方', el('span', { class: 'count' }, '· ' + enemy.length)));
    if (!enemy.length) shell.append(el('div', { class: 'empty-note' }, '没有敌方角色记录。'));
    for (const character of enemy) shell.append(characterCard(character));
  }
  return shell;
}

/* ================= 页面视图：书页 ================= */

const DECK_LIMIT = 5;
const PAGE_LEVEL_ROMAN = { 1: 'Ⅰ', 2: 'Ⅱ', 3: 'Ⅲ' };

function pageLevelLabel(level) {
  return PAGE_LEVEL_ROMAN[toInt(level, 1)] || String(level);
}

function pageLine(page) {
  const isAwakening = page.page_type === 'AWAKENING';
  return el('div', { class: 'deck-page-line' },
    chip(pageLevelLabel(page.level)),
    chip(isAwakening ? '觉醒' : '崩溃', isAwakening ? 'type-awaken' : 'type-break'),
    el('span', { class: 'deck-page-text' },
      (page.name || page.page_key) + (page.description ? '｜' + page.description : '')));
}

function abnormalityBlock(abnormality, box) {
  /* 一个异想体 = 一副小卡组：携带被动 + 分级觉醒/崩溃页。 */
  const block = el('div', { class: 'deck-abnormality' });
  const carriedTag = el('span', {
    class: 'unit-tag carried' + (box.checked ? '' : ' hidden'),
    style: 'margin-left:6px',
  }, '已携带');
  box._carriedTag = carriedTag;
  const locked = abnormality.opened === false;
  if (locked) box.disabled = true;
  block.append(el('label', { class: 'check-row', style: 'padding-left:0' }, box,
    el('span', { class: 'check-label' },
      abnormality.name || abnormality.abnormality_key,
      carriedTag,
      locked ? el('span', { class: 'unit-tag locked', style: 'margin-left:6px' }, '未开放') : null),
    el('span', { class: 'check-sub' },
      (Array.isArray(abnormality.pages) ? abnormality.pages.length : 0) + ' 页')));
  if (abnormality.description) {
    block.append(el('div', { class: 'deck-desc' }, abnormality.description));
  }
  if (abnormality.carry_bonus) {
    block.append(el('div', { class: 'deck-carry' },
      chip('携带被动', 'buff'),
      el('span', { class: 'deck-page-text' },
        (abnormality.carry_bonus.name || '')
        + (abnormality.carry_bonus.description ? '｜' + abnormality.carry_bonus.description : ''))));
  }
  for (const page of (Array.isArray(abnormality.pages) ? abnormality.pages : [])) {
    block.append(pageLine(page));
  }
  return block;
}

function bindDeckLimit(boxes, counter) {
  const update = () => {
    const count = boxes.filter((b) => b.box.checked).length;
    if (counter) counter.textContent = '携带 ' + count + ' / ' + DECK_LIMIT;
    for (const item of boxes) {
      if (item.box._carriedTag) {
        item.box._carriedTag.classList.toggle('hidden', !item.box.checked);
      }
    }
  };
  for (const item of boxes) {
    item.box.addEventListener('change', () => {
      if (item.box.checked
        && boxes.filter((b) => b.box.checked).length > DECK_LIMIT) {
        item.box.checked = false;
        toast('最多携带 ' + DECK_LIMIT + ' 个异想体。', 'error');
      }
      update();
    });
  }
  update();
}

async function renderDeckEditor() {
  /* 战斗不活跃时：构筑携带卡组与预设（2026-07-27 裁定 2）。 */
  const data = await api('/api/deck');
  const isGm = state.role === 'gm';
  const deckKeys = new Set(
    (Array.isArray(data.deck) ? data.deck : []).map((d) => String(d.abnormality_key)));
  const abnormalities = Array.isArray(data.abnormalities) ? data.abnormalities : [];
  const presets = Array.isArray(data.presets) ? data.presets : [];
  const shell = pageShell('异想体书页', isGm
    ? '查看/代管玩家的携带卡组与预设；发布编成时自动带入当前携带'
    : '构筑携带卡组与预设编队；战斗中情感升级时从携带的异想体里出书页候选');

  if (!abnormalities.length) {
    shell.append(el('div', { class: 'card' },
      el('div', { class: 'empty-note' }, isGm
        ? '内容包中还没有可用的异想体书页。'
        : '管理人还没有开放任何异想体书页。')));
    return shell;
  }

  /* --- 开放管理（仅 GM）：控制哪些异想体对玩家可见可用 --- */
  if (isGm) {
    const accessCard = el('div', { class: 'card' },
      el('div', { class: 'card-title' }, '开放管理'),
      el('div', { class: 'card-sub' },
        '控制哪些异想体对玩家开放：未开放的玩家完全不可见，也不能编入卡组/预设。'));
    for (const abnormality of abnormalities) {
      const opened = abnormality.opened !== false;
      accessCard.append(el('div', { class: 'list-row' },
        el('div', { class: 'row-main' },
          el('div', { class: 'row-title' },
            abnormality.name || abnormality.abnormality_key,
            el('span', {
              class: 'unit-tag ' + (opened ? 'carried' : 'locked'),
              style: 'margin-left:8px',
            }, opened ? '已开放' : '未开放')),
          el('div', { class: 'row-sub' }, abnormality.description || '')),
        writeButton(opened ? '收回' : '开放给玩家', opened ? 'danger small' : 'primary small',
          async () => {
            await api('/api/abnormalities/access', {
              method: 'POST',
              body: { abnormality_keys: [abnormality.abnormality_key], opened: !opened },
            });
            renderCurrentView();
          })));
    }
    shell.append(accessCard);
  }

  /* --- 当前携带（只列已开放的；未开放的去「开放管理」找） --- */
  const carriedPool = isGm
    ? abnormalities.filter((item) => item.opened !== false)
    : abnormalities;
  const counter = el('span', { class: 'check-sub' });
  const deckCard = el('div', { class: 'card' },
    el('div', { class: 'card-title' }, '当前携带', el('span', { class: 'spacer' }), counter),
    el('div', { class: 'card-sub' },
      '携带越少，战斗中候选越固定；携带越多越随机，但每个异想体的携带被动都会生效。'
      + '书页按角色自身情感等级解锁上限：情感1-2 可出Ⅰ级页，3-4 解锁至Ⅱ级，5 解锁至Ⅲ级（低级页始终在池内）。'));
  const boxes = [];
  for (const abnormality of carriedPool) {
    const box = el('input', { type: 'checkbox' });
    if (deckKeys.has(String(abnormality.abnormality_key))) box.checked = true;
    boxes.push({ key: String(abnormality.abnormality_key), box });
    deckCard.append(abnormalityBlock(abnormality, box));
  }
  if (!carriedPool.length) {
    deckCard.append(el('div', { class: 'empty-note' },
      '还没有已开放的异想体；先在上方「开放管理」里开放。'));
  }
  bindDeckLimit(boxes, counter);
  deckCard.append(el('div', { class: 'card-footer' },
    writeButton('保存当前携带', 'primary', async () => {
      await api('/api/deck', {
        method: 'POST',
        body: { abnormality_keys: boxes.filter((b) => b.box.checked).map((b) => b.key) },
      });
      toast('携带卡组已保存。', 'info');
      renderCurrentView();
    })));
  shell.append(deckCard);

  /* --- 预设编队 --- */
  const presetCard = el('div', { class: 'card' },
    el('div', { class: 'card-title' }, '携带预设'),
    el('div', { class: 'card-sub' },
      isGm ? '玩家保存的编队预设；应用即覆盖当前携带。'
        : '像编队一样保存几套常用组合；战前可直接应用，也可以现调。'));
  if (!presets.length) {
    presetCard.append(el('div', { class: 'empty-note' }, '还没有保存过预设。'));
  }
  for (const preset of presets) {
    presetCard.append(el('div', { class: 'list-row' },
      el('div', { class: 'row-main' },
        el('div', { class: 'row-title' }, preset.name),
        el('div', { class: 'row-sub' },
          (Array.isArray(preset.abnormality_keys) ? preset.abnormality_keys.length : 0)
          + ' 个异想体')),
      writeButton('应用', 'ghost small', async () => {
        await api('/api/deck', {
          method: 'POST', body: { abnormality_keys: preset.abnormality_keys },
        });
        toast('已应用预设「' + preset.name + '」。', 'info');
        renderCurrentView();
      }),
      writeButton('删除', 'danger small', async () => {
        await api('/api/deck/presets/' + preset.id + '/delete', { method: 'POST', body: {} });
        renderCurrentView();
      })));
  }
  const nameInput = el('input', { type: 'text', placeholder: '预设名称（如：烧伤速攻）', maxlength: '30' });
  presetCard.append(el('div', { class: 'card-section' },
    el('div', { class: 'card-section-title' }, '把当前勾选保存为预设'),
    el('div', { class: 'form-grid' },
      el('div', { class: 'form-field full' }, el('label', null, '名称'), nameInput)),
    el('div', { class: 'card-footer' },
      writeButton('保存预设', 'ghost small', async () => {
        const keys = boxes.filter((b) => b.box.checked).map((b) => b.key);
        if (!nameInput.value.trim()) { toast('请先填预设名称。', 'error'); return; }
        if (!keys.length) { toast('请先勾选要携带的异想体。', 'error'); return; }
        await api('/api/deck/presets', {
          method: 'POST', body: { name: nameInput.value.trim(), abnormality_keys: keys },
        });
        toast('预设已保存。', 'info');
        renderCurrentView();
      }))));
  shell.append(presetCard);
  return shell;
}

async function renderPagesView() {
  /* 书页页面只做战斗外的卡组编成；战斗中的候选选取走战斗频道强制弹窗。 */
  return renderDeckEditor();
}

/* ================= 战斗频道：书页候选强制弹窗（2026-07-27 裁定） ================= */

function renderPageOfferModal(offers) {
  const isGm = state.role === 'gm';
  const modal = openModal({ title: '异想体书页候选', wide: true, locked: !isGm });
  if (!modal) return;
  modal.setNote(isGm ? '正常由玩家选取；必要时你可代选或先关闭'
    : '每组选取一张后才能继续其他操作');
  const body = el('div', null);
  const groups = new Map();
  for (const offer of offers) {
    const key = String(offer.offer_group || offer.id);
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(offer);
  }
  for (const groupOffers of groups.values()) {
    const first = groupOffers[0] || {};
    const card = el('div', { class: 'card' },
      el('div', { class: 'card-title' },
        '「' + (first.character_name || '') + '」的书页候选',
        el('span', { class: 'spacer' }),
        el('span', { class: 'check-sub' }, '每组只能选一张')));
    for (const offer of groupOffers) {
      const isAwakening = offer.page_type === 'AWAKENING';
      const row = el('div', { class: 'list-row' },
        el('div', { class: 'row-main' },
          el('div', { class: 'row-title' },
            offer.name || '书页',
            chip(pageLevelLabel(offer.level)),
            chip(isAwakening ? '觉醒' : '崩溃', isAwakening ? 'type-awaken' : 'type-break')),
          el('div', { class: 'row-sub' }, offer.description || '')));
      row.append(writeButton('选取', 'primary small', async () => {
        await api('/api/pages/' + offer.id + '/accept', { method: 'POST', body: {} });
        state.pageOffersShowing = false;
        closeModal();
        await refreshOverview(); // 还有其他组会立即重开弹窗
      }));
      card.append(row);
    }
    body.append(card);
  }
  modal.setBody(body);
  if (isGm) {
    modal.setFooter(el('button', {
      class: 'btn ghost', type: 'button',
      onclick: () => { state.pageOffersShowing = false; closeModal(); },
    }, '先关闭'));
  }
}

function maybeOpenPageOffers() {
  const offers = state.overview && Array.isArray(state.overview.page_offers)
    ? state.overview.page_offers : [];
  if (!offers.length) {
    if (state.pageOffersShowing) { state.pageOffersShowing = false; closeModal(); }
    return;
  }
  if (state.view !== 'battle') return;
  try {
    if (state.pageOffersShowing) { renderPageOfferModal(offers); return; }
    // 其他弹窗（行动向导等）使用中时不抢占，等其关闭后的下一次刷新再弹。
    if (dom.modalRoot && !dom.modalRoot.classList.contains('hidden')) return;
    state.pageOffersShowing = true;
    renderPageOfferModal(offers);
  } catch (err) {
    // 兜底：任何构建异常都不允许留下空白遮罩。
    state.pageOffersShowing = false;
    closeModal();
    toast('书页候选弹窗渲染失败：' + ((err && err.message) || err), 'error');
  }
}

/* ================= 页面视图：管理人（GM） ================= */

async function renderManagerView() {
  const skills = await api('/api/manager');
  const rows = Array.isArray(skills) ? skills : [];
  const shell = pageShell('经理干预', state.role === 'gm'
    ? '玩家（经理）的战局干预能力一览；必要时你也可代为发动'
    : '你作为经理的战局干预手段，每场战斗次数有限，用在关键回合');
  if (!rows.length) {
    shell.append(el('div', { class: 'card' },
      el('div', { class: 'empty-note' }, '没有已解锁的干预能力，或当前尚无战斗记录。')));
    return shell;
  }
  for (const skill of rows) {
    const maxUses = toInt(skill.max_uses_per_battle, 0);
    const remain = Math.max(0, maxUses - toInt(skill.uses, 0));
    const windowLabel = skill.allowed_phase
      ? (PHASE_LABELS[skill.allowed_phase] || skill.allowed_phase) : '任意合法窗口';
    const card = el('div', { class: 'card' },
      el('div', { class: 'card-title' },
        el('span', null, skill.name || skill.manager_skill_key),
        el('span', { class: 'spacer' }),
        chip('窗口：' + windowLabel),
        chip('剩余 ' + remain + '/' + maxUses, remain > 0 ? 'buff' : 'debuff')),
      el('div', { class: 'card-sub', style: 'margin-bottom:0' }, skill.description || ''));
    const useBtn = writeButton('发动', 'primary small', async () => {
      await api('/api/manager/' + encodeURIComponent(skill.manager_skill_key) + '/use',
        { method: 'POST', body: {} });
      toast('「' + (skill.name || '') + '」已发动。', 'ok');
      renderCurrentView();
    });
    if (remain <= 0) useBtn.disabled = true;
    card.append(el('div', { class: 'card-footer' }, useBtn));
    shell.append(card);
  }
  return shell;
}

/* ================= 页面视图：设置 ================= */

const HELP_SECTIONS = [
  ['故事', '跑团聊天 + 实时战斗播报。玩家以玩家身份发言；管理人输入 角色名：“内容” 即以 NPC 发言，其余为旁白。消息支持编辑、撤回、已读与搜索。'],
  ['战斗编成', '管理人：新建/选中战斗，编排核心、助战、各阶段敌人（预设可删改）与书页池，完成后「发布给玩家」。玩家：收到横幅通知后确认人格与卡组，「确认并开战」。'],
  ['阵容', '查看角色的属性、人格与技能（玩家看不到敌方技能）。可在战斗外切换核心角色的人格。'],
  ['书页', '异想体书页是战前配好的被动卡组；战斗中情感等级提升时从中选取一张，每组只能选一张。'],
  ['干预', '经理（玩家）在战斗中可发动的特殊干预能力，每场战斗有次数限制。'],
  ['设置', '重载内容包（GM）、登出与本帮助。'],
];

function openHelpModal() {
  const modal = openModal({ title: '帮助｜各区块用途', wide: true });
  if (!modal) return;
  const body = el('div');
  for (const [name, desc] of HELP_SECTIONS) {
    body.append(el('div', { class: 'summary-row', style: 'padding:7px 0' },
      el('span', { class: 'summary-key', style: 'width:86px;font-weight:700;color:var(--accent-strong)' }, name),
      el('span', { class: 'summary-val', style: 'color:var(--text-dim)' }, desc)));
  }
  modal.setBody(body);
  modal.setFooter(el('button', { class: 'btn primary', type: 'button', onclick: closeModal }, '知道了'));
}

async function renderSettingsView() {
  const shell = pageShell('设置', '');
  const isGm = state.role === 'gm';

  shell.append(el('div', { class: 'card' },
    el('div', { class: 'card-title' }, '当前身份'),
    el('div', { class: 'card-sub' },
      isGm ? '管理人：拥有编成、阶段控制、书页接纳与系统维护的全部权限。'
        : '玩家：可以查看战况并在我方行动阶段展开行动，其余操作由管理人执行。'),
    el('div', { class: 'card-footer' },
      el('span', { class: 'role-badge ' + (isGm ? 'gm' : 'player'), style: 'margin-right:auto' },
        isGm ? '管理人' : '玩家'),
      writeButton('登出', 'ghost', async () => {
        try { await api('/api/logout', { method: 'POST', body: {} }); } catch (err) { /* 忽略 */ }
        enterLogin();
        toast('已登出。', 'info');
      }))));

  if (isGm) {
    shell.append(el('div', { class: 'card' },
      el('div', { class: 'card-title' }, '内容包'),
      el('div', { class: 'card-sub' }, '重新加载 content/ 下的内容包定义（关卡、技能、异想体等）。'),
      el('div', { class: 'card-footer' },
        el('button', {
          class: 'btn ghost', type: 'button',
          onclick: () => confirmModal({
            title: '重载内容包',
            message: '将按配置路径重新加载全部内容包并校验处理器，确认执行？',
            confirmLabel: '重载',
            onConfirm: async () => {
              await api('/api/reload', { method: 'POST', body: {} });
              toast('内容包已重载。', 'ok');
            },
          }),
        }, '重载内容包'))));
  }

  shell.append(el('div', { class: 'card' },
    el('div', { class: 'card-title' }, '帮助'),
    el('div', { class: 'card-sub' }, '各区块的用途一览。'),
    el('div', { class: 'card-footer' },
      el('button', { class: 'btn ghost', type: 'button', onclick: openHelpModal }, '打开帮助'))));
  return shell;
}

/* ================= 导航与视图切换 ================= */

const VIEWS = {
  battle: { label: '故事', icon: '故', roles: ['gm', 'player'] },
  setup: { label: '战斗编成', icon: '编', roles: ['gm', 'player'], render: renderSetupView },
  roster: { label: '阵容', icon: '阵', roles: ['gm', 'player'], render: renderRosterView },
  pages: { label: '书页', icon: '页', roles: ['gm', 'player'], render: renderPagesView },
  manager: { label: '干预', icon: '干', roles: ['gm', 'player'], render: renderManagerView },
  settings: { label: '设置', icon: '设', roles: ['gm', 'player'], render: renderSettingsView },
};

const navBadgeEls = new Map();

function renderNav() {
  if (!dom.navList) return;
  clearNode(dom.navList);
  navBadgeEls.clear();
  for (const key of Object.keys(VIEWS)) {
    const view = VIEWS[key];
    if (state.role && !view.roles.includes(state.role)) continue;
    const badge = el('span', { class: 'nav-badge hidden' }, '0');
    navBadgeEls.set(key, badge);
    const item = el('button', {
      class: 'nav-item' + (state.view === key ? ' active' : ''),
      type: 'button',
      onclick: () => showView(key),
    },
      el('span', { class: 'nav-icon' }, view.icon),
      el('span', { class: 'nav-label' }, view.label),
      badge);
    dom.navList.append(item);
  }
  renderNavBadges();
}

function renderNavBadges() {
  const offers = state.overview && Array.isArray(state.overview.page_offers)
    ? state.overview.page_offers.length : 0;
  const badge = navBadgeEls.get('pages');
  if (badge) {
    badge.textContent = String(offers);
    badge.classList.toggle('hidden', offers <= 0);
  }
}

function closeSidebars() {
  if (dom.appView) {
    dom.appView.classList.remove('show-nav');
    dom.appView.classList.remove('show-status');
  }
  if (dom.sidebarBackdrop) dom.sidebarBackdrop.classList.add('hidden');
}

function showView(key) {
  const view = VIEWS[key];
  if (!view) return;
  if (state.role && !view.roles.includes(state.role)) return;
  state.view = key;
  state.viewToken += 1;
  closeSidebars();
  if (dom.navList) {
    const items = dom.navList.querySelectorAll('.nav-item');
    const keys = Object.keys(VIEWS).filter((k) => !state.role || VIEWS[k].roles.includes(state.role));
    items.forEach((item, index) => {
      item.classList.toggle('active', keys[index] === key);
    });
  }
  const isBattle = key === 'battle';
  if (dom.logView) dom.logView.classList.toggle('hidden', !isBattle);
  if (dom.pageView) dom.pageView.classList.toggle('hidden', isBattle);
  if (dom.chatBar) dom.chatBar.classList.toggle('hidden', !isBattle);
  if (isBattle) {
    scheduleChatRead();
    maybeOpenPageOffers();
  }
  renderChannelHeader();
  renderBattleStrip();
  renderNoticeBanner();
  renderActionBar();
  if (isBattle) {
    state.pinned = true;
    scrollLogToBottom(true);
  } else {
    renderCurrentView();
  }
}

async function renderCurrentView() {
  const key = state.view;
  const view = VIEWS[key];
  if (!view || !view.render || !dom.pageScroll) return;
  const token = ++state.viewToken;
  clearNode(dom.pageScroll);
  dom.pageScroll.append(el('div', { class: 'page-loading' }, '读取中…'));
  try {
    const content = await view.render();
    if (token !== state.viewToken || state.view !== key) return;
    clearNode(dom.pageScroll);
    if (content) dom.pageScroll.append(content);
  } catch (err) {
    if (err instanceof ApiError && err.status === 401) return;
    if (token !== state.viewToken || state.view !== key) return;
    clearNode(dom.pageScroll);
    dom.pageScroll.append(el('div', { class: 'page-error' },
      el('div', null, (err && err.message) || '读取失败'),
      el('button', { class: 'btn ghost', type: 'button', onclick: () => renderCurrentView() }, '重试')));
  }
}

/* ================= 登录 / 登出 ================= */

function setRole(role) {
  state.role = role;
  if (dom.roleBadge) {
    dom.roleBadge.textContent = role === 'gm' ? '管理人' : '玩家';
    dom.roleBadge.classList.remove('gm', 'player');
    dom.roleBadge.classList.add(role === 'gm' ? 'gm' : 'player');
  }
  if (dom.userBarText) {
    dom.userBarText.textContent = role === 'gm' ? '拥有全部管理权限' : '战斗查看与我方行动';
  }
  if (dom.chatInput) {
    dom.chatInput.placeholder = role === 'gm'
      ? '输入消息…（角色名：“内容” 以 NPC 发言，其余视为旁白）'
      : '输入消息…';
  }
}

function enterLogin() {
  state.loggedIn = false;
  state.role = null;
  closeSSE();
  closeModal();
  closeSidebars();
  if (dom.appView) dom.appView.classList.add('hidden');
  if (dom.loginView) dom.loginView.classList.remove('hidden');
  if (dom.loginKey) {
    dom.loginKey.value = '';
    setTimeout(() => { if (dom.loginKey) dom.loginKey.focus(); }, 60);
  }
}

async function enterApp(role) {
  setRole(role === 'gm' ? 'gm' : 'player');
  state.loggedIn = true;
  state.view = 'battle';
  if (dom.loginView) dom.loginView.classList.add('hidden');
  if (dom.appView) dom.appView.classList.remove('hidden');
  renderNav();
  resetLog();
  if (dom.logList) dom.logList.append(logEmptyNote());
  connectSSE(); // open 回调里会拉取合并历史（战斗播报+聊天）
  await refreshOverview();
  showView('battle');
}

/* ================= 初始化 ================= */

function bindStaticHandlers() {
  if (dom.chatSend) dom.chatSend.addEventListener('click', sendChat);
  if (dom.chatInput) {
    dom.chatInput.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault();
        sendChat();
      }
    });
  }
  if (dom.chatSearchBtn) dom.chatSearchBtn.addEventListener('click', openChatSearch);
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') scheduleChatRead();
  });
  if (dom.loginCard) {
    dom.loginCard.addEventListener('submit', async (event) => {
      event.preventDefault();
      if (state.busy) return;
      const key = dom.loginKey ? dom.loginKey.value.trim() : '';
      if (!key) {
        toast('请输入访问密钥。', 'error');
        if (dom.loginCard) {
          dom.loginCard.classList.remove('shake');
          void dom.loginCard.offsetWidth;
          dom.loginCard.classList.add('shake');
        }
        return;
      }
      state.busy = true;
      if (dom.loginSubmit) { dom.loginSubmit.disabled = true; dom.loginSubmit.classList.add('is-busy'); }
      try {
        const data = await api('/api/login', { method: 'POST', body: { key } });
        await enterApp(data && data.role);
      } catch (err) {
        toast((err && err.message) || '登录失败', 'error');
        if (dom.loginCard) {
          dom.loginCard.classList.remove('shake');
          void dom.loginCard.offsetWidth;
          dom.loginCard.classList.add('shake');
        }
      } finally {
        state.busy = false;
        if (dom.loginSubmit) { dom.loginSubmit.disabled = false; dom.loginSubmit.classList.remove('is-busy'); }
      }
    });
  }

  if (dom.logoutBtn) {
    dom.logoutBtn.addEventListener('click', () => withBusy(dom.logoutBtn, async () => {
      try { await api('/api/logout', { method: 'POST', body: {} }); } catch (err) { /* 忽略 */ }
      enterLogin();
      toast('已登出。', 'info');
    }));
  }

  if (dom.jumpLatest) {
    dom.jumpLatest.addEventListener('click', () => scrollLogToBottom(true));
  }

  if (dom.logScroll) {
    dom.logScroll.addEventListener('scroll', () => {
      const scroller = dom.logScroll;
      const pinned = scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight < 48;
      state.pinned = pinned;
      if (dom.jumpLatest) dom.jumpLatest.classList.toggle('hidden', pinned);
    });
  }

  if (dom.toggleNav) {
    dom.toggleNav.addEventListener('click', () => {
      if (!dom.appView) return;
      dom.appView.classList.toggle('show-nav');
      dom.appView.classList.remove('show-status');
      if (dom.sidebarBackdrop) {
        dom.sidebarBackdrop.classList.toggle('hidden', !dom.appView.classList.contains('show-nav'));
      }
    });
  }
  if (dom.toggleStatus) {
    dom.toggleStatus.addEventListener('click', () => {
      if (!dom.appView) return;
      dom.appView.classList.toggle('show-status');
      dom.appView.classList.remove('show-nav');
      if (dom.sidebarBackdrop) {
        dom.sidebarBackdrop.classList.toggle('hidden', !dom.appView.classList.contains('show-status'));
      }
    });
  }
  if (dom.sidebarBackdrop) {
    dom.sidebarBackdrop.addEventListener('click', closeSidebars);
  }

  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') closeModal();
  });

  window.addEventListener('beforeunload', () => closeSSE());
}

async function init() {
  bindStaticHandlers();
  try {
    const session = await api('/api/session');
    if (session && (session.role === 'gm' || session.role === 'player')) {
      await enterApp(session.role);
      return;
    }
  } catch (err) { /* 未登录 → 落到登录页 */ }
  enterLogin();
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', () => { init(); });
} else {
  init();
}

})();
