from app.agent.context_builder import ContextBuilder, estimate_tokens, split_attachment
from app.agent.types import AgentState, AttachmentPayload, QueryEnvelope
from app.core.config import Settings


def payload(text: str) -> AttachmentPayload:
    return AttachmentPayload(
        document_id="doc-1",
        document_version_id="version-1",
        name="paper.txt",
        media_type="text/plain",
        instruction="逐段比较",
        text=text,
        page_ranges=[
            {
                "char_start": 0,
                "char_end": len(text),
                "page_start": 1,
                "page_end": 9,
            }
        ],
    )


def state() -> AgentState:
    return AgentState(run_id="run", notebook_id="notebook", user_id="user")


def test_attachment_split_has_no_gap_or_loss() -> None:
    text = ("第一段。\n\nSecond paragraph with a method and dataset.\n" * 500).strip()
    windows = split_attachment(payload(text), 500)
    assert len(windows) > 1
    assert windows[0].char_start == 0
    assert windows[-1].char_end == len(text)
    assert all(
        left.char_end == right.char_start for left, right in zip(windows, windows[1:], strict=False)
    )
    assert "".join(item.text for item in windows) == text


def test_full_attachment_is_one_user_message_when_it_fits() -> None:
    settings = Settings(
        model_context_window=20_000,
        max_output_tokens=1_000,
        context_safety_ratio=0.95,
    )
    attachment = payload("完整正文" * 100)
    packets = ContextBuilder(settings).build_packets(
        QueryEnvelope("请分析", [attachment]), history=[], summary=None, state=state()
    )
    assert len(packets) == 1
    assert packets[0].manifest.mode == "single"
    assert attachment.text in packets[0].messages[-1]["content"]
    assert packets[0].manifest.attachments[0]["char_end"] == len(attachment.text)


def test_oversized_attachment_is_fully_windowed() -> None:
    settings = Settings(
        model_context_window=3_000,
        max_output_tokens=300,
        context_safety_ratio=0.9,
    )
    attachment = payload("论文内容。" * 4_000)
    packets = ContextBuilder(settings).build_packets(
        QueryEnvelope("总结所有内容", [attachment]), history=[], summary=None, state=state()
    )
    assert len(packets) > 1
    assert all(item.manifest.mode == "windowed" for item in packets)
    assert (
        "".join(item.attachment_window.text for item in packets if item.attachment_window)
        == attachment.text
    )
    assert all("总结所有内容" in item.messages[-1]["content"] for item in packets)


def test_oversized_raw_query_is_fully_windowed() -> None:
    settings = Settings(
        model_context_window=3_000,
        max_output_tokens=300,
        context_safety_ratio=0.9,
    )
    query = "这是用户直接粘贴的长文章。" * 3_000
    packets = ContextBuilder(settings).build_packets(
        QueryEnvelope(query), history=[], summary=None, state=state()
    )
    assert len(packets) > 1
    assert (
        "".join(item.attachment_window.text for item in packets if item.attachment_window) == query
    )


def test_chinese_windows_never_exceed_text_budget() -> None:
    windows = split_attachment(payload("中文论文内容。" * 4_000), 1_000)
    assert len(windows) > 1
    assert all(estimate_tokens(item.text) <= 1_000 for item in windows)


def test_attachment_switches_to_windows_before_effective_budget_is_full() -> None:
    settings = Settings(
        model_context_window=4_000,
        max_output_tokens=400,
        context_safety_ratio=1.0,
    )
    attachment = payload("中" * 3_500)
    packets = ContextBuilder(settings).build_packets(
        QueryEnvelope("分析", [attachment]), history=[], summary=None, state=state()
    )
    assert len(packets) > 1
    assert all(item.manifest.estimated_tokens <= 3_800 for item in packets)
