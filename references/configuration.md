# 配置约定

## 配置分层

- 工作区 `servers.toml`：用户维护的硬件/候选服务器清单，为新实验提供环境来源，不直接供运行脚本读取。

- 实验目录 `environment.toml`：独立描述当前硬件/模型/框架/方法组合的机器列表和工程路径，不与其他实验共享。Skill 根目录的同名文件仅是初始化模板。
- 实验目录 `experiment.toml`：给用户查看和修改的实验设计表，只保存会改变模型行为、资源规模或性能语义的参数。
- 远端工程目录 `experiment.env`：由 AI 根据设计表、官方命令和必要运行适配生成的内部 Bash 配置，由远端脚本直接 `source`。它不是用户填写表，也不是通用 dotenv；允许使用 Bash 数组保存命令及其参数。

不要在任一文件中保存密码、token 或私钥。

## 首次初始化与填写引导

1. 先确定工作区，读取其 `servers.toml`（不存在则从规范根同名模板创建并引导填写）。用户未指定卡型且无明确选中实验时询问“你打算在什么卡上部署？”；按卡型/厂商匹配清单，多个或无匹配先询问。再确定精确模型、框架、部署方法；不在工作区根目录创建共享的实验environment.toml。
2. 对每个用户确认的组合建立 `<WORKSPACE>/<hardware>/<model>/<framework>/<deployment>/`，在其中放独立 `environment.toml`。身份可由当前请求或明确选中的既有实验确定，不能把旧根级配置自动当作本次身份来源。
3. 可使用 `scripts/create_inference_project.py --init --workspace <workspace> --hardware <confirmed-alias> --model <model> --framework <framework> --deployment <method>` 初始化。生成器从该工作区servers.toml按已确认alias精确取条目，复制其type/alias/operations_command/hosts到实验配置；CLI不做厂商模糊匹配，匹配选择由AI先向用户澄清。清单不存在时兼容手填模式，不能声称已从清单补齐。该操作不搜索教程、不连接远端、不生成服务脚手架；不依赖调用端特定shell。
4. 已有文件绝不覆盖。向用户逐份提供可点击绝对路径和组合说明，让用户填写其余空字符串、多机时复制完整 `[[server.hosts]]` 段，不写凭据，不填设备数量或并行参数。
5. 用户填完后解析 TOML，核对必填项与目录末四级是否等于 `server.alias`、`project.model_name`、`project.framework`、`project.deployment`。错误时修正同一文件；配置完整后才搜索教程、资源预检及生成脚手架。
6. 多实验从各自选中的清单条目初始化独立快照，分别校验、记录状态；清单后续更新不覆盖已有实验。用户明确要求刷新时先展示差异、获确认后更新实验，不让运行脚本动态读取清单。批量范围按用户确认的组合清单建立，不自动扩展全部排列组合。
7. 既有根级/外部配置只作为迁移来源，不再直接执行。先说明新实验内目标、冲突和影响；用户确认迁移后复制并核对，保留原文件，禁止静默搬移或覆盖。已有完整实验目录也不自动重生成或迁移。

规范根目录中的 `environment.toml` 是初始化模板，不是兜底运行配置。不得因工程配置缺失而直接拿模板中的空值执行。

## 工作区 servers.toml

多条硬件记录必须用数组表，不能重复定义普通 `[server]`：

```toml
version = 1

[[servers]]
type = "Example GPU A"
alias = "gpu-a"
operations_command = "nvidia-smi"

[[servers.hosts]]
name = "node-a1"
address = "gpu-a-node-1"

[[servers.hosts]]
name = "node-a2"
address = "gpu-a-node-2"

[[servers]]
type = "Example GPU B"
alias = "gpu-b"
operations_command = "nvidia-smi"

[[servers.hosts]]
name = "node-b1"
address = "gpu-b-node-1"
```

每个alias在工作区唯一，每条记录内host name唯一；address原样交给SSH配置，不推断直连/跳板。候选机器不等于最终全部使用，不填写设备数量。清单不保存凭据、模型设计或实验方法；工程目录和模型路径仍在实验environment.toml填写。不得把本机真实清单复制进通用Skill模板。

## environment.toml

必填字段：

- `server.type`：硬件平台，例如 `NVIDIA H20`、`Huawei Ascend 910C`；不要在这里预设机器数或卡数。
- `server.alias`：目录名使用的短别名，例如 `910c`、`h20`。
- `server.operations_command`：只读设备状态命令，例如 `npu-smi info` 或 `nvidia-smi`。
- `server.hosts[].name`：机器的逻辑名。
- `server.hosts[].address`：传给 `ssh` 的目标；通常与已配置 SSH 别名一致。
- `project.workspace_dir`：远端工程根目录。
- `project.host_models_dir`：宿主机模型根目录。
- `project.model_path`：容器内完整模型目录。
- `project.model_name`、`project.framework`、`project.deployment`。

所有必填字符串都必须填写；空字符串表示尚未配置，不是默认值，不得带着空值执行远端任务。

