# 源码替换示例

这是结构与实现示例，不附整份安装框架源码、编译缓存或真实结果。manifest默认空且baseline，不会自动替换。通用步骤见[源码替换规则](../../../../../../../references/source-overrides.md)；本示例完整实现与调用见[正式报告](../../h20_deepseek-v4-flash_sglang_pd-aggregation.md)。

- operators/experiment_rmsnorm.py是已独立数值和模型调用验证的Triton RMSNorm参考实现；test_rmsnorm.py是数值检查。它不替代所有归一化分支，不保留原FlashInfer PDL优化，也没有性能提升结论。复用到新版本仍须重验。
- 从目标镜像实际安装的sgl_kernel.elementwise提取原文件到baseline/operators，再复制到operators，只把原FlashInfer普通rmsnorm返回路径改为调用experiment_rmsnorm.rmsnorm。通过实际模块__file__确认容器目标；不预填另一台机器的Python包目录。
- framework/中放当前安装http_server源码的修改副本：可添加实验响应header与生成请求日志，以证明真实请求走到新代码。其原版单独保存在baseline/framework；不与baseline/operators混放，不把一个版本的完整框架代码当作其他版本模板。
- manifest声明选定角色、框架与算子的相对source和运行时确认的容器target，额外模块路径仅填operators，并保留已核对的原PYTHONPATH。framework、operator、combined可分别选择；HTTP响应头与单行RMSNorm这两个功能变体仅分别实跑，二者组合仍须验收。历史joint-v1使用另一组模型文件/4行RMSNorm实现，不等于这两个功能变体的组合已通过。
- 同时替换不同目标文件不会发生文件挂载冲突，但需验证版本/API兼容；若两项修改同一目标文件，先合并改动，只保留一次映射并重新确定模式，不能让后挂载遮住前挂载。
- Python改动重新启动进程；Triton首次调用JIT。CUDA/C++扩展须先构建匹配ABI的二进制，不能把.cu直接映射到.so。

本示例未附虚构成功日志或真实GPU采集文件。新环境缺少Torch/Triton/FlashInfer时先询问用户，不自动安装。
