"""
sync_score_guarantee.py
-----------------------
Queries the RP MySQL replica for Score Guarantee data,
saves as CSV, and pushes to GitHub so Streamlit Cloud can read it.

Uses the same .env as sync_exam_data.py:
  RP_HOST, RP_PORT, RP_USER, RP_PASSWORD,
  GITHUB_TOKEN, GITHUB_REPO
"""

import os
import sys
import mysql.connector
import pandas as pd
from datetime import datetime
import time


def run_with_retry(func, max_attempts=5, delay=120):
    for attempt in range(1, max_attempts + 1):
        try:
            return func()
        except Exception as e:
            print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] Attempt {attempt}/{max_attempts} failed: {e}")
            if attempt < max_attempts:
                print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] Retrying in {delay} seconds...")
                time.sleep(delay)
            else:
                print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] All {max_attempts} attempts failed.")
                raise


try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
    # Also try the FL Dashboards .env
    load_dotenv("/Users/tylerharrington/Desktop/Revolution Prep/FL_Dashboards/dashboards/.env")
except ImportError:
    pass

RP_HOST       = os.environ["RP_HOST"]
RP_PORT       = int(os.environ.get("RP_PORT", 3306))
RP_USER       = os.environ["RP_USER"]
RP_PASSWORD   = os.environ["RP_PASSWORD"]
GITHUB_TOKEN  = os.environ["GITHUB_TOKEN"]
GITHUB_REPO   = os.environ["GITHUB_REPO"]
GITHUB_PATH   = "data/score_guarantee.csv"

