# Harness Starter Kit

> 全局 Harness 工程规范模板。
> 每次新建项目时，自动从本目录部署 CLAUDE.md + docs/harness/ 到项目根目录。

## 目录结构

```
D:\HarnessStarterKit\
├── CLAUDE.md                    # 通用行为准则（先思考/简单/外科/目标驱动 + Harness 规范）
├── README.md                    # 本说明
├── docs\
│   └── harness\
│       ├── README.md            # Harness 文档索引
│       └── harness-rules.yaml   # 12 项机读检查规则 + 10 条反模式
└── scripts\
    ├── deploy_harness.py        # 手动部署脚本
    ├── pre_commit_harness_check.py  # commit 前自动检查脚本
    └── rhi_global_setup.py      # RHI 递归 Harness 自进化（v9.22.0+）
```

## 部署方式

**自动部署**（推荐）：TRAE AI 在新项目首次会话时自动复制本目录内容，无需手动操作。

**手动部署**：
```bash
# 从项目根目录执行
python D:\HarnessStarterKit\scripts\deploy_harness.py
```

## 使用说明

1. 部署后，项目根目录会出现 CLAUDE.md 和 docs/harness/
2. 按项目实际情况修改 CLAUDE.md，增补项目专属内容（如 Agent 列表、架构流程等）
3. 逐步创建 docs/harness/01-09 各文档（参考模板 README）
4. commit 前自动运行 pre_commit_harness_check.py

## RHI 递归 Harness 自进化（v9.22.0+）

RHI 让 CLAUDE.md 能自我优化：

```bash
python scripts/rhi_global_setup.py init     # 首版快照
python scripts/rhi_global_setup.py step     # 执行一轮优化
python scripts/rhi_global_setup.py status   # 查看状态
```

每次 step 从四维评分 CLAUDE.md，记录 pairwise 偏好，改进率低于 0.3 时收敛。
参考：RHI (arXiv:2607.15524) + MemoHarness (arXiv:2607.14159)
