from pathlib import Path

from tabs.documentation_tab import read_documentation, render_markdown


def test_read_documentation_splits_level_two_sections(tmp_path: Path):
    readme = tmp_path / "README.md"
    readme.write_text(
        "# Demo\n\nIntro.\n\n## Install\n\nRun it.\n\n## Use it\n\nDone.\n",
        encoding="utf-8",
    )

    sections = read_documentation(readme)

    assert [section["title"] for section in sections] == [
        "Overview",
        "Install",
        "Use it",
    ]
    assert sections[1]["value"] == "install"
    assert '<h2 id="install">Install</h2>' in sections[1]["html"]


def test_renderer_supports_readme_structure_and_escapes_raw_html():
    result = render_markdown(
        """## Guide

**Safe** [site](https://example.com) [local](./secret)

| Name | Value |
| --- | --- |
| Port | `8087` |

```python
print("hello")
```

<script>alert("unsafe")</script>
"""
    )

    assert "<strong>Safe</strong>" in result
    assert 'href="https://example.com"' in result
    assert "./secret" not in result
    assert "<table>" in result
    assert 'class="language-python"' in result
    assert "<script>" not in result
    assert "unsafe" in result


def test_repository_readme_has_documentation_extension_sections():
    readme = Path(__file__).resolve().parents[2] / "README.md"
    sections = read_documentation(readme)
    titles = {section["title"] for section in sections}

    assert "Documentation maintenance" in titles
    assert "Extension roadmap" in titles
    assert "Contributing" in titles
