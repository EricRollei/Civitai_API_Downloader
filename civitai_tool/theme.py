"""Central visual theme for the Civitai Desktop Helper GUI.

Single source of truth for the colour palette, fonts, and ttk widget styling.
Built on Tk's ``clam`` theme, which (unlike the native Windows ``vista`` theme)
honours ``background``/``foreground`` colour settings, so the accent colour and
semantic button colours actually render.
"""
from __future__ import annotations

import re
from tkinter import ttk

# --- Colour palette ---------------------------------------------------------
# A light theme built around a single Civitai-style blue accent plus a small
# set of semantic colours (success / danger / warning / muted).
PALETTE = {
    "bg":            "#f3f5f8",   # window / frame background
    "surface":       "#ffffff",   # entry, treeview field, input backgrounds
    "surface_alt":   "#eef2f7",   # zebra stripe / hover / subtle panels
    "border":        "#d4dae2",   # widget borders / separators
    "border_strong": "#b9c2cd",

    "text":          "#1f2933",   # primary text
    "text_muted":    "#66727f",   # hints, secondary labels
    "text_inverse":  "#ffffff",   # text on coloured buttons

    "accent":        "#1971c2",   # primary accent (links, headings, buttons)
    "accent_hover":  "#1864ab",
    "accent_active": "#15598f",
    "accent_soft":   "#e7f1fb",   # tinted background (tooltips, highlights)

    "success":       "#2f9e44",
    "success_hover": "#2b8a3e",
    "danger":        "#e03131",
    "danger_hover":  "#c92a2a",
    "warning":       "#e8830c",

    "select_bg":     "#d0ebff",   # treeview / selection background
    "select_fg":     "#0b3d66",

    "log_bg":        "#1e1e1e",   # activity log (dark console)
    "log_fg":        "#d4d4d4",
}

# --- Fonts ------------------------------------------------------------------
FONT_FAMILY = "Segoe UI"
FONTS = {
    "base":    (FONT_FAMILY, 9),
    "bold":    (FONT_FAMILY, 9, "bold"),
    "small":   (FONT_FAMILY, 8),
    "section": (FONT_FAMILY, 9, "bold"),
    "title":   (FONT_FAMILY, 15, "bold"),
    "subtitle":(FONT_FAMILY, 9),
    "button":  (FONT_FAMILY, 9),
    "button_bold": (FONT_FAMILY, 9, "bold"),
    "download": (FONT_FAMILY, 10, "bold"),
    "mono":    ("Consolas", 9),
}


