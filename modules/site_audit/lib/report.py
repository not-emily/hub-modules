"""Assemble an audit report: normalised archives plus the seed into Jekyll data.

This is the audit-shaped half of the transform. It knows about the seed
templates, the report's own naming, triage ordering, the manual-review layer
and the link worklist. The Lighthouse-only part lives in lighthouse.py.

Standard library only.
"""

import csv
import gzip
import json
import re
import shutil
import statistics
from datetime import date
from pathlib import Path

import lighthouse as lh

# Abbreviations for the overview table, which is category x form factor and
# runs out of horizontal room fast.
CATEGORY_SHORT = {
    "performance": "Perf",
    "accessibility": "A11y",
    "best-practices": "BP",
    "seo": "SEO",
    "agentic-browsing": "Agent",
}

# How a single-category report names itself. Two or more categories is a
# "Site audit" — calling a four-category report an accessibility audit
# misstates what was actually examined.
CATEGORY_AUDIT_NAME = {
    "performance": "Performance",
    "accessibility": "Accessibility",
    "best-practices": "Best practices",
    "seo": "SEO",
    "agentic-browsing": "Agentic browsing",
}

# Trees in a run's site that belong to the run, not the seed. Never reseeded.
#   _pages_audited — hand-written findings
#   _data — regenerated from the archive on every build
RUN_OWNED = ("_pages_audited", "_data")

# Buckets carried into the report. `ok` is not among them — a working link is
# not a finding, and listing 4,400 of them would bury the 26 that matter.
REPORTED_BUCKETS = ("broken", "unverifiable", "redirect")

# Why a URL could not be verified, in words a client can act on. The crawler
# records machine reasons; this is the only place they become prose.
REASON_LABELS = {
    "timeout": "Timed out",
    "dns": "Host not found",
    "tls": "Certificate error",
    "connection": "Connection failed",
    "redirect_loop": "Redirect loop",
    "blocked": "Blocked during the crawl",
    "run_stopped": "Not checked — the crawl stopped early",
    "error": "Request failed",
}

STATUS_LABELS = {
    401: "401 sign-in required",
    403: "403 forbidden",
    404: "404 not found",
    410: "410 gone",
    429: "429 rate limited",
}

MANUAL_CHECKLIST = """
<!-- Manual findings go below. This file is never overwritten by the
     transform — regenerate the data as often as you like. The "Manual review"
     heading is supplied by the layout, so don't repeat it here. -->

_Automated checks cover roughly a third of WCAG success criteria. Record what
you found by hand here; delete the rows you didn't test._

- **Keyboard only** — can you reach and operate everything without a mouse?
- **Focus visible** — is the focus indicator always clearly visible?
- **Focus order** — does tab order follow the visual reading order?
- **Skip link** — is there a working "skip to content" link?
- **Reflow** — usable at 320px wide / 400% zoom with no horizontal scroll?
- **Alt text quality** — do images describe *meaning*, not filenames?
- **Form labels** — is every field labelled, and are errors announced?
- **Motion** — does anything autoplay or animate without a way to stop it?
- **Headings** — does the heading outline make sense read on its own?
"""


# ---------------------------------------------------------------------------
# archives
# ---------------------------------------------------------------------------

def load_report(raw_dir, slug, strategy):
    """Read one archived report. Gzipped is the norm; plain JSON still works."""
    gz = raw_dir / f"{slug}.{strategy}.json.gz"
    if gz.exists():
        with gzip.open(gz, "rt", encoding="utf-8") as fh:
            return json.load(fh)
    plain = raw_dir / f"{slug}.{strategy}.json"
    if plain.exists():
        return json.loads(plain.read_text(encoding="utf-8"))
    return None


def load_crawl(raw_dir, warnings):
    """Read the crawl archive, or None when the run was never crawled."""
    path = raw_dir / "crawl.json.gz"
    if not path.exists():
        return None
    try:
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError, EOFError):
        warnings.append("the crawl archive is unreadable — "
                        "rendering without link findings")
        return None


