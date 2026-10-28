from __future__ import annotations

import json
import os
from collections import Counter
import time
from dataclasses import replace
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Set, Tuple

from .api_client import ApiError, CivitaiClient, site_base_url
from .image_meta import extract_embedded_metadata, sniff_image_ext
from .state import AppState, DownloadOptions, FilterState
from .transfer import TransferSpec, download_file, resolve_redirect
from .url_resolver import hf_auth_headers

LogFunc = Callable[[str], None]

VIDEO_EXTENSIONS = (".mp4", ".webm", ".mov", ".m4v")
IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp")
MODEL_FILE_EXTENSIONS = {".safetensors", ".ckpt", ".pt", ".pth", ".bin", ".onnx"}
WORKFLOW_FILE_EXTENSIONS = {".zip", ".json", ".workflow", ".yaml", ".yml"}
MODEL_FILE_TYPES = {
    "model", "checkpoint", "pruned model", "trained model",
    "diffusion model", "unet", "vae", "text encoder",
    "lora", "lycoris", "embedding", "textual inversion",
}
# The subset that represents the main generative weights (the thing a quant
# choice is usually about). VAE/Text Encoder are weight files too, but they are
# companion components, so they aren't pre-selected by default.
PRIMARY_MODEL_TYPES = {
    "model", "checkpoint", "pruned model", "trained model",
    "diffusion model", "unet", "lora", "lycoris",
}


def _is_model_file(file_info: Dict, ext_lower: str = "") -> bool:
    """True for the primary weight files (checkpoints/LoRAs/etc.), which are the
    large assets that come in multiple quantizations. Images, workflows, configs
    and other side files are never treated as selectable model variants."""
    file_type = (file_info.get("type") or "").lower()
    if file_type in MODEL_FILE_TYPES:
        return True
    if file_type in {"image", "video", "workflow", "config", "archive"}:
        return False
    return ext_lower in MODEL_FILE_EXTENSIONS


def describe_variant_files(detail: Dict) -> List[Dict]:
    """Normalize a version's model (weight) files into pick-list descriptors.

    Returned dicts expose id, name, precision (fp), format, pruned/full size and
    an approximate size in bytes so the GUI can present the quantization choices
    (e.g. bf16 vs fp8 vs int8) without re-deriving them from the raw API payload.
    """
    descriptors: List[Dict] = []
    for file_info in detail.get("files") or []:
        if not isinstance(file_info, dict):
            continue
        download_url = file_info.get("downloadUrl")
        if not download_url:
            continue
        metadata = file_info.get("metadata") if isinstance(file_info.get("metadata"), dict) else {}
        path_ext = os.path.splitext(urlparse_path(download_url))[-1].lower()
        if not _is_model_file(file_info, path_ext):
            continue
        size_kb = metadata.get("sizeKB")
        if size_kb is None:
            size_kb = file_info.get("sizeKB")
        try:
            size_bytes = int(round(float(size_kb) * 1024)) if size_kb is not None else None
        except (TypeError, ValueError):
            size_bytes = None
        descriptors.append({
            "id": _first_int(file_info.get("id")),
            "name": file_info.get("name") or "",
            "type": (file_info.get("type") or "").strip(),
            "fp": _first_str(metadata.get("fp")),
            "format": _first_str(metadata.get("format")),
            "size_label": _first_str(metadata.get("size")),
            "size_bytes": size_bytes,
            "is_primary": (file_info.get("type") or "").strip().lower() in PRIMARY_MODEL_TYPES,
        })
    return descriptors


