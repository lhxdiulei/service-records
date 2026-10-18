# 知序系统 API 中文接入指南

本文面向前端开发、接口联调和第三方系统接入，说明当前系统实际提供的接口、登录方式及导入到审核的调用顺序。当前接口使用 Cookie 会话，通过同源 `/api/` 反向代理访问；保存草稿与正式审核是分开的操作。

文档核对日期：2026 年 10 月 18 日。

## 文档入口

| 文档 | 用途 |
| --- | --- |
| [中文接口参考](api-reference.zh-CN.md) | 全部当前 HTTP 操作的中文用途、权限、参数、版本来源及响应说明，附请求和校验模型 |
| [中文 OpenAPI](openapi-v1.zh-CN.json) | 可导入支持 OpenAPI 3.1 的接口工具，含中文 `summary`、`description`、请求头及 Cookie 认证说明 |
| [原始 OpenAPI 快照](openapi-v1.json) | FastAPI 原始接口定义，用于保留路径、请求字段和约束 |
| [运行中的 Swagger](http://localhost:8088/api/docs) | 先在系统网页登录，再在同一浏览器、同一来源打开；保留原有自动生成的标题 |
| [运行中的 OpenAPI](http://localhost:8088/api/openapi.json) | 当前部署服务返回的契约，也需要登录 |

公开 HTTPS 部署可将上述 `http://localhost:8088` 替换为实际入口，例如 `https://chat.roiff.site:8443`。主机名、协议或端口变化后属于另一个来源；在 `127.0.0.1` 登录不会让 `localhost` 自动拥有该会话。

中文文件是项目内的补充文档，不替换线上 Swagger，也不修改接口行为。原契约的成功响应多数未声明完整响应模型；中文参考列出实现返回的主要字段，但不保证能直接生成完整的响应类型 SDK。

## 地址和请求格式

- 业务接口前缀：`/api/v1`。
- 健康检查：`GET /api/health`，不需要登录。
- JSON 请求使用 `Content-Type: application/json`；字段名仍使用英文。
- 上传接口使用 `multipart/form-data`，让 HTTP 客户端自动生成 boundary，不要手动覆盖上传的 Content-Type。
- 时间通常是 ISO 8601 字符串，日期字段可能是 `YYYY-MM-DD`；标识符采用 UUID。
- 请求模型通常拒绝额外字段。可选字段不等于可以传 null，是否允许 null 以字段类型为准。

当前前端使用相对地址 `/api/v1`，生产 Nginx 转发到后端。`APP_ORIGINS` 是写请求的来源校验，不是 CORS 开关；直接由另一域名的网页调用后端，还需要额外配置 CORS、预检和 Cookie 携带方式。

## 登录和请求头

### 登录顺序

1. 请求 `GET /api/v1/auth/csrf`，保留服务端 Cookie，并从响应 JSON 取出 `csrf_token`。
2. 请求 `POST /api/v1/auth/login`，提交 `username`、`password`，携带 Cookie、`Origin`、`X-CSRF-Token`。
3. 登录成功后，继续保留服务端设置的 `sr_session` 和 `sr_csrf` Cookie，**把后续请求使用的 Token 更新为登录响应中的新 `csrf_token`**。
4. 请求 `GET /api/v1/auth/me` 检查当前账号，其他受保护接口沿用同一个 Cookie 会话。

两个 Cookie 都是 HttpOnly，浏览器脚本应从响应 JSON 获取 CSRF Token，不要用 `document.cookie` 读取。系统不使用 Bearer Token。当前会话总时限为 12 小时，空闲时限为 2 小时；账号用户名、密码或角色更新会撤销该账号已有会话。

### 公共请求头

| 请求头 | 何时需要 | 中文说明 |
| --- | --- | --- |
| `Cookie` | 登录后的受保护接口 | 由浏览器或脚本 Cookie 容器保存及发送，无需手工拼接 |
| `Origin` | POST、PUT、PATCH、DELETE | 必须与 `APP_ORIGINS` 中某一项完全相同；包含协议、主机及非默认端口，不含路径或末尾斜杠。浏览器自动提供，脚本需自行设置 |
| `X-CSRF-Token` | POST、PUT、PATCH、DELETE | 与当前会话及 `sr_csrf` Cookie 对应的 Token |
| `Idempotency-Key` | 已登录用户的写请求，退出登录除外 | 1–128 字符；建议 UUID。未登录时登录可省略，但已登录后再次登录也会校验，所以示例统一发送 |
| `If-Match` | 需要并发版本校验的接口 | 必须包含双引号，例如 `"3"`；具体版本来源见下表 |

`APP_ORIGINS` 多项用逗号分隔，当前实现不会自动去除每项两端空格。HTTPS 部署应使用与部署一致的 `COOKIE_SECURE` 配置。

### 幂等重试

同一个用户、HTTP 方法、路径和幂等键用于识别同一次写操作。成功响应会保存；原始请求体字节相同的重试可获得原结果，不同请求体返回 `409 idempotency_conflict`。

网络超时导致结果未知时，保留原键和原始请求体重试。业务错误或参数错误需要先修正，不应无限重试。不同操作意图使用新键；查询参数和 If-Match 不参与请求体指纹，尤其不能给 `dry_run=true` 与 `dry_run=false` 共用一个键。权限变化也可能使重放返回 `permission_changed`。不要把幂等记录的过期字段理解成已经实现了固定时长后自动失效。

## 并发版本校验

不同资源使用不同版本，不能把某个接口返回的 ETag 不加区分地用于所有后续写请求。

| 操作 | If-Match 取值 |
| --- | --- |
| 修改、删除、恢复账号 | 目标账号的 `version` |
| 确认导入 | 导入记录的 `batch.version`，预览响应 ETag 也对应它 |
| 修改消息处置或恢复预筛选消息 | 消息列表的 `disposition_version` |
| 替换问题关联消息 | 问题的 `issue.version` |
| 新建工单或 QA 修订、添加工单备注 | 主记录的 `object.version` |
| 提交、批准、驳回修订 | 目标修订的 `state_version` |
| 取消或重试生成任务 | 任务的 `version` |
| `/records/...` 删除、恢复 | 对应记录类型的 `delete_version`，首次通常为 0 |

创建修订同时提交正文中的 `expected_object_version` 和 `base_revision_id`。后者必须是当前正式版本 `object.current_revision_id`；没有正式版本时是 null，**不是当前正在编辑的草稿 ID**。

审核动作正文同时提交 `expected_object_version` 和 `expected_current_revision_id`，而请求头使用修订的 `state_version`。创建修订成功响应的 ETag 也是修订 `state_version`；需要主记录新版本时重新读取详情。

## 分页和返回格式

分页推荐显式发送 `page=1&page_size=10`。页码从 1 开始，每页默认 10，最大 100。常见响应如下，示例中的 `items` 已省略业务数据：

```json
{"items": [], "total": 0, "page": 1, "page_size": 10}
```

接口没有统一的 `total_pages` 字段，可用 `ceil(total / page_size)` 计算。

| 接口 | 返回格式 |
| --- | --- |
| users、imports、tickets、qa、jobs 列表 | 传 page 返回分页对象；省略 page 返回数组，部分接口最多 200 条，不能据此认定已取全 |
| reviews、jobs/{id}/records | 默认返回分页对象 |
| messages | 始终返回分页对象，兼容 offset/limit；传 page 时以 page/page_size 为准 |
| imports/{id}/preview | `{batch, records, warnings, total, page, page_size, screening_summary}`，消息数组名为 records |
| issues | 返回数组，当前没有分页参数 |

搜索在服务端按当前账号可访问的数据执行。`deleted=true` 只查询已删除范围，并要求管理员权限。

## 导入到生成草稿

1. `POST /imports` 上传纯文本文件，非空且最多 10 MiB、20,000 条消息。默认 `encoding=auto`；省略 `group_id` 时系统自动建立来源。返回 `{batch, duplicate}`。
2. `GET /imports/{id}/preview` 查看原文、解析警告以及保留、过滤、恢复统计。重复上传可能返回已确认的旧记录，不会覆盖人工恢复结果。
3. 尚未确认时调用 `POST /imports/{id}/confirm`，携带当前版本并提交 `parse_version`。只有实际检查并接受警告后，才应把 `accept_warnings` 设为 true。确认成功只完成导入。
4. `POST /imports/{id}/extractions` 提交 `{"mode":"both","profile":"local"}`，返回 202 和任务。模式也可选 ticket 或 qa；外部模型使用 external，是否可用取决于当前配置。
5. `GET /jobs/{id}` 查询状态、进度和错误；`GET /jobs/{id}/records?page=1&page_size=10` 查询生成记录。服务可能复用相同任务并返回 `reused_request:true`。
6. 使用生成记录中的 `record_kind`、`record_id` 和 `revision_id` 打开对应工单或 QA 版本。任务成功不等于版本已经审核通过。

原始提问、短回复和原文证据应保留追溯。预筛选恢复使用 `PUT /messages/{id}/disposition`，正文为 `{"state":"needs_review","reason":"人工复核后恢复"}`，采用处置版本；恢复后需要重新启动整理生成流程。

## 编辑和审核

当前没有 `POST /tickets`。手工创建问题使用 `POST /issues`，会自动产生对应工单。`PATCH /issues/{id}/messages` 是**完整替换**关联消息；需要追加时，应先读取旧关联，再合并提交，不能仅发送新增项。

工单保存调用 `POST /tickets/{object_id}/revisions`；QA 保存调用 `POST /qa/{object_id}/revisions`。保存返回新修订后，再对该确切修订执行 `POST .../revisions/{revision_id}/submit`。保存与提交是两个请求，提交失败时已保存的草稿仍然存在。

提交和批准都会检查来源版本、未归属消息、支持证据等条件。QA 还需要明确答案、关键事实及贡献者本人直接发言证据。审核员或管理员明确执行 approve 或 reject；驳回必须填写 comment，缺少原始提问的工单在批准时还需要明确确认 `accept_incomplete_start`。

下面是审核请求正文的带注释示例；**jsonc 仅用于阅读，实际发送须去掉注释**：

```jsonc
{
  "expected_object_version": 7,        // 当前主记录 object.version
  "expected_current_revision_id": null, // 当前正式版本 ID，没有正式版本时为 null
  "comment": "请补充处理结果的原文依据",  // reject 时不能为空
  "accept_incomplete_start": false      // 只有人工确认缺少原始提问后才设为 true
}
```

此请求的 `If-Match` 应来自目标修订的 `state_version`，不一定是上面的 7。批准前读取最新详情，避免以旧正式版本为基础发布。

聊天证据使用 `POST /evidence-spans` 创建。`exact_excerpt` 必须逐字匹配原文；相同文字多次出现时，`occurrence` 从 1 开始。返回的 `start_cp`、`end_cp` 是 Unicode 码点偏移，结束位置不包含在片段内，不能直接当成 JavaScript UTF-16 字符索引。

## 删除与恢复

一般实体采用可恢复删除，由管理员执行；草稿可由管理员或实际创建该版本的账号删除和恢复，正式及历史版本不能作为草稿删除。

- 删除：`DELETE /records/{record_kind}/{record_id}`。
- 恢复：`POST /records/{record_kind}/{record_id}/restore`。
- 类型：message、import、ticket、qa、ticket_draft、qa_draft；草稿类型传修订 ID。
- If-Match 使用该类型的 `delete_version`，而不是主记录业务版本。
- 若消息是随所属文件删除的，需要先恢复文件。

软删除恢复与预筛选恢复是两类接口；二者均保留原始聊天和历史证据。

## 带中文注释的 Python 示例

示例使用 `httpx`（后端依赖已包含）。代码供开发者按需运行，整理文档时不执行登录、上传或模型调用。账号密码交互输入，不写入文件。

### 登录并查询

```python
import getpass
import uuid
import httpx

# 改成实际允许的完整来源，不带末尾斜杠；HTTPS 环境使用 HTTPS 地址。
ORIGIN = "http://localhost:8088"
client = httpx.Client(base_url=ORIGIN, timeout=30.0)

def checked(response):
    # 代理错误可能是 HTML，先处理 HTTP 状态，再解析成功响应。
    response.raise_for_status()
    return response.json()

# 先取得 CSRF Token；client 会自动保存 sr_csrf Cookie。
csrf = checked(client.get("/api/v1/auth/csrf"))["csrf_token"]

login = checked(client.post(
    "/api/v1/auth/login",
    headers={
        "Origin": ORIGIN,
        "X-CSRF-Token": csrf,
        "Idempotency-Key": str(uuid.uuid4()),
    },
    json={"username": input("用户名："), "password": getpass.getpass("密码：")},
))
# 登录后 Token 已轮换，必须更新；会话 Cookie 仍由 client 自动管理。
csrf = login["csrf_token"]

def write(method, path, *, body=None, version=None, key=None, files=None, data=None):
    headers = {
        "Origin": ORIGIN,
        "X-CSRF-Token": csrf,
        "Idempotency-Key": key or str(uuid.uuid4()),
    }
    if version is not None:
        headers["If-Match"] = f'"{version}"'  # 双引号属于头值本身。
    return checked(client.request(
        method, "/api/v1" + path, headers=headers,
        json=body, files=files, data=data,
    ))

page = checked(client.get("/api/v1/tickets", params={"page": 1, "page_size": 10}))
print("可查看工单总数：", page["total"])
# 后续示例复用此 client、csrf 和 write；全部操作结束后调用 client.close()。
```

### 上传并读取预览

```python
# 将文件名替换为自己准备的聊天文件；上传本身不启动大模型。
with open("chat-demo.txt", "rb") as source:
    uploaded = write(
        "POST", "/imports",
        files={"file": ("chat-demo.txt", source, "text/plain")},
        data={"encoding": "auto"},
    )

batch_id = uploaded["batch"]["id"]
preview = checked(client.get(
    f"/api/v1/imports/{batch_id}/preview",
    params={"page": 1, "page_size": 10, "screening": "all"},
))
print("预筛选统计：", preview["screening_summary"])
print("需要人工核对的解析警告：", preview["warnings"])
```

### 确认导入和启动生成

```python
# 先阅读预览；此示例遇到警告会停止，不自动代替人工确认。
batch = preview["batch"]
if not batch.get("confirmed_at"):
    if preview["warnings"]:
        raise RuntimeError("请先核对解析警告，确认后再提交 accept_warnings=true")
    batch = write(
        "POST", f"/imports/{batch_id}/confirm",
        version=batch["version"],
        body={"parse_version": batch["parse_version"], "accept_warnings": False},
    )

# 执行以下调用才会发起或复用 AI 生成任务，请先确认 local 配置可用。
job = write("POST", f"/imports/{batch_id}/extractions",
            body={"mode": "both", "profile": "local"})
job_id = job["id"]
progress = checked(client.get(f"/api/v1/jobs/{job_id}"))
print("任务状态：", progress["state"])
# 可间隔数秒重新查询，结束后读取结果；示例不自动批准任何版本。
records = checked(client.get(f"/api/v1/jobs/{job_id}/records",
                             params={"page": 1, "page_size": 10}))
print("已生成记录数：", records["total"])
client.close()
```

对于网络结果未知的重试，应显式保存并复用 `key` 和原请求体；上传的 multipart boundary 每次可能变化，不应简单重建上传体后复用旧键。文件重复检测另外由服务端文件内容哈希处理。

## 常见错误和处理

业务错误示例：

```json
{"detail": {"code": "version_changed", "message": "数据已变化，请刷新后重试"}}
```

| HTTP 状态 | 常见 code | 处理方式 |
| --- | --- | --- |
| 400 | idempotency_required | 补充合规的幂等键 |
| 401 | not_authenticated、invalid_credentials | 检查账号密码或重新登录，并更新会话与 CSRF |
| 403 | origin_rejected、csrf_rejected、forbidden、customer_forbidden | 核对来源、Token、账号角色和数据权限 |
| 409 | base_changed、source_changed、ingestion_pending、invalid_state、record_deleted | 读取最新版本，处理未归属消息或恢复记录，再决定是否重新保存 |
| 409 | idempotency_conflict、permission_changed | 核对重试键与请求体；权限变化后重新发起获授权的操作 |
| 412 | version_changed | 重新读取目标版本，核对差异后提交 |
| 413 | file_size、file_too_large | 检查空文件和文件/请求大小 |
| 422 | warnings_pending、invalid_evidence、evidence_missing、claims_missing、contributor_missing、contributor_evidence、conflicting_evidence 等 | 按返回信息补足警告确认、原文、事实、贡献者或日期依据 |
| 428 | precondition_required | 补充正确资源版本的 If-Match |
| 429 | login_rate_limited | 同 IP/用户名在 15 分钟内登录失败达到阈值，按提示稍后重试 |
| 500 | internal_error | 检查后端日志和依赖服务 |
| 502 | 通常来自反向代理 | 可能返回 HTML；检查代理到后端的连接与错误日志 |

FastAPI 参数校验失败的 422 响应中，`detail` 是数组；业务错误的 `detail` 通常是对象，还可能附带 `fields`。客户端应兼容两者，不要假定所有错误都有 `detail.code`，也不要把代理 HTML 当作 JSON 解析。

## 文档维护

接口以 `backend/app/main.py`、`models.py` 及服务实现为准。变更接口后，直接从当前代码导出 OpenAPI，更新对应中文注释数据，再生成并检查：

```sh
# 导出当前路由、参数和模型，不启动服务或连接数据库。
python scripts/export_openapi.py
# 更新中文注释后生成 OpenAPI 和接口参考。
python scripts/build_api_docs.py
# 检查源码、接口契约、中文注释、Dify 产物和文档链接。
python scripts/check_project.py
```

中文注释来源为 `api-route-notes.zh-CN.json` 与 `api-schema-notes.zh-CN.json`。检查器能发现接口结构差异和生成文件过时；权限、返回字段和业务规则仍需结合实现复核，不替代接口测试。维护规则见[开发与维护](development.md)。
