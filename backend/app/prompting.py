"""Shared, dependency-free model view; also embedded in Dify code nodes."""
import json
import copy

ID_FIELDS={'message_id','participant_id','issue_id','existing_issue_id','first_visible_message_id',
           'first_question_message_id','occurred_message_id','existing_qa_id','qa_id','ticket_id',
           'revision_id','reply_to_message_id'}
ID_LISTS={'main_message_ids','context_message_ids','allowed_message_ids','support_message_ids','source_issue_ids'}


def alias_maps(payload):
    forward={}
    def add(value,prefix):
        if value and value not in forward:
            forward[value]=prefix+str(1+sum(v.startswith(prefix) for v in forward.values()))
    for m in payload.get('messages',[]):add(m['message_id'],'m')
    for p in payload.get('participants',[]):add(p['participant_id'],'p')
    for i in payload.get('candidate_issues',[]):add(i['issue_id'],'i')
    if payload.get('issue'):add(payload['issue']['issue_id'],'i')
    if payload.get('current_ticket'):
        add(payload['current_ticket']['ticket_id'],'t');add(payload['current_ticket']['revision_id'],'r')
    for q in payload.get('related_qa',[]):
        add(q['qa_id'],'q');add(q['revision_id'],'r')
    return forward,{v:k for k,v in forward.items()}


def replace_ids(value,mapping,key=''):
    if isinstance(value,dict):return {k:replace_ids(v,mapping,k) for k,v in value.items()}
    if isinstance(value,list):return [replace_ids(v,mapping,key) for v in value]
    if isinstance(value,str) and (key in ID_FIELDS or key in ID_LISTS):return mapping.get(value,value)
    return value


def model_view(payload):
    """Only presentation changes: raw text and sender identity stay intact."""
    data=copy.deepcopy(payload)
    for key in ('run','scope'):data.pop(key,None)
    used={m['participant_id'] for m in data['messages']}
    data['participants']=[p for p in data['participants'] if p['participant_id'] in used]
    for m in data['messages']:
        if m.get('body_text')==m['raw_text']:m.pop('body_text')
        for key in ('quoted_text','reply_to_message_id','parse_warnings','has_nontext'):
            if not m.get(key):m.pop(key,None)
        spans=m.get('direct_body_spans',[])
        if spans==[{'start':0,'end':len(m['raw_text'])}]:m.pop('direct_body_spans',None)
    for c in data.get('candidate_issues',[]):
        c.pop('version',None);c.pop('message_version',None)
        if c.get('summary')==c['title']:c.pop('summary',None)
        c.pop('support_message_ids',None)
    processing=data.pop('processing',{})
    if processing:
        data['processing']={k:v for k,v in processing.items() if k in ('phase','source_parts_complete','source_part_count','reduction_note','risks')}
    forward,_=alias_maps(data)
    return replace_ids(data,forward)


def restore_result(payload,result):
    _,reverse=alias_maps(model_view_original_participants(payload))
    return replace_ids(result,reverse)


def model_view_original_participants(payload):
    # Match the participant filtering used in model_view without recursively
    # constructing another model view.
    data=dict(payload)
    used={m['participant_id'] for m in payload['messages']}
    data['participants']=[p for p in payload['participants'] if p['participant_id'] in used]
    return data


def model_json(payload):
    return json.dumps(model_view(payload),ensure_ascii=False,separators=(',',':'))
