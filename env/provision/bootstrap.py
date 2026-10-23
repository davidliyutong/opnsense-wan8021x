#!/usr/bin/env python3
"""Turn a freshly booted OPNsense nano image into the golden test VM.

Stage 1 goes through the serial console (LAN address, ssh, root key),
stage 2 through ssh (API key, sanity checks), then the VM is powered off.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "tools"))
import vmlib  # noqa: E402
from vmlib import log  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))


def stage1(pubkey):
    con = vmlib.Serial(timeout=60, logfile=open(os.path.join(vmlib.CACHE, "run", "bootstrap.log"), "w"))
    log("waiting for the login prompt (first boot takes a few minutes)")
    con.sendline()
    con.expect(r"login: ", timeout=900)
    con.sendline("root")
    con.expect(r"Password:")
    con.sendline("opnsense")
    con.expect(r"Enter an option: ")
    con.sendline("8")
    con.expect(vmlib.SHELL_PROMPT)
    con.sh("stty -echo")
    log("logged in, applying stage 1")
    with open(os.path.join(HERE, "stage1.php"), "rb") as f:
        con.put_file("/tmp/stage1.php", f.read())
    if con.sh(f"php /tmp/stage1.php '{pubkey}' && rm /tmp/stage1.php") != 0:
        raise RuntimeError("stage1.php failed")
    log("reloading interfaces and services")
    con.sh("/usr/local/etc/rc.reload_all", timeout=600)
    con.sendline("exit")


def stage2():
    vmlib.wait_booted()
    log("ssh is up, applying stage 2")
    with open(os.path.join(HERE, "stage2.php")) as f:
        r = vmlib.ssh("cat > /tmp/stage2.php && php /tmp/stage2.php && rm /tmp/stage2.php", input=f.read())
    key = json.loads(r.stdout.strip().splitlines()[-1])
    with open(vmlib.API_KEY_FILE, "w") as f:
        json.dump(key, f)
    os.chmod(vmlib.API_KEY_FILE, 0o600)
    version = vmlib.api("GET", "core/firmware/info")["product_version"]
    log(f"API reachable, OPNsense {version}")
    # fingerprint the tools the spike/plugin depends on
    log(vmlib.ssh("ls -l /usr/sbin/wpa_supplicant /usr/local/sbin/wpa_supplicant 2>&1; true").stdout.strip())


def main():
    pubkey = vmlib.ensure_ssh_key()
    stage1(pubkey)
    stage2()
    log("powering off")
    vmlib.ssh("shutdown -p now", check=False)


if __name__ == "__main__":
    main()
