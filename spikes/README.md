English | [简体中文](README.zh-CN.md)

# Spikes

Validation scripts run by hand inside the test VM during the M2 phase; the conclusions are in [docs/research.md](../docs/research.md).

```
cat spikes/s3-vlan.sh | tools/bin/vm-ssh 'cat > /root/s3.sh'
tools/bin/vm-ssh 'sh /root/s3.sh' </dev/null
```

The `/tmp/spike/wan.conf` used by S1:

```
ctrl_interface=/var/run/spike
ap_scan=0
eapol_version=2
network={
	key_mgmt=IEEE8021X
	eap=PEAP
	identity="alice"
	anonymous_identity="anonymous"
	password="alice-secret"
	phase2="auth=MSCHAPV2"
	eapol_flags=0
}
```
