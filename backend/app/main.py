
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID

from fastapi import FastAPI, Request, Response, UploadFile, File, Form, Query

from . import config, models as M, services as S, identities as I, deletions as D, triage as T, import_screening as F, accounts as U
from .db import one, rows, insert, plain, uid, digest, audit
from .parser import decode_file, parse_text, VERSION
from .security import SecurityMiddleware, login, safe_user, require_role, match, fail, hash_token

app = FastAPI(title='客户服务记录',version='0.1.0',docs_url='/api/docs',openapi_url='/api/openapi.json',redoc_url=None)
app.add_middleware(SecurityMiddleware)
PREFIX='/api/v1'


def output(value, response=None, version=None, status=200):
    if response is not None:
        if version is not None:
            response.headers['ETag']=f'"{version}"'
        response.status_code=status
    return plain(value)


def ctx(request):
    return request.state.db, request.state.user


@app.delete(PREFIX+'/records/{record_kind}/{record_id}')
def delete_record(record_kind:str,record_id:UUID,request:Request):
    return output(D.mutate(*ctx(request),record_kind,record_id,request))


@app.post(PREFIX+'/records/{record_kind}/{record_id}/restore')
def restore_record(record_kind:str,record_id:UUID,request:Request):
    return output(D.mutate(*ctx(request),record_kind,record_id,request,restore=True))


@app.post(PREFIX+'/messages/reassess')
def reassess_messages(request:Request,dry_run:bool=True,state:Literal['needs_review','ignored']='needs_review'):
    db,user=ctx(request);require_role(user,'admin')
    return output(T.reassess(db,user,dry_run=dry_run,state=state))


@app.get('/api/health')
def health():
    from .db import connect
    with connect() as db:
        one(db,'SELECT 1')
    return {'status':'ok'}


@app.get(PREFIX+'/auth/csrf')
def csrf(request: Request, response: Response):
    token=request.cookies.get('sr_csrf') or secrets.token_urlsafe(32)
    session=request.state.session
    if session and not secrets.compare_digest(hash_token(token),bytes(session['csrf_token_hash'])):
        token=secrets.token_urlsafe(32)
        request.state.db.execute('UPDATE user_sessions SET csrf_token_hash=%s WHERE id=%s',(hash_token(token),session['id']))
    response.set_cookie('sr_csrf',token,httponly=True,secure=config.SECURE_COOKIE,samesite='lax',path='/')
    response.headers['Cache-Control']='no-store'
    return {'csrf_token':token}


@app.post(PREFIX+'/auth/login')
def sign_in(data:M.Login,request:Request,response:Response):
    return login(request.state.db,request,response,data.username,data.password)


@app.get(PREFIX+'/auth/me')
def me(request:Request):
    return safe_user(request.state.user)


@app.post(PREFIX+'/auth/logout')
def sign_out(request:Request,response:Response):
    request.state.db.execute('UPDATE user_sessions SET revoked_at=now() WHERE id=%s',(request.state.session['id'],))
    response.delete_cookie('sr_session',path='/')
    response.delete_cookie('sr_csrf',path='/')
    return {'ok':True}


@app.get(PREFIX+'/users')
def users(request:Request,page:int|None=Query(None,ge=1),page_size:int=Query(10,ge=1,le=100),q:str=Query('',max_length=200),
          role:Literal['admin','agent','reviewer']|None=None,status:Literal['active','deleted','all']='active'):
    db,user=ctx(request); require_role(user,'admin')
    query='SELECT '+','.join(U.PUBLIC_FIELDS)+' FROM users WHERE true';args=()
    if status!='all':query+=' AND disabled_at IS '+('NULL' if status=='active' else 'NOT NULL')
    if q.strip():query+=' AND (username ILIKE %s OR display_name ILIKE %s)';pattern=S.search_pattern(q.strip());args+=(pattern,pattern)
    if role:query+=' AND role=%s';args+=(role,)
    result=S.page_rows(db,query,args,'username,id',page,page_size) if page else rows(db,query+' ORDER BY username,id',args)
    for u in (result['items'] if page else result):u.update(U.public(u))
    return output(result)


@app.post(PREFIX+'/users',status_code=201)
def add_user(data:M.UserCreate,request:Request):
    from .security import passwords
    db,user=ctx(request);require_role(user,'admin')
    U.lock_admin(db,user)
    U.validate_username(db,data.username)
    I.validate_names(db,data.username,data.display_name,[])
    u=insert(db,'users',dict(id=uid(),username=data.username,display_name=data.display_name,role=data.role,password_hash=passwords.hash(data.password)))
    insert(db,'user_customer_scopes',dict(user_id=u['id'],customer_id=S.internal_customer(db,user)['id'],granted_by=user['id']))
    I.reconcile(db,bump_catalog=True)
    audit(db,user['id'],'create','user',u['id'])
    return safe_user(u)


@app.get(PREFIX+'/users/{user_id}')
def user_detail(user_id:UUID,request:Request,response:Response):
    db,user=ctx(request);require_role(user,'admin');target=U.target(db,user_id)
    return output(U.public(target),response,target['version'])


@app.patch(PREFIX+'/users/{user_id}')
def update_user(user_id:UUID,data:M.UserUpdate,request:Request,response:Response):
    db,user=ctx(request);require_role(user,'admin')
    result=U.update(db,user,user_id,data,request)
    return output(result,response,result['version'])


@app.delete(PREFIX+'/users/{user_id}')
def delete_user(user_id:UUID,request:Request,response:Response):
    db,user=ctx(request);require_role(user,'admin')
    result=U.remove(db,user,user_id,request)
    return output(result,response,result['version'])


@app.post(PREFIX+'/users/{user_id}/restore')
def restore_user(user_id:UUID,request:Request,response:Response):
    db,user=ctx(request);require_role(user,'admin')
    result=U.remove(db,user,user_id,request,restore=True)
    return output(result,response,result['version'])


