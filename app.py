import asyncio
import json
import os
import re
import uuid
from datetime import datetime
from pathlib import Path

import httpx
import pandas as pd
import requests
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

# --------------------------- Configuration ---------------------------
st.set_page_config(
    page_title="Lead Intelligence | Social House Learning CRM",
    page_icon="☁️",
    layout="wide",
    initial_sidebar_state="expanded",
)

DATA_DIR = Path(__file__).parent / "data"
DB_FILE = DATA_DIR / "leads.json"
STATUSES = ["New", "Contacted", "Qualified", "Converted", "Lost"]
TEXT_COLUMNS = ["id", "name", "email", "phone", "business_name", "status", "created_at", "updated_at"]
REQUEST_TIMEOUT = 25


# --------------------------- Google Sheets API ---------------------------
def get_api_url() -> str:
    """Read the Apps Script deployment URL from environment or Streamlit secrets."""
    url = os.getenv("SHL_SHEETS_API_URL", "").strip()
    if not url:
        try:
            url = str(st.secrets.get("SHL_SHEETS_API_URL", "")).strip()
        except Exception:
            url = ""
    return url


API_URL = get_api_url()


@st.cache_resource
def get_http_session() -> requests.Session:
    """Reuse TCP/TLS connections across requests to reduce handshake overhead."""
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})
    return session


def api_request(method: str, payload: dict | None = None) -> dict:
    if not API_URL:
        raise RuntimeError(
            "Google Sheets API URL is missing. Set SHL_SHEETS_API_URL in your environment "
            "or .streamlit/secrets.toml."
        )
    session = get_http_session()
    try:
        if method == "GET":
            response = session.get(API_URL, timeout=REQUEST_TIMEOUT)
        else:
            response = session.post(API_URL, json=payload, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        result = response.json()
    except requests.RequestException as exc:
        raise RuntimeError(f"Could not connect to Google Sheets: {exc}") from exc
    except ValueError as exc:
        raise RuntimeError(
            "The Apps Script did not return JSON. Check that you deployed the latest version "
            "as a Web App and copied the URL ending in /exec."
        ) from exc

    if not isinstance(result, dict) or not result.get("success"):
        message = (
            result.get("error", "Unknown Google Sheets API error")
            if isinstance(result, dict)
            else "Invalid API response"
        )
        raise RuntimeError(message)
    return result


@st.cache_data(ttl=60, show_spinner=False)
def load_leads() -> list[dict]:
    """Cache leads for 60s so tab switches, searches, and edits don't block on network I/O."""
    result = api_request("GET")
    leads = result.get("leads", [])
    if not isinstance(leads, list):
        raise RuntimeError("Google Sheets returned an invalid leads list.")
    return leads


def valid_email(email: str) -> bool:
    return re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email.strip()) is not None


def format_sheet_phone(phone: str) -> str:
    """Prefix with apostrophe so Google Sheets stores phone numbers strictly as text."""
    cleaned = str(phone or "").strip()
    if cleaned and not cleaned.startswith("'"):
        return f"'{cleaned}"
    return cleaned


def _clean_phone_for_json(phone: str) -> str:
    """Strip leading apostrophe used for Google Sheets text formatting before saving JSON."""
    cleaned = str(phone or "").strip()
    return cleaned[1:] if cleaned.startswith("'") else cleaned


