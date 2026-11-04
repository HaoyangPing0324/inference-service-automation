# Ascend 资料入口

入口核验日期：2026-11-04。这里只维护来源定位，不包含本地部署经验或兼容性结论。

| 目标 | 官方入口 | 如何查找 |
| --- | --- | --- |
| vLLM-Ascend快速部署 | [Quick Start / Online serving](https://docs.vllm.ai/projects/ascend/en/latest/getting_started/quick_start.html#quick-start-online-serving) | 先按Requirements与Installation核对环境，再从Online serving进入最小服务命令；模型参数仍从目标版本Model Tutorials和实际检查点确定。 |
| vLLM-Ascend模型部署 | [文档总览](https://docs.vllm.ai/projects/ascend/en/latest/getting_started/overview.html)、[仓库](https://github.com/vllm-project/vllm-ascend) | 在Model Tutorials定位精确模型，在Installation/Feature Guide核对平台与拓扑；按实际镜像版本的tag读取同名教程、Dockerfile和依赖定义。 |
| vLLM-Ascend采集与调优 | 同一文档的Performance and Debug / Service Profiling Guide，以及对应版本仓库 | 先找原生采集控制、平台profiler包装器和输出说明，再核对当前版本能力；不是直接套用其他模型命令。 |
| torch_npu | [Ascend/pytorch](https://github.com/Ascend/pytorch) | 从仓库README进入其官方维护来源与版本说明；按目标torch_npu版本查profiler实现、输出及分析依赖。 |
| SGLang / Ascend快速部署 | [Ascend NPU Quickstart](https://docs.sglang.io/docs/hardware-platforms/ascend-npus/getting-started/quick_start#start-sglang-server) | 页面给出设备范围、容器环境、服务启动与验证入口；继续核对SGLang NPU安装说明、精确模型、CANN与镜像版本。 |
| SGLang / Ascend导航 | [通用SGLang入口](../sources.md) | 从Hardware Platforms中的Ascend入口进入，再核对该版本平台支持和精确模型教程。 |

具体设备型号与软件组合必须按本次官方资料核验；历史验证结论只从[获批经验](experience.md)读取。

定位模型时先看官方模型族教程（如Dense/MoE分类），再选当前采用版本的tag及必要的固定commit。模型族页已覆盖目标尺寸而未列独立启动命令时，按其平台启动方式与目标检查点形成最小命令直接试跑；不因缺少独立模型标题停下，也不为已配置卡型的显示后缀另做搜索。软件/设备的具体兼容问题在启动日志或实际报错出现后再针对性定位。
