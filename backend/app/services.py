"""Business rules shared by HTTP endpoints and Dify workers."""


from .db import one, rows, insert, uid, plain, audit
from .security import fail, scope
from .parser import TZ, direct_parts
from . import deletions as D


def entity(db, table, key, user=None, lock=False):
    item = one(db, f'SELECT * FROM {table} WHERE id=%s' + (' FOR UPDATE' if lock else ''), (key,))
    if not item:
        fail(404,'not_found','记录不存在')
    if user:
        scope(db,user,item['customer_id'])
    return item


def list_scoped(db, user, table, extra='', args=(), limit=200):
    where = "customer_id IN (SELECT customer_id FROM user_customer_scopes WHERE user_id=%s)" if user['role'] != 'admin' else 'true'
    params = (user['id'],) if user['role'] != 'admin' else ()
    return rows(db,f'SELECT * FROM {table} WHERE {where} {extra} ORDER BY created_at DESC,id LIMIT %s',params+tuple(args)+(limit,))


def visibility(user, alias='', column='customer_id'):
    prefix=alias+'.' if alias else ''
    return ('true',()) if user['role']=='admin' else (prefix+column+' IN (SELECT customer_id FROM user_customer_scopes WHERE user_id=%s)',(user['id'],))


def search_pattern(query):
    return '%'+query.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%'


def page_rows(db, query, args, order, page, page_size=10):
    """Count and page the same scoped, filtered query. SQL is application-owned."""
    total=one(db,'SELECT count(*) AS n FROM ('+query+') matches',args)['n']
    return dict(items=rows(db,query+' ORDER BY '+order+' LIMIT %s OFFSET %s',tuple(args)+(page_size,(page-1)*page_size)),
                total=total,page=page,page_size=page_size)


def internal_customer(db, user):
    """Resolve storage ownership without requiring customer setup in the product."""
    db.execute('SELECT pg_advisory_xact_lock(671904522)')
    where,args=visibility(user,column='id')
    customer=one(db,'SELECT * FROM customers WHERE disabled_at IS NULL AND '+where+' ORDER BY created_at,id LIMIT 1',args)
    if not customer:
        if user['role']!='admin':fail(403,'data_forbidden','当前账号尚未分配记录访问权限，请联系管理员')
        customer=insert(db,'customers',dict(id=uid(),name='内部服务记录'))
    return customer


def source_groups(db, issue_ids, extra_message_ids=()):
    return rows(db,'''SELECT * FROM chat_groups WHERE id IN (
        SELECT primary_group_id FROM issues WHERE id=ANY(%s::uuid[])
        UNION SELECT m.group_id FROM issue_messages im JOIN messages m ON m.id=im.message_id
        WHERE im.issue_id=ANY(%s::uuid[]) AND im.active
        UNION SELECT group_id FROM messages WHERE id=ANY(%s::uuid[])) ORDER BY id FOR UPDATE''',(issue_ids,issue_ids,list(map(str,extra_message_ids))))


def lock_assignment_groups(db,user,customer_id,message_ids,group_ids=()):
    scope(db,user,customer_id)
    messages=rows(db,'SELECT * FROM messages WHERE id=ANY(%s::uuid[])',(list(map(str,message_ids)),))
    if len(messages)!=len(set(map(str,message_ids))) or any(str(m['customer_id'])!=str(customer_id) for m in messages):
        fail(422,'message_scope','消息不在同一可访问数据范围')
    ids=sorted({str(m['group_id']) for m in messages}|set(map(str,group_ids)))
    return rows(db,'SELECT * FROM chat_groups WHERE id=ANY(%s::uuid[]) ORDER BY id FOR UPDATE',(ids,))


def effective_message(db, message):
    m = dict(message)
    a = one(db,'SELECT * FROM message_annotations WHERE message_id=%s ORDER BY annotation_no DESC LIMIT 1',(m['id'],))
    body, quoted, _ = direct_parts(m['raw_text'])
    m.update(body_text=body,quoted_text=quoted,message_annotation_id=None)
    if a:
        for name in ['sender_participant_id','sent_at','quoted_message_id','body_text','quoted_text','direct_body_spans']:
            m[name] = a[name]
        m['message_annotation_id'] = a['id']
    return m


