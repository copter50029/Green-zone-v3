"""Command-line entry point. Reusable functions live in greensight.pipeline."""
import argparse
import sys
from greensight.pipeline import ROOT, prepare_config, run_backend, run_image


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('image_path', nargs='?', help='Input TIFF (same as --image)')
    parser.add_argument('--red-band', type=int, default=3)
    parser.add_argument('--nir-band', type=int, default=4)
    parser.add_argument('--min-area-m2', type=float, default=1000, help='New-image minimum retained patch area')
    parser.add_argument('--clean-radius-m', type=float, default=6, help='New-image opening radius; suppresses narrow strips')
    parser.add_argument('--registry', default='data/registry/suanluang-parks.geojson', help='New-image park reference GeoJSON')
    parser.add_argument('--config', default='data/scenes.json')
    parser.add_argument('--image', help='Analyse a new TIFF instead of the old scene configuration')
    parser.add_argument('--pixel-m', type=float, default=None, help='Analysis metres/pixel; auto: at least 2 m, never upsample, <=20M cells')
    parser.add_argument('--heatmap-style', choices=['red','spectrum','grid','density','proximity'], default='proximity')
    parser.add_argument('--radius-m', type=int, default=150, help='New-image smoothing/proximity radius in metres')
    parser.add_argument('--output', help='New output folder; defaults to a unique timestamp')
    parser.add_argument('--all-districts', action='store_true')
    parser.add_argument('--check', action='store_true', help='Check input paths and reference JSON without processing TIFFs')
    args = parser.parse_args()
    if args.image and args.image_path:
        parser.error('Supply the image once, as a positional path or --image')
    args.image = args.image or args.image_path
    if args.image:
        if args.check:
            parser.error('--check checks configured inputs; use it without --image')
        run_image(args.image, out_dir=args.output, pixel_m=args.pixel_m,
                  heatmap_style=args.heatmap_style, radius_m=args.radius_m,
                  red_band=args.red_band, nir_band=args.nir_band,
                  min_area_m2=args.min_area_m2, clean_radius_m=args.clean_radius_m, registry_path=args.registry)
        return
    if args.check:
        config = prepare_config(args.config)
        print(f"Input paths and reference JSON passed: {len(config['scenes'])} scenes")
        return
    run_backend(args.config, args.output, district=None if args.all_districts else 'suanluang')


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError) as error:
        print(f"Cannot run: {error}", file=sys.stderr)
        raise SystemExit(2)
