"""Exclude mapped structures/private land; this is not a cadastral decision."""
import json

import numpy as np
from rasterio.features import is_valid_geom, rasterize
from rasterio.warp import transform_geom
from scipy.ndimage import distance_transform_edt


def exclude_context(mask, context, transform, crs, *, building_buffer_m=2, house_buffer_m=0, residential_buffer_m=0, return_exclusion_mask=False):
    """Return mask and disjoint removal areas for buildings/residential/private.

    context: WGS84 GeoJSON polygons with properties.tags or tags_json.
    All mapped residential polygons are excluded, possibly including public
    vegetation inside them. Missing coverage/OSM tags are not proof of safety.
    """
    if not np.isfinite(building_buffer_m) or not 0 <= building_buffer_m <= 20:
        raise ValueError("building_buffer_m must be between 0 and 20 metres")
    for value in (house_buffer_m, residential_buffer_m):
        if isinstance(value,bool) or not np.isfinite(value) or not 0 <= value <= 30:
            raise ValueError("House/residential buffer must be from 0 to 30 metres")
    groups = {key: [] for key in ('buildings', 'residential', 'private_access', 'house_context')}
    skipped = 0
    for feature in context.get('features', []):
        props = feature.get('properties') or {}
        tags = props.get('tags') or json.loads(props.get('tags_json') or '{}')
        keys = []
        if tags.get('building') not in (None, 'no', 'false', '0'):
            keys.append('buildings')
        if house_buffer_m and tags.get('building') in ('house','residential','apartments','terrace','detached','semidetached_house','bungalow','dormitory'):
            keys.append('house_context')
        if tags.get('landuse') == 'residential':
            keys.append('residential')
        if tags.get('access') in ('private', 'no', 'customers', 'permit'):
            keys.append('private_access')
        if not keys:
            continue
        geometry = feature.get('geometry') or {}
        if geometry.get('type') not in ('Polygon', 'MultiPolygon') or not is_valid_geom(geometry):
            skipped += 1
            continue
        projected = transform_geom('EPSG:4326', crs, geometry)
        for key in keys:
            groups[key].append(projected)
    result, areas = mask.copy(), {}
    blocked = np.zeros(mask.shape,dtype=bool) if return_exclusion_mask else None
    pixel_m = transform.a
    for key, shapes in groups.items():
        burned = rasterize(shapes, out_shape=mask.shape, transform=transform, fill=0, default_value=1, dtype='uint8').astype(bool) if shapes else np.zeros(mask.shape, dtype=bool)
        buffer_m = {'buildings':building_buffer_m, 'house_context':house_buffer_m,
                    'residential':residential_buffer_m}.get(key,0)
        if burned.any() and buffer_m:
            burned = distance_transform_edt(~burned, sampling=pixel_m) <= buffer_m
        if blocked is not None:
            blocked |= burned
        areas[key] = int(((result == 1) & burned).sum()) * pixel_m**2
        result[burned & (result != 255)] = 0
    coverage = context.get('source', {}).get('coverage_geometry')
    outside = None
    if coverage:
        inside = rasterize([transform_geom('EPSG:4326', crs, coverage)], out_shape=mask.shape, transform=transform, fill=0, default_value=1, dtype='uint8')
        outside = int(((mask != 255) & (inside == 0)).sum()) * pixel_m**2
    report = {'removed_candidate_m2': areas, 'skipped_non_polygon_or_invalid': skipped,
                    'valid_area_outside_context_coverage_m2': outside,
                    'attribution': context.get('source', {}),
                    'buffers_m':{'buildings':building_buffer_m,'houses':house_buffer_m,'residential':residential_buffer_m},
                    'scope': 'outside_mapped_buildings_residential_and_private_areas_not_verified_public_land'}

    return (result,report,blocked) if return_exclusion_mask else (result,report)


def exclude_policy_areas(mask, policy, transform, crs, *, scene_id):
    """Apply explicit visual-policy polygons; never infer land ownership."""
    if policy.get('target')!='eligible_green' or policy.get('purpose')!='area_exclusion':
        raise ValueError('Explicit eligible-green area exclusions required')
    shapes=[]
    for feature in policy.get('features',[]):
        p=feature.get('properties') or {};g=feature.get('geometry') or {}
        if (p.get('policy_decision')!='exclude_residential_context' or p.get('class')!='negative'
                or not p.get('scene_id') or g.get('type') not in ('Polygon','MultiPolygon') or not is_valid_geom(g)):
            raise ValueError('Valid explicit exclusion polygons required')
        if p['scene_id']==scene_id:
            shapes.append(transform_geom('EPSG:4326',crs,g))
    blocked=rasterize(shapes,out_shape=mask.shape,transform=transform,fill=0,default_value=1,dtype='uint8').astype(bool) if shapes else np.zeros(mask.shape,dtype=bool)
    result=mask.copy();result[blocked & (result!=255)]=0
    return result,blocked
