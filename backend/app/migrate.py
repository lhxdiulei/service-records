"""Versioned, checksum-verified migrations; run once before API/worker startup."""
import os
import time
from pathlib import Path
from argon2 import PasswordHasher
from psycopg import sql as pg_sql
from .db import connect, digest, uid, insert, one


def migrate():
    for attempt in range(30):
        try:
            db = connect()
            break
        except Exception:
            if attempt == 29:
                raise
            time.sleep(1)
    with db:
        db.execute('SELECT pg_advisory_xact_lock(671904521)')
        db.execute('CREATE TABLE IF NOT EXISTS schema_migrations (name text PRIMARY KEY, sha256 text NOT NULL, applied_at timestamptz DEFAULT now())')
        for path in sorted((Path(__file__).resolve().parents[1] / 'migrations').glob('*.sql')):
            data = path.read_bytes()
            old = one(db, 'SELECT sha256 FROM schema_migrations WHERE name=%s', (path.name,))
            if old:
                if old['sha256'] != digest(data):
                    raise RuntimeError(f'Migration checksum changed: {path.name}')
                continue
            # Files contain standalone BEGIN/COMMIT; the runner owns the transaction.
            sql = data.decode('utf-8').replace('BEGIN;','',1)
            end = sql.rfind('COMMIT;')
            sql = sql[:end] + sql[end+7:] if end >= 0 else sql
            db.execute(sql, prepare=False)
            insert(db, 'schema_migrations', dict(name=path.name, sha256=digest(data)))
        if not one(db, 'SELECT id FROM users LIMIT 1'):
            password = os.getenv('ADMIN_PASSWORD','')
            if len(password) < 12:
                raise RuntimeError('首次启动请配置至少12位 ADMIN_PASSWORD')
            insert(db, 'users', dict(id=uid(), username=os.getenv('ADMIN_USERNAME','admin'),
                   display_name='系统管理员', role='admin', password_hash=PasswordHasher().hash(password)))
        runtime_password = os.getenv('APP_DB_PASSWORD','')
        if len(runtime_password) < 20:
            raise RuntimeError('请配置至少20位独立的 APP_DB_PASSWORD')
        if not one(db,"SELECT 1 FROM pg_roles WHERE rolname='records_app'"):
            db.execute('CREATE ROLE records_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION')
        db.execute(pg_sql.SQL('ALTER ROLE records_app PASSWORD {}').format(pg_sql.Literal(runtime_password)))
        db.execute('GRANT USAGE ON SCHEMA public TO records_app')
        db.execute('GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO records_app')
        db.execute('REVOKE ALL ON schema_migrations FROM records_app')
        from .identities import reconcile
        reconcile(db)
        # Application role cannot own/alter tables, disable triggers or TRUNCATE.


if __name__ == '__main__':
    migrate()
