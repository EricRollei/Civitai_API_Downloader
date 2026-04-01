from civitai_tool.gui import run_app

if __name__ == "__main__":
    run_app()
    raise SystemExit

import json
import os
import re
import tkinter as tk
from tkinter import ttk, scrolledtext
import requests
from urllib.parse import urlparse, urlunparse
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple
import time

SETTINGS_FILE = Path(__file__).with_name("settings.json")

VALID_GALLERY_SORTS = [
    "Most Reactions",
    "Most Comments",
    "Most Collected",
    "Newest",
    "Oldest",
    "Random",
]

SORT_ALIASES = {
    "MostReactions": "Most Reactions",
    "MostLikes": "Most Reactions",
    "MostComments": "Most Comments",
    "MostCollected": "Most Collected",
    "MostTipped": "Most Collected",
    "HighestRated": "Most Reactions",
    "Newest": "Newest",
    "Oldest": "Oldest",
    "Random": "Random",
}

UUID_PATTERN = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)

VIDEO_EXTENSIONS = {".mp4", ".webm", ".mov", ".m4v"}
DEFAULT_VIDEO_WIDTH = 720


def normalize_gallery_sort(raw_value: Optional[str]) -> str:
    if not raw_value:
        return VALID_GALLERY_SORTS[0]

    cleaned = str(raw_value).strip()
    if cleaned in VALID_GALLERY_SORTS:
        return cleaned

    collapsed = cleaned.replace(" ", "")
    if collapsed in SORT_ALIASES:
        return SORT_ALIASES[collapsed]

    for key, mapped in SORT_ALIASES.items():
        if cleaned.lower() == key.lower():
            return mapped

    return VALID_GALLERY_SORTS[0]


