from __future__ import annotations

import json
import threading
from queue import Queue, Empty
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk

from .api_client import ApiError, CivitaiClient
from .downloads import execute_downloads
from .state import AppState, DownloadOptions
from .url_resolver import resolve_url
from .local_server import LocalURLServer

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
    ("Flux 1D (Dev)", "FLUX.1 [dev]"),
    ("Flux 1S (Schnell)", "FLUX.1 [schnell]"),
    ("Flux 1 Pro", "FLUX.1 [pro]"),
    ("Flux 2", "Flux 2"),
    ("Flux Schnell", "Flux Schnell"),
    ("Flux Dev", "Flux Dev"),
    ("Illustrious", "Illustrious"),
    ("Illustrious XL", "Illustrious XL"),
    ("Pony", "Pony"),
    ("Pony Diffusion XL", "Pony Diffusion XL"),
    ("SD 1.5", "SD 1.5"),
    ("SDXL 1.0", "SDXL 1.0"),
    ("SDXL Turbo", "SDXL Turbo"),
    ("SDXL Lightning", "SDXL Lightning"),
    ("SDXL Refiner", "SDXL Refiner"),
    ("Z-Image-Turbo", "Z-Image-Turbo"),
    ("Qwen 2D", "Qwen 2D"),
    ("Qwen 2.5D", "Qwen 2.5D"),
    ("Wan 2.2", "Wan 2.2"),
    ("Wan 1.3", "Wan 1.3"),
]

