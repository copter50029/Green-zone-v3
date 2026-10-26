"""Withhold transport/restricted green in a separate layer, not the main total."""
import numpy as np
import rasterio
from rasterio.enums import ColorInterp
from rasterio.features import rasterize,is_valid_geom
from rasterio.warp import transform_geom
from .heatmap import make_heatmap


def separate_pending(result, policy, transform, crs, *, scene_id, pixel_m, min_area_m2=300, radius_m=50, style="red"):
    if policy.get('purpose')!='pending_review_areas':raise ValueError('Pending-review area policy required')
    shapes=[]
    for f in policy.get('features',[]):
        p=f.get('properties') or {};g=f.get('geometry') or {}
        if p.get('decision')!='withhold_from_main_total' or not p.get('scene_id') or not is_valid_geom(g) or g.get('type') not in ('Polygon','MultiPolygon'):
            raise ValueError('Explicit pending area polygons required')
        if p['scene_id']==scene_id:shapes.append(transform_geom('EPSG:4326',crs,g))
    mask=result['mask'];zone=rasterize(shapes,out_shape=mask.shape,transform=transform,fill=0,default_value=1,dtype='uint8').astype(bool) if shapes else np.zeros(mask.shape,dtype=bool)
    pending=np.where(mask==255,255,0).astype('uint8');pending[(mask==1)&zone]=1
    main=mask.copy();main[zone&(main!=255)]=0
    cleaned=make_heatmap(main,pixel_m,min_area_m2,radius_m,style=style)
    cleaned['rgba'][zone|(result['rgba'][:,:,3]==0)]=0
    amber=np.zeros((*mask.shape,4),dtype='uint8');amber[pending==1]=[255,174,35,210]
    initial=int((mask==1).sum());withheld=int((pending==1).sum());retained=int((cleaned['mask']==1).sum())
    report={'status':'pending_not_in_main_total','pending_candidate_area_m2':withheld*pixel_m**2,
            'main_candidate_area_m2':retained*pixel_m**2,'pre_partition_candidate_area_m2':initial*pixel_m**2,
            'subminimum_fragments_removed_after_partition_m2':(initial-withheld-retained)*pixel_m**2,
            'ownership_and_access':'unverified','zone_count':len(shapes)}
    return cleaned,pending,amber,report


def write_pending(folder, profile, mask, rgba):
    settings=profile.copy();settings.update(count=1,nodata=255,dtype='uint8')
    with rasterio.open(folder/'pending-mask.tif','w',**settings) as dst:dst.write(mask,1)
    settings.update(count=4,nodata=None)
    with rasterio.open(folder/'pending.tif','w',**settings) as dst:
        dst.write(np.moveaxis(rgba,-1,0));dst.colorinterp=(ColorInterp.red,ColorInterp.green,ColorInterp.blue,ColorInterp.alpha)
