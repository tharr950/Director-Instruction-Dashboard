"""
Jamie — Instruction Leader Dashboard
─────────────────────────────────────
Team-by-team overview: headcount, tiers, tenure, BUC/PT composition, meetings.
"""

import streamlit as st
import pandas as pd
import numpy as np
import psycopg2
import plotly.graph_objects as go
from datetime import date
import os
import requests
import base64


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

    @st.cache_data(ttl=3600)
    def load_team_data():
        query = """
        SELECT DISTINCT
            e1.id AS tutor_id,
            t_users.first_name||' '||t_users.last_name AS tutor,
            m_users.first_name||' '||m_users.last_name AS manager,
            date(e1.hire_date) AS hire_date,
            tiers.name AS tier,
            e1.delivery_target,
            CASE WHEN e1.delivery_target < 30 THEN 'Adjunct' ELSE 'Professional' END AS tutor_type,
            CASE WHEN e1.tier_id = 1 THEN TRUE ELSE FALSE END AS buc_only,
            CASE WHEN e1.tier_id > 1 AND bp.brand_id = 42 THEN TRUE ELSE FALSE END AS buc_and_pt,
            CASE WHEN e1.tier_id > 1 AND bp.brand_id IS NULL THEN TRUE ELSE FALSE END AS pt_only
        FROM dw.employees e1
            JOIN dw.team_members ON team_members.member_id = e1.id
            JOIN dw.teams ON teams.id = team_members.team_id
            JOIN dw.users t_users ON e1.user_id = t_users.id
            JOIN dw.employees e2 ON e2.id = teams.manager_id
            JOIN dw.users m_users ON e2.user_id = m_users.id
            JOIN dw.tiers ON e1.tier_id = tiers.id
            LEFT JOIN orbit_stitch.brand_permissions bp
                ON (bp.user_id = t_users.id AND bp.brand_id = 42)
        WHERE e1.type = 'Tutor' AND e1.end_date IS NULL
            AND e1.tier_id IS NOT NULL AND t_users.title = 'Tutor'
        ORDER BY 1
        """
        conn = get_redshift_connection()
        df = pd.read_sql(query, conn)
        today = pd.Timestamp(date.today())
        df["hire_date"] = pd.to_datetime(df["hire_date"])
        df["tenure_days"] = (today - df["hire_date"]).dt.days
        df["tenure_years"] = (df["tenure_days"] / 365.25).round(1)
        df["brand_composition"] = np.where(
            df["buc_only"], "BUC Only",
            np.where(df["buc_and_pt"], "BUC & PT", "PT Only")
        )
        return df

    @st.cache_data(ttl=3600)
    @st.cache_data(ttl=3600)
    def load_meeting_data(lookback_months=24):
        today = date.today()
        day_end = today.strftime("%Y-%m-%d")
        day_start = (today - pd.DateOffset(months=lookback_months)).strftime("%Y-%m-%d")
        query = f"""
        WITH time_period AS (
          SELECT '{day_start}'::date AS day_start, '{day_end}'::date AS day_end
        ),
        cte_group_meetings AS (
            SELECT e_tutor.id as tutor_id,
                   count(distinct s.id) as attended_meetings
            FROM dw.courses c
                JOIN dw.sessions s ON s.course_id = c.id
                JOIN dw.attendances a ON s.id = a.session_id
                JOIN dw.enrollments e ON e.id = a.enrollment_id
                JOIN dw.employees e_tutor ON e.enrollee_id = e_tutor.id
                LEFT JOIN dw.users tutor ON e_tutor.user_id = tutor.id
            WHERE c.brand_id = 24 AND a.attended IS TRUE
                AND s.starts_at BETWEEN (SELECT day_start FROM time_period)
                    AND (SELECT day_end FROM time_period)
            GROUP BY tutor_id
        ),
        cte_1on1_meetings AS (
            SELECT s.supervisor_id as fl_id, e_tutor.id as tutor_id,
                   count(distinct s.id) as attended_meetings,
                   sum(s.duration)/60.0 as meeting_hours,
                   max(s.starts_at) as last_attended_1on1
            FROM dw.courses c
                JOIN dw.sessions s ON s.course_id = c.id
                JOIN dw.attendances a ON s.id = a.session_id
                JOIN dw.enrollments e ON e.id = a.enrollment_id
                JOIN dw.employees e_tutor ON e.enrollee_id = e_tutor.id
            WHERE c.brand_id = 25
                AND s.starts_at BETWEEN (SELECT day_start FROM time_period)
                    AND (SELECT day_end FROM time_period)
                AND a.attended IS TRUE
            GROUP BY s.supervisor_id, e_tutor.id
        )
        SELECT
            fl.first_name||' '||fl.last_name as faculty_leader,
            tutor.first_name||' '||tutor.last_name as tutor,
            CASE WHEN e_tutor.delivery_target < 30 THEN 'Adjunct' ELSE 'Professional' END AS tutor_type,
            e_tutor.hire_date,
            cte_1on1_meetings.attended_meetings AS attended_1on1_meetings,
            cte_1on1_meetings.meeting_hours AS "1on1_meeting_hours",
            cte_1on1_meetings.last_attended_1on1,
            cte_group_meetings.attended_meetings AS attended_group_meetings,
            next_mtg.next_1on1
        FROM dw.employees e_tutor
            LEFT JOIN dw.users tutor ON e_tutor.user_id = tutor.id
            JOIN dw.team_members ON e_tutor.id = team_members.member_id
            JOIN dw.teams ON team_members.team_id = teams.id
            JOIN dw.employees e_fl ON e_fl.id = teams.manager_id
            JOIN dw.users fl ON e_fl.user_id = fl.id
            LEFT JOIN cte_1on1_meetings
                ON (cte_1on1_meetings.fl_id = e_fl.id
                AND cte_1on1_meetings.tutor_id = e_tutor.id)
            LEFT JOIN cte_group_meetings
                ON cte_group_meetings.tutor_id = e_tutor.id
        LEFT JOIN (
            SELECT s2.supervisor_id AS fl_id, e_t2.id AS tutor_id,
                   MIN(s2.starts_at) AS next_1on1
            FROM dw.courses c2
                JOIN dw.sessions s2 ON s2.course_id = c2.id
                JOIN dw.attendances a2 ON a2.session_id = s2.id
                JOIN dw.enrollments e2 ON e2.id = a2.enrollment_id
                JOIN dw.employees e_t2 ON e2.enrollee_id = e_t2.id
            WHERE c2.brand_id = 25
                AND s2.starts_at > GETDATE()
            GROUP BY s2.supervisor_id, e_t2.id
        ) next_mtg ON (next_mtg.fl_id = e_fl.id AND next_mtg.tutor_id = e_tutor.id)
        WHERE e_tutor.end_date IS NULL
            AND e_tutor.delivery_target > 0
            AND e_tutor.type = 'Tutor'
            AND e_tutor.tier_id >= 1
            AND tutor.title = 'Tutor'
        """
        conn = get_redshift_connection()
        df = pd.read_sql(query, conn)
        df["hire_date"] = pd.to_datetime(df["hire_date"])
        df["last_attended_1on1"] = pd.to_datetime(df["last_attended_1on1"])
        df["1on1_meeting_hours"] = pd.to_numeric(df["1on1_meeting_hours"], errors="coerce").round(1)
        df["attended_1on1_meetings"] = df["attended_1on1_meetings"].fillna(0).astype(int)
        df["attended_group_meetings"] = df["attended_group_meetings"].fillna(0).astype(int)
        df["next_1on1"] = pd.to_datetime(df["next_1on1"], errors="coerce")
        df["days_since_last_1on1"] = np.nan
        mask = df["last_attended_1on1"].notna()
        df.loc[mask, "days_since_last_1on1"] = (pd.Timestamp.now() - df.loc[mask, "last_attended_1on1"]).dt.days
        return df


    @st.cache_data(ttl=3600)
    def load_restricted_data():
        today = date.today()
        lookback_start = (today - pd.DateOffset(years=1)).strftime("%Y-%m-%d")
        query = f"""
        WITH cte_employee_with_histories AS (
            SELECT
                item_id AS employee_id,
                CASE WHEN histories.updated_by_type = 'Employee'
                     THEN histories.updated_by_id ELSE NULL END AS updated_by_employee_id,
                CASE WHEN histories.value = 'Restricted' THEN True ELSE False END AS restricted,
                histories.created_at AS status_starts_at
            FROM dw.histories
            JOIN dw.employees ON histories.item_id = employees.id
            WHERE employees.end_date IS NULL
                AND item_type = 'Employee' AND attr = 'tutor_type'
        ),
        cte_employee_wo_history AS (
            SELECT id AS employee_id, -1 AS updated_by_employee_id,
                CASE WHEN employees.tutor_type = 'Restricted' THEN True ELSE False END AS restricted,
                employees.created_at AS status_starts_at
            FROM dw.employees
            WHERE employees.end_date IS NULL
                AND id NOT IN (SELECT DISTINCT employee_id FROM cte_employee_with_histories)
        ),
        cte_all_histories AS (
            SELECT * FROM cte_employee_with_histories
            UNION
            SELECT * FROM cte_employee_wo_history
        ),
        cte_last_restricted AS (
            SELECT
                cte_all_histories.employee_id,
                cte_all_histories.updated_by_employee_id,
                CASE
                    WHEN cte_all_histories.employee_id = cte_all_histories.updated_by_employee_id THEN 'Tutor'
                    WHEN cte_all_histories.updated_by_employee_id = -1 THEN 'Never Changed'
                    ELSE 'Admin'
                END AS update_type,
                cte_all_histories.restricted,
                cte_all_histories.status_starts_at,
                CASE
                    WHEN LAG(status_starts_at,1) OVER (PARTITION BY employee_id ORDER BY status_starts_at DESC) IS NULL
                    THEN NULL
                    ELSE DATEADD(SECOND, -1, LAG(status_starts_at,1) OVER (PARTITION BY employee_id ORDER BY status_starts_at DESC))
                END AS status_ends_at,
                DATEDIFF(DAY, status_starts_at, status_ends_at) AS days_in_effect,
                CASE WHEN LAG(status_starts_at,1) OVER (PARTITION BY employee_id ORDER BY status_starts_at DESC) IS NULL
                    THEN 1 ELSE 0 END AS current_status_flag
            FROM cte_all_histories
            GROUP BY cte_all_histories.employee_id, cte_all_histories.updated_by_employee_id,
                     cte_all_histories.restricted, cte_all_histories.status_starts_at
        )
        SELECT
            cte_last_restricted.employee_id,
            users.first_name || ' ' || users.last_name AS employee_name,
            teams.name AS team,
            tiers.name AS tier,
            cte_last_restricted.updated_by_employee_id,
            updated_by_users.first_name || ' ' || updated_by_users.last_name AS updated_by_employee_name,
            cte_last_restricted.update_type,
            cte_last_restricted.restricted,
            cte_last_restricted.status_starts_at,
            cte_last_restricted.status_ends_at,
            cte_last_restricted.days_in_effect,
            cte_last_restricted.current_status_flag
        FROM cte_last_restricted
            JOIN dw.employees ON employees.id = cte_last_restricted.employee_id
            JOIN dw.users ON users.id = employees.user_id
            JOIN dw.tiers ON employees.tier_id = tiers.id
            LEFT JOIN dw.employees updated_by_employees
                ON updated_by_employees.id = cte_last_restricted.updated_by_employee_id
            LEFT JOIN dw.users updated_by_users
                ON updated_by_users.id = updated_by_employees.user_id
            JOIN dw.team_members ON team_members.member_id = employees.id
            JOIN dw.teams ON teams.id = team_members.team_id
        WHERE cte_last_restricted.restricted IS TRUE
            AND employees.end_date IS NULL
        GROUP BY cte_last_restricted.employee_id, employee_name, teams.name, tiers.name,
                 cte_last_restricted.updated_by_employee_id, updated_by_employee_name,
                 cte_last_restricted.update_type, cte_last_restricted.restricted,
                 cte_last_restricted.status_starts_at, cte_last_restricted.status_ends_at,
                 cte_last_restricted.days_in_effect, cte_last_restricted.current_status_flag
        HAVING status_starts_at >= '{lookback_start}'
            OR (status_ends_at IS NULL AND current_status_flag = 1)
            OR status_ends_at >= '{lookback_start}'
        """
        conn = get_redshift_connection()
        df = pd.read_sql(query, conn)
        df["status_starts_at"] = pd.to_datetime(df["status_starts_at"])
        df["status_ends_at"] = pd.to_datetime(df["status_ends_at"])
        df.loc[df["current_status_flag"] == 1, "days_in_effect"] = (
            pd.Timestamp.now() - df.loc[df["current_status_flag"] == 1, "status_starts_at"]
        ).dt.days
        return df

    @st.cache_data(ttl=3600)
    def load_dashboard_metrics():
        file = "Dashboard_Metrics.xlsx"
        if os.path.exists(file):
            # Read header row 0 to get date range from first column name
            raw = pd.read_excel(file, sheet_name="MonthlyMetricFullData", header=0, nrows=0)
            date_range_str = raw.columns[0] if len(raw.columns) > 0 else ""
            df = pd.read_excel(file, sheet_name="MonthlyMetricFullData", header=3)
            df.attrs["kpi_date_range"] = date_range_str
            return df
        return pd.DataFrame()

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
        df = pd.read_csv(io.StringIO(decoded))
        return df

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
        decoded = base64.b64decode(r.json()["content"]).decode("utf-8")
        return pd.read_csv(io.StringIO(decoded))

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
        decoded = base64.b64decode(r.json()["content"]).decode("utf-8")
        return pd.read_csv(io.StringIO(decoded))



    # ── Load data ─────────────────────────────────────────────────────────────
    try:
        df = load_team_data()
        df_meetings = load_meeting_data()
        df_restricted = load_restricted_data()
        df_kpi = load_dashboard_metrics()
        df_sg = load_score_guarantee()
        df_sg_sessions = load_sg_sessions()
        df_sg_exams = load_sg_exams()
    except Exception as e:
        st.error(f"Could not connect to Redshift: {e}")
        st.stop()

    managers = sorted(df["manager"].unique())

    # ── Sidebar ───────────────────────────────────────────────────────────────
    with st.sidebar:
        st.markdown(
            "<p style='font-family: Source Serif 4, serif; font-size:1.4rem; "
            "color:#1e293b; margin-bottom:0;'>Team Overview</p>"
            "<p style='color:#64748b; font-size:0.8rem; margin-top:0;'>Instruction Leader Dashboard</p>",
            unsafe_allow_html=True,
        )
        st.divider()

        excluded_managers = ["Katherine Marino", "Nikki Pencak"]
        excluded_teams = ["Team Marino", "Team Pencak"]
        selected_managers = [m for m in managers if m not in excluded_managers]

        st.divider()

        _page_options = [
            "👥 Team Counts",
            "📊 Tier Breakdown",
            "⏳ Tenure",
            "🔀 BUC / PT Split",
            "🚫 Restricted Status",
            "📅 Meetings",
            "📈 KPI Comparison",
            "🎯 Score Guarantee",
            "📋 Full Roster",
        ]
        page = st.radio("📂 Navigation", _page_options, index=0)

        st.divider()
        st.markdown(
            f"<p style='color:#64748b; font-size:0.75rem;'>"
            f"Data as of {date.today().strftime('%B %d, %Y')}<br>"
            f"Total active tutors: {len(df)}</p>",
            unsafe_allow_html=True,
        )

        if st.button("🔄 Refresh Data", use_container_width=True):
            st.cache_data.clear()
            st.rerun()

    # Filter
    filt = df[df["manager"].isin(selected_managers)].copy()
    df_restricted = df_restricted[~df_restricted["team"].isin(excluded_teams)]

        # ══════════════════════════════════════════════════════════════════════════
    # PAGE — TEAM COUNTS
    # ══════════════════════════════════════════════════════════════════════════
    if page == "👥 Team Counts":
        st.markdown(
            "<p class='section-label'>Team Size</p>"
            "<p class='section-title'>Headcount by Faculty Leader</p>",
            unsafe_allow_html=True,
        )

        team_summary = (
            filt.groupby("manager")
            .agg(
                total_tutors=("tutor_id", "count"),
                professional=("tutor_type", lambda x: (x == "Professional").sum()),
                adjunct=("tutor_type", lambda x: (x == "Adjunct").sum()),
                avg_delivery_target=("delivery_target", "mean"),
            )
            .reset_index()
            .rename(columns={"manager": "Faculty Leader"})
            .sort_values("total_tutors", ascending=False)
        )
        team_summary["avg_delivery_target"] = team_summary["avg_delivery_target"].round(1)

        col_chart, col_table = st.columns([1.3, 1])

        with col_chart:
            fig = go.Figure()
            fig.add_trace(go.Bar(
                x=team_summary["Faculty Leader"], y=team_summary["professional"],
                name="Professional", marker_color="#3b82f6",
                text=team_summary["professional"], textposition="inside",
                textfont=dict(size=13, color="white"),
            ))
            fig.add_trace(go.Bar(

                x=team_summary["Faculty Leader"], y=team_summary["adjunct"],
                name="Adjunct", marker_color="#94a3b8",
                text=team_summary["adjunct"], textposition="inside",
                textfont=dict(size=13, color="white"),
            ))
            fig.update_layout(
                barmode="stack", plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                font=dict(family="DM Sans", color="#475569"),
                legend=dict(orientation="h", y=1.08, x=0.5, xanchor="center", font=dict(size=12)),
                margin=dict(l=40, r=20, t=40, b=60),
                xaxis=dict(tickangle=-30, gridcolor="rgba(226,232,240,0.8)"),
                yaxis=dict(gridcolor="rgba(226,232,240,0.8)", title="Tutor Count"),
                height=400,
            )
            st.plotly_chart(fig, use_container_width=True)

        with col_table:
            st.dataframe(
                team_summary.rename(columns={
                    "total_tutors": "Total", "professional": "Professional",
                    "adjunct": "Adjunct", "avg_delivery_target": "Avg Del. Target",
                }),
                hide_index=True, use_container_width=True, height=400,
            )

    # ══════════════════════════════════════════════════════════════════════════
    # PAGE — TIER BREAKDOWN
    # ══════════════════════════════════════════════════════════════════════════
    elif page == "📊 Tier Breakdown":
        st.markdown(
            "<p class='section-label'>Tiers</p>"
            "<p class='section-title'>Tier Distribution by Team</p>",
            unsafe_allow_html=True,
        )

        tier_pivot = filt.groupby(["manager", "tier"]).size().reset_index(name="count")
        tier_order = filt["tier"].value_counts().index.tolist()
        tier_colors = {t: c for t, c in zip(tier_order,
            ["#3b82f6", "#8b5cf6", "#06b6d4", "#f59e0b", "#10b981",
             "#ef4444", "#ec4899", "#64748b", "#a78bfa", "#34d399"])}

        col_hbar, col_pies = st.columns([1.4, 1])

        with col_hbar:
            fig2 = go.Figure()
            for tier in tier_order:
                subset = tier_pivot[tier_pivot["tier"] == tier]
                fig2.add_trace(go.Bar(
                    y=subset["manager"], x=subset["count"], name=tier, orientation="h",
                    marker_color=tier_colors.get(tier, "#64748b"),
                    text=subset["count"], textposition="inside",
                    textfont=dict(size=12, color="white"),
                ))
            fig2.update_layout(
                barmode="stack", plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                font=dict(family="DM Sans", color="#475569"),
                legend=dict(orientation="h", y=-0.15, x=0.5, xanchor="center", font=dict(size=11)),
                margin=dict(l=10, r=20, t=20, b=60),
                xaxis=dict(gridcolor="rgba(226,232,240,0.8)", title="Tutor Count"),
                yaxis=dict(automargin=True),
                height=max(300, len(selected_managers) * 55 + 100),
            )
            st.plotly_chart(fig2, use_container_width=True)

        with col_pies:
            overall_tier = filt["tier"].value_counts().reset_index()
            overall_tier.columns = ["tier", "count"]
            fig_pie = go.Figure(go.Pie(
                labels=overall_tier["tier"], values=overall_tier["count"],
                marker=dict(colors=[tier_colors.get(t, "#64748b") for t in overall_tier["tier"]]),
                textinfo="label+percent", textfont=dict(size=12), hole=0.45,
            ))
            fig_pie.update_layout(
                title=dict(text="Overall Tier Mix", font=dict(size=14, color="#475569"),
                           x=0.5, xanchor="center"),
                plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                font=dict(family="DM Sans", color="#475569"),
                showlegend=False, margin=dict(l=10, r=10, t=40, b=10), height=350,
            )
            st.plotly_chart(fig_pie, use_container_width=True)

        tier_detail = (
            filt.pivot_table(index="manager", columns="tier", values="tutor_id",
                             aggfunc="count", fill_value=0)
            .reset_index().rename(columns={"manager": "Faculty Leader"})
        )
        tier_detail["Total"] = tier_detail.iloc[:, 1:].sum(axis=1)
        tier_detail = tier_detail.sort_values("Total", ascending=False)
        st.dataframe(tier_detail, hide_index=True, use_container_width=True)

    # ══════════════════════════════════════════════════════════════════════════
    # PAGE — TENURE
    # ══════════════════════════════════════════════════════════════════════════
    elif page == "⏳ Tenure":
        st.markdown(
            "<p class='section-label'>Tenure</p>"
            "<p class='section-title'>Team Tenure Analysis</p>",
            unsafe_allow_html=True,
        )

        tenure_stats = (
            filt.groupby("manager")["tenure_years"]
            .agg(["mean", "median", "min", "max", "count"])
            .reset_index()
            .rename(columns={"manager": "Faculty Leader", "mean": "Avg (yr)",
                              "median": "Median (yr)", "min": "Min (yr)",
                              "max": "Max (yr)", "count": "Tutors"})
            .sort_values("Avg (yr)", ascending=False)
        )
        for c in ["Avg (yr)", "Median (yr)", "Min (yr)", "Max (yr)"]:
            tenure_stats[c] = tenure_stats[c].round(1)

        col_box, col_stats = st.columns([1.3, 1])

        with col_box:
            fig3 = go.Figure()
            for mgr in tenure_stats["Faculty Leader"]:
                mgr_data = filt[filt["manager"] == mgr]["tenure_years"]
                fig3.add_trace(go.Box(
                    y=mgr_data, name=mgr, boxmean=True,
                    marker_color="#3b82f6", line_color="#2563eb",
                    fillcolor="rgba(59,130,246,0.12)",
                ))
            fig3.update_layout(
                plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                font=dict(family="DM Sans", color="#475569"),
                margin=dict(l=40, r=20, t=20, b=60),
                yaxis=dict(gridcolor="rgba(226,232,240,0.8)", title="Tenure (years)"),
                xaxis=dict(tickangle=-30), showlegend=False, height=420,
            )
            st.plotly_chart(fig3, use_container_width=True)

        with col_stats:
            st.dataframe(tenure_stats, hide_index=True, use_container_width=True, height=420)

        st.markdown("")
        fig_hist = go.Figure(go.Histogram(
            x=filt["tenure_years"], nbinsx=20, marker_color="#3b82f6", opacity=0.85,
        ))
        fig_hist.update_layout(
            title=dict(text="Tenure Distribution (All Filtered Tutors)",
                       font=dict(size=14, color="#475569"), x=0.5, xanchor="center"),
            plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
            font=dict(family="DM Sans", color="#475569"),
            xaxis=dict(title="Years", gridcolor="rgba(226,232,240,0.8)"),
            yaxis=dict(title="Count", gridcolor="rgba(226,232,240,0.8)"),
            margin=dict(l=40, r=20, t=50, b=40), height=300,
        )
        st.plotly_chart(fig_hist, use_container_width=True)

    # ══════════════════════════════════════════════════════════════════════════
    # PAGE — BUC / PT SPLIT
    # ══════════════════════════════════════════════════════════════════════════
    elif page == "🔀 BUC / PT Split":
        st.markdown(
            "<p class='section-label'>Brand Composition</p>"
            "<p class='section-title'>BUC vs. Private Tutoring Split</p>",
            unsafe_allow_html=True,
        )

        brand_colors = {"BUC Only": "#f59e0b", "BUC & PT": "#8b5cf6", "PT Only": "#10b981"}
        brand_pivot = filt.groupby(["manager", "brand_composition"]).size().reset_index(name="count")

        col_brand_chart, col_brand_table = st.columns([1.3, 1])

        with col_brand_chart:
            fig4 = go.Figure()
            for comp in ["BUC Only", "BUC & PT", "PT Only"]:
                subset = brand_pivot[brand_pivot["brand_composition"] == comp]
                fig4.add_trace(go.Bar(
                    x=subset["manager"], y=subset["count"], name=comp,
                    marker_color=brand_colors[comp],
                    text=subset["count"], textposition="inside",
                    textfont=dict(size=12, color="white"),
                ))
            fig4.update_layout(
                barmode="stack", plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                font=dict(family="DM Sans", color="#475569"),
                legend=dict(orientation="h", y=1.08, x=0.5, xanchor="center", font=dict(size=12)),
                margin=dict(l=40, r=20, t=40, b=60),
                xaxis=dict(tickangle=-30, gridcolor="rgba(226,232,240,0.8)"),
                yaxis=dict(gridcolor="rgba(226,232,240,0.8)", title="Tutor Count"),
                height=400,
            )
            st.plotly_chart(fig4, use_container_width=True)

        with col_brand_table:
            brand_detail = (
                filt.pivot_table(index="manager", columns="brand_composition",
                                 values="tutor_id", aggfunc="count", fill_value=0)
                .reset_index().rename(columns={"manager": "Faculty Leader"})
            )
            brand_detail["Total"] = brand_detail.iloc[:, 1:].sum(axis=1)
            brand_detail = brand_detail.sort_values("Total", ascending=False)
            st.dataframe(brand_detail, hide_index=True, use_container_width=True, height=400)

        st.markdown("")
        ov_brand = filt["brand_composition"].value_counts().reset_index()
        ov_brand.columns = ["brand_composition", "count"]
        c1, c2, c3 = st.columns([1, 1, 1])
        with c2:
            fig_donut = go.Figure(go.Pie(
                labels=ov_brand["brand_composition"], values=ov_brand["count"],
                marker=dict(colors=[brand_colors.get(b, "#64748b") for b in ov_brand["brand_composition"]]),
                textinfo="label+value+percent", textfont=dict(size=13), hole=0.5,
            ))
            fig_donut.update_layout(
                title=dict(text="Overall Brand Composition",
                           font=dict(size=14, color="#475569"), x=0.5, xanchor="center"),
                plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                font=dict(family="DM Sans", color="#475569"),
                showlegend=False, margin=dict(l=10, r=10, t=40, b=10), height=350,
            )
            st.plotly_chart(fig_donut, use_container_width=True)


    # ══════════════════════════════════════════════════════════════════════════
    # PAGE — RESTRICTED STATUS
    # ══════════════════════════════════════════════════════════════════════════
    elif page == "🚫 Restricted Status":

        restr_range_options = {
            "Past 2 Years": 24,
            "Past Year": 12,
            "Past 6 Months": 6,
            "Past 3 Months": 3,
            "Past Month": 1,
        }
        sel_restr_range = st.selectbox("Date Range", list(restr_range_options.keys()), index=1, key="restr_range")
        sel_restr_months = restr_range_options[sel_restr_range]

        restr_range_start = (pd.Timestamp.now() - pd.DateOffset(months=sel_restr_months)).strftime("%B %d, %Y")
        restr_range_end = date.today().strftime("%B %d, %Y")

        st.markdown(
            f"<p class='section-label'>Restricted Tutors</p>"
            f"<p class='section-title'>Current & Historical Restricted Status</p>"
            f"<p style='color:#64748b; font-size:0.82rem; margin-top:-12px;'>Showing data from {restr_range_start} to {restr_range_end}</p>",
            unsafe_allow_html=True,
        )

        # ── Repeat Restriction Alerts (always full data) ─────────────────────
        if not df_restricted.empty:
            today_r = pd.Timestamp.now()
            one_year_ago = today_r - pd.DateOffset(years=1)
            six_months_ago = today_r - pd.DateOffset(months=6)

            restr_full = df_restricted.copy()
            restr_full["status_starts_at"] = pd.to_datetime(restr_full["status_starts_at"], errors="coerce")

            # 3+ times in past year
            past_year = restr_full[restr_full["status_starts_at"] >= one_year_ago]
            year_counts = past_year.groupby(["employee_name", "team"]).size().reset_index(name="count")
            flagged_year = year_counts[year_counts["count"] >= 3].sort_values("employee_name")

            # 2+ times in past 6 months
            past_6mo = restr_full[restr_full["status_starts_at"] >= six_months_ago]
            mo6_counts = past_6mo.groupby(["employee_name", "team"]).size().reset_index(name="count")
            flagged_6mo = mo6_counts[mo6_counts["count"] >= 2].sort_values("employee_name")

            year_html = ""
            if len(flagged_year) > 0:
                items = ""
                for _, row in flagged_year.iterrows():
                    items += (
                        f"<div style='background:white; border:1px solid #fecaca; border-radius:6px; padding:8px 12px; margin:6px 0;'>"
                        f"<p style='color:#1e293b; font-weight:600; font-size:0.85rem; margin:0;'>{row['employee_name']}</p>"
                        f"<table style='width:100%; font-size:0.78rem; color:#64748b; margin-top:4px;'>"
                        f"<tr><td style='padding:1px 0;'>Team</td><td style='padding:1px 0; text-align:right; color:#1e293b;'>{row['team']}</td></tr>"
                        f"<tr><td style='padding:1px 0;'>Restrictions</td><td style='padding:1px 0; text-align:right; color:#991b1b; font-weight:600;'>{int(row['count'])}x in past year</td></tr>"
                        f"</table></div>"
                    )
                year_html = items

            mo6_html = ""
            if len(flagged_6mo) > 0:
                items = ""
                for _, row in flagged_6mo.iterrows():
                    items += (
                        f"<div style='background:white; border:1px solid #fde68a; border-radius:6px; padding:8px 12px; margin:6px 0;'>"
                        f"<p style='color:#1e293b; font-weight:600; font-size:0.85rem; margin:0;'>{row['employee_name']}</p>"
                        f"<table style='width:100%; font-size:0.78rem; color:#64748b; margin-top:4px;'>"
                        f"<tr><td style='padding:1px 0;'>Team</td><td style='padding:1px 0; text-align:right; color:#1e293b;'>{row['team']}</td></tr>"
                        f"<tr><td style='padding:1px 0;'>Restrictions</td><td style='padding:1px 0; text-align:right; color:#92400e; font-weight:600;'>{int(row['count'])}x in past 6 months</td></tr>"
                        f"</table></div>"
                    )
                mo6_html = items

            # Build flag sets for table
            flagged_year_names = set(flagged_year["employee_name"].tolist()) if len(flagged_year) > 0 else set()
            flagged_6mo_names = set(flagged_6mo["employee_name"].tolist()) if len(flagged_6mo) > 0 else set()

            if len(flagged_year) > 0 or len(flagged_6mo) > 0:
                ac1, ac2 = st.columns(2)
                with ac1:
                    with st.expander(f"🔴 3+ Restrictions in Past Year ({len(flagged_year)})", expanded=False):
                        if year_html:
                            st.markdown(year_html, unsafe_allow_html=True)
                        else:
                            st.success("No tutors with 3+ restrictions in the past year.")
                with ac2:
                    with st.expander(f"🟡 2+ Restrictions in Past 6 Months ({len(flagged_6mo)})", expanded=False):
                        if mo6_html:
                            st.markdown(mo6_html, unsafe_allow_html=True)
                        else:
                            st.success("No tutors with 2+ restrictions in the past 6 months.")
                st.markdown("")
        else:
            flagged_year_names = set()
            flagged_6mo_names = set()

        # ── Filter data by selected date range ───────────────────────────────
        restr_cutoff = pd.Timestamp.now() - pd.DateOffset(months=sel_restr_months)

        # Currently restricted tutors
        currently_restricted = df_restricted[df_restricted["current_status_flag"] == 1].copy()

        cr1, cr2, cr3 = st.columns(3)
        cr1.metric("Currently Restricted", len(currently_restricted))
        if len(currently_restricted) > 0:
            cr2.metric("Avg Days Restricted", f"{currently_restricted['days_in_effect'].mean():.0f}")
            cr3.metric("Max Days Restricted", f"{currently_restricted['days_in_effect'].max():.0f}")
        else:
            cr2.metric("Avg Days Restricted", "—")
            cr3.metric("Max Days Restricted", "—")

        st.markdown("")

        # Currently restricted by team
        if len(currently_restricted) > 0:
            st.markdown(
                "<p class='section-label'>Current</p>"
                "<p class='section-title'>Currently Restricted Tutors</p>",
                unsafe_allow_html=True,
            )

            team_restricted = (
                currently_restricted.groupby("team")
                .agg(
                    count=("employee_id", "count"),
                    avg_days=("days_in_effect", "mean"),
                    max_days=("days_in_effect", "max"),
                )
                .reset_index()
                .rename(columns={"team": "Team"})
                .sort_values("count", ascending=False)
            )
            team_restricted["avg_days"] = team_restricted["avg_days"].round(0).astype(int)
            team_restricted["max_days"] = team_restricted["max_days"].astype(int)

            col_rc, col_rt = st.columns([1.3, 1])

            with col_rc:
                fig_r = go.Figure()
                fig_r.add_trace(go.Bar(
                    x=team_restricted["Team"], y=team_restricted["count"],
                    marker_color="#ef4444",
                    text=team_restricted["count"], textposition="outside",
                    textfont=dict(size=13),
                ))
                fig_r.update_layout(
                    plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                    font=dict(family="DM Sans", color="#475569"),
                    margin=dict(l=40, r=20, t=20, b=60),
                    xaxis=dict(tickangle=-30, gridcolor="rgba(226,232,240,0.8)"),
                    yaxis=dict(gridcolor="rgba(226,232,240,0.8)", title="Restricted Tutors"),
                    height=350,
                )
                st.plotly_chart(fig_r, use_container_width=True)

            with col_rt:
                st.dataframe(
                    team_restricted.rename(columns={
                        "count": "Restricted", "avg_days": "Avg Days", "max_days": "Max Days",
                    }),
                    hide_index=True, use_container_width=True, height=350,
                )

            # Individual currently restricted detail
            st.markdown("")
            curr_display = (
                currently_restricted[["employee_name", "team", "tier", "update_type",
                                      "status_starts_at", "days_in_effect"]]
                .rename(columns={
                    "employee_name": "Tutor", "team": "Team", "tier": "Tier",
                    "update_type": "Set By", "status_starts_at": "Restricted Since",
                    "days_in_effect": "Days Restricted",
                })
                .sort_values("Tutor")
            )
            curr_display["Restricted Since"] = curr_display["Restricted Since"].dt.strftime("%Y-%m-%d")
            curr_display["Days Restricted"] = curr_display["Days Restricted"].astype(int)

            # Add flag column
            def get_restr_flag(name):
                if name in flagged_year_names:
                    return "🔴"
                elif name in flagged_6mo_names:
                    return "🟡"
                return ""
            curr_display.insert(0, "Flag", curr_display["Tutor"].apply(get_restr_flag))

            st.markdown(
                "<p style='font-size:0.78rem; color:#64748b; margin-bottom:8px;'>"
                "🔴 3+ restrictions in past year &nbsp;&nbsp;|&nbsp;&nbsp; "
                "🟡 2+ restrictions in past 6 months</p>",
                unsafe_allow_html=True,
            )

            cf1, cf2, cf3 = st.columns([2, 2, 1])
            with cf1:
                curr_teams = sorted(curr_display["Team"].dropna().unique())
                sel_curr_team = st.multiselect("Filter by Team", curr_teams, key="curr_restr_team")
            with cf2:
                curr_tutors = sorted(curr_display["Tutor"].dropna().unique())
                sel_curr_tutor = st.multiselect("Filter by Tutor", curr_tutors, key="curr_restr_tutor")
            with cf3:
                show_flagged_curr = st.selectbox("Show", ["All", "All Flagged", "🔴 3+ / Year", "🟡 2+ / 6mo"], key="curr_flagged_only")
            if sel_curr_team:
                curr_display = curr_display[curr_display["Team"].isin(sel_curr_team)]
            if sel_curr_tutor:
                curr_display = curr_display[curr_display["Tutor"].isin(sel_curr_tutor)]
            if show_flagged_curr == "🔴 3+ / Year":
                curr_display = curr_display[curr_display["Flag"] == "🔴"]
            elif show_flagged_curr == "🟡 2+ / 6mo":
                curr_display = curr_display[curr_display["Flag"] == "🟡"]
            elif show_flagged_curr == "All Flagged":
                curr_display = curr_display[curr_display["Flag"] != ""]

            st.dataframe(curr_display, hide_index=True, use_container_width=True)

        else:
            st.success("No tutors are currently on restricted status.")

        # Historical restricted status (filtered by date range)
        st.markdown("")
        st.markdown(
            "<p class='section-label'>History</p>"
            "<p class='section-title'>Restricted Status History</p>",
            unsafe_allow_html=True,
        )

        hist_all = df_restricted.copy()
        hist_all["status_starts_at"] = pd.to_datetime(hist_all["status_starts_at"], errors="coerce")
        hist_all["status_ends_at"] = pd.to_datetime(hist_all["status_ends_at"], errors="coerce")

        # Filter by date range — include events that started OR ended in range
        hist_filtered = hist_all[
            (hist_all["status_starts_at"] >= restr_cutoff)
            | (hist_all["status_ends_at"] >= restr_cutoff)
            | (hist_all["current_status_flag"] == 1)
        ]

        if len(hist_filtered) > 0:
            # Count by team
            hist_by_team = (
                hist_filtered.groupby("team")
                .agg(
                    events=("employee_id", "count"),
                    unique_tutors=("employee_id", "nunique"),
                    avg_days=("days_in_effect", "mean"),
                )
                .reset_index()
                .rename(columns={"team": "Team"})
                .sort_values("Team")
            )
            hist_by_team["avg_days"] = hist_by_team["avg_days"].round(0).astype(int)

            st.dataframe(
                hist_by_team.rename(columns={
                    "events": "Restriction Events", "unique_tutors": "Unique Tutors",
                    "avg_days": "Avg Days Per Event",
                }),
                hide_index=True, use_container_width=True,
            )

            st.markdown("")
            hist_display = (
                hist_filtered[["employee_name", "team", "tier", "update_type",
                                "status_starts_at", "status_ends_at", "days_in_effect",
                                "current_status_flag"]]
                .rename(columns={
                    "employee_name": "Tutor", "team": "Team", "tier": "Tier",
                    "update_type": "Set By", "status_starts_at": "Start",
                    "status_ends_at": "End", "days_in_effect": "Days",
                    "current_status_flag": "Current",
                })
                .sort_values(["Tutor", "Start"], ascending=[True, False])
            )
            hist_display["Start"] = hist_display["Start"].dt.strftime("%Y-%m-%d")
            hist_display["End"] = hist_display["End"].dt.strftime("%Y-%m-%d").fillna("Present")
            hist_display["Days"] = hist_display["Days"].fillna(0).astype(int)
            hist_display["Current"] = hist_display["Current"].map({1: "Yes", 0: "No"})

            # Add flag
            hist_display.insert(0, "Flag", hist_display["Tutor"].apply(get_restr_flag))

            st.markdown(
                "<p style='font-size:0.78rem; color:#64748b; margin-bottom:8px;'>"
                "🔴 3+ restrictions in past year &nbsp;&nbsp;|&nbsp;&nbsp; "
                "🟡 2+ restrictions in past 6 months</p>",
                unsafe_allow_html=True,
            )

            hf1, hf2, hf3 = st.columns([2, 2, 1])
            with hf1:
                hist_teams = sorted(hist_display["Team"].dropna().unique())
                sel_hist_team = st.multiselect("Filter by Team", hist_teams, key="hist_restr_team")
            with hf2:
                hist_tutors = sorted(hist_display["Tutor"].dropna().unique())
                sel_hist_tutor = st.multiselect("Filter by Tutor", hist_tutors, key="hist_restr_tutor")
            with hf3:
                show_flagged_hist = st.selectbox("Show", ["All", "All Flagged", "🔴 3+ / Year", "🟡 2+ / 6mo"], key="hist_flagged_only")
            if sel_hist_team:
                hist_display = hist_display[hist_display["Team"].isin(sel_hist_team)]
            if sel_hist_tutor:
                hist_display = hist_display[hist_display["Tutor"].isin(sel_hist_tutor)]
            if show_flagged_hist == "🔴 3+ / Year":
                hist_display = hist_display[hist_display["Flag"] == "🔴"]
            elif show_flagged_hist == "🟡 2+ / 6mo":
                hist_display = hist_display[hist_display["Flag"] == "🟡"]
            elif show_flagged_hist == "All Flagged":
                hist_display = hist_display[hist_display["Flag"] != ""]

            st.dataframe(hist_display, hide_index=True, use_container_width=True,
                         height=min(600, len(hist_display) * 35 + 60))
        else:
            st.info("No restriction events found in the selected date range.")

    elif page == "📅 Meetings":

        mtg_range_options = {
            "Past 2 Years": 24,
            "Past Year": 12,
            "Past 6 Months": 6,
            "Past 3 Months": 3,
            "Past Month": 1,
        }
        sel_range = st.selectbox("Date Range", list(mtg_range_options.keys()), index=0, key="mtg_range")
        sel_months = mtg_range_options[sel_range]

        df_meetings_filtered = load_meeting_data(lookback_months=sel_months)

        from dateutil.relativedelta import relativedelta
        range_start = (pd.Timestamp.now() - pd.DateOffset(months=sel_months)).strftime("%B %d, %Y")
        range_end = date.today().strftime("%B %d, %Y")

        st.markdown(
            f"<p class='section-label'>Meeting Frequency</p>"
            f"<p class='section-title'>1-on-1 & Group Meetings</p>"
            f"<p style='color:#64748b; font-size:0.82rem; margin-top:-12px;'>Showing data from {range_start} to {range_end}</p>",
            unsafe_allow_html=True,
        )

        mtg = df_meetings_filtered[df_meetings_filtered["faculty_leader"].isin(selected_managers)].copy()

        mm1, mm2, mm3, mm4 = st.columns(4)
        mm1.metric("Avg 1:1s per Tutor", f"{mtg['attended_1on1_meetings'].mean():.1f}")
        mm2.metric("Avg 1:1 Hours", f"{mtg['1on1_meeting_hours'].mean():.1f}")
        mm3.metric("Avg Group Meetings", f"{mtg['attended_group_meetings'].mean():.1f}")
        avg_days = mtg["days_since_last_1on1"].mean()
        mm4.metric("Avg Days Since Last 1:1", f"{avg_days:.0f}" if not pd.isna(avg_days) else "—")

        st.markdown("")

        # ── Meeting Alerts (always based on full 2-year data) ─────────────────
        mtg_full = load_meeting_data(lookback_months=24)
        mtg_full = mtg_full[mtg_full["faculty_leader"].isin(selected_managers)].copy()
        mtg_full["hire_date"] = pd.to_datetime(mtg_full["hire_date"], errors="coerce")
        today_ts = pd.Timestamp.now()
        mtg_full["days_employed"] = (today_ts - mtg_full["hire_date"]).dt.days

        # Also add days_employed to mtg for display
        mtg["hire_date"] = pd.to_datetime(mtg["hire_date"], errors="coerce")
        mtg["days_employed"] = (today_ts - mtg["hire_date"]).dt.days

        # New tutors (< 100 days) without 1-on-1 in 3 weeks (21 days)
        new_tutors = mtg_full[mtg_full["days_employed"] < 100].copy()
        new_overdue = new_tutors[
            (new_tutors["days_since_last_1on1"] > 21) | (new_tutors["days_since_last_1on1"].isna())
        ].sort_values("tutor")

        # Veteran tutors (>= 100 days) without 1-on-1 in 8 weeks (56 days)
        vet_tutors = mtg_full[mtg_full["days_employed"] >= 100].copy()
        vet_overdue = vet_tutors[
            (vet_tutors["days_since_last_1on1"] > 56) | (vet_tutors["days_since_last_1on1"].isna())
        ].sort_values("tutor")

        new_html = ""
        if len(new_overdue) > 0:
            items = ""
            for _, row in new_overdue.iterrows():
                days_since = f"{int(row['days_since_last_1on1'])} days" if pd.notna(row["days_since_last_1on1"]) else "no meeting on record"
                next_mtg_str = row["next_1on1"].strftime("%Y-%m-%d") if pd.notna(row.get("next_1on1")) else "none scheduled"
                items += (
                    f"<div style='background:white; border:1px solid #fecaca; border-radius:6px; padding:8px 12px; margin:6px 0;'>"
                    f"<p style='color:#1e293b; font-weight:600; font-size:0.85rem; margin:0;'>{row['tutor']}</p>"
                    f"<table style='width:100%; font-size:0.78rem; color:#64748b; margin-top:4px;'>"
                    f"<tr><td style='padding:1px 0;'>Faculty Leader</td><td style='padding:1px 0; text-align:right; color:#1e293b;'>{row['faculty_leader']}</td></tr>"
                    f"<tr><td style='padding:1px 0;'>Last 1:1</td><td style='padding:1px 0; text-align:right; color:#991b1b; font-weight:600;'>{days_since} ago</td></tr>"
                    f"<tr><td style='padding:1px 0;'>Next 1:1</td><td style='padding:1px 0; text-align:right; color:#1e293b;'>{next_mtg_str}</td></tr>"
                    f"<tr><td style='padding:1px 0;'>Hire Date</td><td style='padding:1px 0; text-align:right; color:#1e293b;'>{row['hire_date'].strftime('%b %d, %Y')} ({int(row['days_employed'])}d)</td></tr>"
                    f"</table></div>"
                )
            new_html = (
                "<div style='background:#fef2f2; border:1px solid #fecaca; border-radius:10px; padding:14px 16px; height:100%;'>"
                "<p style='color:#991b1b; font-weight:600; font-size:0.8rem; margin:0 0 10px 0;'>"
                "🔴 NEW TUTORS — No 1:1 in 3+ weeks</p>"
                f"{items}</div>"
            )

        vet_html = ""
        if len(vet_overdue) > 0:
            items = ""
            for _, row in vet_overdue.iterrows():
                days_since = f"{int(row['days_since_last_1on1'])} days" if pd.notna(row["days_since_last_1on1"]) else "no meeting on record"
                next_mtg_str = row["next_1on1"].strftime("%Y-%m-%d") if pd.notna(row.get("next_1on1")) else "none scheduled"
                items += (
                    f"<div style='background:white; border:1px solid #fde68a; border-radius:6px; padding:8px 12px; margin:6px 0;'>"
                    f"<p style='color:#1e293b; font-weight:600; font-size:0.85rem; margin:0;'>{row['tutor']}</p>"
                    f"<table style='width:100%; font-size:0.78rem; color:#64748b; margin-top:4px;'>"
                    f"<tr><td style='padding:1px 0;'>Faculty Leader</td><td style='padding:1px 0; text-align:right; color:#1e293b;'>{row['faculty_leader']}</td></tr>"
                    f"<tr><td style='padding:1px 0;'>Last 1:1</td><td style='padding:1px 0; text-align:right; color:#92400e; font-weight:600;'>{days_since} ago</td></tr>"
                    f"<tr><td style='padding:1px 0;'>Next 1:1</td><td style='padding:1px 0; text-align:right; color:#1e293b;'>{next_mtg_str}</td></tr>"
                    f"</table></div>"
                )
            vet_html = (
                "<div style='background:#fffbeb; border:1px solid #fde68a; border-radius:10px; padding:14px 16px; height:100%;'>"
                "<p style='color:#92400e; font-weight:600; font-size:0.8rem; margin:0 0 10px 0;'>"
                "🟡 VETERAN TUTORS — No 1:1 in 8+ weeks</p>"
                f"{items}</div>"
            )

        # Build sets of flagged tutors for table highlighting
        new_overdue_names = set(new_overdue["tutor"].tolist()) if len(new_overdue) > 0 else set()
        vet_overdue_names = set(vet_overdue["tutor"].tolist()) if len(vet_overdue) > 0 else set()

        if len(new_overdue) > 0 or len(vet_overdue) > 0:
            ac1, ac2 = st.columns(2)
            with ac1:
                with st.expander(f"🔴 New Tutors — No 1:1 in 3+ weeks ({len(new_overdue)})", expanded=False):
                    if len(new_overdue) > 0:
                        st.markdown(new_html, unsafe_allow_html=True)
                    else:
                        st.success("All new tutors are up to date.")
            with ac2:
                with st.expander(f"🟡 Veteran Tutors — No 1:1 in 8+ weeks ({len(vet_overdue)})", expanded=False):
                    if len(vet_overdue) > 0:
                        st.markdown(vet_html, unsafe_allow_html=True)
                    else:
                        st.success("All veteran tutors are up to date.")
            st.markdown("")

        fl_mtg_summary = (
            mtg.groupby("faculty_leader")
            .agg(
                tutors=("tutor", "count"),
                avg_1on1s=("attended_1on1_meetings", "mean"),
                total_1on1_hrs=("1on1_meeting_hours", "sum"),
                avg_group=("attended_group_meetings", "mean"),
                avg_days_since=("days_since_last_1on1", "mean"),
            )
            .reset_index()
            .rename(columns={"faculty_leader": "Faculty Leader"})
            .sort_values("avg_1on1s", ascending=False)
        )
        for c in ["avg_1on1s", "total_1on1_hrs", "avg_group", "avg_days_since"]:
            fl_mtg_summary[c] = fl_mtg_summary[c].round(1)

        col_mtg_chart, col_mtg_table = st.columns([1.3, 1])

        with col_mtg_chart:
            fig_mtg = go.Figure()
            fig_mtg.add_trace(go.Bar(
                x=fl_mtg_summary["Faculty Leader"], y=fl_mtg_summary["avg_1on1s"],
                name="Avg 1:1 Meetings", marker_color="#3b82f6",
                text=fl_mtg_summary["avg_1on1s"], textposition="outside", textfont=dict(size=12),
            ))
            fig_mtg.add_trace(go.Bar(
                x=fl_mtg_summary["Faculty Leader"], y=fl_mtg_summary["avg_group"],
                name="Avg Group Meetings", marker_color="#8b5cf6",
                text=fl_mtg_summary["avg_group"], textposition="outside", textfont=dict(size=12),
            ))
            fig_mtg.update_layout(
                barmode="group", plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                font=dict(family="DM Sans", color="#475569"),
                legend=dict(orientation="h", y=1.08, x=0.5, xanchor="center", font=dict(size=12)),
                margin=dict(l=40, r=20, t=40, b=60),
                xaxis=dict(tickangle=-30, gridcolor="rgba(226,232,240,0.8)"),
                yaxis=dict(gridcolor="rgba(226,232,240,0.8)", title="Avg Meetings per Tutor"),
                height=400,
            )
            st.plotly_chart(fig_mtg, use_container_width=True)

        with col_mtg_table:
            st.dataframe(
                fl_mtg_summary.rename(columns={
                    "tutors": "Tutors", "avg_1on1s": "Avg 1:1s",
                    "total_1on1_hrs": "Total 1:1 Hrs", "avg_group": "Avg Group",
                    "avg_days_since": "Avg Days Since Last 1:1",
                }),
                hide_index=True, use_container_width=True, height=400,
            )

        st.markdown("")
        st.markdown(
            "<p class='section-label'>Attention</p>"
            "<p class='section-title'>Tutors by Days Since Last 1-on-1</p>",
            unsafe_allow_html=True,
        )

        fig_days = go.Figure()
        for mgr in sorted(mtg["faculty_leader"].unique()):
            mgr_data = mtg[mtg["faculty_leader"] == mgr]
            fig_days.add_trace(go.Box(
                y=mgr_data["days_since_last_1on1"], name=mgr, boxmean=True,
                marker_color="#3b82f6", line_color="#2563eb",
                fillcolor="rgba(59,130,246,0.12)",
                text=mgr_data["tutor"],
                hovertemplate="<b>%{text}</b><br>Days since last 1:1: %{y}<extra></extra>",
            ))
        fig_days.update_layout(
            plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
            font=dict(family="DM Sans", color="#475569"),
            margin=dict(l=40, r=20, t=20, b=60),
            yaxis=dict(gridcolor="rgba(226,232,240,0.8)", title="Days Since Last 1:1"),
            xaxis=dict(tickangle=-30), showlegend=False, height=350,
        )
        st.plotly_chart(fig_days, use_container_width=True)

        st.markdown("")
        st.markdown(
            "<p class='section-label'>Detail</p>"
            "<p class='section-title'>Tutor-Level Meeting Log</p>",
            unsafe_allow_html=True,
        )

        mtg_fl_options = sorted(mtg["faculty_leader"].dropna().unique())
        mtg_tutor_options = sorted(mtg["tutor"].dropna().unique())
        mf1, mf2, mf3 = st.columns([2, 2, 1])
        with mf1:
            sel_mtg_fl = st.multiselect("Filter by Faculty Leader", mtg_fl_options, key="mtg_fl_filter")
        with mf2:
            sel_mtg_tutor = st.multiselect("Filter by Tutor", mtg_tutor_options, key="mtg_tutor_filter")
        with mf3:
            show_flagged_mtg = st.selectbox("Show", ["All", "All Flagged", "🔴 New Tutors", "🟡 Veterans"], key="mtg_flagged_only")

        mtg_display = (
            mtg[["faculty_leader", "tutor", "tutor_type", "attended_1on1_meetings",
                 "1on1_meeting_hours", "last_attended_1on1", "days_since_last_1on1",
                 "attended_group_meetings", "next_1on1"]]
            .rename(columns={
                "faculty_leader": "Faculty Leader", "tutor": "Tutor", "tutor_type": "Type",
                "attended_1on1_meetings": "1:1 Count", "1on1_meeting_hours": "1:1 Hours",
                "last_attended_1on1": "Last 1:1", "days_since_last_1on1": "Days Since",
                "attended_group_meetings": "Group Mtgs", "next_1on1": "Next 1:1",
            })
            .sort_values(["Faculty Leader", "Days Since"], ascending=[True, False])
        )
        mtg_display["Last 1:1"] = mtg_display["Last 1:1"].dt.strftime("%Y-%m-%d")
        mtg_display["Next 1:1"] = pd.to_datetime(mtg_display["Next 1:1"], errors="coerce").dt.strftime("%Y-%m-%d").fillna("—")
        if sel_mtg_fl:
            mtg_display = mtg_display[mtg_display["Faculty Leader"].isin(sel_mtg_fl)]
        if sel_mtg_tutor:
            mtg_display = mtg_display[mtg_display["Tutor"].isin(sel_mtg_tutor)]


        # Add flag column
        def get_flag(tutor_name):
            if tutor_name in new_overdue_names:
                return "🔴"
            elif tutor_name in vet_overdue_names:
                return "🟡"
            return ""
        mtg_display.insert(0, "Flag", mtg_display["Tutor"].apply(get_flag))
        if show_flagged_mtg == "🔴 New Tutors":
            mtg_display = mtg_display[mtg_display["Flag"] == "🔴"]
        elif show_flagged_mtg == "🟡 Veterans":
            mtg_display = mtg_display[mtg_display["Flag"] == "🟡"]
        elif show_flagged_mtg == "All Flagged":
            mtg_display = mtg_display[mtg_display["Flag"] != ""]



        st.markdown(
            "<p style='font-size:0.78rem; color:#64748b; margin-bottom:8px;'>"
            "🔴 New tutor (&lt;100 days) — no 1:1 in 3+ weeks &nbsp;&nbsp;|&nbsp;&nbsp; "
            "🟡 Veteran tutor — no 1:1 in 8+ weeks</p>",
            unsafe_allow_html=True,
        )
        st.dataframe(mtg_display, hide_index=True, use_container_width=True,
                     height=min(600, len(mtg_display) * 35 + 60))


    # ══════════════════════════════════════════════════════════════════════════
    # PAGE — KPI COMPARISON
    # ══════════════════════════════════════════════════════════════════════════
    elif page == "📈 KPI Comparison":
        st.markdown(
            "<p class='section-label'>Performance</p>"
            "<p class='section-title'>Team KPI Comparison</p>",
            unsafe_allow_html=True,
        )

        if not df_kpi.empty:
            kpi_date_range = df_kpi.attrs.get("kpi_date_range", "")
            st.markdown(
                f"<div style='background:#f0f9ff; border:1px solid #bae6fd; border-radius:8px; padding:10px 16px; margin-bottom:16px;'>"
                f"<p style='color:#0369a1; font-size:0.82rem; margin:0;'>"
                f"📊 <b>Date Range:</b> {kpi_date_range}</p></div>",
                unsafe_allow_html=True,
            )

        if df_kpi.empty:
            st.warning("Dashboard_Metrics.xlsx not found or empty.")
        else:
            import plotly.express as px

            # Filter out excluded teams
            kpi = df_kpi[~df_kpi["Faculty Leader Name"].isin(excluded_managers)].copy()

            metrics = [
                "% to Delivery Target",
                "% to Availability Target",
                "Prep Time %",
                "% Parents Updates Done on Time",
                "% Sessions on Time",
                "% of Active Students with Progress Updates Completed",
            ]

            # Team-level averages
            leader_group = kpi.groupby("Faculty Leader Name")[metrics].mean().reset_index()

            # Summary KPIs across all teams
            st.markdown(
                "<p class='section-label'>Overall Averages</p>",
                unsafe_allow_html=True,
            )
            k1, k2, k3 = st.columns(3)
            k1.metric("Avg Delivery %", f"{kpi['% to Delivery Target'].mean()*100:.1f}%")
            k2.metric("Avg Availability %", f"{kpi['% to Availability Target'].mean()*100:.1f}%")
            k3.metric("Avg On-Time %", f"{kpi['% Sessions on Time'].mean()*100:.1f}%")
            k4, k5, k6 = st.columns(3)
            k4.metric("Avg Parent Updates %", f"{kpi['% Parents Updates Done on Time'].mean()*100:.1f}%")
            k5.metric("Avg Prep Time %", f"{kpi['Prep Time %'].mean()*100:.1f}%")
            k6.metric("Avg Progress Updates %", f"{kpi['% of Active Students with Progress Updates Completed'].mean()*100:.1f}%")

            st.markdown("")
            st.markdown("")

            # Bar chart per metric — all teams compared
            for metric in metrics:
                plot_df = leader_group[["Faculty Leader Name", metric]].copy()
                plot_df[metric + "_pct"] = plot_df[metric] * 100
                plot_df = plot_df.sort_values(metric + "_pct", ascending=False)

                fig = go.Figure()
                fig.add_trace(go.Bar(
                    x=plot_df["Faculty Leader Name"],
                    y=plot_df[metric + "_pct"],
                    marker_color="#3b82f6",
                    text=plot_df[metric + "_pct"].apply(lambda x: f"{x:.1f}%"),
                    textposition="outside",
                    textfont=dict(size=12),
                ))

                y_max = 130 if metric == "% to Availability Target" else 110
                fig.update_layout(
                    title=dict(text=metric, font=dict(size=14, color="#1e293b"),
                               x=0.5, xanchor="center"),
                    plot_bgcolor="rgba(0,0,0,0)",
                    paper_bgcolor="rgba(0,0,0,0)",
                    font=dict(family="DM Sans", color="#475569"),
                    margin=dict(l=40, r=20, t=50, b=60),
                    xaxis=dict(tickangle=-30, gridcolor="rgba(226,232,240,0.8)"),
                    yaxis=dict(gridcolor="rgba(226,232,240,0.8)",
                               range=[0, y_max], ticksuffix="%"),
                    height=400,
                    showlegend=False,
                )

                col1, col2, col3 = st.columns([0.5, 4, 0.5])
                with col2:
                    st.plotly_chart(fig, use_container_width=True)

                st.markdown("")

            # Full KPI table
            st.markdown(
                "<p class='section-label'>Detail</p>"
                "<p class='section-title'>Team KPI Averages</p>",
                unsafe_allow_html=True,
            )

            kpi_table = leader_group.copy()
            kpi_table.columns = ["Faculty Leader"] + metrics
            for m in metrics:
                kpi_table[m] = (kpi_table[m] * 100).round(1)
            kpi_table = kpi_table.sort_values("Faculty Leader")

            st.dataframe(kpi_table, hide_index=True, use_container_width=True)


    # ══════════════════════════════════════════════════════════════════════════
    # PAGE — SCORE GUARANTEE
    # ══════════════════════════════════════════════════════════════════════════
    elif page == "🎯 Score Guarantee":
        st.markdown(
            "<p class='section-label'>Test Prep</p>"
            "<p class='section-title'>Score Guarantee Overview</p>",
            unsafe_allow_html=True,
        )

        if df_sg.empty:
            st.warning("Score guarantee data not available. Check GitHub secrets.")
        else:
            # ── Score Guarantee Alerts ────────────────────────────────────────
            sg_alert_data = df_sg.copy()
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
            ].sort_values("student")

            no_baseline_html = ""
            if len(no_baseline) > 0:
                items = ""
                for _, row in no_baseline.iterrows():
                    student = row.get("student", "Unknown")
                    advisor = row.get("advisor", "Unknown")
                    first_sess = row["first_test_prep_session"].strftime("%Y-%m-%d") if pd.notna(row.get("first_test_prep_session")) else "—"
                    items += (
                        f"<p style='color:#991b1b; margin:2px 0; font-size:0.82rem;'>"
                        f"• <b>{student}</b><br>"
                        f"&nbsp;&nbsp;Advisor: {advisor}<br>"
                        f"&nbsp;&nbsp;Tutoring since: {first_sess}</p>"
                    )
                no_baseline_html = items

            # Alert 2: Behind on exams
            behind_on_exams = []
            if not df_sg_sessions.empty and not df_sg_exams.empty:
                for _, row in sg_alert_data.iterrows():
                    sid = row["student_id"]
                    pkg_hrs = row["package_hours"]
                    if pd.isna(pkg_hrs) or pd.isna(row.get("first_test_prep_session")):
                        continue
                    if pkg_hrs <= 24:
                        required_total = 4
                        num_milestones = 4
                    else:
                        required_total = 4 + int((pkg_hrs - 24) / 6)
                        num_milestones = required_total
                    milestone_hours = [(pkg_hrs / num_milestones) * (i + 1) for i in range(num_milestones)]
                    completed = row["completed_test_prep_hours"] if pd.notna(row.get("completed_test_prep_hours")) else 0
                    exams_expected = sum(1 for mh in milestone_hours if completed >= mh)
                    exams_taken = 0
                    if sid in df_sg_exams["student_id"].values:
                        exams_taken = len(df_sg_exams[(df_sg_exams["student_id"] == sid) & (df_sg_exams["before_or_after_tutoring"] == "after")])
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
                        f"<p style='color:#92400e; margin:2px 0; font-size:0.82rem;'>"
                        f"• <b>{b['student']}</b><br>"
                        f"&nbsp;&nbsp;Advisor: {b['advisor']} | Tutor: {b['tutor']}<br>"
                        f"&nbsp;&nbsp;{b['exams_taken']}/{b['exams_expected']} exams "
                        f"({b['completed']:.0f}/{b['pkg_hrs']:.0f} hrs)</p>"
                    )
                behind_html = items

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
                    after_exams = stu_exams[
                        (stu_exams["before_or_after_tutoring"] == "after") & stu_exams["score"].notna()
                    ].sort_values("exam_date")
                    if len(after_exams) == 0:
                        continue
                    most_recent = after_exams.iloc[-1]["score"]
                    avg_score = after_exams["score"].mean()
                    recent_vs_baseline = most_recent - baseline
                    if recent_vs_baseline <= 0:
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
                        f"<p style='color:#991b1b; margin:2px 0; font-size:0.82rem;'>"
                        f"• <b>{sc['student']}</b><br>"
                        f"&nbsp;&nbsp;Advisor: {sc['advisor']} | Tutor: {sc['tutor']}<br>"
                        f"&nbsp;&nbsp;Baseline: {sc['baseline']:.0f} → Latest: {sc['most_recent']:.0f} "
                        f"({sc['recent_change']:+.0f}) | {sc['num_exams']} exams {sc['trend']}</p>"
                    )
                score_html = items

            # Render alerts horizontally
            alert_configs = [
                ("⚠️ No Baseline Score", no_baseline_html, len(no_baseline) if len(no_baseline) > 0 else 0),
                ("⚠️ Behind on Practice Tests", behind_html, len(behind_on_exams)),
                ("⚠️ No Score Improvement", score_html, len(score_concerns)),
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

            # ── Build compliance checklist per student ─────────────────────────
            compliance_rows = []
            for _, row in sg.iterrows():
                sid = row["student_id"]
                checks = {}

                # 1. Package 20+ hours
                checks["1_pkg_20hrs"] = row["package_hours"] >= 20 if pd.notna(row["package_hours"]) else False

                # 2. Used full hours
                checks["2_hours_used"] = (
                    row["completed_test_prep_hours"] >= row["package_hours"]
                    if pd.notna(row["completed_test_prep_hours"]) and pd.notna(row["package_hours"])
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
                checks["4_baseline"] = (
                    pd.notna(row["starting_test_taken"]) and pd.notna(row["first_test_prep_session"])
                    and row["starting_test_taken"] <= row["first_test_prep_session"]
                )

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

                # 7. Minimum practice tests (excluding baseline)
                pkg_hrs = row["package_hours"] if pd.notna(row["package_hours"]) else 0
                if pkg_hrs <= 24:
                    required_tests = 4
                else:
                    required_tests = 4 + int((pkg_hrs - 24) / 6)

                if not df_sg_exams.empty and sid in df_sg_exams["student_id"].values:
                    stu_exams = df_sg_exams[df_sg_exams["student_id"] == sid].copy()
                    stu_exams["exam_date"] = pd.to_datetime(stu_exams["exam_date"], errors="coerce")
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

                checks["student_id"] = sid
                checks["student"] = row.get("student", "")
                checks["tutor"] = row.get("tutor", "")
                checks["advisor"] = row.get("advisor", "")
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

            # Filters
            fc1, fc2, fc3 = st.columns(3)
            with fc1:
                sg_students = sorted(comp_df["student"].dropna().unique())
                sel_students = st.multiselect("Filter by Student", sg_students, key="sg_filter_student")
            with fc2:
                sg_tutors = sorted(comp_df["tutor"].dropna().unique())
                sel_tutors = st.multiselect("Filter by Tutor", sg_tutors, key="sg_filter_tutor")
            with fc3:
                sg_advisors = sorted(comp_df["advisor"].dropna().unique())
                sel_advisors = st.multiselect("Filter by Advisor", sg_advisors, key="sg_filter_advisor")

            filtered_comp = comp_df.copy()
            if sel_students:
                filtered_comp = filtered_comp[filtered_comp["student"].isin(sel_students)]
            if sel_tutors:
                filtered_comp = filtered_comp[filtered_comp["tutor"].isin(sel_tutors)]
            if sel_advisors:
                filtered_comp = filtered_comp[filtered_comp["advisor"].isin(sel_advisors)]
            filtered_comp = filtered_comp.sort_values("student")

            def status_icon(val):
                if val is True:
                    return "✅"
                elif val is False:
                    return "❌"
                return "—"

            matrix = filtered_comp[["student", "tutor", "advisor"]].copy()
            matrix["Pkg ≥20hr"] = filtered_comp.apply(
                lambda r: f"{status_icon(r['1_pkg_20hrs'])} {r['package_hours']:.0f}hr" if pd.notna(r.get("package_hours")) else "—", axis=1
            )
            matrix["Hrs Used"] = filtered_comp.apply(
                lambda r: f"{status_icon(r['2_hours_used'])} {r['completed_hours']:.1f}/{r['package_hours']:.0f}" if pd.notna(r.get("completed_hours")) and pd.notna(r.get("package_hours")) else "—", axis=1
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
            matrix = matrix.rename(columns={"student": "Student", "tutor": "Tutor", "advisor": "Advisor"})

            st.dataframe(matrix, hide_index=True, use_container_width=True,
                         height=min(700, len(matrix) * 35 + 60))

            # ── Student Detail Drilldown ──────────────────────────────────────
            st.markdown("")
            st.markdown(
                "<p class='section-label'>Drilldown</p>"
                "<p class='section-title'>Student Detail</p>",
                unsafe_allow_html=True,
            )

            student_names = sorted(sg["student"].dropna().unique())
            selected_student = st.selectbox("Select a student:", student_names, key="sg_student_select")

            if selected_student:
                stu_row = sg[sg["student"] == selected_student].iloc[0]
                sid = stu_row["student_id"]

                # Package info
                st.markdown("---")
                st.markdown(f"### {selected_student}")
                p1, p2, p3, p4 = st.columns(4)
                p1.metric("Tutor", stu_row.get("tutor", "—") or "—")
                p2.metric("Advisor", stu_row.get("advisor", "—") or "—")
                p3.metric("Package Hours", f"{stu_row['package_hours']:.0f}" if pd.notna(stu_row.get("package_hours")) else "—")
                p4.metric("Won Date", stu_row["won_at"].strftime("%Y-%m-%d") if pd.notna(stu_row.get("won_at")) else "—")

                p5, p6, p7, p8 = st.columns(4)
                p5.metric("Completed Hours", f"{stu_row['completed_test_prep_hours']:.1f}" if pd.notna(stu_row.get("completed_test_prep_hours")) else "—")
                p6.metric("Starting Score", f"{stu_row['starting_score']:.0f}" if pd.notna(stu_row.get("starting_score")) else "—")
                p7.metric("Latest Score", f"{stu_row['latest_test_score']:.0f}" if pd.notna(stu_row.get("latest_test_score")) else "—")
                score_ch = stu_row.get("score_change")
                p8.metric("Score Change", f"{score_ch:+.0f}" if pd.notna(score_ch) else "—")

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
                    lines.append(check_line("Used full package hours", sc.get("2_hours_used"),
                        f"— {sc.get('completed_hours', 0):.1f} / {sc.get('package_hours', 0):.0f} hrs" if pd.notna(sc.get("completed_hours")) else ""))
                    lines.append(check_line("Pace 1-2 hrs/week", sc.get("3_pace_ok"),
                        f"— {sc.get('3_pace_val', 0):.1f} hrs/wk" if pd.notna(sc.get("3_pace_val")) else ""))
                    lines.append(check_line("Baseline score before first session", sc.get("4_baseline")))
                    lines.append(check_line("100% session attendance", sc.get("5_attendance"),
                        f"— {int(sc.get('5_attended', 0))}/{int(sc.get('5_total', 0))} attended" if pd.notna(sc.get("5_attended")) else ""))
                    lines.append("⚪ **Homework completion** — not yet tracked")
                    lines.append(check_line(f"Minimum practice tests", sc.get("7_practice_tests"),
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
            has_scores = comp_df.dropna(subset=["starting_score", "latest_score"])
            if len(has_scores) > 0:
                st.markdown("")
                st.markdown(
                    "<p class='section-label'>Results</p>"
                    "<p class='section-title'>Score Changes by Student</p>",
                    unsafe_allow_html=True,
                )
                plot_sg = has_scores[["student", "score_change"]].sort_values("score_change", ascending=True)
                colors = ["#10b981" if x >= 0 else "#ef4444" for x in plot_sg["score_change"]]
                fig_sg = go.Figure()
                fig_sg.add_trace(go.Bar(
                    y=plot_sg["student"], x=plot_sg["score_change"], orientation="h",
                    marker_color=colors,
                    text=plot_sg["score_change"].apply(lambda x: f"{x:+.0f}"),
                    textposition="outside", textfont=dict(size=11),
                ))
                fig_sg.update_layout(
                    plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                    font=dict(family="DM Sans", color="#475569"),
                    margin=dict(l=10, r=40, t=20, b=40),
                    xaxis=dict(gridcolor="rgba(226,232,240,0.8)", title="Score Change"),
                    yaxis=dict(automargin=True),
                    height=max(400, len(plot_sg) * 30 + 80),
                    showlegend=False,
                )
                st.plotly_chart(fig_sg, use_container_width=True)

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
    elif page == "📋 Full Roster":
        st.markdown(
            "<p class='section-label'>Roster</p>"
            "<p class='section-title'>Full Tutor Roster</p>",
            unsafe_allow_html=True,
        )

        roster = (
            filt[["tutor", "manager", "tier", "tutor_type", "brand_composition",
                  "delivery_target", "hire_date", "tenure_years"]]
            .rename(columns={
                "tutor": "Tutor", "manager": "Faculty Leader", "tier": "Tier",
                "tutor_type": "Type", "brand_composition": "Brand",
                "delivery_target": "Del. Target", "hire_date": "Hire Date",
                "tenure_years": "Tenure (yr)",
            })
            .sort_values(["Faculty Leader", "Tutor"])
        )
        roster["Hire Date"] = roster["Hire Date"].dt.strftime("%Y-%m-%d")

        search = st.text_input("🔍 Search tutor name", placeholder="Type to filter...")
        if search:
            roster = roster[roster["Tutor"].str.contains(search, case=False, na=False)]

        st.dataframe(roster, hide_index=True, use_container_width=True,
                     height=min(700, len(roster) * 35 + 60))

        st.download_button(
            "📥 Download Roster CSV",
            data=roster.to_csv(index=False).encode("utf-8"),
            file_name=f"tutor_roster_{date.today().isoformat()}.csv",
            mime="text/csv",
        )
