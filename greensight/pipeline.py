"""Reusable backend pipeline: image -> detect -> heatmap -> park references.

CLI wrappers live at the repository root; algorithms remain in their own modules.
"""
from copy import deepcopy
from datetime import datetime
from pathlib import Path
import shutil

from .audit import audit_scene
from .scene import analyse_scene, read_json, write_json
from .park_lookup import find_parks_in_image

ROOT = Path(__file__).resolve().parents[1]


def run_all(config_path='data/scenes.json', out_dir='Output/runs/analysis'):
    """Analyse all configured images; refuse existing output to preserve runs."""
    output = Path(out_dir)
    if output.exists():
        raise FileExistsError('Choose a new output root')
    settings = read_json(config_path)
    results = []
    for scene in settings['scenes']:
        results.append(analyse_scene(
            scene['path'], output/scene['id'], scene_id=scene['id'],
            red_band=scene['red_band'], nir_band=scene['nir_band'],
            context_path=scene.get('context'), imagery_date=scene.get('imagery_date'),
            registry_path=settings.get('registry'),min_area_m2=scene.get('min_area_m2',settings.get('min_area_m2',300)),
            heatmap_style=scene.get('heatmap_style',settings.get('heatmap_style','red')),
            radius_m=scene.get('radius_m',settings.get('radius_m',50)),
            clean_radius_m=scene.get('clean_radius_m',settings.get('clean_radius_m',0)),
            building_buffer_m=settings.get('building_buffer_m',2),house_buffer_m=settings.get('house_buffer_m',0),
            residential_buffer_m=settings.get('residential_buffer_m',0), policy_exclusions=settings.get('policy_exclusions'),pending_areas=settings.get('pending_areas'), progress=lambda message: print(message,flush=True)))
    write_json(output/'summary-all.json',results)
    return results


def verify_parks(config_path='data/scenes.json', out_dir='Output/runs/parks', *, district='don-mueang'):
    output=Path(out_dir)
    if output.exists():raise FileExistsError('Choose a new output folder')
    config=read_json(config_path);output.mkdir(parents=True)
    results=[]
    for scene in config['scenes']:
        result=find_parks_in_image(scene['path'],config['registry'],district=district)
        result['scene_id']=scene['id']
        for feature in result['features']:
            feature['properties']['scene_id']=scene['id']
        write_json(output/(scene['id']+'-parks.geojson'),result)
        results.append({'scene_id':scene['id'],'registry_points_in_valid_image':len(result['features']),
                        'verified_parks':0,'district_filter':district,'status':result['status']})
    write_json(output/'summary.json',results)
    return results


def prepare_config(config_path, *, project_root=ROOT):
    """Resolve input paths against project_root; check before processing."""
    root = Path(project_root).resolve()
    path = Path(config_path)
    config = deepcopy(read_json(path if path.is_absolute() else root / path))
    scenes = config.get('scenes', [])
    ids = [scene['id'] for scene in scenes]
    if not ids or len(set(ids)) != len(ids):
        raise ValueError('Configure at least one scene with unique IDs')
    for scene in scenes:
        name = scene['id']
        if not isinstance(name, str) or not name or any(c in name for c in '/\\:') or name in ('.', '..'):
            raise ValueError('Scene IDs must be simple folder names')
        if not scene.get('context'):
            raise ValueError('Each scene needs a context file for the full audit')
    inputs = [(config, 'registry')]
    inputs += [(config, key) for key in ('policy_exclusions', 'pending_areas') if config.get(key)]
    inputs += [(scene, key) for scene in scenes for key in ('path', 'context')]
    for owner, key in inputs:
        path = Path(owner[key])
        path = (path if path.is_absolute() else root / path).resolve()
        if not path.is_file():
            raise FileNotFoundError(f'Missing {key}: {path}')
        if key != 'path':
            reference = read_json(path)
            if not isinstance(reference, dict) or not isinstance(reference.get('features'), list) or (key in ('registry', 'context') and reference.get('type') != 'FeatureCollection'):
                raise ValueError(f'Expected GeoJSON FeatureCollection with features list: {path}')
        owner[key] = str(path)
    return config


