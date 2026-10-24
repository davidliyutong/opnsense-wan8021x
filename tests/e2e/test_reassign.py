"""The plugin follows the WAN to another device (Interfaces: Assignments) without being touched."""
import pytest

import vmlib
from conftest import authorized, wait_for
from test_vlan import VLAN_PREFIX, cleanup, vlans


MOVE_WAN = """<?php
require_once 'config.inc';
$cfg = OPNsense\\Core\\Config::getInstance();
$cfg->object()->interfaces->wan->if = $argv[1];
$cfg->save();
"""


def move_saved(device):
    """Mapping saved first, then the interface reconfigured (console, scripts): the 'dhcp' hook."""
    vmlib.ssh(f"cat > /tmp/move.php && php /tmp/move.php {device} && configctl interface reconfigure wan",
              input=MOVE_WAN)


def move_api(device):
    """As the GUI does it: the new device is configured before the mapping is saved."""
    r = vmlib.api("POST", "interfaces/assignment/set_item/wan", {"interface": {"if": device}})
    assert r["result"] == "saved", r
    assert vmlib.api("POST", "interfaces/assignment/reconfigure")["status"] == "ok"


@pytest.mark.parametrize("move", [move_api, move_saved])
def test_follows_interface_reassignment(plugin, move):
    """WAN moved to another device under Interfaces: Assignments, without touching the plugin."""
    cleanup()
    vmlib.api("POST", "interfaces/vlan_settings/add_item", {"vlan": {"if": "vtnet1", "tag": "100",
                                                                     "descr": f"{VLAN_PREFIX} move"}})
    vmlib.api("POST", "interfaces/vlan_settings/reconfigure")
    device = wait_for(vlans, timeout=10, what="VLAN 100")[0]["vlanif"].split()[0]
    try:
        plugin.configure()
        wait_for(lambda: authorized("untagged"), timeout=30, what="authentication on vtnet1")
        if move is move_api:
            wait_for(lambda: device in vmlib.api("GET", "interfaces/assignment/get_item/wan")["interface"]["if"],
                     timeout=30, what=f"{device} to become assignable")
        move(device)
        wait_for(lambda: authorized("v100"), timeout=40, what="authentication on the new WAN device")
        assert plugin.status()["device"] == device
    finally:
        move_saved("vtnet1")
        cleanup()
