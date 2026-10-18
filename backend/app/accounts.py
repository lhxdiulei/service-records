"""Administrator account maintenance without deleting historical ownership."""
from . import identities as I
from .db import one,audit
from .security import fail,match,passwords

PUBLIC_FIELDS=('id','username','display_name','role','version','disabled_at','created_at','last_login_at')


def public(account):
    return {key:account[key] for key in PUBLIC_FIELDS}


def lock_admin(db,actor):
    # Serialize name changes, deletion and recovery with identity maintenance.
    db.execute('SELECT pg_advisory_xact_lock(671904523)')
    current=one(db,'SELECT role,disabled_at FROM users WHERE id=%s',(actor['id'],))
    if not current or current['disabled_at'] or current['role']!='admin':
        fail(403,'forbidden','只有管理员可以维护账号')


def target(db,user_id,request=None):
    account=one(db,'SELECT * FROM users WHERE id=%s'+(' FOR UPDATE' if request else ''),(user_id,))
    if not account:fail(404,'not_found','账号不存在')
    if request:match(request,account['version'])
    return account


def validate_username(db,username,user_id=None):
    existing=one(db,'SELECT id FROM users WHERE lower(username)=lower(%s)',(username,))
    if existing and str(existing['id'])!=str(user_id):
        fail(409,'username_taken','用户名已存在；已删除的账号可在“已删除”列表中恢复')


def update(db,actor,user_id,data,request):
    lock_admin(db,actor)
    account=target(db,user_id,request)
    if account['disabled_at']:fail(409,'account_deleted','请先恢复账号，再编辑资料')
    own=str(account['id'])==str(actor['id'])
    if own and data.role!=account['role']:
        fail(409,'self_role_change','不能修改当前登录账号的角色，请由另一名管理员操作')
    if account['role']=='admin' and data.role!='admin':protect_last_admin(db,account)
    validate_username(db,data.username,user_id)
    I.validate_names(db,data.username,data.display_name,account['wechat_nicknames'],user_id)
    changed=[key for key in ('username','display_name','role') if getattr(data,key)!=account[key]]
    if data.password is not None:changed.append('password')
    invalidate=data.password is not None or any(key in changed for key in ('username','role'))
    if changed:
        updated=one(db,'''UPDATE users SET username=%s,display_name=%s,role=%s,password_hash=%s,version=version+1
            WHERE id=%s RETURNING *''',(data.username,data.display_name,data.role,
            passwords.hash(data.password) if data.password is not None else account['password_hash'],user_id))
        if invalidate:db.execute('UPDATE user_sessions SET revoked_at=now() WHERE user_id=%s AND revoked_at IS NULL',(user_id,))
        I.reconcile(db,bump_catalog=True)
        audit(db,actor['id'],'update','user',user_id,details={'changed_fields':changed})
        account=updated
    return dict(public(account),reauthenticate_self=own and invalidate)


def protect_last_admin(db,account):
    if account['role']=='admin' and not one(db,"SELECT 1 FROM users WHERE role='admin' AND disabled_at IS NULL AND id<>%s LIMIT 1",(account['id'],)):
        fail(409,'last_admin','系统至少需要保留一名可用管理员')


def remove(db,actor,user_id,request,restore=False):
    lock_admin(db,actor)
    account=target(db,user_id,request)
    if str(account['id'])==str(actor['id']):fail(409,'self_delete','不能删除当前登录账号')
    if restore:
        if not account['disabled_at']:fail(409,'account_active','账号已恢复，无需重复操作')
        I.validate_names(db,account['username'],account['display_name'],account['wechat_nicknames'],user_id)
    else:
        if account['disabled_at']:fail(409,'account_deleted','账号已删除')
        protect_last_admin(db,account)
    account=one(db,'UPDATE users SET disabled_at='+('NULL' if restore else 'now()')+',version=version+1 WHERE id=%s RETURNING *',(user_id,))
    db.execute('UPDATE user_sessions SET revoked_at=now() WHERE user_id=%s AND revoked_at IS NULL',(user_id,))
    I.reconcile(db,bump_catalog=True)
    audit(db,actor['id'],'restore' if restore else 'delete','user',user_id)
    return public(account)
