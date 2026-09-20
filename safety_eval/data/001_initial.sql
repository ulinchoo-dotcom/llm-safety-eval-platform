CREATE TABLE IF NOT EXISTS schema_migrations (version integer PRIMARY KEY);
CREATE TABLE eval_cases (
 case_code text PRIMARY KEY,
 payload jsonb NOT NULL,
 label_verified boolean NOT NULL DEFAULT false,
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE eval_runs (
 id uuid PRIMARY KEY,
 model text NOT NULL,
 mode text NOT NULL CHECK (mode = 'demo'),
 prompt_version text NOT NULL,
 handbook_version text NOT NULL,
 case_snapshot jsonb NOT NULL,
 status text NOT NULL CHECK (status IN ('running', 'pending_review', 'completed', 'failed')),
 started_at timestamptz NOT NULL DEFAULT now(),
 finished_at timestamptz
);
CREATE TABLE judge_results (
 id uuid PRIMARY KEY,
 run_id uuid NOT NULL REFERENCES eval_runs(id),
 case_code text NOT NULL REFERENCES eval_cases(case_code),
 payload jsonb NOT NULL,
 UNIQUE (run_id, case_code)
);
CREATE TABLE reviews (
 id uuid PRIMARY KEY,
 result_id uuid NOT NULL UNIQUE REFERENCES judge_results(id),
 reviewer_id text NOT NULL,
 payload jsonb NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX result_run_idx ON judge_results(run_id);
INSERT INTO schema_migrations(version) VALUES (1);