以下值由流程推导，不让用户填写：

- 容器模型根目录固定为 `/models`。生成的容器参数把 `project.host_models_dir` 映射到 `/models`，`project.model_path` 因此必须等于 `/models` 或位于 `/models/` 下。
- 本地交付目录是environment.toml所在四级目录，只放环境表、可编辑设计表、正式报告和必要结果；远端workspace_dir/title是执行工程与脚本真源。不要在本地再生成脚本树或嵌套四级路径。

新配置不得包含 `project.container_models_dir` 或 `project.output_root`。生成器仅兼容旧模板遗留的空值以及 `container_models_dir = "/models"`；冲突的非空值会报错，避免静默使用错误挂载或输出位置。

### 多机 `server.hosts` 写法

每台物理机使用一组完整的 `[[server.hosts]]`，不要在同一组里写多个 `name` 或 `address`：

```toml
[[server.hosts]]
name = "gpu01"
address = "gpu-node-01"

[[server.hosts]]
name = "gpu02"
address = "gpu-node-02"
```

- `name`：当前实验内唯一的逻辑名称，只用于生成文档、日志和资源分配表；建议使用简短的 ASCII 名称，如 `gpu01`、`prefill-01`、`decode-01`。
- `address`：交给 `ssh` 的目标字符串，通常是用户 SSH 配置中的主机别名。该别名可以代表直连、单级跳板或由 `ProxyJump` 等机制配置的多级跳板；Skill 把它视为不透明值，不自行增删跳板。不要把整条 SSH 命令写进来。

这些条目是候选机器清单，不承诺全部用于本次实验。有精确教程时依教程确定机器数、角色与设备；无精确教程时按[迁移部署规则](reference-migration.md)形成候选并在授权范围内直接试跑。若候选机器不够，再向用户报告缺口。

所有 `name` 必须互不重复。主机顺序按部署拓扑填写；如果框架区分 prefill/decode 等角色，可在 `name` 中体现角色，但实际角色与设备映射仍以随后生成的 `experiment.env` 和资源分配表为准。

## experiment.toml

远端设计表随当前阶段维护，发布后回收本地可编辑副本；不为完整填表阻塞启动：

- 已存在时，校验后按其中参数部署；不得用模板或官方默认静默覆盖用户值。
- 不存在时优先依据精确检查点和当前框架/部署方式的官方配置生成；没有完全匹配教程时，按迁移部署规则依据模型结构、目标平台官方要求和同类部署形成可试跑候选；先生成当前启动必要项，直接启动后按需回填生效值，不穷举默认值或逐项等待用户批准。
- 用户修改本地设计表并明确应用后，由design对比并更新远端设计与experiment.env；冻结当前运行快照，执行新版本前校验重叠字段一致，不静默覆盖任一侧用户值。

设计表随阶段维护，仅记录本阶段实际使用或已明确要调整的内容，可涉及：检查点格式与量化、推理/attention/MoE backend、TP/DP/EP/PP 和角色规模、总设备数、prefix cache、KV cache、chunked prefill、speculative/draft model、显存利用比例、上下文/批处理/调度限制，以及 benchmark/profiling 的语义参数。只保留当前实验真实使用或允许用户调整的项，不机械罗列无关框架选项。

设计表不得包含 IP、端口、SSH 目标、跳板、容器名、宿主机/容器路径、设备编号、PID 或临时目录。这些是运行布线或现场状态，不是实验设计参数，保留在 `environment.toml`、内部 `experiment.env` 或 `LOG.md`。

### 按阶段记录设计参数

- 部署先写用户给定值、参考命令的显式参数、当前最小启动所需的模型/并行/cache配置；框架未显式覆盖的项保持默认或auto，不扫描全部CLI/源码穷举默认值，不要求每个可调参数都出现。
- 当前阶段不用的benchmark、采集、优化参数不提前核实或填数。运行协议不得把未开展阶段的模板占位当启动失败；只校验本阶段实际调用到的命令、文件和配置。
- 实际镜像版本、后端与解析后的默认值，在启动日志/配置输出已提供时按需回填；尚未知但不影响本次启动的项省略，不虚构具体数值、不为补表重复启动。
- 首次仍保持参考命令和用户固定设置，框架自动识别优先，不擅自强制量化/backend。错误出现后在已授权范围修正，记录有意义的旧值→新值→验证结果；涉及用户意图变化再问。
- 用户要求完整设计审阅或进入具体调优时，才核实本次会修改/比较的参数及来源；已知值保留准确类型和简短注释，不把其他版本/example的数字当成本次实测。

### 用户设计表的生成样式