def write_local_leads_json(records: list[dict]) -> None:
    """Atomically write normalized lead records to data/leads.json."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    normalized = []
    for item in records:
        rec = {col: str(item.get(col) or "") for col in TEXT_COLUMNS}
        rec["phone"] = _clean_phone_for_json(rec["phone"])
        normalized.append(rec)

    tmp_file = DB_FILE.with_suffix(".json.tmp")
    tmp_file.write_text(json.dumps(normalized, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp_file, DB_FILE)


def sync_local_json_from_leads(records: list[dict]) -> None:
    """Best-effort sync of data/leads.json so every mutation or sync reflects locally."""
    try:
        write_local_leads_json(records)
    except OSError as exc:
        st.toast(f"Sheets updated, but local JSON sync failed: {exc}", icon="⚠️")


def _get_current_leads_uncached() -> list[dict]:
    result = api_request("GET")
    records = result.get("leads", [])
    return records if isinstance(records, list) else []


def add_lead(name: str, email: str, phone: str, business: str, status: str) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    lead_id = str(uuid.uuid4())
    sheet_lead = {
        "id": lead_id,
        "name": name.strip(),
        "email": email.strip().lower(),
        "phone": format_sheet_phone(phone),
        "business_name": business.strip(),
        "status": status,
        "created_at": now,
        "updated_at": now,
    }
    api_request("POST", {"action": "add", "lead": sheet_lead})
    load_leads.clear()

    current = _get_current_leads_uncached()
    if not any(str(x.get("id")) == lead_id for x in current):
        current.append({**sheet_lead, "phone": _clean_phone_for_json(phone)})
    sync_local_json_from_leads(current)


def update_lead(lead_id: str, name: str, email: str, phone: str, business: str, status: str) -> bool:
    now = datetime.now().isoformat(timespec="seconds")
    sheet_lead = {
        "id": lead_id,
        "name": name.strip(),
        "email": email.strip().lower(),
        "phone": format_sheet_phone(phone),
        "business_name": business.strip(),
        "status": status,
        "updated_at": now,
    }
    api_request("POST", {"action": "update", "lead": sheet_lead})
    load_leads.clear()

    current = _get_current_leads_uncached()
    updated_records = []
    for row in current:
        if str(row.get("id")) == str(lead_id):
            merged = dict(row)
            merged.update({**sheet_lead, "phone": _clean_phone_for_json(phone)})
            updated_records.append(merged)
        else:
            updated_records.append(row)
    sync_local_json_from_leads(updated_records)
    return True


def delete_lead(lead_id: str) -> bool:
    api_request("POST", {"action": "delete", "id": lead_id})
    load_leads.clear()

    current = _get_current_leads_uncached()
    remaining = [row for row in current if str(row.get("id")) != str(lead_id)]
    sync_local_json_from_leads(remaining)
    return True


async def _post_lead_async(
    client: httpx.AsyncClient, semaphore: asyncio.Semaphore, lead: dict
) -> None:
    """Send a single lead creation request asynchronously with concurrency throttling."""
    async with semaphore:
        resp = await client.post(API_URL, json={"action": "add", "lead": lead})
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, dict) or not data.get("success"):
            raise RuntimeError(data.get("error", "Failed to import lead"))


async def _import_leads_concurrently(leads_to_import: list[dict]) -> None:
    """Run multiple Apps Script POST requests concurrently (max 5 in flight)."""
    semaphore = asyncio.Semaphore(5)
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT, follow_redirects=True) as client:
        tasks = [_post_lead_async(client, semaphore, lead) for lead in leads_to_import]
        await asyncio.gather(*tasks)


def import_local_json_to_sheets(existing_leads: list[dict]) -> tuple[int, int]:
    """Concurrent migration of local JSON records not already in the Sheet."""
    if not DB_FILE.exists():
        return 0, 0
    try:
        local_leads = json.loads(DB_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise RuntimeError(f"Could not read local JSON backup: {exc}") from exc
    if not isinstance(local_leads, list):
        raise RuntimeError("data/leads.json must contain a JSON list.")

    existing_ids = {str(x.get("id", "")) for x in existing_leads}
    existing_emails = {str(x.get("email", "")).lower() for x in existing_leads}

    to_import = []
    skipped = 0
    for lead in local_leads:
        email = str(lead.get("email", "")).lower()
        lead_id = str(lead.get("id", ""))
        if (lead_id and lead_id in existing_ids) or (email and email in existing_emails):
            skipped += 1
            continue
        lead_copy = dict(lead)
        lead_copy["phone"] = format_sheet_phone(lead_copy.get("phone", ""))
        to_import.append(lead_copy)
        if lead_id:
            existing_ids.add(lead_id)
        if email:
            existing_emails.add(email)

    if to_import:
        asyncio.run(_import_leads_concurrently(to_import))
        load_leads.clear()
        refreshed = _get_current_leads_uncached()
        sync_local_json_from_leads(refreshed)

    return len(to_import), skipped


# --------------------------- Social House Learning Theme CSS ---------------------------
# Edit the colour tokens in :root to match your brand exactly (paste hex codes from the website).
st.markdown(
    """
