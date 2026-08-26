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
_MERMAID_FLOWCHART_RE = re.compile(r"^\s*flowchart\s+LR\s*$")
_MERMAID_NODE_RE = re.compile(
    r'^\s*(?P<id>[A-Za-z][A-Za-z0-9_]*)\s*\[\s*"(?P<label>.+)"\s*\]\s*$'
)
_MERMAID_EDGE_RE = re.compile(
    r"^\s*(?P<source>[A-Za-z][A-Za-z0-9_]*)\s*"
    r'(?P<arrow><-->|-->)\s*(?:\|"(?P<label>[^"]+)"\|\s*)?'
    r"(?P<target>[A-Za-z][A-Za-z0-9_]*)\s*$"
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


def _render_mermaid_flowchart(lines: list[str]) -> str | None:
    """Render the small, trusted Mermaid LR subset used by the README."""
    content = [line for line in lines if line.strip()]
    if not content or _MERMAID_FLOWCHART_RE.fullmatch(content[0]) is None:
        return None

    nodes: dict[str, list[str]] = {}
    edges: list[tuple[str, str, str, str]] = []
    for line in content[1:]:
        node_match = _MERMAID_NODE_RE.fullmatch(line)
        if node_match is not None:
            label_parts = re.split(r"<br\s*/?>", node_match.group("label"))
            nodes[node_match.group("id")] = [
                _RAW_TAG_RE.sub("", part).strip()
                for part in label_parts
                if part.strip()
            ]
            continue
        edge_match = _MERMAID_EDGE_RE.fullmatch(line)
        if edge_match is not None:
            edges.append(
                (
                    edge_match.group("source"),
                    edge_match.group("target"),
                    edge_match.group("arrow"),
                    edge_match.group("label") or "",
                )
            )
            continue
        return None

    if (
        not nodes
        or not edges
        or any(
            source not in nodes or target not in nodes for source, target, _, _ in edges
        )
    ):
        return None

    ranks = dict.fromkeys(nodes, 0)
    for _ in nodes:
        changed = False
        for source, target, _, _ in edges:
            candidate = ranks[source] + 1
            if candidate > ranks[target]:
                ranks[target] = candidate
                changed = True
        if not changed:
            break

    columns: dict[int, list[str]] = {}
    for node_id in nodes:
        columns.setdefault(ranks[node_id], []).append(node_id)

    node_width = 190
    node_height = 70
    column_gap = 64
    row_gap = 42
    margin = 34
    max_rank = max(columns)
    max_rows = max(len(column) for column in columns.values())
    width = margin * 2 + (max_rank + 1) * node_width + max_rank * column_gap
    height = max(
        350,
        margin * 2 + max_rows * node_height + (max_rows - 1) * row_gap,
    )
    positions: dict[str, tuple[float, float]] = {}
    for rank, column in columns.items():
        group_height = len(column) * node_height + (len(column) - 1) * row_gap
        start_y = (height - group_height) / 2
        for row, node_id in enumerate(column):
            positions[node_id] = (
                margin + rank * (node_width + column_gap),
                start_y + row * (node_height + row_gap),
            )

    svg: list[str] = [
        '<figure class="documentation-flowchart">',
        (
            f'<svg viewBox="0 0 {width} {height}" role="img" '
            'aria-labelledby="documentation-flowchart-title" '
            'preserveAspectRatio="xMidYMid meet">'
        ),
        '<title id="documentation-flowchart-title">FOAMTrame architecture flowchart</title>',
        "<defs>",
        (
            '<marker id="documentation-arrow-end" viewBox="0 0 10 10" '
            'refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
            '<path d="M 0 0 L 10 5 L 0 10 z" /></marker>'
        ),
        "</defs>",
    ]

    for source, target, arrow, label in edges:
        source_x, source_y = positions[source]
        target_x, target_y = positions[target]
        x1 = source_x + node_width
        y1 = source_y + node_height / 2
        x2 = target_x
        y2 = target_y + node_height / 2
        control = max(28, (x2 - x1) * 0.45)
        marker_start = (
            ' marker-start="url(#documentation-arrow-end)"' if arrow == "<-->" else ""
        )
        svg.append(
            f'<path class="documentation-flowchart__edge" d="M {x1} {y1} '
            f'C {x1 + control} {y1}, {x2 - control} {y2}, {x2} {y2}" '
            f'marker-end="url(#documentation-arrow-end)"{marker_start} />'
        )
        if label:
            label_x = (x1 + x2) / 2
            label_y = (y1 + y2) / 2 - 7
            svg.append(
                f'<text class="documentation-flowchart__edge-label" '
                f'x="{label_x}" y="{label_y}">{html_lib.escape(label)}</text>'
            )

    for node_id, label_lines in nodes.items():
        x, y = positions[node_id]
        center_x = x + node_width / 2
        center_y = y + node_height / 2
        svg.append('<g class="documentation-flowchart__node">')
        svg.append(
            f'<rect x="{x}" y="{y}" width="{node_width}" height="{node_height}" '
            'rx="13" ry="13" />'
        )
        first_y = center_y - (len(label_lines) - 1) * 10
        for index, label_line in enumerate(label_lines):
            text_class = (
                "documentation-flowchart__node-title"
                if index == 0
                else "documentation-flowchart__node-detail"
            )
            svg.append(
                f'<text class="{text_class}" x="{center_x}" '
                f'y="{first_y + index * 21}">{html_lib.escape(label_line)}</text>'
            )
        svg.append("</g>")

    svg.extend(
        [
            "</svg>",
            "<figcaption>FOAMTrame components and their validated data flows.</figcaption>",
            "</figure>",
        ]
    )
    return "".join(svg)


def _render_fenced_block(language: str, lines: list[str]) -> str:
    if language.lower() == "mermaid":
        diagram = _render_mermaid_flowchart(lines)
        if diagram is not None:
            return diagram
    language_class = (
        f' class="language-{html_lib.escape(language, quote=True)}"' if language else ""
    )
    return (
        f"<pre><code{language_class}>"
        + html_lib.escape("\n".join(lines))
        + "</code></pre>"
    )


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
                rendered.append(_render_fenced_block(code_language, code_lines))
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
        rendered.append(_render_fenced_block(code_language, code_lines))
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
    with html.Div(
        v_show="active_tab === 6",
        classes="pa-3 documentation-drawer",
        role="region",
        aria_label="Documentation navigation",
    ):
        with html.Div(classes="d-flex align-center mb-1"):
            vuetify.VIcon(
                "mdi-book-open-page-variant", color="cyan darken-3", classes="mr-2"
            )
            html.Div("Documentation", classes="text-subtitle-1 font-weight-bold")
            vuetify.VSpacer()
            with vuetify.VBtn(
                icon=True,
                small=True,
                click=ctrl.reload_documentation,
                title="Reload README",
                aria_label="Reload README documentation",
            ):
                vuetify.VIcon("mdi-refresh", small=True)
        html.P(
            "README sections",
            classes="text-overline text--secondary mb-1",
        )
        with vuetify.VList(
            dense=True,
            nav=True,
            classes="documentation-section-list pa-0",
            aria_label="README sections",
        ):
            with vuetify.VListItem(
                v_for="item in documentation_sections",
                key=("item.value",),
                click="documentation_section = item.value",
                input_value=("documentation_section === item.value",),
                active_class="documentation-section-item--active",
                classes="documentation-section-item px-2",
                aria_current=("documentation_section === item.value ? 'page' : null",),
            ):
                with vuetify.VListItemIcon(classes="documentation-section-marker mr-2"):
                    vuetify.VIcon(
                        "{{ documentation_section === item.value ? 'mdi-chevron-right-circle' : 'mdi-circle-small' }}",
                        x_small=True,
                        color=(
                            "documentation_section === item.value ? 'cyan darken-3' : 'grey lighten-1'",
                        ),
                    )
                vuetify.VListItemTitle(
                    "{{ item.title }}", classes="documentation-section-title"
                )
        html.Div(
            "{{ documentation_status }}",
            classes="documentation-status text-caption mt-1 px-1",
            role="status",
            aria_live="polite",
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
