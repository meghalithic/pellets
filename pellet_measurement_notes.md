# Pellet width measurement tool: notes for future use

A summary of how the tool was built, how to run it, and how to fix common problems. It is organised by topic rather than as a word-for-word transcript.

## 1. What this is

A Python command-line tool (`measure_pellets.py`) that:

- reads a folder of photos (JPG, PNG, TIFF, BMP and camera RAW such as **CR2**);
- finds the pellets (dark ovals on a white background);
- measures each pellet's **width in mm** (shortest axis, across the middle of the pellet, perpendicular to its long axis);
- writes a **CSV** and a **check image** for every photo.

Built with open-source packages: scikit-image (detection, and the watershed step that separates touching pellets), SciPy, pandas, matplotlib, and rawpy (reads CR2).

Why Python and not R: Python has the stronger computer-vision libraries (OpenCV, scikit-image). R was not needed.

Files to keep together in one folder:

- `measure_pellets.py`: the tool (always use the **latest** version)
- `requirements.txt`: the list of packages it needs

## 2. One-time setup (Mac / Terminal)

A fresh, isolated "virtual environment" avoids version clashes with other Python packages on the computer. An earlier pandas/numpy clash was fixed this way.

```
cd ~/Desktop/pellet_measure
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

- **Each new Terminal session:** run `cd ~/Desktop/pellet_measure` and `source venv/bin/activate` first. `(venv)` appears at the start of the prompt.
- **To leave the environment:** type `deactivate`.

## 3. Everyday command

```
python measure_pellets.py ./photos/ --same-scale --exclude
```

### What happens

For each photo, windows open in this order:

1. **Step 1, scale:** click two points on the ruler, as far apart as possible (for example the 0 mm and 100 mm marks). Then type the real distance between them in mm in the Terminal. With `--same-scale` this is only asked for the **first** image, and the same scale is reused for the others.
2. **Step 2, ignore areas** (with `--exclude`): outline the **scale bar** first, then the **ID card**, by clicking around each one.
   - Click corner by corner, just outside the edge. The shape can be anything, for example an L for an L-shaped ruler.
   - **Right-click** undoes the last point.
   - Press **Enter** when you have gone all the way round.
   - Pressing **Enter straight away** skips an area that is not in that photo.
   - At least 3 points are needed. With fewer, the Terminal warns you and the area is *not* ignored.

The tool then measures the pellets.

### Where results go

A `results/` folder is created inside the photo folder:

| File | Contents |
|---|---|
| `measurements.csv` | one row per pellet |
| `<photo>_annotated.png` | check image (saved at most about 2000 px wide) |

Saved in the photo folder itself:

| File | Contents |
|---|---|
| `calibration.csv` | the saved scale (px per mm) |
| `exclusions.csv` | the saved ignore outlines |

### CSV columns

| Column | Meaning |
|---|---|
| `image` | photo file name |
| `pellet_id` | number of the pellet within that photo (matches the number printed on the check image) |
| `x_px`, `y_px` | pellet centre, in pixels from the top-left of the photo |
| `width_mm` | **width at the midpoint** (the main measurement) |
| `width_max_mm` | the widest point anywhere along the pellet (for comparison) |
| `px_per_mm` | the scale used (should be the same on every row if the camera setup never changed) |

### Reading the check image

- **Red outline + blue number:** a pellet that was measured.
- **Orange outline + word:** an object that was found but **rejected**, with the reason (`too big`, `too small`, `edge`, `too thin`). Orange can look yellow.
- **Grey dashed outline:** an ignore area you drew.

### Reading the Terminal summary line

```
scale 16.72 px/mm | 157 pellets kept | rejected: 1 too thin, 4 too big, 1 edge | inside ignore areas: 0
```

- **Scale:** if this looks wrong, redo the scale (`--redo`).
- **"too big":** clumps of touching pellets, or large patches of background picked up as pellet.
- **"edge":** the object touches the photo border (these are skipped on purpose).
- **"inside ignore areas":** how many objects were dropped because they sit inside your outlines. A large number means an outline covers pellets.

## 4. All options

| Option | What it does |
|---|---|
| `--same-scale` | Calibrate once (first image) and reuse that scale for all images. Only valid if camera height and zoom never change. Spelled **with a hyphen**. |
| `--exclude` | Ask for outlines of the scale bar and ID card on **every** image, then ignore objects inside them. |
| `--same-areas` | With `--exclude`: outline once (first image) and reuse for all images. Only if the ruler and card never move. |
| `--redo` | Forget the saved scale and saved outlines, and ask again. Use it only to fix a mistake or start a new setup; otherwise it asks every time. |
| `--px-per-mm 12.5` | Give the scale directly and skip the ruler clicking. |
| `--pellet-width-mm 4` | Typical pellet width (default 4). Controls how deep a "pinch" between two touching pellets must be before they are split. |
| `--no-split` | Do not split touching pellets. |
| `--threshold 0.8` | Brightness cut-off relative to the background (background = 1.0). Try about 0.8 for pale pellets, about 0.6 for dark ones, if detection looks wrong. Default is automatic. |
| `--no-flatten` | Skip the uneven-lighting correction. |
| `--min-area-mm2 2` / `--max-area-mm2 300` | Ignore objects smaller or larger than this area. |
| `--max-aspect 5` | Ignore objects longer and thinner than this (to drop rulers). |

## 5. Common workflows

**After redoing the scale or outlines:** run the normal command **without** `--redo`:

```
python measure_pellets.py ./photos/ --same-scale --exclude
```

**Adding new images** (same camera setup): put them in the same photos folder and run the same command.

- Old images reuse their saved scale and outlines.
- New images get the saved scale and ask for outlines only.
- `measurements.csv` is rewritten with all images.

**New images with a different camera setup (different scale):** leave out `--same-scale`:

```
python measure_pellets.py ./photos/ --exclude
```

Old images keep their saved scale. Only the new ones ask you to click the ruler.

**Start completely over:**

```
python measure_pellets.py ./photos/ --same-scale --exclude --redo
```

**A new folder** starts fresh and asks for the scale and outlines again.

## 6. Troubleshooting log (what went wrong, and the fix)

| Symptom | Cause | Fix |
|---|---|---|
| Error `numpy.dtype size changed` when importing pandas | Clashing package versions on the Mac | Use a fresh virtual environment (section 2) |
| Script ignored CR2 files | RAW support was missing | Added `rawpy`; CR2/CR3/NEF/ARW/DNG/ORF/RW2 now work |
| Asked to calibrate every picture | Default behaviour | Use `--same-scale` |
| Couldn't redo the ignore boxes | Choices are saved | Use `--redo` |
| Ruler is L-shaped, a box excluded too much | Boxes were rectangles | Switched to free-shape outlines |
| CSV nearly empty, no outlines on the check image | Windows appeared in a different order than described, and the scale/areas got mixed up | Fixed the order: scale first, then ignore areas; windows now say "STEP 1" or "STEP 2" |
| "too big" huge areas, only 2 of 50+ pellets kept | Uneven lighting and shadows were picked up as pellet, merging into giant objects | Added lighting correction before detection (**most likely main fix**) |
| Ignoring the ID card/ruler made detection worse | Painting areas white changed the detection itself | Detection now runs on the untouched photo; objects mostly inside an outline are dropped afterwards |
| Single pellets cut in two | A symmetric pellet had two exactly equal peaks in the distance map | Fixed with a tiny tie-breaking jitter, and a split threshold tied to pellet width |
| Large check images | Full-size RAW | Check images are now saved at most about 2000 px wide |
| Outline placement for items that move between photos | `--same-scale` also reused outlines | Outlines are now per image; `--same-areas` is the opt-in to reuse them |

Final result on the user's real photos: **157 pellets kept**, with 4 too big, 1 too thin and 1 edge rejected. The "too big" ones were still worth a look.

## 7. Limits and honest caveats

- The tool was tested on **computer-drawn test images** (including 50 pellets under uneven light, an L-shaped ruler, an ID card, and touching pellets), where widths came out within about 0.1 mm of the true values. The click-selection windows were tested with simulated clicks.
- It was used on the user's real photos, but accuracy there hasn't been checked against hand measurements. **Spot-check a few pellets with calipers or a manual measurement.**
- Very dirty, cracked or pale subfossil pellets may need `--threshold` adjusted.
- Pellets that touch with a wide contact (no clear pinch between them) may not be split. Check "too big" orange outlines.
- Pellets touching the photo edge are skipped on purpose.
- Higher-resolution photos give better width measurements, because each pixel adds a little error.
- Accuracy depends on a correct scale: click the ruler points far apart and type the right distance.
- The scale is only valid if the camera height and zoom are identical across the photos it is applied to.

## 8. Quick sanity checks for any run

1. Most `width_mm` values fall in the expected range (here about 3-5 mm). A few much smaller or larger values usually mean a merged clump or a fragment.
2. `px_per_mm` is the same on every row (if the setup never changed).
3. Open a check image: red outlines should sit on single pellets, and orange outlines should be clumps, debris, the ruler or the card.
4. Compare the number of pellets kept with what you can count by eye.
