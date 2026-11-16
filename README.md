# 大客售后智能系统

七牛云技术支持部内部项目：从大客户售后群聊中识别并持续更新售后事件。本仓库包含可复用的增量处理后端、FastAPI 接口与事件管理网页。

开发前先读：

- [CONTRIBUTING.md](CONTRIBUTING.md)：分支开发、提交格式与 PR 合并的简单约定
- [docs/项目简报.md](docs/项目简报.md)：现况、领导与官方要求、一期要做成什么样、接口与事件约定、开发约束
- [docs/群识别与消息过滤开发方案.md](docs/群识别与消息过滤开发方案.md)：待实现的群分类、供应商与内部产品群排除规则、配置及验收要求
- [docs/多客户接入与定时增量开发方案.md](docs/多客户接入与定时增量开发方案.md)：全量群发现、UID 补查、大客户筛选、主备负责人及定时执行规划
- [docs/大客售后智能系统-技术方案草案.docx](docs/大客售后智能系统-技术方案草案.docx)：架构与增量洗数的详细方案
- [AGENTS.md](AGENTS.md)：给 Codex / 编程助手的操作约定

一期实现官方取数、消息归一、增量抽取与跨天事件更新。处理周期可配置，默认 `15m`，将周期设为 `1d` 可以演示 2026-11-08 至 2026-11-12 五轮回放。存储使用本项目独立的本地 Docker MySQL。FastAPI 和网页复用既有业务服务。2026-11-16 用户进一步明确采用定时器驱动多客户增量处理，已纳入上述开发规划，尚未实现或部署；角色分发与日报周报仍留待后续。

数据路径：官方 `chatRecords` → 数据源适配器 → 统一消息 → 增量抽取 / 跨天匹配 → 标准事件。命令行与 HTTP 后台任务调用同一套增量和回放服务。目录职责与调用关系见 [工程架构](docs/工程架构.md)。

## 安装与启动

需要 Python 3.11 及以上版本、Node.js 24、npm、Docker 与 Docker Compose。在项目根目录执行：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e './backend[dev]'
```

若创建环境时提示缺少 `ensurepip`，先安装与 Python 版本对应的 venv 组件；Ubuntu 通常使用 `python3-venv`。已有 `.venv` 时可直接安装项目依赖。

如需复用当前验证过的依赖版本，可将上面的安装命令替换为：

```bash
.venv/bin/python -m pip install -r backend/requirements.lock
.venv/bin/python -m pip install -e ./backend --no-deps
```

首次使用将 `.env.example` 复制为 `.env`，分别设置 `MYSQL_PASSWORD` 和 `MYSQL_ROOT_PASSWORD` 为不同的随机密码。已有本地 `.env` 时保留原文件，再启动数据库并建表：

```bash
docker compose up -d --wait mysql
docker compose ps
.venv/bin/dake init-db
docker compose exec -T mysql sh -c 'MYSQL_PWD="$MYSQL_PASSWORD" exec mysql --user="$MYSQL_USER" "$MYSQL_DATABASE"' < backend/migrations/001_processing_attempts.sql
```

MySQL 8.4 仅监听 `127.0.0.1:3307`，数据库默认 `dake_aftersales`，应用用户默认 `dake`。数据保存在 `data/mysql/`。健康检查使用应用账号执行查询，启动完成后应显示 `healthy`。

业务存储使用 `messages` 和 `events`，网页任务存于 `processing_runs`（API 启动时幂等创建），逐窗口执行与重试存于 `processing_attempts`。执行记录表由 `backend/migrations/001_processing_attempts.sql` 显式迁移；当前本地库已有此表，新环境需先迁移。消息的处理标记与事件更新在同一事务提交；`data/state/` 的水位仅帮助选择下一次窗口，丢失后可依据数据库记录去重。

`docker compose stop mysql` 可停止数据库；再次运行启动命令会使用原有数据。初始化账号和密码只在空数据目录首次启动时生效，修改 `.env` 不会自动修改已有数据库密码。

## 网页与接口

在两个终端分别启动服务。以下命令从仓库根目录执行。

后端：

```bash
.venv/bin/python -m uvicorn dake.main:app --host 127.0.0.1 --port 8001
```

前端：

```bash
cd web
npm ci
npm run dev
```

打开 <http://localhost:8000>。前端将 `/api/` 请求代理到本地 `127.0.0.1:8001`。后端接口说明位于 <http://localhost:8001/docs>。默认两端均仅监听本机。

需要同一局域网查看时，在根 `.env` 的 `API_ALLOWED_HOSTS` 中保留本机地址并追加当前局域网 IP（逗号分隔，无端口），重启后端，在 `web/` 执行 `npm run dev:lan`。访问 `http://<本机局域网 IP>:8000`；网页的同源代理继续连接本机后端。WSL 镜像网络还需允许 Windows / Hyper-V 防火墙的入站 TCP 8000，范围限定为本地子网。恢复仅本机展示时改回 `npm run dev`。

