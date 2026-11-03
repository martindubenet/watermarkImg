#!/usr/bin/env python3
from __future__ import annotations

"""
add_watermark.py

Batch-adds a bottom-left watermark (SVG or PNG24) to a set of images.
Meant to be called from an Automator "Run Shell Script" Quick Action that
passes the Finder-selected image files as command-line arguments.

Workflow:
    1. Receive image file paths as CLI arguments (from the Finder selection).
    2. Show a single native macOS open panel to pick the watermark file
       (SVG preferred, PNG24 accepted), with one fixed "Resize for sharing"
       checkbox below the file list. Cancel exits silently.
       The panel is used exactly as Apple intends (static accessory view, no
       timers, no delegate, no live relayout), so no click gets lost.
    3. If the watermark is an SVG, validate it contains a `viewBox` (or
       `viewbox`) attribute -- abort otherwise.
    4. For each image: optionally downscale it (longer side capped at
       RESIZE_MAX_LONG_SIDE), compute the watermark width as 15% of the image
       width (floor of MIN_WM_WIDTH), composite it into the bottom-left corner,
       flatten the result onto an opaque background, and save it next to the
       original as "<name>__<watermark-name>[_s]<ext>". The watermark name is
       cleaned up to be file-system friendly (see slugify_suffix): with the
       watermark "ma signature photo.svg", photo.jpg ->
       "photo__ma-signature-photo_s.jpg" ("_s" only when "Resize for sharing"
       is checked). Originals are left untouched.

       HEIC/HEIF/AVIF inputs are decoded fine, but are always written back
       out as high-quality JPEG (photo.heic -> "photo__ma-signature-photo.jpg").
       See OUTPUT_FORMAT_OVERRIDE below to change this.

Adding the capture date to file names is a separate script: ../addDateImg/add_date.py

Requires on the Mac running this:
    - Python 3.9+ with Pillow 11+    (pip3 install -U Pillow) -- 11+ is needed to write XMP into JPEG
    - pillow-heif, for HEIC/HEIF/AVIF input (pip3 install pillow-heif)
    - rsvg-convert, only for SVG watermarks (brew install librsvg)
"""

import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from PIL import Image, ImageOps, PngImagePlugin

try:
    import pillow_heif  # adds HEIC/HEIF (and, if the underlying libheif supports it, AVIF) read support to Pillow

    pillow_heif.register_heif_opener()
    try:
        pillow_heif.register_avif_opener()
    except Exception:
        pass  # older pillow-heif builds don't expose a separate AVIF opener; HEIC/HEIF still work
except ImportError:
    pillow_heif = None

# --- Tunables -------------------------------------------------------------
MIN_WM_WIDTH = 50       # px -- hard floor for the watermark width
WM_WIDTH_RATIO = 0.15   # watermark width = 15% of the image width
MARGIN_PX = 20          # distance from the bottom-left corner, in px.
                        # Not specified in the original brief -- tweak freely.
FLATTEN_BG = (255, 255, 255)  # background color used when flattening transparency

WATERMARK_SUFFIX_PREFIX = "__"           # between the original file stem and the watermark name
WATERMARK_SUFFIX_FALLBACK = "watermark"   # used if the watermark file name is empty once cleaned up
RESIZE_SUFFIX = "_s"                      # appended to the watermark suffix when "Resize for sharing" is on

# --- Watermark list ---------------------------------------------------------
# Every SVG/PNG in this folder is offered in the list. An ordering prefix such as
# "1 ", "02-" or "3_" sets the list order and is left out of the label and suffix.
SCRIPT_DIR = Path(__file__).resolve().parent
WATERMARK_DIR = SCRIPT_DIR / "watermarks"
LAST_CHOICE_FILE = SCRIPT_DIR / ".last_choice"   # preselected item next time (git-ignored)
ORDER_PREFIX_RE = re.compile(r"^\d+[\s._-]+")
LABEL_RESIZE = "   \u2014  resize for sharing"
LABEL_FULL = "   \u2014  full size"
LABEL_OTHER = "Other file\u2026"

