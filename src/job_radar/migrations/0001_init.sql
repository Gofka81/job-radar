-- Initial schema: jobs + scan history.
CREATE TABLE IF NOT EXISTS jobs (
    job_id      VARCHAR PRIMARY KEY,
    source      VARCHAR,
    company     VARCHAR,
    title       VARCHAR,
    url         VARCHAR,
    location    VARCHAR,
    posted_at   DATE,
    salary_min  DOUBLE,
    salary_max  DOUBLE,
    currency    VARCHAR,
    remote      BOOLEAN,
    status      VARCHAR DEFAULT 'new',
    score       DOUBLE,
    report_num  INTEGER,
    first_seen  TIMESTAMP,
    last_seen   TIMESTAMP,
    raw         JSON
);

CREATE TABLE IF NOT EXISTS scan_runs (
    run_id       VARCHAR,
    started_at   TIMESTAMP,
    finished_at  TIMESTAMP,
    source       VARCHAR,
    found        INTEGER,
    new          INTEGER,
    dupes        INTEGER,
    filtered     INTEGER,
    errors       INTEGER,
    error_detail VARCHAR
);
