from __future__ import annotations

import json
import os
from collections import Counter
import time
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Set, Tuple

from .api_client import ApiError, CivitaiClient
from .state import AppState, DownloadOptions, FilterState

LogFunc = Callable[[str], None]

VIDEO_EXTENSIONS = (".mp4", ".webm", ".mov", ".m4v")
MODEL_FILE_EXTENSIONS = {".safetensors", ".ckpt", ".pt", ".pth", ".bin", ".onnx"}
WORKFLOW_FILE_EXTENSIONS = {".zip", ".json", ".workflow", ".yaml", ".yml"}


def _slugify(value: str) -> str:
    cleaned = value.strip()
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in cleaned)
    return safe.lower() or "model"


def _folder_segment(value: object, default: str = "item") -> str:
    if value is None:
        return default
    text = str(value).strip()
    if not text:
        return default
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in text)
    return safe or default


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _first_int(*values: object) -> Optional[int]:
    for value in values:
        if value is None:
            continue
        try:
            return int(str(value).strip())
        except (TypeError, ValueError):
            continue
    return None


def _first_str(*values: object) -> Optional[str]:
    for value in values:
        if isinstance(value, str):
            text = value.strip()
            if text:
                return text
    return None


def _resolve_media_paths(
    *,
    model_id: Optional[int],
    model_version_id: Optional[int],
    username: Optional[str],
    fallback: str,
    options: DownloadOptions,
    model_name: Optional[str] = None,
    model_version_name: Optional[str] = None,
) -> Dict[str, Path]:
    root = Path(options.output_root).expanduser()
    _ensure_dir(root)

    if model_id is not None and model_version_id is not None:
        model_segment = _folder_segment(model_id)
        if model_name:
            name_segment = _folder_segment(model_name, "")
            if name_segment:
                model_segment = f"{model_segment}-{name_segment}"
        version_segment = _folder_segment(model_version_id)
        if model_version_name:
            version_name_segment = _folder_segment(model_version_name, "")
            if version_name_segment:
                version_segment = f"{version_segment}-{version_name_segment}"
        base = root / model_segment / version_segment
    elif model_id is not None:
        model_segment = _folder_segment(model_id)
        if model_name:
            name_segment = _folder_segment(model_name, "")
            if name_segment:
                model_segment = f"{model_segment}-{name_segment}"
        base = root / model_segment
    elif username:
        base = root / _folder_segment(username)
    else:
        base = root / _folder_segment(fallback)

    images = base / "images"
    videos = base / "videos"
    workflows = base / "workflows"
    for directory in (base, images, videos, workflows):
        _ensure_dir(directory)
    return {"base": base, "images": images, "videos": videos, "workflows": workflows}


def _choose_video_url(item: Dict) -> Optional[str]:
    meta = item.get("meta") or item.get("metadata") or {}
    for key in ("videoUrl", "animationUrl", "originalVideoUrl", "signedUrl"):
        value = meta.get(key)
        if isinstance(value, str) and value.startswith("http"):
            return value
    direct = item.get("url")
    if isinstance(direct, str) and direct.lower().endswith(VIDEO_EXTENSIONS):
        return direct
    resources = item.get("resources") or []
    if isinstance(resources, list):
        for entry in resources:
            if isinstance(entry, dict):
                for key in ("downloadUrl", "url", "originalUrl"):
                    candidate = entry.get(key)
                    if isinstance(candidate, str) and candidate.lower().endswith(VIDEO_EXTENSIONS):
                        return candidate
    return None


def _determine_model_name(item: Optional[Dict], fallback: str = "misc") -> str:
    if not item:
        return fallback
    name = item.get("modelName") or item.get("model", {}).get("name")
    if isinstance(name, str) and name.strip():
        return name
    username = item.get("username")
    if isinstance(username, str) and username.strip():
        return f"{username}_{fallback}"
    return fallback


WORKFLOW_META_KEYS = {
    "workflow",
    "workflowJson",
    "comfyWorkflow",
    "workflowNodes",
    "graph",
    "graphData",
    "workflowGraph",
}


