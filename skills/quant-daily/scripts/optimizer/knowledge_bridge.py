"""知识库桥接器 — 明鉴秋在辩论流程中调取品种相关知识

用法（在辩论流程中）:
  from scripts.optimizer.knowledge_bridge import get_symbol_knowledge, get_knowledge_summary
  
  # 获取单个品种的周期适配和参数信息
  info = get_symbol_knowledge("rb")
  
  # 获取辩论相关的知识摘要（用于注入辩论prompt）
  summary = get_knowledge_summary(["rb", "sc", "MA"])
"""

import json
import os
import re

KNOWLEDGE_DIR = os.path.expanduser("~/.skills/Knowledge")
METHOD_DIR = os.path.join(KNOWLEDGE_DIR, "method")


def _read_kb_file(filename: str) -> str:
    """读取知识库文件"""
    path = os.path.join(METHOD_DIR, filename)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    return ""


def get_symbol_knowledge(symbol: str) -> dict:
    """获取某个品种的知识"""
    sym_lower = symbol.lower()  # 知识库文件使用小写
    result = {
        "symbol": symbol,
        "cycle_category": None,
        "daily_test_accuracy": None,
        "h_test_accuracy": None,
        "daily_overfit": False,
        "h_overfit": False,
        "optimized_params": {},
    }

    # 从周期适配指南中找分类
    guide = _read_kb_file("2026-07-07_62品种交易周期适配指南.md")
    if guide:
        cat_keywords = {
            "适合日线": "日线最优", "适合60分钟": "60分钟最优",
            "双周期": "两者都适合", "勉强可用": "勉强可用", "不适合": "都不适合",
        }
        sections = guide.split("\n## ")
        for sec in sections:
            header = sec.split("\n")[0].strip()
            cat_label = None
            for kw, label in cat_keywords.items():
                if kw in header:
                    cat_label = label
                    break
            if cat_label:
                for line in sec.split("\n"):
                    cells = [c.strip() for c in line.split("|")]
                    if len(cells) >= 3 and cells[2].lower() == sym_lower:
                        result["cycle_category"] = cat_label
                        break

    # 从训练测试表中找准确率
    detail = _read_kb_file("2026-07-07_62品种日线60分钟训练测试详表.md")
    if detail:
        sym_match = sym_lower
        for line in detail.split("\n"):
            cells = [c.strip() for c in line.split("|")]
            if len(cells) >= 9 and cells[1].lower() == sym_match:
                m_test = re.search(r'(\d+)%', cells[5])
                m_60m = re.search(r'(\d+)%', cells[8])
                if m_test: result["daily_test_accuracy"] = int(m_test.group(1))
                if m_60m: result["h_test_accuracy"] = int(m_60m.group(1))
                if "过拟合" in cells[6]: result["daily_overfit"] = True
                if "过拟合" in cells[9]: result["h_overfit"] = True
                break

    # 从optimized_params.json查优化参数（键名用小写）
    params_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "optimizer", "optimized_params.json"
    )
    if os.path.exists(params_path):
        try:
            with open(params_path, "r", encoding="utf-8") as f:
                params_data = json.load(f)
            per_symbol = params_data.get("per_symbol", {})
            # optimized_params.json使用原始大小写
            for key in [sym_lower, sym_lower.upper(), symbol]:
                if key in per_symbol:
                    result["optimized_params"] = per_symbol[key]
                    break
        except Exception:
            pass

    return result


def get_knowledge_summary(symbols: list) -> str:
    """生成一段知识摘要，供辩论过程中注入到Agent prompt

    这段文本包含:
      - 每个品种的周期适配建议
      - 训练/测试准确率
      - 是否过拟合（应降低该品种信号权重）
    """
    lines = []
    lines.append("【知识库参考】以下为回测优化结果供参考：")

    for sym in symbols:
        k = get_symbol_knowledge(sym)
        parts = [f"{sym}"]
        if k["cycle_category"]:
            parts.append(k["cycle_category"])
        acc_parts = []
        if k["daily_test_accuracy"]:
            acc_parts.append(f"日线{k['daily_test_accuracy']}%")
        if k["h_test_accuracy"]:
            acc_parts.append(f"60m{k['h_test_accuracy']}%")
        if acc_parts:
            parts.append("测试准确率:" + "/".join(acc_parts))
        if k["daily_overfit"] or k["h_overfit"]:
            parts.append("⚠过拟合")
        if k["optimized_params"].get("daily") or k["optimized_params"].get("60m"):
            parts.append("有优化参数")
        lines.append("  - " + " | ".join(parts))

    return "\n".join(lines)