@app.post(PREFIX+'/imports',status_code=201)
def upload(request:Request,file:Annotated[UploadFile,File()],group_id:Annotated[UUID|None,Form()]=None,encoding:Annotated[str,Form()]='auto'):
    db,user=ctx(request);require_role(user,'admin','agent')
    group=S.entity(db,'chat_groups',group_id,user,True) if group_id else None
    content=file.file.read(config.MAX_FILE_BYTES+1)
    if not content or len(content)>config.MAX_FILE_BYTES:fail(413,'file_size','文件不能为空，且最大10MB')
    sha=digest(content)
    if group:
        old=one(db,'SELECT * FROM import_batches WHERE group_id=%s AND file_sha256=%s',(group_id,sha))
    else:
        customer=S.internal_customer(db,user)
        old=one(db,'SELECT * FROM import_batches WHERE customer_id=%s AND file_sha256=%s ORDER BY created_at,id LIMIT 1',(customer['id'],sha))
    if old:
        D.active(db,'import',old['id'])
        F.annotate_batches(db,[old])
        return output(dict(batch=old,duplicate=True))
    try:
        text,resolved=decode_file(content,encoding);entries=parse_text(text)
    except ValueError as exc:fail(422,'parse_failed',str(exc))
    if len(entries)>20000:fail(422,'too_many_messages','单个文件最多20000条，请拆分文件')
    screening=F.prepare(entries)
    warnings=[{'index':i,'message':w} for i,e in enumerate(entries) for w in e['warnings']]
    if not group:
        group=insert(db,'chat_groups',dict(id=uid(),customer_id=customer['id'],name=Path(file.filename or 'chat.txt').name[:200]))
        group_id=group['id']
    key=f"imports/{group['customer_id']}/{group['id']}/{sha}.bin"
    path=config.DATA_DIR/key;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(content)
    batch=insert(db,'import_batches',dict(id=uid(),customer_id=group['customer_id'],group_id=group_id,uploaded_by=user['id'],
        original_filename=Path(file.filename or 'chat.txt').name,storage_key=key,file_sha256=sha,byte_size=len(content),
        source_encoding=resolved,parser_version=VERSION,state='needs_review' if warnings else 'ready',message_count=len(entries),parse_issues=warnings,
        prefilter_report=screening))
    job=insert(db,'background_jobs',dict(id=uid(),customer_id=group['customer_id'],kind='parse_import',batch_id=batch['id'],
        requested_by=user['id'],input_hash=sha,input_payload={'encoding':encoding},state='succeeded',attempt_count=1,started_at=datetime.now(timezone.utc),finished_at=datetime.now(timezone.utc)))
    snap=insert(db,'import_parse_snapshots',dict(id=uid(),customer_id=group['customer_id'],batch_id=batch['id'],source_job_id=job['id'],
        parse_version=1,parser_version=VERSION,parse_config={'encoding':encoding},resolved_encoding=resolved,preview_records=entries,
        warnings=warnings,record_count=len(entries),warning_count=len(warnings),error_count=sum(e['kind']=='malformed' for e in entries)))
    batch=one(db,'UPDATE import_batches SET parse_version=1,current_parse_snapshot_id=%s,parsed_at=now() WHERE id=%s RETURNING *',(snap['id'],batch['id']))
    audit(db,user['id'],'upload','import',batch['id'],batch['customer_id'])
    F.annotate_batches(db,[batch])
    return output(dict(batch=batch,duplicate=False))


def annotate_imports(db,batches):
    F.annotate_batches(db,batches)
    counts={}
    if batches:
        active='NOT '+D.deleted('message','m')
        for item in rows(db,'''SELECT m.batch_id,
            count(*) FILTER (WHERE '''+active+''') AS active,
            count(*) FILTER (WHERE '''+D.deleted('message','m')+''') AS deleted,
            count(*) FILTER (WHERE '''+active+''' AND d.state IN ('pending','needs_review')) AS pending,
            count(*) FILTER (WHERE '''+active+''' AND d.state='needs_review') AS needs_review,
            count(*) FILTER (WHERE '''+active+''' AND d.state='assigned') AS assigned,
            count(*) FILTER (WHERE '''+active+''' AND d.state='ignored') AS ignored
            FROM messages m JOIN message_dispositions d ON d.message_id=m.id
            WHERE m.batch_id=ANY(%s::uuid[]) GROUP BY m.batch_id''',([str(b['id']) for b in batches],)):
            counts[str(item.pop('batch_id'))]=item
    for batch in batches:
        batch['message_counts']=counts.get(str(batch['id']),dict(active=0,deleted=0,pending=0,needs_review=0,assigned=0,ignored=0))
    return batches


@app.get(PREFIX+'/imports')
def imports(request:Request,group_id:UUID|None=None,page:int|None=Query(None,ge=1),page_size:int=Query(10,ge=1,le=100),deleted:bool=False,
            q:str=Query('',max_length=200),status:Literal['all','confirmed','pending']='all'):
    db,user=ctx(request)
    if deleted:require_role(user,'admin')
    where,args=S.visibility(user,'b')
    if group_id:where+=' AND b.group_id=%s';args+=(group_id,)
    if q.strip():where+=' AND b.original_filename ILIKE %s';args+=(S.search_pattern(q.strip()),)
    if status!='all':where+=' AND b.confirmed_at IS '+('NOT NULL' if status=='confirmed' else 'NULL')
    query='SELECT b.*,'+D.metadata('import','b')+' FROM import_batches b WHERE '+where+' AND '+D.deleted('import','b')+'=%s'
    args+=(deleted,)
    result=S.page_rows(db,query,args,'b.created_at DESC,b.id',page,page_size) if page else rows(db,query+' ORDER BY b.created_at DESC,b.id LIMIT 200',args)
    annotate_imports(db,result['items'] if page else result)
    return output(result)


@app.get(PREFIX+'/imports/{import_id}')
def import_detail(import_id:UUID,request:Request):
    db,user=ctx(request)
    S.entity(db,'import_batches',import_id,user)
    batch=one(db,'SELECT b.*,'+D.metadata('import','b')+' FROM import_batches b WHERE b.id=%s',(import_id,))
    if batch['is_deleted']:require_role(user,'admin')
    return output(annotate_imports(db,[batch])[0])