def slugify_url(url):
    """Match the archive naming: "/" -> home, "/a/b/" -> a-b."""
    path = re.sub(r"^[a-zA-Z]+://[^/]+", "", url or "")
    path = re.sub(r"[?#].*$", "", path).strip("/")
    slug = re.sub(r"[^A-Za-z0-9]+", "-", path).strip("-")
    return slug or "home"


def discover_pages(raw_dir):
    """Work out the page list from the archives alone.

    So the tool is usable against an archive captured by hand, with no client
    record to read. Labels are derived from the slug, which is the one thing
    the archive cannot tell us.
    """
    slugs = {}
    for path in sorted(raw_dir.glob("*.json.gz")):
        if path.name == "crawl.json.gz":
            continue
        stem = path.name[:-len(".json.gz")]
        slug, _, strategy = stem.rpartition(".")
        if not slug or strategy not in lh.STRATEGIES:
            continue
        slugs.setdefault(slug, []).append(strategy)

    pages = []
    for slug, strategies in slugs.items():
        url = ""
        for strategy in strategies:
            doc = load_report(raw_dir, slug, strategy)
            if not doc:
                continue
            lhr = doc.get("lighthouseResult") or {}
            url = (lhr.get("requestedUrl") or doc.get("id")
                   or lhr.get("finalDisplayedUrl") or "")
            if url:
                break
        label = " ".join(w.capitalize() for w in slug.replace("-", " ").split())
        pages.append({"label": label or slug, "url": url, "slug": slug})

    # Home first, then alphabetical — the order a reader expects.
    pages.sort(key=lambda p: (p["slug"] != "home", p["slug"]))
    return pages


# ---------------------------------------------------------------------------
# the site tree
# ---------------------------------------------------------------------------

def scaffold_site(site, seed):
    """Create this run's site from the seed on first use.

    Each audit is a frozen deliverable, so it gets its own copy of the
    templates. Improvements go into the seed and reach the next audit; an
    already published run keeps looking exactly as the client received it.
    """
    if site.exists():
        return False
    if not seed.is_dir():
        raise FileNotFoundError(f"no seed at {seed} — cannot scaffold a site")
    shutil.copytree(seed, site,
                    ignore=shutil.ignore_patterns("_site", ".jekyll-cache"))
    return True


def reseed_site(site, seed):
    """Copy the seed's templates over an existing run's site.

    Use after editing the seed to pull those changes into a run already on
    disk. Manual findings are never touched. Template edits made *inside* the
    run are overwritten — that is the point of the flag, so the changed files
    are listed explicitly rather than applied silently.
    """
    added, updated, unchanged = [], [], []

    for src in sorted(seed.rglob("*")):
        if not src.is_file():
            continue
        rel = src.relative_to(seed)
        if rel.parts[0] in RUN_OWNED or rel.name == ".gitkeep":
            continue

        dst = site / rel
        if not dst.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            added.append(str(rel))
        elif dst.read_bytes() != src.read_bytes():
            shutil.copy2(src, dst)
            updated.append(str(rel))
        else:
            unchanged.append(str(rel))

    # Files the run has that the seed no longer does — usually a template
    # renamed in the seed. Reported, not deleted: one of them might be a
    # deliberate per-run addition.
    skip_dirs = RUN_OWNED + ("_site", ".jekyll-cache", "assets")
    orphans = []
    for found in sorted(site.rglob("*")):
        if not found.is_file():
            continue
        rel = found.relative_to(site)
        if rel.parts[0] in skip_dirs or rel.name.startswith("."):
            continue
        if not (seed / rel).exists():
            orphans.append(str(rel))

    return {"added": added, "updated": updated,
            "unchanged": len(unchanged), "orphans": orphans}


def write_stub(path, page, slug, deep_dive):
    """Create this page's document in the collection, which is what puts
    /pages/<slug>/ on the site at all — every run needs one, or the links out
    of the Overview and Pages tables lead nowhere.

    The manual checklist is the deep-dive part, so an automated-only run gets
    front matter and an empty body. Existing files are left alone — that is
    where hand-written findings live — except an empty body on a deep-dive
    run, which gets the checklist it was missing.
    """
    body = MANUAL_CHECKLIST if deep_dive else ""

    if path.exists():
        if not deep_dive:
            return False
        existing = path.read_text(encoding="utf-8")
        _, _, written = existing.partition("---\n")[2].partition("---\n")
        if written.strip():
            return False

    path.write_text(
        f"""---
layout: page-audit
title: {json.dumps(page.get("label") or slug)}
slug: {slug}
url: {json.dumps(page.get("url", ""))}
---
{body}""",
        encoding="utf-8",
    )
    return True


