English | [简体中文](ROADMAP.zh-CN.md)

# OPNsense WAN 802.1X Plugin: Environment Setup and Development Roadmap

## Progress (2026-10-23)

| Milestone | Status |
|---|---|
| M0 Skeleton | ✅ |
| M1 Test environment | ✅ Golden image builds in about 1 minute, `make reset` takes about 20 seconds |
| M2 Spike | ✅ Findings in research.md (active re-authentication is needed after a cable unplug; the EAPOL destination MAC cannot be customized) |
| M3 Plugin MVP | ✅ PEAP/TTLS, status page, manual re-authentication, automatic re-authentication on link up |
| M4 Robustness | ✅ VLAN, multiple interfaces, recovery after reboot, failure reasons, logging, protection of sensitive data, upgrade and uninstall |
| M5 e2e | ✅ 24 test cases; `make check` runs from a fresh VM in about 3 minutes |
| M6 Packaging | 🟡 `make package` works; not yet submitted upstream, documentation still to be completed (screenshots, user manual) |

Differences from the original plan: first authorization and authorization recovery trigger an asynchronous fresh IPv4 DHCP exchange instead of a full `interface reconfigure` (S2 only tested initial lease acquisition and missed authenticated subnet changes; its conclusion has been corrected); re-authentication that retains authorization preserves the lease, and refreshes are rate limited;
link monitoring uses `route -n monitor` instead of devd (devd only runs the highest-priority matching rule);
the promisc option was removed (the core interface settings already provide it).

---


## Context