# EXIF tags
EXIF_IFD_POINTER = 0x8769
EXIF_ARTIST = 0x013B             # Artist (IFD0)
EXIF_ORIENTATION = 0x0112        # Orientation (IFD0)
EXIF_PIXEL_X = 0xA002            # PixelXDimension (Exif IFD)
EXIF_PIXEL_Y = 0xA003            # PixelYDimension (Exif IFD)
TIFF_XMP = 700                   # XMLPacket tag: where TIFF stores XMP

# --- Output quality & metadata ----------------------------------------------
RESIZE_MAX_LONG_SIDE = 1350  # px, "Resize for sharing": cap on the longer side (never upscales)
JPEG_QUALITY = 95        # above 95 files grow a lot for no visible gain
JPEG_SUBSAMPLING = 0     # 0 = 4:4:4: full-resolution color (Pillow's default is 4:2:0)

# Author credits written into every output (EXIF Artist + XMP/IPTC Creator fields)
AUTHOR_NAME = "Martin Dubé"
AUTHOR_URL = "https://photo.martindube.net"

SUPPORTED_EXT = {
    ".jpg", ".jpeg", ".png", ".webp",
    ".heic", ".heif", ".avif",
    ".tif", ".tiff", ".bmp",
}

# Formats we can read but don't re-encode: written out as high-quality JPEG instead
# (JPEG_QUALITY, 4:4:4, ICC + EXIF kept) -- far smaller than lossless PNG, visually identical.
OUTPUT_FORMAT_OVERRIDE = {".heic": ".jpg", ".heif": ".jpg", ".avif": ".jpg"}


def _as_literal(text: str) -> str:
    """Escape a Python string for safe interpolation into an inline AppleScript string literal."""
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


@dataclass
class Options:
    """User choices from the watermark list."""
    resize: bool = True  # "Resize for sharing": cap the longer side at RESIZE_MAX_LONG_SIDE


def run_dialog(body: str) -> tuple[Optional[str], bool]:
    """Run an AppleScript dialog owned by the frontmost app (Finder, for a Quick Action).

    A dialog shown by a background osascript process may not get the keyboard/mouse
    focus when launched from the Finder (lost clicks since macOS 27.2). Asking the
    frontmost app to show it avoids that. If macOS refuses the Apple Event (Automation
    permission denied), the dialog is shown by osascript itself as a fallback.

    Returns (stdout, cancelled).
    """
    wrapped = ("tell application (path to frontmost application as text)\n"
               "activate\n" + body + "\nend tell")
    for script in (wrapped, body):
        result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
        if result.returncode == 0:
            return result.stdout.strip(), False
        if "-128" in result.stderr:  # user clicked Cancel
            return None, True
        print(f"Dialog failed: {result.stderr.strip()}", file=sys.stderr)
    return None, True


def notify(message: str, title: str = "Watermark batch") -> None:
    """Show a native macOS alert dialog (visible even though this runs headless from Automator)."""
    run_dialog(f"display dialog {_as_literal(message)} with title {_as_literal(title)} "
               "buttons {\"OK\"} default button \"OK\"")


def display_name(wm_path: Path) -> str:
    """File name without an ordering prefix: "1 signature.svg" -> "signature.svg"."""
    return ORDER_PREFIX_RE.sub("", wm_path.name) or wm_path.name


def list_watermarks() -> list[Path]:
    """SVG/PNG files of WATERMARK_DIR, sorted by name (hidden files ignored)."""
    if not WATERMARK_DIR.is_dir():
        return []
    files = [p for p in WATERMARK_DIR.iterdir()
             if p.is_file() and not p.name.startswith(".") and p.suffix.lower() in (".svg", ".png")]
    return sorted(files, key=lambda p: p.name.casefold())


