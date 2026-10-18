BEGIN;
ALTER TABLE users ADD COLUMN wechat_nicknames jsonb NOT NULL DEFAULT '[]' CHECK (jsonb_typeof(wechat_nicknames)='array');
CREATE TABLE identity_catalog (
  singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
  version bigint NOT NULL DEFAULT 1 CHECK (version>0)
);
INSERT INTO identity_catalog(singleton) VALUES(true);
CREATE TABLE record_deletions (
  record_kind text NOT NULL CHECK (record_kind IN ('message','import','ticket','qa','ticket_draft','qa_draft')),
  record_id uuid NOT NULL,
  customer_id uuid NOT NULL REFERENCES customers(id),
  deleted_at timestamptz NOT NULL DEFAULT now(),
  deleted_by uuid NOT NULL REFERENCES users(id),
  restored_at timestamptz,
  restored_by uuid REFERENCES users(id),
  version bigint NOT NULL DEFAULT 1 CHECK (version>0),
  PRIMARY KEY(record_kind,record_id)
);
CREATE INDEX record_deletions_active_idx ON record_deletions(record_kind,record_id) WHERE restored_at IS NULL;
CREATE TABLE extraction_job_records (
  job_id uuid NOT NULL REFERENCES extraction_jobs(id),
  customer_id uuid NOT NULL REFERENCES customers(id),
  record_kind text NOT NULL CHECK (record_kind IN ('ticket','qa')),
  record_id uuid NOT NULL,
  revision_id uuid NOT NULL,
  issue_id uuid NOT NULL REFERENCES issues(id),
  action text NOT NULL CHECK (action IN ('created','updated','reused','manual_review_required')),
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY(job_id,record_kind,revision_id)
);
COMMIT;
