# Ascend 获批经验

新增或修订遵循[提出与批准规则](../README.md)。以下条目只在其注明的版本和验证范围内使用。

## 原生Profiler结果回收：保存整个profile-output

- 适用范围：torch_npu ascend_pt原生采集，含多rank的`PROF_*/device_*/data`、host、`ASCEND_PROFILER_OUTPUT`及workload/控制证据。它与NVIDIA单一gzip trace结果结构不同。
- 做法：在实验`profiling_results/profiler/C<C>/capture/`保留已验收的可读rank结果；在同级`raw/`回收原始`profile-output/`整树。跨Windows长路径时传输为一个tar，tar内仍以`profile-output/`为顶层。逐文件比对相对路径、大小、SHA-256；保留失败尝试但不计作有效rank。原始目录包含的空壳`*.pt.trace.json.gz`不能取代经analyse导出的真实trace。
- 边界：本条描述回收方法，不表示仅靠归档就通过窗口、设备活动或rank完整性验收；后者仍按采集协议和下列版本经验检查。源目录与归档大小因版本/采集时长变化，不固定路径、rank数或字节数。

## vLLM-Ascend 0.23.0：NPU统计不等于原生key_averages

- 适用范围：vLLM-Ascend v0.23.0的TorchNPUProfilerWrapper；本次镜像核验版本为vLLM 0.23.0、torch_npu 2.10.0.post4。不是所有Ascend版本的通用结论，升级后须重查包装器及实际接口。
- 结论：已核验的框架采集链使用torch_npu.profiler，未提供PyTorch原生`key_averages`导出路径。不可把CUDA/Kineto的聚合接口假定为该包装器已支持的功能，也不可把昇腾生成的`op_statistic.csv`等统计文件称为原生`key_averages`。
- 处理：运行前说明该限制，确认关闭原生聚合后采集NPU trace并保留实际生成的昇腾统计。需要原生聚合时，先核验目标版本实现及其适配范围，不能默默用离线统计替代。关闭聚合的选择仅适用于明确确认的运行，不代替后续任务的用户选择。
- 证据：[冻结包装器源码](https://github.com/vllm-project/vllm-ascend/blob/5cb98caaadeff42b5b62b996e34bb2aaa29d20fd/vllm_ascend/profiler/torch_npu_profiler.py)、[对应采集指南](https://github.com/vllm-project/vllm-ascend/blob/5cb98caaadeff42b5b62b996e34bb2aaa29d20fd/docs/source/developer_guide/performance_and_debug/service_profiling_guide.md)。框架集成的接口/导出路径经过静态核验，软件版本经过容器核验；本条写入时NPU Profiler实际采集与产物验收尚未完成，不表示trace或统计导出已实测成功。
- 核验日期与批准：2026-10-25。用户在确认本次关闭原生`key_averages`时明确批准“同时经验写入skill”；本条仅记录这一限制及处理边界，不包括其他平台经验或耗时预测规则。

## torch 2.10 设备后端自动加载：独立采集进程导入 transformers 失败

- 适用范围：Ascend/NPU 镜像内 torch 2.10.0+cpu（实测 torch_npu 2.10.0.post4），以**独立 Python 进程**运行采集/客户端脚本、且脚本需要 `from transformers import AutoTokenizer`（加载已挂载本地 `MODEL_PATH` tokenizer）时。vLLM 服务进程本身不报错，因其在更早处显式 `import torch_npu`；本陷阱只发生在与服务进程隔离的独立采集子进程中。
- 结论：torch 2.x 默认 `TORCH_DEVICE_BACKEND_AUTOLOAD=1`，导入链经 `transformers` 触发 torch 设备后端自动加载，去加载 `torch_npu` 后端失败，连累上层 `from transformers import AutoTokenizer` 报 `RuntimeError: Failed to load the backend extension: torch_npu`，或连带 `ModuleNotFoundError: AutoTokenizer`。这不是数据/网络问题，也不是 transformers 未安装；同镜像内 `import torch_npu`、`vllm` 与对外服务均正常。
- 处理：在采集脚本导入 `transformers`/`torch` **之前**设置 `os.environ['TORCH_DEVICE_BACKEND_AUTOLOAD'] = '0'`（与设置 `HF_HUB_OFFLINE`/`TRANSFORMERS_OFFLINE` 同一处）。验证：`TORCH_DEVICE_BACKEND_AUTOLOAD=0 python3 -c "from transformers import AutoTokenizer; from vllm.benchmarks.datasets import RandomDataset"` 应输出成功。该修改仅为导入顺序修正，不改变协议、数据集、并发或 token 数，也不改服务侧参数。
- 证据：本次 910C qwen3-30b-a3b vLLM single 采集（workloads/20261025-c4/profile.py）实跑复现；失败 trace 见该实验 `profile-output/attempt-20261025T021540-failed/job.log`，修复经本地/远端校验和比对确认上传生效。
- 核验日期与批准：2026-10-25。用户明确指令“把相关经验完善进入 skill”批准写入；本条仅记录该导入陷阱及规避，不包括 `profile.py` 文件名遮蔽（见 profiling/SKILL.md 采集脚本执行环境）或其他平台经验。

## torch_npu ascend_pt 模式：自动导出的 chrome trace 为空，需 msprof 后处理

- 适用范围：Ascend/NPU 镜像使用 `torch_npu.profiler` 且 profiler backend 为 ascend_pt（CANN Profiler 后端）时，经 vLLM-Ascend 的 `TorchNPUProfilerWrapper` 做服务内 start/stop 采集；本次镜像核验 torch_npu 2.10.0.post4、CANN 9.1.0。不是所有 Ascend 采集路径的通用结论；NPU 原生 trace 与 CUDA/Kineto 的标准 `trace_view.json` 行为不同。
- 结论：采集（profiling）本身成功——4 个 rank 的 NPU 原始性能数据已落盘到各 rank 的 `PROF_<id>/device_0/data` 与 `host/`（msprof 原始采集，每 rank 十余 MB）。但 torch_npu 在 stop 后自动导出的 chrome trace（容器内文件名形如 `*.pt.trace.json.gz`，位于 `traces/` 根）**只是一个空壳**：解压后约 8KB，仅含 `process_name`/`thread_name` 等 M 元数据事件，`ph:"X"` 实际事件数与 kernel 事件数均为 0；真正的算子/kernel 活动没有被转换成标准 chrome trace 的可视化事件。这与 CUDA/Kineto 会自动产出完整 `trace_view.json` 不同。
- 处理：后处理转出的**已实测可用方案**见本文件下条 `torch_npu.profiler.profiler.analyse`。裸 `msprof --export=on` 解析不了 ascend_pt 格式（对 `ascend_pt` 目录或内层 `PROF_*` 都报 `Failed to find profiling data`），不要用；顶层 `torch_npu.profiler.analyse` 未导出、`Profiler.export_chrome_trace` 是需已加载数据的实例方法，均非离线入口。验收脚本也不应按标准 `trace_view.json` 或空壳 `*.pt.trace.json.gz` 判定通过；应识别 Ascend 原生产物（非空、rank 齐全、含 device 活动）或转出的完整 trace。转出命令随 CANN 版本变化，使用前须按当前版本核实。
- 证据：本次 910C qwen3-30b-a3b vLLM single 采集（workloads/20261025-c4）实跑复现；空壳 trace 见 `traces/` 根 `opc-*.async_llm.*.pt.trace.json.gz`（压缩 823B/解压 8096B、X_events=0、kernel=0），原始数据见 `dp0_pp0_tp*_*_rank*_ascend_pt/PROF_*/device_0/data`。本实验 `validate_profile.py` 因按标准 `trace_view.json` 验收、找不到文件而 `exitcode=2`；原始数据已随 profile-output 迁回本地 `profiling_results/profiler/C4/capture/`。
- 核验日期与批准：2026-10-25。用户明确指令“把相关经验完善进入 skill”批准写入；本条记录该采集/导出边界及处理，下条已给出**实测成功**的离线转出方案，本实验 4 rank trace 已转出并迁回本地 `profiling_results/profiler/C4/capture/single/`（MANIFEST.md 含每 rank SHA-256），不再有“未实测”缺口；不包括其他平台经验或耗时预测规则。

## torch_npu ascend_pt 模式：已实测的完整 trace 离线转出方案（torch_npu.profiler.profiler.analyse）

- 适用范围：同本文件“自动导出为空”条（Ascend/NPU，torch_npu 2.10.0.post4 / CANN 9.1.0，vLLM-Ascend `TorchNPUProfilerWrapper`，ascend_pt 后端）。是对该条“需后处理”的实测可用方案，不是通用结论；其他 CANN 版本须重核工具名与路径。
- 结论：裸 `msprof --export=on` 解析不了 ascend_pt 格式，对 `ascend_pt` 目录或内层 `PROF_*` 目录都报 `Failed to find profiling data`；顶层 `torch_npu.profiler.analyse` 未从 `torch_npu.profiler` 导出（`ImportError`/`NameError`）；`Profiler.export_chrome_trace` 是实例方法、需已加载数据的 Profiler 对象。唯一实测可用的离线入口是**子模块函数** `torch_npu.profiler.profiler.analyse(profiler_path=...)`。
- 解决方案（具体命令，已实测成功）：
  1. 数据在容器内且原始 `PROF_*/device_0` 目录是 root 所有 `drwxr-x---`，宿主机非 root 用户读不到 → **必须在容器内以 root 运行**：`docker exec -u root <container_id> bash -c '...'`。
  2. 用容器内实际含 `torch_npu` 的解释器；本次镜像系统 `/usr/bin/python3` 不含该包。先在容器内定位 `torch_npu` 所在环境，并用该环境解释器验证 `import torch_npu`，不要把本次镜像的解释器绝对路径当通用值。
  3. 设置运行环境：`export LD_LIBRARY_PATH=/usr/local/Ascend/ascend-toolkit/latest/lib64:/usr/local/Ascend/driver/lib64:$LD_LIBRARY_PATH; export ASCEND_OPP_PATH=/usr/local/Ascend/ascend-toolkit/latest/opp`（前缀随 CANN 版本变，先确认 `/usr/local/Ascend/ascend-toolkit/latest` 存在）。
  4. 调用（`<ascend_pt_dir>` 为含 `FRAMEWORK/` 与 `PROF_*` 的采集目录）：用环境变量传入路径避免引号嵌套——`export ASCEND_PT_DIR=<ascend_pt_dir>; python3 -c "import os; from torch_npu.profiler.profiler import analyse; analyse(profiler_path=os.environ['ASCEND_PT_DIR'])"`。
  5. 输出：在 `<ascend_pt_dir>/ASCEND_PROFILER_OUTPUT/` 下生成 `trace_view.json`（本次 4 rank 各约 430MB，含真实 `ph:"X"` 事件）+ `op_statistic.csv`/`kernel_details.csv`/`task_time.csv`/`api_statistic.csv`/`step_trace_time.csv`/`communication.json`/`communication_matrix.json`/`analysis.db` 等统计文件。
  6. 注：若仍想用裸 `msprof --export`，其 `--output` 还要求输出目录不能对组可写（否则 `writable by groups`），须 `chmod 755`；本方案用 torch_npu analyse 不经 msprof 导出，可绕过该限制。
- 验证：`ls -la <ascend_pt_dir>/ASCEND_PROFILER_OUTPUT/trace_view.json` 应远大于 8KB；`grep -o '"ph"' trace_view.json | wc -l` 应 > 0（本次每 rank 数十万级事件）。
- 证据：本次 910C qwen3-30b-a3b vLLM single 采集（workloads/20261025-c4）实跑；4 rank trace 已转出并迁回本地 `profiling_results/profiler/C4/capture/single/`，MANIFEST.md 含每 rank SHA-256 与大小。
- 核验日期与批准：2026-10-25。用户在“用符合当前平台的命令重跑”与“所有平台特有命令完善进 skill”指令下批准写入；本条为已实测方案，覆盖上条“尚未实测”旧标记；不包括其他平台经验或耗时预测规则。
