# Harness Starter Kit

> 一键接入 Harness 工程规范。
> 将此目录复制到你的项目根目录，按实际需求修改。

## 使用方法

```bash
# 1. 复制到项目
cp -r harness-starter-kit/* /your-project/

# 2. 修改 CLAUDE.md 适配项目特定规则
# 3. 按需创建 docs/harness/01-09 各文档
# 4. 运行检查
python scripts/pre_commit_harness_check.py
```

## 目录结构

```
CLAUDE.md           # 通用行为准则（核心入口，必须）
docs/
  harness/
    README.md       # Harness 文档索引
    harness-rules.yaml  # 12 项机读检查规则（建议）
scripts/
  pre_commit_harness_check.py  # 自动检查脚本（建议）
```

## 核心原则

1. 文档先行 — 先改文档，再写代码
2. 契约优先 — 先定义 Schema/TypedDict，再实现
3. 测试随重构 — 先写测试，全绿再进入下一阶段
4. trace_id 全链路 — 贯穿所有模块和日志
5. 角色边界钉死 — Agent 职责不可越界
6. 差距管理 — 技术债务登记 P0/P1/P2
7. 版本号纪律 — 每阶段 bump

## 12 项检查

详见 CLAUDE.md 或 harness-rules.yaml（机读版）。
