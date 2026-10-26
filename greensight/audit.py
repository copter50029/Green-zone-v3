"""Whole-scene software consistency audit; semantic park verification stays pending."""
from pathlib import Path
import math
import numpy as np
import rasterio
from rasterio.windows import Window
from rasterio.warp import transform as project_points,transform_geom
from rasterio.features import rasterize
from scipy.ndimage import label,find_objects
from .scene import read_json,write_json,digest,windows
from .detect import detect_green
from .exclusions import exclude_context,exclude_policy_areas


def audit_scene(scene_dir, source_path, *, context_path, policy_path=None, pending_path=None):
    """Check every source pixel/window and every retained component; no accuracy claim."""
    folder=Path(scene_dir);s=read_json(folder/'summary.json')
    if read_json(folder/'status.json')['status']!='complete':raise ValueError('Incomplete scene')
    for name,h in s['artifact_sha256'].items():
        if digest(folder/name)!=h:raise ValueError('Artifact hash mismatch: '+name)
    if digest(source_path)!=s['provenance']['source_sha256']:raise ValueError('Source hash mismatch')
    if digest(context_path)!=s['provenance']['context_sha256']:raise ValueError('Context hash mismatch')
    if policy_path and digest(policy_path)!=s['provenance']['policy_exclusions_sha256']:raise ValueError('Policy hash mismatch')
    checked_pixels=valid_pixels=0
    with rasterio.open(source_path) as source,rasterio.open(folder/'raw-mask.tif') as raw:
        assert source.shape==raw.shape and source.crs==raw.crs and source.transform==raw.transform
        for win in windows(source.width,source.height,512):
            actual=raw.read(1,window=win)
            if source.read_masks(1,window=win).any():
                expected=detect_green(source.read(window=win),red_band=s['red_band_assumption'],nir_band=s['nir_band_assumption'],nodata=source.nodata,valid_mask=(source.read_masks(window=win)!=0).all(axis=0))
                np.testing.assert_array_equal(actual,expected)
            else:assert (actual==255).all()
            checked_pixels+=int(win.width*win.height);valid_pixels+=int((actual!=255).sum())
        col,row,width,height=s['crop_window']
        original=raw.read(1,window=Window(col,row,width,height))
        expected_grid=source.window_transform(Window(col,row,width,height))
    with rasterio.open(folder/'candidate-mask.tif') as src,rasterio.open(folder/'heatmap.tif') as heat:
        assert src.crs==heat.crs and src.transform==heat.transform==expected_grid and src.shape==heat.shape==(height,width)
        mask=src.read(1);rgba=heat.read()
        assert np.array_equal(original==255,mask==255)
        assert not ((mask==1)&(original!=1)).any()
        assert not rgba[:,mask==255].any()
        cfg=s['context_exclusions']['buffers_m']
        filtered,_,blocked=exclude_context(original,read_json(context_path),src.transform,src.crs,building_buffer_m=cfg['buildings'],house_buffer_m=cfg['houses'],residential_buffer_m=cfg['residential'],return_exclusion_mask=True)
        if policy_path:
            filtered,policy=exclude_policy_areas(filtered,read_json(policy_path),src.transform,src.crs,scene_id=s['scene_id']);blocked|=policy
        assert not (mask[blocked]==1).any() and not rgba[3,blocked].any()
        assert not ((mask==1)&(filtered!=1)).any()
        components,count=label(mask==1,structure=[[0,1,0],[1,1,1],[0,1,0]])
        sizes=np.bincount(components.ravel(),minlength=count+1)[1:]
        pixel_area=abs(src.transform.a*src.transform.e)
        assert (sizes*pixel_area>=s['minimum_patch_m2']).all()
        area=int(sizes.sum())*pixel_area
        assert area==s['stats']['retainedCandidateAreaM2']
        assert count==s['stats']['retainedPatchCount']
        assert valid_pixels*pixel_area==s['valid_area_m2']
        pending_count=0
        if pending_path:
            assert digest(pending_path)==s['provenance']['pending_areas_sha256']
            with rasterio.open(folder/'pending-mask.tif') as psrc,rasterio.open(folder/'pending.tif') as prgba:
                assert psrc.transform==src.transform and psrc.crs==src.crs and psrc.shape==src.shape
                p=psrc.read(1);pending_alpha=prgba.read(4)
                assert np.array_equal(p==255,mask==255)
                assert not ((p==1)&((mask==1)|(original!=1)|blocked)).any()
                assert not pending_alpha[p!=1].any()
                pending_count=int((p==1).sum())
            zones=[transform_geom('EPSG:4326',src.crs,f['geometry']) for f in read_json(pending_path)['features'] if f['properties']['scene_id']==s['scene_id']]
            zone=rasterize(zones,out_shape=mask.shape,transform=src.transform,fill=0,default_value=1,dtype='uint8').astype(bool) if zones else np.zeros(mask.shape,dtype=bool)
            assert not (mask[zone]==1).any() and not rgba[3,zone].any()
            report=s['pending_review']
            assert pending_count*pixel_area==report['pending_candidate_area_m2']
            assert area+report['pending_candidate_area_m2']+report['subminimum_fragments_removed_after_partition_m2']==report['pre_partition_candidate_area_m2']
        catalog=[]
        for identifier,box in enumerate(find_objects(components),1):
            if box is None:continue
            rr,cc=np.argwhere(components[box]==identifier)[0]
            rr+=box[0].start;cc+=box[1].start
            x,y=src.transform*(int(cc)+.5,int(rr)+.5)
            lon,lat=project_points(src.crs,'EPSG:4326',[x],[y])
            catalog.append({'patch_id':identifier,'area_m2':int(sizes[identifier-1])*pixel_area,
                'window':[box[1].start,box[0].start,box[1].stop-box[1].start,box[0].stop-box[0].start],
                'sample_lon_lat':[lon[0],lat[0]],'public_eligibility':'needs_independent_review'})
    result={'scene_id':s['scene_id'],'software_consistency':'passed','source_pixels_checked':checked_pixels,
            'valid_pixels_checked':valid_pixels,'retained_components_checked':count,'candidate_area_m2':area,
            'exclusion_core_and_alpha_check':'passed','hashes':'passed','real_accuracy':None,
            'public_park_verification':'pending','separate_pending_pixels':pending_count,'limitations':'Exhaustive pixel consistency is not proof of vegetation truth or public access.'}
    write_json(folder/'patch-review-catalog.json',catalog);write_json(folder/'audit.json',result)
    return result