OPNsense (currently 26.7.x, based on FreeBSD 14) has no GUI feature for 802.1X authentication on a wired WAN port. The only existing community solutions are shell scripts in the style of pfatt/opnatt ([opnatt-supplicant.sh](https://git.hhf.technology/hhf/pfatt/src/branch/supplicant/bin/opnatt-supplicant.sh)), which are hard to maintain. Goal: build a plugin that follows the opnsense/plugins conventions and lets the user configure PEAP / TTLS (MSCHAPv2) authentication for WAN (a physical port or a VLAN subinterface) in the GUI, together with a test environment built on Docker + KVM that can be reset with a single command. The whole toolchain lives in the current directory and is managed with git.

Confirmed facts (research findings):
- Host: Docker 29.8, `/dev/kvm` available, 16 cores / 60G RAM, 1.3T of free disk; no libvirt installed (and none needed); the project directory is empty.
- The FreeBSD base system builds wpa with `-DCONFIG_DRIVER_WIRED` (`usr.sbin/wpa/Makefile.inc`), so `wpa_supplicant -D wired` works on OPNsense. OPNsense core's own Wi-Fi client uses `/usr/local/sbin/wpa_supplicant` (`interfaces.inc:1859-2031`), and the plugin can reuse its approach to config generation and certificate export directly.
- `interface_configure()` (`interfaces.inc:2233`) has **no plugin hook** before DHCP starts; it only calls `plugins_configure('ipsec'|'dhcp'|'dns'|'updateip')` afterwards. The supplicant therefore has to run as a standalone service started in the `early` boot stage; after successful authentication, an event script triggers a fresh DHCP lease on WAN.
- Plugin hooks all live in `plugins.inc.d/<name>.inc`: `_services`, `_configure` (event → task), `_syslog`, `_devices`, and so on.
- The official **nano image** is a preinstalled system with a serial console, which makes it a good fit for fast resets using a qcow2 golden image plus overlays.

Choices already made by the user: the first release supports **PEAP/TTLS (MSCHAPv2)**; **both physical ports and VLANs are supported**, with options for the EAPOL destination address; the plugin lives in a **standalone repository that follows the opnsense/plugins directory layout**.

---

## 1. Repository Layout (current directory `/home/liyutong/Projects/opnsense-802-1x`)

```
.
├── Makefile                     # single entry point: env-*, vm-*, deploy, test, lint, package
├── README.md / docs/
│   ├── ROADMAP.md               # this roadmap (saved copy)
│   ├── research.md              # research and spike findings
│   └── testenv.md               # test environment topology and usage
├── env/                         # test environment (fully Dockerized)
│   ├── compose.yml
│   ├── versions.env             # OPNsense version + sha256, base image digests, all pinned
│   ├── vm/      Dockerfile, entrypoint.sh       # debian:trixie@digest + qemu-system-x86 + qemu-utils + iproute2 + nftables
│   ├── auth/    Dockerfile, hostapd*.conf, eap_user, portctl.sh, dnsmasq.conf, gen-certs.sh
│   ├── dev/     Dockerfile      # php-cli, phpcs, python3 + pytest + pexpect + paramiko + requests, xmllint, shellcheck
│   └── provision/ bootstrap.py, config.xml.j2   # serial-console automation that builds the golden image
├── tools/bin/                   # wrapper scripts: vm-ssh, vm-console, vm-api, in-dev (runs inside the dev container)
├── vendor/opnsense-plugins      # git submodule pinned to the tag matching 26.7; provides Mk/ and lint rules
├── Mk -> vendor/opnsense-plugins/Mk   # symlink so net/wan8021x/Makefile can include ../../Mk/plugins.mk
├── net/wan8021x/                # the plugin itself (upstream layout, ready for a PR later)
│   ├── Makefile, pkg-descr
│   └── src/…                    # see section 3
├── tests/e2e/                   # pytest scenarios
└── .cache/  (gitignored)        # OPNsense image, golden.qcow2, overlays, ssh keys, certificates, serial logs
```

The host only needs docker and git. Every other tool (qemu, php, Python dependencies, certificate tools, etc.) is baked into `env/*/Dockerfile` and built locally by `make tools`.

Git: run `git init -b main`; `.gitignore` excludes `.cache/`; commit once per completed milestone; no remote is configured and nothing is pushed.

## 2. Test Environment (Docker + KVM)

### Topology

```
 host 127.0.0.1:8443 ─┐                       ┌─ container "auth" (shares the vm container's netns)
 host 127.0.0.1:2222 ─┤ QEMU user-net         │   hostapd -D wired (built-in EAP server: PEAP/TTLS-MSCHAPv2)
                      │  hostfwd → vtnet0 LAN │   nftables netdev ingress: unauthorized MACs may only send 0x888e
 container "vm"       │                       │   hostapd_cli -a portctl.sh: add/remove authorized MACs on auth success/disconnect
  qemu-system-x86_64 -enable-kvm              │   dnsmasq: serves DHCP on tap-wan (and tap-wan.100)
   vtnet0 = LAN/management (10.0.2.15)        │
   vtnet1 = WAN ── tap-wan ───────────────────┘   (VLAN scenario: a second hostapd instance on tap-wan.100)
```

- WAN is attached directly to a tap device **without going through a Linux bridge**, which avoids the bridge dropping 01:80:c2:00:00:03 by default (working around it with `group_fwd_mask` is possible but unreliable).
- The authenticator uses hostapd's built-in EAP server (Debian's hostapd is built with the wired driver and PEAP/TTLS/MSCHAPv2), and nftables plus a set of authorized MACs simulate the authorized/unauthorized state of a switch port. A FreeRADIUS container can be added later as a backend (optional).
- The vm container needs `devices: /dev/kvm, /dev/net/tun` and `cap_add: NET_ADMIN`; ports bind only to 127.0.0.1; serial output goes to `.cache/run/serial.sock` and is also logged.
- MAC addresses, IPs and certificates are all generated deterministically; images are pinned by digest and the OPNsense image is checked against its sha256, so the environment stays reproducible.

### Golden Image + Overlay Reset

1. `make vm-image`: download `OPNsense-26.7-nano-amd64.img.bz2` into `.cache/`, verify its sha256 and convert it to `base.qcow2`.
2. `make vm-golden`: `provision/bootstrap.py` (pexpect over the serial console) does the following: first boot → log in as root/opnsense → drop to a shell → write the rendered `config.xml` (LAN=vtnet0 10.0.2.15/24, WAN=vtnet1 DHCP, SSH key login enabled, API key, initial wizard disabled) → install `git` and `rsync` → shut down. The result is `golden.qcow2`.
3. Before each test run, `make vm-reset` creates a new overlay on top of the golden image (`qemu-img create -b golden.qcow2 -F qcow2`), returning to a clean state within seconds.

### Makefile Targets

`tools`, `env-up`, `env-down`, `vm-reset`, `vm-console`, `vm-ssh`, `deploy` (rsync the plugin into the VM and run `make install`/`make upgrade`), `package` (run `make package` inside the VM and fetch the .pkg), `lint` (run php -l, phpcs, xmllint and shellcheck in the dev container, plus upstream `make lint`/`style`), `test` (pytest e2e).

## 3. Plugin Design (`net/wan8021x`, package name `os-wan8021x`)

Follow the patterns of existing upstream plugins (for example the MVC, configd and rc structure of `net/upnp` and `net/frr`), as well as how core generates the wpa config and exports certificates in `interfaces.inc:1859-2031`.

| Layer | Files (relative to `src/`) | Contents |
|---|---|---|
| Model | `opnsense/mvc/app/models/OPNsense/Wan8021x/Wan8021x.xml/.php`, `Menu/Menu.xml`, `ACL/ACL.xml` | `general.enabled`; ArrayField `supplicants`: enabled, interface (InterfaceField, a physical port or VLAN device), eap_method (PEAP/TTLS), phase2 (MSCHAPV2, plus PAP for TTLS), identity, anonymous_identity, password, ca_ref (CertificateField/CA, optional), domain_suffix_match, eapol_version (1/2), EAPOL destination address (PAE multicast / nearest-bridge 01:80:c2:00:00:00), trigger DHCP after successful authentication, debug |
| API | `controllers/OPNsense/Wan8021x/Api/{Settings,Service,Status}Controller.php` | Extend `ApiMutableModelControllerBase` and `ApiMutableServiceControllerBase`; Status returns `wpa_cli status` for each interface (EAP state, Supplicant PAE state) |
| UI | `controllers/.../IndexController.php`, `views/OPNsense/Wan8021x/index.volt`, `forms/*.xml` | Menu Interfaces → 802.1X; bootgrid to edit the supplicant for each interface; status tab; log tab |
| configd | `service/conf/actions.d/actions_wan8021x.conf` | start / stop / restart / reconfigure / status |
| Generator | `scripts/OPNsense/Wan8021x/setup.php` | Render `/var/etc/wan8021x/<dev>.conf` from the config (mode 0600, `ap_scan=0`, network block) and export the CA |
| Service | `etc/rc.d/os-wan8021x` (or scheduled directly by configd) | Run `wpa_supplicant -B -D wired -i <dev> -c … -P … -s` once per interface, plus `wpa_cli -B -a event.sh` |
| Events | `scripts/OPNsense/Wan8021x/event.sh` | On CONNECTED, run `configctl interface reconfigure <if>` for the mapped OPNsense interface (the spike evaluates switching to a lighter dhclient restart) |
| Hooks | `etc/inc/plugins.inc.d/wan8021x.inc` | `_services` (dashboard and service start/stop), `_configure` → start at `early`, `_syslog` → `/var/log/wan8021x/` |

Passwords: stored in config.xml using `UpdateOnlyTextField`; generated config files are set to 0600; credentials are never written to logs.

## 4. Development Roadmap (Milestones)

- **M0 Skeleton**: git init, directories, `.gitignore`, the `vendor/opnsense-plugins` submodule and the `Mk` symlink, a stub Makefile, `docs/`.
- **M1 Test environment**: the three Dockerfiles, the compose file, bootstrap generating the golden image; after `make env-up` the GUI and SSH are reachable. The authenticator initially stays "unauthorized", so the VM's WAN gets no DHCP lease, which is exactly the expected state.
- **M2 Technical spike (manual verification, findings recorded in `docs/research.md`)**
  - S1: with a hand-written conf in the VM, `wpa_supplicant -D wired` with PEAP-MSCHAPv2 authenticates against hostapd → nft lets traffic through → dhclient obtains a lease. Also determine whether to use the binary under `/usr/local/sbin` or `/usr/sbin`.
  - S2: boot ordering. Start the supplicant in the `early` stage and check whether dhclient's own retries obtain an address once authentication succeeds; then check whether an event-triggered reconfigure is necessary and whether it has side effects.
  - S3: authentication on a VLAN subinterface (vtnet1_vlan100), and the effect of the parent interface's VLAN offload flags (see the pfatt experience with `-vlanhwtag -vlanhwfilter`).
  - S4: EAPOL destination address. How the FreeBSD wired driver handles PAE multicast versus 01:80:c2:00:00:00, and whether promisc mode or joining a multicast group is required; if customization is needed and wpa_supplicant cannot provide it, decide here (patch it, use a different port implementation, or offer only the PAE/nearest-bridge options in the first release).
  - S5: supplicant behavior on cable unplug (`ip link set tap-wan down/up`), authenticator-initiated re-authentication, a wrong password, and a CA mismatch.
- **M3 Plugin MVP**: implement PEAP/TTLS on physical ports as described in section 3; after `make deploy` it can be configured and started in the GUI and shows its status, and WAN obtains an address.
- **M4 Robustness**: VLAN, EAPOL address options, recovery from cable unplug and re-authentication, failure reasons visible on the status page, log integration, multiple interfaces side by side, automatic recovery after reboot.
- **M5 Automated e2e**: `tests/e2e`; run vm-reset before each test case, configure through the API, and assert that the VM gets an IP and that the hostapd log shows EAP success or failure. Coverage: PEAP success, TTLS success, wrong password, wrong CA, VLAN, recovery after unplug, recovery after reboot, clean removal after uninstalling the plugin.
- **M6 Packaging and release**: run `make package` in the VM to produce `os-wan8021x-*.pkg`, run upstream lint/style, complete the documentation; then, depending on circumstances, open a PR against opnsense/plugins.
- **Optional follow-ups**: EAP-TLS (client certificates, the AT&T scenario), EAP-MD5, a FreeRADIUS backend, HA sync (`_xmlrpc_sync`).

## 5. Risks

- The exact file name of the nano image for 26.7 and the details of its serial console interaction should be taken from the download directory; the bootstrap script has to cope with changes in prompt text, so it is pinned per version.
- An interface reconfigure in OPNsense may cause a brief outage or repeated triggering. S2 verifies this first; if necessary, switch to restarting only dhclient.
- hostapd's wired driver does not actually block the port; this is simulated with nftables. The differences from a real switch are documented in `docs/testenv.md`.

## 6. Verification

1. `make tools && make vm-image vm-golden && make env-up`: https://127.0.0.1:8443 can be opened and logged into in a browser, and `tools/bin/vm-ssh` can connect.
2. Before installing the plugin: `vm-ssh ifconfig vtnet1` shows no IPv4 address, and the authenticator's nft counters show non-EAPOL packets being dropped.
3. `make deploy`, then configure a PEAP account for WAN in the GUI and apply: the status page shows `EAP state=SUCCESS` and `suppPortStatus=Authorized`, WAN obtains 172.31.0.x, and `CTRL-EVENT-EAP-SUCCESS` appears in the hostapd log.
4. `make test` runs the whole e2e suite from a clean overlay and everything passes; `make lint` reports no errors; `make package` produces an installable .pkg.
