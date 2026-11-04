# 三层调度流水线与安全切换

实验组合是task，部署/benchmark/采集/分析是phase，单角色可验收工作单元是stage；每次执行标明task/phase/stage/attempt。二级维护design/execute/analyze三个队列、依赖、忙闲及资源；不使用Python轮询、SQLite消息总线或新建独立会话。

| 前置完成 | 后继 |
|---|---|
| design远端最小脚本/配置冻结 | execute在无冲突的已预留资源启动 |
| execute真实chat通过 | 用户已授权时才benchmark/采集 |
| execute结果封存并验收 | 已授权时analyze远端分析，或design整理必要交付 |
| analyze结果/结论就绪 | design更新报告及必要设计表，回收干净交付 |
| analyze提出优化建议 | 用户已批准目标/范围/预算后才design候选 |

不要求design先完成整个实验全部脚本。execute压测时design可准备同实验隔离采集版本，execute采集时analyze可分析先前有效基线；不改活动文件，不争用测量资源。部署到真实chat的请求不提前准备benchmark/Profiler/Nsys。

优先当前主任务，角色没有就绪stage才做后续可安全暂停的工作；同类别FIFO。收到高优先级指令，由二级在最近安全边界安排切换，三级只回二级，不越级派工。命令发出/消息送达/模型回合结束都不是成功完成；明确验收或安全暂停后才归idle。

design暂停在文件/跨机同步/回收的安全边界，analyze保存未发布分析，execute测量与加载未必可无损暂停；无法立即切换回报pause_blocked及最近边界，不硬杀后声称测量有效。确需断点只在被暂停远端实验coordination/<task>/<role>.md保存当前标识、版本、已完成、下一步及实际作业/剩余资源，不自动复制本地。

驻留服务继续占设备，execute确认真正释放后才更新预留。跨卡型共用设备/目录/端口，由一级协调各二级一致预留。恢复先核对真实后台与版本，重复/迟到消息不重复执行或覆盖新结果。无新事件保持安静，不循环询问三个角色是否完成。