def read_last_choice() -> Optional[str]:
    try:
        return LAST_CHOICE_FILE.read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def save_last_choice(label: str) -> None:
    try:
        LAST_CHOICE_FILE.write_text(label, encoding="utf-8")
    except OSError:
        pass  # not critical: the first item is preselected next time


def choose_watermark_and_options(count: int) -> tuple[bool, Optional[Path], Options]:
    """One native list: each watermark twice (resized / full size), plus "Other file...".

    Returns (cancelled, path, options).
    """
    choices: dict[str, tuple[Path, bool]] = {}
    for wm in list_watermarks():
        name = display_name(wm)
        choices[f"{name}{LABEL_RESIZE}"] = (wm, True)
        choices[f"{name}{LABEL_FULL}"] = (wm, False)
    if not choices:  # empty folder: go straight to the file chooser
        return choose_other_file()

    labels = list(choices) + [LABEL_OTHER]
    last = read_last_choice()
    default = last if last in choices else labels[0]
    items = "{" + ", ".join(_as_literal(label) for label in labels) + "}"
    picked, cancelled = run_dialog(
        f"set picked to choose from list {items} with title \"Add Watermark\" "
        f"with prompt {_as_literal(f'Watermark for {count} image(s):')} "
        f"default items {{{_as_literal(default)}}} OK button name \"Submit\"\n"
        "if picked is false then return \"\"\n"
        "return item 1 of picked")
    if cancelled or not picked:
        return True, None, Options()
    if picked == LABEL_OTHER:
        return choose_other_file()
    save_last_choice(picked)
    wm_path, resize = choices[picked]
    return False, wm_path, Options(resize=resize)


def choose_other_file() -> tuple[bool, Optional[Path], Options]:
    """Plain file chooser, then a Yes/No dialog for "Resize for sharing"."""
    path, cancelled = run_dialog(
        "POSIX path of (choose file with prompt \"Add Watermark : Select the image (SVG or PNG)\" "
        "of type {\"public.svg-image\", \"public.png\"})")
    if cancelled or not path:
        return True, None, Options()
    answer, cancelled = run_dialog(
        f"button returned of (display dialog \"Resize for sharing (longer side max "
        f"{RESIZE_MAX_LONG_SIDE} px)?\" with title \"Add Watermark\" "
        "buttons {\"Cancel\", \"No\", \"Yes\"} default button \"Yes\" cancel button \"Cancel\")")
    if cancelled:
        return True, None, Options()
    return False, Path(path), Options(resize=(answer == "Yes"))


def slugify_suffix(text: str) -> str:
    """Turn the watermark file name into a file-system friendly suffix.

    Every character that is not a letter or a digit (spaces, punctuation,
    symbols, characters macOS rejects such as ":" or "/") becomes a hyphen,
    then runs of hyphens collapse into one and edge hyphens are trimmed:
    "ma signature photo" -> "ma-signature-photo", "logo  (v2)--final" -> "logo-v2-final".
    Accented letters are kept (macOS handles them fine).
    """
    # NFC: macOS may hand over decomposed accents ("e" + combining accent); recompose them first.
    text = unicodedata.normalize("NFC", text)
    slug = "".join(ch if ch.isalnum() else "-" for ch in text)
    slug = re.sub(r"-{2,}", "-", slug).strip("-")
    return slug or WATERMARK_SUFFIX_FALLBACK


def build_output_name(stem: str, out_ext: str, options: Options, wm_suffix: str) -> str:
    """Build '<stem>__<wm_suffix>[_s]<ext>'."""
    name = f"{stem}{WATERMARK_SUFFIX_PREFIX}{wm_suffix}"
    if options.resize:
        name += RESIZE_SUFFIX
    return f"{name}{out_ext}"


