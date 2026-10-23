# spikes

M2 阶段在测试 VM 内手工运行的验证脚本，结论见 `docs/research.md`。

```
cat spikes/s3-vlan.sh | tools/bin/vm-ssh 'cat > /root/s3.sh'
tools/bin/vm-ssh 'sh /root/s3.sh' </dev/null
```

S1 用到的 `/tmp/spike/wan.conf`：

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
