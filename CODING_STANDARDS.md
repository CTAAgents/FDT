本文档定义FDT项目的代码风格与开发规范 版本：v0.1.0 | 创建日期：2026-07-14 | 更新日期：2026-07-14

定位说明
本文档面向所有开发者（人类+AI），定义代码风格、命名规范、最佳实践等开发规范。

代码风格规范（v2.0 新增）
自动化工具
本项目使用 Ruff 进行代码风格检查和自动修复。配置文件：pyproject.toml

# 安装 ruff
pip install ruff

# 检查代码风格
ruff check scripts/ tools/ tests/

# 自动修复
ruff check --fix scripts/ tools/ tests/

# 格式化代码
ruff format scripts/ tools/ tests/
1. 导入排序
使用 isort 规则，按以下顺序组织导入：

# 1. 标准库
import os
import sys
from datetime import datetime
from typing import Dict, List, Optional

# 2. 第三方库
import numpy as np
import pandas as pd
from scipy import stats

# 3. 本地模块
from trend_scanner.indicators import IndicatorEngine
from trend_scanner.models import MarketContext
规则：

每组之间空 2 行
标准库 → 第三方库 → 本地模块
字母顺序排列
2. 文档字符串
使用 Google 风格文档字符串：

def get_kline(self, symbol: str, days: int = 120) -> Optional[pd.DataFrame]:
    """获取K线数据

    Args:
        symbol: 品种代码（如 "RB", "I"）
        days: 获取天数，默认 120

    Returns:
        DataFrame 包含 date, open, high, low, close, volume 列
        数据不可用时返回 None

    Raises:
        ValueError: 当 symbol 为空时
    """
    pass
规则：

所有公共方法必须有文档字符串
包含 Args、Returns、Raises（如适用）
使用中文描述（与项目语言一致）
一行简述 + 详细说明
3. 类型提示
所有公共方法必须有类型提示：

# 正确
def calculate_signal(self, df: pd.DataFrame, threshold: float = 0.5) -> Dict[str, Any]:
    pass

# 错误（缺少类型提示）
def calculate_signal(self, df, threshold=0.5):
    pass
规则：

参数和返回值都需要类型提示
使用 Optional[T] 表示可选值
使用 Dict[str, Any] 表示字典
4. 注释风格
# 单行注释：# 后空格，首字母大写
# 这是一个注释

# 多行注释：每行独立
# 第一行注释
# 第二行注释

# 分隔线：用于区分代码段
# ──────────────────────────────────────────────
# 或
# ===========================================================================
规则：

使用中文注释（与项目语言一致）
注释解释"为什么"，不解释"做什么"
避免注释代码（直接删除更好）
5. 命名约定
类型	风格	示例
类名	PascalCase	IndicatorEngine, TrendScanner
函数/方法	snake_case	get_kline(), calculate_signal()
变量	snake_case	trend_strength, price_data
常量	UPPER_SNAKE_CASE	MAX_RETRIES, DEFAULT_TIMEOUT
私有成员	_前缀	_cache, _validate()
6. 错误处理
# 正确：捕获具体异常
try:
    result = api.call()
except ConnectionError as e:
    logger.error(f"连接失败: {e}")
    return None
except TimeoutError as e:
    logger.warning(f"超时: {e}")
    return None

# 错误：裸 except
try:
    result = api.call()
except:
    return None
规则：

捕获具体异常，不使用裸 except:
使用 logging 记录错误
优雅降级（返回 None 或默认值）
7. 行宽限制
最大行宽：120 字符
长行处理：使用括号换行，不使用反斜杠
# 正确
result = some_function(
    argument_one,
    argument_two,
    argument_three,
)

# 错误
result = some_function(argument_one, argument_two, argument_three)
1. 先思考再编码
不要假设。不要隐藏困惑。暴露权衡。

实施前：

明确说明假设，不确定时提问
存在多种解释时，全部列出，不要默默选择
有更简单方案时，主动提出，必要时反驳
遇到不清楚的地方，停下来，说明困惑，提问
2. 简单优先
最少代码解决问题。不做投机性开发。

不添加未要求的功能
不为单次使用代码创建抽象
不为未要求的"灵活性"或"可配置性"设计
不为不可能的场景添加错误处理
200 行能 50 行完成的，重写
自问：资深工程师会觉得这过于复杂吗？如果是，简化。

