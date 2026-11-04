# 平台资料导航与获批经验

本目录按平台维护“去哪里查”和“哪些经验已获批”。只加载本次平台，不全量读取所有平台；平台目录不是独立Skill，也不改变实验参数来源或授权。

下表的部署链接来自《[全网 Infra 优秀资料合集](https://pinghaoyang.com.cn/articles/notes/posts/infra-resources/)》Project → Deployment，并于 2026-11-04 逐项打开官方页面复核。链接可作为定位入口，但不能替代对目标模型、框架版本、硬件型号和部署拓扑的精确核验。

| 平台 | vLLM 部署入口 | SGLang 部署入口 | 平台资料 | 获批经验 |
| --- | --- | --- | --- | --- |
| Ascend / 昇腾 | [vLLM-Ascend Quick Start](https://docs.vllm.ai/projects/ascend/en/latest/getting_started/quick_start.html#quick-start-online-serving) | [Ascend NPU Quickstart](https://docs.sglang.io/docs/hardware-platforms/ascend-npus/getting-started/quick_start#start-sglang-server) | [ascend/sources.md](ascend/sources.md) | [ascend/experience.md](ascend/experience.md) |
| NVIDIA / CUDA | [vLLM NVIDIA Recipe](https://docs.vllm.ai/projects/recipes/en/latest/Llama/Llama3.3-70B.html#deployment-steps) | [SGLang CUDA Quickstart](https://docs.sglang.io/docs/get-started/quickstart#install-and-start) | [nvidia/sources.md](nvidia/sources.md) | [nvidia/experience.md](nvidia/experience.md) |
| Moore Threads / MUSA | [vLLM-MUSA S5000](https://docs.mthreads.com/vllm-musa/vllm-musa-doc-online/S5000/quick_start/) | [SGLang-MUSA Quick Start](https://docs.mthreads.com/sglang-musa/sglang-musa-doc-online/quick_start/) | [moore/sources.md](moore/sources.md) | [moore/experience.md](moore/experience.md) |
| AMD / ROCm | [AMD vLLM Tutorial](https://rocm.docs.amd.com/projects/ai-developer-hub/en/latest/notebooks/inference/3_inference_ver3_HF_vllm.html) | [SGLang AMD GPUs](https://docs.sglang.io/docs/hardware-platforms/amd_gpu#examples) | [amd/sources.md](amd/sources.md) | [amd/experience.md](amd/experience.md) |
| Intel / XPU | [Intel vLLM XPU](https://github.com/intel/ai-containers/blob/main/vllm/xpu.md#43-launch-workloads) | [SGLang XPU](https://docs.sglang.io/docs/hardware-platforms/xpu#launch-of-the-serving-engine) | [intel/sources.md](intel/sources.md) | [intel/experience.md](intel/experience.md) |
| Google / TPU | [vLLM JAX Quickstart](https://docs.vllm.ai/projects/tpu/en/latest/getting_started/quickstart/#run-the-vllm-server) | [SGLang TPU](https://docs.sglang.io/docs/hardware-platforms/tpu#launch-of-the-serving-engine) | [tpu/sources.md](tpu/sources.md) | [tpu/experience.md](tpu/experience.md) |
| Apple Silicon / Metal | [vLLM Metal Recipes](https://docs.vllm.ai/projects/vllm-metal/en/latest/recipes/#start-the-server) | [SGLang Apple Metal](https://docs.sglang.io/docs/hardware-platforms/apple_metal#launch-of-the-serving-engine) | [apple/sources.md](apple/sources.md) | [apple/experience.md](apple/experience.md) |
| CPU | [Intel vLLM CPU](https://github.com/intel/optimization-zone/blob/main/software/vllm/README.md) | [SGLang CPU Servers](https://docs.sglang.io/docs/hardware-platforms/cpu_server#launch-of-the-serving-engine) | [cpu/sources.md](cpu/sources.md) | [cpu/experience.md](cpu/experience.md) |

通用框架与模型来源见[sources.md](sources.md)。新增平台沿用小写平台目录；同平台不同卡型、框架、模型与版本通过条目适用范围区分，不默认互相兼容。AMD、Intel XPU、Google TPU、Apple Metal 与 CPU 当前只建立资料导航，没有已批准实验经验；不能把“官方页面可访问”写成“本项目已在该平台部署成功”。

没有精确平台/模型教程时按[迁移部署规则](../references/reference-migration.md)组合目标模型事实、平台官方接口与同类部署证据。经验库记录已验证的错误与解决方案；平台特有采集、导出或验收实现先放实验工程，重复验证且获批后才提升为平台脚本，不强行共用NVIDIA实现。

## 强制前置：任何平台任务先检索本平台经验

- 在 Ascend / NVIDIA / Moore Threads 等平台上执行**部署、benchmark、profiling 或分析**前，必须先读对应平台的 `experience.md`（与 `sources.md`），只选读与当前阶段有关的“已获批经验”；不因部署而通读Profiler/导出/分析经验，不把平台经验阅读扩展为全量预检。
- 平台经验包含该平台的特有命令、工具路径、权限/容器约束与已知导入/导出陷阱（例如 Ascend 的 `TORCH_DEVICE_BACKEND_AUTOLOAD`、采集脚本 `-P`、`ascend_pt` 空 trace 与 `torch_npu.profiler.profiler.analyse` 离线转出等）。这些不是通用 Python/Shell 知识，跨平台不成立；每次新平台/新卡型先查，不要凭其他平台经验假定通用。
- 若 experience.md 已覆盖本次问题，直接套用其“处理/解决方案”，不重新踩坑、不重新试错；若无覆盖且本次发现新坑，按“经验与Skill改进”流程提议并获批后写入。
- 本规则不改变实验参数来源或执行授权，只约束“先检索、后执行”。

## 资料定位：导航优先，检索兜底

配置验收后，先读本页及对应平台的sources.md与experience.md，再读通用来源中本任务需要的框架入口。直接打开已知官方入口，在其模型目录、版本菜单、文档索引或官方仓库对应tag中定位目标教程；可在该官方仓库内查找文件，不先做全网检索。

已收录入口足以定位时，不为相邻模型重复搜索。入口缺失、失效、不能覆盖目标组合或存在版本冲突时，才针对缺口检索，优先官方来源；找不到精确组合按迁移规则选择合理配置直接试跑，如实区分参考模型与目标模型，不因不完全匹配停在资料整理。

模型族教程明确涵盖目标架构/尺寸时即可作为启动参考，不要求每个模型尺寸都有独立标题和完整专属命令。典型来源链是本平台sources.md → 官方模型族教程 → 实际采用版本的tag/commit；不因缺少独立模型页重开搜索。已在工程配置明确的卡型，工具只显示系列名称时，先用既有平台命令启动，不为核实型号后缀反复检索或询问；实际设备选择/兼容报错再查。

对来源有疑问时，用已有记录简短说明实际采用的来源链，区分直接打开已收录链接与搜索引擎检索。网页/GitHub引用的显示本身不能证明做过web search，也不能据此认定未读sources.md。不生成来源审计长文或为证明查找过程重复访问已足够的资料。

导航只回答“去哪里查”，不能替代读取本次精确检查点、目标版本和官方命令。每次使用仍核对适用硬件/框架/拓扑，冻结实际URL、tag/commit、访问日期；latest/main和版本路径都可能变化。已知URL可直接读取核验，无需先调用搜索引擎。配置未完成时仍不得提前查部署教程。

## 经验与Skill改进：先提议，获批后写

- 部署、benchmark、profiling或分析过程中遇到可复用的平台问题、兼容性边界或重复查证成本时，可提出平台经验或Skill改进建议；不必等任务结束，也不因发现问题自动修改Skill。实验修复授权不等于共享规则写入授权。
- 建议通过当前对话提出；多agent由直属上级汇总给用户。列出问题证据、适用范围、拟写入的具体内容、预期影响及运行时解析的准确绝对文件路径。未获批准的候选留在对话或必要的实验记录，不写入本目录，不以“待验证经验”绕过批准。
- 用户明确批准具体条目及修改范围后，才更新相应experience.md或其他已批准Skill文件；批准一个条目不授权其他条目，批准建立目录也不代表批准填入过去实验经验。
- 正式经验每条注明：问题/结论，精确平台型号与框架/插件/模型/拓扑/版本范围，触发条件，已验证做法及限制，证据的可移植定位（官方固定版本链接、实验相对路径与必要摘要），验证日期和用户批准范围。静态检查、模拟测试、真实设备验证分开；不得把局部成功推广为跨平台支持。
- 不固化机器地址、SSH别名、用户名、盘符、设备编号、临时PID/端口/容器名；现场值留在实验配置。已批准经验不能覆盖更新的官方证据；发现不适用或失效时先报告并提议修订，不静默沿用或改写。
- 新发现的资料入口也可提出补充导航的建议；本次维护授权内可初始化来源导航，此后未经授权不自动改共享文件。来源表只存定位信息与核验状态，不混入未经批准的操作经验。

## 耗时预测的改进建议时机

沿用[阶段契约](../references/task-contract.md)记录执行前预估、依据、实际起止与耗时。每次获得可比较的预估/实耗后，检查偏差及原因，判断是否暴露预测方法的缺项；有依据时主动提出修正Skill预测规则的建议，无需为了凑建议而修改。

建议区分准备、上传、镜像/模型准备、模型加载/编译、服务就绪、chat、采集/导出/排空与回收的实际计时边界，说明缓存、硬件规模、框架版本等条件，以及误差是环境偶发、边界不同还是估计方法缺陷。证据不足时仅标为待验证，不凭一次运行设定全平台固定时长。

提出预测方法改进和写入耗时经验是两件事：前者给具体规则改法与预期收益，后者给适用条件与证据；两者都在用户批准后才落入Skill。这里只规定提出与审批流程，不因本节新增就实施预测算法、填入耗时数值或新增定时任务。
