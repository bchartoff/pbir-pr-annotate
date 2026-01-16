#!/usr/bin/env python3
import argparse
import hashlib
import json
import os
import subprocess

from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Tuple
from urllib.parse import quote


def git_changed_files(base_sha: str, head_sha: str) -> List[str]:
    """Return repo-relative paths changed between base and head."""
    cmd = ["git", "diff", "--name-only", base_sha, head_sha]
    out = subprocess.check_output(cmd, text=True)
    return [line.strip() for line in out.splitlines() if line.strip()]


def git_diff_stats(base_sha: str, head_sha: str) -> Dict[str, Tuple[int, int]]:
    """
    Return per-file insertion/deletion counts using `git diff --numstat`.

    Output format per line:
        <insertions>\t<deletions>\t<path>
    We normalize path separators to '/'.
    """
    cmd = ["git", "diff", "--numstat", base_sha, head_sha]
    out = subprocess.check_output(cmd, text=True)
    stats: Dict[str, Tuple[int, int]] = {}

    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        ins_str, del_str, path = parts[0], parts[1], parts[2]
        # Handle binary files ("-  -  path")
        try:
            ins = int(ins_str)
            dels = int(del_str)
        except ValueError:
            ins = dels = 0
        norm_path = path.replace("\\", "/")
        stats[norm_path] = (ins, dels)

    return stats


def diff_anchor_for_path(filepath: str) -> str:
    """
    Compute GitHub's diff anchor hash for the commit diff URL.
    filepath must be repo-relative with forward slashes.
    """
    h = hashlib.sha256(filepath.encode("utf-8")).hexdigest()
    return h

def pr_diff_url(repo: str, pr_number: str, filepath: str) -> str:
    anchor = diff_anchor_for_path(filepath)
    return f"https://github.com/{repo}/pull/{pr_number}/files#diff-{anchor}"

def workflow_url(repo: str, head_sha: str, workflow_file: str) -> str:
    """Direct link to workflow file under .github/workflows."""
    safe = quote(workflow_file, safe="/")
    return f"https://github.com/{repo}/blob/{head_sha}/.github/workflows/{safe}"


def page_key(page: Dict[str, Any]) -> str:
    """Stable grouping key."""
    return str(page.get("id") or f"{page.get('report','')}/{page.get('name','')}")


def ascii_layout(
    visuals_for_page: List[Tuple[int, Dict[str, Any]]],
    cols: int = 60,
    rows: int = 16,
) -> List[str]:
    """
    Draw each visual as a scaled ASCII rectangle, with its index centered inside.
    """
    if not visuals_for_page:
        return []

    xywh: List[Tuple[int, float, float, float, float]] = []
    max_right = 0.0
    max_bottom = 0.0

    # Collect extents
    for idx, v in visuals_for_page:
        x = float(v.get("x", 0.0))
        y = float(v.get("y", 0.0))
        w = float(v.get("width", 1.0))
        h = float(v.get("height", 1.0))
        xywh.append((idx, x, y, w, h))
        max_right = max(max_right, x + w)
        max_bottom = max(max_bottom, y + h)

    if max_right <= 0 or max_bottom <= 0:
        max_right = max_bottom = 1.0

    sx = cols / max_right
    sy = rows / max_bottom

    # Blank grid
    grid = [[" " for _ in range(cols)] for _ in range(rows)]

    for idx, x, y, w, h in xywh:
        # Scale coordinates
        left = int(round(x * sx))
        top = int(round(y * sy))
        right = int(round((x + w) * sx))
        bottom = int(round((y + h) * sy))

        # Clamp into grid
        left = max(0, min(cols - 1, left))
        right = max(0, min(cols - 1, right))
        top = max(0, min(rows - 1, top))
        bottom = max(0, min(rows - 1, bottom))

        # Force minimum size
        if right <= left:
            right = min(cols - 1, left + 1)
        if bottom <= top:
            bottom = min(rows - 1, top + 1)

        # Draw corners
        grid[top][left] = "+"
        grid[top][right] = "+"
        grid[bottom][left] = "+"
        grid[bottom][right] = "+"

        # Draw edges
        for c in range(left + 1, right):
            grid[top][c] = "-"
            grid[bottom][c] = "-"
        for r in range(top + 1, bottom):
            grid[r][left] = "|"
            grid[r][right] = "|"

        # Centered label
        label = str(idx)

        interior_width = max(1, (right - left - 1))
        interior_height = max(1, (bottom - top - 1))

        center_row = top + 1 + interior_height // 2
        center_col = left + 1 + (interior_width - len(label)) // 2

        center_row = max(top + 1, min(bottom - 1, center_row))
        center_col = max(left + 1, min(right - len(label), center_col))

        for j, ch in enumerate(label):
            c = center_col + j
            if 0 <= center_row < rows and 0 <= c < cols:
                grid[center_row][c] = ch

    border_top = "+" + "-" * cols + "+"
    border_bottom = border_top
    body = ["|" + "".join(row) + "|" for row in grid]
    return [border_top, *body, border_bottom]


