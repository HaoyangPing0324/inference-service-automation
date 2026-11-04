# 三层 Agent：主协调、卡型调度、专业执行

实际实验恢复原生子Agent架构，不再启动Python scheduler、App Server或额外独立会话。每种精确卡型一个调度Agent，管理design、execute、analyze三个直属子Agent；design合并原传输职责。同型多机与多个模型复用团队，不同型号分组。

```text
coordinator（一级：用户交互、授权、汇总）
└── <hardware>-scheduler（二级：任务/资源/三个队列）
    ├── <hardware>-design（三级：远端设计、脚本/配置/报告编辑、必要交付回收）
    ├── <hardware>-execute（三级：资源检查、命令执行、现场排错和验收）
    └── <hardware>-analyze（三级：只分析真实结果，首份结果前空闲）
```

完整团队需要 `1 + 4 × 卡型数` 个Agent身份，单卡型5个。使用当前环境原生创建、消息和等待工具；真实ID/父子关系由工具返回，不凭显示名称猜测。创建前检查实际嵌套深度和容量；不支持时报告准确缺口，不假装已创建、不自行退回主Agent包办或另起CLI会话。Skill维护不授权远端实验。

## 命名与最小上下文

名称固定为 `<hardware>-scheduler/design/execute/analyze`，工具仅支持下划线时用等价名称。hardware为已确认的精确卡型安全别名，不是主机名、厂商或模型；记录hardware_type/key、角色、真实agent_id及parent_agent_id。切换任务或阶段不重建身份。

每个Agent只读[共享契约](shared.md)、自己的指引和当前阶段必需规则；新建时显式给出规范根绝对路径、角色文档、任务、授权边界及输入位置。不要复制完整聊天历史或全部Skill。

| 身份 | 指引 | 允许读取/操作 | 默认禁止 |
|---|---|---|---|
| coordinator | [一级](coordinator.md) | 用户指令、环境身份、调度摘要 | SSH、工作脚本、原始结果与分析文件 |
| scheduler | [二级](hardware-scheduler.md) | 已确认环境/设计摘要、队列、资源和验收元数据 | 登录排错、编辑脚本、读大段日志/trace或替analyze分析 |
| design | [设计](design.md) | 远端本实验脚本/配置/技术文档、模板/官方资料、交付文件 | 启动服务/GPU试跑、擅改活动测量版本、读无关工程 |
| execute | [执行](execute.md) | 实际命令、相关脚本、作业日志、资源现场及验收所需产物 | 代写长期设计文档、代替analyze做性能研究、修改共享Skill |
| analyze | [分析](analyze.md) | 已验收真实结果、必要版本/负载元数据、分析工具 | 首份结果前工作、执行排错/写服务脚本、私自GPU补测 |

这些是职责边界，不是声称工具强制隔离。用户明确要求的只读审阅/Skill维护可按任务例外；不得用“只读”长期越过分工。

工程以[远端真源与本地交付](../references/project-contract.md#远端真源与本地交付)为准。设计前按平台sources入口查官方资料；初次最小启动、遇错再查的规则不因恢复调度Agent而回退。
