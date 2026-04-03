# Civitai Desktop Helper

A Windows desktop application for browsing and downloading models, LoRAs, and preview media from [Civitai](https://civitai.com), with an optional Chrome extension for one-click URL sending from any Civitai page.

---

## Features

- **GUI download tool** — Tkinter-based desktop app with tabs for images, gallery, models, and settings.
- **Model + version downloads** — Downloads `.safetensors` / checkpoint files into an organized folder structure (`modelId-modelName/versionId-versionName/`).
- **Preview media** — Optionally downloads showcase images and videos alongside the model files.
- **Gallery browser** — Fetches community gallery images for a model, filterable by base model, NSFW level, period, tags, and sort order.
- **URL resolver** — Paste any Civitai URL (model, version, post, user) and the tool resolves the correct IDs automatically.
- **Chrome extension** — A browser extension that sends the current Civitai page URL to the desktop app with a single click or keyboard shortcut (`Alt+Shift+C`).
- **Local server** — Lightweight HTTP server (port 7865) that receives URLs from the Chrome extension.
- **Metadata saving** — Optionally saves a `.json` sidecar file alongside each downloaded asset with full API metadata.

---

## Requirements

- Python 3.10+
- Windows (uses Tkinter; should work on macOS/Linux with a Tkinter-capable Python build)
- A [Civitai API key](https://civitai.com/user/account) (free account required for NSFW content)

---

## Installation

### Quick start (Windows)

```bat
start.bat
```

`start.bat` will:
1. Create a Python virtual environment (`venv/`) if one does not exist.
2. Install dependencies from `requirements.txt`.
3. Launch the app.

### Manual setup

```bash
python -m venv venv
venv\Scripts\activate        # Windows
pip install -r requirements.txt
python Civitai_Image_API.py
```

---

## Configuration

On first run the app creates `civitai_tool/settings.json` automatically.  
You can also copy the provided example and fill it in before running:

```bash
copy civitai_tool\settings.example.json civitai_tool\settings.json
```

Then open `civitai_tool/settings.json` and set at minimum:

| Key | Description |
|-----|-------------|
| `api_key` | Your Civitai API key |
| `output` | Default download directory |
| `model_base_path` | Root folder used when organizing model sub-folders |

**Never commit `settings.json`** — it is excluded by `.gitignore` because it contains your personal API key and local paths.

---

## Chrome Extension

The `chrome_extension/` folder contains a Manifest V3 extension that adds a button to your browser toolbar.

### Installation

1. Open Chrome and go to `chrome://extensions/`
2. Enable **Developer mode** (top-right toggle).
3. Click **Load unpacked** and select the `chrome_extension/` folder.
4. Make sure the desktop app is running (the local server must be active).

### Usage

- Click the toolbar icon on any Civitai page, or press **Alt+Shift+C**.
- The current URL is sent to the desktop app, which auto-populates the URL field and resolves model/version IDs.

> The extension requires the desktop app's local server to be running (enabled by default via the **Extension Server** toggle in the Settings tab).

### Generating extension icons

If the PNG icons are missing, run:

```bash
python chrome_extension/create_icons.py
```

---

## Project Structure

```
Civitai_API_tool/
├── Civitai_Image_API.py          # Entry point
├── start.bat                     # Windows launcher
├── requirements.txt
├── settings.example.json         # Template — copy to settings.json
│
├── civitai_tool/
│   ├── gui.py                    # Tkinter GUI (tabs, controls, log)
│   ├── api_client.py             # Civitai REST API wrapper
│   ├── downloads.py              # Download orchestration & file naming
│   ├── url_resolver.py           # Parses Civitai URLs → model/version IDs
│   ├── local_server.py           # HTTP server for Chrome extension
│   ├── state.py                  # Shared app state & settings dataclasses
│   ├── settings.example.json     # Template — copy to settings.json
│   └── __init__.py
│
└── chrome_extension/
    ├── manifest.json
    ├── popup.html
    ├── popup.js
    ├── background.js
    └── create_icons.py           # Generates icon PNGs (requires Pillow)
```

---

## Folder Layout for Downloads

Downloaded files are organized automatically:

```
<output>/
└── <modelId>-<modelName>/
    └── <versionId>-<versionName>/
        ├── mymodel.safetensors
        ├── mymodel.safetensors.json   # sidecar metadata (if enabled)
        ├── images/
        └── videos/
```

---

## Using the App

The app has three tabs: **Filters & Download**, **Search**, and **Settings**.

---

### Filters & Download tab

This is the main working tab. Set your filters here and click **⬇ Download**.

#### Quick Start — Paste a Civitai URL

The fastest way to download anything. Paste a Civitai URL (model page, version page, post, or user profile) and click **⬇ Download**. The app auto-resolves the URL to model/version IDs before downloading. You can also click **Resolve** first to preview what was detected without starting the download.

#### Platforms

Checkboxes for common base models (Flux, SDXL, Pony, SD 1.5, etc.). Checked platforms are used as a `baseModel` filter when searching images by username. Use the **Custom** field for any base model not listed.

#### Model and user filters

| Field | What it does |
|---|---|
| **Username** | Download all images/models from this Civitai user |
| **Model ID** | Target a specific model by its numeric ID |
| **Version ID** | Target a specific model version |
| **Max items** | Cap the number of results fetched (0 = unlimited) |

#### Result options

| Option | What it does |
|---|---|
| **NSFW** | Filter by content rating: None, Soft, Mature, or X |
| **Period** | Time window for sorting: AllTime, Year, Month, Week, Day |
| **Sort** | Sort order: Most Reactions, Most Comments, Newest, etc. |
| **Images / Videos** | Toggle whether image or video type results are included |

#### Download options

Controls what gets saved alongside each downloaded model file:

| Option | What it does |
|---|---|
| **Previews** | Download showcase preview images |
| **Originals** | Download the original full-resolution images |
| **Workflows** | Download ComfyUI workflow JSON files if present |
| **Videos** | Download video previews |
| **Metadata** | Save a `.json` sidecar file with full API metadata |
| **Native size** | Download images at their original resolution rather than a scaled version |

#### Tags

Tags let you narrow image downloads to content matching specific Civitai tags (e.g. `portrait`, `woman`, `sci-fi`).

1. Type a keyword in the **Search** box and click **Search** — matching tags appear in the left list with a count of how many models use each tag.
2. Select a tag in the left list and click **+ Add** — it moves to the **Active Tags** list on the right.
3. Add as many tags as needed. When you click **⬇ Download**, only content tagged with those active tags will be fetched.
4. To remove a tag, select it in the **Active Tags** list and click **- Remove**.

> **Note:** Tags filter image searches (downloads by username or broad browse). If you download by Model ID or URL you are already targeting a specific model, so the tag filter has no additional effect.

---

### Search tab

Use this tab to find models, images, creators, or tags before downloading.

#### Search types

Select the type from the dropdown next to the **Search** button:

| Type | What it searches | Columns shown |
|---|---|---|
| **models** | Model name/keyword | ID, Name, Type, Base Model, Downloads |
| **images** | Community images | ID, Model Name, Media Type, NSFW Level, Creator |
| **creators** | User accounts | Username, Model Count |
| **tags** | Civitai tag names | ID, Tag Name, Model Count |

#### Using results

- **Apply to Filters** (or **double-click** a row) — copies the selected result's IDs into the Filters & Download tab:
  - Model result → sets **Model ID** + **Username** (creator)
  - Image result → sets **Model ID** + **Version ID**
  - Creator result → sets **Username**
  - Tag result → adds the tag to Active Tags
  After applying, switch to the **Filters & Download** tab and click **⬇ Download**.

- **Open in Civitai** — opens the selected result's Civitai page in your browser:
  - Model → `civitai.com/models/{id}`
  - Image → `civitai.com/images/{id}`
  - Creator → `civitai.com/user/{username}`
  - Tag → the tag's model listing page

---

### Settings tab

| Setting | What it does |
|---|---|
| **API Key** | Your Civitai Bearer token — required for NSFW content and higher rate limits. Get one from [civitai.com/user/account](https://civitai.com/user/account) |
| **Model base path** | Root folder used when organizing model files into sub-folders by model/version ID |
| **Extension Server** | Toggle the local HTTP server (port 7865) that receives URLs from the Chrome extension |

---

## License

Apache 2.0 — see [LICENSE](LICENSE).

