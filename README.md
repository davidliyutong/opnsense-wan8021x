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
```

GUI：https://127.0.0.1:18443（root / opnsense）；ssh：`make ssh`。
