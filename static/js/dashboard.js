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
function pillState(st) {
  if (!st) return ['Checking…', 'warn'];
  if (!st.worker_alive) return ['Worker stopped', 'bad'];
  if (st.monitor_state === 'recovering') return ['Recovering', 'warn'];
  if (st.browser_status !== 'running') return ['Browser ' + st.browser_status, 'bad'];
  if (st.auth_status !== 'ok') return ['Login required', 'warn'];
  if (st.ai_status !== 'up') return ['AI ' + st.ai_status, 'warn'];
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
    try { sessionStorage.setItem('pill', JSON.stringify([text, cls])); } catch (e) {}
    if (page === 'dashboard') {
      document.querySelectorAll('[data-stat]').forEach(n => { n.textContent = d.stats[n.dataset.stat] ?? 0; });
      const s = d.status;
      $('#st-monitor').textContent = s.worker_alive ? s.monitor_state : 'stopped';
      $('#st-browser').textContent = s.browser_status;
      $('#st-auth').textContent = s.auth_status;
      $('#st-ai').textContent = s.ai_status;
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
      const on = d.status.autoscroll_until && Date.parse(d.status.autoscroll_until) > Date.now();
      $('#btn-autoscroll').textContent = on ? 'Stop auto scroll' : 'Auto scroll';
      $('#btn-autoscroll').classList.toggle('btn-primary', !!on);
      state.autoAi = !!d.config.auto_ai;
      $('#btn-autoai').textContent = 'Auto AI drafts: ' + (state.autoAi ? 'On' : 'Off');
      $('#btn-autoai').classList.toggle('btn-primary', state.autoAi);
    }
  } catch (e) {
    const pill = $('#health-pill');
    pill.textContent = 'Offline';
    pill.className = 'pill pill-bad';
  }
}
function hint(sel, out) {
  const sync = () => { out.textContent = sel.selectedOptions[0].dataset.hint || ''; };
  sel.addEventListener('change', sync);
  sync();
}
function initDashboard() {
  $('#btn-pause').onclick = () => act(() => api('POST', '/api/monitor/pause')).then(refreshStatus);
  $('#btn-resume').onclick = () => act(() => api('POST', '/api/monitor/resume')).then(refreshStatus);
  $('#btn-poll').onclick = () => act(() => api('POST', '/api/monitor/poll-now'));
  $('#btn-browser').onclick = () => {
    if (confirm('Restart the browser now?')) act(() => api('POST', '/api/browser/restart'));
  };
}
const state = {filter: 'all', sort: 'recent', q: '', page: 1, per: 25, total: 0, selected: new Set()};
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
  const chk = h('input', {type: 'checkbox', onchange: e => { e.target.checked ? state.selected.add(p.id) : state.selected.delete(p.id); }});
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
    p.skipped ? h('button', {class: 'btn btn-sm', title: 'Put this post back into automation.', onclick: run('POST', '/reset')}, 'Reset skip') : h('button', {class: 'btn btn-sm btn-danger', title: 'Exclude this post from automation.', onclick: () => { if (confirm('Skip this post?')) run('POST', '/skip')(); }}, 'Skip')
  ];
  return h('div', {class: 'post'},
    chk,
    h('div', {class: 'post-main'},
      h('h3', {}, p.author_name || 'Unknown author', p.title ? ' · ' + p.title : ''),
      h('div', {class: 'meta'}, 'Published ' + fmt(p.published_at) + ' · Discovered ' + fmt(p.discovered_at)),
      h('div', {class: 'preview'}, p.preview || '(no text)'),
      h('div', {class: 'badges'},
        badge('AI: ' + p.ai_status, statusClass(p.ai_status)),
        badge('Comment: ' + p.comment_status, statusClass(p.comment_status)),
        badge('Like: ' + p.like_status, statusClass(p.like_status)),
        p.skipped ? badge('Skipped: ' + (p.skip_reason || ''), 'warn') : null,
        p.retry_count ? badge('Retries: ' + p.retry_count + (p.next_retry_at ? ' · next ' + fmt(p.next_retry_at) : ''), 'warn') : null),
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
    box.replaceChildren(...(d.posts.length ? d.posts.map(postCard) : [h('p', {class: 'muted'}, 'No posts match this view.')]));
    const pages = Math.max(1, Math.ceil(d.total / state.per));
    $('#page-info').textContent = 'Page ' + state.page + ' of ' + pages;
    $('#count').textContent = d.total + ' post(s)';
    $('#prev').disabled = state.page <= 1;
    $('#next').disabled = state.page >= pages;
    $('#select-all').checked = false;
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
    h('p', {}, h('strong', {}, 'Processing history')),
    h('ul', {class: 'history'},
      d.actions.map(a => h('li', {}, fmt(a.created_at) + ' · ' + a.kind + ' · ' + a.status + (a.detail ? ' · ' + a.detail : ''))),
      d.jobs.map(j => h('li', {}, 'job ' + j.kind + ' · ' + j.status + ' · attempts ' + j.attempts + (j.last_error ? ' · ' + j.last_error : '')))));
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
  $('#btn-autoscroll').onclick = () => act(() => api('POST', '/api/monitor/autoscroll')).then(refreshStatus);
  $('#prev').onclick = () => { state.page--; loadPosts(); };
  $('#next').onclick = () => { state.page++; loadPosts(); };
  $('#select-all').onchange = e => {
    document.querySelectorAll('#posts .post input[type=checkbox]').forEach((c, i) => {
      c.checked = e.target.checked;
      c.dispatchEvent(new Event('change'));
    });
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
    const d = await act(() => api('POST', '/api/posts/bulk', {action, ids}));
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
async function initSettings() {
  const form = $('#settings-form');
  let specs;
  try {
    const d = await api('GET', '/api/settings');
    specs = d.specs;
    form.replaceChildren(...Object.keys(specs).map(k => field(k, specs[k], d.settings[k])));
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
try {
  const c = JSON.parse(sessionStorage.getItem('pill'));
  if (c) { $('#health-pill').textContent = c[0]; $('#health-pill').className = 'pill pill-' + c[1]; }
} catch (e) {}
refreshStatus();
setInterval(refreshStatus, 8000);
if (page === 'dashboard') initDashboard();
if (page === 'posts') initPosts();
if (page === 'settings') initSettings();
if (page === 'logs') initLogs();
})();