#!/bin/sh
# OPNsense VM runner. All state lives in /cache (bind mount of ./.cache).
#
#   run                     boot ${VM_DISK} (default)
#   prepare-base            decompress the nano image into images/base.qcow2
#   overlay <backing> <out> create a copy-on-write disk on top of <backing>
set -eu

CACHE=/cache
RUN_DIR=$CACHE/run
VM_DISK=${VM_DISK:-vm/overlay.qcow2}
VM_MEM=${VM_MEM:-3072}
VM_CPUS=${VM_CPUS:-2}
VM_DISK_SIZE=${VM_DISK_SIZE:-12G}
LAN_MAC=52:54:00:00:01:01
WAN_MAC=52:54:00:00:02:01

prepare_base() {
	img=$CACHE/images/$OPNSENSE_IMAGE
	out=$CACHE/images/base-$OPNSENSE_VERSION.qcow2
	echo "$OPNSENSE_SHA256  $img" | sha256sum -c -
	raw=$CACHE/images/base.raw
	bzip2 -dc "$img" > "$raw"
	qemu-img convert -O qcow2 "$raw" "$out"
	rm -f "$raw"
	qemu-img resize "$out" "$VM_DISK_SIZE"
	chown "${HOST_UID:-0}" "$out"
	echo "base image: $out"
}

overlay() {
	backing=$1
	out=$2
	mkdir -p "$(dirname "$CACHE/$out")"
	chown "${HOST_UID:-0}" "$(dirname "$CACHE/$out")"
	rm -f "$CACHE/$out"
	# backing path is relative to the overlay's directory
	qemu-img create -q -f qcow2 -F qcow2 \
		-b "$(realpath --relative-to="$(dirname "$CACHE/$out")" "$CACHE/$backing")" \
		"$CACHE/$out"
	chown "${HOST_UID:-0}" "$CACHE/$out"
	echo "overlay: $out -> $backing"
}

run() {
	mkdir -p "$RUN_DIR"
	chown "${HOST_UID:-0}" "$RUN_DIR"
	rm -f "$RUN_DIR/serial.sock" "$RUN_DIR/monitor.sock"
	# sockets and logs must be usable by the unprivileged dev container
	umask 000

	# WAN side: a bare tap device. The "auth" container shares this network
	# namespace and runs hostapd/dnsmasq directly on it (no Linux bridge, so
	# EAPOL frames to 01:80:c2:00:00:03 are never filtered).
	ip tuntap add dev tap-wan mode tap 2>/dev/null || true
	ip link set tap-wan up

	# libslirp only rewrites the source of *loopback* connections to 10.0.2.2;
	# published docker ports arrive from the bridge gateway, which the guest
	# cannot route back to. Relay them through loopback.
	for p in 22 443; do
		socat TCP-LISTEN:$p,fork,reuseaddr TCP:127.0.0.1:1$p &
	done

	exec qemu-system-x86_64 \
		-name opnsense \
		-machine q35,accel=kvm -cpu host \
		-smp "$VM_CPUS" -m "$VM_MEM" \
		-drive file="$CACHE/$VM_DISK",if=virtio,format=qcow2,cache=unsafe \
		-netdev user,id=lan,net=10.0.2.0/24,hostfwd=tcp:127.0.0.1:1443-10.0.2.15:443,hostfwd=tcp:127.0.0.1:122-10.0.2.15:22 \
		-device virtio-net-pci,netdev=lan,mac=$LAN_MAC \
		-netdev tap,id=wan,ifname=tap-wan,script=no,downscript=no \
		-device virtio-net-pci,netdev=wan,mac=$WAN_MAC \
		-display none -vga none \
		-chardev socket,id=ser0,path="$RUN_DIR/serial.sock",server=on,wait=off,logfile="$RUN_DIR/serial.log",logappend=on \
		-serial chardev:ser0 \
		-monitor unix:"$RUN_DIR/monitor.sock",server=on,wait=off
}

cmd=${1:-run}
[ $# -gt 0 ] && shift
case $cmd in
run) run ;;
prepare-base) prepare_base ;;
overlay) overlay "$@" ;;
*) exec "$cmd" "$@" ;;
esac