def has_valid_viewbox(svg_path: Path) -> bool:
    """Check the SVG source for a `viewBox` or `viewbox` attribute (exact-case match, as requested)."""
    text = svg_path.read_text(encoding="utf-8", errors="ignore")
    return re.search(r"\bview[Bb]ox\s*=", text) is not None


def find_rsvg_convert() -> str:
    """Locate the rsvg-convert binary; Automator's shell PATH usually doesn't include Homebrew's."""
    found = shutil.which("rsvg-convert")
    if found:
        return found
    for candidate in ("/opt/homebrew/bin/rsvg-convert", "/usr/local/bin/rsvg-convert"):
        if Path(candidate).exists():
            return candidate
    raise FileNotFoundError(
        "rsvg-convert not found. Install it with: brew install librsvg"
    )


def clamp_width(image_width: int) -> int:
    """15% of the image width (no upper limit), never narrower than MIN_WM_WIDTH."""
    return max(MIN_WM_WIDTH, round(image_width * WM_WIDTH_RATIO))


def render_svg_to_png(svg_path: Path, target_width: int, out_path: Path) -> None:
    """Rasterize the SVG to a PNG of the given width, keeping its intrinsic (viewBox) aspect ratio."""
    rsvg_convert = find_rsvg_convert()
    subprocess.run(
        [rsvg_convert, "-w", str(target_width), "-o", str(out_path), str(svg_path)],
        check=True,
    )


def load_watermark(wm_path: Path, target_width: int, cache: dict) -> Image.Image:
    """Return an RGBA watermark resized to target_width, reusing a render/resize cache across the batch."""
    if target_width in cache:
        return cache[target_width]

    if wm_path.suffix.lower() == ".svg":
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp_png = Path(tmp.name)
        render_svg_to_png(wm_path, target_width, tmp_png)
        wm_img = Image.open(tmp_png).convert("RGBA")
        wm_img.load()  # force read before we delete the temp file
        tmp_png.unlink(missing_ok=True)
    else:
        wm_img = Image.open(wm_path).convert("RGBA")
        ratio = target_width / wm_img.width
        wm_img = wm_img.resize((target_width, max(1, round(wm_img.height * ratio))), Image.LANCZOS)

    cache[target_width] = wm_img
    return wm_img


def open_image(path: Path) -> Image.Image:
    """Open an image, raising a clear error if HEIC/HEIF/AVIF support isn't installed."""
    if path.suffix.lower() in (".heic", ".heif", ".avif") and pillow_heif is None:
        raise RuntimeError("pillow-heif is not installed -- run: pip3 install pillow-heif")
    return Image.open(path)



def _xml_escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def build_xmp(source_xmp: Optional[bytes]) -> bytes:
    """Return an XMP packet carrying the author name (dc:creator) and website (IPTC CiUrlWork).

    If the source image already has XMP, our block is added to it (existing
    properties are kept; a creator/website already present is not duplicated).
    """
    existing = ""
    if source_xmp:
        existing = source_xmp.decode("utf-8", errors="ignore") if isinstance(source_xmp, bytes) else str(source_xmp)

    props = []
    if "dc:creator" not in existing:
        props.append(
            f"<dc:creator><rdf:Seq><rdf:li>{_xml_escape(AUTHOR_NAME)}</rdf:li></rdf:Seq></dc:creator>"
        )
    if "CiUrlWork" not in existing:
        props.append(
            '<Iptc4xmpCore:CreatorContactInfo rdf:parseType="Resource">'
            f"<Iptc4xmpCore:CiUrlWork>{_xml_escape(AUTHOR_URL)}</Iptc4xmpCore:CiUrlWork>"
            "</Iptc4xmpCore:CreatorContactInfo>"
        )
    description = (
        '<rdf:Description rdf:about="" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'xmlns:Iptc4xmpCore="http://iptc.org/std/Iptc4xmpCore/1.0/xmlns/">'
        + "".join(props)
        + "</rdf:Description>"
    )

    # Merge into the source packet when it has a usable <rdf:RDF> element.
    if existing and "</rdf:RDF>" in existing:
        if not props:
            return existing.encode("utf-8")
        return existing.replace("</rdf:RDF>", description + "</rdf:RDF>", 1).encode("utf-8")

    packet = (
        '<?xpacket begin="\ufeff" id="W5M0MpCehiHzreSzNTczkc9d"?>'
        '<x:xmpmeta xmlns:x="adobe:ns:meta/">'
        '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
        + description
        + "</rdf:RDF></x:xmpmeta>"
        '<?xpacket end="w"?>'
    )
    return packet.encode("utf-8")


