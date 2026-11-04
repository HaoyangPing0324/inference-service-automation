# PD 分离的时间窗口采集

## 两个计算角色与Router

默认采Prefill和Decode两个角色。客户端请求经过实际Router，采集控制直接到配置中的全部P/D endpoint；Router不作为默认第三份PyTorch/GPU Nsys采集。保留客户端请求时序、Router已有日志/路由指标；怀疑CPU/排队/转发瓶颈时再明确补采范围。

KV传输由实际后端决定，常在P/D角色之间直接传送，不把Router视为KV中继。NCCL/传输调用可在P/D报告观察，网络层问题另取网络指标；不能由GPU事件推断完整链路流量。

## 公共时间窗口

1. 固定seed的本地数据池与本地tokenizer；预热2个请求。持续最多C个在途，完成即补充。
2. 完成4×C正式请求且满足可选最短预运行时间后，并发向所有角色/start_profile：不传num_steps，profile_by_stage=false；Torch用CPU/GPU，Nsys用CUDA_PROFILER。
3. 等全部start响应后计capture_seconds，再并发stop，stop全部确认后继续至少完成C个请求才结束负载。只采这一段中间窗口。不是严格同时开始/结束，但每角色至少覆盖同一客户端控制区间；保留每端点发送/响应时间及实际请求数。
4. 客户端时钟区间不证明GPU或跨机器时钟同步。需要请求链路关联时核实主机时钟偏差与请求标识，缺失时明确限制。
5. 各端独立导出，可能先后完成；请求安全上限/失败/控制失败即本轮未完成。只读查日志、rank和文件写入，不因短时健康超时重启服务。

## 源主机验收与回收

- 各角色按自己的TP/rank清单验收。Torch只要求本角色阶段出现，不要求每端同时有P/D，更不要求固定P4/D128。
- time PyTorch在角色主机运行client/validate_time_window.py RUN --role prefill|decode --tp-size 实际TP --workload 实际客户端workload副本；传入同一run的元数据，不建立空影子目录。
- 多机路径中的output_dir指各角色自己的Linux容器挂载，不意味着共享文件系统。确保各主机相同容器路径指向对应本地工程。client保存workload/exitcode，角色保存trace；collect_profiler_results.py显式传--client-host、--prefill-host、--decode-host，TP不同时传--prefill-tp-size和--decode-tp-size。
- Nsys各角色包装服务，使用相同NSYS_RUN_ID；每角色检查原始.nsys-rep、report-index及实际目标GPU/范围，回收前按官方子Skill核验。
- 本地整理为profiling_results/工具/C<C>/capture/{prefill,decode}/，保留来源与SHA；两个角色及客户端证据均齐全才交付。

历史steps实验见[旧协议](step-windows.md)，保留原始双窗口报告和结果路径；旧成功不证明新time协议GPU实跑通过。

基础生成模板与回收器面向1P1D，允许两角色TP不同。多副本/多端点部署须先建立endpoint→来源主机→独立输出目录→完整rank清单，扩展回收映射后验收；不能仅扩大URL数组就宣称全部副本已回收。
