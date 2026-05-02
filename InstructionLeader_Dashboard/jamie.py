"""
Jamie — Instruction Leader Dashboard
─────────────────────────────────────
Team-by-team overview: headcount, tiers, tenure, BUC/PT composition.
"""

import streamlit as st
import pandas as pd
import numpy as np
import psycopg2
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import date, datetime


# ══════════════════════════════════════════════════════════════════════════════
def render_app(config):
# ══════════════════════════════════════════════════════════════════════════════

    # ── Custom CSS ────────────────────────────────────────────────────────────
    st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Source+Serif+4:wght@400;600;700&family=DM+Sans:wght@300;400;500;600;700&display=swap');

    html, body, [class*="css"] {
        font-family: 'DM Sans', sans-serif;
    }

    .stApp {
        background: #0b0f19;
        color: #e2dfd8;
    }

    /* Sidebar */
    [data-testid="stSidebar"] {
        background: #111827 !important;
        border-right: 1px solid #1e293b;
    }
    [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p {
        color: #94a3b8;
    }

    /* Headers */
    h1, h2, h3 {
        font-family: 'Source Serif 4', serif !important;
        color: #f1efe9 !important;
    }

    /* Metric cards */
    [data-testid="metric-container"] {
        background: #111827;
        border: 1px solid #1e293b;
        border-radius: 10px;
        padding: 16px 20px;
    }
    [data-testid="metric-container"] label {
        color: #64748b !important;
        font-size: 0.75rem !important;
        letter-spacing: 0.1em;
        text-transform: uppercase;
        font-weight: 600;
    }
    [data-testid="metric-container"] [data-testid="stMetricValue"] {
        color: #f8fafc !important;
        font-size: 1.9rem !important;
        font-family: 'Source Serif 4', serif !important;
    }
    [data-testid="metric-container"] [data-testid="stMetricDelta"] > div {
        font-size: 0.8rem !important;
    }

    /* Tabs */
    .stTabs [data-baseweb="tab-list"] {
        gap: 0px;
        background: #111827;
        border-radius: 8px;
        padding: 4px;
    }
    .stTabs [data-baseweb="tab"] {
        border-radius: 6px;
        padding: 8px 20px;
        color: #94a3b8;
        font-weight: 500;
    }
    .stTabs [aria-selected="true"] {
        background: #1e293b !important;
        color: #f8fafc !important;
    }

    /* Dataframes */
    [data-testid="stDataFrame"] {
        border: 1px solid #1e293b;
        border-radius: 8px;
    }

    /* Divider */
    hr {
        border-color: #1e293b !important;
    }

    /* Section header helper */
    .section-label {
        font-family: 'DM Sans', sans-serif;
        font-size: 0.7rem;
        font-weight: 600;
        letter-spacing: 0.15em;
        text-transform: uppercase;
        color: #475569;
        margin-bottom: 4px;
    }
    .section-title {
        font-family: 'Source Serif 4', serif;
        font-size: 1.6rem;
        color: #f1efe9;
        margin-bottom: 16px;
    }

    /* Hide hamburger + footer */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    </style>
    """, unsafe_allow_html=True)

    # ── Redshift connection ──────────────────────────────────────────────────
    @st.cache_resource
    def get_redshift_connection():
        creds = st.secrets["redshift"]
        return psycopg2.connect(
            host=creds["host"],
            port=int(creds["port"]),
            dbname=creds["database"],
            user=creds["user"],
            password=creds["password"],
        )

    @st.cache_data(ttl=3600)
    def load_team_data():
        """Pull active tutor roster with team, tier, tenure, and BUC/PT info."""
        query = """
        SELECT DISTINCT
            e1.id AS tutor_id,
            t_users.first_name||' '||t_users.last_name AS tutor,
            m_users.first_name||' '||m_users.last_name AS manager,
            date(e1.hire_date) AS hire_date,
            tiers.name AS tier,
            e1.delivery_target,
            CASE WHEN e1.delivery_target < 30
                THEN 'Adjunct'
                ELSE 'Professional'
            END AS tutor_type,
            CASE WHEN e1.tier_id = 1
                THEN TRUE
                ELSE FALSE
            END AS buc_only,
            CASE WHEN e1.tier_id > 1
                    AND bp.brand_id = 42
                THEN TRUE
                ELSE FALSE
            END AS buc_and_pt,
            CASE WHEN e1.tier_id > 1
                    AND bp.brand_id IS NULL
                THEN TRUE
                ELSE FALSE
            END AS pt_only
        FROM dw.employees e1
            JOIN dw.team_members
                ON team_members.member_id = e1.id
            JOIN dw.teams
                ON teams.id = team_members.team_id
            JOIN dw.users t_users
                ON e1.user_id = t_users.id
            JOIN dw.employees e2
                ON e2.id = teams.manager_id
            JOIN dw.users m_users
                ON e2.user_id = m_users.id
            JOIN dw.tiers
                ON e1.tier_id = tiers.id
            LEFT JOIN orbit_stitch.brand_permissions bp
                ON (bp.user_id = t_users.id
                AND bp.brand_id = 42)
        WHERE 1 = 1
            AND e1.type = 'Tutor'
            AND e1.end_date IS NULL
            AND e1.tier_id IS NOT NULL
            AND t_users.title = 'Tutor'
        ORDER BY 1
        """
        conn = get_redshift_connection()
        df = pd.read_sql(query, conn)

        # Compute tenure
        today = pd.Timestamp(date.today())
        df["hire_date"] = pd.to_datetime(df["hire_date"])
        df["tenure_days"] = (today - df["hire_date"]).dt.days
        df["tenure_years"] = (df["tenure_days"] / 365.25).round(1)

        # Determine brand composition label
        df["brand_composition"] = np.where(
            df["buc_only"], "BUC Only",
            np.where(df["buc_and_pt"], "BUC & PT", "PT Only")
        )

        return df

    # ── Load data ─────────────────────────────────────────────────────────────
    try:
        df = load_team_data()
    except Exception as e:
        st.error(f"Could not connect to Redshift: {e}")
        st.stop()

    managers = sorted(df["manager"].unique())

    # ── Sidebar ───────────────────────────────────────────────────────────────
    with st.sidebar:
        st.markdown(
            "<p style='font-family: Source Serif 4, serif; font-size:1.4rem; "
            "color:#f1efe9; margin-bottom:0;'>Team Overview</p>"
            "<p style='color:#475569; font-size:0.8rem; margin-top:0;'>Instruction Leader Dashboard</p>",
            unsafe_allow_html=True,
        )
        st.divider()

        selected_managers = st.multiselect(
            "Filter by Faculty Leader",
            options=managers,
            default=managers,
            help="Select one or more FLs to compare",
        )

        st.divider()
        st.markdown(
            f"<p style='color:#475569; font-size:0.75rem;'>"
            f"Data as of {date.today().strftime('%B %d, %Y')}<br>"
            f"Total active tutors: {len(df)}</p>",
            unsafe_allow_html=True,
        )

        if st.button("🔄 Refresh Data", use_container_width=True):
            st.cache_data.clear()
            st.rerun()

    # Filter
    filt = df[df["manager"].isin(selected_managers)].copy()

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

    # ── Tabs ──────────────────────────────────────────────────────────────────
    tab_team, tab_tier, tab_tenure, tab_brand, tab_roster = st.tabs([
        "👥 Team Counts", "📊 Tier Breakdown", "⏳ Tenure", "🔀 BUC / PT Split", "📋 Full Roster"
    ])

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # TAB 1 — TEAM COUNTS
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    with tab_team:
        st.markdown(
            "<p class='section-label'>Team Size</p>"
            "<p class='section-title'>Headcount by Faculty Leader</p>",
            unsafe_allow_html=True,
        )

        # Summary table
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
                x=team_summary["Faculty Leader"],
                y=team_summary["professional"],
                name="Professional",
                marker_color="#3b82f6",
                text=team_summary["professional"],
                textposition="inside",
                textfont=dict(size=13, color="white"),
            ))
            fig.add_trace(go.Bar(
                x=team_summary["Faculty Leader"],
                y=team_summary["adjunct"],
                name="Adjunct",
                marker_color="#64748b",
                text=team_summary["adjunct"],
                textposition="inside",
                textfont=dict(size=13, color="white"),
            ))
            fig.update_layout(
                barmode="stack",
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
                font=dict(family="DM Sans", color="#94a3b8"),
                legend=dict(orientation="h", y=1.08, x=0.5, xanchor="center",
                            font=dict(size=12)),
                margin=dict(l=40, r=20, t=40, b=60),
                xaxis=dict(tickangle=-30, gridcolor="rgba(30,41,59,0.5)"),
                yaxis=dict(gridcolor="rgba(30,41,59,0.5)", title="Tutor Count"),
                height=400,
            )
            st.plotly_chart(fig, use_container_width=True)

        with col_table:
            st.dataframe(
                team_summary.rename(columns={
                    "total_tutors": "Total",
                    "professional": "Professional",
                    "adjunct": "Adjunct",
                    "avg_delivery_target": "Avg Del. Target",
                }),
                hide_index=True,
                use_container_width=True,
                height=400,
            )

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # TAB 2 — TIER BREAKDOWN
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    with tab_tier:
        st.markdown(
            "<p class='section-label'>Tiers</p>"
            "<p class='section-title'>Tier Distribution by Team</p>",
            unsafe_allow_html=True,
        )

        tier_pivot = (
            filt.groupby(["manager", "tier"])
            .size()
            .reset_index(name="count")
        )
        tier_order = filt["tier"].value_counts().index.tolist()

        # Palette for tiers
        tier_colors = {
            tier: color for tier, color in zip(
                tier_order,
                ["#3b82f6", "#8b5cf6", "#06b6d4", "#f59e0b", "#10b981",
                 "#ef4444", "#ec4899", "#64748b", "#a78bfa", "#34d399"]
            )
        }

        col_hbar, col_pies = st.columns([1.4, 1])

        with col_hbar:
            fig2 = go.Figure()
            for tier in tier_order:
                subset = tier_pivot[tier_pivot["tier"] == tier]
                fig2.add_trace(go.Bar(
                    y=subset["manager"],
                    x=subset["count"],
                    name=tier,
                    orientation="h",
                    marker_color=tier_colors.get(tier, "#64748b"),
                    text=subset["count"],
                    textposition="inside",
                    textfont=dict(size=12, color="white"),
                ))
            fig2.update_layout(
                barmode="stack",
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
                font=dict(family="DM Sans", color="#94a3b8"),
                legend=dict(orientation="h", y=-0.15, x=0.5, xanchor="center",
                            font=dict(size=11)),
                margin=dict(l=10, r=20, t=20, b=60),
                xaxis=dict(gridcolor="rgba(30,41,59,0.5)", title="Tutor Count"),
                yaxis=dict(automargin=True),
                height=max(300, len(selected_managers) * 55 + 100),
            )
            st.plotly_chart(fig2, use_container_width=True)

        with col_pies:
            # Overall tier distribution
            overall_tier = filt["tier"].value_counts().reset_index()
            overall_tier.columns = ["tier", "count"]
            fig_pie = go.Figure(go.Pie(
                labels=overall_tier["tier"],
                values=overall_tier["count"],
                marker=dict(colors=[tier_colors.get(t, "#64748b") for t in overall_tier["tier"]]),
                textinfo="label+percent",
                textfont=dict(size=12, color="white"),
                hole=0.45,
            ))
            fig_pie.update_layout(
                title=dict(text="Overall Tier Mix", font=dict(size=14, color="#94a3b8"),
                           x=0.5, xanchor="center"),
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
                font=dict(family="DM Sans", color="#94a3b8"),
                showlegend=False,
                margin=dict(l=10, r=10, t=40, b=10),
                height=350,
            )
            st.plotly_chart(fig_pie, use_container_width=True)

        # Tier detail table
        tier_detail = (
            filt.pivot_table(index="manager", columns="tier", values="tutor_id",
                             aggfunc="count", fill_value=0)
            .reset_index()
            .rename(columns={"manager": "Faculty Leader"})
        )
        tier_detail["Total"] = tier_detail.iloc[:, 1:].sum(axis=1)
        tier_detail = tier_detail.sort_values("Total", ascending=False)
        st.dataframe(tier_detail, hide_index=True, use_container_width=True)

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # TAB 3 — TENURE
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    with tab_tenure:
        st.markdown(
            "<p class='section-label'>Tenure</p>"
            "<p class='section-title'>Team Tenure Analysis</p>",
            unsafe_allow_html=True,
        )

        tenure_stats = (
            filt.groupby("manager")["tenure_years"]
            .agg(["mean", "median", "min", "max", "count"])
            .reset_index()
            .rename(columns={
                "manager": "Faculty Leader",
                "mean": "Avg (yr)",
                "median": "Median (yr)",
                "min": "Min (yr)",
                "max": "Max (yr)",
                "count": "Tutors",
            })
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
                    y=mgr_data,
                    name=mgr,
                    boxmean=True,
                    marker_color="#3b82f6",
                    line_color="#60a5fa",
                    fillcolor="rgba(59,130,246,0.15)",
                ))
            fig3.update_layout(
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
                font=dict(family="DM Sans", color="#94a3b8"),
                margin=dict(l=40, r=20, t=20, b=60),
                yaxis=dict(gridcolor="rgba(30,41,59,0.5)", title="Tenure (years)"),
                xaxis=dict(tickangle=-30),
                showlegend=False,
                height=420,
            )
            st.plotly_chart(fig3, use_container_width=True)

        with col_stats:
            st.dataframe(tenure_stats, hide_index=True, use_container_width=True, height=420)

        # Tenure histogram — all tutors
        st.markdown("")
        fig_hist = go.Figure(go.Histogram(
            x=filt["tenure_years"],
            nbinsx=20,
            marker_color="#3b82f6",
            opacity=0.85,
        ))
        fig_hist.update_layout(
            title=dict(text="Tenure Distribution (All Filtered Tutors)",
                       font=dict(size=14, color="#94a3b8"), x=0.5, xanchor="center"),
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
            font=dict(family="DM Sans", color="#94a3b8"),
            xaxis=dict(title="Years", gridcolor="rgba(30,41,59,0.5)"),
            yaxis=dict(title="Count", gridcolor="rgba(30,41,59,0.5)"),
            margin=dict(l=40, r=20, t=50, b=40),
            height=300,
        )
        st.plotly_chart(fig_hist, use_container_width=True)

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # TAB 4 — BUC / PT SPLIT
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    with tab_brand:
        st.markdown(
            "<p class='section-label'>Brand Composition</p>"
            "<p class='section-title'>BUC vs. Private Tutoring Split</p>",
            unsafe_allow_html=True,
        )

        brand_colors = {
            "BUC Only": "#f59e0b",
            "BUC & PT": "#8b5cf6",
            "PT Only": "#10b981",
        }

        brand_pivot = (
            filt.groupby(["manager", "brand_composition"])
            .size()
            .reset_index(name="count")
        )

        col_brand_chart, col_brand_table = st.columns([1.3, 1])

        with col_brand_chart:
            fig4 = go.Figure()
            for comp in ["BUC Only", "BUC & PT", "PT Only"]:
                subset = brand_pivot[brand_pivot["brand_composition"] == comp]
                fig4.add_trace(go.Bar(
                    x=subset["manager"],
                    y=subset["count"],
                    name=comp,
                    marker_color=brand_colors[comp],
                    text=subset["count"],
                    textposition="inside",
                    textfont=dict(size=12, color="white"),
                ))
            fig4.update_layout(
                barmode="stack",
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
                font=dict(family="DM Sans", color="#94a3b8"),
                legend=dict(orientation="h", y=1.08, x=0.5, xanchor="center",
                            font=dict(size=12)),
                margin=dict(l=40, r=20, t=40, b=60),
                xaxis=dict(tickangle=-30, gridcolor="rgba(30,41,59,0.5)"),
                yaxis=dict(gridcolor="rgba(30,41,59,0.5)", title="Tutor Count"),
                height=400,
            )
            st.plotly_chart(fig4, use_container_width=True)

        with col_brand_table:
            brand_detail = (
                filt.pivot_table(index="manager", columns="brand_composition",
                                 values="tutor_id", aggfunc="count", fill_value=0)
                .reset_index()
                .rename(columns={"manager": "Faculty Leader"})
            )
            brand_detail["Total"] = brand_detail.iloc[:, 1:].sum(axis=1)
            brand_detail = brand_detail.sort_values("Total", ascending=False)
            st.dataframe(brand_detail, hide_index=True, use_container_width=True, height=400)

        # Overall brand composition donut
        st.markdown("")
        ov_brand = filt["brand_composition"].value_counts().reset_index()
        ov_brand.columns = ["brand_composition", "count"]

        c1, c2, c3 = st.columns([1, 1, 1])
        with c2:
            fig_donut = go.Figure(go.Pie(
                labels=ov_brand["brand_composition"],
                values=ov_brand["count"],
                marker=dict(colors=[brand_colors.get(b, "#64748b")
                                    for b in ov_brand["brand_composition"]]),
                textinfo="label+value+percent",
                textfont=dict(size=13, color="white"),
                hole=0.5,
            ))
            fig_donut.update_layout(
                title=dict(text="Overall Brand Composition",
                           font=dict(size=14, color="#94a3b8"),
                           x=0.5, xanchor="center"),
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
                font=dict(family="DM Sans", color="#94a3b8"),
                showlegend=False,
                margin=dict(l=10, r=10, t=40, b=10),
                height=350,
            )
            st.plotly_chart(fig_donut, use_container_width=True)

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # TAB 5 — FULL ROSTER
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    with tab_roster:
        st.markdown(
            "<p class='section-label'>Roster</p>"
            "<p class='section-title'>Full Tutor Roster</p>",
            unsafe_allow_html=True,
        )

        roster = (
            filt[["tutor", "manager", "tier", "tutor_type", "brand_composition",
                  "delivery_target", "hire_date", "tenure_years"]]
            .rename(columns={
                "tutor": "Tutor",
                "manager": "Faculty Leader",
                "tier": "Tier",
                "tutor_type": "Type",
                "brand_composition": "Brand",
                "delivery_target": "Del. Target",
                "hire_date": "Hire Date",
                "tenure_years": "Tenure (yr)",
            })
            .sort_values(["Faculty Leader", "Tutor"])
        )
        roster["Hire Date"] = roster["Hire Date"].dt.strftime("%Y-%m-%d")

        # Search
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