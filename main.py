import streamlit as st
import toml
import importlib
import os

# --- Streamlit page config ---
st.set_page_config(page_title="Instruction Leader Dashboard", layout="wide")

# --- Mapping of IL -> secrets file ---
IL_CONFIGS = {
    "Jamie": "configs/jamie_secrets.toml",
    "Score Guarantee": "configs/score_guarantee_secrets.toml",
}

# --- Load universal config ---
CONFIG_FILE = "config.toml"
config = toml.load(CONFIG_FILE) if os.path.exists(CONFIG_FILE) else {}

# --- Initialize session state ---
if "authenticated" not in st.session_state:
    st.session_state["authenticated"] = False
if "il_choice" not in st.session_state:
    st.session_state["il_choice"] = None

# --- Login form (sidebar) ---
if not st.session_state["authenticated"]:
    with st.sidebar.form("login_form"):
        il_input = st.selectbox(
            "Select Dashboard:",
            list(IL_CONFIGS.keys()),
            index=0
        )
        password_input = st.text_input(
            "Enter password:",
            type="password"
        )
        submitted = st.form_submit_button("Login")

    if submitted:
        secrets_file = IL_CONFIGS[il_input]
        correct_password = ""
        if os.path.exists(secrets_file):
            secrets_data = toml.load(secrets_file)
            correct_password = secrets_data.get("auth", {}).get("password", "")
        if password_input == correct_password:
            st.session_state["authenticated"] = True
            st.session_state["il_choice"] = il_input
        else:
            st.error("Incorrect password")
            st.stop()

# --- Logout button (sidebar) ---
if st.session_state["authenticated"]:
    with st.sidebar:
        if st.button("Logout"):
            st.session_state["authenticated"] = False
            st.session_state["il_choice"] = None
            st.experimental_rerun()

# --- Dashboard content ---
if st.session_state["authenticated"] and st.session_state["il_choice"]:
    st.success(f"Authenticated! Loading {st.session_state['il_choice']} dashboard...")
    choice = st.session_state["il_choice"]
    module_name = f"InstructionLeader_Dashboard.{choice.lower().replace(' ', '_')}"
    dashboard_module = importlib.import_module(module_name)
    dashboard_module.render_app(config)