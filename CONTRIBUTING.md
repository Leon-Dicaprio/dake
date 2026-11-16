# Contributing

三个人先用简单的协作方式：从 `main` 创建任务分支，完成后提 PR，确认改动没问题再合并。`main` 保留可以正常启动的版本，不额外维护 `develop` 分支。

## Quick start

先按 [README](README.md) 安装依赖、启动本地 MySQL 和前后端。开发前看一下 [项目简报](docs/项目简报.md) 和 [工程架构](docs/工程架构.md)。每个人使用自己的 `.env` 和本地数据库，配置示例在 `.env.example`。

## Branches

分支名用英文，按任务创建，不要三个人共用同一个开发分支：

```text
feat/event-filter
fix/run-progress
docs/setup-guide
chore/dependency-cleanup
```

开始一个任务：

```bash
git switch main
git pull --ff-only origin main
git switch -c feat/event-filter
```

改公共接口、数据结构或别人正在改的文件时，先在团队里说一声。一个 PR 尽量只解决一件事，方便其他人查看和合并。

## Commits

提交信息和 PR 标题都用「英文类型前缀 + 中文描述」。范围可写可不写：

```text
feat: 增加事件类型筛选
fix(api): 修复运行进度查询
docs: 补充本地启动说明
refactor: 合并重复查询逻辑
test: 补充跨天事件更新测试
chore: 清理无用依赖
```

正文用中文，说明改了什么、怎么验证；小改动不用写长说明。

```bash
git add web/src/pages/events/index.tsx
git diff --cached
git commit -m "feat(web): 增加事件类型筛选"
git push -u origin feat/event-filter
```

## Pull requests

在 GitHub 上从自己的分支向 `main` 提 PR，按模板简单填写改动和验证结果。没写完也可以先开 Draft PR，方便大家看到进度。

完成后请一位同伴看一下，有问题就在原分支继续提交，PR 会自动更新。不设置强制审批人数或 CI 门槛；小改动简单确认即可，不必等所有人都看完。

有冲突时先在自己的分支合入最新 `main` 并解决：

```bash
git fetch origin
git merge origin/main
# 解决冲突并完成提交后，再推送任务分支。
git push
```

确认可以合并后，优先使用 **Squash and merge**，合并标题沿用上述格式。合并后可以删除远程任务分支，再回到本地 `main` 拉取最新代码；下一个任务重新建分支。

## Checks

只跑与改动相关的检查，在 PR 里如实说明即可；没跑的检查写清原因，不要求文档小改动也跑全部测试。

后端修改，在根目录执行：

```bash
.venv/bin/python -m pytest -q backend/tests -m "not mysql and not isolated_mysql"
```

前端修改，在 `web/` 执行：

```bash
npm run lint
npm run build
```

改交互时启动页面，点一下受影响的功能；现有浏览器测试可用 `npm test` 运行。改持久化或任务流程时补跑相关 MySQL 测试，使用独立测试库；隔离验收入口为 `scripts/verify_execution_mysql.py`，连接参数可查看 `--help`。

改接口后，从根目录重新生成契约和客户端，并一起提交：

```bash
.venv/bin/python scripts/export_openapi.py
npm --prefix web run openapi
```

`web/src/services/generated/` 不手工修改。新增表结构变更放在 `backend/migrations/`，同时写清执行方式和对现有数据的影响。

## Project boundaries

- 前端放 `web/`；HTTP 接口放 `backend/src/dake/api/`；业务流程放 `services/`。网页、命令行和后台任务共用业务服务。
- 保留消息幂等和跨天事件更新，同一件事继续更新原 `event_id`。
- 测试使用自造数据。默认 `stub` 不调用真实模型，真实抽取遵循项目已有授权范围。
- `.env`、`data/`、密钥、真实聊天、截图和本地构建产物不提交，也不贴到 PR 中；用合成例子说明问题。

其他开发约定见 [AGENTS.md](AGENTS.md)。
