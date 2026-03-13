"""
arXiv Tool Handler — Academic paper search via the official arXiv API.

Uses the Atom/XML feed from export.arxiv.org/api/query.
No API key required; polite rate limit is 1 request per 3 seconds.
Parses Atom 1.0 with stdlib xml.etree.ElementTree — no extra dependencies.
"""

import logging
import re
import time
import xml.etree.ElementTree as ET

import requests

logger = logging.getLogger(__name__)

_ARXIV_API = "https://export.arxiv.org/api/query"
_ATOM_NS = "http://www.w3.org/2005/Atom"
_ARXIV_NS = "http://arxiv.org/schemas/atom"

_SORT_MAP = {
    "relevance": "relevance",
    "submitted": "submittedDate",
    "updated": "lastUpdatedDate",
}

_POLITE_DELAY = 3.0  # arXiv asks for 1 req/3s
_last_call = 0.0


def execute(topic: str, params: dict, config: dict = None, telemetry: dict = None) -> dict:
    """
    Search arXiv for academic papers and return structured results.

    Args:
        topic: Conversation topic (unused directly)
        params: {
            "query": str (required),
            "limit": int (optional, default 5, clamped 1-8),
            "sort": str (optional: relevance/submitted/updated),
            "category": str (optional: cs.AI, cs.LG, physics, math, etc.)
        }
        config: Tool config (unused — no API key needed)
        telemetry: Client telemetry (unused)

    Returns:
        {
            "results": [{"title", "authors", "abstract", "url", "pdf_url",
                         "published", "updated", "categories", "primary_category"}],
            "count": int,
            "_meta": {observability fields}
        }
    """
    query = (params.get("query") or "").strip()
    if not query:
        return {"results": [], "count": 0, "_meta": {}}

    limit = max(1, min(8, int(params.get("limit") or 5)))
    sort_key = (params.get("sort") or "relevance").strip().lower()
    sort_by = _SORT_MAP.get(sort_key, "relevance")
    category = (params.get("category") or "").strip()

    t0 = time.time()
    results, error = _search_arxiv(query, limit, sort_by, category)
    fetch_latency_ms = int((time.time() - t0) * 1000)

    if error and not results:
        logger.error(
            '{"event":"arxiv_fetch_error","query":"%s","error":"%s","latency_ms":%d}',
            query, str(error)[:120], fetch_latency_ms,
        )
        return {"results": [], "count": 0, "error": str(error)[:200], "_meta": {}}

    logger.info(
        '{"event":"arxiv_search_ok","query":"%s","count":%d,"sort":"%s","latency_ms":%d}',
        query, len(results), sort_by, fetch_latency_ms,
    )

    return {
        "results": results,
        "count": len(results),
        "_meta": {
            "fetch_latency_ms": fetch_latency_ms,
            "sort_mode": sort_key,
            "category_filter": category or None,
            "result_count": len(results),
        },
    }


# ── arXiv API fetch ───────────────────────────────────────────────────────────

def _search_arxiv(query: str, limit: int, sort_by: str, category: str) -> tuple:
    """
    Call arXiv Atom API and parse results. Returns (results, error).

    Category filter is prepended as 'cat:{category} AND ({query})' in search_query.
    Polite delay of 3s between calls respects arXiv's rate limit policy.
    """
    global _last_call

    # Enforce polite delay
    elapsed = time.time() - _last_call
    if elapsed < _POLITE_DELAY:
        time.sleep(_POLITE_DELAY - elapsed)

    search_query = query
    if category:
        search_query = f"cat:{category} AND ({query})"

    api_params = {
        "search_query": search_query,
        "start": 0,
        "max_results": limit,
    }
    # 'relevance' is arXiv's default behavior — sending it as sortBy is invalid
    if sort_by != "relevance":
        api_params["sortBy"] = sort_by
        api_params["sortOrder"] = "descending"

    try:
        _last_call = time.time()
        resp = requests.get(
            _ARXIV_API,
            params=api_params,
            timeout=25,
            headers={"User-Agent": "Chalie/1.0"},
        )
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
    except Exception as e:
        return [], e

    _e = f"{{{_ATOM_NS}}}"
    _ax = f"{{{_ARXIV_NS}}}"

    results = []
    seen_ids = set()

    for entry in root.findall(f"{_e}entry"):
        # Entry ID is the canonical arXiv URL (e.g., http://arxiv.org/abs/2301.00001v1)
        id_el = entry.find(f"{_e}id")
        entry_id = (id_el.text or "").strip() if id_el is not None else ""
        if not entry_id or entry_id in seen_ids:
            continue
        seen_ids.add(entry_id)

        # Normalize URL to /abs/ form, strip version suffix for stable link
        url = re.sub(r"v\d+$", "", entry_id)
        pdf_url = url.replace("/abs/", "/pdf/")

        title_el = entry.find(f"{_e}title")
        title = _clean_latex(title_el.text or "") if title_el is not None else ""

        authors = []
        for author_el in entry.findall(f"{_e}author"):
            name_el = author_el.find(f"{_e}name")
            if name_el is not None and name_el.text:
                authors.append(name_el.text.strip())

        summary_el = entry.find(f"{_e}summary")
        abstract = _clean_latex(summary_el.text or "") if summary_el is not None else ""

        published_el = entry.find(f"{_e}published")
        published = (published_el.text or "").strip() if published_el is not None else ""

        updated_el = entry.find(f"{_e}updated")
        updated = (updated_el.text or "").strip() if updated_el is not None else ""

        # Primary category
        primary_cat_el = entry.find(f"{_ax}primary_category")
        primary_category = (
            primary_cat_el.get("term", "") if primary_cat_el is not None else ""
        )

        # All categories
        categories = [
            cat_el.get("term", "")
            for cat_el in entry.findall(f"{_e}category")
            if cat_el.get("term")
        ]

        results.append({
            "title": title,
            "authors": authors,
            "abstract": abstract[:800] + ("\u2026" if len(abstract) > 800 else ""),
            "url": url,
            "pdf_url": pdf_url,
            "published": published,
            "updated": updated,
            "categories": categories,
            "primary_category": primary_category,
        })

    return results, None


# ── Utilities ─────────────────────────────────────────────────────────────────

def _clean_latex(text: str) -> str:
    """Normalize whitespace from multi-line Atom text fields."""
    text = re.sub(r"\s+", " ", text.strip())
    return text