def issue_messages(db, issue_id,include_deleted=False):
    return [effective_message(db,m) for m in rows(db,'''SELECT m.*,im.relation,b.original_filename AS source_filename,'''+D.metadata('message','m')+''' FROM issue_messages im
        JOIN messages m ON m.id=im.message_id JOIN import_batches b ON b.id=m.batch_id
        WHERE im.issue_id=%s AND im.active'''+('' if include_deleted else ' AND NOT '+D.deleted('message','m'))+' ORDER BY m.sent_at NULLS LAST,m.source_index,m.id',(issue_id,))]


def lock_sources(db, issue_ids, user, extra_message_ids=()):
    ids = sorted(set(map(str,issue_ids)))
    if not ids:
        fail(422,'source_required','至少关联一个问题')
    issues = rows(db,'SELECT * FROM issues WHERE id=ANY(%s::uuid[]) ORDER BY id',(ids,))
    if len(issues) != len(ids):
        fail(404,'issue_missing','来源问题不存在')
    customers = {str(i['customer_id']) for i in issues}
    if len(customers) != 1:
        fail(422,'customer_mismatch','不能混合不同客户的问题')
    scope(db,user,issues[0]['customer_id'])
    if extra_message_ids:lock_assignment_groups(db,user,issues[0]['customer_id'],extra_message_ids,
        [g['id'] for g in rows(db,'''SELECT DISTINCT m.group_id AS id FROM issue_messages im JOIN messages m ON m.id=im.message_id
            WHERE im.issue_id=ANY(%s::uuid[]) AND im.active UNION SELECT primary_group_id FROM issues WHERE id=ANY(%s::uuid[])''',(ids,ids))])
    groups = source_groups(db,ids,extra_message_ids)
    issues = rows(db,'SELECT * FROM issues WHERE id=ANY(%s::uuid[]) ORDER BY id FOR UPDATE',(ids,))
    if any(i['lifecycle'] != 'active' for i in issues):
        fail(409,'issue_merged','来源问题已合并')
    return issues, groups


def snapshots(issues, groups):
    return ({str(i['id']):i['message_version'] for i in issues},
            {str(g['id']):g['ingestion_version'] for g in groups})


def watermark(db, group_id):
    level = 0
    batches = rows(db,'SELECT * FROM import_batches WHERE group_id=%s AND confirmed_at IS NOT NULL ORDER BY ingestion_version',(group_id,))
    for batch in batches:
        pending = one(db,"""SELECT 1 FROM messages m LEFT JOIN message_dispositions d ON d.message_id=m.id
            WHERE m.batch_id=%s AND NOT """+D.deleted('message','m')+" AND (d.state IS NULL OR d.state IN ('pending','needs_review')) LIMIT 1",(batch['id'],))
        if pending:
            break
        level = batch['ingestion_version']
    db.execute('UPDATE chat_groups SET classified_version=%s WHERE id=%s',(level,group_id))


