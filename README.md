# 知序 · 客户服务记录

从纯文本聊天导入、消息归属，到工单 / QA 草稿编辑与人工审核。系统保留原文、逐字证据、版本历史和可恢复删除；Dify 生成的内容经过人工批准后才成为正式版本。

技术组成：Vue 3、FastAPI、PostgreSQL、Redis、Celery、Dify。浏览器通过同源 `/api/` 代理访问后端，前端与后端分别构建。默认网页入口为 <http://localhost:8088>。

## 启动

1. 将 [.env.example](.env.example) 复制为 `.env`，填写独立数据库管理密码、至少 20 位运行账号密码，以及至少 12 位管理员密码。
2. 在项目根目录执行：

   ```sh
   docker compose up -d --build
   docker compose ps -a
   ```

3. 打开 <http://localhost:8088>，使用 `.env` 中的 `ADMIN_USERNAME` / `ADMIN_PASSWORD` 登录。管理员仅在空用户库首次启动时创建；修改环境变量不会重置已有账号密码。

`migrate` 成功退出是正常状态。网页默认在所有网卡的 `WEB_PORT`（8088）监听；数据库、Redis 和 API 没有宿主机映射端口。公网 HTTPS、来源白名单、日志和更新步骤见[部署运维](docs/deployment.md)。

Windows 若找不到 `docker`，可用完整路径：

```powershell
& "$env:LOCALAPPDATA\Programs\DockerDesktop\resources\bin\docker.exe" compose up -d --build
```

## 文档

| 文档 | 内容 |
| --- | --- |
| [操作说明](docs/user-guide.md) | 导入、预筛选恢复、生成、编辑、审核与原文追溯 |
| [部署运维](docs/deployment.md) | 环境配置、HTTPS、端口、日志、更新与数据卷 |
| [开发与维护](docs/development.md) | 前后端开发、测试、脚本用途及文档同步检查 |
| [API 中文接入指南](docs/api-guide.zh-CN.md) | Cookie、CSRF、版本号、分页和带中文注释的调用示例 |
| [API 中文接口参考](docs/api-reference.zh-CN.md) | 当前接口、参数、权限、模型及响应说明 |
| [中文 OpenAPI](docs/openapi-v1.zh-CN.json) | 可导入支持 OpenAPI 3.1 的接口工具 |
| [本地模型与 Dify](docs/local-model-setup.md) | 两条工作流的导入和本地 Ollama 接入 |
| [模型预算与断点恢复](docs/token-pipeline.md) | 模型切换、分词器、Token 分批和任务恢复 |
| [预筛选验证](docs/prefilter-benchmark.md) | 合成样本、离线基准及可选真实模型对照 |

登录系统后可打开同一来源下的 `/api/docs` 和 `/api/openapi.json`。接口原始快照由当前 FastAPI 源码导出，中文说明由注释数据生成。

## 验证

在已安装后端及文档工具依赖的 Python 环境中执行：

```sh
python scripts/check_project.py
docker compose --profile test run --build --rm --no-deps tests
```

第一条检查源码与文档是否同步；第二条在独立随机 PostgreSQL 测试库中验证业务闭环，使用合成模型响应。前端测试与构建在 `frontend` 中执行：

```sh
node --test
node node_modules/vite/bin/vite.js build
```

详细准备步骤和浏览器回归入口见[开发与维护](docs/development.md)。
