"""Audit source-aligned visual labels without treating them as human truth."""
from collections import Counter
from datetime import date
from hashlib import sha256
from pathlib import Path
import math
import numpy as np
import rasterio
from rasterio.warp import transform_geom
from rasterio.windows import Window


def validate_labels(labels, image_dir, *, minimum_split_gap_m=50, evidence_dir=None):
    """Check assistant core rectangles against original TIFFs; return a QA report.

    Uncertain cores remain in the audit but are withheld from usable counts.
    This validates structure and source alignment, not semantic accuracy.
    """
    if labels.get('target') != 'vegetation' or not math.isfinite(minimum_split_gap_m) or minimum_split_gap_m < 0:
        raise ValueError('Expected vegetation labels and a nonnegative split gap')
    if not labels.get('features'):
        raise ValueError('At least one explicit label is required')
    counts, ids, regions, boxes, evidence = Counter(), set(), {}, [], {}
    for feature in labels.get('features', []):
        p = feature['properties']
        identifier = feature['id']
        if identifier in ids:
            raise ValueError('Duplicate label ID')
        ids.add(identifier)
        category, split = p['class'], p['split']
        if category not in ('positive', 'negative', 'uncertain') or split not in ('train', 'validation', 'test'):
            raise ValueError('Invalid class or split')
        uncertain = category == 'uncertain'
        if (p.get('origin') != 'assistant_visual' or p.get('human_review_status') != 'pending'
                or p.get('review_status') != ('uncertain' if uncertain else 'assistant_reviewed')
                or p.get('certainty') != ('uncertain' if uncertain else 'high')
                or not p.get('reviewer') or not p.get('interpretation')):
            raise ValueError('Explicit assistant provenance and uncertainty are required')
        date.fromisoformat(p['observed_on'])
        scene, region = p['scene_id'], p['region_id']
        if not region or regions.setdefault((scene, region), split) != split:
            raise ValueError('A region cannot cross splits')
        col, row, width, height = p['source_window']
        if any(type(v) is not int for v in (col, row, width, height)) or min(col, row) < 0 or min(width, height) <= 0:
            raise ValueError('Invalid source window')
        with rasterio.open(Path(image_dir) / f'{scene}.tif') as src:
            if not src.crs or not src.crs.is_projected or src.crs.linear_units != 'metre':
                raise ValueError('Metric projected source required')
            if col+width > src.width or row+height > src.height:
                raise ValueError('Label extends outside source')
            values = src.read(window=Window(col, row, width, height))
            if not (src.read_masks(window=Window(col, row, width, height)) != 0).all() or not np.isfinite(values).all():
                raise ValueError('Invalid source pixels in label')
            corners = [src.transform * xy for xy in ((col,row),(col+width,row),(col+width,row+height),(col,row+height),(col,row))]
            geometry = feature['geometry']
            if geometry.get('type') != 'Polygon' or len(geometry['coordinates']) != 1:
                raise ValueError('Core rectangle polygon required')
            actual = np.asarray(transform_geom('EPSG:4326', src.crs, geometry)['coordinates'][0])
            if actual.shape != (5,2) or not np.isfinite(actual).all() or not np.allclose(actual, corners, rtol=0, atol=0.001):
                raise ValueError('Geometry does not match source window')
            area = width*height*abs(src.transform.a*src.transform.e-src.transform.b*src.transform.d)
            if p['core_pixels'] != width*height or not math.isclose(p['area_m2'], area, abs_tol=1e-6):
                raise ValueError('Incorrect core area')
            xs, ys = zip(*corners)
            bounds = (min(xs), min(ys), max(xs), max(ys))
        for other_scene, other_split, other_bounds in boxes:
            if other_scene != scene:
                continue
            a,b,c,d = bounds; e,f,g,h = other_bounds
            if min(c,g) > max(a,e) and min(d,h) > max(b,f):
                raise ValueError('Overlapping label cores')
            gap = math.hypot(max(e-c,a-g,0), max(f-d,b-h,0))
            if other_split != split and gap < minimum_split_gap_m:
                raise ValueError('Different splits are too close')
        boxes.append((scene,split,bounds))
        counts[(scene,split,category)] += 1
        if evidence_dir is not None:
            path = Path(evidence_dir) / (p['source_crop']+'-source.png')
            evidence[path.name] = sha256(path.read_bytes()).hexdigest()
    return {'status':'structural_checks_passed', 'total_labels':len(ids),
            'usable_assistant_labels':sum(n for (_,_,c),n in counts.items() if c!='uncertain'),
            'withheld_uncertain':sum(n for (_,_,c),n in counts.items() if c=='uncertain'),
            'human_reviewed_labels':0, 'real_accuracy':None, 'minimum_split_gap_m':minimum_split_gap_m,
            'counts':[dict(scene_id=s,split=t,category=c,count=n) for (s,t,c),n in sorted(counts.items())],
            'evidence_sha256':evidence,
            'limitations':['Assistant visual interpretation requires independent human review.',
                           'Core labels are spatially separated but not representative area samples.',
                           'Vegetation does not establish ownership, park status or public access.']}
