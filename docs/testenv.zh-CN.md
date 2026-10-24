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

## 测试与检查

```
make lint      # dev 容器：php -l、phpcs(core ruleset)、pycodestyle、xmllint、shellcheck；VM：上游 make lint
make test      # 对当前 VM 运行 e2e（TESTARGS="-k vlan" 可筛选）
make check     # lint + reset + deploy + test，从干净状态全部跑一遍
```

## 与真实交换机的差异

* 端口状态由 nftables 模拟，只过滤 VM 发往认证端的方向。
* hostapd 的内置 EAP server 不等同于运营商或校园网的 RADIUS。后续可以加一个 FreeRADIUS 容器做后端。
* `authctl flap` 通过 QEMU monitor 的 `set_link` 模拟拔线，guest 能看到 link down 事件。
