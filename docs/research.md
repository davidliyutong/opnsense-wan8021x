# 调研与 spike 结论

环境：OPNsense 26.7（FreeBSD 14, nano 镜像）、virtio-net（vtnet1 = WAN）、认证端为 hostapd 2.11 wired + 内置 EAP server。
spike 脚本在 `spikes/` 目录。

## 背景调研

* OPNsense 和 pfSense 都没有在 WAN 有线口上做 802.1X 的 GUI。社区方案是 pfatt/opnatt
  （[opnatt-supplicant.sh](https://git.hhf.technology/hhf/pfatt/src/branch/supplicant/bin/opnatt-supplicant.sh)），
  本质是在 early syshook 里用 shell 脚本拉起 wpa_supplicant。
* 系统里有两个 wpa_supplicant，都是 v2.11，都带 `wired` 驱动：
  * `/usr/sbin/wpa_supplicant`：FreeBSD base，`usr.sbin/wpa/Makefile.inc` 中定义了 `CONFIG_DRIVER_WIRED`
  * `/usr/local/sbin/wpa_supplicant`：ports 包 `wpa_supplicant-2.11_7`，core 的 Wi-Fi 客户端用的就是它（`interfaces.inc`）
  * **决定：使用 `/usr/local/sbin/wpa_supplicant`**，与 core 保持一致，并且随 OPNsense 固件更新。
  * 两者都不支持 `-f` 写日志文件（编译时没开 `CONFIG_DEBUG_FILE`），改用 `-s`（syslog）或 `daemon -o`。
* `interface_configure()` 在启动 dhclient 之前没有插件钩子；`rc.linkup`（由 devd 触发）里也没有。
* 插件框架：`plugins.inc.d/<name>.inc` 提供 `_services`、`_configure`（如 `early`、`bootup` 等事件）、`_syslog`、`_xmlrpc_sync`。
  参考实现：`vendor/opnsense-plugins/net/ndp-proxy-go`（MVC + configd + rc + syslog）。
* 测试 VM 的 root shell 是 csh，远程执行脚本要用 `sh -s`。

## S1 —— wired PEAP 基本可行 ✅

`wpa_supplicant -D wired -i vtnet1`，配置 `ap_scan=0`、`key_mgmt=IEEE8021X`、`eap=PEAP`、`phase2="auth=MSCHAPV2"`、`eapol_flags=0`：

* 约 2 秒完成 EAP-SUCCESS（TLSv1.2，ECDHE-RSA-AES256-GCM-SHA384）。端口放行后，WAN 由 OPNsense 自带的 dhclient 拿到 172.31.0.x。
* TX EAPOL 目标地址为 PAE 组播 `01:80:c2:00:00:03`。驱动通过 `SIOCADDMULTI` 加入该组播组。
* `wpa_cli status` 能直接给出状态页需要的字段：`Supplicant PAE state`、`suppPortStatus`、`EAP state`、`selectedMethod`、`EAP-PEAPv1 Phase2 method`。

## S2 —— 启动时序和 DHCP ✅

* 端口未授权 120 秒（dhclient 已进入退避）后再启动 supplicant：3 秒 EAP 成功，**6 秒拿到租约**。FreeBSD dhclient 的退避上限很短。
* **结论：认证成功后不需要 `interface reconfigure`**（它很重，会先丢掉地址）。supplicant 只要在 `early` 阶段或服务启动时拉起即可。
  插件可以提供一个可选的“认证成功后立即续约”开关（M4 评估）。

## S3 —— VLAN 子接口 ✅

* `ifconfig vlan create vlan 100 vlandev vtnet1` 之后，在 vlan 设备上运行 wired supplicant，认证成功并从 VLAN 100 网段拿到地址。
* 注意：pfatt 记录过在某些真实网卡（igb/ix + netgraph）上需要 `-vlanhwtag -vlanhwfilter -vlanhwtso`。virtio 上无法复现。
  插件可以给出“禁用父接口 VLAN 硬件 offload”的选项（M4）。

## S4 —— EAPOL 目标地址 ⚠️

* 认证端改为单播回复（`use_pae_group_addr=0`）时，认证照常成功；supplicant 发出的帧仍然发往 PAE 组播地址。
* wpa_supplicant（wired 驱动）**没有配置项能改 TX 目标 MAC**：`bssid` 固定为 PAE 组地址。
* 首版能做到的：
  * 用 OPNsense 接口自带的 MAC 克隆（spoofmac）满足“需要特定源 MAC”的场景，无需额外开发；
  * 可选开启 `IFF_ALLMULTI` 或 promisc，以接收发往其他链路本地组播地址（如 `01:80:c2:00:00:00`/`0e`）的 EAPOL。
* 真正自定义目标 MAC 需要给 wpa_supplicant 打补丁或自己实现 EAPOL 发送端。**推迟到有真实需求时再决定**（ROADMAP 的后续可选项）。

## S5 —— 失败与恢复 ⚠️（插件必须处理）

| 场景 | 结果 |
|---|---|
| 错误密码 | `PAE state=HELD`、`EAP state=FAILURE`、`CTRL-EVENT-EAP-FAILURE` |
| CA 不匹配 | `CTRL-EVENT-EAP-TLS-CERT-ERROR reason=1 … err='self-signed certificate in certificate chain'` |
| 正确 CA + `domain_suffix_match` | 成功 |
| **拔线 5 秒，交换机端口重置** | **60 秒内没有恢复**：FreeBSD wired 驱动不跟踪链路状态，supplicant 仍以为自己是 AUTHENTICATED；hostapd 也不会主动重新发起 |
| 上述情况再执行 `wpa_cli reauthenticate` | 4 秒内恢复授权 |

**结论：插件必须监听 WAN（以及 VLAN 的父接口）的 link up 事件，并触发 `wpa_cli reauthenticate`。**
`rc.linkup` 没有插件钩子，可选方案：
1. 插件自带 devd 规则（`/usr/local/etc/devd/`），在 LINK_UP 时执行 `configctl wan8021x linkup <dev>`。需要确认 devd 对同一事件会执行多条 notify 规则。
2. 每个 supplicant 配一个轻量 watcher（`route -n monitor` 或 kqueue），不依赖 devd。

**已验证（M3）**：devd 对同一事件只执行优先级最高的一条 notify 规则。插件自带规则（优先级 0 或 101）都没有被执行，
core 的 `rc.linkup` 照常执行。要想生效就只能用更高的优先级覆盖 core 的规则，这太脆弱，**因此采用方案 2**：
守护进程解析 `route -n monitor` 的 `iface#N <dev> admin UP oper UP|DOWN` 行，在 link 由 DOWN 变 UP 时向 ctrl socket 发送 `REAUTHENTICATE`。
VLAN 子接口会随父接口一起产生事件，所以只需监视 supplicant 自己的设备。

另外，失败原因（密码错误或证书错误）要在状态页里显示：从 wpa_cli 事件（`CTRL-EVENT-EAP-FAILURE`、`CTRL-EVENT-EAP-TLS-CERT-ERROR`）中解析出来，写入状态文件。

## 对插件设计的影响（相对 ROADMAP 的调整）

1. 使用 `/usr/local/sbin/wpa_supplicant -D wired`，日志通过 `-s` 走 syslog。
2. 去掉“认证成功后 interface reconfigure”，改为可选的轻量续约。
3. **新增：link up 时重新认证**（M3 就纳入，否则拔线后断网）。
4. 每个 supplicant 配一个 `wpa_cli -a` action 脚本，记录最近的事件和失败原因，供状态页使用。
5. identity 和 password 按 wpa_supplicant 的语法正确转义，避免 core Wi-Fi 代码里直接插值的问题。

## M3/M4 实现中的发现

* `UpdateOnlyTextField::__toString()` 永远返回空字符串（防止回显）。生成配置时必须用 `getValue()` 取值，否则密码为空。
* 密码为空时，wpa_supplicant 会发出 `CTRL-REQ-PASSWORD` 并无限等待，表现为“卡住”而不是失败。
  守护进程把 `CTRL-REQ-*` 转换为 “credentials incomplete” 错误。
* 用户输入的 identity、password、域名一律以十六进制写入 wpa_supplicant 配置，从根本上避免引号和转义问题
  （用含 `\`、UTF-8 以及 `"` 的密码测试过）。
* core 的接口设置本身就有 `promisc` 和 `disablevlanhwfilter`，因此插件不再重复提供这两个选项。
* 包生命周期：core 的 `rc.configure_plugins` 在 POST_INSTALL 时不会启动服务。插件自带
  `+PRE_DEINSTALL.pre`（停止服务）、`+POST_INSTALL.post`（已启用时重启服务）、`+POST_DEINSTALL.post`（清理）。
* 26.7 新增的接口分配 API（`interfaces/assignment/*`）只负责分配本身，设置 IP 方式还得走旧配置；
  通过 API 分配的接口默认是锁定状态，删除前必须先解锁。
* 上游的 `make lint` 依赖 BSD 版的 find 和 sh，所以放在 VM 中执行（需要同步 core 的 `Mk/`、`Scripts/`、`contrib/parallel-lint`）；
  phpcs 和 pycodestyle 在 dev 容器中执行，使用 core 的 `ruleset.xml`。
