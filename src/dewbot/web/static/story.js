(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const states = {draft:'待定',confirmed:'已确认',withdrawn:'已撤回'};
  const kinds = {lore:'设定',character:'角色',event:'事件',clue:'线索'};
  let role = null, editing = null, next = null, generation = 0, busy = false;
  function node(tag, text, className) {
    const n = document.createElement(tag);
    if (text !== undefined) n.textContent = text;
    if (className) n.className = className;
    return n;
  }
  async function api(path, method = 'GET', body) {
    const options = {method, cache:'no-store'};
    if (body !== undefined) { options.headers = {'Content-Type':'application/json'}; options.body = JSON.stringify(body); }
    const response = await fetch(path, options);
    const data = await response.json();
    if (!response.ok) {
      if (response.status === 401) clearPrivateView();
      throw new Error(data.error || '读取失败，请刷新重试。');
    }
    return data;
  }
  function clearPrivateView() {
    generation++; role = null; editing = null;
    $('entries').replaceChildren(); $('controls').hidden = true; $('more').hidden = true;
    $('editor').close(); $('edit-form').reset();
    $('audience').textContent = '请先返回主界面登录。';
  }
  function openEditor(item) {
    editing = item || null;
    const form = $('edit-form'); form.reset(); $('edit-error').textContent = '';
    for (const key of ['title','kind','world','chapter','status','visibility','body','source']) {
      if (item) form.elements.namedItem(key).value = item[key] || '';
    }
    $('edit-heading').textContent = item ? '编辑条目 · #' + item.id : '新增条目';
    $('editor').showModal();
    form.elements.namedItem('title').focus();
  }
  function card(item) {
    const box = node('article');
    box.append(node('h2', item.title));
    box.append(node('div', '#' + item.id + ' · ' + item.world + (item.chapter ? ' · ' + item.chapter : ''), 'meta'));
    box.append(node('span', kinds[item.kind], 'badge'), node('span', states[item.status], 'badge'));
    if (role === 'gm') box.append(node('span', item.visibility === 'public' ? '玩家可见' : '仅管理人', 'badge'));
    box.append(node('p', item.body, 'body'));
    if (role === 'gm') {
      if (item.source) box.append(node('p', '来源备注：' + item.source, 'source'));
      const edit = node('button', '编辑'); edit.addEventListener('click', () => openEditor(item));
      box.append(edit);
      const history = node('details'); history.append(node('summary', '管理人修订记录'));
      let loaded = false;
      history.addEventListener('toggle', async () => {
        if (!history.open || loaded) return;
        loaded = true;
        const current = generation;
        try {
          const rows = await api('/api/story/entries/' + item.id + '/history');
          if (current !== generation || role !== 'gm') return;
          for (const row of rows) {
            const version = node('details');
            version.append(node('summary', '版本 ' + row.revision + ' · ' + row.updated_at + ' · ' + states[row.status]));
            version.append(node('p', row.title + '\n' + row.body, 'body'));
            history.append(version);
          }
        } catch (err) { loaded = false; $('notice').textContent = err.message; }
      });
      box.append(history);
    }
    return box;
  }
  async function load(more = false) {
    const current = ++generation;
    const params = new URLSearchParams(new FormData($('search-form')));
    if (role !== 'gm') params.delete('status');
    if (more && next) params.set('before_id', next);
    $('more').disabled = true; $('notice').textContent = '';
    try {
      const data = await api('/api/story/entries?' + params);
      if (current !== generation) return;
      if (!more) $('entries').replaceChildren();
      for (const item of data.entries) $('entries').append(card(item));
      if (!more && !data.entries.length) $('entries').append(node('p', '暂无匹配条目。'));
      next = data.next_before_id; $('more').hidden = !next;
    } catch (err) { if (current === generation || !role) $('notice').textContent = err.message; }
    finally { $('more').disabled = false; }
  }
  async function boot() {
    try {
      const session = await api('/api/session');
      if (!session.story_enabled) {
        clearPrivateView(); $('audience').textContent = '故事档案尚未开启。'; return;
      }
      const changed = role !== session.role;
      if (changed) clearPrivateView();
      role = session.role;
      $('audience').textContent = role === 'gm'
        ? '管理人视图：保存设定、线索与事件，决定哪些内容已经可以向玩家揭晓。'
        : '玩家视图：这里收录已确认并向你公开的故事档案。';
      $('controls').hidden = false;
      $('create').hidden = $('status-filter-label').hidden = role !== 'gm';
      if (changed) await load();
    } catch (err) { clearPrivateView(); $('notice').textContent = err.message; }
  }
  $('search-form').addEventListener('submit', e => {e.preventDefault(); load();});
  $('create').addEventListener('click', () => openEditor(null));
  $('cancel').addEventListener('click', () => {if (!busy) $('editor').close();});
  $('editor').addEventListener('cancel', e => {if (busy) e.preventDefault();});
  $('more').addEventListener('click', () => load(true));
  $('edit-form').addEventListener('submit', async e => {
    e.preventDefault(); if (busy) return;
    const data = Object.fromEntries(new FormData(e.target));
    if (editing) data.revision = editing.revision;
    busy = true; $('save').disabled = $('cancel').disabled = true; $('edit-error').textContent = '';
    try {
      await api('/api/story/entries' + (editing ? '/' + editing.id : ''), editing ? 'PUT' : 'POST', data);
      $('editor').close(); await load();
    } catch (err) { $('edit-error').textContent = err.message; }
    finally { busy = false; $('save').disabled = $('cancel').disabled = false; }
  });
  $('export').addEventListener('click', async () => {
    try {
      const data = await api('/api/story/export');
      const url = URL.createObjectURL(new Blob([JSON.stringify(data,null,2)], {type:'application/json'}));
      const link = node('a'); link.href = url; link.download = 'story-archive-' + data.audience + '.json';
      link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (err) { $('notice').textContent = err.message; }
  });
  window.addEventListener('focus', boot);
  window.addEventListener('pageshow', e => {if (e.persisted) {clearPrivateView(); boot();}});
  boot();
})();
