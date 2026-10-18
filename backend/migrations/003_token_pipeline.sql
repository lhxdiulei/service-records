BEGIN;
ALTER TABLE extraction_jobs ADD COLUMN checkpoint jsonb NOT NULL DEFAULT '{}';
ALTER TABLE extraction_jobs ADD COLUMN topic_plan jsonb;
ALTER TABLE job_steps ADD COLUMN input_tokens integer;
ALTER TABLE job_steps ADD COLUMN output_reserve integer;
ALTER TABLE job_steps ADD COLUMN context_limit integer;
ALTER TABLE job_steps ADD COLUMN attempt_history jsonb NOT NULL DEFAULT '[]';
CREATE INDEX job_steps_resume_idx ON job_steps(job_id,stage,target_key);
COMMIT;