QUERY = """
WITH cte_score_guarantee AS (
    SELECT
        DATE(tp.won_at) AS won_at,
        tp.student_id AS student_id,
        CONCAT(student_users.first_name,' ',student_users.last_name) AS student,
        courses.id AS course_id,
        GROUP_CONCAT(DISTINCT CONCAT(tutor_users.first_name,' ',tutor_users.last_name) ORDER BY sessions.starts_at SEPARATOR ', ') AS tutor,
        CONCAT(advisors.first_name,' ',advisors.last_name) AS advisor,
        tp.duration/60.0 AS package_hours,
        GROUP_CONCAT(DISTINCT st.name SEPARATOR ', ') AS subjects_covered,
        MIN(sessions.starts_at) AS first_test_prep_session,
        SUM(sa.minutes)/60.0 AS completed_test_prep_hours,
        students.notes_goals,
        students.notes_personal
    FROM orbit_production.tutor_packages tp
        JOIN orbit_production.students ON tp.student_id = students.id
        JOIN orbit_production.users student_users ON students.user_id = student_users.id
        JOIN orbit_production.enrollments e ON e.enrollee_id = students.id
        JOIN orbit_production.courses ON e.course_id = courses.id
        JOIN orbit_production.parents p ON students.parent_id = p.id
        JOIN orbit_production.employees e1 ON e1.id = p.advisor_id
        JOIN orbit_production.users advisors ON e1.user_id = advisors.id
        LEFT JOIN orbit_production.sessions
            ON (sessions.course_id = courses.id AND sessions.starts_at >= tp.won_at)
        LEFT JOIN orbit_production.session_allotments sa
            ON (sessions.id = sa.session_id AND sa.subject_id IN (43,356,342,316,315))
        LEFT JOIN orbit_production.employees e2
            ON (e2.id = sessions.supervisor_id AND sa.subject_id IN (43,356,342,316,315))
        LEFT JOIN orbit_production.users tutor_users ON e2.user_id = tutor_users.id
        LEFT JOIN orbit_production.subject_translations st
            ON (sa.subject_id = st.subject_id AND st.locale = 'en')
    WHERE tp.name LIKE '%%Score Guarantee%%'
        AND tp.status = 'won'
        AND courses.brand_id = 2
    GROUP BY tp.student_id, tp.won_at, student, courses.id, advisor, package_hours
),
rp_exams AS (
    SELECT DISTINCT
        cte_score_guarantee.won_at,
        cte_score_guarantee.student_id,
        cte_score_guarantee.student,
        cte_score_guarantee.course_id,
        cte_score_guarantee.tutor,
        cte_score_guarantee.advisor,
        cte_score_guarantee.package_hours,
        cte_score_guarantee.subjects_covered,
        cte_score_guarantee.first_test_prep_session,
        cte_score_guarantee.completed_test_prep_hours,
        cte_score_guarantee.notes_goals,
        cte_score_guarantee.notes_personal,
        exams_production.transcripts.id,
        exams_production.transcripts.created_at,
        exams_production.exams.exam_type,
        exams_production.transcripts.score,
        exams_production.exams.form_code AS exam_code,
        exams_production.subjects.name AS section,
        CASE WHEN exams_production.transcript_subjects.scaled_score_range IS NULL
            THEN exams_production.transcript_subjects.scaled_score
            ELSE CEILING((LEFT(exams_production.transcript_subjects.scaled_score_range,3)+ RIGHT(exams_production.transcript_subjects.scaled_score_range,3))/20)*10
        END AS section_score
    FROM cte_score_guarantee
        LEFT JOIN orbit_production.students ON cte_score_guarantee.student_id = orbit_production.students.id
        LEFT JOIN orbit_production.users ON orbit_production.users.id = orbit_production.students.user_id
        LEFT JOIN exams_production.users ON orbit_production.users.id = exams_production.users.handle
        LEFT JOIN exams_production.transcripts
            ON (exams_production.transcripts.user_id = exams_production.users.id
            AND exams_production.transcripts.attempt = 1
            AND exams_production.transcripts.complete = 1
            AND exams_production.transcripts.all_sections_scored = 1)
        LEFT JOIN exams_production.exams ON exams_production.transcripts.exam_id = exams_production.exams.id
        LEFT JOIN exams_production.transcript_subjects ON exams_production.transcript_subjects.transcript_id = exams_production.transcripts.id
        LEFT JOIN exams_production.exam_subjects ON exams_production.exam_subjects.id = exams_production.transcript_subjects.exam_subject_id
        LEFT JOIN exams_production.subjects ON exams_production.subjects.id = exams_production.exam_subjects.subject_id
),
cte_exams AS (
    SELECT
        rp_exams.won_at, rp_exams.student_id, rp_exams.student, rp_exams.course_id,
        rp_exams.tutor, rp_exams.advisor, rp_exams.package_hours, rp_exams.subjects_covered,
        rp_exams.first_test_prep_session, rp_exams.completed_test_prep_hours,
        rp_exams.id, rp_exams.created_at, rp_exams.exam_type, rp_exams.exam_code,
        rp_exams.notes_goals, rp_exams.notes_personal,
        CASE WHEN rp_exams.exam_type = 'SAT' THEN SUM(rp_exams.section_score)
             WHEN rp_exams.exam_type LIKE '%%ACT' THEN rp_exams.score
        END AS score,
        CASE WHEN rp_exams.created_at <= rp_exams.first_test_prep_session
                  OR rp_exams.first_test_prep_session IS NULL THEN 'before'
             WHEN rp_exams.created_at > rp_exams.first_test_prep_session THEN 'after'
        END AS before_or_after_tutoring
    FROM rp_exams
    WHERE rp_exams.exam_type IN ('SAT', 'ACT', 'Digital ACT')
    GROUP BY rp_exams.student_id, rp_exams.id

    UNION ALL

    SELECT
        cte_score_guarantee.won_at, cte_score_guarantee.student_id, cte_score_guarantee.student,
        cte_score_guarantee.course_id, cte_score_guarantee.tutor, cte_score_guarantee.advisor,
        cte_score_guarantee.package_hours, cte_score_guarantee.subjects_covered,
        cte_score_guarantee.first_test_prep_session, cte_score_guarantee.completed_test_prep_hours,
        orbit_production.study_area_snapshots.id AS id,
        orbit_production.study_area_snapshots.date AS created_at,
        orbit_production.subject_translations.name AS exam_type,
        CASE WHEN orbit_production.subject_translations.name = 'ACT'
             THEN 'Official Exam'
             ELSE orbit_production.study_area_snapshots.kind
        END AS exam_code,
        cte_score_guarantee.notes_goals, cte_score_guarantee.notes_personal,
        CAST(orbit_production.study_area_snapshots.score AS DECIMAL) AS score,
        CASE WHEN DATE(orbit_production.study_area_snapshots.date) < DATE(cte_score_guarantee.first_test_prep_session)
                  OR cte_score_guarantee.first_test_prep_session IS NULL THEN 'before'
             WHEN DATE(orbit_production.study_area_snapshots.date) >= DATE(cte_score_guarantee.first_test_prep_session) THEN 'after'
        END AS before_or_after_tutoring
    FROM cte_score_guarantee
        LEFT JOIN orbit_production.students ON cte_score_guarantee.student_id = orbit_production.students.id
        LEFT JOIN orbit_production.study_areas ON orbit_production.study_areas.student_id = orbit_production.students.id
        LEFT JOIN orbit_production.study_area_snapshots
            ON (orbit_production.study_areas.id = orbit_production.study_area_snapshots.study_area_id
            AND orbit_production.study_area_snapshots.date IS NOT NULL)
        LEFT JOIN orbit_production.subjects ON orbit_production.subjects.id = orbit_production.study_areas.subject_id
        LEFT JOIN orbit_production.subject_translations
            ON (orbit_production.subject_translations.subject_id = orbit_production.subjects.id
            AND orbit_production.subject_translations.locale = 'en')
    WHERE orbit_production.subject_translations.name IN ('ACT', 'SAT', 'Digital SAT', 'Digital ACT', 'PSAT', 'PSAT/NMSQT')
),
cte_exams_order AS (
    SELECT *,
        ROW_NUMBER() OVER(PARTITION BY cte_exams.student_id, cte_exams.before_or_after_tutoring ORDER BY cte_exams.created_at DESC) AS rn
    FROM cte_exams
)
SELECT
    cte_exams_order.won_at,
    cte_exams_order.student_id,
    cte_exams_order.student,
    cte_exams_order.course_id,
    cte_exams_order.tutor,
    cte_exams_order.advisor,
    cte_exams_order.package_hours,
    cte_exams_order.subjects_covered,
    cte_exams_order.first_test_prep_session,
    cte_exams_order.completed_test_prep_hours,
    MAX(CASE WHEN cte_exams_order.before_or_after_tutoring = 'before' AND cte_exams_order.rn = 1
         THEN cte_exams_order.created_at END) AS starting_test_taken,
    MAX(CASE WHEN cte_exams_order.before_or_after_tutoring = 'before' AND cte_exams_order.rn = 1
         THEN cte_exams_order.score END) AS starting_score,
    MAX(CASE WHEN cte_exams_order.before_or_after_tutoring = 'after'
         THEN cte_exams_order.rn END) AS exams_since_tutoring,
    MAX(CASE WHEN cte_exams_order.before_or_after_tutoring = 'after' AND cte_exams_order.rn = 1
         THEN cte_exams_order.created_at END) AS last_test_taken,
    MAX(CASE WHEN cte_exams_order.before_or_after_tutoring = 'after' AND cte_exams_order.rn = 1
         THEN cte_exams_order.score END) AS latest_test_score,
    cte_exams_order.notes_goals,
    cte_exams_order.notes_personal
FROM cte_exams_order
GROUP BY cte_exams_order.student_id
ORDER BY won_at, student_id
"""


