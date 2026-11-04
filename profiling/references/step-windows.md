# 历史 steps 双窗口协议

仅在用户明确要求复现P4/D128历史实验时读取。设置 PROFILE_PROTOCOL=steps / --protocol steps；不是当前默认。不得将旧结果重标为time采集。

## 启用旧协议

当前默认设计表不再展示旧步数字段。复现时显式设置protocol="steps"与PROFILE_PROTOCOL=steps，并填prefill_scope="steps"、prefill_steps=4、decode_steps=128、request_multiplier=5、prerun_multiplier=4、warmup_requests=2；与对应PROFILE_*运行字段保持一致。旧单服务P4/D128还需当次明确批准的阶段适配。

## 参数与口令

- 采集前确认结果归属：普通实验沿用根profiling_results/；调优补采须绑定明确study与baseline/candidate版本，并核对实际加载配置/源码，产物与分析放该版本的profiling_results/。不按最近目录猜选，不覆盖原基线，具体见`../references/autotuning.md`的“轮次、版本与新增Profiling的归属”。
- profiler只运行PyTorch Profiler；nsys只运行Nsight Systems；profiling依次完成两者，不自动分析。
- 每次只确认C：客户端最大在途请求数，正整数。K内部固定5，正式请求总数N=5×C，不包含2个预热请求；不再询问K。
- 用户已给C时不重复询问。ISL/OSL、数据、tokenizer、拓扑沿用校验后的实验配置；缺失或冲突时询问。
- 默认双窗口：initial在2个预热请求完成后、正式请求开始前布置；after-prerun在完成4×C个正式请求后触发。每窗口prefill采4个scheduler step，decode采128个scheduler step，均不是token数。
- 第二窗口名称是预运行后窗口，不宣称检测到了稳态，不要求实际batch等于C。K=5且触发点4C意味着进入尾段；必须记录实际完成数、在途数/已发送数、batch范围及导出干扰。
- PyTorch每次仍询问是否开启原生key_averages（当次已选择除外）：关闭只生成trace/摘要，可离线分析；开启只在profiler对象尚存时计算一次、复用CPU/CUDA排序表，可能显著增加内存和耗时。离线统计不能声称等同原生聚合。两种选择都给当前工程耗时估计。
- 预计任一步超过5分钟，先让用户选择AI接管或人工唤醒。AI接管首次及后续计划检查等待均最多15分钟，每次检查一轮；正常则再等待最多15分钟，不循环轮询。人工方式不主动检查。均保存PID、日志、退出码和run标识。

## 一个请求流、两个采集窗口

1. 读取benchmark Skill并完成离线数据/挂载/依赖检查。tokenizer固定为已挂载本地MODEL_PATH，模型配置亦从本地读取。缺文件/依赖、隐式下载或网络失败时报告并询问，不自行换数据、安装或下载。
2. 默认不加载hook（PROFILE_HOOK_ENABLED=0，不加入profiling_hooks的PYTHONPATH）。PD直接对prefill端点传num_steps=4、decode端点传128，使用原生profile_by_stage计数。当前SGLang单服务原生接口只有一个公共num_steps，P4/D128组合须先询问专用适配；获批后仅单服务设置PROFILE_SINGLE_STAGE_ADAPTER_APPROVED=1，并在客户端显式传--single-stage-adapter。基础单服务模板包含隔离的目标计数与采集状态控制：每窗口先等待prefill采到目标，再采decode，避免阶段交错覆盖活动采集器；仅改变采集，不改变模型调度。入口二次读取配置后须保留显式获准的运行开关。该实现已有对应版本单服务PyTorch双窗口验收案例，但新框架版本仍须重验；不能由此宣称Nsys捕获已验证。未批准时在请求前拒绝，PD不加载单服务hook。原生key_averages若无已验证实现，同样先报告限制并询问，不自动启用适配。
3. 预热2个请求并等它们结束。之后一次启动N=5C正式请求的闭环worker池，最多C个在途请求，完成即补充；不把两窗口拆成四轮负载，也不把预热纳入4C计数。
4. initial窗口在首次正式请求前布置。PD直接向各角色实际endpoint发控制请求，可分别设置stage目标，不依赖benchmark CLI互斥的角色参数；单服务只有在已验证的原生能力或用户明确批准的适配支持时才执行，不能静默改变P4/D128。
5. 当正式请求完成数首次达到4C时，安排第二窗口。先确认/结束第一窗口并等待其导出，再重新布置after-prerun；切换控制期间暂停补充新请求，但不取消已在途请求。记录阈值到实际启动的延迟和实际完成数，不能伪称严格在4C时刻开始。
6. 两个窗口都采用相同P4/D128目标。step属于整个角色的调度计数，不保证属于同一请求；输入短时单请求可能仅2chunk，后续请求可补足，但切换/工作结束后仍不足目标就标记窗口不足，禁止无限等待、自动增加N或称完整覆盖全部输入。
7. 正式请求结束后显式stop/finalize，保证未达到自动停止边界的短窗口也可导出、留下不足证据。控制失败、请求失败或窗口不足均如实报告并询问，不偷偷重跑或扩充预算。
8. Profiler导出会干扰请求执行；两组trace用于对比初始与预运行后短窗口，workload延迟不作为普通benchmark性能结果。CPU栈、活动类型等改变需说明，不能静默用删rank/删事件掩盖文件量。

