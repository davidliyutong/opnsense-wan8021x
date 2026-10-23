"""Package removal while running leaves nothing behind; reinstall restores the service."""
from conftest import authorized, vm_sh, wait_for

PKG = "os-wan8021x-devel"
TREE = "/root/plugins/net/wan8021x"


def running():
    return vm_sh("pgrep -f 'wan8021xd.py|wpa_supplicant -D wired' || true").strip()


def test_uninstall_and_reinstall(plugin):
    plugin.configure()
    wait_for(lambda: authorized(), timeout=30, what="authentication")
    assert running()

    vm_sh(f"cd {TREE} && make package >/dev/null && pkg delete -y {PKG} >/dev/null")
    wait_for(lambda: not running(), timeout=20, what="daemon and supplicant to stop on removal")
    leftovers = vm_sh("ls /usr/local/etc/rc.d/wan8021x /usr/local/opnsense/scripts/OPNsense/Wan8021x "
                      "/usr/local/etc/inc/plugins.inc.d/wan8021x.inc 2>/dev/null || true")
    assert leftovers.strip() == ""

    # configuration survives in config.xml, reinstalling brings the port back up
    vm_sh(f"pkg add {TREE}/work/pkg/*.pkg >/dev/null")
    vm_sh("configctl wan8021x start >/dev/null")
    wait_for(lambda: authorized(), timeout=30, what="authentication after reinstall")


def test_upgrade_keeps_running(plugin):
    plugin.configure()
    wait_for(lambda: authorized(), timeout=30, what="authentication")
    before = running()
    vm_sh(f"cd {TREE} && make upgrade >/dev/null 2>&1")
    after = wait_for(running, timeout=20, what="service to come back after upgrade")
    assert after != before, "the daemon should have been restarted with the new code"
    assert plugin.service_status() == "running"
    wait_for(lambda: plugin.status() and plugin.status().get("port") == "Authorized", timeout=30,
             what="port authorized after upgrade")
