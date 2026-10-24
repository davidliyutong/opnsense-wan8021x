[English](ROADMAP.md) | 简体中文

# OPNsense WAN 802.1X 插件 —— 环境搭建与开发路线

## 进度（2026-10-23）

| 里程碑 | 状态 |
|---|---|
| M0 骨架 | ✅ |
| M1 测试环境 | ✅ golden 镜像约 1 分钟生成，`make reset` 约 20 秒 |
| M2 spike | ✅ 结论见 research.md（拔线后需要主动重认证、EAPOL 目标 MAC 无法自定义） |
| M3 插件 MVP | ✅ PEAP/TTLS、状态页、手动重认证、link up 自动重认证 |
| M4 健壮性 | ✅ VLAN、多接口、重启恢复、失败原因、日志、敏感信息保护、升级与卸载 |
| M5 e2e | ✅ 24 个用例，`make check` 从全新 VM 跑完约 3 分钟 |
| M6 打包 | 🟡 `make package` 已可用；尚未提交上游，文档待补（截图、用户手册） |

与原计划的差异：首次获得授权或授权恢复后异步重新获取 IPv4 DHCP 租约，不执行整个接口的 `interface reconfigure`（S2 的初次获取租约实验未覆盖认证后切换网段，已修正）；保持授权期间的重认证保留租约，并限制刷新频率；
link 监听用 `route -n monitor` 代替 devd（devd 只执行优先级最高的规则）；
删除了 promisc 选项（core 接口设置已有）。

---


## Context

