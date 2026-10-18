import hashlib
import json
import uuid
from datetime import date, datetime

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from . import config


def connect():
    return psycopg.connect(config.DATABASE_URL, row_factory=dict_row)


def uid():
    return str(uuid.uuid4())


def plain(value):
    if isinstance(value, dict):
        return {k: plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    return value


def digest(value):
    data = value if isinstance(value, bytes) else json.dumps(plain(value), sort_keys=True, ensure_ascii=False).encode()
    return hashlib.sha256(data).hexdigest()


def one(db, sql, params=()):
    return db.execute(sql, params).fetchone()


def rows(db, sql, params=()):
    return db.execute(sql, params).fetchall()


def insert(db, table, data):
    # Table and column names are supplied exclusively by application code.
    values = [Jsonb(v) if isinstance(v, (dict, list)) else v for v in data.values()]
    return one(db, f"INSERT INTO {table} ({','.join(data)}) VALUES ({','.join(['%s'] * len(data))}) RETURNING *", values)


def audit(db, user, action, kind, object_id, customer=None, details=None):
    insert(db, 'audit_logs', dict(id=uid(), customer_id=customer, actor_user_id=user,
           actor_kind='user' if user else 'worker', action=action, object_type=kind,
           object_id=object_id, changes_summary=details or {}))
