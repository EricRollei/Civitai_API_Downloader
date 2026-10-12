"""Extract AI-generation metadata embedded inside downloaded image files.

Civitai serves the *original* image (via ``original=true``) with the generation
parameters baked into the file itself — either as PNG text chunks (A1111 /
ComfyUI) or, as Civitai now commonly does, inside an EXIF ``UserComment``. The
public API's ``meta`` field is frequently empty for these images, so reading the
file is the only way to recover the prompt, settings and workflow.

This module parses that embedded data with the standard library only (no Pillow
dependency): PNG ``tEXt``/``zTXt``/``iTXt`` chunks, PNG ``eXIf`` chunks, and JPEG
APP1/EXIF segments.
"""

from __future__ import annotations

import json
import re
import struct
import zlib
from pathlib import Path
from typing import Dict, List, Optional


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

# (magic prefix, extension). RIFF/WEBP is handled separately (needs a split check).
_IMAGE_MAGIC = (
    (PNG_SIGNATURE, ".png"),
    (b"\xff\xd8\xff", ".jpg"),
    (b"GIF87a", ".gif"),
    (b"GIF89a", ".gif"),
    (b"BM", ".bmp"),
)


def sniff_image_ext(data: bytes) -> Optional[str]:
    """Return a file extension for ``data`` based on its magic bytes, or None."""
    for magic, ext in _IMAGE_MAGIC:
        if data.startswith(magic):
            return ext
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    return None


def _decode_user_comment(val: bytes) -> str:
    """Decode an EXIF UserComment value, honoring its 8-byte charset prefix."""
    if val[:8] == b"UNICODE\x00":
        body = val[8:]
        # The spec ties the byte order to the TIFF header, but in practice most
        # writers emit UTF-16-BE; fall back to LE if BE looks like garbage.
        for enc in ("utf-16-be", "utf-16-le"):
            try:
                text = body.decode(enc)
            except UnicodeDecodeError:
                continue
            if text.count("\ufffd") <= len(text) / 4:
                return text.rstrip("\x00")
        return body.decode("utf-16-be", "replace").rstrip("\x00")
    if val[:8] in (b"ASCII\x00\x00\x00", b"ASCII\x00\x00"):
        return val[8:].split(b"\x00", 1)[0].decode("latin1", "replace")
    return val.split(b"\x00", 1)[0].decode("utf-8", "replace")


def _tiff_user_fields(exif: bytes) -> Dict[str, str]:
    """Pull ImageDescription (0x010E) and UserComment (0x9286) from a TIFF/EXIF blob.

    UserComment lives in the Exif sub-IFD (reached via tag 0x8769), so that
    pointer is followed in addition to the primary IFD."""
    out: Dict[str, str] = {}
    if len(exif) < 8:
        return out
    byte_order = exif[:2]
    if byte_order == b"II":
        end = "<"
    elif byte_order == b"MM":
        end = ">"
    else:
        return out
    wanted = {0x010E: "ImageDescription", 0x9286: "UserComment"}
    type_size = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 7: 1, 9: 4, 10: 8}
    try:
        (first_ifd,) = struct.unpack(end + "I", exif[4:8])
        pending: List[int] = [first_ifd]
        seen: set = set()
        while pending:
            off = pending.pop()
            if not off or off in seen or off + 2 > len(exif):
                continue
            seen.add(off)
            (count,) = struct.unpack(end + "H", exif[off:off + 2])
            base = off + 2
            for i in range(count):
                entry = base + i * 12
                if entry + 12 > len(exif):
                    break
                tag, typ, cnt = struct.unpack(end + "HHI", exif[entry:entry + 8])
                if tag == 0x8769:  # Exif sub-IFD pointer
                    (sub,) = struct.unpack(end + "I", exif[entry + 8:entry + 12])
                    pending.append(sub)
                    continue
                if tag not in wanted:
                    continue
                size = type_size.get(typ, 1) * cnt
                if size <= 4:
                    raw = exif[entry + 8:entry + 8 + size]
                else:
                    (voff,) = struct.unpack(end + "I", exif[entry + 8:entry + 12])
                    raw = exif[voff:voff + size]
                if tag == 0x9286:
                    out["UserComment"] = _decode_user_comment(raw)
                else:
                    out[wanted[tag]] = raw.split(b"\x00", 1)[0].decode("utf-8", "replace")
    except struct.error:
        pass
    return out


