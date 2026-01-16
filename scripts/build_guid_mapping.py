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
    Convert PBIR formatted strings of form
    "'STRING TEXT'" to "STRING TEXT"
    """
    string = value.strip()
    if len(string) >= 2 and string[0] == "'" and string[-1] == "'":
        string = string[1:-1].strip()
    return string


def extract_visual_type(vobj: Dict[str, Any], visual_path: Path) -> str:
    """
    As per `visualContainer` schema:
    - https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualContainer/2.2.0/schema.json
    - One of either top level `visual` or `visualGroup` is required

    As per `visual` schema: 
    - https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualConfiguration/2.2.0/schema-embedded.json
    - `visualType` is required

    As per `visualGroupConfig` definition:
    - https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualContainer/2.2.0/schema.json#definitions/VisualGroupConfig
    - `displayName` is required
    
    """
    try:
        visual = vobj.get("visual", {}).get("visualType")
        if isinstance(vt, str) and vt.strip():
            return vt.strip()
    except Exception:
        pass

    try:
        visualGroup = vobj.get("visualGroup", {}).get("displayName")
        if isinstance(vg, str) and vg.strip():
            return vg.strip()
    except Exception:
        pass

    raise ValueError(
        f"Unable to determine visual type. "
        f"Expected either visual.visualType or visualGroup.displayName. "
        f"File: {visual_path}"
    )


def extract_title_text(vobj: Dict[str, Any]) -> Optional[str]:
    """
    Look for (non-required):
      visual.visualContainerObjects.title[0].properties.text.expr.Literal.Value
    """
    try:
        title_arr = vobj["visual"]["visualContainerObjects"]["title"]
        if not isinstance(title_arr, list) or not title_arr:
            return None

        title_properties = title_arr[0]["properties"]
        title = title_properties["text"]["expr"]["Literal"]["Value"]
        if not isinstance(title, str):
            return None

        cleaned_title = strip_literal_quotes(title).strip()
        return cleaned_title or None
    except Exception:
        return None


def extract_xywh_from_position(vobj: Dict[str, Any]) -> Tuple[float, float, float, float]:
    """
    As per `visualContainer` schema:
    -  https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualContainer/2.2.0/schema.json
    - `properties` is required

    And as per properties schema:
    - https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualContainer/2.2.0/schema.json#definitions/VisualContainerPosition
    - x, y, height, and width are all required. Yay!

    """
    position  = vobj.get("position", {}) or {}
    x         = float(position.get("x", 0.0))
    y         = float(position.get("y", 0.0))
    width     = float(position.get("width", 1.0))
    height    = float(position.get("height", 1.0))
    
    return x, y, width, height


def find_report_dirs(root: Path) -> List[Path]:
    """
    Recursively find all pbir .Report folders
    """
    return sorted(p for p in root.rglob("*.Report") if p.is_dir())


def get_report_name(report_dir: Path) -> str:
    """
    Extract report name from .Report folder
    """
    name = report_dir.name
    if name.endswith(".Report"):
        return name[: -len(".Report")]
    return name


def under_bookmarks(path: Path) -> bool:
    """
    TO DO: skipping bookmarks for now bc ugh
    """
    return any(part.lower() == "bookmarks" for part in path.parts)


def collect_pages_for_report(report_dir: Path, root: Path) -> List[Dict[str, Any]]:
    """
    
    """
    report_name = get_report_name(report_dir)
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

        page_id = str(pobj.get("name") or page_dir.name)
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
    ap.add_argument("--out", default="_build_artifacts/pbir-mapping.json", help="Output mapping JSON path")
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