PD细节见 [references/pd-disaggregation.md](pd-disaggregation.md)。模板位于 `../scripts/templates/inference-project/` 和 `../scripts/templates/inference-project-pd/`。

### 单服务与PD实现隔离

- 单服务专用修复不得覆盖已验证的PD实现。优先保留独立模板/适配模块和显式拓扑开关；确需共享工具时按能力分支，并测试未选中分支行为不变。普通benchmark实现不随profiling修复修改。
- 修复前记录PD关键入口、控制器及benchmark文件摘要；修复后比对，并运行单服务/PD分支回归。分支单测通过不等于GPU实跑通过，交付中分别说明。
- 检查完整入口链而非只调用适配函数：下一级脚本重新读取配置可能覆盖已导出的开关。用实际入口和最终子进程环境证明适配生效；默认普通服务及PD不得意外加载单服务适配。
- 单服务窗口重入可能先遇到decode，prefill/decode也可能交错。适配需验证不会覆盖活动采集器、不会按错误阶段导出，并按实际阶段step验收P/D各自目标。仅修改初始化目标的方案未经真实窗口验证不能宣称可用；若需要扩展采集状态控制，先报告并获授权，只改变采集控制，不改变模型调度或请求预算。
- 具体修复先在实际工程验证，确认成功后再同步对应单服务模板与示例；失败时保留日志和不完整产物，不改阈值掩盖问题，不将未经验证的实现写成通用解决方案。
- Linux容器Nsys启动前执行单服务模板的`server/nsys_preflight.sh`，确认sysfs中的CPU拓扑online/possible/present可读且非空，失败即在加载模型前退出。单服务模板`server.sh nsys`仅准备容器并增加Linux sysfs只读挂载；之后在容器内启动Nsys服务。其他启动器须在其自身配置中等价处理，不能以privileged替代，也不改PD或benchmark。若出现等待capture range或Importer错误，同时核对真实CUDA控制调用与采集容器的拓扑可见性；用户批准后才重建本实验容器。只读sysfs已在小型探针验证的修复不等于完整模型采集成功，仍须验收正式报告。

## 验收

离线验收/分析不要求与采集处于同一容器，可使用用户明确指定的获准环境；先检查工具兼容性及报告访问。缺少任何依赖或工具时遵循总Skill的先询问规则，不自动安装。工具要求专用解释器而用户指定其他环境时，明确冲突并等待选择，不静默切换。

- 唯一远端run隔离旧产物；服务升级/重建只处理可追溯的本实验对象，保留原始文件和其他任务。
- 无hook时窗口摘要由validate_native_windows.py从导出的原生step spans流式生成，并校验gzip及SHA256；这是窗口验收，不是算子聚合。逐phase/role/rank核对实际步数、batch与非空trace，不能根据num_steps配置伪造实测。原生stop_profile在已自动停止后可能500；通用500只能记录未确认，必须结合完整trace和服务日志消除歧义。
- 同时核对请求总量、成功数、预热数和正式退出状态。只看到HTTP200或complete字段不能代替完整验收。
- 单服务阶段切换/混合调度可能使某阶段不足目标，必须从实际摘要判断，不以配置值当实测。
- Nsys必须保留原始.nsys-rep。重复CUDA capture range生成多个报告时按实际范围顺序/时间映射窗口，不凭文件名猜测；未验证两窗口报告映射时不得声称已支持或完成。不自动为获得报告终止模型服务。
- Nsys启动前检查当前框架的step/stage标记是否真正发射NVTX：torch record_function标签不等于Nsys NVTX标签，CUDA_PROFILER活动也不自动开启torch.profiler。若报告不能直接逐step核验，先报告证据边界，让用户选择依赖原生控制与日志的窗口证据，或批准仅标记阶段/step的最小适配；不得自行开启完整PyTorch算子NVTX、同时采集两种Profiler、安装包或改框架。
- 支持report-ready回调的Nsys版本可用模板nsys_report_ready.sh记录报告完成时刻与原始报告路径，再结合workload控制事件和报告内阶段证据核对窗口。PD每角色预期两个范围，单服务可能每窗口生成两个阶段报告；不能把完成顺序直接当成阶段标签或忽略不足窗口。回调记录是原始报告索引，不是性能分析。
- 所有参与主机核心文件回收至本地，数量、大小和SHA-256一致后才称交付完成。
- 已通过源主机验收的原生PD结果可使用`../scripts/collect_profiler_results.py`回收：显式传实验目录、run、C、远端工程路径、配置中的SSH目标和TP数；调优补采还传--result-owner tuning/<study>/baseline或tuning/<study>/candidates/<id>，普通采集省略。工具不推断SSH路由/版本，不迁移旧结果；暂存SHA验收通过后仅替换所属版本的同C结果，失败保留旧结果。

