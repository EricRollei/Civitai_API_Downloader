from __future__ import annotations

from typing import Optional
from urllib.parse import parse_qs, urlparse

from .api_client import CivitaiClient
from .state import ResolvedEntity


def _extract_numeric(segment: str) -> Optional[int]:
    cleaned = segment.split("-", 1)[0]
    return int(cleaned) if cleaned.isdigit() else None


def resolve_url(raw_url: str, client: CivitaiClient) -> Optional[ResolvedEntity]:
    if not raw_url:
        return None

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
