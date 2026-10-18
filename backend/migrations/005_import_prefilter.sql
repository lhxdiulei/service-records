BEGIN;
ALTER TABLE import_batches ADD COLUMN prefilter_report jsonb
  CHECK (prefilter_report IS NULL OR jsonb_typeof(prefilter_report) = 'object');
ALTER TABLE message_dispositions ADD COLUMN prefilter_reason text;
ALTER TABLE message_dispositions ADD COLUMN prefilter_restored_at timestamptz;
ALTER TABLE message_dispositions ADD CONSTRAINT prefilter_restore_has_reason
  CHECK (prefilter_restored_at IS NULL OR prefilter_reason IS NOT NULL);
COMMIT;
