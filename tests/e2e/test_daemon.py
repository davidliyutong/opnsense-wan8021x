"""Supervisor robustness: crashed or hung supplicants must not take the service down."""
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
    socket; the daemon must survive it and reattach once the supplicant responds again."""
    plugin.configure()
    wait_for(lambda: authorized(), timeout=30, what="authentication")
    daemon = daemon_pid()
    sup = supplicant_pid()
    vm_sh(f"kill -STOP {sup}")
    try:
        auth("flap", "2")
        wait_for(lambda: "re-authentication request failed" in vm_sh("cat /var/log/wan8021x/*.log"),
                 timeout=30, what="the failed request to be logged")
    finally:
        vm_sh(f"kill -CONT {sup}")
    assert daemon_pid() == daemon, "the daemon must not have died"
    assert plugin.service_status() == "running"
    wait_for(lambda: "control interface reattached" in vm_sh("cat /var/log/wan8021x/*.log"),
             timeout=30, what="control interface to be reattached")
    # with the control interface back, link handling works again
    auth("flap", "2")
    wait_for(lambda: authorized(), timeout=30, what="re-authentication after recovery")
    vmlib.log("daemon survived a hung supplicant and recovered")
