from pathlib import Path

import pytest

from app.skills.catalog import SkillCatalog


def test_skill_progressive_load_and_permission_intersection(tmp_path: Path) -> None:
    config = tmp_path / "config" / "skills.yaml"
    root = tmp_path / "skills" / "review"
    root.mkdir(parents=True)
    config.parent.mkdir(exist_ok=True)
    config.write_text("roots: [./skills]\nenabled: [review]\n", encoding="utf-8")
    (root / "SKILL.md").write_text(
        "---\nname: review\ndescription: 文献综述\nversion: 1\n"
        "allowed_tools: [search_notebook, dangerous]\n---\n完整指令",
        encoding="utf-8",
    )
    catalog = SkillCatalog(config)
    catalog.reload({"search_notebook", "dangerous"})
    assert catalog.summaries() == [{"name": "review", "description": "文献综述", "version": "1"}]
    loaded = catalog.load("review", {"search_notebook"})
    assert loaded["instructions"] == "完整指令"
    assert loaded["allowed_tools"] == ["search_notebook"]


def test_skill_unknown_tool_is_rejected(tmp_path: Path) -> None:
    config = tmp_path / "skills.yaml"
    root = tmp_path / "skills" / "bad"
    root.mkdir(parents=True)
    config.write_text("roots: [./skills]\nenabled: [bad]\n", encoding="utf-8")
    (root / "SKILL.md").write_text(
        "---\nname: bad\ndescription: bad\nallowed_tools: [missing]\n---\nbody",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unknown tools"):
        SkillCatalog(config).reload({"search_notebook"})
