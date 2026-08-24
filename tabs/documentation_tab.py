from __future__ import annotations

import html as html_lib
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from trame.widgets import html, vuetify

README_PATH = Path(__file__).resolve().parents[1] / "README.md"

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_FENCE_RE = re.compile(r"^```\s*([\w+-]*)\s*$")
_LIST_RE = re.compile(r"^\s*([-*+] |\d+\. )(.*)$")
_TABLE_DIVIDER_RE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$")
_RAW_TAG_RE = re.compile(r"<[^>]+>")
_INLINE_TOKEN_RE = re.compile(
    r"!\[([^]]*)\]\(([^)]+)\)|\[([^]]+)\]\(([^)]+)\)|`([^`]+)`|\*\*([^*]+)\*\*"
)


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "section"


def _safe_link(url: str) -> str | None:
    value = url.strip()
    parsed = urlparse(value)
    if value.startswith("#") or parsed.scheme in {"http", "https", "mailto"}:
        return html_lib.escape(value, quote=True)
    return None


def _inline_markdown(value: str) -> str:
    output: list[str] = []
    cursor = 0
    for match in _INLINE_TOKEN_RE.finditer(value):
        output.append(html_lib.escape(value[cursor : match.start()]))
        image_alt, image_url, link_text, link_url, code, strong = match.groups()
        if image_alt is not None:
            safe_url = _safe_link(image_url)
            if safe_url and urlparse(image_url).scheme in {"http", "https"}:
                output.append(
                    f'<img src="{safe_url}" alt="{html_lib.escape(image_alt, quote=True)}" '
                    'loading="lazy">'
                )
            else:
                output.append(html_lib.escape(image_alt))
        elif link_text is not None:
            safe_url = _safe_link(link_url)
            label = html_lib.escape(link_text)
            if safe_url:
                external = not link_url.startswith("#")
                target = (
                    ' target="_blank" rel="noopener noreferrer"' if external else ""
                )
                output.append(f'<a href="{safe_url}"{target}>{label}</a>')
            else:
                output.append(label)
        elif code is not None:
            output.append(f"<code>{html_lib.escape(code)}</code>")
        elif strong is not None:
            output.append(f"<strong>{html_lib.escape(strong)}</strong>")
        cursor = match.end()
    output.append(html_lib.escape(value[cursor:]))
    return "".join(output)


def _table_cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def render_markdown(markdown_text: str) -> str:
    """Render the README subset used by FOAMTrame without trusting raw HTML."""

    lines = markdown_text.splitlines()
    rendered: list[str] = []
    paragraph: list[str] = []
    list_kind: str | None = None
    in_code = False
    code_language = ""
    code_lines: list[str] = []
    index = 0

    def flush_paragraph() -> None:
        if paragraph:
            rendered.append(f"<p>{_inline_markdown(' '.join(paragraph))}</p>")
            paragraph.clear()

    def close_list() -> None:
        nonlocal list_kind
        if list_kind:
            rendered.append(f"</{list_kind}>")
            list_kind = None

    while index < len(lines):
        line = lines[index]
        fence = _FENCE_RE.match(line)
        if fence:
            if in_code:
                language_class = (
                    f' class="language-{html_lib.escape(code_language, quote=True)}"'
                    if code_language
                    else ""
                )
                rendered.append(
                    f"<pre><code{language_class}>"
                    + html_lib.escape("\n".join(code_lines))
                    + "</code></pre>"
                )
                code_lines.clear()
                in_code = False
            else:
                flush_paragraph()
                close_list()
                code_language = fence.group(1)
                in_code = True
            index += 1
            continue
        if in_code:
            code_lines.append(line)
            index += 1
            continue

        heading = _HEADING_RE.match(line)
        if heading:
            flush_paragraph()
            close_list()
            level = len(heading.group(1))
            title = heading.group(2).strip()
            rendered.append(
                f'<h{level} id="{_slugify(title)}">{_inline_markdown(title)}</h{level}>'
            )
            index += 1
            continue

        if (
            index + 1 < len(lines)
            and "|" in line
            and _TABLE_DIVIDER_RE.match(lines[index + 1])
        ):
            flush_paragraph()
            close_list()
            headers = _table_cells(line)
            index += 2
            rows: list[list[str]] = []
            while index < len(lines) and "|" in lines[index] and lines[index].strip():
                rows.append(_table_cells(lines[index]))
                index += 1
            rendered.append('<div class="documentation-table-wrap"><table><thead><tr>')
            rendered.extend(f"<th>{_inline_markdown(cell)}</th>" for cell in headers)
            rendered.append("</tr></thead><tbody>")
            for row in rows:
                rendered.append("<tr>")
                rendered.extend(f"<td>{_inline_markdown(cell)}</td>" for cell in row)
                rendered.append("</tr>")
            rendered.append("</tbody></table></div>")
            continue

        list_item = _LIST_RE.match(line)
        if list_item:
            flush_paragraph()
            requested_kind = "ol" if list_item.group(1)[0].isdigit() else "ul"
            if list_kind != requested_kind:
                close_list()
                rendered.append(f"<{requested_kind}>")
                list_kind = requested_kind
            rendered.append(f"<li>{_inline_markdown(list_item.group(2))}</li>")
            index += 1
            continue

        if line.startswith(">"):
            flush_paragraph()
            close_list()
            rendered.append(
                f"<blockquote>{_inline_markdown(line.lstrip('> '))}</blockquote>"
            )
            index += 1
            continue

        if not line.strip():
            flush_paragraph()
            close_list()
        elif line.lstrip().startswith("<"):
            # README presentation HTML is intentionally not trusted by v-html.
            text = _RAW_TAG_RE.sub("", line).strip()
            if text:
                paragraph.append(text)
        else:
            paragraph.append(line.strip())
        index += 1

    if in_code:
        rendered.append(
            "<pre><code>" + html_lib.escape("\n".join(code_lines)) + "</code></pre>"
        )
    flush_paragraph()
    close_list()
    return "\n".join(rendered)


