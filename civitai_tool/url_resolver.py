from __future__ import annotations

from typing import Dict, Optional
from urllib.parse import parse_qs, quote, unquote, urlparse

from .api_client import ApiError, CivitaiClient
from .state import ResolvedEntity
from .transfer import TransferError, resolve_redirect

HF_HOSTS = {"huggingface.co", "www.huggingface.co", "hf.co"}
HF_REPO_TYPE_PREFIXES = {"datasets": "dataset", "spaces": "space"}


def _extract_numeric(segment: str) -> Optional[int]:
    cleaned = segment.split("-", 1)[0]
    return int(cleaned) if cleaned.isdigit() else None


def _extract_file_id(query_params: Dict[str, list]) -> Optional[int]:
    """Pull a specific fileId out of a Civitai download/model URL query string.

    Civitai appends ``?fileId=<id>`` to download links when a version exposes
    several files (e.g. different quantizations like fp16/fp8/int8). Capturing it
    lets the downloader fetch only the chosen variant instead of every file.
    """
    values = query_params.get("fileId")
    if not values:
        return None
    try:
        return int(str(values[0]).strip())
    except (TypeError, ValueError):
        return None


def hf_auth_headers(hf_token: str) -> Dict[str, str]:
    token = (hf_token or "").strip()
    return {"Authorization": f"Bearer {token}"} if token else {}


def parse_hf_url(raw_url: str) -> Optional[Dict[str, str]]:
    """
    Understand the single-file URL shapes Hugging Face produces:

        https://huggingface.co/<org>/<repo>/blob/<rev>/<path/to/file>
        https://huggingface.co/<org>/<repo>/resolve/<rev>/<path/to/file>[?download=true]
        https://huggingface.co/datasets/<org>/<repo>/resolve/<rev>/<path>
        https://huggingface.co/<canonical-repo>/blob/<rev>/<path>       (single-segment repo ids)

    Returns None if the host isn't Hugging Face; raises ApiError for an HF URL
    that doesn't point at a file (repo root, tree view).
    """
    parsed = urlparse(raw_url.strip())
    if not parsed.scheme:
        parsed = urlparse(f"https://{raw_url.strip()}")
    if parsed.netloc.lower() not in HF_HOSTS:
        return None
    segments = [unquote(s) for s in parsed.path.split("/") if s]
    repo_type = "model"
    if segments and segments[0] in HF_REPO_TYPE_PREFIXES:
        repo_type = HF_REPO_TYPE_PREFIXES[segments[0]]
        segments = segments[1:]

    # Find the blob/resolve marker; everything before it is the repo id.
    marker_index = next((i for i, seg in enumerate(segments) if seg in {"blob", "resolve"}), None)
    if marker_index is None or marker_index == 0 or len(segments) < marker_index + 3:
        raise ApiError(
            "That Hugging Face link points at a repo or folder, not a file. "
            "Open the file in the repo's Files tab and paste that link (…/blob/main/<file>)."
        )
    repo_id = "/".join(segments[:marker_index])
    revision = segments[marker_index + 1]
    file_path = "/".join(segments[marker_index + 2 :])
    if not file_path:
        raise ApiError("Hugging Face URL has no file path.")
    type_prefix = {"dataset": "datasets/", "space": "spaces/"}.get(repo_type, "")
    resolve_url_value = (
        f"https://huggingface.co/{type_prefix}{quote(repo_id)}/resolve/{quote(revision)}/{quote(file_path)}"
    )
    return {
        "repo_id": repo_id,
        "repo_type": repo_type,
        "revision": revision,
        "path": file_path,
        "filename": file_path.rsplit("/", 1)[-1],
        "resolve_url": resolve_url_value,
        "page_url": f"https://huggingface.co/{type_prefix}{repo_id}/blob/{revision}/{file_path}",
    }


def resolve_hf_url(raw_url: str, hf_token: str = "") -> Optional[ResolvedEntity]:
    info = parse_hf_url(raw_url)
    if info is None:
        return None
    # One request to the origin: follows the redirect, learns exact size + LFS sha256,
    # and surfaces 401/403 for gated repos right away instead of at download time.
    try:
        source = resolve_redirect(info["resolve_url"], hf_auth_headers(hf_token))
    except TransferError as exc:
        raise ApiError(str(exc)) from exc
    extra: Dict[str, object] = dict(info)
    extra["size"] = source.size
    extra["sha256"] = source.sha256
    identifier = f"{info['repo_id']}@{info['revision']}:{info['path']}"
    return ResolvedEntity(entity_type="hf_file", identifier=identifier, name=info["filename"], extra=extra)


