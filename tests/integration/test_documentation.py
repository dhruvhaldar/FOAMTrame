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

**Safe** [site](https://example.com) [license](./LICENSE) [unsafe](../secret)

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
    assert 'href="https://github.com/dhruvhaldar/FOAMTrame/blob/main/LICENSE"' in result
    assert "../secret" not in result
    assert "<table>" in result
    assert 'class="language-python"' in result
    assert "<script>" not in result
    assert "unsafe" in result


def test_renderer_uses_raw_repository_url_only_for_relative_images():
    result = render_markdown(
        "![FOAMTrame](./static/icons/logo.svg) [logo source](./static/icons/logo.svg)"
    )

    assert (
        'src="https://raw.githubusercontent.com/dhruvhaldar/FOAMTrame/'
        'main/static/icons/logo.svg"' in result
    )
    assert (
        'href="https://github.com/dhruvhaldar/FOAMTrame/blob/'
        'main/static/icons/logo.svg"' in result
    )


def test_repository_readme_has_documentation_extension_sections():
    readme = Path(__file__).resolve().parents[2] / "README.md"
    sections = read_documentation(readme)
    titles = {section["title"] for section in sections}

    assert "Documentation maintenance" in titles
    assert "Extension roadmap" in titles
    assert "Contributing" in titles


def test_renderer_turns_supported_mermaid_flowchart_into_accessible_svg():
    result = render_markdown(
        """## Architecture

```mermaid
flowchart LR
    Browser["Browser UI<br>Vue"]
    Server["Server<br>Trame"]
    Browser <-->|"wslink"| Server
```
"""
    )

    assert "<svg viewBox=" in result
    assert 'role="img"' in result
    assert "FOAMTrame architecture flowchart" in result
    assert "Browser UI" in result
    assert "wslink" in result
    assert 'class="language-mermaid"' not in result


def test_renderer_safely_falls_back_for_unsupported_mermaid():
    result = render_markdown(
        """```mermaid
sequenceDiagram
    User->>App: Open
```
"""
    )

    assert 'class="language-mermaid"' in result
    assert "sequenceDiagram" in result
