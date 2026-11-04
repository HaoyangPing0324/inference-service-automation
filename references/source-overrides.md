# 框架源码与算子替换

仅在用户明确要求源码/算子修改时使用；普通部署默认`baseline`，不自动注入覆盖。框架与算子可以组合，但单项通过不代表组合通过。此机制用于同一框架内的代码变体，不代表把一种框架换成另一种框架。

## 目录与配置

单服务和PD模板均生成：

```text
run_source_variant.sh                  # 选择变体，复用原服务入口
server/source_overrides/
├── manifest.env                      # AI维护的角色、文件映射与模块搜索路径
├── load.sh                           # 启动前校验及只读挂载参数生成
├── baseline/                         # 仅保存本次涉及的原实现，不复制整个框架
│   ├── framework/                   # 框架原文件与摘要
│   └── operators/                   # 算子入口/内核原文件与摘要
├── framework/                        # 框架源码变体
└── operators/                        # 算子分派、新内核或兼容构建产物
```

不把某次工程的完整框架源码、安装路径或二进制编译产物内置到模板。旧工程的实验目录可保留历史名称；迁移时修改全部活动引用，不移动原始日志冒充新验证。baseline备份是比对证据；回退依靠不挂载覆盖后的原镜像，不是往镜像写回备份。

两类原文件必须分开存储，不平铺混放；同一类内部保留原包的相对层级以避免同名文件冲突。只备份本次实际修改或替换的原文件，不预先复制全部框架/算子。新写的GPU内核若原安装中没有同名文件，不伪造baseline，记录其替代的原调用入口/实现来源即可。模板只生成目录占位，不自带真实框架源码。

替换数量没有预设名单或固定上限：SOURCES/TARGETS数组可列多对映射，最终以当前版本可读文件、真实调用链、兼容性和已验收清单为准。一个算子可能跨多个文件，一个文件也可能包含多个算子；文件数不等于算子数。完成回复分别列出“修改的原文件数、新增实现文件数、运行时挂载目标数、测试文件数”，不把框架全部文件都宣称已适配。

`manifest.env`是内部运行布线，不是新增用户填表。AI从已确认的目标版本、角色及授权改动生成：

| 字段 | 含义 |
|---|---|
| `OVERRIDE_ROLES` | 仅对明确选中的server/prefill/decode/router角色生效；默认空，须确认 |
| `OVERRIDE_FRAMEWORK_SOURCES/TARGETS` | 相同长度数组，框架文件逐一映射 |
| `OVERRIDE_OPERATOR_SOURCES/TARGETS` | 相同长度数组，算子文件逐一映射 |
| `OVERRIDE_FRAMEWORK_PYTHONPATH` | 相对source_overrides的额外框架模块目录 |
| `OVERRIDE_OPERATOR_PYTHONPATH` | 相对source_overrides的额外算子模块目录 |
| `OVERRIDE_BASE_PYTHONPATH` | 从基线镜像读取并保留的原PYTHONPATH，可确认其本来为空 |
| `OVERRIDE_BASE_PYTHONPATH_CONFIRMED` | 基线搜索路径已核对后设1；未确认不允许覆盖它 |

SOURCES必须是本目录内的相对文件路径；TARGETS由当前容器已安装模块的真实`__file__`/包清单确定，是仅适用于该容器的绝对文件路径，模板不预填专有值。Python模块目录由既有`server`挂载暴露为容器协议目录`/server/source_overrides/`。调用端系统不作假设；Bash入口及`realpath`检查只在已确认的Linux容器宿主机执行。缺工具/依赖仍先询问，不能自动安装。

## 执行与组合

下列命令均在已确认的远端Linux工程目录执行，且须先获得对应服务重启授权：

```bash
# PD：只对manifest选中的角色生效；不要擅自扩大到所有节点
bash run_source_variant.sh framework prefill
bash run_source_variant.sh operator prefill
bash run_source_variant.sh combined prefill
bash run_source_variant.sh baseline prefill

# 单服务基础模板：准备容器并进入shell，之后仍按原流程启动容器内服务
bash run_source_variant.sh combined shell
bash run_source_variant.sh baseline shell
```

单服务模板仍沿用原容器生命周期，不擅自结束已有容器；已有容器冲突时按授权范围停止/删除准确对象再建。生成的普通服务参数保持原值。PD模板先完成覆盖校验，再执行原有生命周期；普通benchmark脚本不变。源码变体不是profiling hook，不应自动开启torch.profiler或Nsys。

可以只替换prefill，也可按用户要求把兼容变体分别部署到decode或router；必须明确每角色修改清单和节点。`combined`合并两类只读文件挂载与模块目录，保留基线PYTHONPATH：

