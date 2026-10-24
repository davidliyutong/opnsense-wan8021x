[English](testenv.md) | 简体中文

# 测试环境

宿主机只需要 docker（含 compose 插件）、git 和 `/dev/kvm`。其余工具都在本仓库的
Dockerfile 里构建，所有运行状态都放在 `.cache/`（已加入 gitignore）。

## 拓扑

```
 127.0.0.1:18443 (GUI) ─┐
 127.0.0.1:12222 (ssh) ─┤ socat → QEMU hostfwd(127.0.0.1) → vtnet0 LAN 10.0.2.15/24
                        │
 container vm: qemu-system-x86_64 -enable-kvm  (OPNsense 26.7 nano)
    vtnet0 = LAN (QEMU user net, 管理用)
    vtnet1 = WAN ── tap-wan ─┐
                             │ (同一个 network namespace)
 container auth:             │
    hostapd -D wired  on tap-wan       (未打 tag，PAE 组播 01:80:c2:00:00:03)
    hostapd -D wired  on tap-wan.100   (VLAN 100)
    hostapd -D wired  on tap-wan.200   (VLAN 200)
    内置 EAP server：PEAP / TTLS，phase2 MSCHAPv2（TTLS 另支持 PAP）
    nftables netdev ingress：未授权 MAC 只放行 EAPOL（0x888e）
    hostapd_cli -a portctl.sh：AP-STA-CONNECTED/DISCONNECTED → 增删授权 MAC
    dnsmasq：172.31.0.0/24（untagged），172.31.100.0/24（VLAN 100），172.31.200.0/24（VLAN 200）
```

几个细节：
* WAN 不经过 Linux bridge。bridge 默认会丢弃 01:80:c2:00:00:0X 链路本地帧，绕开它省去了调 `group_fwd_mask` 的麻烦。
* 发布出来的端口先经过容器内的 socat 再到 loopback 上的 hostfwd。libslirp 只把来自 loopback 的连接源地址改写为 10.0.2.2；其他来源会保留原始地址，而 guest 没有到那个地址的回程路由。
* VM 的 MAC 地址固定：LAN 52:54:00:00:01:01，WAN 52:54:00:00:02:01。

## 账号

| 用途 | 账号 |
|---|---|
| OPNsense GUI/console | root / opnsense |
| ssh | `.cache/ssh/id_ed25519`（`make ssh`） |
| API | `.cache/ssh/apikey.json` |
| EAP | alice / alice-secret（PEAP、TTLS-MSCHAPv2、TTLS-PAP），bob / bob-secret |
| CA | `.cache/auth/pki/ca.crt`；`rogue-ca.crt` 用于测试 CA 校验失败 |

## 常用命令

```
make tools          # 构建镜像
make image golden   # 下载、校验 nano 镜像，生成 golden 盘（约 5 分钟，只需做一次）
make reset          # 基于 golden 新建 overlay 并启动，回到干净状态
make up / down      # 保留当前 VM 状态启停
make console        # 串口控制台（ctrl-] 退出）
make ssh
make status         # 授权 MAC 集合与计数器
docker compose -f env/compose.yml exec auth authctl sta|deauth MAC|flap 5|leases
```

## 测试如何控制认证端

dev 容器没有 docker 权限。认证端在 `.cache/run/authctl.sock` 上提供 `authctl` 的远程调用
（每个连接发送一行参数，返回输出加 `rc=N`），日志同时写到 `.cache/run/auth.log`。
`tests/e2e/conftest.py` 中的 `auth()`、`authorized()` 就是基于它实现的。

```
printf 'authorized\n' | socat - UNIX-CONNECT:.cache/run/authctl.sock
```

`authctl preauth MAC` 可临时放行尚未认证的 MAC，让它先获取旧租约；
`authctl network changed` 把未打 tag 的网段从 `172.31.0.0/24` 切到 `172.31.10.0/24`，不产生链路事件，
`authctl network default` 则恢复原网段。`tests/e2e/test_dhcp.py` 用这些操作验证认证成功后主动替换旧租约。

## 测试与检查

```
make lint      # dev 容器：静态检查与守护进程单元测试；VM：上游 make lint
make test      # 对当前 VM 运行 e2e（TESTARGS="-k vlan" 可筛选）
make check     # lint + reset + deploy + test，从干净状态全部跑一遍
```

## GitHub CI 与本地 act

`.github/workflows/` 下有三个 workflow：`ci.yml`（每次 push 和 pull request）、`build.yml`（可复用：通过 `vmactions/freebsd-vm` 在 FreeBSD 虚拟机中运行上游 `make lint` + `make package`）和 `release.yml`（`v*` tag）。

```
make ci-local                    # 用 act 运行 ci.yml，基于 HEAD 的干净 clone
make ci-local ACTARGS="-j lint"  # 只运行一个 job
tools/ci-local.sh -W .github/workflows/release.yml -e EVENT.json -j build
                                 # release 构建；EVENT.json: {"ref":"refs/tags/v0.1"}
```

`tools/ci-local.sh` 会把 HEAD clone 到 `.cache/act/work/repo`（未提交的改动不会被测试），构建 job 镜像 `env/act/Dockerfile`（catthehacker ubuntu-24.04 镜像加上 rsync，runner 的 home 设为 `.cache/act`，使 `vmactions/freebsd-vm` 能像在 GitHub runner 上一样找到 `$HOME/work`），并透传 `/dev/kvm`。artifact 保存在 `.cache/act/artifacts`。`release.yml` 的 publish job 只在 GitHub 上运行。

### 资源限制

job 容器按 GitHub 托管的私有仓库 `ubuntu-latest` runner 限制：2 CPU、8 GB 内存、无 swap（`--cpus=2 --memory=8g --memory-swap=8g`）。公开仓库为 4 CPU / 16 GB。两者都有 14 GB SSD；overlay2 无法限制磁盘，因此改为实测磁盘用量。

实测环境：act 0.2.88，2026-10-24（job 容器的 cgroup v2，每 5 秒采样）：

| Job | 耗时 | CPU | 内存 | 磁盘 |
|---|---|---|---|---|
| Lint and format | 约 10 秒（dev 镜像无缓存构建另需约 30 秒） | 不到 1 核 | job 容器 37 MB；dev 镜像（300 MB）在宿主机 docker daemon 中构建，不受限制 | 镜像 300 MB |
| FreeBSD lint + package | 约 1.5–2 分钟 | 虚拟机启动和装包时 2 核跑满，共约 70 CPU 秒 | anon 峰值 3.8 GiB（QEMU 客户机，配置 6 GiB），页缓存约 3.8 GiB；无 OOM kill，未触及 `memory.max` | 峰值约 4.4 GB（下载 FreeBSD 15.1 镜像 + 解压后 3.5 GB 的 qcow2） |

同步进虚拟机的工作区约 230 MB（主要是 `vendor/core`）。lint job 使用宿主机的 docker socket，其 `dev` 容器和镜像构建不受上述限制。

## 与真实交换机的差异

* 端口状态由 nftables 模拟，只过滤 VM 发往认证端的方向。
* hostapd 的内置 EAP server 不等同于运营商或校园网的 RADIUS。后续可以加一个 FreeRADIUS 容器做后端。
* `authctl flap` 通过 QEMU monitor 的 `set_link` 模拟拔线，guest 能看到 link down 事件。
