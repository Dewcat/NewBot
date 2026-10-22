const assert = require('node:assert/strict');
const fs = require('node:fs');
const source = fs.readFileSync('src/dewbot/web/static/app.js', 'utf8');
const start = source.indexOf('  const defended = ');
const end = source.indexOf('  for (const intent of battle.enemy_intents', start);
const makeDefended = new Function('battle', 'positions', source.slice(start, end) + ';return defended;');
const positions = new Map([[2, {unit: {current_hp: 100, is_staggered: false}}]]);
const selected = {id: 11, redirect: {actor_id: 2}};
const other = {id: 12, redirect: null};
for (const kind of ['INTERCEPT', 'MEET']) {
  const defense = {actor_id: 2, active: true, kind, intent_id: 11};
  const responds = makeDefended({defenses: [defense]}, positions);
  assert.equal(responds(2, selected), true);
  assert.equal(responds(2, other), false);
  assert.equal(responds(2), false);
  assert.equal(responds(2, {id: 11, redirect: {actor_id: 3}}), false);
  defense.active = false;
  assert.equal(responds(2, selected), false);
}
for (const kind of ['GUARD', 'EVADE']) {
  const responds = makeDefended({defenses: [{actor_id: 2, active: true, kind}]}, positions);
  assert.equal(responds(2, selected), true);
  assert.equal(responds(2, other), true);
}
console.log('Bound defense arrows: only the selected intent responds; replaced and consumed orders do not.');

// Render the real map to check arrow visibility across preparation and stagger.
class Node {
  constructor(tag) {
    this.tag = tag; this.attrs = {}; this.children = []; this.style = {setProperty() {}}; this.events = {};
    this.classList = {toggle:(name,on)=>{const set=new Set(String(this.attrs.class||'').split(' '));if(on)set.add(name);else set.delete(name);this.attrs.class=[...set].join(' ');},remove:name=>this.classList.toggle(name,false)};
  }
  setAttribute(key, value) { this.attrs[key] = value; }
  append(...nodes) { this.children.push(...nodes); }
  addEventListener(name, handler) { this.events[name] = handler; }
}
const document = {createElementNS: (_, tag) => new Node(tag)};
const dom = {battleStrip: new Node('div')};
const el = (tag, attrs, ...children) => { const node = new Node(tag); node.attrs = attrs || {}; node.append(...children); return node; };
const render = new Function('document', 'dom', 'el', 'enemyIntentLabel',
  source.slice(source.indexOf('function renderTargetMap('), source.indexOf('function renderBattleStrip(')) + ';return renderTargetMap;'
)(document, dom, el, () => '木人 · 轻挥 → 珏');
const unit = (id, faction) => ({id, faction, name:'角色', current_hp:100, max_hp:100, current_stagger:50, max_stagger:50});
const enemy = unit(1, 'ENEMY'), friendly = unit(2, 'FRIENDLY');
const intent = {id:11, actor_id:1, status:'PENDING', attack_target_ids:[2]};
const battle = {phase:'ENEMY_PLANNING', enemy_intents:[intent]};
const nodes = node => [node, ...node.children.filter(child => child instanceof Node).flatMap(nodes)];
const arrowCount = () => {
  dom.battleStrip.children = [];
  render(battle, [enemy], [friendly]);
  return nodes(dom.battleStrip).filter(node => String(node.attrs.class).startsWith('target-edge ')).length;
};
assert.equal(arrowCount(), 0);
battle.phase = 'FRIENDLY_ACTION';
assert.equal(arrowCount(), 1);
intent.disabled = true;
assert.equal(arrowCount(), 0);
intent.disabled = false;
enemy.is_staggered = true;
assert.equal(arrowCount(), 0);
enemy.is_staggered = false;
enemy.current_hp = 0;
assert.equal(arrowCount(), 0);
console.log('Enemy arrows stay hidden during preparation and disappear when the attacker is staggered or defeated.');

enemy.current_hp = 100;
intent.attack_target_ids = [1,2];
intent.area_target_ids = [1,2];
battle.defenses = [{actor_id:2, kind:'EVADE', active:true}];
arrowCount();
let all = nodes(dom.battleStrip);
const area = all.find(node=>node.attrs.class==='target-area red');
assert(area);
assert(all.some(node=>node.textContent==='无差别攻击 · 2人'));
assert.equal(all.filter(node=>node.attrs.class==='area-unit-outline').length, 2);
const summary = area.children.find(node=>node.attrs.class==='area-summary');
const details = area.children.find(node=>node.attrs.class==='area-target-links');
assert.equal(nodes(summary).filter(node=>String(node.attrs.class).startsWith('target-edge ')).length,1);
assert.equal(nodes(details).filter(node=>node.attrs.class==='target-edge yellow').length,1);
assert.equal(area.attrs['aria-expanded'],'false');
area.events.pointerenter();assert.equal(area.attrs['aria-expanded'],'true');
area.events.pointerleave();assert.equal(area.attrs['aria-expanded'],'false');
summary.events.click();area.events.pointerleave();assert.equal(area.attrs['aria-expanded'],'true');
summary.events.click();assert.equal(area.attrs['aria-expanded'],'false');
intent.area_target_ids = [];
arrowCount();assert(!nodes(dom.battleStrip).some(node=>String(node.attrs.class).startsWith('target-area ')));
battle.enemy_intents=[];
battle.friendly_attacks=[{actor_id:2,skill_name:'群攻',target_ids:[1],area_target_ids:[1]}];
arrowCount();assert(nodes(dom.battleStrip).some(node=>node.attrs.class==='target-area blue'));
console.log('Area attacks condense to one solid summary, include both factions, expand defenses and pin on click; equal selected targets stay separate.');
