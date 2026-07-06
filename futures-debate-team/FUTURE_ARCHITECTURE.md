# 期货辩论专家团 — 分布式高频演进方案

> 本文档为期货辩论专家团从当前 WorkBuddy 寄生单体架构，演进为独立部署的分布式高频交易系统的未来发展方案。
> 创建日期：2026-07-06 | 状态：方案讨论稿
>
> **独立化路线图**：详见 `docs/independence_roadmap.md`（Phase 1-4 分步实施计划）
> - Phase 1: 行为独立（内建调度器，删除平台automation）
> - Phase 2: 运行时独立（自启动进程，自身Agent通信）
> - Phase 3: 数据独立（内建全量数据管道）
> - Phase 4: 部署独立（微服务+API+docker）

---

## 一、当前架构的高频瓶颈

| 瓶颈 | 根因 | 限制频率 |
|:-----|:-----|:---------|
| **Agent 串行** | 10 个 Agent 在同一 WorkBuddy 会话内顺次执行，单次辩论 48min | 日频 |
| **数据管道耦合** | `scan_all.py` 数据采集→指标计算→信号评分硬耦合在单一进程 | 日频/4h |
| **LLM 推理延迟** | 每轮辩论需要 LLM 推理 6 次以上，每次 5-15s | 无法缩到分钟级 |
| **无增量计算** | 每次全量扫描 62 品种，增量计算不可用 | 重复计算浪费资源 |
| **单点存储** | 内存/文件系统存储，无分布式缓存 | 扩容时一致性困难 |

要达到 **1min/5min 级频率**，核心思路是 **四层分离 + 消息驱动**。

---

## 二、远期目标架构：四层完全独立

```
┌────────────────────────────────────────────────────────────────────┐
│                       实时数据层                                    │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐              │
│  │ TDX采集   │ │ TqSDK    │ │ 东方财富  │ │ 金十资讯  │ ← 独立Pod  │
│  │ shard 0   │ │ shard 1  │ │ shard 2  │ │ shard 3  │  按品种分区  │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘              │
│       └────────────┴──────┬─────┴────────────┘                     │
│                           │ Kafka Topic: raw_tick, raw_kline       │
└───────────────────────────┼─────────────────────────────────────────┘
                            │
┌───────────────────────────▼────────────────────────────────────────┐
│                       信号计算层                                    │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐              │
│  │ L1-L4引擎 │ │ 因子引擎  │ │ ML预测   │ │ 情感因子  │ ← 独立 Pod  │
│  │ GPU加速  │ │ GPU加速  │ │ GPU加速  │ │          │  可按需扩缩  │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘              │
│       └────────────┴──────┬─────┴────────────┘                     │
│                           │ Kafka Topic: signal_score              │
└───────────────────────────┼─────────────────────────────────────────┘
                            │
┌───────────────────────────▼────────────────────────────────────────┐
│                       Agent 决策层                                  │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐              │
│  │ 闫判官   │ │ 证真     │ │ 慎思     │ │ 风控明   │ ← 独立 Pod   │
│  │ 仲裁服务  │ │ 分析服务  │ │ 分析服务  │ │ 审核服务  │  Kafka 驱动 │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘              │
│       └────────────┴──────┬─────┴────────────┘                     │
│                           │ Kafka Topic: agent_decision            │
└───────────────────────────┼─────────────────────────────────────────┘
                            │
┌───────────────────────────▼────────────────────────────────────────┐
│                        执行层                                       │
│  ┌────────────────────────────────────────────┐                    │
│  │     C++/Rust 低延迟执行引擎                   │                    │
│  │     对接 CTP / 易盛 / XTP 柜台               │                    │
│  │     微秒级风控前置、订单路由                    │                    │
│  └────────────────────────────────────────────┘                    │
└────────────────────────────────────────────────────────────────────┘
```

---

## 三、四层详细设计

### 3.1 实时数据层

**核心变化**：`scan_all.py` 从"全量扫描"变为"流式增量处理"

| 当前 | 目标 |
|:-----|:-----|
| 每天 16:00 全量扫描 62 品种，耗时 ~120s | 1min/5min 分钟级增量更新 |
| 全量计算所有指标 | 只计算新到数据增量部分 |
| 输出到文件 JSON | 输出到 Kafka Topic |
| 单进程 | 按品种分片，每个 shard 独立 Pod |

#### 分片策略

```
Pod: data-shard-0  → 黑色链（RB/HC/I/JM 等 12 个品种）
Pod: data-shard-1  → 能化系（SC/MA/TA/EG 等 15 个品种）
Pod: data-shard-2  → 有色金属（CU/AL/ZN/PB/NI 等 8 个品种）
...
每个 Pod 只处理自己分片的 8-15 个品种，1min K 线流实时计算
```

