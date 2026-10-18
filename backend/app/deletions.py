"""Recoverable admin deletion without changing immutable chat or evidence rows."""
from .db import one, rows, insert, audit, digest
from .security import fail,require_role,match

TABLES={'message':'messages','import':'import_batches','ticket':'tickets','qa':'qa_entries','ticket_draft':'ticket_revisions','qa_draft':'qa_revisions'}


def own_deleted(kind,alias):
    return f"EXISTS (SELECT 1 FROM record_deletions rd WHERE rd.record_kind='{kind}' AND rd.record_id={alias}.id AND rd.restored_at IS NULL)"


def deleted(kind,alias):
    direct=own_deleted(kind,alias)
    if kind=='message':
        return f"({direct} OR EXISTS (SELECT 1 FROM record_deletions rb WHERE rb.record_kind='import' AND rb.record_id={alias}.batch_id AND rb.restored_at IS NULL))"
    return direct


def metadata(kind,alias):
    state=object_deleted(kind,alias) if kind in ('ticket','qa') else deleted(kind,alias)
    return f"{state} AS is_deleted,coalesce((SELECT rd.version FROM record_deletions rd WHERE rd.record_kind='{kind}' AND rd.record_id={alias}.id),0) AS delete_version"+(f',{own_deleted(kind,alias)} AS parent_deleted' if kind in ('ticket','qa') else '')


def object_deleted(kind,alias):
    table,parent=('ticket_revisions','ticket_id') if kind=='ticket' else ('qa_revisions','qa_id')
    return f"({deleted(kind,alias)} OR (EXISTS(SELECT 1 FROM {table} ar WHERE ar.{parent}={alias}.id) AND NOT EXISTS(SELECT 1 FROM {table} ar WHERE ar.{parent}={alias}.id AND NOT {deleted(kind+'_draft','ar')})))"


def draft_permission(user,revision,restore=False):
    if revision['state'] not in ('draft','rejected','in_review'):fail(409,'not_a_draft','正式或历史版本不可作为草稿删除')
    if user['role']!='admin' and str(revision['created_by'])!=str(user['id']):
        fail(403,'draft_forbidden','仅管理员或该草稿的生成用户可删除草稿')


def is_deleted(db,kind,record_id):
    table=TABLES[kind]
    return one(db,f'SELECT {deleted(kind,"r")} AS deleted FROM {table} r WHERE r.id=%s',(record_id,))['deleted']


def active(db,kind,record_id):
    if is_deleted(db,kind,record_id):fail(409,'record_deleted','记录已删除，请先由管理员恢复')


def mutate(db,user,kind,record_id,request,restore=False):
    from . import services as S
    if kind not in TABLES:fail(404,'record_kind','记录类型不存在')
    is_draft=kind.endswith('_draft')
    if not is_draft:require_role(user,'admin')
    table=TABLES[kind]
    item=S.entity(db,table,record_id,user)
    if is_draft:draft_permission(user,item,restore)
    # Serializes delete/restore and gives the list's deletion version a stable meaning.
    db.execute('SELECT pg_advisory_xact_lock(%s)',(int(digest(kind+str(record_id))[:15],16),))
    mids=[]
    if kind=='message':mids=[str(record_id)]
    elif kind=='import':mids=[str(m['id']) for m in rows(db,'SELECT id FROM messages WHERE batch_id=%s',(record_id,))]
    issue_ids=[str(r['issue_id']) for r in rows(db,'SELECT DISTINCT issue_id FROM issue_messages WHERE message_id=ANY(%s::uuid[]) AND active',(mids,))]
    if kind=='ticket':issue_ids=[str(item['issue_id'])]
    parent=None
    if is_draft:
        parent_kind=kind.removesuffix('_draft')
        parent=S.entity(db,TABLES[parent_kind],item['ticket_id' if parent_kind=='ticket' else 'qa_id'],user)
        issue_ids=[str(parent['issue_id'])] if parent_kind=='ticket' else [str(i['issue_id']) for i in rows(db,'SELECT issue_id FROM qa_issue_links WHERE qa_revision_id=%s',(record_id,))]
    if issue_ids:S.lock_sources(db,issue_ids,user,mids)
    elif kind in ('message','import'):S.entity(db,'chat_groups',item['group_id'],user,True)
    if parent:
        parent=S.entity(db,TABLES[parent_kind],parent['id'],user,True)
        active(db,parent_kind,parent['id'])
    item=S.entity(db,table,record_id,user,True)
    if is_draft:draft_permission(user,item,restore)
    old=one(db,'SELECT * FROM record_deletions WHERE record_kind=%s AND record_id=%s FOR UPDATE',(kind,record_id))
    match(request,old['version'] if old else 0)
    currently_deleted=bool(old and old['restored_at'] is None)
    if restore!=currently_deleted:fail(409,'deletion_state','删除状态已变化，请刷新后重试')
    if restore and kind=='message' and is_deleted(db,'import',item['batch_id']):
        fail(409,'import_deleted','请先从导入历史恢复所属文件')
    if restore:
        result=one(db,'UPDATE record_deletions SET restored_at=now(),restored_by=%s,version=version+1 WHERE record_kind=%s AND record_id=%s RETURNING *',(user['id'],kind,record_id))
    elif old:
        result=one(db,'UPDATE record_deletions SET deleted_at=now(),deleted_by=%s,restored_at=NULL,restored_by=NULL,version=version+1 WHERE record_kind=%s AND record_id=%s RETURNING *',(user['id'],kind,record_id))
    else:
        result=insert(db,'record_deletions',dict(record_kind=kind,record_id=record_id,customer_id=item['customer_id'],deleted_by=user['id']))
    if mids:
        db.execute('UPDATE message_dispositions SET version=version+1,updated_at=now() WHERE message_id=ANY(%s::uuid[])',(mids,))
        db.execute('UPDATE issues SET message_version=message_version+1,version=version+1,updated_at=now() WHERE id=ANY(%s::uuid[])',(issue_ids,))
        for g in rows(db,'SELECT DISTINCT group_id FROM messages WHERE id=ANY(%s::uuid[])',(mids,)):S.watermark(db,g['group_id'])
    if kind=='message':db.execute('UPDATE import_batches SET version=version+1 WHERE id=%s',(item['batch_id'],))
    if is_draft:db.execute(f'UPDATE {TABLES[parent_kind]} SET version=version+1 WHERE id=%s',(parent['id'],))
    elif kind!='message':db.execute(f'UPDATE {table} SET version=version+1 WHERE id=%s',(record_id,))
    audit(db,user['id'],'restore' if restore else 'delete',kind,record_id,item['customer_id'],{'recoverable':True,'messages_affected':len(mids)})
    return dict(ok=True,is_deleted=not restore,delete_version=result['version'])
