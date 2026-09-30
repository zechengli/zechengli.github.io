// LiteAKA crypto: Milenage (TS 35.206) + RES* KDF (TS 33.501 A.4), on WebCrypto.
const LiteAKA = (() => {
  const subtle = crypto.subtle;
  const hex = b => Array.from(b, x => x.toString(16).padStart(2, '0')).join('');
  const unhex = s => new Uint8Array(s.match(/../g).map(x => parseInt(x, 16)));
  const xor = (a, b) => a.map((x, i) => x ^ b[i]);
  const cat = (...a) => { const o = new Uint8Array(a.reduce((n, x) => n + x.length, 0)); let p = 0; for (const x of a) { o.set(x, p); p += x.length; } return o; };

  // AES-128 on one block: AES-CBC with zero IV, first 16 bytes of output = ECB(block)
  async function aes(k, block) {
    const key = await subtle.importKey('raw', k, 'AES-CBC', false, ['encrypt']);
    const out = await subtle.encrypt({ name: 'AES-CBC', iv: new Uint8Array(16) }, key, block);
    return new Uint8Array(out).slice(0, 16);
  }
  // cyclic left rotation of 128-bit value by r bits (r multiple of 8)
  const rot = (x, r) => { const n = r / 8; return cat(x.slice(n), x.slice(0, n)); };
  const cst = i => { const c = new Uint8Array(16); c[15] = i; return c; };

  async function opc(k, op) { return xor(await aes(k, op), op); }

  // returns {mac_a, mac_s, res, ck, ik, ak, ak_s}
  async function milenage(k, opc, rand, sqn, amf) {
    const temp = await aes(k, xor(rand, opc));
    const in1 = cat(sqn, amf, sqn, amf);
    const out = async (r, c, extra) => xor(await aes(k, xor(xor(extra, rot(xor(temp, opc), r)), cst(c))), opc);
    const out1 = xor(await aes(k, xor(xor(temp, rot(xor(in1, opc), 64)), cst(0))), opc);
    const out2 = await out(0, 1, new Uint8Array(16));
    const out3 = await out(32, 2, new Uint8Array(16));
    const out4 = await out(64, 4, new Uint8Array(16));
    const out5 = await out(96, 8, new Uint8Array(16));
    return { mac_a: out1.slice(0, 8), mac_s: out1.slice(8, 16), res: out2.slice(8, 16), ak: out2.slice(0, 6),
             ck: out3, ik: out4, ak_s: out5.slice(0, 6) };
  }

  // RES* = low 128 bits of HMAC-SHA-256(CK||IK, 0x6B || P0 || L0 || P1 || L1 || P2 || L2)
  async function resStar(ck, ik, svc, rand, res) {
    const p0 = new TextEncoder().encode(svc);
    const L = n => new Uint8Array([n >> 8, n & 255]);
    const s = cat(new Uint8Array([0x6b]), p0, L(p0.length), rand, L(rand.length), res, L(res.length));
    const key = await subtle.importKey('raw', cat(ck, ik), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
    return new Uint8Array(await subtle.sign('HMAC', key, s)).slice(16, 32);
  }

  const sqnToBytes = n => { const b = new Uint8Array(6); for (let i = 5; i >= 0; i--) { b[i] = n % 256; n = Math.floor(n / 256); } return b; };
  const bytesToSqn = b => b.reduce((n, x) => n * 256 + x, 0);
  const ctEq = (a, b) => a.length === b.length && a.reduce((d, x, i) => d | (x ^ b[i]), 0) === 0;

  return { hex, unhex, xor, cat, aes, opc, milenage, resStar, sqnToBytes, bytesToSqn, ctEq };
})();

// Known-answer tests: TS 35.208 test set 1 (same vectors as srsRAN test_f12345.cc) and srsRAN RES* test.
async function liteakaSelfTest() {
  const { unhex, hex, opc, milenage, resStar } = LiteAKA;
  const k = unhex('465b5ce8b199b49faa5f0a2ee238a6bc');
  const o = await opc(k, unhex('cdc202d5123e20f62b6d676ac72cb318'));
  const m = await milenage(k, o, unhex('23553cbe9637a89d218ae64dae47bf35'), unhex('ff9bb4d0b607'), unhex('b9b9'));
  const rs = await resStar(unhex('3cba902575ed80cbfa3625aff09daffc'), unhex('ba902575ed80cbfa3625aff09daffc3c'),
    '5G:mnc001.mcc001.3gppnetwork.org', unhex('fc2d98a361208bf743639c9e632d7350'), unhex('fc3cba902575ed80'));
  const want = [
    ['OPc', hex(o), 'cd63cb71954a9f4e48a5994e37a02baf'],
    ['f1 MAC-A', hex(m.mac_a), '4a9ffac354dfafb3'],
    ['f1* MAC-S', hex(m.mac_s), '01cfaf9ec4e871e9'],
    ['f2 RES', hex(m.res), 'a54211d5e3ba50bf'],
    ['f3 CK', hex(m.ck), 'b40ba9a3c58b2a05bbf0d987b21bf8cb'],
    ['f4 IK', hex(m.ik), 'f769bcd751044604127672711c6d3441'],
    ['f5 AK', hex(m.ak), 'aa689c648370'],
    ['RES*', hex(rs), 'b0e35b23dbd7a18c848bfad91135e3fd'],
  ];
  return want.map(([name, got, exp]) => ({ name, got, exp, ok: got === exp }));
}
