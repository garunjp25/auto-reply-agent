from pathlib import Path

import pytest

from auto_reply.sources.wiki_loader import WikiLoader


def test_loads_all_md_files(tmp_path: Path):
    (tmp_path / "alpha.md").write_text("# Alpha\n\nAlpha body.\n", encoding="utf-8")
    (tmp_path / "beta.md").write_text("# Beta\n\nBeta body.\n", encoding="utf-8")

    loader = WikiLoader(tmp_path)
    out = loader.load_all()

    assert set(out.keys()) == {"alpha", "beta"}
    assert "Alpha body" in out["alpha"]
    assert "Beta body" in out["beta"]


def test_concatenated_uses_horizontal_rule_separators(tmp_path: Path):
    (tmp_path / "alpha.md").write_text("Alpha", encoding="utf-8")
    (tmp_path / "beta.md").write_text("Beta", encoding="utf-8")

    loader = WikiLoader(tmp_path)
    text = loader.concatenated()
    assert "Alpha" in text
    assert "Beta" in text
    assert "---" in text or "\n\n" in text


def test_missing_directory_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        WikiLoader(tmp_path / "nope").load_all()


def test_empty_directory_returns_empty_dict(tmp_path: Path):
    loader = WikiLoader(tmp_path)
    assert loader.load_all() == {}
    assert loader.concatenated() == ""