def apply_theme(root) -> ttk.Style:
    """Apply the custom light theme to *root* and return the configured Style."""
    p = PALETTE
    style = ttk.Style(root)

    # clam is the most themable built-in engine and is always available.
    if "clam" in style.theme_names():
        style.theme_use("clam")

    root.configure(background=p["bg"])
    # Fallback palette for classic (non-ttk) widgets such as menus/toplevels.
    try:
        root.tk_setPalette(background=p["bg"], foreground=p["text"])
    except Exception:
        pass

    # --- Containers ---------------------------------------------------------
    style.configure("TFrame", background=p["bg"])
    style.configure("TLabel", background=p["bg"], foreground=p["text"], font=FONTS["base"])
    style.configure("TSeparator", background=p["border"])

    style.configure(
        "TLabelframe",
        background=p["bg"],
        bordercolor=p["border"],
        relief="solid",
        borderwidth=1,
    )
    # Section headers (kept neutral/black to avoid visual noise).
    style.configure(
        "TLabelframe.Label",
        background=p["bg"],
        foreground=p["text"],
        font=FONTS["section"],
    )

    # --- Header labels ------------------------------------------------------
    style.configure("Title.TLabel", background=p["bg"], foreground=p["text"], font=FONTS["title"])
    style.configure("Version.TLabel", background=p["bg"], foreground=p["text_muted"], font=FONTS["subtitle"])
    style.configure("Muted.TLabel", background=p["bg"], foreground=p["text_muted"], font=FONTS["small"])
    style.configure("Hint.TLabel", background=p["bg"], foreground=p["text_muted"], font=FONTS["small"])
    style.configure("Link.TLabel", background=p["bg"], foreground=p["accent"], font=FONTS["base"])

    # --- Buttons ------------------------------------------------------------
    # Default button: light surface with a subtle border and accent-tinted hover.
    style.configure(
        "TButton",
        background=p["surface"],
        foreground=p["text"],
        bordercolor=p["border_strong"],
        focuscolor=p["accent"],
        relief="solid",
        borderwidth=1,
        padding=(10, 5),
        font=FONTS["button"],
    )
    style.map(
        "TButton",
        background=[("pressed", p["surface_alt"]), ("active", p["accent_soft"]), ("disabled", p["surface_alt"])],
        foreground=[("disabled", p["text_muted"])],
        bordercolor=[("active", p["accent"]), ("focus", p["accent"])],
    )

    def _solid_button(name: str, base: str, hover: str, active: str,
                      fg: str = p["text_inverse"], font=FONTS["button_bold"], padding=(10, 5)):
        style.configure(
            name, background=base, foreground=fg, bordercolor=base,
            focuscolor=fg, relief="flat", borderwidth=1, padding=padding, font=font,
        )
        style.map(
            name,
            background=[("pressed", active), ("active", hover), ("disabled", base)],
            foreground=[("disabled", p["text_inverse"])],
            bordercolor=[("active", hover), ("pressed", active)],
        )

    # Accent (primary) actions, e.g. Resolve / Apply.
    _solid_button("Accent.TButton", p["accent"], p["accent_hover"], p["accent_active"])
    # Download button: green when ready, red while downloading.
    _solid_button("Download.TButton", p["success"], p["success_hover"], p["success_hover"],
                  font=FONTS["download"], padding=(12, 6))
    _solid_button("Downloading.TButton", p["danger"], p["danger_hover"], p["danger_hover"],
                  font=FONTS["download"], padding=(12, 6))

    # Compact button for recent-directory chips.
    style.configure(
        "Recent.TButton",
        background=p["surface"],
        foreground=p["text"],
        bordercolor=p["border"],
        relief="solid",
        borderwidth=1,
        padding=(8, 3),
        font=FONTS["small"],
    )
    style.map(
        "Recent.TButton",
        background=[("active", p["surface_alt"]), ("pressed", p["surface_alt"])],
        bordercolor=[("active", p["border_strong"])],
    )

    # Larger left-aligned chip used for recent-location buttons in the
    # Quick Download popup (coloured variants are derived from this).
    style.configure(
        "Quick.TButton",
        background=p["surface"],
        foreground=p["text"],
        bordercolor=p["border_strong"],
        relief="solid",
        borderwidth=1,
        padding=(10, 8),
        anchor="w",
        font=FONTS["base"],
    )
    style.map(
        "Quick.TButton",
        background=[("active", p["surface_alt"]), ("pressed", p["surface_alt"])],
        bordercolor=[("active", p["border_strong"])],
    )

    # --- Entries & combobox -------------------------------------------------
    style.configure(
        "TEntry",
        fieldbackground=p["surface"],
        foreground=p["text"],
        bordercolor=p["border_strong"],
        lightcolor=p["border_strong"],
        darkcolor=p["border_strong"],
        insertcolor=p["text"],
        relief="solid",
        borderwidth=1,
        padding=(6, 4),
    )
    style.map(
        "TEntry",
        bordercolor=[("focus", p["accent"])],
        lightcolor=[("focus", p["accent"])],
        darkcolor=[("focus", p["accent"])],
    )

    style.configure(
        "TCombobox",
        fieldbackground=p["surface"],
        background=p["surface"],
        foreground=p["text"],
        bordercolor=p["border_strong"],
        arrowcolor=p["accent"],
        relief="solid",
        borderwidth=1,
        padding=(6, 4),
    )
    style.map(
        "TCombobox",
        fieldbackground=[("readonly", p["surface"]), ("disabled", p["surface_alt"])],
        bordercolor=[("focus", p["accent"]), ("active", p["accent"])],
        arrowcolor=[("active", p["accent_hover"])],
    )

    # --- Checkbuttons -------------------------------------------------------
    style.configure(
        "TCheckbutton",
        background=p["bg"],
        foreground=p["text"],
        focuscolor=p["accent"],
        font=FONTS["base"],
    )
    style.map(
        "TCheckbutton",
        foreground=[("disabled", p["text_muted"])],
        indicatorcolor=[("selected", p["accent"]), ("!selected", p["surface"])],
        background=[("active", p["bg"])],
    )

    # --- Notebook (tabs) ----------------------------------------------------
    style.configure("TNotebook", background=p["bg"], bordercolor=p["border"], tabmargins=(2, 4, 2, 0))
    style.configure(
        "TNotebook.Tab",
        background=p["surface_alt"],
        foreground=p["text_muted"],
        bordercolor=p["border"],
        padding=(16, 7),
        font=FONTS["bold"],
    )
    style.map(
        "TNotebook.Tab",
        background=[("selected", p["surface"]), ("active", p["accent_soft"])],
        foreground=[("selected", p["accent"]), ("active", p["accent_hover"])],
    )

    # --- Treeview -----------------------------------------------------------
    style.configure(
        "Treeview",
        background=p["surface"],
        fieldbackground=p["surface"],
        foreground=p["text"],
        bordercolor=p["border"],
        relief="solid",
        borderwidth=1,
        rowheight=25,
        font=FONTS["base"],
    )
    style.map(
        "Treeview",
        background=[("selected", p["select_bg"])],
        foreground=[("selected", p["select_fg"])],
    )
    style.configure(
        "Treeview.Heading",
        background=p["surface_alt"],
        foreground=p["text"],
        bordercolor=p["border"],
        relief="flat",
        padding=(6, 4),
        font=FONTS["bold"],
    )
    style.map(
        "Treeview.Heading",
        background=[("active", p["accent_soft"])],
        foreground=[("active", p["accent_hover"])],
    )

    # --- Progressbar --------------------------------------------------------
    style.configure(
        "Accent.Horizontal.TProgressbar",
        background=p["accent"],
        troughcolor=p["surface_alt"],
        bordercolor=p["border"],
        lightcolor=p["accent"],
        darkcolor=p["accent"],
    )

    # --- Scrollbars ---------------------------------------------------------
    for sb in ("Vertical.TScrollbar", "Horizontal.TScrollbar"):
        style.configure(
            sb,
            background=p["surface_alt"],
            troughcolor=p["bg"],
            bordercolor=p["bg"],
            arrowcolor=p["text_muted"],
            relief="flat",
        )
        style.map(
            sb,
            background=[("active", p["border_strong"]), ("pressed", p["accent"])],
            arrowcolor=[("active", p["accent"])],
        )

    return style


