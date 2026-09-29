# Watermark batch — Automator Quick Action <img width="48px" src="https://static.wikia.nocookie.net/ipod/images/a/ab/Automator.png/revision/latest?cb=20160908152407" alt="Otto the Automator" />

**English** · [Français](README_fr.md)

Adds a watermark (SVG or PNG24) to the bottom-left corner of a batch of images, straight from the Finder.

<img width="60%" src="screenshot_AddWatermark-macOS-modal.avif" alt="Screenshot">

## 1. Install the dependencies (once)

Open your Terminal app and run:

```bash
# Homebrew must already be installed (otherwise: https://brew.sh)
brew install librsvg          # provides rsvg-convert, to rasterize the SVG

which python3                 # note the returned path, e.g. /opt/homebrew/bin/python3
pip3 install -U Pillow        # image processing library (version 11+ required for JPEG XMP)
pip3 install pillow-heif      # HEIC/HEIF/AVIF read support (iPhone photos)
```

`pillow-heif` usually ships its own copy of `libheif` inside the Python package, so there is nothing to install through Homebrew for it. If `pip3 install pillow-heif` ever fails while trying to build from source, run `brew install libheif`, then run the pip command again.

Write down the exact path returned by `which python3`: you will need it in step 3.

> You already have a `cdscript` alias in your `.zshrc` that points to this folder (`/Volumes/usbgt7/aiScripts`). Use it to move there in Terminal if you want to run the commands above from this folder. Note that this alias only exists in your interactive Terminal: Automator doesn't see it (see step 2 below), so it is only useful for manual use.

## 2. Create a symbolic link to the script (already on the external drive)

The script lives permanently on the external drive, in `/Volumes/usbgT7/aiScripts/watermarkImg/`, so there is no need to move or copy it. But Automator refers to the script by an absolute path under `$HOME` (see step 3.6) and doesn't load the aliases from your `.zshrc` (such as `cdscript`), so it can't find the external drive on its own.

The fix, to do once in your Terminal app:

```bash
ln -s /Volumes/usbgT7/aiScripts ~/aiScripts
chmod +x ~/aiScripts/watermarkImg/add_watermark.py
```

This link makes `~/aiScripts/watermarkImg/add_watermark.py` (the path used by Automator in step 3.6) point directly to the real file on `usbgT7`: a single source of truth, no copy to keep up to date. If the `usbgT7` drive is not plugged in, the link stays in place but is broken until you reconnect the drive.

## 3. Create the Quick Action in Automator

1. Open **Automator** (Spotlight → "Automator").
2. **File > New**, choose **Quick Action**.
3. At the top of the document, set:
   - **Workflow receives current** → **image files**
   - **in** → **Finder**
4. In the actions library on the left, search for **Run Shell Script** and drag it into the area on the right.
5. In this action, set:
   - **Shell** → `/bin/zsh`
   - **Pass input** → **as arguments**
6. Still in Automator, replace the content of the script box (in the **Run Shell Script** action) with the following (replacing the `python3` path with the one you noted in step 1):

   ```bash
   /opt/homebrew/bin/python3 "$HOME/aiScripts/watermarkImg/add_watermark.py" "$@"
   ```

   (This path works thanks to the symbolic link created in step 2: it points to the real file on `usbgT7`.)

7. **File > Save**, and give it a clear name, e.g. **Add watermark**.

That's it: no icon to draw, no bundle to sign. Automator takes care of creating everything properly in `~/Library/Services/`.

## 4. Usage

1. In the Finder, select one or more images (jpg, jpeg, png, webp, heic, heif, avif, tif, tiff, bmp).
2. Right-click → **Services** (or directly in the contextual menu, depending on your macOS version) → **Add watermark**.
3. The **Add Watermark** window asks you to choose the watermark SVG (or PNG24) file. At the bottom of that same window, options let you set how the generated files are named (see below).
   - Click **Cancel** to abort everything: the script stops without any message.
4. The script processes all the selected images and shows a summary at the end.

