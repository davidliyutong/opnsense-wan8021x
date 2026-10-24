English | [简体中文](research.zh-CN.md)

# Research and Spike Results

Environment: OPNsense 26.7 (FreeBSD 14, nano image), virtio-net (vtnet1 = WAN); the authenticator is hostapd 2.11 wired with the built-in EAP server.
The spike scripts are in the `spikes/` directory.

## Background Research

* Neither OPNsense nor pfSense has a GUI for 802.1X on a wired WAN port. The community solution is pfatt/opnatt
  ([opnatt-supplicant.sh](https://git.hhf.technology/hhf/pfatt/src/branch/supplicant/bin/opnatt-supplicant.sh)),
  which essentially starts wpa_supplicant from a shell script in an early syshook.
* Two wpa_supplicant binaries exist, both v2.11 with the `wired` driver:
  * `/usr/sbin/wpa_supplicant`: FreeBSD base; `CONFIG_DRIVER_WIRED` is defined in `usr.sbin/wpa/Makefile.inc`
  * `/usr/local/sbin/wpa_supplicant`: the ports package `wpa_supplicant-2.11_7`, which is what core's Wi-Fi client uses (`interfaces.inc`)
  * **Decision: use `/usr/local/sbin/wpa_supplicant`**, consistent with core and updated together with OPNsense firmware.
  * Neither supports `-f` for writing a log file (built without `CONFIG_DEBUG_FILE`); use `-s` (syslog) or `daemon -o` instead.
* `interface_configure()` has no plugin hook before dhclient is started; neither does `rc.linkup` (triggered by devd).
* Plugin framework: `plugins.inc.d/<name>.inc` provides `_services`, `_configure` (events such as `early`, `bootup`), `_syslog` and `_xmlrpc_sync`.
  Reference implementation: `vendor/opnsense-plugins/net/ndp-proxy-go` (MVC + configd + rc + syslog).
* The test VM's root shell is csh, so remote scripts must be run with `sh -s`.

## S1 — Wired PEAP Works ✅

`wpa_supplicant -D wired -i vtnet1`, configured with `ap_scan=0`, `key_mgmt=IEEE8021X`, `eap=PEAP`, `phase2="auth=MSCHAPV2"`, `eapol_flags=0`:

* EAP-SUCCESS in about 2 seconds (TLSv1.2, ECDHE-RSA-AES256-GCM-SHA384). Once the port is authorized, OPNsense's own dhclient obtains 172.31.0.x on the WAN.
* Transmitted EAPOL frames go to the PAE group address `01:80:c2:00:00:03`. The driver joins that multicast group via `SIOCADDMULTI`.
* `wpa_cli status` directly provides the fields the status page needs: `Supplicant PAE state`, `suppPortStatus`, `EAP state`, `selectedMethod`, `EAP-PEAPv1 Phase2 method`.

## S2 — Startup Ordering and DHCP ✅

* Starting the supplicant after the port has been unauthorized for 120 seconds (dhclient already in backoff): EAP succeeds in 3 seconds, **lease obtained in 6 seconds**. FreeBSD dhclient's backoff ceiling is short.
* This experiment only covered a client without a lease. Real networks may provide a guest/quarantine lease before authentication and then move the port to another subnet; an existing valid lease prevents dhclient from immediately requesting a new address.
* **Corrected conclusion: first authorization and recovery from lost authorization must trigger a fresh IPv4 DHCP exchange.** The plugin asynchronously stops the interface's core DHCP supervisor, clears the old lease and dynamic IPv4 address, and calls core's `interface_dhcp_configure()`. The normal DHCP BOUND callback updates routes, DNS and related services; static IPv4 is skipped. The heavy `interface reconfigure` remains unnecessary and would disturb the link and authentication.
* EAP-STARTED and the UI's authenticating state do not imply loss of authorization. Track authorization separately so successful periodic or manual re-authentication can preserve DHCP. During one daemon run, a 30-second interval coalesces refreshes per interface while retaining recovery requests until they can run. DHCP PID and lease-file modification time alone cannot prove that a client obtained a lease after authorization, so neither is used to skip a needed refresh. A subnet change while authorization remains in place requires an additional network-change signal and is outside this trigger policy.

## S3 — VLAN Subinterfaces ✅

* After `ifconfig vlan create vlan 100 vlandev vtnet1`, running the wired supplicant on the VLAN device authenticates successfully and obtains an address from the VLAN 100 subnet.
* Note: pfatt has documented that some real NICs (igb/ix + netgraph) need `-vlanhwtag -vlanhwfilter -vlanhwtso`. This cannot be reproduced on virtio.
  The plugin can offer a "disable VLAN hardware offload on the parent interface" option (M4).

## S4 — EAPOL Destination Address ⚠️

* When the authenticator replies by unicast (`use_pae_group_addr=0`), authentication still succeeds; frames sent by the supplicant still go to the PAE group address.
* wpa_supplicant (wired driver) has **no configuration option to change the TX destination MAC**: `bssid` is fixed to the PAE group address.
* What the first release can do:
  * Use the MAC cloning (spoofmac) built into OPNsense interfaces for cases that require a specific source MAC; no extra development needed.
  * Optionally enable `IFF_ALLMULTI` or promisc to receive EAPOL sent to other link-local group addresses (e.g. `01:80:c2:00:00:00`/`0e`).
* A truly custom destination MAC requires patching wpa_supplicant or implementing our own EAPOL transmitter. **Deferred until there is a real need** (an optional follow-up item in the ROADMAP).

## S5 — Failure and Recovery (the plugin must handle this) ⚠️

| Scenario | Result |
|---|---|
| Wrong password | `PAE state=HELD`, `EAP state=FAILURE`, `CTRL-EVENT-EAP-FAILURE` |
| CA mismatch | `CTRL-EVENT-EAP-TLS-CERT-ERROR reason=1 … err='self-signed certificate in certificate chain'` |
| Correct CA + `domain_suffix_match` | Success |
| **Cable unplugged for 5 seconds, switch port reset** | **No recovery within 60 seconds**: the FreeBSD wired driver does not track link state, so the supplicant still believes it is AUTHENTICATED; hostapd does not re-initiate on its own either |
| Then running `wpa_cli reauthenticate` | Authorization restored within 4 seconds |

**Conclusion: the plugin must watch for link-up events on the WAN (and on the VLAN parent interface) and trigger `wpa_cli reauthenticate`.**
`rc.linkup` has no plugin hook; the options are:

1. Ship a devd rule with the plugin (`/usr/local/etc/devd/`) that runs `configctl wan8021x linkup <dev>` on LINK_UP. Need to confirm that devd runs multiple notify rules for the same event.
2. Give each supplicant a lightweight watcher (`route -n monitor` or kqueue), independent of devd.

**Verified (M3)**: devd runs only the highest-priority notify rule for a given event. The plugin's own rule (priority 0 or 101) was never executed,
while core's `rc.linkup` ran as usual. The only way to make it work would be to override core's rule with a higher priority, which is too fragile, **so option 2 was adopted**:
the daemon parses `iface#N <dev> admin UP oper UP|DOWN` lines from `route -n monitor` and sends `REAUTHENTICATE` to the ctrl socket when the link goes from DOWN to UP.
VLAN subinterfaces generate events together with their parent, so only the supplicant's own device needs to be monitored.

In addition, the failure reason (wrong password or certificate error) must be shown on the status page: it is parsed from wpa_cli events (`CTRL-EVENT-EAP-FAILURE`, `CTRL-EVENT-EAP-TLS-CERT-ERROR`) and written to the status file.

## Impact on Plugin Design (Changes Relative to the ROADMAP)

1. Use `/usr/local/sbin/wpa_supplicant -D wired`, logging to syslog via `-s`.
2. Obtain a fresh IPv4 DHCP lease asynchronously on first authorization and authorization recovery, including when an old subnet's lease is still valid; preserve DHCP during re-authentication that retains authorization and limit refresh frequency.
3. **New: re-authenticate on link up** (included already in M3; otherwise the connection is lost after unplugging the cable).
4. Each supplicant gets a `wpa_cli -a` action script that records the latest events and failure reason for the status page.
5. Escape identity and password correctly according to wpa_supplicant syntax, avoiding the direct-interpolation problem in core's Wi-Fi code.

## Findings During M3/M4 Implementation

* `UpdateOnlyTextField::__toString()` always returns an empty string (to prevent echoing the value back). Config generation must use `getValue()`, otherwise the password is empty.
* With an empty password, wpa_supplicant emits `CTRL-REQ-PASSWORD` and waits forever, so it appears "stuck" rather than failed.
  The daemon turns `CTRL-REQ-*` into a "credentials incomplete" error.
* User-supplied identity, password and domain names are always written to the wpa_supplicant config as hex, eliminating quoting and escaping problems at the root
  (tested with passwords containing `\`, UTF-8 and `"`).
* Core's interface settings already include `promisc` and `disablevlanhwfilter`, so the plugin no longer duplicates these two options.
* Package lifecycle: core's `rc.configure_plugins` does not start services at POST_INSTALL. The plugin ships
  `+PRE_DEINSTALL.pre` (stop the service), `+POST_INSTALL.post` (restart the service if enabled) and `+POST_DEINSTALL.post` (cleanup).
* The interface assignment API new in 26.7 (`interfaces/assignment/*`) only handles the assignment itself; setting the IP mode still goes through the legacy config.
  Interfaces assigned via the API are locked by default and must be unlocked before they can be deleted.
* Upstream `make lint` depends on BSD find and sh, so it runs in the VM (requires syncing core's `Mk/`, `Scripts/` and `contrib/parallel-lint`);
  phpcs and pycodestyle run in the dev container using core's `ruleset.xml`.