def read_documentation(path: Path = README_PATH) -> list[dict[str, str]]:
    """Read README.md and split it into selectable top-level sections."""

    source = path.read_text(encoding="utf-8")
    sections: list[dict[str, str]] = []
    title = "Overview"
    section_lines: list[str] = []
    used_slugs: set[str] = set()

    def append_section() -> None:
        nonlocal section_lines
        body = "\n".join(section_lines).strip()
        if not body:
            section_lines = []
            return
        base_slug = _slugify(title)
        slug = base_slug
        suffix = 2
        while slug in used_slugs:
            slug = f"{base_slug}-{suffix}"
            suffix += 1
        used_slugs.add(slug)
        if title == "Overview":
            body = "# FOAMTrame Documentation\n\n" + body
        sections.append({"title": title, "value": slug, "html": render_markdown(body)})
        section_lines = []

    for line in source.splitlines():
        if line.startswith("## "):
            append_section()
            title = line[3:].strip()
            section_lines = [line]
        else:
            section_lines.append(line)
    append_section()
    return sections


def setup_documentation_tab(server):
    state, ctrl = server.state, server.controller
    sections: list[dict[str, str]] = []

    def publish_documentation(selected: str | None = None) -> None:
        nonlocal sections
        try:
            sections = read_documentation()
            options = [
                {"title": item["title"], "value": item["value"]} for item in sections
            ]
            values = {item["value"] for item in sections}
            selected_value = selected if selected in values else sections[0]["value"]
            current = next(item for item in sections if item["value"] == selected_value)
            state.documentation_sections = options
            state.documentation_section = selected_value
            state.documentation_html = current["html"]
            state.documentation_status = (
                f"README.md loaded · {len(sections)} sections · "
                f"{datetime.now().astimezone().strftime('%H:%M:%S')}"
            )
            state.documentation_status_color = "success"
        except (OSError, UnicodeError, ValueError) as exc:
            sections = []
            state.documentation_sections = []
            state.documentation_html = (
                "<h2>Documentation unavailable</h2><p>"
                + html_lib.escape(str(exc))
                + "</p>"
            )
            state.documentation_status = "README.md could not be loaded."
            state.documentation_status_color = "error"
        state.flush()

    state.setdefault("documentation_sections", [])
    state.setdefault("documentation_section", "overview")
    state.setdefault("documentation_html", "")
    state.setdefault("documentation_status", "Loading README.md…")
    state.setdefault("documentation_status_color", "info")
    publish_documentation(state.documentation_section)

    @state.change("documentation_section")
    def select_documentation_section(documentation_section, **_):
        match = next(
            (item for item in sections if item["value"] == documentation_section),
            None,
        )
        if match:
            state.documentation_html = match["html"]
            state.dirty("documentation_html")
            state.flush()

    ctrl.reload_documentation = lambda: publish_documentation(
        state.documentation_section
    )


def build_documentation_drawer(ctrl):
    with html.Div(v_show="active_tab === 6", classes="pa-4 documentation-drawer"):
        with html.Div(classes="d-flex align-center mb-3"):
            vuetify.VIcon(
                "mdi-book-open-page-variant", color="cyan darken-3", classes="mr-2"
            )
            html.Div("Documentation", classes="text-subtitle-1 font-weight-bold")
        html.P(
            "Browse the project README by section. Refresh after editing README.md.",
            classes="text-caption mb-4",
        )
        vuetify.VSelect(
            v_model=("documentation_section", "overview"),
            items=("documentation_sections", []),
            item_text="title",
            item_value="value",
            label="README section",
            outlined=True,
            dense=True,
            hide_details=True,
            classes="mb-4",
        )
        vuetify.VBtn(
            "Reload README",
            click=ctrl.reload_documentation,
            outlined=True,
            block=True,
            classes="mb-4",
        )
        vuetify.VAlert(
            "{{ documentation_status }}",
            type=("documentation_status_color", "info"),
            dense=True,
            outlined=True,
        )


def build_documentation_content():
    with vuetify.VContainer(
        fluid=True,
        classes="pa-4 pa-sm-6 documentation-page",
        v_if="active_tab === 6",
    ):
        with vuetify.VCard(classes="glass-card documentation-card pa-5 pa-sm-8"):
            html.Div(
                v_html=("documentation_html", ""),
                classes="documentation-content",
            )
