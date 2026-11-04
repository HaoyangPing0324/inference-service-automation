# 项目结构与验收

## 路径和标题

目录：`<WORKSPACE>/<hardware>/<model>/<framework>/<deployment>/`。先确认四项身份并建立目录，在该目录内创建独立 `environment.toml` 供用户填写；配置所在目录即实验目录，不再嵌套另一份四级路径。

标题：`<hardware>_<model>_<framework>_<deployment>`

所有片段使用小写字母、数字、点和连字符；标题仅用下划线连接四个片段。

## 远端真源与本地交付

本地四级目录是用户交付区；远端workspace_dir/title是实际执行工程。多机明确一个本实验源节点/冻结版本，design直接编辑并只向其他实际角色同步必要文件；不要在本地建立活动源码树。已有本地完整旧工程不自动删除/搬移，既有远端结果也不自动重排；新产生的交付遵循本节。

| 本地内容 | 何时保留 | 用途 |
|---|---|---|
| environment.toml | 初始化即有 | 用户环境/身份、候选SSH与远端路径，不放凭据 |
| experiment.toml | 远端当前设计发布后 | 用户可编辑的设计参数；显式应用后由design更新远端新版本 |
| <title>.md | 已开展阶段实时更新 | 单个Markdown即可复现，完整实际命令/自定义源码及结果 |
| profiling_results/{profiler,nsys}/C<C>/ | 用户要求相应采集后 | 本次原生结果/必要控制证据与MANIFEST；time为capture，PD按角色，原始深层目录可归档入同C的raw/ |
| profiling_results/ANALYSIS.md | 用户要求分析后 | 实测分析及限制；普通部署不生成空分析文件 |
| tuning/<study>/ | 实际获准优化后 | 必要轮次报告、各版本可编辑experiment.toml、本轮实际修改/新增源码与修改说明，以及已要求的采集/分析；原始压测数据及构建树留远端 |

本地示意（只建立确实产生的条目）：

```text
<LOCAL_EXPERIMENT>/
├── environment.toml
├── experiment.toml
├── <title>.md
├── profiling_results/
│   ├── profiler/C<C>/capture/        # 需要时同C另有raw/原生目录归档
│   ├── nsys/C<C>/capture/
│   └── ANALYSIS.md                  # 仅已授权分析
└── tuning/<study>/                  # 参数、实际改动源码、修改说明及必要报告
```

- 不默认建立本地results/或单独的交付索引。压测指标、负载及必要结论直接完整写入<title>.md；原始benchmark JSON/JSONL、逐请求数据和计算中间文件留在远端，只有用户明确索取或指定本地复算时才回收。采集产物自带的必要元数据随原生产物保存，不额外生成顶层交付清单。
- 默认不回收server/、client/运行脚本树、experiment.env、LOG.md、coordination/、bootstrap/、中转文件、调度状态、失败重试日志、编译缓存、二进制库、权重、镜像或框架仓库。它们保留远端，需要特殊交付时另行明确范围。诊断包只在用户明确需要时按指定位置单独回收，不预设额外本地目录。
- 原生采集产物中的日志、数据库/统计、设备数据和目录结构属于必要原始结果，不能以“本地干净”为由裁掉。本次原生目录完整回收，不能顺带复制跨轮历史目录；大型/深层产物可原样归档，文件名和结构保持。
- 必要baseline/candidate设计表保留在对应study/version；普通运行只在本地根保留当前experiment.toml，不每次查询生成一份副本。完整执行工程、活动冻结版本与未改动源码留远端，本轮实际改动源码另作本地审阅副本，报告给可复现定义，必要采集元数据记录精确版本。
- 本地设计表是用户修改入口，远端design维护当前已部署版本；两者必须注明当前状态。用户明确应用后对比变化并同步，不双向自动覆盖、不热改正在跑的配置。应用成功后回收新的设计表/报告；未应用的用户编辑不得被后台回收覆盖。
- 只回收已封存产物，先在本地受控暂存区校验后发布，交付根不遗留半包、散装目录示意或临时副本；断线保留可续传临时包但不当有效结果。不删除源数据或已有用户文件。已有非白名单文件是否清理须单独决定，不能借本规则删历史工程。
- 正式报告由design在远端维护；analyze交必要指标与结论，经二级汇总后design写入。父Agent只读摘要，不要求它们重开原始文件核验。大型结果可按用户明确要求仅留远端，此时在正式报告相关结果处简短注明远端位置，不伪称本地已有。

