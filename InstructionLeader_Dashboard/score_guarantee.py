"""
Score Guarantee Dashboard
─────────────────────────
Standalone dashboard for Score Guarantee tracking and compliance.
"""

import streamlit as st
import pandas as pd
import numpy as np
import psycopg2
import plotly.graph_objects as go
import os
import requests
import base64
from datetime import date


def render_app(config):

    # ── Custom CSS ────────────────────────────────────────────────────────────
    st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Source+Serif+4:wght@400;600;700&family=DM+Sans:wght@300;400;500;600;700&display=swap');
    html, body, [class*="css"] { font-family: 'DM Sans', sans-serif; }
    [data-testid="stSidebar"] { background: #f8f9fb !important; border-right: 1px solid #e2e8f0; }
    h1, h2, h3 { font-family: 'Source Serif 4', serif !important; color: #1e293b !important; }
    [data-testid="metric-container"] {
        background: #f8f9fb; border: 1px solid #e2e8f0; border-radius: 10px; padding: 16px 20px;
    }
    [data-testid="metric-container"] label {
        color: #64748b !important; font-size: 0.75rem !important;
        letter-spacing: 0.1em; text-transform: uppercase; font-weight: 600;
    }
    [data-testid="metric-container"] [data-testid="stMetricValue"] {
        color: #1e293b !important; font-size: 1.9rem !important;
        font-family: 'Source Serif 4', serif !important;
    }
    [data-testid="stDataFrame"] { border: 1px solid #e2e8f0; border-radius: 8px; }
    hr { border-color: #e2e8f0 !important; }
    .section-label {
        font-family: 'DM Sans', sans-serif; font-size: 0.7rem; font-weight: 600;
        letter-spacing: 0.15em; text-transform: uppercase; color: #94a3b8; margin-bottom: 4px;
    }
    .section-title {
        font-family: 'Source Serif 4', serif; font-size: 1.6rem;
        color: #1e293b; margin-bottom: 16px;
    }
    #MainMenu {visibility: hidden;} footer {visibility: hidden;} header {visibility: hidden;}
    </style>
    """, unsafe_allow_html=True)

    # ── Redshift connection ──────────────────────────────────────────────────
    def get_redshift_connection():
        creds = st.secrets["redshift"]
        if "rs_conn" not in st.session_state or st.session_state.rs_conn.closed:
            st.session_state.rs_conn = psycopg2.connect(
                host=creds["host"], port=int(creds["port"]),
                dbname=creds["database"], user=creds["user"], password=creds["password"],
            )
        return st.session_state.rs_conn

    # ── Data loaders ─────────────────────────────────────────────────────────
    @st.cache_data(ttl=3600)
    def load_team_roster():
        query = """
        SELECT DISTINCT
            e1.id AS tutor_id,
            t_users.first_name||' '||t_users.last_name AS tutor,
            m_users.first_name||' '||m_users.last_name AS manager
        FROM dw.employees e1
            JOIN dw.team_members ON team_members.member_id = e1.id
            JOIN dw.teams ON teams.id = team_members.team_id
            JOIN dw.users t_users ON e1.user_id = t_users.id
            JOIN dw.employees e2 ON e2.id = teams.manager_id
            JOIN dw.users m_users ON e2.user_id = m_users.id
        WHERE e1.type = 'Tutor' AND e1.end_date IS NULL
            AND e1.tier_id IS NOT NULL AND t_users.title = 'Tutor'
        """
        conn = get_redshift_connection()
        return pd.read_sql(query, conn)

    @st.cache_data(ttl=3600)
    def load_score_guarantee():
        token = st.secrets.get("github", {}).get("token", "")
        repo = st.secrets.get("github", {}).get("repo", "")
        path = "data/score_guarantee.csv"
        if not token or not repo:
            return pd.DataFrame()
        url = f"https://api.github.com/repos/{repo}/contents/{path}"
        headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}
        r = requests.get(url, headers=headers, timeout=15)
        if r.status_code != 200:
            return pd.DataFrame()
        import io
        decoded = base64.b64decode(r.json()["content"]).decode("utf-8")
        return pd.read_csv(io.StringIO(decoded))

    @st.cache_data(ttl=3600)
    def load_sg_sessions():
        token = st.secrets.get("github", {}).get("token", "")
        repo = st.secrets.get("github", {}).get("repo", "")
        path = "data/score_guarantee_sessions.csv"
        if not token or not repo:
            return pd.DataFrame()
        url = f"https://api.github.com/repos/{repo}/contents/{path}"
        headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}
        r = requests.get(url, headers=headers, timeout=15)
        if r.status_code != 200:
            return pd.DataFrame()
        import io
        return pd.read_csv(io.StringIO(base64.b64decode(r.json()["content"]).decode("utf-8")))

    @st.cache_data(ttl=3600)
    def load_sg_exams():
        token = st.secrets.get("github", {}).get("token", "")
        repo = st.secrets.get("github", {}).get("repo", "")
        path = "data/score_guarantee_exams.csv"
        if not token or not repo:
            return pd.DataFrame()
        url = f"https://api.github.com/repos/{repo}/contents/{path}"
        headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}
        r = requests.get(url, headers=headers, timeout=15)
        if r.status_code != 200:
            return pd.DataFrame()
        import io
        return pd.read_csv(io.StringIO(base64.b64decode(r.json()["content"]).decode("utf-8")))

    def load_sg_notes():
        token = st.secrets.get("github", {}).get("token", "")
        repo = st.secrets.get("github", {}).get("repo", "")
        path = "data/score_guarantee_notes.csv"
        if not token or not repo:
            return pd.DataFrame(columns=["student_id", "note", "color", "updated_at"])
        url = f"https://api.github.com/repos/{repo}/contents/{path}"
        headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}
        r = requests.get(url, headers=headers, timeout=15)
        if r.status_code != 200:
            return pd.DataFrame(columns=["student_id", "note", "color", "updated_at"])
        import io
        decoded = base64.b64decode(r.json()["content"]).decode("utf-8")
        return pd.read_csv(io.StringIO(decoded))

    def save_sg_notes(notes_df):
        token = st.secrets.get("github", {}).get("token", "")
        repo = st.secrets.get("github", {}).get("repo", "")
        path = "data/score_guarantee_notes.csv"
        if not token or not repo:
            return False
        url = f"https://api.github.com/repos/{repo}/contents/{path}"
        headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}
        csv_bytes = notes_df.to_csv(index=False).encode("utf-8")
        encoded = base64.b64encode(csv_bytes).decode("utf-8")
        r = requests.get(url, headers=headers, timeout=15)
        payload = {
            "message": f"Update SG notes — {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}",
            "content": encoded,
        }
        if r.status_code == 200:
            payload["sha"] = r.json().get("sha")
        r2 = requests.put(url, headers=headers, json=payload, timeout=30)
        return r2.status_code in (200, 201)

    def load_sg_legend():
        token = st.secrets.get("github", {}).get("token", "")
        repo = st.secrets.get("github", {}).get("repo", "")
        path = "data/score_guarantee_legend.csv"
        if not token or not repo:
            return {}
        url = f"https://api.github.com/repos/{repo}/contents/{path}"
        headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}
        r = requests.get(url, headers=headers, timeout=15)
        if r.status_code != 200:
            return {}
        import io
        decoded = base64.b64decode(r.json()["content"]).decode("utf-8")
        df = pd.read_csv(io.StringIO(decoded))
        return dict(zip(df["color"], df["label"]))

    def save_sg_legend(legend_dict):
        token = st.secrets.get("github", {}).get("token", "")
        repo = st.secrets.get("github", {}).get("repo", "")
        path = "data/score_guarantee_legend.csv"
        if not token or not repo:
            return False
        url = f"https://api.github.com/repos/{repo}/contents/{path}"
        headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}
        df = pd.DataFrame([{"color": k, "label": v} for k, v in legend_dict.items()])
        csv_bytes = df.to_csv(index=False).encode("utf-8")
        encoded = base64.b64encode(csv_bytes).decode("utf-8")
        r = requests.get(url, headers=headers, timeout=15)
        payload = {
            "message": f"Update SG legend — {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}",
            "content": encoded,
        }
        if r.status_code == 200:
            payload["sha"] = r.json().get("sha")
        r2 = requests.put(url, headers=headers, json=payload, timeout=30)
        return r2.status_code in (200, 201)

    # ── Load data ─────────────────────────────────────────────────────────────
    try:
        df_roster = load_team_roster()
        df_sg = load_score_guarantee()
        df_sg_sessions = load_sg_sessions()
        df_sg_exams = load_sg_exams()
        # Remove exam entries with blank/null scores
        if not df_sg_exams.empty:
            df_sg_exams["score"] = pd.to_numeric(df_sg_exams["score"], errors="coerce")
            df_sg_exams = df_sg_exams[df_sg_exams["score"].notna()].reset_index(drop=True)
        if "sg_notes" not in st.session_state:
            st.session_state.sg_notes = load_sg_notes()
        if "sg_legend" not in st.session_state:
            st.session_state.sg_legend = load_sg_legend()
    except Exception as e:
        st.error(f"Could not load data: {e}")
        st.stop()

    # ── Sidebar ───────────────────────────────────────────────────────────────
    with st.sidebar:
        st.markdown(
            "<p style='font-family: Source Serif 4, serif; font-size:1.4rem; "
            "color:#1e293b; margin-bottom:0;'>Score Guarantee</p>"
            "<p style='color:#64748b; font-size:0.8rem; margin-top:0;'>Compliance Tracker</p>",
            unsafe_allow_html=True,
        )
        st.divider()
        if st.button("🔄 Refresh Data", use_container_width=True):
            st.cache_data.clear()
            st.rerun()

    # ── Score Guarantee Content ──────────────────────────────────────────────
    st.markdown(
        "<p class='section-label'>Test Prep</p>"
        "<p class='section-title'>Score Guarantee Overview</p>",
        unsafe_allow_html=True,
    )

    if df_sg.empty:
        st.warning("Score guarantee data not available. Check GitHub secrets.")
    else:
        # ── New Student Alert ─────────────────────────────────────────────
        sg_new_check = df_sg.copy()
        sg_new_check["won_at"] = pd.to_datetime(sg_new_check["won_at"], errors="coerce")
        seven_days_ago = pd.Timestamp.now() - pd.DateOffset(days=7)
        new_students = sg_new_check[sg_new_check["won_at"] >= seven_days_ago].sort_values("student")

        if len(new_students) > 0:
            items = ""
            for _, row in new_students.iterrows():
                student = row.get("student", "Unknown")
                advisor = row.get("advisor", "Unknown")
                tutor = row.get("tutor", "Unknown") or "Not assigned"
                fl = row.get("faculty_leader", "—") or "—"
                won = row["won_at"].strftime("%b %d, %Y") if pd.notna(row.get("won_at")) else "—"
                pkg = f"{row['package_hours']:.0f} hrs" if pd.notna(row.get("package_hours")) else "—"
                items += (
                    f"<div style='background:white; border:1px solid #bae6fd; border-radius:6px; padding:8px 12px; margin:6px 0;'>"
                    f"<p style='color:#1e293b; font-weight:600; font-size:0.85rem; margin:0;'>{student}</p>"
                    f"<table style='width:100%; font-size:0.78rem; color:#64748b; margin-top:4px;'>"
                    f"<tr><td style='padding:1px 0;'>Advisor</td><td style='padding:1px 0; text-align:right; color:#1e293b;'>{advisor}</td></tr>"
                    f"<tr><td style='padding:1px 0;'>Tutor</td><td style='padding:1px 0; text-align:right; color:#1e293b;'>{tutor}</td></tr>"
                    f"<tr><td style='padding:1px 0;'>Faculty Leader</td><td style='padding:1px 0; text-align:right; color:#1e293b;'>{fl}</td></tr>"
                    f"<tr><td style='padding:1px 0;'>Package</td><td style='padding:1px 0; text-align:right; color:#1e293b;'>{pkg}</td></tr>"
                    f"<tr><td style='padding:1px 0;'>Won Date</td><td style='padding:1px 0; text-align:right; color:#0369a1; font-weight:600;'>{won}</td></tr>"
                    f"</table></div>"
                )
            st.markdown(
                f"<div style='background:#f0f9ff; border:1px solid #bae6fd; border-radius:10px; padding:14px 16px; margin-bottom:16px;'>"
                f"<p style='color:#0369a1; font-weight:600; font-size:0.85rem; margin:0 0 8px 0;'>"
                f"🆕 NEW SCORE GUARANTEE STUDENTS THIS WEEK ({len(new_students)})</p>"
                f"{items}</div>",
                unsafe_allow_html=True,
            )
            st.markdown("")

        # ── Compute hidden tags ───────────────────────────────────────────
        legend_for_hide = st.session_state.sg_legend
        hide_tags_alert = set()
        for emoji, label in legend_for_hide.items():
            if str(label).strip().lower() in ["not score guarantee", "completed", "refunded"]:
                hide_tags_alert.add(emoji)

        hidden_sids_alert = set()
        if not st.session_state.sg_notes.empty and "color" in st.session_state.sg_notes.columns:
            for _, nr in st.session_state.sg_notes.iterrows():
                if str(nr.get("color", "")) in hide_tags_alert:
                    hidden_sids_alert.add(str(nr["student_id"]).split(".")[0])

        # ── Score Guarantee Alerts ────────────────────────────────────────
        sg_alert_data = df_sg.copy()
        for col in ["starting_score", "starting_test_taken", "latest_test_score", "last_test_taken"]:
            if col in sg_alert_data.columns:
                sg_alert_data[col] = sg_alert_data[col].astype(object)
        # Apply test type overrides to alert data too
        if not st.session_state.sg_notes.empty and "test_type_override" in st.session_state.sg_notes.columns:
            for _, nr in st.session_state.sg_notes.iterrows():
                ov = str(nr.get("test_type_override", "") or "")
                if ov not in ["SAT", "ACT"]:
                    continue
                ov_sid = str(nr["student_id"]).split(".")[0]
                for a_idx in sg_alert_data.index:
                    if str(sg_alert_data.at[a_idx, "student_id"]).split(".")[0] == ov_sid:
                        if not df_sg_exams.empty:
                            stu_ex = df_sg_exams[df_sg_exams["student_id"].astype(str).str.split(".").str[0] == ov_sid].copy()
                            stu_ex["exam_date"] = pd.to_datetime(stu_ex["exam_date"], errors="coerce")
                            stu_ex["score"] = pd.to_numeric(stu_ex["score"], errors="coerce")
                            if ov == "SAT":
                                typed = stu_ex[stu_ex["exam_type"].isin(["SAT", "Digital SAT"])]
                            else:
                                typed = stu_ex[stu_ex["exam_type"].isin(["ACT", "Digital ACT"])]
                            typed = typed.dropna(subset=["score"])
                            before = typed[typed["before_or_after_tutoring"] == "before"].sort_values("exam_date", ascending=False)
                            sg_alert_data.at[a_idx, "starting_score"] = float(before.iloc[0]["score"]) if len(before) > 0 else np.nan
                            sg_alert_data.at[a_idx, "starting_test_taken"] = before.iloc[0]["exam_date"] if len(before) > 0 else pd.NaT
                        break
        sg_alert_data["_sid_str"] = sg_alert_data["student_id"].astype(str).str.split(".").str[0]
        sg_alert_data = sg_alert_data[~sg_alert_data["_sid_str"].isin(hidden_sids_alert)]
        sg_alert_data.drop(columns=["_sid_str"], inplace=True)
        for col in ["first_test_prep_session", "starting_test_taken", "won_at"]:
            if col in sg_alert_data.columns:
                sg_alert_data[col] = pd.to_datetime(sg_alert_data[col], errors="coerce")
        for col in ["package_hours", "completed_test_prep_hours", "starting_score"]:
            if col in sg_alert_data.columns:
                sg_alert_data[col] = pd.to_numeric(sg_alert_data[col], errors="coerce")

        # Alert 1: No baseline score
        no_baseline = sg_alert_data[
            sg_alert_data["first_test_prep_session"].notna()
            & (sg_alert_data["starting_score"].isna()
               | sg_alert_data["starting_test_taken"].isna()
               | (sg_alert_data["starting_test_taken"] > sg_alert_data["first_test_prep_session"]))
        ].sort_values("first_test_prep_session", ascending=True, na_position="first")

        no_baseline_html = ""
        if len(no_baseline) > 0:
            items = ""
            for _, row in no_baseline.iterrows():
                student = row.get("student", "Unknown")
                advisor = row.get("advisor", "Unknown")
                first_sess = row["first_test_prep_session"].strftime("%Y-%m-%d") if pd.notna(row.get("first_test_prep_session")) else "—"
                items += (
                    f"<div style='background:white; border:1px solid #fecaca; border-radius:6px; padding:8px 12px; margin:6px 0;'>"
                    f"<p style='color:#1e293b; font-weight:600; font-size:0.85rem; margin:0;'>{student}</p>"
                    f"<table style='width:100%; font-size:0.78rem; color:#64748b; margin-top:4px;'>"
                    f"<tr><td style='padding:1px 0;'>Advisor</td><td style='padding:1px 0; text-align:right; color:#1e293b;'>{advisor}</td></tr>"
                    f"<tr><td style='padding:1px 0;'>Tutoring Since</td><td style='padding:1px 0; text-align:right; color:#991b1b; font-weight:600;'>{first_sess}</td></tr>"
                    f"</table></div>"
                )
            no_baseline_html = (
                    "<p style='color:#64748b; font-size:0.78rem; margin-bottom:10px; font-style:italic;'>"
                    "Students who have started tutoring but do not have a test score recorded before their first session. "
                    "A baseline is required to measure improvement and determine the score guarantee target.</p>"
                ) + items

        # Alert 2: Behind on exams
        behind_on_exams = []
        if not df_sg_sessions.empty and not df_sg_exams.empty:
            for _, row in sg_alert_data.iterrows():
                sid = row["student_id"]
                pkg_hrs = row["package_hours"]
                if pd.isna(pkg_hrs) or pd.isna(row.get("first_test_prep_session")):
                    continue
                required_total = 4
                milestone_hours = [5, 10, 15, 20]
                completed = row["completed_test_prep_hours"] if pd.notna(row.get("completed_test_prep_hours")) else 0
                exams_expected = sum(1 for mh in milestone_hours if completed >= mh)
                exams_taken = 0
                if sid in df_sg_exams["student_id"].values:
                    alert_exams = df_sg_exams[(df_sg_exams["student_id"] == sid) & (df_sg_exams["before_or_after_tutoring"] == "after")].copy()
                    alert_exams["score"] = pd.to_numeric(alert_exams["score"], errors="coerce")
                    # Detect test type for this student
                    alert_baseline = row.get("starting_score")
                    if pd.notna(alert_baseline):
                        if alert_baseline > 100:
                            alert_exams = alert_exams[alert_exams["exam_type"].isin(["SAT", "Digital SAT"])]
                        else:
                            alert_exams = alert_exams[alert_exams["exam_type"].isin(["ACT", "Digital ACT"])]
                    exams_taken = len(alert_exams)
                if exams_expected > 0 and exams_taken < exams_expected:
                    behind_on_exams.append({
                        "student": row.get("student", "Unknown"),
                        "advisor": row.get("advisor", "Unknown"),
                        "tutor": row.get("tutor", "Unknown"),
                        "exams_taken": exams_taken,
                        "exams_expected": exams_expected,
                        "completed": completed,
                        "pkg_hrs": pkg_hrs,
                        "required_total": required_total,
                    })
            behind_on_exams.sort(key=lambda x: x["student"])

        behind_html = ""
        if len(behind_on_exams) > 0:
            items = ""
            for b in behind_on_exams:
                items += (
                    f"<div style='background:white; border:1px solid #fde68a; border-radius:6px; padding:8px 12px; margin:6px 0;'>"
                    f"<p style='color:#1e293b; font-weight:600; font-size:0.85rem; margin:0;'>{b['student']}</p>"
                    f"<table style='width:100%; font-size:0.78rem; color:#64748b; margin-top:4px;'>"
                    f"<tr><td style='padding:1px 0;'>Advisor</td><td style='padding:1px 0; text-align:right; color:#1e293b;'>{b['advisor']}</td></tr>"
                    f"<tr><td style='padding:1px 0;'>Tutor</td><td style='padding:1px 0; text-align:right; color:#1e293b;'>{b['tutor']}</td></tr>"
                    f"<tr><td style='padding:1px 0;'>Exams</td><td style='padding:1px 0; text-align:right; color:#92400e; font-weight:600;'>{b['exams_taken']}/{b['exams_expected']} taken</td></tr>"
                    f"<tr><td style='padding:1px 0;'>Hours</td><td style='padding:1px 0; text-align:right; color:#1e293b;'>{b['completed']:.0f}/20 hrs</td></tr>"
                    f"</table></div>"
                )
            behind_html = (
                    "<p style='color:#64748b; font-size:0.78rem; margin-bottom:10px; font-style:italic;'>"
                    "Students who should have taken more practice tests based on hours completed. "
                    "4 tests are required, spaced at 25%, 50%, 75%, and 100% of package hours.</p>"
                ) + items

        # Alert 3: No score improvement
        score_concerns = []
        if not df_sg_exams.empty:
            for _, row in sg_alert_data.iterrows():
                sid = row["student_id"]
                baseline = row["starting_score"]
                if pd.isna(baseline) or sid not in df_sg_exams["student_id"].values:
                    continue
                stu_exams = df_sg_exams[df_sg_exams["student_id"] == sid].copy()
                stu_exams["exam_date"] = pd.to_datetime(stu_exams["exam_date"], errors="coerce")
                stu_exams["score"] = pd.to_numeric(stu_exams["score"], errors="coerce")
                # Filter by test type
                if pd.notna(baseline):
                    if baseline > 100:
                        stu_exams = stu_exams[stu_exams["exam_type"].isin(["SAT", "Digital SAT"])]
                    else:
                        stu_exams = stu_exams[stu_exams["exam_type"].isin(["ACT", "Digital ACT"])]
                after_exams = stu_exams[
                    (stu_exams["before_or_after_tutoring"] == "after") & stu_exams["score"].notna()
                ].sort_values("exam_date")
                if len(after_exams) == 0:
                    continue
                most_recent = after_exams.iloc[-1]["score"]
                avg_score = after_exams["score"].mean()
                recent_vs_baseline = most_recent - baseline
                # Check against target, not just baseline
                if baseline > 100:  # SAT
                    target = baseline + 150 if baseline < 1350 else 1500
                else:  # ACT
                    target = baseline + 2 if baseline < 29 else 31
                points_to_target = target - most_recent

                # Check if on pace toward target
                on_pace = False
                if len(after_exams) >= 2 and points_to_target > 0:
                    total_needed = target - baseline
                    expected = (total_needed / 4.0) * len(after_exams)
                    actual = most_recent - baseline
                    if total_needed > 0 and actual >= expected * 0.75:
                        on_pace = True

                if (recent_vs_baseline <= 0 or points_to_target > 0) and not on_pace:
                    if len(after_exams) >= 2:
                        first_after = after_exams.iloc[0]["score"]
                        trend = "📈 up" if most_recent > first_after else ("📉 down" if most_recent < first_after else "➡️ flat")
                    else:
                        trend = "—"
                    score_concerns.append({
                        "student": row.get("student", "Unknown"),
                        "advisor": row.get("advisor", "Unknown"),
                        "tutor": row.get("tutor", "Unknown"),
                        "baseline": baseline,
                        "most_recent": most_recent,
                        "recent_change": recent_vs_baseline,
                        "target": target,
                        "points_to_target": points_to_target,
                        "avg_score": avg_score,
                        "num_exams": len(after_exams),
                        "trend": trend,
                    })
            score_concerns.sort(key=lambda x: x["student"])

        score_html = ""
        if len(score_concerns) > 0:
            items = ""
            for sc in score_concerns:
                items += (
                    f"<div style='background:white; border:1px solid #fecaca; border-radius:6px; padding:8px 12px; margin:6px 0;'>"
                    f"<p style='color:#1e293b; font-weight:600; font-size:0.85rem; margin:0;'>{sc['student']}</p>"
                    f"<table style='width:100%; font-size:0.78rem; color:#64748b; margin-top:4px;'>"
                    f"<tr><td style='padding:1px 0;'>Advisor</td><td style='padding:1px 0; text-align:right; color:#1e293b;'>{sc['advisor']}</td></tr>"
                    f"<tr><td style='padding:1px 0;'>Tutor</td><td style='padding:1px 0; text-align:right; color:#1e293b;'>{sc['tutor']}</td></tr>"
                    f"<tr><td style='padding:1px 0;'>Scores</td><td style='padding:1px 0; text-align:right; color:#991b1b; font-weight:600;'>{sc['baseline']:.0f} → {sc['most_recent']:.0f} ({sc['recent_change']:+.0f})</td></tr>"
                    f"<tr><td style='padding:1px 0;'>Target</td><td style='padding:1px 0; text-align:right; color:#1e293b;'>{sc['target']:.0f} ({sc['points_to_target']:+.0f} needed)</td></tr>"
                    f"<tr><td style='padding:1px 0;'>Exams / Trend</td><td style='padding:1px 0; text-align:right; color:#1e293b;'>{sc['num_exams']} exams {sc['trend']}</td></tr>"
                    f"</table></div>"
                )
            score_html = (
                    "<p style='color:#64748b; font-size:0.78rem; margin-bottom:10px; font-style:italic;'>"
                    "Students whose latest score has not improved over baseline or who are not on pace to meet their target. "
                    "SAT: &lt;1350 needs +150, 1350+ needs 1500. ACT: &lt;29 needs +2, 29+ needs 31. "
                    "Students making proportional progress are not flagged.</p>"
                ) + items

        # Render alerts horizontally
        alert_configs = [
            ("⚠️ No Baseline Score", no_baseline_html, len(no_baseline) if len(no_baseline) > 0 else 0),
            ("⚠️ Behind on Practice Tests", behind_html, len(behind_on_exams)),
            ("⚠️ Off Target / No Improvement", score_html, len(score_concerns)),
        ]
        active_alerts = [(label, html, cnt) for label, html, cnt in alert_configs if html]
        if active_alerts:
            cols = st.columns(len(active_alerts))
            for i, (label, html, cnt) in enumerate(active_alerts):
                with cols[i]:
                    with st.expander(f"{label} ({cnt})", expanded=False):
                        st.markdown(html, unsafe_allow_html=True)
            st.markdown("")
        sg = df_sg.copy()
        for col in ["won_at", "first_test_prep_session", "starting_test_taken", "last_test_taken"]:
            if col in sg.columns:
                sg[col] = pd.to_datetime(sg[col], errors="coerce")
        for col in ["package_hours", "completed_test_prep_hours", "starting_score", "latest_test_score"]:
            if col in sg.columns:
                sg[col] = pd.to_numeric(sg[col], errors="coerce")
        sg["score_change"] = sg["latest_test_score"] - sg["starting_score"]

        # Add Faculty Leader from team roster based on tutor name
        tutor_to_fl = df_roster[["tutor", "manager"]].drop_duplicates().rename(
            columns={"tutor": "_tutor_match", "manager": "faculty_leader"}
        )
        # Match on first tutor if multiple
        sg["_tutor_match"] = sg["tutor"].apply(
            lambda x: x.split(",")[1].strip() if pd.notna(x) and "," in x else (x.split(",")[0].strip() if pd.notna(x) else None)
        )
        sg = sg.merge(tutor_to_fl, on="_tutor_match", how="left")
        sg.drop(columns=["_tutor_match"], inplace=True)

        # Score improvement targets (SAT: 400-1600 range, ACT: 1-36 range)
        def calc_target_with_type(score, test_type):
            if pd.isna(score):
                return np.nan
            if test_type == "SAT":
                return score + 150 if score < 1350 else 1500
            else:
                return score + 2 if score < 29 else 31

        def calc_target(score):
            if pd.isna(score):
                return np.nan
            if score > 100:  # SAT
                return score + 150 if score < 1350 else 1500
            else:  # ACT
                return score + 2 if score < 29 else 31
        sg["test_type"] = sg["starting_score"].apply(
            lambda x: "SAT" if pd.notna(x) and x > 100 else ("ACT" if pd.notna(x) else None)
        )
        sg["target_score"] = sg["starting_score"].apply(calc_target)
        sg["points_to_target"] = sg["target_score"] - sg["latest_test_score"]
        sg["on_track"] = sg["latest_test_score"] >= sg["target_score"]

        # ── Apply test type overrides directly to sg ──────────────────────
        # ── Re-derive scores per student based on test_type ─────────────
        # Build set of overridden student IDs so we don't overwrite them
        overridden_sids = set()
        if not st.session_state.sg_notes.empty and "test_type_override" in st.session_state.sg_notes.columns:
            for _, nr in st.session_state.sg_notes.iterrows():
                ov = str(nr.get("test_type_override", "") or "")
                if ov in ["SAT", "ACT"]:
                    overridden_sids.add(str(nr["student_id"]).split(".")[0])

        if not df_sg_exams.empty:
            for sg_idx in sg.index:
                sid = sg.at[sg_idx, "student_id"]
                # Skip students with manual overrides — already handled
                if str(sid).split(".")[0] in overridden_sids:
                    continue
                tt = sg.at[sg_idx, "test_type"]
                if tt not in ["SAT", "ACT"]:
                    continue
                stu_exams = df_sg_exams[df_sg_exams["student_id"] == sid].copy()
                if stu_exams.empty:
                    continue
                stu_exams["exam_date"] = pd.to_datetime(stu_exams["exam_date"], errors="coerce")
                stu_exams["score"] = pd.to_numeric(stu_exams["score"], errors="coerce")
                if tt == "SAT":
                    typed = stu_exams[stu_exams["exam_type"].isin(["SAT", "Digital SAT"])]
                else:
                    typed = stu_exams[stu_exams["exam_type"].isin(["ACT", "Digital ACT"])]
                typed = typed.dropna(subset=["score"])
                before = typed[typed["before_or_after_tutoring"] == "before"].sort_values("exam_date", ascending=False)
                after = typed[typed["before_or_after_tutoring"] == "after"].sort_values("exam_date", ascending=False)
                if len(before) > 0:
                    sg.at[sg_idx, "starting_score"] = float(before.iloc[0]["score"])
                    sg.at[sg_idx, "starting_test_taken"] = before.iloc[0]["exam_date"]
                if len(after) > 0:
                    sg.at[sg_idx, "latest_test_score"] = float(after.iloc[0]["score"])
                    sg.at[sg_idx, "last_test_taken"] = after.iloc[0]["exam_date"]
                else:
                    sg.at[sg_idx, "latest_test_score"] = np.nan
                    sg.at[sg_idx, "last_test_taken"] = pd.NaT
                s = sg.at[sg_idx, "starting_score"]
                l = sg.at[sg_idx, "latest_test_score"]
                sg.at[sg_idx, "score_change"] = float(l - s) if pd.notna(l) and pd.notna(s) else np.nan
                sg.at[sg_idx, "target_score"] = float(calc_target_with_type(s, tt)) if pd.notna(s) else np.nan
                t = sg.at[sg_idx, "target_score"]
                sg.at[sg_idx, "points_to_target"] = float(t - l) if pd.notna(l) and pd.notna(t) else np.nan

        # Convert columns to object type so we can assign mixed types
        for col in ["on_track", "test_type", "starting_score", "latest_test_score",
                     "score_change", "target_score", "points_to_target",
                     "starting_test_taken", "last_test_taken"]:
            if col in sg.columns:
                sg[col] = sg[col].astype(object)

        if not st.session_state.sg_notes.empty and "test_type_override" in st.session_state.sg_notes.columns:
            for _, nr in st.session_state.sg_notes.iterrows():
                ov = str(nr.get("test_type_override", "") or "")
                if ov not in ["SAT", "ACT"]:
                    continue
                ov_sid = str(nr["student_id"]).split(".")[0]
                # Find matching row in sg
                for sg_idx in sg.index:
                    if str(sg.loc[sg_idx, "student_id"]).split(".")[0] == ov_sid:
                        # Re-derive scores from exam data for this test type
                        if not df_sg_exams.empty:
                            stu_exams = df_sg_exams[df_sg_exams["student_id"].astype(str).str.split(".").str[0] == ov_sid].copy()
                            stu_exams["exam_date"] = pd.to_datetime(stu_exams["exam_date"], errors="coerce")
                            stu_exams["score"] = pd.to_numeric(stu_exams["score"], errors="coerce")
                            if ov == "SAT":
                                typed = stu_exams[stu_exams["exam_type"].isin(["SAT", "Digital SAT"])]
                            else:
                                typed = stu_exams[stu_exams["exam_type"].isin(["ACT", "Digital ACT"])]
                            typed = typed.dropna(subset=["score"])
                            before = typed[typed["before_or_after_tutoring"] == "before"].sort_values("exam_date", ascending=False)
                            after = typed[typed["before_or_after_tutoring"] == "after"].sort_values("exam_date", ascending=False)
                            # Clear all scores first
                            sg.at[sg_idx, "starting_score"] = np.nan
                            sg.at[sg_idx, "starting_test_taken"] = pd.NaT
                            sg.at[sg_idx, "latest_test_score"] = np.nan
                            sg.at[sg_idx, "last_test_taken"] = pd.NaT
                            if len(before) > 0:
                                sg.at[sg_idx, "starting_score"] = float(before.iloc[0]["score"])
                                sg.at[sg_idx, "starting_test_taken"] = before.iloc[0]["exam_date"]
                            if len(after) > 0:
                                sg.at[sg_idx, "latest_test_score"] = float(after.iloc[0]["score"])
                                sg.at[sg_idx, "last_test_taken"] = after.iloc[0]["exam_date"]
                        sg.at[sg_idx, "test_type"] = ov
                        # Recalculate derived fields
                        s_score = sg.at[sg_idx, "starting_score"]
                        l_score = sg.at[sg_idx, "latest_test_score"]
                        sg.at[sg_idx, "score_change"] = float(l_score - s_score) if pd.notna(l_score) and pd.notna(s_score) else np.nan
                        sg.at[sg_idx, "target_score"] = float(calc_target_with_type(s_score, ov)) if pd.notna(s_score) else np.nan
                        t_score = sg.at[sg_idx, "target_score"]
                        sg.at[sg_idx, "points_to_target"] = float(t_score - l_score) if pd.notna(l_score) and pd.notna(t_score) else np.nan
                        if pd.notna(l_score) and pd.notna(t_score):
                            sg.at[sg_idx, "on_track"] = bool(l_score >= t_score)
                        else:
                            sg.at[sg_idx, "on_track"] = None
                        break

        # DEBUG: show what overrides were found
        # ── Build compliance checklist per student ─────────────────────────
        compliance_rows = []
        for _, row in sg.iterrows():
            sid = row["student_id"]
            checks = {}

            # Check for 2+ week gaps in tutoring sessions
            checks["session_gap"] = None
            checks["max_session_gap"] = None
            if not df_sg_sessions.empty and sid in df_sg_sessions["student_id"].values:
                stu_sess_gap = df_sg_sessions[df_sg_sessions["student_id"] == sid].copy()
                stu_sess_gap["starts_at"] = pd.to_datetime(stu_sess_gap["starts_at"], errors="coerce")
                stu_sess_gap = stu_sess_gap.dropna(subset=["starts_at"]).sort_values("starts_at")
                if len(stu_sess_gap) >= 2:
                    gaps = stu_sess_gap["starts_at"].diff().dt.days.dropna()
                    max_gap = int(gaps.max()) if len(gaps) > 0 else 0
                    checks["max_session_gap"] = max_gap
                    checks["session_gap"] = max_gap >= 14

            # 1. Package 20+ hours
            checks["1_pkg_20hrs"] = row["package_hours"] >= 20 if pd.notna(row["package_hours"]) else False

            # 2. Used 20+ hours of test prep tutoring
            checks["2_hours_used"] = (
                row["completed_test_prep_hours"] >= 20
                if pd.notna(row["completed_test_prep_hours"])
                else False
            )

            # 3. Pace 1-2 hrs/week — need session detail
            if not df_sg_sessions.empty and sid in df_sg_sessions["student_id"].values:
                stu_sess = df_sg_sessions[df_sg_sessions["student_id"] == sid].copy()
                stu_sess["starts_at"] = pd.to_datetime(stu_sess["starts_at"], errors="coerce")
                stu_sess = stu_sess.dropna(subset=["starts_at"]).sort_values("starts_at")
                if len(stu_sess) >= 2:
                    first_s = stu_sess["starts_at"].min()
                    last_s = stu_sess["starts_at"].max()
                    weeks = max((last_s - first_s).days / 7.0, 1)
                    total_hrs = stu_sess["session_hours"].sum()
                    hrs_per_week = total_hrs / weeks
                    checks["3_pace_ok"] = 0.5 <= hrs_per_week <= 3.0
                    checks["3_pace_val"] = round(hrs_per_week, 2)
                else:
                    checks["3_pace_ok"] = None
                    checks["3_pace_val"] = None
            else:
                checks["3_pace_ok"] = None
                checks["3_pace_val"] = None

            # 4. Baseline score before first session
            has_baseline = pd.notna(row["starting_test_taken"]) and pd.notna(row["starting_score"])
            has_started = pd.notna(row["first_test_prep_session"])
            if has_baseline and not has_started:
                # Has baseline, hasn't started tutoring yet — requirement met
                checks["4_baseline"] = True
            elif has_baseline and has_started:
                # Has baseline and started — check if baseline was before first session
                checks["4_baseline"] = row["starting_test_taken"] <= row["first_test_prep_session"]
            elif not has_baseline and has_started:
                # Started tutoring without a baseline — fail
                checks["4_baseline"] = False
            else:
                # No baseline, no tutoring — not applicable
                checks["4_baseline"] = None

            # 5. No missed sessions
            if not df_sg_sessions.empty and sid in df_sg_sessions["student_id"].values:
                stu_sess = df_sg_sessions[df_sg_sessions["student_id"] == sid]
                total_sessions = len(stu_sess)
                attended_sessions = int(stu_sess["attended"].sum())
                checks["5_attendance"] = attended_sessions == total_sessions
                checks["5_attended"] = attended_sessions
                checks["5_total"] = total_sessions
            else:
                checks["5_attendance"] = None
                checks["5_attended"] = None
                checks["5_total"] = None

            # 7. Minimum 4 practice tests (excluding baseline)
            required_tests = 4

            if not df_sg_exams.empty and sid in df_sg_exams["student_id"].values:
                stu_exams = df_sg_exams[df_sg_exams["student_id"] == sid].copy()
                stu_exams["exam_date"] = pd.to_datetime(stu_exams["exam_date"], errors="coerce")
                # Filter by test type
                _tt = str(sg.loc[sg["student_id"] == sid, "test_type"].iloc[0]) if sid in sg["student_id"].values else ""
                if _tt == "SAT":
                    stu_exams = stu_exams[stu_exams["exam_type"].isin(["SAT", "Digital SAT"])]
                elif _tt == "ACT":
                    stu_exams = stu_exams[stu_exams["exam_type"].isin(["ACT", "Digital ACT"])]
                after_exams = stu_exams[stu_exams["before_or_after_tutoring"] == "after"]
                checks["7_practice_tests"] = len(after_exams) >= required_tests
                checks["7_taken"] = len(after_exams)
                checks["7_required"] = required_tests

                # 8. At least 1 week gap between practice tests
                if len(after_exams) >= 2:
                    exam_dates = after_exams["exam_date"].dropna().sort_values().reset_index(drop=True)
                    gaps = exam_dates.diff().dt.days.dropna()
                    checks["8_week_gaps"] = bool((gaps >= 7).all()) if len(gaps) > 0 else None
                    checks["8_min_gap"] = int(gaps.min()) if len(gaps) > 0 else None
                else:
                    checks["8_week_gaps"] = None
                    checks["8_min_gap"] = None
            else:
                checks["7_practice_tests"] = None
                checks["7_taken"] = 0
                checks["7_required"] = required_tests
                checks["8_week_gaps"] = None
                checks["8_min_gap"] = None

            # 9. Official exam within 14 days of last session
            #    Only counts "Official Exam" in exam_code, taken after all tutoring hours complete
            checks["9_final_14days"] = None
            checks["9_days_after"] = None
            if not df_sg_exams.empty and sid in df_sg_exams["student_id"].values:
                stu_exams_all = df_sg_exams[df_sg_exams["student_id"] == sid].copy()
                stu_exams_all["exam_date"] = pd.to_datetime(stu_exams_all["exam_date"], errors="coerce")
                official_after = stu_exams_all[
                    (stu_exams_all["exam_code"] == "Official Exam")
                    & (stu_exams_all["before_or_after_tutoring"] == "after")
                ]
                if len(official_after) > 0 and not df_sg_sessions.empty and sid in df_sg_sessions["student_id"].values:
                    stu_sess_9 = df_sg_sessions[df_sg_sessions["student_id"] == sid].copy()
                    stu_sess_9["starts_at"] = pd.to_datetime(stu_sess_9["starts_at"], errors="coerce")
                    last_session = stu_sess_9["starts_at"].max()
                    official_date = official_after["exam_date"].max()
                    if pd.notna(official_date) and pd.notna(last_session):
                        days_after = (official_date - last_session).days
                        checks["9_final_14days"] = 0 <= days_after <= 14
                        checks["9_days_after"] = int(days_after)

            # Score target tracking
            checks["target_score"] = row.get("target_score")
            checks["points_to_target"] = row.get("points_to_target")
            checks["on_track"] = row.get("on_track")

            checks["student_id"] = sid
            checks["student"] = row.get("student", "")
            checks["tutor"] = row.get("tutor", "")
            checks["advisor"] = row.get("advisor", "")
            checks["faculty_leader"] = row.get("faculty_leader", "")
            checks["test_type_override"] = row.get("test_type_override", "")
            checks["package_hours"] = row.get("package_hours")
            checks["completed_hours"] = row.get("completed_test_prep_hours")
            checks["starting_score"] = row.get("starting_score")
            checks["latest_score"] = row.get("latest_test_score")
            checks["score_change"] = row.get("score_change")
            compliance_rows.append(checks)

        comp_df = pd.DataFrame(compliance_rows)

        # ── Compliance summary metrics ────────────────────────────────────
        def pct_pass(col):
            valid = comp_df[col].dropna()
            if len(valid) == 0:
                return "—"
            return f"{(valid.sum() / len(valid) * 100):.0f}%"

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total Packages", len(comp_df))
        c2.metric("Pkg ≥ 20hrs", pct_pass("1_pkg_20hrs"))
        c3.metric("Hours Completed", pct_pass("2_hours_used"))
        c4.metric("Baseline Before Start", pct_pass("4_baseline"))

        c5, c6, c7, c8 = st.columns(4)
        c5.metric("Pace 1-2 hrs/wk", pct_pass("3_pace_ok"))
        c6.metric("100% Attendance", pct_pass("5_attendance"))
        c7.metric("Enough Practice Tests", pct_pass("7_practice_tests"))
        c8.metric("1-Week Test Gaps", pct_pass("8_week_gaps"))

        st.markdown("")

        # ── Compliance matrix ─────────────────────────────────────────────
        st.markdown(
            "<p class='section-label'>Compliance</p>"
            "<p class='section-title'>Score Guarantee Requirements Checklist</p>",
            unsafe_allow_html=True,
        )

        with st.expander("📖 What does each column check?", expanded=False):
            st.markdown("""
| Column | Requirement |
|--------|------------|
| **Pkg ≥20hr** | Package size must be at least 20 hours |
| **Hrs Used** | Student must complete at least 20 hours of test prep tutoring |
| **Pace** | Tutoring hours should be completed at a pace of roughly 1–2 hours per week (shown as hrs/wk) |
| **Baseline** | Student must have a baseline score recorded before their first tutoring session |
| **Attend** | Student must attend all scheduled sessions — no cancellations or no-shows (shown as attended/total) |
| **Tests** | Student must take a minimum of 4 practice tests during their program (excluding baseline) |
| **Gaps ≥7d** | There must be at least 1 week (7 days) between each practice test (shows minimum gap) |
| **Final ≤14d** | Student must take the official exam within 14 days of their last tutoring session |
| **Score** | Starting score → latest score (with change). Not a pass/fail check — shown for reference |
| **Test** | SAT or ACT, auto-detected from baseline score. Can be overridden in Edit Tags |
| **Target** | SAT: below 1350 baseline needs +150 points; 1350+ needs to reach 1500. ACT: below 29 needs +2; 29+ needs 31 |
| **To Target** | Whether the student's latest score meets or exceeds the target (✅ ahead / ❌ points needed) |
| **Sess Gap** | Flags if there is a gap of 2+ weeks (14 days) between any consecutive tutoring sessions |
| **Tag** | Custom color tag for tracking purposes |
| **Notes** | Custom notes — persists across sessions |
""")

        # Filters
        fc1, fc2, fc3, fc4 = st.columns(4)
        with fc1:
            sg_students = sorted(comp_df["student"].dropna().unique())
            sel_students = st.multiselect("Filter by Student", sg_students, key="sg_filter_student")
        with fc2:
            sg_tutors = sorted(comp_df["tutor"].dropna().unique())
            sel_tutors = st.multiselect("Filter by Tutor", sg_tutors, key="sg_filter_tutor")
        with fc3:
            sg_advisors = sorted(comp_df["advisor"].dropna().unique())
            sel_advisors = st.multiselect("Filter by Advisor", sg_advisors, key="sg_filter_advisor")
        with fc4:
            sg_fls = sorted(comp_df["faculty_leader"].dropna().unique())
            sel_fls = st.multiselect("Filter by Faculty Leader", sg_fls, key="sg_filter_fl")

        filtered_comp = comp_df.copy()
        if sel_students:
            filtered_comp = filtered_comp[filtered_comp["student"].isin(sel_students)]
        if sel_tutors:
            filtered_comp = filtered_comp[filtered_comp["tutor"].isin(sel_tutors)]
        if sel_advisors:
            filtered_comp = filtered_comp[filtered_comp["advisor"].isin(sel_advisors)]
        if sel_fls:
            filtered_comp = filtered_comp[filtered_comp["faculty_leader"].isin(sel_fls)]
        filtered_comp = filtered_comp.sort_values("student")

        def status_icon(val):
            if val is True:
                return "✅"
            elif val is False:
                return "❌"
            return "—"

        # Merge notes into comp data
        notes_merged = st.session_state.sg_notes.copy() if not st.session_state.sg_notes.empty else pd.DataFrame(columns=["student_id", "note", "color"])
        if "color" not in notes_merged.columns:
            notes_merged["color"] = ""
        if "test_type_override" not in notes_merged.columns:
            notes_merged["test_type_override"] = ""
        merge_cols = ["student_id", "note", "color", "test_type_override"]
        # Ensure student_id types match for merge
        notes_merged["student_id"] = pd.to_numeric(notes_merged["student_id"], errors="coerce")
        filtered_comp["student_id"] = pd.to_numeric(filtered_comp["student_id"], errors="coerce")
        filtered_comp = filtered_comp.merge(notes_merged[merge_cols], on="student_id", how="left")
        filtered_comp["note"] = filtered_comp["note"].fillna("")
        filtered_comp["color"] = filtered_comp["color"].fillna("")
        if "test_type_override" not in filtered_comp.columns:
            filtered_comp["test_type_override"] = ""
        filtered_comp["test_type_override"] = filtered_comp["test_type_override"].fillna("")

        # Hide students tagged as "Not Score Guarantee" or "Completed"
        legend = st.session_state.sg_legend
        hide_tags = set()
        for emoji, label in legend.items():
            if str(label).strip().lower() in ["not score guarantee", "completed", "refunded"]:
                hide_tags.add(emoji)

        show_hidden = st.checkbox("Show hidden students (Not Score Guarantee / Completed / Refunded)", value=False, key="sg_show_hidden")
        if not show_hidden and hide_tags:
            filtered_comp = filtered_comp[~filtered_comp["color"].isin(hide_tags)]

        # Color tag filter
        active_tags = [c for c in filtered_comp["color"].unique() if c and str(c).strip()]
        if active_tags:
            legend = st.session_state.sg_legend
            tag_display = {t: f"{t} {legend[t]}" if legend.get(t) else t for t in sorted(active_tags)}
            tag_options = list(tag_display.values())
            tag_reverse = {v: k for k, v in tag_display.items()}
            tag_selection = st.multiselect("Filter by Tag", tag_options, key="sg_filter_tag")
            if tag_selection:
                selected_raw_tags = [tag_reverse[s] for s in tag_selection]
                filtered_comp = filtered_comp[filtered_comp["color"].isin(selected_raw_tags)]

        filtered_comp = filtered_comp.reset_index(drop=True)

        matrix = filtered_comp[["student", "tutor", "advisor", "faculty_leader"]].copy()
        matrix = matrix.rename(columns={"faculty_leader": "Faculty Leader"})
        matrix["Pkg ≥20hr"] = filtered_comp.apply(
            lambda r: f"{status_icon(r['1_pkg_20hrs'])} {r['package_hours']:.0f}hr" if pd.notna(r.get("package_hours")) else "—", axis=1
        )
        matrix["Hrs Used"] = filtered_comp.apply(
            lambda r: f"{status_icon(r['2_hours_used'])} {r['completed_hours']:.1f}/20" if pd.notna(r.get("completed_hours")) else "—", axis=1
        )
        matrix["Pace"] = filtered_comp.apply(
            lambda r: f"{status_icon(r['3_pace_ok'])} ({r['3_pace_val']:.1f}/wk)" if pd.notna(r.get("3_pace_val")) else status_icon(r["3_pace_ok"]), axis=1
        )
        matrix["Baseline"] = filtered_comp.apply(
            lambda r: f"{status_icon(r['4_baseline'])} {r['starting_score']:.0f}" if pd.notna(r.get("starting_score")) else f"{status_icon(r['4_baseline'])}", axis=1
        )
        matrix["Attend"] = filtered_comp.apply(
            lambda r: f"{status_icon(r['5_attendance'])} ({int(r['5_attended'])}/{int(r['5_total'])})" if pd.notna(r.get("5_attended")) else "—", axis=1
        )
        matrix["Tests"] = filtered_comp.apply(
            lambda r: f"{status_icon(r['7_practice_tests'])} ({int(r['7_taken'])}/{int(r['7_required'])})" if pd.notna(r.get("7_taken")) else "—", axis=1
        )
        matrix["Gaps ≥7d"] = filtered_comp.apply(
            lambda r: f"{status_icon(r['8_week_gaps'])} (min {int(r['8_min_gap'])}d)" if pd.notna(r.get("8_min_gap")) else status_icon(r["8_week_gaps"]), axis=1
        )
        matrix["Final ≤14d"] = filtered_comp.apply(
            lambda r: f"{status_icon(r['9_final_14days'])} ({int(r['9_days_after'])}d)" if pd.notna(r.get("9_days_after")) else "—", axis=1
        )
        matrix["Score"] = filtered_comp.apply(
            lambda r: f"{r['starting_score']:.0f}→{r['latest_score']:.0f} ({r['score_change']:+.0f})"
            if pd.notna(r.get("starting_score")) and pd.notna(r.get("latest_score")) else "—", axis=1
        )
        matrix["Test"] = filtered_comp.apply(
            lambda r: "SAT" if pd.notna(r.get("starting_score")) and r["starting_score"] > 100 else ("ACT" if pd.notna(r.get("starting_score")) else "—"), axis=1
        )
        matrix["Target"] = filtered_comp.apply(
            lambda r: f"{r['target_score']:.0f}" if pd.notna(r.get("target_score")) else "—", axis=1
        )
        matrix["To Target"] = filtered_comp.apply(
            lambda r: (
                f"✅ +{abs(r['points_to_target']):.0f} ahead" if pd.notna(r.get("on_track")) and bool(r["on_track"])
                else f"❌ {r['points_to_target']:.0f} needed" if pd.notna(r.get("points_to_target"))
                else "—"
            ), axis=1
        )
        matrix = matrix.rename(columns={"student": "Student", "tutor": "Tutor", "advisor": "Advisor"})

        # Color tag and notes — always last
        color_options = ["", "🔴", "🟠", "🟡", "🟢", "🔵", "🟣", "⚫", "🟤"]
        matrix["Sess Gap"] = filtered_comp.apply(
            lambda r: f"⚠️ {int(r['max_session_gap'])}d" if pd.notna(r.get("session_gap")) and bool(r.get("session_gap")) else (
                f"✅ {int(r['max_session_gap'])}d" if pd.notna(r.get("max_session_gap")) else "—"
            ), axis=1
        )
        matrix["Tag"] = filtered_comp["color"]
        matrix["Notes"] = filtered_comp["note"]

        # Editable notes in table
        disabled_cols = [c for c in matrix.columns if c not in ["Notes", "Tag"]]
        # Reorder: Tag first, Notes last
        col_order = ["Tag"] + [c for c in matrix.columns if c not in ["Tag", "Notes"]] + ["Notes"]
        matrix = matrix[col_order]

        col_config = {
            "Student": st.column_config.TextColumn("Student", width=140),
            "Tutor": st.column_config.TextColumn("Tutor", width=140),
            "Advisor": st.column_config.TextColumn("Advisor", width=130),
            "Pkg ≥20hr": st.column_config.TextColumn("Pkg ≥20hr", width=90),
            "Hrs Used": st.column_config.TextColumn("Hrs Used", width=100),
            "Pace": st.column_config.TextColumn("Pace", width=110),
            "Baseline": st.column_config.TextColumn("Baseline", width=85),
            "Attend": st.column_config.TextColumn("Attend", width=90),
            "Tests": st.column_config.TextColumn("Tests", width=75),
            "Gaps ≥7d": st.column_config.TextColumn("Gaps ≥7d", width=90),
            "Final ≤14d": st.column_config.TextColumn("Final ≤14d", width=70),
            "Score": st.column_config.TextColumn("Score", width=130),
            "Test": st.column_config.TextColumn("Test", width=50),
            "Target": st.column_config.TextColumn("Target", width=60),
            "To Target": st.column_config.TextColumn("To Target", width=130),
            "Tag": st.column_config.SelectboxColumn(
                    "Tag",
                    options=["", "🔴", "🟠", "🟡", "🟢", "🔵", "🟣"],
                    width=60,
                ),
                "Notes": st.column_config.TextColumn("Notes", width="large"),
        }
        # Color map for row shading
        color_bg_map = {
            "🔴": "rgba(239,68,68,0.12)",
            "🟠": "rgba(249,115,22,0.12)",
            "🟡": "rgba(234,179,8,0.12)",
            "🟢": "rgba(34,197,94,0.12)",
            "🔵": "rgba(59,130,246,0.12)",
            "🟣": "rgba(168,85,247,0.12)",
                "⚫": "rgba(0,0,0,0.08)",
                "🟤": "rgba(180,83,9,0.12)",
        }

        def shade_rows(row):
            tag = row.get("Tag", "")
            bg = color_bg_map.get(str(tag).strip(), "")
            if bg:
                return [f"background-color: {bg}"] * len(row)
            return [""] * len(row)

        styled = matrix.style.apply(shade_rows, axis=1)
        st.dataframe(
            styled,
            hide_index=True,
            use_container_width=True,
            height=min(700, len(matrix) * 38 + 60),
            column_config={
                "Tag": st.column_config.TextColumn("Tag", width=50),
                "Student": st.column_config.TextColumn("Student", width=140),
                "Tutor": st.column_config.TextColumn("Tutor", width=150),
                "Advisor": st.column_config.TextColumn("Advisor", width=130),
                "Faculty Leader": st.column_config.TextColumn("Faculty Leader", width=140),
                "Pkg ≥20hr": st.column_config.TextColumn("Pkg ≥20hr", width=95),
                "Hrs Used": st.column_config.TextColumn("Hrs Used", width=105),
                "Pace": st.column_config.TextColumn("Pace", width=120),
                "Baseline": st.column_config.TextColumn("Baseline", width=90),
                "Attend": st.column_config.TextColumn("Attend", width=95),
                "Tests": st.column_config.TextColumn("Tests", width=80),
                "Gaps ≥7d": st.column_config.TextColumn("Gaps ≥7d", width=95),
                "Final ≤14d": st.column_config.TextColumn("Final ≤14d", width=75),
                "Score": st.column_config.TextColumn("Score", width=140),
                "Test": st.column_config.TextColumn("Test", width=55),
                "Target": st.column_config.TextColumn("Target", width=65),
                "To Target": st.column_config.TextColumn("To Target", width=140),
                "Notes": st.column_config.TextColumn("Notes", width="large"),
            },
        )

        # Download options
        dl1, dl2 = st.columns(2)
        with dl1:
            csv_data = matrix.to_csv(index=False).encode("utf-8")
            st.download_button(
                "📥 Download as CSV",
                data=csv_data,
                file_name=f"score_guarantee_checklist_{date.today().isoformat()}.csv",
                mime="text/csv",
                key="sg_csv_download",
            )
        with dl2:
            # Build a clean Excel export
            import io as _io
            excel_buffer = _io.BytesIO()
            with pd.ExcelWriter(excel_buffer, engine="openpyxl") as writer:
                matrix.to_excel(writer, index=False, sheet_name="Checklist")
                # Auto-size columns
                ws = writer.sheets["Checklist"]
                for col_idx, col_name in enumerate(matrix.columns, 1):
                    max_len = max(
                        len(str(col_name)),
                        matrix[col_name].astype(str).str.len().max() if len(matrix) > 0 else 0
                    )
                    ws.column_dimensions[ws.cell(row=1, column=col_idx).column_letter].width = min(max_len + 3, 40)
            excel_buffer.seek(0)
            st.download_button(
                "📥 Download as Excel",
                data=excel_buffer,
                file_name=f"score_guarantee_checklist_{date.today().isoformat()}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="sg_xlsx_download",
            )

        # Editable tag and notes in expander
        with st.expander("✏️ Edit Tags, Test Type & Notes", expanded=False):
            legend = st.session_state.sg_legend
            tag_emojis = ["🔴", "🟠", "🟡", "🟢", "🔵", "🟣", "⚫", "🟤"]
            tag_to_labeled = {"": "— None —"}
            for e in tag_emojis:
                tag_to_labeled[e] = f"{e} {legend[e]}" if legend.get(e) else e
            labeled_to_tag = {v: k for k, v in tag_to_labeled.items()}
            labeled_options = list(tag_to_labeled.values())

            eq_students = sorted(sg["student"].dropna().unique())
            default_idx = 0
            if "sg_active_student" in st.session_state and st.session_state["sg_active_student"] in eq_students:
                default_idx = eq_students.index(st.session_state["sg_active_student"])
            eq_selected = st.selectbox("Select student:", eq_students, index=default_idx, key="eq_student_select")

            if eq_selected:
                eq_row = sg[sg["student"] == eq_selected].iloc[0]
                eq_sid = eq_row["student_id"]
                sid_str = str(eq_sid).split(".")[0]

                # Load existing values
                eq_existing_note = ""
                eq_existing_color = ""
                eq_existing_test = ""
                eq_updated = ""
                eq_notes_df = st.session_state.sg_notes
                if not eq_notes_df.empty:
                    mask = eq_notes_df["student_id"].astype(str).str.split(".").str[0] == sid_str
                    if mask.any():
                        row_data = eq_notes_df.loc[mask].iloc[0]
                        eq_existing_note = str(row_data.get("note", ""))
                        if eq_existing_note == "nan":
                            eq_existing_note = ""
                        eq_existing_color = str(row_data.get("color", ""))
                        if eq_existing_color == "nan":
                            eq_existing_color = ""
                        eq_existing_test = str(row_data.get("test_type_override", ""))
                        if eq_existing_test == "nan":
                            eq_existing_test = ""
                        eq_updated = str(row_data.get("updated_at", ""))
                        if eq_updated == "nan":
                            eq_updated = ""

                # Show current student info
                st.markdown(f"**Tutor:** {eq_row.get('tutor', '—')} | **Advisor:** {eq_row.get('advisor', '—')} | **FL:** {eq_row.get('faculty_leader', '—')}")
                if eq_updated:
                    st.markdown(f"<p style='color:#94a3b8; font-size:0.75rem;'>Last updated: {eq_updated}</p>", unsafe_allow_html=True)

                ec1, ec2 = st.columns(2)
                with ec1:
                    current_tag_label = tag_to_labeled.get(eq_existing_color, "— None —")
                    tag_idx = labeled_options.index(current_tag_label) if current_tag_label in labeled_options else 0
                    eq_tag = st.selectbox("Tag:", labeled_options, index=tag_idx, key=f"eq_tag_{sid_str}")
                with ec2:
                    test_options = ["Auto", "SAT", "ACT"]
                    current_test = eq_existing_test if eq_existing_test in ["SAT", "ACT"] else "Auto"
                    eq_test = st.selectbox("Test Type:", test_options, index=test_options.index(current_test), key=f"eq_test_{sid_str}")

                eq_note = st.text_area("Notes:", value=eq_existing_note, height=150, key=f"eq_note_{eq_sid}")

                if st.button("💾 Save Changes", key=f"eq_save_{eq_sid}", use_container_width=True):
                    now_str = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M")
                    save_color = labeled_to_tag.get(eq_tag, "")
                    save_test = "" if eq_test == "Auto" else eq_test

                    save_notes = st.session_state.sg_notes.copy()
                    for col in ["note", "color", "updated_at"]:
                        if col in save_notes.columns:
                            save_notes[col] = save_notes[col].astype(str).replace("nan", "")
                    if "test_type_override" not in save_notes.columns:
                        save_notes["test_type_override"] = ""
                    save_notes["test_type_override"] = save_notes["test_type_override"].astype(str).replace("nan", "")
                    save_notes["student_id"] = save_notes["student_id"].astype(str)

                    m = save_notes["student_id"].str.split(".").str[0] == sid_str
                    if m.any():
                        save_notes.loc[m, "note"] = eq_note
                        save_notes.loc[m, "color"] = save_color
                        save_notes.loc[m, "test_type_override"] = save_test
                        save_notes.loc[m, "updated_at"] = now_str
                    else:
                        new_r = pd.DataFrame([{"student_id": sid_str, "note": eq_note, "color": save_color, "test_type_override": save_test, "updated_at": now_str}])
                        save_notes = pd.concat([save_notes, new_r], ignore_index=True)

                    if save_sg_notes(save_notes):
                        st.session_state.sg_notes = save_notes
                        st.rerun()

            # Set edited_matrix to None so the old change detection doesn't run
            edited_matrix = None

                # ── Color Legend ───────────────────────────────────────────────────
        legend = st.session_state.sg_legend
        with st.expander("🎨 Color Legend — click to edit", expanded=False):
            st.markdown("<p style='color:#64748b; font-size:0.82rem;'>Define what each color tag means:</p>", unsafe_allow_html=True)
            st.markdown("<p style='color:#94a3b8; font-size:0.75rem; font-style:italic;'>💡 Students tagged with labels named exactly \"Not Score Guarantee\", \"Completed\", or \"Refunded\" will be automatically hidden from all tables and alerts. Use the checkbox above the table to show them again.</p>", unsafe_allow_html=True)
            legend_colors = ["🔴", "🟠", "🟡", "🟢", "🔵", "🟣", "⚫", "🟤"]
            new_legend = {}
            lc1, lc2 = st.columns(2)
            for idx, color in enumerate(legend_colors):
                col = lc1 if idx < 4 else lc2
                with col:
                    label = st.text_input(
                        f"{color}",
                        value=legend.get(color, ""),
                        key=f"legend_{color}",
                        placeholder="Enter label...",
                    )
                    new_legend[color] = label

            if st.button("💾 Save Legend", key="save_legend"):
                if save_sg_legend(new_legend):
                    st.session_state.sg_legend = new_legend
                    st.rerun()

        # Show active legend inline
        active_legend = {k: v for k, v in st.session_state.sg_legend.items() if v}
        if active_legend:
            legend_str = " &nbsp;&nbsp;|&nbsp;&nbsp; ".join(
                [f"{k} {v}" for k, v in active_legend.items()]
            )
            st.markdown(
                f"<p style='font-size:0.78rem; color:#64748b; margin-bottom:8px;'>{legend_str}</p>",
                unsafe_allow_html=True,
            )

        # Detect and save note/tag changes from expander
        if edited_matrix is not None and False:  # disabled — handled in expander
            changed = False
            notes_df = st.session_state.sg_notes.copy()
            if "color" not in notes_df.columns:
                notes_df["color"] = ""
            # Ensure all columns are string type to avoid dtype errors
            for col in ["note", "color", "updated_at"]:
                if col in notes_df.columns:
                    notes_df[col] = notes_df[col].astype(str).replace("nan", "")
            notes_df["student_id"] = notes_df["student_id"].astype(str)

            if "test_type_override" not in notes_df.columns:
                notes_df["test_type_override"] = ""
            for col in ["test_type_override"]:
                if col in notes_df.columns:
                    notes_df[col] = notes_df[col].astype(str).replace("nan", "")

            for i in range(len(edited_matrix)):
                new_note = str(edited_matrix.iloc[i].get("Notes", "") or "")
                new_color_raw = str(edited_matrix.iloc[i].get("Tag", "") or "")
                new_color = new_color_raw.split(" ")[0].strip() if new_color_raw else ""
                new_test_type = str(edited_matrix.iloc[i].get("Test Type", "") or "")
                if new_test_type == "Auto":
                    new_test_type = ""
                old_note = str(filtered_comp.iloc[i].get("note", "") or "")
                old_color = str(filtered_comp.iloc[i].get("color", "") or "")
                old_test_type = str(filtered_comp.iloc[i].get("test_type_override", "") or "")

                if new_note != old_note or new_color != old_color or new_test_type != old_test_type:
                    sid = str(student_ids_ordered[i])
                    now_str = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M")
                    mask = notes_df["student_id"] == sid
                    if mask.any():
                        notes_df.loc[mask, "note"] = new_note
                        notes_df.loc[mask, "color"] = new_color
                        notes_df.loc[mask, "test_type_override"] = new_test_type
                        notes_df.loc[mask, "updated_at"] = now_str
                    else:
                        new_row = pd.DataFrame([{"student_id": sid, "note": new_note, "color": new_color, "test_type_override": new_test_type, "updated_at": now_str}])
                        notes_df = pd.concat([notes_df, new_row], ignore_index=True)
                    changed = True
            if changed:
                if save_sg_notes(notes_df):
                    st.session_state.sg_notes = notes_df
                    st.rerun()

        st.markdown("<div id='student-detail-anchor'></div>", unsafe_allow_html=True)
        # ── Student Detail Drilldown ──────────────────────────────────────
        st.markdown("")
        st.markdown(
            "<p class='section-label'>Drilldown</p>"
            "<p class='section-title'>Student Detail</p>",
            unsafe_allow_html=True,
        )

        student_names = sorted(sg["student"].dropna().unique())
        detail_default_idx = 0
        if "sg_active_student" in st.session_state and st.session_state["sg_active_student"] in student_names:
            detail_default_idx = student_names.index(st.session_state["sg_active_student"])
        selected_student = st.selectbox("Select a student:", student_names, index=detail_default_idx, key="sg_student_select")

        if selected_student:
            stu_row = sg[sg["student"] == selected_student].iloc[0]
            sid = stu_row["student_id"]

            # Package info
            st.markdown("---")
            st.markdown(f"### {selected_student}")
            p1, p2, p3, p4 = st.columns(4)
            p1.metric("Tutor", stu_row.get("tutor", "—") or "—")
            p2.metric("Advisor", stu_row.get("advisor", "—") or "—")
            st.markdown(f"**Faculty Leader:** {stu_row.get('faculty_leader', '—') or '—'}")
            p3.metric("Package Hours", f"{stu_row['package_hours']:.0f}" if pd.notna(stu_row.get("package_hours")) else "—")
            p4.metric("Won Date", stu_row["won_at"].strftime("%Y-%m-%d") if pd.notna(stu_row.get("won_at")) else "—")

            p5, p6, p7, p8 = st.columns(4)
            p5.metric("Completed Hours", f"{stu_row['completed_test_prep_hours']:.1f}" if pd.notna(stu_row.get("completed_test_prep_hours")) else "—")
            p6.metric("Starting Score", f"{stu_row['starting_score']:.0f}" if pd.notna(stu_row.get("starting_score")) else "—")
            p7.metric("Latest Score", f"{stu_row['latest_test_score']:.0f}" if pd.notna(stu_row.get("latest_test_score")) else "—")
            score_ch = stu_row.get("score_change")
            p8.metric("Score Change", f"{score_ch:+.0f}" if pd.notna(score_ch) else "—")

            # Target score info
            test_type = stu_row.get("test_type", "—")
            target_score = stu_row.get("target_score")
            points_to = stu_row.get("points_to_target")
            if pd.notna(target_score):
                t1, t2, t3 = st.columns(3)
                t1.metric("Test Type", test_type or "—")
                t2.metric("Target Score", f"{target_score:.0f}")
                if pd.notna(points_to):
                    if points_to <= 0:
                        t3.metric("Status", f"✅ Target reached (+{abs(points_to):.0f} ahead)")
                    else:
                        t3.metric("Status", f"❌ {points_to:.0f} points needed")

            # Compliance summary for this student
            stu_comp = comp_df[comp_df["student_id"] == sid]
            if len(stu_comp) > 0:
                sc = stu_comp.iloc[0]
                st.markdown("")
                st.markdown("**Compliance Status:**")

                def check_line(label, passed, detail=""):
                    icon = "✅" if pd.notna(passed) and bool(passed) else ("❌" if pd.notna(passed) and not bool(passed) else "⚪")
                    return f"{icon} **{label}** {detail}"

                lines = []
                lines.append(check_line("Package ≥ 20 hours", sc.get("1_pkg_20hrs"),
                    f"— {sc.get('package_hours', 0):.0f} hours" if pd.notna(sc.get("package_hours")) else ""))
                lines.append(check_line("Used 20+ hours of test prep tutoring", sc.get("2_hours_used"),
                    f"— {sc.get('completed_hours', 0):.1f} / 20 hrs" if pd.notna(sc.get("completed_hours")) else ""))
                lines.append(check_line("Pace 1-2 hrs/week", sc.get("3_pace_ok"),
                    f"— {sc.get('3_pace_val', 0):.1f} hrs/wk" if pd.notna(sc.get("3_pace_val")) else ""))
                lines.append(check_line("Baseline score before first session", sc.get("4_baseline")))
                lines.append(check_line("100% session attendance", sc.get("5_attendance"),
                    f"— {int(sc.get('5_attended', 0))}/{int(sc.get('5_total', 0))} attended" if pd.notna(sc.get("5_attended")) else ""))
                lines.append("⚪ **Homework completion** — not yet tracked")
                lines.append(check_line("Minimum 4 practice tests", sc.get("7_practice_tests"),
                    f"— {int(sc.get('7_taken', 0))}/{int(sc.get('7_required', 0))} taken" if pd.notna(sc.get("7_taken")) else ""))
                lines.append(check_line("≥ 1 week between practice tests", sc.get("8_week_gaps"),
                    f"— min gap {int(sc.get('8_min_gap'))} days" if pd.notna(sc.get("8_min_gap")) else ""))
                lines.append(check_line("Official exam within 14 days of last session", sc.get("9_final_14days"),
                    f"— {int(sc.get('9_days_after'))} days after last session" if pd.notna(sc.get("9_days_after")) else "— no official exam taken yet"))

                for line in lines:
                    st.markdown(line)

            # Sessions table
            st.markdown("")
            st.markdown("**Sessions:**")
            if not df_sg_sessions.empty and sid in df_sg_sessions["student_id"].values:
                stu_sess = df_sg_sessions[df_sg_sessions["student_id"] == sid].copy()
                stu_sess["starts_at"] = pd.to_datetime(stu_sess["starts_at"], errors="coerce")
                stu_sess = stu_sess.sort_values("starts_at")
                sess_display = stu_sess[["starts_at", "session_hours", "attended", "tutor"]].copy()
                sess_display["starts_at"] = sess_display["starts_at"].dt.strftime("%Y-%m-%d %I:%M %p")
                sess_display["attended"] = sess_display["attended"].apply(lambda x: "✅" if x == 1 else "❌")
                sess_display["session_hours"] = sess_display["session_hours"].round(2)
                sess_display = sess_display.rename(columns={
                    "starts_at": "Date", "session_hours": "Hours",
                    "attended": "Attended", "tutor": "Tutor",
                })
                st.dataframe(sess_display, hide_index=True, use_container_width=True)

                st.markdown(f"**Total sessions:** {len(stu_sess)} | "
                            f"**Total hours:** {stu_sess['session_hours'].sum():.1f} | "
                            f"**Attended:** {int(stu_sess['attended'].sum())}/{len(stu_sess)}")
            else:
                st.info("No session data available for this student.")

            # Notes
            st.markdown("")
            st.markdown("**Notes:**")
            existing_note = ""
            notes_df = st.session_state.sg_notes
            if not notes_df.empty and sid in notes_df["student_id"].values:
                existing_note = notes_df[notes_df["student_id"] == sid]["note"].iloc[0]
                if pd.isna(existing_note):
                    existing_note = ""
                last_updated = notes_df[notes_df["student_id"] == sid]["updated_at"].iloc[0]
                if pd.notna(last_updated):
                    st.markdown(f"<p style='color:#94a3b8; font-size:0.75rem;'>Last updated: {last_updated}</p>", unsafe_allow_html=True)

            note_input = st.text_area("Add or edit notes for this student (use new lines for each entry):", value=existing_note, height=150, key=f"note_{sid}")

            if st.button("💾 Save Note", key=f"save_note_{sid}"):
                now_str = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M")
                notes_df = st.session_state.sg_notes.copy()
                for col in ["note", "color", "updated_at"]:
                    if col in notes_df.columns:
                        notes_df[col] = notes_df[col].astype(str).replace("nan", "")
                notes_df["student_id"] = notes_df["student_id"].astype(str)
                sid_str = str(sid)
                mask = notes_df["student_id"] == sid_str
                if mask.any():
                    notes_df.loc[mask, "note"] = note_input
                    notes_df.loc[mask, "updated_at"] = now_str
                else:
                    new_row = pd.DataFrame([{"student_id": sid_str, "note": note_input, "updated_at": now_str}])
                    notes_df = pd.concat([notes_df, new_row], ignore_index=True)
                if save_sg_notes(notes_df):
                    st.session_state.sg_notes = notes_df
                    st.rerun()
                else:
                    st.error("Failed to save note. Check GitHub credentials.")

            # Exams table
            st.markdown("")
            st.markdown("**Exams:**")
            if not df_sg_exams.empty and sid in df_sg_exams["student_id"].values:
                stu_exams = df_sg_exams[df_sg_exams["student_id"] == sid].copy()
                stu_exams["exam_date"] = pd.to_datetime(stu_exams["exam_date"], errors="coerce")
                stu_exams = stu_exams.sort_values("exam_date")
                stu_exams["score"] = pd.to_numeric(stu_exams["score"], errors="coerce")

                # Calculate gaps between exams
                stu_exams["days_since_prev"] = stu_exams["exam_date"].diff().dt.days

                exam_display = stu_exams[["exam_date", "exam_type", "exam_code", "score",
                                          "before_or_after_tutoring", "source", "days_since_prev"]].copy()
                exam_display["exam_date"] = exam_display["exam_date"].dt.strftime("%Y-%m-%d")
                exam_display["score"] = exam_display["score"].apply(lambda x: f"{x:.0f}" if pd.notna(x) else "—")
                exam_display["days_since_prev"] = exam_display["days_since_prev"].apply(
                    lambda x: f"{int(x)}d" if pd.notna(x) else "—")
                exam_display = exam_display.rename(columns={
                    "exam_date": "Date", "exam_type": "Type", "exam_code": "Code",
                    "score": "Score", "before_or_after_tutoring": "Timing",
                    "source": "Source", "days_since_prev": "Gap",
                })
                st.dataframe(exam_display, hide_index=True, use_container_width=True)
            else:
                st.info("No exam data available for this student.")

        # ── Score improvement chart ───────────────────────────────────────
        has_scores = filtered_comp.dropna(subset=["starting_score", "latest_score"])
        if len(has_scores) > 0:
            st.markdown("")
            st.markdown(
                "<p class='section-label'>Results</p>"
                "<p class='section-title'>Score Changes by Student</p>",
                unsafe_allow_html=True,
            )

            # Determine test type per student
            has_scores["_test"] = has_scores.apply(
                lambda r: "SAT" if pd.notna(r.get("starting_score")) and r["starting_score"] > 100 else "ACT", axis=1
            )

            sat_scores = has_scores[has_scores["_test"] == "SAT"]
            act_scores = has_scores[has_scores["_test"] == "ACT"]

            sc_col1, sc_col2 = st.columns(2)

            with sc_col1:
                if len(sat_scores) > 0:
                    plot_sat = sat_scores[["student", "score_change"]].sort_values("score_change", ascending=True)
                    colors_sat = ["#10b981" if x >= 0 else "#ef4444" for x in plot_sat["score_change"]]
                    fig_sat = go.Figure()
                    fig_sat.add_trace(go.Bar(
                        y=plot_sat["student"], x=plot_sat["score_change"], orientation="h",
                        marker_color=colors_sat,
                        text=plot_sat["score_change"].apply(lambda x: f"{x:+.0f}"),
                        textposition="outside", textfont=dict(size=11),
                    ))
                    fig_sat.update_layout(
                        title=dict(text="SAT", font=dict(size=14, color="#1e293b"), x=0.5, xanchor="center"),
                        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                        font=dict(family="DM Sans", color="#475569"),
                        margin=dict(l=10, r=40, t=40, b=40),
                        xaxis=dict(gridcolor="rgba(226,232,240,0.8)", title="Score Change"),
                        yaxis=dict(automargin=True),
                        height=max(300, len(plot_sat) * 30 + 80),
                        showlegend=False,
                    )
                    st.plotly_chart(fig_sat, use_container_width=True)
                else:
                    st.info("No SAT students with score changes.")

            with sc_col2:
                if len(act_scores) > 0:
                    plot_act = act_scores[["student", "score_change"]].sort_values("score_change", ascending=True)
                    colors_act = ["#10b981" if x >= 0 else "#ef4444" for x in plot_act["score_change"]]
                    fig_act = go.Figure()
                    fig_act.add_trace(go.Bar(
                        y=plot_act["student"], x=plot_act["score_change"], orientation="h",
                        marker_color=colors_act,
                        text=plot_act["score_change"].apply(lambda x: f"{x:+.0f}"),
                        textposition="outside", textfont=dict(size=11),
                    ))
                    fig_act.update_layout(
                        title=dict(text="ACT", font=dict(size=14, color="#1e293b"), x=0.5, xanchor="center"),
                        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                        font=dict(family="DM Sans", color="#475569"),
                        margin=dict(l=10, r=40, t=40, b=40),
                        xaxis=dict(gridcolor="rgba(226,232,240,0.8)", title="Score Change"),
                        yaxis=dict(automargin=True),
                        height=max(300, len(plot_act) * 30 + 80),
                        showlegend=False,
                    )
                    st.plotly_chart(fig_act, use_container_width=True)
                else:
                    st.info("No ACT students with score changes.")

        # Fetched at
        if "fetched_at" in df_sg.columns:
            st.markdown(
                f"<p style='color:#94a3b8; font-size:0.75rem; margin-top:16px;'>"
                f"Data last synced: {df_sg['fetched_at'].iloc[0]}</p>",
                unsafe_allow_html=True,
            )


    # ══════════════════════════════════════════════════════════════════════════
    # PAGE — FULL ROSTER
    # ══════════════════════════════════════════════════════════════════════════
