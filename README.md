# Watermark batch —  macOS Automator Quick Action <img width="48px" src="https://static.wikia.nocookie.net/ipod/images/a/ab/Automator.png/revision/latest?cb=20160908152407" alt="Otto the Automator" />

**English** · [Français](README_fr.md)

Adds a watermark (SVG or PNG24) to the bottom-left corner of a batch of images, straight from the Finder.

<img width="60%" src="img_watermarkImg.avif" alt="Screenshot">

> Related scripts in `aiScripts/`: to add the capture date to file names, use [`addDateImg`](../addDateImg/README.md); to make file names server friendly (and save AVIF copies), use [`renameForServer`](../renameForServer/README.md).

## How it works

- `add_watermark.py` — the Python script called by the Quick Action. It does all the image processing.
- `AddWatermark.app` — a small native macOS app (source in `AddWatermarkApp/`, built on your Mac with `build_app.sh`) that only shows the **Add Copyrights Watermark to Image** window and posts the end-of-task notification.
- `watermarks/` — the folder where your watermark files (SVG/PNG) live.

If `AddWatermark.app` is missing or fails, the script automatically falls back to a simple native list dialog (see [Fallback and revert](#fallback-and-revert)).

## 1. Install the dependencies (once)

Open your Terminal app and run:

```bash
# Homebrew must already be installed (otherwise: https://brew.sh)
brew install librsvg          # provides rsvg-convert, to rasterize the SVG

# Install the Python libraries for the SAME python3 that Automator uses (step 4.6)
/opt/homebrew/bin/python3 -m pip install -U Pillow pillow-heif
```

- **Pillow** (11+) is the image processing library; **pillow-heif** reads HEIC/HEIF/AVIF (iPhone photos).
- ⚠ A plain `pip3` may install into a different Python than `/opt/homebrew/bin/python3`. Check that the right one has everything:

  ```bash
  /opt/homebrew/bin/python3 -c "import sys, PIL; print(sys.version.split()[0], PIL.__version__)"
  ```

- `pillow-heif` usually ships its own copy of `libheif`. If the install ever fails while trying to build from source, run `brew install libheif`, then the pip command again.
- **Xcode Command Line Tools** are needed to build the app (step 3). Check with `xcode-select -p`; if it prints an error, run `xcode-select --install`.

> You already have a `cdscript` alias in your `.zshrc` that points to this folder (`/Volumes/usbgt7/aiScripts`). Use it to move there in Terminal if you want to run commands from this folder. Note that this alias only exists in your interactive Terminal: Automator doesn't see it (see step 2 below), so it is only useful for manual use.

## 2. Create a symbolic link to the scripts folder (already on the external drive)

> <mark>⚠</mark> IMPORTANT NOTE: In the following instructions the term « <mark>usbgT7</mark> » refers to my personnal external USB hard drive. If your script is on your macOS's main hard drive, disregard this step (#2).

The scripts live permanently on the external drive, in `/Volumes/usbgT7/aiScripts/`, so there is no need to move or copy them. But Automator refers to the script by an absolute path under `$HOME` (see step 4.6) and doesn't load the aliases from your `.zshrc` (such as `cdscript`), so it can't find the external drive on its own.

The fix, to do once in your Terminal app:

```bash
ln -s /Volumes/usbgT7/aiScripts ~/aiScripts
```

This single link covers every script folder in `aiScripts/` (this one, `addDateImg/`, `renameForServer/`). If the `usbgT7` drive is not plugged in, the link stays in place but is broken until you reconnect the drive.

## 3. Build the app (once, and after any change to `AddWatermarkApp/`)

In your Terminal app:

```bash
~/aiScripts/watermarkImg/build_app.sh
```

It ends with `Built: …/AddWatermark.app`. The app is built and signed locally (ad-hoc signature), so macOS doesn't block it. It is git-ignored: each Mac builds its own.

## 4. Create the Quick Action in Automator

1. Open **Automator** (Spotlight → "Automator").
2. **File > New**, choose `Quick Action`.
3. At the top of the document, set:
   - **Workflow receives current** → `image files`
   - **in** → `Finder`
   - **Image** (*optional, choose from the list an icons to associate to this script*) → `Tag`
4. In the actions library on the left, search for **Run Shell Script** and drag it into the area on the right.
5. In this action, set:
   - **Shell** → `/bin/zsh`
   - **Pass input** → `as arguments`
6. Still in Automator, replace the content of the script box (in the **Run Shell Script** action) with:

   ```bash
   /opt/homebrew/bin/python3 "$HOME/aiScripts/watermarkImg/add_watermark.py" "$@"
   ```

   (This path works thanks to the symbolic link created in step 2: it points to the real file on `usbgT7`.)

7. **File > Save**, and give it a clear name, e.g. **Add watermark to image file**.

Automator saves it in `~/Library/Services/`. To edit it later: in Automator, **Open an Existing Document…**, press **Cmd+Shift+G**, type `~/Library/Services` and pick the `.workflow` file.

## 5. Add your watermark files

Copy your watermark files (SVG preferred, PNG24 accepted) into `watermarks/`. An SVG must have a `viewBox` (or `viewbox`) attribute.

## 6. Usage

1. In the Finder, select one or more images (jpg, jpeg, png, webp, heic, heif, avif, tif, tiff, bmp).
2. Right-click → **Quick Actions** (or **Services**, depending on your macOS version) → **Add watermark to image file**.
3. The **Add Copyrights Watermark to Image** window opens with the last watermark you used (or the first file of `watermarks/`):

   | Element | Effect |
   | --- | --- |
   | Preview (128 × 128) and **File** | The selected watermark. The dashed square in the preview's bottom-left corner shows where the watermark goes. |
   | **Apply this watermark to** | Number of selected images. |
   | **Resize for Sharing** (switch) | Downscales the copies (see below). Its last state is remembered. |
   | **Change Watermark…** | Opens a file chooser (starting in `watermarks/`) to pick another SVG/PNG. The choice is remembered. |
   | **Cancel** (or **Esc**) | Stops everything, without any message. |
   | **Submit** (or **Return**) | Processes the images. |

   The red button closes the window like **Cancel**; the yellow one minimizes it to the Dock. With keyboard navigation on, **Tab** goes Submit → Resize for Sharing → Change Watermark… → Cancel.
4. When everything is done, a **notification** confirms it (e.g. "12 image(s) processed successfully."). If some images failed, a dialog lists the errors instead.

Each original image stays untouched; a watermarked copy is created next to it. For example, with the watermark `ma signature photo.svg`: `photo.jpg` → `photo__ma-signature-photo_s.jpg`.

### Suffix: the watermark file name

The suffix added to the copy's name is the name of the chosen watermark file (without its extension), preceded by two underscores (`__`). This name is first cleaned up to be compatible with the macOS file system:

1. Every character that is neither a letter nor a digit (space, punctuation, symbol, character rejected by macOS such as `:` or `/`) becomes a hyphen `-`.
2. Consecutive hyphens (coming from a double space or `--`, for example) are reduced to a single `-`.
3. Leading and trailing hyphens are removed. Accented letters are kept.
4. A leading number used to order the files in `watermarks/` (e.g. `1 `, `02-`, `3_`) is left out.

| Watermark file | Resulting suffix |
| --- | --- |
| `ma signature photo.svg` | `__ma-signature-photo` |
| `logo  (v2)--final.png` | `__logo-v2-final` |
| `Signé Martin_Dubé!!.svg` | `__Signé-Martin-Dubé` |
| `2 logo.png` | `__logo` |

Example: `fileName.jpg` + `ma signature photo.svg` → `fileName__ma-signature-photo.jpg`, or `fileName__ma-signature-photo_s.jpg` with **Resize for Sharing** on.

If the cleaned-up name is empty (e.g. a file named `...svg`), the suffix `watermark` is used instead. The separator can be changed at the top of the script with `WATERMARK_SUFFIX_PREFIX`.

### Resize for Sharing

Scales the image down so its longer side is at most **1350 px**: the height for a portrait photo, the width for a landscape photo. Proportions are kept, and an image that is already smaller is never enlarged.

- When it is on, `_s` is added to the suffix: `photo__ma-signature-photo_s.jpg` (off: `photo__ma-signature-photo.jpg`).
- The resize happens before the watermark is added, so the watermark is sized on the final image (15% of its width).
- The dimensions stored in the EXIF (`PixelXDimension` / `PixelYDimension`) are updated.
- The limit can be changed at the top of the script with `RESIZE_MAX_LONG_SIDE` (the window shows the value it receives).

**Special case HEIC / HEIF / AVIF:** these formats are read without any problem, but the watermarked copy is always saved as high-quality `.jpg` (95%, 4:4:4 colors) rather than in the original format (e.g. `IMG_1234.heic` → `IMG_1234__ma-signature-photo_s.jpg`): re-encoding to HEIC/AVIF needs extra encoders that are unreliable to install. To get AVIF files afterwards, use [`renameForServer`](../renameForServer/README.md) with its AVIF option.

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

## Fallback and revert

The native window was added because, since macOS 27.2, the file chooser opened by a script launched from the Finder lost most clicks. If the app ever becomes unstable:

- **Instant fallback, no code change:** in the Finder, delete or rename `AddWatermark.app`. The script then shows a native list dialog instead: every file of `watermarks/` twice (`— resize for sharing` / `— full size`) plus `Other file…`, with the last choice preselected.
- **Force the list for a test**, in your Terminal app: `WM_FORCE_LIST=1 /opt/homebrew/bin/python3 ~/aiScripts/watermarkImg/add_watermark.py ~/Desktop/a-photo.jpg`
- **Back to the list-only code:** the git tag `list-version` holds the version before the app (`git checkout list-version -- add_watermark.py`).

## Troubleshooting

- **"rsvg-convert not found"** → the Homebrew install didn't complete (Apple Silicon: `/opt/homebrew/bin/`, Intel: `/usr/local/bin/`).
- **The list dialog shows up instead of the window** → `AddWatermark.app` is missing or failed: rebuild it (step 3). To see why it failed, run the script from your Terminal app (command above, without `WM_FORCE_LIST=1`): the message starting with `AddWatermark.app gave no answer` is printed there.
- **Permission alert "… wants access to control Finder"** → click **Allow**: the list dialog and some messages are shown by the Finder so they get the focus. You can review it in **System Settings › Privacy & Security › Automation**.
- **No notification at the end** → the first time, macOS asks whether **Add Watermark** may send notifications: click **Allow**. Check **System Settings › Notifications › Add Watermark** (alert style **Temporary**), and that no Focus mode is on: a Focus hides banners. If macOS refuses notifications for the app, a small dialog that closes itself after 3 seconds is shown instead.
- **No dialog appears at all** → check that **Pass input** is set to `as arguments`, not "to stdin".
- **Finder alert "The action "Run Shell Script" encountered an error"** → unexpected error: run the script from the Terminal (command above) to see the details.
- **The Quick Action doesn't appear in the menu** → in **System Settings › Keyboard › Keyboard Shortcuts › Services**, check that it is enabled. Relaunching the Finder (**Option**+right-click on its Dock icon → **Relaunch**) can help.
