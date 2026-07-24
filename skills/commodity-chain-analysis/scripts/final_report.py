# -*- coding: utf-8 -*-
"""链证源 — 最终报告合成（含基本面验证）"""

import json
import os
import sys

SKILL_DIR = os.path.dirname(os.path.abspath(__file__))
if SKILL_DIR not in sys.path:
    sys.path.insert(0, SKILL_DIR)

from scripts.chains import CHAIN_PRODUCTS


def get_chain_members(chain_name):
    return CHAIN_PRODUCTS.get(chain_name, [])


# ============================================================
# 完整分析结果（含基本面验证）
# ============================================================
final_output = {
    "cs": {
        "chain": "谷物软商品",
        "chain_members": get_chain_members("谷物软商品"),
        "term_structure": "flat",
        "chain_trend": "震荡",
        "chain_avg_score": 22.3,
        "chain_consistency": 100,
        "aligned": True,
        "z_score": 1.6,
        "z_status": "偏极端",
        "redundant": False,
        "redundant_with": None,
        "fundamental_notes": [
            "玉米淀粉产能2775万吨，Q3新增临清金玉米70万吨+天熙生物70万吨产能预期",
            "6-9月价格窄幅震荡2690-2712元/吨区间，冲高回落走势",
            "淀粉糖消费旺季来临+陈粮成本支撑vs新季玉米上市预期压制",
        ],
        "notes": [
            "谷物软商品整体震荡，cs与lh同向但驱动因素独立(淀粉加工vs养殖)，不冗余",
            "cs偏极端z=+1.60，注意均值回归风险",
            "基本面供增需平，缺乏趋势性行情机会",
        ],
    },
    "hc": {
        "chain": "黑色系",
        "chain_members": get_chain_members("黑色系"),
        "term_structure": "contango",
        "chain_trend": "偏空震荡",
        "chain_avg_score": -54.3,
        "chain_consistency": 100,
        "aligned": True,
        "z_score": -0.7,
        "z_status": "正常",
        "redundant": False,
        "redundant_with": None,
        "fundamental_notes": [
            "黑色系供需双弱：螺纹表需下滑，热卷需求同步下降，库存持续累积",
            "钢厂盘面利润-275元/吨，亏损扩大，高炉减产压力增大",
            "2026年产能置换新规重启，史上最严，压减粗钢产量政策加码",
            "地产投资降幅扩大，基建/制造业投资增速持续回落，内需整体偏弱",
            "但热卷出口仍有韧性，厂库维持低位",
        ],
        "notes": [
            "✅黑色系偏空震荡与SELL方向一致，同链3/3全空头共振",
            "hc评分57>rb评分55，hc为主品种，rb标记为冗余",
            "contango结构（远强近弱），做空有利，展仓收益",
            "基本面供需双弱+亏损扩大+淡季效应，空头逻辑扎实",
        ],
    },
    "sp": {
        "chain": "纸浆造纸",
        "chain_members": get_chain_members("纸浆造纸"),
        "term_structure": "contango",
        "chain_trend": "偏空震荡",
        "chain_avg_score": -57.0,
        "chain_consistency": 100,
        "aligned": True,
        "z_score": -0.7,
        "z_status": "正常",
        "redundant": False,
        "redundant_with": None,
        "fundamental_notes": [
            "港口库存232万吨年内高位，针叶旧货堆积，09合约交割压力大",
            "海外针叶浆外盘下调10美元/吨至670美元，进口成本下移",
            "6月造纸淡季，文化纸开工率仅55%-65%，刚需采购不足",
            "全市场机构共识：偏弱熊市格局，短期反弹缺乏持续性",
        ],
        "notes": [
            "✅纸浆造纸偏空震荡与SELL方向一致",
            "contango结构，做空有利",
            "高库存+淡季+外盘下调，空头基本面逻辑完整",
        ],
    },
    "rb": {
        "chain": "黑色系",
        "chain_members": get_chain_members("黑色系"),
        "term_structure": "contango",
        "chain_trend": "偏空震荡",
        "chain_avg_score": -54.3,
        "chain_consistency": 100,
        "aligned": True,
        "z_score": -0.5,
        "z_status": "正常",
        "redundant": True,
        "redundant_with": "hc",
        "fundamental_notes": [
            "螺纹钢表需大幅下滑，库存明显累积，杭州螺纹库存121.6万吨",
            "中天螺纹现货3200元/吨，盘面利润-275元/吨，亏损持续扩大",
            "地产投资降幅扩大，基建增速回落，终端需求疲弱",
        ],
        "notes": [
            "⚠️同链冗余：rb与hc驱动高度重叠(地产+基建+粗钢)，保留hc(评分更高)",
            "contango结构支持做空方向",
            "建议交易hc而非rb",
        ],
    },
    "lh": {
        "chain": "谷物软商品",
        "chain_members": get_chain_members("谷物软商品"),
        "term_structure": "back",
        "chain_trend": "震荡",
        "chain_avg_score": 22.3,
        "chain_consistency": 100,
        "aligned": True,
        "z_score": 0.4,
        "z_status": "正常",
        "redundant": False,
        "redundant_with": None,
        "fundamental_notes": [
            "生猪出栏均价9.4-9.8元/kg，行业连续10个月全域深度亏损",
            "自繁自养每头肥猪亏损超300元，产能调减目标加大、时限提前",
            "机构共识：短期磨底蓄势，中期上行拐点渐近，猪周期缩短加速",
            "仔猪价格从220元/头快速回落，行业预期6月出现根本逆转",
        ],
        "notes": [
            "谷物软商品整体震荡，lh BUY方向与链趋势一致",
            "back结构（近强远弱）支持做多逻辑",
            "产能去化加速+深度亏损=周期底部信号，中期上行逻辑成立",
        ],
    },
    "rr": {
        "chain": "谷物软商品",
        "chain_members": get_chain_members("谷物软商品"),
        "term_structure": "flat",
        "chain_trend": "震荡",
        "chain_avg_score": 22.3,
        "chain_consistency": 100,
        "aligned": True,
        "z_score": -0.3,
        "z_status": "正常",
        "redundant": False,
        "redundant_with": None,
        "fundamental_notes": [
            "粳米作为谷物软商品成员，受整体粮食供需格局影响",
            "2026年Q1全国农产品进口增长18.1%，粮食进口量3757万吨增长18.1%",
            "玉米及玉米粉进口增长85.9%，谷物市场供应充裕",
        ],
        "notes": [
            "谷物软商品震荡，rr SELL方向无产业链矛盾",
            "但rr同链中仅1/3同向(另2个BUY)，共振不强",
            "基本面支撑偏弱，建议谨慎对待",
        ],
    },
    "SM": {
        "chain": "黑色系",
        "chain_members": get_chain_members("黑色系"),
        "term_structure": "contango",
        "chain_trend": "偏空震荡",
        "chain_avg_score": -54.3,
        "chain_consistency": 100,
        "aligned": True,
        "z_score": -0.1,
        "z_status": "正常",
        "redundant": False,
        "redundant_with": None,
        "fundamental_notes": [
            "锰硅现货5556元/吨，月跌4.17%，一年低位，主力合约围绕6000震荡",
            "成本支撑（焦炭涨价+电价平稳）vs需求走弱，供应压力上升",
            "康密劳6月锰矿报价5.45美元/吨度，环比下跌0.3美元",
            "独立品种：锰硅受锰矿进口+独立供需影响，与RB/HC相关性弱",
        ],
        "notes": [
            "✅黑色系偏空震荡与SELL方向一致，同链3/3共振",
            "⚠️注意：SM虽在黑色系但独立驱动(锰矿进口+铁合金供需)，不与RB/HC同链排除",
            "基本面成本支撑vs需求走弱，多空交织，评分仅51偏低",
        ],
    },
    "a": {
        "chain": "油脂油料",
        "chain_members": get_chain_members("油脂油料"),
        "term_structure": "contango",
        "chain_trend": "强势多头",
        "chain_avg_score": 43.0,
        "chain_consistency": 100,
        "aligned": True,
        "z_score": -0.3,
        "z_status": "正常",
        "redundant": False,
        "redundant_with": None,
        "fundamental_notes": [
            "东北国产大豆基层余粮见底，高蛋白豆源惜售挺价",
            "6月大豆到港1073万吨同期高位，油厂大豆库存660万吨",
            "豆一期货4248元/吨窄幅震荡，产区惜售托底vs进口大量到港压制",
        ],
        "notes": [
            "✅油脂油料强势多头与BUY方向一致，同链3/3全多头共振",
            "⚠️基本面矛盾：信号多头但contango结构做多不利",
            "⚠️基本面矛盾：国产大豆余粮见底(利多)vs南美大豆到港高峰(利空)",
            "评分仅47偏低，建议关注a是否真正具有做多价值",
        ],
    },
    "m": {
        "chain": "油脂油料",
        "chain_members": get_chain_members("油脂油料"),
        "term_structure": "contango",
        "chain_trend": "强势多头",
        "chain_avg_score": 43.0,
        "chain_consistency": 100,
        "aligned": True,
        "z_score": -0.8,
        "z_status": "正常",
        "redundant": False,
        "redundant_with": None,
        "fundamental_notes": [
            "豆粕现货持续累库，全国豆粕库存55.2万吨，环比+2.6%",
            "养殖长期亏损，饲料企业按需少量采购，需求低迷",
            "南美大豆集中到港，油厂高压榨量223万吨/周",
            "豆粕半年报结论：供强需弱，上半年整体承压",
        ],
        "notes": [
            "✅产业链方向一致(强势多头)，但基本面严重偏空",
            "⚠️最大矛盾：BUY信号vs豆粕累库+养殖亏损+大豆到港高峰",
            "contango结构做多不利，展仓成本高",
            "评分仅42偏低，信号强度最弱之一，建议谨慎",
        ],
    },
    "y": {
        "chain": "油脂油料",
        "chain_members": get_chain_members("油脂油料"),
        "term_structure": "contango",
        "chain_trend": "强势多头",
        "chain_avg_score": 43.0,
        "chain_consistency": 100,
        "aligned": True,
        "z_score": -1.0,
        "z_status": "正常",
        "redundant": False,
        "redundant_with": None,
        "fundamental_notes": [
            "豆油持续偏弱，全国一级豆油均价8480元/吨周跌3.85%",
            "南美大豆集中到港+油厂高压榨=豆油持续累库",
            "原油走弱削弱生物燃料需求预期，EPA政策强托底但短期无增量",
        ],
        "notes": [
            "✅产业链方向一致(强势多头)，但基本面严重偏空",
            "⚠️最大矛盾：BUY信号vs豆油累库+压榨高峰+contango结构",
            "评分仅40最低，信号强度最弱，建议观望或排除",
        ],
    },
}

print(json.dumps(final_output, indent=2, ensure_ascii=False))
print("\n###END_CHAIN_ANALYSIS")