def _has_embedded_workflow_payload(item: Dict) -> bool:
    meta_sources: List[Dict] = []
    for key in ("meta", "metadata"):
        payload = item.get(key)
        if isinstance(payload, dict):
            meta_sources.append(payload)

    for meta in meta_sources:
        for key in WORKFLOW_META_KEYS:
            value = meta.get(key)
            if value:
                return True
        system = meta.get("system") or meta.get("generator") or meta.get("app")
        if isinstance(system, str) and "comfy" in system.lower():
            return True
        if isinstance(meta.get("type"), str) and "comfy" in meta["type"].lower():
            return True
        workflow_flag = meta.get("hasWorkflow")
        if isinstance(workflow_flag, bool) and workflow_flag:
            return True

    return False


def _normalize_civitai_url(value: str) -> Optional[str]:
    if not isinstance(value, str):
        return None
    token = value.strip()
    if not token:
        return None
    lowered = token.lower()
    if lowered.startswith("http://") or lowered.startswith("https://"):
        return token
    if lowered.startswith("//"):
        return f"https:{token}"
    if token.startswith("/"):
        return f"https://civitai.com{token}"
    if (
        lowered.startswith("image.civitai.com")
        or lowered.startswith("cdn.civitai.com")
        or lowered.startswith("media.civitai.com")
    ):
        return f"https://{token}" if not lowered.startswith("https://") else token
    return None


def _extract_showcase_url(image: Dict) -> Optional[str]:
    candidates: List[str] = []
    for key in ("url", "imageUrl", "originalUrl", "civitaiUrl", "signedUrl", "src"):
        value = image.get(key)
        if isinstance(value, str):
            candidates.append(value)

    resources = image.get("resources")
    if isinstance(resources, list):
        for entry in resources:
            if not isinstance(entry, dict):
                continue
            for key in ("downloadUrl", "url", "originalUrl"):
                resource_value = entry.get(key)
                if isinstance(resource_value, str):
                    candidates.append(resource_value)

    meta = image.get("meta") or image.get("metadata")
    if isinstance(meta, dict):
        for key in ("imageUrl", "url", "originalUrl", "source"):
            meta_value = meta.get(key)
            if isinstance(meta_value, str):
                candidates.append(meta_value)

    for candidate in candidates:
        normalized = _normalize_civitai_url(candidate)
        if normalized:
            return normalized
    return None


def _write_metadata(path: Path, payload: Dict) -> None:
    meta_path = path.with_suffix(path.suffix + ".json")
    with open(meta_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)


def fetch_images_for_filters(client: CivitaiClient, filters: FilterState, options: DownloadOptions, log: LogFunc) -> List[Dict]:
    collected: List[Dict] = []
    cursor: Optional[str] = None
    page: Optional[int] = 1
    remaining = options.max_items if options.max_items > 0 else None

    max_attempts = 3

    while True:
        limit = min(100, remaining) if remaining else 100

        batch: List[Dict]
        metadata: Dict[str, object] = {}

        for attempt in range(1, max_attempts + 1):
            try:
                batch, metadata = client.search_images(
                    limit=limit,
                    cursor=cursor,
                    page=page if cursor is None else None,
                    model_id=filters.model_id,
                    model_version_id=filters.model_version_id,
                    username=filters.username,
                    nsfw=filters.nsfw if filters.nsfw != "None" else "",
                    period=filters.period,
                    sort=filters.sort,
                    types=filters.types,
                    tag_ids=filters.tag_ids,
                    base_models=filters.base_models,
                    timeout=60,
                )
                break
            except ApiError as exc:
                if attempt >= max_attempts:
                    log(f"Image search failed after {max_attempts} attempts: {exc}")
                    return collected
                wait_seconds = min(2 ** attempt, 10)
                log(f"Image search attempt {attempt} failed ({exc}); retrying in {wait_seconds}s…")
                time.sleep(wait_seconds)

        if not batch:
            break
        collected.extend(batch)
        if remaining is not None:
            remaining -= len(batch)
            if remaining <= 0:
                break

        next_cursor = metadata.get("nextCursor")
        next_page_url = metadata.get("nextPage")

        if next_cursor:
            cursor = next_cursor
            page = None
            log("Continuing to next batch of images...")
            continue

        if isinstance(next_page_url, str):
            parsed_cursor, parsed_page = _parse_next_page(next_page_url)
            if parsed_cursor or parsed_page:
                cursor = parsed_cursor
                page = parsed_page
                log("Continuing to next batch of images...")
                continue

        break

    return collected