def configure_treeview_tags(tree) -> None:
    """Apply zebra-striping row tags to a Treeview."""
    tree.tag_configure("oddrow", background=PALETTE["surface"])
    tree.tag_configure("evenrow", background=PALETTE["surface_alt"])


def row_tag(index: int) -> str:
    """Return the zebra tag ('oddrow'/'evenrow') for a 0-based row index."""
    return "evenrow" if index % 2 else "oddrow"


# ---------------------------------------------------------------------------
# Colour coding for folder categories and model platforms
# ---------------------------------------------------------------------------
# Each list is checked in order; the first keyword that appears anywhere in the
# (separator-stripped, lowercased) text wins. More specific keywords therefore
# come before more generic ones (e.g. "sdxl" before "sd", "photostyle" before
# "photo"). Colours are saturated enough to read as text on a light tint and
# are also used for the small platform swatch and chip borders.

# Folder-category colours (keyword, colour, display label). Checked in order,
# so more specific keywords come before generic ones. Covers the common Civitai
# organisation folders (and a couple of real-world spellings like "ptotostyle").
CATEGORY_COLORS = [
    ("ptotostyle",      "#0b8aaa", "photostyle"),     # real-world spelling
    ("photostyle",      "#0b8aaa", "photostyle"),    # cyan
    ("graphicdesign",   "#4c6ef5", "graphic-design"),# blue
    ("graphicart",      "#6741d9", "graphic-art"),    # violet
    ("character",       "#099268", "character"),      # teal
    ("illustration",    "#1c7ed6", "illustration"),   # sky blue
    ("artstyle",        "#3b5bdb", "art-style"),       # indigo
    ("lightingeffects", "#a07400", "lighting"),        # gold
    ("lightning",       "#a07400", "lighting"),        # real-world spelling
    ("lighting",        "#a07400", "lighting"),
    ("environment",     "#2b8a3e", "environment"),     # green
    ("treatment",       "#d9480f", "treatment"),       # orange
    ("surreal",         "#9c36b5", "surreal"),         # magenta
    ("comic",           "#e8590c", "comic"),           # amber
    ("clothing",        "#c2255c", "clothing"),        # pink
    ("nsfw",            "#c92a2a", "nsfw"),             # red
    ("portrait",        "#a61e4d", "portrait"),         # deep rose
    ("objects",         "#6741d9", "objects"),          # violet
    ("paint",           "#b5330f", "paint"),            # burnt orange
    ("controlnet",      "#0b7285", "controlnet"),       # dark cyan
    ("control",         "#0b7285", "control"),
    ("bodyhelper",      "#495057", "body-helpers"),     # slate
    ("lowvram",         "#5c636a", "low-vram"),         # grey
    ("photo",           "#0b8aaa", "photo"),            # cyan
    ("edit",            "#5c636a", "edit"),             # grey
    ("helper",          "#495057", "helpers"),          # slate
    ("user",            "#495057", "users"),            # slate
    ("style",           "#3b5bdb", "style"),            # generic fallback
]