#### Kafka Topic 设计

| Topic | 内容 | 分区策略 | 保留策略 |
|:------|:-----|:---------|:---------|
| `raw_tick` | 原始 Tick 数据 | 按品种 | 7天 |
| `raw_kline_1min` | 1分钟 K 线 | 按品种 | 30天 |
| `raw_kline_5min` | 5分钟 K 线 | 按品种 | 60天 |
| `indicator_computed` | 计算后的指标 | 按品种 | 30天 |
| `signal_score` | 策略打分结果 | 按品种 | 30天 |
| `agent_cmd` | Agent 触发指令 | 按辩论组 | 7天 |
| `agent_decision` | Agent 决策结果 | 按品种 | 永久 |
| `exec_order` | 执行订单 | 统一 | 永久 |

---

### 3.2 信号计算层

**核心变化**：Python numpy 计算 → GPU 加速 + 流式计算

| 组件 | 技术栈 | 说明 |
|:-----|:-------|:-----|
| L1-L4 技术指标 | CuPy(GPU numpy) + Numba JIT | 45 个指标 GPU 并行，耗时从 60s → <1s |
| factor_timing 因子 | 同上 + Dask 分布式 DataFrame | 5 因子组 GPU 矩阵运算 |
| ML 方向预测 | ONNX Runtime 推理 | LightGBM 转 ONNX，GPU 推理 |
| 情感因子 | 独立 NLP 微服务 | 新闻流式分析 |

#### 增量计算模式

```python
# 当前：全量重算
def compute_all(symbols):
    for s in symbols:
        df = get_full_kline(s)    # 120天K线 → pandas
        compute_indicators(df)    # 全量重算

# 目标：增量更新
def compute_incremental(symbol, new_candle):
    state = load_cached_state(symbol)       # Redis 缓存前序状态
    new_indicators = incremental_update(state, new_candle)
    save_cached_state(symbol, new_state)
    push_to_kafka("signal_score", new_indicators)
```

**关键**：技术指标中 MA/MACD/RSI/ADX 等都有**递推公式**（不依赖全量历史），`calc_core.py` 中已有的 numpy 向量化计算可改造为流式增量版本，改造量不大。

**可增量化的指标**：

| 指标 | 递推公式 | 缓存前序状态大小 | 改造难度 |
|:-----|:---------|:-----------------|:---------|
| MA | `MA_n = MA_{n-1} + (p_n - p_{n-N})/N` | N 个收盘价 | 低 |
| MACD | 依赖 EMA 递推 | 2 个 EMA 值 | 低 |
| RSI | `RSI_n = RSI_{n-1} + α*(Δp_n - RSI_{n-1})` | 前 RSI 值 | 低 |
| ADX | 依赖 TR/+DI/-DI 递推 | 3-4 个状态值 | 中 |
| CCI | 依赖 SMA/MD 递推 | N 个典型价 | 低 |
| BOLL | 依赖 MA + 方差递推 | N 个收盘价 + 方差 | 中 |

**结论**：约 80% 的指标可增量计算，每个品种只需缓存 20-200 个数值。

---

### 3.3 Agent 决策层

**核心变化**：单体对话 → Kafka 消息驱动的异步微服务

每个 Agent 独立部署为一个 Pod，通过 Kafka 消费和发布消息：

```
闫判官 Pod:
  订阅: signal_score topic（信号评分流）
  消费: 新信号到达 → 检查是否需要辩论
  发布: agent_cmd topic（"启动RB辩论"）

证真 Pod:
  订阅: agent_cmd topic + signal_score topic
  消费: "启动RB辩论" → 提取多头论据
  发布: agent_decision topic（多方提案）

慎思 Pod:
  对称逻辑

风控明 Pod:
  订阅: agent_decision topic
  消费: 任意 Agent 决策 → 风控检查
  发布: agent_decision topic（风控 verdict）
```

#### 辩论流程的事件驱动

```
time  speaker    topic                          message
t+0   数据层     signal_score/signal_RB         {"symbol":"RB","l1l4":-72,"factor":-45,...}
t+1   闫判官    agent_cmd/debate_RB            {"action":"start_debate","symbol":"RB","proposition":"bear"}
t+2   证真      consumer agent_cmd             接收 + 生成论据
t+3   慎思      consumer agent_cmd             接收 + 生成论据
t+4   证真      agent_decision/RB_bull_proposal {"entry":3600,"target":3400,"stop":3680}
t+5   慎思      agent_decision/RB_bear_proposal {"entry":3550,"target":3750,"stop":3450}
t+6   闫判官    agent_decision/RB_verdict       {"winner":"bear","scores":{...}}
t+7   策执远    agent_decision/RB_plan          {"lots":4,"contract":"RB2610",...}
t+8   风控明    agent_decision/RB_risk          {"verdict":"green"}
```

