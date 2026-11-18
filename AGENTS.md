# 开发约定

需求以用户最新指示及 [项目简报](docs/项目简报.md) 中最新正式说明为准，不沿用旧演示期限或已被覆盖的限制。架构见 [工程架构](docs/工程架构.md)，启动见 [README](README.md)，协作与提交见 [CONTRIBUTING](CONTRIBUTING.md)。

## 当前范围

- 已有 FastAPI、事件与证据展示、客户管理、任务中心（手动及定时增量）、机器人筛选。先在本地稳定运行，服务器部署暂缓；角色分发、日报周报、机器人拉群改名不在当前范围。
- 已授权通过配置的 XHub（`https://llmapi.qiniu.io`），从 `2026-11-10` 起逐窗口处理全部 L6～L10 大客户，自动纳入新发现的大客户；保留样例 `1383603926` 的既有授权。等级未知、无效或过期时待确认，不能按等级字符串排序判断。

## 处理规则

- 聊天只用官方 `POST https://ts.qiniu.io/api/mars_alert/qq/chatRecords`，支持分钟窗口、可选 UID，兼容日期调用；不用 mars 数据库或旧 `GET /qq/messages`。响应先适配，按 `send_time` 跨群排序，以来源及消息 ID 幂等入库；不用 `created_at` 作事件时间。
- 按窗口增量处理，不把全量分析伪装成逐轮回放。使用 `Asia/Shanghai`、内部 `[start, end)`，命令行日期结束值包含整天。周期默认 `15m`，与各类回溯、匹配及宽限窗口独立配置；接口结果按发送时间过滤，禁止未来消息提前入模。
- 按客户、来源和群 ID 隔离处理，新消息只判断与本群事件的归属；跨群事件间关联由另一模块负责。命中更新原 `event_id`，类型标签变化不改变事件身份；仅复述旧事实按非业务／无需推进记录，归属不明标「待确认」。详见 [本群事件匹配说明](docs/本群事件匹配说明.md)。
- 保留商机、流失、排障、资源需求、功能需求、商务需求六类主事件及公共属性、可核对证据；额外类型与属性放扩展字段。未知不猜，未确认的枚举和评分规则不编造，合理缺省集中配置。
- 全局取数、各客户独立按时间推进，同一客户同时只处理一个窗口。消息处理标记、事件更新及执行收据同事务提交，并核验客户水位与执行权；文件水位、快照和任务状态不能代替数据库提交证明。
- 失败保留已完成窗口；提交或模型结果不明时先核实，不自动重发，展示恢复不得重复分析。机器人及群过滤依据明确配置，不凭名称猜测，不因修改配置隐式重算历史。

## 工程与数据

- 后端为 Python 3.11+、FastAPI。`backend/src/dake/` 中，`api/` 与 CLI 只做输入输出，`services/` 放共用流程，`ingestion/` 适配来源，`analysis/` 分析，`domain/` 定义模型，`repositories/` 持久化，`jobs/` 调度执行；禁止复制增量和回放逻辑。
- 前端沿用 React、TypeScript、Umi 4、Tailwind CSS 4、Radix UI、Lucide，不引入 Ant Design；遵循 [web/AGENTS.md](web/AGENTS.md)。OpenAPI 生成客户端不手改。
- 使用项目独立的 Docker MySQL 8.4（`127.0.0.1:3307`，`data/mysql/`），不用 SQLite 或其他项目数据库。不同启动目录均使用根 `.env` 和 `data/`；结构变更放 `backend/migrations/` 并说明执行方式。
- Provider 可替换，默认 `stub` 不生成事件，显式 `LLM_PROVIDER=xhub` 才启用真实模型。授权不扩展到其他外部服务或真实数据截图。
- 密钥留在本地私有配置；真实聊天、完整响应、证据和快照只留在已忽略的 `data/`（原始响应 `data/raw/`，快照 `data/snapshots/`），不得进入源码、文档、日志、测试期望值或提交说明。测试和截图使用合成数据，不向应用灌入演示客户。
- 新增或修改的注释、文档字符串使用中文，协议字段及外部名称保留原名。

## 验证

- 按改动运行相关检查，纯文档修改无需跑完整测试。后端：`.venv/bin/python -m pytest -q backend/tests -m "not mysql and not isolated_mysql"`；持久化或任务流程改动补跑独立测试库中的 MySQL 测试。
- 前端在 `web/` 运行 `npm run lint`、`npm run build`；交互改动连接真实本地后端验证，必要时运行 `npm test`。
- 接口变更后从根目录运行 `.venv/bin/python scripts/export_openapi.py` 和 `npm --prefix web run openapi`，同步提交契约与生成客户端。
