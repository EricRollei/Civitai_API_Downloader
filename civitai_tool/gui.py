from __future__ import annotations

import json
import threading
import time
import webbrowser
from queue import Queue, Empty
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk

from .api_client import ApiError, CivitaiClient
from .downloads import execute_downloads, describe_variant_files, summarize_version_files, format_size, _select_preferred_version
from .state import AppState, DownloadOptions
from .transfer import ARIA2_VERSION, TransferSettings, ensure_aria2, find_aria2
from .url_resolver import resolve_url
from .local_server import LocalURLServer
from . import theme

SETTINGS_FILE = Path(__file__).with_name("settings.json")

SORT_OPTIONS = [
    "Most Reactions",
    "Most Comments",
    "Most Collected",
    "Newest",
    "Oldest",
    "Random",
]

PLATFORM_CHOICES: List[Tuple[str, str]] = [
    ("Flux.1 Dev", "Flux.1 D"),
    ("Flux.1 Schnell", "Flux.1 S"),
    ("Flux.1 Krea", "Flux.1 Krea"),
    ("Flux.1 Kontext", "Flux.1 Kontext"),
    ("Flux.2 Dev", "Flux.2 D"),
    ("SD 1.5", "SD 1.5"),
    ("SD 3.5", "SD 3.5"),
    ("SDXL 1.0", "SDXL 1.0"),
    ("Pony", "Pony"),
    ("Pony V7", "Pony V7"),
    ("Illustrious", "Illustrious"),
    ("NoobAI", "NoobAI"),
    ("Chroma", "Chroma"),
    ("Anima", "Anima"),
    ("Qwen", "Qwen"),
    ("Qwen 2", "Qwen 2"),
    ("Qwen 2.1", "Qwen 2.1"),
    ("MOSS Image", "MOSS Image"),
    ("Krea 2", "Krea 2"),
    ("Krea 2 Turbo", "Krea 2 Turbo"),
    ("HiDream", "HiDream"),
    ("Z-Image Turbo", "ZImageTurbo"),
    ("Wan Video 2.2 T2V", "Wan Video 2.2 T2V-A14B"),
]

# Offline fallback for the live /api/v1/enums BaseModel list. Used only when the
# enums endpoint cannot be reached; the live list always takes precedence.
BASE_MODELS_FALLBACK: List[str] = [
    "Anima", "AuraFlow", "Chroma", "CogVideoX", "Ernie", "Flux.1 S", "Flux.1 D",
    "Flux.1 Krea", "Flux.1 Kontext", "Flux.2 D", "Flux.2 Klein 9B",
    "Flux.2 Klein 9B-base", "Flux.2 Klein 4B", "Flux.2 Klein 4B-base", "Flux.3",
    "Flux.3 Klein", "Flux.3 Klein-base", "MOSS Image", "Flux 3 Video", "Grok",
    "HappyHorse", "HiDream", "HiDream-O1", "Hunyuan 1", "Hunyuan Video",
    "Ideogram 4.0", "Ideogram 4.5", "Boogu", "Illustrious", "Imagen4", "Kolors",
    "Krea 2", "Krea 2 Turbo", "Krea 3", "LTXV", "LTXV2", "LTXV 2.3", "LTXV 2.5",
    "Lens", "Lumina", "MageFlow", "MAI", "Mochi", "Nano Banana", "NoobAI", "ODOR",
    "OpenAI", "Upscaler", "Other", "PixArt a", "PixArt E", "Playground v2", "Pony",
    "Pony V7", "Qwen", "Qwen 2", "Qwen 2.1", "Qwen 3", "Stable Cascade", "SD 1.4",
    "SD 1.5", "SD 1.5 LCM", "SD 1.5 Hyper", "SD 2.0", "SD 2.0 768", "SD 2.1",
    "SD 2.1 768", "SD 2.1 Unclip", "SD 3", "SD 3.5", "SD 3.5 Large",
    "SD 3.5 Large Turbo", "SD 3.5 Medium", "SDXL 0.9", "SDXL 1.0", "SDXL 1.0 LCM",
    "SDXL Lightning", "SDXL Hyper", "SDXL Turbo", "SDXL Distilled", "Reve",
    "Muse Image", "Seedream", "SVD", "SVD XT", "Sora 2", "Veo 3", "Wan Video",
    "Wan Video 1.3B t2v", "Wan Video 14B t2v", "Wan Video 14B i2v 480p",
    "Wan Video 14B i2v 720p", "Wan Video 2.2 TI2V-5B", "Wan Video 2.2 I2V-A14B",
    "Wan Video 2.2 T2V-A14B", "Wan Video 2.5 T2V", "Wan Video 2.5 I2V",
    "Wan Image 2.7", "Wan Video 2.7", "Wan Video 3.0", "ZImageTurbo", "ZImageBase",
    "Ming Image Design 0.1", "Ming Image Design Layer 0.1", "Vidu Q1", "MiniMax H3",
    "Kling", "Seedance", "ACE Audio", "MiniMax Music 3", "YuE2", "Sonilo",
    "PolyGen", "Tripo", "Hunyuan3D", "Pixal3D", "Trellis.2",
]

# Maps legacy/friendly tokens (lowercased) onto the exact baseModels strings the
# API accepts today. This also migrates older saved settings that stored the now
# invalid strings (e.g. "FLUX.1 [dev]") which otherwise cause an HTTP 400.
PLATFORM_ALIAS_MAP = {
    "flux": "Flux.1 D",
    "flux dev": "Flux.1 D",
    "flux.1d": "Flux.1 D",
    "flux 1d": "Flux.1 D",
    "flux1d": "Flux.1 D",
    "flux 1d (dev)": "Flux.1 D",
    "flux.1 [dev]": "Flux.1 D",
    "flux.1 d": "Flux.1 D",
    "flux 1s": "Flux.1 S",
    "flux.1s": "Flux.1 S",
    "flux schnell": "Flux.1 S",
    "flux.1 [schnell]": "Flux.1 S",
    "flux.1 s": "Flux.1 S",
    "flux 1 pro": "Flux.1 D",
    "flux pro": "Flux.1 D",
    "flux.1 [pro]": "Flux.1 D",
    "flux krea": "Flux.1 Krea",
    "flux.1 krea": "Flux.1 Krea",
    "flux kontext": "Flux.1 Kontext",
    "flux.1 kontext": "Flux.1 Kontext",
    "flux 2": "Flux.2 D",
    "flux2": "Flux.2 D",
    "flux.2 d": "Flux.2 D",
    "pony diffusion": "Pony",
    "pony": "Pony",
    "pony diffusion xl": "Pony",
    "pony v7": "Pony V7",
    "illustrious": "Illustrious",
    "illustrious xl": "Illustrious",
    "noobai": "NoobAI",
    "chroma": "Chroma",
    "anima": "Anima",
    "sdxl": "SDXL 1.0",
    "sdxl 1": "SDXL 1.0",
    "sdxl 1.0": "SDXL 1.0",
    "sdxl turbo": "SDXL Turbo",
    "sdxl lightning": "SDXL Lightning",
    "sdxl refiner": "SDXL 1.0",
    "sd 1.5": "SD 1.5",
    "stable diffusion 1.5": "SD 1.5",
    "sd 3.5": "SD 3.5",
    "qwen": "Qwen",
    "qwen 2d": "Qwen",
    "qwen 2": "Qwen 2",
    "qwen 2.1": "Qwen 2.1",
    "qwen 2.5d": "Qwen 2",
    "qwen 3": "Qwen 3",
    "moss": "MOSS Image",
    "moss image": "MOSS Image",
    "krea 2": "Krea 2",
    "krea2": "Krea 2",
    "krea 2 turbo": "Krea 2 Turbo",
    "krea2 turbo": "Krea 2 Turbo",
    "hidream": "HiDream",
    "wan": "Wan Video 2.2 T2V-A14B",
    "wan 2.2": "Wan Video 2.2 T2V-A14B",
    "wan2.2": "Wan Video 2.2 T2V-A14B",
    "wan video 2.2 t2v": "Wan Video 2.2 T2V-A14B",
    "wan 1.3": "Wan Video 1.3B t2v",
    "z-image-turbo": "ZImageTurbo",
    "z image turbo": "ZImageTurbo",
    "z-image turbo": "ZImageTurbo",
    "zimageturbo": "ZImageTurbo",
}

# Civitai's 5-tier content rating system (replaces the legacy 4-value nsfw
# string). ``browsingLevel`` is a bitmask; a "max rating" selection sends the
# cumulative mask of every tier up to and including the chosen one.
RATING_LEVELS: List[Tuple[str, int]] = [
    ("PG", 1),
    ("PG-13", 2),
    ("R", 4),
    ("X", 8),
    ("XXX", 16),
]
RATING_ORDER: List[str] = [name for name, _ in RATING_LEVELS]
RATING_BIT: Dict[str, int] = {name: bit for name, bit in RATING_LEVELS}

# Migrate the old nsfw string values onto the new rating tiers.
LEGACY_NSFW_TO_RATING = {
    "None": "PG",
    "Soft": "PG-13",
    "Mature": "R",
    "X": "X",
    "false": "PG",
    "true": "XXX",
}


def rating_to_browsing_level(max_tier: str) -> int:
    """Cumulative browsingLevel bitmask for every tier up to *max_tier*."""
    mask = 0
    for name, bit in RATING_LEVELS:
        mask |= bit
        if name == max_tier:
            return mask
    return mask


def normalize_rating(value: str) -> str:
    """Coerce a stored/legacy rating value onto a valid 5-tier label."""
    if value in RATING_BIT:
        return value
    return LEGACY_NSFW_TO_RATING.get(value, "PG")


def _normalize_base_model_token(value: str) -> Optional[str]:
    token = value.strip()
    if not token:
        return None
    mapped = PLATFORM_ALIAS_MAP.get(token.lower())
    return mapped or token


