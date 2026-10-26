"""Explicit human review input, separate from original assistant annotations."""
from copy import deepcopy
from datetime import date


def prepare_label_review(labels):
    """Return an editable queue; blank decisions never count as human review."""
    return {'target':labels['target'],'instructions':'Inspect source imagery. Fill reviewer, reviewed_on, class and notes; leave unsure decisions blank.',
            'decisions':[{'label_id':f['id'],'scene_id':f['properties']['scene_id'],
                          'source_window':f['properties']['source_window'],
                          'source_crop':f['properties']['source_crop'],
                          'suggested_class':f['properties']['class'],
                          'class':None,'reviewer':'','reviewed_on':'','notes':''} for f in labels['features']]}


def apply_label_review(labels, review):
    """Return separate human train/validation/test collections from filled decisions.

    The caller must supply real human decisions; this function checks records,
    not reviewer identity or semantic truth. Originals are never mutated.
    """
    if review.get('target') != labels.get('target'):
        raise ValueError('Review target mismatch')
    source={f['id']:f for f in labels['features']}
    seen=set()
    result={split:{'type':'FeatureCollection','target':labels['target'],'features':[]} for split in ('train','validation','test')}
    for decision in review['decisions']:
        identifier=decision['label_id']
        if identifier not in source or identifier in seen:
            raise ValueError('Unknown or duplicate review ID')
        seen.add(identifier)
        if decision.get('class') is None:
            continue
        if decision['class'] not in ('positive','negative','uncertain') or not all(str(decision.get(k) or '').strip() for k in ('reviewer','reviewed_on','notes')):
            raise ValueError('Reviewed decisions need class, reviewer, date and notes')
        date.fromisoformat(decision['reviewed_on'])
        if decision['class']=='uncertain':
            continue
        feature=deepcopy(source[identifier]); p=feature['properties']
        p['assistant_source']=deepcopy(source[identifier]['properties'])
        p.update({'class':decision['class'],'origin':'human','review_status':'reviewed',
                  'human_review_status':'reviewed','human_reviewer':decision['reviewer'],
                  'reviewer':decision['reviewer'],'observed_on':decision['reviewed_on'],
                  'certainty':'human_reviewed','review_notes':decision['notes']})
        result[p['split']]['features'].append(feature)
    return result
