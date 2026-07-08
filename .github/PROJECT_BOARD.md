# FDT 开发看板 · 设置指南

## 在 GitHub 上创建 Projects Board

1. 打开 [CTAAgents/experts](https://github.com/CTAAgents/experts)
2. 点击顶部 **Projects** 标签 → **Create project**
3. 选择 **Board** 模板（或从头创建）
4. 命名为 **FDT v6 开发路线图**

## 列结构

| 列名 | 用途 |
|:-----|:------|
| 📥 **Backlog** | 待规划的长期事项 |
| 🎯 **This Week** | 本周优先级任务 |
| 🔧 **In Progress** | 正在开发中 |
| ✅ **Done** | 已完成 |

## 初始卡片内容

### 📥 Backlog
- 多周期共振信号（60m/240m/daily 三周期整合）
- 自进化 ML 升级（LightGBM 模型在线部署）
- 跨品种对冲信号（产业链内套利）
- GitHub Release 版本管理（v5.5, v6.0 规划）
- 辩论流程可视化（辩论树/论证链路图）

### 🎯 This Week
- 60m 数据管道修复（已完成 ✅）
- GitHub CI 配置（已完成 ✅）
- Issue 模板上线（已完成 ✅）
- 每日自动同步（已完成 ✅）
- 回测系统 - 自定义参数优化

### 🔧 In Progress
- （在开发中的功能）

### ✅ Done
- v5.4 信息源扩充（info_portals.md）
- 通道突破策略 v1.2 四层回落配置化
- 60m 子周期数据管道修复
- GitHub CI + Issue 模板
- 每日自动同步定时任务

## 自动关联

当你创建 Issue 时，可以在右侧 **Projects** 栏选择此看板，自动将 Issue 放入对应列。