def run_backend(config_path='data/scenes.json', out_dir=None, *, district='don-mueang', project_root=ROOT):
    """Run all automatic stages; human reviews remain pending.

    Relative paths use project_root, never the shell working directory.
    Existing results are preserved; failed runs keep status and partial evidence.
    """
    config = prepare_config(config_path, project_root=project_root)
    output = Path(out_dir) if out_dir else Path('Output/runs') / datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    if not output.is_absolute():
        output = Path(project_root) / output
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    stage = 'configuration'
    write_json(output / 'status.json', {'status': 'running', 'stage': stage})
    try:
        config_file = output / 'config.json'
        write_json(config_file, config)
        stage = 'analysis'
        write_json(output / 'status.json', {'status': 'running', 'stage': stage})
        print('[1/3] Detecting green areas and making heatmaps', flush=True)
        scenes = run_all(config_file, output / 'analysis')
        stage = 'park_lookup'
        write_json(output / 'status.json', {'status': 'running', 'stage': stage})
        print('[2/3] Finding registered parks in valid image pixels', flush=True)
        parks = verify_parks(config_file, output / 'parks', district=district)
        stage = 'audit'
        write_json(output / 'status.json', {'status': 'running', 'stage': stage})
        print('[3/3] Auditing every source window and retained patch (may take time)', flush=True)
        audits = []
        for scene in config['scenes']:
            print('Auditing ' + scene['id'], flush=True)
            audits.append(audit_scene(
                output / 'analysis' / scene['id'], scene['path'],
                context_path=scene['context'], policy_path=config.get('policy_exclusions'),
                pending_path=config.get('pending_areas'),
            ))
        result = {'status': 'complete', 'output': str(output), 'scenes': scenes,
                  'park_lookup': parks, 'audits': audits,
                  'public_park_verification': 'needs_human_review'}
        write_json(output / 'summary.json', result)
        write_json(output / 'status.json', {'status': 'complete', 'stage': 'complete'})
        print('Complete: ' + str(output), flush=True)
        return result
    except Exception as error:
        write_json(output / 'status.json', {'status': 'failed', 'stage': stage,
                                         'error': str(error), 'error_type': type(error).__name__})
        raise


