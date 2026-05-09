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
    @st.cache_resource
    def get_redshift_connection():
        creds = st.secrets["redshift"]
        return psycopg2.connect(
            host=creds["host"], port=int(creds["port"]),
            dbname=creds["database"], user=creds["user"], password=creds["password"],
        )

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
    def load_meeting_data():
        today = date.today()
        day_end = today.strftime("%Y-%m-%d")
        day_start = (today - pd.DateOffset(years=2)).strftime("%Y-%m-%d")
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
            cte_group_meetings.attended_meetings AS attended_group_meetings
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

    # ── Load data ─────────────────────────────────────────────────────────────
    try:
        df = load_team_data()
        df_meetings = load_meeting_data()
        df_restricted = load_restricted_data()
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

    # ── Top-level metrics ─────────────────────────────────────────────────────
    st.markdown(
        "<p class='section-label'>Overview</p>"
        "<p class='section-title'>Team Composition at a Glance</p>",
        unsafe_allow_html=True,
    )

    m1, m2, m3, m4, m5, m6 = st.columns(6)
    m1.metric("Total Tutors", len(filt))
    m2.metric("Faculty Leaders", filt["manager"].nunique())
    m3.metric("Avg Tenure (yr)", f"{filt['tenure_years'].mean():.1f}")
    m4.metric("Professional", len(filt[filt["tutor_type"] == "Professional"]))
    m5.metric("Adjunct", len(filt[filt["tutor_type"] == "Adjunct"]))
    m6.metric("Avg Delivery Target", f"{filt['delivery_target'].mean():.0f}")

    st.markdown("")

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
        st.markdown(
            "<p class='section-label'>Restricted Tutors</p>"
            "<p class='section-title'>Current & Historical Restricted Status</p>",
            unsafe_allow_html=True,
        )

        # Current restricted tutors
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

            # Individual tutor detail
            st.markdown("")
            curr_display = (
                currently_restricted[["employee_name", "team", "tier", "update_type",
                                      "status_starts_at", "days_in_effect"]]
                .rename(columns={
                    "employee_name": "Tutor", "team": "Team", "tier": "Tier",
                    "update_type": "Set By", "status_starts_at": "Restricted Since",
                    "days_in_effect": "Days Restricted",
                })
                .sort_values("Days Restricted", ascending=False)
            )
            curr_display["Restricted Since"] = curr_display["Restricted Since"].dt.strftime("%Y-%m-%d")
            curr_display["Days Restricted"] = curr_display["Days Restricted"].astype(int)
            st.dataframe(curr_display, hide_index=True, use_container_width=True)

        else:
            st.success("No tutors are currently on restricted status.")

        # Historical restricted status
        st.markdown("")
        st.markdown(
            "<p class='section-label'>History</p>"
            "<p class='section-title'>Restricted Status History (Since Jan 2025)</p>",
            unsafe_allow_html=True,
        )

        hist_restricted = df_restricted[df_restricted["current_status_flag"] == 0].copy()

        if len(hist_restricted) > 0:
            # Count of restriction events by team
            hist_by_team = (
                hist_restricted.groupby("team")
                .agg(
                    events=("employee_id", "count"),
                    unique_tutors=("employee_id", "nunique"),
                    avg_days=("days_in_effect", "mean"),
                )
                .reset_index()
                .rename(columns={"team": "Team"})
                .sort_values("events", ascending=False)
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
                df_restricted[["employee_name", "team", "tier", "update_type",
                                "status_starts_at", "status_ends_at", "days_in_effect",
                                "current_status_flag"]]
                .rename(columns={
                    "employee_name": "Tutor", "team": "Team", "tier": "Tier",
                    "update_type": "Set By", "status_starts_at": "Start",
                    "status_ends_at": "End", "days_in_effect": "Days",
                    "current_status_flag": "Current",
                })
                .sort_values("Start", ascending=False)
            )
            hist_display["Start"] = hist_display["Start"].dt.strftime("%Y-%m-%d")
            hist_display["End"] = hist_display["End"].dt.strftime("%Y-%m-%d").fillna("Present")
            hist_display["Days"] = hist_display["Days"].fillna(0).astype(int)
            hist_display["Current"] = hist_display["Current"].map({1: "Yes", 0: "No"})

            hist_search = st.text_input("🔍 Search tutor", placeholder="Type to filter...", key="restr_search")
            if hist_search:
                hist_display = hist_display[hist_display["Tutor"].str.contains(hist_search, case=False, na=False)]

            st.dataframe(hist_display, hide_index=True, use_container_width=True,
                         height=min(600, len(hist_display) * 35 + 60))
        else:
            st.info("No historical restriction events found since Jan 2025.")


    # ══════════════════════════════════════════════════════════════════════════
    # PAGE — MEETINGS
    # ══════════════════════════════════════════════════════════════════════════
    elif page == "📅 Meetings":
        st.markdown(
            "<p class='section-label'>Meeting Frequency</p>"
            "<p class='section-title'>1-on-1 & Group Meetings (Jan–Apr 2026)</p>",
            unsafe_allow_html=True,
        )

        mtg = df_meetings[df_meetings["faculty_leader"].isin(selected_managers)].copy()

        mm1, mm2, mm3, mm4 = st.columns(4)
        mm1.metric("Avg 1:1s per Tutor", f"{mtg['attended_1on1_meetings'].mean():.1f}")
        mm2.metric("Avg 1:1 Hours", f"{mtg['1on1_meeting_hours'].mean():.1f}")
        mm3.metric("Avg Group Meetings", f"{mtg['attended_group_meetings'].mean():.1f}")
        avg_days = mtg["days_since_last_1on1"].mean()
        mm4.metric("Avg Days Since Last 1:1", f"{avg_days:.0f}" if not pd.isna(avg_days) else "—")

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

        mtg_display = (
            mtg[["faculty_leader", "tutor", "tutor_type", "attended_1on1_meetings",
                 "1on1_meeting_hours", "last_attended_1on1", "days_since_last_1on1",
                 "attended_group_meetings"]]
            .rename(columns={
                "faculty_leader": "Faculty Leader", "tutor": "Tutor", "tutor_type": "Type",
                "attended_1on1_meetings": "1:1 Count", "1on1_meeting_hours": "1:1 Hours",
                "last_attended_1on1": "Last 1:1", "days_since_last_1on1": "Days Since",
                "attended_group_meetings": "Group Mtgs",
            })
            .sort_values(["Faculty Leader", "Days Since"], ascending=[True, False])
        )
        mtg_display["Last 1:1"] = mtg_display["Last 1:1"].dt.strftime("%Y-%m-%d")

        mtg_search = st.text_input("🔍 Search tutor", placeholder="Type to filter...", key="mtg_search")
        if mtg_search:
            mtg_display = mtg_display[mtg_display["Tutor"].str.contains(mtg_search, case=False, na=False)]

        st.dataframe(mtg_display, hide_index=True, use_container_width=True,
                     height=min(600, len(mtg_display) * 35 + 60))

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
