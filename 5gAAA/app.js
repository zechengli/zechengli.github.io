// Talks to the demo's bridge on this computer (127.0.0.1:8791). When the
// bridge is not there, the page shows a recorded state and no buttons work.
var LOCAL = location.hostname === '127.0.0.1' || location.hostname === 'localhost';
var BRIDGE = LOCAL ? '' : 'http://127.0.0.1:8791';

var RECORDED = [
  { name: 'alice', ip: '10.45.0.11', state: 'IDLE', tmsi: 0xc0000328, ue_id: 808, pf: 80, i_s: 0 },
  { name: 'bob', ip: '10.45.0.12', state: 'IDLE', tmsi: 0xc0000407, ue_id: 7, pf: 14, i_s: 0 },
  { name: 'carol', ip: '10.45.0.13', state: 'IDLE', tmsi: 0xc0000585, ue_id: 389, pf: 10, i_s: 0 }
];

var live = false;
var busy = false;

function $(id) { return document.getElementById(id); }

function api(path, body) {
  var ctl = new AbortController();
  var timer = setTimeout(function () { ctl.abort(); }, body ? 70000 : 3000);
  var opt = { signal: ctl.signal, cache: 'no-store' };
  if (body) {
    opt.method = 'POST';
    opt.headers = { 'Content-Type': 'application/json' };
    opt.body = JSON.stringify(body);
  }
  return fetch(BRIDGE + path, opt)
    .then(function (r) { return r.json(); })
    .finally(function () { clearTimeout(timer); });
}

function cell(text, cls) {
  var td = document.createElement('td');
  td.textContent = text;
  if (cls) td.className = cls;
  return td;
}

function button(label, cmd, arg, enabled) {
  var b = document.createElement('button');
  b.textContent = label;
  b.disabled = !enabled;
  b.onclick = function () { run(cmd, arg); };
  return b;
}

function cap(s) { return s.charAt(0).toUpperCase() + s.slice(1); }

function showPhones(phones, usable) {
  var body = $('phones');
  body.textContent = '';
  phones.forEach(function (p) {
    var tr = document.createElement('tr');
    var st = p.state || 'OFF';
    var has = p.tmsi !== undefined;
    tr.appendChild(cell(cap(p.name)));
    tr.appendChild(cell(p.ip || '-'));
    tr.appendChild(cell(st, st.toLowerCase()));
    tr.appendChild(cell(has ? '0x' + p.tmsi.toString(16) : '-'));
    tr.appendChild(cell(has ? String(p.ue_id) : '-'));
    tr.appendChild(cell(has ? 'frame ' + p.pf + ' of 128, slot ' + p.i_s : '-'));
    var act = document.createElement('td');
    var on = usable && !busy;
    var up = st === 'CONNECTED' || st === 'IDLE';
    act.appendChild(button('Call', 'call', p.name, on && (up || st === 'LOST')));
    act.appendChild(button('Use', 'use', p.name, on && up));
    if (st === 'LOST') act.appendChild(button('Find', 'find', p.name, on));
    else act.appendChild(button('Lose', 'lose', p.name, on && up));
    tr.appendChild(act);
    body.appendChild(tr);
  });
  $('idle').disabled = !(usable && !busy);
}

function setConn(text, showHowto) {
  $('conn').textContent = text;
  $('howto').hidden = !showHowto;
}

function run(cmd, arg) {
  if (busy) return;
  busy = true;
  $('busy').textContent = 'Working ...';
  $('out').textContent = 'Running: ' + cmd + (arg ? ' ' + arg : '') + ' ...';
  poll();
  api('/api/cmd', { cmd: cmd, arg: arg || '' })
    .then(function (r) { $('out').textContent = r.output || r.error || 'Done.'; })
    .catch(function () { $('out').textContent = 'The demo did not answer.'; })
    .finally(function () {
      busy = false;
      $('busy').textContent = '';
      poll();
    });
}

function poll() {
  api('/api/state').then(function (s) {
    live = !!s.running;
    if (!live) {
      setConn('The bridge is running but the demo is not. Start it with ./paging up.', false);
      showPhones(RECORDED, false);
      return;
    }
    setConn('Connected to the live demo on this computer.', false);
    showPhones(s.phones && s.phones.length ? s.phones : RECORDED, true);
    return api('/api/wire').then(function (w) {
      var el = $('wire');
      var text = w.lines.length ? w.lines.join('\n') : 'Nothing yet.';
      if (el.textContent !== text) {
        el.textContent = text;
        el.scrollTop = el.scrollHeight;
      }
    });
  }).catch(function () {
    live = false;
    setConn('Not connected to a live demo. The table shows a recorded run.', true);
    showPhones(RECORDED, false);
  });
}

$('idle').onclick = function () { run('idle'); };
showPhones(RECORDED, false);
poll();
setInterval(poll, 1500);
