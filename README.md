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

## License

Apache 2.0 — see [LICENSE](LICENSE).
