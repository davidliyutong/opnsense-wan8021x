"""Supervisor robustness: crashed or hung supplicants must not take the service down."""
import threading
import time

import vmlib
from conftest import VM_WAN_MAC, auth, authorized, vm_sh, wait_for

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


def test_hung_supplicant_is_restarted(plugin):
    """A supplicant that stops answering without exiting (SIGSTOP): a request reports the problem
    instead of a traceback, the daemon survives, kills the process and starts a new one."""
    plugin.configure()
    wait_for(lambda: authorized(), timeout=30, what="authentication")
    daemon = daemon_pid()
    sup = supplicant_pid()
    auth("reset")
    vm_sh(f"kill -STOP {sup}")
    try:
        r = vmlib.api("POST", "wan8021x/service/reauthenticate/wan")
        assert r["status"] == "failed" and r["response"].startswith("failed:"), r
        assert plugin.status()["status"] != "authorized"
        wait_for(lambda: (p := supplicant_pid()) and p != sup and p, timeout=30,
                 what="the hung supplicant to be replaced")
    finally:
        vm_sh(f"kill -CONT {sup} 2>/dev/null || true")
    assert daemon_pid() == daemon, "the daemon must not have died"
    assert "not responding for" in vm_sh("cat /var/log/wan8021x/*.log")
    wait_for(lambda: authorized(), timeout=30, what="authentication by the new supplicant")
    wait_for(lambda: plugin.status()["status"] == "authorized", timeout=30, what="status to recover")


def test_failed_generation_keeps_previous_config(plugin):
    """setup.php cannot write its files (e.g. a full disk): it reports an error, the previous
    configuration stays intact and the supplicant keeps running from it."""
    plugin.configure()
    wait_for(lambda: authorized(), timeout=30, what="authentication")
    before = vm_sh("cat /var/etc/wan8021x/supplicants.json")
    # a file where the staging directory goes makes generating fail
    vm_sh("touch /var/etc/wan8021x.new")
    try:
        out = vm_sh("/usr/local/etc/rc.d/wan8021x restart 2>&1; echo exit=$?", check=False)
        assert "exit=1" in out and "cannot create" in out, out
        assert vm_sh("cat /var/etc/wan8021x/supplicants.json") == before
        assert plugin.service_status() == "running"
    finally:
        vm_sh("rm -f /var/etc/wan8021x.new")
    wait_for(lambda: authorized(), timeout=30, what="authentication with the previous configuration")


def test_concurrent_restarts(plugin):
    """configd, hooks and package scripts can restart at the same time; runs are serialized and
    always leave a consistent configuration behind."""
    plugin.configure()
    vm_sh("for i in 1 2 3 4; do /usr/local/etc/rc.d/wan8021x restart >/dev/null 2>&1 & done; wait")
    check = """cat > /tmp/chk.php <<'EOF'
<?php
$index = json_decode(file_get_contents('/var/etc/wan8021x/supplicants.json'), true);
foreach ($index['supplicants'] as $s) { if (!is_file($s['config'])) { echo "missing "; } }
echo count($index['supplicants']);
EOF
php /tmp/chk.php"""
    assert vm_sh(check).strip() == "1"
    assert vm_sh("pgrep -f 'wpa_supplicant -D wired' | wc -l").strip() == "1"
    assert plugin.service_status() == "running"
    wait_for(lambda: authorized(), timeout=30, what="authentication after the restarts")


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


def test_authenticator_reauthentication(plugin):
    """A re-authentication the switch starts (e.g. RADIUS Session-Timeout) long after the last
    one the daemon kicked must run to completion, not be taken for a stalled exchange."""
    # hostapd frees the station of the previous test's supplicant (EAPOL-Logoff) only 5s later;
    # an exchange started before ends up on the freed station, where EAPOL_REAUTH fails
    time.sleep(6)
    plugin.configure()
    wait_for(lambda: plugin.status()["status"] == "authorized", timeout=30, what="authentication")
    time.sleep(22)  # past EAP_RESULT_TIMEOUT since the daemon last kicked an exchange
    sup = supplicant_pid()
    before = plugin.status()["authenticated_at"]
    assert auth("reauth", VM_WAN_MAC).strip() == "OK"
    wait_for(lambda: plugin.status()["authenticated_at"] > before, timeout=30, what="re-authentication")
    time.sleep(3)
    assert supplicant_pid() == sup, "the supplicant must not have been restarted"
    assert plugin.status()["status"] == "authorized"


def test_status_write_failure_keeps_authenticating(plugin):
    """The status file is only for the GUI: failing to write it must not stop the supplicants."""
    plugin.configure()
    wait_for(lambda: authorized(), timeout=30, what="authentication")
    daemon, sup = daemon_pid(), supplicant_pid()
    # a directory where the temporary status file goes
    vm_sh("mkdir /var/run/wan8021x/status.json.tmp")
    try:
        auth("reset")
        assert vmlib.api("POST", "wan8021x/service/reauthenticate/wan")["status"] == "ok"
        wait_for(lambda: authorized(), timeout=30, what="re-authentication while the status cannot be written")
        assert "cannot write the status file" in vm_sh("cat /var/log/wan8021x/*.log")
        assert (daemon_pid(), supplicant_pid()) == (daemon, sup)
    finally:
        vm_sh("rmdir /var/run/wan8021x/status.json.tmp")
    wait_for(lambda: plugin.status()["status"] == "authorized", timeout=10, what="status file to be written again")


def test_link_monitor_restart_resyncs(plugin):
    """A link loss while the link monitor is gone must still lead to a re-authentication."""
    plugin.configure()
    wait_for(lambda: authorized(), timeout=30, what="authentication")
    monitor = vm_sh("pgrep -f 'route -n monitor'").split()
    # stopped, it misses the link events; killed afterwards, they are never delivered
    vm_sh(f"kill -STOP {' '.join(monitor)}")
    auth("flap", "3")
    vm_sh(f"kill -9 {' '.join(monitor)}")
    wait_for(lambda: "link monitor restarted" in vm_sh("cat /var/log/wan8021x/*.log"),
             timeout=15, what="the monitor to be restarted")
    wait_for(lambda: authorized(), timeout=30, what="re-authentication after the missed link loss")
