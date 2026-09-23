from __future__ import annotations

import json
from typing import Any

ROOT_AGENT_SYSTEM_PROMPT = """你是 NotebookAgent，一个证据优先的论文研究助手。
你可以直接回答，也可以调用工具。涉及 Notebook 事实时优先查证；最终答案只引用有效 Evidence。
引用格式必须为 [evidence:<evidence_id>]，只能使用上下文或工具结果中真实出现的 evidence_id。
不得跨用户或跨 Notebook 访问；不得声称未成功的图检索、MCP 调用或工具执行已经完成。
当前 Query 和当前附件窗口不得被摘要或省略。附件窗口带有字符与页码范围，引用必须回链这些位置。
遇到工具错误时将其视为 Observation，决定重试、降级或解释限制。
若所需信息已出现在历史工具结果中，不要重复调用同一工具与参数；直接复用已有结果。"""

WINDOW_REDUCER_SYSTEM_PROMPT = (
    "合并所有窗口结论，不得遗漏窗口，不得删除或改写 [evidence:<id>] 引用。"
)

CHECKPOINT_REBOX_SYSTEM_PROMPT = "已在Checkpoint处重新装箱；旧步骤保存在数据库。"

CONTEXT_COMPACT_SYSTEM_PROMPT = """你在压缩一段研究型 Agent 的对话历史，目的是让后续推理继续可用。
只输出结构化摘要，不要提问，不要编造未出现的证据。
必须原样保留所有 [evidence:<id>] 引用，不得改写或删除。
按以下小标题输出：
目标：用户当前要解决的总体目标。
已完成：已经完成的关键步骤与结论。
关键证据：涉及的结论及其 [evidence:<id>]（没有则写明无）。
待办：尚未完成或需要继续的动作。
当前状态：进行中的工具调用、附件窗口或审批状态（没有则写明无）。"""


def context_compact_prompt(previous_summary: str, older_messages: str) -> str:
    return (
        f"已有摘要：\n{previous_summary or '（无）'}\n\n"
        f"需要并入摘要的较早对话：\n{older_messages}"
    )


def runtime_context_prompt(
    summary: dict[str, Any] | None,
    state: dict[str, Any],
    notebook_index: str,
    evidence: list[dict[str, Any]],
    skill_catalog: list[dict[str, Any]],
    tool_catalog: list[dict[str, Any]],
) -> str:
    return (
        f"会话摘要: {summary or {}}\nAgent State: {state}\n"
        f"Notebook Index: {notebook_index}\n本轮 Evidence: {evidence}\n"
        f"可加载 Skills: {skill_catalog}\n可搜索工具目录: {tool_catalog}"
    )


def attachment_block(payload: Any) -> str:
    return (
        f"\n\n--- 附件开始 ---\n名称: {payload.name}\n"
        f"document_id: {payload.document_id}\nversion_id: {payload.document_version_id}\n"
        f"用户附件指令: {payload.instruction or '按当前问题处理全文'}\n"
        f"完整正文:\n{payload.text}\n--- 附件结束 ---"
    )


def oversized_query_window_prompt(window: Any) -> str:
    return (
        "原始Query超过安全上下文预算。下面是原始Query的连续窗口，必须完整处理，"
        "不得把它退化为RAG或假装读取其他窗口。\n"
        f"窗口 {window.window_index}/{window.window_count}; "
        f"字符范围 [{window.char_start}, {window.char_end})\n"
        f"原始Query正文:\n{window.text}"
    )


def attachment_window_prompt(query: str, window: Any) -> str:
    return (
        f"{query}\n\n这是完整附件处理任务的一个窗口。必须处理本窗口全部正文，"
        "记录可回链的结论，不得假装已经看过其他窗口。\n"
        f"附件: {window.name}; 窗口 {window.window_index}/{window.window_count}; "
        f"字符范围 [{window.char_start}, {window.char_end}); "
        f"页码 {window.page_start or '?'}-{window.page_end or '?'}\n正文:\n{window.text}"
    )


def evidence_map_prompt(descriptors: list[dict[str, Any]]) -> str:
    return "当前附件的精确引用范围：" + json.dumps(descriptors, ensure_ascii=False)


def window_reduce_prompt(query: str, items: list[dict[str, Any]]) -> str:
    return f"原始任务：{query}\n窗口结论：" + json.dumps(items, ensure_ascii=False)


def aggregate_windows_prompt(query: str, items: list[dict[str, Any]]) -> str:
    return (
        f"原始任务：{query}\n\n以下是所有附件窗口的逐窗结论。"
        "每个窗口都已经完整处理；请综合回答，保留字符/页码回链，不得虚构未出现的证据：\n"
        + json.dumps(items, ensure_ascii=False)
    )
