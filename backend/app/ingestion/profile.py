from __future__ import annotations

import json
import re
from typing import Any

from app.prompts.profile import DOCUMENT_PROFILE_SYSTEM_PROMPT, document_profile_prompt

ABSTRACT_MARKERS = ("abstract", "摘要")
KEYWORD_MARKERS = ("keywords", "key words", "关键词", "关键字")
HEADING_PATTERN = re.compile(r"^(?:#{1,6}\s+|\d+(?:\.\d+)*[、.\s]+)[^\n]{1,80}$")


def extract_abstract(text: str) -> str:
    lines = text.lstrip("\ufeff").splitlines()
    for index, line in enumerate(lines):
        marker = line.strip().lstrip("\ufeff").lstrip("#").strip().lower()
        if marker in ABSTRACT_MARKERS or marker.startswith(("abstract", "摘要")):
            collected: list[str] = []
            for following in lines[index + 1 :]:
                current = following.strip()
                lowered = current.lower()
                if collected and (
                    any(lowered.startswith(word) for word in KEYWORD_MARKERS)
                    or HEADING_PATTERN.match(current)
                ):
                    break
                collected.append(following)
                if len("\n".join(collected)) > 3000:
                    break
            abstract = "\n".join(collected).strip()
            if abstract:
                return abstract
    return ""


def extract_keywords(text: str) -> list[str]:
    for line in text.lstrip("\ufeff").splitlines():
        stripped = line.strip()
        lowered = stripped.lstrip("\ufeff").lower()
        for marker in KEYWORD_MARKERS:
            if lowered.startswith(marker):
                payload = re.split(r"[:：]", stripped, maxsplit=1)
                if len(payload) == 2:
                    parts = re.split(r"[;,；，、]", payload[1])
                    return [item.strip() for item in parts if item.strip()][:20]
    return []


def profile_text(
    title: str,
    keywords: list[str],
    abstract: str,
    profile: dict[str, Any],
) -> str:
    sections = [
        f"标题：{title}",
        f"关键词：{'、'.join(keywords)}" if keywords else "",
        f"摘要：{abstract}" if abstract else "",
        f"一句话概括：{profile.get('one_sentence', '')}",
        f"数据与方法：{profile.get('data_and_method', '')}",
        f"结果与结论：{profile.get('results_conclusion', '')}",
        f"创新与不足：{profile.get('contribution_limitations', '')}",
    ]
    return "\n".join(item for item in sections if item and not item.endswith("："))


def _fallback(title: str, abstract: str) -> dict[str, Any]:
    return {
        "one_sentence": "",
        "data_and_method": "",
        "results_conclusion": "",
        "contribution_limitations": "",
        "keywords": [],
        "region": "",
        "time_range": "",
        "authors": [],
        "year": None,
        "abstract": abstract,
    }


def _parse_json(raw: str) -> dict[str, Any] | None:
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.IGNORECASE)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


async def build_document_profile(
    *,
    title: str,
    full_text: str,
    section_titles: list[str],
    provider: Any,
    model_name: str,
) -> dict[str, Any]:
    abstract = extract_abstract(full_text)
    keywords = extract_keywords(full_text)
    abstract_source = "original" if abstract else "missing"
    result = _fallback(title, abstract)
    result["keywords"] = keywords
    extractor_model = "heuristic"

    if provider is not None:
        excerpt = full_text[:8000]
        try:
            response = await provider.invoke(
                [
                    {"role": "system", "content": DOCUMENT_PROFILE_SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": document_profile_prompt(
                            title, abstract, section_titles, excerpt
                        ),
                    },
                ],
                [],
            )
            parsed = _parse_json(response.content)
        except Exception:
            parsed = None
        if parsed:
            extractor_model = model_name
            for key in (
                "one_sentence",
                "data_and_method",
                "results_conclusion",
                "contribution_limitations",
                "region",
                "time_range",
            ):
                value = parsed.get(key)
                if value:
                    result[key] = str(value)
            if parsed.get("keywords"):
                merged = [str(item).strip() for item in parsed["keywords"] if str(item).strip()]
                result["keywords"] = list(dict.fromkeys([*keywords, *merged]))[:20]
            if parsed.get("authors"):
                result["authors"] = [str(item) for item in parsed["authors"] if str(item).strip()]
            year = parsed.get("year")
            if isinstance(year, int):
                result["year"] = year
            generated_abstract = str(parsed.get("abstract") or "").strip()
            if abstract:
                result["abstract"] = abstract
            elif generated_abstract:
                result["abstract"] = generated_abstract
                abstract_source = "generated"
    if not result.get("abstract"):
        result["abstract"] = ""
    result["abstract_source"] = abstract_source
    result["extractor_model"] = extractor_model
    result["profile_text"] = profile_text(
        title,
        list(result.get("keywords") or []),
        str(result.get("abstract") or ""),
        result,
    )
    return result
