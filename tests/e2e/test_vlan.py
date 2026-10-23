"""802.1X on a tagged uplink: VLAN 100 on the WAN NIC, assigned as its own interface."""
import pytest

import vmlib
from conftest import authorized, ipv4, vm_sh, wait_for

VLAN_DESCR = "wan8021x test"
IFACE_DESCR = "WANVLAN"

ENABLE_DHCP = """<?php
require_once 'config.inc';
$cfg = OPNsense\\Core\\Config::getInstance();
$iface = $cfg->object()->interfaces->{$argv[1]};
$iface->enable = '1';
$iface->ipaddr = 'dhcp';
unset($iface->blockpriv);
$cfg->save();
"""


@pytest.fixture(scope="module")
def vlan_iface():
    """Create VLAN 100 on vtnet1, assign it with DHCP; tear everything down afterwards."""
    vlans = [r for r in vmlib.api("GET", "interfaces/vlan_settings/search_item")["rows"] if r["descr"] == VLAN_DESCR]
    if not vlans:
        vmlib.api("POST", "interfaces/vlan_settings/add_item", {"vlan": {"if": "vtnet1", "tag": "100",
                                                                         "descr": VLAN_DESCR}})
        vmlib.api("POST", "interfaces/vlan_settings/reconfigure")
        vlans = [r for r in vmlib.api("GET", "interfaces/vlan_settings/search_item")["rows"]
                 if r["descr"] == VLAN_DESCR]
    device = vlans[0]["vlanif"].split()[0]  # "vlan01 [WANVLAN]" once assigned
    assigned = [r for r in vmlib.api("GET", "interfaces/assignment/search_item")["rows"] if r["if"] == device]
    if not assigned:
        vmlib.api("POST", "interfaces/assignment/add_item", {"interface": {"if": device, "descr": IFACE_DESCR}})
        vmlib.api("POST", "interfaces/assignment/reconfigure")
        assigned = [r for r in vmlib.api("GET", "interfaces/assignment/search_item")["rows"] if r["if"] == device]
    ifname = assigned[0]["identifier"]
    vmlib.ssh(f"cat > /tmp/dhcp.php && php /tmp/dhcp.php {ifname} && configctl interface reconfigure {ifname}",
              input=ENABLE_DHCP)
    yield ifname, device
    # interfaces assigned through the API start out locked
    vmlib.api("POST", f"interfaces/assignment/set_item/{ifname}", {"interface": {"lock": "0"}})
    vmlib.api("POST", f"interfaces/assignment/del_item/{ifname}")
    vmlib.api("POST", "interfaces/assignment/reconfigure")
    vmlib.api("POST", f"interfaces/vlan_settings/del_item/{vlans[0]['uuid']}")
    vmlib.api("POST", "interfaces/vlan_settings/reconfigure")


def test_vlan_uplink(plugin, vlan_iface):
    ifname, device = vlan_iface
    plugin.configure(interface=ifname)
    wait_for(lambda: authorized("v100"), timeout=30, what="VLAN 100 port to be authorized")
    assert not authorized("untagged"), "the untagged port must stay closed"
    row = wait_for(lambda: (s := plugin.status(ifname)) and s.get("port") == "Authorized" and s,
                   timeout=30, what="supplicant on the VLAN to report Authorized")
    assert row["device"] == device
    wait_for(lambda: ipv4(device).startswith("172.31.100."), timeout=60, what="DHCP lease on VLAN 100")
    assert "1 packets received" in vm_sh("ping -c 1 -t 2 172.31.100.1 2>&1", check=False)


def test_wan_and_vlan_together(plugin, vlan_iface):
    """Two supplicants side by side, one per port."""
    ifname, _device = vlan_iface
    plugin.add(interface="wan")
    plugin.configure(interface=ifname, identity="bob", password="bob-secret")
    wait_for(lambda: authorized("untagged") and authorized("v100"), timeout=40, what="both ports to be authorized")
    assert len(vmlib.api("GET", "wan8021x/service/supplicants")["rows"]) == 2
