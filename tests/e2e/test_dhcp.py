"""Refresh an existing DHCP lease after authentication without disturbing static IPv4."""
import time

import vmlib
from conftest import VM_WAN_MAC, auth, authorized, ipv4, vm_sh, wait_for
from test_auth import assert_authenticated
from test_daemon import daemon_pid, supplicant_pid


SET_IPV4 = """<?php
require_once 'config.inc';
require_once 'auth.inc';
require_once 'util.inc';
require_once 'filter.inc';
require_once 'system.inc';
require_once 'interfaces.inc';
interface_reset('wan');
$cfg = OPNsense\\Core\\Config::getInstance();
$iface = $cfg->object()->interfaces->wan;
$iface->ipaddr = $argv[1];
if ($argv[1] === 'dhcp') {
    unset($iface->subnet);
} else {
    $iface->subnet = '24';
}
$cfg->save();
"""


def dhclient_pid():
    """The core-owned supervisor changes when DHCP is restarted."""
    return vm_sh("pgrep -nF /var/run/dhclient.vtnet1.pid 2>/dev/null || true").strip()


def dhcp_refresh_count():
    """Count plugin refreshes separately from core's own DHCP restart on link up."""
    return int(vm_sh("cat /var/log/wan8021x/*.log | "
                     "grep -c 'wan: restarted IPv4 DHCP after authentication on vtnet1' || true").strip())


def reachable(address):
    return "1 packets received" in vm_sh(f"ping -c 1 -t 2 {address} 2>&1", check=False)


def set_ipv4(address):
    vmlib.ssh(f"cat > /tmp/wan8021x-ipv4.php && php /tmp/wan8021x-ipv4.php {address} "
              "&& configctl interface reconfigure wan", input=SET_IPV4)


def restore_default_network(plugin):
    """Leave the WAN with its original subnet and a usable lease, even after a failed assertion."""
    plugin.reset()
    auth("network", "default")
    auth("preauth", VM_WAN_MAC)
    set_ipv4("dhcp")
    wait_for(lambda: ipv4("vtnet1").startswith("172.31.0."), timeout=30, what="the default WAN lease")


def test_authentication_replaces_old_subnet_lease(plugin):
    """A one-hour pre-auth lease must be replaced immediately when the port changes subnet."""
    try:
        auth("network", "default")
        auth("preauth", VM_WAN_MAC)
        set_ipv4("dhcp")
        old_address = wait_for(lambda: (ip := ipv4("vtnet1")).startswith("172.31.0.") and ip,
                               timeout=30, what="a pre-authentication lease")
        assert reachable("172.31.0.1")
        before = dhclient_pid()
        assert before

        # The old gateway disappears while the cable stays connected. Starting the
        # plugin below must be sufficient; there is no renew/reconfigure after it.
        auth("network", "changed")
        auth("reset")
        assert ipv4("vtnet1") == old_address
        assert not reachable("172.31.0.1")
        # hostapd delays station teardown after deauth; let it finish before a
        # new authentication, or the old timer can revoke the new authorization.
        time.sleep(6)
        plugin.configure()
        assert_authenticated(plugin)
        wait_for(lambda: ipv4("vtnet1").startswith("172.31.10."), timeout=25,
                 what="a replacement lease on the authenticated subnet")
        wait_for(lambda: reachable("172.31.10.1"), timeout=10, what="traffic on the new subnet")
        assert dhclient_pid() != before
    finally:
        restore_default_network(plugin)


