"""End-to-end test helpers: drive OPNsense through its API and ssh, and the
authenticator through its control socket. Run inside the dev container
(`make test`), against a VM with the plugin deployed."""
import os
import socket
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "tools"))
import vmlib  # noqa: E402

VM_WAN_MAC = "52:54:00:00:02:01"
PKI = os.path.join(vmlib.CACHE, "auth", "pki")
AUTH_LOG = os.path.join(vmlib.CACHE, "run", "auth.log")


def wait_for(predicate, timeout=60, interval=1, what="condition"):
    deadline = time.time() + timeout
    while True:
        value = predicate()
        if value:
            return value
        if time.time() > deadline:
            raise AssertionError(f"timed out after {timeout}s waiting for {what}")
        time.sleep(interval)


def auth(*args):
    """Run authctl in the authenticator container, return its output."""
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(60)
    sock.connect(os.path.join(vmlib.CACHE, "run", "authctl.sock"))
    sock.sendall((" ".join(args) + "\n").encode())
    data = b""
    while chunk := sock.recv(4096):
        data += chunk
    sock.close()
    out, _, rc = data.decode().rstrip("\n").rpartition("rc=")
    assert rc == "0", f"authctl {args} failed: {out}"
    return out


def authorized(port="untagged"):
    return VM_WAN_MAC in auth("authorized", port).split()


def vm_sh(script, check=True):
    return vmlib.ssh("sh -s", input=script, check=check).stdout


def ipv4(device):
    out = vm_sh(f"ifconfig {device} 2>/dev/null | awk '/inet /{{print $2}}'", check=False)
    return out.strip().split("\n")[0]


class Plugin:
    """API wrapper for the os-wan8021x settings."""

    def reset(self):
        for row in vmlib.api("GET", "wan8021x/settings/search_supplicant")["rows"]:
            vmlib.api("POST", f"wan8021x/settings/del_supplicant/{row['uuid']}")
        vmlib.api("POST", "wan8021x/settings/set", {"wan8021x": {"general": {"enabled": "0", "debug": "0"}}})
        self.apply()

    def apply(self):
        r = vmlib.api("POST", "wan8021x/service/reconfigure")
        assert r["status"] == "ok", r

    def add(self, **fields):
        supplicant = {"enabled": "1", "interface": "wan", "eap_method": "PEAP", "phase2": "MSCHAPV2",
                      "identity": "alice", "password": "alice-secret"}
        supplicant.update(fields)
        return vmlib.api("POST", "wan8021x/settings/add_supplicant", {"supplicant": supplicant})

    def enable(self, **general):
        settings = {"enabled": "1"}
        settings.update(general)
        r = vmlib.api("POST", "wan8021x/settings/set", {"wan8021x": {"general": settings}})
        assert r["result"] == "saved", r

    def configure(self, **fields):
        r = self.add(**fields)
        assert r["result"] == "saved", r
        self.enable()
        self.apply()
        return r["uuid"]

    def status(self, interface="wan"):
        for row in vmlib.api("GET", "wan8021x/service/supplicants")["rows"]:
            if row["interface"] == interface:
                return row
        return None

    def service_status(self):
        return vmlib.api("GET", "wan8021x/service/status")["status"]


@pytest.fixture(scope="session")
def ca_refs():
    """Import the test CA and the rogue CA once, return {name: refid}."""
    refs = {}
    existing = {row["descr"]: row["refid"] for row in vmlib.api("GET", "trust/ca/search")["rows"]}
    for name in ("ca", "rogue-ca"):
        descr = f"wan8021x test {name}"
        if descr not in existing:
            with open(os.path.join(PKI, f"{name}.crt")) as f:
                r = vmlib.api("POST", "trust/ca/add", {"ca": {"action": "existing", "descr": descr,
                                                              "crt_payload": f.read()}})
            assert r["result"] == "saved", r
            existing = {row["descr"]: row["refid"] for row in vmlib.api("GET", "trust/ca/search")["rows"]}
        refs[name] = existing[descr]
    return refs


@pytest.fixture
def plugin():
    """A clean plugin configuration and an unauthorized switch port for every test."""
    p = Plugin()
    p.reset()
    auth("reset")
    yield p
    p.reset()
    auth("reset")