def _parse_next_page(url: str) -> Tuple[Optional[str], Optional[int]]:
    from urllib.parse import parse_qs, urlparse

    try:
        parsed = urlparse(url)
    except Exception:
        return None, None
    params = parse_qs(parsed.query)
    if "cursor" in params and params["cursor"]:
        return params["cursor"][0], None
    if "page" in params and params["page"]:
        try:
            return None, int(params["page"][0])
        except ValueError:
            return None, None
    return None, None


def download_image_items(
    client: CivitaiClient,
    items: Iterable[Dict],
    state: AppState,
    log: LogFunc,
    *,
    default_version_id: Optional[int] = None,
    default_version_name: Optional[str] = None,
) -> Dict[str, int]:
    counts = {"images": 0, "videos": 0}
    options = state.downloads
    resolved = state.resolved
    resolved_extra = resolved.extra if resolved else {}

    for item in items:
        model_id = _first_int(
            item.get("modelId"),
            state.filters.model_id,
            resolved.model_id if resolved else None,
        )
        model_version_id = _first_int(
            item.get("modelVersionId"),
            state.filters.model_version_id,
            resolved.model_version_id if resolved else None,
        )
        if model_version_id is None and default_version_id is not None:
            try:
                model_version_id = int(default_version_id)
            except (TypeError, ValueError):
                model_version_id = model_version_id
        username = _first_str(
            item.get("username"),
            state.filters.username,
            resolved_extra.get("username") if isinstance(resolved_extra.get("username"), str) else None,
        )
        prefer_username = False
        if state.filters.username and state.filters.model_id is None and state.filters.model_version_id is None:
            prefer_username = True
        if resolved and resolved.entity_type == "creator":
            prefer_username = True
        if prefer_username:
            model_id = None
            model_version_id = None
        fallback = _determine_model_name(item)

        model_candidates: List[object] = [item.get("modelName")]
        model_obj = item.get("model")
        if isinstance(model_obj, dict):
            model_candidates.append(model_obj.get("name"))
        resolved_model_name = resolved_extra.get("modelName")
        if isinstance(resolved_model_name, str):
            model_candidates.append(resolved_model_name)
        resolved_model_obj = resolved_extra.get("model")
        if isinstance(resolved_model_obj, dict):
            model_candidates.append(resolved_model_obj.get("name"))
        if resolved and resolved.model_id == model_id and resolved.name:
            model_candidates.append(resolved.name)
        model_name = _first_str(*model_candidates)

        version_candidates: List[object] = [item.get("modelVersionName")]
        version_obj = item.get("modelVersion")
        if isinstance(version_obj, dict):
            version_candidates.append(version_obj.get("name"))
        resolved_version_name = resolved_extra.get("modelVersionName")
        if isinstance(resolved_version_name, str):
            version_candidates.append(resolved_version_name)
        resolved_version_obj = resolved_extra.get("modelVersion")
        if isinstance(resolved_version_obj, dict):
            version_candidates.append(resolved_version_obj.get("name"))
        if resolved and resolved.model_version_id == model_version_id and resolved.name:
            version_candidates.append(resolved.name)
        if default_version_name:
            try:
                if model_version_id is not None and default_version_id is not None and int(model_version_id) == int(default_version_id):
                    version_candidates.append(default_version_name)
            except (TypeError, ValueError):
                pass
        version_name = _first_str(*version_candidates)
        paths = _resolve_media_paths(
            model_id=model_id,
            model_version_id=model_version_id,
            username=username,
            fallback=fallback,
            options=options,
            model_name=model_name,
            model_version_name=version_name,
        )

        item_id = item.get("id") or item.get("imageId")
        if not item_id:
            continue
        media_type = (item.get("type") or "image").lower()
        has_embedded_workflow = _has_embedded_workflow_payload(item)

        if media_type == "video":
            if not options.grab_videos:
                continue
            video_url = _choose_video_url(item)
            if not video_url:
                log(f"No video URL for {item_id} - skipped")
                continue
            ext = os.path.splitext(video_url)[-1] or ".mp4"
            filename = f"{item_id}{ext}"
            if has_embedded_workflow:
                embedded_media_dir = paths["workflows"] / "embedded_media"
                _ensure_dir(embedded_media_dir)
                target_dir = embedded_media_dir
            else:
                target_dir = paths["videos"]
            target = target_dir / filename
            if target.exists():
                continue
            try:
                client.download_to_path(video_url, str(target))
                counts["videos"] += 1
                destination = "workflow media" if has_embedded_workflow else "video"
                log(f"Saved {destination} {filename} → {target.parent}")
                if options.save_metadata:
                    _write_metadata(target, {key: item.get(key) for key in item.keys()})
            except ApiError as exc:
                log(f"Video failed for {item_id}: {exc}")
            continue

        if not options.grab_previews:
            continue
        image_url = item.get("url")
        if not isinstance(image_url, str) or not image_url.startswith("http"):
            log(f"No image URL for {item_id}")
            continue
        ext = os.path.splitext(urlparse_path(image_url))[-1] or ".jpg"
        filename = f"{item_id}{ext}"
        if has_embedded_workflow:
            embedded_media_dir = paths["workflows"] / "embedded_media"
            _ensure_dir(embedded_media_dir)
            target_dir = embedded_media_dir
        else:
            target_dir = paths["images"]
        target = target_dir / filename
        if target.exists():
            continue
        try:
            client.download_to_path(image_url, str(target))
            counts["images"] += 1
            destination = "workflow media" if has_embedded_workflow else "image"
            log(f"Saved {destination} {filename} → {target.parent}")
            if options.save_metadata:
                _write_metadata(target, {key: item.get(key) for key in item.keys()})
        except ApiError as exc:
            log(f"Image failed for {item_id}: {exc}")

    return counts


