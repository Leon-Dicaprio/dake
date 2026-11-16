# 大客售后工作台

事件列表与运行进度两个页面，使用 React 19、Umi 4、TypeScript、Tailwind CSS 4、Radix UI 和 Lucide。界面沿用 `linq-bs/web` 的管理端风格，不使用 Ant Design。

## 运行

使用 Node.js 24，在此目录执行：

```bash
npm ci
npm run dev
```

默认访问 `http://127.0.0.1:8000`。`config/proxy.ts` 将 `/api/` 转发至本地 `http://127.0.0.1:8001`，通过 `DAKE_API_PROXY` 可覆盖。代理保留原 Host，使后端能够核对浏览器的同源请求。

Umi 4.7.3 的开发监听未使用其 `HOST` 参数，本工程通过 `scripts/patch-umi-host.mjs` 在安装和启动时修正这一个调用。脚本核对版本、文件归属和原始代码后才修改，重复执行安全；版本或实现变化时会终止并要求重新核对。开发服务因此只监听 `127.0.0.1:8000`。

## 目录

- `config/`：路由、开发代理和构建配置。
- `scripts/`：受版本与原始代码校验约束的开发监听修复。
- `src/layouts/`：侧栏与共享客户配置。
- `src/pages/events/`：客户、事件分类和详情入口。
- `src/pages/runs/`：处理记录、提交表单与逐轮变化。
- `src/components/`：事件详情、提示与基础控件。
- `src/services/request.ts`：同源请求、超时及错误提示。
- `src/services/generated/`：根据后端 OpenAPI 自动生成的类型与客户端，禁止手工修改。
- `src/lib/`：请求状态和时间等通用功能。
- `tests/`：连接真实本地后端的浏览器验收。

后端重新导出 `docs/api/openapi.json` 后执行 `npm run openapi`。生成文件与契约一起保存。

## 验证

```bash
npm run lint
npm run build
npm test
```

页面交互测试需要前端已启动，使用测试内构造的响应。真实后端验收使用 `scripts/verify_execution_mysql.py` 和 `scripts/serve_execution_panel.py` 创建的隔离测试服务，不使用业务库。测试默认不保存截图或轨迹；指定 `DAKE_SCREENSHOTS` 后仅保存合成演示画面。`DAKE_BROWSER_PATH` 可指定本地浏览器可执行文件。

真实客户是否生成分析事件取决于后端配置：`stub` 不分析，显式启用的 `xhub` 调用获授权的模型。应用不再提供演示客户、历史演示或模拟生命周期入口。
