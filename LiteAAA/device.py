#!/usr/bin/env python3
"""Run one LiteAAA device anywhere. Needs only Python 3, nothing to install.

    python3 device.py dave

The device finds the network's current address by itself, registers, and then
waits. It can be released, paged and verified from
https://zechengli.github.io/LiteAAA/ like the built-in phones.

    --network URL   use this network address instead of looking it up
    --key HEX       the device's secret key (default: the demo key)
"""
# One file, made by build_device.py. Do not edit; edit the parts.

# ---- from crypto.py ----
import os
import time


def _make_sbox():
    box, p, q = [0] * 256, 1, 1
    while True:
        p = (p ^ (p << 1) ^ (0x1B if p & 0x80 else 0)) & 0xFF
        q ^= q << 1
        q ^= q << 2
        q ^= q << 4
        q &= 0xFF
        if q & 0x80:
            q ^= 0x09
        x = q
        for shift in (1, 2, 3, 4):
            x ^= ((q << shift) | (q >> (8 - shift))) & 0xFF
        box[p] = x ^ 0x63
        if p == 1:
            break
    box[0] = 0x63
    return box


SBOX = _make_sbox()


def _xtime(a):
    return ((a << 1) ^ 0x1B) & 0xFF if a & 0x80 else a << 1


def aes128(key, block):
    """Encrypt one 16-byte block."""
    w = [list(key[i:i + 4]) for i in range(0, 16, 4)]
    rcon = 1
    for i in range(4, 44):
        t = list(w[i - 1])
        if i % 4 == 0:
            t = [SBOX[t[1]] ^ rcon, SBOX[t[2]], SBOX[t[3]], SBOX[t[0]]]
            rcon = _xtime(rcon)
        w.append([a ^ b for a, b in zip(w[i - 4], t)])
    rk = [sum(w[4 * r:4 * r + 4], []) for r in range(11)]
    s = [b ^ k for b, k in zip(block, rk[0])]
    for rnd in range(1, 11):
        s = [SBOX[b] for b in s]
        s = [s[4 * ((c + r) % 4) + r] for c in range(4) for r in range(4)]   # ShiftRows
        if rnd < 10:                                                       # MixColumns
            m = []
            for c in range(4):
                a = s[4 * c:4 * c + 4]
                t = a[0] ^ a[1] ^ a[2] ^ a[3]
                m += [a[i] ^ t ^ _xtime(a[i] ^ a[(i + 1) % 4]) for i in range(4)]
            s = m
        s = [b ^ k for b, k in zip(s, rk[rnd])]
    return bytes(s)


def xor(a, b):
    return bytes(x ^ y for x, y in zip(a, b))


def _rot(x, nbytes):
    return x[nbytes:] + x[:nbytes]


def _const(n):
    return bytes(15) + bytes([n])


def f1(k, opc, rand, sqn, amf):
    """MAC: the network's proof that it knows K."""
    temp = aes128(k, xor(rand, opc))
    in1 = (sqn + amf) * 2
    return xor(aes128(k, xor(temp, _rot(xor(in1, opc), 8))), opc)[:8]


def f2345(k, opc, rand):
    """RES (the device's proof), CK, IK, and AK (which hides SQN)."""
    temp = xor(aes128(k, xor(rand, opc)), opc)
    out2 = xor(aes128(k, xor(temp, _const(1))), opc)
    out3 = xor(aes128(k, xor(_rot(temp, 4), _const(2))), opc)
    out4 = xor(aes128(k, xor(_rot(temp, 8), _const(4))), opc)
    return out2[8:], out3, out4, out2[:6]


AMF = bytes.fromhex("8000")


class SoftSim:
    """Device side. Checks the network's proof, then gives its own."""

    def __init__(self, k, opc):
        self.k, self.opc, self.sqn = k, opc, 0

    def authenticate(self, rand, autn):
        res, _ck, _ik, ak = f2345(self.k, self.opc, rand)
        sqn = xor(autn[:6], ak)
        if f1(self.k, self.opc, rand, sqn, autn[6:8]) != autn[8:]:
            return False, "MAC in AUTN is wrong"                 # not my network
        if int.from_bytes(sqn, "big") <= self.sqn:
            return False, "old sequence number (replay)"         # seen before
        self.sqn = int.from_bytes(sqn, "big")
        return True, res


