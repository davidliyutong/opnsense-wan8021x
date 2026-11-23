"""The plugin follows the WAN to another device (Interfaces: Assignments) without being touched."""
import time

import pytest

import vmlib
from conftest import authorized, hidden_fields, vm_sh, wait_for
from test_vlan import VLAN_PREFIX, cleanup, has_assignment_api, vlans


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


@pytest.mark.parametrize("method", ["gui", "saved"])
def test_follows_interface_reassignment(plugin, gui_session, method):
    """WAN moved to another device under Interfaces: Assignments, without touching the plugin."""
    cleanup()
    vmlib.api("POST", "interfaces/vlan_settings/add_item", {"vlan": {"if": "vtnet1", "tag": "100",
                                                                     "descr": f"{VLAN_PREFIX} move"}})
    vmlib.api("POST", "interfaces/vlan_settings/reconfigure")
    device = wait_for(vlans, timeout=10, what="VLAN 100")[0]["vlanif"].split()[0]
    try:
        plugin.configure()
        wait_for(lambda: authorized("untagged"), timeout=30, what="authentication on vtnet1")
        if method == "saved":
            move_saved(device)
        elif has_assignment_api():
            wait_for(lambda: device in vmlib.api("GET", "interfaces/assignment/get_item/wan")["interface"]["if"],
                     timeout=30, what=f"{device} to become assignable")
            move_api(device)
        else:
            session, base = gui_session
            url = f"{base}/interfaces_assign.php"
            page = session.get(url, timeout=60)
            assert page.ok and 'name="wan"' in page.text
            data = hidden_fields(page.text)
            data.update(wan=device, Submit="yes")
            response = session.post(url, data=data, allow_redirects=False, timeout=60)
            assert response.is_redirect, response.status_code
        wait_for(lambda: authorized("v100"), timeout=40, what="authentication on the new WAN device")
        assert plugin.status()["device"] == device
    finally:
        move_saved("vtnet1")
        cleanup()


def test_saved_supplicant_waits_for_apply(plugin):
    """Saving plugin changes (here: a second supplicant) triggers the configuration hooks, which
    must leave them to Apply instead of restarting the service."""
    plugin.configure()
    wait_for(lambda: authorized(), timeout=30, what="authentication")
    pid = vm_sh("pgrep -f 'wpa_supplicant -D wired' || true").strip()
    r = plugin.add(interface="lan")
    assert r["result"] == "saved", r
    time.sleep(8)  # the config hook runs asynchronously after the save
    assert vm_sh("pgrep -f 'wpa_supplicant -D wired' || true").strip() == pid
    assert [s["interface"] for s in vmlib.api("GET", "wan8021x/service/supplicants")["rows"]] == ["wan"]
