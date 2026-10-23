"""Authentication against the emulated switch port (hostapd wired, EAP server built in)."""
import pytest

import vmlib
from conftest import auth, authorized, ipv4, vm_sh, wait_for


def wan_reachable():
    """The data path through the port works (it only opens once authorized)."""
    return "1 packets received" in vm_sh("ping -c 1 -t 2 172.31.0.1 2>&1", check=False)


def assert_authenticated(plugin, interface="wan", port="untagged"):
    wait_for(lambda: authorized(port), timeout=30, what="authenticator to authorize the port")
    row = wait_for(lambda: (s := plugin.status(interface)) and s.get("port") == "Authorized" and s,
                   timeout=30, what="supplicant to report Authorized")
    assert row["eap_state"] == "SUCCESS"
    assert row["state"] == "authenticated"
    assert row["last_error"] == ""
    return row


@pytest.mark.parametrize("method,phase2,inner", [
    ("PEAP", "MSCHAPV2", "MSCHAPV2"),
    ("TTLS", "MSCHAPV2", "MSCHAPV2"),
    ("TTLS", "PAP", "PAP"),
])
def test_methods(plugin, method, phase2, inner):
    plugin.configure(eap_method=method, phase2=phase2)
    row = assert_authenticated(plugin)
    assert row["method"] == method
    assert inner in row["phase2"]
    assert plugin.service_status() == "running"
    wait_for(wan_reachable, timeout=30, what="traffic through the port")
    assert ipv4("vtnet1").startswith("172.31.0.")


def test_outer_identity(plugin):
    plugin.configure(anonymous_identity="anonymous@example.test")
    assert_authenticated(plugin)


def test_wrong_password(plugin):
    plugin.configure(password="not-the-password")
    row = wait_for(lambda: (s := plugin.status()) and s["state"] == "failed" and s,
                   timeout=30, what="failure to be reported")
    assert "rejected" in row["last_error"]
    assert row["port"] == "Unauthorized"
    assert not authorized()
    assert not wan_reachable()


def test_server_validation(plugin, ca_refs):
    plugin.configure(ca=ca_refs["ca"], domain_match="example.test")
    assert_authenticated(plugin)


def test_rogue_server_rejected(plugin, ca_refs):
    plugin.configure(ca=ca_refs["rogue-ca"])
    row = wait_for(lambda: (s := plugin.status()) and s["state"] == "failed" and s,
                   timeout=30, what="certificate failure to be reported")
    assert "certificate" in row["last_error"]
    assert not authorized()


def test_wrong_server_domain(plugin, ca_refs):
    plugin.configure(ca=ca_refs["ca"], domain_match="other.test")
    row = wait_for(lambda: (s := plugin.status()) and s["state"] == "failed" and s,
                   timeout=30, what="domain mismatch to be reported")
    assert "certificate" in row["last_error"]


def test_special_characters_in_credentials(plugin):
    """Quotes, backslashes and non-ASCII must reach the server unchanged (hex encoding in the config)."""
    plugin.configure(identity='carol \\ \u00fc', password='p"a\\ss w0rd#; \u00fc=}')
    assert_authenticated(plugin)


def test_link_loss_reauthenticates(plugin):
    """After a cable pull the switch resets the port; the plugin must authenticate again on link up."""
    plugin.configure()
    assert_authenticated(plugin)
    plugin_status_before = plugin.status()
    auth("flap", "3")
    wait_for(lambda: authorized(), timeout=30, what="re-authentication after link up")
    wait_for(wan_reachable, timeout=30, what="traffic after link up")
    assert plugin.status()["authenticated_at"] > plugin_status_before["authenticated_at"]


def test_manual_reauthenticate(plugin):
    plugin.configure()
    assert_authenticated(plugin)
    auth("reset")
    assert not authorized()
    r = vmlib.api("POST", "wan8021x/service/reauthenticate/wan")
    assert r["status"] == "ok", r
    wait_for(lambda: authorized(), timeout=30, what="re-authentication")


def test_disable_stops_service(plugin):
    plugin.configure()
    assert_authenticated(plugin)
    plugin.reset()
    assert plugin.service_status() == "disabled"
    assert vm_sh("pgrep -f 'wpa_supplicant -D wired' || true").strip() == ""