class CivitaiApp:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("Civitai Desktop Helper")
        self.root.geometry("1100x900")
        self.root.minsize(900, 700)

        self.client = CivitaiClient()
        self.state = AppState()

        # Track last resolved URL to detect changes
        self._last_resolved_url: str = ""

        # File-variant selection chosen for the next download run (None = all)
        self._pending_file_ids: Optional[List[int]] = None

        # Apply the centralized light theme (clam-based, fully colourable).
        self._style = theme.apply_theme(self.root)
        self._set_window_icon()

        # Cache for colour-coded folder-category chip styles (keyed by colour).
        self._chip_style_cache: Dict[tuple, str] = {}

        self._message_queue: Queue[tuple[str, str]] = Queue()
        self._selected_tags: Dict[str, str] = {}  # tag_name -> display_name
        self._current_results: List[Dict] = []
        self.status_var = tk.StringVar(value="Ready")
        self.download_button: Optional[ttk.Button] = None
        
        # Recent directories feature
        self._recent_dirs: List[str] = []
        self._pinned_dirs: List[str] = []
        self._recent_dirs_frame: Optional[ttk.Frame] = None
        self._max_recent_dirs = 14
        
        # Download queue for queuing multiple downloads
        self._download_queue: List[Dict[str, str]] = []  # List of {url, output_dir}
        
        # Local server for Chrome extension
        self._local_server = LocalURLServer()
        self._local_server.set_callback(self._on_url_received)
        self._extension_enabled_var = tk.BooleanVar(value=False)

        self._build_variables()
        self._build_layout()
        self._load_settings()

        # Colour the status text automatically whenever it changes.
        self.status_var.trace_add("write", self._on_status_changed)

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(200, self._drain_messages)
        self._refresh_base_model_choices()

    def _set_window_icon(self) -> None:
        """Use one of the bundled PNG icons as the window icon (best-effort)."""
        try:
            icon_dir = Path(__file__).resolve().parent.parent / "chrome_extension"
            for name in ("icon48.png", "icon128.png", "icon16.png"):
                candidate = icon_dir / name
                if candidate.exists():
                    self._app_icon = tk.PhotoImage(file=str(candidate))
                    self.root.iconphoto(True, self._app_icon)
                    break
        except Exception:
            pass

    def _on_status_changed(self, *_args) -> None:
        """Recolour the status value label based on its text content."""
        label = getattr(self, "_status_value_label", None)
        if label is None:
            return
        text = self.status_var.get().lower()
        pal = theme.PALETTE
        if any(k in text for k in ("fail", "error", "cancel", "invalid")):
            color = pal["danger"]
        elif any(k in text for k in ("download", "resolv", "search", "working", "fetch")):
            color = pal["accent"]
        elif any(k in text for k in ("done", "complete", "finished", "success", "saved")):
            color = pal["success"]
        else:
            color = pal["text_muted"]
        label.configure(foreground=color)

    def _chip_style(self, base_style: str, text_color: Optional[str]) -> str:
        """Return a ttk style (derived from *base_style*) with a neutral fill and
        border, and *text_color* used only for the label (folder category).
        """
        if not text_color:
            return base_style
        key = (base_style, text_color)
        name = self._chip_style_cache.get(key)
        if name:
            return name
        pal = theme.PALETTE
        name = f"c{len(self._chip_style_cache)}.{base_style}"
        self._style.configure(name, foreground=text_color)
        self._style.map(
            name,
            foreground=[("active", text_color), ("disabled", pal["text_muted"])],
        )
        self._chip_style_cache[key] = name
        return name

    def _set_progress_active(self, active: bool) -> None:
        """Show and animate the indeterminate progress bar while downloading."""
        bar = getattr(self, "_progress", None)
        if bar is None:
            return
        try:
            if active:
                if not bar.winfo_ismapped():
                    bar.pack(side=tk.RIGHT, padx=(0, 4))
                bar.start(12)
            else:
                bar.stop()
                if bar.winfo_ismapped():
                    bar.pack_forget()
        except Exception:
            pass

    def _build_variables(self) -> None:
        self.api_key_var = tk.StringVar()
        self.url_var = tk.StringVar()
        self.search_type_var = tk.StringVar(value="models")
        self.search_query_var = tk.StringVar()

        self.username_var = tk.StringVar()
        self.model_id_var = tk.StringVar()
        self.version_id_var = tk.StringVar()
        self.max_items_var = tk.StringVar(value="0")

        self.base_models_var = tk.StringVar()
        self.tag_query_var = tk.StringVar()

        self.nsfw_var = tk.StringVar(value="XXX")
        self.period_var = tk.StringVar(value="AllTime")
        self.sort_var = tk.StringVar(value=SORT_OPTIONS[0])

        self.include_images_var = tk.BooleanVar(value=True)
        self.include_videos_var = tk.BooleanVar(value=True)
        self.include_previews_var = tk.BooleanVar(value=True)
        self.include_originals_var = tk.BooleanVar(value=True)
        self.include_workflows_var = tk.BooleanVar(value=False)
        self.save_metadata_var = tk.BooleanVar(value=True)
        self.native_images_var = tk.BooleanVar(value=True)
        self.save_prompts_var = tk.BooleanVar(value=True)

        self.output_dir_var = tk.StringVar(value="downloads")
        self.model_base_path_var = tk.StringVar(value="")

        # Hugging Face + large-file transfer settings
        self.hf_token_var = tk.StringVar()
        self.use_aria2_var = tk.BooleanVar(value=True)
        self.aria2_path_var = tk.StringVar(value="")
        self.aria2_connections_var = tk.StringVar(value="8")

        self.platform_vars = {value: tk.BooleanVar(value=False) for _, value in PLATFORM_CHOICES}
        self._tag_lookup: Dict[str, int] = {}
        # Canonical baseModels strings the API accepts. Seeded from the bundled
        # fallback, then replaced with the live /api/v1/enums list at startup.
        self._valid_base_models: List[str] = list(BASE_MODELS_FALLBACK)
        self._valid_base_models_set = set(BASE_MODELS_FALLBACK)
        self.add_platform_var = tk.StringVar()

    def _build_layout(self) -> None:
        # Header with title
        header_frame = ttk.Frame(self.root)
        header_frame.pack(fill=tk.X, padx=15, pady=(10, 5))
        title_label = ttk.Label(header_frame, text="Civitai Desktop Helper", style="Title.TLabel")
        title_label.pack(side=tk.LEFT)
        version_label = ttk.Label(header_frame, text="v1.2", style="Version.TLabel")
        version_label.pack(side=tk.LEFT, padx=(8, 0), pady=(6, 0))

        # Separator
        ttk.Separator(self.root, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=15, pady=5)

        # Output directory and recent dirs (moved up, API key moved to Settings)
        output_frame = ttk.Frame(self.root)
        output_frame.pack(fill=tk.X, padx=15, pady=4)
        ttk.Label(output_frame, text="Output:").grid(row=0, column=0, sticky="w", padx=(0, 8))
        ttk.Entry(output_frame, textvariable=self.output_dir_var, width=50).grid(row=0, column=1, padx=5, sticky="we")
        ttk.Button(output_frame, text="Browse", command=self._browse_output_dir).grid(row=0, column=2, padx=8)
        output_frame.columnconfigure(1, weight=1)
        
        # Recent directories section
        recent_container = ttk.Frame(self.root)
        recent_container.pack(fill=tk.X, padx=15, pady=(0, 4))
        ttk.Label(recent_container, text="Recent:", style="Muted.TLabel").pack(side=tk.LEFT, padx=(0, 8))
        self._recent_dirs_frame = ttk.Frame(recent_container)
        self._recent_dirs_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)

        notebook = ttk.Notebook(self.root)
        notebook.pack(fill=tk.BOTH, expand=True, padx=15, pady=8)

        primary_tab = ttk.Frame(notebook, padding=5)
        self.search_tab = ttk.Frame(notebook, padding=5)
        self.settings_tab = ttk.Frame(notebook, padding=10)

        notebook.add(primary_tab, text="  Filters & Download  ")
        notebook.add(self.search_tab, text="  Search  ")
        notebook.add(self.settings_tab, text="  Settings  ")

        self._build_filters_section(primary_tab)
        self._build_search_tab()
        self._build_settings_tab()

        log_frame = ttk.LabelFrame(self.root, text="Activity Log")
        log_frame.pack(fill=tk.BOTH, padx=15, pady=(0, 10))
        self.log_box = scrolledtext.ScrolledText(
            log_frame, 
            height=5, 
            state=tk.DISABLED,
            font=theme.FONTS["mono"],
            bg=theme.PALETTE["log_bg"],
            fg=theme.PALETTE["log_fg"],
            insertbackground="white",
            selectbackground="#264f78",
            relief=tk.FLAT,
            padx=8,
            pady=8
        )
        self.log_box.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        # Colour tags for log lines (classified in _drain_messages).
        self.log_box.tag_configure("error", foreground="#f08c8c")
        self.log_box.tag_configure("success", foreground="#8ce09a")
        self.log_box.tag_configure("warning", foreground="#f0c674")
        self.log_box.tag_configure("info", foreground=theme.PALETTE["log_fg"])

        status_frame = ttk.Frame(self.root)
        status_frame.pack(fill=tk.X, padx=15, pady=(0, 12))
        ttk.Label(status_frame, text="Status:", style="TLabel", font=theme.FONTS["bold"]).pack(side=tk.LEFT)
        self._status_value_label = ttk.Label(status_frame, textvariable=self.status_var, font=theme.FONTS["base"])
        self._status_value_label.pack(side=tk.LEFT, padx=(6, 0))
        self._progress = ttk.Progressbar(
            status_frame, mode="indeterminate", length=180,
            style="Accent.Horizontal.TProgressbar",
        )
        # Packed/started only while a download is active (see _set_progress_active).
        self._on_status_changed()

    def _build_search_tab(self) -> None:
        ttk.Label(
            self.search_tab,
            text="Search results help populate the filters below. Select a row, then click Apply to Filters.",
            wraplength=760,
        ).pack(fill=tk.X, padx=10, pady=(10, 0))

        search_frame = ttk.LabelFrame(self.search_tab, text="Search Civitai")
        search_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        ttk.Label(search_frame, text="Category:").grid(row=0, column=0, sticky="w")
        ttk.Combobox(
            search_frame,
            textvariable=self.search_type_var,
            values=["models", "images", "creators", "tags"],
            width=15,
            state="readonly",
        ).grid(row=0, column=1, sticky="w", padx=5)

        ttk.Label(search_frame, text="Query:").grid(row=0, column=2, sticky="w")
        ttk.Entry(search_frame, textvariable=self.search_query_var).grid(row=0, column=3, sticky="we", padx=5)
        self._search_button = ttk.Button(search_frame, text="Search", command=self._perform_search)
        self._search_button.grid(row=0, column=4, padx=5)
        ttk.Button(search_frame, text="Clear", command=self._clear_search).grid(row=0, column=5, padx=5)
        search_frame.columnconfigure(3, weight=1)
        ttk.Label(
            search_frame,
            text="💡 Images have no free-text search — for the Images category the query is matched as tag name(s); "
                 "separate multiple tags with commas. Platform checkboxes and Max rating also apply. "
                 "Leave the query empty to browse a Username's images; the Model ID / Version fields never limit a search.",
            font=("Segoe UI", 8),
            foreground="#666666",
            wraplength=720,
            justify=tk.LEFT,
        ).grid(row=3, column=0, columnspan=6, sticky="w", pady=(0, 2))

        _TREE_COLS = ("col1", "col2", "col3", "col4", "col5")
        _COL_WIDTHS = (60, 260, 90, 130, 90)
        self.results_tree = ttk.Treeview(search_frame, columns=_TREE_COLS, show="headings", height=12)
        for col, w in zip(_TREE_COLS, _COL_WIDTHS):
            self.results_tree.heading(col, text="")
            self.results_tree.column(col, width=w, minwidth=40)
        self.results_tree.grid(row=1, column=0, columnspan=6, sticky="nsew", pady=8)
        theme.configure_treeview_tags(self.results_tree)
        self.results_tree.bind("<Double-1>", lambda _e: self._apply_selection())
        search_frame.rowconfigure(1, weight=1)

        btn_frame = ttk.Frame(search_frame)
        btn_frame.grid(row=2, column=0, columnspan=6, sticky="ew", pady=5)
        ttk.Label(
            btn_frame,
            text="ℹ️ Double-click or Apply → loads the selected item\'s IDs into the Download tab filters.",
            font=("Segoe UI", 8),
            foreground="#555555",
        ).pack(side=tk.LEFT)
        self.apply_selection_button = ttk.Button(btn_frame, text="Apply to Filters", command=self._apply_selection)
        self.apply_selection_button.pack(side=tk.RIGHT, padx=5)
        ttk.Button(btn_frame, text="Open in Civitai", command=self._open_result_in_browser).pack(side=tk.RIGHT, padx=5)

    def _build_filters_section(self, parent: ttk.Frame) -> None:
        url_frame = ttk.LabelFrame(parent, text="Quick Start - Paste a Civitai or Hugging Face URL")
        url_frame.pack(fill=tk.X, padx=5, pady=(3, 5))
        
        # URL entry with placeholder-like hint
        url_entry = ttk.Entry(url_frame, textvariable=self.url_var, font=("Segoe UI", 10))
        url_entry.grid(row=0, column=0, padx=6, pady=6, sticky="we")
        
        # Button container for better grouping
        btn_container = ttk.Frame(url_frame)
        btn_container.grid(row=0, column=1, padx=(0, 6), pady=6)
        
        ttk.Button(btn_container, text="Resolve", command=self._resolve_url, style="Accent.TButton").pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_container, text="Preview files", command=self._preview_files).pack(side=tk.LEFT, padx=2)
        self.download_button = ttk.Button(btn_container, text="⬇ Download", style="Download.TButton", command=self._start_download)
        self.download_button.pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_container, text="Clear", command=self._clear_filters).pack(side=tk.LEFT, padx=2)
        
        url_frame.columnconfigure(0, weight=1)
        
        hint_label = ttk.Label(
            url_frame, 
            text="💡 Civitai model/version/image/user URLs, or a Hugging Face file link (…/blob/main/file.safetensors) - auto-resolves!",
            font=("Segoe UI", 8),
            foreground="#666666"
        )
        hint_label.grid(row=1, column=0, columnspan=2, sticky="w", padx=6, pady=(0, 4))

        platform_frame = ttk.LabelFrame(parent, text="Platforms")
        platform_frame.pack(fill=tk.X, padx=5, pady=(5, 3))
        columns = 5
        for index, (label, value) in enumerate(PLATFORM_CHOICES):
            row = index // columns
            col = index % columns
            ttk.Checkbutton(
                platform_frame,
                text=label,
                variable=self.platform_vars[value],
                command=self._sync_platforms,
            ).grid(row=row, column=col, padx=(4, 8), pady=2, sticky="w")

        footer_row = (len(PLATFORM_CHOICES) + columns - 1) // columns
        ttk.Label(platform_frame, text="Custom:").grid(row=footer_row, column=0, sticky="w", padx=(4, 8), pady=(4, 2))
        ttk.Entry(platform_frame, textvariable=self.base_models_var).grid(row=footer_row, column=1, columnspan=columns - 1, sticky="we", padx=2, pady=(4, 2))

        picker_row = footer_row + 1
        ttk.Label(platform_frame, text="All models:").grid(row=picker_row, column=0, sticky="w", padx=(4, 8), pady=(0, 4))
        self._platform_picker = ttk.Combobox(
            platform_frame,
            textvariable=self.add_platform_var,
            values=self._valid_base_models,
            state="readonly",
            width=28,
        )
        self._platform_picker.grid(row=picker_row, column=1, columnspan=2, sticky="we", padx=2, pady=(0, 4))
        self._platform_picker.bind("<<ComboboxSelected>>", lambda _e: self._add_picked_platform())
        ttk.Button(platform_frame, text="Add", command=self._add_picked_platform).grid(
            row=picker_row, column=3, sticky="w", padx=2, pady=(0, 4)
        )
        for col in range(columns):
            platform_frame.columnconfigure(col, weight=1)

        model_frame = ttk.LabelFrame(parent, text="Model and user filters")
        model_frame.pack(fill=tk.X, padx=5, pady=3)
        ttk.Label(model_frame, text="Username:").grid(row=0, column=0, sticky="w", padx=2)
        ttk.Entry(model_frame, textvariable=self.username_var, width=18).grid(row=0, column=1, padx=2)
        ttk.Label(model_frame, text="Model ID:").grid(row=0, column=2, sticky="w", padx=2)
        ttk.Entry(model_frame, textvariable=self.model_id_var, width=10).grid(row=0, column=3, padx=2)
        ttk.Label(model_frame, text="Version ID:").grid(row=0, column=4, sticky="w", padx=2)
        ttk.Entry(model_frame, textvariable=self.version_id_var, width=10).grid(row=0, column=5, padx=2)
        ttk.Label(model_frame, text="Max items:").grid(row=0, column=6, sticky="w", padx=2)
        ttk.Entry(model_frame, textvariable=self.max_items_var, width=6).grid(row=0, column=7, padx=2)

        options_frame = ttk.LabelFrame(parent, text="Result options")
        options_frame.pack(fill=tk.X, padx=5, pady=3)
        ttk.Label(options_frame, text="Max rating:").grid(row=0, column=0, sticky="w", padx=2)
        ttk.Combobox(options_frame, textvariable=self.nsfw_var, values=RATING_ORDER, state="readonly", width=8).grid(row=0, column=1, padx=2)
        ttk.Label(options_frame, text="Period:").grid(row=0, column=2, sticky="w", padx=2)
        ttk.Combobox(options_frame, textvariable=self.period_var, values=["AllTime", "Year", "Month", "Week", "Day"], state="readonly", width=8).grid(row=0, column=3, padx=2)
        ttk.Label(options_frame, text="Sort:").grid(row=0, column=4, sticky="w", padx=2)
        ttk.Combobox(options_frame, textvariable=self.sort_var, values=SORT_OPTIONS, state="readonly", width=14).grid(row=0, column=5, padx=2)
        ttk.Checkbutton(options_frame, text="Images", variable=self.include_images_var).grid(row=0, column=6, sticky="w", padx=4)
        ttk.Checkbutton(options_frame, text="Videos", variable=self.include_videos_var).grid(row=0, column=7, sticky="w", padx=4)

        # Download options (merged here so tag_frame is last and can expand properly)
        ttk.Separator(parent, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=10, pady=(4, 2))
        dl_frame = ttk.LabelFrame(parent, text="Download options")
        dl_frame.pack(fill=tk.X, padx=5, pady=(0, 3))
        ttk.Checkbutton(dl_frame, text="Previews",    variable=self.include_previews_var).grid( row=0, column=0, sticky="w", padx=3, pady=2)
        ttk.Checkbutton(dl_frame, text="Originals",   variable=self.include_originals_var).grid(row=0, column=1, sticky="w", padx=3, pady=2)
        ttk.Checkbutton(dl_frame, text="Workflows",   variable=self.include_workflows_var).grid(row=0, column=2, sticky="w", padx=3, pady=2)
        ttk.Checkbutton(dl_frame, text="Videos",      variable=self.include_videos_var).grid(    row=0, column=3, sticky="w", padx=3, pady=2)
        ttk.Checkbutton(dl_frame, text="Metadata",    variable=self.save_metadata_var).grid(     row=0, column=4, sticky="w", padx=3, pady=2)
        ttk.Checkbutton(dl_frame, text="Native size", variable=self.native_images_var).grid(     row=0, column=5, sticky="w", padx=3, pady=2)
        ttk.Checkbutton(dl_frame, text="Prompts",     variable=self.save_prompts_var).grid(      row=0, column=6, sticky="w", padx=3, pady=2)
        ttk.Label(
            dl_frame,
            text="💡 Prompts come from each image's embedded metadata. Enable Prompts with Previews off to collect prompts.txt without keeping the images.",
            font=("Segoe UI", 8),
            foreground="#666666",
            wraplength=720,
            justify=tk.LEFT,
        ).grid(row=1, column=0, columnspan=8, sticky="w", padx=3, pady=(0, 2))

        tag_frame = ttk.LabelFrame(parent, text="Tags")
        tag_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=3)
        ttk.Label(tag_frame, text="Search:").grid(row=0, column=0, sticky="w", padx=2)
        ttk.Entry(tag_frame, textvariable=self.tag_query_var).grid(row=0, column=1, sticky="we", padx=2)
        ttk.Button(tag_frame, text="Search", command=self._search_tags).grid(row=0, column=2, padx=2)
        ttk.Button(tag_frame, text="+ Add", command=self._add_selected_tag).grid(row=0, column=3, padx=2)
        ttk.Button(tag_frame, text="- Remove", command=self._remove_selected_tag).grid(row=0, column=4, padx=2)
        tag_frame.columnconfigure(1, weight=1)

        # Side by side tag lists
        tag_lists_frame = ttk.Frame(tag_frame)
        tag_lists_frame.grid(row=1, column=0, columnspan=5, sticky="nsew", pady=3)
        tag_frame.rowconfigure(1, weight=1)
        
        # Search results (left)
        tag_columns = ("name", "models")
        self.tag_results_tree = ttk.Treeview(tag_lists_frame, columns=tag_columns, show="headings", height=5)
        self.tag_results_tree.heading("name", text="Search Results")
        self.tag_results_tree.heading("models", text="#")
        self.tag_results_tree.column("name", width=180)
        self.tag_results_tree.column("models", width=40)
        tag_vsb = ttk.Scrollbar(tag_lists_frame, orient=tk.VERTICAL, command=self.tag_results_tree.yview)
        self.tag_results_tree.configure(yscrollcommand=tag_vsb.set)
        theme.configure_treeview_tags(self.tag_results_tree)
        self.tag_results_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tag_vsb.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 6))

        # Active tags (right)
        self.active_tags_tree = ttk.Treeview(tag_lists_frame, columns=("tag",), show="headings", height=5)
        self.active_tags_tree.heading("tag", text="Active Tags")
        self.active_tags_tree.column("tag", width=200)
        active_vsb = ttk.Scrollbar(tag_lists_frame, orient=tk.VERTICAL, command=self.active_tags_tree.yview)
        self.active_tags_tree.configure(yscrollcommand=active_vsb.set)
        theme.configure_treeview_tags(self.active_tags_tree)
        self.active_tags_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        active_vsb.pack(side=tk.LEFT, fill=tk.Y)

    def _build_download_section(self, parent: ttk.Frame) -> None:
        # Options are now embedded in _build_filters_section; this method is kept
        # for compatibility but does nothing.
        pass


    def _build_settings_tab(self) -> None:
        """Build the Settings tab with API key and path configurations."""
        
        # API Key section
        api_frame = ttk.LabelFrame(self.settings_tab, text="Civitai API Key")
        api_frame.pack(fill=tk.X, padx=10, pady=(10, 15))
        
        ttk.Label(
            api_frame, 
            text="Your API key is used to access the Civitai API. Get one from civitai.red/user/account",
            font=("Segoe UI", 8),
            foreground="#666666"
        ).grid(row=0, column=0, columnspan=3, sticky="w", padx=10, pady=(10, 5))
        
        ttk.Label(api_frame, text="API Key:").grid(row=1, column=0, sticky="w", padx=10, pady=10)
        api_entry = ttk.Entry(api_frame, textvariable=self.api_key_var, width=60, show="*")
        api_entry.grid(row=1, column=1, padx=5, pady=10, sticky="we")
        ttk.Button(api_frame, text="Apply", command=self._apply_api_key).grid(row=1, column=2, padx=10, pady=10)
        api_frame.columnconfigure(1, weight=1)
        
        # Show/hide toggle
        self._show_api_key = tk.BooleanVar(value=False)
        def toggle_api_visibility():
            api_entry.config(show="" if self._show_api_key.get() else "*")
        ttk.Checkbutton(
            api_frame, 
            text="Show API key", 
            variable=self._show_api_key,
            command=toggle_api_visibility
        ).grid(row=2, column=1, sticky="w", padx=5, pady=(0, 10))
        
        # Model base path section
        paths_frame = ttk.LabelFrame(self.settings_tab, text="Default Paths")
        paths_frame.pack(fill=tk.X, padx=10, pady=15)
        
        ttk.Label(
            paths_frame, 
            text="Set a base path for your models. When browsing for output, this will be the starting location.",
            font=("Segoe UI", 8),
            foreground="#666666"
        ).grid(row=0, column=0, columnspan=3, sticky="w", padx=10, pady=(10, 5))
        
        ttk.Label(paths_frame, text="Models base path:").grid(row=1, column=0, sticky="w", padx=10, pady=10)
        ttk.Entry(paths_frame, textvariable=self.model_base_path_var, width=50).grid(row=1, column=1, padx=5, pady=10, sticky="we")
        ttk.Button(paths_frame, text="Browse", command=self._browse_model_base_path).grid(row=1, column=2, padx=10, pady=10)
        paths_frame.columnconfigure(1, weight=1)
        
        # Quick set buttons for common paths
        quick_paths_frame = ttk.Frame(paths_frame)
        quick_paths_frame.grid(row=2, column=0, columnspan=3, sticky="w", padx=10, pady=(0, 10))
        ttk.Label(quick_paths_frame, text="Quick set:", font=("Segoe UI", 8)).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(
            quick_paths_frame, 
            text="Use as Output", 
            command=self._use_base_as_output,
            style="Recent.TButton"
        ).pack(side=tk.LEFT, padx=2)
        
        # Hugging Face section
        hf_frame = ttk.LabelFrame(self.settings_tab, text="Hugging Face")
        hf_frame.pack(fill=tk.X, padx=10, pady=15)
        ttk.Label(
            hf_frame,
            text="Optional. Needed only for gated repos (FLUX, some SD3/Wan releases). Create a read token at huggingface.co/settings/tokens",
            font=("Segoe UI", 8),
            foreground="#666666",
        ).grid(row=0, column=0, columnspan=3, sticky="w", padx=10, pady=(10, 5))
        ttk.Label(hf_frame, text="Access token:").grid(row=1, column=0, sticky="w", padx=10, pady=10)
        hf_entry = ttk.Entry(hf_frame, textvariable=self.hf_token_var, width=60, show="*")
        hf_entry.grid(row=1, column=1, padx=5, pady=10, sticky="we")
        hf_frame.columnconfigure(1, weight=1)
        self._show_hf_token = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            hf_frame,
            text="Show token",
            variable=self._show_hf_token,
            command=lambda: hf_entry.config(show="" if self._show_hf_token.get() else "*"),
        ).grid(row=2, column=1, sticky="w", padx=5, pady=(0, 10))

        # Large-file transfer section
        xfer_frame = ttk.LabelFrame(self.settings_tab, text="Large-file downloads (resume + verify)")
        xfer_frame.pack(fill=tk.X, padx=10, pady=15)
        ttk.Label(
            xfer_frame,
            text=(
                "Model files download to a .part file, resume automatically after connection drops, "
                "re-fetch expired links, and are size/SHA-256 checked before being renamed into place.\n"
                "aria2 adds multi-connection downloads; without it a built-in single-connection resumable downloader is used."
            ),
            font=("Segoe UI", 8),
            foreground="#666666",
            justify=tk.LEFT,
        ).grid(row=0, column=0, columnspan=4, sticky="w", padx=10, pady=(10, 5))
        ttk.Checkbutton(
            xfer_frame,
            text="Use aria2 when available (auto-installs into the app's bin folder on first use)",
            variable=self.use_aria2_var,
        ).grid(row=1, column=0, columnspan=4, sticky="w", padx=10, pady=(0, 6))
        ttk.Label(xfer_frame, text="aria2c path:").grid(row=2, column=0, sticky="w", padx=10, pady=6)
        ttk.Entry(xfer_frame, textvariable=self.aria2_path_var, width=50).grid(row=2, column=1, padx=5, pady=6, sticky="we")
        ttk.Button(xfer_frame, text="Browse", command=self._browse_aria2_path).grid(row=2, column=2, padx=(5, 2), pady=6)
        ttk.Button(xfer_frame, text="Detect / Install", command=self._detect_aria2).grid(row=2, column=3, padx=(2, 10), pady=6)
        ttk.Label(xfer_frame, text="Connections per file:").grid(row=3, column=0, sticky="w", padx=10, pady=6)
        ttk.Spinbox(xfer_frame, from_=1, to=16, width=5, textvariable=self.aria2_connections_var).grid(row=3, column=1, sticky="w", padx=5, pady=6)
        self._aria2_status_label = ttk.Label(xfer_frame, text="", font=("Segoe UI", 8), foreground="#888888")
        self._aria2_status_label.grid(row=4, column=0, columnspan=4, sticky="w", padx=10, pady=(0, 10))
        xfer_frame.columnconfigure(1, weight=1)
        self.root.after(200, self._refresh_aria2_status)

        # Chrome Extension section
        extension_frame = ttk.LabelFrame(self.settings_tab, text="Chrome Extension Integration")
        extension_frame.pack(fill=tk.X, padx=10, pady=15)
        
        ttk.Label(
            extension_frame, 
            text="Enable the local server to receive URLs from the Chrome extension.\nUse Alt+Shift+C in Chrome to send the current Civitai page here.",
            font=("Segoe UI", 8),
            foreground="#666666"
        ).grid(row=0, column=0, columnspan=3, sticky="w", padx=10, pady=(10, 5))
        
        ext_controls = ttk.Frame(extension_frame)
        ext_controls.grid(row=1, column=0, columnspan=3, sticky="w", padx=10, pady=10)
        
        ttk.Checkbutton(
            ext_controls, 
            text="Enable Chrome extension server (port 7865)", 
            variable=self._extension_enabled_var,
            command=self._toggle_extension_server
        ).pack(side=tk.LEFT, padx=(0, 15))
        
        self._server_status_label = ttk.Label(ext_controls, text="● Server stopped", foreground="#888888")
        self._server_status_label.pack(side=tk.LEFT)
        
        ttk.Label(
            extension_frame, 
            text="To install: Open chrome://extensions, enable Developer mode, click 'Load unpacked',\nand select the chrome_extension folder in this app's directory.",
            font=("Segoe UI", 8),
            foreground="#666666"
        ).grid(row=2, column=0, columnspan=3, sticky="w", padx=10, pady=(5, 10))
        
        # Info section
        info_frame = ttk.LabelFrame(self.settings_tab, text="About")
        info_frame.pack(fill=tk.X, padx=10, pady=15)
        
        about_text = """Civitai Desktop Helper v1.2

A tool for downloading images and metadata from Civitai.

• Paste a Civitai URL and click Download
• Paste a Hugging Face file link to download it (resumable, verified)
• Use filters to search for specific content
• Recent directories are saved for quick access
• Use Chrome extension to send URLs directly (Ctrl+Shift+D)

Settings are automatically saved when you close the app."""
        
        ttk.Label(
            info_frame, 
            text=about_text,
            font=("Segoe UI", 9),
            justify=tk.LEFT
        ).pack(padx=10, pady=10, anchor="w")
    
    def _browse_aria2_path(self) -> None:
        path = filedialog.askopenfilename(
            title="Locate aria2c",
            filetypes=[("aria2c", "aria2c.exe aria2c"), ("All files", "*.*")],
        )
        if path:
            self.aria2_path_var.set(path)
            self._refresh_aria2_status()

    def _refresh_aria2_status(self) -> None:
        if not hasattr(self, "_aria2_status_label"):
            return
        found = find_aria2(self.aria2_path_var.get().strip())
        if found:
            self._aria2_status_label.config(text=f"● aria2 found: {found}", foreground="#2e7d32")
        else:
            self._aria2_status_label.config(
                text="● aria2 not found - it will be fetched automatically on the first large download, or click Detect / Install.",
                foreground="#888888",
            )

    def _detect_aria2(self) -> None:
        settings = TransferSettings(use_aria2=True, aria2_path=self.aria2_path_var.get().strip(), auto_fetch_aria2=True)

        def _worker() -> None:
            found = ensure_aria2(settings, self._queue_log)
            if found:
                self._queue_log(f"aria2 ready: {found}")
            else:
                self._queue_log("aria2 unavailable; the built-in resumable downloader will be used.")
            self._queue_action("aria2_status", {})

        threading.Thread(target=_worker, daemon=True).start()

    def _browse_model_base_path(self) -> None:
        """Browse for model base path."""
        current = self.model_base_path_var.get().strip()
        initial_dir = current if current and Path(current).exists() else None
        chosen = filedialog.askdirectory(initialdir=initial_dir)
        if chosen:
            self.model_base_path_var.set(chosen)
            self._queue_log(f"Model base path set to: {chosen}")
    
    def _use_base_as_output(self) -> None:
        """Set the output directory to the model base path."""
        base = self.model_base_path_var.get().strip()
        if base:
            self.output_dir_var.set(base)
            self._add_recent_dir(base)
            self._queue_log(f"Output directory set to base path: {base}")
        else:
            messagebox.showinfo("Base Path", "Set a model base path first.")
    
    def _toggle_extension_server(self) -> None:
        """Toggle the local server for Chrome extension."""
        if self._extension_enabled_var.get():
            if self._local_server.start():
                self._server_status_label.config(text="● Server running", foreground="#44aa44")
                self._queue_log("Chrome extension server started on port 7865")
            else:
                self._extension_enabled_var.set(False)
                self._server_status_label.config(text="● Failed to start", foreground="#aa4444")
                self._queue_log("Failed to start Chrome extension server (port may be in use)")
        else:
            self._local_server.stop()
            self._server_status_label.config(text="● Server stopped", foreground="#888888")
            self._queue_log("Chrome extension server stopped")
    
    def _on_url_received(self, url: str) -> None:
        """Called when a URL is received from the Chrome extension."""
        # This runs in the server thread, so we need to use the message queue
        self._message_queue.put(("action", ("url_received", {"url": url})))
    
    def _show_quick_download_popup(self, url: str) -> None:
        """Quick-download popup: stable last-used folder buttons plus a multi-root
        folder tree that reveals and highlights recently-used folders wherever they
        live (not just under the model base path)."""
        popup = tk.Toplevel(self.root)
        popup.title("Quick Download")
        popup.geometry("600x720")
        popup.minsize(520, 560)
        popup.transient(self.root)
        popup.grab_set()

        popup.update_idletasks()
        x = (popup.winfo_screenwidth() - 600) // 2
        y = (popup.winfo_screenheight() - 720) // 2
        popup.geometry(f"600x720+{x}+{y}")
        popup.attributes('-topmost', True)
        popup.focus_force()

        # URL display
        url_frame = ttk.LabelFrame(popup, text="URL from Civitai")
        url_frame.pack(fill=tk.X, padx=15, pady=(15, 6))
        display_url = url if len(url) < 70 else url[:67] + "..."
        ttk.Label(url_frame, text=display_url, font=("Segoe UI", 9), foreground="#0066cc").pack(padx=10, pady=6)

        selected_dir = tk.StringVar(value=self.output_dir_var.get())

        def _norm(p: str) -> str:
            try:
                return str(Path(p).resolve()).lower()
            except Exception:
                return (p or "").strip().lower()

        def _anchor(p: str) -> str:
            try:
                return Path(p).anchor or str(Path(p))
            except Exception:
                return p

        recent_norm = {_norm(d) for d in self._recent_dirs}

        # Save-to entry + Browse
        current_frame = ttk.Frame(popup)
        current_frame.pack(fill=tk.X, padx=15, pady=(4, 2))
        ttk.Label(current_frame, text="Save to:").pack(side=tk.LEFT)
        location_entry = ttk.Entry(current_frame, textvariable=selected_dir)
        location_entry.pack(side=tk.LEFT, padx=8, fill=tk.X, expand=True)

        def browse_location():
            base = self.model_base_path_var.get().strip()
            initial = selected_dir.get() or base or None
            if initial and Path(initial).exists():
                chosen = filedialog.askdirectory(initialdir=initial, parent=popup)
            else:
                chosen = filedialog.askdirectory(parent=popup)
            if chosen:
                selected_dir.set(chosen)
                reveal(chosen, select=True)

        ttk.Button(current_frame, text="Browse", command=browse_location).pack(side=tk.LEFT)

        # Last-used folders — stable buttons (sorted so they never jump around)
        recent_frame = ttk.LabelFrame(popup, text="Last used folders (click to select)")
        recent_frame.pack(fill=tk.X, padx=15, pady=(8, 4))
        recent_inner = ttk.Frame(recent_frame)
        recent_inner.pack(fill=tk.X, padx=6, pady=4)
        recent_sorted = sorted(
            (d for d in self._recent_dirs if d),
            key=lambda d: self._get_short_dir_name(d).lower(),
        )
        if not recent_sorted:
            ttk.Label(recent_inner, text="(none yet — downloaded-to folders will appear here)",
                      style="Muted.TLabel").grid(row=0, column=0, sticky="w")
        else:
            for idx, d in enumerate(recent_sorted[:12]):
                name = self._get_short_dir_name(d)
                if len(name) > 26:
                    name = "…" + name[-24:]
                b = ttk.Button(recent_inner, text=f"📁 {name}",
                               command=lambda dd=d: (selected_dir.set(dd), reveal(dd, select=True)))
                b.grid(row=idx // 3, column=idx % 3, sticky="ew", padx=2, pady=2)
                self._add_tooltip(b, d)
            for c in range(3):
                recent_inner.columnconfigure(c, weight=1)

        # Folder tree (multi-root: one node per drive/anchor involved)
        tree_frame = ttk.LabelFrame(popup, text="Folders (recent folders highlighted)")
        tree_frame.pack(fill=tk.BOTH, expand=True, padx=15, pady=(4, 4))

        filter_row = ttk.Frame(tree_frame)
        filter_row.pack(fill=tk.X, padx=6, pady=(6, 2))
        ttk.Label(filter_row, text="Filter:").pack(side=tk.LEFT)
        filter_var = tk.StringVar()
        filter_entry = ttk.Entry(filter_row, textvariable=filter_var)
        filter_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 6))

        tree_container = ttk.Frame(tree_frame)
        tree_container.pack(fill=tk.BOTH, expand=True, padx=6, pady=(0, 6))
        tree = ttk.Treeview(tree_container, show="tree", selectmode="browse", height=12)
        vsb = ttk.Scrollbar(tree_container, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        tree.tag_configure("recent", background="#fff3bf")

        item_paths: Dict[str, str] = {}

        def _subdirs(path: str) -> List[str]:
            try:
                return sorted(
                    (str(c) for c in Path(path).iterdir() if c.is_dir() and not c.name.startswith('.')),
                    key=str.lower,
                )
            except Exception:
                return []

        def _has_subdir(path: str) -> bool:
            try:
                return any(c.is_dir() and not c.name.startswith('.') for c in Path(path).iterdir())
            except Exception:
                return False

        def add_node(parent_item: str, path: str, text: Optional[str] = None) -> str:
            label = text if text is not None else (Path(path).name or path)
            tags = ("recent",) if _norm(path) in recent_norm else ()
            item = tree.insert(parent_item, "end", text=f"📁 {label}", open=False, tags=tags)
            item_paths[item] = path
            if _has_subdir(path):
                tree.insert(item, "end", text="…")  # lazy placeholder
            return item

        def populate(item: str) -> None:
            children = tree.get_children(item)
            if len(children) == 1 and children[0] not in item_paths:
                tree.delete(children[0])
                for sub in _subdirs(item_paths[item]):
                    add_node(item, sub)

        def on_open(_event=None):
            populate(tree.focus())

        def on_select(_event=None):
            sel = tree.selection()
            if sel and sel[0] in item_paths:
                selected_dir.set(item_paths[sel[0]])

        tree.bind("<<TreeviewOpen>>", on_open)
        tree.bind("<<TreeviewSelect>>", on_select)

        # Build one root per distinct drive/anchor across the base path, recent
        # folders, and the current target — so folders on any drive are reachable.
        base_path = self.model_base_path_var.get().strip()
        seeds: List[str] = []
        for s in [base_path, self.output_dir_var.get().strip(), *self._recent_dirs, selected_dir.get()]:
            if s and Path(s).exists() and s not in seeds:
                seeds.append(s)
        if not seeds:
            seeds.append(str(Path.home()))

        anchor_items: Dict[str, str] = {}
        for s in seeds:
            anc = _anchor(s)
            key = _norm(anc)
            if key not in anchor_items and Path(anc).exists():
                root_item = add_node("", anc, text=anc)
                anchor_items[key] = root_item
                tree.item(root_item, open=True)
                populate(root_item)

        def reveal(path: str, select: bool = False) -> Optional[str]:
            try:
                p = Path(path)
            except Exception:
                return None
            root = anchor_items.get(_norm(_anchor(path)))
            if not root or not p.exists():
                return None
            populate(root)
            current = root
            for part in p.parts[1:]:
                match = None
                for child in tree.get_children(current):
                    cp = item_paths.get(child)
                    if cp and Path(cp).name.lower() == part.lower():
                        match = child
                        break
                if match is None:
                    break
                populate(match)
                tree.item(match, open=True)
                current = match
            if select:
                tree.selection_set(current)
            tree.see(current)
            return current

        # Reveal the base path and each recent folder (highlighted), then select
        # the current target.
        if base_path and Path(base_path).exists():
            reveal(base_path)
        for d in self._recent_dirs:
            reveal(d)
        if selected_dir.get():
            reveal(selected_dir.get(), select=True)

        def jump_to_filter(_event=None):
            query = filter_var.get().strip().lower()
            if not query:
                return "break"
            for item, path in item_paths.items():
                if query in Path(path).name.lower():
                    tree.see(item)
                    tree.selection_set(item)
                    tree.focus(item)
                    break
            return "break"

        filter_var.trace_add("write", lambda *_a: jump_to_filter())
        filter_entry.bind("<Return>", jump_to_filter)

        # Bottom buttons (fixed position)
        btn_frame = ttk.Frame(popup)
        btn_frame.pack(fill=tk.X, padx=15, pady=(4, 15), side=tk.BOTTOM)

        def do_download():
            self.output_dir_var.set(selected_dir.get())
            self._add_recent_dir(selected_dir.get())
            popup.destroy()
            self._start_download()

        def cancel():
            popup.destroy()

        ttk.Button(btn_frame, text="Cancel", command=cancel).pack(side=tk.LEFT, padx=5)
        download_btn = ttk.Button(btn_frame, text="⬇ Download Now", style="Download.TButton", command=do_download)
        download_btn.pack(side=tk.RIGHT, padx=5)

        popup.bind('<Escape>', lambda e: cancel())
        download_btn.focus_set()

    def _apply_api_key(self) -> None:
        key = self.api_key_var.get().strip()
        self.state.api_key = key
        self.client.update_api_key(key)
        self._queue_log("API key applied.")

    def _browse_output_dir(self) -> None:
        # Start from model base path if set, otherwise current output dir
        base_path = self.model_base_path_var.get().strip()
        current_output = self.output_dir_var.get().strip()
        
        initial_dir = None
        if current_output and Path(current_output).exists():
            initial_dir = current_output
        elif base_path and Path(base_path).exists():
            initial_dir = base_path
        
        chosen = filedialog.askdirectory(initialdir=initial_dir)
        if chosen:
            self.output_dir_var.set(chosen)
            self._add_recent_dir(chosen)
    
    def _add_recent_dir(self, directory: str) -> None:
        """Add a directory to the recent list and refresh the buttons."""
        if not directory:
            return
        # Remove if already exists (will re-add at front)
        if directory in self._recent_dirs:
            self._recent_dirs.remove(directory)
        # Add to front
        self._recent_dirs.insert(0, directory)
        # Keep only max recent
        self._recent_dirs = self._recent_dirs[:self._max_recent_dirs]
        self._refresh_recent_dirs_buttons()
    
    def _refresh_recent_dirs_buttons(self) -> None:
        """Rebuild the recent directory buttons."""
        if self._recent_dirs_frame is None:
            return
        # Clear existing buttons
        for widget in self._recent_dirs_frame.winfo_children():
            widget.destroy()
        
        if not self._recent_dirs:
            ttk.Label(
                self._recent_dirs_frame, 
                text="(No recent directories)", 
                font=("Segoe UI", 8),
                foreground="#888888"
            ).pack(side=tk.LEFT)
            return
        
        # Create a button for each recent directory (compact strip: cap to keep one row)
        for idx, dir_path in enumerate(self._recent_dirs[:5]):
            # Get a short display name (last folder name or drive)
            display_name = self._get_short_dir_name(dir_path)
            btn = ttk.Button(
                self._recent_dirs_frame,
                text=f"📁 {display_name}",
                command=lambda d=dir_path: self._select_recent_dir(d),
            )
            btn.pack(side=tk.LEFT, padx=(0, 4))
            # Add tooltip-like behavior
            self._add_tooltip(btn, dir_path)
    
    def _get_short_dir_name(self, dir_path: str) -> str:
        """Get a shortened display name for a directory."""
        from pathlib import Path
        p = Path(dir_path)
        parts = p.parts
        if len(parts) >= 2:
            # Show last two parts of the path
            return "/".join(parts[-2:])
        elif len(parts) == 1:
            return parts[0]
        return dir_path
    
    def _select_recent_dir(self, directory: str) -> None:
        """Select a recent directory and move it to the front."""
        self.output_dir_var.set(directory)
        # Move to front of list
        if directory in self._recent_dirs:
            self._recent_dirs.remove(directory)
        self._recent_dirs.insert(0, directory)
        self._refresh_recent_dirs_buttons()
        self._queue_log(f"Output directory set to: {directory}")
    
    def _add_tooltip(self, widget: tk.Widget, text: str) -> None:
        """Add a simple tooltip to a widget showing the full path."""
        tooltip = None
        
        def show_tooltip(event):
            nonlocal tooltip
            x, y, _, _ = widget.bbox("insert") if hasattr(widget, 'bbox') else (0, 0, 0, 0)
            x += widget.winfo_rootx() + 25
            y += widget.winfo_rooty() + 25
            
            tooltip = tk.Toplevel(widget)
            tooltip.wm_overrideredirect(True)
            tooltip.wm_geometry(f"+{x}+{y}")
            
            label = ttk.Label(
                tooltip, 
                text=text, 
                background="#ffffe1", 
                relief="solid", 
                borderwidth=1,
                font=("Segoe UI", 8),
                padding=(4, 2)
            )
            label.pack()
        
        def hide_tooltip(event):
            nonlocal tooltip
            if tooltip:
                tooltip.destroy()
                tooltip = None
        
        widget.bind("<Enter>", show_tooltip)
        widget.bind("<Leave>", hide_tooltip)

    def _resolve_url(self, max_retries: int = 3, show_errors: bool = True) -> bool:
        """Resolve the URL with automatic retry on failure.
        
        Returns True if resolution succeeded, False otherwise.
        """
        url = self.url_var.get().strip()
        if not url:
            if show_errors:
                messagebox.showinfo("Resolve", "Enter a Civitai or Hugging Face URL first.")
            return False
        
        self.status_var.set("Resolving URL…")
        entity = None
        last_error = None
        
        for attempt in range(1, max_retries + 1):
            try:
                entity = resolve_url(url, self.client, hf_token=self.hf_token_var.get().strip())
                if entity:
                    break
            except ApiError as exc:
                last_error = exc
                if attempt < max_retries:
                    self._queue_log(f"Resolve attempt {attempt} failed, retrying...")
                    time.sleep(0.5)  # Brief pause before retry
                continue
            except Exception as exc:
                last_error = exc
                if attempt < max_retries:
                    self._queue_log(f"Resolve attempt {attempt} failed, retrying...")
                    time.sleep(0.5)
                continue
        
        self.status_var.set("Ready")
        
        if not entity:
            if last_error and show_errors:
                messagebox.showerror("Resolve failed", f"Failed after {max_retries} attempts: {last_error}")
            elif show_errors:
                messagebox.showinfo("Resolve", "Could not identify entity from URL.")
            return False
        
        self.state.resolved = entity
        self._last_resolved_url = url
        
        if entity.model_id:
            self.model_id_var.set(str(entity.model_id))
        else:
            self.model_id_var.set("")
        if entity.model_version_id:
            self.version_id_var.set(str(entity.model_version_id))
        else:
            self.version_id_var.set("")
        self.username_var.set(entity.extra.get("username") or "")
        # A pasted URL targets a specific model/user/image, so clear the discovery
        # filters (platform checkboxes + tags) — otherwise leftover selections
        # silently narrow the gallery (e.g. a stale "Krea 2" cutting 300 → 25).
        for var in self.platform_vars.values():
            var.set(False)
        self.base_models_var.set("")
        if self._selected_tags:
            self._selected_tags.clear()
            self._refresh_active_tags()
        self._queue_log(f"Resolved {entity.entity_type}: {entity.identifier}")
        return True

    def _perform_search(self) -> None:
        # Read all tkinter variables on the main thread before handing off to a worker thread
        query = self.search_query_var.get().strip()
        category = self.search_type_var.get()
        username = self.username_var.get().strip() or ""
        base_models = self._collect_base_models()
        model_id = self._safe_int(self.model_id_var.get())
        version_id = self._safe_int(self.version_id_var.get())
        nsfw_val = self.nsfw_var.get()
        browsing_level = rating_to_browsing_level(normalize_rating(nsfw_val))
        media_types = self._selected_media_types()
        # For image search the API has no free-text query, so treat the query box
        # as a comma-separated list of tag names to match.
        image_tags = [t.strip() for t in query.split(",") if t.strip()]

        self.status_var.set("Searching…")
        if hasattr(self, "_search_button"):
            self._search_button.config(state=tk.DISABLED)

        def _worker() -> None:
            try:
                if category == "models":
                    payload = self.client.search_models(
                        query=query, username=username, base_models=base_models
                    )
                    items = payload.get("items", [])
                    display = [
                        (
                            item.get("id", ""),
                            item.get("name", ""),
                            item.get("type", ""),
                            # first version's base model (most recent version)
                            (item.get("modelVersions") or [{}])[0].get("baseModel", ""),
                            item.get("stats", {}).get("downloadCount", ""),
                        )
                        for item in items
                    ]
                elif category == "images":
                    # The Search tab shares the Model ID / Version / Username fields
                    # with the download form, so never let those stale download
                    # targets silently scope a search. A keyword search is global
                    # (filtered only by platform + rating); with no keyword we fall
                    # back to a username-scoped browse when one is provided.
                    if image_tags:
                        items, _ = self.client.search_images(
                            limit=50, browsing_level=browsing_level,
                            types=media_types, base_models=base_models,
                            tag_names=image_tags,
                        )
                    else:
                        items, _ = self.client.search_images(
                            limit=50, username=username, browsing_level=browsing_level,
                            types=media_types, base_models=base_models,
                        )
                    display = [
                        (
                            item.get("id", ""),
                            item.get("modelName", ""),
                            item.get("type", ""),
                            item.get("nsfwLevel", ""),
                            item.get("username", ""),
                        )
                        for item in items
                    ]
                elif category == "creators":
                    payload = self.client.search_creators(query=query or username)
                    items = payload.get("items", [])
                    display = [
                        (entry.get("username", ""), entry.get("modelCount", ""), "", "", "")
                        for entry in items
                    ]
                else:
                    payload = self.client.search_tags(query=query)
                    items = payload.get("items", [])
                    display = [
                        (entry.get("id", ""), entry.get("name", ""), entry.get("modelCount", ""), "", "")
                        for entry in items
                    ]
                self._queue_action("search_results", {"items": items, "display": display, "category": category})
            except ApiError as exc:
                self._queue_action("search_error", {"message": str(exc)})

        threading.Thread(target=_worker, daemon=True).start()

    def _clear_search(self) -> None:
        self.search_query_var.set("")
        for row in self.results_tree.get_children():
            self.results_tree.delete(row)
        self._current_results = []
        self.results_tree.selection_remove(self.results_tree.selection())
        self._queue_log("Cleared search inputs and results.")

    def _clear_filters(self) -> None:
        self.url_var.set("")
        self.username_var.set("")
        self.model_id_var.set("")
        self.version_id_var.set("")
        self.max_items_var.set("100")
        self.base_models_var.set("")
        for var in self.platform_vars.values():
            var.set(False)
        self.tag_query_var.set("")
        self.nsfw_var.set("X")
        self.period_var.set("AllTime")
        self.sort_var.set(SORT_OPTIONS[0])
        self._selected_tags.clear()
        self._refresh_active_tags()
        for row in self.tag_results_tree.get_children():
            self.tag_results_tree.delete(row)
        self.state.reset_filters()
        self.state.filters.nsfw = "X"
        self.state.downloads.max_items = 100
        self.state.resolved = None
        self._queue_log("Cleared filter inputs.")
        self._tag_lookup.clear()

    def _apply_selection(self) -> None:
        selected = self.results_tree.selection()
        if not selected:
            return
        index = self.results_tree.index(selected[0])
        if index >= len(self._current_results):
            return
        item = self._current_results[index]
        category = self.search_type_var.get()
        if category == "models":
            model_id = item.get("id")
            if model_id:
                self.model_id_var.set(str(model_id))
            if item.get("creator") and item["creator"].get("username"):
                self.username_var.set(item["creator"]["username"])
            self._queue_log(f"Applied model {model_id} to filters.")
        elif category == "images":
            model_id = item.get("modelId")
            version_id = item.get("modelVersionId")
            if model_id:
                self.model_id_var.set(str(model_id))
            if version_id:
                self.version_id_var.set(str(version_id))
            self._queue_log(f"Image {item.get('id')} populated model/version filters.")
        elif category == "creators":
            username = item.get("username") or self.results_tree.item(selected[0], "values")[0]
            if username:
                self.username_var.set(username)
            self._queue_log(f"Applied creator {username} to filters.")
        else:
            name = item.get("name")
            if name:
                self._selected_tags[name] = name
                self._refresh_active_tags()
            self._queue_log(f"Tag {name} queued for filtering.")

    def _open_result_in_browser(self) -> None:
        selected = self.results_tree.selection()
        if not selected:
            return
        index = self.results_tree.index(selected[0])
        if index >= len(self._current_results):
            return
        item = self._current_results[index]
        category = self.search_type_var.get()
        site = self.client.base_url
        if category == "models":
            url = f"{site}/models/{item.get('id')}"
        elif category == "images":
            url = f"{site}/images/{item.get('id')}"
        elif category == "creators":
            url = f"{site}/user/{item.get('username')}"
        else:
            # tags have a link field
            url = item.get("link", "")
        if url:
            webbrowser.open(url)

    def _search_tags(self) -> None:
        query = self.tag_query_var.get().strip()
        self.status_var.set("Searching tags…")

        def _worker() -> None:
            try:
                payload = self.client.search_tags(query=query)
            except ApiError as exc:
                self._queue_action("search_error", {"message": str(exc)})
                return
            finally:
                self._queue_status("Ready")
            items = payload.get("items", [])
            self._queue_action("tag_results", {"items": items})

        threading.Thread(target=_worker, daemon=True).start()

    def _add_selected_tag(self) -> None:
        selection = self.tag_results_tree.selection()
        if not selection:
            return
        for iid in selection:
            name = self._tag_lookup.get(iid) or iid
            self._selected_tags[name] = name
        self._refresh_active_tags()

    def _remove_selected_tag(self) -> None:
        selection = self.active_tags_tree.selection()
        if not selection:
            return
        for iid in selection:
            self._selected_tags.pop(iid, None)
        self._refresh_active_tags()

    def _refresh_active_tags(self) -> None:
        for row in self.active_tags_tree.get_children():
            self.active_tags_tree.delete(row)
        for idx, name in enumerate(sorted(self._selected_tags)):
            self.active_tags_tree.insert("", tk.END, values=(name,), iid=name, tags=(theme.row_tag(idx),))

    def _add_picked_platform(self) -> None:
        """Append the base model chosen in the 'All models' picker to the filter."""
        choice = self.add_platform_var.get().strip()
        if not choice:
            return
        if choice in self.platform_vars:
            self.platform_vars[choice].set(True)
        else:
            existing = [e.strip() for e in self.base_models_var.get().split(",") if e.strip()]
            if choice not in existing:
                existing.append(choice)
                self.base_models_var.set(", ".join(existing))
        self.add_platform_var.set("")
        self._sync_platforms()

    def _refresh_base_model_choices(self) -> None:
        """Fetch Civitai's live base-model enum list in the background."""
        def _worker() -> None:
            try:
                choices = self.client.base_model_choices()
            except ApiError:
                return
            if choices:
                self._queue_action("base_models_loaded", {"choices": choices})

        threading.Thread(target=_worker, daemon=True).start()

    def _sync_platforms(self) -> None:
        selected_values = [value for value, var in self.platform_vars.items() if var.get()]
        manual_entries: List[str] = []
        for entry in self.base_models_var.get().split(","):
            normalized = _normalize_base_model_token(entry)
            if not normalized:
                continue
            if normalized in self.platform_vars:
                continue
            if normalized not in manual_entries:
                manual_entries.append(normalized)

        combined: List[str] = []
        for value in selected_values + manual_entries:
            if value not in combined:
                combined.append(value)

        self.base_models_var.set(", ".join(combined))

    def _collect_base_models(self) -> List[str]:
        selected_values = [value for value, var in self.platform_vars.items() if var.get()]
        manual_values: List[str] = []
        for entry in self.base_models_var.get().split(","):
            normalized = _normalize_base_model_token(entry)
            if not normalized:
                continue
            if normalized in selected_values or normalized in manual_values:
                continue
            manual_values.append(normalized)

        combined: List[str] = []
        for value in selected_values + manual_values:
            if value not in combined:
                combined.append(value)

        # Drop values Civitai no longer accepts — a single bad token makes the
        # whole request fail with HTTP 400, which previously broke all searching.
        valid: List[str] = []
        for value in combined:
            if value in self._valid_base_models_set:
                valid.append(value)
            else:
                self._queue_log(f"Ignoring unknown base model '{value}' (not a valid Civitai platform).")
        return valid

    def _selected_media_types(self) -> List[str]:
        types: List[str] = []
        if self.include_images_var.get():
            types.append("image")
        if self.include_videos_var.get():
            types.append("video")
        return types or ["image"]

    @staticmethod
    def _format_download_summary(results: Dict[str, int]) -> str:
        def segment(key: str, label: str) -> str:
            count = int(results.get(key, 0) or 0)
            return f"{count} {label}{'' if count == 1 else 's'}"

        parts = [
            segment("images", "image"),
            segment("videos", "video"),
            segment("assets", "asset"),
        ]
        return "Download complete – " + ", ".join(parts)

    def _start_download(self) -> None:
        current_url = self.url_var.get().strip()
        current_output = self.output_dir_var.get().strip()
        
        # If download is in progress, queue this one
        if getattr(self, "_download_thread", None) and self._download_thread.is_alive():
            if current_url:
                self._download_queue.append({"url": current_url, "output_dir": current_output})
                queue_pos = len(self._download_queue)
                self._queue_log(f"📋 Added to queue (position {queue_pos}): {current_url}")
                self._update_queue_status()
            return
        
        self._apply_api_key()
        
        # Auto-resolve URL if it has changed or hasn't been resolved yet
        if current_url and current_url != self._last_resolved_url:
            self._queue_log("URL changed, auto-resolving...")
            if not self._resolve_url(max_retries=3, show_errors=True):
                # Resolution failed, try next in queue
                self._process_next_in_queue()
                return
        
        # Add current output directory to recent list
        if current_output:
            self._add_recent_dir(current_output)

        # Let the user choose which weight-file variant(s) to pull when a version
        # exposes several quantizations (fp16/fp8/int8/…). Returns False if the
        # user cancels, in which case we abort this run and move to the queue.
        if not self._select_variant_files_if_needed():
            self._queue_log("Download cancelled at variant selection.")
            self._process_next_in_queue()
            return

        self._apply_ui_to_state()
        self._update_queue_status()
        if self.download_button is not None:
            self.download_button.config(text="Downloading…", style="Downloading.TButton", state=tk.DISABLED)
        self._set_progress_active(True)
        self._queue_log("Starting download run...")
        self._download_thread = threading.Thread(target=self._run_download_worker, daemon=True)
        self._download_thread.start()

    def _preferred_version_id_from_state(self) -> Optional[int]:
        """Resolve the version id the downloader will default to for the current
        model, mirroring execute_downloads' preferred-version selection."""
        resolved = self.state.resolved
        extra = resolved.extra if resolved else {}
        model_detail = extra.get("model") if isinstance(extra, dict) else None
        versions = model_detail.get("modelVersions") if isinstance(model_detail, dict) else None
        if not versions:
            model_id = self._safe_int(self.model_id_var.get())
            if model_id is None and resolved is not None:
                model_id = resolved.model_id
            if model_id is None:
                return None
            try:
                model_detail = self.client.get_model(int(model_id))
            except Exception:  # noqa: BLE001 - treat lookup failure as "no info"
                return None
            versions = model_detail.get("modelVersions") if isinstance(model_detail, dict) else None
        if not versions:
            return None
        preferred = _select_preferred_version(versions)
        if not isinstance(preferred, dict):
            return None
        try:
            return int(preferred.get("id"))
        except (TypeError, ValueError):
            return None

    def _target_version_detail(self) -> Tuple[Optional[int], Optional[Dict[str, Any]]]:
        """Resolve the version id the next run targets plus its API detail.

        Reuses the version payload the resolver already fetched when possible so
        both the variant picker and the file preview avoid redundant API calls.
        Returns (None, None) when no version can be determined or the lookup fails."""
        resolved = self.state.resolved
        extra = resolved.extra if isinstance(getattr(resolved, "extra", None), dict) else {}

        version_id = self._safe_int(self.version_id_var.get())
        if version_id is None and resolved is not None:
            version_id = resolved.model_version_id
        if version_id is None:
            version_id = self._preferred_version_id_from_state()
        if version_id is None:
            return None, None

        cached_version = extra.get("modelVersion")
        if isinstance(cached_version, dict) and cached_version.get("files"):
            try:
                cached_id = int(cached_version.get("id"))
            except (TypeError, ValueError):
                cached_id = None
            if cached_id == int(version_id):
                return version_id, cached_version
        try:
            return version_id, self.client.get_model_version(int(version_id))
        except Exception as exc:  # noqa: BLE001 - don't block on API hiccups
            self._queue_log(f"Could not inspect version files ({exc}).")
            return version_id, None

    def _select_variant_files_if_needed(self) -> bool:
        """Populate self._pending_file_ids for the upcoming run.

        Returns False only when the user cancels the variant picker, signalling
        the caller to abort this download."""
        self._pending_file_ids = None
        resolved = self.state.resolved
        extra = resolved.extra if isinstance(getattr(resolved, "extra", None), dict) else {}

        # A pasted download link may pin an explicit fileId (e.g. a chosen
        # quantization). Honor it directly without prompting.
        explicit_file_id = extra.get("fileId")
        if isinstance(explicit_file_id, int):
            self._pending_file_ids = [explicit_file_id]
            self._queue_log(f"Using the specific file (id {explicit_file_id}) from the pasted link.")
            return True

        # Only matters when weight files are actually being fetched.
        if not self.include_originals_var.get():
            return True

        version_id, detail = self._target_version_detail()
        if version_id is None or not isinstance(detail, dict):
            return True

        variants = describe_variant_files(detail)
        if len(variants) <= 1:
            return True  # single (or no) weight file — nothing to choose

        # Pin the version so the worker downloads exactly what the user picked.
        if not self.version_id_var.get().strip():
            self.version_id_var.set(str(version_id))

        chosen = self._prompt_variant_selection(variants, detail.get("name") or str(version_id))
        if chosen is None:
            return False
        self._pending_file_ids = chosen
        names = ", ".join(
            str(v.get("fp") or v.get("name") or v.get("id"))
            for v in variants if v.get("id") in chosen
        )
        self._queue_log(f"Selected {len(chosen)} file variant(s): {names}")
        return True

    def _prompt_variant_selection(self, variants: List[Dict[str, Any]], version_name: str) -> Optional[List[int]]:
        """Modal multi-select picker for a version's quantized weight files.

        Returns the chosen file ids, or None if the user cancels."""
        dialog = tk.Toplevel(self.root)
        dialog.title("Select file variants")
        dialog.transient(self.root)
        dialog.resizable(False, True)

        ttk.Label(
            dialog,
            text=f"\u201c{version_name}\u201d offers several files (e.g. different precisions).\n"
                 "Choose which one(s) to download:",
            font=("Segoe UI", 10, "bold"),
            wraplength=460,
            justify="left",
        ).pack(anchor="w", padx=12, pady=(12, 8))

        body = ttk.Frame(dialog)
        body.pack(fill=tk.BOTH, expand=True, padx=12)

        # Pre-check the smallest *primary* weight file (the main model/diffusion
        # weights) as a sensible default; fall back to the smallest overall.
        primary_sizes = [v.get("size_bytes") for v in variants
                         if v.get("is_primary") and isinstance(v.get("size_bytes"), int)]
        all_sizes = [v.get("size_bytes") for v in variants if isinstance(v.get("size_bytes"), int)]
        default_size = min(primary_sizes) if primary_sizes else (min(all_sizes) if all_sizes else None)
        default_used = False

        vars_and_ids: List[Tuple[tk.BooleanVar, int]] = []
        for variant in variants:
            fid = variant.get("id")
            if not isinstance(fid, int):
                continue
            descriptor_bits = [str(variant[k]) for k in ("fp", "format", "size_label") if variant.get(k)]
            descriptor = " / ".join(descriptor_bits) or (variant.get("name") or f"file {fid}")
            type_label = str(variant.get("type") or "").strip()
            if type_label:
                descriptor = f"{type_label}  \u2014  {descriptor}"
            size_bytes = variant.get("size_bytes")
            size_txt = f"{size_bytes / (1024 ** 3):.2f} GB" if isinstance(size_bytes, int) else "size unknown"
            label = f"{descriptor}    \u2022    {size_txt}"
            is_default = (
                not default_used
                and default_size is not None
                and size_bytes == default_size
                and (variant.get("is_primary") or not primary_sizes)
            )
            if is_default:
                default_used = True
            bv = tk.BooleanVar(value=is_default)
            ttk.Checkbutton(body, text=label, variable=bv).pack(anchor="w", pady=2)
            vars_and_ids.append((bv, fid))

        result: Dict[str, Optional[List[int]]] = {"ids": None}

        def _confirm() -> None:
            chosen = [fid for bv, fid in vars_and_ids if bv.get()]
            if not chosen:
                messagebox.showinfo("Select files", "Pick at least one file, or press Cancel.", parent=dialog)
                return
            result["ids"] = chosen
            dialog.destroy()

        def _cancel() -> None:
            result["ids"] = None
            dialog.destroy()

        btns = ttk.Frame(dialog)
        btns.pack(fill=tk.X, padx=12, pady=12)
        ttk.Button(btns, text="Download selected", style="Accent.TButton", command=_confirm).pack(side=tk.RIGHT, padx=4)
        ttk.Button(btns, text="Cancel", command=_cancel).pack(side=tk.RIGHT, padx=4)

        dialog.protocol("WM_DELETE_WINDOW", _cancel)
        dialog.update_idletasks()
        dialog.grab_set()
        self.root.wait_window(dialog)
        return result["ids"]

    def _preview_files(self) -> None:
        """Show the files (and their sizes) a download run would fetch, without
        downloading anything — handy before committing to multi-GB checkpoints."""
        url = self.url_var.get().strip()
        if url and url != self._last_resolved_url:
            self.status_var.set("Resolving URL…")
            if not self._resolve_url(max_retries=3, show_errors=True):
                return

        version_id, detail = self._target_version_detail()
        if version_id is None or not isinstance(detail, dict):
            messagebox.showinfo(
                "Preview files",
                "Could not determine a model version to preview. Resolve a model or "
                "version URL, or enter a Version ID first.",
            )
            return

        rows = summarize_version_files(detail)
        if not rows:
            messagebox.showinfo("Preview files", "This version has no downloadable files.")
            return
        self._show_file_preview(detail.get("name") or str(version_id), version_id, rows)

    def _show_file_preview(self, version_name: str, version_id: int, rows: List[Dict[str, Any]]) -> None:
        dialog = tk.Toplevel(self.root)
        dialog.title("Files in this version")
        dialog.transient(self.root)
        dialog.resizable(True, True)

        ttk.Label(
            dialog,
            text=f"\u201c{version_name}\u201d (version {version_id}) contains these files:",
            font=("Segoe UI", 10, "bold"),
            wraplength=560,
            justify="left",
        ).pack(anchor="w", padx=12, pady=(12, 8))

        columns = ("type", "precision", "format", "size", "name")
        tree = ttk.Treeview(dialog, columns=columns, show="headings", height=min(14, max(4, len(rows))))
        headings = {"type": "Type", "precision": "Precision", "format": "Format", "size": "Size", "name": "File name"}
        widths = {"type": 90, "precision": 80, "format": 90, "size": 90, "name": 320}
        for col in columns:
            tree.heading(col, text=headings[col])
            anchor = tk.E if col == "size" else tk.W
            tree.column(col, width=widths[col], anchor=anchor, stretch=(col == "name"))

        for row in rows:
            tag = "weight" if row.get("is_model") else "other"
            tree.insert(
                "", tk.END,
                values=(
                    (row.get("type") or "").title() or "—",
                    row.get("fp") or "—",
                    row.get("format") or "—",
                    format_size(row.get("size_bytes")),
                    row.get("name") or "—",
                ),
                tags=(tag,),
            )
        tree.tag_configure("weight", background="#eef5ff")

        scroll = ttk.Scrollbar(dialog, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        tree_frame = ttk.Frame(dialog)
        tree_frame.pack(fill=tk.BOTH, expand=True, padx=12)
        tree.pack(in_=tree_frame, side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(in_=tree_frame, side=tk.RIGHT, fill=tk.Y)

        weight_total = sum(r["size_bytes"] for r in rows if r.get("is_model") and isinstance(r.get("size_bytes"), int))
        all_total = sum(r["size_bytes"] for r in rows if isinstance(r.get("size_bytes"), int))
        summary = (
            f"Weight files: {sum(1 for r in rows if r.get('is_model'))}  "
            f"({format_size(weight_total)})      "
            f"All files total: {format_size(all_total)}"
        )
        ttk.Label(dialog, text=summary, font=("Segoe UI", 9)).pack(anchor="w", padx=12, pady=(8, 0))
        ttk.Label(
            dialog,
            text="Tip: weight files are highlighted. When several exist you'll be asked "
                 "to choose which to download.",
            font=("Segoe UI", 8),
            foreground="#666666",
            wraplength=560,
            justify="left",
        ).pack(anchor="w", padx=12, pady=(2, 0))

        btns = ttk.Frame(dialog)
        btns.pack(fill=tk.X, padx=12, pady=12)
        ttk.Button(btns, text="Close", command=dialog.destroy).pack(side=tk.RIGHT, padx=4)

        dialog.update_idletasks()
        dialog.grab_set()
        self.root.wait_window(dialog)

    def _update_queue_status(self) -> None:
        """Update status to show queue count if any."""
        if self._download_queue:
            self.status_var.set(f"Downloading… ({len(self._download_queue)} in queue)")
        elif getattr(self, "_download_thread", None) and self._download_thread.is_alive():
            self.status_var.set("Downloading…")
        else:
            self.status_var.set("Ready")
    
    def _process_next_in_queue(self) -> None:
        """Process the next item in the download queue."""
        if not self._download_queue:
            self._update_queue_status()
            return
        
        # Get next item from queue
        next_item = self._download_queue.pop(0)
        url = next_item.get("url", "")
        output_dir = next_item.get("output_dir", "")
        
        self._queue_log(f"📋 Processing queued download: {url}")
        
        # Set up for this download
        self.url_var.set(url)
        if output_dir:
            self.output_dir_var.set(output_dir)
        
        # Clear the last resolved URL to force re-resolution
        self._last_resolved_url = ""
        
        # Start the download (this will resolve and download)
        self._start_download()

    def _apply_ui_to_state(self) -> None:
        self.state.filters.query = self.search_query_var.get().strip()
        self.state.filters.username = self.username_var.get().strip()
        self.state.filters.base_models = self._collect_base_models()
        self.state.filters.tag_names = list(self._selected_tags.keys())
        self.state.filters.nsfw = normalize_rating(self.nsfw_var.get())
        self.state.filters.browsing_level = rating_to_browsing_level(self.state.filters.nsfw)
        self.state.filters.period = self.period_var.get()
        sort_value = self.sort_var.get()
        if sort_value not in SORT_OPTIONS:
            sort_value = SORT_OPTIONS[0]
            self.sort_var.set(sort_value)
        self.state.filters.sort = sort_value
        self.state.filters.types = self._selected_media_types()
        self.state.filters.model_id = self._safe_int(self.model_id_var.get())
        self.state.filters.model_version_id = self._safe_int(self.version_id_var.get())

        max_items = self._safe_int(self.max_items_var.get(), allow_zero=True)
        max_items = max_items if max_items is not None else 0

        downloads = DownloadOptions(
            grab_previews=self.include_previews_var.get(),
            grab_originals=self.include_originals_var.get(),
            grab_workflows=self.include_workflows_var.get(),
            grab_videos=self.include_videos_var.get(),
            save_metadata=self.save_metadata_var.get(),
            prefer_native_images=self.native_images_var.get(),
            max_items=max_items or 0,
            output_root=self.output_dir_var.get().strip() or "downloads",
            selected_file_ids=self._pending_file_ids,
            save_prompts=self.save_prompts_var.get(),
        )
        self.state.downloads = downloads

        self.state.hf_token = self.hf_token_var.get().strip()
        connections = self._safe_int(self.aria2_connections_var.get()) or 8
        self.state.transfer = TransferSettings(
            use_aria2=self.use_aria2_var.get(),
            aria2_path=self.aria2_path_var.get().strip(),
            connections=max(1, min(16, connections)),
        )

    def _run_download_worker(self) -> None:
        success = False
        results: Dict[str, int] = {}
        try:
            results = execute_downloads(self.client, self.state, self._queue_log)
            success = True
            self._queue_log(self._format_download_summary(results))
        except ApiError as exc:
            self._queue_log(f"Download failed: {exc}")
        except Exception as exc:  # noqa: BLE001 - surface unexpected failures to the activity log
            self._queue_log(f"Unexpected error during download: {exc}")
        finally:
            self._queue_status("Ready")
            self._queue_action("download_finished", {"success": success, "results": results})

    def _queue_log(self, message: str) -> None:
        print(message)
        self._message_queue.put(("log", message))

    def _queue_status(self, message: str) -> None:
        self._message_queue.put(("status", message))

    def _queue_action(self, action: str, data: Optional[Dict[str, Any]] = None) -> None:
        self._message_queue.put(("action", (action, data)))

    def _classify_log_line(self, line: str) -> str:
        """Pick a colour tag for an activity-log line based on its content."""
        low = line.lower()
        if any(k in low for k in ("error", "fail", "❌", "could not", "unable", "invalid", "exception")):
            return "error"
        if any(k in low for k in ("✓", "✅", "done", "complete", "finished", "saved", "success")):
            return "success"
        if any(k in low for k in ("⚠", "warning", "skip", "retry", "cancel")):
            return "warning"
        return "info"

    def _drain_messages(self) -> None:
        flushed = False
        while True:
            try:
                kind, payload = self._message_queue.get_nowait()
            except Empty:
                break
            if kind == "log":
                self.log_box.configure(state=tk.NORMAL)
                self.log_box.insert(tk.END, payload + "\n", (self._classify_log_line(payload),))
                self.log_box.see(tk.END)
                self.log_box.configure(state=tk.DISABLED)
                flushed = True
            elif kind == "status":
                self.status_var.set(payload)
            elif kind == "action":
                self._handle_action(payload)
        if flushed:
            self.root.update_idletasks()
        self.root.after(200, self._drain_messages)

    def _handle_action(self, payload: Any) -> None:
        if isinstance(payload, tuple):
            action, data = payload
        else:
            action, data = payload, None

        if action == "aria2_status":
            self._refresh_aria2_status()
            return
        if action == "base_models_loaded" and data is not None:
            choices = data.get("choices") or []
            if choices:
                self._valid_base_models = list(choices)
                self._valid_base_models_set = set(choices)
                if getattr(self, "_platform_picker", None) is not None:
                    self._platform_picker.configure(values=self._valid_base_models)
            return
        if action == "download_finished" and self.download_button is not None:
            self.download_button.config(text="⬇ Download", style="Download.TButton", state=tk.NORMAL)
            self._set_progress_active(False)
            if data and not data.get("success", True):
                self.status_var.set("Download failed")
            else:
                # Process next item in queue if any
                self._process_next_in_queue()
        
        elif action == "search_results" and data is not None:
            items: List[Dict] = data.get("items", [])
            display: List[tuple] = data.get("display", [])
            cat: str = data.get("category", "models")
            # Update column headings to match the search type
            _HEADERS: Dict[str, List[str]] = {
                "models":   ["ID", "Name", "Type", "Base Model", "Downloads"],
                "images":   ["ID", "Model Name", "Media Type", "Rating", "Creator"],
                "creators": ["Username", "Model Count", "", "", ""],
                "tags":     ["ID", "Tag Name", "Model Count", "", ""],
            }
            for col, heading in zip(
                ("col1", "col2", "col3", "col4", "col5"),
                _HEADERS.get(cat, ["Col 1", "Col 2", "Col 3", "Col 4", "Col 5"]),
            ):
                self.results_tree.heading(col, text=heading)
            for row in self.results_tree.get_children():
                self.results_tree.delete(row)
            self._current_results = items
            for row_index, entry in enumerate(display):
                values = tuple(value if value is not None else "" for value in entry)
                self.results_tree.insert("", tk.END, values=values, tags=(theme.row_tag(row_index),))
            self._queue_log(f"Search returned {len(items)} items.")
            self._queue_status("Ready")
            if hasattr(self, "_search_button"):
                self._search_button.config(state=tk.NORMAL)

        elif action == "tag_results" and data is not None:
            items = data.get("items", [])
            self._tag_lookup.clear()
            for row in self.tag_results_tree.get_children():
                self.tag_results_tree.delete(row)
            inserted = 0
            for item in items:
                name = item.get("name", "").strip()
                if not name:
                    continue
                iid = name  # tag name is the unique key
                self._tag_lookup[iid] = name
                model_count = item.get("modelCount", "")
                self.tag_results_tree.insert("", tk.END, values=(name, model_count), iid=iid, tags=(theme.row_tag(inserted),))
                inserted += 1
            self._queue_log(f"Loaded {inserted} of {len(items)} tags.")

        elif action == "search_error" and data is not None:
            messagebox.showerror("Search failed", data.get("message", "Unknown error"))
            self._queue_status("Ready")
            if hasattr(self, "_search_button"):
                self._search_button.config(state=tk.NORMAL)

        elif action == "url_received" and data:
            # URL received from Chrome extension
            url = data.get("url", "")
            if url:
                self._queue_log(f"📥 URL received from Chrome extension: {url}")
                self.url_var.set(url)
                # Show quick download popup
                self._show_quick_download_popup(url)

    def _load_settings(self) -> None:
        if not SETTINGS_FILE.exists():
            return
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except Exception:
            return
        self.api_key_var.set(data.get("api_key", ""))
        api_base = data.get("api_base")
        if api_base:
            self.client.update_base_url(str(api_base))
        self.username_var.set(data.get("username", ""))
        self.model_id_var.set(str(data.get("model_id", "")) if data.get("model_id") else "")
        self.version_id_var.set(str(data.get("version_id", "")) if data.get("version_id") else "")
        self.nsfw_var.set(normalize_rating(data.get("nsfw", "XXX")))
        self.period_var.set(data.get("period", "AllTime"))
        saved_sort = data.get("sort", SORT_OPTIONS[0])
        if saved_sort not in SORT_OPTIONS:
            saved_sort = SORT_OPTIONS[0]
        self.sort_var.set(saved_sort)
        self.output_dir_var.set(data.get("output", "downloads"))
        self.model_base_path_var.set(data.get("model_base_path", ""))
        self.hf_token_var.set(data.get("hf_token", ""))
        self.use_aria2_var.set(bool(data.get("use_aria2", True)))
        self.aria2_path_var.set(data.get("aria2_path", ""))
        self.aria2_connections_var.set(str(data.get("aria2_connections", "8")))
        self.max_items_var.set(str(data.get("max_items", "0")))
        normalized_models: List[str] = []
        for entry in data.get("base_models", []):
            normalized = _normalize_base_model_token(entry) or ""
            if not normalized:
                continue
            if normalized in self.platform_vars:
                self.platform_vars[normalized].set(True)
            if normalized not in normalized_models:
                normalized_models.append(normalized)
        self.base_models_var.set(", ".join(normalized_models))
        tag_map = data.get("tags", {})
        if isinstance(tag_map, dict):
            self._selected_tags = {str(k): str(v) for k, v in tag_map.items()}
            self._refresh_active_tags()
        # Load recent directories
        recent = data.get("recent_dirs", [])
        if isinstance(recent, list):
            self._recent_dirs = [d for d in recent if isinstance(d, str)][:self._max_recent_dirs]
        pinned = data.get("pinned_dirs", [])
        if isinstance(pinned, list):
            self._pinned_dirs = [d for d in pinned if isinstance(d, str)]
        self._refresh_recent_dirs_buttons()
        
        # Load extension server setting and auto-start if was enabled
        extension_enabled = data.get("extension_server_enabled", False)
        if extension_enabled:
            self._extension_enabled_var.set(True)
            self._toggle_extension_server()
        
        self._apply_api_key()

    def _save_settings(self) -> None:
        # Ensure current output dir is in recent list before saving
        current_output = self.output_dir_var.get().strip()
        if current_output and current_output not in self._recent_dirs:
            self._recent_dirs.insert(0, current_output)
            self._recent_dirs = self._recent_dirs[:self._max_recent_dirs]
        
        payload = {
            "api_key": self.api_key_var.get().strip(),
            "api_base": self.client.base_url,
            "username": self.username_var.get().strip(),
            "model_id": self.model_id_var.get().strip(),
            "version_id": self.version_id_var.get().strip(),
            "nsfw": self.nsfw_var.get(),
            "period": self.period_var.get(),
            "sort": self.sort_var.get(),
            "output": self.output_dir_var.get().strip(),
            "model_base_path": self.model_base_path_var.get().strip(),
            "hf_token": self.hf_token_var.get().strip(),
            "use_aria2": self.use_aria2_var.get(),
            "aria2_path": self.aria2_path_var.get().strip(),
            "aria2_connections": self.aria2_connections_var.get().strip(),
            "max_items": self.max_items_var.get().strip(),
            "base_models": self._collect_base_models(),
            "tags": {str(k): v for k, v in self._selected_tags.items()},
            "recent_dirs": self._recent_dirs,
            "pinned_dirs": self._pinned_dirs,
            "extension_server_enabled": self._extension_enabled_var.get(),
        }
        try:
            with open(SETTINGS_FILE, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2)
        except Exception:
            pass

    def _on_close(self) -> None:
        self._save_settings()
        # Stop the extension server if running
        if self._local_server.is_running:
            self._local_server.stop()
        self.root.destroy()

    @staticmethod
    def _safe_int(value: str, allow_zero: bool = False) -> int | None:
        if not value:
            return None
        try:
            parsed = int(value)
        except ValueError:
            return None
        if not allow_zero and parsed == 0:
            return None
        return parsed

    def run(self) -> None:
        self.root.mainloop()


def run_app() -> None:
    app = CivitaiApp()
    app.run()
