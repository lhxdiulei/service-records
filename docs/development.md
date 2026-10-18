# 开发与维护

## 源码与生成文件

| 路径 | 维护规则 |
| --- | --- |
| `backend/app/` | FastAPI、权限、业务校验、AI 任务与工作流适配 |
| `backend/migrations/` | 按顺序执行且校验和固定；只追加，不改写或删除已应用迁移 |
| `backend/workflows/` | 当前工作流输入 / 输出 JSON Schema、业务 System 规则及合成示例，直接维护这些源文件 |
| `backend/tokenizers/` | 分词器文件、来源及校验指纹 |
| `frontend/src/` | Vue 页面、组件、交互与样式 |
| `backend/tests/`、`frontend/tests/` | 合成数据回归测试 |
| `dify/` | 由生成器输出的 DSL 及实际 System / User 提示词 |
| `docs/openapi-v1.json` | 从当前 FastAPI 定义导出，避免手工维护第二套接口 |
| `docs/api-*-notes.zh-CN.json` | 人工维护的中文接口和模型说明 |
| `docs/api-reference.zh-CN.md`、`docs/openapi-v1.zh-CN.json` | 生成的中文参考和 OpenAPI，不直接编辑 |

所有者、来源容器、历史昵称、权限范围和修订历史仍服务于现有数据的隔离、追溯和任务恢复。它们的数据库结构并非可随意删除的旧管理页面代码。

Git 换行规则见根目录 `.gitattributes`：源码统一使用 LF；迁移和分词器保留原始字节，避免跨平台检出改变校验和。

## Python 环境

项目容器使用 Python 3.12，本机开发可使用兼容的 Python 环境。从根目录建立环境并安装依赖：

```sh
python -m venv .venv
python -m pip install -r backend/requirements.lock -r backend/requirements-dev.txt
```

安装命令中的 `python` 应指向已激活虚拟环境；Windows 也可直接用 `.venv\Scripts\python.exe`。依赖清单见 [requirements.txt](../backend/requirements.txt)、[完整锁定依赖](../backend/requirements.lock) 与 [开发依赖](../backend/requirements-dev.txt)。

## 文档与接口同步

接口有改动时，先更新源码，再执行：

```sh
python scripts/export_openapi.py
# 增删接口或字段后，同时维护 docs/api-route-notes.zh-CN.json 和 api-schema-notes.zh-CN.json。
python scripts/build_api_docs.py
python scripts/check_project.py
```

导出器直接读取当前 FastAPI 定义，不启动服务或连接数据库。同步检查比较全部路径、参数、请求模型和响应声明，并检查中文注释覆盖、文档相对链接，以及 Dify 生成文件是否匹配源文件；失败返回非零退出码。它适合在提交前或 CI 中运行，不替代业务测试。

业务行为调整时同步更新[操作说明](user-guide.md)；环境、端口或代理调整时更新[部署运维](deployment.md)和 [.env.example](../.env.example)。不要把某次本机运行的任务 ID、业务聊天或验收计数写成当前功能说明。

## 前端开发与测试

先启动项目 Compose，再在 `frontend` 目录执行：

```sh
npm ci
node node_modules/vite/bin/vite.js --host 127.0.0.1
```

开发页默认 `http://127.0.0.1:5173`，Vite 的 `/api` 转发到已启动的网页代理 `http://127.0.0.1:8088`。若修改 `WEB_PORT`，同步调整 [Vite 配置](../frontend/vite.config.js)。本地联调写请求还需将开发来源加入 `.env` 的 `APP_ORIGINS`，重新创建 API；通过 HTTP 开发时 Cookie 配置也应与该访问方式匹配。

```sh
node --test
node node_modules/vite/bin/vite.js build
```

Windows 项目路径含 `&` 时，直接运行上面的 Node / Vite 入口可避免 npm 包装脚本的路径解析问题。

前端 Docker 构建使用自身的 `.dockerignore`，排除宿主机 `node_modules`、构建产物和测试报告，避免把 Windows 依赖覆盖进 Linux 构建环境。

浏览器回归需要 Playwright 及浏览器，可通过 `PLAYWRIGHT_MODULE` 指定已有模块入口、`PLAYWRIGHT_CHANNEL` 指定浏览器。先启动 Vite，再按需运行 `tests/workflow-browser.mjs`、`editor-browser.mjs`、`evidence-picker-browser.mjs`、`navigation-browser.mjs`、`mobile-browser.mjs`。这些脚本拦截 API 使用合成数据，产物写入忽略的 `frontend/test-results/`。

## 后端回归

先确保项目 PostgreSQL 已运行，再执行：

```sh
docker compose --profile test run --build --rm --no-deps tests
```

测试会创建并删除自己的随机数据库；解析、预筛选、权限隔离、原文证据、审核版本、删除恢复和任务恢复均使用合成数据，模型采用替身。已应用迁移的校验和仍参与验证。

## Dify 源文件同步

```sh
python scripts/build_dify_dsl.py
python scripts/test_dify_prompts.py -v
```

先改 `backend/workflows/` 或生成器，再生成 `dify/`。回归检查比较完整 Schema 约束、提示词、示例和 9 节点图，避免后端与 Dify 使用不同契约。生成本地文件不会自动更新已发布 Dify 应用；发布和连接步骤见[模型配置](local-model-setup.md)。

## 运维脚本用途

下列脚本保留为可复用工具，不在日常启动时自动运行。

| 脚本 | 默认行为与适用范围 |
| --- | --- |
| `export_openapi.py`、`build_api_docs.py`、`check_project.py` | 导出、生成、检查当前文档；不访问业务库 |
| `build_dify_dsl.py`、`test_dify_prompts.py` | 生成和离线校验工作流产物 |
| `benchmark_prefilter.py` | 只用合成聊天测预筛选保留率、Token 与打包时间 |
| `benchmark_prefilter_live.py` | 默认离线核对输入；显式 `--execute` 才调用本地模型 |
| `verify_pagination.py` | 在 API 容器内登录后只读检查分页；可指定 `--batch-id`，无历史任务依赖 |
| `live_dify_check.py` | 显式运行会上传带唯一标记的合成文件并调用本地模型，保留草稿供检查；不会批准 |
| `recover_ignored.py` | 默认预览；需 `--plan` 人工复核计划与 `--output` 可写报告路径，显式 `--apply` 才恢复归属并排队本地生成 |
| `cleanup_ai_duplicates.py` | 默认预览；可用 `--report` 保存报告；显式 `--apply` 才软删除同来源、同答案依据且无人工审核的重复 AI QA |
| `repair_local_dify.py` | 适配 Dify 1.17.1，默认预览；显式 `--apply` 才修改匹配应用并发布 |
| `validate_dify_nodes.py` | 在匹配版本 Dify API 容器内验证节点形状和沙箱代码，不调用模型 |

一次性的业务补录、特定聊天验收脚本、旧设计契约和历史截图不再作为项目源码维护。正式运行结果应按实际环境另存到忽略的 `.local/` 或指定报告目录。