def _read_png(data: bytes) -> Dict[str, object]:
    text_chunks: Dict[str, str] = {}
    exif: Dict[str, str] = {}
    pos = 8
    while pos + 12 <= len(data):
        (length,) = struct.unpack(">I", data[pos:pos + 4])
        ctype = data[pos + 4:pos + 8]
        chunk = data[pos + 8:pos + 8 + length]
        if ctype in (b"tEXt", b"zTXt", b"iTXt"):
            nul = chunk.find(b"\x00")
            if nul != -1:
                keyword = chunk[:nul].decode("latin1", "replace")
                rest = chunk[nul + 1:]
                try:
                    if ctype == b"zTXt":
                        rest = zlib.decompress(rest[1:]) if rest else b""
                    elif ctype == b"iTXt":
                        comp_flag = rest[0] if rest else 0
                        rest = rest[2:]  # skip compression flag + method
                        for _ in range(2):  # skip language tag + translated keyword
                            sep = rest.find(b"\x00")
                            rest = rest[sep + 1:] if sep != -1 else rest
                        if comp_flag == 1:
                            rest = zlib.decompress(rest)
                    text_chunks[keyword] = rest.decode("utf-8", "replace")
                except (zlib.error, IndexError):
                    pass
        elif ctype == b"eXIf":
            exif = _tiff_user_fields(chunk)
        pos += 12 + length
        if ctype == b"IEND":
            break
    return {"text_chunks": text_chunks, "exif": exif}


def _read_jpeg_exif(data: bytes) -> Dict[str, str]:
    pos = 2
    size = len(data)
    while pos + 4 <= size:
        if data[pos] != 0xFF:
            break
        marker = data[pos + 1]
        if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
            pos += 2
            continue
        if marker == 0xDA:  # start of scan — image data follows, no more metadata
            break
        (seg_len,) = struct.unpack(">H", data[pos + 2:pos + 4])
        segment = data[pos + 4:pos + 2 + seg_len]
        if marker == 0xE1 and segment[:6] == b"Exif\x00\x00":
            return _tiff_user_fields(segment[6:])
        pos += 2 + seg_len
    return {}


def _balanced_json(text: str, start: int) -> Optional[str]:
    open_ch = text[start]
    close_ch = {"{": "}", "[": "]"}.get(open_ch)
    if close_ch is None:
        return None
    depth = 0
    in_str = False
    escaped = False
    for i in range(start, len(text)):
        ch = text[i]
        if escaped:
            escaped = False
            continue
        if ch == "\\":
            escaped = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch == open_ch:
            depth += 1
        elif ch == close_ch:
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return None