`web/scripts/patch-umi-host.mjs` 在安装和启动时修复锁定的 Umi 4.7.3 开发服务器未将 `HOST` 传给监听调用的问题，只修改本项目依赖。升级 Umi 时需要重新核对该补丁；版本或上游代码不符时会停止启动，避免悄悄监听所有网卡。

- **事件**：按客户和六类主类型筛选，查看事件详情、消息证据和历次变化。
- **处理记录**：选择客户、日期范围、处理周期和数据读取方式，提交后台处理，查看逐轮新建、更新与待确认。刷新后可继续查看持久化记录。

真实客户抽取需显式设置 `LLM_PROVIDER=xhub`；默认 `stub` 只验证处理链路，不生成分析事件。

聊天展示身份可在私有的 `data/config/sender_roles.json` 中配置，结构为 `{"accounts":[{"uid":"synthetic-customer","source":"official_chat","sender_id":"synthetic-service-account","role":"support"}]}`（示例账号均为虚构）。按客户、来源、账号 ID 精确匹配，已确认配置优先于接口原始标记；支持 `internal`、`support`、`customer`、`external`、`unknown` 五种展示角色。按用户确认的展示口径，未配置账号沿用原规则：`1` 在右侧显示“内部”，`0` 在左侧显示“客户”，未知不显示身份标签；已确认的我方客服在右侧单独标“客服”。接口标记的完整语义仍待确认，不将展示标签作为跟进人识别依据。配置在查询时读取，刷新页面即可生效，不改写消息、证据或事件，也无需重新清洗。真实账号只保存在 `data/`，不要写入源码或文档。

运行状态的“排队、处理中、完成、失败”属于程序执行状态，与官方尚待确认的事件状态分开。任务按周期真实执行，失败保留已完成的周期和脱敏错误。当前后台执行器为本机单实例执行，使用一个 Uvicorn worker（默认值），不提供自动定时调度或分布式执行保证。命名锁用于防止误启动的实例同时领取任务；数据库连接异常时，业务事务仍依靠客户锁和消息幂等保护事件。

### 机器人身份与通知过滤

机器人身份配置保存在私有文件 `data/config/sender_kinds.json`，与 `sender_roles.json` 中的内部／外部角色独立。缺少配置时身份为未知，不根据昵称或外部标记过滤。配置示例全部为虚构内容：

```json
{
  "accounts": [
    {
      "uid": "synthetic-customer",
      "source": "official_chat",
      "conversation_id": "synthetic-alert-group",
      "sender_id": "synthetic-alert-account",
      "kind": "bot",
      "label": "虚构告警机器人",
      "basis": "管理员确认该群内的通知账号"
    }
  ]
}
```

`kind` 可配置为 `human`、`bot` 或 `unknown`，这是技术身份分类，不是事件等级。`basis` 必填；`label` 只便于维护，不参与匹配。同一个机器人名称可以对应多条群与账号配置。建议填写 `conversation_id` 限定群；省略时才对该客户、来源、账号的所有群生效。更具体的群配置优先。真实账号清单只放 `data/`，待确认清单可放 `sender_kinds.pending.json`，该文件不会生效。

