# 知序系统 API 中文接口参考

适用于当前 FastAPI 实现，共 46 个 HTTP 操作。接入前请先阅读 [中文接入指南](api-guide.zh-CN.md)，其中包含登录、请求头、版本校验、错误处理和带中文注释的调用示例。

本参考由 `scripts/build_api_docs.py` 根据现有 OpenAPI 与中文注释生成。接口路径、方法、字段类型和约束沿用原契约；权限、版本号和返回结构说明补充自实现。成功响应未定义完整 schema 的接口，下面列出主要字段，不代表穷尽全部返回字段。

## 接口目录

| 模块 | 方法与路径 | 用途 |
| --- | --- | --- |
| 删除与恢复 | `DELETE /api/v1/records/{record_kind}/{record_id}` | 可恢复地删除记录 |
| 删除与恢复 | `POST /api/v1/records/{record_kind}/{record_id}/restore` | 恢复已删除记录 |
| 消息与证据 | `POST /api/v1/messages/reassess` | 重新评估消息归属 |
| 系统 | `GET /api/health` | 服务健康检查 |
| 认证 | `GET /api/v1/auth/csrf` | 获取请求校验令牌 |
| 认证 | `POST /api/v1/auth/login` | 登录 |
| 认证 | `GET /api/v1/auth/me` | 获取当前账号 |
| 认证 | `POST /api/v1/auth/logout` | 退出登录 |
| 账号管理 | `GET /api/v1/users` | 查询账号列表 |
| 账号管理 | `POST /api/v1/users` | 创建账号 |
| 账号管理 | `GET /api/v1/users/{user_id}` | 获取账号详情 |
| 账号管理 | `PATCH /api/v1/users/{user_id}` | 修改账号资料或密码 |
| 账号管理 | `DELETE /api/v1/users/{user_id}` | 删除账号 |
| 账号管理 | `POST /api/v1/users/{user_id}/restore` | 恢复账号 |
| 文件导入 | `POST /api/v1/imports` | 上传并预览聊天文件 |
| 文件导入 | `GET /api/v1/imports` | 查询导入文件列表 |
| 文件导入 | `GET /api/v1/imports/{import_id}` | 获取导入文件详情 |
| 文件导入 | `GET /api/v1/imports/{import_id}/preview` | 查看解析原文与预筛选结果 |
| 文件导入 | `POST /api/v1/imports/{import_id}/confirm` | 确认导入解析结果 |
| 消息与证据 | `GET /api/v1/messages` | 查询原始聊天消息 |
| 消息与证据 | `PUT /api/v1/messages/{message_id}/disposition` | 忽略消息或恢复待处理 |
| 消息与证据 | `POST /api/v1/evidence-spans` | 从原文创建证据片段 |
| 问题归属 | `GET /api/v1/issues` | 查询来源问题 |
| 问题归属 | `POST /api/v1/issues` | 从消息创建问题和工单 |
| 问题归属 | `GET /api/v1/issues/{issue_id}` | 获取问题及关联消息 |
| 问题归属 | `PATCH /api/v1/issues/{issue_id}/messages` | 替换问题关联消息 |
| 工单与修订 | `GET /api/v1/tickets` | 查询工单列表 |
| QA 与修订 | `GET /api/v1/qa` | 查询QA列表 |
| QA 与修订 | `POST /api/v1/qa` | 创建 QA 草稿 |
| 审核 | `GET /api/v1/reviews` | 查询待审核记录 |
| 统计 | `GET /api/v1/overview` | 获取工作台统计 |
| 工单与修订 | `GET /api/v1/tickets/{object_id}` | 获取工单详情及历史 |
| QA 与修订 | `GET /api/v1/qa/{object_id}` | 获取QA详情及历史 |
| 工单与修订 | `POST /api/v1/tickets/{object_id}/revisions` | 保存工单新修订 |
| QA 与修订 | `POST /api/v1/qa/{object_id}/revisions` | 保存QA新修订 |
| 审核 | `POST /api/v1/tickets/{object_id}/revisions/{revision_id}/{action}` | 提交或审核工单修订 |
| 审核 | `POST /api/v1/qa/{object_id}/revisions/{revision_id}/{action}` | 提交或审核QA修订 |
| 工单与修订 | `POST /api/v1/tickets/{ticket_id}/notes` | 追加工单备注 |
| 统计 | `GET /api/v1/statistics/daily` | 按工单日期统计 |
| AI 任务 | `GET /api/v1/integrations/dify` | 查看模型密钥配置状态 |
| AI 任务 | `POST /api/v1/imports/{import_id}/extractions` | 为文件发起 AI 归属与抽取 |
| AI 任务 | `POST /api/v1/issues/{issue_id}/extractions` | 为问题重新抽取草稿 |
| AI 任务 | `GET /api/v1/jobs` | 查询 AI 任务列表 |
| AI 任务 | `GET /api/v1/jobs/{job_id}` | 查看 AI 任务进度与诊断 |
| AI 任务 | `GET /api/v1/jobs/{job_id}/records` | 查看任务生成的记录 |
| AI 任务 | `POST /api/v1/jobs/{job_id}/{action}` | 取消或重试 AI 任务 |

## 01 删除与恢复

### 01 可恢复地删除记录

`DELETE /api/v1/records/{record_kind}/{record_id}`

记录删除状态，保留原文、证据和历史；不物理删除业务数据。

- 权限：非草稿仅 admin；ticket_draft、qa_draft 可由 admin 或该草稿 created_by 用户操作；均须满足客户范围。
- If-Match：必需；使用目标记录的 delete_version（尚无删除记录时为 0），不要使用业务 version。

| 参数 | 位置 | 必填 | 类型与约束 | 中文说明 |
| --- | --- | --- | --- | --- |
| `record_kind` | 路径 | 是 | 字符串 | 记录类型；草稿类型的 record_id 是修订 UUID。 |
| `record_id` | 路径 | 是 | 字符串（uuid） | 目标记录 UUID。 |

请求体：无。

成功状态：`200`。

{ok:true,is_deleted:true,delete_version}；delete_version 为更新后的删除状态版本。

- record_kind 仅支持 message、import、ticket、qa、ticket_draft、qa_draft。
- 草稿仅允许 draft、rejected、in_review；正式与历史版本不能当作草稿删除。
- 删除导入文件会使其消息一同不可用；消息或文件的删除会影响来源快照及待审核修订。
- is_deleted 可能包含父级删除影响；具体删除记录用其自身 delete_version。

### 02 恢复已删除记录

`POST /api/v1/records/{record_kind}/{record_id}/restore`

撤销对应记录的软删除标记，保留删除和恢复审计。

- 权限：非草稿仅 admin；草稿可由 admin 或 created_by 用户恢复，且须满足客户范围和可恢复草稿状态。
- If-Match：必需；使用目标记录最新 delete_version。

| 参数 | 位置 | 必填 | 类型与约束 | 中文说明 |
| --- | --- | --- | --- | --- |
| `record_kind` | 路径 | 是 | 字符串 | 记录类型：message 消息、import 导入文件、ticket 工单、qa 问答、ticket_draft 工单草稿、qa_draft 问答草稿。 |
| `record_id` | 路径 | 是 | 字符串（uuid） | 目标记录或草稿修订 UUID。 |

请求体：无。

成功状态：`200`。

{ok:true,is_deleted:false,delete_version}；表示已恢复，delete_version 为更新后的删除状态版本。

- record_kind 取值同删除接口。
- 恢复消息前必须先恢复其所属文件；恢复草稿前父工单或 QA 必须可用。
- 状态已改变或重复恢复返回 409；恢复不会自动提交审核或重新调用模型。

## 03 消息与证据

### 03 重新评估消息归属

`POST /api/v1/messages/reassess`

按现有规则重新评估 needs_review 或 ignored 消息；排除人工处理及已删除消息。

- 权限：仅 admin。
- If-Match：无

| 参数 | 位置 | 必填 | 类型与约束 | 中文说明 |
| --- | --- | --- | --- | --- |
| `dry_run` | 查询 | 否 | 布尔值；默认 `true` | 默认 true；设 false 执行实际调整。 |
| `state` | 查询 | 否 | 字符串；可选 `needs_review`、`ignored`；默认 `"needs_review"` | 待重评状态：needs_review（默认）或 ignored。 |

请求体：无。

成功状态：`200`。

{before,ignored,linked,business_review,dry_run,source_state,issue_ids}；分别为检查数量、忽略数量、关联数量、待人工确认数量及涉及问题。

- 默认 dry_run=true，仅统计建议；dry_run=false 才写入归属/处理状态并更新来源水位。
- 这是规则重评，不是发起大模型抽取。

## 04 系统

### 04 服务健康检查

`GET /api/health`

检查应用及数据库连通性。

- 权限：无需登录。
- If-Match：无

请求体：无。

成功状态：`200`。

{status:'ok'}；表示健康检查通过。


## 05 认证

### 05 获取请求校验令牌

`GET /api/v1/auth/csrf`

获取 csrf_token 并设置 sr_csrf Cookie；已登录时同步会话中的校验信息。

- 权限：无需登录；已登录也可调用。
- If-Match：无

请求体：无。

成功状态：`200`。

{csrf_token}；响应设置 HttpOnly 的 sr_csrf Cookie。

