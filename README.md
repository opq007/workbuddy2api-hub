# WorkBuddy2API-Hub — 国际版、国内版多账号网关中枢

<p align="center">
  <a href="https://github.com/ardeyouxipianyi/workbuddy2api-hub/releases"><img src="https://img.shields.io/badge/Release-v1.5.4-2496ED?style=flat-square" alt="Version 1.5.4"></a>
  <img src="https://img.shields.io/badge/Python-3.9+-blue.svg?style=flat-square" alt="Python">
  <img src="https://img.shields.io/badge/API-OpenAI_Compatible-412991?style=flat-square" alt="OpenAI API">
  <img src="https://img.shields.io/badge/Dual_Realm-Intl_&_CN-0DBD8B?style=flat-square" alt="Dual Realm">
  <img src="https://img.shields.io/badge/License-MIT-green.svg?style=flat-square" alt="License">
  <img src="https://img.shields.io/badge/Vibe_Coding-100%25-ff69b4?style=flat-square" alt="Vibe Coding">
</p>

本项目为 **WorkBuddy2API-Hub**，将腾讯 **[www.workbuddy.ai](https://www.workbuddy.ai)** (国际版) 与 **[codebuddy.cn](https://www.codebuddy.cn)** (国内版) 原生服务封装为标准 OpenAI 兼容接口，支持 Chat Completions 与 Responses API。具备多账号负载轮询、稳定物理设备指纹隔离、OAuth 一键免客户端登录、国内版每日签到与实时积分查询、国内成长任务全自动完成与国内版积分任务、后台常驻定时调度器、Web 监控看板等全套能力。

- **开箱即用**：绿色包自带精简 Python ，双击批处理脚本即启。
- **双区域独立路由**：支持 🌐 国际版 与 🇨🇳 国内版独立配置与管理，严格隔离串号，看板一键切换且状态落盘持久化。
- **模型列表严格按照桌面应用 1:1 对齐**：按官方桌面端主界面清洗收敛，彻底剔除内部代码补全通道与底层专线变体。
- **稳定物理设备指纹隔离 (`derive_id`)**：国际版与国内版统一方案，以账号自身 UID 稳定哈希派生专属机器特征与会话标识，同一账号长期固定在一台虚拟物理设备上，天然防多号关联风控。
- **OAuth 一键免客户端登录**：无需在本地安装桌面客户端，点击看板链接在浏览器完成授权即可自动入库；亦支持扫描本地客户端两步确认导入。
- **国内版签到与实时积分查询**：支持国内版每日签到领积分，实时聚合账户资源包用量与余额。
- **国内成长任务与积分任务全自动完成**：全自动接取任务、构造行为事件上报点亮并自动领取奖励，支持猫猫日常旅行与连续打卡。
- **后台常驻定时调度器**：每日整点排程（09:00/21:00 签到与猫猫旅行 · 22:00 保活 · 01:00 夜猫），国际版自适应为专属 Token 集中保活。
- **双协议全功能支持**：同时支持标准 OpenAI Chat Completions 协议与 Responses API (Codex / Claude Code)。
- **现代化 Web 看板**：单行自适应弹性指标卡片、模型性能指标与用量一览融合大表、实时请求流水监控。

> ⚡ **Vibe Coding 产物**：本项目为 100% Vibe Coding 协同产物，由人类开发者提出架构与业务意图，AI 助手端到端完成逆向分析、链路调度、WAF 指纹脱敏与界面编写。

---

## 一、快速启动

### 1. 本机单机使用

**Windows**：双击运行 **`start-wb-proxy.bat`**，保持窗口运行：

- **API 接口地址**：`http://127.0.0.1:8788/v1`
- **Web 监控看板**：`http://127.0.0.1:8788/`

**macOS**：双击运行 **`start-wb-proxy.command`**（首次打开若被 Gatekeeper 拦截，在 Finder 中右键该文件 →「打开」确认一次即可），或在终端执行：

```bash
./start-wb-proxy.sh          # 默认 8788 端口
./start-wb-proxy.sh 9000     # 自定义端口
```

启动脚本会自动挑选可用的 Python 3.9+（优先 `/usr/bin/python3` 与 Homebrew 的 `python3`，也兼容绿色包内置的 `python/bin/python3`）；若系统没装，可用 `xcode-select --install` 或 `brew install python` 安装。

> 从 zip 解压后如果提示权限不足，先执行一次：
> `chmod +x start-wb-proxy.sh start-wb-proxy.command start-wb-proxy-lan.sh start-wb-proxy-lan.command allow-firewall.command`

首次启动若无账号，直接打开看板点击 **「+ 添加账号 (OAuth)」**，在浏览器完成授权即可自动加入（macOS 上也可在看板「设置」里扫描本地桌面客户端凭据导入）。

### 2. 面板访问密码

打开看板需要先输入**面板访问密码**，默认是 `admin`。它与 API Key 相互独立：

- 面板密码只用于打开网页看板，可在看板的「设置」页随时修改（也可启动时用 `--panel-password` 指定）；
- 密码以 PBKDF2-SHA256 摘要形式保存在 `accounts/settings.json`，不存明文；
- 登录状态存放在浏览器会话中，关闭浏览器或重启网关后需要重新输入。

> 首次登录后请立即到「设置」修改默认密码。

### 3. 局域网共享模式
允许局域网内其他设备（手机、平板、协同电脑）访问：

- **Windows**：双击运行 **`start-wb-proxy-lan.bat`**；
- **macOS**：双击运行 **`start-wb-proxy-lan.command`**，或在终端执行：

```bash
./start-wb-proxy-lan.sh              # 端口 8788，自动生成/复用 API Key
./start-wb-proxy-lan.sh 8788 我的Key  # 自定义端口与 Key
```

- **Base URL**：`http://<本机局域网IP>:8788/v1`
- **密钥随机生成并持久化**：LAN 模式不会使用任何写死的默认密钥。首次启动时自动生成一个高强度随机 API Key，保存到 `accounts/settings.json`，并在终端打印；之后重启会复用同一个 Key（不会每次变化）。
- **自定义 Key**：启动脚本支持第二个参数传入自己的 Key，例如 `start-wb-proxy-lan.bat 8788 我的Key`（Windows）/ `./start-wb-proxy-lan.sh 8788 我的Key`（macOS），此时以你传入的为准。
- **macOS 防火墙**：首次监听网络端口时系统会弹窗询问是否允许 Python 接受传入连接，选择「允许」即可；macOS 15+ 还需在「系统设置 → 隐私与安全性 → 本地网络」中允许终端访问。也可运行 `./allow-firewall.command` 查看防火墙状态并把 Python 加入允许列表。
- 支持带密钥直达面板：`http://<IP>:8788/?key=生成的Key`。

---

### 4. 多 API Key 管理与出口绑定 

网关支持**多 API Key 并行管理**，并可为每个 Key 指定独立出口。不同客户端使用各自绑定的 Key，国内/国外流量互不干扰，完全无需在看板上手动频繁切换网关全局出口：

在 Web 看板的「设置」页面中进行管理：
- **添加与在线生成**：输入 Key 名称，点击「生成随机 Key」即可一键生成高强度密钥，支持随时复制；
- **出口自由绑定**：
  - **🌐 国际版出口**：该 Key 的调用流量强制固定走腾讯国际版官方出口（`www.workbuddy.ai`）；
  - **🇨🇳 国内版出口**：该 Key 的调用流量强制固定走腾讯国内版官方出口（`copilot.tencent.com`）；
  - **跟随面板切换**：未绑定特定出口的 Key，请求将实时跟随看板顶部的全局出口开关分流。
- **状态管理**：可单独开启/停用某个 Key，支持一键删除，删除即刻失效；
- **配置持久化**：所有 Key 均保存在本地 `accounts/settings.json` 中，重启保持生效；
- **安全防冲突机制**：一旦在面板配置保存过 API Key，启动命令或脚本中的旧参数（如 `--api-key`）会自动失效，彻底避免旧密钥在后台漏网继续使用；
- **模型区域自检防护**：当某个 Key 绑定的出口与其请求的模型不匹配时（例如用国际版 Key 去调国内独占的 `deepseek-v4-pro`），网关会直接返回通俗易懂的 400 校验错误，杜绝上游 WAF 晦涩的拒流报错。

### 5. Docker 容器化部署 
自带完整容器配置，零外部依赖，极速启动：

```bash
# 1. 后台启动容器 (自动构建并运行)
docker compose up -d

# 2. 查看网关日志
docker compose logs -f
```

亦可直接使用 `docker run` 启动：
```bash
docker run -d   --name wb-proxy   --restart unless-stopped   -p 8788:8788   -v $(pwd)/accounts:/app/accounts   -v $(pwd)/usage:/app/usage   -e API_KEY=your_secret_key   $(docker build -q .)
```

- **持久化目录**：`./accounts` (账号凭证及活动区域) 与 `./usage` (请求流水与指标快照)；
- **配置参数**：通过环境变量 `API_KEY`、`PORT` 自定义。

---

## 二、核心特性详解

### 1. 模型列表严格按照桌面应用 1:1 对齐
针对官方本地配置清单（50+ 底层模型）进行了深度清洗，剔除行内代码补全专用模型（如 `codewise-*`、`completion-gf`、`hunyuan-3b/7b`）与底层多云专线变体（如 `*-volc`、`*-lkeap`），严格对齐官方桌面端主界面：

* **🌐 国际版 (16 个)**：`deepseek-v4.1-flash`、`gpt-6-astra`、`hy4-preview-f`、`hy4-preview`、`hy3`、`gpt-5.6-sol`、`gpt-5.6-terra`、`gpt-5.6-luna`、`gpt-5.5`、`gpt-5.4`、`gpt-5.3-codex`、`gemini-3.5-flash`、`glm-5.3`、`glm-5.2`、`kimi-k3`、`kimi-k2.6`。
* **🇨🇳 国内版 (14 个)**：`hy4-preview-f`、`hy3`、`deepseek-v4.1-flash`、`deepseek-v4-pro`、`glm-5.3`、`glm-5.3-flash`、`glm-5.2`、`glm-5.1`、`glm-5v-turbo`、`minimax-m3`、`kimi-k3-1`、`kimi-k2.8-preview`、`kimi-k2.7`、`kimi-k2.6`。

每个模型均宣告完整桌面软件中显示的上下文窗口（K/M 规范）、单次最大输出、视觉支持、工具调用以及推理档位。

> 💡 **关于同模型跨区域混合轮询的说明**：
> 目前对于同时存在于国内版和国际版的同名模型（如 `deepseek-v4.1-flash` 等），**暂未实现跨国内/国际账号的自动混合轮询**，而是作为两个独立区域分别配置与调度，请求只能走当前所选网关的独立出口。这主要是出于各区域网络环境隔离、出站指纹对齐与账号防风控安全考量；待作者后续实测验证确认长期使用稳定且无封号风险后，会尽快跟进并补齐同名模型的跨区域混合轮询能力。

### 2. 稳定物理设备指纹隔离 (`derive_id`)
国际版与国内版统一采用相同的底层算法内核：以账号自身的 UID 结合固定业务盐值单向哈希派生出固定的机器码与会话标识：

- **同一账号长期稳定**：每次出站请求固定来自同一台虚拟个人物理设备，彻底规避机器码随机漂移风控；
- **多账号天然隔离**：不同账号之间机器码与会话彼此独立，彻底阻断跨账号关联风控检测。

### 3. 国内版每日签到、成长任务与积分任务全自动完成
集成官方成长中心全套自动化完成引擎：

- **每日签到**：一键完成国内版每日打卡领取日常积分；
- **成长任务与积分任务**：自动批量接取未接任务，构造真实规范行为事件上报点亮（画布创建、灵感案例、模板使用、模型体验、多轮对话等 14 项任务），并自动调用端点领奖入账；
- **猫猫日常**：自动检查猫猫旅行状态，在家时自动派出旅行，归来时自动领取奖励。

### 4. 后台常驻定时调度器 (Scheduler)
常驻后台，每日按固定整点执行自动化运维排程：

- **每日 09:00 & 21:00**：国内版账号自动签到与猫猫旅行闭环；
- **每日 22:00**：集中扫描全库账号，Token 剩余寿命不足 2 小时自动调用 Refresh Token 保活；
- **每日 01:00**：深夜时段自动执行夜猫子任务；
- **国际版动态自适应**：切换至国际版视图时，调度器自动隐藏签到/猫猫逻辑，专职执行 Token 自动保活与凭证常驻。

---

## 三、账号添加与管理

打开看板 `http://127.0.0.1:8788/`，在「账号」区域操作：

### 方式一：浏览器 OAuth 授权（推荐，免客户端）
1. 点击 **「+ 添加账号 (OAuth)」**；
2. 选择要登录的区域（国际版 / 国内版），点击弹出的官方授权链接并在浏览器完成登录；
3. 程序自动检测回调，完成后账号自动加入账号池，无需手动复制凭证。

### 方式二：从本地桌面应用导入（两步确认）
1. 点击 **「📥 扫描桌面客户端账号」**；
2. 弹窗只读展示本机检测到的桌面客户端账号（昵称、区域、域名、有效期）；
3. 确认无误后点击该行对应的 **「导入」** 按钮，国际版账号自动归入国际版列表，国内版账号自动归入国内版列表。

---

## 四、客户端配置与接入

### OpenAI 兼容客户端 (Chatbox / NextChat / Cherry Studio / Kelivo 等)
- **API 接口地址 (Base URL)**：`http://127.0.0.1:8788/v1`（局域网为 `http://<局域网IP>:8788/v1`）
- **API Key**：
  - 本机单机模式（未配置 Key 且未开 LAN）：可留空或填任意字符；
  - 已在看板配置 Key 或 LAN 模式：在看板「设置」页面添加或复制已绑好出口的 API Key（如固定走国际版的 Key 或国内版的 Key）。
- **模型名称**：填入 `/v1/models` 中列出的任意官方对齐模型 ID（如 `deepseek-v4.1-flash`、`gpt-6-astra`、`glm-5.3` 等）

### Codex CLI / Claude Code (Responses API)
网关原生内置 Responses 协议双向转换与 WAF 指纹脱敏：
```bash
export OPENAI_BASE_URL="http://127.0.0.1:8788/v1"
export OPENAI_API_KEY="你在看板设置中添加并绑定的API_Key"
```

---

## 五、看板与接口一览

访问 `http://127.0.0.1:8788/` 即可使用集成看板，核心接口包括：

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | / | Web 用量与任务监控看板 |
| POST | /v1/chat/completions | 标准 Chat Completions 接口 |
| POST | /v1/responses | Responses API 协议接口 |
| GET | /v1/models | 官方对齐模型列表（含能力与规格宣告） |
| GET | /tasks | 国内版成长任务、连续打卡与猫猫日常状态 |
| POST | /tasks/run | 触发国内成长任务全自动点亮与领奖 |
| POST | /tasks/travel | 触发猫猫日常旅行（派出 / 领奖） |
| GET | /scheduler | 定时调度器运行状态与排程日志 |
| POST | /scheduler/trigger | 手动立即执行后台巡检保活 |

---

## 六、版本更新记录 (Changelog)

### 未发布 (Unreleased)

- **修复代理槽位测试报 `<urlopen error [Errno 104] Connection reset by peer>`**：网关此前把所有槽位 URL 都交给 urllib 的 `ProxyHandler`，而 urllib 只会说 HTTP——对 `socks5://` 槽位，它把原始 `CONNECT` 文本直接发到 SOCKS 端口，SOCKS 服务器按 RFC 1928 校验首字节版本号失败后直接 RST，报错看似"代理不可用"，实际代理本身完全正常。现按 scheme 分流：`http(s)://` 槽位维持原有 HTTP 代理路径（CONNECT + URL 内嵌 Basic 认证），`socks5/socks5h/socks4/socks4a` 槽位改走纯标准库实现的 SOCKS 隧道（RFC 1928 握手 + 用户名/密码子协商），域名交由代理端解析（避免本地 DNS 泄露出口关联）。出口 IP 测试同时不再只盯 `api.ipify.org` 单一目标（该域名对部分国内出口会被 GFW 掐断 TLS 造成误报），改为多个回显端点依次回退，失败时聚合报出尝试过的目标。

### v1.5.4

- **国内版模型目录补上 `hy4-preview-f`**：国内版白名单 `CN_UI_ORDER` 的第一项就是 `hy4-preview-f`，但内置的国内版静态目录里只有同名的旧 id `hy4-preview`（x0.29），它不在白名单里、会被裁剪掉，而 `hy4-preview-f` 本身只能靠本机桌面端缓存补进来。国内版没有国际版那样的上游兜底，所以在没装过国内版桌面端的机器上，国内版列表会少一个、Hy4 preview 直接消失。现按桌面端缓存里的实际条目补进静态目录（x0.00、1M 输入 / 64k 输出、推理档 high）。

- **看板显示积分消耗与账号昵称**（PR #45，感谢 [@Pro-XK](https://github.com/Pro-XK)）：最近请求表新增「积分」列（逐条请求的上游扣费），账号列改显示昵称并在 tooltip 里保留完整 uid（账号已不在池中时回退 uid 前缀）；「网关调用量」卡片副标题追加累计积分；账号透视表新增「消耗积分」列，跟随「今日 / 全部历史」切换。

- **积分口径统一**：卡片读 `/usage`（当前出口、原先只累计成功请求），透视表读 `/usage/analytics`（全出口、含失败请求），同一页面上两个都叫「消耗积分」的数字永远对不上。现在两边统一为「上游实际计费过的请求都计入，客户端取消不计」——失败请求若已被上游扣费同样计入；卡片文案改为「本出口累计消耗」、透视表列名改为「消耗积分 (全出口)」，把各自覆盖的范围写明。另外 credit 记录为 0 的行现在显示 `0.00` 而不是 `—`。

### v1.5.3

- **移除网关内置的 `web_search` / `web_fetch` 代跑**（修复 issue #43）：v1.5.0 曾让网关在客户端声明这两个工具时自行注入定义、拦截调用、在本地执行搜索并把结果喂回模型。该实现有三个缺陷：参数名只认 `query`（模型若传 `queries` 数组会被判成"查询为空"）、客户端原有的声明未被去重导致工具被重复下发、以及内部循环耗尽后发出一条合成的 `resp_wrapup`（`status=completed`、`output=[]`）——把一次工具失败伪装成"回答正常结束"，用户看到的是回答说到一半突然停住。

  实测确认**上游本来就没有服务端 `web_search` 能力**：直接向上游声明 `{"type":"web_search"}` / `web_search_preview` / `web_fetch`，国际版与国内版的模型反应均与"不声明任何工具"完全一致（都回答"我无法联网搜索"），调用次数为 0。因此不再由网关代跑，**工具声明原样透传**：客户端能拿到自己声明的工具调用，模型在无搜索能力时如实回答"我无法联网"。

  行为变化：声明 `web_search` 的客户端不再获得网关代跑的搜索结果；如果客户端自己声明的是普通函数形式的搜索工具，工具调用现在会正常返回给客户端（此前会被网关吞掉）。

### v1.5.2

- **修复 Docker 镜像缺少运行时模块**（PR #41，感谢 [@wiggins-kong](https://github.com/wiggins-kong)）：v1.5.0 新增 `wb_identity.py` 与 `wb_webtools.py` 后，Dockerfile 仍沿用 v1.5.0 之前的显式 COPY 清单，两个模块未进入镜像。容器启动即报 `ModuleNotFoundError: No module named 'wb_identity'`，Docker 部署完全不可用。现改为 `COPY wb_*.py dashboard.html ./`，按既有 `wb_*.py` 命名约定自动纳入，后续新增模块不会再漏。

  > 影响范围：**仅 Docker 部署**。v1.5.0 / v1.5.1 的标签提交与 ghcr 镜像受影响；便携绿色包始终包含全部模块，Windows / macOS 直接运行不受影响。使用 Docker 的用户请升级到本版本。

### v1.5.1

- **数据看板「今日 / 全部历史」口径修正**（issue #39）：切换按钮此前只影响部分指标卡，第一张卡被写死为今日、第二张写死为累计，因此按钮看起来「不起作用」；而当日志中只有当天的数据时，两张卡天然显示同一个数字，看起来就像「今天和全部一样」。现在首张卡跟随切换（标题同步变为「今日消耗 Token」/「全部历史消耗 Token」），第二张固定为累计作为对照；当两者数值相同时会明确标注原因（日志中暂无更早数据 / 当前为全部历史视图）。
- **模型性能表跟随时间范围**：该表此前直接读取全量数据，与页面顶部的时间范围无关。`/usage` 与 `/usage/perf` 新增 `range` 参数（`range=today` 取本地零点起算，与「今日」指标的既有口径一致；缺省或未知值不过滤，既有调用方行为不变），表格数据随之切换。
- **修复账号用量透视表丢失**：`renderAnalytics()` 一直在向 `analyticsAccountTbody` 写入数据，但该表格的标记在一次「移除冗余区块」的改动中被误删，`getElementById` 恒为 `null`，导致整个「各账号用量透视与模型消耗分布」区块从未渲染。已恢复表格并适配移动端卡片布局。
- **模型性能表新增筛选**（issue #39）：表格标题栏新增「账号」「模型」两个下拉，可单独或组合筛选。汇总行会随筛选重算（标签变为「筛选结果合计」，延迟/速度按各自样本数加权平均），不会出现合计与明细互相矛盾；下拉选项由当前数据动态生成，某项在切换范围后消失时会自动清除该筛选，避免停留在必然空结果的状态。
- **新增测试**：`_test_usage_range.py`（22 项断言，时间范围过滤语义、缓存隔离、与 analytics 口径一致性）与 `_test_matrix_filters.js`（19 项断言，以 Node 驱动真实 dashboard 代码验证筛选、汇总重算与失效应答）。全部测试合计 290 项断言通过。

### v1.5.0

- **Codex App namespace 工具支持**（PR #33，感谢 [@Cekxri](https://github.com/Cekxri)）：新版 Codex App 把 MCP／插件／子代理的工具包在 `namespace` 里声明，此前原样转发导致上游看不懂、工具全部消失，回程的 `function_call` 又缺 `namespace` 字段，客户端找不到执行器。现展开 namespace 后转发，并在回程补上 namespace；同时支持 `agent_message`（子代理）与无 `call_id` 的 `function_call_output`。
- **出站身分标头修正**（PR #33）：原 `X-Product: WorkBuddy` / `X-IDE-Type: WorkBuddy` 是自创组合，官方为 `X-Product: SaaS` 且区分 CLI 与 WorkBuddy 两套身分（各自对应不同端点）。新增 `wb_identity.py` 定义两套身分，并在看板账号行提供 CLI/WB 切换。默认仍为 CLI，行为与旧版一致。
- **本地 `web_search` / `web_fetch`**（PR #33）：客户端声明时由网关代跑（DuckDuckGo HTML，纯标准库）。
- **DeepSeek 多轮 `reasoning_content` 回填补全**（PR #36，感谢 [@ayeaaaa](https://github.com/ayeaaaa)）：补上官方 `ReasoningContentBackfillRule` 的 `thinkingEnabled` 半边——只要 thinking 开启就回填，不再只依赖历史里已有推理痕迹；同时把字段镜像到 `reasoning` 且保证非空（上游校验 `len(reasoning) > 0`），非字符串值按缺失处理。与 v1.4.9 的档位注入互补：那个让上游真的返回思维链，这个让丢失思维链的历史不被拒。
- **看板移动端布局**（PR #37，感谢 [@ayeaaaa](https://github.com/ayeaaaa)）：新增 `≤640px` 手机布局（表格转卡片、指标卡两列换行、触控目标 ≥40px）与 `≤400px` 小屏微调；`>860px` 桌面布局完全不变。
- **API Key 行 id 唯一化**（PR #40，感谢 [@wiggins-kong](https://github.com/wiggins-kong)）：新行 id 原本由列表下标生成，删除一行后再新增会复用仍在行的 id，两行同 id 时 `/settings/reveal` 只返回第一个匹配，导致第二行的复制按钮拿到别人的 key。现改为写入时生成唯一 id，重复者带数字后缀（`k6` / `k6-2`）以便 reveal 仍能解析；读取时也去重，历史文件无需等下次保存即自愈。
- **修复 `/v1/responses` 非流式路径崩溃**：PR #33 在该路径引用了未定义的 `ns_map`（函数形参名为 `namespace_map`），任何非流式 Responses 请求都会在拿到上游响应后抛 `NameError`、连接被直接断开。实测发现并修复，流式路径不受影响。

### v1.4.9

- **DeepSeek 思维链默认开启**：此前网关只注入 `thinking:{type:"enabled"}` 而不带推理档位，上游据此仍按「不思考」应答——客户端不发 `reasoning_effort` 时思维链被静默丢弃（实测 `reasoning_content` 长度 0、`reasoning_tokens` 0）。现在缺档时按模型目录声明的默认档补齐（无声明回退 `high`），实测同一请求变为 `reasoning_content` 112 / `reasoning_tokens` 36。客户端显式指定的档位（snake/camel 双字段）一律不覆盖；`thinking:{type:"disabled"}` 与 `reasoning_effort:"none"` 仍然照常退出，不会被迫思考。
- **工具调用配对自愈**：工具执行失败时客户端会把 assistant 的 `tool_calls` 写进会话历史却写不回结果消息，这条坏历史随后被每一轮原样重放，上游对之后每条消息都返回 `400 code 11148`（"tool calls and tool results do not match, please start a new conversation and retry"）——一次失败调用即可让整条会话报废。并行工具调用时中间插入的消息（如 Codex 的 `image_resize_notice`）同样会打断配对。现在请求出站前先修复：把结果块移回所属批次，再按同一份 id 集合对称裁剪「有调用无结果」与「有结果无调用」，任何输入都不会再产生半截配对。实测同一条坏历史由 400 变为 200，正常配对的历史行为不变。
- **`prompt_cache_key` 注入（默认关闭）**：新增按账号隔离的缓存键注入（`wb2a-<uid8>-<摘要>`，账号段不可省——上游前缀缓存按账号隔离，跨账号共用键会命中他人缓存），可用 `WB_PROMPT_CACHE_KEY=1` 开启。**默认关闭的原因**：实测该上游本来就会自动复用重复前缀，带不带此字段结果一致——相同 ~8k token 前缀第二次调用在两个出口、免费与收费模型上均报 `prompt_cache_hit_tokens=9600` 且扣费相同，因此不再为每个请求附加该字段。
- **新增 `_test_upstream_repairs.py`**（49 项断言，无网络依赖）：覆盖缓存键的账号隔离与优先级、思维链补档与退出路径、配对重排与孤儿裁剪、以及 `build_upstream_body` 的整合行为。

### v1.4.8

- **HTTP 连接同步修复**（PR #30）：修复请求被提前拒绝时未读取请求体、导致后续请求在同一 keep-alive 连接上解析失败的问题（日志表现为空请求行的伪 414）；同时支持 chunked 请求体、`Expect: 100-continue`、超大请求体立即返回 413，并扩展了鉴权头写法。
- **超长请求行的回复丢失修复**：请求行超限时回复 414 后直接关闭会因未读数据触发 RST，导致客户端收不到任何响应；现先有限度排空再回复。
- **macOS 启动脚本**（PR #31）：新增 `start-wb-proxy.sh` / `.command`、局域网版本与防火墙助手，并按平台调整端口占用提示与凭据目录探测；原有 `.bat` 脚本未修改，Windows 行为不变。

### v1.4.7

- **每账号独立出口代理**（PR #26）：新增可命名、可启停的代理槽位，账号绑定槽位后其全部出站请求固定走该出口，避免多账号共用同一出口 IP 触发上游风控；看板支持槽位增删、出口 IP 测试与逐账号绑定。
- **账号身份请求全量走代理**：修复 `refresh` / `checkin` / `fetch_credits` 未传代理的遗留问题。这三处请求携带账号凭据（refresh token 与 uid，或 Bearer token）却从宿主机真实 IP 发出，会把账号身份与宿主机 IP 关联在一起。
- **槽位 ID 不再回收**：槽位 ID 改由持久化计数器分配，只增不减；删除槽位时同步解绑指向它的账号，避免新增槽位拿到释放出来的 ID 而静默接管原账号出口。
- **顶部 GitHub 仓库入口**：看板顶部导航右侧新增项目仓库图标。

### v1.4.6

- **看板数据口径与展示修正**：指标看板改为固定展示国际版与国内版合计数据，不再跟随网关当前出口；模型性能表按「模型 × 出口 × 账号」逐行展开，同一模型在两个出口或多个账号下的用量不再合并；新增「失败」列，输入 / 输出 / 思考三色分列展示。
- **看板会话与页面保持**：会话失效（如网关重启）后前端立即停止轮询并清除旧凭证，不再每 5 秒刷一条 401 日志与重复弹窗；刷新后保持原本所在页面，且在首屏前完成切换，不再闪回网关页。

### v1.4.5

- **GPT 系列流式 Token 监控与生成速度修复**：修复腾讯 WorkBuddy 上游 GPT 系列模型流式传输时中间帧携带全 0 usage 占位导致最终 Token 被丢弃的缺陷；实现非零 usage 优先吸纳与断流 Fallback 估算器，彻底解决 `gpt-5.6-luna` / `gpt-6-astra` 等模型输入输出为 0 与生成速度缺失问题。

---

## 七、致谢与引用声明 (Credits & References)

本项目在协议兼容、风控规避与任务链路设计过程中，深度参考并吸纳了开源社区现有项目的经验与逆向成果，特此致谢：

- **[Sliverkiss/workbuddy2api](https://github.com/Sliverkiss/workbuddy2api)**：
  - **成长任务全链路逆向**：参考了其对腾讯成长任务中心（任务列表、接取、事件上报、领奖端点）的逆向分析与点亮逻辑；
  - **设备指纹稳定派生设计 (`derive_id`)**：吸纳了其以账号 UID 稳定哈希派生固定设备码的思路，有效解决多号防关联风控；
  - **整点排程调度理念 (`Scheduler`)**：参考了其采用每日固定整点排程模拟真人打卡的设计思路；
  - **指纹脱敏管线设计与 DeepSeek 多轮思维链回填**：吸纳了其过滤系统敏感指令与回填 `reasoning_content` 的实践。
- **[CangShui/workbuddy-cliproxy-fix](https://github.com/CangShui/workbuddy-cliproxy-fix)**：
  - 提供了早期关于 WorkBuddy 客户端代理修复与接口差异的参考。
- **[lovingfish/workbuddy-cliproxy](https://github.com/lovingfish/workbuddy-cliproxy)** 与 **[mmqz/cpa-multi-plugins](https://github.com/mmqz/cpa-multi-plugins)**：
  - 提供了关于网关通信与多插件管理的原型参考。
- **[ardeyouxipianyi/workbuddy2api](https://github.com/ardeyouxipianyi/workbuddy2api)**：
  - 提供了国内版分发包逆向分析与出站 User-Agent 规范参考。
- **[@ddddd-ren](https://github.com/ddddd-ren)**：
  - **用量日志高性能倒序检索与看板防堆叠**（PR #14）：实现倒序分块 Seek 读取日志末尾数据，TTL 内存缓存化高频聚合接口，彻底消除大文件（20MB+ / 45k+ 行）下前端看板 60 秒超时与 GIL 卡死问题；
  - **原子写入与并发竞争修复**（PR #13）：消除多线程重写用量摘要文件时的 `ENOENT` 异常与临时文件残留；
  - **账号池 JSON 导出/导入支持**（PR #5）：实现了全量/单账号导出与 Dry-Run 安全导入机制。
- **[@wylftw0314-glitch](https://github.com/wylftw0314-glitch)**：
  - **Responses API custom 工具协议双向转译**（PR #12）：出站降级与入站重构还原 freeform 工具调用，彻底解决 Codex CLI (`apply_patch`) 工具调用静默失效问题，并补充了完整单元测试。
- **[@shuishuipingan](https://github.com/shuishuipingan)**：
  - **成长任务领取竞态修复**（PR #21）：上报事件后改为轮询任务进度、达成后再领奖，解决「一轮跑完全部 +0 积分」；并透传上游拒绝原因，失败不再无从诊断；
  - **专家/团队事件 id 去重**：按任务进度轮换互不相同的专家与团队 id，修复上游按 `(eventCode, id)` 去重导致进度永远不动的问题；
  - **猫猫旅行派出修复**：对齐官方前端协议，先取 `travel/config` 目的地再携带 `location_id` 派出，解决 `HTTP 400 invalid request`；
  - **夜猫子任务接入调度器**：23:00-08:00 夜间窗口判定与每日 01:00 自动上报，此前该整点从未真正上报过夜猫事件；
  - **启动端口误判修复**：端口自检校验回包特征，区分「本服务已在运行」与「端口被其他程序占用」，并为绑定失败补充友好提示。
  - **上游限频按模型冷却**（PR #22）：识别上游 429（code 6004）为模型级限流而非账号失效，将冷却粒度从账号级细化为账号加模型级，冷却时长优先采用上游返回的 reset 时间，并直接返回 429 与 Retry-After 头；修复单账号场景下一个模型被限频就连带拖垮同账号其它模型的问题。
  - **成长任务接取强化与轮询加速**（PR #27）：细化任务接取状态解析，未接取自动补救重试，杜绝静默失败导致全线 0 进度；调整判断顺序确保已达标任务先领奖再跳过；动态快查缩短任务轮询等待时间；
  - **网络抖动分类重试与 403 直通**（PR #28）：识别 SSL EOF / 连接重置等网络抖动并自动退避重试，不误记账号冷却，消除伪 429 误报；将 403（内容审核拦截）与 401 凭据失效严格解耦，单次违规请求原样透传，避免毒化全账号池。

- **[@ayeaaaa](https://github.com/ayeaaaa)**：
  - **按账号绑定出口代理槽**（PR #26）：引入可命名、可启停的代理槽位，账号与槽位绑定后其全部出站请求固定走该出口，避免多账号共用同一出口 IP 触发上游风控；看板支持槽位增删、出口 IP 测试与逐账号绑定。

---

## 八、免责声明 (Disclaimer)

1. 本项目为非官方自托管网关，仅供技术研究、逆向协议学习与个人合法授权账号在私有环境测试使用。
2. 本项目不提供任何账号及额度。请严格遵守官方服务条款，禁止用于任何商业转售、恶意并发或违规滥用。
