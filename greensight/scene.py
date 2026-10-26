"""Full-scene windowed detection, followed by global filtering on valid bounds."""
import hashlib
import json
from pathlib import Path

import numpy as np
import rasterio
from rasterio.enums import ColorInterp
from rasterio.windows import Window

from .detect import detect_green
from .heatmap import make_heatmap, CANDIDATE_RGBA
from .pending import separate_pending,write_pending
from .park_verify import prepare_park_review, write_park_preview
from .exclusions import exclude_context, exclude_policy_areas


def windows(width, height, size=512):
    """Cover every source pixel exactly once, including partial edge windows."""
    if isinstance(size, bool) or not isinstance(size, int) or size < 1:
        raise ValueError('Window size must be a positive integer')
    for row in range(0, height, size):
        for col in range(0, width, size):
            yield Window(col, row, min(size, width-col), min(size, height-row))


def digest(path):
    checksum = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(8*1024*1024), b''):
            checksum.update(chunk)
    return checksum.hexdigest()


def read_json(path):
    """Read JSON without silently replacing missing or malformed reference data."""
    source = Path(path).resolve()
    try:
        text = source.read_text(encoding='utf-8-sig')
    except UnicodeDecodeError as error:
        raise ValueError(f'JSON file must use UTF-8: {source}') from error
    try:
        return json.loads(text)
    except json.JSONDecodeError as error:
        reason = 'File is empty or whitespace-only' if not text.strip() else error.msg
        raise json.JSONDecodeError(f'{source}: {reason}', error.doc, error.pos) from error


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def extend_detection_preview(detect_path, mask_path, heatmap_path, out_path):
    """Continue from a saved detect PNG; preserve every detected green pixel.

    Use the saved class mask for geometry, never guess vegetation from RGB.
    Only non-candidate pixels receive the heatmap overlay.
    """
    out_path = Path(out_path)
    if out_path.exists():
        raise FileExistsError('Choose a new heatmap PNG; existing images are preserved')
    with rasterio.open(detect_path) as base, rasterio.open(mask_path) as mask, rasterio.open(heatmap_path) as heat:
        if base.count != 3 or heat.count != 4 or mask.count != 1:
            raise ValueError('Expected RGB detect PNG, class mask and RGBA heatmap')
        if mask.shape != heat.shape or mask.crs != heat.crs or mask.transform != heat.transform:
            raise ValueError('Mask and heatmap grids must match')
        if abs(base.height - round(base.width * mask.height / mask.width)) > 1:
            raise ValueError('Detect preview must cover the full mask footprint')
        image = np.moveaxis(base.read(), 0, -1)
        candidates = mask.read(1, out_shape=base.shape) == 1
        rgba = np.moveaxis(heat.read(out_shape=(4,*base.shape)), 0, -1)
    alpha = rgba[:,:,3:4].astype('float32') / 255
    alpha[candidates] = 0  # Keep the existing detection image exactly as saved.
    result = np.round(image * (1-alpha) + rgba[:,:,:3] * alpha).astype('uint8')
    with rasterio.open(out_path, 'w', driver='PNG', count=3, width=image.shape[1],
                       height=image.shape[0], dtype='uint8') as dst:
        dst.write(np.moveaxis(result, -1, 0))
    return {'base_image':str(detect_path), 'base_sha256':digest(detect_path),
            'candidate_preview_pixels_preserved':int(candidates.sum()),
            'method':'saved_detect_png_plus_heatmap_on_non_candidate_pixels_only'}


