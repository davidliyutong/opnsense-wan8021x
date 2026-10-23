# os-wan8021x —— OPNsense WAN 802.1X supplicant 插件

为 OPNsense 的 WAN（物理口或 VLAN 子接口）提供 IEEE 802.1X 有线认证（PEAP / TTLS，MSCHAPv2），可在 GUI 中配置。

* 插件源码：`net/wan8021x/`（目录布局与 opnsense/plugins 一致）
* 开发路线：[docs/ROADMAP.md](docs/ROADMAP.md)
* 调研与 spike 结论：[docs/research.md](docs/research.md)
* 测试环境：[docs/testenv.md](docs/testenv.md)

## 快速开始

宿主机需要 docker（含 compose）、git 和 `/dev/kvm`。

```sh
git submodule update --init
make tools            # 构建本地工具镜像
make image golden     # 准备 OPNsense 26.7 golden VM（只需做一次）
make reset            # 启动干净的 VM 和认证端
make deploy           # 把插件安装进 VM
make test             # 端到端测试
make check            # lint + 全新 VM + 部署 + 全部测试
make package          # 生成 .cache/pkg/os-wan8021x-devel-*.pkg
```

## 功能

* 菜单 **Interfaces → 802.1X Supplicant**：为每个已分配的接口（物理口或 VLAN）配置一个 supplicant
* PEAP / TTLS，内层 MSCHAPv2（TTLS 另支持 PAP），可设外层匿名身份
* 可选的服务器证书校验（System → Trust 中的 CA）和域名后缀匹配
* 开机时在 `early` 阶段启动；link up 时自动重新认证（拔线恢复）；进程退出后自动重启
* 状态页显示端口状态、EAP 状态、方法和最近一次失败原因，并支持手动重新认证
* 日志：Interfaces → 802.1X Supplicant → Log File

GUI：https://127.0.0.1:18443（root / opnsense）；ssh：`make ssh`。
