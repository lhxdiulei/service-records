BEGIN;
CREATE TABLE auth_attempts (
  id uuid PRIMARY KEY,
  key_hash text NOT NULL,
  succeeded boolean NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX auth_attempts_lookup ON auth_attempts(key_hash,created_at DESC);
ALTER TABLE extraction_jobs ADD COLUMN lease_owner text;
ALTER TABLE extraction_jobs ADD COLUMN lease_until timestamptz;
ALTER TABLE extraction_jobs ADD COLUMN fencing_token bigint NOT NULL DEFAULT 0;
ALTER TABLE extraction_jobs ADD COLUMN classification_committed boolean NOT NULL DEFAULT false;
ALTER TABLE extraction_jobs ADD COLUMN result_issue_ids jsonb NOT NULL DEFAULT '[]';
ALTER TABLE extraction_jobs ADD COLUMN input_manifest jsonb NOT NULL DEFAULT '{}';
COMMIT;