def visual_label(vis: Dict[str, Any]) -> str:
    """Format: visualType — titleText or fallback."""
    vtype = (vis.get("visualType") or "").strip()
    title = (vis.get("titleText") or "").strip()
    fallback = (vis.get("name") or "").strip()

    if title:
        return f"{vtype} :: `{title}`" if vtype else title
    if vtype and fallback:
        return f"{vtype} :: `{fallback}`"
    if vtype:
        return vtype
    if fallback:
        return fallback
    return "(unnamed visual)"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mapping", default="_build_artifacts/pbir-mapping.json")
    ap.add_argument("--out", default="_build_artifacts/pbir-comment.md")
    ap.add_argument(
        "--workflow-file",
        default="pbir-pr-annotate.yml",
        help="Workflow filename under .github/workflows/",
    )
    args = ap.parse_args()

    repo = os.environ["REPO"]     # e.g. "owner/repo"
    pr_number = os.environ.get("PR_NUMBER", "LOCAL")
    base_sha = os.environ["BASE_SHA"]
    head_sha = os.environ["HEAD_SHA"]

    mapping_path = Path(args.mapping)
    if not mapping_path.exists():
        raise SystemExit(f"Mapping not found: {mapping_path}")

    mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
    pages = mapping.get("pages", [])

    # Precompute diff stats per path
    diff_stats = git_diff_stats(base_sha, head_sha)

    page_by_path: Dict[str, Dict[str, Any]] = {}
    visuals_by_path: Dict[str, Tuple[Dict[str, Any], Dict[str, Any]]] = {}

    for page in pages:
        ppath = page.get("path")
        if ppath:
            page_by_path[ppath.replace("\\", "/")] = page
        for vis in page.get("visuals", []):
            vpath = vis.get("path")
            if vpath:
                visuals_by_path[vpath.replace("\\", "/")] = (page, vis)

    changed = [p.replace("\\", "/") for p in git_changed_files(base_sha, head_sha)]

    # Aggregate per page
    per_page: Dict[str, Dict[str, Any]] = {}

    for path in changed:
        if path in page_by_path:
            page = page_by_path[path]
            key = page_key(page)
            per_page.setdefault(
                key, {"page": page, "page_changed": False, "page_path": path, "visuals": []}
            )
            per_page[key]["page_changed"] = True

        if path in visuals_by_path:
            page, vis = visuals_by_path[path]
            key = page_key(page)
            per_page.setdefault(
                key,
                {"page": page, "page_changed": False, "page_path": page.get("path", ""), "visuals": []},
            )
            per_page[key]["visuals"].append((path, vis))

    # Group by report
    reports: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for info in per_page.values():
        report = (info["page"].get("report") or "(unknown report)").strip()
        reports[report].append(info)

    report_names = sorted(reports.keys(), key=lambda s: s.casefold())

    def sort_pages(info: Dict[str, Any]) -> tuple:
        page = info["page"]
        return ((page.get("name") or "").casefold(), (page.get("id") or "").casefold())

    lines: List[str] = []
    lines.append(f"_List of pages & visuals changed in this PR (#{pr_number})_")
    lines.append("")
    lines.append("")

    if not per_page:
        lines.append("_No mapped PBIR pages or visuals changed in this PR._")
    else:
        first_report = True
        for report in report_names:
            if not first_report:
                lines.append("")
            first_report = False

            lines.append(f"## Report: _{report}_")
            lines.append("")

            page_infos = sorted(reports[report], key=sort_pages)

            first_page = True
            for info in page_infos:
                if not first_page:
                    lines.append("")
                    lines.append("---")
                    lines.append("")
                first_page = False

                page = info["page"]
                page_name = page.get("name") or "(unnamed page)"
                page_id = page.get("id") or ""

                if page_id:
                    lines.append(f"#### Page: _{page_name}_ :: `{page_id}`")
                else:
                    lines.append(f"#### Page: _{page_name}_")

                lines.append("")

                # Page def changed
                if info["page_changed"] and info["page_path"]:
                    purl = pr_diff_url(repo, pr_number, info["page_path"])
                    ins, dels = diff_stats.get(info["page_path"], (0, 0))
                    lines.append(
                        f"   - Page definition changed ([page.json]({purl})) _( +{ins}_ 🟩 _/ -{dels}_ 🟥 _)_"
                    )
                    lines.append("")
                    lines.append("")

                # Visuals
                vis_items: List[Tuple[str, Dict[str, Any]]] = info["visuals"]
                if vis_items:
                    lines.append("##### Visuals Changed:")
                    lines.append("")
                    # sort visuals by label
                    vis_items = sorted(vis_items, key=lambda t: visual_label(t[1]).casefold())

                    vis_for_ascii: List[Tuple[int, Dict[str, Any]]] = []
                    for idx, (vpath, vis) in enumerate(vis_items, start=1):
                        vurl = pr_diff_url(repo, pr_number, vpath)
                        label = visual_label(vis)

                        # insertion/deletion stats for this visual file
                        ins, dels = diff_stats.get(vpath, (0, 0))
                        lines.append(
                            f"   {idx}. <a href =\"{vurl}\" target=\"_blank\">{label}</a> _( +{ins}_ 🟩 _/ -{dels}_ 🟥 _)_"
                        )

                        vis_for_ascii.append((idx, vis))

                    lines.append("")
                    lines.append("_Map of approximate visual size and location, for reference_")
                    lines.append("   ```text")
                    for row in ascii_layout(vis_for_ascii):
                        lines.append(f"   {row}")
                    lines.append("   ```")
                else:
                    lines.append("   _(No visual layout changes to map for this page)_")

    lines.append("")
    lines.append("")
    lines.append(
        f"_This comment is auto-generated by the workflow "
        f"[{args.workflow_file}]({workflow_url(repo, head_sha, args.workflow_file)})_"
    )

    Path(args.out).write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