3. 外科手术式修改
只修改必须修改的部分。只清理自己制造的混乱。

编辑现有代码时：

不"改进"相邻代码、注释或格式
不重构没有问题的代码
匹配现有风格，即使你会做得不同
发现无关死代码时，提及但不删除
修改产生孤立代码时：

删除你的修改导致的未使用导入/变量/函数
不删除预存在的死代码，除非被要求
测试：每一行修改都应该直接追溯到用户请求。

4. 目标驱动执行
定义成功标准。循环直到验证通过。

5. 数据时效性检查（2026-06-17 新增）
数据是分析的基础，过期数据会导致错误结论。

所有涉及行情分析、交易建议、持仓评估的操作，必须先检查数据是否最新：

检查流程
1. 获取系统数据最新时间
   ↓
2. 对比当前时间
   ↓
3. 数据滞后 > 1 天？
   ├── 是 → 向用户确认是否继续
   │        ├── 用户确认 → 标注数据截止时间，继续分析
   │        └── 用户拒绝 → 先执行数据同步
   └── 否 → 正常分析
实施要求
场景	处理方式
扫描行情	执行前检查数据时间，滞后则提示用户
持仓健康度	执行前检查数据时间，滞后则提示用户
交易建议	执行前检查数据时间，滞后则提示用户
因子评估	执行前检查数据时间，滞后则提示用户
输出规范
使用非最新数据时，必须在分析结果中标注数据截止时间
示例：⚠️ 数据截止: 2026-06-15，当前: 2026-06-17
同步命令
# 同步最近5天数据
python tools/core/sync_data.py sync --days 5
将任务转化为可验证的目标：

"添加验证" → "为无效输入编写测试，然后使其通过"
"修复 bug" → "编写复现测试，然后使其通过"
"重构 X" → "确保重构前后测试通过"
多步骤任务，先陈述简要计划：

1. [步骤] → 验证：[检查]
2. [步骤] → 验证：[检查]
3. [步骤] → 验证：[检查]
强成功标准支持独立循环，弱标准需要反复确认。

有效性标志
这些准则有效的标志：

diff 中不必要的更改更少
因过度复杂导致的重写更少
澄清问题在实施前而非错误后提出
与工作流程的集成
开发工作流
1. 更新文档（明确需求和接口）
   ↓
2. 编写测试（定义成功标准）
   ↓
3. 实施代码（遵循本准则）
   ↓
4. 运行测试（验证成功标准）
   ↓
5. 更新所有文档（同步变更）
   ↓
6. 提交 GitHub（记录更改）
分析工作流（2026-06-17 新增）
0. 数据时效性检查（必须）
   ├── 数据最新 → 继续
   └── 数据滞后 → 提示用户，确认后继续
   ↓
1. 执行分析（扫描/评估/建议）
   ↓
2. 输出结果（标注数据截止时间）
各步骤说明
步骤	产出物	检查点
1. 更新文档	README.md、docs/设计文档	需求明确、接口定义清晰
2. 编写测试	test_*.py	测试覆盖正常/边界/异常场景
3. 实施代码	*.py	遵循本准则四条原则
4. 运行测试	测试报告	所有测试通过、覆盖率达标
5. 更新文档	README.md、docs/TESTING.md、memory/MEMORY.md	文档与代码一致
6. 提交 GitHub	Git commit	提交信息清晰描述更改
文档更新清单
步骤 5 必须更新以下FDT项目的记忆：

README.md：模块列表、测试状态、版本号（用户手册 + 技术规范的唯一来源）
docs/TESTING.md：测试数量、覆盖率、测试文件列表
memory/MEMORY.md：项目记忆、关键决策
memory/YYYY-MM-DD.md：工作日志
在步骤 3 实施代码时，严格遵循本准则的四条原则
先思考再编码：明确假设，列出多种解释，主动提出更简单方案
简单优先：最少代码解决问题，不添加未要求功能
外科手术式修改：只改必须改的，不改进相邻代码
目标驱动执行：定义成功标准，循环直到验证通过
附注：AI编码行为准则
本文档中的"先思考再编码"、"简单至上"、"外科手术式修改"、"目标驱动执行"四条核心原则，完整版本由项目根目录的 CLAUDE.md 统一管理。

本文档保留精简版本作为快速参考，详细说明请查看 CLAUDE.md。