def assign_messages(db, user, issue, assignments, replace=False, ai=False):
    mids = [str(a['message_id']) for a in assignments]
    if len(set(mids)) != len(mids):
        fail(422,'duplicate_message','消息不能重复选择')
    messages = rows(db,'SELECT m.* FROM messages m WHERE id=ANY(%s::uuid[]) AND NOT '+D.deleted('message','m'),(mids,)) if mids else []
    ticket=one(db,'SELECT id FROM tickets WHERE issue_id=%s',(issue['id'],))
    D.active(db,'ticket',ticket['id'])
    if len(messages) != len(mids) or any(str(m['customer_id']) != str(issue['customer_id']) for m in messages):
        fail(422,'message_scope','消息不在同一可访问数据范围')
    scope(db,user,issue['customer_id'])
    affected = set(mids)
    if replace:
        old = rows(db,'SELECT message_id FROM issue_messages WHERE issue_id=%s AND active',(issue['id'],))
        affected |= {str(m['message_id']) for m in old}
        db.execute('UPDATE issue_messages SET active=false,removed_at=now() WHERE issue_id=%s AND active',(issue['id'],))
    for a in assignments:
        db.execute('''INSERT INTO issue_messages(customer_id,issue_id,message_id,relation,assignment_source,assigned_by)
            VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT(issue_id,message_id) DO UPDATE SET
            active=true,removed_at=NULL,relation=excluded.relation,assignment_source=excluded.assignment_source,
            assigned_by=excluded.assigned_by,assigned_at=now()''',
            (issue['customer_id'],issue['id'],str(a['message_id']),a['relation'],'ai_candidate' if ai else 'human_confirmed',None if ai else user['id']))
    for mid in sorted(affected):
        assigned = one(db,'SELECT 1 FROM issue_messages WHERE message_id=%s AND active LIMIT 1',(mid,))
        state = 'assigned' if assigned else 'needs_review'
        db.execute('''INSERT INTO message_dispositions(customer_id,message_id,state,decision_source,reason,decided_by)
            VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT(message_id) DO UPDATE SET state=excluded.state,
            decision_source=excluded.decision_source,reason=excluded.reason,decided_by=excluded.decided_by,
            version=message_dispositions.version+1,updated_at=now(),
            prefilter_restored_at=CASE WHEN message_dispositions.prefilter_reason IS NOT NULL
                THEN coalesce(message_dispositions.prefilter_restored_at,now()) ELSE NULL END''',
            (issue['customer_id'],mid,state,'model_validated' if ai else 'human','问题归属更新',None if ai else user['id']))
    db.execute('UPDATE issues SET message_version=message_version+1,version=version+1,updated_at=now() WHERE id=%s',(issue['id'],))
    for g in rows(db,'SELECT DISTINCT group_id FROM messages WHERE id=ANY(%s::uuid[])',(sorted(affected),)):
        watermark(db,g['group_id'])


def create_issue(db, user, group, title, assignments, ai=False):
    issue = insert(db,'issues',dict(id=uid(),customer_id=group['customer_id'],primary_group_id=group['id'],label=title,created_by=user['id']))
    ticket = insert(db,'tickets',dict(id=uid(),customer_id=group['customer_id'],issue_id=issue['id'],ticket_no='TK-'+uid()[:12].upper()))
    assign_messages(db,user,issue,assignments,ai=ai)
    audit(db,user['id'],'create','issue',issue['id'],group['customer_id'])
    return dict(issue=entity(db,'issues',issue['id']),ticket=ticket)


def locate(raw, excerpt, occurrence=1):
    start = -1
    for _ in range(occurrence):
        start = raw.find(excerpt,start+1)
        if start < 0:
            fail(422,'invalid_evidence','逐字引文不存在或出现次数超出范围')
    return start, start+len(excerpt)


def evidence(db, user, message_id, excerpt, occurrence=1):
    m = entity(db,'messages',message_id,user)
    entity(db,'chat_groups',m['group_id'],user,True)
    D.active(db,'message',message_id)
    start,end = locate(m['raw_text'],excerpt,occurrence)
    old = one(db,'SELECT * FROM evidence_spans WHERE message_id=%s AND start_cp=%s AND end_cp=%s',(message_id,start,end))
    return old or insert(db,'evidence_spans',dict(id=uid(),customer_id=m['customer_id'],message_id=message_id,start_cp=start,end_cp=end))


def validate_bindings(db, customer, issue_ids, bindings, claims):
    keys = [c['claim_key'] for c in claims]
    if len(keys) != len(set(keys)):
        fail(422,'duplicate_claim','断言编号不能重复')
    for b in bindings:
        e = one(db,'''SELECT e.* FROM evidence_spans e JOIN issue_messages im ON im.message_id=e.message_id AND im.active
            JOIN messages m ON m.id=e.message_id WHERE e.id=%s AND e.customer_id=%s AND im.issue_id=ANY(%s::uuid[]) AND NOT '''+D.deleted('message','m')+' LIMIT 1',(str(b['evidence_span_id']),customer,list(map(str,issue_ids))))
        if not e:
            fail(422,'evidence_scope','证据必须来自已关联的来源问题')
        field = b['field_key']
        if '.' in field:
            prefix,key = field.split('.',1)
            if prefix not in ('claims','answer_claims') or key not in keys:
                fail(422,'invalid_claim_key','证据指向的断言不存在')


