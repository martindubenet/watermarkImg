#!/usr/bin/env python3
from __future__ import annotations

"""
add_watermark.py

Batch-adds a bottom-left watermark (SVG or PNG24) to a set of images.
Meant to be called from an Automator "Run Shell Script" Quick Action that
passes the Finder-selected image files as command-line arguments.

Workflow:
    1. Receive image file paths as CLI arguments (from the Finder selection).
    2. Prompt the user with a native macOS open panel to pick a watermark file
       (SVG preferred, PNG24 accepted as a fallback). The panel embeds an
       options box (accessory view): an "Add date created" switch that, when ON,
       reveals the date position and time sub-options. Cancel exits silently.
    3. If the watermark is an SVG, validate it contains a `viewBox` (or
       `viewbox`) attribute -- abort otherwise.
    4. For each image: compute the watermark width as 15% of the image
       width (no upper limit, floor of MIN_WM_WIDTH), render/resize the
       watermark to that width, composite it into the bottom-left corner,
       flatten the result onto an opaque background, and save it next to
       the original with a "___photo-MartinDube" suffix inserted before the
       extension (e.g. photo.jpg -> photo___photo-MartinDube.jpg). When the
       "Add date created" option is on, the capture date is added as
       "YYMMDD-HHhMM" (or "YYMMDD"), separated by a space, before the name
       (default, e.g. "260925-14h32 photo___photo-MartinDube.jpg") or after
       the suffix (e.g. "photo___photo-MartinDube 260925-14h32.jpg").
       Originals are left untouched.

       HEIC/HEIF/AVIF inputs are decoded fine, but are always written back
       out as lossless PNG24 (photo.heic -> photo___photo-MartinDube.png): encoding
       back to those formats needs extra licensed encoders that aren't
       reliably available, so PNG is used as the practical, always-available,
       compression-free output. See OUTPUT_FORMAT_OVERRIDE below to change this.

Requires on the Mac running this:
    - Python 3.9+ with Pillow 11+    (pip3 install -U Pillow) -- 11+ is needed to write XMP into JPEG
    - pillow-heif, for HEIC/HEIF/AVIF input (pip3 install pillow-heif)
    - rsvg-convert, only for SVG watermarks (brew install librsvg)
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime
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

WATERMARK_SUFFIX = "___photo-MartinDube"  # appended to the original file stem
DATE_FORMAT_FULL = "%y%m%d-%Hh%M"         # YYMMDD-HHhMM (lowercase "h" = "heure")
DATE_FORMAT_DAY = "%y%m%d"                # YYMMDD, when hours/minutes are turned off
DATE_SEPARATOR = " "                      # between the file name part and the date stamp

# EXIF tags used to find when the photo was taken (first one found wins)
EXIF_IFD_POINTER = 0x8769
EXIF_DATETIME_ORIGINAL = 36867   # DateTimeOriginal: when the shutter fired
EXIF_DATETIME_DIGITIZED = 36868  # DateTimeDigitized
EXIF_DATETIME = 306              # DateTime (IFD0): last change by camera/software
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

# Formats we can happily read but won't try to re-encode: written out as lossless PNG24 instead.
OUTPUT_FORMAT_OVERRIDE = {".heic": ".png", ".heif": ".png", ".avif": ".png"}


def notify(message: str, title: str = "Watermark batch") -> None:
    """Show a native macOS alert dialog (visible even though this runs headless from Automator)."""
    script = (
        f"display dialog {_as_literal(message)} "
        f"with title {_as_literal(title)} buttons {{\"OK\"}} default button \"OK\""
    )
    subprocess.run(["osascript", "-e", script], check=False)


def _as_literal(text: str) -> str:
    """Escape a Python string for safe interpolation into an inline AppleScript string literal."""
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


@dataclass
class NamingOptions:
    """User choices from the "Options" box of the watermark picker."""
    add_date: bool = True
    position: str = "before"  # "before" or "after" the file name
    include_time: bool = True
    resize: bool = True       # "Resize for sharing": cap the longer side at RESIZE_MAX_LONG_SIDE


# JXA (JavaScript for Automation) script: shows a native NSOpenPanel with an
# "Options" box as accessory view, and prints the result as JSON on stdout.
_OPEN_PANEL_JXA = r"""
ObjC.import('AppKit');

