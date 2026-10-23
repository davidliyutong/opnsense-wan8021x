#!/usr/bin/env python3
"""Day-to-day VM operations, used by the top-level Makefile.

  vmctl.py wait                 wait until the VM finished booting
  vmctl.py serial CMD...        run a shell command over the serial console
  vmctl.py deploy PLUGIN_DIR    install the plugin source tree into the VM
  vmctl.py remove PLUGIN_DIR    remove the plugin files from the VM
  vmctl.py package PLUGIN_DIR   build the pkg inside the VM, copy to .cache/pkg
  vmctl.py lint PLUGIN_DIR      run the upstream "make lint" inside the VM
"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vmlib  # noqa: E402
from vmlib import log  # noqa: E402

# Layout inside the VM mirroring the opnsense/plugins repository next to a
# core checkout (Mk/ looks for ../core), so the upstream Mk/ files work unmodified.
VM_TREE = "/root/plugins"
VM_CORE = "/root/core"


def serial(cmd):
    con = vmlib.Serial()
    con.sendline()
    i = con.expect([r"login: ", r"Enter an option: ", vmlib.SHELL_PROMPT])
    if i == 0:
        con.sendline("root")
        con.expect(r"Password:")
        con.sendline("opnsense")
        i = con.expect([r"Enter an option: ", vmlib.SHELL_PROMPT])
    if i == 1 or i == 0:
        con.sendline("8")
        con.expect(vmlib.SHELL_PROMPT)
    con.sendline(cmd + "; echo __RC=$?")
    con.expect(r"__RC=(\d+)", timeout=300)
    out = con.p.before
    print(out.split("\n", 1)[1] if "\n" in out else out)
    return int(con.p.match.group(1))


def copy_tar(tar_args, dest, timeout=300):
    """tar on this side | ssh tar -x into dest on the VM, both ends supervised."""
    tar = subprocess.Popen(["tar"] + tar_args, stdout=subprocess.PIPE)
    ssh = subprocess.Popen(vmlib.ssh_base() + [f"rm -rf {dest} && mkdir -p {dest} && tar -C {dest} -xf -"],
                           stdin=tar.stdout)
    # only ssh may hold the read end, so tar gets SIGPIPE instead of blocking if ssh dies early
    tar.stdout.close()
    try:
        ssh.wait(timeout)
        tar.wait(timeout)
    finally:
        for proc in (ssh, tar):
            if proc.poll() is None:
                proc.kill()
                proc.wait()
    if ssh.returncode or tar.returncode:
        raise RuntimeError(f"copying to {dest} failed (tar {tar.returncode}, ssh {ssh.returncode})")


def sync_tree(plugin):
    """Copy the upstream build glue + the plugin directory to the VM (tar over ssh, no rsync needed)."""
    copy_tar(["-C", vmlib.ROOT, "-chf", "-", "--exclude=.git", "--exclude=__pycache__",
              "Mk", "Templates", "Scripts", "Keywords", plugin], VM_TREE)
    copy_tar(["-C", os.path.join(vmlib.ROOT, "vendor", "core"), "-cf", "-", "Mk", "Scripts", "ruleset.xml",
              "contrib/parallel-lint", "src/opnsense/mvc/app/models"], VM_CORE)


def make(plugin, target):
    r = vmlib.ssh(f"cd {VM_TREE}/{plugin} && make {target}", check=False, capture=False)
    if r.returncode:
        sys.exit(r.returncode)


def main():
    cmd, args = sys.argv[1], sys.argv[2:]
    if cmd == "wait":
        log("waiting for the VM")
        vmlib.wait_booted()
        log("VM is up")
    elif cmd == "serial":
        sys.exit(serial(" ".join(args)))
    elif cmd == "deploy":
        sync_tree(args[0])
        # build and (re)install a real package, so the pkg scripts run like in production
        make(args[0], "upgrade")
        log(f"deployed {args[0]}")
    elif cmd == "remove":
        sync_tree(args[0])
        make(args[0], "remove")
    elif cmd == "lint":
        sync_tree(args[0])
        make(args[0], "lint")
    elif cmd == "package":
        sync_tree(args[0])
        make(args[0], "package")
        out = os.path.join(vmlib.CACHE, "pkg")
        os.makedirs(out, exist_ok=True)
        subprocess.run(["scp", "-i", vmlib.SSH_KEY, "-P", str(vmlib.SSH_PORT),
                        "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null",
                        "-o", "LogLevel=ERROR",
                        f"root@127.0.0.1:{VM_TREE}/{args[0]}/work/pkg/*.pkg", out + "/"], check=True)
        log(f"package copied to {out}")
    else:
        print(__doc__)
        sys.exit(64)


if __name__ == "__main__":
    main()
