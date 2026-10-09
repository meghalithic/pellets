#!/usr/bin/env python3
"""
Measure the width of ovate pellets in photos taken on a white background.

Usage:
    python measure_pellets.py PHOTO_FOLDER
    python measure_pellets.py PHOTO_FOLDER --px-per-mm 12.5     (skip calibration clicking)
    python measure_pellets.py PHOTO_FOLDER --same-scale --exclude
        (calibrate once, reuse the scale for all images; outline the scale bar / ID card
         on every image, since they are not always in the same place)
    add --same-areas to outline them once only and reuse the outlines for all images
    add --redo to forget saved scales/outlines and be asked again

For each image you click two points on the ruler and type the real distance
between them (in mm). Calibrations are saved in PHOTO_FOLDER/calibration.csv,
so you only do this once per image.

Outputs (in PHOTO_FOLDER/results/):
    measurements.csv      one row per pellet
    <image>_annotated.png check image with outlines and pellet IDs
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import ndimage as ndi
from skimage import io, color, filters, morphology, measure, segmentation, feature, util, draw, transform
from matplotlib.figure import Figure
from matplotlib.patches import Polygon
from matplotlib.backends.backend_agg import FigureCanvasAgg

RAW_EXTS = {".cr2", ".cr3", ".nef", ".arw", ".dng", ".orf", ".rw2"}  # camera RAW files
EXTS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp"} | RAW_EXTS


def load_image(path):
    if path.suffix.lower() in RAW_EXTS:
        import rawpy  # only needed for RAW files
        with rawpy.imread(str(path)) as raw:
            img = raw.postprocess(use_camera_wb=True, output_bps=8)
    else:
        img = io.imread(path)
    if img.ndim == 2:
        img = np.dstack([img] * 3)
    img = img[..., :3]
    rgb = util.img_as_ubyte(img)
    gray = color.rgb2gray(rgb)
    return rgb, gray


def calibrate_interactive(rgb, name):
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(12, 8))
    ax.imshow(rgb)
    ax.set_title(f"STEP 1 (scale) - {name}: click two points on the ruler "
                 "(far apart is more accurate), then type their distance in mm in the Terminal")
    pts = plt.ginput(2, timeout=0)
    plt.close(fig)
    if len(pts) < 2:
        raise SystemExit("Calibration cancelled.")
    px = float(np.hypot(pts[0][0] - pts[1][0], pts[0][1] - pts[1][1]))
    mm = float(input(f"[{name}] Real distance between the two points in mm: "))
    return px / mm


def flatten_background(gray, px_per_mm):
    """Divide out uneven lighting/shadows so the background is ~1.0 everywhere.

    The background level is estimated on a shrunken copy: a grey 'closing' wipes out
    anything darker and smaller than ~15 mm (pellets, ruler ticks), leaving only the
    smooth lighting; dividing by it makes the paper evenly bright.
    """
    f = max(1, int(round(0.6 * px_per_mm)))  # shrink factor
    small = transform.downscale_local_mean(gray, (f, f))
    r = max(3, int(round(15 * px_per_mm / f)))  # ~15 mm, in shrunken pixels
    bg = ndi.grey_closing(small, size=(2 * r + 1, 2 * r + 1))
    bg = filters.gaussian(bg, r / 2)
    bg = transform.resize(bg, gray.shape, order=1, mode="edge")
    return np.clip(gray / np.maximum(bg, 0.05), 0, 1.2)


def segment(gray, px_per_mm, min_width_mm, min_area_px, split_touching=True, threshold=None,
            flatten=True):
    if flatten:
        gray = flatten_background(gray, px_per_mm)
    smooth = filters.gaussian(gray, 1)
    if threshold is None:
        # Otsu picks the cut-off automatically; capped so an empty/noisy background
        # (brightness ~1.0) can never be mistaken for pellet.
        threshold = min(filters.threshold_otsu(smooth), 0.9)
    mask = smooth < threshold  # pellets are darker than the background
    # Fill light holes inside pellets, but NOT for objects touching the photo edge:
    # a dark table around a sheet of white paper would otherwise "enclose" the
    # paper and swallow every pellet on it into one giant object.
    lab0 = measure.label(mask)
    edge = np.unique(np.concatenate([lab0[0], lab0[-1], lab0[:, 0], lab0[:, -1]]))
    touching = np.isin(lab0, edge[edge > 0])
    mask = (mask & touching) | ndi.binary_fill_holes(mask & ~touching)
    mask = ndi.binary_opening(mask, structure=morphology.disk(2))
    # drop tiny specks
    lab = measure.label(mask)
    sizes = np.bincount(lab.ravel())
    keep = sizes >= min_area_px
    keep[0] = False
    mask = keep[lab]
    base = measure.label(mask)
    if not split_touching:
        return base
    # Split touching pellets at "necks": a new seed is only made where the
    # distance map rises by more than h above the saddle between two blobs.
    # (A plain local-maximum search wrongly cuts long single pellets in two.)
    dist = filters.gaussian(ndi.distance_transform_edt(mask), 1)
    # Required "neck depth" = 25% of a typical pellet's half-width, so ordinary wiggles in
    # the outline of ONE pellet never cause a split, but a real pinch between two does.
    h = max(2.0, 0.25 * 0.5 * px_per_mm * min_width_mm)
    # A symmetric pellet can have two peaks of EXACTLY equal height with only a shallow dip
    # between them; h_maxima keeps both. A tiny random jitter breaks such ties so the
    # shallower peak is absorbed (its dip is smaller than h).
    rng = np.random.default_rng(0)
    dist_j = dist + rng.uniform(0, 1e-3, dist.shape)
    markers = measure.label(morphology.h_maxima(dist_j, h))
    return segmentation.watershed(-dist, markers, mask=mask)


def measure_region(region):
    """Width = cross-section perpendicular to the long axis, at its midpoint."""
    pts = region.coords.astype(float)  # (row, col)
    c = pts.mean(axis=0)
    evals, evecs = np.linalg.eigh(np.cov((pts - c).T))
    major, minor = evecs[:, 1], evecs[:, 0]
    u, v = (pts - c) @ major, (pts - c) @ minor
    length = u.max() - u.min() + 1
    mid = (u.max() + u.min()) / 2
    band = np.abs(u - mid) <= max(1.0, 0.02 * length)
    width_mid = v[band].max() - v[band].min() + 1
    # widest cross-section anywhere along the pellet (for comparison)
    bins = np.round(u).astype(int)
    width_max = max(v[bins == b].max() - v[bins == b].min() + 1 for b in np.unique(bins))
    return width_mid, width_max, length


def select_exclusions(rgb, name):
    """Click around each area to ignore (scale bar, ID card): any shape, e.g. an L."""
    import matplotlib.pyplot as plt
    shapes = []
    # One area at a time, so each gets its own window and clear instructions.
    for what in ("the SCALE BAR / ruler", "the ID CARD"):
        fig, ax = plt.subplots(figsize=(12, 8))
        ax.imshow(rgb)
        for poly in shapes:  # show what is already marked
            ax.add_patch(Polygon(poly, closed=True, fill=False, ec="red", lw=1.5, ls="--"))
        ax.set_title(f"STEP 2 (ignore areas) - {name}: click around the outline of {what}, "
                     "corner by corner (just outside its edge).\nRight-click = undo last point.  "
                     "Press Enter when finished (Enter straight away = skip).", fontsize=10)
        pts = plt.ginput(-1, timeout=0)
        plt.close(fig)
        if len(pts) >= 3:
            shapes.append([(float(x), float(y)) for x, y in pts])
        elif pts:
            print(f"   Only {len(pts)} point(s) clicked for {what} - need at least 3, so it was NOT ignored.")
    return shapes


def apply_exclusions(gray, shapes):
    gray = gray.copy()
    for poly in shapes:
        xs, ys = zip(*poly)
        rr, cc = draw.polygon(ys, xs, shape=gray.shape)
        gray[rr, cc] = 1.0  # paint white = background
    return gray


def annotate(rgb, labels, kept_ids, out_path, shapes=(), rejected=None):
    # Save the check image at most ~2000 px wide so full-size RAW photos give small, shareable files
    s = min(1.0, 2000 / max(rgb.shape[:2]))
    fig = Figure(figsize=(rgb.shape[1] * s / 100, rgb.shape[0] * s / 100), dpi=100)
    FigureCanvasAgg(fig)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.imshow(rgb)
    ax.axis("off")
    for pid, region_label in kept_ids.items():
        m = labels == region_label
        for cnt in measure.find_contours(m.astype(float), 0.5):
            ax.plot(cnt[:, 1], cnt[:, 0], color="red", lw=1.2)
        cy, cx = ndi.center_of_mass(m)
        ax.text(cx, cy, str(pid), color="blue", fontsize=10, ha="center", va="center",
                bbox=dict(facecolor="white", alpha=0.6, pad=1, lw=0))
    for region_label, why in (rejected or {}).items():  # rejected objects: orange + reason
        m = labels == region_label
        for cnt in measure.find_contours(m.astype(float), 0.5):
            ax.plot(cnt[:, 1], cnt[:, 0], color="orange", lw=1.2)
        cy, cx = ndi.center_of_mass(m)
        ax.text(cx, cy, why, color="darkorange", fontsize=9, ha="center", va="center",
                bbox=dict(facecolor="white", alpha=0.6, pad=1, lw=0))
    for poly in shapes:  # ignored areas, dashed grey
        ax.add_patch(Polygon(poly, closed=True, fill=False, ec="gray", lw=1.5, ls="--"))
    fig.savefig(out_path)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder", type=Path)
    ap.add_argument("--px-per-mm", type=float, help="use this scale for all images instead of clicking")
    ap.add_argument("--same-scale", action="store_true",
                    help="calibrate once (first image) and reuse that scale for all images")
    ap.add_argument("--exclude", action="store_true",
                    help="outline areas to ignore (scale bar, ID card; any shape). You are asked "
                         "for them on every image, unless you also use --same-areas")
    ap.add_argument("--same-areas", action="store_true",
                    help="with --exclude: outline the ignore areas once (first image) and reuse them "
                         "for all images (only if the ruler/ID card never move)")
    ap.add_argument("--redo", action="store_true",
                    help="forget the saved scale and ignore-areas and ask for them again")
    ap.add_argument("--min-area-mm2", type=float, default=2.0, help="ignore objects smaller than this")
    ap.add_argument("--max-area-mm2", type=float, default=300.0, help="ignore objects larger than this")
    ap.add_argument("--max-aspect", type=float, default=5.0, help="ignore objects longer/thinner than this (ruler)")
    ap.add_argument("--pellet-width-mm", type=float, default=4.0,
                    help="typical pellet width in mm; sets how deep a 'neck' must be to split "
                         "touching pellets (default 4)")
    ap.add_argument("--no-split", action="store_true", help="do not split touching pellets")
    ap.add_argument("--threshold", type=float,
                    help="brightness cut-off relative to the background (background = 1.0): anything "
                         "darker counts as pellet. Default: chosen automatically. "
                         "Try e.g. 0.8 (pale pellets) or 0.6 (dark) if detection looks wrong")
    ap.add_argument("--no-flatten", action="store_true",
                    help="skip the uneven-lighting correction")
    args = ap.parse_args()

    out_dir = args.folder / "results"
    out_dir.mkdir(exist_ok=True)
    cal_path = args.folder / "calibration.csv"
    cal = dict(pd.read_csv(cal_path).values) if cal_path.exists() and not args.redo else {}

    exc_path = args.folder / "exclusions.csv"
    exc = {}  # image name -> list of ignored areas, each a list of (x, y) outline points
    if exc_path.exists() and not args.redo:
        df = pd.read_csv(exc_path)
        for name, grp in df.groupby("image", sort=False):
            exc[name] = []
            if "x0" in df.columns:  # older box-format file: convert boxes to outlines
                for r in grp.dropna(subset=["x0"]).itertuples():
                    exc[name].append([(r.x0, r.y0), (r.x1, r.y0), (r.x1, r.y1), (r.x0, r.y1)])
            else:
                for _, a in grp.dropna(subset=["area"]).groupby("area", sort=True):
                    exc[name].append(list(zip(a.x, a.y)))

    def save_exclusions():
        recs = []
        for name, polys in exc.items():
            pts = [(name, i, x, y) for i, poly in enumerate(polys) for x, y in poly]
            recs += pts or [(name, np.nan, np.nan, np.nan)]
        pd.DataFrame(recs, columns=["image", "area", "x", "y"]).to_csv(exc_path, index=False)

    images = sorted(p for p in args.folder.iterdir() if p.suffix.lower() in EXTS)
    if not images:
        raise SystemExit(f"No images found in {args.folder}")

    rows = []
    for path in images:
        rgb, gray = load_image(path)
        # STEP 1: scale (ruler clicks)
        ppm = args.px_per_mm or cal.get(path.name)
        if ppm is None and args.same_scale and cal:
            ppm = list(cal.values())[0]  # reuse the first calibration
            cal[path.name] = ppm
        if ppm is None:
            ppm = calibrate_interactive(rgb, path.name)
            cal[path.name] = ppm
            pd.DataFrame(sorted(cal.items()), columns=["image", "px_per_mm"]).to_csv(cal_path, index=False)

        # STEP 2: areas to ignore (scale bar, ID card)
        shapes = []
        ignore_mask = np.zeros(gray.shape, dtype=bool)
        if args.exclude:
            if path.name in exc:
                shapes = exc[path.name]
            elif args.same_areas and exc:
                shapes = list(exc.values())[0]  # reuse the first image's areas
                exc[path.name] = shapes
            else:
                shapes = select_exclusions(rgb, path.name)
                exc[path.name] = shapes
                save_exclusions()
            # The photo itself is left untouched; objects mostly inside these areas are dropped below.
            for poly in shapes:
                xs, ys = zip(*poly)
                rr, cc = draw.polygon(ys, xs, shape=gray.shape)
                ignore_mask[rr, cc] = True

        min_area_px = args.min_area_mm2 * ppm ** 2
        labels = segment(gray, ppm, args.pellet_width_mm, min_area_px, not args.no_split, args.threshold,
                          flatten=not args.no_flatten)

        kept, pid = {}, 0
        rejected = {}  # label -> reason, drawn in orange on the check image
        ignored = 0    # objects dropped because they lie inside an ignore area
        h, w = labels.shape
        for r in measure.regionprops(labels):
            if ignore_mask[r.coords[:, 0], r.coords[:, 1]].mean() >= 0.5:
                ignored += 1
                continue
            area_mm2 = r.area / ppm ** 2
            r0, c0, r1, c1 = r.bbox
            touches_border = r0 == 0 or c0 == 0 or r1 == h or c1 == w
            aspect = r.axis_major_length / max(r.axis_minor_length, 1e-6)
            if area_mm2 < args.min_area_mm2:
                rejected[r.label] = "too small"
                continue
            if area_mm2 > args.max_area_mm2:
                rejected[r.label] = "too big"
                continue
            if touches_border:
                rejected[r.label] = "edge"
                continue
            if aspect > args.max_aspect:
                rejected[r.label] = "too thin"
                continue
            width_mid, width_max, length = measure_region(r)
            pid += 1
            kept[pid] = r.label
            cy, cx = r.centroid
            rows.append({
                "image": path.name,
                "pellet_id": pid,
                "x_px": round(cx, 1),
                "y_px": round(cy, 1),
                "width_mm": round(width_mid / ppm, 3),
                "width_max_mm": round(width_max / ppm, 3),
                "px_per_mm": round(ppm, 3),
            })
        annotate(rgb, labels, kept, out_dir / f"{path.stem}_annotated.png", shapes, rejected)
        why = {}
        for reason in rejected.values():
            why[reason] = why.get(reason, 0) + 1
        why_txt = ", ".join(f"{n} {reason}" for reason, n in why.items()) or "none"
        print(f"{path.name}: scale {ppm:.2f} px/mm | {pid} pellets kept | rejected: {why_txt}"
              f" | inside ignore areas: {ignored}")
        if pid == 0:
            print("   -> nothing kept. Open the _annotated.png: orange outlines show what was found "
                  "and why it was rejected. If the scale looks wrong, rerun with --redo.")

    cols = ["image", "pellet_id", "x_px", "y_px", "width_mm", "width_max_mm", "px_per_mm"]
    pd.DataFrame(rows, columns=cols).to_csv(out_dir / "measurements.csv", index=False)
    print(f"\nDone. See {out_dir}")


if __name__ == "__main__":
    main()