class MemoryKeyStore:
    """Network side. Hands out a fresh challenge and the answer to expect."""

    def __init__(self, opc):
        self.opc, self.k, self.sqn = opc, {}, {}

    def add(self, name, k):
        self.k[name] = k
        self.sqn.setdefault(name, int(time.time() * 1000))    # never goes back

    def challenge(self, name):
        rand = os.urandom(16)
        self.sqn[name] += 1
        sqn = self.sqn[name].to_bytes(6, "big")
        expected, _ck, _ik, ak = f2345(self.k[name], self.opc, rand)
        autn = xor(sqn, ak) + AMF + f1(self.k[name], self.opc, rand, sqn, AMF)
        return rand, autn, expected

# ---- from liteaaa.py ----
import json
import secrets

VERSION = 1


def pack(kind, **fields):
    return json.dumps({"v": VERSION, "type": kind, **fields}).encode()


def unpack(data):
    msg = json.loads(data)
    if msg.get("v") != VERSION:
        raise ValueError("unknown message version")
    return msg


class Device:
    """One device. Idle means: it reacts to nothing except a page for itself."""

    def __init__(self, name, sim):
        self.name, self.sim = name, sim
        self.identity, self.idle = None, False

    def hello(self):
        return pack("register", name=self.name)

    def handle(self, data):
        """Bytes in, reply bytes out (or None when there is nothing to say)."""
        msg = unpack(data)
        kind = msg["type"]
        if kind == "accept":
            self.identity = msg["identity"]
        elif kind == "release":
            self.idle = True
        elif kind == "page":                      # every device hears a page
            if self.idle and msg["identity"] == self.identity:
                self.idle = False
                return pack("answer", identity=self.identity)
        elif kind == "challenge" and not self.idle:
            ok, value = self.sim.authenticate(bytes.fromhex(msg["rand"]),
                                              bytes.fromhex(msg["autn"]))
            return pack("response", res=value.hex()) if ok else pack("reject", cause=value)
        return None


class Network:
    """Keeps track of devices, pages them, challenges them, checks the nonce."""

    def __init__(self, reach, keys, wait=2.0, tries=3, log=print, admit=None):
        self.reach, self.keys, self.log = reach, keys, log
        self.admit = admit                        # optional: admit(name, handle) -> bool
        self.wait, self.tries = wait, tries       # page again after `wait`, `tries` times
        self.devices = {}                         # name -> handle, identity, idle
        self.nonce = None                         # (name, number) after a pass

    def _expect(self, kinds, timeout, identity=None):
        """Wait for one message of the wanted kind; None when time runs out."""
        while True:
            got = self.reach.receive(timeout)
            if got is None:
                return None
            handle, data = got
            try:
                msg = unpack(data)
            except ValueError:
                continue
            if msg["type"] == "register":         # a device may appear any time
                self._register(handle, msg["name"])
            elif msg["type"] in kinds and identity in (None, msg.get("identity")):
                return msg

    def _register(self, handle, name):
        if self.admit and not self.admit(name, handle):
            return
        dev = {"handle": handle, "identity": secrets.randbits(32), "idle": False}
        self.devices[name] = dev
        self.reach.send(handle, pack("accept", identity=dev["identity"]))

    def accept_registrations(self, count, timeout=3.0):
        while len(self.devices) < count:
            got = self.reach.receive(timeout)
            if got is None:
                break
            msg = unpack(got[1])
            if msg["type"] == "register":
                self._register(got[0], msg["name"])
        return len(self.devices)

    def poll(self):
        """Take in devices that are waiting to register. Does not block."""
        while True:
            got = self.reach.receive(0)
            if got is None:
                return
            try:
                msg = unpack(got[1])
            except ValueError:
                continue
            if msg["type"] == "register":
                self._register(got[0], msg["name"])

    def release_all(self):
        for dev in self.devices.values():
            dev["idle"] = True
            self.reach.send(dev["handle"], pack("release"))

    def page(self, name):
        """Broadcast the device's identity; only that device answers."""
        dev, who = self.devices[name], name.capitalize()
        if not dev["idle"]:
            self.log("   %s is connected; no page needed" % who)
            return True
        for i in range(1, self.tries + 1):
            self.log("   PAGING     network -> all phones   identity %08x%s" %
                     (dev["identity"], "" if i == 1 else "   (attempt %d)" % i))
            self.reach.broadcast(pack("page", identity=dev["identity"]))
            if self._expect({"answer"}, self.wait, dev["identity"]):
                self.log("   ANSWER     %s -> network   I am here" % who)
                dev["idle"] = False
                return True
        self.log("   no answer; giving up")
        return False

    def verify(self, name):
        """Page, then both sides verify. True on pass; a nonce is then waiting."""
        dev, who = self.devices[name], name.capitalize()
        self.nonce = None
        if not self.page(name):
            self.log("   result: FAIL (the phone never answered the page)")
            return False
        rand, autn, expected = self.keys.challenge(name)
        self.log("   CHALLENGE  network -> %s   RAND, AUTN" % who)
        self.reach.send(dev["handle"], pack("challenge", rand=rand.hex(), autn=autn.hex()))
        msg = self._expect({"response", "reject"}, self.wait)
        if msg is None:
            self.log("   result: FAIL (no reply to the challenge)")
            return False
        if msg["type"] == "reject":
            self.log("   REFUSED    %s -> network   %s" % (who, msg["cause"]))
            self.log("   phone verified network:  FAIL")
            self.log("   network verified phone:  not reached")
            self.log("   result: FAIL")
            return False
        self.log("   RESPONSE   %s -> network   RES" % who)
        ok = secrets.compare_digest(bytes.fromhex(msg["res"]), expected)
        self.log("   phone verified network:  PASS   the SIM accepted AUTN")
        self.log("   network verified phone:  %s" %
                 ("PASS   RES matched" if ok else "FAIL   RES did not match"))
        if not ok:
            self.log("   result: FAIL")
            return False
        self.nonce = (name, secrets.randbelow(99) + 1)
        self.log("   result: PASS")
        self.log("   nonce: %d   enter it to finish:  nonce <number>" % self.nonce[1])
        return True

    def enter_nonce(self, text):
        if not self.nonce:
            self.log("   nothing is waiting for a nonce; run verify <phone> first")
            return False
        (name, want), self.nonce = self.nonce, None            # one try only
        ok = str(text).isdigit() and int(text) == want
        self.log("   nonce entered: %s\n   %s is %sverified." %
                 ("PASS" if ok else "FAIL", name.capitalize(), "" if ok else "NOT "))
        return ok