def build_exif(source: Image.Image, ascii_only: bool = False,
               size: Optional[tuple[int, int]] = None) -> Optional[bytes]:
    """Return the source EXIF (camera, lens, GPS, dates...) with Artist set and Orientation reset.

    Orientation is reset to 1 because the pixels are rotated upright before
    watermarking (so the watermark always lands in the visual bottom-left).
    """
    try:
        exif = source.getexif()
        if ascii_only:  # TIFF writer only accepts plain ASCII here; XMP keeps the accented name
            exif[EXIF_ARTIST] = "Martin Dube"
        else:
            # UTF-8 bytes: the de facto standard read by macOS, Lightroom and exiftool.
            exif[EXIF_ARTIST] = AUTHOR_NAME.encode("utf-8")
        exif[EXIF_ORIENTATION] = 1
        if size is not None:
            # Keep the recorded pixel dimensions in sync with the saved image.
            exif_ifd = exif.get_ifd(EXIF_IFD_POINTER)
            if exif_ifd:
                exif_ifd[EXIF_PIXEL_X] = size[0]
                exif_ifd[EXIF_PIXEL_Y] = size[1]
        return exif.tobytes()
    except Exception as exc:  # noqa: BLE001 -- unusual EXIF: keep the raw block rather than nothing
        print(f"EXIF rewrite failed ({exc}); copying the original EXIF as-is.", file=sys.stderr)
        raw = source.info.get("exif")
        return raw if isinstance(raw, bytes) else None


def save_with_metadata(img: Image.Image, out_path: Path, source: Image.Image) -> None:
    """Save the flattened image with maximum quality and the source metadata (EXIF, ICC, XMP)."""
    ext = out_path.suffix.lower()
    icc = source.info.get("icc_profile")
    xmp = build_xmp(source.info.get("xmp"))
    kwargs: dict = {}
    if icc:
        kwargs["icc_profile"] = icc  # keeps colors right (e.g. iPhone Display P3)

    if ext in (".jpg", ".jpeg"):
        kwargs.update(quality=JPEG_QUALITY, subsampling=JPEG_SUBSAMPLING, xmp=xmp)
        exif = build_exif(source, size=img.size)
    elif ext == ".png":
        info = PngImagePlugin.PngInfo()
        info.add_itxt("XML:com.adobe.xmp", xmp.decode("utf-8"))
        kwargs.update(optimize=True, pnginfo=info)
        exif = build_exif(source, size=img.size)
    elif ext == ".webp":
        kwargs.update(lossless=True, xmp=xmp)  # lossless: no extra quality loss
        exif = build_exif(source, size=img.size)
    elif ext in (".tif", ".tiff"):
        exif = build_exif(source, ascii_only=True, size=img.size)
        if exif is not None:
            # TIFF stores XMP as tag 700 inside the same directory as the EXIF IFD0.
            tiff_exif = Image.Exif()
            tiff_exif.load(exif)
            tiff_exif[TIFF_XMP] = xmp
            exif = tiff_exif.tobytes()
    else:  # .bmp and others: the format can't carry metadata
        exif = None
        kwargs.pop("icc_profile", None)

    if exif:
        kwargs["exif"] = exif
    img.save(out_path, **kwargs)