- 仅有已确认机器人的新增消息时，不调用抽取器，不创建或更新客户事件；原消息仍保留，并记录已处理标记，防止重试重复分析。
- 有非机器人新增消息时，机器人通知移入辅助上下文。候选必须包含本轮非机器人证据；客户主动反馈无需等待内部回复。模型规则进一步要求明确问题、诉求或相关人工讨论，不能用无关问候为告警创建事件。
- 人工稍后讨论时，可以在当前上下文回看范围内引用先前通知；超过回看范围仍依赖后续历史检索能力，当前不承诺无限期取回。
- 页面通过独立 `sender_kind` 显示机器人身份，不再把已配置的机器人标成客户；未配置账号保持既有角色展示和未知技术身份。
- 每轮 `filter_audit` 保存消息键、处理原因、过滤版本和身份配置指纹，不保存额外聊天正文。`processed` 包括已处理的机器人通知，并不等同于模型实际分析量。审计随周期结果保存，沿用现有快照／任务记录的恢复边界。

配置在每轮开始读取并冻结，查询展示时重新读取。过滤策略采用独立版本，模型记录保存实际系统提示词哈希；不更换已有事件的分析流，也不改变原始消息 digest。新增配置不会自动重洗已处理消息或删除旧事件；历史误识别需另行复核。配置格式错误会停止处理，不静默忽略。

当前提供本地文件配置，设置页面尚未实现。若需要重新评估历史通知，必须另行指定范围，不能通过修改账号配置隐式触发全量分析。

## 工程目录

| 目录 | 内容 |
| --- | --- |
| `backend/src/dake/api/` | FastAPI 接口与请求响应结构 |
| `backend/src/dake/services/` | 摄入、单周期增量、范围回放、查询 |
| `backend/src/dake/ingestion/` | 官方客户端与数据适配器 |
| `backend/src/dake/domain/` | 统一消息与事件定义 |
| `backend/src/dake/analysis/` | Provider、校验、合并、匹配和更新 |
| `backend/src/dake/repositories/` | MySQL、运行记录、水位与快照 |
| `backend/src/dake/jobs/` | 后台处理执行器 |
| `backend/tests/` | 业务、接口和存储测试 |
| `web/` | React / Umi 管理端 |
| `docs/` | 项目约束、架构与生成的接口定义 |
| `data/` | 本地私有数据，不提交 |

## 命令行运行

以下命令均在项目根目录执行。省略客户、日期和周期参数时读取 `.env`；单次命令可用参数覆盖。

### 取数与回放

取数只调用官方接口，将原始响应保存到 `data/raw/`，并通过适配器将消息归一后存入 MySQL，不做事件分析：

```bash
.venv/bin/dake fetch --uid 1383603926 --start 2026-11-08 --end 2026-11-12
```

已有对应日期的本地响应后，可以离线逐日回放五轮：

```bash
.venv/bin/dake replay --uid 1383603926 --start 2026-11-08 --end 2026-11-12 --interval 1d --offline
```

去掉 `--offline` 会通过官方接口取数。`fetch`、`process`、`replay` 都支持 `--offline`；该参数只控制官方取数使用缓存；缺少缓存时不会补抓。若配置为 XHub，抽取仍会调用模型；完全离线验证应使用 stub。

配置缺省为 `stub`，仅验证链路，不生成分析事件。获授权后在根 `.env` 设置 `LLM_PROVIDER=xhub`，配合 `XHub_API_KEY`、`XHub_BASE_URL` 和 `XHub_MODEL` 启用真实抽取。当前本地按用户要求使用 `gpt-6.1-sol`；不要把密钥写入命令行或文档。正式归属合约位于 `backend/src/dake/analysis/attribution.py`，基础字段校验位于 `analysis/contract.py`。

### 单个处理周期

```bash
.venv/bin/dake process --interval 15m
```

