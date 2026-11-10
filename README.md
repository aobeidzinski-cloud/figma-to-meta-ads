# figma-to-meta-ads

A Claude Code skill (and a small Python tool) that turns approved Figma frames into PAUSED Meta ads. One creative set in, one placement-mapped draft ad out, with 5 primary texts, 5 headlines and 1 description, no uploads by hand.

## What it does
1. Finds every `Approved_{SetName}_{ratio}` frame in a Figma file over the REST API and exports the `4:5`, `9:16` and `16:9` PNGs.
2. Fixes the two image traps that break delivery: an off-ratio feed image (cropped to a true 4:5) and oversize exports (longest side capped at 1920 px).
3. Uploads the images, builds one `asset_feed_spec` creative per set with the right image on the right placement, and creates the ad **PAUSED** in the ad set you name.
4. Skips sets that already exist, skips sets with missing or duplicate frames, and stops at Meta's 50-ads-per-ad-set cap with instructions to archive.

## Install
```bash
git clone <this repo> figma-to-meta-ads
cp -r figma-to-meta-ads ~/.claude/skills/figma-to-meta-ads
pip install requests pillow
```
Open Claude Code in your project and say: "build the Meta drafts from Figma." The skill reads `SKILL.md` and asks for what it needs. You can also run the scripts directly.

## Setup
```bash
cp ~/.claude/skills/figma-to-meta-ads/examples/config.env.example config.env
# fill in the values, then
python3 ~/.claude/skills/figma-to-meta-ads/scripts/run.py --env-file config.env ingest
```
- **Figma token**: a personal access token with the **`file_content:read`** scope. Tokens with other scopes return 403 on `/v1/files` even though they look valid.
- **Meta token**: a long-lived system-user token with `ads_management` that can reach the ad account. The account id works with or without `act_`.
- **Ad set**: must already exist and must not be dynamic creative. Its `destination_type` should match your CTA (website, lead form, or both). If `META_LEAD_FORM_ID` is set the CTA opens that form; otherwise it goes to `DESTINATION_URL`.

## Run
```bash
python3 scripts/run.py --env-file config.env ingest            # Figma -> assets/manifest.json + PNGs
# write copy/<SetName>.json for each set (prompts/copy-writer.md)
python3 scripts/run.py --env-file config.env build --dry-run   # specs only, nothing touches Meta
python3 scripts/run.py --env-file config.env build --sets ColdBrewLaunch,OfficeBox
python3 scripts/run.py --env-file config.env build             # every complete set with copy
python3 scripts/run.py --env-file config.env archive --ads 1234,5678   # free slots under the cap
```
`assets/` and `copy/` are created in the directory you run from. `examples/dry-run-output.txt` shows what a run looks like.

## Gotchas we hit so you don't
- **Figma MCP truncates.** Its metadata call drops page children on large files. Enumerate with the REST API.
- **Figma render timeouts.** `/v1/images` returns 400 "Render timeout" on a cold render of many frames. Export in chunks of 4 with retry and backoff.
- **Off-ratio feed image = silent non-delivery.** A frame named `4:5` that exports as 2:3 is below the feed floor (0.8). Stories and right column keep delivering, so the ad looks alive while feed shows nothing. Pre-crop the file.
- **`image_crops` on the feed image = #2446035.** "Invalid Target Rule Count For Format" is caused by the crop spawning an extra target rule, not by the age range. Remove the crop; crop the file instead.
- **`standard_enhancements` is rejected on create** (subcode 3858504). Older live creatives still show it, so do not copy it from a template. Send individual features.
- **Export size.** Scale-2 frames can exceed Meta's upload limit. The cap at 1920 px is plenty; feed renders around 1080 px.
- **50 ads per ad set**, paused included (error 1487809). Archiving frees a slot; the count drops immediately.
- **The format works on a non-dynamic ad set** because of `optimization_type: PLACEMENT` + `ad_formats: AUTOMATIC_FORMAT`. You do not need Dynamic Creative for 5 texts and 3 ratios.

## Limitations
- Static image ads only. **Carousels are not covered**: they use a different payload (`optimization_type: DEGREES_OF_FREEDOM`, per-card attachments), and Meta allows only `bodies` in a carousel's asset feed, no title or description variations.
- Assumes a **non-dynamic ad set** that already exists. The tool does not create campaigns or ad sets.
- The feed crop is centered. If your text sits at the very top or bottom of a tall frame, design the 4:5 frame as a true 4:5 instead of relying on the crop.
- Placement positions are a snapshot of Meta's list at the time of writing; Meta adds and renames positions. Edit `PLACEMENT_RULES` in `scripts/meta_build.py` if a position is rejected.
- No scheduling. Run it per batch.

## Files
- `SKILL.md`: the procedure and the reasons for each step.
- `scripts/figma_export.py`: enumerate, validate, export (chunked, with retry).
- `scripts/imageutil.py`: true-4:5 crop and 1920 px cap (Pillow).
- `scripts/meta_build.py`: env config, placement rules, creative spec, Graph API calls.
- `scripts/run.py`: `ingest`, `build [--dry-run] [--sets ...] [--print-spec]`, `archive --ads ...`.
- `prompts/copy-writer.md`: produces the 5/5/1 copy JSON for a set.
- `examples/`: env template, one copy file for an invented brand, a sample dry-run.

## License
MIT.