def run_image(image_path, *, out_dir=None, pixel_m=None, heatmap_style='proximity', radius_m=150, red_band=3, nir_band=4,
              min_area_m2=1000, clean_radius_m=6, registry_path='data/registry/suanluang-parks.geojson'):
    """Prepare a metric TIFF and run one new footprint without old area policies.

    Missing local context is explicit: results are vegetation candidates, not
    public-park eligibility. The original TIFF is read only.
    """
    import math
    import rasterio
    from rasterio.enums import Resampling
    from rasterio.warp import reproject
    from greensight.scene import digest
    from greensight.heatmap import make_heatmap

    registry_path = Path(registry_path)
    registry_path = (registry_path if registry_path.is_absolute() else ROOT / registry_path).resolve()
    registry = read_json(registry_path)
    if not isinstance(registry, dict) or registry.get('type') != 'FeatureCollection' or not isinstance(registry.get('features'), list):
        raise ValueError(f'Expected a park registry FeatureCollection: {registry_path}')
    source = Path(image_path)
    source = (source if source.is_absolute() else ROOT / source).resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    folder = Path(out_dir) if out_dir else Path('Output/runs') / datetime.now().strftime('image-%Y%m%d-%H%M%S-%f')
    folder = (folder if folder.is_absolute() else ROOT / folder).resolve()
    if folder.exists():
        raise FileExistsError('Choose a new output folder')
    source_hash = digest(source)
    stamp = (source.stat().st_size, source.stat().st_mtime_ns)
    with rasterio.open(source) as src:
        if not all(type(b) is int and 1 <= b <= src.count for b in (red_band, nir_band)) or red_band == nir_band:
            raise ValueError('Choose distinct valid --red-band and --nir-band numbers (one-based); RGB-only photos do not supply NIR')
        if not src.crs or not src.crs.is_projected or not math.isclose(src.crs.linear_units_factor[1], 1):
            raise ValueError('Expected a georeferenced TIFF with a projected CRS in metres')
        if src.transform.b or src.transform.d or src.transform.a <= 0 or src.transform.e >= 0:
            raise ValueError('Expected a north-up source grid')
        if pixel_m is None:
            # Never upsample; keep automatic runs below a conservative 20M-cell budget.
            extent_area = (src.bounds.right-src.bounds.left) * (src.bounds.top-src.bounds.bottom)
            pixel_m = max(2, max(src.res), math.ceil(math.sqrt(extent_area / 20_000_000)))
        make_heatmap([[0]], pixel_m, min_area_m2=min_area_m2, radius_m=radius_m,
                     style=heatmap_style, clean_radius_m=clean_radius_m)
        if pixel_m < max(src.res):
            raise ValueError('Use source resolution or coarser; upsampling adds no detail')
        width = math.ceil((src.bounds.right - src.bounds.left) / pixel_m)
        height = math.ceil((src.bounds.top - src.bounds.bottom) / pixel_m)
        if width * height > 80_000_000:
            raise ValueError('Image exceeds 80M-cell budget; choose a coarser --pixel-m')
        folder.mkdir(parents=True)
        prepared = folder / 'analysis-input.tif'
        grid = rasterio.transform.from_origin(src.bounds.left, src.bounds.top, pixel_m, pixel_m)
        profile = dict(driver='GTiff', width=width, height=height, count=src.count,
                       dtype='float32', crs=src.crs, transform=grid, nodata=float('nan'),
                       tiled=True, blockxsize=256, blockysize=256, compress='deflate')
        print(f'Preparing {pixel_m:g} m experimental grid; source remains unchanged', flush=True)
        with rasterio.open(prepared, 'w', **profile) as dst:
            for band in range(1, src.count + 1):
                reproject(source=rasterio.band(src, band), destination=rasterio.band(dst, band),
                          resampling=Resampling.average, warp_mem_limit=64, num_threads=1)
    context = folder / 'context-unavailable.geojson'
    write_json(context, {'type': 'FeatureCollection', 'features': [],
                        'source': {'status': 'unavailable_for_new_footprint'}})
    config_file = folder / 'image-config.json'
    write_json(config_file, {'registry': str(registry_path),
        'min_area_m2': min_area_m2, 'clean_radius_m': clean_radius_m, 'heatmap_style': heatmap_style, 'radius_m': radius_m,
        'scenes': [{'id': 'new-image', 'path': str(prepared), 'context': str(context),
                    'red_band': red_band, 'nir_band': nir_band}]})
    note = {'source': str(source), 'original_sha256': source_hash, 'analysis_pixel_m': pixel_m,
            'resampling': 'average', 'band_identity_and_date': 'unconfirmed',
            'context': 'unavailable: residential/private vegetation and roofs may remain',
            'heatmap': 'proximity: green vegetation to yellow/red farther away; not heat or walking access',
            'registry': str(registry_path),
            'registry_scope': 'supplied point references; all matching records; park decisions remain pending',
            'noise_screening': {'minimum_patch_m2':min_area_m2, 'opening_radius_m':clean_radius_m,
                                'meaning':'size and width screening, not proof a feature is roadside/private'}}
    write_json(folder / 'experiment-notes.json', note)
    print('No local housing exclusions for this footprint; park access remains unverified', flush=True)
    result = run_backend(config_file, folder / 'pipeline', district=None)
    if stamp != (source.stat().st_size, source.stat().st_mtime_ns) or digest(source) != source_hash:
        raise RuntimeError('Original changed during processing; check experiment provenance')
    # Put the three deliverables together; native rasters and evidence stay in pipeline/.
    scene_folder = Path(result['output']) / 'analysis/new-image'
    images = {}
    for key, source_name, output_name in (
        ('detect', 'detect.png', '01-detect-greenzone.png'),
        ('heatmap', 'heatmap.png', '02-heatmap.png'),
        ('verify_park', 'parks-map.png', '03-verify-parks.png'),
    ):
        destination = folder / output_name
        shutil.copy2(scene_folder / source_name, destination)
        images[key] = str(destination)
    result['images'] = images
    result['run_folder'] = str(folder)
    write_json(folder / 'result.json', result)
    print('Three output images:', flush=True)
    for name, path in images.items():
        print(f'  {name}: {path}', flush=True)
    return result


