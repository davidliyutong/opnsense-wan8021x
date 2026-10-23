"""The port is authenticated again after a reboot, without any user action."""
import time

import vmlib
from conftest import auth, authorized, ipv4, vm_sh, wait_for


def test_authenticates_at_boot(plugin):
    plugin.configure()
    wait_for(lambda: authorized(), timeout=30, what="initial authentication")

    booted = vm_sh("sysctl -n kern.boottime")
    vmlib.ssh("shutdown -r now", check=False)
    time.sleep(10)
    auth("reset")  # the switch sees the link drop while the VM reboots
    t0 = time.time()
    vmlib.wait_booted(timeout=600)
    assert vm_sh("sysctl -n kern.boottime") != booted, "the VM did not reboot"
    wait_for(lambda: authorized(), timeout=60, what="authentication after boot")
    wait_for(lambda: ipv4("vtnet1").startswith("172.31.0."), timeout=60, what="WAN lease after boot")
    vmlib.log(f"authenticated and leased {time.time() - t0:.0f}s after the VM came back")
    boot_log = vm_sh("grep -h 'wan8021x' /var/log/wan8021x/*.log | tail -20")
    assert "starting supplicant on vtnet1" in boot_log
    assert plugin.service_status() == "running"
