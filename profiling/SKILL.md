---
name: profiling
description: Collect and validate a bounded continuous time window under sustained inference load, for single-service or PD endpoints, using PyTorch Profiler or Nsight Systems; recover core artifacts without automatically analyzing them.
metadata:
  short-description: 持续负载下的时间窗口采集
---

# Inference profiling

只负责采集、验收和回收。总编排见[根Skill](../SKILL.md)，负载准备见[benchmark](../benchmark/SKILL.md)，Nsys报告核验/分析见[nsight-systems](nsight-systems/SKILL.md)。普通benchmark协议不变。

## 默认：持续负载，一个连续时间窗口

- profiler只采PyTorch；nsys只采Nsys；profiling依次分开运行两者，不同时打开，不自动分析。
- 确认结果属于普通实验还是明确study/baseline/candidate；不覆盖其他版本，见[调优归属](../references/autotuning.md)。
- C为最大在途请求数。长度、数据、tokenizer和拓扑沿用验收后的实验。默认设计表为protocol="time"、prerun_completed_multiplier=4、postrun_completed_multiplier=1、prerun_seconds=0、capture_seconds=15、max_requests=100000；运行前展示实际值，用户或已有配置优先。时长是可修改的协议默认，不是自动探测稳态的结论。
- 采集前结合已有同负载请求耗时及预热观测评估单次请求周期与窗口覆盖风险，尤其是C=1；预热耗时仅为估计，不保证窗口同时覆盖prefill与decode。窗口不足时在开始采集前说明风险并由用户明确选择，不能静默延长、改变请求调度或重采。实际缺覆盖须保留证据并报告，不得宣称完整。
- 用户选择默认负载时，先采用当前实验已确认配置或对应项目模板默认，核对 ISL、OSL、dataset、tokenizer 与服务上下文及资源。若默认与上下文或资源冲突，先报告并等待用户选择；不得静默换用框架示例或更改既定负载。
- 预热2个请求并等待结束，然后持续运行最多C个worker，完成一个补一个。完成prerun_completed_multiplier×C（默认4C）个正式请求后开始采集，可选prerun_seconds还可要求最短预运行时间。等所有角色的开始响应返回，再保持capture_seconds，向所有角色并发发送停止请求。停止导出期间仍补充负载，所有stop确认后再完成至少postrun_completed_multiplier×C（默认C）个请求，最后停止补充并排空在途。整个运行只采capture这一个中间窗口，不采initial/after-prerun。
- 采前4C与采后C用于把窗口放在持续负载中间，不是划分两次采集；不固定N=5C。5C仅为本地prompt池大小，采用固定seed循环复用；正式请求数取决于实际运行时长。默认要求关闭prefix cache；若要开启，应先明确新的prompt生成/复用语义，不能将命中缓存的负载与无缓存负载混为一谈。
- max_requests为硬安全上限；触顶、请求失败、控制失败均标为未完成，停止补充并清理本次采集，不自动增预算。请求自身有超时，采后负载达标再停止补充并等待在途结束。导出/排空计入实际耗时，不能把配置的窗口时长说成整个阶段耗时。
- time模式不传num_steps，profile_by_stage=false。不加载Hook，不强制先P再D，不启用旧单服务阶段适配。单服务得到同一时间区间内实际交错的P/D；PD分别得到各角色的连续时间线。
- P/D steps、batch范围是采后的覆盖证据，不是停止条件。单服务短窗口不保证含有P和D；必须逐rank验证两者，PD只要求各自阶段。缺覆盖保留产物并报告，不凭“同一个节点”假定齐全，不静默延长或重跑。

## 控制路径与时钟

当前入口为容器内client/profile_capture.sh → profile_workload.sh → run_time_profile.py → time_profile.py，只生成一个capture窗口。profile_windows.py仅供显式历史steps兼容，不进入当前默认采集或报告。公共执行源在scripts/templates/shared/client/，生成器复制到工程；不得依赖另一个工程目录。