def test_reauthentication_preserves_dhcp_lease(plugin):
    """Successful periodic and manual re-auth keep an already authorized port's lease intact."""
    # hostapd can free the previous supplicant's station five seconds after Logoff.
    time.sleep(6)
    before_refreshes = dhcp_refresh_count()
    plugin.configure()
    assert_authenticated(plugin)
    wait_for(lambda: dhcp_refresh_count() > before_refreshes, timeout=15, what="the initial DHCP refresh")
    refreshed_at = time.monotonic()
    wait_for(lambda: ipv4("vtnet1").startswith("172.31.0."), timeout=30, what="the WAN lease")
    wait_for(lambda: reachable("172.31.0.1"), timeout=15, what="traffic after initial authentication")
    daemon, supplicant = daemon_pid(), supplicant_pid()
    before_pid = dhclient_pid()
    before_address = ipv4("vtnet1")
    before_refreshes = dhcp_refresh_count()
    assert before_pid
    for source in ("periodic", "manual"):
        before_auth = plugin.status()["authenticated_at"]
        time.sleep(1)  # authenticated_at uses whole seconds
        if source == "periodic":
            assert auth("reauth", VM_WAN_MAC).strip() == "OK"
        else:
            assert vmlib.api("POST", "wan8021x/service/reauthenticate/wan")["status"] == "ok"
        wait_for(lambda: plugin.status()["authenticated_at"] > before_auth, timeout=30,
                 what=f"{source} re-authentication")
        assert_authenticated(plugin)
        assert dhclient_pid() == before_pid, f"{source} re-authentication must keep DHCP running"
        assert ipv4("vtnet1") == before_address
        assert reachable("172.31.0.1")

    after_auth = plugin.status()["authenticated_at"]
    # A wrongly queued refresh can hide behind the 30s cooldown. Observe beyond
    # that window as well as checking immediately after the two EAP exchanges.
    time.sleep(max(0, 35 - (time.monotonic() - refreshed_at)))
    assert dhclient_pid() == before_pid, "re-authentication must not queue a delayed DHCP refresh"
    assert dhcp_refresh_count() == before_refreshes
    assert ipv4("vtnet1") == before_address
    assert plugin.status()["authenticated_at"] == after_auth, "re-authentication must not trigger an EAP loop"
    assert (daemon_pid(), supplicant_pid()) == (daemon, supplicant)


def test_link_recovery_retains_dhcp_refresh_during_cooldown(plugin):
    """A real recovery inside the 30s cooldown refreshes DHCP once the limit expires."""
    time.sleep(6)
    before_refreshes = dhcp_refresh_count()
    plugin.configure()
    row = assert_authenticated(plugin)
    wait_for(lambda: dhcp_refresh_count() > before_refreshes, timeout=15, what="the initial DHCP refresh")
    wait_for(lambda: ipv4("vtnet1").startswith("172.31.0."), timeout=15, what="the initial WAN lease")
    daemon, supplicant = daemon_pid(), supplicant_pid()
    before_refreshes = dhcp_refresh_count()

    # Six seconds also lets hostapd finish removing the previous station before
    # the new exchange starts. Core may restart DHCP itself on the link event.
    auth("flap", "6")
    recovered = wait_for(lambda: (s := plugin.status()) and s["authenticated_at"] > row["authenticated_at"]
                         and s["state"] == "authenticated" and authorized() and s,
                         timeout=15, what="authentication after link recovery")
    assert dhcp_refresh_count() == before_refreshes, "a recovery inside the cooldown must wait"
    linkup_pid = wait_for(dhclient_pid, timeout=5, what="core's DHCP client after link up")
    wait_for(lambda: dhcp_refresh_count() == before_refreshes + 1, timeout=40,
             what="the deferred DHCP refresh after recovery")
    wait_for(lambda: (pid := dhclient_pid()) and pid != linkup_pid, timeout=5,
             what="the DHCP client restarted after the cooldown")
    wait_for(lambda: reachable("172.31.0.1"), timeout=15, what="traffic after the deferred refresh")
    time.sleep(5)
    assert dhcp_refresh_count() == before_refreshes + 1
    assert plugin.status()["authenticated_at"] == recovered["authenticated_at"]
    assert (daemon_pid(), supplicant_pid()) == (daemon, supplicant)


def test_reauthentication_preserves_static_ipv4(plugin):
    """A static interface stays static through initial authentication and a later re-authentication."""
    try:
        set_ipv4("172.31.0.250")
        time.sleep(6)
        plugin.configure()
        assert_authenticated(plugin)
        assert ipv4("vtnet1") == "172.31.0.250"
        assert dhclient_pid() == ""
        daemon, supplicant = daemon_pid(), supplicant_pid()
        before_auth = plugin.status()["authenticated_at"]
        time.sleep(1)
        assert auth("reauth", VM_WAN_MAC).strip() == "OK"
        wait_for(lambda: plugin.status()["authenticated_at"] > before_auth, timeout=30,
                 what="re-authentication on static IPv4")
        time.sleep(5)
        assert ipv4("vtnet1") == "172.31.0.250"
        assert dhclient_pid() == ""
        assert reachable("172.31.0.1")
        assert (daemon_pid(), supplicant_pid()) == (daemon, supplicant)
    finally:
        restore_default_network(plugin)
