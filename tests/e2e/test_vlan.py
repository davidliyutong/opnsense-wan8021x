"""802.1X on a tagged uplink: VLANs on the WAN NIC, each assigned as its own interface."""
import json
from functools import cache

import pytest

import vmlib
from conftest import authorized, ipv4, vm_sh, wait_for

ENABLE_DHCP = """<?php
require_once 'config.inc';
$cfg = OPNsense\\Core\\Config::getInstance();
$iface = $cfg->object()->interfaces->{$argv[1]};
$iface->enable = '1';
$iface->ipaddr = 'dhcp';
unset($iface->blockpriv);
$cfg->save();
"""


VLAN_PREFIX = "wan8021x test"
IFACE_PREFIX = "WANVLAN"
LEGACY_ASSIGNMENTS = """php <<'PHP'
<?php
require_once 'config.inc';
echo json_encode(config_read_array('interfaces'));
PHP
"""

LEGACY_VLAN_ASSIGN = """<?php
require_once 'config.inc';
$cfg = OPNsense\\Core\\Config::getInstance();
$interfaces = $cfg->object()->interfaces;
for ($i = 1; isset($interfaces->{'opt' . $i}); $i++) {
}
$iface = $interfaces->addChild('opt' . $i);
$iface->if = $argv[1];
$iface->descr = $argv[2];
$cfg->save();
"""

LEGACY_VLAN_REMOVE = """<?php
require_once 'config.inc';
require_once 'auth.inc';
require_once 'util.inc';
require_once 'filter.inc';
require_once 'system.inc';
require_once 'interfaces.inc';
interface_reset($argv[1]);
$cfg = OPNsense\\Core\\Config::getInstance();
unset($cfg->object()->interfaces->{$argv[1]});
$cfg->save();
"""


def vlans():
    return [r for r in vmlib.api("GET", "interfaces/vlan_settings/search_item")["rows"]
            if r["descr"].startswith(VLAN_PREFIX)]


@cache
def has_assignment_api():
    controller = "/usr/local/opnsense/mvc/app/controllers/OPNsense/Interfaces/Api/AssignmentController.php"
    return vmlib.ssh(f"test -f {controller}", check=False).returncode == 0


def assignments():
    if has_assignment_api():
        rows = vmlib.api("GET", "interfaces/assignment/search_item")["rows"]
    else:
        rows = [{**interface, "identifier": name} for name, interface in json.loads(vm_sh(LEGACY_ASSIGNMENTS)).items()]
    return [r for r in rows if r.get("descr", "").startswith(IFACE_PREFIX)]


def cleanup():
    """Remove whatever a previous (possibly aborted) run left behind."""
    for row in assignments():
        name = row["identifier"]
        if has_assignment_api():
            # interfaces assigned through the API start out locked
            vmlib.api("POST", f"interfaces/assignment/set_item/{name}", {"interface": {"lock": "0"}})
            vmlib.api("POST", f"interfaces/assignment/del_item/{name}")
        else:
            vmlib.ssh(f"cat > /tmp/wan8021x-vlan.php && php /tmp/wan8021x-vlan.php {name}", input=LEGACY_VLAN_REMOVE)
    if has_assignment_api():
        vmlib.api("POST", "interfaces/assignment/reconfigure")
    for row in vlans():
        vmlib.api("POST", f"interfaces/vlan_settings/del_item/{row['uuid']}")
    vmlib.api("POST", "interfaces/vlan_settings/reconfigure")
    assert not vlans() and not assignments(), "test VLANs could not be removed"


def add_vlan_iface(tag):
    """VLAN <tag> on vtnet1, assigned with DHCP; returns (ifname, device)."""
    vmlib.api("POST", "interfaces/vlan_settings/add_item", {"vlan": {"if": "vtnet1", "tag": str(tag),
                                                                     "descr": f"{VLAN_PREFIX} {tag}"}})
    vmlib.api("POST", "interfaces/vlan_settings/reconfigure")
    vlan = wait_for(lambda: [r for r in vlans() if r["tag"] == str(tag)], timeout=10, what=f"VLAN {tag}")[0]
    device = vlan["vlanif"].split()[0]  # "vlan01 [WANVLAN100]" once assigned
    description = f"{IFACE_PREFIX}{tag}"
    if has_assignment_api():
        wait_for(lambda: device in vmlib.api("GET", "interfaces/assignment/get_item")["interface"]["if"],
                 timeout=30, what=f"{device} to become assignable")
        r = vmlib.api("POST", "interfaces/assignment/add_item", {"interface": {"if": device, "descr": description}})
        assert r["result"] == "saved", r
        vmlib.api("POST", "interfaces/assignment/reconfigure")
    else:
        vmlib.ssh(f"cat > /tmp/wan8021x-vlan.php && php /tmp/wan8021x-vlan.php {device} {description}",
                  input=LEGACY_VLAN_ASSIGN)
    ifname = [r for r in assignments() if r["if"] == device][0]["identifier"]
    vmlib.ssh(f"cat > /tmp/dhcp.php && php /tmp/dhcp.php {ifname} && configctl interface reconfigure {ifname}",
              input=ENABLE_DHCP)
    return ifname, device


@pytest.fixture(scope="module")
def vlan_ifaces():
    """{tag: (ifname, device)} for VLAN 100 and 200 on the WAN NIC."""
    cleanup()
    try:
        yield {tag: add_vlan_iface(tag) for tag in (100, 200)}
    finally:
        cleanup()


def test_vlan_uplink(plugin, vlan_ifaces):
    ifname, device = vlan_ifaces[100]
    plugin.configure(interface=ifname)
    wait_for(lambda: authorized("v100"), timeout=30, what="VLAN 100 port to be authorized")
    assert not authorized("untagged"), "the untagged port must stay closed"
    row = wait_for(lambda: (s := plugin.status(ifname)) and s.get("status") == "authorized" and s,
                   timeout=30, what="supplicant on the VLAN to report authorized")
    assert row["device"] == device
    wait_for(lambda: ipv4(device).startswith("172.31.100."), timeout=60, what="DHCP lease on VLAN 100")
    assert "1 packets received" in vm_sh("ping -c 1 -t 2 172.31.100.1 2>&1", check=False)


def test_two_vlans_together(plugin, vlan_ifaces):
    """Two supplicants side by side on one uplink, e.g. internet and IPTV VLANs.

    (Untagged + VLAN on the same NIC is not used here: the Linux authenticator's raw socket on
    the parent also receives the tagged frames, which disturbs its untagged exchange.)"""
    plugin.add(interface=vlan_ifaces[100][0])
    plugin.configure(interface=vlan_ifaces[200][0], identity="bob", password="bob-secret")
    wait_for(lambda: authorized("v100") and authorized("v200"), timeout=40, what="both ports to be authorized")
    rows = vmlib.api("GET", "wan8021x/service/supplicants")["rows"]
    assert sorted(r["status"] for r in rows) == ["authorized", "authorized"]
