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
    hostapd -D wired  on tap-wan.200   (VLAN 200)
    built-in EAP server: PEAP / TTLS, phase2 MSCHAPv2 (TTLS also supports PAP)
    nftables netdev ingress: unauthorized MACs may only send EAPOL (0x888e)
    hostapd_cli -a portctl.sh: AP-STA-CONNECTED/DISCONNECTED → add/remove authorized MAC
    dnsmasq: 172.31.0.0/24 (untagged), 172.31.100.0/24, 172.31.200.0/24 (VLAN 100/200)
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

## CI on GitHub and Locally with act

`.github/workflows/` holds three workflows: `ci.yml` (every push and pull
request), `build.yml` (reusable: upstream `make lint` + `make package` in a
FreeBSD VM via `vmactions/freebsd-vm`) and `release.yml` (`v*` tags).

```
make ci-local                    # ci.yml under act, on a clean clone of HEAD
make ci-local ACTARGS="-j lint"  # one job only
tools/ci-local.sh -W .github/workflows/release.yml -e EVENT.json -j build
                                 # release build; EVENT.json: {"ref":"refs/tags/v0.1"}
```

`tools/ci-local.sh` clones HEAD (uncommitted changes are not tested) to
`.cache/act/work/repo`, builds the job image `env/act/Dockerfile` (the
catthehacker ubuntu-24.04 image plus rsync, with the runner home at
`.cache/act` so `vmactions/freebsd-vm` finds `$HOME/work` like on a GitHub
runner) and passes `/dev/kvm` through. Artifacts land in
`.cache/act/artifacts`. Run the publish job of `release.yml` on GitHub only.

### Resource limits

Job containers are capped like a GitHub-hosted `ubuntu-latest` runner for
private repositories: 2 CPU, 8 GB RAM, no swap (`--cpus=2 --memory=8g
--memory-swap=8g`). Public repositories get 4 CPU / 16 GB. Both have 14 GB of
SSD, which cannot be capped with overlay2, so disk use is measured instead.

Measured with act 0.2.88 on 2026-10-24 (cgroup v2 of the job container,
sampled every 5 s):

| Job | Wall time | CPU | Memory | Disk |
|---|---|---|---|---|
| Lint and format | ~10 s (+~30 s for an uncached dev image build) | <1 core | job container 37 MB; the dev image (300 MB) builds in the host docker daemon, outside the cap | 300 MB image |
| FreeBSD lint + package | ~1.5–2 min | 2 cores saturated while the VM boots and installs packages, ~70 CPU-s in total | anon peak 3.8 GiB (QEMU guest, configured with 6 GiB), page cache ~3.8 GiB; no OOM kill, `memory.max` never hit | ~4.4 GB peak (FreeBSD 15.1 image download + extracted 3.5 GB qcow2) |

The workspace synced into the VM is ~230 MB (mostly `vendor/core`). The
lint job uses the host docker socket, so its `dev` container and image build
are not limited by the caps.

## Differences from a Real Switch

* Port state is emulated with nftables, and only the direction from the VM to the authenticator is filtered.
* hostapd's built-in EAP server is not the same as an ISP's or campus network's RADIUS. A FreeRADIUS container could be added later as a backend.
* `authctl flap` emulates unplugging the cable via `set_link` on the QEMU monitor, and the guest sees a link-down event.