def urlparse_path(url: str) -> str:
    from urllib.parse import urlparse

    try:
        return urlparse(url).path
    except Exception:
        return url


def download_version_assets(
    client: CivitaiClient,
    version_id: int,
    state: AppState,
    log: LogFunc,
    *,
    model_detail: Optional[Dict] = None,
) -> Tuple[int, int]:
    try:
        detail = client.get_model_version(version_id)
    except ApiError as exc:
        log(f"Version lookup failed for {version_id}: {exc}")
        return 0

    options = state.downloads
    resolved = state.resolved
    resolved_extra = resolved.extra if resolved else {}

    model_info = detail.get("model") or {}
    creator = model_info.get("creator") if isinstance(model_info.get("creator"), dict) else None
    model_id = _first_int(
        model_info.get("id"),
        detail.get("modelId"),
        state.filters.model_id,
        resolved.model_id if resolved else None,
    )
    username = _first_str(
        creator.get("username") if isinstance(creator, dict) else None,
        state.filters.username,
        resolved_extra.get("username") if isinstance(resolved_extra.get("username"), str) else None,
    )
    fallback_name = model_info.get("name") or detail.get("name") or str(version_id)

    model_candidates: List[object] = [model_info.get("name")]
    resolved_model_name = resolved_extra.get("modelName")
    if isinstance(resolved_model_name, str):
        model_candidates.append(resolved_model_name)
    resolved_model_obj = resolved_extra.get("model")
    if isinstance(resolved_model_obj, dict):
        model_candidates.append(resolved_model_obj.get("name"))
    if resolved and resolved.model_id == model_id and resolved.name:
        model_candidates.append(resolved.name)
    model_name = _first_str(*model_candidates)

    version_candidates: List[object] = [detail.get("name")]
    resolved_version_name = resolved_extra.get("modelVersionName")
    if isinstance(resolved_version_name, str):
        version_candidates.append(resolved_version_name)
    resolved_version_obj = resolved_extra.get("modelVersion")
    if isinstance(resolved_version_obj, dict):
        version_candidates.append(resolved_version_obj.get("name"))
    if resolved and resolved.model_version_id == version_id and resolved.name:
        version_candidates.append(resolved.name)
    version_name = _first_str(*version_candidates)

    paths = _resolve_media_paths(
        model_id=model_id,
        model_version_id=version_id,
        username=username,
        fallback=fallback_name,
        options=options,
        model_name=model_name,
        model_version_name=version_name,
    )

    version_entry = _find_version_entry(model_detail, version_id) if model_detail else None
    showcase_media: List[Dict] = []
    if options.grab_previews:
        showcase_media = _collect_showcase_images(detail, model_detail, version_entry)

    files = detail.get("files") or []
    saved_assets = 0
    eligible_files = 0
    skipped_existing = 0
    for file_info in files:
        file_type = (file_info.get("type") or "").lower()
        download_url = file_info.get("downloadUrl")
        if not download_url:
            continue
        metadata = file_info.get("metadata") or {}
        fmt = metadata.get("format")
        path_ext = os.path.splitext(urlparse_path(download_url))[-1]
        ext_candidates: List[str] = []
        if path_ext:
            ext_candidates.append(path_ext)
        if isinstance(fmt, str) and fmt.strip():
            fmt_clean = fmt.strip().lower()
            # Normalize API format aliases to correct file extensions
            _FORMAT_ALIASES = {"safetensor": ".safetensors"}
            if fmt_clean in _FORMAT_ALIASES:
                fmt_clean = _FORMAT_ALIASES[fmt_clean]
            if fmt_clean not in {"other", "unknown"}:
                ext_candidates.append(fmt_clean if fmt_clean.startswith(".") else f".{fmt_clean}")

        ext = next((candidate for candidate in ext_candidates if candidate and candidate.lower() not in {".other", ".unknown"}), "")
        if not ext and path_ext:
            ext = path_ext
        if not ext and file_type == "workflow":
            ext = ".zip"
        if not ext:
            ext = ".bin"
        if not ext.startswith("."):
            ext = f".{ext}"
        ext_lower = ext.lower()

        if file_type == "image" and not options.grab_originals:
            continue
        if file_type == "video" and not options.grab_videos:
            continue
        if (file_type == "workflow" or ext_lower in WORKFLOW_FILE_EXTENSIONS) and not options.grab_workflows:
            continue

        name_piece = file_info.get("name") or file_info.get("id") or "asset"
        # Strip any extension from the API-provided name so it doesn't get
        # slugified into the stem (e.g. "file.safetensors" -> "file_safetensors")
        name_stem = Path(str(name_piece)).stem
        safe_name = _slugify(name_stem)
        if file_type == "video" or ext_lower in VIDEO_EXTENSIONS:
            target_dir = paths["videos"]
        elif file_type == "workflow" or ext_lower in WORKFLOW_FILE_EXTENSIONS:
            target_dir = paths["workflows"]
        elif file_type in {"model", "checkpoint", "pruned model", "trained model", "lora", "embedding", "textual inversion"} or ext_lower in MODEL_FILE_EXTENSIONS:
            target_dir = paths["base"]
        else:
            target_dir = paths["images"]

        filename = f"{version_id}_{safe_name}{ext}"
        target = target_dir / filename
        eligible_files += 1
        if target.exists():
            skipped_existing += 1
            continue

        try:
            client.download_to_path(download_url, str(target))
            saved_assets += 1
            descriptor = file_type or "asset"
            log(f"Saved {descriptor} {filename} → {target.parent}")
            if options.save_metadata:
                _write_metadata(target, file_info)
        except ApiError as exc:
            log(f"Asset failed for {filename}: {exc}")

    if eligible_files == 0:
        log(f"No downloadable asset files found for version {version_id}.")
    elif saved_assets == 0 and skipped_existing == eligible_files:
        log(f"All asset files for version {version_id} already exist; nothing new downloaded.")
    elif saved_assets == 0:
        log(f"No asset files were downloaded for version {version_id}.")

    if showcase_media:
        showcase_saved = _download_showcase_images(
            client,
            images=showcase_media,
            version_id=version_id,
            paths=paths,
            options=options,
            log=log,
        )
        if showcase_saved > 0:
            log(f"Captured {showcase_saved} showcase image(s) for version {version_id}.")
    else:
        showcase_saved = 0

    return saved_assets, showcase_saved


