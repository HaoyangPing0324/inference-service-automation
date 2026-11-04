# 优化轮次

| study | 内容 |
|---|---|
| [20261021-joint-c1-c8-c32](20261021-joint-c1-c8-c32/修改说明.md) | joint-v1可编辑参数、实际框架/算子改动与既有C1/8/32结果 |

单候选的干净回收结构：

```text
20261021-joint-c1-c8-c32/
├── experiment.toml
├── baseline/source/
│   ├── framework/deepseek_v4.py
│   └── operators/elementwise.py
├── source/
│   ├── framework/deepseek_v4.py
│   └── operators/
│       ├── elementwise.py
│       └── grouped_rmsnorm.py
├── 修改说明.md
├── AUTOTUNING_PLAN.md
└── AUTOTUNING_REPORT.md
```

只收本轮实际修改/新增文件及被替换文件的真实原件，不附基线全树、验证脚本、benchmark原始数据、缓存、编译产物或未采集结果占位目录。源文件对应既有joint-v1归档，当前未重新执行；效果与验证范围见轮次报告。新任务未获准优化不建tuning目录，多候选分别归档，不覆盖这一轮。
