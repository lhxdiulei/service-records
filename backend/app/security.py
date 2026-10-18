import hashlib
import hmac
import json
import logging
import secrets
from datetime import datetime, timezone, timedelta

import psycopg
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, InvalidHashError
from fastapi import HTTPException
from fastapi.responses import JSONResponse, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.concurrency import run_in_threadpool
from . import config
from .db import connect, one, insert, digest, uid, plain

passwords = PasswordHasher()
log = logging.getLogger(__name__)


def fail(status, code, message, **details):
    raise HTTPException(status, {'code': code, 'message': message, **details})


def hash_token(value):
    return hashlib.sha256(value.encode()).digest()


def safe_user(user):
    return {k: plain(user[k]) for k in ['id','username','display_name','role','version']}


def require_role(user, *roles):
    if user['role'] not in roles:
        fail(403, 'forbidden', '当前角色没有此操作权限')


def scope(db, user, customer_id):
    if not one(db, 'SELECT id FROM customers WHERE id=%s AND disabled_at IS NULL', (customer_id,)):
        fail(404, 'not_found', '客户不存在')
    if user['role'] != 'admin' and not one(db, 'SELECT 1 FROM user_customer_scopes WHERE user_id=%s AND customer_id=%s', (user['id'], customer_id)):
        fail(403, 'customer_forbidden', '没有该客户的数据访问权限')


def match(request, version):
    header = request.headers.get('if-match')
    if not header:
        fail(428, 'precondition_required', '缺少 If-Match 版本前提')
    if header != f'"{version}"':
        fail(412, 'version_changed', '数据已变化，请刷新后重试')


class SecurityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if not request.url.path.startswith('/api/') or request.url.path == '/api/health':
            return await call_next(request)
        path = request.url.path
        public = path in ['/api/v1/auth/csrf', '/api/v1/auth/login']
        unsafe = request.method not in ['GET','HEAD','OPTIONS']
        db = None
        try:
            db = await run_in_threadpool(connect)
            request.state.db = db
            token = request.cookies.get('sr_session','')
            session = await run_in_threadpool(one,db, '''SELECT s.*, u.username,u.display_name,u.role,u.version AS user_version,u.scope_version
                FROM user_sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=%s
                AND s.revoked_at IS NULL AND s.expires_at>now() AND s.idle_expires_at>now() AND u.disabled_at IS NULL''', (hash_token(token),)) if token else None
            user = dict(id=session['user_id'],username=session['username'],display_name=session['display_name'],role=session['role'],version=session['user_version']) if session else None
            request.state.user, request.state.session = user, session
            if not public and not user:
                fail(401, 'not_authenticated', '请先登录')
            if unsafe:
                if request.headers.get('origin') not in config.ORIGINS:
                    fail(403, 'origin_rejected', '请求来源不被允许')
                csrf = request.headers.get('x-csrf-token','')
                cookie_csrf = request.cookies.get('sr_csrf','')
                if not csrf or not cookie_csrf or not hmac.compare_digest(csrf,cookie_csrf):
                    fail(403, 'csrf_rejected', '请求校验失败，请刷新页面')
                if session and not hmac.compare_digest(hash_token(csrf), bytes(session['csrf_token_hash'])):
                    fail(403, 'csrf_rejected', '会话校验失败')
            idem = None
            if unsafe and user and path != '/api/v1/auth/logout':
                key = request.headers.get('idempotency-key','')
                if not 1 <= len(key) <= 128:
                    fail(400,'idempotency_required','写请求需要 Idempotency-Key')
                body = await request.body()
                if len(body) > config.MAX_FILE_BYTES + 1024*1024:
                    fail(413,'file_too_large','请求过大')
                # Serializes only identical keys, inside the same business transaction.
                lock = int.from_bytes(hash_token(str(user['id'])+request.method+path+key)[:8], 'big', signed=True)
                await run_in_threadpool(db.execute,'SELECT pg_advisory_xact_lock(%s)', (lock,))
                old = await run_in_threadpool(one,db, '''SELECT * FROM idempotency_records WHERE user_id=%s AND http_method=%s
                    AND request_path=%s AND idempotency_key=%s''', (user['id'],request.method,path,key))
                fingerprint = digest(body)
                if old:
                    if old['request_hash'] != fingerprint:
                        fail(409,'idempotency_conflict','相同幂等键对应了不同请求')
                    if old['state'] == 'completed':
                        saved = old['response_headers'] or {}
                        if saved.get('_scope_version') != session['scope_version'] or saved.get('_user_version') != session['user_version']:
                            fail(409,'permission_changed','权限已变化，请使用新的请求标识重试')
                        await run_in_threadpool(db.rollback)
                        return JSONResponse(old['response_body'], status_code=old['response_status'], headers={k:v for k,v in saved.items() if not k.startswith('_')})
                idem = dict(id=uid(),user_id=user['id'],http_method=request.method,request_path=path,
                    idempotency_key=key,request_hash=fingerprint,state='completed',expires_at=datetime.now(timezone.utc)+timedelta(days=7))
            response = await call_next(request)
            if response.status_code >= 400:
                # Login failures are deliberately durable for rate limiting.
                if path == '/api/v1/auth/login' and response.status_code in (401,429):
                    await run_in_threadpool(db.commit)
                else:
                    await run_in_threadpool(db.rollback)
            else:
                if idem:
                    content = b''.join([chunk async for chunk in response.body_iterator])
                    idem.update(response_status=response.status_code,response_body=json.loads(content),
                                response_headers={'_scope_version': session['scope_version'], '_user_version':session['user_version'], **({'ETag': response.headers['etag']} if 'etag' in response.headers else {})})
                    await run_in_threadpool(insert,db,'idempotency_records',idem)
                    response = Response(content,status_code=response.status_code,headers=dict(response.headers),media_type='application/json')
                if session and (datetime.now(timezone.utc)-session['last_seen_at']).total_seconds()>60:
                    await run_in_threadpool(db.execute,"UPDATE user_sessions SET last_seen_at=now(),idle_expires_at=least(expires_at,now()+interval '2 hours') WHERE id=%s",(session['id'],))
                await run_in_threadpool(db.commit)
            response.headers['X-Content-Type-Options'] = 'nosniff'
            response.headers['Cache-Control'] = 'no-store'
            return response
        except HTTPException as exc:
            if db:
                await run_in_threadpool(db.rollback)
            return JSONResponse({'detail':exc.detail}, status_code=exc.status_code)
        except psycopg.IntegrityError:
            if db:
                await run_in_threadpool(db.rollback)
            log.exception('Database constraint rejected request')
            return JSONResponse({'detail':{'code':'constraint_conflict','message':'数据约束冲突，请刷新后检查关联与状态'}},status_code=409)
        except Exception:
            if db:
                await run_in_threadpool(db.rollback)
            log.exception('Request failed')
            return JSONResponse({'detail':{'code':'internal_error','message':'服务暂时不可用，请稍后重试'}},status_code=500)
        finally:
            if db:
                await run_in_threadpool(db.close)