- 按语义分为 runtime、model、parallelism、cache、speculative、memory、workload、profiling 等 section；只增加当前拓扑需要的 section，段落之间空一行。
- 每个 section 内将键名、等号、值和行尾 `#` 注释按列对齐；使用空格补齐 tab 式列宽，避免编辑器 tab 宽度差异。值较长时只扩展当前 section，不让整份文件形成过宽空列。
- 每个配置项都附简短中文行尾注释，说明用途、单位或关键取值；复杂限制放在段前，避免每行重复长说明。数值、布尔值保持 TOML 原生类型。
- 文件开头简要说明：这是用户设计表；修改后由 AI 同步内部 `experiment.env` 并校验，按需重启或重跑。未实现自动转换时，不能声称只改 TOML 就会自动生效。
- 按“按阶段记录设计参数”填写已知值；未覆盖项由框架解析，不为填表阻塞启动。
- 生成及格式调整后解析 TOML；只改排版/注释时，比较修改前后的解析结果，确保键、值和类型完全不变。模板、参考示例与实际工程采用相同样式。

## experiment.env

`experiment.env` 及本节 Bash 数组属于远端 Linux/容器运行协议，不代表调用端必须是 Linux，也不能据此选择调用端文件操作命令。

它是每个实验必须生成并随工程交付的内部执行配置：

- 先读取并校验 `experiment.toml`；再将设计字段映射到当前框架的准确 CLI/环境变量，并补齐路径、端口、设备编号、容器名和挂载等运行字段。
- 所有部署、benchmark 与 profiling 脚本都读取 `experiment.env`，但其中与设计表重叠的值必须来自设计表。不得绕开两层配置临时拼接另一套参数。
- 设计表与官方依据冲突并且用户未明确要求覆盖时，展示差异并询问；不得把冲突值伪装成官方默认。
- 部署完成回复给用户的是 `experiment.toml` 路径和设计摘要；`experiment.env` 只在排错、复现运行协议或用户明确要求时列出。

生成项目后，按官方教程填充以下组：

- 元数据和路径：`PROJECT_TITLE`、`REMOTE_PROJECT_DIR`、`MODEL_PATH`、`HOST_MODELS_DIR`、`CONTAINER_MODELS_DIR`。
- 远端目标：`AVAILABLE_SSH_TARGETS` 来自候选机器；`SSH_TARGETS`、`OFFICIAL_NODE_COUNT`、`HOST_DEVICE_COUNTS`、`DEVICE_COUNT` 和各并行参数由官方教程与实际分配共同填写。
- 容器：`CONTAINER_CLI`、镜像、容器名、server/client 参数数组。
- 服务：`SERVICE_CMD` 和 `SERVICE_ARGS`。所有教程中显式出现的服务参数都放在这里。
- prefix cache：`PREFIX_CACHE_MODE` 与 `PREFIX_CACHE_DISABLE_ARGS`。首轮为 `disabled`。
- benchmark：输入/输出长度、并发列表、每并发请求倍数、数据集、命令和动态 flag 名。
- profiling：TP 数、采集前缀、活动类型、hook 开关以及框架官方 profiling 参数。
- time配置：PROFILE_PROTOCOL='time'、PROFILE_PRERUN_COMPLETED_MULTIPLIER=4、PROFILE_POSTRUN_COMPLETED_MULTIPLIER=1、PROFILE_PRERUN_SECONDS=0、PROFILE_CAPTURE_SECONDS=15、PROFILE_MAX_REQUESTS；默认不加载Hook。验收实际控制区间、请求成功数、每rank的GPU活动与阶段覆盖；不强制P4/D128。历史steps字段只在显式旧协议中生效。
- 证据：官方参考 URL、版本/commit、访问日期。

数组必须按 shell token 拆分，不能把整条命令塞成一个字符串，也不要使用 `eval`。例如：

```bash
SERVICE_CMD=(sglang serve)
SERVICE_ARGS=(
  --model-path "$MODEL_PATH"
  --served-model-name "$SERVED_MODEL_NAME"
  --tp-size 8
)
PREFIX_CACHE_DISABLE_ARGS=(--disable-radix-cache)
```

`SERVER_CONTAINER_ARGS` 和 `CLIENT_CONTAINER_ARGS` 必须把项目的 `experiment.env` 只读挂载为容器内 `/experiment.env`，并保持 example 的 `/server`、`/client` 挂载路径。容器运行时、设备参数和额外挂载只能来自官方教程或当前平台实际要求。

若某个值含空格，它仍应是一个数组元素。只有在官方教程明确要求 shell 展开时才保留展开语法。

## 分析驱动的候选设计

获准自动调优时，配置与框架/算子按`autotuning.md`组成一个联合候选。依据对应安装版本的官方调优指南与分析证据填写候选值；保存基线experiment.toml/env快照，再同步候选设计、运行协议与展开命令。设计差异必须显式列入计划与报告，不更改benchmark负载来制造收益；分析请求本身不授权修改设计。


## 远端生成与干净交付

本地只用生成器--init创建environment.toml；实际脚手架在目标远端工程用--remote生成。生成器/模板可以一次性引导到远端coordination/bootstrap；--local-scaffold仅供模板/example维护和离线测试，不用于实际部署。远端配置路径必须准确等于workspace_dir/title/environment.toml，拒绝错误目录，已有脚本不覆盖重生成。设计和回收边界见project-contract“远端真源与本地交付”。
