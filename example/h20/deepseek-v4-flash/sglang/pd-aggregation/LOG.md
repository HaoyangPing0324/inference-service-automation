# 示例实验记录

这是历史经验摘要，不表示当前有活动服务；不记录连接、上传、轮询和容器操作。

## 关键失败与修正

- 检查点为FP8稠密/FP4专家混合格式，不能强制关闭FP4专家解释；按精确检查点选择flashinfer_mxfp4与内置DSPARK。
- PD采集须分别控制角色端点，请求成功不等于两端窗口完整；原生stop返回500须结合实际产物核实。
- 并发请求上限不等于GPU实际batch；当前time单窗口需由实测事件核查，不能继承旧采集数字。

## 证据入口

完整执行与历史结果见[h20_deepseek-v4-flash_sglang_pd-aggregation.md](h20_deepseek-v4-flash_sglang_pd-aggregation.md)；
当前time采集分析状态见[ANALYSIS.md](profiling_results/ANALYSIS.md)；已开展优化的记录见[tuning/README.md](tuning/README.md)。

## 当前工程与交付方式

本目录是完整远端工程的参考样式，脚本在实际远端由design编辑，execute运行，analyze只处理真实结果；不代表需整包下载到本地。普通本地交付只含环境/设计表、正式报告及已要求的原生采集/分析；压测原始数据、LOG和运行脚本留远端。本例已开展优化，tuning中仅展示实际修改源码、参数、说明和必要报告。