# ---------------------------------------------------------------------------
# link integrity
# ---------------------------------------------------------------------------

def link_key(url):
    """Loose key for pairing a crawled URL with a configured page.

    Deliberately lossy: scheme, `www.` and a trailing slash all differ between
    what someone typed into a client record and what the crawler normalised,
    and none of those differences mean a different page.
    """
    key = re.sub(r"^https?://", "", (url or "").strip().lower())
    key = re.sub(r"^www\.", "", key)
    key = re.sub(r"[?#].*$", "", key)
    return key.rstrip("/")


def url_path(url):
    """Path portion, for a table column that would otherwise repeat the host on
    every row."""
    path = re.sub(r"^[a-zA-Z]+://[^/]+", "", url or "")
    return path or "/"


def status_label(record):
    """One short human-readable phrase for why this URL is listed."""
    status = record.get("status")
    reason = record.get("reason")
    if status is None or reason in REASON_LABELS:
        return REASON_LABELS.get(reason, "Unreachable")
    if status in STATUS_LABELS:
        return STATUS_LABELS[status]
    if 500 <= status <= 599:
        return f"{status} server error"
    return str(status)


def build_link_entry(record, page_index, bucket):
    """One reported URL, with the pages that link to it.

    Same shape as an issue's `pages` array in issues.json, so the templates can
    reuse the pattern the Issues page already establishes: one row per problem,
    the places it appears listed underneath, ordered by reach.
    """
    referrers = []
    for ref in record.get("referrers", []):
        page = page_index.get(link_key(ref.get("url", "")))
        referrers.append({
            "url": ref.get("url", ""),
            "anchor": ref.get("anchor", ""),
            "label": page["label"] if page else "",
            "slug": page["slug"] if page else "",
            "audited": bool(page),
        })

    # The anchor text is what someone searches for in a CMS, so surface the
    # first non-empty one rather than making the reader open the list.
    anchor = next((r["anchor"] for r in referrers if r["anchor"]), "")

    chain = record.get("redirect_chain") or []
    return {
        "url": record["url"],
        "bucket": bucket,
        "status": record.get("status"),
        "status_label": status_label(record),
        "reason": record.get("reason"),
        "internal": record.get("internal", True),
        "depth": record.get("depth", 0),
        "source": record.get("source", "link"),
        "anchor": anchor,
        "referrers": referrers,
        "referrer_count": record.get("referrer_count", 0),
        # A nav link on a large site can have hundreds of referrers and the
        # crawler keeps only the first 20. The count stays exact, so the
        # template can say "and 139 more" rather than under-reporting reach.
        "referrers_truncated": record.get("referrer_count", 0) > len(referrers),
        "redirect_to": chain[-1]["url"] if chain else "",
        "redirect_hops": len(chain),
        "confirmed": bool(record.get("confirmed")),
        # The re-check ran but could not reach the URL (rate limited, timed
        # out). The finding stands on the original evidence; the template can
        # note that confirmation did not complete.
        "recheck_inconclusive": bool(record.get("recheck_inconclusive")),
        "in_sitemap": record.get("source") == "sitemap",
    }


