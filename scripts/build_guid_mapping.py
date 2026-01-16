#!/usr/bin/env python3
import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def read_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def strip_literal_quotes(value: str) -> str:
    """
    Power BI often stores Literal.Value strings like:
      "'SALES AND MARKETING'"
    We want to turn that into "SALES AND MARKETING".
    """
    v = value.strip()
    if len(v) >= 2 and v[0] == "'" and v[-1] == "'":
        v = v[1:-1].strip()
    return v


def extract_visual_type(vobj: Dict[str, Any]) -> str:
    try:
        return str(vobj["visual"]["visualType"])
    except Exception:
        return ""


def extract_title_text(vobj: Dict[str, Any]) -> Optional[str]:
    """
    Look for:
      visual.visualContainerObjects.title[0].properties.text.expr.Literal.Value
    """
    try:
        title_arr = vobj["visual"]["visualContainerObjects"]["title"]
        if not isinstance(title_arr, list) or not title_arr:
            return None

        props = title_arr[0]["properties"]
        literal = props["text"]["expr"]["Literal"]["Value"]
        if not isinstance(literal, str):
            return None

        cleaned = strip_literal_quotes(literal).strip()
        return cleaned or None
    except Exception:
        return None


def extract_xywh_from_position(vobj: Dict[str, Any]) -> Tuple[float, float, float, float]:
    """
    You said position is always present; we'll still guard lightly.
    """
    pos = vobj.get("position", {}) or {}
    x = float(pos.get("x", 0.0))
    y = float(pos.get("y", 0.0))
    w = float(pos.get("width", 1.0))
    h = float(pos.get("height", 1.0))
    return x, y, w, h


def find_report_dirs(root: Path) -> List[Path]:
    # e.g. Finance.Report
    return sorted(p for p in root.rglob("*.Report") if p.is_dir())


def infer_report_name(report_dir: Path) -> str:
    name = report_dir.name
    if name.endswith(".Report"):
        return name[: -len(".Report")]
    return name


def under_bookmarks(path: Path) -> bool:
    return any(part.lower() == "bookmarks" for part in path.parts)


def collect_pages_for_report(report_dir: Path, root: Path) -> List[Dict[str, Any]]:
    """
    For a given *.Report directory, match your structure:

    Finance.Report/
      definition/
        bookmarks/...
        pages/
          <pageId>/
            page.json
            visuals/
              <visualId>/
                visual.json
          ...
    """
    report_name = infer_report_name(report_dir)
    definition_dir = report_dir / "definition"
    pages_root = definition_dir / "pages"

    if not pages_root.is_dir():
        return []

    pages_out: List[Dict[str, Any]] = []

    for page_dir in sorted(p for p in pages_root.iterdir() if p.is_dir()):
        page_json = page_dir / "page.json"
        if not page_json.is_file() or under_bookmarks(page_json):
            continue

        pobj = read_json(page_json) or {}

        # Page ID is the technical name (e.g. "ReportSection3949...")
        page_id = str(pobj.get("name") or page_dir.name)
        # Friendly name from displayName, fall back to ID/dir
        page_name = str(pobj.get("displayName") or page_dir.name or page_id)

        page_entry: Dict[str, Any] = {
            "id": page_id,
            "name": page_name,
            "report": report_name,
            "path": str(page_json.relative_to(root)).replace("\\", "/"),
            "visuals": [],
        }

        visuals_root = page_dir / "visuals"
        if visuals_root.is_dir():
            for visual_dir in sorted(p for p in visuals_root.iterdir() if p.is_dir()):
                visual_json = visual_dir / "visual.json"
                if not visual_json.is_file() or under_bookmarks(visual_json):
                    continue

                vobj = read_json(visual_json) or {}

                vis_id = str(vobj.get("name") or vobj.get("id") or visual_dir.name)
                vis_name = str(vobj.get("name") or visual_dir.name)

                x, y, w, h = extract_xywh_from_position(vobj)
                visual_type = extract_visual_type(vobj)
                title_text = extract_title_text(vobj)

                vis_entry = {
                    "id": vis_id,
                    "name": vis_name,
                    "visualType": visual_type,
                    "titleText": title_text,
                    "path": str(visual_json.relative_to(root)).replace("\\", "/"),
                    "x": x,
                    "y": y,
                    "width": w,
                    "height": h,
                }
                page_entry["visuals"].append(vis_entry)

        pages_out.append(page_entry)

    return pages_out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".", help="Repo root to scan")
    ap.add_argument("--out", default="pbir-mapping.json", help="Output mapping JSON path")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    out_path = Path(args.out).resolve()

    all_pages: List[Dict[str, Any]] = []
    for report_dir in find_report_dirs(root):
        all_pages.extend(collect_pages_for_report(report_dir, root))

    mapping = {
        "version": 1,
        "root": str(root),
        "pages": all_pages,
    }

    out_path.write_text(json.dumps(mapping, indent=2), encoding="utf-8")
    print(f"Wrote mapping: {out_path} (pages={len(all_pages)})")


if __name__ == "__main__":
    main()