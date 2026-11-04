# Intel XPU 资料入口

入口核验日期：2026-11-04。这里只维护来源定位，不包含本地部署经验或兼容性结论。

| 目标 | 官方入口 | 如何查找 |
| --- | --- | --- |
| vLLM XPU容器与服务 | [Intel AI Containers：vLLM on XPU](https://github.com/intel/ai-containers/blob/main/vllm/xpu.md#43-launch-workloads) | 从支持硬件、驱动和容器准备进入Launch Workloads；固定实际镜像tag，并按目标模型核对设备、精度与并行参数。 |
| SGLang XPU部署 | [SGLang XPU](https://docs.sglang.io/docs/hardware-platforms/xpu#launch-of-the-serving-engine) | 页面覆盖安装、Serving Engine、请求Benchmark、XPU Graph与实验性PD；只启用当前硬件和版本明确支持的功能。 |
| Intel GPU软件栈 | [Intel GPU PyTorch Getting Started](https://docs.pytorch.org/docs/stable/notes/get_start_xpu.html) | 用于核对PyTorch XPU依赖和设备可见性；不以PyTorch可用单独证明vLLM/SGLang模型兼容。 |
| vLLM / SGLang通用资料 | [通用框架入口](../sources.md) | 继续核对目标模型、框架版本与CLI，不从CUDA或CPU条目迁移未经验证的参数。 |

实际经验只从[获批经验](experience.md)读取。