def revision_detail(db, kind, revision_id):
    table = 'ticket_revisions' if kind == 'ticket' else 'qa_revisions'
    r = entity(db,table,revision_id)
    r.update(one(db,'SELECT '+D.metadata(kind+'_draft','r')+f' FROM {table} r WHERE r.id=%s',(revision_id,)))
    parent=entity(db,'tickets' if kind=='ticket' else 'qa_entries',r['ticket_id' if kind=='ticket' else 'qa_id'])
    r['stale'] = any(not (v := one(db,'SELECT message_version FROM issues WHERE id=%s',(key,))) or v['message_version']!=version for key,version in r['issue_input_versions'].items()) or any(not (v := one(db,'SELECT ingestion_version FROM chat_groups WHERE id=%s',(key,))) or v['ingestion_version']!=version for key,version in r['group_input_versions'].items())
    if r['state'] in ('draft','in_review','rejected') and r['base_object_version']!=parent['version']:r['stale']=True
    parent_field = 'ticket_revision_id' if kind == 'ticket' else 'qa_revision_id'
    r['evidence'] = rows(db,f'''SELECT e.id AS evidence_span_id,re.field_key,re.relation,e.message_id,e.start_cp,e.end_cp,
        substring(m.raw_text FROM e.start_cp+1 FOR e.end_cp-e.start_cp) AS excerpt,
        m.sender_name_raw,m.sent_at FROM revision_evidence re JOIN evidence_spans e ON e.id=re.evidence_span_id
        JOIN messages m ON m.id=e.message_id WHERE re.{parent_field}=%s ORDER BY re.field_key,e.id''',(revision_id,))
    if kind == 'qa':
        r['issue_ids'] = [str(x['issue_id']) for x in rows(db,'SELECT issue_id FROM qa_issue_links WHERE qa_revision_id=%s ORDER BY issue_id',(revision_id,))]
        r['contributors'] = rows(db,'SELECT c.*,p.identity_verified FROM qa_contributors c JOIN participants p ON p.id=c.participant_id WHERE c.qa_revision_id=%s ORDER BY c.participant_id',(revision_id,))
        for c in r['contributors']:
            c['evidence_span_ids'] = [str(e['evidence_span_id']) for e in rows(db,'SELECT evidence_span_id FROM contributor_evidence WHERE contributor_id=%s',(c['id'],))]
    return r