def coverage_note(crawl):
    """One honest paragraph about what the crawl did and did not reach.

    Same job as the accessibility scope note: the report is never allowed to
    look more complete than it is.
    """
    stats = crawl.get("stats", {})
    settings = crawl.get("settings", {})
    sitemap = crawl.get("sitemap", {})
    depth = settings.get("depth", 3)
    parts = []

    parts.append(
        f"Followed links from the {len(crawl.get('seeds', []))} audited pages "
        f"up to {depth} click{'s' if depth != 1 else ''} away, reaching "
        f"{stats.get('pages_expanded', 0)} pages and checking "
        f"{stats.get('urls_checked', 0)} links."
    )

    if crawl.get("blocked"):
        parts.append(
            "The crawl stopped early because the site stopped responding to "
            "it, so this is a partial picture — there may be more."
        )
    if crawl.get("limits_hit", {}).get("global_cap"):
        parts.append("A page limit was reached, so coverage is partial.")
    if crawl.get("limits_hit", {}).get("max_checks"):
        parts.append(
            "A ceiling on how many links could be checked was reached, so "
            "some of what was found was never tested."
        )
    if crawl.get("throttled_to"):
        parts.append(
            "The crawl slowed itself down part way through because the site "
            "was shedding requests."
        )

    if sitemap.get("found") and sitemap.get("not_reached"):
        if sitemap.get("depth_limited"):
            parts.append(
                f"{sitemap['not_reached']} of the "
                f"{sitemap.get('url_count', 0)} URLs in the sitemap were not "
                f"reachable within {depth} clicks of an audited page."
            )
        else:
            parts.append(
                f"{sitemap['not_reached']} of the "
                f"{sitemap.get('url_count', 0)} URLs in the sitemap have no "
                f"links pointing to them from anywhere we crawled."
            )
        # A sampled cross-check must never read as though every unreached URL
        # was tested. The count is exact; the testing is not.
        if sitemap.get("not_reached_sampled"):
            parts.append(
                f"{sitemap.get('not_reached_checked', 0)} of those were "
                f"status-checked as a sample — the rest were counted but not "
                f"requested, so any of them could also be broken."
            )

    parts.append(
        "Links added by JavaScript after the page loads are not followed."
    )
    return " ".join(parts)


def write_links_csv(path, entries):
    """The worklist.

    Deliberately *not* deduplicated the way the on-page table is: one row per
    place each link appears, because this is worked through page by page in a
    CMS. Collapsing it to one row per broken URL would make it useless for the
    only thing it is for.
    """
    rows = 0
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow([
            "status", "issue", "link_url", "link_type", "pages_affected",
            "anchor_text", "found_on_url", "found_on_page", "click_depth",
            "redirects_to",
        ])
        for entry in entries:
            base = [
                entry["status"] if entry["status"] is not None else entry["reason"],
                entry["status_label"],
                entry["url"],
                "internal" if entry["internal"] else "external",
                # True reach on every row, not the number of rows written. The
                # crawler archives at most 20 referrers, so a footer link on
                # 159 pages would otherwise look like a 20-page job. Sorting
                # the sheet by this column puts the template-level fixes first,
                # which is the order someone should actually work in.
                entry["referrer_count"],
            ]
            tail = [entry["depth"], entry["redirect_to"]]
            if not entry["referrers"]:
                # Sitemap-sourced URLs have no referring page by definition.
                writer.writerow(
                    base + ["", "", "(no inbound links — listed in sitemap)"] + tail)
                rows += 1
                continue
            for ref in entry["referrers"]:
                writer.writerow(base + [ref["anchor"], ref["url"], ref["label"]] + tail)
                rows += 1
    return rows