def coerce_bool(value: object, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
        return default
    if isinstance(value, (int, float)):
        return bool(value)
    return default


def load_settings() -> Dict[str, object]:
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as handle:
            data = json.load(handle)
            if isinstance(data, dict):
                return data
    except FileNotFoundError:
        pass
    except Exception as exc:
        print(f"Failed to load settings: {exc}")
    return {}


def save_settings() -> None:
    settings = {
        "limit": limit_var.get().strip(),
        "max_downloads": max_downloads_var.get().strip(),
        "post_id": post_id_var.get().strip(),
        "model_id": model_id_var.get().strip(),
        "model_version_id": model_version_id_var.get().strip(),
        "username": username_var.get().strip(),
        "api_key": api_key_var.get().strip(),
        "nsfw": nsfw_var.get(),
        "period": period_var.get(),
        "page_start": page_start_var.get().strip(),
        "page_end": page_end_var.get().strip(),
        "preview": bool(preview_var.get()),
        "originals": bool(originals_var.get()),
        "workflows": bool(workflows_var.get()),
        "videos": bool(videos_var.get()),
        "gallery_use": bool(gallery_var.get()),
        "gallery_sort": normalize_gallery_sort(gallery_sort_var.get()),
        "gallery_base_models": gallery_base_models_var.get().strip(),
        "gallery_tag_ids": gallery_tag_ids_var.get().strip(),
        "gallery_tool_ids": gallery_tool_ids_var.get().strip(),
        "gallery_technique_ids": gallery_technique_ids_var.get().strip(),
        "gallery_with_meta": bool(gallery_with_meta_var.get()),
        "gallery_native": bool(gallery_native_size_var.get()),
    }

    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as handle:
            json.dump(settings, handle, indent=2)
    except Exception as exc:
        print(f"Failed to save settings: {exc}")


def apply_settings(settings: Dict[str, object]) -> None:
    limit_var.set(settings.get("limit", limit_var.get()))
    max_downloads_var.set(settings.get("max_downloads", max_downloads_var.get()))
    post_id_var.set(settings.get("post_id", post_id_var.get()))
    model_id_var.set(settings.get("model_id", model_id_var.get()))
    model_version_id_var.set(settings.get("model_version_id", model_version_id_var.get()))
    username_var.set(settings.get("username", username_var.get()))
    api_key_var.set(settings.get("api_key", api_key_var.get()))
    nsfw_var.set(settings.get("nsfw", nsfw_var.get()))
    period_var.set(settings.get("period", period_var.get()))
    page_start_var.set(settings.get("page_start", page_start_var.get()))
    page_end_var.set(settings.get("page_end", page_end_var.get()))
    preview_var.set(coerce_bool(settings.get("preview"), preview_var.get()))
    originals_var.set(coerce_bool(settings.get("originals"), originals_var.get()))
    workflows_var.set(coerce_bool(settings.get("workflows"), workflows_var.get()))
    videos_var.set(coerce_bool(settings.get("videos"), videos_var.get()))
    gallery_var.set(coerce_bool(settings.get("gallery_use"), gallery_var.get()))
    gallery_sort_var.set(normalize_gallery_sort(settings.get("gallery_sort")))
    gallery_base_models_var.set(settings.get("gallery_base_models", gallery_base_models_var.get()))
    gallery_tag_ids_var.set(settings.get("gallery_tag_ids", gallery_tag_ids_var.get()))
    gallery_tool_ids_var.set(settings.get("gallery_tool_ids", gallery_tool_ids_var.get()))
    gallery_technique_ids_var.set(settings.get("gallery_technique_ids", gallery_technique_ids_var.get()))
    gallery_with_meta_var.set(coerce_bool(settings.get("gallery_with_meta"), gallery_with_meta_var.get()))
    gallery_native_size_var.set(coerce_bool(settings.get("gallery_native"), gallery_native_size_var.get()))


def fetch_images():
    """Download assets based on the selected options."""

    # Read values from GUI
    raw_limit = limit_var.get().strip()
    raw_max_downloads = max_downloads_var.get().strip()
    post_id = post_id_var.get().strip()
    model_id = model_id_var.get().strip()
    model_version_id = model_version_id_var.get().strip()
    username = username_var.get().strip()
    api_key = api_key_var.get().strip()
    nsfw_value = nsfw_var.get()
    period = period_var.get()
    page_start = int(page_start_var.get())
    page_end = int(page_end_var.get())
    grab_previews = preview_var.get()
    grab_originals = originals_var.get()
    grab_workflows = workflows_var.get()
    grab_videos = videos_var.get()
    gallery_requested = gallery_var.get()
    fallback_gallery = grab_originals and not model_version_id
    use_gallery = gallery_requested or fallback_gallery
    gallery_sort = normalize_gallery_sort(gallery_sort_var.get())
    gallery_sort_var.set(gallery_sort)
    gallery_types: List[str] = []
    if grab_previews or grab_originals:
        gallery_types.append("image")
    if grab_videos:
        gallery_types.append("video")
    if gallery_types:
        gallery_types = list(dict.fromkeys(gallery_types))
    if not gallery_types:
        gallery_types = ["image"]

    base_models = [bm.strip() for bm in gallery_base_models_var.get().split(",") if bm.strip()]
    gallery_model_ids, invalid_model_tokens = parse_int_csv(model_id)
    gallery_version_ids, invalid_version_tokens = parse_int_csv(model_version_id)
    gallery_post_ids, invalid_post_tokens = parse_int_csv(post_id)
    gallery_tag_ids, invalid_tag_tokens = parse_int_csv(gallery_tag_ids_var.get())
    gallery_tool_ids, invalid_tool_tokens = parse_int_csv(gallery_tool_ids_var.get())
    gallery_technique_ids, invalid_tech_tokens = parse_int_csv(gallery_technique_ids_var.get())
    prefer_native = gallery_native_size_var.get()
    save_meta = gallery_with_meta_var.get()
    fetch_meta = save_meta or grab_videos

    save_settings()

    # Clear output box before reporting anything
    output_box.delete(1.0, tk.END)

    if use_gallery:
        if invalid_tag_tokens:
            output_box.insert(tk.END, f"⚠️ Invalid tag IDs ignored: {', '.join(invalid_tag_tokens)}\n")
        if invalid_tool_tokens:
            output_box.insert(tk.END, f"⚠️ Invalid tool IDs ignored: {', '.join(invalid_tool_tokens)}\n")
        if invalid_tech_tokens:
            output_box.insert(tk.END, f"⚠️ Invalid technique IDs ignored: {', '.join(invalid_tech_tokens)}\n")
        if invalid_model_tokens:
            output_box.insert(tk.END, f"⚠️ Invalid model IDs ignored: {', '.join(invalid_model_tokens)}\n")
        if invalid_version_tokens:
            output_box.insert(tk.END, f"⚠️ Invalid model version IDs ignored: {', '.join(invalid_version_tokens)}\n")
        if invalid_post_tokens:
            output_box.insert(tk.END, f"⚠️ Invalid post IDs ignored: {', '.join(invalid_post_tokens)}\n")

    try:
        limit_value = int(raw_limit)
    except ValueError:
        limit_value = 100
        output_box.insert(tk.END, "⚠️ Invalid limit provided. Defaulting to 100.\n")

    if limit_value < 1:
        limit_value = 1
    if limit_value > 200:
        output_box.insert(tk.END, "ℹ️ Limit capped at Civitai maximum of 200.\n")
        limit_value = 200

    try:
        max_downloads = int(raw_max_downloads) if raw_max_downloads else 0
    except ValueError:
        max_downloads = 0
        output_box.insert(tk.END, "⚠️ Invalid max downloads value. No cap will be enforced.\n")

    if max_downloads < 0:
        max_downloads = 0

    download_state = {"count": 0, "max": max_downloads}
    detail_cache: Dict[int, Dict] = {}

    # Create base output folder
    base_output_dir = Path(__file__).parent / "downloads"
    base_output_dir.mkdir(exist_ok=True)

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    # Preview downloads (JPEG thumbnails)
    gallery_preview_request = use_gallery and grab_previews
    gallery_original_request = use_gallery and grab_originals

    if gallery_original_request:
        if fallback_gallery and not gallery_requested:
            output_box.insert(
                tk.END,
                "ℹ️ Original image requests without a model version ID use the gallery feed for native files.\n",
            )

        fallback_types = [t for t in gallery_types if t != "video"]
        if fallback_gallery and not gallery_requested and not fallback_types:
            if grab_originals:
                fallback_types.append("image")
        if not fallback_types:
            fallback_types = ["image"]

        fetch_gallery_images(
            headers=headers,
            limit=limit_value,
            page_start=page_start,
            page_end=page_end,
            post_id=post_id,
            post_ids=gallery_post_ids,
            model_id=model_id,
            model_ids=gallery_model_ids,
            model_version_id=model_version_id,
            model_version_ids=gallery_version_ids,
            username=username,
            nsfw_value=nsfw_value,
            period=period,
            sort=gallery_sort,
            types=fallback_types or ["image"],
            base_models=base_models,
            tag_ids=gallery_tag_ids,
            tool_ids=gallery_tool_ids,
            technique_ids=gallery_technique_ids,
            output_dir=base_output_dir / "gallery_originals",
            download_state=download_state,
            prefer_native=True,
            with_meta=fetch_meta,
            save_meta=save_meta,
            detail_cache=detail_cache,
            include_videos=False,
        )

        if reached_limit(download_state):
            output_box.insert(tk.END, "⏹️ Reached maximum download limit.\n")
            return

    if gallery_preview_request:
        preview_types = [t for t in gallery_types if t != "video"] or ["image"]

        fetch_gallery_images(
            headers=headers,
            limit=limit_value,
            page_start=page_start,
            page_end=page_end,
            post_id=post_id,
            post_ids=gallery_post_ids,
            model_id=model_id,
            model_ids=gallery_model_ids,
            model_version_id=model_version_id,
            model_version_ids=gallery_version_ids,
            username=username,
            nsfw_value=nsfw_value,
            period=period,
            sort=gallery_sort,
            types=preview_types,
            base_models=base_models,
            tag_ids=gallery_tag_ids,
            tool_ids=gallery_tool_ids,
            technique_ids=gallery_technique_ids,
            output_dir=base_output_dir / "previews",
            download_state=download_state,
            prefer_native=prefer_native,
            with_meta=fetch_meta,
            save_meta=save_meta,
            detail_cache=detail_cache,
            include_videos=False,
        )

        if reached_limit(download_state):
            output_box.insert(tk.END, "⏹️ Reached maximum download limit.\n")
            return

    preview_images_needed = not gallery_requested and grab_previews
    preview_fetch_needed = preview_images_needed or grab_videos

    if preview_fetch_needed:
        fetch_preview_images(
            headers=headers,
            limit=limit_value,
            page_start=page_start,
            page_end=page_end,
            post_id=post_id,
            model_id=model_id,
            model_version_id=model_version_id,
            username=username,
            nsfw_value=nsfw_value,
            period=period,
            output_dir=base_output_dir / "previews",
            download_state=download_state,
            include_images=preview_images_needed,
            include_videos=grab_videos,
        )

        if reached_limit(download_state):
            output_box.insert(tk.END, "⏹️ Reached maximum download limit.\n")
            return

    # Full assets require a model version id and usually an API key
    asset_types = []
    if grab_originals and not use_gallery:
        asset_types.append("image")
    if grab_workflows:
        asset_types.append("workflow")
    if grab_videos and not use_gallery:
        asset_types.append("video")

    if use_gallery and "image" in asset_types and not model_version_id:
        asset_types.remove("image")
        output_box.insert(
            tk.END,
            "ℹ️ Gallery downloads already attempt the native-resolution image files. Provide a Model Version ID only when you also need workflows or direct version assets.\n",
        )

    if asset_types:
        if not model_version_id:
            output_box.insert(tk.END, "⚠️ Provide a Model Version ID to download original assets.\n")
        else:
            if not api_key:
                output_box.insert(tk.END, "⚠️ Original assets usually require an API key. Proceeding without one may fail.\n")

            version_ids = [v.strip() for v in model_version_id.split(",") if v.strip()]
            for vid in version_ids:
                if reached_limit(download_state):
                    break

                fetch_version_assets(
                    version_id=vid,
                    headers=headers,
                    types=asset_types,
                    output_dir=base_output_dir,
                    download_state=download_state,
                )

            if reached_limit(download_state):
                output_box.insert(tk.END, "⏹️ Reached maximum download limit.\n")


# Helper utilities


def fetch_preview_images(
    *,
    headers: Dict[str, str],
    limit: int,
    page_start: int,
    page_end: int,
    post_id: Optional[str],
    model_id: Optional[str],
    model_version_id: Optional[str],
    username: Optional[str],
    nsfw_value: str,
    period: str,
    output_dir: Path,
    download_state: Dict[str, int],
    include_images: bool,
    include_videos: bool,
) -> None:
    """Download preview media from the public images endpoint."""

    if not include_images and not include_videos:
        return

    output_dir.mkdir(parents=True, exist_ok=True)
    video_dir: Optional[Path] = None
    if include_videos:
        video_dir = output_dir / "videos"
        video_dir.mkdir(parents=True, exist_ok=True)
    base_url = "https://civitai.com/api/v1/images"

    for page in range(page_start, page_end + 1):
        params = {
            "limit": limit,
            "page": page,
        }
        if post_id:
            params["postId"] = post_id
        if model_id:
            params["modelId"] = model_id
        if model_version_id:
            params["modelVersionId"] = model_version_id
        if username:
            params["username"] = username
        if nsfw_value != "None":
            params["nsfw"] = nsfw_value
        if period:
            params["period"] = period
        if include_videos and not include_images:
            params["types"] = "video"
        elif include_images and not include_videos:
            params["types"] = "image"
        elif include_images and include_videos:
            params["types"] = "image,video"
        if include_videos:
            params["metadata"] = "true"

        try:
            response = requests.get(base_url, params=params, headers=headers, timeout=30)
            response.raise_for_status()
            data = response.json()

            for img in data.get("items", []):
                if reached_limit(download_state):
                    return
                item_id = img.get("id")

                if not item_id:
                    continue

                metadata = collect_gallery_metadata({}, img)
                video_url: Optional[str] = None
                if include_videos:
                    video_url = extract_video_url({}, img, metadata)
                    if not video_url:
                        video_url = fallback_preview_video_url(img, metadata)

                if include_videos and video_url:
                    try:
                        numeric_id = int(str(item_id))
                    except (TypeError, ValueError):
                        numeric_id = abs(hash(str(item_id))) % 1_000_000_000

                    filename = build_gallery_filename(numeric_id, {}, img, video_url, default_ext=".mp4")
                    assert video_dir is not None
                    filepath = video_dir / filename

                    if filepath.exists():
                        if not download_state.get("preview_video_skip_notice"):
                            output_box.insert(tk.END, "⏭️  Some preview videos already exist; skipping duplicates.\n")
                            download_state["preview_video_skip_notice"] = True
                        continue

                    if download_file(video_url, filepath, headers):
                        download_state["count"] += 1
                        output_box.insert(tk.END, f"🎞️  Preview video saved: {filename}\n")
                    continue

                if include_videos and not include_images and not video_url:
                    if not download_state.get("preview_video_missing_notice"):
                        output_box.insert(tk.END, "⚠️ Preview feed did not return video URLs; consider retrying or enabling gallery images for inspection.\n")
                        download_state["preview_video_missing_notice"] = True
                    continue

                item_type = (img.get("type") or "image").lower()

                if include_images and (item_type != "video" or not include_videos):
                    img_url = img.get("url")
                    if not img_url:
                        continue

                    parsed_url = urlparse(img_url)
                    ext = os.path.splitext(parsed_url.path)[-1] or ".jpg"
                    filepath = output_dir / f"{item_id}{ext}"

                    if filepath.exists():
                        continue

                    if download_file(img_url, filepath, headers):
                        download_state["count"] += 1
                        output_box.insert(tk.END, f"🖼️  Preview saved: {filepath.name}\n")

        except Exception as e:
            output_box.insert(tk.END, f"❌ Preview error on page {page}: {e}\n")


def fetch_gallery_images(
    *,
    headers: Dict[str, str],
    limit: int,
    page_start: int,
    page_end: int,
    post_id: Optional[str],
    post_ids: List[int],
    model_id: Optional[str],
    model_ids: List[int],
    model_version_id: Optional[str],
    model_version_ids: List[int],
    username: Optional[str],
    nsfw_value: str,
    period: str,
    sort: str,
    types: List[str],
    base_models: List[str],
    tag_ids: List[int],
    tool_ids: List[int],
    technique_ids: List[int],
    output_dir: Path,
    download_state: Dict[str, int],
    prefer_native: bool,
    with_meta: bool,
    save_meta: bool,
    detail_cache: Dict[int, Dict],
    include_videos: bool,
) -> None:
    """Fetch gallery items via the tRPC endpoint to mirror web sorting."""

    output_dir.mkdir(parents=True, exist_ok=True)
    endpoint = "https://civitai.com/api/trpc/image.getInfinite"
    effective_period = period or "AllTime"
    start_page = max(1, page_start)
    end_page = max(start_page, page_end)
    cursor: Optional[str] = None

    for page_index in range(1, end_page + 1):
        if reached_limit(download_state):
            return

        payload = build_gallery_payload(
            cursor=cursor,
            limit=limit,
            sort=sort,
            types=types,
            period=effective_period,
            nsfw_value=nsfw_value,
            base_models=base_models,
            tag_ids=tag_ids,
            tool_ids=tool_ids,
            technique_ids=technique_ids,
            username=username,
            post_id=post_id,
            post_ids=post_ids,
            model_id=model_id,
            model_ids=model_ids,
            model_version_id=model_version_id,
            model_version_ids=model_version_ids,
            include_meta=with_meta,
        )

        batch_payload = {"0": {"json": payload}}
        params = {
            "batch": "1",
            "input": json.dumps(batch_payload, separators=(",", ":")),
        }

        max_retries = 3
        attempt = 1
        result_json: Optional[Dict] = None

        while attempt <= max_retries:
            try:
                response = requests.get(endpoint, headers=headers, params=params, timeout=45)
                response.raise_for_status()
                result_json = extract_gallery_json(response.json())
                break
            except requests.Timeout as timeout_err:
                if attempt >= max_retries:
                    output_box.insert(
                        tk.END,
                        f"❌ Gallery request failed on page {page_index} after {max_retries} timeouts: {timeout_err}\n",
                    )
                    output_box.insert(tk.END, f"ℹ️ Payload snapshot: {json.dumps(payload, indent=2)[:500]}\n")
                    return
                output_box.insert(
                    tk.END,
                    f"⚠️ Gallery request timed out on page {page_index}; retrying ({attempt}/{max_retries}).\n",
                )
                attempt += 1
                time.sleep(min(2 * attempt, 10))
            except requests.HTTPError as http_err:
                detail = http_err.response.text if http_err.response is not None else "(no response body)"
                output_box.insert(
                    tk.END,
                    f"❌ Gallery request failed on page {page_index}: {http_err}. Response: {detail[:500]}\n",
                )
                output_box.insert(tk.END, f"ℹ️ Payload snapshot: {json.dumps(payload, indent=2)[:500]}\n")
                return
            except requests.RequestException as req_err:
                if attempt >= max_retries:
                    output_box.insert(
                        tk.END,
                        f"❌ Gallery request failed on page {page_index} after {max_retries} attempts: {req_err}\n",
                    )
                    output_box.insert(tk.END, f"ℹ️ Payload snapshot: {json.dumps(payload, indent=2)[:500]}\n")
                    return
                output_box.insert(
                    tk.END,
                    f"⚠️ Gallery request error on page {page_index}; retrying ({attempt}/{max_retries}). {req_err}\n",
                )
                attempt += 1
                time.sleep(min(2 * attempt, 10))
            except Exception as exc:
                output_box.insert(tk.END, f"❌ Gallery request failed on page {page_index}: {exc}\n")
                return

        if result_json is None:
            output_box.insert(tk.END, f"⚠️ Gallery request returned no data for page {page_index}.\n")
            return

        if not result_json:
            output_box.insert(tk.END, "⚠️ Unexpected gallery response structure.\n")
            return

        cursor = result_json.get("nextCursor")
        items = result_json.get("items", [])

        if page_index < start_page:
            if not cursor:
                break
            continue

        for item in items:
            if reached_limit(download_state):
                return

            if not passes_nsfw_filter(item, nsfw_value):
                continue

            item_type = item.get("type")

            limit_videos = nsfw_value != "X"

            if item_type == "image" or (item_type == "video" and include_videos and not limit_videos):
                download_gallery_media(
                    item=item,
                    headers=headers,
                    output_dir=output_dir,
                    download_state=download_state,
                    prefer_native=prefer_native,
                    detail_cache=detail_cache,
                    save_meta=save_meta,
                    is_video=item_type == "video",
                )
            elif item_type == "video":
                if not include_videos:
                    if not download_state.get("gallery_video_disabled_notice"):
                        output_box.insert(
                            tk.END,
                            "ℹ️ Gallery video cards skipped; preview endpoint will handle videos.\n",
                        )
                        download_state["gallery_video_disabled_notice"] = True
                elif limit_videos and not download_state.get("gallery_video_notice_shown"):
                    output_box.insert(
                        tk.END,
                        "ℹ️ Gallery videos detected but skipped (enable NSFW 'X' + Videos).\n",
                    )
                    download_state["gallery_video_notice_shown"] = True
            else:
                output_box.insert(tk.END, f"ℹ️ Skipping unsupported gallery item type '{item_type}'.\n")

        if not cursor:
            output_box.insert(tk.END, "ℹ️ No further cursor returned; stopping gallery fetch.\n")
            break


def build_gallery_payload(
    *,
    cursor: Optional[str],
    limit: int,
    sort: str,
    types: List[str],
    period: str,
    nsfw_value: str,
    base_models: List[str],
    tag_ids: List[int],
    tool_ids: List[int],
    technique_ids: List[int],
    username: Optional[str],
    post_id: Optional[str],
    post_ids: List[int],
    model_id: Optional[str],
    model_ids: List[int],
    model_version_id: Optional[str],
    model_version_ids: List[int],
    include_meta: bool,
) -> Dict:
    """Construct the gallery input payload for image.getInfinite."""

    query: Dict[str, object] = {
        "types": types,
        "sort": sort,
        "period": period,
        "view": "feed",
        "hidden": False,
        "withMeta": include_meta,
        "browsing": True,
    }

    if nsfw_value and nsfw_value != "None":
        query["nsfw"] = nsfw_value

    if base_models:
        query["baseModels"] = base_models
    if tag_ids:
        query["tagIds"] = tag_ids
    if tool_ids:
        query["toolIds"] = tool_ids
    if technique_ids:
        query["techniqueIds"] = technique_ids
    if username:
        query["username"] = username

    post_candidates = list(post_ids) if post_ids else []
    parsed_post = safe_int(post_id)
    if parsed_post is not None:
        post_candidates.append(parsed_post)
    if post_candidates:
        post_candidates = list(dict.fromkeys(post_candidates))
        if len(post_candidates) == 1:
            query["postId"] = post_candidates[0]
        else:
            query["postIds"] = post_candidates

    model_candidates = list(model_ids) if model_ids else []
    parsed_model = safe_int(model_id)
    if parsed_model is not None:
        model_candidates.append(parsed_model)
    if model_candidates:
        model_candidates = list(dict.fromkeys(model_candidates))
        if len(model_candidates) == 1:
            query["modelId"] = model_candidates[0]
        else:
            query["modelIds"] = model_candidates

    version_candidates = list(model_version_ids) if model_version_ids else []
    parsed_version = safe_int(model_version_id)
    if parsed_version is not None:
        version_candidates.append(parsed_version)
    if version_candidates:
        version_candidates = list(dict.fromkeys(version_candidates))
        if len(version_candidates) == 1:
            query["modelVersionId"] = version_candidates[0]
        query["modelVersionIds"] = version_candidates

    payload = {
        "limit": limit,
        "period": period,
        "types": types,
        "sort": sort,
        "query": query,
    }

    if cursor is not None:
        payload["cursor"] = cursor

    if include_meta:
        payload["include"] = ["tags", "meta"]

    return payload


def extract_gallery_json(response_json) -> Optional[Dict]:
    """Normalize the gallery response into a dict with items/nextCursor."""

    if isinstance(response_json, list) and response_json:
        entry = response_json[0]
    elif isinstance(response_json, dict):
        if "0" in response_json and isinstance(response_json["0"], dict):
            entry = response_json["0"]
        else:
            entry = response_json
    else:
        return None

    return entry.get("result", {}).get("data", {}).get("json")


def extract_trpc_json(response_json) -> Optional[Dict]:
    if isinstance(response_json, dict):
        if "0" in response_json:
            response_json = response_json["0"]
    elif isinstance(response_json, list) and response_json:
        response_json = response_json[0]
    else:
        return None

    return response_json.get("result", {}).get("data", {}).get("json")


def collect_gallery_metadata(detail: Dict, item: Dict) -> Dict:
    meta: Dict[str, object] = {}
    for candidate in (
        detail.get("metadata"),
        detail.get("meta"),
        item.get("metadata"),
        item.get("meta"),
    ):
        if isinstance(candidate, dict):
            meta.update(candidate)

    width = meta.get("width") or item.get("width") or item.get("originalWidth")
    height = meta.get("height") or item.get("height") or item.get("originalHeight")

    def _coerce_dimension(value: object) -> Optional[int]:
        if value is None:
            return None
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None

    coerced_width = _coerce_dimension(width)
    coerced_height = _coerce_dimension(height)

    if coerced_width is not None and "width" not in meta:
        meta["width"] = coerced_width
    if coerced_height is not None and "height" not in meta:
        meta["height"] = coerced_height

    return meta


def passes_nsfw_filter(item: Dict, nsfw_value: str) -> bool:
    """Client-side NSFW filtering to mirror the UI selection."""

    threshold = nsfw_threshold_from_selection(nsfw_value)
    level = item.get("combinedNsfwLevel")
    if level is None:
        level = item.get("nsfwLevel")
    if level is None:
        return True
    try:
        level_int = int(level)
    except (TypeError, ValueError):
        return True
    return level_int <= threshold


def nsfw_threshold_from_selection(selection: str) -> int:
    mapping = {
        "None": 1,
        "Soft": 2,
        "Mature": 4,
        "X": 8,
    }
    return mapping.get(selection, 8)


def download_gallery_media(
    *,
    item: Dict,
    headers: Dict[str, str],
    output_dir: Path,
    download_state: Dict[str, int],
    prefer_native: bool,
    detail_cache: Dict[int, Dict],
    save_meta: bool,
    is_video: bool,
) -> None:
    media_id = item.get("id")
    if media_id is None:
        output_box.insert(tk.END, "⚠️ Gallery item missing id; skipping.\n")
        return

    detail = get_image_detail(media_id, headers, detail_cache) or {}

    metadata = collect_gallery_metadata(detail, item)

    if is_video:
        media_url = extract_video_url(detail, item, metadata)
        default_ext = ".mp4"
    else:
        media_url = resolve_gallery_image_url(detail, item, metadata, prefer_native)
        default_ext = ".jpg"

    if not media_url:
        detail_source = "video" if is_video else "image"
        output_box.insert(tk.END, f"⚠️ No downloadable URL for gallery {detail_source} item {media_id}.\n")
        return

    filename = build_gallery_filename(media_id, detail, item, media_url, default_ext=default_ext)
    media_dir = output_dir / "videos" if is_video else output_dir
    media_dir.mkdir(parents=True, exist_ok=True)
    filepath = media_dir / filename

    if filepath.exists():
        output_box.insert(
            tk.END,
            f"⏭️  Skipping existing gallery {'video' if is_video else 'image'}: {filename}\n",
        )
        return

    try:
        if download_file(media_url, filepath, headers):
            download_state["count"] += 1
            icon = "🎞️" if is_video else "🖼️"
            output_box.insert(
                tk.END,
                f"{icon}  Gallery {'video' if is_video else 'image'} saved: {filename}\n",
            )
            if save_meta:
                meta_payload = collect_gallery_metadata(detail, item)
                if meta_payload:
                    write_meta_file(filepath, meta_payload)
    except Exception as exc:
        output_box.insert(tk.END, f"❌ Failed to download gallery item {media_id}: {exc}\n")


def get_image_detail(image_id: int, headers: Dict[str, str], cache: Dict[int, Dict]) -> Optional[Dict]:
    if image_id in cache:
        return cache[image_id]

    endpoint = f"https://civitai.com/api/v1/images/{image_id}"
    try:
        response = requests.get(endpoint, headers=headers, timeout=30)
        response.raise_for_status()
        data = response.json()
        if isinstance(data, dict):
            cache[image_id] = data
            return data
        output_box.insert(tk.END, f"⚠️ Unexpected detail format for image {image_id}.\n")
    except requests.HTTPError as http_err:
        status = http_err.response.status_code if http_err.response is not None else None
        if status == 404:
            detail = fetch_trpc_image_detail(image_id, headers)
            if detail:
                cache[image_id] = detail
                return detail
            output_box.insert(tk.END, f"⚠️ Gallery detail not found via REST or tRPC for id {image_id}.\n")
        else:
            output_box.insert(tk.END, f"❌ Failed to fetch image details for {image_id}: {http_err}\n")
    except Exception as exc:
        output_box.insert(tk.END, f"❌ Failed to fetch image details for {image_id}: {exc}\n")

    cache[image_id] = {}
    return None


def fetch_trpc_image_detail(image_id: int, headers: Dict[str, str]) -> Optional[Dict]:
    endpoint = "https://civitai.com/api/trpc/image.get"
    payload = {"0": {"json": {"id": image_id, "include": ["meta", "tags"]}}}
    params = {
        "batch": "1",
        "input": json.dumps(payload, separators=(",", ":")),
    }

    try:
        response = requests.get(endpoint, headers=headers, params=params, timeout=30)
        response.raise_for_status()
        detail_json = extract_trpc_json(response.json())
        if isinstance(detail_json, dict):
            return detail_json
    except Exception as exc:
        output_box.insert(tk.END, f"⚠️ tRPC detail lookup failed for {image_id}: {exc}\n")

    return None


def adjust_image_url(url: str, metadata: Dict, prefer_native: bool) -> str:
    if not prefer_native or not metadata:
        return url

    adjusted = url
    width = metadata.get("width")
    height = metadata.get("height")
    if width:
        adjusted = re.sub(r"width=\d+", f"width={int(width)}", adjusted)
    if height:
        adjusted = re.sub(r"height=\d+", f"height={int(height)}", adjusted)
    return adjusted


KNOWN_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"}


def build_gallery_filename(image_id: int, detail: Dict, item: Dict, url: str, *, default_ext: str) -> str:
    raw_name = detail.get("name") or detail.get("id") or item.get("url") or str(image_id)
    name_root, name_ext = os.path.splitext(str(raw_name))
    safe_base = sanitize_filename(name_root if name_ext else str(raw_name))
    normalized_name_ext = name_ext.lower() if name_ext else ""

    parsed_path = urlparse(url).path
    ext = os.path.splitext(parsed_path)[-1]
    if not ext:
        meta = detail.get("meta") or detail.get("metadata") or item.get("metadata") or {}
        candidate = meta.get("extension") or meta.get("format") or meta.get("mimeType")
        if isinstance(candidate, str):
            candidate = candidate.strip().lower()
            if candidate.startswith("image/"):
                candidate = candidate.split("/", 1)[-1]
            candidate = candidate.lstrip(".")
            if candidate:
                ext = f".{candidate}"
    if not ext:
        ext = default_ext
    if not ext.startswith("."):
        ext = f".{ext}"
    if ext == default_ext and normalized_name_ext in KNOWN_IMAGE_EXTENSIONS:
        ext = normalized_name_ext
    return f"{image_id}_{safe_base}{ext}"


def sanitize_filename(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
    return cleaned or "file"


def build_guid_url(guid: Optional[str], metadata: Dict, prefer_native: bool) -> Optional[str]:
    if not guid:
        return None

    width = metadata.get("width") if prefer_native else None
    if width:
        return f"https://image.civitai.com/xG1nkqKTMzGDvpLrqQqA8w/{guid}/width={int(width)}"
    return f"https://image.civitai.com/xG1nkqKTMzGDvpLrqQqA8w/{guid}/width=1024"


def resolve_gallery_image_url(detail: Dict, item: Dict, metadata: Dict, prefer_native: bool) -> Optional[str]:
    candidates: List[str] = []

    for key in ("url", "imageUrl", "originalUrl"):
        value = detail.get(key)
        if isinstance(value, str):
            candidates.append(value)

    meta_sources = [detail.get("meta"), detail.get("metadata"), item.get("meta"), item.get("metadata")]
    for meta in meta_sources:
        if isinstance(meta, dict):
            for key in ("imageUrl", "url", "downloadUrl", "civitaiUrl", "originalUrl", "source"):
                maybe = meta.get(key)
                if isinstance(maybe, str):
                    candidates.append(maybe)
                elif isinstance(maybe, dict):
                    for sub_key in ("url", "downloadUrl", "civitaiUrl", "source"):
                        nested = maybe.get(sub_key)
                        if isinstance(nested, str):
                            candidates.append(nested)
                elif isinstance(maybe, list):
                    for entry in maybe:
                        if isinstance(entry, dict):
                            for sub_key in ("url", "downloadUrl", "civitaiUrl", "source"):
                                nested = entry.get(sub_key)
                                if isinstance(nested, str):
                                    candidates.append(nested)

    for key in ("imageUrl", "url"):
        value = item.get(key)
        if isinstance(value, str):
            candidates.append(value)

    guid_candidates: List[str] = []
    for candidate in candidates:
        normalized = normalize_gallery_url(candidate, metadata, prefer_native)
        if normalized:
            return normalized

        if isinstance(candidate, str):
            stripped = candidate.strip()
            if stripped and UUID_PATTERN.match(stripped):
                guid_candidates.append(stripped)

    if guid_candidates:
        for guid in guid_candidates:
            resolved = build_guid_url(guid, metadata, prefer_native)
            if resolved:
                return resolved

    fallback_guid = item.get("url")
    if isinstance(fallback_guid, str) and UUID_PATTERN.match(fallback_guid.strip()):
        return build_guid_url(fallback_guid.strip(), metadata, prefer_native)

    return None


def normalize_gallery_url(candidate: Optional[str], metadata: Dict, prefer_native: bool) -> Optional[str]:
    if not isinstance(candidate, str):
        return None

    value = candidate.strip()
    if not value:
        return None

    lowered = value.lower()
    if lowered.startswith("http://") or lowered.startswith("https://"):
        return adjust_image_url(value, metadata, prefer_native)

    if lowered.startswith("//"):
        return adjust_image_url(f"https:{value}", metadata, prefer_native)

    if value.startswith("/"):
        return adjust_image_url(f"https://civitai.com{value}", metadata, prefer_native)

    if lowered.startswith("image.civitai.com") or lowered.startswith("media.civitai.com") or lowered.startswith("cdn.civitai.com"):
        return adjust_image_url(f"https://{value}", metadata, prefer_native)

    if UUID_PATTERN.match(value):
        return build_guid_url(value, metadata, prefer_native)

    return None


def is_video_url(url: Optional[str]) -> bool:
    if not isinstance(url, str):
        return False

    try:
        path = urlparse(url).path
    except Exception:
        return False

    ext = os.path.splitext(path)[-1].lower()
    return ext in VIDEO_EXTENSIONS


def build_video_guid_url(guid: Optional[str], item_id: Optional[int], metadata: Dict) -> Optional[str]:
    if not guid or item_id is None:
        return None

    meta_dict = metadata if isinstance(metadata, dict) else {}

    width = meta_dict.get("width") or meta_dict.get("originalWidth")
    try:
        width_value = int(float(width)) if width else DEFAULT_VIDEO_WIDTH
    except (TypeError, ValueError):
        width_value = DEFAULT_VIDEO_WIDTH

    try:
        return (
            f"https://image.civitai.com/xG1nkqKTMzGDvpLrqFT7WA/{guid}/"
            f"transcode=true,width={width_value},optimized=true/{int(item_id)}.mp4"
        )
    except (TypeError, ValueError):
        return None


def build_video_url_from_poster(poster_url: Optional[str], item_id: Optional[int], metadata: Dict) -> Optional[str]:
    if not isinstance(poster_url, str) or item_id is None:
        return None

    try:
        parsed = urlparse(poster_url)
    except Exception:
        return None

    if not parsed.scheme or not parsed.netloc:
        return None

    segments = [seg for seg in parsed.path.split("/") if seg]
    if len(segments) < 3:
        return None

    meta_dict = metadata if isinstance(metadata, dict) else {}

    width = meta_dict.get("width") or meta_dict.get("originalWidth")
    try:
        width_value = int(float(width)) if width else None
    except (TypeError, ValueError):
        width_value = None

    param_tokens = [token for token in segments[-2].split(",") if token]
    param_tokens = [token for token in param_tokens if token not in {"anim=false", "original=false"}]

    if width_value is not None:
        replaced = False
        for idx, token in enumerate(param_tokens):
            if token.startswith("width="):
                param_tokens[idx] = f"width={width_value}"
                replaced = True
        if not replaced:
            param_tokens.append(f"width={width_value}")

    if not any(token.startswith("transcode=") for token in param_tokens):
        param_tokens.insert(0, "transcode=true")
    if not any(token.startswith("optimized=") for token in param_tokens):
        param_tokens.append("optimized=true")

    segments[-2] = ",".join(param_tokens)
    try:
        segments[-1] = f"{int(item_id)}.mp4"
    except (TypeError, ValueError):
        return None

    new_path = "/" + "/".join(segments)
    rebuilt = urlunparse((parsed.scheme, parsed.netloc, new_path, "", "", ""))
    return rebuilt


def extract_video_url(detail: Dict, item: Dict, metadata: Dict) -> Optional[str]:
    candidates: List[str] = []

    def append_candidate(value: Optional[object]) -> None:
        if isinstance(value, str):
            candidates.append(value)
        elif isinstance(value, dict):
            for key in ("downloadUrl", "url", "videoUrl", "civitaiUrl", "originalUrl", "source", "signedUrl"):
                append_candidate(value.get(key))
        elif isinstance(value, list):
            for entry in value:
                append_candidate(entry)

    for key in ("videoUrl", "originalVideoUrl", "url"):
        append_candidate(detail.get(key))

    append_candidate(detail.get("video"))
    append_candidate((detail.get("meta") or detail.get("metadata")))

    append_candidate(item.get("video"))
    for key in ("videoUrl", "originalVideoUrl", "url", "source"):
        append_candidate(item.get(key))

    append_candidate(item.get("resources"))
    append_candidate(item.get("files"))
    append_candidate(item.get("attachments"))

    append_candidate(metadata)
    append_candidate(item.get("metadata"))
    append_candidate(item.get("meta"))

    seen: set = set()
    for candidate in candidates:
        normalized = normalize_video_url(candidate)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        return normalized

    poster_url = None
    if isinstance(metadata, dict):
        poster_url = metadata.get("cover") or metadata.get("poster") or metadata.get("preview")
    if not poster_url:
        poster_url = item.get("cover") or item.get("previewImage")

    numeric_id = safe_int(item.get("id"))

    poster_video = build_video_url_from_poster(poster_url, numeric_id, metadata)
    if poster_video and is_video_url(poster_video):
        return poster_video

    guid = item.get("url")
    if not guid and isinstance(metadata, dict):
        guid = metadata.get("hash") or metadata.get("guid")
    guid_video = None
    if isinstance(guid, str) and UUID_PATTERN.match(guid.strip()) and numeric_id is not None:
        guid_video = build_video_guid_url(guid.strip(), numeric_id, metadata)

    if guid_video and is_video_url(guid_video):
        return guid_video

    return None


def fallback_preview_video_url(item: Dict, metadata: Dict) -> Optional[str]:
    candidates: List[str] = []

    for key in ("videoUrl", "originalVideoUrl", "video", "animationUrl"):
        value = metadata.get(key) if isinstance(metadata, dict) else None
        if isinstance(value, str):
            candidates.append(value)

    for key in ("url", "imageUrl", "videoUrl", "cover"):
        value = item.get(key)
        if isinstance(value, str):
            candidates.append(value)

    for candidate in candidates:
        normalized = normalize_video_url(candidate)
        if normalized:
            return normalized

    poster_url = None
    if isinstance(metadata, dict):
        poster_url = metadata.get("cover") or metadata.get("poster") or metadata.get("preview")
    if not poster_url:
        poster_url = item.get("cover") or item.get("previewImage")

    numeric_id = safe_int(item.get("id"))

    poster_video = build_video_url_from_poster(poster_url, numeric_id, metadata)
    if poster_video and is_video_url(poster_video):
        return poster_video

    guid = item.get("url")
    if not guid and isinstance(metadata, dict):
        guid = metadata.get("hash") or metadata.get("guid")
    if isinstance(guid, str) and UUID_PATTERN.match(guid.strip()) and numeric_id is not None:
        guid_video = build_video_guid_url(guid.strip(), numeric_id, metadata)
        if guid_video and is_video_url(guid_video):
            return guid_video

    return None


def normalize_video_url(candidate: Optional[str]) -> Optional[str]:
    if not isinstance(candidate, str):
        return None

    value = candidate.strip()
    if not value:
        return None

    lowered = value.lower()

    if lowered.startswith("http://") or lowered.startswith("https://"):
        return value if is_video_url(value) else None

    if lowered.startswith("//"):
        normalized = f"https:{value}"
        return normalized if is_video_url(normalized) else None

    if value.startswith("/"):
        normalized = f"https://civitai.com{value}"
        return normalized if is_video_url(normalized) else None

    if (
        lowered.startswith("image.civitai.com")
        or lowered.startswith("media.civitai.com")
        or lowered.startswith("cdn.civitai.com")
    ):
        normalized = f"https://{value}" if not lowered.startswith("https://") else value
        return normalized if is_video_url(normalized) else None

    return None


def write_meta_file(image_path: Path, meta_payload: Dict) -> None:
    try:
        meta_path = image_path.with_suffix(image_path.suffix + ".json")
        with open(meta_path, "w", encoding="utf-8") as handle:
            json.dump(meta_payload, handle, indent=2)
    except Exception as exc:
        output_box.insert(tk.END, f"⚠️ Failed to write metadata for {image_path.name}: {exc}\n")


def parse_int_csv(raw_value: Optional[str]) -> Tuple[List[int], List[str]]:
    if not raw_value:
        return [], []

    values: List[int] = []
    invalid: List[str] = []

    for token in raw_value.split(","):
        cleaned = token.strip()
        if not cleaned:
            continue
        try:
            values.append(int(cleaned))
        except ValueError:
            invalid.append(cleaned)

    return values, invalid


def safe_int(raw_value: Optional[str]) -> Optional[int]:
    if raw_value is None:
        return None
    try:
        return int(str(raw_value).strip())
    except (TypeError, ValueError):
        return None


def fetch_version_assets(
    *,
    version_id: str,
    headers: Dict[str, str],
    types: Iterable[str],
    output_dir: Path,
    download_state: Dict[str, int],
):
    """Fetch original assets (images/workflows/videos) for a model version."""

    endpoint = f"https://civitai.com/api/v1/model-versions/{version_id}"
    try:
        resp = requests.get(endpoint, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        output_box.insert(tk.END, f"❌ Failed to fetch version {version_id}: {exc}\n")
        return

    files = data.get("files", [])
    if not files:
        output_box.insert(tk.END, f"ℹ️  No files listed for version {version_id}.\n")
        return

    for file_info in files:
        if reached_limit(download_state):
            break

        file_type = file_info.get("type", "").lower()
        metadata = file_info.get("metadata", {}) or {}
        fmt = (metadata.get("format") or metadata.get("extension") or "").lower()
        download_url = file_info.get("downloadUrl")

        if not download_url:
            continue

        save_category: Optional[str] = None
        if "image" in types and (file_type == "image" or fmt in {"png", "jpg", "jpeg"}):
            save_category = "original_images"
        elif "workflow" in types and file_type == "workflow":
            save_category = "workflows"
        elif "video" in types and (file_type == "video" or fmt in {"mp4", "webm", "mov"}):
            save_category = "videos"

        if not save_category:
            continue

        filename = build_filename(version_id, file_info, download_url, fmt)
        target_dir = output_dir / save_category
        target_dir.mkdir(parents=True, exist_ok=True)
        filepath = target_dir / filename

        try:
            if download_file(download_url, filepath, headers):
                download_state["count"] += 1
                output_box.insert(tk.END, f"✅ {save_category.title()} saved: {filename}\n")
        except Exception as exc:
            output_box.insert(tk.END, f"❌ Failed to save {filename}: {exc}\n")


def build_filename(version_id: str, file_info: Dict, download_url: str, fmt: str) -> str:
    """Create a descriptive filename with the best available metadata."""

    name_part = file_info.get("name") or file_info.get("id") or "asset"
    parsed = urlparse(download_url)
    ext = os.path.splitext(parsed.path)[-1]

    if not ext and fmt:
        ext = f".{fmt}"
    elif not ext:
        ext = ".bin"

    safe_name = "_".join(name_part.split())  # simple spacing cleanup
    return f"{version_id}_{safe_name}{ext}"


def download_file(url: str, path: Path, headers: Dict[str, str]) -> bool:
    """Download a file to disk, streaming to avoid large memory spikes."""

    response = requests.get(url, headers=headers, stream=True, timeout=60)
    response.raise_for_status()

    with open(path, "wb") as handle:
        for chunk in response.iter_content(chunk_size=8192):
            if chunk:
                handle.write(chunk)

    return True


def reached_limit(download_state: Dict[str, int]) -> bool:
    """Return True when the configured maximum has been reached."""

    max_downloads = download_state.get("max", 0)
    if max_downloads <= 0:
        return False
    return download_state.get("count", 0) >= max_downloads


# GUI Setup
root = tk.Tk()
root.title("Civitai Asset Fetcher")

# Input variables
limit_var = tk.StringVar(value="100")
max_downloads_var = tk.StringVar(value="200")
post_id_var = tk.StringVar()
model_id_var = tk.StringVar()
model_version_id_var = tk.StringVar()
username_var = tk.StringVar()
api_key_var = tk.StringVar()
nsfw_var = tk.StringVar(value="X")
period_var = tk.StringVar(value="AllTime")
page_start_var = tk.StringVar(value="1")
page_end_var = tk.StringVar(value="1")
preview_var = tk.BooleanVar(value=True)
originals_var = tk.BooleanVar(value=True)
workflows_var = tk.BooleanVar(value=False)
videos_var = tk.BooleanVar(value=True)
gallery_var = tk.BooleanVar(value=True)
gallery_sort_var = tk.StringVar(value=VALID_GALLERY_SORTS[0])
gallery_base_models_var = tk.StringVar()
gallery_tag_ids_var = tk.StringVar()
gallery_tool_ids_var = tk.StringVar()
gallery_technique_ids_var = tk.StringVar()
gallery_with_meta_var = tk.BooleanVar(value=False)
gallery_native_size_var = tk.BooleanVar(value=True)

# Load saved preferences, if available
saved_settings = load_settings()
if saved_settings:
    apply_settings(saved_settings)
else:
    gallery_sort_var.set(normalize_gallery_sort(gallery_sort_var.get()))

# Layout
tk.Label(root, text="Limit:").grid(row=0, column=0, sticky="w")
tk.Entry(root, textvariable=limit_var).grid(row=0, column=1)

tk.Label(root, text="Max downloads (0 = unlimited):").grid(row=0, column=2, sticky="w")
tk.Entry(root, textvariable=max_downloads_var, width=6).grid(row=0, column=3, sticky="w")

tk.Label(root, text="Post ID:").grid(row=1, column=0, sticky="w")
tk.Entry(root, textvariable=post_id_var).grid(row=1, column=1)

tk.Label(root, text="Model ID:").grid(row=2, column=0, sticky="w")
tk.Entry(root, textvariable=model_id_var).grid(row=2, column=1)

tk.Label(root, text="Model Version ID:").grid(row=3, column=0, sticky="w")
tk.Entry(root, textvariable=model_version_id_var).grid(row=3, column=1)

tk.Label(root, text="Username:").grid(row=4, column=0, sticky="w")
tk.Entry(root, textvariable=username_var).grid(row=4, column=1)

# NSFW options (single-select using radiobuttons)
tk.Label(root, text="NSFW:").grid(row=5, column=0, sticky="w")
for i, val in enumerate(["None", "Soft", "Mature", "X"]):
    tk.Radiobutton(root, text=val, variable=nsfw_var, value=val).grid(row=5, column=i+1)

# Period dropdown
tk.Label(root, text="Period:").grid(row=6, column=0, sticky="w")
period_dropdown = ttk.Combobox(root, textvariable=period_var, values=["AllTime", "Year", "Month", "Week", "Day"])
period_dropdown.grid(row=6, column=1)

# Page range
tk.Label(root, text="Page Start:").grid(row=7, column=0, sticky="w")
tk.Entry(root, textvariable=page_start_var).grid(row=7, column=1)

tk.Label(root, text="Page End:").grid(row=8, column=0, sticky="w")
tk.Entry(root, textvariable=page_end_var).grid(row=8, column=1)

tk.Label(root, text="API Key:").grid(row=9, column=0, sticky="w")
tk.Entry(root, textvariable=api_key_var, show="*").grid(row=9, column=1)

# Asset options
options_frame = tk.LabelFrame(root, text="Download Options")
options_frame.grid(row=10, column=0, columnspan=5, pady=5, sticky="we")

tk.Checkbutton(options_frame, text="Preview thumbnails (JPEG)", variable=preview_var).grid(row=0, column=0, sticky="w")
tk.Checkbutton(options_frame, text="Original images", variable=originals_var).grid(row=0, column=1, sticky="w")
tk.Checkbutton(options_frame, text="Workflows", variable=workflows_var).grid(row=0, column=2, sticky="w")
tk.Checkbutton(options_frame, text="Videos", variable=videos_var).grid(row=0, column=3, sticky="w")

# Gallery filters
gallery_frame = tk.LabelFrame(root, text="Gallery (tRPC) Filters")
gallery_frame.grid(row=11, column=0, columnspan=5, pady=5, sticky="we")

tk.Checkbutton(gallery_frame, text="Use gallery sort (web feed)", variable=gallery_var).grid(row=0, column=0, columnspan=2, sticky="w")
tk.Checkbutton(gallery_frame, text="Prefer native resolution", variable=gallery_native_size_var).grid(row=0, column=2, columnspan=2, sticky="w")

tk.Label(gallery_frame, text="Sort:").grid(row=1, column=0, sticky="w")
ttk.Combobox(
    gallery_frame,
    textvariable=gallery_sort_var,
    values=VALID_GALLERY_SORTS,
    width=18,
    state="readonly",
).grid(row=1, column=1, columnspan=3, sticky="w")

tk.Label(gallery_frame, text="Base models (comma):").grid(row=2, column=0, sticky="w")
tk.Entry(gallery_frame, textvariable=gallery_base_models_var, width=25).grid(row=2, column=1, sticky="w")

tk.Label(gallery_frame, text="Tag IDs (comma):").grid(row=2, column=2, sticky="w")
tk.Entry(gallery_frame, textvariable=gallery_tag_ids_var, width=25).grid(row=2, column=3, columnspan=2, sticky="w")

tk.Label(gallery_frame, text="Tool IDs (comma):").grid(row=3, column=0, sticky="w")
tk.Entry(gallery_frame, textvariable=gallery_tool_ids_var, width=25).grid(row=3, column=1, sticky="w")

tk.Label(gallery_frame, text="Technique IDs (comma):").grid(row=3, column=2, sticky="w")
tk.Entry(gallery_frame, textvariable=gallery_technique_ids_var, width=25).grid(row=3, column=3, columnspan=2, sticky="w")

tk.Checkbutton(gallery_frame, text="Save item metadata (JSON)", variable=gallery_with_meta_var).grid(row=4, column=0, columnspan=3, sticky="w")

# Fetch button
tk.Button(root, text="Fetch Assets", command=fetch_images).grid(row=12, column=0, columnspan=5, pady=10)


def on_close() -> None:
    save_settings()
    root.destroy()


# Output box
output_box = scrolledtext.ScrolledText(root, width=100, height=20)
output_box.grid(row=13, column=0, columnspan=5)

# Run the GUI loop
root.protocol("WM_DELETE_WINDOW", on_close)
root.mainloop()

