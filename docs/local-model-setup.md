# 本地模型与 Dify

## 导入两条工作流

项目提供 [问题归属 DSL](../dify/topic_assignment_v1.yml) 和 [记录抽取 DSL](../dify/record_extraction_v1.yml)。模板按 Dify 1.17.1 的节点结构生成，输入为 `payload_json` 字符串，输出为 `result_json`、`validation_status`、`error_code`。

1. 在 Dify 工作室分别导入两份 DSL。
2. 为抽取和修正两个 LLM 节点选择实际可用的本地模型。`SELECT_YOUR_LOCAL_QWEN_MODEL` 是占位符，不能直接运行。模板默认提供商为 Ollama，其他提供商需调整参数及 JSON 输出方式。
3. 同步模型上下文、最大输出及本项目 Token 预算，见[模型预算与断点恢复](token-pipeline.md)。
4. 使用 [归属输入示例](../backend/workflows/example.topic.input.json) 和 [抽取输入示例](../backend/workflows/example.extraction.input.json) 的完整 JSON 文本调试 `payload_json`。
5. 分别发布工作流，把两个 API Key 填入项目 `.env`：

   ```dotenv
   DIFY_LOCAL_BASE_URL=http://host.docker.internal:8880/v1
   DIFY_LOCAL_TOPIC_KEY=app-问题归属应用密钥
   DIFY_LOCAL_RECORD_KEY=app-记录抽取应用密钥
   ```

6. 重新创建读取环境变量的容器：

   ```sh
   docker compose up -d --no-deps --force-recreate api worker beat
   ```

`DIFY_LOCAL_BASE_URL` 是业务容器访问 Dify 的地址，需带 `/v1`。Dify 提供商中的模型 Base URL 则是 Dify 插件容器访问模型的地址；两段连接都必须可达。API Key 已配置不代表模型连接已通过。

## 可选 Ollama 容器

[模型 Compose](../compose.local-model.yaml) 使用 `qwen3-vl:4b-instruct-q4_K_M` 处理纯文本，默认只读挂载 `E:/Ollama/models`，加入已有 `dify-local_default` 网络，不映射宿主机端口。该文件不会下载模型；使用前需确保目录中已有对应模型，并根据实际环境配置 `.env` 的 `LOCAL_OLLAMA_MODELS_DIR` 和 `LOCAL_DIFY_NETWORK`。

先启动已有 Dify，再在根目录执行：

```sh
docker compose -f compose.local-model.yaml up -d
```

此配置要求可用的 NVIDIA 容器 GPU，使用单并发、8192 上下文及 3GB 容器内存限制；换硬件或 CPU 部署应调整 [Compose](../compose.local-model.yaml) 并实测。Dify Ollama 提供商中的模型地址为 `http://records-ollama:11434`，模型名需与已存在模型一致。

停止此模型服务：

```sh
docker compose -f compose.local-model.yaml stop
```

模板的 `num_ctx` 和 `num_predict` 读取任务预算，默认归属输出 1800、抽取输出 2600，Ollama 配置还需允许相应上限。JSON Schema 使用静态参数文本，后端继续独立执行完整 Schema、逐字证据和贡献者校验。

## 校验与发布

每条工作流包含 9 个节点：输入、输入校验、抽取、输出校验、条件分支、直接输出、修正、再次校验、修正后输出。首次输出不合格时反馈具体错误，最多修正一次；仍不合格则由业务任务保留失败状态。

源规则与输入 / 输出契约位于 `backend/workflows/`。修改后执行生成和回归：

```sh
python scripts/build_dify_dsl.py
python scripts/test_dify_prompts.py -v
```

本地文件更新后，还需同步到 Dify 并发布，运行中的应用不会自动读取仓库文件。更换提供商时需同时调整抽取和修正节点，不能只修改模型名称标签。

`scripts/repair_local_dify.py` 可在匹配的 Dify 1.17.1 API 容器内同步两个既有应用；默认只预览，显式 `--apply` 才更新模型凭据和发布流程。它仅选择唯一匹配的应用并核对模型，保留历史版本和 API Key。使用前按实际容器名替换以下示例：

```powershell
$dockerPath = "$env:LOCALAPPDATA\Programs\DockerDesktop\resources\bin\docker.exe"
& $dockerPath exec dify-local-api-1 mkdir -p /tmp/records-repair
& $dockerPath cp scripts/repair_local_dify.py dify-local-api-1:/tmp/records-repair/repair_local_dify.py
& $dockerPath cp dify/. dify-local-api-1:/tmp/records-repair/
& $dockerPath exec -w /app/api dify-local-api-1 /app/api/.venv/bin/python -c "exec(compile(open('/tmp/records-repair/repair_local_dify.py').read(),'<repair>','exec'))"
```

## 真实模型联调

以下脚本会创建带唯一标记的合成聊天文件、确认导入、调用已配置的本地模型并保留草稿，不会批准内容：

```powershell
$dockerPath = "$env:LOCALAPPDATA\Programs\DockerDesktop\resources\bin\docker.exe"
$scriptPath = (Resolve-Path -LiteralPath 'scripts/live_dify_check.py').Path
& $dockerPath compose run --rm --no-deps -v "${scriptPath}:/srv/live_check.py:ro" api python /srv/live_check.py
```

恢复合成任务时可传入 `LIVE_CHECK_JOB_ID`；脚本只接受当前命名规则的合成文件任务，并复用已成功步骤。技术链路通过不等于真实业务内容已审核，实际抽取质量仍需人工核对。