def create_revision(db, user, kind, object_id, data, origin='human', step_id=None):
    parent_table, rev_table, parent_field = ('tickets','ticket_revisions','ticket_id') if kind == 'ticket' else ('qa_entries','qa_revisions','qa_id')
    parent = entity(db,parent_table,object_id,user)
    D.active(db,kind,object_id)
    issue_ids = [str(parent['issue_id'])] if kind == 'ticket' else list(map(str,data['issue_ids']))
    issues,groups = lock_sources(db,issue_ids,user)
    for issue in issues:
        ticket=one(db,'SELECT id FROM tickets WHERE issue_id=%s',(issue['id'],))
        D.active(db,'ticket',ticket['id'])
    parent = entity(db,parent_table,object_id,user,True)
    D.active(db,kind,object_id)
    if parent['version'] != data['expected_object_version'] or str(parent['current_revision_id'] or '') != str(data.get('base_revision_id') or ''):
        fail(409,'base_changed','正式版本已变化，请重新加载后创建修订')
    if str(parent['customer_id']) != str(issues[0]['customer_id']):
        fail(422,'customer_mismatch','来源问题不属于该客户')
    if kind == 'qa' and parent['lifecycle'] != 'active':
        fail(409,'qa_withdrawn','请先恢复已归档知识')
    content = plain(data['content'])
    bindings = plain(data.get('evidence',[]))
    claims = content.get('claims' if kind == 'ticket' else 'answer_claims',[])
    validate_bindings(db,parent['customer_id'],issue_ids,bindings,claims)
    number = one(db,f'SELECT coalesce(max(revision_no),0)+1 AS n FROM {rev_table} WHERE {parent_field}=%s',(object_id,))['n']
    iv,gv = snapshots(issues,groups)
    values = dict(id=uid(),customer_id=parent['customer_id'],**{parent_field:object_id},revision_no=number,
        base_revision_id=parent['current_revision_id'],base_object_version=parent['version'],
        replaces_revision_id=data.get('replaces_revision_id'),issue_input_versions=iv,group_input_versions=gv,
        origin=origin,source_job_step_id=step_id,created_by=user['id'])
    if kind == 'ticket':
        mids = {str(m['id']):m for m in issue_messages(db,issue_ids[0])}
        fid,qid = str(content['first_visible_message_id']), str(content.get('first_question_message_id') or '')
        if fid not in mids or (qid and qid not in mids):
            fail(422,'date_source','日期来源消息必须属于此问题')
        if (content['date_basis']=='first_question') != bool(qid):
            fail(422,'date_basis','日期依据与原始提问消息不一致')
        first, question = mids[fid],mids.get(qid)
        known_times = [m['sent_at'] for m in mids.values() if m['sent_at']]
        if known_times and first['sent_at'] != min(known_times):
            fail(422,'first_visible_date','首次可见消息必须来自该问题最早的可见时间')
        chosen = question or first
        if not first['sent_at'] or not chosen['sent_at']:
            fail(422,'date_unknown','请先更正来源消息的时间')
        values.update(title=content['title'],first_visible_message_id=fid,first_visible_at=first['sent_at'],
            first_question_message_id=qid or None,first_question_at=question['sent_at'] if question else None,
            date_basis=content['date_basis'],ticket_date=chosen['sent_at'].astimezone(TZ).date(),
            start_context_complete=bool(question),problem_text=content['problem'],impact_text=content.get('impact',''),
            handling_summary=content.get('handling_summary',''),current_conclusion=content.get('current_conclusion',''),
            claims=claims,next_actions=content.get('next_actions',[]),status=content['status'])
        for action in values['next_actions']:
            if action['basis']=='explicit_in_chat' and not action['evidence_span_ids']:
                fail(422,'action_evidence','聊天中的待办必须提供证据')
            validate_bindings(db,parent['customer_id'],issue_ids,[dict(evidence_span_id=e,field_key='next_actions',relation='supports') for e in action['evidence_span_ids']],[])
    else:
        values.update(question=content['question'],answer=content.get('answer'),answer_state=content['answer_state'],
            applicability=content.get('applicability',''),answer_claims=claims)
    if data.get('replaces_revision_id'):
        D.active(db,kind+'_draft',data['replaces_revision_id'])
        old = entity(db,rev_table,data['replaces_revision_id'],user,True)
        if str(old[parent_field]) != str(object_id) or old['state'] not in ('draft','in_review','rejected'):
            fail(409,'cannot_replace','只能基于本对象的待审核或驳回版本修改')
        if old['state'] in ('draft','in_review'):
            db.execute(f"UPDATE {rev_table} SET state='superseded',state_version=state_version+1 WHERE id=%s",(old['id'],))
    r = insert(db,rev_table,values)
    if kind == 'qa':
        for issue_id in issue_ids:
            insert(db,'qa_issue_links',dict(customer_id=parent['customer_id'],qa_revision_id=r['id'],issue_id=issue_id))
        for c in content.get('contributors',[]):
            participant = entity(db,'participants',c['participant_id'],user)
            if str(participant['customer_id']) != str(parent['customer_id']):
                fail(422,'contributor_scope','核心贡献者必须来自当前记录的数据范围')
            contributor = insert(db,'qa_contributors',dict(id=uid(),customer_id=parent['customer_id'],qa_revision_id=r['id'],
                participant_id=c['participant_id'],contribution=c['contribution']))
            for eid in c['evidence_span_ids']:
                validate_bindings(db,parent['customer_id'],issue_ids,[dict(evidence_span_id=eid,field_key='contributor',relation='supports')],[])
                e = entity(db,'evidence_spans',eid)
                msg = effective_message(db,entity(db,'messages',e['message_id']))
                if str(msg['sender_participant_id']) != str(participant['id']) or not any(s['start_cp']<=e['start_cp'] and e['end_cp']<=s['end_cp'] for s in msg['direct_body_spans']):
                    fail(422,'contributor_evidence','贡献证据必须是本人直接发言，不能使用引用内容')
                insert(db,'contributor_evidence',dict(customer_id=parent['customer_id'],contributor_id=contributor['id'],
                    evidence_span_id=eid,message_annotation_id=msg['message_annotation_id']))
    for b in bindings:
        insert(db,'revision_evidence',dict(id=uid(),customer_id=parent['customer_id'],**{parent_field.replace('_id','_revision_id'):r['id']},**b))
    audit(db,user['id'],'create_revision',kind,r['id'],parent['customer_id'],{'reason':data.get('change_reason','')})
    return revision_detail(db,kind,r['id'])


