#!/bin/sh
# Test helper inside the auth container.
#   authctl status            authorized MACs + drop counters
#   authctl sta [iface]       hostapd station table
#   authctl deauth MAC [if]   force port back to unauthorized
#   authctl flap [secs]       pull the VM's WAN cable for a while (QEMU set_link)
#   authctl leases            dnsmasq leases
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
*) echo "unknown command: $cmd" >&2; exit 64 ;;
esac