@app.get(PREFIX+'/imports/{import_id}/preview')
def preview(import_id:UUID,request:Request,response:Response,offset:int=Query(0,ge=0),limit:int=Query(10,ge=1,le=500),page:int|None=Query(None,ge=1),page_size:int=Query(10,ge=1,le=100),screening:Literal['all','filtered','retained']='all'):
    db,user=ctx(request);batch=S.entity(db,'import_batches',import_id,user)
    batch['is_deleted']=D.is_deleted(db,'import',import_id)
    if batch['is_deleted']:require_role(user,'admin')
    snap=S.entity(db,'import_parse_snapshots',batch['current_parse_snapshot_id'],user)
    if page:offset=(page-1)*page_size;limit=page_size
    records=F.preview_records(db,batch,snap['preview_records'])
    batch['screening_summary']=F.preview_summary(batch,records)
    if screening!='all':records=[r for r in records if r['prefilter_filtered']==(screening=='filtered')]
    warnings=[]
    for warning in snap['warnings']:
        entry=snap['preview_records'][warning['index']]
        warnings.append(dict(warning,source_line_start=entry['source_line_start'],source_line_end=entry['source_line_end']))
    return output(dict(batch=batch,records=records[offset:offset+limit],warnings=warnings,total=len(records),page=page or offset//limit+1,
                       page_size=limit,screening_summary=batch['screening_summary']),response,batch['version'])


@app.post(PREFIX+'/imports/{import_id}/confirm')
def confirm(import_id:UUID,data:M.ConfirmImport,request:Request,response:Response):
    db,user=ctx(request);require_role(user,'admin','agent')
    batch=S.entity(db,'import_batches',import_id,user);group=S.entity(db,'chat_groups',batch['group_id'],user,True)
    batch=S.entity(db,'import_batches',import_id,user,True);match(request,batch['version'])
    D.active(db,'import',import_id)
    if batch['confirmed_at']:fail(409,'already_confirmed','此文件已经导入')
    if data.parse_version!=batch['parse_version']:fail(409,'parse_changed','解析结果已变化')
    snap=S.entity(db,'import_parse_snapshots',batch['current_parse_snapshot_id'])
    if snap['warnings'] and not data.accept_warnings:fail(422,'warnings_pending','请检查并确认解析警告')
    lookup=I.mapping(db)
    for index,e in enumerate(snap['preview_records']):
        person=None
        if e['sender']:
            person=one(db,'SELECT * FROM participants WHERE group_id=%s AND display_name=%s ORDER BY id LIMIT 1',(group['id'],e['sender']))
            person=person or insert(db,'participants',dict(id=uid(),customer_id=group['customer_id'],group_id=group['id'],display_name=e['sender'],**I.resolve(e['sender'],lookup)))
        mid=uid()
        insert(db,'messages',dict(id=mid,customer_id=group['customer_id'],group_id=group['id'],batch_id=import_id,source_index=index,
            sender_participant_id=person['id'] if person else None,sender_name_raw=e['sender'],sent_at=e['sent_at'],timestamp_raw=e['timestamp_raw'],
            raw_header=e['raw_header'],raw_text=e['raw_text'],normalized_text=e['raw_text'].strip(),direct_body_spans=e['direct_body_spans'],
            text_sha256=digest(e['raw_text'].encode()),kind=e['kind'],source_line_start=e['source_line_start'],source_line_end=e['source_line_end'],
            source_body_start=e['source_body_start'],source_body_end=e['source_body_end'],parse_warnings=e['warnings']))
        prefilter_reason=e.get('prefilter_reason')
        ignored=bool(prefilter_reason) or not batch.get('prefilter_report') and e['kind']=='media_placeholder'
        insert(db,'message_dispositions',dict(customer_id=group['customer_id'],message_id=mid,state='ignored' if ignored else 'needs_review' if e['kind']=='malformed' else 'pending',
            decision_source='rule' if ignored else None,prefilter_reason=prefilter_reason,
            reason=('导入预筛选：'+e['prefilter_reason_label']) if prefilter_reason else '仅媒体占位，当前只处理纯文本' if ignored else ''))
    batch=one(db,"""UPDATE import_batches SET state='confirmed',confirmed_at=now(),ingestion_version=%s,version=version+1 WHERE id=%s RETURNING *""",(group['ingestion_version']+1,import_id))
    db.execute('UPDATE chat_groups SET ingestion_version=ingestion_version+1,version=version+1 WHERE id=%s',(group['id'],))
    S.watermark(db,group['id']);audit(db,user['id'],'confirm','import',import_id,group['customer_id'])
    F.annotate_batches(db,[batch])
    return output(batch,response,batch['version'])


