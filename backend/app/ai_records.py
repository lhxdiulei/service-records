"""Stable AI record reuse and job -> concrete revision links."""
import re
import unicodedata
from . import services as S, models as M, deletions as D
from .db import one,rows,plain,digest


def normalized(text):
    return re.sub(r'[\W_]+','',unicodedata.normalize('NFKC',text or '')).casefold()


def revision_content(kind,r):
    if kind=='ticket':
        return dict(title=r['title'],first_visible_message_id=r['first_visible_message_id'],first_question_message_id=r['first_question_message_id'],date_basis=r['date_basis'],
            problem=r['problem_text'],impact=r['impact_text'],handling_summary=r['handling_summary'],current_conclusion=r['current_conclusion'],status=r['status'],claims=r['claims'],next_actions=r['next_actions'])
    return dict(question=r['question'],answer=r['answer'],answer_state=r['answer_state'],applicability=r['applicability'],answer_claims=r['answer_claims'],
        contributors=[{key:c[key] for key in ('participant_id','contribution','evidence_span_ids')} for c in r['contributors']])


def signature(kind,content,bindings):
    content=plain((M.TicketContent if kind=='ticket' else M.QAContent).model_validate(content).model_dump())
    if kind=='qa':
        for c in content['contributors']:c['evidence_span_ids']=sorted(c['evidence_span_ids'])
        content['contributors'].sort(key=lambda c:c['participant_id'])
    proof=sorted({(b['field_key'],str(b['evidence_span_id']),b.get('relation','supports')) for b in bindings})
    return digest(dict(content=content,evidence=proof))


def latest(db,kind,object_id):
    table,parent=('ticket_revisions','ticket_id') if kind=='ticket' else ('qa_revisions','qa_id')
    r=one(db,f'SELECT r.id FROM {table} r WHERE r.{parent}=%s AND NOT '+D.deleted(kind+'_draft','r')+' ORDER BY revision_no DESC LIMIT 1',(object_id,))
    return S.revision_detail(db,kind,r['id']) if r else None


def link(db,job,kind,parent,revision,issue_id,action):
    db.execute('''INSERT INTO extraction_job_records(job_id,customer_id,record_kind,record_id,revision_id,issue_id,action)
        VALUES(%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING''',(job['id'],job['customer_id'],kind,parent['id'],revision['id'],issue_id,action))


def save(db,user,job,step,kind,parent,content,bindings,issue_ids):
    parent=S.entity(db,'tickets' if kind=='ticket' else 'qa_entries',parent['id'],user,True)
    old=latest(db,kind,parent['id'])
    if old and signature(kind,revision_content(kind,old),old['evidence'])==signature(kind,content,bindings):
        action='reused';revision=old
    elif old and (old['state']=='in_review' or old['origin']=='human' and old['state'] in ('draft','rejected')):
        action='manual_review_required';revision=old
    else:
        data=dict(content=content,evidence=bindings,expected_object_version=parent['version'],base_revision_id=parent['current_revision_id'])
        if kind=='qa':data['issue_ids']=issue_ids
        if old and old['state'] in ('draft','rejected') and old['origin']=='ai':data['replaces_revision_id']=old['id']
        revision=S.create_revision(db,user,kind,parent['id'],data,origin='ai',step_id=step['id'])
        action='updated' if old else 'created'
    link(db,job,kind,parent,revision,issue_ids[0],action)
    return revision


def answer_proof(db,evidence_ids):
    return sorted((str(e['message_id']),e['start_cp'],e['end_cp']) for e in rows(db,'SELECT * FROM evidence_spans WHERE id=ANY(%s::uuid[])',(list(map(str,evidence_ids)),)))


def find_qa(db,issue_id,question,bindings):
    proof=answer_proof(db,{b['evidence_span_id'] for b in bindings if b['field_key']=='answer' or b['field_key'].startswith('answer_claims.')})
    question_proof=answer_proof(db,{b['evidence_span_id'] for b in bindings if b['field_key']=='question'})
    candidates=rows(db,'''SELECT DISTINCT q.* FROM qa_entries q JOIN qa_revisions r ON r.qa_id=q.id JOIN qa_issue_links l ON l.qa_revision_id=r.id
        WHERE l.issue_id=%s AND q.lifecycle='active' AND NOT '''+D.deleted('qa','q')+' ORDER BY q.created_at,q.id',(issue_id,))
    for q in candidates:
        r=latest(db,'qa',q['id'])
        if not r:continue
        existing=answer_proof(db,{b['evidence_span_id'] for b in r['evidence'] if b['field_key']=='answer' or b['field_key'].startswith('answer_claims.')})
        existing_question=answer_proof(db,{b['evidence_span_id'] for b in r['evidence'] if b['field_key']=='question'})
        if normalized(r['question'])==normalized(question) or proof and proof==existing or question_proof and question_proof==existing_question:return q
    return None


def existing_issue(db,customer_id,links):
    questions=[str(m['message_id']) for m in links if m['relation']=='question']
    if not questions:return None
    from .triage import suggest_issue
    quoted={issue_id for m in rows(db,'SELECT * FROM messages WHERE id=ANY(%s::uuid[])',(questions,)) if (issue_id:=suggest_issue(db,customer_id,m))}
    if len(quoted)==1:return one(db,'SELECT * FROM issues WHERE id=%s',(next(iter(quoted)),))
    return one(db,'''SELECT i.* FROM issues i JOIN tickets t ON t.issue_id=i.id WHERE i.customer_id=%s AND i.lifecycle='active'
        AND NOT '''+D.deleted('ticket','t')+''' AND EXISTS(SELECT 1 FROM issue_messages im JOIN messages a ON a.id=im.message_id
        JOIN messages b ON b.id=ANY(%s::uuid[]) WHERE im.issue_id=i.id AND im.active AND im.relation='question'
        AND NOT '''+D.deleted('message','a')+'''
        AND (a.id=b.id OR (a.text_sha256=b.text_sha256 AND a.sender_name_raw=b.sender_name_raw AND a.sent_at=b.sent_at)))
        ORDER BY i.created_at,i.id LIMIT 1''',(customer_id,questions))
