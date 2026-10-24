#!/bin/sh
# Test helper inside the auth container.
#   authctl status            authorized MACs + drop counters
#   authctl sta [iface]       hostapd station table
#   authctl deauth MAC [if]   force port back to unauthorized
#   authctl flap [secs]       pull the VM's WAN cable for a while (QEMU set_link)
#   authctl leases            dnsmasq leases
#   authctl authorized [v100|v200]  authorized MACs, one per line
#   authctl reset             all ports back to unauthorized
#   authctl reauth MAC        authenticator-initiated re-authentication (untagged port)
#   authctl preauth MAC       allow data before authentication to obtain an old lease
#   authctl network default|changed  switch the untagged subnet without a link event
set -eu
cmd=${1:-status}
case $cmd in
status) nft list table netdev wan8021x ;;
sta) hostapd_cli -p /run/hostapd -i "${2:-tap-wan}" all_sta ;;
deauth) hostapd_cli -p /run/hostapd -i "${3:-tap-wan}" deauthenticate "$2" ;;
flap)
	mon() { echo "$1" | socat - UNIX-CONNECT:/cache/run/monitor.sock >/dev/null; }
	mon "set_link wan off"
	# a real switch drops the port back to unauthorized on link loss
	for sta in $(hostapd_cli -p /run/hostapd -i tap-wan list_sta); do
		hostapd_cli -p /run/hostapd -i tap-wan deauthenticate "$sta" >/dev/null
	done
	nft flush set netdev wan8021x auth_untagged
	sleep "${2:-3}"
	mon "set_link wan on"
	;;
leases) cat /var/lib/misc/dnsmasq.leases 2>/dev/null || true ;;
authorized)
	set=auth_untagged
	case ${2:-} in v100 | v200) set=auth_$2 ;; esac
	nft -j list set netdev wan8021x "$set" |
		grep -oE '([0-9a-f]{2}:){5}[0-9a-f]{2}' || true
	;;
reset)
	for ifc in tap-wan tap-wan.100 tap-wan.200; do
		for sta in $(hostapd_cli -p /run/hostapd -i $ifc list_sta); do
			hostapd_cli -p /run/hostapd -i $ifc deauthenticate "$sta" >/dev/null
		done
	done
	nft flush set netdev wan8021x auth_untagged
	nft flush set netdev wan8021x auth_v100
	nft flush set netdev wan8021x auth_v200
	;;
reauth) hostapd_cli -p /run/hostapd -i tap-wan raw "EAPOL_REAUTH $2" ;;
preauth) nft add element netdev wan8021x auth_untagged "{ $2 }" ;;
network)
	case ${2:-} in
	default) old=172.31.10.1; new=172.31.0.1 ;;
	changed) old=172.31.0.1; new=172.31.10.1 ;;
	*) echo "network must be default or changed" >&2; exit 64 ;;
	esac
	ip addr replace "$new/24" dev tap-wan
	ip addr del "$old/24" dev tap-wan 2>/dev/null || true
	;;
*) echo "unknown command: $cmd" >&2; exit 64 ;;
esac
