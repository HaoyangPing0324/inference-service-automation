# 示例实验记录

结构参考，无活动任务；本轮只做静态整理，没有重新部署GLM或采集数据。

## 必要修正

旧脚本混用/data路径与缺失的/experiment.env，新示例统一/models与/datasets挂载并提供两层实验配置；基线显式关闭prefix cache。默认已改为无Hook的单个中间time窗口，GLM GPU time采集仍须实测；分阶段适配只用于显式历史steps复现，不能继承其他模型成功结论。

## 证据入口

[正式报告](h20_glm-v53-flash_sglang_single.md)、[分析状态](profiling_results/ANALYSIS.md)。本示例未开展优化，不创建tuning目录。

## 当前工程与交付方式

本目录是完整远端工程的参考样式，脚本在实际远端由design编辑，execute运行，analyze只处理真实结果；不代表需整包下载到本地。普通本地交付只含环境/设计表、正式报告及已要求的原生采集/分析；压测原始数据、LOG和运行脚本留远端。本例没有实际优化，不创建tuning或源码审阅空目录。
