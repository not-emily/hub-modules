"""Normalise a PageSpeed Insights payload into scores, issues and DOM nodes.

Nothing here knows about audits, clients, Jekyll or this report's shape — it
speaks only Lighthouse. That is deliberate: it is the one part of the transform
that another consumer could want, so it is kept liftable into a real utility
(Layer 1.5) if a second consumer ever appears. Everything audit-shaped lives in
report.py.

Standard library only.
"""

import base64
import re

CATEGORIES = ["performance", "accessibility", "best-practices", "seo",
              "agentic-browsing"]

CATEGORY_LABELS = {
    "performance": "Performance",
    "accessibility": "Accessibility",
    "best-practices": "Best Practices",
    "seo": "SEO",
    "agentic-browsing": "Agentic Browsing",
}

# What someone might type for a category, including the obvious shorthands.
CATEGORY_ALIASES = {
    "a11y": "accessibility",
    "perf": "performance",
    "bp": "best-practices",
    "bestpractices": "best-practices",
    "best_practices": "best-practices",
    "agent": "agentic-browsing",
    "agentic": "agentic-browsing",
    "agentbrowsing": "agentic-browsing",
    "agentic_browsing": "agentic-browsing",
}

# Lighthouse scores Agentic Browsing with categoryScoreDisplayMode "fraction":
# six equally weighted checks reported as "n of 6 passed", not a 0-100 gauge.
# Rendering it as a percentage beside the other four would invite a comparison
# the number cannot support — 4/6 is not "a 67 like a 67 in SEO".
FRACTION_CATEGORIES = {"agentic-browsing"}

STRATEGIES = ["mobile", "desktop"]

# Lab metrics worth pulling out by name, in display order.
LAB_METRICS = ["first-contentful-paint", "largest-contentful-paint",
               "total-blocking-time", "cumulative-layout-shift", "speed-index"]

# Cap nodes stored per audit so one pathological page cannot bloat the data set.
MAX_NODES_PER_AUDIT = 50

# axe impact ordering, most severe first.
IMPACT_ORDER = {"critical": 0, "serious": 1, "moderate": 2, "minor": 3, "": 4}


class Unknown(ValueError):
    """An unrecognised category name."""


def resolve_categories(raw):
    """Normalise a category filter into a set, or every category when empty.

    Accepts a list or a comma-separated string, since a tool param may arrive
    as either.
    """
    if raw is None or raw == "":
        return set(CATEGORIES)
    if isinstance(raw, str):
        raw = raw.split(",")
    wanted = set()
    for item in raw:
        name = str(item).strip().lower()
        if not name:
            continue
        name = CATEGORY_ALIASES.get(name, name)
        if name not in CATEGORIES:
            raise Unknown(
                f"unknown category: {item}. Valid: {', '.join(CATEGORIES)}")
        wanted.add(name)
    return wanted or set(CATEGORIES)


def score_to_int(score):
    """Lighthouse scores are 0..1 floats, or None for non-scored audits."""
    if score is None:
        return None
    return round(score * 100)


def strip_markdown_links(text):
    """Lighthouse descriptions embed [text](url). Keep the text, drop the URL."""
    return re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1", text or "").strip()


def first_doc_link(text):
    """Pull the first documentation URL out of a Lighthouse description."""
    match = re.search(r"\[[^\]]+\]\((https?://[^)]+)\)", text or "")
    return match.group(1) if match else None


def classify(audit, group=""):
    """Bucket an audit for reporting.

    The distinction that matters: accessibility audits are `binary` — they pass
    or they fail, and a failure is a defect. Performance audits are mostly
    measurements. Treating a Largest Contentful Paint score of 0.21 as a
    "failing check" would report a dozen failures that are really one slow
    page, so lab metrics get their own bucket and graded diagnostics become
    opportunities rather than defects.
    """
    mode = audit.get("scoreDisplayMode", "")
    score = audit.get("score")

    if mode == "manual":
        return "manual"
    if mode == "notApplicable":
        return "not_applicable"
    if mode == "informative" or score is None:
        return "informative"
    if group == "metrics":
        return "metrics"
    if mode == "binary":
        return "passed" if score >= 1 else "failed"

    # numeric / metricSavings — diagnostics and savings opportunities
    return "passed" if score >= 0.9 else "opportunity"


def extract_impact(audit):
    """axe severity, when Lighthouse passes it through."""
    details = audit.get("details") or {}
    debug = details.get("debugData") or {}
    if debug.get("impact"):
        return debug["impact"]

    # Some audits carry impact per item instead of on the audit.
    for item in (details.get("items") or []):
        if isinstance(item, dict) and item.get("impact"):
            return item["impact"]
    return ""


