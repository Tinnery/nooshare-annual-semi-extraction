-- H1 抽取结果表 + 专用写入角色（幂等，可重复执行）
-- 在 DEV 库 nooshare_dev 执行：psql -U travis -d nooshare_dev -f h1_corpus_results.sql
-- trust 认证下无需密码；CI 经 stunnel 隧道以 ci 身份写入。

DO $do$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ci') THEN
    CREATE ROLE ci LOGIN;
  END IF;
END
$do$;

CREATE TABLE IF NOT EXISTS annual_semi.h1_corpus_results (
    slot_key                    TEXT PRIMARY KEY,
    stock_code                  TEXT        NOT NULL,
    report_year                 INTEGER     NOT NULL,
    period                      INTEGER     NOT NULL,
    source_sha256               TEXT        NOT NULL,
    n_bytes                     BIGINT      NOT NULL,
    extraction_method           TEXT,
    n_headings                  INTEGER,
    ordinal_valid               BOOLEAN,
    ordinal_verdict             TEXT,
    is_complete_l1              BOOLEAN,
    coverage_ratio              DOUBLE PRECISION,
    headings_json               JSONB,
    missing_always_sections     INTEGER[],
    missing_conditional_sections INTEGER[],
    reg_version                 TEXT,
    loaded_at                   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_h1_corpus_stock_year
    ON annual_semi.h1_corpus_results (stock_code, report_year, period);

GRANT USAGE ON SCHEMA annual_semi TO ci;
GRANT SELECT, INSERT, UPDATE ON annual_semi.h1_corpus_results TO ci;
