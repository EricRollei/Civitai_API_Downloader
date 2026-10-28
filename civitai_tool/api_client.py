from __future__ import annotations

import json
from typing import Dict, Iterable, List, Optional, Tuple

import requests


DEFAULT_TIMEOUT = 30

# Civitai serves the full site (all content ratings) from the ".red" domain; the
# ".com" / "green" domain silently filters results to SFW regardless of the
# requested rating. Default to ".red" so the in-app rating filters do the work.
DEFAULT_BASE_URL = "https://civitai.red"

# Mirrors the active client base URL so the standalone URL builders in
# downloads.py / url_resolver.py resolve links against the same domain.
CIVITAI_BASE_URL = DEFAULT_BASE_URL


def site_base_url() -> str:
    """Return the currently configured Civitai site/API base URL."""
    return CIVITAI_BASE_URL


class ApiError(RuntimeError):
    pass


class CivitaiClient:
    def __init__(self, api_key: str | None = None, session: Optional[requests.Session] = None,
                 base_url: str = DEFAULT_BASE_URL) -> None:
        self._session = session or requests.Session()
        self._api_key = api_key
        self._enums_cache: Optional[Dict] = None
        self._base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self._publish_base_url()

    def _publish_base_url(self) -> None:
        global CIVITAI_BASE_URL
        CIVITAI_BASE_URL = self._base_url

    @property
    def base_url(self) -> str:
        return self._base_url

    def update_base_url(self, base_url: str) -> None:
        self._base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self._publish_base_url()
        # Enum values are identical across domains, but drop the cache to be safe.
        self._enums_cache = None

    def update_api_key(self, api_key: str) -> None:
        self._api_key = api_key or ""

    def _headers(self) -> Dict[str, str]:
        headers = {"Accept": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    def _get(self, path: str, params: Optional[Dict[str, object]] = None, timeout: int = DEFAULT_TIMEOUT) -> Dict:
        url = f"{self._base_url}{path}"
        try:
            response = self._session.get(url, params=params, headers=self._headers(), timeout=timeout)
        except requests.exceptions.RequestException as req_exc:
            raise ApiError(f"Request failed for {url}: {req_exc}") from req_exc
        try:
            response.raise_for_status()
        except requests.HTTPError as http_err:
            raise ApiError(f"HTTP {response.status_code} for {url}: {response.text[:500]}") from http_err
        try:
            return response.json()
        except json.JSONDecodeError as decode_err:
            raise ApiError(f"Invalid JSON from {url}") from decode_err

    def search_models(self, *, query: str = "", username: str = "", base_models: Iterable[str] | None = None,
                      tags: Iterable[str] | None = None, sort: str = "Highest Rated", period: str = "AllTime",
                      page: int = 1, limit: int = 20, types: Iterable[str] | None = None,
                      cursor: Optional[str] = None) -> Dict:
        params: Dict[str, object] = {
            "limit": limit,
            "sort": sort,
            "period": period,
        }
        if query:
            # Civitai API rejects "page" when a query string is present; use cursor-based pagination instead
            params["query"] = query
            if cursor:
                params["cursor"] = cursor
        else:
            # Page-based pagination is only valid for browsing without a search query
            params["page"] = page
        if username:
            params["username"] = username
        if base_models:
            params["baseModels"] = ",".join(sorted(set(base_models)))
        if tags:
            params["tag"] = ",".join(sorted(set(tags)))
        if types:
            params["types"] = ",".join(sorted(set(types)))
        return self._get("/api/v1/models", params)

    def get_model(self, model_id: int) -> Dict:
        return self._get(f"/api/v1/models/{model_id}")

    def get_model_version(self, model_version_id: int) -> Dict:
        return self._get(f"/api/v1/model-versions/{model_version_id}")

    def get_image(self, image_id: int) -> Dict:
        return self._get(f"/api/v1/images/{image_id}")

    def search_images(self, *, limit: int = 100, cursor: Optional[str] = None, page: Optional[int] = None,
                      model_id: Optional[int] = None, model_version_id: Optional[int] = None,
                      username: str = "", nsfw: str = "", browsing_level: Optional[int] = None,
                      period: str = "AllTime", sort: str = "Most Reactions",
                      types: Iterable[str] | None = None, tag_ids: Iterable[int] | None = None,
                      tag_names: Iterable[str] | None = None,
                      base_models: Iterable[str] | None = None, timeout: int = DEFAULT_TIMEOUT) -> Tuple[List[Dict], Dict[str, object]]:
        params: Dict[str, object] = {
            "limit": limit,
            "period": period,
            "sort": sort,
        }
        if cursor:
            params["cursor"] = cursor
        if page is not None:
            params["page"] = page
        if model_id is not None:
            params["modelId"] = model_id
        if model_version_id is not None:
            params["modelVersionId"] = model_version_id
        if username:
            params["username"] = username
        # browsingLevel is the modern 5-tier bitmask (PG/PG-13/R/X/XXX) and takes
        # precedence over the legacy string nsfw filter when both are supplied.
        if browsing_level is not None:
            params["browsingLevel"] = browsing_level
        elif nsfw:
            params["nsfw"] = nsfw
        if types:
            # The images endpoint uses a singular `type` that accepts ONE value
            # (image|video|audio). Send it only when exactly one type is selected;
            # otherwise omit it so all media types come back. (The old code sent a
            # comma-joined `types` param, which the API silently ignored.)
            type_list = [t for t in types if t]
            if len(type_list) == 1:
                params["type"] = type_list[0]
        if tag_ids:
            params["tagIds"] = ",".join(str(tid) for tid in tag_ids)
        if tag_names:
            params["tag"] = ",".join(tag_names)
        if base_models:
            params["baseModels"] = ",".join(base_models)
        payload = self._get("/api/v1/images", params, timeout=timeout)
        return payload.get("items", []), payload.get("metadata", {})

    def search_creators(self, *, query: str = "", limit: int = 20, page: int = 1) -> Dict:
        params: Dict[str, object] = {"limit": limit, "page": page}
        if query:
            params["query"] = query
        return self._get("/api/v1/creators", params)

    def search_tags(self, *, query: str = "", limit: int = 50, page: int = 1) -> Dict:
        params: Dict[str, object] = {"limit": limit, "page": page}
        if query:
            params["query"] = query
        return self._get("/api/v1/tags", params)

    def get_enums(self, *, force: bool = False) -> Dict:
        """Return Civitai's live enum lists (model types, base models, …).

        Cached after the first successful call so repeated lookups are cheap."""
        if self._enums_cache is None or force:
            self._enums_cache = self._get("/api/v1/enums")
        return self._enums_cache

    def base_model_choices(self, *, active_only: bool = False) -> List[str]:
        """Return the canonical list of ``baseModels`` filter values.

        These are the exact strings the API accepts for ``baseModels=`` — using
        anything else yields an HTTP 400. ``active_only`` restricts the result to
        base models Civitai's on-site generation currently supports."""
        data = self.get_enums()
        key = "ActiveBaseModel" if active_only else "BaseModel"
        values = data.get(key)
        if not isinstance(values, list):
            values = data.get("BaseModel") or []
        return [v for v in values if isinstance(v, str) and v and v != "..."]

    def get_generation_data(self, image_id: int) -> Optional[Dict]:
        """Fetch an image's full generation data (prompt, resources, settings).

        This uses Civitai's authenticated tRPC endpoint — the same source the
        website uses — which still returns the prompt even when the public
        ``/images`` API hides ``meta`` and the file has no embedded metadata.
        Requires an API key; returns ``None`` on any failure."""
        if not self._api_key:
            return None
        from urllib.parse import quote

        payload = quote(json.dumps({"json": {"id": int(image_id)}}))
        url = f"{self._base_url}/api/trpc/image.getGenerationData?input={payload}"
        try:
            response = self._session.get(url, headers=self._headers(), timeout=DEFAULT_TIMEOUT)
            response.raise_for_status()
            data = response.json()
        except (requests.exceptions.RequestException, json.JSONDecodeError):
            return None
        try:
            return data["result"]["data"]["json"]
        except (KeyError, TypeError):
            return None

    def model_versions_by_ids(self, version_ids: Iterable[int]) -> Dict[int, Dict]:
        results: Dict[int, Dict] = {}
        for version_id in version_ids:
            try:
                results[int(version_id)] = self.get_model_version(int(version_id))
            except ApiError:
                continue
        return results

    def auth_headers(self) -> Dict[str, str]:
        """Authorization header only (no Accept: application/json) for binary downloads."""
        if self._api_key:
            return {"Authorization": f"Bearer {self._api_key}"}
        return {}

    @property
    def session(self) -> requests.Session:
        return self._session

    def download_to_path(self, url: str, path: str, chunk_size: int = 1 << 15) -> None:
        """Small-file download (previews, showcase images): .part + rename, 3 attempts."""
        from pathlib import Path

        from .transfer import TransferError, download_small

        try:
            download_small(url, Path(path), headers=self.auth_headers(), session=self._session)
        except TransferError as exc:
            raise ApiError(str(exc)) from exc