def extract_nodes(audit):
    """Pull the offending DOM elements out of an audit's details table.

    This is the payload that makes a report actionable: a CSS selector and the
    actual markup for every element that failed the check.
    """
    details = audit.get("details") or {}
    nodes = []

    for item in (details.get("items") or []):
        if not isinstance(item, dict):
            continue

        # Most a11y audits nest the element under "node"; some items *are* nodes.
        candidates = []
        if isinstance(item.get("node"), dict):
            candidates.append(item["node"])
        elif item.get("type") == "node":
            candidates.append(item)
        for related in (item.get("relatedNodes") or []):
            if isinstance(related, dict):
                candidates.append(related)

        for node in candidates:
            nodes.append({
                "lh_id": node.get("lhId", ""),
                "selector": node.get("selector", ""),
                "snippet": node.get("snippet", ""),
                "label": node.get("nodeLabel", ""),
                "explanation": strip_markdown_links(node.get("explanation", "")),
                "path": node.get("path", ""),
                # Kept as a fallback: nodes carry their own rect, which lets us
                # still draw a box when the screenshot index omits the id.
                "_rect_px": node.get("boundingRect"),
            })

    return nodes


def dedupe_nodes(nodes):
    """The same element can arrive via both `node` and `relatedNodes`."""
    seen = set()
    out = []
    for node in nodes:
        key = (node["selector"], node["snippet"])
        if key in seen:
            continue
        seen.add(key)
        out.append(node)
    return out


def rect_to_pct(rect, shot_meta):
    """Convert a pixel boundingRect into screenshot-relative percentages."""
    if not rect or not shot_meta:
        return None
    width, height = shot_meta.get("width") or 0, shot_meta.get("height") or 0
    rect_w, rect_h = rect.get("width") or 0, rect.get("height") or 0
    if width <= 0 or height <= 0 or rect_w <= 0 or rect_h <= 0:
        return None
    return {
        "left": round(rect.get("left", 0) / width * 100, 3),
        "top": round(rect.get("top", 0) / height * 100, 3),
        "width": round(rect_w / width * 100, 3),
        "height": round(rect_h / height * 100, 3),
    }


def extract_screenshot(lhr, name, out_dir):
    """Write the full-page screenshot and return its metadata plus a map of
    lhId to bounding box, expressed in percentages.

    Percentages rather than pixels so a layout can overlay highlight boxes with
    plain CSS at any rendered width — no image compositing, and the boxes stay
    interactive.
    """
    fps = lhr.get("fullPageScreenshot")
    if not fps:
        # Older Lighthouse versions expose it as a regular audit.
        fps = ((lhr.get("audits") or {}).get("full-page-screenshot") or {}).get("details")
    if not fps:
        return None, {}

    shot = fps.get("screenshot") or {}
    data_uri = shot.get("data") or ""
    width = shot.get("width") or 0
    height = shot.get("height") or 0

    if not data_uri.startswith("data:image/") or "," not in data_uri:
        return None, {}
    if not width or not height:
        return None, {}

    header, b64 = data_uri.split(",", 1)
    # Lighthouse 13 emits WebP; older versions emit JPEG. Derive the extension
    # from the declared mime type rather than assuming either.
    match = re.match(r"data:image/([a-zA-Z0-9.+-]+)", header)
    subtype = match.group(1).lower() if match else "png"
    ext = {"jpeg": "jpg", "svg+xml": "svg"}.get(subtype, subtype)
    filename = f"{name}.{ext}"

    try:
        blob = base64.b64decode(b64)
    except Exception:
        return None, {}

    (out_dir / filename).write_bytes(blob)

    rects = {}
    for lh_id, rect in (fps.get("nodes") or {}).items():
        rect_w, rect_h = rect.get("width") or 0, rect.get("height") or 0
        if rect_w <= 0 or rect_h <= 0:
            continue
        rects[lh_id] = {
            "left": round(rect.get("left", 0) / width * 100, 3),
            "top": round(rect.get("top", 0) / height * 100, 3),
            "width": round(rect_w / width * 100, 3),
            "height": round(rect_h / height * 100, 3),
        }

    return {"file": filename, "width": width, "height": height,
            "bytes": len(blob)}, rects