### 优化源码的本地审阅副本

仅实际修改框架/算子后回收，不为普通部署创建空source目录。单个候选默认放在tuning/<study>/source/framework/和source/operators/，按该源工程相对层级保存完整的实际改动文件；新增依赖实现一并保留，只收修改或新增的那几份文件，不复制整个框架、未改动文件、基线全树、运行脚本、缓存或编译产物。

同轮多个候选使用candidates/<candidate-id>/{experiment.toml,source/,修改说明.md}隔离，不覆盖或混合候选；各目录对应同一个已验收冻结版本。单候选的布局为：

```text
tuning/<study>/
├── experiment.toml
├── baseline/source/                # 仅被替换文件的真实原件，同名同层级
├── source/
│   ├── framework/                   # 实际修改的框架文件，保留内部相对层级
│   └── operators/                   # 实际修改/新增的算子文件
├── 修改说明.md                     # 改动、原因、原版本、远端映射、验证边界
└── AUTOTUNING_REPORT.md             # 已实际开展的轮次结果
```

修改说明只解释本轮改动及必要版本/适用范围，链接已有结果而不重复写压测表，不是新增交付索引。完整修改文件必须与实际执行版本一致，报告中的自定义源码/确定性补丁仍完整展开，不以本地附件替代单文档复现。用户只要求源码替换、未运行性能优化时，也可使用一个命名study交付实际修改与说明，但不得虚构优化收益或空结果报告。

源码在远端由design编辑、execute验证，design再回收冻结审阅副本。本地文件供阅读/修改，用户明确要求应用后才对比并同步到远端新版本；不自动覆盖活动版本。多机相同文件只回收一次，不同角色真实差异须在说明中对应清楚。

## 远端工程结构（随实际阶段生成）

本地工作区根部另有 `servers.toml`，集中保存各硬件及候选服务器；它不是实验运行配置。新实验从选中条目复制服务器快照，已有实验不自动跟随清单更新。清单模板位于规范根同名文件；不得把当前工作区真实环境写进模板。

```text
<deployment>/
|-- environment.toml
|-- experiment.toml
|-- experiment.env
|-- tuning/                         # 优化实验与报告归档
|   |-- README.md                   # 历次优化索引
|   |-- templates/                  # 计划/报告骨架
|   `-- <study-id>/                 # 本轮计划、分析、报告、baseline和candidates
|-- benchmark_test.sh
|-- client.sh
|-- <title>.md                     # 唯一正式交付报告
|-- LOG.md
|-- server.sh
|-- run_source_variant.sh
|-- client/
|   |-- analyze_torch_trace.py
|   |-- chat_test.sh
|   |-- check_profile_window.py
|   |-- parse_bench_result.py
|   |-- profile_capture.sh
|   `-- profile_workload.sh
|-- profiling_results/
|   `-- ANALYSIS.md
`-- server/
    |-- nsys_service.sh
    |-- nsys_stats.sh
    |-- profile_service.sh
    |-- service.sh
    |-- source_overrides/             # 框架/算子隔离替换，默认不启用
    |   |-- manifest.env
    |   |-- load.sh
    |   |-- baseline/
    |   |   |-- framework/            # 仅本次涉及的框架原文件
    |   |   `-- operators/            # 仅本次涉及的算子原文件
    |   |-- framework/
    |   `-- operators/
    `-- profiling_hooks/
        |-- <model-family>_decode_window.py
        `-- sitecustomize.py
```