- 文件不重叠且API/版本兼容时可以同时启用。
- 两类覆盖指向相同容器文件时，启动前拒绝，不能让后一个挂载悄悄遮住前一个。先将修改合并为同一版本，并在manifest中只声明一次该目标，再记录归属与重新选择模式；若全部修改已合在一个文件，可按单组模式加载并明确文件同时包含两类改动，不宣称combined会自动合并代码。不得删除某项改动来绕过冲突。
- 路径必须可读、留在source_overrides内部；拒绝缺文件、数组长度不符、未确认角色/搜索路径和路径歧义。只读bind mount遮住该容器原文件，不改写镜像；`ro`不禁止Python读取或执行。
- 文件挂载非热更新保证。Python进程必须重启重新导入；不能只改文件后对旧进程做chat并声称变体生效。

## 可以替换什么

| 类别 | 适用文件/模块 | 必须说明的边界 |
|---|---|---|
| 框架Python源码 | HTTP/API入口、scheduler、tokenizer管理、模型实现、后端分派 | 真实模块和导入路径来自当前安装版本；调度修改另做请求语义回归 |
| Python算子入口 | 将原分派切换到新内核的入口文件 | 只写内核而未改真实调用链不算生效 |
| Triton算子 | RMSNorm及其他用户指定的Triton内核 | 首次调用JIT编译，核对dtype/shape/stride、CUDA Graph和数值误差；不自动保留原实现的PDL等优化 |
| CUDA/C++算子 | 源码及匹配构建后的扩展库 | 不能拿.py/.cu直接代替.so；先在兼容CUDA、PyTorch、ABI和GPU架构下构建，再映射正确产物，必要时用隔离镜像 |

已验证参考是SGLang普通RMSNorm的真实分派替换及HTTP入口修改，两者分别实跑过；不宣称组合实跑或其他算子均通过。vLLM等Python框架可采用相同挂载机制，但本模板不提供其已验证模块清单。TensorRT-LLM及其他含已编译后端的改动按实际构建链处理，不把文件挂载当作自动移植。

GEMM、Attention、RoPE、量化、MoE、融合残差归一化等只是可能的候选，需要用户指定目标并逐项验证，不能列作已实现算子。切换SGLang/vLLM等框架本身须回到实验身份和官方配置流程。

## 验证与报告

1. 先读取实际安装源码，确认模型到分派到内核的调用链、版本、API签名和原文件摘要；只读提取基线，镜像和共享包不原地修改。
2. 算子做预先确定容差的数值测试、dtype/shape/out/stride覆盖；新依赖、编译或缓存清理范围需用户批准。生成源码/扩展仅在本工程隔离目录构建，不删共享缓存。
3. 启动前检查manifest和与原容器参数已有挂载的重叠；从脚本展开完整Docker、环境与最终服务命令。缺目标文件、编译产物、角色或不明兼容性时先问，不擅自重启。
4. 记录实际模块路径/摘要、真实模型调用标记或内核证据。框架响应头只证明HTTP改动，不证明GPU算子替换；算子单测也不证明模型采用新路径。
5. 每种所需模式分别做健康、真实chat及与改动有关的回归。组合模式必须独立验证，不从两个单项成功推导。流程跑通不等于性能或完整精度已验证。
6. 仅当用户明确要求回退baseline时，核对实验挂载/专用搜索路径/标记已移除，真实chat再通过。正常收尾不自动回退、不为证明可回退额外重载；保留基线文件与证据即可。只重建准确授权对象，保留模型、结果和源码。
7. 交付`SOURCE_MODIFICATION_VALIDATION.md`：模块/文件清单、角色、基线/改动后/组合的真实展开命令、编译方式、验证结果与限制、最终运行版本、预计和实际时间。仅在用户要求回退时附回退证明。执行流水写LOG；不只写“运行某个脚本”。未经请求不自动做benchmark或profiling。

## 分析驱动的自动调优

用户要求优化而非仅替换时，转`autotuning.md`：配置、框架、算子按证据组成一个联合候选，设计表/env与源码同步，先正确性及chat再一次候选benchmark。已验证的独立替换方式是执行基础，不强制为三层各跑一轮完整benchmark；组合结果不证明每层独立收益。普通“替换”口令仍不自动扩大为性能测试。

## 编辑与交付位置

design直接在远端实验server/source_overrides的隔离版本编辑，execute现场验证，成功补丁由design在远端固化。本轮实际修改/新增的框架和算子源码按project-contract回收本地tuning/<study>/source/{framework,operators}供审阅，附experiment.toml和修改说明；未改动源码、基线全树及编译产物不回收；最终报告完整给出实际自定义源码/确定性补丁步骤，必要测试结果与设计表按交付白名单回收。不能为了新分工修改正在使用的只读挂载源文件。

实际被替换文件的修改前原件也要回收至tuning/<study>/baseline/source/{framework,operators}/，仅保留本轮涉及文件；原文件名和内部相对层级不变，修改版在source/对应位置。多候选共用同一真实基线时只存一份，基线不同则按候选隔离并说明。原件必须在修改前从实际运行版本冻结，不能事后猜造；新增文件没有原件，在修改说明中标为新增，不建空基线文件。
