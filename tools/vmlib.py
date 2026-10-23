"""Helpers to drive the OPNsense test VM (serial console, ssh, API).

Runs inside the dev container, where the repository is mounted at /src.
"""
import base64
import json
import os
import socket
import subprocess
import time

import pexpect
import pexpect.fdpexpect

ROOT = os.environ.get("REPO_ROOT", "/src")
CACHE = os.path.join(ROOT, ".cache")
SERIAL_SOCK = os.path.join(CACHE, "run", "serial.sock")
SSH_KEY = os.path.join(CACHE, "ssh", "id_ed25519")
API_KEY_FILE = os.path.join(CACHE, "ssh", "apikey.json")
SSH_PORT = int(os.environ.get("SSH_PORT", "12222"))
GUI_PORT = int(os.environ.get("GUI_PORT", "18443"))
SHELL_PROMPT = r"root@[^\r\n]*[#$] $"


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def ensure_ssh_key():
    if not os.path.exists(SSH_KEY):
        os.makedirs(os.path.dirname(SSH_KEY), exist_ok=True)
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "wan8021x-dev",
                        "-f", SSH_KEY], check=True)
    with open(SSH_KEY + ".pub") as f:
        return f.read().strip()


class Serial:
    """pexpect session on the VM's serial console (QEMU unix socket)."""

    def __init__(self, timeout=30, logfile=None):
        deadline = time.time() + 60
        while True:
            try:
                self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                self.sock.connect(SERIAL_SOCK)
                break
            except OSError:
                if time.time() > deadline:
                    raise
                time.sleep(1)
        self.p = pexpect.fdpexpect.fdspawn(self.sock.fileno(), timeout=timeout,
                                           encoding="utf-8", codec_errors="replace")
        self.p.logfile_read = logfile

    def expect(self, pattern, timeout=-1):
        return self.p.expect(pattern, timeout=timeout)

    def send(self, s):
        # the emulated UART has no flow control: feed it in small pieces
        for i in range(0, len(s), 64):
            self.p.send(s[i:i + 64])
            time.sleep(0.01)

    def sendline(self, s=""):
        self.send(s + "\r")

    def sh(self, cmd, timeout=120):
        """Run a command at the root shell prompt, return its exit status."""
        self.sendline(cmd + "; echo __RC=$?")
        self.p.expect(r"__RC=(\d+)", timeout=timeout)
        rc = int(self.p.match.group(1))
        self.p.expect(SHELL_PROMPT, timeout=timeout)
        return rc

    def put_file(self, path, data, mode="0600"):
        """Copy bytes to the VM through the console as base64 lines."""
        b64 = base64.b64encode(data).decode()
        self.sh(f"rm -f {path}.b64")
        for i in range(0, len(b64), 512):
            if self.sh(f"echo '{b64[i:i + 512]}' >> {path}.b64") != 0:
                raise RuntimeError("serial transfer failed")
        rc = self.sh(f"b64decode -r < {path}.b64 > {path} && rm {path}.b64 && chmod {mode} {path}")
        if rc != 0:
            raise RuntimeError(f"decoding {path} failed")


def ssh_base():
    return ["ssh", "-i", SSH_KEY, "-p", str(SSH_PORT),
            "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null",
            "-o", "LogLevel=ERROR", "-o", "ConnectTimeout=5", "root@127.0.0.1"]


def ssh(cmd, check=True, capture=True, input=None, timeout=600):
    r = subprocess.run(ssh_base() + [cmd], capture_output=capture, text=True,
                       input=input, timeout=timeout)
    if check and r.returncode != 0:
        raise RuntimeError(f"ssh '{cmd}' failed ({r.returncode}): {r.stderr}{r.stdout}")
    return r


def wait_ssh(timeout=600):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if ssh("true", check=False, timeout=15).returncode == 0:
                return
        except subprocess.TimeoutExpired:
            pass
        time.sleep(3)
    raise TimeoutError("VM did not become reachable over ssh")


def wait_booted(timeout=600):
    """ssh up is not enough: wait until the rc bootup sequence finished."""
    wait_ssh(timeout)
    deadline = time.time() + timeout
    while time.time() < deadline:
        if ssh("/usr/local/bin/flock -n /var/run/booting true", check=False).returncode == 0:
            return
        time.sleep(3)
    raise TimeoutError("VM still booting")


def api(method, path, data=None):
    import requests
    import urllib3
    urllib3.disable_warnings()
    with open(API_KEY_FILE) as f:
        k = json.load(f)
    r = requests.request(method, f"https://127.0.0.1:{GUI_PORT}/api/{path}",
                         auth=(k["key"], k["secret"]), json=data, verify=False, timeout=60)
    r.raise_for_status()
    return r.json()