def resolve_url(raw_url: str, client: CivitaiClient, hf_token: str = "") -> Optional[ResolvedEntity]:
    if not raw_url:
        return None

    hf_entity = resolve_hf_url(raw_url, hf_token)
    if hf_entity is not None:
        return hf_entity

    parsed = urlparse(raw_url.strip())
    if not parsed.scheme:
        parsed = urlparse(f"https://{raw_url.strip()}")
    segments = [segment for segment in parsed.path.split("/") if segment]
    if not segments:
        return None

    query_params = parse_qs(parsed.query)

    first = segments[0].lower()

    if first == "models" and len(segments) >= 2:
        model_id = _extract_numeric(segments[1])
        if model_id is None:
            return None
        detail = client.get_model(model_id)
        extra = {"modelId": model_id, "modelName": detail.get("name"), "model": detail}
        file_id = _extract_file_id(query_params)
        if file_id is not None:
            extra["fileId"] = file_id
        version_id = None
        if "modelVersionId" in query_params:
            try:
                version_id = int(query_params["modelVersionId"][0])
            except (ValueError, TypeError, IndexError):
                version_id = None
        if version_id:
            try:
                version_detail = client.get_model_version(version_id)
                extra["modelVersionId"] = version_id
                extra["modelVersion"] = version_detail
                extra["modelVersionName"] = version_detail.get("name")
            except Exception:
                extra["modelVersionId"] = version_id
        return ResolvedEntity(entity_type="model", identifier=str(model_id), name=detail.get("name"), extra=extra)

    if first in {"model", "model-version", "model-versions"} and len(segments) >= 2:
        version_id = _extract_numeric(segments[1])
        if version_id is None:
            return None
        version_detail = client.get_model_version(version_id)
        extra = {
            "modelVersionId": version_id,
            "modelVersion": version_detail,
            "modelVersionName": version_detail.get("name"),
        }
        file_id = _extract_file_id(query_params)
        if file_id is not None:
            extra["fileId"] = file_id
        model_info = version_detail.get("model")
        if isinstance(model_info, dict):
            extra["modelId"] = model_info.get("id")
            extra["modelName"] = model_info.get("name")
            extra["model"] = model_info
        return ResolvedEntity(entity_type="modelVersion", identifier=str(version_id), name=version_detail.get("name"), extra=extra)

    if first == "api" and len(segments) >= 3 and segments[1] == "download" and segments[2] == "models" and len(segments) >= 4:
        try:
            version_id = int(segments[3])
        except ValueError:
            return None
        version_detail = client.get_model_version(version_id)
        extra = {
            "modelVersionId": version_id,
            "modelVersion": version_detail,
            "modelVersionName": version_detail.get("name"),
        }
        file_id = _extract_file_id(query_params)
        if file_id is not None:
            extra["fileId"] = file_id
        model_info = version_detail.get("model")
        if isinstance(model_info, dict):
            extra["modelId"] = model_info.get("id")
            extra["modelName"] = model_info.get("name")
            extra["model"] = model_info
        return ResolvedEntity(entity_type="modelVersion", identifier=str(version_id), name=version_detail.get("name"), extra=extra)

    if first == "images" and len(segments) >= 2:
        image_id = _extract_numeric(segments[1])
        if image_id is None:
            return None
        detail = client.get_image(image_id)
        extra = {
            "modelId": detail.get("modelId"),
            "modelVersionId": detail.get("modelVersionId"),
            "imageId": image_id,
        }
        model_info = detail.get("model")
        if isinstance(model_info, dict):
            extra["modelName"] = model_info.get("name")
            extra["model"] = model_info
        version_info = detail.get("modelVersion")
        if isinstance(version_info, dict):
            extra["modelVersionName"] = version_info.get("name")
            extra["modelVersion"] = version_info
        return ResolvedEntity(entity_type="image", identifier=str(image_id), name=f"Image {image_id}", extra=extra)

    if first == "user" and len(segments) >= 2:
        username = segments[1]
        detail = client.search_models(username=username, limit=1)
        extra = {"username": username, "modelsLink": f"https://civitai.com/api/v1/models?username={username}"}
        if detail.get("items"):
            first_model = detail["items"][0]
            extra["modelId"] = first_model.get("id")
        return ResolvedEntity(entity_type="creator", identifier=username, name=username, extra=extra)

    return None
