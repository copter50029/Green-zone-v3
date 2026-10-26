"""Display Green-zone-v3 masks and save PNG previews."""

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap
from matplotlib.patches import Patch
import rasterio
from rasterio.enums import Resampling


PROJECT_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = PROJECT_DIR / "Green-zone-v3" / "Final_Results"
SCENES = ("Theosmain")


def save_preview(input_path: Path, output: Path):
    with rasterio.open(input_path) as src:
        if src.count < 1:
            raise ValueError(f"No raster bands found in {input_path}")

        scale = min(1, 3000 / max(src.width, src.height))
        width = max(1, round(src.width * scale))
        height = max(1, round(src.height * scale))
        mask = src.read(
            1,
            out_shape=(height, width),
            masked=True,
            resampling=Resampling.nearest,
        )
        extent = (
            src.bounds.left,
            src.bounds.right,
            src.bounds.bottom,
            src.bounds.top,
        )
        crs = src.crs
        nodata = src.nodata

    fig, ax = plt.subplots(figsize=(10, 8))
    image = ax.imshow(
        mask,
        cmap=ListedColormap(["#d9d9d9", "#22a447"]),
        vmin=0,
        vmax=1,
        interpolation="nearest",
        extent=extent,
    )
    image.cmap.set_bad((1, 1, 1, 0))
    ax.set_title(input_path.name)
    ax.set_xlabel(f"Easting ({crs})" if crs else "Column")
    ax.set_ylabel(f"Northing ({crs})" if crs else "Row")
    ax.legend(
        handles=[
            Patch(color="#22a447", label="Mask value 1"),
            Patch(color="#d9d9d9", label="Mask value 0"),
            Patch(facecolor="white", edgecolor="#888888", label=f"NoData ({nodata})"),
        ],
        loc="upper right",
    )
    fig.tight_layout()
    fig.savefig(output, dpi=160)
    print(f"Preview saved to: {output}")
    return fig


def main():
    parser = argparse.ArgumentParser(description="View Green-zone-v2 GeoTIFF masks.")
    parser.add_argument(
        "input",
        nargs="?",
        type=Path,
        help="View only this mask instead of all configured scene masks",
    )
    parser.add_argument(
        "--scene",
        choices=SCENES,
        help="View only this scene instead of all configured scene masks",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="PNG path for one mask, or output directory when processing all scenes",
    )
    parser.add_argument(
        "--no-show",
        action="store_true",
        help="Save the preview without opening a plot window.",
    )
    args = parser.parse_args()

    if args.input and args.scene:
        parser.error("Use either an input path or --scene, not both.")

    if args.input:
        input_paths = [args.input]
    elif args.scene:
        input_paths = [OUTPUT_DIR / args.scene / "green_mask_round1.tif"]
    else:
        input_paths = [
            OUTPUT_DIR / scene / "green_mask_round1.tif"
            for scene in SCENES
        ]

    missing = [path for path in input_paths if not path.is_file()]
    if missing:
        parser.error("Input TIFF not found: " + ", ".join(str(path) for path in missing))

    if args.output and len(input_paths) > 1:
        output_dir = args.output
    else:
        output_dir = None

    figures = []
    for input_path in input_paths:
        if output_dir is not None:
            output = output_dir / f"{input_path.stem}_preview.png"
        else:
            output = args.output or input_path.with_name(f"{input_path.stem}_preview.png")
        output.parent.mkdir(parents=True, exist_ok=True)
        figures.append(save_preview(input_path, output))

    if args.no_show:
        for fig in figures:
            plt.close(fig)
    else:
        plt.show()


if __name__ == "__main__":
    main()
