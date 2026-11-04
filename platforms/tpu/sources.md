# Google TPU 资料入口

入口核验日期：2026-11-04。这里只维护来源定位，不包含本地部署经验或兼容性结论。

| 目标 | 官方入口 | 如何查找 |
| --- | --- | --- |
| Cloud TPU平台与拓扑 | [Google Cloud TPU Documentation](https://cloud.google.com/tpu/docs) | 先确认TPU代际、VM/Pod拓扑、运行时和区域资源；不同代际不能默认共享编译与并行配置。 |
| vLLM JAX快速部署 | [vLLM JAX Quickstart](https://docs.vllm.ai/projects/tpu/en/latest/getting_started/quickstart/#run-the-vllm-server) | 页面覆盖TPU环境、vllm-tpu安装、设备验证和服务启动；继续从Feature Matrix与对应代际Recipes核对目标模型。 |
| SGLang TPU部署 | [SGLang TPU](https://docs.sglang.io/docs/hardware-platforms/tpu#launch-of-the-serving-engine) | 先选择SGLang-TorchTPU或SGL-JAX后端；两者的框架、硬件范围、模型覆盖和部署配置彼此独立，不能混用。 |
| vLLM / SGLang通用资料 | [通用框架入口](../sources.md) | 用于定位模型与服务语义；TPU后端实现、镜像和拓扑仍以本页对应插件资料为准。 |

实际经验只从[获批经验](experience.md)读取。