def execute_downloads(client: CivitaiClient, state: AppState, log: LogFunc) -> Dict[str, int]:
    results = {"images": 0, "videos": 0, "assets": 0}

    resolved = state.resolved
    resolved_extra = resolved.extra if resolved else {}

    needs_assets = state.downloads.grab_originals or state.downloads.grab_workflows or state.downloads.grab_videos

    model_detail: Optional[Dict] = None

    model_id_value: Optional[int] = None
    model_id_raw = state.filters.model_id or (resolved.model_id if resolved else None)
    if model_id_raw is not None:
        try:
            model_id_value = int(str(model_id_raw))
        except (TypeError, ValueError):
            log(f"Invalid model ID provided: {model_id_raw}")

    preferred_version_id: Optional[int] = state.filters.model_version_id
    preferred_version_name: Optional[str] = None

    if preferred_version_id is None and resolved and resolved.model_version_id is not None:
        preferred_version_id = resolved.model_version_id

    if preferred_version_id is not None:
        name_candidates: List[object] = []
        if resolved:
            resolved_version_obj = resolved_extra.get("modelVersion") if isinstance(resolved_extra.get("modelVersion"), dict) else None
            if resolved_version_obj:
                name_candidates.append(resolved_version_obj.get("name"))
            resolved_version_name = resolved_extra.get("modelVersionName")
            if isinstance(resolved_version_name, str):
                name_candidates.append(resolved_version_name)
            if resolved.model_version_id == preferred_version_id and resolved.name:
                name_candidates.append(resolved.name)
        preferred_version_name = _first_str(*name_candidates)

    if needs_assets and preferred_version_id is None and model_id_value is not None:
        log(f"Resolving versions for model {model_id_value}…")
        try:
            model_detail = client.get_model(model_id_value)
        except ApiError as exc:
            log(f"Model lookup failed for {model_id_value}: {exc}")
        else:
            preferred = _select_preferred_version(model_detail.get("modelVersions") or [])
            if preferred is not None:
                version_id = _first_int(preferred.get("id"))
                if version_id is not None:
                    preferred_version_id = version_id
                    preferred_version_name = preferred_version_name or _first_str(preferred.get("name"))
                    if preferred_version_name:
                        log(f"Defaulting to version {version_id} ({preferred_version_name}) for model downloads.")
                    else:
                        log(f"Defaulting to version {version_id} for model downloads.")
            else:
                log(f"Model {model_id_value} has no versions available to download.")

    log("Fetching preview media…")
    items = fetch_images_for_filters(client, state.filters, state.downloads, log)
    item_count = len(items)
    log(f"Preview query returned {item_count} item(s).")

    if item_count and preferred_version_id is None:
        inferred_version_id = _infer_version_from_items(items)
        if inferred_version_id is not None:
            preferred_version_id = inferred_version_id
            inferred_name = _infer_version_name_from_items(items, inferred_version_id)
            if inferred_name:
                preferred_version_name = preferred_version_name or inferred_name
            log(f"Inferred version {inferred_version_id} from preview items.")

    if item_count:
        counts = download_image_items(
            client,
            items,
            state,
            log,
            default_version_id=preferred_version_id,
            default_version_name=preferred_version_name,
        )
        results["images"] += counts.get("images", 0)
        results["videos"] += counts.get("videos", 0)
    else:
        log("No preview downloads were saved.")

    if not needs_assets:
        return results

    if preferred_version_id is None:
        log("No model version ID available; skipping model asset download.")
        return results

    saved_assets, showcase_saved = download_version_assets(
        client,
        preferred_version_id,
        state,
        log,
        model_detail=model_detail,
    )
    results["assets"] += saved_assets
    if showcase_saved:
        results["images"] += showcase_saved

    return results


