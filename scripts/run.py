#!/usr/bin/env python3
"""figma-to-meta-ads: Approved_ Figma frames -> PAUSED Meta ads.

  run.py ingest                 enumerate + export frames, write assets/manifest.json
  run.py build --dry-run        build every creative spec locally, touch nothing on Meta
  run.py build --sets A,B       upload images and create PAUSED ads for the named sets
  run.py archive --ads ID,ID    archive ads to free slots under the 50-per-ad-set cap

Config comes from env vars (see examples/config.env.example) or --env-file.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import figma_export, imageutil, meta_build  # noqa: E402

from meta_build import AD_CAP_PER_ADSET, Config  # noqa: E402


def load_env_file(path):
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def read_manifest(assets_dir):
    path = os.path.join(assets_dir, "manifest.json")
    if not os.path.exists(path):
        raise SystemExit(f"no {path}; run `run.py ingest` first")
    with open(path) as fh:
        return json.load(fh)


def cmd_ingest(args):
    cfg = Config.from_env(require_meta=False)
    sets, problems = figma_export.ingest(cfg.figma_token, cfg.figma_file_key,
                                         args.assets_dir, only_sets=args.sets)
    with open(os.path.join(args.assets_dir, "manifest.json"), "w") as fh:
        json.dump({"sets": sets, "problems": problems}, fh, indent=2)
    print(f"Ingested {len(sets)} complete set(s): {', '.join(sets) or '(none)'}")
    for p in problems:
        print("  SKIP:", p)


def prepare_images(cfg, ratios):
    """Crop the feed image to a true 4:5, cap the longest side, upload all three."""
    hashes = {}
    for ratio, info in ratios.items():
        path = info["path"]
        if ratio == "4:5":
            path = imageutil.crop_to_ratio(path, path.replace(".png", "_feed45.png"))
        path = imageutil.downscale(path, path.replace(".png", "_up.png"))
        hashes[ratio] = meta_build.upload_image(cfg, path)
    return hashes


def cmd_build(args):
    cfg = Config.from_env(require_figma=False, require_meta=not args.dry_run)
    manifest = read_manifest(args.assets_dir)
    sets = manifest["sets"]
    if args.sets:
        sets = {k: v for k, v in sets.items() if k in args.sets}
    for p in manifest.get("problems", []):
        print("  SKIP:", p)

    existing, free_slots = set(), None
    if not args.dry_run:
        ads = meta_build.adset_ads(cfg)
        live = [a for a in ads if a["effective_status"] != "ARCHIVED"]
        existing = {a["name"] for a in live}
        free_slots = AD_CAP_PER_ADSET - len(live)
        print(f"Ad set has {len(live)}/{AD_CAP_PER_ADSET} non-archived ads, {free_slots} free slot(s)")

    built = 0
    for name, ratios in sets.items():
        ad_name = cfg.ad_name_prefix + name
        copy_path = os.path.join(args.copy_dir, f"{name}.json")
        if ad_name in existing:
            print(f"= {ad_name}: already in ad set, skipping")
            continue
        if not os.path.exists(copy_path):
            print(f"! {ad_name}: no copy file at {copy_path}, skipping")
            continue
        copy = meta_build.load_copy(copy_path)
        if args.dry_run:
            hashes = {r: f"DRYRUN_{r}" for r in ratios}
            spec = meta_build.build_creative_spec(cfg, hashes, copy)
            n_rules = len(spec["asset_feed_spec"]["asset_customization_rules"])
            print(f"~ DRY-RUN {ad_name}: {n_rules} placement rules, {len(copy['bodies'])} bodies, "
                  f"{len(copy['titles'])} titles, 1 description, status PAUSED")
            if args.print_spec:
                print(json.dumps(spec, indent=2))
            built += 1
            continue
        if free_slots is not None and free_slots <= 0:
            print(f"! {ad_name}: ad set is at the {AD_CAP_PER_ADSET}-ad cap. "
                  f"Archive ads with `run.py archive --ads ...` and re-run.")
            break
        hashes = prepare_images(cfg, ratios)
        spec = meta_build.build_creative_spec(cfg, hashes, copy)
        creative_id = meta_build.create_creative(cfg, ad_name, spec)
        ad_id = meta_build.create_ad(cfg, ad_name, creative_id)
        free_slots -= 1
        built += 1
        print(f"+ {ad_name}: creative {creative_id} -> ad {ad_id} (PAUSED)")
    print(f"{'Would build' if args.dry_run else 'Built'} {built} ad(s).")


def cmd_archive(args):
    cfg = Config.from_env(require_figma=False)
    for ad_id in args.ads:
        meta_build.archive_ad(cfg, ad_id)
        print(f"archived {ad_id}")
    live = [a for a in meta_build.adset_ads(cfg) if a["effective_status"] != "ARCHIVED"]
    print(f"Ad set now has {len(live)}/{AD_CAP_PER_ADSET} non-archived ads")


def _csv(arg):
    return [x.strip() for x in arg.split(",") if x.strip()] if arg else None


def main(argv=None):
    ap = argparse.ArgumentParser(prog="run.py", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--env-file", help="KEY=VALUE file to load into the environment first")
    ap.add_argument("--assets-dir", default="assets", help="where exported PNGs go (default: ./assets)")
    ap.add_argument("--copy-dir", default="copy", help="where <set>.json copy files live (default: ./copy)")
    sub = ap.add_subparsers(dest="stage", required=True)

    p = sub.add_parser("ingest", help="enumerate Approved_ frames in Figma and export PNGs")
    p.add_argument("--sets", type=_csv, help="comma-separated set names to limit to")

    p = sub.add_parser("build", help="create one PAUSED ad per complete set")
    p.add_argument("--sets", type=_csv, help="comma-separated set names to limit to")
    p.add_argument("--dry-run", action="store_true", help="build specs locally; no Meta calls")
    p.add_argument("--print-spec", action="store_true", help="with --dry-run, print each creative spec")

    p = sub.add_parser("archive", help="archive ads by id to free slots in the ad set")
    p.add_argument("--ads", type=_csv, required=True, help="comma-separated ad ids")

    args = ap.parse_args(argv)
    if args.env_file:
        load_env_file(args.env_file)
    {"ingest": cmd_ingest, "build": cmd_build, "archive": cmd_archive}[args.stage](args)


if __name__ == "__main__":
    main()