time结果为profiling_results/{profiler,nsys}/C<C>/capture/{single或prefill、decode}/；历史steps结果保留原initial/after-prerun布局，旧结果不伪造迁移验收。

以上是远端执行工程结构，不是本地交付必需文件树；tuning、source_overrides等仅在相应阶段确实需要时建立。普通实验不创建空优化目录。调优补采的同样结构属于tuning/<study>/baseline/或candidates/<id>/，分析也写该版本profiling_results/ANALYSIS.md；新轮次独立study，已有原始根结果不迁移。基线/候选配置与源run归属按autotuning.md核对，不以C相同为由覆盖另一版本。

## 实验记录

`LOG.md`是实验决策与验证摘要，不是终端流水或操作审计；`FOLLOWUP.md`等接续记录只维护当前状态、未完成事项和恢复所需信息。

- **保留**：实验身份/版本与配置快照、改变设计的原因、重要失败的根因→修复→验证、有效/无效结果边界、核心指标/限制与报告或原始证据位置。每条应回答“这会影响什么决定或避免什么重复错误”。同一结果只保留一次，详细指标与完整复现命令引用正式报告。
- **不记**：正常SSH连接/上传/chmod、无变化的资源查询或轮询、临时PID与工具会话、每次进度百分比、转义/拼写重试、已修复的一次性工具噪声、逐个停止/删除容器过程及反复“未重启/未改参数”。若这些导致实验无效或有长期影响，记录最终原因和影响即可。
- 资源查询默认只在对话汇报，不写项目日志；阻塞部署的资源冲突、安全授权边界或持续故障保留必要证据。暂停/清理仅更新“项目已停止、文件保留”的当前状态，不展开操作清单。活动后台任务确需接管时，PID/日志入口/退出状态只放接续记录，完成后移除失效入口。
- 按关键里程碑及时更新，不等待最后凭记忆补写，也不要求每个动作追加。允许合并重复段落、删除过时待办并压缩噪声；不得修改历史测量数字、掩盖失败或把未确认原因写成已解决。大量整理前保留可恢复副本于工作区外，避免工程内不断生成备份日志。
- 接续记录用“当前状态→未完成/下一步→核心入口”短结构；无活动任务就明确写无，不保留逐次检查历史和相互矛盾的旧指令。LOG不再复制一份接续时间线。
- 多agent为主任务让路且确需持久化时，仅在被暂停实验工程的`coordination/<task-id>/<role>.md`维护最新几行断点，按[中断接续规则](../multi-agent/task-pipeline.md)记录标识、让路原因、已完成、下一步和现场；不把队列或暂停消息流水复制进LOG。二级调度必要状态只按需维护在归属远端实验coordination/<session>/<hardware>/；原生Agent状态足够时不落盘，不复制本地，不在工作区根生成调度目录。
- 本规则仅针对AI维护的Markdown记录；程序原始`.log`、JSON/JSONL、trace、报告、MANIFEST、SHA和用户编辑的对话文档不因整理日志而删除或改写。官方附属Skill不修改。不写凭据。

## 中间文件边界

本节指远端实验根，只放当前实际需要的入口：`environment.toml`、`experiment.toml`、`experiment.env`、`<title>.md`、`LOG.md`及模板规定的启动/压测脚本。AI自用的官方依据摘录、预检快照、报告准备清单、临时补丁、交接状态和诊断输出统一放在该实验的`coordination/`下，并按`research/`、`preflight/`、`report/`、`handoff/`分组；原始测量结果仍放`profiling_results/`，可复现的正式部署证据可留`deployment/`。工作区根不得生成调度目录或散落实验文件。