def unique_path(path: Path) -> Path:
    """Return path, or 'name (1).ext', 'name (2).ext'... if it already exists (macOS style)."""
    if not path.exists():
        return path
    index = 1
    while True:
        candidate = path.with_name(f"{path.stem} ({index}){path.suffix}")
        if not candidate.exists():
            return candidate
        index += 1


def resize_for_sharing(img: Image.Image) -> Image.Image:
    """Downscale so the longer side is at most RESIZE_MAX_LONG_SIDE px (never upscales)."""
    long_side = max(img.size)
    if long_side <= RESIZE_MAX_LONG_SIDE:
        return img
    ratio = RESIZE_MAX_LONG_SIDE / long_side
    new_size = (max(1, round(img.width * ratio)), max(1, round(img.height * ratio)))
    return img.resize(new_size, Image.LANCZOS)


def apply_watermark(image_path: Path, wm_path: Path, cache: dict, options: Options) -> Path:
    """Composite the watermark onto one image, flatten, and save as <name>__<watermark-name>[_s]<ext>."""
    source = open_image(image_path)
    # Rotate the pixels upright per the EXIF Orientation tag, so the watermark lands
    # in the visual bottom-left corner (the saved EXIF Orientation is reset to 1).
    base = ImageOps.exif_transpose(source).convert("RGBA")
    if options.resize:
        base = resize_for_sharing(base)
    target_width = clamp_width(base.width)
    wm_img = load_watermark(wm_path, target_width, cache)

    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    x = MARGIN_PX
    y = base.height - wm_img.height - MARGIN_PX
    overlay.paste(wm_img, (x, y), wm_img)

    composited = Image.alpha_composite(base, overlay)

    # Flatten: merge everything onto an opaque background, like Photoshop's "Flatten Image".
    flattened = Image.new("RGB", composited.size, FLATTEN_BG)
    flattened.paste(composited, mask=composited.split()[3])

    src_ext = image_path.suffix.lower()
    out_ext = OUTPUT_FORMAT_OVERRIDE.get(src_ext, image_path.suffix)
    out_name = build_output_name(image_path.stem, out_ext, options, slugify_suffix(Path(display_name(wm_path)).stem))
    out_path = unique_path(image_path.with_name(out_name))
    save_with_metadata(flattened, out_path, source)
    return out_path


def main() -> int:
    image_paths = [Path(p) for p in sys.argv[1:] if Path(p).suffix.lower() in SUPPORTED_EXT]
    if not image_paths:
        notify("No valid image was received (supported formats: jpg, jpeg, png, webp, heic, heif, avif, tif, tiff, bmp).")
        return 0  # handled: our dialog is enough, avoid Automator's extra error alert

    cancelled, wm_path, options = choose_watermark_and_options(len(image_paths))
    if cancelled or wm_path is None:
        return 0  # user clicked Cancel: exit quietly (non-zero would trigger Automator's error alert)
    if wm_path.suffix.lower() not in (".svg", ".png"):
        notify("The watermark must be an SVG or PNG image.")
        return 0

    if wm_path.suffix.lower() == ".svg":
        if not has_valid_viewbox(wm_path):
            notify(f"File \"{wm_path.name}\" has no valid viewBox (or viewbox) attribute. Operation cancelled.")
            return 0
        try:
            find_rsvg_convert()
        except FileNotFoundError as exc:
            notify(str(exc))
            return 0

    cache: dict = {}
    done, errors = [], []
    for path in image_paths:
        try:
            done.append(apply_watermark(path, wm_path, cache, options))
        except Exception as exc:  # noqa: BLE001 -- surfaced to the user via dialog, not swallowed
            errors.append(f"{path.name}: {exc}")

    summary = f"{len(done)} image(s) processed successfully."
    if errors:
        summary += "\n\nErrors:\n" + "\n".join(errors)
    notify(summary)
    return 0  # errors (if any) are already listed in the summary dialog


if __name__ == "__main__":
    sys.exit(main())