def login(db, request, response, username, password):
    key = digest((request.client.host if request.client else '')+'|'+username.casefold())
    # A durable per-identity/IP rate limit also works across multiple API workers.
    db.execute('SELECT pg_advisory_xact_lock(%s)', (int(key[:15],16),))
    attempts = one(db,"SELECT count(*) AS n FROM auth_attempts WHERE key_hash=%s AND NOT succeeded AND created_at>now()-interval '15 minutes'",(key,))['n']
    if attempts >= 10:
        fail(429,'login_rate_limited','尝试次数过多，请15分钟后重试')
    user = one(db,'SELECT * FROM users WHERE lower(username)=lower(%s) AND disabled_at IS NULL',(username,))
    valid = False
    try:
        if user:
            valid = passwords.verify(user['password_hash'],password)
        else:
            passwords.hash(password)
    except (VerificationError,InvalidHashError):
        pass
    insert(db,'auth_attempts',dict(id=uid(),key_hash=key,succeeded=valid))
    if not valid:
        fail(401,'invalid_credentials','用户名或密码错误')
    if request.state.session:
        db.execute('UPDATE user_sessions SET revoked_at=now() WHERE id=%s',(request.state.session['id'],))
    token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    insert(db,'user_sessions',dict(id=uid(),user_id=user['id'],token_hash=hash_token(token),csrf_token_hash=hash_token(csrf),
        expires_at=now+timedelta(hours=config.SESSION_HOURS),idle_expires_at=now+timedelta(hours=2)))
    db.execute('UPDATE users SET last_login_at=now() WHERE id=%s',(user['id'],))
    for name, value in [('sr_session',token),('sr_csrf',csrf)]:
        response.set_cookie(name,value,httponly=True,secure=config.SECURE_COOKIE,samesite='lax',max_age=config.SESSION_HOURS*3600,path='/')
    return dict(user=safe_user(user),csrf_token=csrf)
