# CPU 资料入口

入口核验日期：2026-11-04。这里只维护来源定位，不包含本地部署经验或兼容性结论。

| 目标 | 官方入口 | 如何查找 |
| --- | --- | --- |
| vLLM CPU部署 | [Intel Optimization Zone：vLLM](https://github.com/intel/optimization-zone/blob/main/software/vllm/README.md) | 用作Intel CPU容器、模型与服务示例入口；继续核对目标处理器指令集、NUMA、内存容量、框架版本和量化格式。 |
| SGLang CPU部署 | [SGLang CPU Servers](https://docs.sglang.io/docs/hardware-platforms/cpu_server#launch-of-the-serving-engine) | 页面重点覆盖带Intel AMX的较新Xeon平台，包含CPU镜像、源码安装和Serving Engine；其他CPU架构不能直接视为已支持。 |
| Intel CPU软件优化 | [Intel oneAPI Documentation](https://www.intel.com/content/www/us/en/developer/tools/oneapi/documentation.html) | 仅在目标部署确实使用对应组件时核对运行库与工具，不把oneAPI可安装推导为模型或框架兼容。 |
| vLLM / SGLang通用资料 | [通用框架入口](../sources.md) | 核对目标模型、API和CLI；GPU/NPU专用并行、显存与profiling参数不得迁移到CPU。 |

实际经验只从[获批经验](experience.md)读取。
