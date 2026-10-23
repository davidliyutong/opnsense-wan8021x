English | [简体中文](testenv.zh-CN.md)

# Test Environment

The host only needs docker (with the compose plugin), git and `/dev/kvm`. Every other tool is
built from the Dockerfiles in this repository, and all runtime state lives in `.cache/` (gitignored).

## Topology

```
 127.0.0.1:18443 (GUI) ─┐
 127.0.0.1:12222 (ssh) ─┤ socat → QEMU hostfwd(127.0.0.1) → vtnet0 LAN 10.0.2.15/24
                        │
 container vm: qemu-system-x86_64 -enable-kvm  (OPNsense 26.7 nano)
    vtnet0 = LAN (QEMU user net, for management)
    vtnet1 = WAN ── tap-wan ─┐
                             │ (same network namespace)
 container auth:             │
    hostapd -D wired  on tap-wan       (untagged, PAE multicast 01:80:c2:00:00:03)
    hostapd -D wired  on tap-wan.100   (VLAN 100)
    built-in EAP server: PEAP / TTLS, phase2 MSCHAPv2 (TTLS also supports PAP)
    nftables netdev ingress: unauthorized MACs may only send EAPOL (0x888e)
    hostapd_cli -a portctl.sh: AP-STA-CONNECTED/DISCONNECTED → add/remove authorized MAC
    dnsmasq: 172.31.0.0/24 (untagged), 172.31.100.0/24 (VLAN 100)
```

A few details:
* The WAN does not go through a Linux bridge. A bridge drops 01:80:c2:00:00:0X link-local frames by default; bypassing it avoids having to tune `group_fwd_mask`.
* Published ports first pass through socat inside the container and then reach hostfwd on loopback. libslirp only rewrites the source address to 10.0.2.2 for connections coming from loopback; other sources keep their original address, and the guest has no return route to it.
* The VM MAC addresses are fixed: LAN 52:54:00:00:01:01, WAN 52:54:00:00:02:01.

## Accounts

| Purpose | Account |
|---|---|
| OPNsense GUI/console | root / opnsense |
| ssh | `.cache/ssh/id_ed25519` (`make ssh`) |
| API | `.cache/ssh/apikey.json` |
| EAP | alice / alice-secret (PEAP, TTLS-MSCHAPv2, TTLS-PAP), bob / bob-secret |
| CA | `.cache/auth/pki/ca.crt`; `rogue-ca.crt` is used to test CA verification failure |

## Common Commands

```
make tools          # build the images
make image golden   # download and verify the nano image, build the golden disk (about 5 min, only needed once)
make reset          # create a new overlay from golden and boot it, back to a clean state
make up / down      # start/stop while keeping the current VM state
make console        # serial console (ctrl-] to exit)
make ssh
make status         # authorized MAC set and counters
docker compose -f env/compose.yml exec auth authctl sta|deauth MAC|flap 5|leases
```

## How Tests Control the Authenticator

The dev container has no docker access. The authenticator exposes remote calls to `authctl` on `.cache/run/authctl.sock`
(each connection sends one line of arguments and gets back the output followed by `rc=N`); the log is also written to `.cache/run/auth.log`.
`auth()` and `authorized()` in `tests/e2e/conftest.py` are built on top of it.

```
printf 'authorized\n' | socat - UNIX-CONNECT:.cache/run/authctl.sock
```

## Tests and Checks

```
make lint      # dev container: php -l, phpcs(core ruleset), pycodestyle, xmllint, shellcheck; VM: upstream make lint
make test      # run e2e against the current VM (filter with TESTARGS="-k vlan")
make check     # lint + reset + deploy + test, a full run from a clean state
```

## Differences from a Real Switch

* Port state is emulated with nftables, and only the direction from the VM to the authenticator is filtered.
* hostapd's built-in EAP server is not the same as an ISP's or campus network's RADIUS. A FreeRADIUS container could be added later as a backend.
* `authctl flap` emulates unplugging the cable via `set_link` on the QEMU monitor, and the guest sees a link-down event.
