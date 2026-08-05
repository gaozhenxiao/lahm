"""个股分析核心框架：只写经营几项，短、硬。

产品约束：
- 不做技术分析、不做情绪/社媒分析
- 正文只保留：需求 / 竞争 / 产供销 / 量价利 / 股东（如有）/ 中远期重大影响
- 整份合计约 2 页 A4 以内；每维只写要点
"""
from __future__ import annotations

CORE_PILLARS = (
    ("industry_demand", "行业需求及变化"),
    ("competition", "竞争格局及变化"),
    ("ops_chain", "产供销及变化"),
    ("volume_price_profit", "量价利及变化"),
    ("shareholders", "股东变化（如有）"),
    ("mid_long_term", "中远期重大影响因素"),
)

CORE_PILLARS_LIST = "\n".join(
    f"{i}. **{title}**" for i, (_, title) in enumerate(CORE_PILLARS, 1)
)

# 默认分析师：不要技术面(market)、不要情绪/社媒(social)
DEFAULT_SELECTED_ANALYSTS = ["fundamentals", "news"]

LENGTH_BUDGET = """
【篇幅硬约束——约 2 页 A4 以内】
- 全文合计约 1200～1800 汉字（含标题），宁短勿长。
- 禁止结论专章、禁止操作建议专章、禁止估值/目标价、禁止长段散文与套话。
- 禁止技术指标、K线、舆情热度、散户情绪。
- 每节短 bullet，一节最多 3 条。
- 信息不足写「暂无可靠证据」，禁止编造。
""".strip()

CORE_ANALYSIS_RULES = f"""
【分析原则】
- 正文只写这几项：行业需求、竞争格局、产供销、量价利、股东（如有）、中远期重大影响。
- 每条尽量含：现状 / 变化 / 证据（数据、公告或硬新闻）。
- 「中远期重大影响因素」专盯 6～24 个月以上能改写基本面的变量（产能/资本开支、政策与监管、技术路线、大客户/大订单、行业周期拐点、重大并购或股权变动等）；没有就写「未见明确中远期重大变量」。
- 中文。

{LENGTH_BUDGET}
""".strip()

FUNDAMENTALS_REPORT_STRUCTURE = f"""
严格按下列结构写，不要增删章节，不要写「结论」「操作建议」：

# 经营要点

## 一、行业需求及变化
- 至多 3 条

## 二、竞争格局及变化
- 至多 3 条

## 三、产供销及变化
- 至多 3 条

## 四、量价利及变化
- 至多 3 条（尽量有量、价、利数字）

## 五、股东变化（如有）
- 有则 1～2 条；无则「近期未见重大股东变动」

## 六、中远期重大影响因素
- 至多 3 条；只写真正能改写 6～24 个月基本面的因素
- 没有则一句「未见明确中远期重大变量」
""".strip()

NEWS_ANALYSIS_FOCUS = f"""
新闻只服务上述经营几项，不要情绪解读。
- 至多 5 条有实质影响的新闻
- 每条一行：时间 · 事件 · 对应哪一项（需求/竞争/产供销/量价利/股东/中远期）
- 尤其标出可能影响中远期基本面的事件
- 噪音直接忽略
全文不超过约 350 汉字。
""".strip()

RESEARCH_MANAGER_FOCUS = f"""
你输出的是读者唯一需要看的「经营要点」报告。

只保留下列结构，禁止另写结论章、买卖建议章、技术面、情绪面：
{CORE_PILLARS_LIST}

规则：
- 每项 ≤3 条要点；无材料可跳过该项并写「暂无可靠证据」
- 「中远期重大影响因素」必须单独成节：筛有没有 6～24 个月级重大变量；没有就明确写「未见明确中远期重大变量」
- 辩论只提炼证据，不复述长篇

{LENGTH_BUDGET}
""".strip()

BRIEF_AGENT_RULE = (
    "回复必须极短：不超过 200 汉字。"
    "只谈经营几项与中远期重大变量，禁止技术面、情绪面、买卖口号。"
)


def fundamentals_system_tail(currency_name: str, currency_symbol: str) -> str:
    return (
        f"{CORE_ANALYSIS_RULES}\n\n"
        f"{FUNDAMENTALS_REPORT_STRUCTURE}\n\n"
        f"货币单位：{currency_name}（{currency_symbol}）。"
    )
