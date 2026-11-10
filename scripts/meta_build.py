"""Meta side: config from env, the asset_feed_spec payload, and the Graph API calls.

Format: one ad per creative set on a NON-dynamic ad set, using asset_feed_spec
with optimization_type PLACEMENT and ad_formats AUTOMATIC_FORMAT. Three image
ratios are mapped to placements by label; 5 bodies, 5 titles and 1 description
are shared across every rule so all copy variations run on every placement.
"""
import json
import os
from dataclasses import dataclass

import requests

from figma_export import REQUIRED_RATIOS

AD_CAP_PER_ADSET = 50          # Meta error 1487809 "Too Many Ads"; paused ads count, archived do not
DEFAULT_URL_TAGS = ("utm_source={{site_source_name}}&utm_medium={{placement}}"
                    "&utm_campaign={{campaign.name}}&utm_content={{ad.name}}")


class MetaError(RuntimeError):
    pass


@dataclass
class Config:
    figma_token: str; figma_file_key: str
    meta_token: str; ad_account: str; page_id: str; adset_id: str
    ig_user_id: str; lead_form_id: str
    destination_url: str; display_url: str
    ad_name_prefix: str; cta: str; url_tags: str; graph_api: str

    @classmethod
    def from_env(cls, require_figma=True, require_meta=True):
        env = os.environ.get
        required = ["FIGMA_TOKEN", "FIGMA_FILE_KEY"] if require_figma else []
        if require_meta:
            required += ["META_ACCESS_TOKEN", "META_AD_ACCOUNT", "META_PAGE_ID",
                         "META_ADSET_ID", "DESTINATION_URL"]
        missing = [k for k in required if not env(k)]
        if missing:
            raise SystemExit(f"missing env var(s): {', '.join(missing)} "
                             f"(see examples/config.env.example)")
        account = env("META_AD_ACCOUNT", "")
        if account and not account.startswith("act_"):
            account = "act_" + account
        dest = env("DESTINATION_URL", "")
        return cls(
            figma_token=env("FIGMA_TOKEN", ""), figma_file_key=env("FIGMA_FILE_KEY", ""),
            meta_token=env("META_ACCESS_TOKEN", ""), ad_account=account,
            page_id=env("META_PAGE_ID", ""), adset_id=env("META_ADSET_ID", ""),
            ig_user_id=env("META_IG_USER_ID", ""), lead_form_id=env("META_LEAD_FORM_ID", ""),
            destination_url=dest,
            display_url=env("DISPLAY_URL", "/".join(dest.split("/")[:3]) if dest else ""),
            ad_name_prefix=env("AD_NAME_PREFIX", "Figma_"), cta=env("CTA_TYPE", "LEARN_MORE"),
            url_tags=env("URL_TAGS", DEFAULT_URL_TAGS),
            graph_api=f"https://graph.facebook.com/{env('GRAPH_API_VERSION', 'v23.0')}",
        )


# Each rule maps ONE image ratio to a set of placements. The last rule is the
# age-only fallback and reuses the feed image. age 13-65 is Meta's widest range;
# the rules must not split by demographic or the creative fails #2446035.
_AGE = {"age_min": 13, "age_max": 65}
PLACEMENT_RULES = [
    {"priority": 1, "image_ratio": "4:5", "spec": dict(_AGE,
        publisher_platforms=["facebook", "instagram", "threads"],
        facebook_positions=["feed", "marketplace", "biz_disco_feed", "facebook_reels_overlay",
                            "profile_feed", "notification"],
        instagram_positions=["stream", "profile_feed"], threads_positions=["threads_stream"])},
    {"priority": 2, "image_ratio": "9:16", "spec": dict(_AGE,
        publisher_platforms=["facebook", "instagram", "audience_network", "messenger"],
        facebook_positions=["instream_video", "story", "facebook_reels"],
        instagram_positions=["story", "reels"], messenger_positions=["story"],
        audience_network_positions=["classic", "rewarded_video"])},
    {"priority": 3, "image_ratio": "16:9", "spec": dict(_AGE,
        publisher_platforms=["facebook"], facebook_positions=["right_hand_column", "search"])},
    {"priority": 4, "image_ratio": "4:5", "spec": dict(_AGE)},   # fallback
]


def validate_copy(c):
    for key in ("bodies", "titles", "description"):
        if key not in c:
            raise ValueError(f"copy missing '{key}'")
    if len(c["bodies"]) != 5 or any(not b.strip() for b in c["bodies"]):
        raise ValueError("expected exactly 5 non-empty bodies")
    if len(c["titles"]) != 5 or any(not t.strip() for t in c["titles"]):
        raise ValueError("expected exactly 5 non-empty titles")
    if not isinstance(c["description"], str) or not c["description"].strip():
        raise ValueError("description must be a non-empty string")
    return c


