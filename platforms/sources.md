# 通用官方资料入口

本页是跨平台导航，按需与对应平台sources.md联合使用。入口核验日期：2026-10-25；核验仅证明页面/仓库可访问，不证明任何模型已部署或目标平台受支持。

| 资料类型 | 官方入口 | 定位方法 |
| --- | --- | --- |
| vLLM | [文档](https://docs.vllm.ai/)、[官方仓库](https://github.com/vllm-project/vllm) | 先选目标版本，再按模型支持、部署拓扑、CLI、benchmark/profiler分类定位；平台插件细节从平台导航进入。 |
| SGLang | [文档](https://docs.sglang.io/)、[文档索引](https://docs.sglang.io/llms.txt)、[官方仓库](https://github.com/sgl-project/sglang) | 文档索引按模型、硬件平台、PD与profiling主题定位，再到实际版本tag固定依据。 |
| 精确模型 | 当前检查点自带README、config.json、权重索引与tokenizer；模型厂商发布的对应仓库/模型卡 | 从已确认检查点的元数据进入其厂商来源；保留后缀、量化变体及revision，不靠模型家族推断仓库或参数。 |

同框架的不同模型可复用目录入口和定位路线，不能复用未经目标版本核实的启动参数。缺少目标资料时按[导航规则](README.md)检索兜底。

模型文件下载首选[ModelScope](https://modelscope.cn/models)：由对应execute从已确认发布方/精确检查点定位仓库和适用版本。原HF模型不先测试huggingface.co或hf-mirror；具体授权、版本对应和失败边界见[模型下载规则](../references/operations/common-operations.md#模型下载execute负责优先modelscope)。本条是下载来源偏好，不表示所有同名仓库都已核验等价，也不替代框架/平台官方部署资料入口。