<style>
@import url('https://fonts.googleapis.com/css2?family=Sora:wght@600;700;800&family=Inter:wght@400;500;600;700&display=swap');

:root {
    --bg: #0a1228;          /* page background */
    --bg-deep: #060c1f;     /* sidebar */
    --card: #141f42;        /* panels, cards */
    --field: #0f1936;       /* inputs */
    --line: #2a3a6b;        /* borders */
    --text: #f1f4ff;        /* main text */
    --muted: #a9b4da;       /* secondary text */
    --accent: #ffb52e;      /* brand accent (buttons, highlights) */
    --accent-ink: #1a1405;  /* text on accent */
    --blue: #4f8cff;
    --ok: #3ddc97;
    --danger: #ff6b81;
}

html, body, [class*="css"] {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
}
.stApp { background: var(--bg); color: var(--text); }
[data-testid="stHeader"] { background: transparent; }
.block-container { padding-top: 2.1rem; max-width: 1440px; }

h1, h2, h3, h4 {
    font-family: 'Sora', 'Inter', sans-serif;
    color: var(--text) !important;
    font-weight: 700;
    letter-spacing: -0.02em;
}

/* ---------- Make EVERY piece of text readable on the dark background ---------- */
.stApp p, .stApp li, .stApp label,
[data-testid="stMarkdownContainer"],
[data-testid="stMarkdownContainer"] *,
[data-testid="stWidgetLabel"],
[data-testid="stWidgetLabel"] *,
[data-testid="stCheckbox"] label,
[data-testid="stCheckbox"] label *,
[data-testid="stRadio"] label,
[data-testid="stRadio"] label * { color: var(--text) !important; }
small, [data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] * { color: var(--muted) !important; }

