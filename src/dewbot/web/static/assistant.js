(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  let privacy = true, epoch = null, configured = false, digest = null, generation = 0, busy = false;
  let messageCursor = null, noteCursor = null, active = false;
  function invalidate() {
    generation++; digest = null;
    $('preview-text').textContent = $('draft').textContent = $('counts').textContent = '';
    buttons();
  }
  function buttons() {
    $('preview').disabled = privacy || busy;
    $('export').disabled = privacy || busy || !digest;
    $('generate').disabled = privacy || busy || !digest || !configured;
  }
  function clear() {
    active = false; privacy = true; epoch = null; invalidate();
    $('desk').hidden = true; $('messages').replaceChildren(); $('notes').replaceChildren(); $('instruction').value = '';
  }
  async function api(path, method = 'GET', body) {
    const options = {method, cache:'no-store'};
    if (body !== undefined) { options.headers = {'Content-Type':'application/json'}; options.body = JSON.stringify(body); }
    const response = await fetch(path, options);
    const result = await response.json();
    if (!response.ok) {
      if ([401,403].includes(response.status)) clear();
      throw new Error(result.error || '操作失败，请刷新重试。');
    }
    return result;
  }
  function applyPrivacy(value) {
    if (epoch !== value.epoch) invalidate();
    epoch = value.epoch; privacy = !!value.enabled;
    if ('api_configured' in value) configured = value.api_configured;
    $('privacy').textContent = privacy ? '隐私模式：开 · 点击关闭' : '隐私模式：关 · 点击开启';
    $('privacy').setAttribute('aria-pressed', String(privacy));
    $('provider').textContent = configured ? '模型 API 已配置' : '模型 API 未配置，仍可导出材料';
    buttons();
  }
  function selected(container) {
    return Array.from($(container).querySelectorAll('input:checked'), x => Number(x.value));
  }
  function payload() {
    return {instruction:$('instruction').value, message_ids:selected('messages'), note_ids:selected('notes'), digest};
  }
  function choices(container, rows, kind, more) {
    if (!more) $(container).replaceChildren();
    for (const row of rows) {
      const label = document.createElement('label'); label.className = 'check selection';
      const box = document.createElement('input'); box.type = 'checkbox'; box.value = row.id;
      box.addEventListener('change', invalidate);
      const text = document.createElement('span');
      text.textContent = '#' + row.id + ' ' + (kind === 'message' ? (row.speaker || '旁白') + '：' + row.content : row.title + '\n' + row.body);
      label.append(box, text); $(container).append(label);
    }
    if (!$(container).children.length) $(container).textContent = '暂无可选材料。';
  }
  async function loadMessages(more = false) {
    const current = generation;
    const result = await api('/api/assistant/messages' + (more && messageCursor ? '?before_id=' + messageCursor : ''));
    if (!active || current !== generation) return;
    choices('messages', result.messages, 'message', more); messageCursor = result.next_before_id;
    $('more-messages').hidden = !messageCursor;
  }
  async function loadNotes(more = false) {
    const current = generation;
    const result = await api('/api/assistant/notes' + (more && noteCursor ? '?before_id=' + noteCursor : ''));
    if (!active || current !== generation) return;
    choices('notes', result.entries, 'note', more); noteCursor = result.next_before_id;
    $('more-notes').hidden = !noteCursor;
  }
  async function refresh() {
    invalidate(); await Promise.all([loadMessages(), loadNotes()]);
  }
  async function check() {
    const session = await api('/api/session');
    if (session.role !== 'gm') { clear(); throw new Error('AI 写作仅向管理人开放。'); }
    applyPrivacy(await api('/api/assistant/privacy'));
    const first = !active; active = true; $('desk').hidden = false;
    if (first) { $('notice').textContent = ''; await refresh(); }
  }
  function action(id, fn) {
    $(id).addEventListener('click', async () => {
      try { $('notice').textContent = ''; await fn(); }
      catch (err) { $('notice').textContent = err.message; }
    });
  }
  action('privacy', async () => { applyPrivacy(await api('/api/assistant/privacy', 'PUT', {enabled:!privacy})); });
  action('refresh', refresh);
  action('more-messages', () => loadMessages(true));
  action('more-notes', () => loadNotes(true));
  action('protect', async () => {
    await api('/api/assistant/protect', 'POST', {message_ids:selected('messages')}); await check(); await refresh();
  });
  $('instruction').addEventListener('input', invalidate);
  action('preview', async () => {
    if (busy) return;
    invalidate(); const current = generation; busy = true; buttons();
    try {
      const result = await api('/api/assistant/preview', 'POST', payload());
      if (current !== generation) return;
      digest = result.digest; $('preview-text').textContent = result.prompt; $('preview-box').open = true;
      $('counts').textContent = result.message_count + ' 条聊天 · ' + result.note_count + ' 条笔记。请检查上面的完整材料后再发送或导出。';
    } finally { busy = false; buttons(); }
  });
  action('export', async () => {
    const current = generation;
    const result = await api('/api/assistant/export', 'POST', payload());
    if (current !== generation || privacy) return;
    const url = URL.createObjectURL(new Blob([result.prompt], {type:'text/plain;charset=utf-8'}));
    const link = document.createElement('a'); link.href = url; link.download = 'writing-context.txt'; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  });
  action('generate', async () => {
    if (busy) return;
    const current = generation; busy = true; buttons(); $('draft').textContent = '正在生成…';
    try {
      const result = await api('/api/assistant/draft', 'POST', payload());
      if (current === generation && !privacy) $('draft').textContent = result.draft;
    } catch (err) { $('draft').textContent = ''; throw err; }
    finally { busy = false; buttons(); }
  });
  async function sync() {try {await check();} catch (err) {clear(); $('notice').textContent = err.message;}}
  window.addEventListener('focus', sync);
  window.addEventListener('pagehide', clear);
  window.addEventListener('pageshow', e => {if (e.persisted) sync();});
  setInterval(() => {if (document.visibilityState === 'visible') sync();}, 5000);
  sync();
})();
