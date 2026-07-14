# 更新日志

## [1.1.0] — 2026-07-14

### 安全

- **密码保护。** `ExplorationTask.password` 改用 Pydantic `SecretStr`，防止日志和序列化意外泄露。`get_task` API 响应在传给客户端之前会过滤掉密码字段。`CreateTaskRequest` 不再接收明文 username/password。
- **并发限制。** `POST /api/tasks` 会检查 `MAX_CONCURRENT_TASKS`（默认 5），超限时返回 HTTP 429，避免无限制的 Playwright 进程耗尽系统资源。

### 持久化

- **SQLite 任务存储。** 任务完成、失败或取消时自动持久化到 `tasks.db`。服务重启后从数据库恢复所有历史任务。截图不进行持久化以控制数据库体积。
- 此前定义但未使用的 `DATABASE_URL` 配置项现已接入真实的持久化层。

### 健壮性

- **浏览器清理日志。** `WebExplorer.stop()` 现在逐组件（context、browser、playwright）记录清理错误，不再静默吞掉所有异常，便于发现孤儿浏览器进程造成的资源泄漏。
- **更智能的导航等待。** `navigate()` 中的盲等 `asyncio.sleep(2)` 替换为 `wait_for_load_state("networkidle")`，超时可控，SPA 页面不会永久挂起。
- **TestRunner 回退逻辑修正。** `run_with_fallback` 此前文档和逻辑对无头/有头模式的标注有误，现已修正为：先无头执行，失败后有头重试（适用于可视化调试）。
- **安全的 `_derive_page_name`。** 现在会滤除非法字符并处理数字开头的情况，避免从特殊 URL 生成无效的 Python 类名。

### 代码质量

- **消除 locator 生成器重复。** `_generate_playwright_locator` 在 `script_generator.py` 和 `page_object_generator.py` 中完全重复，现已提取到共享模块 `generators/_locator_utils.py`。
- **`build_locator` 选择器转义（部分）。** label、placeholder、test-id 选择器字符串现在通过 `_esc()` 处理引号和换行符。role/name 组合的完整转义尚待后续补全。

### 前端

- **WebSocket 自动重连。** `app.js` 断线后自动重连，指数退避（1s → 30s），最多 5 次。
- **优化 `escapeHtml`。** 将每次调用创建 `document.createElement('div')` 改为复用单个 `<span>` 节点，减少实时步骤渲染时的 DOM 开销。
- **CSS 跨浏览器修复。** 在 `background-clip: text` 旁增加了 `-webkit-` 前缀。

### 已知限制

- `build_locator` 中 `get_by_role(role, name=...)` 和 `get_by_text(...)` 的 `_esc` 转义因补丁管道语法冲突未完全落地，建议后续手动补齐。
- CORS 仍然全开（`allow_origins=["*"]`）且开启了 credentials，这在现代浏览器中会静默失效。本地开发工具可接受，生产环境需显式限制来源。
- `desktop_app.py`（~1800 行）本轮未动刀，仍为单体文件。

## [1.2.0] — 2026-07-14

### 结构重构

- **`main.py` 拆分。** 从约 476 行缩减至约 70 行。提取出：
  - `state.py` — 全局共享状态（tasks_store、ws_connections、agent、test_runner、信号量）
  - `routes/tasks.py` — 6 个 REST 端点，使用 APIRouter
  - `routes/ws.py` — WebSocket 端点
  - `services/db.py` — SQLite 持久化层
  - `services/exploration.py` — 探索编排、广播、manifest 辅助函数
  - `logging_config.py` — Web 和桌面端共用的集中日志配置
- **APIRouter 路由分离。** 路由使用 FastAPI `APIRouter` + `include_router()` 实现清晰的模块分离。
- **`desktop/worker.py`。** `ExplorationWorker` 线程从 `desktop_app.py` 提取为独立模块，可复用。
- **`config.py` 嵌套化。** 扁平 `Settings` 类替换为 `ServerConfig`、`BrowserConfig`、`AgentConfig`、`AIConfig`、`SecurityConfig`、`DatabaseConfig` 嵌套模型。保留向后兼容的扁平属性访问器。
- **CLI 入口。** 新增 `cli.py`，支持 `serve` 和 `explore` 两个子命令：`python cli.py explore <url> -r "登录测试"`。
- **Output manifest。** `output/_manifest.json` 记录每个完成任务的 ID、URL、状态和时间戳（保留最近 100 条）。
- **测试。** 新增 `tests/test_schemas.py`（8 项）和 `tests/test_generators.py`（7 项），全部 15 项通过。
