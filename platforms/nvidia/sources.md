# NVIDIA 资料入口

入口核验日期：2026-11-04。这里只维护来源定位，不包含本地部署经验或兼容性结论。

| 目标 | 官方入口 | 如何查找 |
| --- | --- | --- |
| 驱动、CUDA与平台工具 | [NVIDIA Documentation Hub](https://docs.nvidia.com/) | 按产品与组件进入目标版本文档；不以驱动/CUDA组件的单项支持推导模型支持。 |
| vLLM快速部署 | [Llama 3.3 70B on NVIDIA Blackwell & Hopper](https://docs.vllm.ai/projects/recipes/en/latest/Llama/Llama3.3-70B.html#deployment-steps) | 用作NVIDIA容器、配置文件与服务启动流程入口；该页面针对Llama 3.3 70B及Blackwell/Hopper，迁移到其他模型或GPU时必须重查模型recipe、精度、显存和并行配置。 |
| SGLang快速部署 | [CUDA Quickstart](https://docs.sglang.io/docs/get-started/quickstart#install-and-start) | 页面给出NVIDIA GPU、CUDA兼容驱动、容器/uv安装、服务启动与请求验证；实际运行固定所用版本与镜像tag，不直接照抄latest。 |
| vLLM / SGLang模型部署、PD与采集 | [通用框架入口](../sources.md) | 在目标版本模型支持、教程和部署拓扑目录定位精确模型；同平台不同GPU型号仍核对设备与并行要求。 |
| Nsight Systems报告核验与分析 | [内置nsight-systems Skill](../../profiling/nsight-systems/SKILL.md) | 按该Skill的bootstrap、官方文档入口与报告证据规则执行，不另维护一套分析协议。 |

可复用入口不意味着所有模型共享参数；实际经验只从[获批经验](experience.md)读取。
