"""Chat roles come from internal accounts; unmatched senders are customers."""
from .db import one, rows
from .security import fail


def key(value):
    return value.strip().casefold()


def accounts(db):
    return rows(db,'SELECT id,username,display_name,wechat_nicknames FROM users WHERE disabled_at IS NULL ORDER BY id')


def names(account):
    return {key(v) for v in [account['username'],account['display_name'],*account['wechat_nicknames']] if key(v)}


def mapping(db):
    result={}
    for account in accounts(db):
        for name in names(account):
            if name not in result:result[name]=account['id']
            elif result[name]!=account['id']:result[name]=None
    return result


def validate_names(db,username,display_name,nicknames,user_id=None):
    db.execute('SELECT pg_advisory_xact_lock(671904523)')
    proposed=names(dict(username=username,display_name=display_name,wechat_nicknames=nicknames))
    if any(str(a['id'])!=str(user_id) and proposed & names(a) for a in accounts(db)):
        fail(422,'chat_name_conflict','用户名或显示姓名与其他内部账号重复，请使用可唯一识别的名称')


def resolve(name,lookup):
    user_id=lookup.get(key(name))
    return dict(role='support' if user_id else 'customer',linked_user_id=user_id,identity_verified=True)


def version(db):
    return one(db,'SELECT version FROM identity_catalog WHERE singleton')['version']


def reconcile(db,bump_catalog=False):

    lookup=mapping(db)
    changed=[]
    for p in rows(db,'SELECT * FROM participants ORDER BY id'):
        values=resolve(p['display_name'],lookup)
        if p['role']!=values['role'] or p['linked_user_id']!=values['linked_user_id'] or not p['identity_verified']:
            changed.append((p,values))
    if changed:
        ids=[str(p['id']) for p,_ in changed]
        issue_ids=[str(r['issue_id']) for r in rows(db,'''SELECT DISTINCT im.issue_id FROM issue_messages im JOIN messages m ON m.id=im.message_id
            WHERE im.active AND m.sender_participant_id=ANY(%s::uuid[])''',(ids,))]
        # Use the same group -> issue -> participant lock order as edits and review.
        group_ids={str(p['group_id']) for p,_ in changed}
        if issue_ids:
            groups=rows(db,'''SELECT primary_group_id AS id FROM issues WHERE id=ANY(%s::uuid[])
                UNION SELECT m.group_id FROM issue_messages im JOIN messages m ON m.id=im.message_id
                WHERE im.active AND im.issue_id=ANY(%s::uuid[])''',(issue_ids,issue_ids))
            group_ids.update(str(g['id']) for g in groups)
        rows(db,'SELECT id FROM chat_groups WHERE id=ANY(%s::uuid[]) ORDER BY id FOR UPDATE',(sorted(group_ids),))
        rows(db,'SELECT id FROM issues WHERE id=ANY(%s::uuid[]) ORDER BY id FOR UPDATE',(issue_ids,))
        for p,values in changed:
            db.execute('UPDATE participants SET role=%s,linked_user_id=%s,identity_verified=true,version=version+1 WHERE id=%s',
                (values['role'],values['linked_user_id'],p['id']))
        db.execute('UPDATE issues SET message_version=message_version+1,version=version+1,updated_at=now() WHERE id=ANY(%s::uuid[])',(issue_ids,))
    if bump_catalog and changed:db.execute('UPDATE identity_catalog SET version=version+1 WHERE singleton')
    return len(changed)
