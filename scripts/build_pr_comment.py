#!/usr/bin/env python3
import argparse
import json
import os
import subprocess
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Tuple


def git_changed_files(base_sha: str, head_sha: str) -> List[str]:
    """Return repo-relative paths of files changed between base and head."""
    cmd = ["git", "diff", "--name-only", base_sha, head_sha]
    out = subprocess.check_output(cmd, text=True)
    return [line.strip() for line in out.splitlines() if line.strip()]


def file_url(repo: str, head_sha: str, path: str) -> str:
    """Stable link to a file at the PR head SHA."""
    return f"https://github.com/{repo}/blob/{head_sha}/{path}"


def page_key(page: Dict[str, Any]) -> str:
    """Stable key for grouping pages."""
    return str(page.get("id") or f"{page.get('report','')}/{page.get('name','')}".strip("/"))


def ascii_layout(
    visuals_for_page: List[Tuple[int, Dict[str, Any]]],
    cols: int = 60,
    rows: int = 16,
) -> List[str]:
    """
    Build a simple ASCII map of the page.

    visuals_for_page: [(index_in_visual_list, visual_dict), ...]
    We place the numeric index (1,2,3,...) at the scaled center of each visual.
    """
    if not visuals_for_page:
        return []

    xywh: List[Tuple[int, float, float, float, float]] = []
    max_right = 0.0
    max_bottom = 0.0

    for idx, v in visuals_for_page:
        x = float(v.get("x", 0.0))
        y = float(v.get("y", 0.0))
        w = float(v.get("width", 1.0))
        h = float(v.get("height", 1.0))
        xywh.append((idx, x, y, w, h))
        max_right = max(max_right, x + w)
        max_bottom = max(max_bottom, y + h)

    if max_right <= 0 or max_bottom <= 0:
        max_right, max_bottom = 1.0, 1.0

    sx = cols / max_right
    sy = rows / max_bottom

    # Initialize blank grid
    grid = [[" " for _ in range(cols)] for _ in range(rows)]

    # Place each visual's index at its center
    for idx, x, y, w, h in xywh:
        cx = x + w / 2.0
        cy = y + h / 2.0
        col = int(round(cx * sx))
        row = int(round(cy * sy))
        col = max(0, min(cols - 1, col))
        row = max(0, min(rows - 1, row))

        label = str(idx)
        start = max(0, min(cols - len(label), col - len(label) // 2))
        for j, ch in enumerate(label):
            grid[row][start + j] = ch

    top = "+" + "-" * cols + "+"
    body = ["|" + "".join(r) + "|" for r in grid]
    bottom = top
    return [top, *body, bottom]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mapping", default="pbir-mapping.json", help="Path to mapping JSON")
    ap.add_argument("--out", default="pbir-comment.md", help="Output markdown file")
    args = ap.parse_args()

    repo = os.environ["REPO"]
    pr_number = os.environ.get("PR_NUMBER", "")
    base_sha = os.environ["BASE_SHA"]
    head_sha = os.environ["HEAD_SHA"]

    mapping_path = Path(args.mapping)
    if not mapping_path.exists():
        raise SystemExit(f"Mapping not found: {mapping_path}")

    mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
    pages = mapping.get("pages", [])

    # Index pages + visuals by their paths
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

    changed_paths = [p.replace("\\", "/") for p in git_changed_files(base_sha, head_sha)]

    # Per-page aggregate structure:
    #   {
    #     "page": <page dict>,
    #     "page_changed": bool,
    #     "page_path": str,
    #     "visuals": [ (path, visual_dict), ... ]
    #   }
    per_page: Dict[str, Dict[str, Any]] = {}

    for path in changed_paths:
        if path in page_by_path:
            page = page_by_path[path]
            key = page_key(page)
            info = per_page.setdefault(
                key,
                {
                    "page": page,
                    "page_changed": False,
                    "page_path": path,
                    "visuals": [],
                },
            )
            info["page_changed"] = True

        if path in visuals_by_path:
            page, vis = visuals_by_path[path]
            key = page_key(page)
            info = per_page.setdefault(
                key,
                {
                    "page": page,
                    "page_changed": False,
                    "page_path": page.get("path", ""),
                    "visuals": [],
                },
            )
            info["visuals"].append((path, vis))

    # Nothing changed that we know about
    if not per_page:
        content = "\n".join(
            [
                "### PBIR pages & visuals changed in this PR",
                "",
                "_No mapped PBIR pages or visuals changed in this PR._",
            ]
        )
        Path(args.out).write_text(content, encoding="utf-8")
        return

    # Sort pages by (report, page name)
    def page_sort_key(info: Dict[str, Any]) -> Tuple[str, str]:
        page = info["page"]
        return (page.get("report", "") or "", page.get("name", "") or "")

    page_infos = sorted(per_page.values(), key=page_sort_key)

    lines: List[str] = []
    lines.append("### PBIR pages & visuals changed in this PR")
    lines.append("")
    lines.append(f"_PR #{pr_number}_")
    lines.append("")

    page_idx = 0
    for info in page_infos:
        page_idx += 1
        page = info["page"]
        page_changed = info["page_changed"]
        page_path = info.get("page_path") or page.get("path", "")

        page_name = page.get("name", "(unnamed page)")
        report_name = page.get("report", "")

        # 1st-level ordered list: page
        if report_name:
            lines.append(f"{page_idx}. **{page_name}** _(report: {report_name})_")
        else:
            lines.append(f"{page_idx}. **{page_name}**")
        lines.append("")

        # Note if page.json changed
        if page_changed and page_path:
            url = file_url(repo, head_sha, page_path)
            lines.append(f"   - Page definition changed ([page.json]({url}))")
            lines.append("")

        # 2nd-level ordered list: visuals for this page
        vis_items = info["visuals"]
        vis_items = sorted(vis_items, key=lambda t: (t[1].get("titleText") or t[1].get("name") or ""))

        vis_for_ascii: List[Tuple[int, Dict[str, Any]]] = []
        vis_idx = 0

        for vpath, vis in vis_items:
            vis_idx += 1
            vtype = (vis.get("visualType") or "").strip()
            title = (vis.get("titleText") or "").strip()
            fallback = (vis.get("name") or "").strip()

            if title:
                label = f"{vtype} — {title}" if vtype else title
            elif vtype and fallback:
                label = f"{vtype} — {fallback}"
            elif vtype:
                label = vtype
            elif fallback:
                label = fallback
            else:
                label = "(unnamed visual)"

            url = file_url(repo, head_sha, vpath)
            lines.append(f"   {vis_idx}. [{label}]({url})")
            vis_for_ascii.append((vis_idx, vis))

        lines.append("")

        # ASCII layout (numbers correspond to the 2nd-level list)
        art = ascii_layout(vis_for_ascii)
        if art:
            lines.append("   ```text")
            for row in art:
                lines.append(f"   {row}")
            lines.append("   ```")
            lines.append("")
        else:
            if not vis_items and page_changed:
                lines.append("   _(No visual layout changes to map for this page)_")
                lines.append("")

    Path(args.out).write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
