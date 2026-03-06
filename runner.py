"""
arXiv Tool Runner — Generates an inline HTML carousel card.

One paper per slide with title, authors, primary category, abstract excerpt,
and links to the abstract page and PDF.
JS wiring via [data-carousel] convention in tool_result.js.
Outputs IPC contract: {"text": str, "html": str, "results": [...], "_meta": {...}}
"""

import sys
import json
import base64
from html import escape
from handler import execute


# ── Radiant palette ───────────────────────────────────────────────────────────

_ACCENT = "#B31B1B"          # arXiv red/maroon
_ACCENT_BG = "rgba(179,27,27,0.15)"
_TEXT_PRIMARY = "#eae6f2"
_TEXT_SECONDARY = "rgba(234,230,242,0.58)"
_TEXT_TERTIARY = "rgba(234,230,242,0.38)"
_SURFACE = "rgba(255,255,255,0.04)"
_BORDER = "rgba(255,255,255,0.07)"
_DOT_ACTIVE = "#8A5CFF"
_DOT_INACTIVE = "rgba(255,255,255,0.25)"
_CAT_BG = "rgba(179,27,27,0.12)"


# ── SVG icons ─────────────────────────────────────────────────────────────────

_LINK_ICON = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="11" height="11" viewBox="0 0 24 24" '
    'fill="none" stroke="currentColor" stroke-width="2.5" '
    'stroke-linecap="round" stroke-linejoin="round" '
    'style="vertical-align:middle;flex-shrink:0;">'
    '<path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>'
    '<polyline points="15 3 21 3 21 9"/>'
    '<line x1="10" y1="14" x2="21" y2="3"/>'
    '</svg>'
)

_CHEVRON_LEFT = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" '
    'fill="none" stroke="currentColor" stroke-width="2.5" '
    'stroke-linecap="round" stroke-linejoin="round">'
    '<polyline points="15 18 9 12 15 6"/>'
    '</svg>'
)

_CHEVRON_RIGHT = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" '
    'fill="none" stroke="currentColor" stroke-width="2.5" '
    'stroke-linecap="round" stroke-linejoin="round">'
    '<polyline points="9 18 15 12 9 6"/>'
    '</svg>'
)


# ── Utilities ─────────────────────────────────────────────────────────────────

def _format_authors(authors: list) -> str:
    """Format author list: first 3 names, then 'et al.' if more."""
    if not authors:
        return ""
    if len(authors) <= 3:
        return ", ".join(authors)
    return ", ".join(authors[:3]) + " et al."


def _format_date(iso: str) -> str:
    """Shorten ISO 8601 date to YYYY-MM-DD."""
    return iso[:10] if iso else ""


# ── Slide rendering ───────────────────────────────────────────────────────────

def _render_slide(result: dict, visible: bool) -> str:
    title = result.get("title") or ""
    authors = result.get("authors", [])
    abstract = result.get("abstract") or ""
    url = result.get("url") or ""
    pdf_url = result.get("pdf_url") or ""
    primary_category = result.get("primary_category") or ""
    published = result.get("published") or ""
    display = "flex" if visible else "none"

    # Category pill + published date
    cat_html = ""
    if primary_category:
        cat_html = (
            f'<span style="background:{_CAT_BG};color:{_ACCENT};'
            f'font-size:10px;font-weight:600;border-radius:3px;padding:1px 7px;'
            f'margin-right:6px;">{escape(primary_category)}</span>'
        )
    date_str = _format_date(published)
    meta_html = (
        f'<div style="display:flex;align-items:center;'
        f'font-size:11px;margin-bottom:6px;flex-wrap:wrap;">'
        + cat_html
        + (f'<span style="color:{_TEXT_TERTIARY};">{date_str}</span>' if date_str else "")
        + '</div>'
    )

    # Authors line
    authors_html = ""
    authors_str = _format_authors(authors)
    if authors_str:
        authors_html = (
            f'<div style="font-size:11px;color:{_TEXT_SECONDARY};margin-bottom:6px;">'
            f'{escape(authors_str)}</div>'
        )

    # Abstract excerpt
    abstract_html = ""
    if abstract:
        excerpt = abstract[:280] + ("\u2026" if len(abstract) > 280 else "")
        abstract_html = (
            f'<p style="font-size:13px;color:{_TEXT_SECONDARY};'
            f'line-height:1.55;margin:0 0 8px 0;">{escape(excerpt)}</p>'
        )

    # Dual links: abstract + PDF
    links_html = '<div style="display:flex;gap:10px;flex-wrap:wrap;">'
    if url:
        links_html += (
            f'<a href="{escape(url)}" target="_blank" rel="noopener noreferrer" '
            f'style="display:inline-flex;align-items:center;gap:5px;'
            f'color:{_ACCENT};font-size:12px;text-decoration:none;opacity:0.85;">'
            + _LINK_ICON + '<span>Abstract</span></a>'
        )
    if pdf_url:
        links_html += (
            f'<a href="{escape(pdf_url)}" target="_blank" rel="noopener noreferrer" '
            f'style="display:inline-flex;align-items:center;gap:5px;'
            f'color:{_TEXT_SECONDARY};font-size:12px;text-decoration:none;opacity:0.75;">'
            + _LINK_ICON + '<span>PDF</span></a>'
        )
    links_html += '</div>'

    return (
        f'<div data-slide '
        f'style="display:{display};flex-direction:column;'
        f'padding:13px 15px;background:{_SURFACE};'
        f'border-radius:9px;border:1px solid {_BORDER};">'
        + meta_html
        + f'<div style="font-weight:600;font-size:14px;color:{_TEXT_PRIMARY};'
          f'line-height:1.3;margin-bottom:5px;">{escape(title)}</div>'
        + authors_html
        + abstract_html
        + links_html
        + '</div>'
    )


