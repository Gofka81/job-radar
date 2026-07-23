"""Seed a throwaway DuckDB with synthetic jobs for README screenshots/GIFs.

Fake companies + realistic DE roles only — NEVER real target companies, so nothing
personal leaks into the public repo. The DB it writes (default data/demo.duckdb) is
gitignored; only this script is committed. Regenerate any time:

    PYTHONPATH=src python scripts/seed_demo.py            # -> data/demo.duckdb
    PYTHONPATH=src python scripts/seed_demo.py /tmp/x.db  # custom path

Then serve it:  JOB_RADAR_DB=data/demo.duckdb uv run job-serve
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone

from job_radar.schema import make_job_id, make_vacancy_key
from job_radar.store import Store

NOW = datetime.now(timezone.utc)


def ago(hours: float) -> datetime:
    return NOW - timedelta(hours=hours)


# (company, title, source, cities, sal_min, sal_max, remote, jd, status, score, reason, seen_h)
# JDs carry real tech terms so the full-text search demo (spark/airflow/snowflake) lands.
JOBS = [
    ("Northwind Data", "Senior Data Engineer", "greenhouse", ["Edinburgh"], 65000, 80000, True,
     "Build batch and streaming pipelines in PySpark on Databricks. Delta Lake, Airflow orchestration, "
     "AWS (S3, Glue). You'll own data quality and CI/CD for our lakehouse.",
     "new", 9.0, "Strong PySpark/Databricks/Delta match; Edinburgh + remote; mid-level scope.", 3),
    ("Meridian Analytics", "Data Engineer (Spark)", "lever", ["Glasgow"], 55000, 70000, True,
     "Spark SQL and PySpark at scale, Snowflake warehouse, dbt models, Airflow DAGs. Modern AWS stack.",
     "new", 8.5, "Spark + Snowflake + Airflow; Glasgow; salary in band.", 5),
    ("Cobalt Systems", "Analytics Engineer", "ashby", ["Remote"], 50000, 65000, True,
     "dbt, Snowflake, and BI. Some Python. Own the semantic layer and metrics.",
     "new", 6.5, "Adjacent (analytics eng, dbt-heavy); less core PySpark.", 8),
    ("Halcyon Bank", "Senior Data Engineer", "workday", ["London", "Edinburgh"], 70000, 90000, False,
     "PySpark, Spark SQL, Delta Lake on Databricks. Financial data at scale. Airflow, AWS, strong SQL.",
     "new", 8.0, "Great tech match; London/Edinburgh; on-site leaning.", 6),
    ("Brightloom", "Data Platform Engineer", "indeed", ["Manchester"], 60000, 75000, True,
     "Kubernetes, Terraform, and Spark on EMR. Platform tooling for data teams. Python, Go.",
     "new", 7.0, "Platform-leaning; Spark present; infra-heavy.", 12),
    ("Verdant AI", "Machine Learning Data Engineer", "greenhouse", ["Remote"], 65000, 85000, True,
     "Feature pipelines in PySpark, feature store, Airflow. Snowflake + Delta. Support ML training data.",
     "viewed", 7.5, "ML-data blend; solid Spark/Airflow; remote.", 20),
    ("Ashford Retail", "Data Engineer", "reed", ["Leeds"], 45000, 55000, False,
     "SQL Server, SSIS, some Azure Data Factory. Reporting pipelines. Growing data team.",
     "viewed", 4.0, "MS/SSIS stack; little Spark; below salary target.", 26),
    ("Lumen Health", "Senior Data Engineer", "lever", ["Edinburgh", "Glasgow", "London"], 68000, 82000, True,
     "PySpark, Databricks, Delta Lake, Airflow. Healthcare data at scale across the UK. AWS.",
     "saved", 9.0, "Excellent match; multi-city incl. Edinburgh; remote-friendly.", 30),
    ("Pinnacle Media", "Data Engineer (Airflow)", "ashby", ["London"], 58000, 72000, True,
     "Airflow, Python, Snowflake, dbt. Event pipelines for media analytics. AWS.",
     "saved", 7.5, "Airflow/Snowflake match; London; remote OK.", 34),
    ("Orion Freight", "Big Data Engineer", "greenhouse", ["Birmingham"], 60000, 78000, True,
     "Spark, Kafka streaming, Delta Lake. Logistics telemetry. Scala or Python.",
     "applied", 8.0, "Spark + streaming; strong; applied.", 48),
    ("Cascade Fintech", "Data Engineer", "workable", ["Edinburgh"], 62000, 75000, True,
     "PySpark, Snowflake, dbt, Airflow. Payments data. Edinburgh HQ, hybrid.",
     "applied", 8.5, "Core match; Edinburgh; hybrid.", 52),
    ("Grayson Insurance", "Junior Data Engineer", "reed", ["Bristol"], 35000, 42000, False,
     "Entry-level. SQL, Python basics, Power BI. Learn Spark on the job.",
     "rejected", 2.5, "Junior/entry; below level and salary.", 70),
    ("Tavistock Consulting", "Data Warehouse Developer", "adzuna", ["London"], 50000, 60000, False,
     "Redshift, SQL, ETL. Warehouse modelling for clients. Some Python.",
     "rejected", 3.5, "Warehouse-only; no Spark; consulting.", 74),
    # --- unscored, fresh inbox (so 'run triage' has targets in the GIF) ---
    ("Kestrel Labs", "Data Engineer", "linkedin", ["Remote"], 58000, 72000, True,
     "PySpark, AWS, Airflow, Delta Lake. Product data pipelines. Fully remote UK.", "new", None, None, 2),
    ("Solstice Energy", "Senior Data Engineer", "greenhouse", ["Aberdeen", "Edinburgh"], 66000, 80000, True,
     "Spark, Databricks, Delta Lake. Energy sensor data. Scotland-based, remote-friendly.", "new", None, None, 4),
    ("Foundry Retail", "Analytics Engineer", "lever", ["London"], 52000, 64000, True,
     "dbt, Snowflake, Looker. Analytics engineering for e-commerce.", "new", None, None, 7),
    ("Whitfield Gov", "Data Engineer", "indeed", ["Cardiff"], 48000, 58000, False,
     "Azure, Databricks, PySpark. Public-sector data platform. Cardiff.", "new", None, None, 9),
    ("Nimbus Cloud", "Platform Data Engineer", "ashby", ["Remote"], 63000, 78000, True,
     "Spark on Kubernetes, Terraform, Airflow. Internal data platform.", "new", None, None, 11),
    ("Ardent Trading", "Data Engineer (Snowflake)", "workable", ["London"], 60000, 74000, True,
     "Snowflake, dbt, Python, Airflow. Trading analytics pipelines.", "new", None, None, 14),
    # --- expired (history / generations demo) ---
    ("Thornbury Group", "Data Engineer", "reed", ["Glasgow"], 55000, 68000, True,
     "PySpark, AWS, Airflow. Retail analytics. (Older listing, since closed.)", "expired", 7.0,
     "Good match but the posting has since closed.", 200),
]


def main(path: str = "data/demo.duckdb") -> None:
    store = Store(path)
    con = store.con
    con.execute("DELETE FROM jobs")
    con.execute("DELETE FROM scan_runs")
    con.execute("DELETE FROM llm_runs")

    for (company, title, source, cities, smin, smax, remote, jd, status, score, reason, seen_h) in JOBS:
        url = f"https://example.com/{source}/{company.lower().replace(' ', '-')}/{title.lower().replace(' ', '-')}"
        vkey = make_vacancy_key(company, title, url)
        first_seen = ago(seen_h)
        job_id = make_job_id(vkey, first_seen)
        evaluated_at = ago(seen_h - 0.5) if score is not None else None
        con.execute(
            """INSERT INTO jobs (job_id, vacancy_key, source, company, title, url, location,
                 locations, description, jd_full, posted_at, salary_min, salary_max, currency,
                 remote, status, score, eval_reason, evaluated_at, engine, first_seen, last_seen, raw)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            [job_id, vkey, source, company, title, url, cities[0], json.dumps(cities), jd, True,
             first_seen.date(), float(smin), float(smax), "GBP", remote, status,
             score, reason, evaluated_at, ("claude-cli" if score is not None else None),
             first_seen, ago(max(0, seen_h - 1)), "{}"],
        )

    # A recent scan run + a triage ledger row so the funnel / Usage view aren't empty.
    con.execute(
        """INSERT INTO scan_runs (run_id, started_at, finished_at, source, found, new, dupes,
             filtered, errors, error_detail)
           VALUES ('demo', ?, ?, 'all', 214, 21, 173, 20, 0, NULL)""",
        [ago(2), ago(2) + timedelta(seconds=48)],
    )
    con.execute(
        """INSERT INTO llm_runs (run_id, stage, model, engine, started_at, finished_at, jobs,
             scored, errors, input_tokens, output_tokens, cache_read_tokens, cache_write_tokens,
             cost_usd, budget_hit, note)
           VALUES ('demo', 'triage', 'claude-cli', 'claude-cli', ?, ?, 14, 14, 0,
             28000, 1900, 0, 0, 0.0, FALSE, 'Pro subscription — no per-token cost')""",
        [ago(1), ago(1) + timedelta(seconds=95)],
    )

    total = con.execute("SELECT count(*) FROM jobs").fetchone()[0]
    by_status = con.execute("SELECT status, count(*) FROM jobs GROUP BY status ORDER BY 2 DESC").fetchall()
    store.close()
    print(f"Seeded {total} jobs into {path}")
    print("  " + "  ".join(f"{s}={n}" for s, n in by_status))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "data/demo.duckdb")