## 本地核心结构

以下结构相对于“结果所属版本”：普通实验为实验根；调优为tuning/<study>/baseline或candidates/<id>。单服务和PD一致；用户仅留远端时用同样归属索引源run，不把路径示意当已下载完成。

```text
profiling_results/
|-- profiler/                         # PyTorch结果
|   `-- C<C>/                        # 如C1、C16
|       |-- MANIFEST.md               # run与来源、命令、校验
|       |-- workload.json             # 请求量和窗口触发证据
|       |-- initial/                  # 初始窗口
|       |   |-- prefill/              # Prefill阶段，单服务与PD统一
|       |   `-- decode/
|       `-- after-prerun/             # 完成4×C请求后触发
|           |-- prefill/
|           `-- decode/
|-- nsys/                             # 同样按C和窗口组织
`-- ANALYSIS.md                       # 按用户分析口令更新
```

- 单服务与PD统一目录：每个initial/after-prerun下都建立prefill/和decode/，分别保存TP-<rank>.trace.json.gz和对应window摘要。目录表示计算阶段，不要求来自不同机器；单服务两阶段可来自同一服务/主机。远端原生混合目录在回收时按trace阶段后缀拆分，不在本地交付single/层。
- PD各角色目录保存`TP-<rank>.trace.json.gz`及对应窗口摘要；只有启用聚合才保留原生表。
- Nsys同层保存实际.nsys-rep及必要窗口元数据，CSV/SQLite/stats不是GUI主报告。
- 同一C复跑：在独立暂存目录校验新结果，明确旧目录范围后替换该C结果，不混入旧文件；不删除其他C、另一工具或远端原始结果。失败的新结果不得覆盖旧的合格结果。
- 最终只保留核心trace/报告、摘要、workload、manifest及启用的原生表；清理可重建临时副本，不暴露主机/server/profiles/时间戳多层嵌套。

## 报告与完成回复

用户要求分析时，按 `../references/analysis-report.md` 组织ANALYSIS：范围/核心文件、读图与thread/stream说明、现象→分析→结论表、最终瓶颈判断与优化验证建议。Nsys证据仍使用内置官方Skill；不修改其规则，不用长段文字代替可查阅的结论表。

调优版分析写在所属版本的profiling_results/ANALYSIS.md，本轮报告链接该分析；实验根原始ANALYSIS仅保留索引，不混写不同版本的时间线或性能结论。

Profiler和Nsys分析都须给出具体配置/框架/算子优化候选：证据、目标模块/参数、拟改逻辑与风险、正确性和benchmark验收指标；SGLang配置结合当前版本官方调优指南。只分析不执行改动；用户授权自动调优时转`../references/autotuning.md`，默认三层联合一个候选，chat后做同条件benchmark基线对比，不默认分三轮benchmark或每次重采两种Profiling。

采集方法/验收与必要结果更新到统一`<title>.md`的Profiling章，PyTorch与Nsys为子节；按`../references/delivery-report.md`完整给控制器/适配/callback/验收源码，再给实际调用，不只附关键片段。详细thread/stream分析仍写所属版本ANALYSIS，不挤入正文；不写连接上传、停止收尾等操作流水。

完成回复解释C、固定K5/N、预热2、ISL/OSL、两窗口目标/实际起点、P4/D128实际步数、batch范围和全部rank验收。列出Perfetto可打开的核心文件准确本地路径；Nsys列GUI报告。给出ANALYSIS路径及“尚未分析/已更新”状态；不自动分析。对比原估计与实际耗时，后续分析/补采等选项分别给出估计。未完成/窗口不足不能宣告全部成功。
