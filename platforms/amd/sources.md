# AMD ROCm 资料入口

入口核验日期：2026-11-04。这里只维护来源定位，不包含本地部署经验或兼容性结论。

| 目标 | 官方入口 | 如何查找 |
| --- | --- | --- |
| ROCm平台、驱动与兼容性 | [ROCm Documentation](https://rocm.docs.amd.com/) | 先核对目标AMD GPU、ROCm版本、操作系统与容器支持；不能用单个教程成功推导其他型号兼容。 |
| vLLM快速部署 | [AMD AI Developer Hub：Deploying Llama-3.1 8B using vLLM](https://rocm.docs.amd.com/projects/ai-developer-hub/en/latest/notebooks/inference/3_inference_ver3_HF_vllm.html) | 用作AMD官方vLLM部署流程入口；该页面的模型、镜像和参数有明确示例范围，目标模型仍需从当前vLLM/ROCm支持信息定位。 |
| SGLang快速部署 | [SGLang AMD GPUs](https://docs.sglang.io/docs/hardware-platforms/amd_gpu#examples) | 从系统配置、安装方式和Examples进入；按实际GPU与ROCm版本核对镜像、attention backend、并行与模型recipe。 |
| vLLM / SGLang通用资料 | [通用框架入口](../sources.md) | 选择目标版本后定位模型支持、CLI、PD、benchmark与profiling；平台插件参数不能从CUDA直接照搬。 |

实际经验只从[获批经验](experience.md)读取。
