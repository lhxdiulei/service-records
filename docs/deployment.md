# 部署与运维

## 服务和数据

主项目 Compose 名为 `service-records`。浏览器访问 `web`（Nginx / Vue），`/api/` 代理到 `api:8000`；API、Worker、Beat 使用 PostgreSQL 与 Redis，Worker 调用 Dify。可选本地 Ollama 使用独立的 `service-records-model` 项目。

默认网页监听 `0.0.0.0:${WEB_PORT:-8088}`，即宿主机所有网卡；是否能从局域网或公网访问，还取决于防火墙和路由映射。PostgreSQL、Redis、API 均没有宿主机映射端口。

| 数据卷 | 内容 |
| --- | --- |
| `records_db` | 原始消息、工单 / QA、证据、审核、账号和任务记录 |
| `records_files` | 原始导入文件 |
| `records_redis` | 任务传输数据 |

备份应覆盖数据库、原始文件和实际环境配置。迁移服务使用管理账号，业务服务使用无 DDL / TRUNCATE 权限的 `records_app`。迁移文件带校验和，已应用文件必须保留原样，新增结构通过后续迁移实现。

## 环境变量与管理员

配置入口为根目录 `.env`，字段示例见 [.env.example](../.env.example)。数据库管理密码与运行密码应独立，运行密码至少 20 位；管理员密码至少 12 位。

首次在空用户库运行迁移时创建 `ADMIN_USERNAME` / `ADMIN_PASSWORD`。已有管理员应通过“设置”修改密码；修改 `.env` 不会覆盖数据库中的密码。`admin123` 不符合当前最短长度校验。

改动环境变量后，需要重新创建读取该配置的容器：

```sh
docker compose up -d --no-deps --force-recreate api worker beat
```

只执行 `restart` 不会重新加载 Compose 注入的环境变量。数据库密码变更还涉及数据库角色更新，不应只改 `.env` 后直接重建业务容器。

## HTTPS、来源白名单与分离部署

公网示例：浏览器访问 `https://chat.roiff.site:8443`，云端或第三方 HTTPS 代理再转发到本机网页端口。根据实际网络，将路由 TCP 公网端口转发到运行本项目的内网主机对应端口；HTTPS 若在云端终止，代理回源应使用本机实际提供的 HTTP 服务。

```dotenv
WEB_PORT=8088
APP_ORIGINS=https://chat.roiff.site:8443,http://localhost:8088,http://127.0.0.1:8088
COOKIE_SECURE=true
```

`APP_ORIGINS` 校验写请求的 Origin；每项填写完整协议、域名及非默认端口，无路径和末尾斜杠，多项逗号分隔且不要添加空格。域名解析或端口转发成功不等于已经加入来源白名单。`COOKIE_SECURE=true` 后应通过 HTTPS 登录和使用服务。

前后端可分别构建和运行；当前网页请求使用相对路径 `/api/v1`，推荐在网页同一来源反向代理 `/api/`。项目当前未启用跨来源 CORS，直接从另一域名网页调用后端还需配置预检、凭据和 Cookie 策略，添加 `APP_ORIGINS` 本身不会开启 CORS。

## 更新和停止

```sh
docker compose up -d --build
docker compose ps -a
```

更新代码需要重新构建镜像。`migrate` 成功退出为正常状态，其他服务应保持运行；API 和依赖服务的健康检查应通过。

```sh
docker compose down
```

日常停止使用上面的命令，它保留数据卷。不要附加 `-v`，该选项会删除数据卷。

## 日志与 502 排查

在项目根目录执行：

```sh
docker compose logs --tail=200 web api
docker compose logs --tail=200 worker beat
docker compose logs --tail=200 migrate postgres redis
```

持续查看可增加 `-f`。本项目 Nginx 和应用日志输出到容器标准输出 / 错误，通过 Compose 查看，不需要在光猫页面寻找应用错误日志。

公网出现 `502 openresty` 时，先查看承载 HTTPS 的云服务器或第三方代理平台的站点错误日志，核对回源协议、地址、端口及网络连通。再检查本机 `web` 和 `api` 日志与健康状态；若本机网页正常、仅公网失败，重点检查云端到本机回源链路。`401/403` 通常属于登录、CSRF、来源或权限校验，与代理 502 的排查入口不同。

## Dify 与模型

Dify 归属与抽取两条应用分别配置 API Key。`configured=true` 仅表示两条 Key 均已填写，不代表地址连通或发布流程可运行。API Key 变更后按前述步骤重新创建容器。

导入与模型连接见[本地模型与 Dify](local-model-setup.md)，模型切换和任务预算见[模型预算与断点恢复](token-pipeline.md)。
