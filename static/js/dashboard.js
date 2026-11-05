(() => {
const $ = (s, r = document) => r.querySelector(s);
const csrf = $('meta[name=csrf]').content;
const TZ = document.body.dataset.tz || 'UTC';
const page = document.body.dataset.page;
async function api(method, url, body) {
  const opt = {method, headers: {'X-CSRF-Token': csrf, Accept: 'application/json'}, credentials: 'same-origin'};
  if (body !== undefined) {
    opt.headers['Content-Type'] = 'application/json';
    opt.body = JSON.stringify(body);
  }
  let r;
  try {
    r = await fetch(url, opt);
  } catch (e) {
    throw new Error('Server unreachable');
  }
  if (r.status === 401) {
    location.href = '/login';
    throw new Error('Session expired');
  }
  let data = {};
  try {
    data = await r.json();
  } catch (e) {}
  if (!r.ok || data.ok === false) {
    const err = new Error(data.error || 'Request failed (' + r.status + ')');
    err.details = data.errors;
    throw err;
  }
  return data;
}
function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === 'class') el.className = v;
    else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
    else if (k === 'text') el.textContent = v;
    else el.setAttribute(k, v === true ? '' : v);
  }
  for (const kid of kids.flat()) {
    if (kid === null || kid === undefined || kid === false) continue;
    el.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
  }
  return el;
}
let toastTimer;
function toast(msg, bad) {
  const t = $('#toast');
  t.textContent = msg;
  t.className = 'toast' + (bad ? ' bad' : '');
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.hidden = true; }, 4000);
}
function fmt(iso) {
  if (!iso) return '–';
  try {
    return new Date(iso).toLocaleString([], {timeZone: TZ, year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit'});
  } catch (e) {
    return iso;
  }
}
async function act(fn, okMsg) {
  try {
    const d = await fn();
    toast(d && d.message ? d.message : okMsg || 'Done');
    return d;
  } catch (e) {
    toast(e.message, true);
    return null;
  }
}
const STATUS = {none: 'not started', pending: 'waiting', generating: 'writing', queued: 'waiting', running: 'running', publishing: 'posting', published: 'posted', approved: 'approved', draft: 'draft ready', liked: 'liked', failed: 'failed', verification_required: 'needs your check', done: 'finished', cancelled: 'removed', skipped_insufficient_text: 'too little text', ok: 'OK', up: 'online', down: 'offline', auth_required: 'login needed', paused: 'paused', recovering: 'recovering', stopped: 'stopped'};
function nice(v) {
  return STATUS[v] || String(v ?? '–').replace(/_/g, ' ');
}
function pillState(st) {
  if (!st) return ['Checking…', 'warn'];
  if (!st.worker_alive) return ['Assistant stopped', 'bad'];
  if (st.monitor_state === 'recovering') return ['Recovering', 'warn'];
  if (st.browser_status !== 'running') return ['Browser ' + nice(st.browser_status), 'bad'];
  if (st.auth_status !== 'ok') return ['LinkedIn login needed', 'warn'];
  if (st.ai_status !== 'up') return ['AI service ' + nice(st.ai_status), 'warn'];
  if (st.monitor_state === 'paused') return ['Paused', 'warn'];
  return ['Running', 'ok'];
}
async function refreshStatus() {
  try {
    const d = await api('GET', '/api/stats');
    const [text, cls] = pillState(d.status);
    const pill = $('#health-pill');
    pill.textContent = text;
    pill.className = 'pill pill-' + cls;
    syncSwitches(d.config);
    try { sessionStorage.setItem('pill', JSON.stringify([text, cls])); } catch (e) {}
    if (page === 'dashboard') {
      document.querySelectorAll('[data-stat]').forEach(n => { n.textContent = d.stats[n.dataset.stat] ?? 0; });
      document.querySelectorAll('[data-limit]').forEach(n => { const l = d.config[n.dataset.limit]; n.textContent = l ? ' / ' + l : ' (no limit)'; });
      [['#m-likes', 'likes_24h', 'daily_like_limit'], ['#m-comments', 'comments_24h', 'daily_comment_limit'], ['#m-connects', 'connects_24h', 'daily_connect_limit'], ['#m-ai', 'ai_1h', 'ai_hourly_limit'], ['#m-queue', 'queued_jobs', 'max_queue'], ['#m-backlog', 'ai_backlog', 'poll_backlog_limit']].forEach(([sel, used, lim]) => { const pct = d.config[lim] ? Math.min(100, d.stats[used] / d.config[lim] * 100) : 0; $(sel).style.width = pct + '%'; $(sel).className = pct >= 100 ? 'bad' : pct >= 80 ? 'warn' : ''; });
      const s = d.status;
      $('#st-monitor').textContent = nice(s.worker_alive ? s.monitor_state : 'stopped');
      $('#st-browser').textContent = nice(s.browser_status);
      $('#st-auth').textContent = nice(s.auth_status);
      $('#st-ai').textContent = nice(s.ai_status);
      $('#st-last').textContent = fmt(s.last_poll_ok);
      const u = s.ai_usage || {};
      const uok = u.status === 'ok';
      $('#u-24h').textContent = uok ? u.tokens_24h.toLocaleString() : '–';
      $('#u-30d').textContent = uok ? u.tokens_30d.toLocaleString() : '–';
      $('#u-left').textContent = !uok ? '–' : u.session_left != null ? Math.round(u.session_left) + '% session · ' + Math.round(u.weekly_left) + '% week' : u.left_usd != null ? '$' + u.left_usd.toFixed(2) + ' of $' + u.allowance_usd.toFixed(2) : '–';
      $('#u-reset').textContent = uok ? fmt(u.session_resets || u.until) : '–';
      $('#u-msg').textContent = uok ? '' : u.message || 'Waiting for usage data';
      $('#st-next').textContent = d.config.monitoring_enabled ? fmt(s.next_poll_at) : 'paused';
      const msgs = [s.browser_error, s.auth_status !== 'ok' ? s.auth_message : '', s.ai_status !== 'up' ? s.ai_message : '', s.last_error].filter(Boolean);
      $('#st-msg').textContent = msgs.join(' · ');
    }
    if (page === 'posts') {
      state.autoAi = !!d.config.auto_ai;
      $('#btn-autoai').textContent = 'Auto-write drafts: ' + (state.autoAi ? 'On' : 'Off');
      $('#btn-autoai').classList.toggle('on', state.autoAi);
    }
  } catch (e) {
    const pill = $('#health-pill');
    pill.textContent = 'Offline';
    pill.className = 'pill pill-bad';
  }
}
function syncSwitches(c) {
  document.querySelectorAll('.sw[data-sw]').forEach(b => {
    const on = !!c[b.dataset.sw + '_enabled'];
    b.classList.toggle('on', on);
    b.classList.toggle('off', !on);
    b.querySelector('.sw-state').textContent = on ? 'On' : 'Paused';
  });
}
function initSwitches() {
  document.querySelectorAll('.sw[data-sw]').forEach(b => {
    b.onclick = () => act(() => api('POST', '/api/feature/' + b.dataset.sw + '/' + (b.classList.contains('on') ? 'pause' : 'resume'))).then(refreshStatus);
  });
}
async function bulk(url, action, ids, size) {
  let done = 0;
  const errors = [];
  for (let i = 0; i < ids.length; i += size) {
    const d = await api('POST', url, {action, ids: ids.slice(i, i + size)});
    done += d.done;
    errors.push(...(d.errors || []));
  }
  return {done, errors, message: done + ' of ' + ids.length + ' updated'};
}
function hint(sel, out) {
  const sync = () => { out.textContent = sel.selectedOptions[0].dataset.hint || ''; };
  sel.addEventListener('change', sync);
  sync();
}
function initDashboard() {
  $('#btn-browser').onclick = () => {
    if (confirm('Restart the browser now?')) act(() => api('POST', '/api/browser/restart'));
  };
}
const state = {filter: 'all', sort: 'recent', q: '', page: 1, per: 30, total: 0, selected: new Set()};
function pCount() {
  $('#count').textContent = state.total + ' post(s)' + (state.selected.size ? ' · ' + state.selected.size + ' selected' : '');
}
function badge(text, cls) {
  return h('span', {class: 'badge ' + (cls || '')}, text);
}
function statusClass(v) {
  if (['published', 'liked', 'done'].includes(v)) return 'ok';
  if (['failed'].includes(v)) return 'bad';
  if (['verification_required', 'queued', 'publishing', 'pending', 'generating', 'draft', 'approved'].includes(v)) return 'warn';
  return '';
}
function postCard(p) {
  const chk = h('input', {type: 'checkbox', onchange: e => { e.target.checked ? state.selected.add(p.id) : state.selected.delete(p.id); pCount(); }});
  chk.checked = state.selected.has(p.id);
  const run = (method, path, body, msg) => async () => {
    await act(() => api(method, '/api/posts/' + p.id + path, body), msg);
    loadPosts();
  };
  const btns = [
    h('a', {class: 'btn btn-sm', href: p.url, target: '_blank', rel: 'noopener noreferrer', title: 'Open this post on LinkedIn.'}, 'Open post'),
    h('button', {class: 'btn btn-sm', title: 'See the full post and edit the comment.', onclick: () => openDetail(p.id)}, 'Details / edit'),
    h('button', {class: 'btn btn-sm', title: 'Ask the AI to write a comment draft.', onclick: run('POST', '/generate')}, p.draft ? 'Regenerate' : 'Generate'),
    p.comment && ['draft', 'approved', 'failed', 'none'].includes(p.comment_status) ? h('button', {class: 'btn btn-sm', title: 'Approve this comment without publishing it.', onclick: run('POST', '/approve')}, 'Approve') : null,
    p.comment && ['draft', 'approved', 'failed', 'none'].includes(p.comment_status) ? h('button', {class: 'btn btn-sm btn-primary', title: 'Queue this comment to be posted on LinkedIn.', onclick: () => { if (confirm('Publish this comment to LinkedIn?')) run('POST', '/publish')(); }}, 'Publish') : null,
    p.like_status !== 'liked' ? h('button', {class: 'btn btn-sm', title: 'Queue a like for this post.', onclick: run('POST', '/like')}, 'Like') : null,
    ['failed', 'verification_required'].includes(p.comment_status) || ['failed', 'verification_required'].includes(p.like_status) || p.ai_status === 'failed' ? h('button', {class: 'btn btn-sm', title: 'Retry the failed or unverified work now.', onclick: run('POST', '/retry')}, 'Retry') : null,
    p.comment_status === 'verification_required' || p.like_status === 'verification_required' ? h('button', {class: 'btn btn-sm btn-primary', title: 'Confirm it went through on LinkedIn and mark it done.', onclick: () => { if (confirm('Was this really done on LinkedIn?')) run('POST', '/confirm')(); }}, 'Mark as done') : null,
    p.skipped ? h('button', {class: 'btn btn-sm', title: 'Bring this post back so the assistant handles it again.', onclick: run('POST', '/reset')}, 'Un-skip') : h('button', {class: 'btn btn-sm btn-danger', title: 'Ignore this post: no automatic likes or comments.', onclick: () => { if (confirm('Skip this post?')) run('POST', '/skip')(); }}, 'Skip')
  ];
  return h('div', {class: 'post'},
    chk,
    h('div', {class: 'post-main'},
      h('h3', {}, p.author_name || 'Unknown author', p.title ? ' · ' + p.title : ''),
      h('div', {class: 'meta'}, 'Posted ' + fmt(p.published_at) + ' · Found ' + fmt(p.discovered_at)),
      h('div', {class: 'preview'}, p.preview || '(no text)'),
      h('div', {class: 'badges'},
        badge('AI draft: ' + nice(p.ai_status), statusClass(p.ai_status)),
        badge('Comment: ' + nice(p.comment_status), statusClass(p.comment_status)),
        badge('Like: ' + nice(p.like_status), statusClass(p.like_status)),
        p.skipped ? badge('Skipped' + (p.skip_reason ? ': ' + p.skip_reason : ''), 'warn') : null,
        p.retry_count ? badge('Tried again ' + p.retry_count + ' time(s)' + (p.next_retry_at ? ' · next try ' + fmt(p.next_retry_at) : ''), 'warn') : null),
      p.comment ? h('div', {class: 'draft'}, p.comment) : null,
      p.last_error ? h('div', {class: 'err'}, p.last_error) : null,
      h('div', {class: 'row-actions'}, btns)));
}
async function loadPosts() {
  try {
    const qs = new URLSearchParams({filter: state.filter, sort: state.sort, q: state.q, page: state.page, per_page: state.per});
    const d = await api('GET', '/api/posts?' + qs);
    state.total = d.total;
    const box = $('#posts');
    box.replaceChildren(...(d.posts.length ? d.posts.map(postCard) : [h('p', {class: 'muted'}, 'No posts match these filters.')]));
    const pages = Math.max(1, Math.ceil(d.total / state.per));
    $('#page-info').textContent = 'Page ' + state.page + ' of ' + pages;
    $('#select-page').textContent = 'Select page (' + d.posts.length + ')';
    pCount();
    $('#prev').disabled = state.page <= 1;
    $('#next').disabled = state.page >= pages;
  } catch (e) {
    toast(e.message, true);
  }
}
async function openDetail(id) {
  let d;
  try {
    d = await api('GET', '/api/posts/' + id);
  } catch (e) {
    toast(e.message, true);
    return;
  }
  const p = d.post;
  const dlg = $('#detail');
  const ta = h('textarea', {maxlength: '1250'});
  ta.value = p.comment || '';
  const editable = !['published', 'publishing', 'queued', 'verification_required'].includes(p.comment_status);
  ta.disabled = !editable;
  const close = () => dlg.close();
  const save = async () => {
    const r = await act(() => api('PUT', '/api/posts/' + id + '/comment', {text: ta.value}));
    if (r) { close(); loadPosts(); }
  };
  dlg.replaceChildren(
    h('h3', {}, p.author_name || 'Unknown author'),
    h('div', {class: 'meta muted'}, p.url),
    p.title ? h('p', {}, h('strong', {}, 'Title: '), p.title) : null,
    h('p', {}, h('strong', {}, 'Post text')),
    h('pre', {}, p.body || '(none)'),
    p.alt_text ? h('p', {}, h('strong', {}, 'Alt text: '), p.alt_text) : null,
    p.extra_text ? h('p', {}, h('strong', {}, 'Other text: '), p.extra_text) : null,
    h('p', {}, h('strong', {}, 'Comment')),
    ta,
    h('div', {class: 'row-actions'},
      editable ? h('button', {class: 'btn btn-primary btn-sm', title: 'Save your edited comment.', onclick: save}, 'Save edit') : null,
      h('button', {class: 'btn btn-sm', title: 'Close this window.', onclick: close}, 'Close')),
    h('p', {}, h('strong', {}, 'Activity history')),
    h('ul', {class: 'history'},
      d.actions.map(a => h('li', {}, fmt(a.created_at) + ' · ' + a.kind + ' · ' + a.status + (a.detail ? ' · ' + a.detail : ''))),
      d.jobs.map(j => h('li', {}, 'Queue job: ' + j.kind + ' · ' + nice(j.status) + ' · tries ' + j.attempts + (j.last_error ? ' · ' + j.last_error : '')))));
  dlg.showModal();
}
function initPosts() {
  hint($('#filter'), $('#filter-hint'));
  hint($('#bulk-action'), $('#bulk-hint'));
  $('#filter').onchange = e => { state.filter = e.target.value; state.page = 1; loadPosts(); };
  $('#sort').onchange = e => { state.sort = e.target.value; state.page = 1; loadPosts(); };
  let t;
  $('#search').oninput = e => { clearTimeout(t); t = setTimeout(() => { state.q = e.target.value.trim(); state.page = 1; loadPosts(); }, 300); };
  $('#btn-refresh').onclick = loadPosts;
  $('#btn-autoai').onclick = () => act(() => api('PUT', '/api/settings', {auto_ai: !state.autoAi})).then(refreshStatus);
  $('#prev').onclick = () => { state.page--; loadPosts(); };
  $('#next').onclick = () => { state.page++; loadPosts(); };
  $('#select-page').onclick = () => document.querySelectorAll('#posts .post input[type=checkbox]').forEach(c => {
    c.checked = true;
    c.dispatchEvent(new Event('change'));
  });
  $('#select-all').onclick = async () => {
    const d = await act(() => api('GET', '/api/posts/ids?' + new URLSearchParams({filter: state.filter, q: state.q})));
    if (!d) return;
    d.ids.forEach(i => state.selected.add(i));
    document.querySelectorAll('#posts .post input[type=checkbox]').forEach(c => { c.checked = true; });
    pCount();
  };
  $('#select-none').onclick = () => {
    state.selected.clear();
    document.querySelectorAll('#posts .post input[type=checkbox]').forEach(c => { c.checked = false; });
    pCount();
  };
  $('#bulk-run').onclick = async () => {
    const action = $('#bulk-action').value;
    const ids = [...state.selected];
    if (!action) return toast('Choose a bulk action', true);
    if (!ids.length) return toast('Select at least one post', true);
    if (action === 'open') {
      const urls = [...document.querySelectorAll('#posts .post')].filter(el => el.querySelector('input').checked).map(el => el.querySelector('a').href);
      urls.slice(0, 10).forEach(u => window.open(u, '_blank', 'noopener,noreferrer'));
      return;
    }
    if (action === 'skip' && !confirm('Skip ' + ids.length + ' post(s)?')) return;
    if (action === 'delete' && !confirm('Permanently delete ' + ids.length + ' post(s)? They will not be collected again.')) return;
    const d = await act(() => bulk('/api/posts/bulk', action, ids, 200));
    if (d && d.errors && d.errors.length) toast(d.message + '. ' + d.errors[0], true);
    state.selected.clear();
    loadPosts();
  };
  loadPosts();
  setInterval(loadPosts, 20000);
}
function field(key, spec, value) {
  const id = 'f-' + key;
  let input;
  if (spec.type === 'bool') {
    input = h('input', {type: 'checkbox', id, name: key});
    input.checked = !!value;
    return h('div', {class: 'field bool', 'data-key': key}, input, h('div', {class: 'field-text'}, h('label', {for: id}, spec.label), h('span', {class: 'hint'}, spec.help)), h('span', {class: 'error'}));
  }
  if (spec.type === 'choice') {
    input = h('select', {id, name: key}, spec.choices.map(c => h('option', {value: c}, spec.choice_help ? c + ' – ' + spec.choice_help[c] : c)));
    input.value = value;
  } else if (key === 'comment_style') {
    input = h('textarea', {id, name: key, maxlength: '500'});
    input.value = value;
  } else {
    input = h('input', {id, name: key, type: spec.type === 'int' ? 'number' : 'text', min: spec.min, max: spec.max});
    input.value = value;
  }
  return h('div', {class: 'field', 'data-key': key}, h('label', {for: id}, spec.label), h('span', {class: 'hint'}, spec.help), input, h('span', {class: 'error'}));
}
const GROUPS = [['Feed checking', 'How the assistant looks for new posts.', ['monitoring_enabled', 'poll_interval', 'lookback_days', 'poll_backlog_limit']], ['AI drafts', 'Which AI writes your comment drafts and how it behaves.', ['ai_model', 'ollama_endpoint', 'ai_timeout', 'auto_ai', 'ai_gap', 'ai_hourly_limit', 'comment_style', 'max_comment_length', 'comment_max_age_hours']], ['Publishing', 'What happens automatically and what waits for you.', ['publishing_mode', 'like_enabled', 'comment_enabled', 'connect_enabled', 'auto_like', 'auto_comment', 'like_max_age_hours']], ['Daily limits and pacing', 'Keeps your activity natural and your LinkedIn account safe.', ['daily_like_limit', 'daily_comment_limit', 'daily_connect_limit', 'like_gap', 'comment_cooldown', 'connect_gap', 'post_retry_cooldown']], ['Queue and retries', 'How jobs are processed and tried again when something goes wrong.', ['batch_size', 'max_queue', 'max_retries', 'backoff_base', 'backoff_max']], ['Display and logs', 'How times are shown and how much detail is logged.', ['log_level', 'timezone']]];
async function initSettings() {
  const form = $('#settings-form');
  let specs;
  try {
    const d = await api('GET', '/api/settings');
    specs = d.specs;
    const rest = Object.keys(specs).filter(k => !GROUPS.some(g => g[2].includes(k)));
    form.replaceChildren(...[...GROUPS, ['Other', '', rest]].filter(g => g[2].some(k => specs[k])).map(([title, desc, keys]) => h('section', {class: 'panel'}, h('h2', {}, title), h('p', {class: 'hint'}, desc), h('div', {class: 'form-grid'}, keys.filter(k => specs[k]).map(k => field(k, specs[k], d.settings[k]))))));
  } catch (e) {
    return toast(e.message, true);
  }
  $('#save-settings').onclick = async () => {
    const payload = {};
    for (const k of Object.keys(specs)) {
      const el = form.querySelector('[name=' + k + ']');
      payload[k] = specs[k].type === 'bool' ? el.checked : el.value;
    }
    form.querySelectorAll('.error').forEach(e => { e.textContent = ''; });
    try {
      const d = await api('PUT', '/api/settings', payload);
      toast(d.message);
    } catch (e) {
      toast(e.message, true);
      for (const [k, m] of Object.entries(e.details || {})) {
        const f = form.querySelector('[data-key=' + k + '] .error');
        if (f) f.textContent = m;
      }
    }
  };
}
async function loadLogs() {
  const qs = new URLSearchParams({limit: 300});
  const lv = $('#log-level').value;
  const comp = $('#log-component').value.trim();
  const post = $('#log-post').value.trim();
  if (lv) qs.set('level', lv);
  if (comp) qs.set('component', comp);
  if (post) qs.set('post_id', post);
  try {
    const d = await api('GET', '/api/logs?' + qs);
    $('#log-body').replaceChildren(...d.events.map(e => h('tr', {},
      h('td', {}, fmt(e.ts)),
      h('td', {class: 'lvl-' + e.level}, e.level),
      h('td', {}, e.component || ''),
      h('td', {}, e.post_id || ''),
      h('td', {class: 'msg'}, e.message))));
  } catch (e) {
    toast(e.message, true);
  }
}
function initLogs() {
  hint($('#log-level'), $('#log-hint'));
  $('#log-refresh').onclick = loadLogs;
  $('#log-clear').onclick = async () => {
    if (!confirm('Delete all log entries and empty the log file?')) return;
    await act(() => api('POST', '/api/logs/clear'));
    loadLogs();
  };
  ['#log-level'].forEach(s => { $(s).onchange = loadLogs; });
  loadLogs();
  setInterval(loadLogs, 15000);
}
const qstate = {status: 'active', kind: 'all', sort: 'next', q: '', page: 1, per: 30, cpage: 1, csort: 'newest', crange: 'all', total: 0, selected: new Set(), sig: ''};
function qCount() {
  $('#count').textContent = qstate.total + ' job(s)' + (qstate.selected.size ? ' · ' + qstate.selected.size + ' selected' : '');
}
function jobRow(j) {
  const chk = h('input', {type: 'checkbox', onchange: e => { e.target.checked ? qstate.selected.add(j.id) : qstate.selected.delete(j.id); qCount(); }});
  chk.checked = qstate.selected.has(j.id);
  const run = action => async () => {
    await act(() => api('POST', '/api/queue/bulk', {action, ids: [j.id]}));
    qstate.selected.delete(j.id);
    loadQueue(true);
  };
  return h('tr', {},
    h('td', {}, chk),
    h('td', {}, j.id),
    h('td', {class: 'msg'}, h('strong', {}, j.author_name || 'Unknown author'), j.title ? ' · ' + j.title : '', h('div', {class: 'muted'}, j.preview || '(no text)'), j.kind !== 'like' && j.comment ? h('div', {class: 'draft'}, j.comment) : null),
    h('td', {}, badge({ai: 'AI draft', like: 'Like', comment: 'Comment'}[j.kind] || j.kind)),
    h('td', {}, badge(nice(j.status), statusClass(j.status === 'running' ? 'queued' : j.status))),
    h('td', {}, j.attempts),
    h('td', {}, j.status === 'queued' ? fmt(j.next_run_at) : '–'),
    h('td', {}, fmt(j.updated_at)),
    h('td', {class: 'msg err'}, j.last_error || ''),
    h('td', {},
      h('div', {class: 'row-actions'},
        h('a', {class: 'btn btn-sm', href: j.url, target: '_blank', rel: 'noopener noreferrer', title: 'Open this post on LinkedIn.'}, 'Open post'),
        j.status === 'queued' ? h('button', {class: 'btn btn-sm', title: 'Make this job due right now.', onclick: run('run_now')}, 'Run now') : null,
        j.status === 'queued' ? h('button', {class: 'btn btn-sm btn-danger', title: 'Take this job out of the queue.', onclick: () => { if (confirm('Remove this job from the queue?')) run('cancel')(); }}, 'Remove') : null,
        ['failed', 'cancelled'].includes(j.status) ? h('button', {class: 'btn btn-sm', title: 'Put this job back in the queue.', onclick: run('retry')}, 'Retry') : null,
        j.status !== 'running' ? h('button', {class: 'btn btn-sm', title: 'Delete this job record.', onclick: run('delete')}, 'Delete') : null)));
}
async function loadQueue(force) {
  try {
    const qs = new URLSearchParams({status: qstate.status, kind: qstate.kind, sort: qstate.sort, q: qstate.q, page: qstate.page, per_page: qstate.per, c_page: qstate.cpage, c_sort: qstate.csort, c_range: qstate.crange});
    const d = await api('GET', '/api/queue?' + qs);
    const pages = Math.max(1, Math.ceil(d.total / qstate.per));
    if (qstate.page > pages) {
      qstate.page = pages;
      return loadQueue(true);
    }
    const cpages = Math.max(1, Math.ceil(d.connections_total / 50));
    if (qstate.cpage > cpages) {
      qstate.cpage = cpages;
      return loadQueue(true);
    }
    const sig = JSON.stringify(d);
    if (!force && sig === qstate.sig) return;
    qstate.sig = sig;
    qstate.total = d.total;
    document.querySelectorAll('[data-qcount]').forEach(n => { n.textContent = d.counts[n.dataset.qcount] ?? 0; });
    $('#q-cap').textContent = d.counts.active + ' / ' + d.max_queue;
    $('#q-limits').textContent = 'Last 24 hours: ' + d.usage.like + ' of ' + (d.limits.like || 'unlimited') + ' likes · ' + d.usage.comment + ' of ' + (d.limits.comment || 'unlimited') + ' comments · ' + d.usage.connect + ' of ' + (d.limits.connect || 'unlimited') + ' connections. Jobs wait automatically when a daily limit is reached.';
    $('#q-body').replaceChildren(...(d.jobs.length ? d.jobs.map(jobRow) : [h('tr', {}, h('td', {colspan: '10', class: 'muted'}, 'No jobs match these filters.'))]));
    $('#c-body').replaceChildren(...(d.connections.length ? d.connections.map((c, i) => h('tr', {}, h('td', {}, (qstate.cpage - 1) * 50 + i + 1), h('td', {}, c.url ? h('a', {href: c.url, target: '_blank', rel: 'noopener noreferrer', title: 'Open this profile on LinkedIn.'}, c.name || 'Unknown') : c.name || 'Unknown'), h('td', {}, fmt(c.created_at)))) : [h('tr', {}, h('td', {colspan: '3', class: 'muted'}, 'No connection requests match these filters.'))]));
    $('#c-page-info').textContent = 'Page ' + qstate.cpage + ' of ' + cpages + ' · ' + d.connections_total + ' request(s)';
    $('#c-prev').disabled = qstate.cpage <= 1;
    $('#c-next').disabled = qstate.cpage >= cpages;
    $('#page-info').textContent = 'Page ' + qstate.page + ' of ' + pages;
    $('#prev').disabled = qstate.page <= 1;
    $('#next').disabled = qstate.page >= pages;
    $('#select-page').textContent = 'Select page (' + d.jobs.length + ')';
    qCount();
  } catch (e) {
    toast(e.message, true);
  }
}
function initQueue() {
  hint($('#q-status'), $('#filter-hint'));
  hint($('#bulk-action'), $('#bulk-hint'));
  $('#q-status').onchange = e => { qstate.status = e.target.value; qstate.page = 1; loadQueue(true); };
  $('#q-kind').onchange = e => { qstate.kind = e.target.value; qstate.page = 1; loadQueue(true); };
  document.querySelectorAll('[data-kind]').forEach(c => { c.style.cursor = 'pointer'; c.onclick = () => { $('#q-kind').value = qstate.kind = c.dataset.kind; qstate.page = 1; loadQueue(true); }; });
  $('#sort').onchange = e => { qstate.sort = e.target.value; qstate.page = 1; loadQueue(true); };
  let t;
  $('#search').oninput = e => { clearTimeout(t); t = setTimeout(() => { qstate.q = e.target.value.trim(); qstate.page = 1; loadQueue(true); }, 300); };
  $('#btn-refresh').onclick = () => loadQueue(true);
  $('#prev').onclick = () => { qstate.page--; loadQueue(true); };
  $('#next').onclick = () => { qstate.page++; loadQueue(true); };
  $('#c-range').onchange = e => { qstate.crange = e.target.value; qstate.cpage = 1; loadQueue(true); };
  $('#c-sort').onchange = e => { qstate.csort = e.target.value; qstate.cpage = 1; loadQueue(true); };
  $('#c-prev').onclick = () => { qstate.cpage--; loadQueue(true); };
  $('#c-next').onclick = () => { qstate.cpage++; loadQueue(true); };
  $('#select-page').onclick = () => document.querySelectorAll('#q-body input[type=checkbox]').forEach(c => {
    c.checked = true;
    c.dispatchEvent(new Event('change'));
  });
  $('#select-all').onclick = async () => {
    const d = await act(() => api('GET', '/api/queue/ids?' + new URLSearchParams({status: qstate.status, kind: qstate.kind, q: qstate.q})));
    if (!d) return;
    d.ids.forEach(i => qstate.selected.add(i));
    document.querySelectorAll('#q-body input[type=checkbox]').forEach(c => { c.checked = true; });
    qCount();
  };
  $('#select-none').onclick = () => {
    qstate.selected.clear();
    document.querySelectorAll('#q-body input[type=checkbox]').forEach(c => { c.checked = false; });
    qCount();
  };
  $('#q-clear').onclick = async () => {
    if (!confirm('Delete every done and cancelled job record?')) return;
    await act(() => api('POST', '/api/queue/clear'));
    qstate.selected.clear();
    loadQueue(true);
  };
  $('#bulk-run').onclick = async () => {
    const action = $('#bulk-action').value;
    const ids = [...qstate.selected];
    if (!action) return toast('Choose a bulk action', true);
    if (!ids.length) return toast('Select at least one job', true);
    if (action === 'cancel' && !confirm('Take ' + ids.length + ' job(s) out of the queue?')) return;
    if (action === 'delete' && !confirm('Delete ' + ids.length + ' job record(s)?')) return;
    await act(() => bulk('/api/queue/bulk', action, ids, 500));
    qstate.selected.clear();
    loadQueue(true);
  };
  loadQueue(true);
  setInterval(() => { if (!document.hidden) loadQueue(); }, 3000);
}
try {
  const c = JSON.parse(sessionStorage.getItem('pill'));
  if (c) { $('#health-pill').textContent = c[0]; $('#health-pill').className = 'pill pill-' + c[1]; }
} catch (e) {}
refreshStatus();
setInterval(refreshStatus, 8000);
initSwitches();
if (page === 'dashboard') initDashboard();
if (page === 'posts') initPosts();
if (page === 'settings') initSettings();
if (page === 'logs') initLogs();
if (page === 'queue') initQueue();
})();