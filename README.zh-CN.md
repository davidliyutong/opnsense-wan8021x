[English](README.md) | 简体中文

# os-wan8021x — 适用于 OPNsense WAN 接口的 IEEE 802.1X supplicant

部分运营商、校园网和企业网络会把上联链路置于 802.1X 受控端口之后：在路由器完成认证之前，交换机会丢弃除 EAPOL 以外的所有报文，因此 DHCP 始终无法获得租约。OPNsense 没有为有线接口提供相应的 GUI 配置，本插件补上了这一功能。

* 菜单 **Interfaces → 802.1X Supplicant**，每个已分配的接口（物理接口或 VLAN）对应一个 supplicant
* 支持 PEAP 或 TTLS，内层认证为 MSCHAPv2（TTLS 还支持 PAP），可选外层（匿名）身份
* 可选使用 System → Trust 中的证书颁发机构（CA）校验服务器，并支持域名后缀匹配
* 开机时在接口配置完成后立即启动（`early` 钩子）；端口放行后 dhclient 即可获取租约
* 链路恢复（拔插网线、交换机重启）时重新认证，并在 supplicant 崩溃时自动重启
* 状态页显示端口状态、EAP 状态、认证方式和最近一次失败原因，并提供手动重新认证按钮；同一菜单下可查看日志文件
* 密码在 API 和 GUI 中均为只写，生成的配置文件仅 root 可读写（0600），凭据永远不会写入日志

| 设置 | 编辑 |
|---|---|
| ![settings](docs/screenshots/settings.jpg) | ![edit](docs/screenshots/edit-dialog.jpg) |

![status ok](docs/screenshots/status-ok.png)
![status failed](docs/screenshots/status-failed.png)

目标平台为 OPNsense 26.7（FreeBSD 14）。插件位于 `net/wan8021x/`，目录结构与 [opnsense/plugins](https://github.com/opnsense/plugins) 一致，因此可以原样提交到上游。

## 工作原理

```
GUI / API ──► config.xml ──► setup.php ──► /var/etc/wan8021x/<dev>.conf (0600)
                                              │
rc.d/wan8021x ──► daemon(8) ──► wan8021xd.py ─┼─► wpa_supplicant -D wired -i <dev>   (one per interface)
                                              ├─► control socket: EAP events → status.json
                                              └─► route -n monitor: link DOWN→UP → REAUTHENTICATE
```

* 所用的 `wpa_supplicant` 即 OPNsense 自带的版本（`/usr/local/sbin`，wired 驱动）。
* 身份、密码和域名均以十六进制编码写入，因此引号、反斜杠和 UTF-8 字符都无需转义。
* FreeBSD 的 wired 驱动感知不到链路变化。拔插网线后，交换机会重置端口，而 supplicant 仍认为自己处于已认证状态，因此由守护进程自行跟踪链路状态。这里无法使用 devd：它对每个事件只执行优先级最高的规则，而该规则是 core 的 `rc.linkup`。

背景与实测数据：[docs/research.zh-CN.md](docs/research.zh-CN.md)。

## 仓库结构

```
net/wan8021x/      插件本体（opnsense/plugins 目录结构）
env/               测试环境：vm/（QEMU/KVM）、auth/（认证端）、dev/（工具链）、provision/
tests/e2e/         端到端测试（pytest）
tools/             vmctl.py, vmlib.py, lint.sh, bin/vm-ssh
spikes/            docs/research.md 背后的实验脚本
vendor/plugins     opnsense/plugins @ 26.7.7（Mk/、Templates/ 等由此软链接）
vendor/core        opnsense/core @ 26.7.7（lint 规则、ruleset.xml）
docs/              路线图、调研笔记、测试环境
.cache/            下载的镜像、虚拟机磁盘、密钥、日志（git 忽略）
```

## 开发

宿主机需要带 compose 的 docker、git 以及 `/dev/kvm`。其余所有组件（QEMU、hostapd、PHP 和 Python 工具链）都由 `env/*/Dockerfile` 构建，所有输入（OPNsense 镜像及其 SHA256、基础镜像 digest、Debian snapshot、phpcs）都在 `env/versions.env` 和各 Dockerfile 中固定版本。

```sh
git clone --recurse-submodules https://github.com/davidliyutong/opnsense-wan8021x.git
make tools            # 构建本地镜像
make image golden     # 下载并校验 OPNsense 26.7 nano，制作 golden 磁盘（约 1 分钟，仅需一次）
make reset            # 基于 golden 磁盘重建全新虚拟机和认证端（约 20 秒）
make deploy           # 在虚拟机内构建软件包并安装
make test             # 针对运行中的虚拟机执行端到端测试（TESTARGS="-k vlan"）
make lint             # 本地运行 phpcs/pycodestyle/shellcheck，并在虚拟机内运行上游 "make lint"
make check            # lint + reset + deploy + test（约 3 分钟）
make package          # .cache/pkg/os-wan8021x-devel-*.pkg
make help             # 其他所有目标（console、ssh、logs、down 等）
```

GUI：https://127.0.0.1:18443（root / opnsense，自签名证书）；ssh：`make ssh`。端口在 `env/versions.env` 中设置。

### 测试环境

```
 127.0.0.1:18443/12222 ─► vm container: qemu-system-x86_64 -enable-kvm (OPNsense 26.7 nano)
                              vtnet0 = LAN (QEMU user net, management)
                              vtnet1 = WAN ── tap-wan ──┐
 auth container (same netns):                           │
   hostapd -D wired on tap-wan and tap-wan.100 (VLAN 100), built-in EAP server
   nftables: only EAPOL passes until hostapd authorizes the MAC
   dnsmasq: 172.31.0.0/24 untagged, 172.31.100.0/24 on VLAN 100
```

测试账号：`alice` / `alice-secret`（PEAP、TTLS-MSCHAPv2、TTLS-PAP），`bob` / `bob-secret`，以及一个用户名含反斜杠和 UTF-8 字符、密码含引号的用户（见 `env/auth/eap_user`）。认证端（authenticator）可以拔掉虚拟机的网线、重置端口并报告已授权的 MAC（`authctl`）；测试通过 `.cache/run/authctl.sock` 访问它。详见 [docs/testenv.zh-CN.md](docs/testenv.zh-CN.md)。

25 个端到端测试覆盖了：所有认证方式、错误密码、伪造 CA 与域名不匹配、特殊字符、链路中断、手动重新认证、VLAN 上联、同时使用两个接口、重启、升级与卸载、输入校验、敏感信息保护以及 GUI 页面。

## 状态与限制

里程碑 M0–M5 已完成；打包已可用，尚待提交上游。参见 [docs/ROADMAP.zh-CN.md](docs/ROADMAP.zh-CN.md)。

* 暂不支持 EAP-TLS（客户端证书）、EAP-MD5 以及在 802.1X 端口上运行 PPPoE。
* EAPOL 目的地址固定为 PAE 组播地址 `01:80:c2:00:00:03`；wpa_supplicant 没有修改它的选项。如果认证端有需要，请使用接口自身的混杂模式和 MAC 克隆（spoofmac）设置。
* 仅针对 hostapd 内置的 EAP 服务器进行过测试，未在真实的 RADIUS 服务器或真实交换机上测试。

## 许可证

BSD 2-Clause，与 OPNsense 相同。