def approval_checks(db, kind, r, user):
    # All referenced groups/issues have already been locked by the caller.
    issues,groups = lock_sources(db,list(r['issue_input_versions']),user)
    iv,gv = snapshots(issues,groups)
    if iv != r['issue_input_versions'] or gv != r['group_input_versions']:
        fail(409,'source_changed','来源消息已变化，请基于最新消息重新保存草稿')
    for g in groups:
        if g['classified_version'] != g['ingestion_version'] or one(db,"""SELECT 1 FROM message_dispositions d
            JOIN messages m ON m.id=d.message_id WHERE m.group_id=%s AND NOT """+D.deleted('message','m')+" AND d.state IN ('pending','needs_review') LIMIT 1",(g['id'],)):
            fail(409,'ingestion_pending','相关来源记录仍有待归属消息，请先处理后审核')
    evidence_rows = rows(db,'SELECT * FROM revision_evidence WHERE '+('ticket_revision_id' if kind=='ticket' else 'qa_revision_id')+'=%s',(r['id'],))
    claims=r['claims'] if kind=='ticket' else r['answer_claims']
    validate_bindings(db,r['customer_id'],list(r['issue_input_versions']),evidence_rows,claims)
    supported = {e['field_key'] for e in evidence_rows if e['relation']=='supports'}
    if any(e['relation']=='contradicts' for e in evidence_rows):
        fail(422,'conflicting_evidence','请先处理矛盾证据，再提交新版本')
    if kind == 'qa':
        if r['answer_state'] != 'supported' or not (r['answer'] or '').strip():
            fail(422,'answer_missing','只有有明确答案的 QA 可以批准')
        required = {'question','answer'} | {'answer_claims.'+c['claim_key'] for c in r['answer_claims']}
        if not r['answer_claims']:
            fail(422,'claims_missing','请在“关键事实与依据”中列出回答的关键事实并关联原文依据')
        contributors = rows(db,'SELECT * FROM qa_contributors WHERE qa_revision_id=%s',(r['id'],))
        if not contributors:
            fail(422,'contributor_missing','请确认至少一名核心贡献者及证据')
    else:
        # Tickets are reviewed as service records. Existing fact citations also
        # support record review; summary fields need not duplicate those links.
        required = {'claims.'+c['claim_key'] for c in r['claims']}
        if not supported.intersection(required | {'problem','handling_summary','current_conclusion','status'}):
            fail(422,'evidence_missing','工单尚未关联有效的原文依据，请在“原文与依据”中引用至少一段来源聊天文字')
    if not required <= supported:
        labels={'question':'问题','answer':'回答'}
        prefix='claims.' if kind=='ticket' else 'answer_claims.'
        labels.update({prefix+c['claim_key']:f'关键事实 {i}' for i,c in enumerate(claims,1)})
        fields=[{'field_key':key,'label':label} for key,label in labels.items() if key in required-supported]
        fail(422,'evidence_missing','以下内容尚未关联支持它的原文依据：'+'、'.join(f['label'] for f in fields)+'。请在“原文与依据”中补充。',fields=fields)
