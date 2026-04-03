from __future__ import annotations

import json
from typing import Dict, Iterable, List, Optional, Tuple

import requests


DEFAULT_TIMEOUT = 30


class ApiError(RuntimeError):
    pass


class CivitaiClient:
    def __init__(self, api_key: str | None = None, session: Optional[requests.Session] = None) -> None:
        self._session = session or requests.Session()
        self._api_key = api_key

    def update_api_key(self, api_key: str) -> None:
        self._api_key = api_key or ""

    def _headers(self) -> Dict[str, str]:
        headers = {"Accept": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    def _get(self, path: str, params: Optional[Dict[str, object]] = None, timeout: int = DEFAULT_TIMEOUT) -> Dict:
        url = f"https://civitai.com{path}"
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
                      username: str = "", nsfw: str = "", period: str = "AllTime", sort: str = "Most Reactions",
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
        if nsfw:
            params["nsfw"] = nsfw
        if types:
            params["types"] = ",".join(types)
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

    def model_versions_by_ids(self, version_ids: Iterable[int]) -> Dict[int, Dict]:
        results: Dict[int, Dict] = {}
        for version_id in version_ids:
            try:
                results[int(version_id)] = self.get_model_version(int(version_id))
            except ApiError:
                continue
        return results

    def download_to_path(self, url: str, path: str, chunk_size: int = 1 << 15) -> None:
        try:
            response = self._session.get(url, headers=self._headers(), stream=True, timeout=60)
        except requests.exceptions.RequestException as req_exc:
            raise ApiError(f"Failed download {url}: {req_exc}") from req_exc
        try:
            response.raise_for_status()
        except requests.HTTPError as http_err:
            raise ApiError(f"Failed download {url}: {response.status_code}") from http_err
        with open(path, "wb") as handle:
            for chunk in response.iter_content(chunk_size=chunk_size):
                if chunk:
                    handle.write(chunk)
