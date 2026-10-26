"""Run Nike's full-scene analysis without changing the team's grid.py."""
import argparse
import json
from pathlib import Path

from greensight.scene import analyse_scene
from greensight.pipeline import run_all

# Keep the previous import usable by teammates.
run_analysis = analyse_scene


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('tif_path', nargs='?')
    parser.add_argument('out_dir', nargs='?')
    parser.add_argument('--all', action='store_true')
    parser.add_argument('--output', default='Output/runs/analysis')
    parser.add_argument('--config', default='data/scenes.json')
    parser.add_argument('--scene-id')
    parser.add_argument('--heatmap-style', choices=['red','spectrum','grid','density','proximity'], default='red')
    parser.add_argument('--radius-m', type=int, default=50)
    parser.add_argument('--min-area-m2',type=float,default=300)
    parser.add_argument('--red-band', type=int)
    parser.add_argument('--nir-band', type=int)
    parser.add_argument('--registry', default='data/registry/parks15.geojson')
    parser.add_argument('--policy-exclusions', default='data/labels/policies/area-exclusions.geojson')
    parser.add_argument('--pending-areas',default='data/labels/policies/pending-areas.geojson')
    parser.add_argument('--exclude')
    parser.add_argument('--context')
    parser.add_argument('--imagery-date')
    parser.add_argument('--clean-radius-m',type=float,default=3)
    parser.add_argument('--building-buffer-m',type=float,default=8)
    parser.add_argument('--house-buffer-m',type=float,default=20)
    parser.add_argument('--residential-buffer-m',type=float,default=10)
    args = parser.parse_args()
    if args.all:
        results = run_all(args.config,args.output)
        print(json.dumps([{'scene':r['scene_id'],'area_m2':r['stats']['retainedCandidateAreaM2']} for r in results],indent=2))
    else:
        if not all((args.tif_path,args.out_dir,args.scene_id,args.red_band,args.nir_band)):
            parser.error('Supply TIFF/output, --scene-id, --red-band and --nir-band; or use --all')
        result = analyse_scene(args.tif_path,args.out_dir,scene_id=args.scene_id,min_area_m2=args.min_area_m2,
                               heatmap_style=args.heatmap_style,radius_m=args.radius_m,
                               red_band=args.red_band,nir_band=args.nir_band,
                               registry_path=args.registry,exclude_path=args.exclude,
                               context_path=args.context,imagery_date=args.imagery_date,clean_radius_m=args.clean_radius_m,
                               building_buffer_m=args.building_buffer_m,house_buffer_m=args.house_buffer_m,residential_buffer_m=args.residential_buffer_m,policy_exclusions=args.policy_exclusions,pending_areas=args.pending_areas,
                               progress=lambda message: print(message,flush=True))
        print(json.dumps(result,indent=2))