var WINDOW_TITLE = 'Add Watermark';
var MESSAGE = 'Add Watermark : Select the image (SVG or PNG)';  // system-styled panel header

// Options box geometry (non-flipped view: rows are placed from the top edge down)
var BOX_WIDTH = 600;
var TOP_GAP = 18;           // space between the file list and the switch row
var ROW_HEIGHT = 28;        // vertical rhythm between rows
var BOTTOM_PAD = 12;
var LEFT_EXPANDED = 24 + 2 * ROW_HEIGHT;  // left zone content: switch row + 2 sub-options
var LEFT_COLLAPSED = 24;                   // left zone content: switch row only
var ZONE_GAP = 10;          // space on each side of the vertical ruler
var RIGHT_MARGIN = 20;      // right edge padding of the options box
var RESIZE_TEXT = 'Reduce image dimensions to a maximum of __RESIZE_MAX__ pixels on its longer side ' +
                  '(Y for portrait OR X for landscape axis).';
var ANIM_DURATION = 0.22;   // seconds, collapse/expand transition

function run(argv) {
    var DEBUG = (argv && argv.length > 0 && argv[0] === 'debug');
    function log(msg) { if (DEBUG) { console.log('[wm-debug] ' + msg); } }

    var app = $.NSApplication.sharedApplication;
    app.setActivationPolicy(1); // Accessory: lets the panel take focus without a Dock icon
    app.activateIgnoringOtherApps(true);

    var alignX = 20;        // left edge; re-synced with the panel title when reachable
    var expanded = true;
    var timersWork = false; // set on the first timer tick; animation needs working timers

    // --- Options container: plain view, no title, no background ----------
    var box = $.NSView.alloc.initWithFrame($.NSMakeRect(0, 0, BOX_WIDTH, 120));
    box.autoresizingMask = 2;  // NSViewWidthSizable: stretch with the panel
    box.clipsToBounds = true;  // sub-options get clipped while the box collapses

    // Main toggle: small <Switch> + label matching the system panel header (bold, system size)
    var swDate = $.NSSwitch.alloc.initWithFrame($.NSMakeRect(0, 0, 40, 22));
    swDate.controlSize = 1;    // NSControlSizeSmall: closer to checkbox/radio size
    swDate.setFrameSize(swDate.fittingSize);
    swDate.state = 1;
    box.addSubview(swDate);
    var swLabel = $.NSTextField.labelWithString('Add date created');
    swLabel.font = $.NSFont.boldSystemFontOfSize($.NSFont.systemFontSize);
    swLabel.sizeToFit;
    box.addSubview(swLabel);

    function makeButton(title, type, checked) {
        var btn = $.NSButton.alloc.initWithFrame($.NSMakeRect(0, 0, 300, 20));
        btn.setButtonType(type); // 3 = checkbox (switch button), 4 = radio
        btn.title = title;
        btn.state = checked ? 1 : 0;
        btn.sizeToFit;
        box.addSubview(btn);
        return btn;
    }

    // <li> 1. Position relative to file name: (o) Before  ( ) After
    var posLabel = $.NSTextField.labelWithString('1. Position relative to file name:');
    box.addSubview(posLabel);
    var rBefore = makeButton('Before', 4, true);
    var rAfter = makeButton('After', 4, false);
    rBefore.tag = 1;
    rAfter.tag = 2;

    // <li> 2. [x] Include hours and minutes (HHhMM)
    var timeNum = $.NSTextField.labelWithString('2.');
    box.addSubview(timeNum);
    var cbTime = makeButton('Include hours and minutes (HHhMM)', 3, true);

    var subOptions = [posLabel, rBefore, rAfter, timeNum, cbTime];

    // --- Vertical ruler between the two zones -------------------------------
    var ruler = $.NSBox.alloc.initWithFrame($.NSMakeRect(0, 0, 1, 60));
    ruler.boxType = 2;  // NSBoxSeparator: native thin separator line
    box.addSubview(ruler);

    // --- Right zone: [x] Resize for sharing + explanation -------------------
    var cbResize = makeButton('Resize for sharing', 3, true);
    cbResize.font = $.NSFont.boldSystemFontOfSize($.NSFont.systemFontSize); // same style as the switch label
    cbResize.sizeToFit;
    var resizeText = $.NSTextField.wrappingLabelWithString(RESIZE_TEXT);
    resizeText.font = $.NSFont.systemFontOfSize($.NSFont.systemFontSize);  // same style as the left option labels
    box.addSubview(resizeText);

    // Horizontal offset of the checkbox title, so the explanation aligns with it.
    function checkboxTitleInset() {
        try {
            var x = cbResize.cell.titleRectForBounds(cbResize.bounds).origin.x;
            if (x >= 12 && x <= 30) { return Math.round(x); }
        } catch (e) { /* fall through to the default */ }
        return 20;
    }

    // Size the explanation to the available width; return the right zone content height.
    var rightX = 0;
    function measureRightZone() {
        var leftEdge = Math.max(
            swLabel.frame.origin.x + swLabel.frame.size.width,
            rAfter.frame.origin.x + rAfter.frame.size.width,
            cbTime.frame.origin.x + cbTime.frame.size.width
        );
        var rulerX = Math.round(leftEdge + ZONE_GAP);
        ruler.setFrameOrigin($.NSMakePoint(rulerX, ruler.frame.origin.y));
        rightX = rulerX + 1 + ZONE_GAP;
        var textW = Math.max(180, box.frame.size.width - rightX - checkboxTitleInset() - RIGHT_MARGIN);
        resizeText.preferredMaxLayoutWidth = textW;
        var fit = resizeText.fittingSize;
        resizeText.setFrameSize($.NSMakeSize(textW, Math.ceil(fit.height)));
        return 24 + 2 + resizeText.frame.size.height;  // checkbox row + gap + text
    }

    // Box height for a given switch state: the taller of the two zones.
    // Switch OFF: both zones collapse to their first row (the explanation is hidden too).
    function heightFor(isExpanded) {
        var rightFull = measureRightZone();  // also positions the ruler and right zone
        var right = isExpanded ? rightFull : 24;
        var left = isExpanded ? LEFT_EXPANDED : LEFT_COLLAPSED;
        return TOP_GAP + Math.max(left, right) + BOTTOM_PAD;
    }

    // Vertically center a control on a row's center line.
    function place(view, x, centerY) {
        view.setFrameOrigin($.NSMakePoint(x, Math.round(centerY - view.frame.size.height / 2)));
    }

    // Lay out every control for a given box height; rows hang from the top edge,
    // so shrinking the height clips the sub-options from the bottom up.
    function layout(height, showSubs) {
        box.setFrameSize($.NSMakeSize(box.frame.size.width, height));
        var row0 = height - TOP_GAP - 12;
        var row1 = row0 - ROW_HEIGHT;
        var row2 = row1 - ROW_HEIGHT;

        place(swDate, alignX, row0);
        var labelX = alignX + swDate.frame.size.width + 8;
        place(swLabel, labelX, row0);

        var subX = labelX;  // <ol> indent aligned with the switch label text
        place(posLabel, subX, row1);
        var bx = subX + posLabel.frame.size.width + 12;
        place(rBefore, bx, row1);
        place(rAfter, bx + rBefore.frame.size.width + 16, row1);
        place(timeNum, subX, row2);
        place(cbTime, subX + timeNum.frame.size.width + 6, row2);

        for (var i = 0; i < subOptions.length; i++) {
            subOptions[i].hidden = !showSubs;
        }

        // Right zone, top-aligned with the switch row; ruler spans the content height.
        measureRightZone();
        place(cbResize, rightX, row0);
        var textTop = row0 - 12 - 2;
        resizeText.setFrameOrigin($.NSMakePoint(rightX + checkboxTitleInset(), Math.round(textTop - resizeText.frame.size.height)));
        resizeText.hidden = !showSubs;  // explanation collapses with the switch, like the sub-options
        ruler.setFrame($.NSMakeRect(ruler.frame.origin.x, BOTTOM_PAD, 1, Math.max(1, height - TOP_GAP - BOTTOM_PAD)));
    }
    layout(120, true);                // place controls once so measurements are real
    layout(heightFor(true), true);
    var lastWidth = box.frame.size.width;

    var panel = $.NSOpenPanel.openPanel;

    // Ask the panel to re-measure the accessory view after a height change.
    function refreshAccessory() {
        panel.accessoryView = $();
        panel.accessoryView = box;
        panel.accessoryViewDisclosed = true;
    }

    // --- Collapse / expand animation (ease-in-out, stepped by a timer) -----
    var anim = null;  // { from, to, start, timer }
    function easeInOut(t) { return t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2; }

    function animateTo(targetHeight) {
        if (anim !== null) { anim.timer.invalidate; anim = null; }
        if (!timersWork) {  // no working run-loop timers: jump to the final state
            layout(targetHeight, expanded);
            refreshAccessory();
            return;
        }
        var t = $.NSTimer.timerWithTimeIntervalTargetSelectorUserInfoRepeats(1 / 60, handler, 'animStep:', $(), true);
        anim = { from: box.frame.size.height, to: targetHeight, start: Date.now(), timer: t };
        $.NSRunLoop.currentRunLoop.addTimerForMode(t, 'kCFRunLoopCommonModes');
        $.NSRunLoop.currentRunLoop.addTimerForMode(t, 'NSModalPanelRunLoopMode');
    }

    function animStep() {
        if (anim === null) { return; }
        var t = Math.min(1, (Date.now() - anim.start) / (ANIM_DURATION * 1000));
        var h = Math.round(anim.from + (anim.to - anim.from) * easeInOut(t));
        // Keep sub-options visible while moving; hide them only once fully collapsed.
        layout(h, t < 1 ? true : expanded);
        refreshAccessory();
        if (t >= 1) { anim.timer.invalidate; anim = null; }
    }

    // Recursively collect the panel's subviews (used for the cosmetic tweaks below).
    function allSubviews(view, out) {
        var subs = view.subviews;
        for (var i = 0; i < subs.count; i++) {
            var v = subs.objectAtIndex(i);
            out.push(v);
            allSubviews(v, out);
        }
        return out;
    }

    var dumped = false;

    // Best-effort tweaks on the panel's own views (no-op when they are not reachable,
    // e.g. when macOS hosts the file browser in a separate process):
    //  - hide the "Hide Options" / "Show Options" button
    //  - left-align the options with the title
    function tweakPanelUI() {
        var frameView = panel.contentView.superview;
        if (!frameView || frameView.isNil()) { log('no frame view'); return; }
        var views = allSubviews(frameView, []);

        if (DEBUG && !dumped) {
            dumped = true;
            var names = {};
            for (var d = 0; d < views.length; d++) {
                var cls = ObjC.unwrap(views[d].className);
                names[cls] = (names[cls] || 0) + 1;
                if (views[d].isKindOfClass($.NSTextField)) { log('text field: ' + JSON.stringify(views[d].stringValue.js)); }
                if (views[d].isKindOfClass($.NSButton)) { log('button: ' + JSON.stringify(views[d].title.js)); }
            }
            log('view count: ' + views.length);
            log('classes: ' + JSON.stringify(names));
        }

        var titleField = null;
        for (var i = 0; i < views.length; i++) {
            var v = views[i];
            if (v.isKindOfClass($.NSTextField) && !v.isDescendantOf(box)
                && v.stringValue.js === MESSAGE) {
                titleField = v;  // used below to left-align the options with the header
            } else if (v.isKindOfClass($.NSButton) && !v.isDescendantOf(box)
                       && /option/i.test(v.title.js) && !v.hidden) {
                v.hidden = true; // e.g. "Hide Options" (localized titles contain "option" too)
                log('options button hidden');
            }
        }

        // Left-align the switch with the title text.
        if (titleField !== null && anim === null) {
            var origin = box.convertPointFromView(titleField.frame.origin, titleField.superview);
            var x = Math.round(origin.x + 2); // + label text inset
            if (x >= 0 && x < 300 && Math.abs(x - alignX) > 0.5) {
                alignX = x;
                layout(box.frame.size.height, expanded);
            }
        }

        // Panel width changed (stretch or window resize): re-wrap the explanation
        // and let the panel re-measure if the needed height changed.
        if (anim === null && Math.abs(box.frame.size.width - lastWidth) > 0.5) {
            lastWidth = box.frame.size.width;
            var target = heightFor(expanded);
            var oldH = box.frame.size.height;
            layout(target, expanded);
            if (Math.abs(target - oldH) > 0.5) { refreshAccessory(); }
        }
    }

    // --- Event handler ---------------------------------------------------------
    ObjC.registerSubclass({
        name: 'WMOptionsHandler',
        methods: {
            'positionChanged:': {
                types: ['void', ['id']],
                implementation: function (sender) {
                    rBefore.state = (sender.tag == 1) ? 1 : 0;
                    rAfter.state = (sender.tag == 2) ? 1 : 0;
                }
            },
            'dateToggled:': {
                types: ['void', ['id']],
                implementation: function (sender) {
                    expanded = (swDate.state == 1);
                    animateTo(heightFor(expanded));
                }
            },
            'animStep:': {
                types: ['void', ['id']],
                implementation: function (timer) { animStep(); }
            },
            'tweakUI:': {
                types: ['void', ['id']],
                implementation: function (timer) {
                    if (!timersWork) { timersWork = true; log('timer tick OK'); }
                    tweakPanelUI();
                }
            }
        }
    });
    var handler = $.WMOptionsHandler.alloc.init;
    rBefore.target = handler;
    rBefore.action = 'positionChanged:';
    rAfter.target = handler;
    rAfter.action = 'positionChanged:';
    swDate.target = handler;
    swDate.action = 'dateToggled:';

    // --- Open panel -----------------------------------------------------------
    panel.title = WINDOW_TITLE;
    panel.message = MESSAGE;
    panel.prompt = 'Submit';  // default-button label
    panel.canChooseFiles = true;
    panel.canChooseDirectories = false;
    panel.allowsMultipleSelection = false;
    panel.allowedFileTypes = $(['svg', 'png']);
    panel.accessoryView = box;
    panel.accessoryViewDisclosed = true; // show the options without an extra toggle

    // The panel builds its views lazily, so apply the tweaks on a short repeating
    // timer that also runs while the modal panel is up.
    var timer = $.NSTimer.timerWithTimeIntervalTargetSelectorUserInfoRepeats(0.15, handler, 'tweakUI:', $(), true);
    $.NSRunLoop.currentRunLoop.addTimerForMode(timer, 'kCFRunLoopCommonModes');
    $.NSRunLoop.currentRunLoop.addTimerForMode(timer, 'NSModalPanelRunLoopMode');

    var response = panel.runModal;
    timer.invalidate;
    if (anim !== null) { anim.timer.invalidate; }
    log('timers worked: ' + timersWork);

    if (response != 1) { // 1 = NSModalResponseOK
        return JSON.stringify({ cancelled: true });
    }
    return JSON.stringify({
        cancelled: false,
        path: panel.URL.path.js,
        addDate: swDate.state == 1,
        position: (rBefore.state == 1) ? 'before' : 'after',
        includeTime: cbTime.state == 1,
        resize: cbResize.state == 1
    });
}
"""


def choose_watermark_and_options() -> tuple[Optional[Path], NamingOptions]:
    """Show the watermark picker with its "Options" box.

    Returns (path, options); path is None when the user clicked Cancel.
    Falls back to the plain AppleScript chooser (default options) if the
    JXA open panel can't run for some reason.
    """
    # WM_DEBUG=1 prints the open panel's diagnostics (view hierarchy, timers) to the Terminal.
    debug = os.environ.get("WM_DEBUG") == "1"
    script = _OPEN_PANEL_JXA.replace("__RESIZE_MAX__", str(RESIZE_MAX_LONG_SIDE))
    cmd = ["osascript", "-l", "JavaScript", "-e", script]
    if debug:
        cmd.append("debug")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if debug and result.stderr:
        print(result.stderr, file=sys.stderr)
    if result.returncode == 0:
        try:
            data = json.loads(result.stdout.strip())
        except json.JSONDecodeError:
            data = None
        if isinstance(data, dict):
            if data.get("cancelled"):
                return None, NamingOptions()
            options = NamingOptions(
                add_date=bool(data.get("addDate", True)),
                position="after" if data.get("position") == "after" else "before",
                include_time=bool(data.get("includeTime", True)),
                resize=bool(data.get("resize", True)),
            )
            return Path(data["path"]), options

    # Fallback: the open panel failed (not a Cancel) -- log why and use the legacy chooser.
    print(f"JXA open panel failed: {result.stderr.strip()}", file=sys.stderr)
    return choose_watermark_file_legacy(), NamingOptions()


def choose_watermark_file_legacy() -> Optional[Path]:
    """Plain AppleScript 'choose file' dialog (no options); return the picked path, or None if cancelled."""
    script = (
        "POSIX path of (choose file "
        "with prompt \"Add Watermark : Select the image (SVG or PNG)\" "
        "of type {\"public.svg-image\", \"public.png\"})"
    )
    result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    if result.returncode != 0 or not result.stdout.strip():
        return None
    return Path(result.stdout.strip())


def get_date_created(image_path: Path, img: Image.Image) -> datetime:
    """Return when the photo was taken: EXIF DateTimeOriginal first, then the file's creation date."""
    try:
        exif = img.getexif()
        sub_ifd = exif.get_ifd(EXIF_IFD_POINTER)
        candidates = (
            sub_ifd.get(EXIF_DATETIME_ORIGINAL),
            sub_ifd.get(EXIF_DATETIME_DIGITIZED),
            exif.get(EXIF_DATETIME),
        )
        for raw in candidates:
            if not raw:
                continue
            if isinstance(raw, bytes):
                raw = raw.decode("ascii", errors="ignore")
            try:
                return datetime.strptime(raw.strip("\x00 ")[:19], "%Y:%m:%d %H:%M:%S")
            except ValueError:
                continue  # e.g. "0000:00:00 00:00:00" -- try the next tag
    except Exception:  # noqa: BLE001 -- missing/corrupt EXIF: fall back to the file date
        pass

    # No usable EXIF (screenshots, exports...): use the file's creation date (macOS birthtime).
    stat = image_path.stat()
    return datetime.fromtimestamp(getattr(stat, "st_birthtime", stat.st_mtime))


