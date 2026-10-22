// 5gAAA live page: talks to the PAKA bridge running on the lab PC.
// The bridge only listens on the PC's loopback interface, so this page can
// drive the demo only when it is opened on that same PC.
'use strict';

const BRIDGE_PORT = 8790;
// Served by the bridge itself (local testing): same origin. Otherwise the loopback bridge.
const BRIDGE = location.port === String(BRIDGE_PORT) ? '' : 'http://127.0.0.1:' + BRIDGE_PORT;

const $ = (id) => document.getElementById(id);
const esc = (s) => s.replace(/[&<>]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]));

// Terminal text with SGR color codes -> HTML spans
function ansiToHtml(text) {
  let bold = false, dim = false, fg = 0, html = '';
  const parts = text.split(/\x1b\[([0-9;]*)m/);
  for (let i = 0; i < parts.length; i++) {
    if (i % 2 === 0) {
      if (!parts[i]) continue;
      const cls = [bold && 'a-b', dim && 'a-d', fg && 'a-' + fg].filter(Boolean).join(' ');
      html += cls ? '<span class="' + cls + '">' + esc(parts[i]) + '</span>' : esc(parts[i]);
      continue;
    }
    for (const c of (parts[i] || '0').split(';').map(Number)) {
      if (c === 0) { bold = dim = false; fg = 0; }
      else if (c === 1) bold = true;
      else if (c === 2) dim = true;
      else if (c === 22) bold = dim = false;
      else if (c >= 30 && c <= 37) fg = c;
      else if (c >= 90 && c <= 97) fg = c - 60;
      else if (c === 39) fg = 0;
    }
  }
  return html;
}

async function call(path, body) {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), body ? 200000 : 4000);
  try {
    const r = await fetch(BRIDGE + path, body
      ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body), signal: ctl.signal }
      : { signal: ctl.signal, cache: 'no-store' });
    return { code: r.status, data: await r.json() };
  } finally {
    clearTimeout(timer);
  }
}

// Replace a pane's text; stay pinned to the bottom unless the reader scrolled up
function setPane(id, text, pinBottom) {
  const el = $(id);
  const html = text ? ansiToHtml(text) : '<span class="empty">(nothing yet)</span>';
  if (el.dataset.last === html) return;
  const atBottom = el.scrollTop + el.clientHeight >= el.scrollHeight - 8;
  el.innerHTML = html;
  el.dataset.last = html;
  if (pinBottom && atBottom) el.scrollTop = el.scrollHeight;
}

let busy = false;

function showConnection(ok, text) {
  $('dot').className = 'dot ' + (ok ? 'on' : 'off');
  $('connText').textContent = text;
  $('howto').hidden = ok;
}

function showState(s) {
  if (!s.running) {
    showConnection(false, 'Connected to the lab PC, but the demo is not running. Start it there with ./paka up');
  } else {
    showConnection(true, 'Live: connected to the lab PC demo · target ' + s.target + ' · speed ' + s.speed);
  }
  const wrong = (s.keyWrong || []).includes(s.target);
  for (const b of document.querySelectorAll('#controls button')) {
    const g = b.dataset.group, a = b.dataset.arg;
    b.classList.toggle('sel', (g === 'target' && a === s.target.toLowerCase()) ||
      (g === 'speed' && a === s.speed) || (g === 'key' && a === (wrong ? 'wrong' : 'real')));
    b.classList.toggle('next', !g && s.running && b.dataset.cmd === s.next);
    b.disabled = busy || s.busy || !s.running;
  }
  $('hint').innerHTML = !s.running ? '' : s.next === 'wait'
    ? 'working ... (message in flight, or waiting for the paging slot)'
    : s.next ? 'next: <b>' + esc(s.next) + '</b>' : '';
}

async function poll() {
  try {
    const st = await call('/api/state');
    showState(st.data);
    if (st.data.running) {
      const p = (await call('/api/panes')).data;
      $('phoneTitle').textContent = p.phoneTitle || 'Phone';
      setPane('phone', p.phone, true);
      setPane('wire', p.wire, true);
      setPane('server', p.server, true);
      setPane('cell', p.cell, false);
    }
  } catch (e) {
    showConnection(false, 'Not connected to the lab PC.');
    for (const b of document.querySelectorAll('#controls button')) b.disabled = true;
  }
  setTimeout(poll, 700);
}

async function run(cmd, arg) {
  busy = true;
  $('out').innerHTML = '<span class="empty">running: ' + esc(cmd + (arg ? ' ' + arg : '')) + ' ...</span>';
  try {
    const r = await call('/api/cmd', { cmd, arg: arg || '' });
    const text = r.data.output || r.data.error || '';
    $('out').innerHTML = '<span class="a-d">paka&gt; ' + esc(cmd + (arg ? ' ' + arg : '')) + '</span>\n' + ansiToHtml(text);
  } catch (e) {
    $('out').textContent = 'Could not reach the lab PC: ' + e.message;
  } finally {
    busy = false;
  }
}

document.getElementById('controls').addEventListener('click', (ev) => {
  const b = ev.target.closest('button');
  if (b && !b.disabled) run(b.dataset.cmd, b.dataset.arg);
});

poll();