def parse_generation_parameters(text: str) -> Dict[str, object]:
    """Parse an A1111-style ``parameters`` string into structured fields.

    Handles the ``<prompt>\\nNegative prompt: <neg>\\n<key: val, ...>`` layout and
    extracts the JSON ``Civitai metadata``/``Civitai resources`` blobs Civitai
    appends (which carry the structured prompt, seed, steps and workflow)."""
    text = (text or "").strip()
    result: Dict[str, object] = {"raw": text}
    if not text:
        return result

    settings_line = ""
    neg_marker = re.search(r"(?:^|\n)Negative prompt:", text)
    steps_marker = re.search(r"(?:^|\n)Steps:\s", text)

    if neg_marker:
        result["prompt"] = text[:neg_marker.start()].strip()
        remainder = text[neg_marker.end():]
        rem_steps = re.search(r"(?:^|\n)Steps:\s", remainder)
        if rem_steps:
            result["negativePrompt"] = remainder[:rem_steps.start()].strip()
            settings_line = remainder[rem_steps.start():].strip()
        else:
            result["negativePrompt"] = remainder.strip()
    elif steps_marker:
        result["prompt"] = text[:steps_marker.start()].strip()
        settings_line = text[steps_marker.start():].strip()
    else:
        result["prompt"] = text

    # Structured JSON blobs Civitai appends to the settings line.
    for key, pattern in (("civitaiMetadata", r"Civitai metadata:\s*(\{)"),
                         ("civitaiResources", r"Civitai resources:\s*(\[)")):
        match = re.search(pattern, settings_line)
        if match:
            blob = _balanced_json(settings_line, match.start(1))
            if blob:
                try:
                    result[key] = json.loads(blob)
                except json.JSONDecodeError:
                    pass

    # Scalar settings (Steps/Sampler/CFG scale/Seed/Size …) — the part of the
    # settings line before any embedded JSON blob.
    cut = len(settings_line)
    for marker in ("Civitai metadata:", "Civitai resources:"):
        idx = settings_line.find(marker)
        if idx != -1:
            cut = min(cut, idx)
    scalar_part = settings_line[:cut].rstrip(", ").strip()
    fields: Dict[str, str] = {}
    if scalar_part:
        for piece in scalar_part.split(", "):
            if ": " in piece:
                field_key, field_val = piece.split(": ", 1)
                fields[field_key.strip()] = field_val.strip()
    if fields:
        result["fields"] = fields
    return result


def _normalize(raw_sources: Dict[str, object]) -> Optional[Dict[str, object]]:
    text_chunks: Dict[str, str] = raw_sources.get("text_chunks", {})  # type: ignore[assignment]
    exif: Dict[str, str] = raw_sources.get("exif", {})  # type: ignore[assignment]

    summary: Dict[str, object] = {}
    source: Optional[str] = None
    parameters_text: Optional[str] = None

    # Preferred A1111 text sources, in order.
    if "parameters" in text_chunks:
        parameters_text = text_chunks["parameters"]
        source = "png-text:parameters"
    elif exif.get("UserComment"):
        parameters_text = exif["UserComment"]
        source = "exif-usercomment"
    elif exif.get("ImageDescription"):
        parameters_text = exif["ImageDescription"]
        source = "exif-imagedescription"

    if parameters_text:
        parsed = parse_generation_parameters(parameters_text)
        summary.update(parsed)

    # ComfyUI stores the executable graph as JSON text chunks.
    for key in ("workflow", "prompt"):
        value = text_chunks.get(key)
        if value and value.lstrip().startswith(("{", "[")):
            try:
                summary.setdefault("comfy", {})[key] = json.loads(value)  # type: ignore[union-attr]
                source = source or "png-text:comfy"
            except json.JSONDecodeError:
                pass

    # Surface a ready-to-use workflow if Civitai included one.
    civitai_meta = summary.get("civitaiMetadata")
    if isinstance(civitai_meta, dict) and civitai_meta.get("workflow") and "workflow" not in summary:
        summary["workflow"] = civitai_meta.get("workflow")

    if not summary:
        return None
    summary["source"] = source
    return summary


def extract_embedded_metadata(path: Path) -> Optional[Dict[str, object]]:
    """Read an image file and return its embedded generation metadata, or None.

    The returned dict may include ``prompt``, ``negativePrompt``, ``fields``
    (scalar settings), ``civitaiMetadata``/``civitaiResources`` (parsed JSON),
    ``comfy`` (ComfyUI graph), ``workflow`` and ``raw`` (the original text)."""
    try:
        with open(path, "rb") as handle:
            data = handle.read()
    except OSError:
        return None
    if not data:
        return None
    try:
        if data.startswith(PNG_SIGNATURE):
            return _normalize(_read_png(data))
        if data.startswith(b"\xff\xd8\xff"):
            return _normalize({"text_chunks": {}, "exif": _read_jpeg_exif(data)})
    except Exception:
        # Metadata extraction must never break a successful download.
        return None
    return None