# ---- from device_main.py ----
import argparse
import secrets
import time
import urllib.error
import urllib.request


SITE = "https://zechengli.github.io/LiteAAA/machine.json"
DEMO_K = "465B5CE8B199B49FAA5F0A2EE238A6BC"
OPC = bytes.fromhex("E8ED289DEBA952E4283B54E88E6183CA")


def http(url, data=None, timeout=40):
    req = urllib.request.Request(url, data=data, headers={"User-Agent": "liteaaa-device/1"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read()


def find_network():
    import json
    return json.loads(http(SITE + "?t=%d" % time.time())[1])["url"].rstrip("/")


def say(text):
    print(time.strftime("%H:%M:%S"), text, flush=True)


def main():
    ap = argparse.ArgumentParser(description="Run one LiteAAA device.")
    ap.add_argument("name", help="a short name, for example dave")
    ap.add_argument("--network")
    ap.add_argument("--key", default=DEMO_K)
    args = ap.parse_args()
    name = args.name.lower()
    device = Device(name, SoftSim(bytes.fromhex(args.key), OPC))
    link = secrets.token_hex(8)              # this device's mailbox at the network
    net = hello_at = None
    while True:
        try:
            if net is None:
                net = (args.network or find_network()).rstrip("/")
                say("network: " + net)
            if device.identity is None and (hello_at is None or time.time() - hello_at > 5):
                http(net + "/link/up?id=" + link, device.hello())
                hello_at = time.time()
            status, data = http(net + "/link/down?id=" + link)
        except (urllib.error.URLError, OSError, ValueError, KeyError) as e:
            say("network not reachable (%s); trying again" % e.__class__.__name__)
            net, device.identity, hello_at = None, None, None
            time.sleep(5)
            continue
        if not data:
            continue
        kind = unpack(data)["type"]
        was_idle = device.idle
        reply = device.handle(data)
        if kind == "accept":
            say("registered as %s, identity %08x" % (name, device.identity))
        elif kind == "release":
            say("released: I am idle now and only a page for me wakes me")
        elif kind == "page":
            say("page for my identity: answering" if reply else
                "heard a page for someone else" if was_idle else "heard a page; I am already awake")
        elif kind == "challenge" and reply:
            ok = unpack(reply)["type"] == "response"
            say("challenge: AUTN is right, so I trust this network; sending RES" if ok else
                "challenge: REFUSED, " + unpack(reply)["cause"])
        if reply:
            http(net + "/link/up?id=" + link, reply)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
