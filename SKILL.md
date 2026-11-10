---
name: figma-to-meta-ads
description: "Turn approved Figma frames into PAUSED Meta ads, 50 at a time, with no uploads by hand. Enumerates Approved_{name}_{ratio} frames over the Figma REST API, exports the 4:5, 9:16 and 16:9 PNGs, fixes the two image traps that make feed placements undeliverable or get the creative rejected, and builds one placement-mapped ad per set with 5 primary texts, 5 headlines and 1 description. Triggers on: build the Meta drafts from Figma, push approved frames to Meta, figma to meta ads, draft the ads for this batch."
---

# figma-to-meta-ads

One approved creative in Figma becomes one PAUSED ad in Meta: three aspect ratios mapped to the placements they were drawn for, five primary texts, five headlines, one description, a CTA button. Nothing goes live. A human turns ads on in Ads Manager after looking at them.

The scripts in `scripts/` do the work. This file is the procedure and the reasons behind each step, so you can run it, debug it, or rebuild it in another language.

## Prerequisites

- `pip install requests pillow`
- Env vars from `examples/config.env.example`: `FIGMA_TOKEN` (scope `file_content:read`), `FIGMA_FILE_KEY`, `META_ACCESS_TOKEN`, `META_AD_ACCOUNT`, `META_PAGE_ID`, `META_ADSET_ID`, `DESTINATION_URL`. Optional: `META_IG_USER_ID`, `META_LEAD_FORM_ID`, `AD_NAME_PREFIX`.
- The target ad set exists, is **not** dynamic creative (`is_dynamic_creative=false`), and its `destination_type` matches what the CTA does (website, lead form, or both).

## Stage 0: Name the frames in Figma

Designers name each approved export frame `Approved_{SetName}_{ratio}`, where ratio is exactly `4:5`, `9:16` or `16:9`. Examples: `Approved_ColdBrewLaunch_4:5`, `Approved_Growler_Gift_9:16` (underscores inside the set name are fine; the ratio is always the last token).

A set is complete when all three ratios exist exactly once. Anything else is skipped and reported, never guessed. Frames that are not approved keep any other prefix.

## Stage 1: Ingest (`run.py ingest`)

1. `GET /v1/files/{key}?depth=4` on the Figma REST API with the personal access token. Walk the tree and collect every node whose name starts with `Approved_`. Use the REST API, not the Figma MCP: the MCP's metadata call truncates page children on large files and you will silently miss frames.
2. Parse names, group by set, validate (all three ratios, no duplicates). Print one line per skipped set.
3. Export PNGs with `GET /v1/images/{key}?ids=...&format=png&scale=2` **in chunks of 4 node ids, with retry and backoff** (4 attempts, 2s/4s/6s). Figma cold-renders large frames and returns 400 "Render timeout" when you ask for a full batch at once.
4. Write `assets/manifest.json` with `{set: {ratio: {node_id, path}}}` plus the problems list. `build` reads only this file, so ingest once and build as many times as you like.

## Stage 2: Copy (`copy/<SetName>.json`)

For each set, run `prompts/copy-writer.md` with the 4:5 image attached and your brand notes. It writes exactly 5 bodies, 5 titles, 1 description; see `examples/copy/ColdBrewLaunch.json`. The loader rejects anything else.

Review the copy before building. This is the human gate, and the only one you get before the ad exists (paused) in the account.

## Stage 3: Build (`run.py build --dry-run`, then `run.py build`)

Always dry-run first. It builds every creative spec locally with placeholder hashes, prints the summary per set (and the full JSON with `--print-spec`), and never calls Meta.

For the real build, per set:

1. **Check the cap.** Meta allows **50 ads per ad set, paused ones included** (error 1487809 "Too Many Ads"). Count non-archived ads in the ad set first. Archiving frees slots; deleting is not needed. `run.py archive --ads id,id` does it. Pick zero-spend drafts to archive, and ask the account owner which.
2. **Idempotency.** Skip any set whose ad name (`{AD_NAME_PREFIX}{SetName}`) already exists in the ad set. Re-running after a partial failure only builds what is missing.
3. **Prepare the 4:5 image.** If the exported "4:5" frame is not a true 4:5 (within 1%), center-crop the file to 4:5 before upload. Feed placements accept 0.8 to 1.91; a 2:3 frame (0.667) is silently undeliverable in feed while every other placement works, so nobody notices until spend is flat. Never fix this with `asset_feed_spec.image_crops` on the feed image: the crop creates an extra target rule and the whole creative fails with `#2446035 Invalid Target Rule Count For Format`. The 9:16 and 16:9 images deliver as-is.
4. **Cap the longest side at 1920 px** for all three images. Scale-2 Figma exports can be 13 MB and Meta rejects them with "Resized Image Too Large" or a bare "Invalid parameter".
5. **Upload** each PNG to `POST /{act}/adimages` and keep the three hashes.
6. **Build the creative** with `asset_feed_spec`:
   - `optimization_type: "PLACEMENT"`, `ad_formats: ["AUTOMATIC_FORMAT"]`. This is what makes multi-text plus multi-ratio work on a non-dynamic ad set.
   - `images`: three hashes, each labeled by ratio (`img_4x5`, `img_9x16`, `img_16x9`).
   - `bodies` (5), `titles` (5), `descriptions` (1), `link_urls` (1), `call_to_action_types` and `call_to_actions` (lead form id if set, else the link).
   - `asset_customization_rules`, four of them, each pointing at one image label and the shared body/title/link labels:
     1. `4:5` -> Facebook feed, marketplace, profile feed, business discovery feed, reels overlay, notifications; Instagram stream, profile feed; Threads.
     2. `9:16` -> Facebook story, reels, in-stream video; Instagram story, reels; Messenger story; Audience Network classic and rewarded video.
     3. `16:9` -> Facebook right column, search.
     4. fallback, age-only, `4:5` image.
   - `degrees_of_freedom_spec.creative_features_spec` with individual features only (`text_optimizations`, `advantage_plus_creative`). **Omit `standard_enhancements`**; Meta rejects it on create (subcode 3858504) even though older live creatives still show it.
   - `object_story_spec`: `page_id` and, if present, `instagram_user_id`. Nothing else.
   - No `image_crops` anywhere.
7. `POST /{act}/adcreatives`, then `POST /{act}/ads` with `status: "PAUSED"` and the creative id. Print the ids.

## Stage 4: Verify

Open the ad set in Ads Manager. For one ad from the batch, check the preview in feed, story and right-column, confirm five text variations show under "Text variations", and confirm the ad is paused. Then let the account owner switch them on.

## Rules

- Ads are created PAUSED. This skill never activates anything.
- Dry-run before every real build.
- Never put `image_crops` on the feed image. Pre-crop the file.
- Never send `standard_enhancements` on create.
- One set, one ad. Carousels are a different payload (see README limitations).
- Keep tokens in env vars or an ignored `config.env`. Never in the repo, never in the copy files.