def analyse_scene(tif_path, out_dir, *, scene_id, red_band, nir_band,
                  registry_path=None, context_path=None, exclude_path=None,
                  imagery_date=None, window_size=512, min_area_m2=300,
                  radius_m=50, heatmap_style="red", clean_radius_m=0, building_buffer_m=2, house_buffer_m=0, residential_buffer_m=0, policy_exclusions=None, pending_areas=None, progress=None):
    """Process a TIFF once in windows; merge before patch filtering/heatmap.

    Outputs preserve the source CRS and native pixel grid, cropped only to
    exact valid-pixel bounds. Cropping never discards a valid image pixel.
    Global filters use RAM on the cropped mask (maximum 80 million cells).
    Does not manufacture model accuracy, ownership or public-access evidence.
    """
    destination, tif_path = Path(out_dir), Path(tif_path)
    if destination.exists():
        raise FileExistsError('Choose a new output directory; existing results are preserved')
    registry = read_json(registry_path) if registry_path else {'type': 'FeatureCollection', 'features': []}
    context = read_json(context_path) if context_path else None
    pending_policy=read_json(pending_areas) if pending_areas else None
    policy=read_json(policy_exclusions) if policy_exclusions else None
    # Validate user options before reading a large input or creating output.
    detect_green(np.ones((4, 1, 1)), red_band=red_band, nir_band=nir_band)
    make_heatmap(np.zeros((1, 1), dtype='uint8'), 1, min_area_m2, radius_m, style=heatmap_style, clean_radius_m=clean_radius_m)
    exclude_context(np.zeros((1,1),dtype='uint8'),{'features':[]},rasterio.Affine(1,0,0,0,-1,1),'EPSG:32647',
                    building_buffer_m=building_buffer_m,house_buffer_m=house_buffer_m,residential_buffer_m=residential_buffer_m)
    list(windows(1, 1, window_size))
    stamp = (tif_path.stat().st_size, tif_path.stat().st_mtime_ns)
    if progress:
        progress(f'{scene_id}: hashing source')
    source_hash = digest(tif_path)
    exclusion = None
    with rasterio.open(tif_path) as src:
        if src.crs is None or not src.crs.is_projected or not np.isclose(src.crs.linear_units_factor[1], 1):
            raise ValueError('Expected a projected raster in metres')
        if not all(np.isfinite(tuple(src.transform)[:6])) or src.transform.b or src.transform.d or src.transform.a <= 0 or src.transform.e >= 0 or not np.isclose(src.res[0], src.res[1]):
            raise ValueError('Expected north-up square pixels')
        detect_green(np.ones((src.count, 1, 1)), red_band=red_band, nir_band=nir_band)
        if exclude_path:
            exclusion = rasterio.open(exclude_path)
            if exclusion.crs != src.crs or exclusion.transform != src.transform or exclusion.shape != src.shape or exclusion.count != 1:
                exclusion.close()
                raise ValueError('Exclusion must be one band on the exact source grid/CRS')
        destination.mkdir(parents=True)
        write_json(destination / 'status.json', {'status': 'processing', 'scene_id': scene_id})
        profile = dict(driver='GTiff', count=1, width=src.width, height=src.height,
                       crs=src.crs, transform=src.transform, dtype='uint8', nodata=255,
                       tiled=True, blockxsize=256, blockysize=256, compress='deflate', BIGTIFF='IF_SAFER')
        top, left, bottom, right = src.height, src.width, 0, 0
        total = seen = nonempty = 0
        raw = destination / 'raw-mask.tif'
        try:
            with rasterio.open(raw, 'w', SPARSE_OK=True, **profile) as dst:
                for win in windows(src.width, src.height, window_size):
                    total += 1
                    # A missing first band cannot be valid across all bands.
                    if not src.read_masks(1, window=win).any():
                        continue
                    bands = src.read(window=win)
                    extra = None if exclusion is None else (exclusion.read(1, window=win) != 0) & (exclusion.read_masks(1, window=win) != 0)
                    mask = detect_green(bands, red_band=red_band, nir_band=nir_band,
                                        nodata=src.nodata, valid_mask=(src.read_masks(window=win) != 0).all(axis=0), exclude_mask=extra)
                    valid = mask != 255
                    if not valid.any():
                        continue
                    dst.write(mask, 1, window=win)
                    rr, cc = np.where(valid)
                    top, left = min(top, int(win.row_off)+int(rr.min())), min(left, int(win.col_off)+int(cc.min()))
                    bottom, right = max(bottom, int(win.row_off)+int(rr.max())+1), max(right, int(win.col_off)+int(cc.max())+1)
                    seen += int(valid.sum())
                    nonempty += 1
                    if progress and nonempty % 20 == 0:
                        progress(f'{scene_id}: {nonempty} data windows / {seen:,} valid pixels')
        finally:
            if exclusion is not None:
                exclusion.close()
        crop = Window(left, top, right-left, bottom-top) if seen else Window(0, 0, 1, 1)
        if crop.width * crop.height > 80_000_000:
            raise ValueError('Valid extent exceeds 80M-cell global-filter budget; raw-mask.tif is retained')
        transform = src.window_transform(crop)
        with rasterio.open(raw) as source:
            mask = source.read(1, window=crop)
        if int((mask != 255).sum()) != seen:
            raise RuntimeError('Window merging lost or invented valid pixels')
        exclusion_report = None
        blocked = None
        if context:
            mask, exclusion_report, blocked = exclude_context(mask, context, transform, src.crs, building_buffer_m=building_buffer_m,house_buffer_m=house_buffer_m,residential_buffer_m=residential_buffer_m,return_exclusion_mask=True)
        if policy:
            mask,policy_blocked=exclude_policy_areas(mask,policy,transform,src.crs,scene_id=scene_id)
            blocked=policy_blocked if blocked is None else blocked|policy_blocked
        if progress:
            progress(f'{scene_id}: global patch filter and distance over {mask.shape}')
        result = make_heatmap(mask, src.res[0], min_area_m2, radius_m, style=heatmap_style, clean_radius_m=clean_radius_m)
        pending_report=None
        if pending_policy:
            result,pending_mask,pending_rgba,pending_report=separate_pending(result,pending_policy,transform,src.crs,scene_id=scene_id,pixel_m=src.res[0],min_area_m2=min_area_m2,radius_m=radius_m,style=heatmap_style)
        if blocked is not None:
            result['rgba'][blocked]=0
        tasks = prepare_park_review(registry, result['mask'], transform, src.crs,
                                    scene_id=scene_id, imagery_date=imagery_date)
        profile.update(width=int(crop.width), height=int(crop.height), transform=transform)
        with rasterio.open(destination / 'candidate-mask.tif', 'w', **profile) as dst:
            dst.write(result['mask'], 1)
        if pending_report is not None:
            write_pending(destination,profile,pending_mask,pending_rgba)
        profile.update(count=4, nodata=None)
        with rasterio.open(destination / 'heatmap.tif', 'w', **profile) as dst:
            dst.write(np.moveaxis(result['rgba'], -1, 0))
            dst.colorinterp = (ColorInterp.red, ColorInterp.green, ColorInterp.blue, ColorInterp.alpha)
        # Compact display artifact; raw radiometry is not modified.
        preview_scale = min(1, 2000 / max(crop.width, crop.height))
        height = max(1, round(crop.height * preview_scale))
        width = max(1, round(crop.width * preview_scale))
        rgb = src.read([red_band, 2 if src.count >= 2 else red_band, 1], window=crop, out_shape=(3,height,width)).astype('float32')
        valid_preview = src.read_masks(1, window=crop, out_shape=(height,width)) != 0
        for band in rgb:
            limits = np.percentile(band[valid_preview], [2,98]) if valid_preview.any() else [0,1]
            band[:] = np.clip((band-limits[0])/max(limits[1]-limits[0],1), 0, 1)*255
        rgb = np.moveaxis(rgb.astype('uint8'), 0, -1)
        rgb[~valid_preview] = [236,234,230]
        preview_derivation = None
        for name in ('source', 'detect', 'heatmap'):
            if name == 'heatmap' and heatmap_style == 'proximity':
                preview_derivation = extend_detection_preview(destination/'detect.png', destination/'candidate-mask.tif',
                                                               destination/'heatmap.tif', destination/'heatmap.png')
                continue
            image = rgb
            if name != 'source':
                if name == 'detect':
                    with rasterio.open(destination / 'candidate-mask.tif') as layer:
                        detected = layer.read(1, out_shape=(height,width)) == 1
                    rgba = np.zeros((height,width,4), dtype='uint8')
                    rgba[detected] = CANDIDATE_RGBA
                else:
                    with rasterio.open(destination / 'heatmap.tif') as layer:
                        rgba = np.moveaxis(layer.read(out_shape=(4,height,width)),0,-1)
                # One compositing formula keeps candidate pixels identical in both PNGs.
                alpha = rgba[:,:,3:4].astype('float32')/255
                image = np.round(rgb*(1-alpha)+rgba[:,:,:3]*alpha).astype('uint8')
            with rasterio.open(destination / f'{name}.png', 'w', driver='PNG', width=width,height=height,count=3,dtype='uint8') as dst:
                dst.write(np.moveaxis(image,-1,0))
        write_park_preview(destination, tasks, transform, src.crs, result['mask'].shape)
        summary = {
            'scene_id':scene_id, 'input_file':tif_path.name,
            'status':'experimental_raw_band_ratio_unvalidated',
            'red_band_assumption':red_band,'nir_band_assumption':nir_band,
            'band_mapping_status':'standard_order_supported_file_identity_unconfirmed',
            'calibration_verified':False, 'real_accuracy':None,
            'imagery_date':imagery_date,'imagery_date_basis':'source filename; product metadata not verified',
            'pixel_m':src.res[0], 'valid_area_m2':seen*src.res[0]**2,
            'source_shape':[src.height,src.width], 'crop_window':[int(crop.col_off),int(crop.row_off),int(crop.width),int(crop.height)],
            'transform':list(transform)[:6], 'crs':src.crs.to_string(),
            'window_size':window_size,'windows_scanned':total,'data_windows':nonempty,
            'clean_radius_m':clean_radius_m, 'minimum_patch_m2':min_area_m2,'halo_radius_m':radius_m, 'heatmap_style':heatmap_style, 'candidate_rgba':list(CANDIDATE_RGBA),
            'heatmap_meaning':'smoothed_local_vegetation_occupancy' if heatmap_style=='density' else 'candidate_proximity',
            'heatmap_legend':({'green_m':0,'yellow_m':radius_m/2,'red_at_least_m':radius_m} if heatmap_style=='proximity' else None),
            'preview_files':{'detect':'detect.png','heatmap':'heatmap.png','park_registry':'parks-map.png'},
            'heatmap_preview_derivation':preview_derivation,
            'exclusion_supplied':bool(context_path or exclude_path), 'context_exclusions':exclusion_report,
            'stats':result['stats'], 'review_tasks':len(tasks['features']), 'verified_parks':0,
            'provenance':{'source_sha256':source_hash,
                          'policy_exclusions_sha256':digest(policy_exclusions) if policy_exclusions else None,
                          'registry_sha256':digest(registry_path) if registry_path else None,
                          'context_sha256':digest(context_path) if context_path else None,
                          'exclusion_sha256':digest(exclude_path) if exclude_path else None,
                          'code_sha256':{p.name:digest(p) for p in Path(__file__).parent.glob('*.py')}},
            'limitations':['No independent reviewed labels; no real accuracy.',
                           'OSM exclusions are incomplete and are not ownership or public-access verification.',
                           'Residential exclusion can remove public vegetation inside broad residential polygons.',
                           'RGB preview band identities and image dates are not file-level verified.'],
        }
    if (tif_path.stat().st_size,tif_path.stat().st_mtime_ns) != stamp:
        raise RuntimeError('Source changed during analysis; output is not publishable')
    if pending_report is not None:
        summary['pending_review']=pending_report
        summary['provenance']['pending_areas_sha256']=digest(pending_areas)
    write_json(destination / 'park-review.geojson',tasks)
    summary['artifact_sha256'] = {name:digest(destination/name) for name in ('raw-mask.tif','candidate-mask.tif','heatmap.tif','park-review.geojson','source.png','detect.png','heatmap.png','parks-map.png')}
    if pending_report is not None:
        summary['artifact_sha256'].update({name:digest(destination/name) for name in ('pending-mask.tif','pending.tif')})
    write_json(destination / 'summary.json',summary)
    write_json(destination / 'status.json',{'status':'complete','scene_id':scene_id})
    return summary