def _infer_version_from_items(items: Iterable[Dict]) -> Optional[int]:
    candidates: List[int] = []
    for item in items:
        candidate = _first_int(item.get("modelVersionId"))
        if candidate is None and isinstance(item.get("modelVersion"), dict):
            candidate = _first_int(item["modelVersion"].get("id"))
        if candidate is not None:
            candidates.append(candidate)
    if not candidates:
        return None
    ranking = Counter(candidates).most_common(1)
    return ranking[0][0] if ranking else None


def _select_preferred_version(versions: Iterable[Dict]) -> Optional[Dict]:
    best_entry: Optional[Dict] = None
    best_stamp = ""
    for entry in versions:
        version_id = _first_int(entry.get("id"))
        if version_id is None:
            continue
        stamp = ""
        for key in ("publishedAt", "createdAt", "updatedAt"):
            value = entry.get(key)
            if isinstance(value, str) and value.strip():
                stamp = value.strip()
                break
        if best_entry is None or stamp > best_stamp:
            best_entry = entry
            best_stamp = stamp
    return best_entry


def _infer_version_name_from_items(items: Iterable[Dict], version_id: int) -> Optional[str]:
    for item in items:
        candidate = _first_int(item.get("modelVersionId"))
        if candidate is None and isinstance(item.get("modelVersion"), dict):
            candidate = _first_int(item["modelVersion"].get("id"))
        if candidate != version_id:
            continue
        name = _first_str(
            item.get("modelVersionName"),
            item.get("modelVersion", {}).get("name") if isinstance(item.get("modelVersion"), dict) else None,
        )
        if name:
            return name
    return None