- 后续写请求需同时携带 Cookie、Origin 和 X-CSRF-Token。
- 这是 Cookie 会话机制，不提供 Bearer Token。

### 06 登录

`POST /api/v1/auth/login`

校验用户名和密码，创建新会话，返回当前用户与新的 CSRF 令牌。

- 权限：无需事先登录；仍须通过 Origin、CSRF 校验。
- If-Match：无

请求体：`application/json`，必填；[Login](#login)。

成功状态：`200`。

{user:{id,username,display_name,role,version},csrf_token}；同时设置 sr_session、sr_csrf Cookie。

- 先调用 GET /auth/csrf；登录后使用本接口返回的新 csrf_token。
- 同一用户名/IP 组合在 15 分钟内已有 10 次失败会限流，返回 429。
- 登录成功撤销当前已有会话；普通未登录登录请求不要求 Idempotency-Key，已登录调用仍受写请求幂等规则约束。

### 07 获取当前账号

`GET /api/v1/auth/me`

获取当前会话对应的安全用户信息。

- 权限：须登录。
- If-Match：无

请求体：无。

成功状态：`200`。

{id,username,display_name,role,version}；不返回密码。


### 08 退出登录

`POST /api/v1/auth/logout`

撤销当前会话，并清除会话与 CSRF Cookie。

- 权限：须登录；仍须通过 Origin、CSRF 校验。
- If-Match：无

请求体：无。

成功状态：`200`。

{ok:true}；表示退出登录成功。

- 此接口不要求 Idempotency-Key。

## 09 账号管理

### 09 查询账号列表

`GET /api/v1/users`

查询可用、已删除或全部账号，并返回各账号的数据范围。

- 权限：仅 admin。
- If-Match：无

| 参数 | 位置 | 必填 | 类型与约束 | 中文说明 |
| --- | --- | --- | --- | --- |
| `page` | 查询 | 否 | 整数 或 null；最小值 1 | 从 1 起；不传则返回数组。 |
| `page_size` | 查询 | 否 | 整数；最小值 1；最大值 100；默认 `10` | 每页 1～100，默认 10；仅分页时生效。 |
| `q` | 查询 | 否 | 字符串；最长字符数 200；默认 `""` | 按用户名或显示名称模糊搜索，最长 200 字符。 |
| `role` | 查询 | 否 | 字符串 或 null；可选 `admin`、`agent`、`reviewer` | admin、agent、reviewer；省略不按角色过滤。 |
| `status` | 查询 | 否 | 字符串；可选 `active`、`deleted`、`all`；默认 `"active"` | active（默认）、deleted、all。 |

请求体：无。

成功状态：`200`。

传 page 时返回 {items,total,page,page_size}；不传 page 时返回数组。账号包含 id、username、display_name、role、version、disabled_at、created_at、last_login_at。


### 10 创建账号

`POST /api/v1/users`

创建账号、设置角色与聊天昵称，并分配客户数据范围。

- 权限：仅 admin。
- If-Match：无

请求体：`application/json`，必填；[UserCreate](#usercreate)。

成功状态：`201`。

201；返回新账号的公开资料 {id,username,display_name,role,version}，不包含密码。

- 密码按请求模型要求为 12～200 字符；微信昵称会去空白、去重并参与身份识别。
- 用户名及身份名称需通过唯一性/歧义校验。

### 11 获取账号详情

`GET /api/v1/users/{user_id}`

读取账号公开资料及授权客户范围。

- 权限：仅 admin。
- If-Match：无

| 参数 | 位置 | 必填 | 类型与约束 | 中文说明 |
| --- | --- | --- | --- | --- |
| `user_id` | 路径 | 是 | 字符串（uuid） | 账号 UUID。 |

请求体：无。

成功状态：`200`。

账号资料含 id、username、display_name、role、version、disabled_at、created_at、last_login_at。

- 版本说明：响应 ETag 对应账号 version。

### 12 修改账号资料或密码

`PATCH /api/v1/users/{user_id}`

修改 username、display_name、role；password 省略或 null 时不更换密码。

- 权限：仅 admin。
- If-Match：必需；使用账号 version（可从详情 ETag 获取）。

| 参数 | 位置 | 必填 | 类型与约束 | 中文说明 |
| --- | --- | --- | --- | --- |
| `user_id` | 路径 | 是 | 字符串（uuid） | 账号 UUID。 |

请求体：`application/json`，必填；[UserUpdate](#userupdate)。

成功状态：`200`。

账号公开资料及 reauthenticate_self；响应 ETag 为更新后的账号 version。

- 虽使用 PATCH，username、display_name、role 仍都是请求模型必填字段。
- 修改用户名、角色或密码会撤销目标账号会话；修改自己的这些信息后 reauthenticate_self=true。
- 不能修改当前登录账号自身角色；不能降级最后一名可用管理员；已删除账号需先恢复。

### 13 删除账号

`DELETE /api/v1/users/{user_id}`

停用账号、撤销其会话，并更新聊天身份识别；历史业务归属仍保留。

- 权限：仅 admin。
- If-Match：必需；使用账号 version，不是通用记录 delete_version。

| 参数 | 位置 | 必填 | 类型与约束 | 中文说明 |
| --- | --- | --- | --- | --- |
| `user_id` | 路径 | 是 | 字符串（uuid） | 要停用的账号 UUID。 |

请求体：无。

成功状态：`200`。

更新后的账号公开资料；disabled_at 非空，version 增加；响应 ETag 对应 version。

- 禁止删除当前账号或最后一名可用管理员。
- 这是可恢复停用；用户名仍被占用。

### 14 恢复账号

`POST /api/v1/users/{user_id}/restore`

恢复已停用账号，并重新校验身份名称、更新聊天身份识别。

- 权限：仅 admin。
- If-Match：必需；使用账号 version。

| 参数 | 位置 | 必填 | 类型与约束 | 中文说明 |
| --- | --- | --- | --- | --- |
| `user_id` | 路径 | 是 | 字符串（uuid） | 已停用账号 UUID。 |

请求体：无。

成功状态：`200`。

恢复后的账号公开资料；disabled_at=null；响应 ETag 对应 version。

- 不会恢复旧登录会话；已恢复账号再次恢复返回 409。

## 15 文件导入

### 15 上传并预览聊天文件

`POST /api/v1/imports`

以 multipart/form-data 上传文件，解码、解析并进行确定噪声预筛选，保存不可变原始文件及解析快照；此时尚未正式导入消息。

- 权限：仅 admin、agent；仅限有权访问的客户数据范围。
- If-Match：无

请求体：`multipart/form-data`，必填；[Body_upload_api_v1_imports_post](#body_upload_api_v1_imports_post)。

成功状态：`201`。

201；{batch,duplicate}；batch 包含 id、version、parse_version、current_parse_snapshot_id、state、message_count、parse_issues、screening_summary 等。

- file 必填；encoding 默认 auto；group_id 可省略，省略时自动选择内部客户并新建文件分组。
- 文件不能为空，最大 10 MB；单文件最多解析 20000 条记录。
- 相同内容按 SHA-256 在指定分组或默认客户范围去重；duplicate=true 时复用已有批次。
- 预筛选只标记消息而不移除原文；正式导入需再调用 confirm。

### 16 查询导入文件列表

`GET /api/v1/imports`

搜索导入文件、确认状态与删除状态，并附带消息处理数量和预筛选统计。

- 权限：已登录的 admin、agent、reviewer；仅限有权访问的客户数据范围（admin 可访问所有有效客户）。 deleted=true 仅 admin。
- If-Match：无

| 参数 | 位置 | 必填 | 类型与约束 | 中文说明 |
| --- | --- | --- | --- | --- |
| `group_id` | 查询 | 否 | 字符串（uuid） 或 null | 可选分组 UUID。 |
| `page` | 查询 | 否 | 整数 或 null；最小值 1 | 从 1 起；不传返回最多 200 条数组。 |
| `page_size` | 查询 | 否 | 整数；最小值 1；最大值 100；默认 `10` | 每页 1～100，默认 10。 |
| `deleted` | 查询 | 否 | 布尔值；默认 `false` | 默认 false；true 查询已删除文件，仅 admin。 |
| `q` | 查询 | 否 | 字符串；最长字符数 200；默认 `""` | 按文件名搜索，最长 200 字符。 |
| `status` | 查询 | 否 | 字符串；可选 `all`、`confirmed`、`pending`；默认 `"all"` | all（默认）、confirmed、pending。 |

请求体：无。

成功状态：`200`。

传 page 时返回 {items,total,page,page_size}；不传 page 时返回数组。每项包含批次资料、is_deleted、delete_version、screening_summary、message_counts（active/deleted/pending/needs_review/assigned/ignored）。

- 不分页时最多返回 200 条。
- 版本说明：批次 version 用于确认，delete_version 用于软删除。

### 17 获取导入文件详情

`GET /api/v1/imports/{import_id}`

读取文件批次、解析状态、预筛选统计及消息处理数量。

- 权限：已登录的 admin、agent、reviewer；仅限有权访问的客户数据范围（admin 可访问所有有效客户）。 已删除文件仅 admin 可查看。
- If-Match：无

| 参数 | 位置 | 必填 | 类型与约束 | 中文说明 |
| --- | --- | --- | --- | --- |
| `import_id` | 路径 | 是 | 字符串（uuid） | 导入批次 UUID。 |

请求体：无。

成功状态：`200`。

批次对象，包含 is_deleted、delete_version、screening_summary、message_counts 等。

- 版本说明：返回 batch.version、parse_version、delete_version 等版本字段。

### 18 查看解析原文与预筛选结果

`GET /api/v1/imports/{import_id}/preview`

读取当前解析快照，可筛选过滤或保留的记录；警告提供原文件行号。

- 权限：已登录的 admin、agent、reviewer；仅限有权访问的客户数据范围（admin 可访问所有有效客户）。 已删除文件仅 admin 可查看。
- If-Match：无

| 参数 | 位置 | 必填 | 类型与约束 | 中文说明 |
| --- | --- | --- | --- | --- |
| `import_id` | 路径 | 是 | 字符串（uuid） | 导入批次 UUID。 |
| `offset` | 查询 | 否 | 整数；最小值 0；默认 `0` | 从 0 起，默认 0；不传 page 时生效。 |
| `limit` | 查询 | 否 | 整数；最小值 1；最大值 500；默认 `10` | 1～500，默认 10；不传 page 时生效。 |
| `page` | 查询 | 否 | 整数 或 null；最小值 1 | 从 1 起，传入则改用 page_size。 |
| `page_size` | 查询 | 否 | 整数；最小值 1；最大值 100；默认 `10` | 1～100，默认 10。 |
| `screening` | 查询 | 否 | 字符串；可选 `all`、`filtered`、`retained`；默认 `"all"` | all（默认）、filtered、retained。 |

请求体：无。

成功状态：`200`。

{batch,records,warnings,total,page,page_size,screening_summary}；records 含原文、时间、行号、解析及预筛选标记；total 为筛选后数量。

- page 传入时覆盖 offset、limit；否则使用 offset/limit。
- warnings 为当前完整快照警告，非仅当前页；保留原文可供追溯。
- 版本说明：响应 ETag 是 batch.version，确认时仍需额外携带 batch.parse_version。

### 19 确认导入解析结果

`POST /api/v1/imports/{import_id}/confirm`

把当前快照写入消息、参与者和处理状态，更新文件/分组版本；不会直接启动 AI。

- 权限：仅 admin、agent；仅限有权访问的客户数据范围。
- If-Match：必需；If-Match 为 batch.version；请求体 parse_version 必须等于当前 batch.parse_version，两者不可互换。

| 参数 | 位置 | 必填 | 类型与约束 | 中文说明 |
| --- | --- | --- | --- | --- |
| `import_id` | 路径 | 是 | 字符串（uuid） | 导入批次 UUID。 |

请求体：`application/json`，必填；[ConfirmImport](#confirmimport)。

成功状态：`200`。

更新后的批次对象，state='confirmed'、confirmed_at 非空；ETag 为新 batch.version。

- 有解析警告时必须 accept_warnings=true；已确认文件重复确认返回 409。
- 确定噪声初始状态为 ignored；异常解析为 needs_review；其它消息为 pending。
- 要恢复被预筛选消息，确认后调用消息 disposition 接口设 needs_review。

## 20 消息与证据

### 20 查询原始聊天消息

`GET /api/v1/messages`

按文件、分组、处理状态、正文或发言人搜索消息，返回归属与可追溯的原文信息。

- 权限：已登录的 admin、agent、reviewer；仅限有权访问的客户数据范围（admin 可访问所有有效客户）。 deleted=true 或所属文件已删除时仅 admin 可访问。
- If-Match：无

| 参数 | 位置 | 必填 | 类型与约束 | 中文说明 |
| --- | --- | --- | --- | --- |
| `group_id` | 查询 | 否 | 字符串（uuid） 或 null | 可选分组 UUID。 |
| `offset` | 查询 | 否 | 整数；最小值 0；默认 `0` | 默认 0，非负；不传 page 时生效。 |
| `limit` | 查询 | 否 | 整数；最小值 1；最大值 500；默认 `10` | 1～500，默认 10；不传 page 时生效。 |
| `state` | 查询 | 否 | 字符串 或 null | 处理状态过滤。 |
| `q` | 查询 | 否 | 字符串；最长字符数 200；默认 `""` | 按正文或原始发言人名称搜索，最长 200 字符。 |
| `page` | 查询 | 否 | 整数 或 null；最小值 1 | 从 1 起；传入则使用 page_size。 |
| `page_size` | 查询 | 否 | 整数；最小值 1；最大值 100；默认 `10` | 1～100，默认 10。 |
| `deleted` | 查询 | 否 | 布尔值；默认 `false` | 默认 false；true 仅 admin，包含随文件删除的消息。 |
| `batch_id` | 查询 | 否 | 字符串（uuid） 或 null | 可选导入批次 UUID。 |

请求体：无。

成功状态：`200`。

{items,total,page,page_size}；items 含 raw_text、body_text、quoted_text、direct_body_spans、sent_at、source_filename、disposition、disposition_version、disposition_reason、disposition_note、assigned_issues、删除状态等。

- page 传入时覆盖 offset/limit；raw_text 保持原始内容，body_text 等可体现最新解析注释。
- state 为字符串过滤，不是受模型约束的枚举；常用 pending、needs_review、assigned、ignored。
- 版本说明：返回 disposition_version 和 delete_version，分别用于处理状态更新与删除恢复。

### 21 忽略消息或恢复待处理

`PUT /api/v1/messages/{message_id}/disposition`

人工设置消息为 ignored 或 needs_review，并记录原因；可用来恢复被预筛选的消息。

- 权限：已登录的 admin、agent、reviewer；仅限有权访问的客户数据范围（admin 可访问所有有效客户）。
- If-Match：必需；使用消息列表中的 disposition_version，不是 delete_version。

| 参数 | 位置 | 必填 | 类型与约束 | 中文说明 |
| --- | --- | --- | --- | --- |
| `message_id` | 路径 | 是 | 字符串（uuid） | 消息 UUID。 |

请求体：`application/json`，必填；[Disposition](#disposition)。

成功状态：`200`。

处理状态记录，含 message_id、state、decision_source='human'、reason、version、prefilter_reason、prefilter_restored_at 等；ETag 为该 version。

- 请求 state 只允许 ignored、needs_review；reason 必填。
- 已关联任一问题的消息必须先从问题移除，否则返回 409 message_assigned。
- 消息必须未删除；预筛选消息恢复到 needs_review 时记录恢复时间，但不自动发起模型任务。

### 22 从原文创建证据片段

`POST /api/v1/evidence-spans`

在单条消息 raw_text 中逐字定位 exact_excerpt，返回不可变的证据区间；同消息同区间复用已有证据。

- 权限：已登录的 admin、agent、reviewer；仅限有权访问的客户数据范围（admin 可访问所有有效客户）。
- If-Match：无

请求体：`application/json`，必填；[EvidenceCreate](#evidencecreate)。

成功状态：`201`。

201；证据对象含 id、message_id、customer_id、start_cp、end_cp 等；id 可作为后续 evidence_span_id。

- occurrence 从 1 起，选择同一逐字片段的第几次出现；匹配允许重叠。
- start_cp/end_cp 为 Unicode 码点偏移，左闭右开，不是 JavaScript UTF-16 下标。
- 引文不存在、次数越界返回 422；原消息已删除不可新建证据。

## 23 问题归属

### 23 查询来源问题

`GET /api/v1/issues`

列出未删除工单对应的来源问题，可按主分组过滤。

- 权限：已登录的 admin、agent、reviewer；仅限有权访问的客户数据范围（admin 可访问所有有效客户）。
- If-Match：无

| 参数 | 位置 | 必填 | 类型与约束 | 中文说明 |
| --- | --- | --- | --- | --- |
| `group_id` | 查询 | 否 | 字符串（uuid） 或 null | 可选主分组 UUID。 |

请求体：无。

成功状态：`200`。

问题数组，每项含 id、label、primary_group_id、version、message_version、ticket_id 等。

- 该接口不分页。

### 24 从消息创建问题和工单

`POST /api/v1/issues`

选取消息及关联关系建立来源问题，同时创建尚无正式修订的工单。

- 权限：已登录的 admin、agent、reviewer；仅限有权访问的客户数据范围（admin 可访问所有有效客户）。
- If-Match：无

请求体：`application/json`，必填；[IssueCreate](#issuecreate)。

成功状态：`201`。

201；{issue,ticket}；issue 含 version/message_version；ticket 含 id、ticket_no、version、current_revision_id。

- 至少 1 条、最多 1000 条消息；消息不可重复，必须在同一可访问客户范围且未删除。
- relation 可为 question、answer、progress、context、correction；同客户内可关联不同文件分组。
- 未传 group_id 时采用首条消息分组；创建对象不等于已有草稿内容或完成审核。

### 25 获取问题及关联消息

`GET /api/v1/issues/{issue_id}`

读取来源问题、对应工单 ID 及当前有效关联消息。

- 权限：已登录的 admin、agent、reviewer；仅限有权访问的客户数据范围（admin 可访问所有有效客户）。
- If-Match：无

| 参数 | 位置 | 必填 | 类型与约束 | 中文说明 |
| --- | --- | --- | --- | --- |
| `issue_id` | 路径 | 是 | 字符串（uuid） | 来源问题 UUID。 |

请求体：无。

成功状态：`200`。

{issue,ticket_id,messages}；messages 含 relation、原文、有效正文、来源文件等。

- 关联消息默认排除已删除消息；工单/QA 详情可提供包含已删除来源的追溯数据。
- 版本说明：ETag 对应 issue.version。

### 26 替换问题关联消息

`PATCH /api/v1/issues/{issue_id}/messages`

用请求中的完整 messages 数组替换当前有效关联，并更新消息处理状态和来源版本。

- 权限：已登录的 admin、agent、reviewer；仅限有权访问的客户数据范围（admin 可访问所有有效客户）。
- If-Match：必需；使用 issue.version（不是 message_version）。

| 参数 | 位置 | 必填 | 类型与约束 | 中文说明 |
| --- | --- | --- | --- | --- |
| `issue_id` | 路径 | 是 | 字符串（uuid） | 来源问题 UUID。 |

请求体：`application/json`，必填；[IssueMessages](#issuemessages)。

成功状态：`200`。

更新后的 issue 对象；ETag 对应新 issue.version。

- 这是整体替换，不是追加；允许空数组移除全部关联。
- 消息不可重复，须同客户、未删除；关联后变 assigned，无其它有效关联的移出消息变 needs_review。
- 来源变化会使已有草稿快照过期，提交前需重新保存。

## 27 工单与修订

### 27 查询工单列表

`GET /api/v1/tickets`

查询工单及其当前正式修订、最新可见修订和来源文件。

- 权限：已登录的 admin、agent、reviewer；仅限有权访问的客户数据范围（admin 可访问所有有效客户）。 deleted=true 仅 admin。
- If-Match：无

| 参数 | 位置 | 必填 | 类型与约束 | 中文说明 |
| --- | --- | --- | --- | --- |
| `page` | 查询 | 否 | 整数 或 null；最小值 1 | 从 1 起；省略返回最多 200 条数组。 |
| `page_size` | 查询 | 否 | 整数；最小值 1；最大值 100；默认 `10` | 每页 1～100，默认 10。 |
| `customer_id` | 查询 | 否 | 字符串（uuid） 或 null | 可选客户 UUID；仍按当前账号范围过滤。 |
| `q` | 查询 | 否 | 字符串；最长字符数 200；默认 `""` | 按编号及内容搜索，最长 200 字符。 |
| `deleted` | 查询 | 否 | 布尔值；默认 `false` | 默认 false；true 仅 admin。 |

请求体：无。

成功状态：`200`。

传 page 时返回 {items,total,page,page_size}；不传 page 时返回数组。每项包含对象字段、current_revision、latest_revision、source_filenames、is_deleted、delete_version、parent_deleted。

- 未传 page 时最多返回 200 条。
- 所有草稿均已删除的对象也会出现在已删除列表；只剩历史或正式版本时仍按实际可见修订判断。
- 版本说明：业务 version 与 delete_version 分开使用。

## 28 QA 与修订

### 28 查询QA列表

`GET /api/v1/qa`

查询QA及其当前正式修订、最新可见修订和来源文件。

- 权限：已登录的 admin、agent、reviewer；仅限有权访问的客户数据范围（admin 可访问所有有效客户）。 deleted=true 仅 admin。
- If-Match：无

| 参数 | 位置 | 必填 | 类型与约束 | 中文说明 |
| --- | --- | --- | --- | --- |
| `page` | 查询 | 否 | 整数 或 null；最小值 1 | 从 1 起；省略返回最多 200 条数组。 |
| `page_size` | 查询 | 否 | 整数；最小值 1；最大值 100；默认 `10` | 每页 1～100，默认 10。 |
| `customer_id` | 查询 | 否 | 字符串（uuid） 或 null | 可选客户 UUID；仍按当前账号范围过滤。 |
| `q` | 查询 | 否 | 字符串；最长字符数 200；默认 `""` | 按编号及内容搜索，最长 200 字符。 |
| `deleted` | 查询 | 否 | 布尔值；默认 `false` | 默认 false；true 仅 admin。 |

请求体：无。

成功状态：`200`。

传 page 时返回 {items,total,page,page_size}；不传 page 时返回数组。每项包含对象字段、current_revision、latest_revision、source_filenames、is_deleted、delete_version、parent_deleted。

- 未传 page 时最多返回 200 条。
- 所有草稿均已删除的对象也会出现在已删除列表；只剩历史或正式版本时仍按实际可见修订判断。
- 版本说明：业务 version 与 delete_version 分开使用。

### 29 创建 QA 草稿

`POST /api/v1/qa`

基于一个或多个同客户问题创建 QA 对象和首个草稿修订。

- 权限：已登录的 admin、agent、reviewer；仅限有权访问的客户数据范围（admin 可访问所有有效客户）。
- If-Match：无

请求体：`application/json`，必填；[QACreate](#qacreate)。

成功状态：`201`。

201；{object,revision}；revision 包含修订正文、证据、贡献者、state、state_version 等。

- 必须有 issue_ids，来源问题须有效且对应工单未删除。
- 贡献者证据必须为该参与者本人直接发言，不能引用他人的内容。
- 创建草稿不代表批准；保存可不满足全部审核条件，提交时再作严格检查。
- 版本说明：首次对象版本由服务端初始化。

## 30 审核

### 30 查询待审核记录

`GET /api/v1/reviews`

分页列出最新未删除修订处于 in_review 的工单和 QA。

- 权限：已登录的 admin、agent、reviewer；仅限有权访问的客户数据范围（admin 可访问所有有效客户）。 浏览队列不等于拥有批准权限；approve/reject 仅 admin、reviewer。
- If-Match：无

| 参数 | 位置 | 必填 | 类型与约束 | 中文说明 |
| --- | --- | --- | --- | --- |
| `page` | 查询 | 否 | 整数；最小值 1；默认 `1` | 从 1 起，默认 1。 |
| `page_size` | 查询 | 否 | 整数；最小值 1；最大值 100；默认 `10` | 1～100，默认 10。 |
| `customer_id` | 查询 | 否 | 字符串（uuid） 或 null | 可选客户 UUID。 |

请求体：无。

成功状态：`200`。

{items,total,page,page_size}；items 为装饰后的工单/QA 对象，额外 objectKind='ticket' 或 'qa'。

- 只选各对象的最新可见修订；已删除对象和草稿不进入队列。

## 31 统计

### 31 获取工作台统计

`GET /api/v1/overview`

汇总可见工单、正式工单、QA、正式 QA、待审核数量和待归属消息数量。

- 权限：已登录的 admin、agent、reviewer；仅限有权访问的客户数据范围（admin 可访问所有有效客户）。
- If-Match：无

| 参数 | 位置 | 必填 | 类型与约束 | 中文说明 |
| --- | --- | --- | --- | --- |
| `customer_id` | 查询 | 否 | 字符串（uuid） 或 null | 可选客户 UUID，限制整体统计范围。 |
| `group_id` | 查询 | 否 | 字符串（uuid） 或 null | 可选分组 UUID，只限制 unassigned_messages；同时指定 customer_id 但二者不匹配时，不应用该分组过滤。 |

请求体：无。

成功状态：`200`。

返回概览计数 {tickets,official_tickets,qa,official_qa,reviews,unassigned_messages}，分别对应工单、正式工单、QA、正式 QA、待审核记录和待分配消息数量。

- group_id 仅用于待归属消息数量，不缩小工单、QA、审核等统计。
- 待归属消息指 pending 或 needs_review；删除记录排除。

## 32 工单与修订

### 32 获取工单详情及历史

`GET /api/v1/tickets/{object_id}`

读取工单对象、未删除历史修订、证据和来源消息，用于编辑与原文追溯。

- 权限：已登录的 admin、agent、reviewer；仅限有权访问的客户数据范围（admin 可访问所有有效客户）。 对象处于已删除状态时仅 admin。
- If-Match：无

| 参数 | 位置 | 必填 | 类型与约束 | 中文说明 |
| --- | --- | --- | --- | --- |
| `object_id` | 路径 | 是 | 字符串（uuid） | 工单对象 UUID。 |

请求体：无。

成功状态：`200`。

{object,revisions,source_messages,participants,reviews,events,notes}；revisions 逐项含 state_version、evidence、stale、delete_version；QA 修订还含 issue_ids、contributors。

- 修订列表按 revision_no 倒序，排除已软删除的草稿；原文来源包含带删除标记的消息以支持追溯。
- object.current_revision_id 指向当前正式版；最新草稿不一定等于正式版。
- 版本说明：ETag 对应 object.version，不能用作后续审核的修订状态版本。

## 33 QA 与修订

### 33 获取QA详情及历史

`GET /api/v1/qa/{object_id}`

读取QA对象、未删除历史修订、证据和来源消息，用于编辑与原文追溯。

- 权限：已登录的 admin、agent、reviewer；仅限有权访问的客户数据范围（admin 可访问所有有效客户）。 对象处于已删除状态时仅 admin。
- If-Match：无

| 参数 | 位置 | 必填 | 类型与约束 | 中文说明 |
| --- | --- | --- | --- | --- |
| `object_id` | 路径 | 是 | 字符串（uuid） | QA对象 UUID。 |

请求体：无。

成功状态：`200`。

{object,revisions,source_messages,participants,reviews}；revisions 逐项含 state_version、evidence、stale、delete_version；QA 修订还含 issue_ids、contributors。

- 修订列表按 revision_no 倒序，排除已软删除的草稿；原文来源包含带删除标记的消息以支持追溯。
- object.current_revision_id 指向当前正式版；最新草稿不一定等于正式版。
- 版本说明：ETag 对应 object.version，不能用作后续审核的修订状态版本。

## 34 工单与修订

### 34 保存工单新修订

`POST /api/v1/tickets/{object_id}/revisions`

保存不可变的新草稿，关联证据与来源快照；可通过 replaces_revision_id 替代同对象旧草稿。

- 权限：已登录的 admin、agent、reviewer；仅限有权访问的客户数据范围（admin 可访问所有有效客户）。
- If-Match：必需；If-Match 使用 object.version；请求体 expected_object_version 同值，base_revision_id 应为 object.current_revision_id。成功 ETag 改为新修订 state_version。

| 参数 | 位置 | 必填 | 类型与约束 | 中文说明 |
| --- | --- | --- | --- | --- |
| `object_id` | 路径 | 是 | 字符串（uuid） | 工单对象 UUID。 |

请求体：`application/json`，必填；[TicketRevisionCreate](#ticketrevisioncreate)。

成功状态：`201`。

201；新修订详情，含 id、revision_no、state、state_version、base_object_version、base_revision_id、evidence、来源快照及 stale 等。

- 保存和提交是两次独立请求；提交失败时已保存草稿仍保留。
- replaces_revision_id 仅能指向本对象 draft、in_review、rejected 修订；原 draft/in_review 会变 superseded。
- 工单日期由关联来源消息推导；first_visible_message_id 须指向最早有效可见时间，日期依据需与 first_question_message_id 一致。
- QA 贡献者证据须属于本人直接发言；所有证据须来自当前关联问题。

## 35 QA 与修订

### 35 保存QA新修订

`POST /api/v1/qa/{object_id}/revisions`

保存不可变的新草稿，关联证据与来源快照；可通过 replaces_revision_id 替代同对象旧草稿。

- 权限：已登录的 admin、agent、reviewer；仅限有权访问的客户数据范围（admin 可访问所有有效客户）。
- If-Match：必需；If-Match 使用 object.version；请求体 expected_object_version 同值，base_revision_id 应为 object.current_revision_id。成功 ETag 改为新修订 state_version。

| 参数 | 位置 | 必填 | 类型与约束 | 中文说明 |
| --- | --- | --- | --- | --- |
| `object_id` | 路径 | 是 | 字符串（uuid） | QA对象 UUID。 |

请求体：`application/json`，必填；[QARevisionCreate](#qarevisioncreate)。

成功状态：`201`。

201；新修订详情，含 id、revision_no、state、state_version、base_object_version、base_revision_id、evidence、来源快照及 stale 等。

- 保存和提交是两次独立请求；提交失败时已保存草稿仍保留。
- replaces_revision_id 仅能指向本对象 draft、in_review、rejected 修订；原 draft/in_review 会变 superseded。
- 工单日期由关联来源消息推导；first_visible_message_id 须指向最早有效可见时间，日期依据需与 first_question_message_id 一致。
- QA 贡献者证据须属于本人直接发言；所有证据须来自当前关联问题。

## 36 审核

### 36 提交或审核工单修订

`POST /api/v1/tickets/{object_id}/revisions/{revision_id}/{action}`

对指定草稿进行提交、批准或驳回；成功批准才更新对象正式版本指针。

- 权限：submit：已登录 admin、agent、reviewer；approve/reject：仅 admin、reviewer；均须满足客户数据范围。
- If-Match：必需；If-Match 使用目标 revision.state_version；请求体 expected_object_version 使用 object.version，expected_current_revision_id 使用 object.current_revision_id。

| 参数 | 位置 | 必填 | 类型与约束 | 中文说明 |
| --- | --- | --- | --- | --- |
| `object_id` | 路径 | 是 | 字符串（uuid） | 工单对象 UUID。 |
| `revision_id` | 路径 | 是 | 字符串（uuid） | 修订 UUID，必须属于 object_id。 |
| `action` | 路径 | 是 | 字符串 | submit（提交）、approve（批准）、reject（驳回）。 |

请求体：`application/json`，必填；[Review](#review)。

成功状态：`200`。

操作后的修订详情；ETag 为更新后的 state_version。

- action 仅 submit、approve、reject；未知值返回 404。
- submit 仅允许 draft，approve/reject 仅允许 in_review；驳回 comment 必须非空。
- 提交与批准都会核对来源快照、未归属消息、矛盾证据和必需支持证据；QA 还要求明确答案、关键事实及贡献者。
- 批准工单若缺少原始提问，必须显式 accept_incomplete_start=true；QA 不使用该确认。
- 批准会增加 object.version；应重新获取对象详情再进行后续保存或审核。

### 37 提交或审核QA修订

`POST /api/v1/qa/{object_id}/revisions/{revision_id}/{action}`

对指定草稿进行提交、批准或驳回；成功批准才更新对象正式版本指针。

- 权限：submit：已登录 admin、agent、reviewer；approve/reject：仅 admin、reviewer；均须满足客户数据范围。
- If-Match：必需；If-Match 使用目标 revision.state_version；请求体 expected_object_version 使用 object.version，expected_current_revision_id 使用 object.current_revision_id。

| 参数 | 位置 | 必填 | 类型与约束 | 中文说明 |
| --- | --- | --- | --- | --- |
| `object_id` | 路径 | 是 | 字符串（uuid） | QA对象 UUID。 |
| `revision_id` | 路径 | 是 | 字符串（uuid） | 修订 UUID，必须属于 object_id。 |
| `action` | 路径 | 是 | 字符串 | submit（提交）、approve（批准）、reject（驳回）。 |

请求体：`application/json`，必填；[Review](#review)。

成功状态：`200`。

操作后的修订详情；ETag 为更新后的 state_version。

- action 仅 submit、approve、reject；未知值返回 404。
- submit 仅允许 draft，approve/reject 仅允许 in_review；驳回 comment 必须非空。
- 提交与批准都会核对来源快照、未归属消息、矛盾证据和必需支持证据；QA 还要求明确答案、关键事实及贡献者。
- 批准工单若缺少原始提问，必须显式 accept_incomplete_start=true；QA 不使用该确认。
- 批准会增加 object.version；应重新获取对象详情再进行后续保存或审核。

## 38 工单与修订

### 38 追加工单备注

`POST /api/v1/tickets/{ticket_id}/notes`

为未删除工单追加人工备注，不改写已保存修订正文。

- 权限：已登录的 admin、agent、reviewer；仅限有权访问的客户数据范围（admin 可访问所有有效客户）。
- If-Match：必需；使用工单 object.version。

| 参数 | 位置 | 必填 | 类型与约束 | 中文说明 |
| --- | --- | --- | --- | --- |
| `ticket_id` | 路径 | 是 | 字符串（uuid） | 工单 UUID。 |

请求体：`application/json`，必填；[Note](#note)。

成功状态：`201`。

201；备注对象，含 id、ticket_id、body、author_id、created_at、author_name、author_username。

- note 为 1～4000 字符；本接口自身不增加工单 version。

## 39 统计

### 39 按工单日期统计

`GET /api/v1/statistics/daily`

按当前正式修订的 ticket_date 汇总有效工单数量。

- 权限：已登录的 admin、agent、reviewer；仅限有权访问的客户数据范围（admin 可访问所有有效客户）。
- If-Match：无

请求体：无。

成功状态：`200`。

数组 [{day,tickets},...]；按日期倒序，最多 90 个日期分组。

- 只统计已有正式修订且工单未删除的记录；最多 90 个分组并不等于补齐最近 90 个自然日。

## 40 AI 任务

### 40 查看模型密钥配置状态

`GET /api/v1/integrations/dify`

查询 local、external 两种 Dify 配置是否同时具有主题归属和记录抽取 API Key。

- 权限：须登录；所有角色均可查看。
- If-Match：无

请求体：无。

成功状态：`200`。

返回模型配置状态 [{id:'local',configured:boolean},{id:'external',configured:boolean}]；configured 表示两条工作流 API Key 是否均已配置，不代表地址连通或工作流可运行，不返回密钥。

- 不会返回 API Key；configured 只检查两个 Key 是否配置，不会实际探测地址、联网或验证工作流可运行。

### 41 为文件发起 AI 归属与抽取

`POST /api/v1/imports/{import_id}/extractions`

为已确认文件中的待归属消息创建后台抽取任务；按 mode 生成工单、QA 或两者草稿。

- 权限：仅 admin、agent；仅限有权访问的客户数据范围。
- If-Match：无

| 参数 | 位置 | 必填 | 类型与约束 | 中文说明 |
| --- | --- | --- | --- | --- |
| `import_id` | 路径 | 是 | 字符串（uuid） | 导入批次 UUID。 |

请求体：`application/json`，必填；[Extract](#extract)。

成功状态：`202`。

202；任务对象，含 id、state、mode、batch_id、version、model_profile_snapshot、input_manifest 等；复用任务时 reused_request=true。

- mode：ticket、qa、both（默认）；profile：local（默认）、external。
- 文件须已确认且未删除；仅 pending、needs_review 消息进入主输入。
- 相同来源/mode/profile 的 queued/running 任务可复用；新恢复消息未包含在活动任务内时返回 409。
- 没有待归属消息时可能复用已成功任务，否则返回 409 no_pending_messages；可从已有问题重新抽取。
- 调用会排队执行真实模型工作流；结果仍是草稿，不会自动批准。
- 版本说明：服务端记录输入批次、消息处置和身份配置快照。

### 42 为问题重新抽取草稿

`POST /api/v1/issues/{issue_id}/extractions`

基于已有来源问题创建抽取任务，用于重新生成工单或 QA 草稿。

- 权限：仅 admin、agent；仅限有权访问的客户数据范围。
- If-Match：无

| 参数 | 位置 | 必填 | 类型与约束 | 中文说明 |
| --- | --- | --- | --- | --- |
| `issue_id` | 路径 | 是 | 字符串（uuid） | 来源问题 UUID。 |

请求体：`application/json`，必填；[Extract](#extract)。

成功状态：`202`。

202；任务对象，含 id、target_issue_id、mode、state、version 等；复用活动任务时 reused_request=true。

- mode：ticket、qa、both（默认）；profile：local（默认）、external。
- 来源工单必须未删除；同来源、mode、profile 的活动任务可复用。
- 调用会排队执行真实模型工作流，结果需人工审核。
- 版本说明：服务端记录输入和身份配置快照。

### 43 查询 AI 任务列表

`GET /api/v1/jobs`

按客户或导入批次查看后台抽取任务状态及进度。

- 权限：已登录的 admin、agent、reviewer；仅限有权访问的客户数据范围（admin 可访问所有有效客户）。
- If-Match：无

| 参数 | 位置 | 必填 | 类型与约束 | 中文说明 |
| --- | --- | --- | --- | --- |
| `page` | 查询 | 否 | 整数 或 null；最小值 1 | 从 1 起；省略返回最多 200 条数组。 |
| `page_size` | 查询 | 否 | 整数；最小值 1；最大值 100；默认 `10` | 1～100，默认 10。 |
| `customer_id` | 查询 | 否 | 字符串（uuid） 或 null | 可选客户 UUID。 |
| `batch_id` | 查询 | 否 | 字符串（uuid） 或 null | 可选文件导入批次 UUID，用于文件处理页跟踪任务。 |

请求体：无。

成功状态：`200`。

传 page 时返回 {items,total,page,page_size}；不传 page 时返回数组。每项为任务记录，移除 topic_plan，并过滤 checkpoint 中内部 owned_disposition_versions/issue_versions。

- 不分页时最多返回 200 条；batch_id 会先检查批次范围。
- 版本说明：job.version 用于取消或重试。

### 44 查看 AI 任务进度与诊断

`GET /api/v1/jobs/{job_id}`

读取任务状态、计数、诊断和各执行步骤，供轮询进度使用。

- 权限：已登录的 admin、agent、reviewer；仅限有权访问的客户数据范围（admin 可访问所有有效客户）。
- If-Match：无

| 参数 | 位置 | 必填 | 类型与约束 | 中文说明 |
| --- | --- | --- | --- | --- |
| `job_id` | 路径 | 是 | 字符串（uuid） | AI 抽取任务 UUID。 |

请求体：无。

成功状态：`200`。

任务对象加 steps 数组；steps 含 id、stage、target_key、state、attempt_count、error_code、error_summary、dify_workflow_run_id、input_tokens、output_reserve、context_limit。

- 步骤不返回完整输入/输出聊天文本；公开任务移除 topic_plan 和部分内部 checkpoint 字段。
- input_tokens 是步骤测算输入量，output_reserve 是预算预留，不能直接当作实际输出 Token 用量。
- 版本说明：返回 job.version，但不设置 ETag。

### 45 查看任务生成的记录

`GET /api/v1/jobs/{job_id}/records`

分页列出任务创建或更新的工单、QA 修订，支持从文件处理结果直达草稿。

- 权限：已登录的 admin、agent、reviewer；仅限有权访问的客户数据范围（admin 可访问所有有效客户）。
- If-Match：无

| 参数 | 位置 | 必填 | 类型与约束 | 中文说明 |
| --- | --- | --- | --- | --- |
| `job_id` | 路径 | 是 | 字符串（uuid） | AI 抽取任务 UUID。 |
| `page` | 查询 | 否 | 整数；最小值 1；默认 `1` | 从 1 起，默认 1。 |
| `page_size` | 查询 | 否 | 整数；最小值 1；最大值 100；默认 `10` | 1～100，默认 10。 |

请求体：无。

成功状态：`200`。

{items,total,page,page_size}；每项含 record_kind、record_id、revision_id、issue_id、action、title、record_no、revision_no、state、created_by、is_deleted、created_at。

- 同时兼容旧任务由 source_job_step_id 反查的结果；返回删除标记以便客户端避免误用已删除草稿。

### 46 取消或重试 AI 任务

`POST /api/v1/jobs/{job_id}/{action}`

请求取消进行中任务，或从已失败/取消的任务继续重试。

- 权限：仅 admin、agent；仅限有权访问的客户数据范围。
- If-Match：必需；使用 job.version。

| 参数 | 位置 | 必填 | 类型与约束 | 中文说明 |
| --- | --- | --- | --- | --- |
| `job_id` | 路径 | 是 | 字符串（uuid） | AI 抽取任务 UUID。 |
| `action` | 路径 | 是 | 字符串 | cancel（请求取消）或 retry（重试）。 |

请求体：无。

成功状态：`200`。

更新后的任务对象，包含 state、version 等；此接口当前不设置 ETag。

- action 仅 cancel 或 retry；cancel 允许 queued、running，转为 cancel_requested，实际停止由 worker 执行。
- retry 允许 failed、partial_failed、cancelled，转为 queued；已有完成结果保留。
- 身份配置版本变化后不能重试旧任务，应创建新任务；无效 action 或状态返回 409。

## 请求与校验模型

标为“必填”的属性必须提交；“可选”只表示可省略，只有类型包含 null 时才允许显式传 null。业务请求模型默认拒绝未声明的额外字段。JSON 不支持注释，中文说明放在表格和 OpenAPI 的 description 中。

### Assignment

将一条原始消息关联到问题，并说明该消息在问题中的作用。

| 字段 | 必填 | 类型 | 约束和默认值 | 中文说明 |
| --- | --- | --- | --- | --- |
| `message_id` | 是 | 字符串（uuid） | — | 原始消息 UUID，来自消息列表或导入后的消息记录；消息必须处于可访问的同一客户范围内。 |
| `relation` | 否 | 字符串 | 可选 `question`、`answer`、`progress`、`context`、`correction`；默认 `"context"` | 消息作用：question=提问，answer=回答，progress=处理进展，context=补充上下文，correction=更正。 |

### Body_upload_api_v1_imports_post

聊天文件上传表单，使用 multipart/form-data，而不是 JSON。上传后返回解析结果，仍需确认导入。

| 字段 | 必填 | 类型 | 约束和默认值 | 中文说明 |
| --- | --- | --- | --- | --- |
| `file` | 是 | 字符串（binary） | — | 聊天记录文本文件的二进制内容；文件不能为空且不得超过服务器配置的大小上限。 |
| `group_id` | 否 | 字符串（uuid） 或 null | — | 已有聊天群组 UUID；省略时使用当前用户的内部数据范围，并根据文件名自动建立群组。 |
| `encoding` | 否 | 字符串 | 默认 `"auto"` | 文本编码；auto 按 utf-8-sig、gb18030、utf-16 的顺序尝试解码，也可明确指定文件使用的编码。 |

### Claim

工单或 QA 中需要单独关联原文依据的一项关键事实。

| 字段 | 必填 | 类型 | 约束和默认值 | 中文说明 |
| --- | --- | --- | --- | --- |
| `claim_key` | 是 | 字符串 | 最长字符数 80；格式 `^[a-z][a-z0-9_-]*$` | 当前修订内唯一且稳定的事实标识，例如 c1；用于证据字段 claims.c1 或 answer_claims.c1，不是数据库 UUID。 |
| `text` | 是 | 字符串 | 最短字符数 1；最长字符数 20000 | 关键事实的文字表述；提交审核时每一项都需要 supports 类型的原文依据。 |

### ConfirmImport

确认当前解析快照，将解析结果写入原始消息记录；不直接启动 AI 抽取。

| 字段 | 必填 | 类型 | 约束和默认值 | 中文说明 |
| --- | --- | --- | --- | --- |
| `parse_version` | 是 | 整数 | 最小值 1.0 | 刚刚查看并确认的解析版本号，取自导入详情或预览的 batch.parse_version；解析版本变化时返回冲突。 |
| `accept_warnings` | 否 | 布尔值 | 默认 `false` | 是否已人工查看并接受解析警告；当前解析结果存在警告时必须为 true 才能确认。 |

### Contributor

QA 核心贡献者及其贡献证据；贡献者身份来自聊天参与者，不直接填写系统用户 UUID。

| 字段 | 必填 | 类型 | 约束和默认值 | 中文说明 |
| --- | --- | --- | --- | --- |
| `participant_id` | 是 | 字符串（uuid） | — | 聊天参与者 UUID，来自参与者列表或详情中的 participants；必须与当前 QA 属于同一客户范围。 |
| `contribution` | 是 | 字符串 | 最短字符数 1；最长字符数 2000 | 说明该参与者提供了什么关键帮助，例如提供处理方案或验证解决结果。 |
| `evidence_span_ids` | 是 | 数组〈字符串（uuid）〉 | 最少项数 1；最多项数 100 | 证据片段 UUID 列表。每一段都必须来自已关联来源问题，且完全位于该参与者本人的直接发言区域内；引用他人的文字不能作为本人贡献。 |

### Disposition

人工调整尚未归属问题的消息处理状态；忽略不会删除原文。

| 字段 | 必填 | 类型 | 约束和默认值 | 中文说明 |
| --- | --- | --- | --- | --- |
| `state` | 是 | 字符串 | 可选 `ignored`、`needs_review` | ignored=忽略，needs_review=恢复为待人工处理。已关联问题的消息必须先解除问题关联才能使用此接口调整。 |
| `reason` | 是 | 字符串 | 最短字符数 1；最长字符数 2000 | 人工忽略或恢复消息的原因，用于保留处理依据和审计记录。 |

### EvidenceBinding

将已创建的原文证据片段绑定到当前修订的具体字段或关键事实。

| 字段 | 必填 | 类型 | 约束和默认值 | 中文说明 |
| --- | --- | --- | --- | --- |
| `evidence_span_id` | 是 | 字符串（uuid） | — | 由 POST /api/v1/evidence-spans 返回的片段 UUID；片段必须来自当前修订关联的来源问题。 |
| `field_key` | 是 | 字符串 | 最长字符数 160；格式 `^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_-]*)?$` | 被解释的字段名，例如 problem、handling_summary、current_conclusion、status、question、answer；关键事实使用 claims.<claim_key> 或 answer_claims.<claim_key>，且该事实必须存在。 |
| `relation` | 否 | 字符串 | 可选 `supports`、`contradicts`、`context`；默认 `"supports"` | supports=支持该内容，contradicts=与该内容矛盾，context=仅提供上下文。存在矛盾证据时不能提交或批准，context 不计入必需的支持依据。 |

### EvidenceCreate

通过逐字引文在不可变原始消息中定位证据；服务端计算 Unicode 码点偏移，相同消息及位置会复用已有片段。

| 字段 | 必填 | 类型 | 约束和默认值 | 中文说明 |
| --- | --- | --- | --- | --- |
| `message_id` | 是 | 字符串（uuid） | — | 证据所在原始消息的 UUID；可从消息列表或记录详情的 source_messages 获取，不能引用已删除消息。 |
| `exact_excerpt` | 是 | 字符串 | 最短字符数 1；最长字符数 20000 | 必须与消息 raw_text 完全一致的原文片段，包含原有换行、空白和标点；不能传改写、摘要或消息外的文本。 |
| `occurrence` | 否 | 整数 | 最小值 1.0；默认 `1` | 该逐字引文在同一 raw_text 中第几次出现，从 1 开始；按从左到右逐位置查找，重复出现时用于确定具体位置，允许重叠匹配。 |

### Extract

请求后台执行 AI 抽取，创建工单和/或 QA 草稿；结果仍需人工审核。

| 字段 | 必填 | 类型 | 约束和默认值 | 中文说明 |
| --- | --- | --- | --- | --- |
| `mode` | 否 | 字符串 | 可选 `ticket`、`qa`、`both`；默认 `"both"` | ticket=抽取工单草稿，qa=抽取 QA 草稿，both=两类都抽取。 |
| `profile` | 否 | 字符串 | 可选 `local`、`external`；默认 `"local"` | Dify 连接配置：local=本地配置，external=外部配置。对应配置必须已在服务端设置；可通过 /api/v1/integrations/dify 查询配置状态。 |

### HTTPValidationError

FastAPI 对请求参数或请求体结构校验失败时返回的 HTTP 422 错误结构；与业务错误结构不同。

| 字段 | 必填 | 类型 | 约束和默认值 | 中文说明 |
| --- | --- | --- | --- | --- |
| `detail` | 否 | 数组〈[ValidationError](#validationerror)〉 | — | 字段校验错误数组；每一项说明错误位置、文字提示及错误类型。 |

### IssueCreate

人工将原始消息组织为一个问题，同时创建关联工单对象；工单正文需要另行保存修订。

| 字段 | 必填 | 类型 | 约束和默认值 | 中文说明 |
| --- | --- | --- | --- | --- |
| `group_id` | 否 | 字符串（uuid） 或 null | — | 问题的主要聊天群组 UUID；省略时使用 messages 第一条消息所属群组。来源消息可以跨群组，但必须处于同一可访问客户范围。 |
| `title` | 是 | 字符串 | 最短字符数 1；最长字符数 300 | 问题标题，用于识别来源话题。 |
| `messages` | 是 | 数组〈[Assignment](#assignment)〉 | 最少项数 1；最多项数 1000 | 初始关联消息及其作用；message_id 不得重复。 |

### IssueMessages

整体替换一个问题的消息关联集合，同时保留历史关联记录。

| 字段 | 必填 | 类型 | 约束和默认值 | 中文说明 |
| --- | --- | --- | --- | --- |
| `messages` | 是 | 数组〈[Assignment](#assignment)〉 | 最多项数 1000 | 更新后的完整关联列表，不是仅新增的差量；传空数组解除全部当前关联。被移除且不再关联其他问题的消息恢复为 needs_review。 |

### Login

使用系统账号登录并建立 Cookie 会话。

| 字段 | 必填 | 类型 | 约束和默认值 | 中文说明 |
| --- | --- | --- | --- | --- |
| `username` | 是 | 字符串 | 最短字符数 1；最长字符数 100 | 系统账号登录名。 |
| `password` | 是 | 字符串 | 最短字符数 1；最长字符数 200 | 该账号当前密码。本登录字段的长度规则不同于用户创建/修改密码接口，不用于设置初始管理员密码。 |

### NextAction

工单的后续处理事项，并明确区分聊天已经约定的事项和审核人员建议。

| 字段 | 必填 | 类型 | 约束和默认值 | 中文说明 |
| --- | --- | --- | --- | --- |
| `text` | 是 | 字符串 | 最短字符数 1；最长字符数 2000 | 后续处理事项的具体说明。 |
| `basis` | 是 | 字符串 | 可选 `explicit_in_chat`、`reviewer_suggestion` | explicit_in_chat=聊天中明确提出，reviewer_suggestion=审核人员提出的建议。 |
| `evidence_span_ids` | 否 | 数组〈字符串（uuid）〉 | 默认 `[]` | 支持该事项的原文片段 UUID 列表；explicit_in_chat 时不得为空，所有片段必须来自该工单的问题来源。 |

### Note

向工单追加人工备注；备注与版本正文独立保存。

| 字段 | 必填 | 类型 | 约束和默认值 | 中文说明 |
| --- | --- | --- | --- | --- |
| `note` | 是 | 字符串 | 最短字符数 1；最长字符数 4000 | 本次追加的备注内容。 |

### QAContent

QA 修订正文。草稿可保留尚无答案、存在冲突或上下文缺失的情况；提交审核和批准另有完整性校验。

| 字段 | 必填 | 类型 | 约束和默认值 | 中文说明 |
| --- | --- | --- | --- | --- |
| `question` | 是 | 字符串 | 最短字符数 1；最长字符数 10000 | 整理后的知识问题；提交审核时需要绑定支持该问题的原文依据。 |
| `answer` | 否 | 字符串 或 null | 最长字符数 50000 | 整理后的回答。草稿允许为空；提交审核或批准要求非空且有原文支持。 |
| `answer_state` | 否 | 字符串 | 可选 `supported`、`no_answer`、`conflict`、`missing_context`；默认 `"supported"` | supported=有依据的答案，no_answer=尚无答案，conflict=答案存在冲突，missing_context=缺少必要上下文；提交审核和批准要求 supported。 |
| `applicability` | 否 | 字符串 | 最长字符数 5000；默认 `""` | 答案适用的前提、环境或范围，避免将特定场景的结论无条件推广。 |
| `answer_claims` | 否 | 数组〈[Claim](#claim)〉 | 默认 `[]` | 回答中的关键事实；提交审核时至少需要一项，并为每项绑定 answer_claims.<claim_key> 的支持依据。 |
| `contributors` | 否 | 数组〈[Contributor](#contributor)〉 | 默认 `[]` | 对回答有关键贡献的聊天参与者及本人直接发言证据；提交审核时至少需要一名。 |

### QACreate

新建 QA 对象并保存其第一份草稿，不直接成为已批准知识。

| 字段 | 必填 | 类型 | 约束和默认值 | 中文说明 |
| --- | --- | --- | --- | --- |
| `issue_ids` | 是 | 数组〈字符串（uuid）〉 | 最少项数 1；最多项数 100 | 来源问题 UUID 列表，来自问题列表或工单对象的 issue_id；来源必须处于同一客户范围。 |
| `content` | 是 | [QAContent](#qacontent) | — | 第一份 QA 草稿的完整正文。 |
| `evidence` | 否 | 数组〈[EvidenceBinding](#evidencebinding)〉 | 默认 `[]` | 该草稿字段与原文片段的绑定列表；所有片段必须位于 issue_ids 对应的问题来源中。 |

### QARevisionCreate

为已有 QA 保存一份不可变的新草稿修订，并校验正式版本是否已变化。

| 字段 | 必填 | 类型 | 约束和默认值 | 中文说明 |
| --- | --- | --- | --- | --- |
| `expected_object_version` | 是 | 整数 | 最小值 1.0 | 读取 QA 详情时取得的 object.version；必须与服务端当前对象版本一致。它不同于修订的 state_version。 |
| `base_revision_id` | 否 | 字符串（uuid） 或 null | — | 读取详情时的 object.current_revision_id，即当前已批准的正式版本 UUID；尚无正式版本时传 null。不能用正在编辑的草稿 UUID 代替。 |
| `replaces_revision_id` | 否 | 字符串（uuid） 或 null | — | 本次编辑所替代的同一 QA 草稿、审核中或驳回修订 UUID。旧草稿/审核中版本会标记为 superseded，驳回版本保持原状态；正文和历史不被覆盖。 |
| `evidence` | 否 | 数组〈[EvidenceBinding](#evidencebinding)〉 | 最多项数 1000；默认 `[]` | 新修订的完整字段证据绑定集合，不是差量更新。 |
| `change_reason` | 否 | 字符串 | 最长字符数 2000；默认 `""` | 本次修改的原因，写入创建修订的审计记录。 |
| `content` | 是 | [QAContent](#qacontent) | — | 新修订的完整 QA 正文。 |
| `issue_ids` | 是 | 数组〈字符串（uuid）〉 | 最少项数 1；最多项数 100 | 新修订的完整来源问题 UUID 列表；全部来源必须与 QA 属于同一客户范围。 |

### Review

提交、批准或驳回指定修订时的并发校验与审核说明；动作由 URL 中的 action 决定。

| 字段 | 必填 | 类型 | 约束和默认值 | 中文说明 |
| --- | --- | --- | --- | --- |
| `expected_object_version` | 是 | 整数 | 最小值 1.0 | 刚读取的工单/QA object.version；所有审核动作都检查此值。修订 state_version 另通过 If-Match 请求头传递。 |
| `expected_current_revision_id` | 否 | 字符串（uuid） 或 null | — | 刚读取的 object.current_revision_id，即当前正式版本 UUID；尚无正式版本时传 null，不能填写本次待审草稿 UUID。 |
| `comment` | 否 | 字符串 | 最长字符数 2000；默认 `""` | 提交或审核意见；驳回时必须填写非空白原因。 |
| `accept_incomplete_start` | 否 | 布尔值 | 默认 `false` | 批准工单时，是否明确接受缺少原始提问、以首次可见上下文确定日期的情况；该类工单批准时必须为 true，不会补造原始提问。 |

### TicketContent

工单修订的完整正文。日期来自所关联原文消息，服务端计算并保存日期快照。

| 字段 | 必填 | 类型 | 约束和默认值 | 中文说明 |
| --- | --- | --- | --- | --- |
| `title` | 是 | 字符串 | 最短字符数 1；最长字符数 300 | 工单标题。 |
| `first_visible_message_id` | 是 | 字符串（uuid） | — | 该问题来源中最早具有有效时间的可见消息 UUID；服务端校验它确实对应最早可见时间，不接受手填日期替代。 |
| `first_question_message_id` | 否 | 字符串（uuid） 或 null | — | 经人工或抽取确认的原始提问消息 UUID，必须属于该问题且具有有效时间；缺少原始提问时应传 null，不能用后续回答冒充。 |
| `date_basis` | 否 | 字符串 | 可选 `first_question`、`first_visible_context`；默认 `"first_question"` | first_question=按原始提问时间确定工单日期，此时必须提供 first_question_message_id；first_visible_context=按首次可见上下文确定日期，此时提问 ID 必须为空，批准还需人工确认上下文不完整。 |
| `problem` | 是 | 字符串 | 最短字符数 1；最长字符数 20000 | 问题描述。 |
| `impact` | 否 | 字符串 | 最长字符数 10000；默认 `""` | 问题产生的影响或涉及范围。 |
| `handling_summary` | 否 | 字符串 | 最长字符数 30000；默认 `""` | 已发生处理过程的摘要。 |
| `current_conclusion` | 否 | 字符串 | 最长字符数 20000；默认 `""` | 根据现有记录得出的当前结论。 |
| `claims` | 否 | 数组〈[Claim](#claim)〉 | 默认 `[]` | 需要单独核对的关键事实；有条目时，每项均须绑定 claims.<claim_key> 的支持依据才能提交审核。 |
| `next_actions` | 否 | 数组〈[NextAction](#nextaction)〉 | 默认 `[]` | 后续处理事项列表，分别注明聊天约定或审核人员建议。 |
| `status` | 否 | 字符串 | 可选 `open`、`in_progress`、`waiting_customer`、`waiting_internal`、`answered`、`resolved`、`cancelled`、`unknown`；默认 `"open"` | 业务处理状态：open=待处理，in_progress=处理中，waiting_customer=等待客户，waiting_internal=等待内部处理，answered=已答复，resolved=已解决，cancelled=已取消，unknown=未知。它不同于修订的草稿/审核状态。 |

### TicketRevisionCreate

为已有工单保存一份不可变的新草稿修订；保存不会直接替换正式版本。

| 字段 | 必填 | 类型 | 约束和默认值 | 中文说明 |
| --- | --- | --- | --- | --- |
| `expected_object_version` | 是 | 整数 | 最小值 1.0 | 读取工单详情时取得的 object.version；必须与服务端当前对象版本一致。它不同于修订的 state_version。 |
| `base_revision_id` | 否 | 字符串（uuid） 或 null | — | 读取详情时的 object.current_revision_id，即当前已批准的正式版本 UUID；尚无正式版本时传 null。不能用正在编辑的草稿 UUID 代替。 |
| `replaces_revision_id` | 否 | 字符串（uuid） 或 null | — | 本次编辑所替代的同一工单草稿、审核中或驳回修订 UUID。旧草稿/审核中版本会标记为 superseded，驳回版本保持原状态；正文和历史不被覆盖。 |
| `evidence` | 否 | 数组〈[EvidenceBinding](#evidencebinding)〉 | 最多项数 1000；默认 `[]` | 新修订的完整字段证据绑定集合，不是差量更新。 |
| `change_reason` | 否 | 字符串 | 最长字符数 2000；默认 `""` | 本次修改的原因，写入创建修订的审计记录。 |
| `content` | 是 | [TicketContent](#ticketcontent) | — | 新修订的完整工单正文。 |

### UserCreate

由管理员创建内部账号；密码至少 12 位。新账号自动获得默认内部记录范围，发送人按用户名或显示姓名识别。

| 字段 | 必填 | 类型 | 约束和默认值 | 中文说明 |
| --- | --- | --- | --- | --- |
| `username` | 是 | 字符串 | 最短字符数 2；最长字符数 100 | 唯一登录名；服务端会去除首尾空白。 |
| `display_name` | 是 | 字符串 | 最短字符数 1；最长字符数 100 | 账号显示名称；服务端会去除首尾空白。 |
| `password` | 是 | 字符串 | 最短字符数 12；最长字符数 200 | 新账号密码；本接口要求至少 12 个字符。该规则适用于创建账号接口，不代表部署时初始管理员环境配置的校验规则。 |
| `role` | 是 | 字符串 | 可选 `admin`、`agent`、`reviewer` | admin=管理员，agent=业务操作人员，reviewer=审核人员；具体接口权限见接口说明。 |

### UserUpdate

管理员更新系统账号；虽然使用 PATCH，但 username、display_name、role 仍须一并提交。

| 字段 | 必填 | 类型 | 约束和默认值 | 中文说明 |
| --- | --- | --- | --- | --- |
| `username` | 是 | 字符串 | 最短字符数 2；最长字符数 100 | 更新后的唯一登录名；服务端会去除首尾空白。 |
| `display_name` | 是 | 字符串 | 最短字符数 1；最长字符数 100 | 更新后的账号显示名称；服务端会去除首尾空白。 |
| `role` | 是 | 字符串 | 可选 `admin`、`agent`、`reviewer` | 更新后的账号角色：admin=管理员，agent=业务操作人员，reviewer=审核人员。 |
| `password` | 否 | 字符串 或 null | 最短字符数 12；最长字符数 200 | 需要重置时填写新密码，本接口要求至少 12 个字符；省略或 null 保留现有密码，空字符串不等于保留。 |

### ValidationError

一项请求结构或类型校验错误。

| 字段 | 必填 | 类型 | 约束和默认值 | 中文说明 |
| --- | --- | --- | --- | --- |
| `loc` | 是 | 数组〈字符串 或 整数〉 | — | 错误位置路径，例如 ["body", "content", "title"]；可包含字段名或数组元素下标。 |
| `msg` | 是 | 字符串 | — | 框架返回的错误说明文字，不保证为中文。 |
| `type` | 是 | 字符串 | — | 供程序识别的校验错误类型，例如 missing、string_too_short。 |