def build_output_name(stem: str, out_ext: str, taken_at: Optional[datetime], options: NamingOptions) -> str:
    """Build '<stem>___photo-MartinDube[ YYMMDD-HHhMM]<ext>' (date before or after, per options)."""
    name = f"{stem}{WATERMARK_SUFFIX}"
    if options.add_date and taken_at is not None:
        stamp = taken_at.strftime(DATE_FORMAT_FULL if options.include_time else DATE_FORMAT_DAY)
        if options.position == "before":
            name = f"{stamp}{DATE_SEPARATOR}{name}"
        else:
            name = f"{name}{DATE_SEPARATOR}{stamp}"
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


def apply_watermark(image_path: Path, wm_path: Path, cache: dict, options: NamingOptions) -> Path:
    """Composite the watermark onto one image, flatten, and save as <name>___photo-MartinDube[ date]<ext>."""
    source = open_image(image_path)
    # Read the capture date before convert(), which drops the EXIF metadata.
    taken_at = get_date_created(image_path, source) if options.add_date else None
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
    out_path = unique_path(image_path.with_name(build_output_name(image_path.stem, out_ext, taken_at, options)))
    save_with_metadata(flattened, out_path, source)
    return out_path


def main() -> int:
    image_paths = [Path(p) for p in sys.argv[1:] if Path(p).suffix.lower() in SUPPORTED_EXT]
    if not image_paths:
        notify("No valid image was received (supported formats: jpg, jpeg, png, webp, heic, heif, avif, tif, tiff, bmp).")
        return 0  # handled: our dialog is enough, avoid Automator's extra error alert

    wm_path, options = choose_watermark_and_options()
    if wm_path is None:
        return 0  # user clicked Cancel: exit quietly (non-zero would trigger Automator's error alert)

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