# Civitai Desktop Helper

A Windows desktop application for browsing and downloading models, LoRAs, and preview media from [Civitai](https://civitai.com), with an optional Chrome extension for one-click URL sending from any Civitai page.

---

## Features

- **GUI download tool** — Tkinter-based desktop app with tabs for images, gallery, models, and settings.
- **Model + version downloads** — Downloads `.safetensors` / checkpoint files into an organized folder structure (`modelId-modelName/versionId-versionName/`).
- **Quantization / variant selection** — When a version ships several weight files (e.g. `bf16`, `fp8`, `int8`, `nvfp4`, GGUF), the app prompts you to pick which one(s) to download instead of pulling every multi-GB variant. Split-component models are handled too: each file is listed with its component type (Diffusion Model, VAE, Text Encoder, …), precision and size, so you can grab, say, just the bf16 diffusion model plus the VAE and one text encoder. Pasting a download link with a specific `?fileId=` honors that exact file automatically. Downloaded weight files are tagged with their precision (e.g. `..._bf16.safetensors`) so variants stay easy to tell apart.
- **Preview media** — Optionally downloads showcase images and videos alongside the model files.
- **Full-resolution images with generation data** — Gallery/preview images are fetched at their original resolution (the uploaded file, not a scaled JPEG) and saved with the correct extension (`.png`/`.jpg`/…). The prompt, negative prompt, sampler settings, and any ComfyUI/Civitai workflow embedded in the file are extracted and written into the `.json` sidecar under `_embedded` — even when the public API hides that metadata. An optional **Prompts** toggle also collects every image's prompt into a combined `prompts.txt` (one per line).
- **Gallery browser** — Fetches community gallery images for a model, filterable by base model, NSFW level, period, tags, and sort order.
- **URL resolver** — Paste any Civitai URL (model, version, post, user) and the tool resolves the correct IDs automatically.
- **File preview (dry run)** — Click **Preview files** to see every file a version offers — type, precision, format, and size — with weight-file and grand totals, before downloading anything.
- **Chrome extension** — A browser extension that sends the current Civitai page URL to the desktop app with a single click or keyboard shortcut (default `Ctrl+Shift+K`).
- **Local server** — Lightweight HTTP server (port 7865) that receives URLs from the Chrome extension.
- **Metadata saving** — Optionally saves a `.json` sidecar file alongside each downloaded asset with full API metadata. Weight files also get a compact `_variant` block recording the precision, format, size, and resolved filename.
- **Resumable, verified large-file downloads** — Model files download to a `.part` file via aria2 (multi-connection) or a built-in resumable downloader, survive connection drops and expired signed CDN links, are size/SHA-256 checked, and only then renamed into place. A truncated file left by an earlier failed run is resumed, not mistaken for a finished download.
- **Hugging Face file downloads** — Paste a Hugging Face file link (`…/blob/main/file.safetensors` or `…/resolve/…`) and it downloads flat into the chosen output folder, with an optional access token for gated repos.

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
   - **Tip:** the folder picker only lists *folders*, not files. Navigate to `Civitai_API_tool`, single-click `chrome_extension` to highlight it (do **not** double-click into it — it will look empty because it contains only files), then click **Select Folder**.
4. Make sure the desktop app is running (the local server must be active).

### Usage

- Click the toolbar icon on any Civitai page, or press the keyboard shortcut (default **Ctrl+Shift+K**).
- The current URL is sent to the desktop app, which opens a **Quick Download** window where you pick a download location (recent-location buttons or Browse) and click **Download**.

> The extension requires the desktop app's local server to be running. Enable it via the **Extension Server** toggle in the Settings tab (see Troubleshooting — it is **off** by default on each launch).

### Reloading the extension after a Chrome update

Chrome sometimes removes **unpacked** extensions after an update or restart (often because **Developer mode** was turned off). If the extension disappears from your toolbar or `chrome://extensions/`:

1. Go to `chrome://extensions/`
2. Turn **Developer mode** back **on** — the extension may reappear immediately.
3. If it does not, click **Load unpacked** and re-select the `chrome_extension/` folder (see the Tip above).
4. Re-set the keyboard shortcut (Chrome clears it when an extension is re-added — see below).

### Setting / checking the keyboard shortcut

1. Go to `chrome://extensions/shortcuts`
2. Under **Civitai to Desktop**, find **"Send current Civitai page to Desktop Helper"**.
3. Click the box and press your desired combo (default **Ctrl+Shift+K**).
4. Set the scope to **In Chrome**, or **Global** if you want it to work even when Chrome is not the focused window.

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
├── bin/                          # aria2c.exe lands here when auto-installed (created on first use)
│
├── civitai_tool/
│   ├── gui.py                    # Tkinter GUI (tabs, controls, log)
│   ├── api_client.py             # Civitai REST API wrapper
│   ├── downloads.py              # Download orchestration & file naming
│   ├── url_resolver.py           # Parses Civitai URLs → model/version IDs; Hugging Face file URLs
│   ├── transfer.py               # Resumable/verified download engine (aria2 or built-in), redirect resolver
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

The fastest way to download anything. Paste a Civitai URL (model page, version page, post, or user profile) and click **⬇ Download**. The app auto-resolves the URL to model/version IDs before downloading. You can also click **Resolve** first to preview what was detected without starting the download, or **Preview files** to see the exact file list and sizes a run would fetch.

> **Multiple quantizations:** If the resolved version has several weight files (for example `bf16`, `fp8`, `int8`, `nvfp4`, or GGUF), a picker appears so you can choose which variant(s) to download rather than fetching all of them. Each file is listed with its component type (Diffusion Model, VAE, Text Encoder, …), precision and size, and you can tick more than one. The smallest main-model variant is pre-selected by default. If you paste a direct download link that already specifies a file (`…/api/download/models/<id>?fileId=<fileId>`), that exact file is downloaded without prompting.

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
| **Metadata** | Save a `.json` sidecar file with full API metadata, plus an `_embedded` block holding any generation data (prompt, negative prompt, settings, workflow) recovered from the image file itself |
| **Native size** | Download images at their original resolution (`original=true`) rather than a scaled/re-encoded version. This also preserves the embedded generation metadata, which the scaled copies strip out |
| **Prompts** | Collect each image's positive prompt into a combined `prompts.txt` in the image folder — one prompt per line. Lines are de-duplicated, so re-running a download never adds the same prompt twice |

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
| **Hugging Face token** | Optional read token for gated repos (FLUX, some SD3/Wan releases). Create one at [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens) |
| **Use aria2** | Use aria2 for model-file downloads. If `aria2c` isn't on PATH or in `bin/`, the official 1.37.0 Windows build is fetched into `bin/` on first use. Untick to use the built-in single-connection resumable downloader |
| **aria2c path** | Point at a specific `aria2c.exe`; **Detect / Install** locates or fetches it |
| **Connections per file** | Parallel connections aria2 opens per file (default 8). Lower it if a site throttles you |

### How large downloads behave

1. The tool follows the site's redirect itself (with your API key/token) and hands the bare signed CDN URL to the downloader, so auth headers never leak to the CDN and expired links are re-fetched instead of retried forever.
2. Data lands in `<name>.part` (plus `<name>.part.aria2` for aria2's segment map). Kill the app, lose the connection, reboot — re-run the same URL and it resumes.
3. On completion the size (and SHA-256 when Civitai/Hugging Face publish one) is checked; only then is `.part` renamed to the final filename.
4. On re-run, an existing final file is skipped only if its size matches what the server reports. A short file is resumed; a wrong-sized file is re-downloaded.

---

## Troubleshooting

### The keyboard shortcut stopped working / the extension disappeared

This is the most common issue after a **Chrome update** or **computer restart**. The Chrome extension is loaded as an *unpacked* extension, and Chrome may drop it or clear its keyboard shortcut when it updates.

**Symptoms:**
- Pressing the shortcut (e.g. `Ctrl+Shift+K`) does nothing — no Quick Download window appears.
- The **Civitai to Desktop** extension is missing from `chrome://extensions/`.

**Cause:** Chrome turned off **Developer mode** (which hides/disables unpacked extensions) and/or cleared the extension's keyboard shortcut binding.

**Fix:**
1. Open `chrome://extensions/` and turn **Developer mode** back **on**. If the extension does not reappear, click **Load unpacked** and re-select the `chrome_extension/` folder (remember: single-click the folder and choose **Select Folder** — it looks empty inside because it only contains files).
2. Open `chrome://extensions/shortcuts` and re-assign **Ctrl+Shift+K** to **"Send current Civitai page to Desktop Helper"**.
3. In the desktop app's **Settings** tab, make sure **Extension Server (port 7865)** is checked (it resets to *off* on each launch).
4. Go to a Civitai page and press the shortcut — the desktop **Quick Download** window should appear.

### Nothing happens even though the shortcut is set

The extension talks to the desktop app over `http://127.0.0.1:7865`. If the server is not running, the URL is never received.

- Confirm **Extension Server (port 7865)** is enabled in the Settings tab.
- Verify the server is reachable — in a terminal:
  ```powershell
  Invoke-WebRequest -Uri "http://127.0.0.1:7865/status" -UseBasicParsing
  ```
  A `200` response with `{"status": "ok", ...}` means the server is up.

### "Desktop app not running" in the extension popup

Same cause as above — the local server is off or blocked. Enable the **Extension Server** toggle and, if you use a firewall, allow local connections to port 7865.

### The "Load unpacked" folder looks empty

Chrome's folder picker only shows sub-folders, not files. The `chrome_extension/` folder contains only files, so it appears empty when you open it. Don't go inside it — highlight the `chrome_extension` folder itself and click **Select Folder**.

---

## License

Apache 2.0 — see [LICENSE](LICENSE).