# ── Navigation ────────────────────────────────────────────────────────────────

def _render_navigation(count: int) -> str:
    btn_style = (
        f"background:{_SURFACE};border:1px solid rgba(255,255,255,0.12);"
        "border-radius:50%;width:28px;height:28px;display:inline-flex;align-items:center;"
        "justify-content:center;cursor:pointer;color:rgba(234,230,242,0.7);padding:0;"
        "flex-shrink:0;outline:none;"
        "transition:background 220ms ease,border-color 220ms ease,color 220ms ease;"
    )
    dots = "".join(
        f'<span data-dot style="'
        + (
            f"width:7px;height:7px;border-radius:50%;background:{_DOT_ACTIVE};"
            "transform:scale(1.2);flex-shrink:0;cursor:pointer;transition:all 220ms ease;"
            if i == 0 else
            f"width:7px;height:7px;border-radius:50%;background:{_DOT_INACTIVE};"
            "flex-shrink:0;cursor:pointer;transition:all 220ms ease;"
        )
        + '"></span>'
        for i in range(count)
    )
    return (
        '<div style="display:flex;align-items:center;justify-content:center;'
        'gap:8px;margin-top:10px;">'
        + f'<button type="button" data-prev style="{btn_style}">{_CHEVRON_LEFT}</button>'
        + f'<div style="display:flex;align-items:center;gap:5px;">{dots}</div>'
        + f'<button type="button" data-next style="{btn_style}">{_CHEVRON_RIGHT}</button>'
        + '</div>'
    )


# ── Card assembly ─────────────────────────────────────────────────────────────

def _render_html(results: list) -> str:
    results = results[:8]
    if not results:
        return (
            f'<p style="color:{_TEXT_TERTIARY};font-size:13px;'
            f'font-family:system-ui,-apple-system,sans-serif;padding:12px 14px;margin:0;">'
            f'No arXiv papers found.</p>'
        )
    slides = "".join(_render_slide(r, i == 0) for i, r in enumerate(results))
    nav = _render_navigation(len(results)) if len(results) > 1 else ""
    return (
        '<div data-carousel '
        'style="font-family:system-ui,-apple-system,sans-serif;">'
        + slides + nav + '</div>'
    )


# ── Text for LLM synthesis ────────────────────────────────────────────────────

def _format_text(results: list, query: str) -> str:
    if not results:
        return f'No arXiv papers found for "{query}". Try a broader query or omit the category filter.'
    lines = [f'arXiv papers for "{query}":']
    for i, r in enumerate(results, 1):
        lines.append(f"\n{i}. {r.get('title', '')}")
        if authors := r.get("authors", []):
            lines.append(f"   Authors: {_format_authors(authors)}")
        if cat := r.get("primary_category", ""):
            lines.append(f"   Category: {cat}")
        if pub := r.get("published", ""):
            lines.append(f"   Published: {_format_date(pub)}")
        if abstract := r.get("abstract", ""):
            lines.append(f"   {abstract[:300]}")
        if url := r.get("url", ""):
            lines.append(f"   Abstract: {url}")
        if pdf := r.get("pdf_url", ""):
            lines.append(f"   PDF: {pdf}")
    return "\n".join(lines)


# ── Entry point ───────────────────────────────────────────────────────────────

payload = json.loads(base64.b64decode(sys.argv[1]))
params = payload.get("params", {})
settings = payload.get("settings", {})
telemetry = payload.get("telemetry", {})

result = execute(topic="", params=params, config=settings, telemetry=telemetry)
results = result.get("results", [])

output = {
    "results": results,
    "count": result.get("count", 0),
    "text": _format_text(results, params.get("query", "")),
    "html": _render_html(results) if results else None,
    "_meta": result.get("_meta", {}),
}
if "error" in result:
    output["error"] = result["error"]

print(json.dumps(output))