def load_copy(path):
    with open(path) as fh:
        return validate_copy(json.load(fh))


def _img_label(ratio):
    return "img_" + ratio.replace(":", "x")


def build_creative_spec(cfg, image_hashes, copy):
    """image_hashes: {'4:5': hash, '9:16': hash, '16:9': hash}. copy: validated dict.
    The 4:5 image must already be a true 4:5 file. No image_crops here, ever."""
    rules = [{
        "customization_spec": r["spec"],
        "image_label": {"name": _img_label(r["image_ratio"])},
        "body_label": {"name": "body"}, "title_label": {"name": "title"},
        "link_url_label": {"name": "link"}, "priority": r["priority"],
    } for r in PLACEMENT_RULES]
    cta_value = ({"lead_gen_form_id": cfg.lead_form_id} if cfg.lead_form_id
                 else {"link": cfg.destination_url})
    asset_feed_spec = {
        "images": [{"hash": image_hashes[r], "adlabels": [{"name": _img_label(r)}]}
                   for r in REQUIRED_RATIOS],
        "bodies": [{"text": b, "adlabels": [{"name": "body"}]} for b in copy["bodies"]],
        "titles": [{"text": t, "adlabels": [{"name": "title"}]} for t in copy["titles"]],
        "descriptions": [{"text": copy["description"]}],
        "link_urls": [{"website_url": cfg.destination_url, "display_url": cfg.display_url,
                       "adlabels": [{"name": "link"}]}],
        "call_to_action_types": [cfg.cta],
        "call_to_actions": [{"type": cfg.cta, "value": cta_value}],
        "ad_formats": ["AUTOMATIC_FORMAT"],
        "optimization_type": "PLACEMENT",
        "asset_customization_rules": rules,
    }
    story = {"page_id": cfg.page_id}
    if cfg.ig_user_id:
        story["instagram_user_id"] = cfg.ig_user_id
    return {
        "object_story_spec": story,
        "asset_feed_spec": asset_feed_spec,
        # The umbrella `standard_enhancements` field is rejected on create
        # (subcode 3858504). Name individual features only.
        "degrees_of_freedom_spec": {"creative_features_spec": {
            "text_optimizations": {"enroll_status": "OPT_IN"},
            "advantage_plus_creative": {"enroll_status": "OPT_IN"},
        }},
        "url_tags": cfg.url_tags,
    }


def _check(resp):
    body = resp.json()
    if "error" in body:
        err = body["error"]
        raise MetaError(f"{err.get('message')} (code {err.get('code')}, "
                        f"subcode {err.get('error_subcode')})")
    return body


def _get_all(cfg, path, params):
    """Follow Graph API paging and return every row."""
    url, rows = f"{cfg.graph_api}/{path}", []
    params = dict(params, access_token=cfg.meta_token)
    while url:
        body = _check(requests.get(url, params=params, timeout=60))
        rows += body.get("data", [])
        url, params = body.get("paging", {}).get("next"), {}
    return rows


def upload_image(cfg, path):
    """Upload a PNG to /adimages and return its hash."""
    with open(path, "rb") as fh:
        resp = requests.post(f"{cfg.graph_api}/{cfg.ad_account}/adimages",
                             params={"access_token": cfg.meta_token},
                             files={"filename": fh}, timeout=120)
    return next(iter(_check(resp)["images"].values()))["hash"]


def create_creative(cfg, name, spec):
    data = {"access_token": cfg.meta_token, "name": name}
    data.update({k: json.dumps(v) if isinstance(v, (dict, list)) else v for k, v in spec.items()})
    return _check(requests.post(f"{cfg.graph_api}/{cfg.ad_account}/adcreatives",
                                data=data, timeout=120))["id"]


def create_ad(cfg, name, creative_id, status="PAUSED"):
    data = {"access_token": cfg.meta_token, "name": name, "adset_id": cfg.adset_id,
            "creative": json.dumps({"creative_id": creative_id}), "status": status}
    return _check(requests.post(f"{cfg.graph_api}/{cfg.ad_account}/ads",
                                data=data, timeout=120))["id"]


def adset_ads(cfg):
    """Every ad in the ad set as {id, name, effective_status}."""
    return _get_all(cfg, f"{cfg.adset_id}/ads",
                    {"fields": "id,name,effective_status", "limit": 100})


def archive_ad(cfg, ad_id):
    _check(requests.post(f"{cfg.graph_api}/{ad_id}",
                         data={"access_token": cfg.meta_token, "status": "ARCHIVED"}, timeout=60))