这个模式下，**多品种可以并行辩论**——RB、HC、CU 各走各的 Kafka Partition，互不阻塞。

#### Agent Pod 扩缩策略

```yaml
# K8s HPA 配置示例
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: agent-zhnegzhen
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: agent-zhnegzhen
  minReplicas: 1
  maxReplicas: 10
  metrics:
  - type: Object
    object:
      metric:
        name: kafka_consumer_lag
      describedObject:
        apiVersion: v1
        kind: Pod
        name: agent-zhnegzhen
      target:
        type: Value
        value: 50  # 积压超过50条消息时扩容
```

---

### 3.4 执行层

**核心变化**：Python 决策 → C++/Rust 低延迟执行

| 功能 | 当前（Python） | 远期（C++/Rust） |
|:-----|:--------------|:-----------------|
| 订单路由 | 无 | 微秒级，对接 CTP/易盛 |
| 风控前置 | 辩论后审核 | 下单前纳秒级风控 |
| 订单簿管理 | 无 | Tick 级订单簿同步 |
| 延迟 | ~100ms (Python 网络) | <10μs |

**架构分离逻辑**：Agent 决策层产出的是**交易指令**（方向/品种/价位/手数），执行层负责把这些指令翻译成交易所 API 调用。两者通过 Kafka 解耦，即使执行层偶尔抖动，Agent 决策层不受影响。

---

## 四、三阶段实现路线

### 阶段一：单服务微服务化（3-4个月）

**目标**：数据层和策略层独立部署，Agent 仍集中运行

```
scan_all.py → 拆为 data-service + signal-service
  data-service:   定时采集 + 多源降级 + DuckDB 存储
  signal-service: 读取 data-service → 计算指标 + 信号评分
                  → 输出 candidates JSON（不变）
  Agent 编排:     CrewAI（3-4个 Agent 先跑通道A）
```

**关键交付**：
- [ ] `data-service` 独立 Docker 容器，REST API + Kafka Producer
- [ ] `signal-service` 独立 Docker 容器，消费 data-service 输出
- [ ] 增量指标计算（MA/RSI/MACD/ADX 递推公式实现）
- [ ] Agent 通道A（直接推荐）在 CrewAI 上跑通
- [ ] FastAPI 提供 REST 接口，Postman 可调用

**验证指标**：

| 指标 | 当前（单体） | 阶段一目标 |
|:-----|:-----------|:----------|
| 数据采集+信号 | 120s 全量 | 30s 全量 / 5s 增量 |
| 直接推荐(通道A) | ~8min（含 Agent 推理） | ~2min |
| 完整辩论(通道B) | ~60min | ~60min（不变） |
| 部署方式 | WorkBuddy 寄生 | Docker 容器 |

---

### 阶段二：Agent 异步化（3-4个月）

**目标**：Agent 独立 Pod + Kafka 消息驱动，多品种并行辩论

```
数据层 ──Kafka──→ 信号层 ──Kafka──→ Agent 决策层 ──Kafka──→ 结果层
                                    ↑
                              每个 Agent 独立 Container
                              K8s Deployment 自动扩缩
```

**关键交付**：
- [ ] 闫判官/证真/慎思/风控明/策执远 5 个 Agent 独立 Pod
- [ ] Kafka 消息协议标准化（`agent_cmd` / `agent_decision` schema）
- [ ] 多品种并行辩论演示（同时辩论 RB + HC + CU）
- [ ] Agent Pod 自动扩缩（K8s HPA based on Kafka lag）
- [ ] 自建 LLM 推理接入（替代 WorkBuddy 内置 LLM）

**验证指标**：

| 指标 | 阶段一目标 | 阶段二目标 |
|:-----|:----------|:----------|
| 数据采集+信号 | 30s 全量 / 5s 增量 | 10s 全量 / 1s 增量 |
| 直接推荐(通道A) | ~2min | ~30s |
| 完整辩论(通道B) | ~60min | ~15min（多品种并行 <5min 聚合）|
| 多品种并发 | 1组 | 5组同时 |
| 部署方式 | Docker | K8s |

---

### 阶段三：高频适配（3-4个月）

**目标**：达到 1min/5min 级别，执行层接入柜台

```
数据层:   实时 Tick → 1min K 线 → 5min K 线（增量流式）
信号层:   GPU 加速指标计算 → 因子打分（<1s/62品种）
Agent层:  1min 级别快速判断（通道A）+ 5min 级别完整辩论（通道B）
执行层:   C++ 低延迟路由 → CTP 柜台
```

**关键交付**：
- [ ] 1min K 线增量流式处理
- [ ] GPU 加速指标计算（CuPy + Numba JIT）
- [ ] 通道A 在 1min 级别自动触发
- [ ] 执行引擎接入 CTP 仿真环境
- [ ] Prometheus + Grafana 全链路监控