@app.get(PREFIX+'/messages')
def messages(request:Request,group_id:UUID|None=None,offset:int=Query(0,ge=0),limit:int=Query(10,ge=1,le=500),state:str|None=None,q:str=Query('',max_length=200),page:int|None=Query(None,ge=1),page_size:int=Query(10,ge=1,le=100),deleted:bool=False,batch_id:UUID|None=None):
    db,user=ctx(request)
    if deleted:require_role(user,'admin')
    if group_id:S.entity(db,'chat_groups',group_id,user)
    if batch_id:
        S.entity(db,'import_batches',batch_id,user)
        if D.is_deleted(db,'import',batch_id):require_role(user,'admin')
    where,args=S.visibility(user,'m')
    query='''SELECT m.*,b.original_filename AS source_filename,'''+D.metadata('message','m')+','+D.deleted('import','b')+''' AS deleted_with_import,
        p.role AS sender_role,p.linked_user_id AS sender_user_id,d.state AS disposition,d.version AS disposition_version,d.reason AS disposition_reason,
        d.decision_source AS disposition_source,
        CASE WHEN d.decision_source='model_validated' THEN (SELECT u->>'note' FROM jsonb_array_elements(js.output_json->'result'->'unassigned_messages') u WHERE u->>'message_id'=m.id::text LIMIT 1) ELSE '' END AS disposition_note
        FROM messages m JOIN import_batches b ON b.id=m.batch_id LEFT JOIN participants p ON p.id=m.sender_participant_id JOIN message_dispositions d ON d.message_id=m.id LEFT JOIN job_steps js ON js.id=d.source_job_step_id
        WHERE '''+where+' AND '+D.deleted('message','m')+'''=%s AND (%s::uuid IS NULL OR m.group_id=%s) AND (%s::text IS NULL OR d.state=%s) AND (m.raw_text ILIKE %s OR coalesce(m.sender_name_raw,'') ILIKE %s)'''
    pattern=S.search_pattern(q.strip())
    if page:offset=(page-1)*page_size;limit=page_size
    params=args+(deleted,group_id,group_id,state,state,pattern,pattern)
    if batch_id:query+=' AND m.batch_id=%s';params+=(batch_id,)
    result=S.page_rows(db,query,params,'m.sent_at NULLS LAST,m.batch_id,m.source_index,m.id',page or offset//limit+1,limit)
    if page is None and offset%limit:
        result['items']=rows(db,query+' ORDER BY m.sent_at NULLS LAST,m.batch_id,m.source_index,m.id LIMIT %s OFFSET %s',params+(limit,offset))
    result['items']=[S.effective_message(db,m) for m in result['items']]
    associated={str(m['id']):[] for m in result['items']}
    if associated:
        issue_where,issue_args=S.visibility(user,'i')
        for link in rows(db,'''SELECT im.message_id,i.id AS issue_id,i.label,t.id AS ticket_id
            FROM issue_messages im JOIN issues i ON i.id=im.issue_id JOIN tickets t ON t.issue_id=i.id
            WHERE im.active AND im.message_id=ANY(%s::uuid[]) AND '''+issue_where+' AND NOT '+D.deleted('ticket','t')+
            ' ORDER BY i.created_at,i.id', (list(associated),)+issue_args):
            associated[str(link.pop('message_id'))].append(link)
    for message in result['items']:message['assigned_issues']=associated[str(message['id'])]
    return output(result)


@app.put(PREFIX+'/messages/{message_id}/disposition')
def disposition(message_id:UUID,data:M.Disposition,request:Request,response:Response):
    db,user=ctx(request);require_role(user,'admin','agent','reviewer')
    m=S.entity(db,'messages',message_id,user);S.entity(db,'chat_groups',m['group_id'],user,True)
    D.active(db,'message',message_id)
    old=one(db,'SELECT * FROM message_dispositions WHERE message_id=%s FOR UPDATE',(message_id,));match(request,old['version'])
    if one(db,'SELECT 1 FROM issue_messages WHERE message_id=%s AND active',(message_id,)):
        fail(409,'message_assigned','请先从问题中移除此消息，再忽略')
    restored=bool(old['prefilter_reason'] and data.state=='needs_review')
    result=one(db,'''UPDATE message_dispositions SET state=%s,decision_source='human',reason=%s,decided_by=%s,version=version+1,updated_at=now(),
        prefilter_restored_at=CASE WHEN %s THEN coalesce(prefilter_restored_at,now()) ELSE prefilter_restored_at END
        WHERE message_id=%s RETURNING *''',(data.state,data.reason,user['id'],restored,message_id))
    S.watermark(db,m['group_id']);audit(db,user['id'],'disposition','message',message_id,m['customer_id'],{'state':data.state,'reason':data.reason,'prefilter_restored':restored})
    return output(result,response,result['version'])


@app.post(PREFIX+'/evidence-spans',status_code=201)
def add_evidence(data:M.EvidenceCreate,request:Request):
    db,user=ctx(request)
    return output(S.evidence(db,user,str(data.message_id),data.exact_excerpt,data.occurrence))


@app.get(PREFIX+'/issues')
def issues(request:Request,group_id:UUID|None=None):
    db,user=ctx(request)
    where,args=S.visibility(user,'i')
    if group_id:where+=' AND i.primary_group_id=%s';args+=(group_id,)
    result=rows(db,'SELECT i.* FROM issues i JOIN tickets t ON t.issue_id=i.id WHERE '+where+' AND NOT '+D.deleted('ticket','t')+' ORDER BY i.created_at DESC,i.id',args)
    for i in result:
        t=one(db,'SELECT id FROM tickets WHERE issue_id=%s',(i['id'],));i['ticket_id']=t['id'] if t else None
    return output(result)


@app.post(PREFIX+'/issues',status_code=201)
def new_issue(data:M.IssueCreate,request:Request):
    db,user=ctx(request);require_role(user,'admin','agent','reviewer')
    first=S.entity(db,'messages',data.messages[0].message_id,user)
    group=S.entity(db,'chat_groups',data.group_id or first['group_id'],user)
    S.lock_assignment_groups(db,user,group['customer_id'],[a.message_id for a in data.messages],[group['id']])
    return output(S.create_issue(db,user,group,data.title,[plain(a.model_dump()) for a in data.messages]))


@app.get(PREFIX+'/issues/{issue_id}')
def issue_detail(issue_id:UUID,request:Request,response:Response):
    db,user=ctx(request);issue=S.entity(db,'issues',issue_id,user)
    ticket=one(db,'SELECT id FROM tickets WHERE issue_id=%s',(issue_id,))
    return output(dict(issue=issue,ticket_id=ticket['id'] if ticket else None,messages=S.issue_messages(db,issue_id)),response,issue['version'])


@app.patch(PREFIX+'/issues/{issue_id}/messages')
def update_issue(issue_id:UUID,data:M.IssueMessages,request:Request,response:Response):
    db,user=ctx(request);S.lock_sources(db,[issue_id],user,[a.message_id for a in data.messages])
    issue=S.entity(db,'issues',issue_id,user);match(request,issue['version'])
    S.assign_messages(db,user,issue,[plain(a.model_dump()) for a in data.messages],replace=True)
    issue=S.entity(db,'issues',issue_id)
    audit(db,user['id'],'reassign','issue',issue_id,issue['customer_id'])
    return output(issue,response,issue['version'])


def decorate_objects(db,kind,items,include_deleted=False):
    for item in items:
        table,parent=('ticket_revisions','ticket_id') if kind=='ticket' else ('qa_revisions','qa_id')
        item['current_revision']=S.revision_detail(db,kind,item['current_revision_id']) if item['current_revision_id'] else None
        latest=one(db,f'SELECT r.id FROM {table} r WHERE {parent}=%s'+('' if include_deleted else ' AND NOT '+D.deleted(kind+'_draft','r'))+' ORDER BY revision_no DESC LIMIT 1',(item['id'],))
        item['latest_revision']=S.revision_detail(db,kind,latest['id']) if latest else None
        ids=[item['issue_id']] if kind=='ticket' else (item['latest_revision'] or {}).get('issue_ids',[])
        item['source_filenames']=[r['original_filename'] for r in rows(db,'''SELECT DISTINCT b.original_filename FROM issue_messages im
            JOIN messages m ON m.id=im.message_id JOIN import_batches b ON b.id=m.batch_id
            WHERE im.issue_id=ANY(%s::uuid[]) AND im.active ORDER BY b.original_filename''',(ids,))]
    return items


def list_objects(db,user,kind,page=None,page_size=10,customer_id=None,q='',deleted=False):
    if deleted:require_role(user,'admin')
    table,revisions,parent=('tickets','ticket_revisions','ticket_id') if kind=='ticket' else ('qa_entries','qa_revisions','qa_id')
    where,args=S.visibility(user,'t')
    if customer_id:where+=' AND t.customer_id=%s';args+=(customer_id,)
    search="coalesce(r.title,i.label,'')||' '||t.ticket_no||' '||coalesce(r.problem_text,'')||' '||coalesce(r.handling_summary,'')||' '||coalesce(r.current_conclusion,'')" if kind=='ticket' else "t.qa_no||' '||coalesce(r.question,'')||' '||coalesce(r.answer,'')||' '||coalesce(r.applicability,'')"
    query=f'''SELECT t.*,{D.metadata(kind,'t')} FROM {table} t LEFT JOIN LATERAL
        (SELECT * FROM {revisions} vr WHERE {parent}=t.id'''+('' if deleted else ' AND NOT '+D.deleted(kind+'_draft','vr'))+' ORDER BY revision_no DESC LIMIT 1) r ON true'
    if kind=='ticket':query+=' LEFT JOIN issues i ON i.id=t.issue_id'
    query+=' WHERE '+where+' AND '+D.object_deleted(kind,'t')+'=%s AND ('+search+') ILIKE %s';args+=(deleted,S.search_pattern(q.strip()))
    if not page:return decorate_objects(db,kind,rows(db,query+' ORDER BY t.created_at DESC,t.id LIMIT 200',args),deleted)
    result=S.page_rows(db,query,args,'t.created_at DESC,t.id',page,page_size)
    result['items']=decorate_objects(db,kind,result['items'],deleted)
    return result


@app.get(PREFIX+'/tickets')
def tickets(request:Request,page:int|None=Query(None,ge=1),page_size:int=Query(10,ge=1,le=100),customer_id:UUID|None=None,q:str=Query('',max_length=200),deleted:bool=False):
    return output(list_objects(*ctx(request),'ticket',page,page_size,customer_id,q,deleted))


@app.get(PREFIX+'/qa')
def qa(request:Request,page:int|None=Query(None,ge=1),page_size:int=Query(10,ge=1,le=100),customer_id:UUID|None=None,q:str=Query('',max_length=200),deleted:bool=False):
    return output(list_objects(*ctx(request),'qa',page,page_size,customer_id,q,deleted))


def review_query(user,customer_id=None):
    branches=[];args=()
    for kind,table,revisions,parent in [('ticket','tickets','ticket_revisions','ticket_id'),('qa','qa_entries','qa_revisions','qa_id')]:
        where,params=S.visibility(user,'t')
        if customer_id:where+=' AND t.customer_id=%s';params+=(customer_id,)
        branches.append(f'''SELECT t.id,'{kind}' AS object_kind,t.customer_id,r.created_at FROM {table} t JOIN LATERAL
            (SELECT * FROM {revisions} vr WHERE {parent}=t.id AND NOT {D.deleted(kind+'_draft','vr')} ORDER BY revision_no DESC LIMIT 1) r ON true
            WHERE {where} AND NOT {D.deleted(kind,'t')} AND r.state='in_review' ''')
        args+=params
    return ' UNION ALL '.join(branches),args


@app.get(PREFIX+'/reviews')
def reviews(request:Request,page:int=Query(1,ge=1),page_size:int=Query(10,ge=1,le=100),customer_id:UUID|None=None):
    db,user=ctx(request);query,args=review_query(user,customer_id)
    result=S.page_rows(db,query,args,'created_at DESC,id,object_kind',page,page_size)
    items=[]
    for r in result['items']:
        kind=r['object_kind'];item=S.entity(db,'tickets' if kind=='ticket' else 'qa_entries',r['id'],user)
        items.append(dict(decorate_objects(db,kind,[item])[0],objectKind=kind))
    result['items']=items
    return output(result)


@app.get(PREFIX+'/overview')
def overview(request:Request,customer_id:UUID|None=None,group_id:UUID|None=None):
    db,user=ctx(request);where,args=S.visibility(user,'r')
    if customer_id:where+=' AND r.customer_id=%s';args+=(customer_id,)
    result={}
    for key,table,extra in [('tickets','tickets',''),('official_tickets','tickets',' AND current_revision_id IS NOT NULL'),('qa','qa_entries',''),('official_qa','qa_entries',' AND current_revision_id IS NOT NULL')]:
        record_kind='ticket' if table=='tickets' else 'qa'
        result[key]=one(db,'SELECT count(*) AS n FROM '+table+' r WHERE '+where+' AND NOT '+D.object_deleted(record_kind,'r')+extra,args)['n']
    query,params=review_query(user,customer_id)
    result['reviews']=one(db,'SELECT count(*) AS n FROM ('+query+') pending',params)['n']
    message_where,message_args=S.visibility(user,'m')
    if customer_id:message_where+=' AND m.customer_id=%s';message_args+=(customer_id,)
    result['unassigned_messages']=one(db,"SELECT count(*) AS n FROM message_dispositions d JOIN messages m ON m.id=d.message_id WHERE "+message_where+' AND NOT '+D.deleted('message','m')+" AND d.state IN ('pending','needs_review')",message_args)['n']
    if group_id:
        g=S.entity(db,'chat_groups',group_id,user)
        if not customer_id or g['customer_id']==customer_id:
            result['unassigned_messages']=one(db,"SELECT count(*) AS n FROM message_dispositions d JOIN messages m ON m.id=d.message_id WHERE m.group_id=%s AND NOT "+D.deleted('message','m')+" AND d.state IN ('pending','needs_review')",(group_id,))['n']
    return output(result)


@app.post(PREFIX+'/qa',status_code=201)
def new_qa(data:M.QACreate,request:Request):
    db,user=ctx(request);issues,_=S.lock_sources(db,data.issue_ids,user)
    parent=insert(db,'qa_entries',dict(id=uid(),customer_id=issues[0]['customer_id'],qa_no='QA-'+uid()[:12].upper()))
    r=S.create_revision(db,user,'qa',parent['id'],dict(issue_ids=list(map(str,data.issue_ids)),content=plain(data.content.model_dump()),evidence=plain([e.model_dump() for e in data.evidence]),expected_object_version=1,base_revision_id=None))
    return output(dict(object=parent,revision=r))


def get_object(kind,object_id,request,response):
    db,user=ctx(request);obj=S.entity(db,'tickets' if kind=='ticket' else 'qa_entries',object_id,user)
    obj.update(one(db,'SELECT '+D.metadata(kind,'r')+' FROM '+D.TABLES[kind]+' r WHERE r.id=%s',(object_id,)))
    if obj['is_deleted']:require_role(user,'admin')
    table,parent=('ticket_revisions','ticket_id') if kind=='ticket' else ('qa_revisions','qa_id')
    revisions=rows(db,f'SELECT r.id FROM {table} r WHERE {parent}=%s AND NOT '+D.deleted(kind+'_draft','r')+' ORDER BY revision_no DESC',(object_id,))
    detail=dict(object=obj,revisions=[S.revision_detail(db,kind,r['id']) for r in revisions])
    issue_ids=[str(obj['issue_id'])] if kind=='ticket' else list({i for r in detail['revisions'] for i in r['issue_ids']})
    detail['source_messages']=list({str(m['id']):m for i in issue_ids for m in S.issue_messages(db,i,include_deleted=True)}.values())
    detail['participants']=rows(db,'SELECT * FROM participants WHERE id=ANY(%s::uuid[]) ORDER BY display_name,id',
        (sorted({str(m['sender_participant_id']) for m in detail['source_messages'] if m['sender_participant_id']}),))
    if kind=='ticket':
        detail['events']=rows(db,'SELECT * FROM ticket_events WHERE ticket_id=%s ORDER BY occurred_at,id',(object_id,))
        detail['notes']=rows(db,'''SELECT n.*,u.display_name AS author_name,u.username AS author_username
            FROM ticket_notes n LEFT JOIN users u ON u.id=n.author_id WHERE n.ticket_id=%s ORDER BY n.created_at,n.id''',(object_id,))
    revision_key='ticket_revision_id' if kind=='ticket' else 'qa_revision_id'
    detail['reviews']=rows(db,'''SELECT a.*,u.display_name AS actor_name,u.username AS actor_username,
        r.id AS revision_id,r.revision_no FROM review_actions a LEFT JOIN users u ON u.id=a.actor_id
        JOIN '''+table+' r ON r.id=a.'+revision_key+' WHERE a.'+revision_key+'=ANY(%s::uuid[]) ORDER BY a.created_at,a.id',
        ([str(r['id']) for r in detail['revisions']],)) if detail['revisions'] else []
    return output(detail,response,obj['version'])


@app.get(PREFIX+'/tickets/{object_id}')
def ticket_detail(object_id:UUID,request:Request,response:Response):return get_object('ticket',object_id,request,response)


@app.get(PREFIX+'/qa/{object_id}')
def qa_detail(object_id:UUID,request:Request,response:Response):return get_object('qa',object_id,request,response)


@app.post(PREFIX+'/tickets/{object_id}/revisions',status_code=201)
def ticket_revision(object_id:UUID,data:M.TicketRevisionCreate,request:Request,response:Response):
    db,user=ctx(request);obj=S.entity(db,'tickets',object_id,user);match(request,obj['version'])
    r=S.create_revision(db,user,'ticket',object_id,plain(data.model_dump()))
    return output(r,response,r['state_version'],201)


@app.post(PREFIX+'/qa/{object_id}/revisions',status_code=201)
def qa_revision(object_id:UUID,data:M.QARevisionCreate,request:Request,response:Response):
    db,user=ctx(request);obj=S.entity(db,'qa_entries',object_id,user);match(request,obj['version'])
    r=S.create_revision(db,user,'qa',object_id,plain(data.model_dump()))
    return output(r,response,r['state_version'],201)


def review(kind,object_id,revision_id,action,data,request,response):
    db,user=ctx(request)
    D.active(db,kind,object_id);D.active(db,kind+'_draft',revision_id)
    if action in ('approve','reject'):require_role(user,'admin','reviewer')
    table,parent_table,parent=('ticket_revisions','tickets','ticket_id') if kind=='ticket' else ('qa_revisions','qa_entries','qa_id')
    r=S.entity(db,table,revision_id,user)
    if str(r[parent])!=str(object_id):fail(404,'not_found','版本不属于此记录')
    S.lock_sources(db,list(r['issue_input_versions']),user)
    obj=S.entity(db,parent_table,object_id,user,True);r=S.entity(db,table,revision_id,user,True)
    D.active(db,kind,object_id);D.active(db,kind+'_draft',revision_id)
    match(request,r['state_version'])
    if data.expected_object_version!=obj['version'] or str(data.expected_current_revision_id or '')!=str(obj['current_revision_id'] or ''):
        fail(409,'base_changed','正式版本已变化')
    if action=='submit':
        if r['state']!='draft':fail(409,'invalid_state','只能提交草稿')
        S.approval_checks(db,kind,r,user)
        db.execute(f"UPDATE {table} SET state='in_review',state_version=state_version+1,submitted_at=now() WHERE id=%s",(revision_id,))
    else:
        if r['state']!='in_review':fail(409,'invalid_state','此版本不在审核中')
        if action=='approve':
            S.approval_checks(db,kind,r,user)
            if r['base_object_version']!=obj['version'] or str(r['base_revision_id'] or '')!=str(obj['current_revision_id'] or ''):
                fail(409,'base_changed','此草稿基于旧正式版本，请重新保存')
            if kind=='ticket':
                if not r['start_context_complete'] and not data.accept_incomplete_start:
                    fail(422,'incomplete_start','缺少原始提问，请明确确认以首次可见上下文记录日期')
                linked=S.issue_messages(db,obj['issue_id'])
                evidence_by_message={}
                for e in rows(db,'SELECT e.* FROM revision_evidence re JOIN evidence_spans e ON e.id=re.evidence_span_id WHERE re.ticket_revision_id=%s',(revision_id,)):
                    evidence_by_message.setdefault(str(e['message_id']),[]).append(e['id'])
                mapping={'question':'customer_message','answer':'support_reply','progress':'follow_up','correction':'correction','context':'follow_up'}
                for m in linked:
                    if not m['sent_at']:continue
                    event_key=f"{m['id']}:{mapping[m['relation']]}"
                    if one(db,'SELECT 1 FROM ticket_events WHERE ticket_id=%s AND event_key=%s',(object_id,event_key)):continue
                    event=insert(db,'ticket_events',dict(id=uid(),customer_id=obj['customer_id'],ticket_id=object_id,source_revision_id=revision_id,
                        event_key=event_key,kind=mapping[m['relation']],occurred_at=m['sent_at'],occurred_at_basis='source_message',summary=m['body_text'][:2000],created_by=user['id']))
                    for eid in set(evidence_by_message.get(str(m['id']),[])):insert(db,'event_evidence',dict(customer_id=obj['customer_id'],ticket_event_id=event['id'],evidence_span_id=eid))
                previous=one(db,'SELECT status FROM ticket_revisions WHERE id=%s',(obj['current_revision_id'],)) if obj['current_revision_id'] else None
                if not previous or previous['status']!=r['status']:
                    insert(db,'ticket_events',dict(id=uid(),customer_id=obj['customer_id'],ticket_id=object_id,source_revision_id=revision_id,event_key='revision:'+str(revision_id),
                        kind='status_change',occurred_at=datetime.now(timezone.utc),occurred_at_basis='approval_time',summary='审核确认状态',status_from=previous['status'] if previous else None,status_to=r['status'],created_by=user['id']))
            db.execute(f"UPDATE {table} SET state='approved',state_version=state_version+1,reviewed_by=%s,reviewed_at=now() WHERE id=%s",(user['id'],revision_id))
            db.execute(f'UPDATE {parent_table} SET current_revision_id=%s,version=version+1,updated_at=now() WHERE id=%s',(revision_id,object_id))
        else:
            if not data.comment.strip():fail(422,'reason_required','驳回需要填写原因')
            db.execute(f"UPDATE {table} SET state='rejected',state_version=state_version+1,reviewed_by=%s,reviewed_at=now() WHERE id=%s",(user['id'],revision_id))
    insert(db,'review_actions',dict(id=uid(),customer_id=obj['customer_id'],**{('ticket_revision_id' if kind=='ticket' else 'qa_revision_id'):revision_id},
        action=action,actor_id=user['id'],reason=data.comment,checks_snapshot={'issues':r['issue_input_versions'],'groups':r['group_input_versions']}))
    audit(db,user['id'],action,kind,revision_id,obj['customer_id'])
    result=S.revision_detail(db,kind,revision_id)
    return output(result,response,result['state_version'])


@app.post(PREFIX+'/tickets/{object_id}/revisions/{revision_id}/{action}')
def review_ticket(object_id:UUID,revision_id:UUID,action:str,data:M.Review,request:Request,response:Response):
    if action not in ('submit','approve','reject'):fail(404,'not_found','操作不存在')
    return review('ticket',object_id,revision_id,action,data,request,response)


@app.post(PREFIX+'/qa/{object_id}/revisions/{revision_id}/{action}')
def review_qa(object_id:UUID,revision_id:UUID,action:str,data:M.Review,request:Request,response:Response):
    if action not in ('submit','approve','reject'):fail(404,'not_found','操作不存在')
    return review('qa',object_id,revision_id,action,data,request,response)


@app.post(PREFIX+'/tickets/{ticket_id}/notes',status_code=201)
def note(ticket_id:UUID,data:M.Note,request:Request):
    db,user=ctx(request);t=S.entity(db,'tickets',ticket_id,user);match(request,t['version'])
    D.active(db,'ticket',ticket_id)
    result=insert(db,'ticket_notes',dict(id=uid(),customer_id=t['customer_id'],ticket_id=ticket_id,body=data.note,author_id=user['id']))
    result.update(author_name=user['display_name'],author_username=user['username'])
    audit(db,user['id'],'note','ticket',ticket_id,t['customer_id'])
    return output(result)


@app.get(PREFIX+'/statistics/daily')
def statistics(request:Request):
    db,user=ctx(request)
    visible="true" if user['role']=='admin' else 't.customer_id IN (SELECT customer_id FROM user_customer_scopes WHERE user_id=%s)'
    args=() if user['role']=='admin' else (user['id'],)
    return output(rows(db,f'''SELECT r.ticket_date AS day,count(*) AS tickets FROM tickets t JOIN ticket_revisions r ON r.id=t.current_revision_id
        WHERE {visible} AND NOT {D.deleted('ticket','t')} GROUP BY r.ticket_date ORDER BY r.ticket_date DESC LIMIT 90''',args))


@app.get(PREFIX+'/integrations/dify')
def integrations(request:Request):
    from .dify import profiles
    return profiles()


@app.post(PREFIX+'/imports/{import_id}/extractions',status_code=202)
def import_extract(import_id:UUID,data:M.Extract,request:Request):
    db,user=ctx(request);require_role(user,'admin','agent')
    b=S.entity(db,'import_batches',import_id,user)
    if not b['confirmed_at']:fail(409,'not_confirmed','请先确认导入')
    from .worker import enqueue
    return output(enqueue(db,user,data,batch=b))


@app.post(PREFIX+'/issues/{issue_id}/extractions',status_code=202)
def issue_extract(issue_id:UUID,data:M.Extract,request:Request):
    db,user=ctx(request);require_role(user,'admin','agent')
    issue=S.entity(db,'issues',issue_id,user)
    from .worker import enqueue
    return output(enqueue(db,user,data,issue=issue))


@app.get(PREFIX+'/jobs')
def jobs(request:Request,page:int|None=Query(None,ge=1),page_size:int=Query(10,ge=1,le=100),customer_id:UUID|None=None,batch_id:UUID|None=None):
    db,user=ctx(request)
    if batch_id:S.entity(db,'import_batches',batch_id,user)
    where,args=S.visibility(user)
    if customer_id:where+=' AND customer_id=%s';args+=(customer_id,)
    if batch_id:where+=' AND batch_id=%s';args+=(batch_id,)
    query='SELECT * FROM extraction_jobs WHERE '+where
    if not page:return output([public_job(j) for j in rows(db,query+' ORDER BY created_at DESC,id LIMIT 200',args)])
    result=S.page_rows(db,query,args,'created_at DESC,id',page,page_size)
    result['items']=[public_job(j) for j in result['items']]
    return output(result)


def public_job(job):
    job.pop('topic_plan',None)
    job['checkpoint']={k:v for k,v in job.get('checkpoint',{}).items() if k not in ('owned_disposition_versions','issue_versions')}
    return job


@app.get(PREFIX+'/jobs/{job_id}')
def job_detail(job_id:UUID,request:Request):
    db,user=ctx(request);job=S.entity(db,'extraction_jobs',job_id,user)
    # Input/output chat text remains server-side; UI sees progress and diagnostics only.
    job['steps']=rows(db,'SELECT id,stage,target_key,state,attempt_count,error_code,error_summary,dify_workflow_run_id,input_tokens,output_reserve,context_limit FROM job_steps WHERE job_id=%s ORDER BY created_at,id',(job_id,))
    return output(public_job(job))


@app.get(PREFIX+'/jobs/{job_id}/records')
def job_records(job_id:UUID,request:Request,page:int=Query(1,ge=1),page_size:int=Query(10,ge=1,le=100)):
    db,user=ctx(request);S.entity(db,'extraction_jobs',job_id,user)
    query='''SELECT record_kind,record_id,revision_id,issue_id,action,created_at FROM extraction_job_records WHERE job_id=%s
        UNION ALL SELECT 'ticket',t.id,r.id,t.issue_id,'created',r.created_at FROM ticket_revisions r JOIN tickets t ON t.id=r.ticket_id
        JOIN job_steps s ON s.id=r.source_job_step_id WHERE s.job_id=%s AND NOT EXISTS
        (SELECT 1 FROM extraction_job_records x WHERE x.job_id=s.job_id AND x.record_kind='ticket' AND x.revision_id=r.id)
        UNION ALL SELECT 'qa',q.id,r.id,(SELECT issue_id FROM qa_issue_links WHERE qa_revision_id=r.id ORDER BY issue_id LIMIT 1),'created',r.created_at
        FROM qa_revisions r JOIN qa_entries q ON q.id=r.qa_id JOIN job_steps s ON s.id=r.source_job_step_id WHERE s.job_id=%s AND NOT EXISTS
        (SELECT 1 FROM extraction_job_records x WHERE x.job_id=s.job_id AND x.record_kind='qa' AND x.revision_id=r.id)'''
    result=S.page_rows(db,'SELECT * FROM ('+query+') results',(job_id,job_id,job_id),'created_at,record_kind,revision_id',page,page_size)
    for item in result['items']:
        kind=item['record_kind'];parent=S.entity(db,D.TABLES[kind],item['record_id'],user)
        revision=S.revision_detail(db,kind,item['revision_id'])
        item.update(title=revision.get('title') or revision.get('question'),record_no=parent.get('ticket_no') or parent.get('qa_no'),
            revision_no=revision['revision_no'],state=revision['state'],created_by=revision['created_by'],
            is_deleted=D.is_deleted(db,kind,parent['id']) or revision['is_deleted'])
    return output(result)


@app.post(PREFIX+'/jobs/{job_id}/{action}')
def job_action(job_id:UUID,action:str,request:Request):
    db,user=ctx(request);require_role(user,'admin','agent');job=S.entity(db,'extraction_jobs',job_id,user,True);match(request,job['version'])
    if action=='cancel' and job['state'] in ('queued','running'):
        db.execute("UPDATE extraction_jobs SET state='cancel_requested',cancel_requested_at=now(),version=version+1 WHERE id=%s",(job_id,))
    elif action=='retry' and job['state'] in ('failed','partial_failed','cancelled'):
        if job['input_manifest'].get('identity_version')!=I.version(db):fail(409,'identity_changed','客服账号或微信昵称配置已变化，请创建新任务；已有结果保留')
        db.execute("UPDATE extraction_jobs SET state='queued',finished_at=NULL,error_code=NULL,error_summary=NULL,version=version+1 WHERE id=%s",(job_id,))
    else:fail(409,'invalid_job_action','此任务状态不允许该操作')
    audit(db,user['id'],action,'job',job_id,job['customer_id'])
    return output(S.entity(db,'extraction_jobs',job_id))
