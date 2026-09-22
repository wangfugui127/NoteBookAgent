from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True, slots=True)
class SkillManifest:
    name: str
    description: str
    version: str
    allowed_tools: tuple[str, ...]
    path: Path
    body: str

    def summary(self) -> dict[str, str]:
        return {"name": self.name, "description": self.description, "version": self.version}


def _frontmatter(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---\n"):
        raise ValueError("SKILL.md must start with YAML frontmatter")
    marker = text.find("\n---\n", 4)
    if marker < 0:
        raise ValueError("SKILL.md frontmatter is not closed")
    metadata = yaml.safe_load(text[4:marker]) or {}
    return metadata, text[marker + 5 :].strip()


class SkillCatalog:
    def __init__(self, config_path: Path) -> None:
        self.config_path = config_path
        self.skills: dict[str, SkillManifest] = {}

    def reload(self, known_tools: set[str] | None = None) -> list[SkillManifest]:
        config = yaml.safe_load(self.config_path.read_text(encoding="utf-8")) or {}
        enabled = set(config.get("enabled") or [])
        roots = config.get("roots") or []
        loaded: dict[str, SkillManifest] = {}
        for root_value in roots:
            configured = Path(root_value)
            if configured.is_absolute():
                root = configured
            else:
                project_relative = (self.config_path.parent.parent / configured).resolve()
                config_relative = (self.config_path.parent / configured).resolve()
                root = project_relative if project_relative.exists() else config_relative
            if not root.exists():
                continue
            for path in sorted(root.glob("*/SKILL.md")):
                metadata, body = _frontmatter(path.read_text(encoding="utf-8"))
                name = str(metadata.get("name") or path.parent.name)
                if name not in enabled:
                    continue
                description = str(metadata.get("description") or "").strip()
                if not description:
                    raise ValueError(f"skill {name} has no description")
                if name in loaded:
                    raise ValueError(f"duplicate skill id: {name}")
                allowed = tuple(str(value) for value in metadata.get("allowed_tools") or [])
                unknown = set(allowed) - (known_tools or set(allowed))
                if unknown:
                    raise ValueError(f"skill {name} references unknown tools: {sorted(unknown)}")
                loaded[name] = SkillManifest(
                    name=name,
                    description=description,
                    version=str(metadata.get("version") or "1"),
                    allowed_tools=allowed,
                    path=path,
                    body=body,
                )
        missing = enabled - loaded.keys()
        if missing:
            raise ValueError(f"enabled skills not found: {sorted(missing)}")
        self.skills = loaded
        return list(loaded.values())

    def summaries(self) -> list[dict[str, str]]:
        return [item.summary() for item in self.skills.values()]

    def load(self, name: str, user_allowed_tools: set[str]) -> dict[str, Any]:
        skill = self.skills.get(name)
        if not skill:
            raise KeyError(f"unknown skill: {name}")
        effective_tools = sorted(set(skill.allowed_tools) & user_allowed_tools)
        references_root = (skill.path.parent / "references").resolve()
        references: dict[str, str] = {}
        referenced_paths = re.findall(r"(?:\(|\s)(references/[A-Za-z0-9._/-]+)", skill.body)
        for relative in list(dict.fromkeys(referenced_paths))[:10]:
            target = (skill.path.parent / relative).resolve()
            if references_root not in target.parents or not target.is_file():
                continue
            references[relative] = target.read_text(encoding="utf-8")[:50_000]
        return {
            **skill.summary(),
            "instructions": skill.body,
            "allowed_tools": effective_tools,
            "references": references,
        }