Each original image stays untouched; a watermarked copy is created next to it. For example, with the watermark `ma signature photo.svg`: `photo.jpg` → `photo __ma-signature-photo_s.jpg`.

### Suffix: the watermark file name

The suffix added to the copy's name is the name of the chosen watermark file (without its extension), preceded by a space and two underscores (` __`). This name is first cleaned up to be compatible with the macOS file system:

1. Every character that is neither a letter nor a digit (space, punctuation, symbol, character rejected by macOS such as `:` or `/`) becomes a hyphen `-`.
2. Consecutive hyphens (coming from a double space or `--`, for example) are reduced to a single `-`.
3. Leading and trailing hyphens are removed. Accented letters are kept.

| Watermark file | Resulting suffix |
| --- | --- |
| `ma signature photo.svg` | ` __ma-signature-photo` |
| `logo  (v2)--final.png` | ` __logo-v2-final` |
| `Signé Martin_Dubé!!.svg` | ` __Signé-Martin-Dubé` |

Example: `fileName.jpg` + `ma signature photo.svg` → `fileName __ma-signature-photo.jpg`, or `fileName __ma-signature-photo_s.jpg` with **Resize for sharing** checked.

If the cleaned-up name is empty (e.g. a file named `...svg`), the suffix `watermark` is used instead.

### Options (left area): add the capture date

| Option | Default | Effect |
| --- | --- | --- |
| **Add date created** (switch) | ON | Adds the capture date to the file name, separated by a space. When OFF, both sub-options are hidden and the box shrinks to this single line. |
| 1. **Position relative to file name**: Before / After | Before | Puts the date at the start of the name (Before) or after the suffix (After). |
| 2. **Include hours and minutes** | checked | Format `YYMMDD-HHhMM` (the lowercase "h" separates hours from minutes). Unchecked: `YYMMDD` only. |

Examples for `photo.jpg` taken on September 25, 2026 at 2:32 PM:

- Before (default): `260925-14h32 photo __ma-signature-photo_s.jpg`
- After: `photo __ma-signature-photo_s 260925-14h32.jpg`
- Without hours and minutes: `260925 photo __ma-signature-photo_s.jpg`
- Add date created OFF: `photo __ma-signature-photo_s.jpg`

The date is read from the photo's EXIF metadata (`DateTimeOriginal`, the moment the shot was taken). If the image has no EXIF (screenshot, web export…), the file's creation date is used instead.

The suffix separator and the date formats can be changed at the top of the script: `WATERMARK_SUFFIX_PREFIX`, `DATE_FORMAT_FULL`, `DATE_FORMAT_DAY`, `DATE_SEPARATOR`.

### Option (right area): Resize for sharing

**Resize for sharing** checkbox, checked by default. It scales the image down so its longer side is at most **1350 px**: the height for a portrait photo, the width for a landscape photo. Proportions are kept, and an image that is already smaller is never enlarged.

- When the **Add date created** switch is OFF, the explanatory sentence is hidden too: both areas only show their first line. The checkbox stays clickable.
- When the option is checked, `_s` is added to the suffix: `photo __ma-signature-photo_s.jpg` (unchecked: `photo __ma-signature-photo.jpg`).
- The resize happens before the watermark is added, so the watermark is sized on the final image (15% of its width).
- The dimensions stored in the EXIF (`PixelXDimension` / `PixelYDimension`) are updated.
- The limit can be changed at the top of the script with `RESIZE_MAX_LONG_SIDE`. The window text updates itself.

**Special case HEIC / HEIF / AVIF:** these formats are read without any problem, but the watermarked copy is always saved as `.png` (PNG24, lossless) rather than in the original format (e.g. `IMG_1234.heic` → `260925-14h32 IMG_1234 __ma-signature-photo_s.png`). Properly re-encoding to HEIC/AVIF requires extra encoders that are unreliable to install, whereas PNG avoids any lossy compression. If you then want to convert these PNGs to AVIF, XnConvert.app does the job very well in batch.