OPNsense（当前 26.7.x，基于 FreeBSD 14）没有在 WAN 有线口上做 802.1X 认证的 GUI 功能；社区现有方案只有 pfatt/opnatt 一类 shell 脚本（[opnatt-supplicant.sh](https://git.hhf.technology/hhf/pfatt/src/branch/supplicant/bin/opnatt-supplicant.sh)），并不可维护。目标：做一个符合 opnsense/plugins 规范的插件，在 GUI 中为 WAN（物理口或 VLAN 子接口）配置 PEAP / TTLS（MSCHAPv2）认证，并配套一个用 Docker + KVM 搭建、可一键重置的测试环境。所有工具链放在当前目录，使用 git 管理。

已确认的事实（调研结论）：
- 宿主机：Docker 29.8、`/dev/kvm` 可用、16 核 / 60G 内存、磁盘 1.3T 空闲；目前没有 libvirt（不需要它），项目目录为空。
- FreeBSD 基础系统的 wpa 编译带 `-DCONFIG_DRIVER_WIRED`（`usr.sbin/wpa/Makefile.inc`），因此 `wpa_supplicant -D wired` 在 OPNsense 上可行。OPNsense core 自己的 Wi-Fi 客户端使用 `/usr/local/sbin/wpa_supplicant`（`interfaces.inc:1859-2031`），插件可以直接复用它的配置生成和证书导出方式。
- `interface_configure()`（`interfaces.inc:2233`）在启动 DHCP 之前**没有插件钩子**，只在之后调用 `plugins_configure('ipsec'|'dhcp'|'dns'|'updateip')`。所以 supplicant 必须作为独立服务，在 `early` 启动阶段拉起；认证成功后，由事件脚本触发 WAN 的 DHCP 重新获取地址。
- 插件钩子都在 `plugins.inc.d/<name>.inc` 里：`_services`、`_configure`（事件 → 任务）、`_syslog`、`_devices` 等。
- 官方 **nano 镜像** 是预装系统、使用串口控制台，适合用 qcow2 做 golden 镜像加 overlay 的方式快速重置。

用户已确定的选择：首版支持 **PEAP/TTLS（MSCHAPv2）**；**物理口和 VLAN 都支持**，并提供 EAPOL 目标地址相关选项；采用**独立仓库，按 opnsense/plugins 的目录布局**。

---

## 1. 仓库布局（当前目录 `/home/liyutong/Projects/opnsense-802-1x`）

```
.
├── Makefile                     # 唯一入口：env-*, vm-*, deploy, test, lint, package
├── README.md / docs/
│   ├── ROADMAP.md               # 本路线（落盘版）
│   ├── research.md              # 调研与 spike 结论
│   └── testenv.md               # 测试环境拓扑与使用
├── env/                         # 测试环境（全部 Docker 化）
│   ├── compose.yml
│   ├── versions.env             # OPNsense 版本 + sha256、基础镜像 digest，统一钉死
│   ├── vm/      Dockerfile, entrypoint.sh       # debian:trixie@digest + qemu-system-x86 + qemu-utils + iproute2 + nftables
│   ├── auth/    Dockerfile, hostapd*.conf, eap_user, portctl.sh, dnsmasq.conf, gen-certs.sh
│   ├── dev/     Dockerfile      # php-cli、phpcs、python3 + pytest + pexpect + paramiko + requests、xmllint、shellcheck
│   └── provision/ bootstrap.py, config.xml.j2   # 串口自动化生成 golden 镜像
├── tools/bin/                   # 包装脚本：vm-ssh、vm-console、vm-api、in-dev（在 dev 容器内执行）
├── vendor/opnsense-plugins      # git submodule，钉在与 26.7 对应的 tag，提供 Mk/ 和 lint 规则
├── Mk -> vendor/opnsense-plugins/Mk   # 软链，让 net/wan8021x/Makefile 能 include ../../Mk/plugins.mk
├── net/wan8021x/                # 插件本体（按上游布局，日后可直接提 PR）
│   ├── Makefile, pkg-descr
│   └── src/…                    # 见第 3 节
├── tests/e2e/                   # pytest 场景
└── .cache/  (gitignored)        # OPNsense 镜像、golden.qcow2、overlay、ssh 密钥、证书、串口日志
```

宿主机只要求装有 docker 和 git，其余工具（qemu、php、python 依赖、证书工具等）都打进 `env/*/Dockerfile`，由 `make tools` 在本地构建。

git 方面：执行 `git init -b main`；`.gitignore` 忽略 `.cache/`；每完成一个里程碑提交一次；不配置远程，也不推送。

## 2. 测试环境（Docker + KVM）

### 拓扑

```
 host 127.0.0.1:8443 ─┐                       ┌─ container "auth"（共享 vm 容器的 netns）
 host 127.0.0.1:2222 ─┤ QEMU user-net         │   hostapd -D wired（内置 EAP server: PEAP/TTLS-MSCHAPv2）
                      │  hostfwd → vtnet0 LAN │   nftables netdev ingress：未授权 MAC 只放行 0x888e
 container "vm"       │                       │   hostapd_cli -a portctl.sh：认证成功/断开时增删授权 MAC
  qemu-system-x86_64 -enable-kvm              │   dnsmasq：在 tap-wan（及 tap-wan.100）上提供 DHCP
   vtnet0 = LAN/管理 (10.0.2.15)              │
   vtnet1 = WAN ── tap-wan ───────────────────┘   （VLAN 场景：tap-wan.100 上再起一个 hostapd 实例）
```

- WAN 直接接在 tap 上，**不经过 Linux bridge**，从而避开 bridge 默认丢弃 01:80:c2:00:00:03 的问题（用 `group_fwd_mask` 绕过也行，但不稳定）。
- 认证端使用 hostapd 的内置 EAP server（Debian 的 hostapd 编译了 wired 驱动和 PEAP/TTLS/MSCHAPv2），用 nftables 加授权 MAC 集合来模拟交换机端口的 authorized/unauthorized 状态。后续可以再加 FreeRADIUS 容器做后端（可选）。
- vm 容器需要：`devices: /dev/kvm, /dev/net/tun`，`cap_add: NET_ADMIN`；端口只绑定 127.0.0.1；串口输出到 `.cache/run/serial.sock`，同时写日志。
- MAC 地址、IP、证书都固定生成；镜像通过 digest 钉死，OPNsense 镜像要校验 sha256，以保证环境一致。

### Golden 镜像 + overlay 重置

1. `make vm-image`：下载 `OPNsense-26.7-nano-amd64.img.bz2` 到 `.cache/`，校验 sha256 后转换为 `base.qcow2`。
2. `make vm-golden`：`provision/bootstrap.py`（pexpect，通过串口）完成以下操作：首次启动 → 以 root/opnsense 登录 → 进入 shell → 写入渲染好的 `config.xml`（LAN=vtnet0 10.0.2.15/24、WAN=vtnet1 DHCP、开启 SSH 密钥登录、API key、关闭初始向导）→ 安装 `git`、`rsync` → 关机。产出 `golden.qcow2`。
3. 每次测试执行 `make vm-reset`：基于 golden 新建 overlay（`qemu-img create -b golden.qcow2 -F qcow2`），几秒内回到干净状态。

### Makefile 目标

`tools`、`env-up`、`env-down`、`vm-reset`、`vm-console`、`vm-ssh`、`deploy`（rsync 插件到 VM 并执行 `make install`/`make upgrade`）、`package`（在 VM 内执行 `make package`，取回 .pkg）、`lint`（在 dev 容器内执行 php -l、phpcs、xmllint、shellcheck，以及上游的 `make lint`/`style`）、`test`（pytest e2e）。

## 3. 插件设计（`net/wan8021x`，包名 `os-wan8021x`）

参考上游已有插件的写法（例如 `net/upnp`、`net/frr` 的 MVC、configd 和 rc 结构），以及 core 的 `interfaces.inc:1859-2031` 中 wpa 配置生成和证书导出的写法。

| 层 | 文件（相对 `src/`） | 内容 |
|---|---|---|
| Model | `opnsense/mvc/app/models/OPNsense/Wan8021x/Wan8021x.xml/.php`、`Menu/Menu.xml`、`ACL/ACL.xml` | `general.enabled`；ArrayField `supplicants`：enabled、interface（InterfaceField，可选物理口或 VLAN 设备）、eap_method（PEAP/TTLS）、phase2（MSCHAPV2，TTLS 额外支持 PAP）、identity、anonymous_identity、password、ca_ref（CertificateField/CA，可选）、domain_suffix_match、eapol_version（1/2）、eapol 目标地址（PAE 组播 / nearest-bridge 01:80:c2:00:00:00）、认证成功后触发 DHCP、debug |
| API | `controllers/OPNsense/Wan8021x/Api/{Settings,Service,Status}Controller.php` | 继承 `ApiMutableModelControllerBase` 和 `ApiMutableServiceControllerBase`；Status 返回每个接口的 `wpa_cli status`（EAP 状态、Supplicant PAE 状态） |
| UI | `controllers/.../IndexController.php`、`views/OPNsense/Wan8021x/index.volt`、`forms/*.xml` | 菜单 Interfaces → 802.1X；bootgrid 编辑每个接口的 supplicant；状态页签；日志页签 |
| configd | `service/conf/actions.d/actions_wan8021x.conf` | start / stop / restart / reconfigure / status |
| 生成器 | `scripts/OPNsense/Wan8021x/setup.php` | 从 config 渲染 `/var/etc/wan8021x/<dev>.conf`（权限 0600，`ap_scan=0`，network 块），导出 CA |
| 服务 | `etc/rc.d/os-wan8021x`（或由 configd 直接调度） | 每个接口执行一次 `wpa_supplicant -B -D wired -i <dev> -c … -P … -s`，外加 `wpa_cli -B -a event.sh` |
| 事件 | `scripts/OPNsense/Wan8021x/event.sh` | 收到 CONNECTED 时，对映射到的 OPNsense 接口执行 `configctl interface reconfigure <if>`（spike 中评估改成更轻量的 dhclient 重启） |
| 钩子 | `etc/inc/plugins.inc.d/wan8021x.inc` | `_services`（仪表盘和服务启停）、`_configure` → `early` 启动、`_syslog` → `/var/log/wan8021x/` |

关于密码：使用 `UpdateOnlyTextField` 存入 config.xml，生成的配置文件设为 0600，日志中不输出凭据。

## 4. 开发路线（里程碑）

- **M0 骨架**：git init、目录、`.gitignore`、`vendor/opnsense-plugins` submodule 和 `Mk` 软链、Makefile 空壳、`docs/`。
- **M1 测试环境**：三个 Dockerfile、compose 文件、bootstrap 生成 golden、`make env-up` 后 GUI 和 SSH 可达。认证端先保持“未授权”，此时 VM 的 WAN 拿不到 DHCP，这正是预期状态。
- **M2 技术 spike（手工验证，结论写入 `docs/research.md`）**
  - S1：VM 内手写 conf，`wpa_supplicant -D wired` 加 PEAP-MSCHAPv2 与 hostapd 认证成功 → nft 放行 → dhclient 获得租约。同时确认用 `/usr/local/sbin` 还是 `/usr/sbin` 下的二进制。
  - S2：启动时序。在 `early` 阶段启动 supplicant，看 dhclient 自身的重试能否在认证成功后拿到地址；再看 event 触发 reconfigure 是否必要以及会不会产生副作用。
  - S3：VLAN 子接口（vtnet1_vlan100）上认证，以及父接口 VLAN offload 标志的影响（参见 pfatt 中 `-vlanhwtag -vlanhwfilter` 的经验）。
  - S4：EAPOL 目标地址。FreeBSD wired 驱动对 PAE 组播与 01:80:c2:00:00:00 的处理，以及是否需要 promisc 或加入组播组；如果需要定制而 wpa_supplicant 无法满足，在此做出决策（打补丁、换端口实现，或首版只提供 PAE/nearest-bridge 两个选项）。
  - S5：拔线（`ip link set tap-wan down/up`）、认证端主动重认证、错误密码、CA 不匹配时 supplicant 的表现。
- **M3 插件 MVP**：按第 3 节实现物理口上的 PEAP/TTLS；`make deploy` 后能在 GUI 中配置、启动并显示状态，WAN 能拿到地址。
- **M4 健壮性**：VLAN、EAPOL 地址选项、拔线和重认证的恢复、失败原因在状态页可见、日志集成、多接口并存、重启后自动恢复。
- **M5 自动化 e2e**：`tests/e2e`，每个用例前执行 vm-reset，通过 API 配置，并断言 VM 获得 IP 以及 hostapd 日志中的 EAP 成功或失败。覆盖：PEAP 成功、TTLS 成功、错误密码、错误 CA、VLAN、拔线恢复、重启恢复、插件卸载后清理干净。
- **M6 打包与发布**：在 VM 内 `make package` 产出 `os-wan8021x-*.pkg`，执行上游 lint/style，补全文档；之后视情况向 opnsense/plugins 提 PR。
- **后续可选**：EAP-TLS（客户端证书，AT&T 场景）、EAP-MD5、FreeRADIUS 后端、HA 同步（`_xmlrpc_sync`）。

## 5. 风险

- nano 镜像在 26.7 的具体文件名和串口交互细节，以下载目录为准；bootstrap 脚本需要应对提示文本的变化，因此按版本钉死。
- 在 OPNsense 中做 interface reconfigure 可能导致短暂断线或重复触发。S2 先验证，必要时改为只重启 dhclient。
- hostapd 的 wired 驱动不会真正阻断端口，靠 nftables 模拟；它和真实交换机的差异记录在 `docs/testenv.md` 中。

## 6. 验证

1. `make tools && make vm-image vm-golden && make env-up`：浏览器打开 https://127.0.0.1:8443 能登录，`tools/bin/vm-ssh` 可以连上。
2. 安装插件前：`vm-ssh ifconfig vtnet1` 没有 IPv4 地址，认证端 nft 计数显示非 EAPOL 包被丢弃。
3. `make deploy`，在 GUI 中为 WAN 配置 PEAP 账号并应用：状态页显示 `EAP state=SUCCESS`、`suppPortStatus=Authorized`，WAN 拿到 172.31.0.x，hostapd 日志出现 `CTRL-EVENT-EAP-SUCCESS`。
4. `make test` 从干净的 overlay 跑完整个 e2e 套件并全部通过；`make lint` 无错误；`make package` 产出可安装的 .pkg。
