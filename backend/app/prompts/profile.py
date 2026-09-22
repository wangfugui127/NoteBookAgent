from __future__ import annotations

DOCUMENT_PROFILE_SYSTEM_PROMPT = """你在为学术论文建立检索画像。
只返回一个 JSON 对象，不要输出多余文字或代码块标记。
JSON 字段：
- one_sentence: 一句话概括：研究什么问题、用了什么方法、得到什么结论
- data_and_method: 数据与方法：数据来源、研究区域、时间范围、实验流程和模型
- results_conclusion: 结果与结论：关键结果、具体指标、相比基线提升多少
- contribution_limitations: 创新与不足：主要贡献、适用范围和局限性
- keywords: 字符串数组
- region: 研究地区，没有则空字符串
- time_range: 时间范围，没有则空字符串
- authors: 作者字符串数组
- year: 发表年份整数，未知则为 null
- abstract: 论文原始摘要。若用户消息已提供摘要，原样保留；否则用一段忠实概括填充
只依据提供的论文内容，不得编造未出现的数据或结论。"""


def document_profile_prompt(
    title: str,
    abstract: str,
    section_titles: list[str],
    excerpt: str,
) -> str:
    return (
        f"标题：{title}\n"
        f"已知摘要：{abstract or '（原文未检测到，请依据正文概括）'}\n"
        f"章节标题：{'、'.join(section_titles[:40]) or '（无）'}\n"
        f"正文节选：\n{excerpt}"
    )
