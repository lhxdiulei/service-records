# 预筛选验证

## 离线合成基准

[`scripts/benchmark_prefilter.py`](../scripts/benchmark_prefilter.py) 用固定、有标签的合成聊天比较“仅媒体过滤”与当前保守预筛选。脚本不读取客户聊天、`.env` 或业务数据库，也不调用模型。

两条路径使用同一分词器、System / User 提示词、固定候选问题池和预算，调用实际解析、分片、分批及 Token 计数实现。检查有效消息保留、原文不变、分片覆盖和每个输入包不超预算。

在安装后端依赖的环境中，从根目录执行：

```sh
python scripts/benchmark_prefilter.py --output .local/prefilter-benchmark.json
```

`--repetitions` 控制预筛计时重复次数，默认 25；`--pack-repetitions` 控制打包计时重复次数，默认 3。两者预热后取中位数。可显式设置 `--tokenizer`、`--context-tokens` 和 `--topic-output-tokens`，必须与所评估模型匹配。

| 合成组 | 覆盖内容 |
| --- | --- |
| `isolated_noise` | 空白、媒体占位、独立问候 / 致谢和系统通知 |
| `business_only_control` | 完整问答、状态和纠正 |
| `mixed_workday` | 邻近业务的问候、确认回复、失败、需求号和媒体 |
| `cross_day_reply` | 跨天建议、失败、恢复和纠正 |
| `quotes_sql_and_ambiguity` | 引用、SQL、普通用户发送的类似系统通知和不确定文本 |
| `long_sql` | 长 SQL、Unicode、换行和分片 |
| `many_batches` | 多组问答与状态消息，验证自动分批 |

报告输出当前版本、分词器和提示词指纹、Token、过滤原因、保留率与计时；任何有效消息丢失、原文变化或预算异常均返回非零退出码。最新结果以本次执行报告为准，不把旧机器上的时间或特定任务计数作为系统当前性能。

离线报告只测归属阶段输入与打包时间，不包含模型输出、工单 / QA 抽取、校正重试和推理耗时。合成样本不代表真实业务分布；零原文遗漏也不能证明模型最终答案没有遗漏。

## 可选本地模型 A/B

[`scripts/benchmark_prefilter_live.py`](../scripts/benchmark_prefilter_live.py) 固定使用 `local`，仅比较两次合成归属请求，不连接业务库或调用外部配置。默认只校验输入：

```sh
python scripts/benchmark_prefilter_live.py --output .local/prefilter-live.json
```

实际调用前需向脚本环境提供 Dify 本地地址与 Key；显式 `--execute` 才调用模型。可在 API 容器内执行并挂载脚本；Dify 会保留合成请求日志。

```powershell
$projectRoot = (Get-Location).Path
$dockerPath = "$env:LOCALAPPDATA\Programs\DockerDesktop\resources\bin\docker.exe"
& $dockerPath compose run --rm --no-deps --entrypoint python `
  --volume "${projectRoot}/scripts/benchmark_prefilter_live.py:/srv/benchmark_prefilter_live.py:ro" `
  --volume "${projectRoot}/scripts/benchmark_prefilter.py:/srv/benchmark_prefilter.py:ro" `
  api /srv/benchmark_prefilter_live.py --execute
```

每组只请求一次，不自动重试；Dify 内部仍可能执行一次校正。需比较相同发布版本、输入 Token、有效问答保留与模型结果，并考虑冷启动、缓存、输出长度和其他负载。扩大过滤规则前，应额外对真实聊天做人工标注与受控对照。
