#!/bin/bash
# Authenticator ("switch port" + EAP server) for the OPNsense WAN.
# Runs inside the vm container's network namespace, on its tap-wan device.
set -eu
E=/etc/authenv
PKI=/cache/auth/pki
STATE=/cache/auth
LOGLEVEL=${AUTH_LOGLEVEL:-1}
REAUTH=${AUTH_REAUTH:-3600}
PAE=${AUTH_PAE_GROUP:-1}

mkdir -p "$STATE" /run/hostapd
"$E/gen-certs.sh" "$PKI"

echo "waiting for tap-wan ..."
while ! ip link show tap-wan >/dev/null 2>&1; do sleep 1; done

ip link set tap-wan up
ip addr replace 172.31.0.1/24 dev tap-wan
for vid in 100 200; do
	ip link add link tap-wan name tap-wan.$vid type vlan id $vid 2>/dev/null || true
	ip link set tap-wan.$vid up
	ip addr replace 172.31.$vid.1/24 dev tap-wan.$vid
done

nft delete table netdev wan8021x 2>/dev/null || true
nft -f "$E/port.nft"

pids=()
dnsmasq --conf-file="$E/dnsmasq.conf" --log-facility=- --keep-in-foreground &
pids+=($!)

for ifc in tap-wan tap-wan.100 tap-wan.200; do
	sed -e "s|@IFACE@|$ifc|" -e "s|@PKI@|$PKI|" -e "s|@LOGLEVEL@|$LOGLEVEL|" \
		-e "s|@REAUTH@|$REAUTH|" -e "s|@PAE@|$PAE|" \
		"$E/hostapd.conf.in" > "/run/hostapd-$ifc.conf"
	(hostapd "/run/hostapd-$ifc.conf" 2>&1; echo "hostapd on $ifc exited") | sed -u "s/^/[hostapd $ifc] /" &
	pids+=($!)
done
sleep 2
for ifc in tap-wan tap-wan.100 tap-wan.200; do
	hostapd_cli -p /run/hostapd -i "$ifc" -a "$E/portctl.sh" &
	pids+=($!)
done

# remote control for the test suite (the dev container has no docker access)
rm -f /cache/run/authctl.sock
socat UNIX-LISTEN:/cache/run/authctl.sock,fork,mode=666 EXEC:"$E/authctl-sock.sh" &
pids+=($!)

# exit (and let compose restart us) as soon as any child is gone, also one that failed
# during startup: wait -n would not report a job that ended before it was called
while sleep 1; do
	for pid in "${pids[@]}"; do
		if ! kill -0 "$pid" 2>/dev/null; then
			echo "child process $pid exited, stopping" >&2
			exit 1
		fi
	done
done