def parse_report(doc, screenshot_name, screenshot_dir, wanted):
    """Turn one raw PSI response into a normalised per-strategy result.

    `wanted` restricts which categories are reported. Categories absent from
    the response are skipped regardless — a report fetched with
    categories=accessibility simply has no performance data to read.
    """
    lhr = doc.get("lighthouseResult") or {}
    all_audits = lhr.get("audits") or {}
    categories = lhr.get("categories") or {}

    shot_meta, rects = extract_screenshot(lhr, screenshot_name, screenshot_dir)

    scores = {}
    fractions = {}
    grouped = {}

    for cat_key in CATEGORIES:
        if cat_key not in wanted:
            continue
        cat = categories.get(cat_key)
        if not cat:
            continue

        scores[cat_key] = score_to_int(cat.get("score"))

        buckets = {"failed": [], "opportunity": [], "metrics": [], "manual": [],
                   "not_applicable": [], "passed": [], "informative": []}

        for ref in (cat.get("auditRefs") or []):
            audit_id = ref.get("id")
            audit = all_audits.get(audit_id)
            if not audit:
                continue

            bucket = classify(audit, ref.get("group", ""))
            entry = {
                "id": audit_id,
                "title": audit.get("title", audit_id),
                "description": strip_markdown_links(audit.get("description", "")),
                "doc_url": first_doc_link(audit.get("description", "")),
                "weight": ref.get("weight", 0),
                "group": ref.get("group", ""),
                "score": score_to_int(audit.get("score")),
            }
            if audit.get("displayValue"):
                entry["display_value"] = audit["displayValue"]

            if bucket in ("failed", "opportunity"):
                nodes = dedupe_nodes(extract_nodes(audit))
                entry["impact"] = extract_impact(audit)
                entry["node_count"] = len(nodes)
                entry["nodes_truncated"] = len(nodes) > MAX_NODES_PER_AUDIT
                # Attach the screenshot rect to each node so a layout can draw
                # a box without a second lookup.
                for node in nodes[:MAX_NODES_PER_AUDIT]:
                    node["rect"] = (rects.get(node["lh_id"])
                                    or rect_to_pct(node.get("_rect_px"), shot_meta))
                    node.pop("_rect_px", None)
                entry["nodes"] = nodes[:MAX_NODES_PER_AUDIT]

            buckets[bucket].append(entry)

        # Heaviest failures first — that is remediation order, not alphabetical.
        buckets["failed"].sort(
            key=lambda e: (IMPACT_ORDER.get(e.get("impact", ""), 4),
                           -e["weight"], -e["node_count"]))
        buckets["opportunity"].sort(key=lambda e: (-e["weight"], e["title"]))
        grouped[cat_key] = buckets

        # "n of 6 passed", mirroring how Lighthouse's own renderer builds a
        # fraction: manual and not-applicable checks drop out of the
        # denominator entirely, everything else that was scored counts, and
        # only a genuine pass counts up top. Informative and errored audits sit
        # in the denominator without passing, which is what Lighthouse does and
        # is why this number matches what PSI shows on the web.
        if cat_key in FRACTION_CATEGORIES:
            passed_n = len(buckets["passed"])
            total_n = (passed_n + len(buckets["failed"]) + len(buckets["opportunity"])
                       + len(buckets["informative"]) + len(buckets["metrics"]))
            fractions[cat_key] = {"passed": passed_n, "total": total_n}

    # Lab metrics are performance-only, so they stay out of an
    # accessibility-scoped report even when the archive happens to hold them.
    metrics = {}
    if "performance" in wanted:
        for metric_id in LAB_METRICS:
            audit = all_audits.get(metric_id)
            if audit:
                metrics[metric_id] = {
                    "title": audit.get("title", metric_id),
                    "value": audit.get("displayValue", ""),
                    "score": score_to_int(audit.get("score")),
                }

    # CrUX field data — only present for URLs with enough real traffic.
    field = None
    experience = doc.get("loadingExperience") or {}
    if "performance" in wanted and experience.get("metrics"):
        field = {
            "overall": experience.get("overall_category", ""),
            "metrics": {
                k: {"category": v.get("category", ""), "percentile": v.get("percentile")}
                for k, v in experience["metrics"].items()
            },
        }

    return {
        "scores": scores,
        "fractions": fractions,
        "audits": grouped,
        "metrics": metrics,
        "field_data": field,
        "screenshot": shot_meta,
        "lighthouse_version": lhr.get("lighthouseVersion", ""),
        "fetch_time": lhr.get("fetchTime", ""),
        "final_url": lhr.get("finalDisplayedUrl") or lhr.get("finalUrl", ""),
    }