PLATFORM_ALIAS_MAP = {
    "flux": "FLUX.1 [dev]",
    "flux dev": "FLUX.1 [dev]",
    "flux.1d": "FLUX.1 [dev]",
    "flux 1d": "FLUX.1 [dev]",
    "flux .1d": "FLUX.1 [dev]",
    "flux1d": "FLUX.1 [dev]",
    "flux 1d (dev)": "FLUX.1 [dev]",
    "flux.1 [dev]": "FLUX.1 [dev]",
    "flux 1s": "FLUX.1 [schnell]",
    "flux .1s": "FLUX.1 [schnell]",
    "flux.1s": "FLUX.1 [schnell]",
    "flux schnell": "FLUX.1 [schnell]",
    "flux.1 [schnell]": "FLUX.1 [schnell]",
    "flux 1 pro": "FLUX.1 [pro]",
    "flux pro": "FLUX.1 [pro]",
    "flux.1p": "FLUX.1 [pro]",
    "flux.1 [pro]": "FLUX.1 [pro]",
    "flux dev legacy": "Flux Dev",
    "flux schnell legacy": "Flux Schnell",
    "pony diffusion": "Pony",
    "pony": "Pony",
    "pony diffusion xl": "Pony Diffusion XL",
    "illustrious": "Illustrious",
    "illustrious xl": "Illustrious XL",
    "sdxl": "SDXL 1.0",
    "sdxl 1": "SDXL 1.0",
    "sdxl 1.0": "SDXL 1.0",
    "sdxl turbo": "SDXL Turbo",
    "sdxl lightning": "SDXL Lightning",
    "sdxl refiner": "SDXL Refiner",
    "sd 1.5": "SD 1.5",
    "stable diffusion 1.5": "SD 1.5",
    "qwen": "Qwen 2D",
    "qwen 2d": "Qwen 2D",
    "qwen 2.5d": "Qwen 2.5D",
    "wan": "Wan 2.2",
    "wan 2.2": "Wan 2.2",
    "wan2.2": "Wan 2.2",
    "wan 1.3": "Wan 1.3",
    "flux 2": "Flux 2",
    "flux2": "Flux 2",
    "z-image-turbo": "Z-Image-Turbo",
    "z image turbo": "Z-Image-Turbo",
    "zimageturbo": "Z-Image-Turbo",
}


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

        self._style = ttk.Style(self.root)
        # Try to use a modern theme if available
        available_themes = self._style.theme_names()
        for preferred in ("vista", "winnative", "clam", "alt"):
            if preferred in available_themes:
                self._style.theme_use(preferred)
                break

        # Configure custom styles with better visual appearance
        self._style.configure("TFrame", background="#f5f5f5")
        self._style.configure("TLabelframe", background="#f5f5f5")
        self._style.configure("TLabelframe.Label", background="#f5f5f5", font=("Segoe UI", 9, "bold"))
        self._style.configure("TLabel", background="#f5f5f5", font=("Segoe UI", 9))
        self._style.configure("TButton", padding=(10, 5), font=("Segoe UI", 9))
        self._style.configure("TCheckbutton", background="#f5f5f5", font=("Segoe UI", 9))
        self._style.configure("TEntry", padding=(5, 3))
        self._style.configure("TCombobox", padding=(5, 3))
        
        # Download button styles
        self._style.configure("Download.TButton", padding=(12, 6), font=("Segoe UI", 10, "bold"))
        self._style.configure("Downloading.TButton", padding=(12, 6), font=("Segoe UI", 10, "bold"), foreground="white", background="#d9534f")
        self._style.map("Downloading.TButton", background=[("disabled", "#d9534f")])
        
        # Accent button style for important actions
        self._style.configure("Accent.TButton", padding=(10, 5), font=("Segoe UI", 9, "bold"))
        
        # Treeview styling
        self._style.configure("Treeview", font=("Segoe UI", 9), rowheight=24)
        self._style.configure("Treeview.Heading", font=("Segoe UI", 9, "bold"))
        
        # Recent directory button style
        self._style.configure("Recent.TButton", padding=(6, 2), font=("Segoe UI", 8))

        self._message_queue: Queue[tuple[str, str]] = Queue()
        self._selected_tags: Dict[int, str] = {}
        self._current_results: List[Dict] = []
        self.status_var = tk.StringVar(value="Ready")
        self.download_button: Optional[ttk.Button] = None
        
        # Recent directories feature
        self._recent_dirs: List[str] = []
        self._recent_dirs_frame: Optional[ttk.Frame] = None
        self._max_recent_dirs = 5
        
        # Download queue for queuing multiple downloads
        self._download_queue: List[Dict[str, str]] = []  # List of {url, output_dir}
        
        # Local server for Chrome extension
        self._local_server = LocalURLServer()
        self._local_server.set_callback(self._on_url_received)
        self._extension_enabled_var = tk.BooleanVar(value=False)

        self._build_variables()
        self._build_layout()
        self._load_settings()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(200, self._drain_messages)

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

        self.nsfw_var = tk.StringVar(value="None")
        self.period_var = tk.StringVar(value="AllTime")
        self.sort_var = tk.StringVar(value=SORT_OPTIONS[0])

        self.include_images_var = tk.BooleanVar(value=True)
        self.include_videos_var = tk.BooleanVar(value=True)
        self.include_previews_var = tk.BooleanVar(value=True)
        self.include_originals_var = tk.BooleanVar(value=True)
        self.include_workflows_var = tk.BooleanVar(value=False)
        self.save_metadata_var = tk.BooleanVar(value=True)
        self.native_images_var = tk.BooleanVar(value=True)

        self.output_dir_var = tk.StringVar(value="downloads")
        self.model_base_path_var = tk.StringVar(value="")

        self.platform_vars = {value: tk.BooleanVar(value=False) for _, value in PLATFORM_CHOICES}
        self._tag_lookup: Dict[str, int] = {}

    def _build_layout(self) -> None:
        # Header with title
        header_frame = ttk.Frame(self.root)
        header_frame.pack(fill=tk.X, padx=15, pady=(10, 5))
        title_label = ttk.Label(header_frame, text="Civitai Desktop Helper", font=("Segoe UI", 14, "bold"))
        title_label.pack(side=tk.LEFT)
        version_label = ttk.Label(header_frame, text="v1.2", font=("Segoe UI", 9))
        version_label.pack(side=tk.LEFT, padx=(8, 0), pady=(4, 0))

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
        ttk.Label(recent_container, text="Recent:", font=("Segoe UI", 8)).pack(side=tk.LEFT, padx=(0, 8))
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
        ttk.Separator(primary_tab, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=10, pady=(6, 6))
        self._build_download_section(primary_tab)
        self._build_search_tab()
        self._build_settings_tab()

        log_frame = ttk.LabelFrame(self.root, text="Activity Log")
        log_frame.pack(fill=tk.BOTH, padx=15, pady=(0, 10))
        self.log_box = scrolledtext.ScrolledText(
            log_frame, 
            height=5, 
            state=tk.DISABLED,
            font=("Consolas", 9),
            bg="#1e1e1e",
            fg="#d4d4d4",
            insertbackground="white",
            selectbackground="#264f78",
            relief=tk.FLAT,
            padx=8,
            pady=8
        )
        self.log_box.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        status_frame = ttk.Frame(self.root)
        status_frame.pack(fill=tk.X, padx=15, pady=(0, 12))
        ttk.Label(status_frame, text="Status:", font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT)
        ttk.Label(status_frame, textvariable=self.status_var, font=("Segoe UI", 9)).pack(side=tk.LEFT, padx=(6, 0))

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
        ttk.Button(search_frame, text="Search", command=self._perform_search).grid(row=0, column=4, padx=5)
        ttk.Button(search_frame, text="Clear", command=self._clear_search).grid(row=0, column=5, padx=5)
        search_frame.columnconfigure(3, weight=1)

        columns = ("col1", "col2", "col3")
        self.results_tree = ttk.Treeview(search_frame, columns=columns, show="headings", height=12)
        headings = {
            "col1": "Identifier",
            "col2": "Name",
            "col3": "Details",
        }
        for col in columns:
            self.results_tree.heading(col, text=headings.get(col, col))
            self.results_tree.column(col, width=220)
        self.results_tree.grid(row=1, column=0, columnspan=6, sticky="nsew", pady=8)
        search_frame.rowconfigure(1, weight=1)

        btn_frame = ttk.Frame(search_frame)
        btn_frame.grid(row=2, column=0, columnspan=6, sticky="e", pady=5)
        ttk.Label(btn_frame, text="Apply sets the IDs/filters only; downloads start on the Download tab.").pack(side=tk.LEFT)
        self.apply_selection_button = ttk.Button(btn_frame, text="Apply to Filters", command=self._apply_selection)
        self.apply_selection_button.pack(side=tk.RIGHT, padx=5)

    def _build_filters_section(self, parent: ttk.Frame) -> None:
        url_frame = ttk.LabelFrame(parent, text="Quick Start - Paste a Civitai URL")
        url_frame.pack(fill=tk.X, padx=5, pady=(3, 5))
        
        # URL entry with placeholder-like hint
        url_entry = ttk.Entry(url_frame, textvariable=self.url_var, font=("Segoe UI", 10))
        url_entry.grid(row=0, column=0, padx=6, pady=6, sticky="we")
        
        # Button container for better grouping
        btn_container = ttk.Frame(url_frame)
        btn_container.grid(row=0, column=1, padx=(0, 6), pady=6)
        
        ttk.Button(btn_container, text="Resolve", command=self._resolve_url, style="Accent.TButton").pack(side=tk.LEFT, padx=2)
        self.download_button = ttk.Button(btn_container, text="⬇ Download", style="Download.TButton", command=self._start_download)
        self.download_button.pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_container, text="Clear", command=self._clear_filters).pack(side=tk.LEFT, padx=2)
        
        url_frame.columnconfigure(0, weight=1)
        
        hint_label = ttk.Label(
            url_frame, 
            text="💡 Just paste a URL and click Download - auto-resolves!",
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
            ).grid(row=row, column=col, padx=2, pady=1, sticky="w")

        footer_row = (len(PLATFORM_CHOICES) + columns - 1) // columns
        ttk.Label(platform_frame, text="Custom:").grid(row=footer_row, column=0, sticky="w", padx=2)
        ttk.Entry(platform_frame, textvariable=self.base_models_var).grid(row=footer_row, column=1, columnspan=columns - 1, sticky="we", padx=2)
        for col in range(columns):
            platform_frame.columnconfigure(col, weight=1 if col == 1 else 0)

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
        ttk.Label(options_frame, text="NSFW:").grid(row=0, column=0, sticky="w", padx=2)
        ttk.Combobox(options_frame, textvariable=self.nsfw_var, values=["None", "Soft", "Mature", "X"], state="readonly", width=8).grid(row=0, column=1, padx=2)
        ttk.Label(options_frame, text="Period:").grid(row=0, column=2, sticky="w", padx=2)
        ttk.Combobox(options_frame, textvariable=self.period_var, values=["AllTime", "Year", "Month", "Week", "Day"], state="readonly", width=8).grid(row=0, column=3, padx=2)
        ttk.Label(options_frame, text="Sort:").grid(row=0, column=4, sticky="w", padx=2)
        ttk.Combobox(options_frame, textvariable=self.sort_var, values=SORT_OPTIONS, state="readonly", width=14).grid(row=0, column=5, padx=2)
        ttk.Checkbutton(options_frame, text="Images", variable=self.include_images_var).grid(row=0, column=6, sticky="w", padx=4)
        ttk.Checkbutton(options_frame, text="Videos", variable=self.include_videos_var).grid(row=0, column=7, sticky="w", padx=4)

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
        self.tag_results_tree = ttk.Treeview(tag_lists_frame, columns=tag_columns, show="headings", height=4)
        self.tag_results_tree.heading("name", text="Search Results")
        self.tag_results_tree.heading("models", text="#")
        self.tag_results_tree.column("name", width=180)
        self.tag_results_tree.column("models", width=40)
        self.tag_results_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 4))

        # Active tags (right)
        self.active_tags_tree = ttk.Treeview(tag_lists_frame, columns=("tag",), show="headings", height=4)
        self.active_tags_tree.heading("tag", text="Active Tags")
        self.active_tags_tree.column("tag", width=200)
        self.active_tags_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

    def _build_download_section(self, parent: ttk.Frame) -> None:
        options_frame = ttk.LabelFrame(parent, text="Download options")
        options_frame.pack(fill=tk.X, padx=5, pady=3)
        ttk.Checkbutton(options_frame, text="Previews", variable=self.include_previews_var).grid(row=0, column=0, sticky="w", padx=3, pady=2)
        ttk.Checkbutton(options_frame, text="Originals", variable=self.include_originals_var).grid(row=0, column=1, sticky="w", padx=3, pady=2)
        ttk.Checkbutton(options_frame, text="Workflows", variable=self.include_workflows_var).grid(row=0, column=2, sticky="w", padx=3, pady=2)
        ttk.Checkbutton(options_frame, text="Videos", variable=self.include_videos_var).grid(row=0, column=3, sticky="w", padx=3, pady=2)
        ttk.Checkbutton(options_frame, text="Metadata", variable=self.save_metadata_var).grid(row=0, column=4, sticky="w", padx=3, pady=2)
        ttk.Checkbutton(options_frame, text="Native size", variable=self.native_images_var).grid(row=0, column=5, sticky="w", padx=3, pady=2)

        # Download button now lives next to the URL entry for quicker access.

    def _build_settings_tab(self) -> None:
        """Build the Settings tab with API key and path configurations."""
        
        # API Key section
        api_frame = ttk.LabelFrame(self.settings_tab, text="Civitai API Key")
        api_frame.pack(fill=tk.X, padx=10, pady=(10, 15))
        
        ttk.Label(
            api_frame, 
            text="Your API key is used to access the Civitai API. Get one from civitai.com/user/account",
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
        """Show a popup for quick download with location selection."""
        popup = tk.Toplevel(self.root)
        popup.title("Quick Download")
        popup.geometry("550x420")
        popup.resizable(False, False)
        popup.transient(self.root)
        popup.grab_set()
        
        # Center on screen
        popup.update_idletasks()
        x = (popup.winfo_screenwidth() - 550) // 2
        y = (popup.winfo_screenheight() - 420) // 2
        popup.geometry(f"550x420+{x}+{y}")
        
        # Make it topmost
        popup.attributes('-topmost', True)
        popup.focus_force()
        
        # URL display
        url_frame = ttk.LabelFrame(popup, text="URL from Civitai")
        url_frame.pack(fill=tk.X, padx=15, pady=(15, 8))
        
        # Truncate URL for display
        display_url = url if len(url) < 65 else url[:62] + "..."
        ttk.Label(url_frame, text=display_url, font=("Segoe UI", 9), foreground="#0066cc").pack(padx=10, pady=6)
        
        # Location selection
        location_frame = ttk.LabelFrame(popup, text="Download Location")
        location_frame.pack(fill=tk.BOTH, expand=True, padx=15, pady=8)
        
        selected_dir = tk.StringVar(value=self.output_dir_var.get())
        
        # Current location
        current_frame = ttk.Frame(location_frame)
        current_frame.pack(fill=tk.X, padx=10, pady=(8, 5))
        ttk.Label(current_frame, text="Save to:").pack(side=tk.LEFT)
        location_entry = ttk.Entry(current_frame, textvariable=selected_dir, width=45)
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
        
        ttk.Button(current_frame, text="Browse", command=browse_location).pack(side=tk.LEFT)
        
        # Recent directories as buttons in a 2-column grid
        if self._recent_dirs:
            ttk.Label(location_frame, text="Recent locations (click to select):", font=("Segoe UI", 8)).pack(anchor="w", padx=10, pady=(8, 4))
            
            recent_frame = ttk.Frame(location_frame)
            recent_frame.pack(fill=tk.X, padx=10, pady=(0, 8))
            
            # Configure 2 columns
            recent_frame.columnconfigure(0, weight=1)
            recent_frame.columnconfigure(1, weight=1)
            
            for idx, dir_path in enumerate(self._recent_dirs[:6]):  # Show up to 6 recent dirs
                short_name = self._get_short_dir_name(dir_path)
                # Truncate if too long
                if len(short_name) > 28:
                    short_name = "..." + short_name[-25:]
                
                row = idx // 2
                col = idx % 2
                
                btn = ttk.Button(
                    recent_frame,
                    text=f"📁 {short_name}",
                    command=lambda d=dir_path: selected_dir.set(d)
                )
                btn.grid(row=row, column=col, sticky="ew", padx=2, pady=2)
                # Tooltip with full path
                self._add_tooltip(btn, dir_path)
        
        # Buttons at bottom - fixed position
        btn_frame = ttk.Frame(popup)
        btn_frame.pack(fill=tk.X, padx=15, pady=(8, 15), side=tk.BOTTOM)
        
        def do_download():
            # Update output directory
            self.output_dir_var.set(selected_dir.get())
            self._add_recent_dir(selected_dir.get())
            # Close popup
            popup.destroy()
            # Start download (will queue if busy)
            self._start_download()
        
        def cancel():
            popup.destroy()
        
        ttk.Button(btn_frame, text="Cancel", command=cancel).pack(side=tk.LEFT, padx=5)
        download_btn = ttk.Button(btn_frame, text="⬇ Download Now", style="Download.TButton", command=do_download)
        download_btn.pack(side=tk.RIGHT, padx=5)
        
        # Bind Enter key to download
        popup.bind('<Return>', lambda e: do_download())
        # Bind Escape to cancel
        popup.bind('<Escape>', lambda e: cancel())
        
        # Focus the download button
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
        
        # Create a button for each recent directory
        for idx, dir_path in enumerate(self._recent_dirs):
            # Get a short display name (last folder name or drive)
            display_name = self._get_short_dir_name(dir_path)
            btn = ttk.Button(
                self._recent_dirs_frame,
                text=f"📁 {display_name}",
                command=lambda d=dir_path: self._select_recent_dir(d),
                style="Recent.TButton"
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
                messagebox.showinfo("Resolve", "Enter a Civitai URL first.")
            return False
        
        self.status_var.set("Resolving URL…")
        entity = None
        last_error = None
        
        for attempt in range(1, max_retries + 1):
            try:
                entity = resolve_url(url, self.client)
                if entity:
                    break
            except ApiError as exc:
                last_error = exc
                if attempt < max_retries:
                    self._queue_log(f"Resolve attempt {attempt} failed, retrying...")
                    import time
                    time.sleep(0.5)  # Brief pause before retry
                continue
            except Exception as exc:
                last_error = exc
                if attempt < max_retries:
                    self._queue_log(f"Resolve attempt {attempt} failed, retrying...")
                    import time
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
        if entity.extra.get("username"):
            self.username_var.set(entity.extra["username"])
        self._queue_log(f"Resolved {entity.entity_type}: {entity.identifier}")
        return True

    def _perform_search(self) -> None:
        query = self.search_query_var.get().strip()
        category = self.search_type_var.get()
        self.status_var.set("Searching…")
        try:
            if category == "models":
                payload = self.client.search_models(query=query, username=self.username_var.get().strip() or "", base_models=self._collect_base_models())
                items = payload.get("items", [])
                display = [(item.get("id"), item.get("name"), item.get("type")) for item in items]
            elif category == "images":
                items, _ = self.client.search_images(limit=50, username=self.username_var.get().strip() or "", model_id=self._safe_int(self.model_id_var.get()), model_version_id=self._safe_int(self.version_id_var.get()), nsfw=self.nsfw_var.get() if self.nsfw_var.get() != "None" else "", types=self._selected_media_types(), base_models=self._collect_base_models())
                display = [(item.get("id"), item.get("modelName"), item.get("type")) for item in items]
            elif category == "creators":
                payload = self.client.search_creators(query=query or self.username_var.get().strip())
                items = payload.get("items", [])
                display = [(entry.get("username"), entry.get("modelCount"), "Creator") for entry in items]
            else:
                payload = self.client.search_tags(query=query)
                items = payload.get("items", [])
                display = [(entry.get("id"), entry.get("name"), entry.get("modelCount")) for entry in items]
        except ApiError as exc:
            messagebox.showerror("Search failed", str(exc))
            return
        finally:
            self.status_var.set("Ready")

        for row in self.results_tree.get_children():
            self.results_tree.delete(row)
        self._current_results = items

        for entry in display:
            values = tuple(value if value is not None else "" for value in entry)
            self.results_tree.insert("", tk.END, values=values)

        self._queue_log(f"Search returned {len(items)} items.")

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
            tag_id = item.get("id")
            name = item.get("name")
            if tag_id and name:
                self._selected_tags[int(tag_id)] = name
                self._refresh_active_tags()
            self._queue_log(f"Tag {name} queued for filtering.")

    def _search_tags(self) -> None:
        query = self.tag_query_var.get().strip()
        self.status_var.set("Searching tags…")
        try:
            payload = self.client.search_tags(query=query)
        except ApiError as exc:
            messagebox.showerror("Tag search failed", str(exc))
            return
        finally:
            self.status_var.set("Ready")
        self._tag_lookup.clear()
        for row in self.tag_results_tree.get_children():
            self.tag_results_tree.delete(row)
        for item in payload.get("items", []):
            tag_id = item.get("id")
            try:
                tag_int = int(tag_id)
            except (TypeError, ValueError):
                continue
            iid = str(tag_int)
            self._tag_lookup[iid] = tag_int
            self.tag_results_tree.insert("", tk.END, values=(item.get("name"), item.get("modelCount")), iid=iid)
        self._queue_log(f"Loaded {len(payload.get('items', []))} tags.")

    def _add_selected_tag(self) -> None:
        selection = self.tag_results_tree.selection()
        if not selection:
            return
        for iid in selection:
            tag_id = self._tag_lookup.get(iid)
            if tag_id is None:
                continue
            name = self.tag_results_tree.item(iid, "values")[0]
            self._selected_tags[tag_id] = name
        self._refresh_active_tags()

    def _remove_selected_tag(self) -> None:
        selection = self.active_tags_tree.selection()
        if not selection:
            return
        for iid in selection:
            try:
                tag_id = int(iid)
            except ValueError:
                continue
            self._selected_tags.pop(tag_id, None)
        self._refresh_active_tags()

    def _refresh_active_tags(self) -> None:
        for row in self.active_tags_tree.get_children():
            self.active_tags_tree.delete(row)
        for tag_id, name in sorted(self._selected_tags.items()):
            self.active_tags_tree.insert("", tk.END, values=(f"{tag_id} – {name}",), iid=str(tag_id))

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
        return combined

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
        
        self._apply_ui_to_state()
        self._update_queue_status()
        if self.download_button is not None:
            self.download_button.config(text="Downloading…", style="Downloading.TButton", state=tk.DISABLED)
        self._queue_log("Starting download run...")
        self._download_thread = threading.Thread(target=self._run_download_worker, daemon=True)
        self._download_thread.start()
    
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
        self.state.filters.tag_ids = list(self._selected_tags.keys())
        self.state.filters.nsfw = self.nsfw_var.get()
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
        )
        self.state.downloads = downloads

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

    def _drain_messages(self) -> None:
        flushed = False
        while True:
            try:
                kind, payload = self._message_queue.get_nowait()
            except Empty:
                break
            if kind == "log":
                self.log_box.configure(state=tk.NORMAL)
                self.log_box.insert(tk.END, payload + "\n")
                self.log_box.see(tk.END)
                self.log_box.configure(state=tk.DISABLED)
                flushed = True
            elif kind == "status":
                self.status_var.set(payload)
            elif kind == "action":
                self._handle_action(payload)
        if flushed:
            self.log_box.update_idletasks()
        self.root.after(200, self._drain_messages)

    def _handle_action(self, payload: Any) -> None:
        if isinstance(payload, tuple):
            action, data = payload
        else:
            action, data = payload, None

        if action == "download_finished" and self.download_button is not None:
            self.download_button.config(text="⬇ Download", style="Download.TButton", state=tk.NORMAL)
            if data and not data.get("success", True):
                self.status_var.set("Download failed")
            else:
                # Process next item in queue if any
                self._process_next_in_queue()
        
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
        self.username_var.set(data.get("username", ""))
        self.model_id_var.set(str(data.get("model_id", "")) if data.get("model_id") else "")
        self.version_id_var.set(str(data.get("version_id", "")) if data.get("version_id") else "")
        self.nsfw_var.set(data.get("nsfw", "None"))
        self.period_var.set(data.get("period", "AllTime"))
        saved_sort = data.get("sort", SORT_OPTIONS[0])
        if saved_sort not in SORT_OPTIONS:
            saved_sort = SORT_OPTIONS[0]
        self.sort_var.set(saved_sort)
        self.output_dir_var.set(data.get("output", "downloads"))
        self.model_base_path_var.set(data.get("model_base_path", ""))
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
            self._selected_tags = {int(k): v for k, v in tag_map.items()}
            self._refresh_active_tags()
        # Load recent directories
        recent = data.get("recent_dirs", [])
        if isinstance(recent, list):
            self._recent_dirs = [d for d in recent if isinstance(d, str)][:self._max_recent_dirs]
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
            "username": self.username_var.get().strip(),
            "model_id": self.model_id_var.get().strip(),
            "version_id": self.version_id_var.get().strip(),
            "nsfw": self.nsfw_var.get(),
            "period": self.period_var.get(),
            "sort": self.sort_var.get(),
            "output": self.output_dir_var.get().strip(),
            "model_base_path": self.model_base_path_var.get().strip(),
            "max_items": self.max_items_var.get().strip(),
            "base_models": self._collect_base_models(),
            "tags": {str(k): v for k, v in self._selected_tags.items()},
            "recent_dirs": self._recent_dirs,
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
