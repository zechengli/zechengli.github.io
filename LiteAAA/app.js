// A live session with the small demo (mini.py) on the lab machine.
var DEFAULT_ADDR = 'http://127.0.0.1:8792';
var LOCAL = location.hostname === '127.0.0.1' || location.hostname === 'localhost';
var addr = '';
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
  return fetch(addr + path, opt)
    .then(function (r) { return r.json(); })
    .finally(function () { clearTimeout(timer); });
}

function print(text) {
  var out = $('out');
  out.textContent += text + '\n';
  out.scrollTop = out.scrollHeight;
}

function poll() {
  api('/api/state').then(function (s) {
    if (!s.running) {
      $('conn').textContent = 'connected, but the demo is not running (./lite up)';
      return;
    }
    showNonce(s.nonce);
    var parts = (s.phones || []).map(function (p) { return p.name + ' ' + p.state; });
    $('conn').textContent = 'connected: ' + parts.join(', ') + (s.busy ? ' (busy)' : '');
  }).catch(function () {
    $('conn').textContent = 'not connected';
  });
}

function showNonce(n) {
  $('nonceText').textContent = n ? 'Nonce for ' + n.phone + ': ' + n.value : '';
}

function connect() {
  addr = $('addr').value.trim().replace(/\/+$/, '');
  $('conn').textContent = 'connecting ...';
  poll();
}

function run(line) {
  line = line.trim().toLowerCase();
  if (!line || busy) return;
  var words = line.split(/\s+/);
  busy = true;
  $('run').disabled = true;
  print('> ' + line);
  api('/api/cmd', { cmd: words[0], arg: words.slice(1).join(' ') })
    .then(function (r) { print(r.error ? 'error: ' + r.error : (r.output || 'done')); })
    .catch(function () { print('error: no answer from the machine'); })
    .finally(function () {
      busy = false;
      $('run').disabled = false;
      print('');
      poll();
    });
}

$('form').onsubmit = function (e) {
  e.preventDefault();
  run($('cmd').value);
  $('cmd').value = '';
};
$('connect').onclick = connect;
$('clear').onclick = function () { $('out').textContent = ''; };
Array.prototype.forEach.call(document.querySelectorAll('a[data-cmd]'), function (a) {
  a.onclick = function (e) {
    e.preventDefault();
    var c = a.getAttribute('data-cmd');
    if (c.slice(-1) === ' ') {          // needs a phone name: let the user type it
      $('cmd').value = c;
      $('cmd').focus();
    } else {
      run(c);
    }
  };
});

// The lab machine publishes its current public address in machine.json.
function start(url) {
  $('addr').value = url;
  connect();
  setInterval(poll, 2000);
}
if (LOCAL) {
  start(location.origin);
} else {
  fetch('machine.json?t=' + Date.now(), { cache: 'no-store' })
    .then(function (r) { return r.json(); })
    .then(function (m) { start(m.url || $('addr').value || DEFAULT_ADDR); })
    .catch(function () { start($('addr').value || DEFAULT_ADDR); });
}
