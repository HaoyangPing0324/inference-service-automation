# Apple Silicon / Metal 资料入口

入口核验日期：2026-11-04。这里只维护来源定位，不包含本地部署经验或兼容性结论。

| 目标 | 官方入口 | 如何查找 |
| --- | --- | --- |
| vLLM Metal快速部署 | [vLLM Metal Recipes](https://docs.vllm.ai/projects/vllm-metal/en/latest/recipes/#start-the-server) | 先按Mac统一内存选择recipe，再核对安装、支持模型、Metal功能和可用上下文；该插件不是CUDA vLLM的参数等价实现。 |
| SGLang Apple Metal部署 | [SGLang Apple Silicon with Metal](https://docs.sglang.io/docs/hardware-platforms/apple_metal#launch-of-the-serving-engine) | 页面当前以MLX serving runtime为主，并区分SGLang Diffusion的PyTorch MPS路径；先核对macOS、PyTorch、MLX和Metal编译要求。 |
| Apple MLX | [MLX Documentation](https://ml-explore.github.io/mlx/build/html/index.html) | 用于理解SGLang Metal路径的运行时与设备约束；不能单凭MLX支持推导某模型已被SGLang支持。 |
| vLLM / SGLang通用资料 | [通用框架入口](../sources.md) | 核对OpenAI兼容服务、模型语义与目标版本；平台实现和启动参数仍以Metal专用文档为准。 |

实际经验只从[获批经验](experience.md)读取。