def build_links_data(crawl, pages, csv_path):
    """Crawl archive to the rendered view, plus the CSV worklist."""
    page_index = {}
    for page in pages:
        key = link_key(page.get("url", ""))
        if key:
            page_index[key] = {
                "label": page.get("label") or page.get("slug") or key,
                "slug": page.get("slug") or slugify_url(page.get("url", "")),
            }

    grouped = {b: {"internal": [], "external": []} for b in REPORTED_BUCKETS}
    unchecked = 0
    for record in crawl.get("urls", []):
        bucket = record.get("bucket")
        if bucket == "unchecked":
            unchecked += 1
            continue
        if bucket not in grouped:
            continue
        entry = build_link_entry(record, page_index, bucket)
        grouped[bucket]["internal" if entry["internal"] else "external"].append(entry)

    # Reach first, then the definitive statuses, then the URL for stability.
    # A link that appears on 159 pages is one fix worth 159 pages.
    def order(entry):
        return (-entry["referrer_count"], entry["status"] or 999, entry["url"])

    for bucket in grouped.values():
        bucket["internal"].sort(key=order)
        bucket["external"].sort(key=order)

    stats = crawl.get("stats", {})
    settings = crawl.get("settings", {})
    sitemap = crawl.get("sitemap", {})

    data = {
        "crawled": True,
        "crawled_at": crawl.get("crawled_at", ""),
        "complete": crawl.get("complete", True),
        "truncated": bool(crawl.get("truncated")),
        "blocked": bool(crawl.get("blocked")),
        "throttled_to": crawl.get("throttled_to"),
        "aborted_at_depth": crawl.get("aborted_at_depth"),
        "depth": settings.get("depth", 3),
        "checked_external": settings.get("check_external", True),
        "pages_crawled": stats.get("pages_expanded", 0),
        # The pages the crawl started from. Distinct from audit.page_count,
        # which counts pages that produced *scan* data and is 0 in a links-only
        # run — and Liquid's `default` filter will not substitute for a 0.
        "seed_count": len(crawl.get("seeds", [])),
        "urls_checked": stats.get("urls_checked", 0),
        "deep_pages": stats.get("deep_pages", 0),
        "unchecked_count": unchecked,
        "sitemap_found": sitemap.get("found", False),
        "sitemap_url_count": sitemap.get("url_count", 0),
        "sitemap_not_reached": sitemap.get("not_reached", 0),
        # Without these the report would imply every unreached URL was tested.
        "sitemap_not_reached_checked": sitemap.get("not_reached_checked",
                                                   sitemap.get("not_reached", 0)),
        "sitemap_not_reached_sampled": bool(sitemap.get("not_reached_sampled")),
        "sitemap_depth_limited": sitemap.get("depth_limited", False),
        "recheck": crawl.get("recheck", {"attempted": 0, "cleared": 0}),
        "coverage_note": coverage_note(crawl),
        "csv_path": "/assets/links.csv",
    }

    for bucket in REPORTED_BUCKETS:
        internal = grouped[bucket]["internal"]
        external = grouped[bucket]["external"]
        data[bucket] = {
            "internal": internal,
            "external": external,
            "internal_count": len(internal),
            "external_count": len(external),
            "count": len(internal) + len(external),
        }

    # Per-audited-page index, so each page's own report can list the broken
    # links found on it — which is where they are actually fixable. Built here
    # rather than filtered in Liquid, which cannot search nested referrer
    # arrays without an O(pages x findings) loop in the template.
    by_page = {}
    for bucket in ("broken", "unverifiable"):
        for entry in data[bucket]["internal"] + data[bucket]["external"]:
            for ref in entry["referrers"]:
                if not ref["slug"]:
                    continue
                row = by_page.setdefault(ref["slug"], [])
                if any(e["url"] == entry["url"] for e in row):
                    continue
                row.append({
                    "url": entry["url"],
                    "status_label": entry["status_label"],
                    "bucket": bucket,
                    "internal": entry["internal"],
                    "anchor": ref["anchor"] or entry["anchor"],
                    "referrer_count": entry["referrer_count"],
                })
    for row in by_page.values():
        row.sort(key=lambda e: (e["bucket"] != "broken", -e["referrer_count"], e["url"]))
    data["by_page"] = by_page

    # Every page the crawl expanded, with how far it sits from a key page, how
    # much it links out to, and how many of those links are a problem. This is
    # what the Pages index becomes when there are no Lighthouse scores to rank
    # by, and it needs no extra capture.
    problems_by_url = {}
    for bucket in ("broken", "unverifiable"):
        for entry in data[bucket]["internal"] + data[bucket]["external"]:
            for ref in entry["referrers"]:
                problems_by_url[ref["url"]] = problems_by_url.get(ref["url"], 0) + 1

    inventory = []
    for record in crawl.get("urls", []):
        if not record.get("expanded"):
            continue
        url = record["url"]
        page = page_index.get(link_key(url))
        inventory.append({
            "url": url,
            "path": url_path(url),
            "label": page["label"] if page else "",
            "slug": page["slug"] if page else "",
            "audited": bool(page),
            "depth": record.get("depth", 0),
            "outbound_total": record.get("outbound_total", 0),
            "outbound_internal": record.get("outbound_internal", 0),
            "problems": problems_by_url.get(url, 0),
        })
    # Most problems first, then the pages hardest to reach — the two reasons a
    # page is worth looking at in a link audit.
    inventory.sort(key=lambda e: (-e["problems"], -e["depth"], e["path"]))
    data["pages"] = inventory
    data["pages_with_problems"] = sum(1 for e in inventory if e["problems"])
    # Whether outbound counts are available at all: archives written before the
    # crawler recorded them have none, and the template must not render a
    # column of zeroes as though every page linked nowhere.
    data["has_outbound_counts"] = any(e["outbound_total"] for e in inventory)

    # Everything the client would work through, in one file they can filter.
    worklist = []
    for bucket in REPORTED_BUCKETS:
        worklist.extend(data[bucket]["internal"] + data[bucket]["external"])
    data["csv_rows"] = write_links_csv(csv_path, worklist)
    data["finding_count"] = data["broken"]["count"] + data["unverifiable"]["count"]

    return data