/* Inputs */
.stTextInput [data-baseweb="input"],
.stTextInput [data-baseweb="base-input"],
.stSelectbox [data-baseweb="select"] > div {
    background: var(--field) !important;
    border: 1px solid var(--line) !important;
    border-radius: 10px !important;
}
.stTextInput input {
    color: var(--text) !important;
    -webkit-text-fill-color: var(--text) !important;
    background: transparent !important;
}
.stTextInput input::placeholder { color: #7c89b5 !important; -webkit-text-fill-color: #7c89b5 !important; }
.stSelectbox [data-baseweb="select"] *,
.stSelectbox [data-baseweb="select"] svg { color: var(--text) !important; fill: var(--text) !important; }
.stTextInput [data-baseweb="input"]:focus-within,
.stSelectbox [data-baseweb="select"] > div:focus-within { border-color: var(--accent) !important; box-shadow: 0 0 0 1px var(--accent); }

/* Dropdown menus render in a portal outside .stApp */
[data-baseweb="popover"] [role="listbox"],
[data-baseweb="popover"] ul,
[data-baseweb="menu"] { background: var(--card) !important; }
[data-baseweb="popover"] li,
[data-baseweb="popover"] li * { color: var(--text) !important; }
[data-baseweb="popover"] li:hover,
[data-baseweb="popover"] li[aria-selected="true"] { background: #1f2d5c !important; }

/* Checkbox box */
[data-testid="stCheckbox"] [data-baseweb="checkbox"] > div:first-child {
    border-color: var(--muted) !important;
    background: var(--field) !important;
}

/* Alerts (st.info / success / error) */
[data-testid="stAlert"] {
    background: #16224a !important;
    border: 1px solid var(--line);
    border-radius: 10px;
}
[data-testid="stAlert"] *  { color: var(--text) !important; }

/* ---------- Sidebar ---------- */
[data-testid="stSidebar"] {
    background: var(--bg-deep);
    border-right: 1px solid var(--line);
}
[data-testid="stSidebar"] hr { border-color: var(--line); }
[data-testid="stSidebar"] .stButton button {
    background: var(--card);
    color: var(--text) !important;
    border: 1px solid var(--line);
    border-radius: 10px;
    font-weight: 600;
}
[data-testid="stSidebar"] .stButton button * { color: var(--text) !important; }
[data-testid="stSidebar"] .stButton button:hover { border-color: var(--accent); background: #1b2954; }
[data-testid="stSidebar"] .stButton button:disabled { opacity: .5; }
.sf-sidebar-eyebrow {
    color: var(--accent) !important;
    font-size: 0.72rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.14em;
}

/* ---------- Header banner ---------- */
.sf-eyebrow {
    color: var(--accent) !important;
    font-size: 0.74rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.14em;
}
.sf-page-header {
    background: linear-gradient(135deg, #16265a 0%, #0f1b42 60%, #14204a 100%);
    border: 1px solid var(--line);
    border-left: 5px solid var(--accent);
    border-radius: 14px;
    padding: 22px 26px;
    margin-bottom: 20px;
}
.sf-page-header h1 { color: var(--text) !important; }
.sf-page-header p { color: var(--muted) !important; }

/* ---------- KPI cards ---------- */
.metric-card {
    background: var(--card);
    border: 1px solid var(--line);
    border-top: 4px solid var(--accent);
    border-radius: 14px;
    padding: 16px 20px;
}
.metric-card.success { border-top-color: var(--ok); }
.metric-card.navy { border-top-color: var(--blue); }
.metric-label {
    color: var(--muted) !important;
    font-size: 0.74rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.1em;
}
.metric-value {
    color: var(--text) !important;
    font-family: 'Sora', sans-serif;
    font-size: 2rem;
    font-weight: 700;
    margin-top: 4px;
    line-height: 1.2;
}
.metric-note { color: var(--ok) !important; font-size: 0.78rem; font-weight: 500; margin-top: 4px; }

/* ---------- Panels (real bordered containers) ---------- */
div[data-testid="stVerticalBlockBorderWrapper"] {
    background: var(--card);
    border: 1px solid var(--line) !important;
    border-radius: 14px !important;
    padding: 8px 10px;
}
div[data-testid="stVerticalBlockBorderWrapper"] div[data-testid="stVerticalBlockBorderWrapper"] {
    background: transparent;
}
[data-testid="stForm"] { border: none !important; padding: 0 !important; }

/* ---------- Tabs ---------- */
.stTabs [data-baseweb="tab-list"] { gap: 8px; border-bottom: 1px solid var(--line); }
.stTabs [data-baseweb="tab"] { color: var(--muted) !important; font-weight: 600; padding: 12px 16px; }
.stTabs [data-baseweb="tab"] * { color: inherit !important; }
.stTabs [aria-selected="true"] { color: var(--accent) !important; }
.stTabs [data-baseweb="tab-highlight"] { background-color: var(--accent) !important; }
.stTabs [data-baseweb="tab-border"] { background-color: transparent !important; }

/* ---------- Buttons ---------- */
.stButton button, .stFormSubmitButton button {
    border-radius: 10px;
    font-weight: 700;
    transition: transform .12s ease, background .12s ease, border-color .12s ease;
}
.stButton button[kind="primary"],
.stFormSubmitButton button[kind="primary"],
[data-testid="stBaseButton-primary"],
[data-testid="stBaseButton-primaryFormSubmit"] {
    background: var(--accent) !important;
    border: 1px solid var(--accent) !important;
    color: var(--accent-ink) !important;
}
.stButton button[kind="primary"] *,
.stFormSubmitButton button[kind="primary"] *,
[data-testid="stBaseButton-primary"] *,
[data-testid="stBaseButton-primaryFormSubmit"] * { color: var(--accent-ink) !important; }
.stButton button[kind="primary"]:hover,
.stFormSubmitButton button[kind="primary"]:hover { filter: brightness(1.08); transform: translateY(-1px); }

/* Delete button (secondary) */
.stButton button[kind="secondary"],
[data-testid="stBaseButton-secondary"] {
    background: transparent;
    border: 1px solid var(--danger);
    color: var(--danger) !important;
}
.stButton button[kind="secondary"] *,
[data-testid="stBaseButton-secondary"] * { color: var(--danger) !important; }
.stButton button[kind="secondary"]:hover { background: rgba(255,107,129,.12); }
.stButton button:disabled { opacity: .55; cursor: not-allowed; }
[data-testid="stSidebar"] [data-testid="stBaseButton-secondary"] { border-color: var(--line); }
[data-testid="stSidebar"] [data-testid="stBaseButton-secondary"] * { color: var(--text) !important; }

/* ---------- Dataframes ---------- */
div[data-testid="stDataFrame"] {
    border: 1px solid var(--line);
    border-radius: 10px;
    overflow: hidden;
}
</style>
""",
    unsafe_allow_html=True,
)


# --------------------------- Data Load & Arrow Type Normalization ---------------------------
try:
    leads = load_leads()
    sync_local_json_from_leads(leads)
except Exception as exc:
    st.error(f"Google Sheets connection failed: {exc}")
    st.info("Check your Apps Script deployment URL and make sure the Web App is accessible.")
    st.stop()

df = pd.DataFrame(leads)
if df.empty:
    df = pd.DataFrame(columns=TEXT_COLUMNS)
else:
    for col in TEXT_COLUMNS:
        if col in df.columns:
            df[col] = df[col].fillna("").astype(str)
        else:
            df[col] = ""

total = len(df)
new_count = int((df["status"] == "New").sum()) if total else 0
converted_count = int((df["status"] == "Converted").sum()) if total else 0
conversion_rate = (converted_count / total * 100) if total else 0


# --------------------------- Sidebar ---------------------------
with st.sidebar:
    st.markdown('<div class="sf-sidebar-eyebrow">SOCIAL HOUSE LEARNING</div>', unsafe_allow_html=True)
    logo_path = Path(__file__).parent / "3b9704_e5a4b9038153439cb480077dd260c7f1_mv2-removebg-preview.png"
    if logo_path.exists():
        st.image(str(r"logo.png"), width="content")
    st.title("☁️ Lead CRM Console")
    st.caption("Pipeline & Lead Workspace")
    page = st.radio("NAVIGATION", ["Overview", "Manage leads"], label_visibility="visible")
    st.divider()
    st.caption("DATA & JSON MIRROR")
    if API_URL:
        st.success("Sheets + JSON Sync Active")
        if st.button("↻ Sync Latest Records", width='content'):
            load_leads.clear()
            st.rerun()
    else:
        st.error("API URL Not Configured")
        st.caption("Set SHL_SHEETS_API_URL in .env or secrets.toml")

    if st.button("Import Local JSON Backup", width='content', disabled=not bool(API_URL)):
        try:
            with st.spinner("Syncing leads concurrently..."):
                imported, skipped = import_local_json_to_sheets(leads)
            st.toast(f"Imported {imported} leads; skipped {skipped} existing.", icon="✅")
            st.rerun()
        except Exception as exc:
            st.error(str(exc))
    st.caption("This will add any leads in data/leads.json that are not already in the Google Sheet.")


# --------------------------- Header ---------------------------
st.markdown(
    """
    <div class="sf-page-header">
        <div class="sf-eyebrow">SHL / LEAD INTELLIGENCE</div>
        <h1 style="margin: 2px 0 4px 0; font-size: 1.75rem;">Lead Analytics & Pipeline Console</h1>
        <p style="margin: 0; font-size: 0.92rem;">
            Monitor pipeline & Status.
        </p>
    </div>
    """,
    unsafe_allow_html=True,
)


# --------------------------- Fragments ---------------------------
@st.fragment
def render_lead_directory(dataframe: pd.DataFrame, total_count: int) -> None:
    """Isolated fragment so typing in search doesn't rerun the entire page."""
    search_col, status_col = st.columns([2, 1])
    query = search_col.text_input("Search leads", placeholder="Search by name, email, or company...")
    status_filter = status_col.selectbox("Lead Status", ["All"] + STATUSES)

    filtered = dataframe
    if query:
        mask = (
            filtered["name"].str.contains(query, case=False, na=False)
            | filtered["email"].str.contains(query, case=False, na=False)
            | filtered["business_name"].str.contains(query, case=False, na=False)
        )
        filtered = filtered[mask]
    if status_filter != "All":
        filtered = filtered[filtered["status"] == status_filter]

    st.caption(f"Showing {len(filtered)} of {total_count} items • Synced with data/leads.json")
    if filtered.empty:
        st.info("No matching leads found. Adjust your filters or create a new lead.")
    else:
        view = filtered[["name", "email", "phone", "business_name", "status", "created_at"]].copy()
        view.columns = ["Lead Name", "Email", "Phone", "Company", "Lead Status", "Created Date"]
        st.dataframe(view, hide_index=True, width='content')


# --------------------------- Overview ---------------------------
if page == "Overview":
    c1, c2, c3, c4 = st.columns(4)
    metrics = [
        (c1, "TOTAL LEADS", total, "Active pipeline records", ""),
        (c2, "OPEN / NEW LEADS", new_count, "Awaiting initial outreach", "navy"),
        (c3, "CONVERTED LEADS", converted_count, "Closed-won opportunities", "success"),
        (c4, "CONVERSION RATE", f"{conversion_rate:.1f}%", "Converted vs. total leads", "success"),
    ]
    for col, label, value, note, variant in metrics:
        with col:
            st.markdown(
                f'<div class="metric-card {variant}"><div class="metric-label">{label}</div>'
                f'<div class="metric-value">{value}</div><div class="metric-note">{note}</div></div>',
                unsafe_allow_html=True,
            )

    st.write("")
    left, right = st.columns([1.25, 1])
    with left:
        with st.container(border=True):
            st.subheader("Pipeline Stage Distribution")
            if total:
                status_counts = df["status"].value_counts().reindex(STATUSES, fill_value=0)
                chart_df = status_counts.rename_axis("Status").reset_index(name="Leads")
                st.bar_chart(chart_df, x="Status", y="Leads", color="#FFB52E", width='content')
            else:
                st.info("No lead data yet. Add your first lead from Manage leads.")

    with right:
        with st.container(border=True):
            st.subheader("Stage Breakdown")
            if total:
                status_counts = df["status"].value_counts().reindex(STATUSES, fill_value=0)
                st.dataframe(
                    pd.DataFrame(
                        {
                            "Stage": status_counts.index,
                            "Record Count": status_counts.values,
                            "Pipeline Share": [f"{v / total * 100:.1f}%" for v in status_counts.values],
                        }
                    ),
                    hide_index=True,
                    width='content',
                )
            else:
                st.info("Stage metrics will populate once leads are created.")

    with st.container(border=True):
        st.subheader("Recent Lead Activity")
        if total:
            recent = df.sort_values("updated_at", ascending=False).head(6)
            display = recent[["name", "business_name", "status", "updated_at"]].copy()
            display.columns = ["Lead Name", "Company", "Stage", "Last Modified"]
            st.dataframe(display, hide_index=True, width='content')
        else:
            st.info("Your workspace is ready. Create a lead to start tracking activity.")


# --------------------------- Manage Leads ---------------------------
else:
    add_tab, edit_tab, table_tab = st.tabs(["＋ New Lead", "✎ Edit / Delete Record", "▤ All Leads Directory"])

    with add_tab:
        with st.container(border=True):
            st.markdown('<div class="sf-eyebrow">LEAD INFORMATION</div>', unsafe_allow_html=True)
            st.subheader("Create New Lead")
            with st.form("add_lead_form", clear_on_submit=True):
                col1, col2 = st.columns(2)
                name = col1.text_input("Full Name *", placeholder="e.g. Aditi Sharma")
                email = col2.text_input("Email Address *", placeholder="aditi@company.com")
                col3, col4 = st.columns(2)
                phone = col3.text_input("Phone Number", placeholder="+91 98765 43210")
                business = col4.text_input("Company / Account Name", placeholder="Acme Corp")
                status = st.selectbox("Lead Status", STATUSES)
                submitted = st.form_submit_button("Save Lead", type="primary", width='content')
                if submitted:
                    clean_email = email.strip().lower()
                    if not name.strip():
                        st.error("Please enter the lead's full name.")
                    elif not valid_email(clean_email):
                        st.error("Please enter a valid email address.")
                    elif any(str(x.get("email", "")).lower() == clean_email for x in leads):
                        st.error("A lead with this email already exists.")
                    else:
                        try:
                            add_lead(name, clean_email, phone, business, status)
                            st.toast("Lead saved to Sheets and data/leads.json.", icon="✅")
                            st.rerun()
                        except Exception as exc:
                            st.error(f"Could not save lead: {exc}")

    with edit_tab:
        if not leads:
            st.info("No lead records available to edit. Create a lead first.")
        else:
            options = {f'{str(x.get("name", ""))} · {str(x.get("email", ""))}': str(x["id"]) for x in leads}
            selected_label = st.selectbox("Select Lead Record", list(options.keys()))
            selected_id = options[selected_label]
            selected = next(x for x in leads if str(x["id"]) == selected_id)

            with st.container(border=True):
                st.markdown('<div class="sf-eyebrow">EDIT RECORD</div>', unsafe_allow_html=True)
                with st.form("edit_lead_form"):
                    e1, e2 = st.columns(2)
                    edit_name = e1.text_input("Full Name", value=str(selected.get("name") or ""))
                    edit_email = e2.text_input("Email Address", value=str(selected.get("email") or ""))
                    e3, e4 = st.columns(2)
                    edit_phone = e3.text_input("Phone Number", value=str(selected.get("phone") or ""))
                    edit_business = e4.text_input("Company / Account Name", value=str(selected.get("business_name") or ""))
                    current_status = str(selected.get("status") or "New")
                    edit_status = st.selectbox(
                        "Lead Status",
                        STATUSES,
                        index=STATUSES.index(current_status) if current_status in STATUSES else 0,
                    )
                    save_edit = st.form_submit_button("Save Changes", type="primary")
                    if save_edit:
                        clean_edit_email = edit_email.strip().lower()
                        duplicate = any(
                            str(x["id"]) != selected_id and str(x.get("email", "")).lower() == clean_edit_email
                            for x in leads
                        )
                        if not edit_name.strip():
                            st.error("Full Name is required.")
                        elif not valid_email(clean_edit_email):
                            st.error("Enter a valid email address.")
                        elif duplicate:
                            st.error("Another record already uses this email address.")
                        else:
                            try:
                                update_lead(
                                    selected_id, edit_name, clean_edit_email, edit_phone, edit_business, edit_status
                                )
                                st.toast("Lead updated in Sheets and data/leads.json.", icon="✅")
                                st.rerun()
                            except Exception as exc:
                                st.error(f"Could not update lead: {exc}")

                st.divider()
                confirm_delete = st.checkbox("Confirm permanent deletion of this lead record.")
                if st.button("Delete Record", type="secondary", disabled=not confirm_delete):
                    try:
                        delete_lead(selected_id)
                        st.toast("Lead removed from Sheets and data/leads.json.", icon="🗑️")
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Could not delete lead: {exc}")

    with table_tab:
        with st.container(border=True):
            render_lead_directory(df, total)

st.markdown("---")
st.caption("LEADLAB CRM • Social House Learning • Synced with Google Sheets & data/leads.json")