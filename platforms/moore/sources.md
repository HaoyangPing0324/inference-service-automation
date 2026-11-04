# Moore Threads 资料入口

入口核验日期：2026-11-04。这里只维护来源定位，不包含本地部署经验或兼容性结论。

| 目标 | 官方入口 | 如何查找 |
| --- | --- | --- |
| 厂商软件与框架适配来源 | [MooreThreads官方组织](https://github.com/MooreThreads) | 从组织仓库及README定位厂商维护的目标运行时/框架、版本和文档，不根据相似仓库名猜插件地址。 |
| PyTorch MUSA适配 | [torch_musa](https://github.com/MooreThreads/torch_musa) | 从对应release/tag的README及文档目录核对依赖、设备活动、采集与导出接口。 |
| vLLM-MUSA / S5000快速部署 | [vLLM-MUSA模型部署](https://docs.mthreads.com/vllm-musa/vllm-musa-doc-online/S5000/quick_start/) | 先读同版本的支持模型、环境准备与版本发布信息，再使用页面给出的模型recipe；页面示例参数只适用于其注明模型与性能目标。 |
| SGLang-MUSA快速部署 | [SGLang-MUSA快速开始](https://docs.mthreads.com/sglang-musa/sglang-musa-doc-online/quick_start/) | 页面包含PD角色参数、环境准备与服务启动；实际拓扑、脚本和DeepEP配置必须回到精确模型部署指南核对。 |
| SGLang / MUSA导航 | [通用SGLang入口](../sources.md) | 从Hardware Platforms中的Moore Threads MUSA入口进入，核对精确型号、模型、框架版本和拓扑。 |

本页未列出的推理框架组合不视为已支持；在上述官方入口无法定位后再按[导航规则](../README.md)检索。实际经验只从[获批经验](experience.md)读取。
