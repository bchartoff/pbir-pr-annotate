#!/usr/bin/env python3
import argparse
import os
import sys
import requests


DEFAULT_MARKER = "<!-- pbir-layout-summary -->"


def die(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--comment",
        default="_build_artifacts/pbir-comment.md",
        help="Markdown file to post as PR comment",
    )
    ap.add_argument(
        "--marker",
        default=DEFAULT_MARKER,
        help="Hidden marker used to find/update existing comment",
    )
    args = ap.parse_args()

    token = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("REPO")          # e.g. owner/repo
    pr_number = os.environ.get("PR_NUMBER")

    if not token:
        die("GITHUB_TOKEN not set")
    if not repo:
        die("REPO not set (expected owner/repo)")
    if not pr_number:
        die("PR_NUMBER not set")

    if not os.path.exists(args.comment):
        die(f"Comment file not found: {args.comment}")

    body_md = open(args.comment, encoding="utf-8").read().strip()
    if not body_md:
        die("Comment file is empty")

    final_body = f"{args.marker}\n{body_md}"

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "pbir-pr-annotate",
    }

    comments_url = f"https://api.github.com/repos/{repo}/issues/{pr_number}/comments"

    # Fetch existing comments
    r = requests.get(comments_url, headers=headers)
    if r.status_code != 200:
        die(f"Failed to list PR comments: {r.status_code} {r.text}")

    comments = r.json()

    existing_id = None
    for c in comments:
        if args.marker in (c.get("body") or ""):
            existing_id = c.get("id")
            break

    if existing_id:
        print(f"Updating existing PR comment (id={existing_id})")
        update_url = f"https://api.github.com/repos/{repo}/issues/comments/{existing_id}"
        r = requests.patch(update_url, headers=headers, json={"body": final_body})

        if r.status_code not in (200, 201):
            die(f"Failed to update comment: {r.status_code} {r.text}")
    else:
        print("Creating new PR comment")
        r = requests.post(comments_url, headers=headers, json={"body": final_body})
        if r.status_code not in (200, 201):
            die(f"Failed to create comment: {r.status_code} {r.text}")

    print("PR comment posted successfully")


if __name__ == "__main__":
    main()
