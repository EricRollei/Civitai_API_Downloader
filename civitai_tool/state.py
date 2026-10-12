from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .transfer import TransferSettings


@dataclass
class ResolvedEntity:
    entity_type: str
    identifier: str
    name: Optional[str] = None
    extra: Dict[str, object] = field(default_factory=dict)

    @property
    def model_id(self) -> Optional[int]:
        value = self.extra.get("modelId")
        return int(value) if isinstance(value, (int, str)) and str(value).isdigit() else None

    @property
    def model_version_id(self) -> Optional[int]:
        value = self.extra.get("modelVersionId")
        return int(value) if isinstance(value, (int, str)) and str(value).isdigit() else None

    @property
    def slug(self) -> str:
        base = self.name or self.identifier
        sanitized = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in str(base))
        return sanitized.lower() or "model"


@dataclass
class FilterState:
    query: str = ""
    base_models: List[str] = field(default_factory=list)
    tag_names: List[str] = field(default_factory=list)
    nsfw: str = "None"
    period: str = "AllTime"
    sort: str = "Most Reactions"
    username: str = ""
    types: List[str] = field(default_factory=lambda: ["image"])
    model_id: Optional[int] = None
    model_version_id: Optional[int] = None


@dataclass
class DownloadOptions:
    grab_previews: bool = True
    grab_originals: bool = True
    grab_workflows: bool = False
    grab_videos: bool = True
    save_metadata: bool = True
    prefer_native_images: bool = True
    save_prompts: bool = False
    max_items: int = 0
    output_root: str = "downloads"
    # When set, only model-type files whose id is in this list are downloaded.
    # None means "no restriction" (download every model file in the version).
    selected_file_ids: Optional[List[int]] = None


@dataclass
class AppState:
    api_key: str = ""
    hf_token: str = ""
    resolved: Optional[ResolvedEntity] = None
    filters: FilterState = field(default_factory=FilterState)
    downloads: DownloadOptions = field(default_factory=DownloadOptions)
    transfer: TransferSettings = field(default_factory=TransferSettings)

    def reset_filters(self) -> None:
        self.filters = FilterState()