# ---------------------------------------------------------------------------
# per-page triage
# ---------------------------------------------------------------------------

def page_summary(slug, label, url, per_strategy):
    """The row this page gets in the Overview table, and its triage position."""
    summary_scores = {s: per_strategy[s]["scores"] for s in per_strategy}
    summary_fractions = {s: per_strategy[s].get("fractions", {}) for s in per_strategy}
    fail_counts = {
        s: {c: len(per_strategy[s]["audits"].get(c, {}).get("failed", []))
            for c in per_strategy[s]["audits"]}
        for s in per_strategy
    }

    # Per-page triage figures. The Overview table already carries scores; this
    # is the other question — how much work does this page need, and of what
    # kind. Deduped across form factors: the same finding on mobile and desktop
    # is one thing to fix.
    #
    # Opportunities count as findings, not just binary failures. A page can
    # have zero failing performance checks and still be carrying twelve
    # opportunities worth a megabyte of savings.
    findings = {}
    for result in per_strategy.values():
        for cat, buckets in result["audits"].items():
            for audit in buckets["failed"] + buckets["opportunity"]:
                entry = findings.setdefault(
                    audit["id"], {"category": cat, "impact": "", "nodes": 0})
                entry["impact"] = entry["impact"] or audit.get("impact", "")
                entry["nodes"] = max(entry["nodes"], audit["node_count"])

    by_cat = {}
    for entry in findings.values():
        cat = by_cat.setdefault(entry["category"], {"count": 0, "rank": 5})
        cat["count"] += 1
        cat["rank"] = min(cat["rank"], lh.IMPACT_ORDER.get(entry["impact"], 4))

    impact_rank = min(
        [lh.IMPACT_ORDER.get(e["impact"], 4) for e in findings.values()], default=5)
    worst_impact = next((k for k, v in lh.IMPACT_ORDER.items() if v == impact_rank), "")

    # Lowest score on the page, and which category it belongs to. For
    # performance the score *is* the severity signal — nothing in that category
    # carries an axe impact, so a 44 would otherwise be invisible to triage.
    # Fraction categories are excluded: 2-of-6 arithmetically flattens to 33,
    # which would outrank a genuinely broken performance score on the strength
    # of a category that is experimental. Its failures still surface as
    # findings.
    worst_score = worst_key = worst_strategy = None
    for strategy in lh.STRATEGIES:
        for key, value in (summary_scores.get(strategy) or {}).items():
            if key in lh.FRACTION_CATEGORIES:
                continue
            if value is not None and (worst_score is None or value < worst_score):
                worst_score, worst_key, worst_strategy = value, key, strategy

    # The same category on the other form factor. The worst score is nearly
    # always mobile and the gap is often 40+ points, so a bare "41" would read
    # as a site-wide problem when desktop is at 91.
    best_other = best_other_strategy = None
    for strategy in lh.STRATEGIES:
        if strategy == worst_strategy:
            continue
        value = (summary_scores.get(strategy) or {}).get(worst_key)
        if value is not None and (best_other is None or value > best_other):
            best_other, best_other_strategy = value, strategy

    # Priority ladder blending both signals, because they measure the same
    # thing from different ends: a sub-50 score is as urgent as a critical
    # accessibility failure.
    if impact_rank == 0 or (worst_score is not None and worst_score < 50):
        priority = 0
    elif impact_rank == 1 or (worst_score is not None and worst_score < 90):
        priority = 1
    elif impact_rank <= 3:
        priority = 2
    elif findings:
        priority = 3
    else:
        priority = 4

    return {
        "slug": slug,
        "label": label,
        "url": url,
        "scores": summary_scores,
        "fractions": summary_fractions,
        "failed_counts": fail_counts,
        "finding_count": len(findings),
        "element_count": sum(e["nodes"] for e in findings.values()),
        "worst_impact": worst_impact,
        "worst_score": worst_score,
        "worst_score_key": worst_key,
        "worst_score_short": CATEGORY_SHORT.get(worst_key, ""),
        "worst_score_strategy": worst_strategy,
        "worst_score_other": best_other,
        "worst_score_other_strategy": best_other_strategy,
        "priority": priority,
        "findings_by_category": [
            {"key": c, "short": CATEGORY_SHORT[c], "label": lh.CATEGORY_LABELS[c],
             "count": by_cat[c]["count"],
             "impact": next((k for k, v in lh.IMPACT_ORDER.items()
                             if v == by_cat[c]["rank"]), "")}
            for c in lh.CATEGORIES if c in by_cat
        ],
        # Single sortable key, ascending: priority, then worst score, then
        # volume. Liquid cannot sort on multiple fields, and volume alone as
        # the tiebreak put a 69-scoring page above a 41-scoring one. No score
        # at all sorts last within its band rather than first.
        "triage_rank": (priority * 1000000
                        + (100 if worst_score is None else worst_score) * 1000
                        - min(len(findings), 999)),
    }


