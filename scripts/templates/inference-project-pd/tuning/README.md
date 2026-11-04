# {{TITLE}} 优化实验索引

每轮建立独立study-id目录，实验、分析、最终报告放在同一轮下。templates/仅供复制，不是已执行实验；原始Profiling文件用路径/run/SHA引用，不复制大文件。

每轮含baseline/及candidates/<id>/。补采优化版Profiler/Nsys时，结果与ANALYSIS写该版本的profiling_results/，其下按工具/C/窗口/阶段组织；新轮次新study，不混入根目录基线。复用旧证据只链接，运行后的实际配置/源码与源run须可追溯。

| 轮次/报告 | 目标 | 基线/候选 | 状态 | 指标变化 |
|---|---|---|---|---|

正常结束不自动恢复基线；保留基线证据与记录最终运行版本是不同操作。
