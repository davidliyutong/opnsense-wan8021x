"""Package removal while running leaves nothing behind; reinstall restores the service."""
import pytest

from conftest import authorized, vm_sh, wait_for

TREE = "/root/plugins/net/wan8021x"


def running():
    return vm_sh("pgrep -f 'wan8021xd.py|wpa_supplicant -D wired' || true").strip()


@pytest.fixture
def package():
    name = vm_sh("opnsense-version -n wan8021x").strip()
    assert name in ("os-wan8021x", "os-wan8021x-devel"), name
    return name


def test_preinstall_rejects_unsupported_series(package):
    """A real pkg add must leave the target untouched when its core is unsupported."""
    devel = "" if package == "os-wan8021x" else "yes"
    vm_sh(f"""set -eu
cd {TREE}
make package PLUGIN_DEVEL={devel} >/dev/null
pkgfile={TREE}/work/pkg/{package}-$(opnsense-version -v wan8021x).pkg

target=$(mktemp -d)
trap 'rm -rf "$target"' EXIT
mkdir -p "$target/bin" "$target/libexec" "$target/usr/local/sbin" "$target/var/db/pkg"
cp /bin/sh "$target/bin/"
cp /libexec/ld-elf.so.1 "$target/libexec/"
for lib in $(ldd /bin/sh | awk '$3 ~ "^/" {{print $3}}'); do
    mkdir -p "$target$(dirname "$lib")"
    cp "$lib" "$target$lib"
done
cat > "$target/usr/local/sbin/opnsense-version" <<'VERSION'
#!/bin/sh
case "$1" in
    -V) echo 25.7 ;;
    -v) echo 25.7.12 ;;
esac
VERSION
chmod 755 "$target/usr/local/sbin/opnsense-version"
test "$(chroot "$target" /usr/local/sbin/opnsense-version -V)" = 25.7

output=$(pkg -r "$target" add "$pkgfile" 2>&1) || :
printf '%s\\n' "$output"
printf '%s\\n' "$output" | grep -F 'found 25.7.12' >/dev/null
test ! -e "$target/usr/local/etc/rc.d/wan8021x"
test ! -e "$target/usr/local/opnsense/version/wan8021x"
if pkg -r "$target" info -e {package}; then
    exit 1
fi
""")


def test_uninstall_and_reinstall(plugin, package):
    plugin.configure()
    wait_for(lambda: authorized(), timeout=30, what="authentication")
    assert running()

    devel = "" if package == "os-wan8021x" else "yes"
    vm_sh(f"cd {TREE} && make package PLUGIN_DEVEL={devel} >/dev/null && pkg delete -y {package} >/dev/null")
    try:
        wait_for(lambda: not running(), timeout=20, what="daemon and supplicant to stop on removal")
        leftovers = vm_sh("ls /usr/local/etc/rc.d/wan8021x /usr/local/opnsense/scripts/OPNsense/Wan8021x "
                          "/usr/local/etc/inc/plugins.inc.d/wan8021x.inc /var/etc/wan8021x 2>/dev/null || true")
        assert leftovers.strip() == ""
    finally:
        # configuration survives in config.xml, reinstalling brings the port back up
        vm_sh(f"pkg add {TREE}/work/pkg/*.pkg >/dev/null")
    vm_sh("configctl wan8021x start >/dev/null")
    wait_for(lambda: authorized(), timeout=30, what="authentication after reinstall")


def test_upgrade_keeps_running(plugin, package):
    plugin.configure()
    wait_for(lambda: authorized(), timeout=30, what="authentication")
    before = running()
    devel = "" if package == "os-wan8021x" else "yes"
    vm_sh(f"cd {TREE} && make upgrade PLUGIN_DEVEL={devel} >/dev/null 2>&1")
    after = wait_for(running, timeout=20, what="service to come back after upgrade")
    assert after != before, "the daemon should have been restarted with the new code"
    assert plugin.service_status() == "running"
    wait_for(lambda: plugin.status() and plugin.status().get("port") == "Authorized", timeout=30,
             what="port authorized after upgrade")
