"""Clean saved candidate masks without rereading original satellite radiometry."""
from copy import deepcopy
from pathlib import Path
import shutil
import numpy as np
import rasterio
from rasterio.enums import ColorInterp
from .heatmap import make_heatmap
from .park_verify import prepare_park_review
from .scene import read_json,write_json,digest
from .pending import separate_pending,write_pending
from .exclusions import exclude_context, exclude_policy_areas


def clean_saved_results(run_dir, out_dir, *, clean_radius_m=2, registry_path='data/registry/parks15.geojson',
                        contexts=None, building_buffer_m=2, house_buffer_m=0, residential_buffer_m=0, policy_exclusions=None, pending_areas=None):
    """Remove narrow/small candidate fragments, recheck >=300m2, rebuild halos.

    Works on globally merged masks. Never adds candidate pixels; previous
    masks and their measurements remain available for before/after comparison.
    """
    source,output=Path(run_dir),Path(out_dir)
    if output.exists(): raise FileExistsError('Choose a new output directory')
    results=read_json(source/'summary-all.json'); registry=read_json(registry_path)
    pending_policy=read_json(pending_areas) if pending_areas else None
    policy=read_json(policy_exclusions) if policy_exclusions else None
    if policy:
        exclude_policy_areas(np.zeros((1,1),dtype='uint8'),policy,rasterio.Affine(1,0,0,0,-1,1),'EPSG:32647',scene_id='preflight')
    make_heatmap([[0]],.5,clean_radius_m=clean_radius_m)
    for old in results:
        scene=old['scene_id']
        if Path(scene).name!=scene or scene in ('.','..') or '/' in scene or '\\' in scene:
            raise ValueError('Invalid scene ID')
        if read_json(source/scene/'status.json')['status']!='complete': raise ValueError('Incomplete source run')
        for name in ('candidate-mask.tif','heatmap.tif','source.png'):
            if digest(source/scene/name)!=old['artifact_sha256'][name]: raise ValueError('Source hash mismatch')
        if digest(registry_path)!=old['provenance']['registry_sha256']: raise ValueError('Registry snapshot changed')
    if contexts:
        for old in results:
            context_path=contexts[old['scene_id']]
            if digest(context_path)!=old['provenance']['context_sha256']:
                raise ValueError('Context snapshot changed')
    output.mkdir(parents=True)
    updated=[]
    for old in results:
        scene=old['scene_id']; folder=output/scene;folder.mkdir()
        write_json(folder/'status.json',{'status':'processing','scene_id':scene})
        with rasterio.open(source/scene/'candidate-mask.tif') as src:
            mask=src.read(1); profile=src.profile.copy()
            eligibility_report=None
            filtered=mask
            blocked=None
            if contexts:
                filtered,eligibility_report,blocked=exclude_context(mask,read_json(contexts[scene]),src.transform,src.crs,
                    building_buffer_m=building_buffer_m,house_buffer_m=house_buffer_m,residential_buffer_m=residential_buffer_m,return_exclusion_mask=True)
            if policy:
                filtered,policy_mask=exclude_policy_areas(filtered,policy,src.transform,src.crs,scene_id=scene)
                blocked=policy_mask if blocked is None else blocked|policy_mask
            cleaned=make_heatmap(filtered,old['pixel_m'],old['minimum_patch_m2'],old['halo_radius_m'],style=old.get('heatmap_style','red'),clean_radius_m=clean_radius_m)
            pending_report=None
            if pending_policy:
                cleaned,pending_mask,pending_rgba,pending_report=separate_pending(cleaned,pending_policy,src.transform,src.crs,scene_id=scene,pixel_m=old['pixel_m'],min_area_m2=old['minimum_patch_m2'],radius_m=old['halo_radius_m'],style=old.get('heatmap_style','red'))
                write_pending(folder,profile,pending_mask,pending_rgba)
            with rasterio.open(source/scene/'heatmap.tif') as parent_heat:
                cleaned['rgba'][parent_heat.read(4)==0]=0
            if blocked is not None:
                cleaned['rgba'][blocked]=0
            assert not ((cleaned['mask']==1)&(mask!=1)).any()
            with rasterio.open(folder/'candidate-mask.tif','w',**profile) as dst: dst.write(cleaned['mask'],1)
            profile.update(count=4,nodata=None)
            with rasterio.open(folder/'heatmap.tif','w',**profile) as dst:
                dst.write(np.moveaxis(cleaned['rgba'],-1,0))
                dst.colorinterp=(ColorInterp.red,ColorInterp.green,ColorInterp.blue,ColorInterp.alpha)
            tasks=prepare_park_review(registry,cleaned['mask'],src.transform,src.crs,scene_id=scene,imagery_date=old['imagery_date'])
        shutil.copyfile(source/scene/'source.png',folder/'source.png')
        with rasterio.open(folder/'source.png') as src: rgb=src.read()
        with rasterio.open(folder/'heatmap.tif') as src: rgba=src.read(out_shape=(4,*rgb.shape[1:]))
        alpha=rgba[3:4].astype('float32')/255
        composite=np.round(rgb*(1-alpha)+rgba[:3]*alpha).astype('uint8')
        with rasterio.open(folder/'heatmap.png','w',driver='PNG',width=rgb.shape[2],height=rgb.shape[1],count=3,dtype='uint8') as dst: dst.write(composite)
        write_json(folder/'park-review.geojson',tasks)
        s=deepcopy(old)
        s.update(stats=cleaned['stats'],clean_radius_m=clean_radius_m,review_tasks=len(tasks['features']),verified_parks=0,
                 cleanup_parent={'summary_sha256':digest(source/scene/'summary.json'),'candidate_sha256':old['artifact_sha256']['candidate-mask.tif'],
                                 'candidate_area_m2':old['stats']['retainedCandidateAreaM2'],'run_directory':str(source.resolve())},
                 cleanup_method='disk morphological opening, then global four-neighbour area filter; no filling or added vegetation')
        if eligibility_report is not None:
            s['additional_eligibility_exclusions']=eligibility_report
            s['halo_clipped_to_exclusion_mask']=True
            s['eligibility_status']='conservative_screening_not_verified_public_land'
            s['limitations'].append('House/residential buffers deliberately exclude ambiguous neighbouring vegetation; incomplete mapping can still miss private yards.')
        if pending_report is not None:
            s['pending_review']=pending_report
            s['provenance']['pending_areas_sha256']=digest(pending_areas)
        if policy:
            s['policy_exclusions_sha256']=digest(policy_exclusions)
            s['policy_exclusions_basis']='assistant visual area interpretation; conservative exclusion, ownership unknown'
        s['provenance']['code_sha256']={p.name:digest(p) for p in Path(__file__).parent.glob('*.py')}
        s['limitations'].append('Morphology removes narrow vegetation and canopy fringes too; it does not prove semantic accuracy.')
        s['artifact_sha256']={name:digest(folder/name) for name in ('candidate-mask.tif','heatmap.tif','park-review.geojson','source.png','heatmap.png')}
        if pending_report is not None:
            s['artifact_sha256'].update({name:digest(folder/name) for name in ('pending-mask.tif','pending.tif')})
        write_json(folder/'summary.json',s)
        write_json(folder/'status.json',{'status':'complete','scene_id':scene})
        updated.append(s)
        print(scene,old['stats']['retainedCandidateAreaM2'],'->',s['stats']['retainedCandidateAreaM2'],flush=True)
    write_json(output/'summary-all.json',updated)
    return updated
