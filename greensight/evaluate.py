"""Evaluate a mask only against explicit, independently reviewed references."""
from datetime import date
import numpy as np
from rasterio.features import rasterize, is_valid_geom
from rasterio.warp import transform_geom


def evaluate_mask(mask, references, transform, crs, *, target):
    """Return binary metrics or a clear not-ready status; never invent labels.

    references: WGS84 polygon GeoJSON with matching top-level target, plus
    properties: class=positive/negative, origin=human, split=test,
    review_status=reviewed, reviewer, observed_on, region_id.
    Evaluate raw-mask for vegetation; final mask for eligible_green only.
    uncertain=2 is abstention, included in coverage/overall accuracy reporting.
    """
    if target not in ('vegetation','eligible_green') or references.get('target') != target:
        raise ValueError('References must explicitly match the evaluation target')
    predicted = np.asarray(mask)
    if predicted.ndim != 2 or not all(predicted.shape) or not np.isin(predicted,[0,1,2,255]).all():
        raise ValueError('Expected a non-empty class mask')
    features = references.get('features',[])
    if not features:
        return {'status':'reviewed_labels_required','target':target,'metrics':None,'reviewed_polygons':0}
    truth = np.full(predicted.shape,255,dtype='uint8')
    for f in features:
        props=f.get('properties') or {}
        if not (props.get('origin')=='human' and props.get('split')=='test' and props.get('review_status')=='reviewed'
                and props.get('reviewer') and props.get('observed_on') and props.get('region_id')):
            raise ValueError('Independent human-reviewed test references are required')
        date.fromisoformat(props['observed_on'])
        if props.get('class') not in ('positive','negative'):
            raise ValueError('Reference class must be positive or negative')
        geometry=f.get('geometry') or {}
        if geometry.get('type') not in ('Polygon','MultiPolygon') or not is_valid_geom(geometry):
            raise ValueError('Valid reference polygons are required')
        footprint=rasterize([transform_geom('EPSG:4326',crs,geometry)],out_shape=truth.shape,transform=transform,fill=0,default_value=1,dtype='uint8').astype(bool)
        if (footprint & (truth!=255)).any():
            raise ValueError('Reference polygons must not overlap on the evaluation grid')
        truth[footprint]=int(props['class']=='positive')
    valid=(truth!=255)&(predicted!=255)
    covered=valid&(predicted!=2)
    if not valid.any() or not (truth[valid]==0).any() or not (truth[valid]==1).any():
        return {'status':'both_reference_classes_required','target':target,'metrics':None,'reviewed_polygons':len(features)}
    tp=int((covered&(truth==1)&(predicted==1)).sum())
    tn=int((covered&(truth==0)&(predicted==0)).sum())
    fp=int((covered&(truth==0)&(predicted==1)).sum())
    fn=int((covered&(truth==1)&(predicted==0)).sum())
    ratio=lambda a,b: a/b if b else None
    return {'status':'evaluated_on_supplied_references_only','target':target,'reviewed_polygons':len(features),
            'metrics':{'tp':tp,'tn':tn,'fp':fp,'fn':fn,'precision':ratio(tp,tp+fp),'recall_on_classified':ratio(tp,tp+fn),
                       'f1_on_classified':ratio(2*tp,2*tp+fp+fn),'iou_on_classified':ratio(tp,tp+fp+fn),
                       'positive_recall_including_abstentions':ratio(tp,int((valid&(truth==1)).sum())),
                       'reference_valid_data_coverage':ratio(int(valid.sum()),int((truth!=255).sum())),
                       'classified_coverage':ratio(int(covered.sum()),int(valid.sum())),
                       'accuracy_including_abstentions':ratio(tp+tn,int(valid.sum())),
                       'abstained_reference_pixels':int((valid&(predicted==2)).sum())},
            'limitations':['Caller must establish reference independence, dates, representativeness and label truth.']}