def _find_version_entry(model_detail: Dict, version_id: int) -> Optional[Dict]:
    versions = model_detail.get("modelVersions")
    if not isinstance(versions, list):
        return None
    for entry in versions:
        if not isinstance(entry, dict):
            continue
        candidate_id = _first_int(entry.get("id"))
        if candidate_id == version_id:
            return entry
    return None


def _collect_showcase_images(
    version_detail: Dict,
    model_detail: Optional[Dict],
    version_entry: Optional[Dict],
) -> List[Dict]:
    collected: List[Dict] = []
    for source in (version_detail, version_entry, model_detail):
        if not isinstance(source, dict):
            continue
        images = source.get("images")
        if isinstance(images, list):
            for image in images:
                if isinstance(image, dict):
                    collected.append(image)
    return collected


def _download_showcase_images(
    client: CivitaiClient,
    *,
    images: Iterable[Dict],
    version_id: int,
    paths: Dict[str, Path],
    options: DownloadOptions,
    log: LogFunc,
) -> int:
    saved = 0
    seen: Set[str] = set()
    for index, image in enumerate(images, start=1):
        url = _extract_showcase_url(image)
        if not url:
            continue
        if url in seen:
            continue
        seen.add(url)

        suffix = os.path.splitext(urlparse_path(url))[-1] or ".jpg"
        if not suffix.startswith("."):
            suffix = f".{suffix}"

        image_id = _first_int(image.get("id"), image.get("imageId"))
        name_hint = _first_str(image.get("name"), image.get("type"))
        slug_base = f"showcase_{image_id}" if image_id is not None else name_hint or f"showcase_{index}"
        filename = f"{version_id}_{_slugify(str(slug_base))}{suffix}"

        has_workflow = _has_embedded_workflow_payload(image)
        if has_workflow:
            embedded_dir = paths["workflows"] / "embedded_media"
            _ensure_dir(embedded_dir)
            target_dir = embedded_dir
        else:
            target_dir = paths["images"]

        target = target_dir / filename
        if target.exists():
            continue

        try:
            client.download_to_path(url, str(target))
            log(f"Saved showcase image {filename} → {target_dir}")
            if options.save_metadata:
                _write_metadata(target, image)
            saved += 1
        except ApiError as exc:
            log(f"Showcase image failed for {filename}: {exc}")

    return saved
