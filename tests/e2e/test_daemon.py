"""Supervisor robustness: crashed or hung supplicants must not take the service down."""
import threading
import time

import vmlib
from conftest import auth, authorized, vm_sh, wait_for

SUPPLICANT = "wpa_supplicant -D wired -i vtnet1"


def supplicant_pid():
    return vm_sh(f"pgrep -f '{SUPPLICANT}' || true").strip()


def daemon_pid():
    return vm_sh("pgrep -f wan8021xd.py || true").strip()


def test_crashed_supplicant_is_restarted(plugin):
    plugin.configure()
    wait_for(lambda: authorized(), timeout=30, what="authentication")
    old = supplicant_pid()
    auth("reset")
    vm_sh(f"kill -9 {old}")
    new = wait_for(lambda: (p := supplicant_pid()) and p != old and p, timeout=20, what="supplicant restart")
    assert new
    wait_for(lambda: authorized(), timeout=30, what="authentication after restart")


def test_hung_supplicant_does_not_stop_the_daemon(plugin):
    """A link-up re-authentication against an unresponsive supplicant times out on the control
    socket. The daemon must survive it, must not report the port as authorized meanwhile, and
    must send the pending re-authentication by itself once the supplicant responds again."""
    plugin.configure()
    wait_for(lambda: authorized(), timeout=30, what="authentication")
    daemon = daemon_pid()
    sup = supplicant_pid()
    vm_sh(f"kill -STOP {sup}")
    try:
        auth("flap", "2")
        wait_for(lambda: "re-authentication request failed" in vm_sh("cat /var/log/wan8021x/*.log"),
                 timeout=30, what="the failed request to be logged")
        # the switch reset the port, the GUI must not show it as authorized
        assert plugin.status()["status"] != "authorized"
        # a manual request reports the problem instead of a traceback
        r = vmlib.api("POST", "wan8021x/service/reauthenticate/wan")
        assert r["status"] == "failed" and r["response"].startswith("failed:"), r
    finally:
        vm_sh(f"kill -CONT {sup}")
    assert daemon_pid() == daemon, "the daemon must not have died"
    assert plugin.service_status() == "running"
    # no second cable pull: the pending re-authentication is retried after reattaching
    wait_for(lambda: authorized(), timeout=30, what="pending re-authentication to be sent")
    wait_for(lambda: plugin.status()["status"] == "authorized", timeout=30, what="status to recover")
    assert "control interface reattached" in vm_sh("cat /var/log/wan8021x/*.log")


def test_start_failure_backs_off(plugin):
    """A supplicant that cannot even be started is retried every few seconds, not in a tight loop."""
    binary = "/usr/local/sbin/wpa_supplicant"
    vm_sh(f"mv {binary} {binary}.off")
    try:
        plugin.configure()
        time.sleep(10)
        failures = vm_sh("cat /var/log/wan8021x/*.log | grep -c 'start failed' || true").split()
        assert 1 <= int(failures[-1]) <= 4, failures
        assert plugin.service_status() == "running"
    finally:
        vm_sh(f"mv {binary}.off {binary}")
    wait_for(lambda: authorized(), timeout=30, what="authentication once the binary is back")


def test_started_while_link_down(plugin):
    """The service starts while the cable is out; authentication must follow the link coming up."""
    pull = threading.Thread(target=auth, args=("flap", "12"))
    pull.start()
    try:
        time.sleep(2)
        plugin.configure()
        assert not authorized()
    finally:
        pull.join()
    wait_for(lambda: authorized(), timeout=40, what="authentication after the link came up")