**验证指标**：

| 指标 | 阶段二目标 | 阶段三目标 |
|:-----|:----------|:----------|
| 数据采集+信号 | 10s 全量 / 1s 增量 | 0.5s 增量 |
| 直接推荐(通道A) | ~30s | <5s |
| 完整辩论(通道B) | ~15min | ~3min（多频率并行）|
| 最低运行周期 | - | 1min |
| 执行延迟 | - | <10μs |

---

## 五、关键选型建议

| 组件 | 推荐 | 理由 |
|:-----|:-----|:-----|
| **消息队列** | Kafka | 持久化+重放+多消费者组，Agent 故障后可恢复状态 |
| **容器编排** | K8s (K3s) | 生产级自动扩缩+自愈，轻量级部署用 K3s |
| **Agent 框架** | CrewAI → 自研轻量编排 | 初期 CrewAI 快速原型，后期 Kafka 驱动代替 |
| **GPU 计算** | CuPy + Numba JIT | 与现有 numpy 代码兼容，迁移成本低 |
| **增量计算引擎** | Redis + 递推公式 | 缓存前序状态，避免全量重算 |
| **序列化** | Avro (Confluent Schema Registry) | 强 schema + 向后兼容，Agent 间协议版本管理 |
| **执行引擎** | Rust (Nona-Grid/Crate 组合) | 比 C++ 更安全的内存模型，适合金融场景 |

**不建议的选型**：
- ❌ Flink/Spark Streaming 做指标计算 → 太重，62 品种的指标计算用 CuPy 更快
- ❌ 完全自研 Agent 编排 → CrewAI 够用，Kafka 打通后订阅模式即可
- ❌ 全量 C++ 重写 Python 代码 → 只重写执行层和热点路径，信号逻辑保持 Python

---

## 六、风险与缓解

| 风险 | 概率 | 影响 | 缓解 |
|:-----|:----:|:----:|:-----|
| LLM 推理延迟 > 5s | 高 | 高频决策信号滞后 | 通道A（规则/信号）与通道B（LLM辩论）异步分离，通道A走快速路径 |
| LLM API 成本飙升 | 中 | 5min 级别辩论消耗 Token 巨大 | 辩论触发频率自适应（ADX 高才辩，低信号不辩） |
| 数据源实时性不足 | 中 | 1min K 线有延迟 | TDX Local + TqSDK 实时行情优先，东方财富/AKShare 作为降级 |
| 分布式状态一致性 | 低 | Kafka 至少一次投递导致重复判断 | `debate_id` 幂等判断，重复消息直接丢弃 |
| GPU 资源不足 | 低 | 指标计算变慢 | 按品种分片 + 优先级队列（黑色链优先） |

---

## 七、关键增量指标递推公式（参考）

### MA（移动平均线）

```python
# 全量计算
def sma(data, n):
    return rolling(data, n).mean()

# 增量计算
def sma_incremental(prev_sma, new_price, oldest_price, n):
    # prev_sma = sum(prices[-n:]) / n
    # new_sma = (sum(prices[-n:]) - oldest_price + new_price) / n
    return prev_sma + (new_price - oldest_price) / n
```

### EMA（指数移动平均）

```python
def ema_incremental(prev_ema, new_price, alpha):
    # alpha = 2 / (n + 1)
    return alpha * new_price + (1 - alpha) * prev_ema
```

### RSI

```python
def rsi_incremental(prev_avg_gain, prev_avg_loss, new_price, prev_price, n):
    change = new_price - prev_price
    gain = max(change, 0)
    loss = max(-change, 0)
    avg_gain = (prev_avg_gain * (n - 1) + gain) / n
    avg_loss = (prev_avg_loss * (n - 1) + loss) / n
    if avg_loss == 0: return 100
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))
```

---

## 八、路线图总结

```
时间线:  Month0 ──── Month3 ──── Month6 ──── Month9 ──── Month12
         当前      阶段一完成    阶段二完成    阶段三完成
         │          │            │            │
         │ 数据层   │ Agent      │ 高频       │
         │ 微服务化  │ 异步化     │ 适配       │
         │          │            │            │
频率:   daily ─── 4h/1h ─── 15min ─── 5min/1min
延迟:   60min ─── 10min ─── 1min ─── <5s
吞吐:   1批/日 ── 6批/日 ── 96批/日 ── 1440批/日
```

> **核心原则**：不急于一步到位高频。当前 daily 频率下先把独立部署跑通（阶段一），再逐步升级到 1h→15min→5min→1min。每个频率等级验证通过后再往下走。通道A（直接推荐）始终走在通道B（辩论）前面——快速路径先上线，慢速路径按需优化。