def finalise_issues(issue_index):
    """Order the site-wide issue index and collapse it to one row per page."""
    issues = sorted(
        issue_index.values(),
        key=lambda i: (lh.IMPACT_ORDER.get(i["impact"], 4),
                       -len({a["slug"] for a in i["affected"]}),
                       -i["weight"]),
    )

    for issue in issues:
        issue["page_count"] = len({a["slug"] for a in issue["affected"]})

        # Collapse the per-strategy hits into one row per page. A page failing
        # on both form factors is one page to fix, not two — "affected pages"
        # has to count pages or the number is simply wrong.
        by_page = {}
        for affected in issue["affected"]:
            entry = by_page.setdefault(affected["slug"], {
                "slug": affected["slug"], "label": affected["label"],
                "url": affected["url"], "strategies": [], "node_count": 0,
            })
            entry["strategies"].append(affected["strategy"])
            # Worst single form factor, not the sum: the same element failing
            # on mobile and desktop is one element.
            entry["node_count"] = max(entry["node_count"], affected["node_count"])

        for entry in by_page.values():
            # Canonical order, so the chips read mobile-then-desktop
            # everywhere. A page listing one factor rather than two is a
            # responsive-only failure; the template shows that by chip count.
            entry["strategies"] = [s for s in lh.STRATEGIES if s in entry["strategies"]]

        issue["pages"] = sorted(by_page.values(), key=lambda e: -e["node_count"])
        issue["element_count"] = sum(e["node_count"] for e in issue["pages"])

        # Some audits do not enumerate DOM elements at all — console messages,
        # cookies, devtools issues. Reporting "0 elements" against a real
        # defect reads as "nothing to fix", so the templates say "page-level".
        issue["element_scoped"] = any(e["node_count"] > 0 for e in issue["pages"])

    return issues


def long_date(iso):
    """"2026-09-15" -> "September 15, 2026", without relying on %-d."""
    try:
        parsed = date.fromisoformat(iso)
    except (TypeError, ValueError):
        return iso or ""
    return f"{parsed:%B} {parsed.day}, {parsed:%Y}"
