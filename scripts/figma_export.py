"""Figma side: enumerate Approved_{name}_{ratio} frames and export them as PNGs.

Uses the Figma REST API directly. The Figma MCP's metadata call truncates page
children on large files, so it is not safe for enumeration.
"""
import os
import time

import requests

FIGMA_API = "https://api.figma.com/v1"
REQUIRED_RATIOS = ("4:5", "9:16", "16:9")
PREFIX = "Approved_"


def parse_frame_name(name):
    """'Approved_{set}_{ratio}' -> (set, ratio), or None if it does not match."""
    if not name.startswith(PREFIX):
        return None
    parts = name.split("_")
    if len(parts) < 3 or parts[-1] not in REQUIRED_RATIOS:
        return None
    set_name = "_".join(parts[1:-1])
    return (set_name, parts[-1]) if set_name else None


def group_and_validate(frames):
    """frames: [(frame_name, node_id)] -> (complete, problems).

    complete: {set_name: {ratio: node_id}} for sets with every ratio exactly once.
    problems: human-readable reasons for each skipped set."""
    grouped = {}
    for name, node_id in frames:
        parsed = parse_frame_name(name)
        if parsed:
            set_name, ratio = parsed
            grouped.setdefault(set_name, {}).setdefault(ratio, []).append(node_id)
    complete, problems = {}, []
    for set_name, ratios in sorted(grouped.items()):
        dups = [r for r, ids in ratios.items() if len(ids) > 1]
        missing = [r for r in REQUIRED_RATIOS if r not in ratios]
        if dups:
            problems.append(f"{set_name}: duplicate frames for {dups}, skipped")
        elif missing:
            problems.append(f"{set_name}: missing ratio(s) {missing}, skipped")
        else:
            complete[set_name] = {r: ids[0] for r, ids in ratios.items()}
    return complete, problems


def walk_tree(node, out=None):
    """Collect (name, id) for every node whose name starts with the prefix."""
    out = [] if out is None else out
    if node.get("name", "").startswith(PREFIX) and node.get("id"):
        out.append((node["name"], node["id"]))
    for child in node.get("children") or []:
        walk_tree(child, out)
    return out


def fetch_tree(token, file_key, depth=4):
    r = requests.get(f"{FIGMA_API}/files/{file_key}", params={"depth": depth},
                     headers={"X-Figma-Token": token}, timeout=60)
    r.raise_for_status()
    return r.json()["document"]


def _render_urls(token, file_key, ids, scale, retries=4):
    """Render a small chunk of node ids -> {node_id: url}.

    Figma returns 400 'Render timeout' on cold renders of many large frames,
    so render few at a time and back off between attempts."""
    last = None
    for attempt in range(retries):
        r = requests.get(f"{FIGMA_API}/images/{file_key}",
                         params={"ids": ",".join(ids), "format": "png", "scale": scale},
                         headers={"X-Figma-Token": token}, timeout=120)
        last = r
        if r.status_code == 200 and not r.json().get("err"):
            return r.json().get("images", {})
        if attempt < retries - 1:
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"Figma render failed for {ids}: {last.status_code} {last.text[:200]}")


def export_pngs(token, file_key, node_ids, out_dir, scale=2, chunk=4):
    """Download each node as <out_dir>/<node-id>.png. Returns {node_id: path}."""
    os.makedirs(out_dir, exist_ok=True)
    paths = {}
    for i in range(0, len(node_ids), chunk):
        batch = node_ids[i:i + chunk]
        for node_id, url in _render_urls(token, file_key, batch, scale).items():
            if not url:
                continue
            dest = os.path.join(out_dir, node_id.replace(":", "-") + ".png")
            img = requests.get(url, timeout=120)
            img.raise_for_status()
            with open(dest, "wb") as fh:
                fh.write(img.content)
            paths[node_id] = dest
        print(f"  exported {min(i + chunk, len(node_ids))}/{len(node_ids)} frames")
    return paths


def ingest(token, file_key, out_dir, only_sets=None):
    """Enumerate, validate, export. Returns (sets, problems) where
    sets = {set_name: {ratio: {'node_id': ..., 'path': ...}}}."""
    frames = walk_tree(fetch_tree(token, file_key))
    complete, problems = group_and_validate(frames)
    if only_sets:
        complete = {k: v for k, v in complete.items() if k in only_sets}
    all_ids = [nid for ratios in complete.values() for nid in ratios.values()]
    paths = export_pngs(token, file_key, all_ids, out_dir)
    sets = {name: {r: {"node_id": nid, "path": paths.get(nid)} for r, nid in ratios.items()}
            for name, ratios in complete.items()}
    return sets, problems