# Model-platform colours (keyword, colour, display label).
PLATFORM_COLORS = [
    ("illustrious", "#f76707", "Illustrious"),  # orange
    ("zimage",      "#f03e3e", "Z-Image"),      # red
    ("flux",        "#1864ab", "Flux"),         # deep blue
    ("krea",        "#d6336c", "Krea"),         # rose
    ("qwen",        "#5f3dc4", "Qwen"),         # deep indigo
    ("pony",        "#9c36b5", "Pony"),         # purple
    ("sdxl",        "#1098ad", "SDXL"),         # cyan
    ("wan",         "#0ca678", "Wan"),          # teal
    ("sd",          "#868e96", "SD"),           # grey
]


def _norm(text: str) -> str:
    """Lowercase and strip everything but letters/digits for keyword matching."""
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def _match(text: str, table):
    n = _norm(text)
    for keyword, color, label in table:
        if keyword in n:
            return color, label
    return None, None


def category_color(text: str):
    """Return a hex colour for a folder category keyword found in *text*, or None."""
    return _match(text, CATEGORY_COLORS)[0]


def category_label(text: str):
    """Return the display label for a folder category keyword in *text*, or None."""
    return _match(text, CATEGORY_COLORS)[1]


def platform_color(text: str):
    """Return a hex colour for a model-platform keyword found in *text*, or None."""
    return _match(text, PLATFORM_COLORS)[0]


def platform_label(text: str):
    """Return the display label for a model-platform keyword in *text*, or None."""
    return _match(text, PLATFORM_COLORS)[1]

