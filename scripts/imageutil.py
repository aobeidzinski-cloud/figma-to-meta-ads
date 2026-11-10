"""Image prep before upload (Pillow).

Two fixes that matter:
1. Feed placements go undeliverable when the "4:5" frame exports off-ratio
   (a 2:3 frame is 0.667, below the feed floor of 0.8). Pre-crop the file to a
   true 4:5. Do NOT fix this with asset_feed_spec image_crops: a crop on the
   feed image spawns an extra target rule and Meta rejects the creative with
   "#2446035 Invalid Target Rule Count For Format".
2. Scale-2 Figma exports can exceed Meta's upload size ("Resized Image Too
   Large"). Cap the longest side; feed renders at about 1080 px anyway.
"""
from PIL import Image

FEED_RATIO = 4 / 5
MAX_UPLOAD_DIM = 1920
RATIO_TOLERANCE = 0.01


def centered_crop_box(w, h, target_ratio):
    """Return (left, top, right, bottom) for a centered crop at width/height ratio."""
    if w / h > target_ratio:            # too wide: trim width
        new_w = round(target_ratio * h)
        left = (w - new_w) // 2
        return (left, 0, left + new_w, h)
    new_h = round(w / target_ratio)     # too tall: trim height
    top = (h - new_h) // 2
    return (0, top, w, top + new_h)


def crop_to_ratio(src, dst, target_ratio=FEED_RATIO):
    """Write a centered crop of src at target_ratio to dst. Returns the path to
    upload: src if it already matches, else dst."""
    with Image.open(src) as im:
        w, h = im.size
        if abs(w / h - target_ratio) <= RATIO_TOLERANCE:
            return src
        box = centered_crop_box(w, h, target_ratio)
        print(f"  cropped {w}x{h} -> {box[2]-box[0]}x{box[3]-box[1]} (true {target_ratio:.2f})")
        im.crop(box).save(dst, "PNG")
    return dst


def downscale(src, dst, max_dim=MAX_UPLOAD_DIM):
    """Resize so the longest side is <= max_dim. Returns src if already small enough."""
    with Image.open(src) as im:
        if max(im.size) <= max_dim:
            return src
        im.thumbnail((max_dim, max_dim), Image.LANCZOS)
        im.save(dst, "PNG")
        print(f"  downscaled to {im.size[0]}x{im.size[1]}")
    return dst