def summarize_version_files(detail: Dict) -> List[Dict]:
    """Normalize every downloadable file in a version for a pre-download preview.

    Unlike describe_variant_files (weight files only) this lists all files —
    weights, previews, configs, workflows — so the user can see exactly what a
    run would fetch and how large it is before committing."""
    rows: List[Dict] = []
    for file_info in detail.get("files") or []:
        if not isinstance(file_info, dict):
            continue
        download_url = file_info.get("downloadUrl")
        if not download_url:
            continue
        metadata = file_info.get("metadata") if isinstance(file_info.get("metadata"), dict) else {}
        path_ext = os.path.splitext(urlparse_path(download_url))[-1].lower()
        size_kb = metadata.get("sizeKB")
        if size_kb is None:
            size_kb = file_info.get("sizeKB")
        try:
            size_bytes = int(round(float(size_kb) * 1024)) if size_kb is not None else None
        except (TypeError, ValueError):
            size_bytes = None
        rows.append({
            "id": _first_int(file_info.get("id")),
            "name": file_info.get("name") or "",
            "type": (file_info.get("type") or "").lower(),
            "fp": _first_str(metadata.get("fp")),
            "format": _first_str(metadata.get("format")),
            "size_label": _first_str(metadata.get("size")),
            "size_bytes": size_bytes,
            "is_model": _is_model_file(file_info, path_ext),
        })
    return rows


def format_size(num_bytes: Optional[object]) -> str:
    """Human-readable byte size for preview tables (e.g. 12.2 GB)."""
    try:
        value = float(num_bytes)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return "—"
    if value <= 0:
        return "—"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{int(value)} B" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"


def _variant_metadata_summary(file_info: Dict, saved_as: str, size_bytes: Optional[int]) -> Dict[str, object]:
    """Compact precision/format block added to a weight file's .json sidecar so
    the quantization of a saved checkpoint is obvious without re-querying the API."""
    metadata = file_info.get("metadata") if isinstance(file_info.get("metadata"), dict) else {}
    hashes = file_info.get("hashes") if isinstance(file_info.get("hashes"), dict) else {}
    return {
        "fileId": _first_int(file_info.get("id")),
        "precision": _first_str(metadata.get("fp")),
        "format": _first_str(metadata.get("format")),
        "sizeLabel": _first_str(metadata.get("size")),
        "sizeBytes": size_bytes,
        "savedAs": saved_as,
        "sha256": _first_str(hashes.get("SHA256"), hashes.get("sha256")),
    }


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


def _civitai_original_url(url: str) -> str:
    """Rewrite a Civitai image CDN URL to request the full original asset.

    Civitai image URLs look like
    ``https://image.civitai.com/<bucket>/<uuid>/<transform>/<filename>`` where
    ``<transform>`` (e.g. ``width=450``) downscales/re-encodes the image. Forcing
    ``original=true`` returns the uploaded file verbatim — full resolution and,
    crucially, with the generation metadata (prompt/workflow) still embedded."""
    from urllib.parse import urlparse

    try:
        parsed = urlparse(url)
    except Exception:
        return url
    if "image.civitai.com" not in parsed.netloc.lower():
        return url
    segments = [seg for seg in parsed.path.split("/") if seg]
    if len(segments) < 2:
        return url
    # The transform segment, when present, is the one containing '=' just before
    # the filename. Replace it, or insert original=true ahead of the filename.
    if len(segments) >= 3 and "=" in segments[-2]:
        if "original=true" not in segments[-2]:
            segments[-2] = "original=true"
    else:
        segments.insert(len(segments) - 1, "original=true")
    return parsed._replace(path="/" + "/".join(segments), query="").geturl()


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

    if options.folder_override:
        base = root / _folder_segment(options.folder_override)
    elif model_id is not None and model_version_id is not None:
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


