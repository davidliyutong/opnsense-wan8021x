#!/bin/sh
# hostapd_cli action script: $1=interface $2=event $3=station MAC
case $1 in
tap-wan) set=auth_untagged ;;
tap-wan.100) set=auth_v100 ;;
*) exit 0 ;;
esac
case $2 in
AP-STA-CONNECTED)
	nft add element netdev wan8021x $set "{ $3 }"
	echo "[portctl] $1 $3 authorized"
	;;
AP-STA-DISCONNECTED)
	nft delete element netdev wan8021x $set "{ $3 }" 2>/dev/null
	echo "[portctl] $1 $3 unauthorized"
	;;
esac
