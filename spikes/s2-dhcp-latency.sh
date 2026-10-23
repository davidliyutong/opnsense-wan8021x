#!/bin/sh
# S2: how long after EAP success does the stock OPNsense dhclient get a lease,
# when the port was unauthorized for DELAY seconds beforehand (dhclient backoff)?
# Run inside the VM: sh s2-dhcp-latency.sh [DELAY]; needs /tmp/spike/wan.conf (S1).
IF=vtnet1
DELAY=${1:-60}
ts() { date +%H:%M:%S; }
pkill -f "wpa_supplicant.*spike"; sleep 1
echo "$(ts) reconfigure wan (drops lease, restarts dhclient)"
configctl interface reconfigure wan >/dev/null
echo "$(ts) dhclient: $(pgrep -lf dhclient | tr '\n' ' ')"
sleep "$DELAY"
echo "$(ts) after ${DELAY}s: $(ifconfig $IF | grep 'inet ' || echo 'no IPv4 (expected)')"
t0=$(date +%s)
daemon -o /tmp/spike/wpa.log -p /tmp/spike/pid /usr/local/sbin/wpa_supplicant -dd -D wired -i $IF -c /tmp/spike/wan.conf
while ! /usr/local/sbin/wpa_cli -p /var/run/spike -i $IF status 2>/dev/null | grep -q 'EAP state=SUCCESS'; do sleep 0.2; done
t1=$(date +%s)
echo "$(ts) EAP success"
while ! ifconfig $IF | grep -q 'inet '; do sleep 0.5; [ $(($(date +%s) - t1)) -gt 600 ] && break; done
t2=$(date +%s)
echo "$(ts) eap_success_after=$((t1 - t0))s lease_after_success=$((t2 - t1))s"