## Rules applied by the script

- Position: bottom-left, with a 20 px margin (adjustable via `MARGIN_PX` at the top of the script).
- Watermark width: always 15% of the image width (`WM_WIDTH_RATIO`), with a 50 px minimum for very small images (`MIN_WM_WIDTH`).
- The result is flattened onto an opaque white background before saving.
- An SVG without a `viewBox` (or `viewbox`) attribute is rejected.
- A photo taken in portrait mode (EXIF orientation) is first rotated upright, so the watermark always lands in the visible bottom-left corner.

## Preserved quality and metadata

- **JPEG:** 95% quality (`JPEG_QUALITY`) with full-resolution 4:4:4 colors (`JPEG_SUBSAMPLING = 0`). Above 95%, the file grows a lot with no visible gain.
- **WebP:** saved lossless.
- **ICC color profile** preserved (e.g. the iPhone's Display P3), so colors don't shift.
- **Full EXIF preserved:** camera, lens, settings, dates and geolocation (GPS).
- **Author added** to every copy (`AUTHOR_NAME` and `AUTHOR_URL` constants at the top of the script):
  - EXIF `Artist`: Martin Dubé
  - XMP `dc:creator`: Martin Dubé (the "Creator" field in Lightroom, Photoshop, Bridge)
  - XMP IPTC `CreatorContactInfo › CiUrlWork`: https://photo.martindube.net (the creator's "Website" field)
- If the original image already contains XMP (e.g. from Lightroom), it is kept and these fields are added to it, without overwriting an existing creator or website.
- **Limits:** BMP can't hold any metadata. In TIFF, the EXIF `Artist` field is written without the accent ("Martin Dube"); the XMP keeps "Martin Dubé".

To check a copy's metadata, in your Terminal app (after `brew install exiftool`): `exiftool -a -G1 "file-name.jpg"`.

## Troubleshooting

- **"rsvg-convert not found"** → the Homebrew install didn't complete, or the path in the Automator script doesn't point to the right `python3`/`rsvg-convert` (Apple Silicon: `/opt/homebrew/bin/`, Intel: `/usr/local/bin/`).
- **No dialog appears** → check that **Pass input** is set to **as arguments**, not "to stdin".
- **The options don't show up (old window without options)** → the window with options couldn't open and the script fell back to the old picker, with the default options. To see why, run the script from your Terminal app: `/opt/homebrew/bin/python3 ~/aiScripts/watermarkImg/add_watermark.py ~/Desktop/a-photo.jpg`. The message starting with `JXA open panel failed:` is printed in the Terminal.
- **Debug mode (`WM_DEBUG=1`)** → if the window or the options behave oddly (e.g. after a macOS update: missing options, switch animation that jumps), run the script with this prefix in your Terminal app (drag a real photo from the Finder in place of the example path):

  ```bash
  WM_DEBUG=1 /opt/homebrew/bin/python3 ~/aiScripts/watermarkImg/add_watermark.py ~/Desktop/a-photo.jpg
  ```

  In the window, toggle the switch OFF then ON, then click **Cancel**. `[wm-debug]` lines are then printed in the Terminal:
  - `timer tick OK` / `timers worked: true` → timers work, so the switch animation does too. If it says `false`, the switch changes state without animation.
  - `view count` and `classes` → the internal structure of the system window, useful to understand what changed on the macOS side.
  - `JXA open panel failed: …` → the window with options couldn't open; the message that follows gives the cause.

  This mode doesn't change the script's behavior (if you click **Submit**, the images are processed normally): it only adds this information in the Terminal.
- **Finder alert "The action "Run Shell Script" encountered an error"** → the script shouldn't trigger it anymore (Cancel and known errors end cleanly). If it shows up again, it's an unexpected error: run the script from the Terminal (command above) to see the details.
- **The Quick Action doesn't appear in the Services menu** → in **System Settings > Keyboard > Keyboard Shortcuts > Services**, check that it is checked/enabled.