def fetch_score_guarantee():
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] Connecting to MySQL for Score Guarantee...")
    conn = mysql.connector.connect(
        host=RP_HOST,
        port=RP_PORT,
        user=RP_USER,
        password=RP_PASSWORD,
        connection_timeout=30,
        charset="utf8mb4",
        auth_plugin="mysql_native_password",
    )
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SET SESSION MAX_EXECUTION_TIME=300000")
        cursor.execute(QUERY)
        rows = cursor.fetchall()
        cursor.close()
    finally:
        conn.close()
    df = pd.DataFrame(rows)
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] Fetched {len(df):,} rows.")
    return df


def push_to_github(df):
    from github import Github
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] Pushing to GitHub ({GITHUB_REPO}/{GITHUB_PATH})...")

    df["fetched_at"] = datetime.now().strftime("%B %d, %Y at %I:%M %p")
    csv_bytes = df.to_csv(index=False).encode("utf-8")

    g    = Github(GITHUB_TOKEN)
    repo = g.get_repo(GITHUB_REPO)
    commit_msg = f"Auto-update score guarantee data — {datetime.now():%Y-%m-%d %H:%M}"

    try:
        existing = repo.get_contents(GITHUB_PATH)
        repo.update_file(GITHUB_PATH, commit_msg, csv_bytes, existing.sha)
        print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] Updated existing file.")
    except Exception:
        repo.create_file(GITHUB_PATH, commit_msg, csv_bytes)
        print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] Created new file.")


if __name__ == "__main__":
    def _run():
        df = fetch_score_guarantee()
        push_to_github(df)
        print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] ✅ Done.")
    run_with_retry(_run)