1. 配置验收后先按[平台导航](../platforms/README.md)定位本平台官方采集资料及获批经验，再核对精确框架版本、平台及其原生连续start/stop接口。当前脚本实现是SGLang HTTP API；vLLM或NPU需按当前版本核实并适配，不能宣称通用兼容。在 NPU/Ascend 镜像内以独立 Python 进程运行采集/客户端脚本时，还需注意 torch 2.10 设备后端自动加载与 `profile.py` 文件名遮蔽两类导入陷阱，分别见[平台经验](../platforms/ascend/experience.md)与下文的“采集脚本执行环境（独立 Python 进程陷阱）”小节。SGLang官方接口支持省略num_steps后手动stop，依据见[官方说明](https://github.com/sgl-project/sglang/blob/main/docs/docs/developer_guide/benchmark_and_profiling.mdx)；部署仍冻结实际版本的源码/文档，不能以main替代目标版本。
2. 检查离线dataset、已挂载本地MODEL_PATH tokenizer及依赖。缺失时按根Skill报告，不安装/下载或替换负载。
3. single控制实际服务；PD生成请求发router，但start/stop直接发全部P/D实际endpoint，不依赖router转发。PD还核验router的workers健康。详见[PD规则](references/pd-disaggregation.md)。
4. 每个控制请求记录endpoint、body、发送/响应的客户端wall与monotonic时间、当时issued/completed；仅HTTP200不够，显式success=false也失败。开始部分失败或响应超时，要对所有尝试启动的端点做有界stop清理；清理不确认则明确报告。
5. 两角色开始/停止并发下发，实际响应不会绝对同步。workload中的control_common_interval_seconds仅为“最晚开始响应→最早停止发送”的保守客户端控制区间；不能冒充GPU实际起止或跨机时钟对齐。PD链路对齐需记录主机时钟偏差和请求关联标识；没有证据时分别分析角色，不直接相减跨主机trace时间戳。

## 采集脚本执行环境（独立 Python 进程陷阱）

profile_capture 链路最终以独立 Python 进程运行采集脚本（容器内 `/workload` 或 `client/` 下的采集脚本）。该进程与 vLLM/SGLang 服务进程隔离，**不继承服务进程已显式 `import torch_npu` 的副作用**，因此会暴露两类导入链陷阱。下列规则与具体机器、镜像 tag、目录无关，凡在容器内以独立 Python 进程跑采集脚本皆先按对应分支排查；不要把失败静默归为“数据/网络问题”或“transformers 未安装”。

### 通用：采集脚本命名为 `profile.py` 被标准库遮蔽

- 现象：采集脚本名为 `profile.py` 且位于脚本目录（运行时会进入 `sys.path[0]`）时，导入链 `transformers → generation → masking_utils → torch._dynamo → cProfile` 触发 `import profile`，把本脚本误当标准库 `profile` 导入，报 `AttributeError: module 'profile' has no attribute 'run'`（出现在 cProfile 启动处）。这是脚本文件名与标准库 `profile` 同名造成的遮蔽，与 NPU 无关，是纯 Python 陷阱。
- 规避：以 `python3 -P` 启动采集脚本（Python 3.11+ 的 `-P` 标志：运行脚本时不把脚本所在目录加入 `sys.path`），彻底消除遮蔽；无需改名，也不动报告/任务契约中对 `profile.py` 的引用。验证：在脚本同目录下 `python3 -P -c "import cProfile; from transformers import AutoTokenizer"` 不再触发遮蔽。
- 注意：若运行环境 Python < 3.11，不能依赖 `-P`，应改为在导入前调整 `sys.path` 或给采集脚本改名（避免与 `profile`/`cProfile` 冲突）；不要只因为“本机跑过”就假定 `-P` 可用。

### NPU/Ascend：torch 2.10 设备后端自动加载

在 NPU/Ascend 镜像内以独立 Python 进程运行需 `from transformers import ...` 的采集脚本时，还会遇到 torch 2.10 默认 `TORCH_DEVICE_BACKEND_AUTOLOAD=1` 去加载 `torch_npu` 后端失败的导入陷阱。详见[平台经验：torch 2.10 设备后端自动加载](../platforms/ascend/experience.md)。该条已给出设置 `TORCH_DEVICE_BACKEND_AUTOLOAD=0` 的规避与验证；凡在 NPU 镜像内独立进程使用 transformers 加载本地 tokenizer 的采集/客户端脚本，先按该条排查。另见同文件的“torch_npu ascend_pt 模式：自动导出的 chrome trace 为空”与下条“已实测的完整 trace 离线转出方案（torch_npu.profiler.profiler.analyse）”：stop 后自动导出的 `*.pt.trace.json.gz` 常为无 device/kernel 事件的空壳，真实 NPU 数据在 `PROF_*/device_0/data` 原始目录；离线转出必须用 `torch_npu.profiler.profiler.analyse`（裸 `msprof --export` 解析不了 ascend_pt 格式），验收须按对应条目处理，不要按标准 `trace_view.json` 判定。

## PyTorch Profiler

- start请求activities=["CPU","GPU"]，profile_by_stage=false，detailed_annotations=true，不传num_steps；显式stop导出原生混合trace。
- 每次确认native key_averages选择；基础模板仅支持关闭。开启需验证目标版本的实现并取得适配授权，不能把离线聚合冒充原生key_averages，也不默认注入Hook。
- 在各角色源主机运行client/validate_time_window.py RUN_DIR --role single|prefill|decode --tp-size TP。PD的workload.json来自真实client主机，必要时明确复制并传--workload；输出time-validation-ROLE.json。
- 验收控制区间、请求成功数、每个期望rank的唯一非空GPU trace、gzip/JSON完整性、SHA-256和原生P/D step spans。single要求P与D均出现；PD仅要求自己的阶段。不再要求4/128；存在额外DP/PP/EP rank维度时先扩展明确的rank身份清单，不能只按TP删文件。
- scripts/collect_profiler_results.py自动识别time workload，支持--single-host或两PD主机、显式--client-host及两角色独立TP数。回收后重新检查本地混合trace，暂存通过才发布；失败保留旧合格结果。
- Trace导出可能干扰服务，这次负载延迟不作为普通benchmark指标。

## Nsys

- 仅在NVIDIA且目标版本支持时使用。各计算角色先以server/nsys_service.sh包装服务；single不传角色，PD分别传prefill/decode。这不是对普通服务的事后attach。
- 设置所有参与角色相同的唯一NSYS_RUN_ID，并让client的PROFILE_RUN_DIR=/server/profiles/同一run；此路径是Linux容器内协议。旧服务冲突先按本实验对象规则处理，不能为采集擅自停他人服务。
- client使用同样的time请求流，activities=["CUDA_PROFILER"]；通过框架原生cudaProfilerStart/Stop驱动capture range，不同时开启torch.profiler。
- 保留cuda/nvtx/osrt、cudaProfilerApi范围、repeat:sync导出和kill=none。一个time窗口正常每角色一个范围；不能因文件存在就认定范围/设备齐全。report-ready回调只记录路径与时间，不证明报告健康或覆盖。
- 单服务模板包含sysfs CPU拓扑预检及只读挂载；PD或其他启动器也须先确认采集容器的online/possible/present可读，按自身配置等价处理，不使用privileged替代。
- 采集后按官方nsight-systems Skill核验原始.nsys-rep健康、目标设备、CUDA活动、范围与客户端控制事件。不得把validate_time_window.py用于Nsys，不要求Nsys凭空具有PyTorch step spans。
- record_function不自动成为NVTX。若无可识别的阶段标记，仅说明角色/控制区间证据；单服务P/D覆盖未确认时，不把kernel存在冒充P/D均有。需要逐阶段关联时先获准添加最小标记，不自动启用完整算子NVTX。
- 不自动为得到报告而终止模型服务。报告未ready或Importer失败时保留索引/日志并报告未完成，不能强杀服务充当正常导出。

## PD是否采Router

默认只采P和D两个计算角色；同时保留client请求时序、失败信息和router已有的访问/错误日志及可用路由指标。Router通常负责控制/路由，P→D的KV数据路径取决于实际传输后端，常由角色之间直接传送；先核实实际拓扑，不能假定KV必经Router。

只有怀疑Router CPU、排队或转发瓶颈时，才经明确范围选择补采Router CPU时间线；CPU/Rust Router不能因为暴露HTTP就调用PyTorch start_profile，也不默认分配第三份GPU采集。GPU通信与传输的相关调用先看P/D时间线；网络吞吐、丢包、RDMA等需要专门指标，不把两份GPU trace称为完整网络抓包。

## 回收、报告与边界

time布局为profiling_results/{profiler,nsys}/C<C>/capture/；single下为single/混合trace，PD下为prefill/、decode/角色trace。不把同一份single混合trace复制成P和D两份。保留workload.json、MANIFEST.md、每rank窗口摘要或Nsys报告索引及健康证据；来源、实际rank/设备、命令、时长与SHA-256入清单。

步骤采集的历史结果仍保留initial/after-prerun/{prefill,decode}/，不迁移或重标。只有用户明确要求复现时设置protocol=steps并读取[历史协议](references/step-windows.md)；旧P4/D128适配不用于time模式。

普通实验/调优版本分别隔离结果。同C复跑先验暂存，再在明确范围替换，不混旧文件。源主机和本地数量、大小、SHA一致且各角色完整后才称交付成功；采集退出码0仅表示captured-unvalidated。

Ascend/torch_npu的`ascend_pt`原始结果是多rank深层目录，含`PROF_*/device_*/data`、host、离线分析输出、数据库、统计表和控制/失败证据；不能只回收四份`trace_view.json`或套用NVIDIA的`*.trace.json.gz`判据。先在`capture/`整理可直接打开的每rank结果及MANIFEST，再把本轮远端`profile-output/`**整个目录**按原层级回收到同一C目录的`raw/`；跨系统遇路径长度限制时用单个tar归档保留原始目录，不用逐文件scp造成缺失。长传输或不稳定链路先在源端生成固定归档与SHA-256，再使用可续传协议回收；本地完整摘要匹配后才发布，断线产生的半包不得当结果。核对源与本地的文件相对路径、数量、大小和SHA-256；归档用`tar -tf`确认目录与条目，解包或流式计算摘要后才能称完整。保留原始失败尝试并在manifest注明哪些是有效采集；不要把空壳trace当有效rank。大文件暂存、归档和已有capture占用的空间先核实，不在传输失败时覆盖已验收capture。

统一正式报告的Profiling章给完整实际调用与自定义源码。完成回复汇报C、预热2、采前4C/采后C覆盖、capture配置与实际控制区间、实际请求数、阶段覆盖/batch、rank/设备与聚合选择；列可打开核心trace或.nsys-rep路径。ANALYSIS仅在收到分析口令时更新，Nsys分析走官方子Skill。超过5分钟的实际实验遵循[阶段契约](../references/task-contract.md)；修改Skill或模拟测试不等于真实GPU采集成功。

## 角色与干净交付

采集脚本由design在远端工程编辑，execute运行、验收并封存；二级再按授权派analyze远端离线分析。design负责把本次完整原生产物和必要分析按project-contract白名单回收本地，不回收脚本、coordination或整个服务器历史profiles。collect_profiler_results.py是已支持格式的trace/窗口整理工具，不等于任何平台原生目录全量回收；需要完整原生目录时仍原样归档并验证后交付。最终报告由design统一更新，自定义实现仍完整嵌入Markdown。