def handle_knowledge_request(request: str) -> str:
    """处理Agent发来的自然语言知识请求，返回可用信息
    
    Agent可以通过SendMessage向明鉴秋发送如下格式的请求：
      "知识库: 查询 rb, sc, MA 的周期适配信息"
      "知识库: rb 的优化参数是什么"
      "知识库: 哪些品种适合60分钟"
    
    明鉴秋收到后调用此函数，返回格式化文本。
    """
    import re

    request_lower = request.lower()

    # 提取符号列表（大小写不敏感）
    symbols = re.findall(r'\b([a-zA-Z]{2,4})\b', request)
    valid_symbols = []
    for s in symbols:
        su = s.upper()
        if su in SYMBOL_CHAIN_MAP:
            valid_symbols.append(su)

    if not valid_symbols:
        # 尝试理解意图
        if "适合60" in request or "60分钟" in request:
            return get_knowledge_summary(['PB','LC','M','NI','Y','FG','CF','EG','RM','OP','SR','L','AG'])
        if "适合日线" in request or "日线" in request:
            return get_knowledge_summary(['SC','UR','AU','EB','FU','LU','SP','BU','HC','MA','PF','PG','PS','LH','PP','BR','NR','RB'])
        if "都不适合" in request or "不适合" in request:
            return "通道突破策略不适合的品种: b, sn, zn, SF, SS, SM, jm, al, CJ"
        if "全部" in request or "所有" in request:
            return get_knowledge_summary(list(SYMBOL_CHAIN_MAP.keys())[:10]) + "\n  ...(共62品种, 可用 knowledge_bridge.py <symbol1> <symbol2> 查询具体品种)"
        return "请指定品种代码，如: 知识库: rb, sc, MA"

    return get_knowledge_summary(valid_symbols)


# 为了Agent方便查询，提供符号→产业链映射的子集
SYMBOL_CHAIN_MAP = {
    'RB':'黑色系','HC':'黑色系','I':'铁矿石','J':'焦炭','JM':'焦煤','SF':'硅铁','SM':'锰硅',
    'SC':'能源链','LU':'能源链','FU':'能源链','BU':'能源链','PG':'能源链','PX':'能源链',
    'TA':'聚酯链','PF':'聚酯链','PR':'聚酯链','EG':'聚酯链','EB':'聚酯链',
    'V':'塑化链','PP':'聚酯链','L':'塑化链','MA':'塑化链',
    'SH':'化工','SA':'化工','UR':'化工','CU':'有色金属','AL':'有色金属','ZN':'有色金属','PB':'有色金属',
    'NI':'有色金属','SN':'有色金属','AO':'有色金属','SS':'有色金属','AU':'贵金属','AG':'贵金属',
    'A':'油脂油料','B':'油脂油料','M':'油脂油料','Y':'油脂油料','P':'油脂油料','OI':'油脂油料',
    'RM':'油脂油料','PK':'油脂油料','C':'农产品','CS':'农产品','SR':'农产品','CF':'农产品',
    'JD':'农产品','LH':'农产品','AP':'果蔬','CJ':'果蔬','FG':'建材化工','RU':'建材化工',
    'NR':'建材化工','BR':'建材化工','SP':'建材化工','OP':'建材化工','LC':'新能源','SI':'新能源',
    'PS':'新能源','EC':'航运','RR':'其他',
}


if __name__ == "__main__":
    # 快速测试
    import sys
    symbols = sys.argv[1:] if len(sys.argv) > 1 else ["rb", "sc", "ag", "l"]
    for sym in symbols:
        k = get_symbol_knowledge(sym)
        print(f"\n{sym}:")
        print(f"  周期分类: {k['cycle_category']}")
        print(f"  日线测试: {k['daily_test_accuracy']}%  60m测试: {k['h_test_accuracy']}%")
        print(f"  过拟合: 日线={k['daily_overfit']} 60m={k['h_overfit']}")
        print(f"  优化参数: {json.dumps(k['optimized_params'], ensure_ascii=False)}")
    print("\n--- 辩论摘要 ---")
    print(get_knowledge_summary(symbols))