每个新文件在创建前先判断：用户交付、可复现证据、恢复任务三者均不是时，不落盘；能写入现有LOG、ANALYSIS或manifest时不再造同义Markdown。`OFFICIAL_DESIGN.md`、`PREFLIGHT.md`、`REPORT_READINESS.md`这类AI辅助文件若确有内容，分别归入`coordination/research/`、`coordination/preflight/`、`coordination/report/`；一次性清单不用永久保留。对既有文件先核对引用和内容后提出迁移/合并，不盲目删除原始证据。

## 验收检查

- 每轮调优报告含逐档主目标/平均与尾延迟对比表、目标下的总体好坏/代价、配置框架算子原预期对照实测与归因限制、下一轮具体假设/改法/对照/判读/风险/估时。未消融不分摊收益，未量化预期不事后倒填；报告中的下一轮建议不自动授权执行。
- 每轮调优先有可独立阅读的`tuning/<study-id>/AUTOTUNING_PLAN.md`，含三层具体改法/不变项、证据风险、验收顺序、阶段状态及相对上一轮的变化；索引和原始分析能链接到计划。每版压测语义验收后立即更新统一正式报告实际数据/展开命令/成功与token数/耗时/结果位置，并同步计划、报告和LOG；汇报完成前核对已落盘且状态一致，不延迟到整轮结束。
- 自动调优遵循autotuning.md：分析提出具体建议，配置/框架/算子形成一个联合候选，通过正确性和chat_test后执行一套候选benchmark，与可比基线对比。无基线先确认补测成本；不改变普通benchmark协议。分析请求本身不授权调优。
- benchmark_test.sh默认/full保留完整CONCURRENCIES（首次基线1/2/4/8/16/32）；tuning仅本次选1/8/32，不改完整配置。每档请求数、预热、数据和seed协议不变，候选逐档与完整基线相同C比较；调优报告明确未复测档位。

- ANALYSIS.md按 `analysis-report.md` 说明各图/主要线程和stream的实际含义，以现象/分析/结论表组织证据，并以瓶颈判断和有验证指标的优化建议收尾；没有原始结果时不填写实测结论。