def _clean_prompt_text(value: object) -> Optional[str]:
    """Return *value* as a flattened one-line prompt, or ``None`` if it isn't
    usable prompt text (e.g. a ComfyUI graph or other JSON blob)."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    # ComfyUI stores its executable graph as JSON; never treat that as a prompt.
    if text[0] in "{[":
        return None
    return " ".join(text.split())


def _best_prompt(item: Dict, embedded: Optional[Dict]) -> Optional[str]:
    """Pick the most reliable positive prompt for an image, flattened to one line.

    Prefers the prompt embedded in the file (authoritative, present even when the
    API hides metadata), then the API ``meta`` prompt, then Civitai's structured
    metadata block."""
    candidates: List[object] = []
    if isinstance(embedded, dict):
        candidates.append(embedded.get("prompt"))
        civ_meta = embedded.get("civitaiMetadata")
        if isinstance(civ_meta, dict):
            candidates.append(civ_meta.get("prompt"))
    meta = item.get("meta")
    if isinstance(meta, dict):
        candidates.append(meta.get("prompt"))
    for candidate in candidates:
        cleaned = _clean_prompt_text(candidate)
        if cleaned:
            return cleaned
    return None


def _prompt_from_meta(meta: Optional[Dict]) -> Optional[str]:
    """Flatten a positive prompt out of a generation-data ``meta`` block."""
    if isinstance(meta, dict):
        return _clean_prompt_text(meta.get("prompt"))
    return None


def _api_generation_data(client: CivitaiClient, image_id: Optional[object]) -> Optional[Dict]:
    """Fetch an image's server-side generation data (prompt/resources) via the
    authenticated tRPC endpoint — the last-resort source when the file and public
    API both lack a prompt. Returns ``None`` on any failure."""
    if image_id is None:
        return None
    try:
        return client.get_generation_data(int(image_id))
    except (TypeError, ValueError):
        return None


def _resolve_image_prompt(client: CivitaiClient, item: Dict, embedded: Optional[Dict],
                          image_id: Optional[object],
                          gen_data: Optional[Dict] = None) -> Tuple[Optional[str], Optional[Dict]]:
    """Return ``(prompt, gen_data)`` trying file/API meta first, then the
    authenticated generation-data endpoint. ``gen_data`` is fetched lazily and
    returned so callers can reuse it (e.g. for the metadata sidecar)."""
    prompt = _best_prompt(item, embedded)
    if prompt:
        return prompt, gen_data
    if gen_data is None:
        gen_data = _api_generation_data(client, image_id)
    if isinstance(gen_data, dict):
        prompt = _prompt_from_meta(gen_data.get("meta"))
    return prompt, gen_data


def _comfy_workflow_from_gen(gen_data: Optional[Dict]) -> Optional[object]:
    """Extract a loadable ComfyUI workflow from generation data.

    Prefers the UI ``workflow`` (nodes/links/groups — the drag-and-drop format),
    falling back to the API ``prompt`` graph. Returns ``None`` if neither is
    present (e.g. the image was not generated with ComfyUI)."""
    if not isinstance(gen_data, dict):
        return None
    meta = gen_data.get("meta")
    comfy = meta.get("comfy") if isinstance(meta, dict) else None
    if not isinstance(comfy, dict):
        return None
    workflow = comfy.get("workflow")
    if isinstance(workflow, (dict, list)) and workflow:
        return workflow
    prompt_graph = comfy.get("prompt")
    if isinstance(prompt_graph, (dict, list)) and prompt_graph:
        return prompt_graph
    return None


def _write_workflow_file(workflows_dir: Path, item_id: object, workflow: object, log: LogFunc) -> bool:
    """Write a ComfyUI workflow JSON into *workflows_dir* (loadable via drag-drop).

    Returns True if a new file was written. Skips silently when it already exists."""
    _ensure_dir(workflows_dir)
    path = workflows_dir / f"{item_id}_workflow.json"
    if path.exists():
        return False
    try:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(workflow, handle)
        log(f"Saved ComfyUI workflow → {path}")
        return True
    except OSError as exc:
        log(f"Could not write workflow {path}: {exc}")
        return False


def _write_prompts_file(target_dir: Path, prompts: List[str], log: LogFunc,
                        filename: str = "prompts.txt") -> None:
    """Append new prompts (one per line) to *filename* in ``target_dir``.

    The file is named after its source (e.g. ``model_1234_prompts.txt`` or
    ``user_alice_prompts.txt``) so prompts from different models/users don't mix.
    Existing lines are preserved and used to de-duplicate, so re-running a
    download never adds the same prompt twice."""
    if not prompts:
        return
    path = target_dir / filename
    existing: List[str] = []
    if path.exists():
        try:
            existing = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            existing = []
    seen: Set[str] = set(existing)
    added: List[str] = []
    for prompt in prompts:
        if prompt and prompt not in seen:
            seen.add(prompt)
            added.append(prompt)
    if not added:
        return
    try:
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("\n".join(existing + added) + "\n")
        log(f"Wrote {len(added)} new prompt(s) → {path}")
    except OSError as exc:
        log(f"Could not write prompts file {path}: {exc}")


def _prompts_filename(model_id: Optional[int], username: Optional[str],
                      prefer_username: bool = False) -> str:
    """Name the prompts file after its source: ``model_<id>_prompts.txt`` for a
    model page, ``user_<name>_prompts.txt`` for a user gallery."""
    if prefer_username and username:
        return f"user_{_slugify(str(username))}_prompts.txt"
    if model_id is not None:
        return f"model_{model_id}_prompts.txt"
    if username:
        return f"user_{_slugify(str(username))}_prompts.txt"
    return "prompts.txt"


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
        return f"{site_base_url()}{token}"
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
                    browsing_level=filters.browsing_level,
                    period=filters.period,
                    sort=filters.sort,
                    types=filters.types,
                    tag_names=filters.tag_names,
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
    prompts_by_dir: Dict[Path, List[str]] = {}
    prompt_file_by_dir: Dict[Path, str] = {}

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
        if options.folder_override:
            prompts_filename = f"{_folder_segment(options.folder_override)}_prompts.txt"
        else:
            prompts_filename = _prompts_filename(model_id, username, prefer_username)
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

        # Images are kept on disk only when previews are requested. When the user
        # only wants prompts, we still fetch the original (to read its embedded
        # generation metadata) but discard the file afterwards.
        keep_image = options.grab_previews
        if not keep_image and not options.save_prompts:
            continue
        image_url = item.get("url")
        if not isinstance(image_url, str) or not image_url.startswith("http"):
            log(f"No image URL for {item_id}")
            continue
        # Civitai's optimized/scaled CDN images have their metadata stripped, so
        # prompt extraction needs the original file.
        want_original = options.prefer_native_images or options.save_prompts
        download_url = _civitai_original_url(image_url) if want_original else image_url
        if has_embedded_workflow:
            embedded_media_dir = paths["workflows"] / "embedded_media"
            _ensure_dir(embedded_media_dir)
            target_dir = embedded_media_dir
        else:
            target_dir = paths["images"]
        _ensure_dir(target_dir)
        # The real format is only known after download (original=true can return
        # a PNG even when the URL ends in .jpeg), so skip if any variant exists.
        existing_image = next(
            (target_dir / f"{item_id}{candidate}" for candidate in IMAGE_EXTENSIONS
             if (target_dir / f"{item_id}{candidate}").exists()),
            None,
        )
        if keep_image and existing_image is not None:
            gen_cached: Optional[Dict] = None
            if options.save_prompts:
                embedded_existing = extract_embedded_metadata(existing_image)
                prompt, gen_cached = _resolve_image_prompt(client, item, embedded_existing, item_id)
                if prompt:
                    prompts_by_dir.setdefault(paths["base"], []).append(prompt)
                    prompt_file_by_dir.setdefault(paths["base"], prompts_filename)
            if options.grab_workflows and not (paths["workflows"] / f"{item_id}_workflow.json").exists():
                if gen_cached is None:
                    gen_cached = _api_generation_data(client, item_id)
                workflow = _comfy_workflow_from_gen(gen_cached)
                if workflow is not None:
                    _write_workflow_file(paths["workflows"], item_id, workflow, log)
            continue
        tmp_target = target_dir / f"{item_id}.part-img"
        try:
            client.download_to_path(download_url, str(tmp_target))
        except ApiError as exc:
            log(f"Image failed for {item_id}: {exc}")
            tmp_target.unlink(missing_ok=True)
            continue

        with open(tmp_target, "rb") as handle:
            head = handle.read(32)
        ext = sniff_image_ext(head)
        if not ext:
            ext = os.path.splitext(urlparse_path(image_url))[-1].lower() or ".jpg"

        embedded = (extract_embedded_metadata(tmp_target)
                    if (options.save_metadata or options.save_prompts) else None)
        api_meta_empty = not (isinstance(item.get("meta"), dict) and item.get("meta"))
        gen_data: Optional[Dict] = None  # server-side generation data, fetched lazily

        if keep_image:
            filename = f"{item_id}{ext}"
            target = target_dir / filename
            os.replace(tmp_target, target)
            counts["images"] += 1
            destination = "workflow media" if has_embedded_workflow else "image"
            log(f"Saved {destination} {filename} → {target.parent}")
            if options.save_metadata:
                payload = {key: item.get(key) for key in item.keys()}
                if embedded:
                    payload["_embedded"] = embedded
                    if api_meta_empty:
                        log(f"Recovered embedded generation data for {filename}.")
                elif api_meta_empty:
                    gen_data = _api_generation_data(client, item_id)
                    if gen_data:
                        payload["_generationData"] = gen_data
                        log(f"Recovered generation data from Civitai for {filename}.")
                _write_metadata(target, payload)
        else:
            # Prompts-only: we don't keep the image file.
            tmp_target.unlink(missing_ok=True)

        if options.save_prompts:
            prompt, gen_data = _resolve_image_prompt(client, item, embedded, item_id, gen_data)
            if prompt:
                prompts_by_dir.setdefault(paths["base"], []).append(prompt)
                prompt_file_by_dir.setdefault(paths["base"], prompts_filename)
            else:
                log(f"No prompt found for image {item_id} (not in file, API, or generation data).")

        # Save the ComfyUI workflow (when present) as a loadable JSON. The public
        # API no longer exposes workflows, so this comes from the generation data.
        if options.grab_workflows:
            if gen_data is None:
                gen_data = _api_generation_data(client, item_id)
            workflow = _comfy_workflow_from_gen(gen_data)
            if workflow is not None:
                _write_workflow_file(paths["workflows"], item_id, workflow, log)

    if options.save_prompts:
        for folder, prompts in prompts_by_dir.items():
            _write_prompts_file(folder, prompts, log,
                                filename=prompt_file_by_dir.get(folder, "prompts.txt"))

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
        return 0, 0

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
    selected_file_ids = options.selected_file_ids
    selected_id_set: Optional[Set[int]] = None
    if selected_file_ids:
        selected_id_set = {int(fid) for fid in selected_file_ids}
    saved_assets = 0
    eligible_files = 0
    skipped_existing = 0
    for file_info in files:
        file_type = (file_info.get("type") or "").lower()
        download_url = file_info.get("downloadUrl")
        if not download_url:
            continue
        path_ext_raw = os.path.splitext(urlparse_path(download_url))[-1].lower()
        # When the user picked specific quantizations, restrict only the weight
        # files to that selection. Previews/workflows/configs are left untouched
        # so a precision choice never suppresses companion downloads.
        if selected_id_set is not None and _is_model_file(file_info, path_ext_raw):
            file_id = _first_int(file_info.get("id"))
            if file_id is None or file_id not in selected_id_set:
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
        # Tag weight files with their precision (e.g. bf16/fp8/int8) so multiple
        # quantizations of the same version stay distinguishable on disk.
        if _is_model_file(file_info, ext_lower):
            fp_value = _first_str(metadata.get("fp")) if isinstance(metadata, dict) else None
            if fp_value:
                fp_slug = _slugify(fp_value)
                if fp_slug and fp_slug not in safe_name.lower():
                    filename = f"{version_id}_{safe_name}_{fp_slug}{ext}"
        target = target_dir / filename
        eligible_files += 1

        # Civitai reports sizeKB as a float (approximate) and a SHA256 for most
        # model files. The exact byte count comes from the CDN at resolve time;
        # sizeKB is only the fallback, with a little slack.
        size_kb = metadata.get("sizeKB") if isinstance(metadata, dict) else None
        if size_kb is None:
            size_kb = file_info.get("sizeKB")
        approx_size: Optional[int] = None
        try:
            if size_kb is not None:
                approx_size = int(round(float(size_kb) * 1024))
        except (TypeError, ValueError):
            approx_size = None
        hashes = file_info.get("hashes") if isinstance(file_info.get("hashes"), dict) else {}
        sha256 = _first_str(hashes.get("SHA256"), hashes.get("sha256"))

        spec = TransferSpec(
            target=target,
            resolve=lambda url=download_url: resolve_redirect(url, client.auth_headers(), session=client.session),
            display_name=filename,
            expected_size=approx_size,
            expected_sha256=sha256,
            size_tolerance=4096,
        )
        result = download_file(spec, state.transfer, log, session=client.session)
        if result.status == "skipped":
            skipped_existing += 1
            continue
        if result.status == "downloaded":
            saved_assets += 1
            descriptor = file_type or "asset"
            log(f"Saved {descriptor} {filename} → {target.parent} [{result.engine}]")
            if options.save_metadata:
                if _is_model_file(file_info, ext_lower):
                    payload = dict(file_info)
                    payload["_variant"] = _variant_metadata_summary(file_info, filename, approx_size)
                    _write_metadata(target, payload)
                else:
                    _write_metadata(target, file_info)
        else:
            log(f"Asset failed for {filename}: {result.message}")

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
            model_id=model_id,
            username=username,
        )
        if showcase_saved > 0:
            log(f"Captured {showcase_saved} showcase image(s) for version {version_id}.")
    else:
        showcase_saved = 0

    return saved_assets, showcase_saved


def download_hf_file(client: CivitaiClient, state: AppState, log: LogFunc) -> Dict[str, int]:
    """Download a single Hugging Face file, flat into the chosen output directory."""
    results = {"images": 0, "videos": 0, "assets": 0}
    resolved = state.resolved
    if resolved is None or resolved.entity_type != "hf_file":
        return results
    info = resolved.extra
    resolve_url_value = str(info.get("resolve_url") or "")
    filename = str(info.get("filename") or resolved.name or "download.bin")
    if not resolve_url_value:
        log("Hugging Face entity has no resolve URL; nothing to download.")
        return results

    root = Path(state.downloads.output_root).expanduser()
    _ensure_dir(root)
    target = root / filename
    headers = hf_auth_headers(state.hf_token)

    log(f"Hugging Face: {info.get('repo_id')} @ {info.get('revision')} / {info.get('path')}")
    spec = TransferSpec(
        target=target,
        resolve=lambda: resolve_redirect(resolve_url_value, headers, session=client.session),
        display_name=filename,
        expected_size=info.get("size") if isinstance(info.get("size"), int) else None,
        expected_sha256=info.get("sha256") if isinstance(info.get("sha256"), str) else None,
    )
    result = download_file(spec, state.transfer, log, session=client.session)
    if result.status == "skipped":
        log(f"{filename} already exists in {root} (size matches); nothing to do.")
    elif result.status == "downloaded":
        results["assets"] += 1
        log(f"Saved {filename} → {root} [{result.engine}]")
        if state.downloads.save_metadata:
            _write_metadata(target, {key: value for key, value in info.items() if key != "resolve_url"} | {"source": "huggingface"})
    else:
        log(f"Download failed for {filename}: {result.message}")
    return results


def execute_downloads(client: CivitaiClient, state: AppState, log: LogFunc) -> Dict[str, int]:
    results = {"images": 0, "videos": 0, "assets": 0}

    resolved = state.resolved
    resolved_extra = resolved.extra if resolved else {}

    if resolved is not None and resolved.entity_type == "hf_file":
        return download_hf_file(client, state, log)

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
    # Target the gallery query at the resolved model/version. These ids are
    # computed locally above and are not necessarily present on state.filters
    # (e.g. an extension quick-download leaves the Model ID field blank), so inject
    # them here — otherwise the query hits the global feed instead of this model.
    gallery_filters = replace(
        state.filters,
        model_id=model_id_value if model_id_value is not None else state.filters.model_id,
        model_version_id=(preferred_version_id if preferred_version_id is not None
                          else state.filters.model_version_id),
    )
    # When a specific model/version is targeted, or the user pasted a model/user/
    # image URL, discovery filters (platform + tags) would wrongly narrow the
    # gallery — a pasted URL should yield that target's full gallery. Drop them.
    targeted = (gallery_filters.model_id is not None
                or gallery_filters.model_version_id is not None
                or resolved is not None)
    if targeted:
        gallery_filters = replace(gallery_filters, base_models=[], tag_names=[])

    # A tag/keyword feed (/images?tags=…): drive the query by the tag IDs the user
    # pasted, scope by any feed username, and group everything into one folder.
    if resolved is not None and resolved.entity_type == "imageFeed":
        feed_tag_ids = [int(t) for t in (resolved.extra.get("tagIds") or [])
                        if isinstance(t, (int, str)) and str(t).isdigit()]
        feed_username = resolved.extra.get("username")
        gallery_filters = replace(
            gallery_filters,
            tag_ids=feed_tag_ids or gallery_filters.tag_ids,
            username=feed_username if isinstance(feed_username, str) and feed_username else gallery_filters.username,
        )
        if state.downloads.folder_override is None:
            if feed_tag_ids:
                state.downloads.folder_override = "tag_" + "_".join(str(t) for t in feed_tag_ids)
            elif isinstance(feed_username, str) and feed_username:
                state.downloads.folder_override = _folder_segment(feed_username)

    items = fetch_images_for_filters(client, gallery_filters, state.downloads, log)
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
    model_id: Optional[int] = None,
    username: Optional[str] = None,
) -> int:
    saved = 0
    seen: Set[str] = set()
    showcase_prompts: List[str] = []
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

        # Fetch the original (not a scaled copy) when we need its embedded
        # generation metadata, so prompt extraction can work.
        want_original = options.prefer_native_images or options.save_prompts
        download_url = _civitai_original_url(url) if want_original else url

        try:
            client.download_to_path(download_url, str(target))
            log(f"Saved showcase image {filename} → {target_dir}")
            embedded = (extract_embedded_metadata(target)
                        if (options.save_metadata or options.save_prompts) else None)
            if options.save_metadata:
                payload = dict(image)
                if embedded:
                    payload["_embedded"] = embedded
                _write_metadata(target, payload)
            if options.save_prompts:
                prompt, gen_showcase = _resolve_image_prompt(client, image, embedded, image_id)
                if prompt:
                    showcase_prompts.append(prompt)
            else:
                gen_showcase = None
            if options.grab_workflows and image_id is not None:
                if gen_showcase is None:
                    gen_showcase = _api_generation_data(client, image_id)
                workflow = _comfy_workflow_from_gen(gen_showcase)
                if workflow is not None:
                    _write_workflow_file(paths["workflows"], image_id, workflow, log)
            saved += 1
        except ApiError as exc:
            log(f"Showcase image failed for {filename}: {exc}")

    if options.save_prompts and showcase_prompts:
        _write_prompts_file(paths["base"], showcase_prompts, log,
                            filename=_prompts_filename(model_id, username))

    return saved
