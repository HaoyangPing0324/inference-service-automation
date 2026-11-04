# Profiling结果布局

只采一个中间time窗口：预热2，完成至少4×C正式请求后采集默认15秒，停止采集后继续至少C请求并排空。

目录为profiling_results/{profiler,nsys}/C<C>/capture/，其中按single保存原生结果；同一single混合时间线不拆成P/D两份。MANIFEST记录本轮来源、参数、验收与摘要。

本工程示例的新time协议尚未设备实跑，所有.placeholder均不是有效采集文件。
