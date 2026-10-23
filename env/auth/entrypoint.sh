#!/bin/sh
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
ip link add link tap-wan name tap-wan.100 type vlan id 100 2>/dev/null || true
ip link set tap-wan.100 up
ip addr replace 172.31.100.1/24 dev tap-wan.100

nft delete table netdev wan8021x 2>/dev/null || true
nft -f "$E/port.nft"

dnsmasq --conf-file="$E/dnsmasq.conf" --log-facility=- --keep-in-foreground &

for ifc in tap-wan tap-wan.100; do
	sed -e "s|@IFACE@|$ifc|" -e "s|@PKI@|$PKI|" -e "s|@LOGLEVEL@|$LOGLEVEL|" \
		-e "s|@REAUTH@|$REAUTH|" -e "s|@PAE@|$PAE|" \
		"$E/hostapd.conf.in" > "/run/hostapd-$ifc.conf"
	hostapd "/run/hostapd-$ifc.conf" 2>&1 | sed -u "s/^/[hostapd $ifc] /" &
done
sleep 2
for ifc in tap-wan tap-wan.100; do
	hostapd_cli -p /run/hostapd -i "$ifc" -a "$E/portctl.sh" &
done

# exit (and let compose restart us) if any child dies
wait -n 2>/dev/null || wait
