---
name: benchmark
description: Prepare and run reproducible LLM inference benchmark workloads with explicit parameters, dataset provenance, offline-dependency checks, and result preservation. Use for benchmark request generation and result parsing, not profiler collection or trace analysis.
metadata:
  short-description: 推理压测与 workload
---

# Inference benchmark

本 Skill 只负责推理服务的 workload 准备、benchmark 执行和结果整理。端到端部署与阶段编排由 `../SKILL.md` 负责；profiling 采集与结果验收由 `../profiling/SKILL.md` 负责。

## 参数来源

- 普通 benchmark 的并发、请求数、输入/输出长度、预热次数和数据集必须来自已确认的实验配置或用户指令。
- 首次基线保留完整C=1、2、4、8、16、32；优化调试默认仅C=1、8、32。使用benchmark_test.sh的full（默认）或tuning显式模式，不永久覆盖完整CONCURRENCIES；每档请求数、预热、数据及seed协议不变。
- tokenizer 固定使用容器内已挂载检查点的 `MODEL_PATH`。API 的 served model name 只用于请求字段，不作为 tokenizer 下载标识。

配置验收后查框架/平台的负载实现或CLI前，先按[平台导航](../platforms/README.md)直接定位目标版本官方资料，找不到再检索；经验不能替代当前版本的数据集行为核验。

## 离线依赖预检

正式运行前，在目标镜像的实际版本中检查 benchmark CLI 和所选 dataset 实现，不能仅凭参数名称判断其离线行为。

至少确认：

1. tokenizer 与模型配置是否仍会根据 served model name 访问远端仓库；
2. dataset 是否会隐式下载语料、图片或其他辅助文件；
3. 所需本地文件是否已挂载到 client 容器且可读；
4. 预热和正式请求开始前是否仍存在未解析的网络依赖。

某些框架版本的 `random` dataset 并非纯随机离线生成。例如 SGLang 0.5.21 的 `random` 会在没有有效 `dataset_path` 时下载 ShareGPT，再重复/截断其中的 token；仅设置本地 tokenizer 不能消除该下载。该版本的 `random-ids` 可离线生成整数 token，但会改变输入 token 分布，源码也提示可能触发 NaN，不能静默替换。

发现隐式网络依赖或缺少外部数据时，停止当前运行并标记为无效。向用户报告实际版本、缺少的数据、访问目标、失败证据和以下可用方案，等待选择：

- 提供并挂载与当前 dataset schema 匹配的本地数据文件；
- 使用当前版本明确支持的离线合成 dataset，并说明 workload 语义和风险变化；
- 明确授权 AI 从指定或已确认的可信来源下载到用户选择的目录，随后校验格式、记录来源并只读挂载；
- 由用户配置网络或已有缓存。

用户没有明确选择前，不得自行下载数据、生成替代数据集、把 `random` 换成 `random-ids`，或把失败运行计入正式结果。用户选择“AI 下载”但下载来源或保存位置会影响结果或共享存储时，先补问缺失项；不能自行决定。

## 执行与结果

- 执行前根据模型/服务是否已就绪、并发档位、每档请求数、ISL/OSL、预热和现场资源给出预计耗时区间；完成、失败或停止后报告实际耗时及偏差原因。完成回复中的合理下一步也分别标注基于当前工程状态的预计耗时。
- 预计单次 benchmark 超过 5 分钟时，启动前按总 Skill 让用户选择“AI 接管查询”或“人工唤醒”。两种方式都使用后台模式并记录 PID/作业 ID、日志、退出状态和结果目录；前者每次计划等待最多15分钟，唤醒后检查一轮，正常则继续等待最多15分钟，不循环轮询；后者只告知建议回来时间并等待用户，不主动检查。
- 执行前向用户概述本轮实际并发、请求数、ISL、OSL、预热次数、dataset 和 tokenizer 来源。
- 保存完整参数、原始输出、退出状态和结果文件；LOG只记有效性结论、重要异常及结果/报告入口，不复制每条命令或进度。
- 初始化或数据准备阶段失败时不得生成成功 benchmark 结论。
- 每个基线/候选版本压测验收后立即回写统一正式报告对应版本章节：带版本标签的实际指标表/单位、成功数与token量、从脚本快照展开的完整命令、预计/实际耗时和结果位置；同步LOG及该轮计划/报告/索引状态，再汇报完成，不等整轮调优结束。失败只记录失败证据与未完成边界，不伪造结果。

## 调优前后对比

完整自动调优时按`../references/autotuning.md`复用每档原负载协议。默认配置/框架/算子合为一个候选，只执行一套1、8、32三档；逐档提取完整基线中相同C比较，不与六档合计比较、不外推未测档位。已有合格基线可复用，无可比基线先确认补测成本。关闭Profiler/Nsys，固定负载与资源预算，保留允许改变的设计差异、实际token量与成功率；性能以端到端指标为准，不以chat或采集窗口延迟代替。单次对比只称观测变化，不擅自重复多轮或声称统计显著。可用`../scripts/compare_tuning_benchmarks.py`逐档作离线规范结果对比。

## 远端执行与本地结果

脚本/内部配置在远端由design维护、execute运行，真实结果需要分析时由二级派analyze。指标、实际负载与结论由design及时完整写进最终报告并回收报告；原始JSON/JSONL、计算证据和逐请求日志默认留远端，不额外创建本地results/或交付索引。仅用户明确需要原始数据/本地复算时再回收。不要为交付benchmark把整个client目录带回本地。