每次只执行一个窗口，然后退出。默认从 `data/state/` 的水位继续；首次运行从配置起始时间开始。`--start` 可以显式指定起点，`--end` 是本次允许处理到的截至时间。处理到配置结束时间后，需要更新结束时间才能继续。

例如，处理一个明确的 15 分钟窗口：

```bash
.venv/bin/dake process --start 2026-11-11T09:00:00 --end 2026-11-11T09:15:00 --interval 15m --offline
```

当前没有自动定时执行；后续调度接入同一业务服务。

### 输出位置

控制台只显示时间、类型、事件 ID 和计数，不打印聊天原文或事件概述。完整结果统一保存在已忽略的 `data/` 内：

| 路径 | 内容 |
| --- | --- |
| `data/raw/` | 官方接口原始响应 |
| `data/mysql/` | 本项目 MySQL 数据 |
| `data/state/` | 下次处理窗口的本地水位 |
| `data/snapshots/` | 每轮事件快照和创建、更新记录 |
| `data/run-results/` | 任务周期结果日志，用于进度写入中断后的恢复 |

快照可能含有证据和事件概述，应与原始聊天一样保留在本地，不写入 README、测试期望值或提交说明。

## 配置约定

配置默认从仓库根目录 `.env` 读取，示例见 `.env.example`。从 `backend/` 启动也使用同一 `.env` 和 `data/`；显式 `--env-file` 可指定其他配置文件，但数据仍限制在项目 `data/` 下。`PROCESS_UID`、`PROCESS_START`、`PROCESS_END` 控制客户与日期范围；`PROCESS_INTERVAL` 控制处理周期。上下文回溯、事件匹配、关闭宽限和补漏回溯分别通过 `CONTEXT_LOOKBACK`、`MATCH_WINDOW`、`CLOSED_GRACE`、`INGEST_LOOKBACK` 配置，不随周期自动改变。

业务时间统一为 `Asia/Shanghai`，内部窗口采用 `[start, end)`。日期形式的 `--end 2026-11-12` 包含当天整日；精确时间形式的 `--end 2026-11-12T09:15:00` 不包含该端点。接口按日期取数，重叠读取用于补漏，消息以 ID 去重，抽取器只看到本周期新增消息及此前的上下文。

`DEFAULT_STATUS`、`DEFAULT_SEVERITY` 默认均为「未知」，`CLOSED_STATUSES` 默认留空。这些规则仍待官方确认，不能把开发缺省当成正式枚举；确认后的关闭状态可用逗号分隔配置。

`LLM_PROVIDER=stub` 用于验证增量链路。真实模型应在确认使用范围后接入，不应只通过填写外部密钥就发送真实聊天。

## 验证

单元测试使用合成数据：

```bash
.venv/bin/python -m pytest -q backend/tests
```

本地数据库启动后，可启用 MySQL 集成测试：

```bash
RUN_MYSQL_TESTS=1 .venv/bin/python -m pytest -q backend/tests
```

前端检查（先启动后端和前端，再执行浏览器测试）：

首次执行浏览器测试前，在 `web/` 运行 `npx playwright install chromium`。本机已有兼容的 Chromium 时，也可通过 `DAKE_BROWSER_PATH` 指定浏览器可执行文件。截图默认关闭；需要合成演示截图时，将 `DAKE_SCREENSHOTS` 指定到项目 `data/screenshots/`。

```bash
cd web
npm run lint
npm run build
npm test
```

本地接口单次范围最多 31 天、2048 个周期，等待和执行中的任务合计最多 32 个；运行列表展示最近 200 条。这些技术上限集中在 `backend/src/dake/config.py`，不属于官方业务规则。

更新接口后，重新导出定义并生成前端客户端：

```bash
.venv/bin/python scripts/export_openapi.py
cd web
npm run openapi
```

`docs/api/openapi.json` 从后端代码生成，不包含真实聊天响应；`web/src/services/generated/` 由生成器维护，不手工修改。

更多参数可通过 `.venv/bin/dake --help` 或对应子命令的 `--help` 查看。

原始聊天数据和密钥不要提交进仓库。