- 每个实验有独立 `environment.toml`，文件内身份与目录末四级一致；工作区根目录和 Skill 模板不作为共享运行配置。生成时保留已有环境表、用户设计表和日志。
- 所有 shell 文件使用 `set -euo pipefail`，引用数组时使用 `"${ARRAY[@]}"`，不使用 `eval`。
- 所有 Python 文件使用 UTF-8，命令行输入有校验，失败返回非零状态。
- `experiment.toml` 必须存在并作为用户设计参数真源；只包含有调优意义的设计项，不含 IP、端口、SSH、容器名、路径、设备编号或进程信息。`experiment.env` 必须由设计表、精确官方命令和必要运行适配生成，本次启动需用的SERVICE_CMD、SERVICE_ARGS和容器参数已填充；benchmark/采集字段只在对应阶段使用前填充。两者当前生效的重叠字段一致。
- 正式设计表按当前阶段记录显式配置和已知生效值；首次不穷举内部默认参数，未覆盖项沿用框架解析。按configuration.md随运行日志或调优需求补齐，不为完整填表延迟启动。
- Profiler/Nsys默认只采一个中间time窗口：预热2后持续最多C个在途，完成4×C正式请求后采capture_seconds（默认15秒），停止采集后继续完成至少C请求再结束负载；不固定N=5C，不采initial/after-prerun。可选最短预运行时间默认0秒。P/D步数仅事后统计，max_requests触顶即失败；single保留混合trace，PD并发控制P/D端点，默认不采Router GPU。
- 首轮配置明确为无 prefix cache；禁用参数或“默认即关闭”的证据已记录。
- 即使官方配置启用了 prefix cache，首轮也只覆盖这一项；官方原始命令与差异证据保存在工程，正式报告给完整实际命令，用必要代码注释标出该偏差，不堆来源核验流水。
- 唯一正式报告`<title>.md`按[delivery-report.md](delivery-report.md)组织，按启动服务/Baseline压测/Profiling/已开展优化轮次分章；未开展轮次不造章，不能按偶然操作时间排序。
- 正式报告包含完整实际命令与自定义源码，不以其他工程文件或未定义脚本补齐；文件完整内容与调用分开，源码等价/补丁摘要/结果表须核对。只写必要说明、结果和简短分析；详细ANALYSIS、轮次计划/报告与重要失败LOG仍单独维护，不能一并删除。
- 文件路径和容器挂载相互一致；server/client 容器都能读取 `/experiment.env`。
- 所有实际服务、测试和profiling命令都由容器内脚本执行；design远端编辑/同步后、execute运行前确保相关sh可执行。
- `chat_test.sh` 与健康探活分离；其 endpoint、输入编码、提示词和采样参数可追溯到精确官方示例，或在官方未提供时追溯到对应 example。脚本校验 HTTP 状态、模型名、非空生成内容和响应结构，不用自造的固定字符串指令代替参考问答，也不把未编码 completion 的随机续写算作 chat test 通过。
- 远端指定源节点的冻结版本是源码真源，参与角色只同步必要的同版本文件；execute成功试修经二级交design固化远端版本。本地无需脚本镜像。
- 默认将所有参与节点核心产物回收到所属版本的profiling_results/并核对数量/大小/SHA；Ascend原生采集还要保留完整原始`profile-output/`于同C的`raw/`（Windows深路径可用tar），详见profiling Skill。用户明确仅留远端时，按其边界验收并在版本目录索引源run，不冒称本地已有。调优不覆盖根结果或其他study/候选。
- 多机结果目录中的主机层表示来源机器，不表示 GPU；`server/` 放服务角色采集文件，`client/` 放 workload 结果。不得在未承载某角色的主机下交付没有 trace/`.nsys-rep` 的影子角色目录；跨机角色映射、参数和验收状态写入 run 级 `MANIFEST.md` 与 `LOG.md`。
- 回收暂存不作为交付目录。time整理到工具/C<C>/capture/下的single或P/D角色目录；混合trace不复制拆成P/D两份。保留来源、SHA、workload及MANIFEST；同C复跑先验新暂存再替换。
- `profiling_results/ANALYSIS.md` 分别维护 PyTorch Profiler、Nsys 和综合瓶颈部分。单项分析只更新对应部分；Nsys 分析遵循 `profiling/nsight-systems/SKILL.md`，不得用 stats CSV 代替 `.nsys-rep` 证据。
- 每阶段给出核心产物和实际方法；Profiler说明实际时间窗口、请求数和阶段覆盖，历史steps则给其实际步数。正式报告完整展开实际命令与自定义源码。
- time配置：PROFILE_PROTOCOL='time'、PROFILE_PRERUN_SECONDS、PROFILE_CAPTURE_SECONDS、PROFILE_MAX_REQUESTS；默认不加载Hook。验收实际控制区间、请求成功数、每rank的GPU活动与阶段覆盖；不强制P4/D128。历史steps字段只在显式旧协议中生效。
- `LOG.md`和接续文件符合上节“实验记录”：保留决策、关键失败与验证、结果入口；不堆日常操作、重复状态或过期待办，不改原始证据。
- 不把示例结果数字复制为新实验结果。
- 源码替换按`source-overrides.md`执行：模板默认baseline，文件映射按实际安装版本生成；framework/operator/combined分别记录验证状态，合并目标冲突在停止容器前拒绝。只读挂载不改变镜像，不引入真实工程的大型源码/二进制副本到Skill。用户未要求时不启用变体，不改普通benchmark。


实际被替换文件的修改前原件也要回收至tuning/<study>/baseline/source/{framework,operators}/，仅保留本轮涉及文件；原文件名和内部相对层级不变，修改版在source/对应位置。多候选共用同一真实基线时只存一份，基线不同则按候选隔离并说明。原件必须在修改前从实际运行版本冻结，不能事后猜造；新增文件没有原件，在修改说明中标为新增，不建空基线文件。
