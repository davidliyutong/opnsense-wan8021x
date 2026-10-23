"""Model validation, secret handling and the GUI page."""
import re

import requests

import vmlib
from conftest import authorized, vm_sh, wait_for


def test_pap_requires_ttls(plugin):
    r = plugin.add(eap_method="PEAP", phase2="PAP")
    assert r["result"] == "failed"
    assert "supplicant.phase2" in r["validations"]


def test_domain_requires_ca(plugin):
    r = plugin.add(domain_match="example.test")
    assert r["result"] == "failed"
    assert "supplicant.domain_match" in r["validations"]


def test_one_supplicant_per_interface(plugin):
    assert plugin.add()["result"] == "saved"
    r = plugin.add()
    assert r["result"] == "failed"
    assert "supplicant.interface" in r["validations"]


def test_line_breaks_rejected(plugin):
    r = plugin.add(identity="alice\nnetwork={")
    assert r["result"] == "failed"
    assert "supplicant.identity" in r["validations"]


def test_password_is_write_only(plugin):
    uuid = plugin.configure()
    assert vmlib.api("GET", f"wan8021x/settings/get_supplicant/{uuid}")["supplicant"]["password"] == ""
    # saving without a password keeps the stored one
    r = vmlib.api("POST", f"wan8021x/settings/set_supplicant/{uuid}", {"supplicant": {"identity": "alice"}})
    assert r["result"] == "saved", r
    plugin.apply()
    assert "password=" + b"alice-secret".hex() in vm_sh("cat /var/etc/wan8021x/vtnet1.conf")


def test_secrets_not_exposed(plugin):
    plugin.configure()
    listing = vm_sh("ls -ld /var/etc/wan8021x /var/etc/wan8021x/vtnet1.conf")
    assert listing.startswith("drwx------")
    assert "\n-rw-------" in "\n" + listing.split("\n", 1)[1]
    logs = vm_sh("cat /var/log/wan8021x/*.log /var/log/system/*.log 2>/dev/null")
    assert "alice-secret" not in logs
    assert b"alice-secret".hex() not in logs


def test_gui_page():
    """The settings page renders (volt + forms compile) for a logged in user."""
    s = requests.Session()
    s.verify = False
    base = f"https://127.0.0.1:{vmlib.GUI_PORT}"
    form = s.get(f"{base}/").text
    data = {"usernamefld": "root", "passwordfld": "opnsense", "login": "1"}
    data.update(re.findall(r'<input type="hidden" name="([^"]+)" value="([^"]*)"', form))
    s.post(f"{base}/", data=data, allow_redirects=False)  # the redirect drops the forwarded port
    page = s.get(f"{base}/ui/wan8021x")
    assert page.status_code == 200
    assert "supplicantStatus" in page.text
    assert "/api/wan8021x/settings/search_supplicant" in page.text


def test_log_lines_not_double_prefixed(plugin):
    plugin.configure()
    wait_for(lambda: authorized(), timeout=30, what="authentication")
    logs = vm_sh("cat /var/log/wan8021x/*.log")
    assert "CTRL-EVENT-EAP-SUCCESS" in logs
    assert "vtnet1: vtnet1:" not in logs.split("starting supplicant")[-1]
