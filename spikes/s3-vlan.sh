#!/bin/sh
# S3: 802.1X on a VLAN sub-interface (VLAN 100 on the WAN NIC), no OPNsense
# assignment involved. Run inside the VM; needs /tmp/spike/wan.conf (S1).
pkill -f "wpa_supplicant.*spike"; sleep 1
ifconfig vlan0100 destroy 2>/dev/null
V=$(ifconfig vlan create vlan 100 vlandev vtnet1) && ifconfig $V name vlan0100 >/dev/null && ifconfig vlan0100 up
daemon -o /tmp/spike/wpa-vlan.log /usr/local/sbin/wpa_supplicant -dd -D wired -i vlan0100 -c /tmp/spike/wan.conf
for i in $(seq 1 50); do
	/usr/local/sbin/wpa_cli -p /var/run/spike -i vlan0100 status 2>/dev/null | grep -q 'EAP state=SUCCESS' && break
	sleep 0.2
done
/usr/local/sbin/wpa_cli -p /var/run/spike -i vlan0100 status | grep -E 'PAE|PortStatus|EAP state|address'
dhclient -b vlan0100 >/dev/null 2>&1; sleep 5
ifconfig vlan0100 | grep -E 'inet |vlan:'
pkill -f "wpa_supplicant.*vlan0100"; pkill -f "dhclient.*vlan0100"; ifconfig vlan0100 destroy
