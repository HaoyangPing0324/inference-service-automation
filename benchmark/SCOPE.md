# Benchmark 目录边界

本目录本身是推理服务 benchmark/压测 Skill，只保存 workload、压测执行和结果整理规则。跨部署、压测、profiling、分析和清理的总流程归入根入口 `../SKILL.md`；profiling 采集与分析资源归入 `../profiling/`。

新增内容必须使用相对资源定位、运行时路径解析或配置字段，不得写入开发机绝对路径、固定用户目录、主机信息或调用端专有命令。
