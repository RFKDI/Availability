"""
BSNL Network Operations Intelligence Dashboard
Run:  streamlit run bsnl_network_ops.py
"""

import io
import re
import tempfile
import warnings
from datetime import datetime

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

warnings.filterwarnings("ignore")

# ──────────────────────────────────────────────────────────────
# PAGE CONFIG
# ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="BSNL Network Ops Intelligence",
    page_icon="📡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ──────────────────────────────────────────────────────────────
# CONSTANTS
# ──────────────────────────────────────────────────────────────
MONTH_MAP = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

TECH_RULES = [
    {"vendor_key": "NOKIA",   "profile": "Nokia 2G", "cnt_col": "2G cnt",     "avail_col": "Nw Avail (2G)",  "color": "#e74a3b"},
    {"vendor_key": "NOKIA",   "profile": "Nokia 3G", "cnt_col": "3G cnt",     "avail_col": "Nw Avail (3G)",  "color": "#4e73df"},
    {"vendor_key": "NORTEL",  "profile": "Nortel 2G","cnt_col": "2G cnt",     "avail_col": "Nw Avail (2G)",  "color": "#858796"},
    {"vendor_key": "TEJAS",   "profile": "Tejas 4G", "cnt_col": "4G cnt",     "avail_col": "4G_Avail_Final", "color": "#f6c23e"},
    {"vendor_key": "ZTE",     "profile": "ZTE 3G",   "cnt_col": "3G cnt",     "avail_col": "Nw Avail (3G)",  "color": "#6f42c1"},
    {"vendor_key": "HUAWEI",  "profile": "Huawei",   "cnt_col": "Total cnt",  "avail_col": "Nw Avail (2G)",  "color": "#1cc88a"},
]

# Fault group keyword mapping — order matters, first match wins
FAULT_GROUPS = {
    "CNTX Media issue": [
        "cntx-zone ofc break", "cntx-zone media issue", "str cable cut",
        "cntx ofc", "cntx media"
    ],
    "TCS Hardware/issue": [
        "tejas hardware", "tcs hardware", "2nd level mtce", "tejas team visit",
        "tcs team visit", "rrh link down", "rac card", "2nd level maintenance"
    ],
    "DWM issue": [
        "minilink fault", "ceregon dmw", "hfcl ubr", "far end mini link",
        "dmw issue", "ubr issue", "dwm fault", "mini link fault"
    ],
    "Battery issue": [
        "battery not available", "battery life expired", "battery backup zero",
        "poor battery backup", "dg not working"
    ],
    "Power plant issue": [
        "power plant fault", "pp control panel fault", "power plant", "pp fault"
    ],
    "DG issue": [
        "dg faulty", "dg failure", "generator fault", "diesel generator fault"
    ],
    "Hub site issue": [
        "due to hub site", "aggregation site issue", "hub site down", "agg site"
    ],
    "EB Supply": [
        "mains failure", "mains not available", "eb failure", "eb supply",
        "eb pole break", "eb pole", "eb not available", "electricity",
        "power cut", "no eb", "no mains", "transformer faults", "transformer fault"
    ],
    "Media / OFC": [
        "ofc", "fibre", "fiber", "e1", "ssa media", "ssa ofc", "cpan",
        "re-routing", "rerouting", "media", "transmission", "microwave",
        "backhaul", "leased", "bandwidth"
    ],
    "Hardware (BTS)": [
        "hardware", "sector down", "site resetting", "reset", "card fail",
        "trx", "feeder", "antenna", "vswr", "media builtup"
    ],
    "Infra / Power": [
        "rectifier", "ups", "temperature", "tempature", "cooling",
        "ac fail", "air condition", "thermal"
    ]
}

FAULT_COLORS = {
    "EB Supply":           "#ef4444",
    "CNTX Media issue":    "#6366f1",
    "TCS Hardware/issue":  "#8b5cf6",
    "DWM issue":           "#06b6d4",
    "Battery issue":       "#f59e0b",
    "Power plant issue":   "#dc2626",
    "DG issue":            "#16a34a",
    "Hub site issue":      "#ec4899",
    "Media / OFC":         "#3b82f6",
    "Hardware (BTS)":      "#a855f7",
    "Infra / Power":       "#f97316",
    "Other":               "#94a3b8"
}

def classify_fault(fault_str):
    if pd.isna(fault_str):
        return "Other"
    fl = str(fault_str).lower().strip()
    # Check specific groups first (order matters)
    for group, keywords in FAULT_GROUPS.items():
        for kw in keywords:
            if kw in fl:
                return group
    return "Other"


# ──────────────────────────────────────────────────────────────
# UTILITIES
# ──────────────────────────────────────────────────────────────
def classify_fault(fault_str):
    if pd.isna(fault_str):
        return "Other"
    fl = str(fault_str).lower().strip()
    for group, keywords in FAULT_GROUPS.items():
        if group == "Other":
            continue
        for kw in keywords:
            if kw in fl:
                return group
    return "Other"


def parse_down_hours(s):
    if pd.isna(s):
        return 0.0
    txt = str(s)
    d = re.search(r"(\d+)\s*day", txt)
    h = re.search(r"(\d+)\s*hour", txt)
    m = re.search(r"(\d+)\s*min", txt)
    total = 0.0
    if d:
        total += int(d.group(1)) * 24
    if h:
        total += int(h.group(1))
    if m:
        total += int(m.group(1)) / 60
    return round(total, 3)


def color_avail(val):
    try:
        v = float(val)
    except Exception:
        return "#94a3b8"
    if v >= 99:
        return "#10b981"
    if v >= 97:
        return "#f59e0b"
    if v >= 95:
        return "#f97316"
    return "#ef4444"


def styled_avail_df(df, avail_cols):
    def highlight(val):
        try:
            v = float(val)
            if v >= 99:
                return "background-color:#d1fae5;color:#065f46"
            if v >= 97:
                return "background-color:#fef3c7;color:#92400e"
            if v >= 95:
                return "background-color:#ffedd5;color:#9a3412"
            return "background-color:#fee2e2;color:#991b1b"
        except Exception:
            return ""
    existing = [c for c in avail_cols if c in df.columns]
    if existing:
        return df.style.applymap(highlight, subset=existing)
    return df.style


# ──────────────────────────────────────────────────────────────
# DATA LOADING
# ──────────────────────────────────────────────────────────────
@st.cache_data(show_spinner=False)
def load_network_data(file_bytes_list, file_names):
    chunks = []
    for data, name in zip(file_bytes_list, file_names):
        df = pd.read_csv(io.BytesIO(data))
        df.columns = df.columns.str.strip()
        chunks.append(df)
    df = pd.concat(chunks, ignore_index=True)

    num_cols = [
        "Nw Avail (2G)", "Nw Avail (3G)", "Nw Avail (4G)", "Nw Avail (4G TCS)",
        "Erl Total", "Data GB Total", "2G cnt", "3G cnt", "4G cnt", "Total cnt",
    ]
    for col in num_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(
                df[col].astype(str).str.replace("%", "", regex=False), errors="coerce"
            )

    if "Nw Avail (4G TCS)" in df.columns:
        df["4G_Avail_Final"] = df["Nw Avail (4G TCS)"].fillna(df.get("Nw Avail (4G)", np.nan))
    else:
        df["4G_Avail_Final"] = df.get("Nw Avail (4G)", np.nan)

    df["MONTH"] = df["MONTH"].astype(str).str.strip()
    df["YEAR"] = df["YEAR"].astype(str).str.strip()
    df["Month_Idx"] = df["MONTH"].str.lower().str[:3].map(MONTH_MAP).fillna(0)
    df["Year_Idx"] = pd.to_numeric(df["YEAR"], errors="coerce").fillna(2026)
    df["Period"] = df["YEAR"] + " - " + df["MONTH"]
    df["BTS_IP_CLEAN"] = df["BTS IP ID"].astype(str).str.strip()
    df["Vendor_Upper"] = df["Vendor"].astype(str).str.upper()
    df = df.sort_values(["Year_Idx", "Month_Idx"]).reset_index(drop=True)
    return df


@st.cache_data(show_spinner=False)
def load_incharge(data, name):
    if name.lower().endswith(".csv"):
        df = pd.read_csv(io.BytesIO(data))
    else:
        df = pd.read_excel(io.BytesIO(data), engine="openpyxl")
    df.columns = df.columns.str.strip()
    df["BTSIPID_CLEAN"] = df["BTSIPID"].astype(str).str.strip()
    return df


def _read_xls_bytes(data: bytes, name: str) -> pd.DataFrame:
    """
    Read a legacy .xls file from raw bytes.
    Strategy:
      1. Write bytes to a named temp file (required — LibreOffice needs a real path).
      2. Try xlrd first (fast, no subprocess).
      3. On ANY xlrd failure (including 'Workbook corruption'), fall back to
         LibreOffice headless CSV conversion, which handles all BSNL-generated
         .xls files reliably.
    """
    import os, subprocess

    # Always write to a real temp file with the original .xls extension
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".xls")
    try:
        with os.fdopen(tmp_fd, "wb") as fh:
            fh.write(data)

        # ── Strategy 1: xlrd ──────────────────────────────────────────────
        try:
            df = pd.read_excel(tmp_path, engine="xlrd")
            return df
        except Exception:
            pass  # fall through to LibreOffice

        # ── Strategy 2: LibreOffice headless CSV conversion ───────────────
        out_dir = tempfile.mkdtemp()
        result = subprocess.run(
            ["libreoffice", "--headless", "--convert-to", "csv",
             tmp_path, "--outdir", out_dir],
            capture_output=True, timeout=90,
        )

        # LibreOffice names the output after the input basename
        base_no_ext = os.path.splitext(os.path.basename(tmp_path))[0]
        csv_path = os.path.join(out_dir, base_no_ext + ".csv")

        if os.path.exists(csv_path):
            return pd.read_csv(csv_path)

        # If still not found, list what LibreOffice actually produced
        produced = os.listdir(out_dir)
        if produced:
            return pd.read_csv(os.path.join(out_dir, produced[0]))

        raise RuntimeError(
            "LibreOffice conversion produced no output for " + name
            + ". stderr: " + result.stderr.decode(errors="replace")
        )
    finally:
        # Clean up the temp .xls file (output CSVs are in their own dir)
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


@st.cache_data(show_spinner=False)
def load_alarm_logs(file_bytes_list, file_names):
    chunks = []
    errors = []

    for data, name in zip(file_bytes_list, file_names):
        nm = name.lower().strip()
        df = pd.DataFrame()
        try:
            if nm.endswith(".csv"):
                df = pd.read_csv(io.BytesIO(data))
            elif nm.endswith(".xls"):
                df = _read_xls_bytes(data, name)
            elif nm.endswith(".xlsx") or nm.endswith(".xlsm"):
                df = pd.read_excel(io.BytesIO(data), engine="openpyxl")
            else:
                errors.append(name + ": unsupported file type")
                continue
        except Exception as exc:
            errors.append(name + ": " + str(exc))
            continue

        if df.empty:
            errors.append(name + ": file loaded but contains no data")
            continue

        # ── Normalise column names ──────────────────────────────────────
        df.columns = df.columns.str.strip()
        alias = {
            "bts_ip_id":    "bts_ip_id",
            "btsipid":      "bts_ip_id",
            "bts_name":     "bts_name",
            "btsname":      "bts_name",
            "fault_type":   "fault_type",
            "fault type":   "fault_type",
            "faulttype":    "fault_type",
            "bts_down_dt":  "bts_down_dt",
            "down_time":    "bts_down_dt",
            "bts_up_dt":    "bts_up_dt",
            "up_time":      "bts_up_dt",
            "downperiod":   "downPeriod",
            "down_period":  "downPeriod",
            "sdca_name":    "sdca_name",
            "sdca":         "sdca_name",
            "ssa_name":     "ssa_name",
            "ssa":          "ssa_name",
            "vendor":       "vendor",
            "bts_type":     "bts_type",
        }
        df.columns = [alias.get(c.lower().strip(), c.lower().strip()) for c in df.columns]

        # ── Derived columns ─────────────────────────────────────────────
        dp_col = next((c for c in ["downPeriod", "downperiod", "down_period"] if c in df.columns), None)
        df["down_hours"] = df[dp_col].apply(parse_down_hours) if dp_col else 0.0

        ft_series = df["fault_type"] if "fault_type" in df.columns else pd.Series(dtype=str)
        df["fault_group"] = ft_series.apply(classify_fault)

        if "bts_ip_id" in df.columns:
            df["bts_ip_id"] = df["bts_ip_id"].astype(str).str.strip()

        df["source_file"] = name
        chunks.append(df)

    # Surface any load errors as a single Streamlit warning (not one per file)
    if errors:
        st.warning("⚠️ Some alarm files had issues:\n" + "\n".join("• " + e for e in errors))

    if not chunks:
        return pd.DataFrame()
    return pd.concat(chunks, ignore_index=True)


# ──────────────────────────────────────────────────────────────
# ANALYSIS FUNCTIONS
# ──────────────────────────────────────────────────────────────
def get_periods(df, ssa):
    sub = df[df["SSA"].str.strip().str.upper() == ssa.upper()]
    chron = (
        sub.groupby(["Year_Idx", "Month_Idx", "Period"])
        .size()
        .reset_index()
        .sort_values(["Year_Idx", "Month_Idx"])
    )
    return chron["Period"].tolist()


def get_vendor_summary(df):
    """
    Count sites using EXACT manual cross-check logic:
    - Nokia 2G:  Vendor=NOKIA + "BCF" in BTS Site ID (2G) → count unique BTS Site ID (2G)
    - Nokia 3G:  Vendor=NOKIA + "WBTS" in BTS Site ID (3G) → count unique BTS Site ID (3G)
    - ZTE 3G:    Vendor=ZTE + BTS Site ID (3G) not null → count unique BTS Site ID (3G)
    - Nortel 2G: Vendor=NORTEL → count unique BTS Name
    - Tejas 4G:  Vendor=TEJAS → count unique BTS Name
    """
    rows = []
    for r in TECH_RULES:
        vk = r["vendor_key"].strip()
        profile = r["profile"].strip()
        ac = r["avail_col"].strip()

        # ── Apply EXACT manual logic per technology ──────────────────
        if profile == "Nokia 2G":
            # Manual: Vendor=NOKIA & "BCF" in BTS Site ID (2G)
            mask = df["Vendor_Upper"].str.contains("NOKIA", na=False)
            if "BTS Site ID (2G)" in df.columns:
                mask = mask & df["BTS Site ID (2G)"].astype(str).str.contains("BCF", na=False)
            sub = df[mask]
            count_col = "BTS Site ID (2G)"

        elif profile == "Nokia 3G":
            # Manual: Vendor=NOKIA & "WBTS" in BTS Site ID (3G)
            mask = df["Vendor_Upper"].str.contains("NOKIA", na=False)
            if "BTS Site ID (3G)" in df.columns:
                mask = mask & df["BTS Site ID (3G)"].astype(str).str.contains("WBTS", na=False)
            sub = df[mask]
            count_col = "BTS Site ID (3G)"

        elif profile == "ZTE 3G":
            # Manual: Vendor=ZTE & BTS Site ID (3G) not null
            mask = df["Vendor_Upper"].str.contains("ZTE", na=False)
            if "BTS Site ID (3G)" in df.columns:
                mask = mask & df["BTS Site ID (3G)"].notna()
            sub = df[mask]
            count_col = "BTS Site ID (3G)"

        elif profile == "Nortel 2G":
            # Manual: Vendor=NORTEL (no extra filters)
            mask = df["Vendor_Upper"].str.contains("NORTEL", na=False)
            sub = df[mask]
            count_col = "BTS Name"

        elif profile == "Tejas 4G":
            # Manual: Vendor=TEJAS (no extra filters)
            mask = df["Vendor_Upper"].str.contains("TEJAS", na=False)
            sub = df[mask]
            count_col = "BTS Name"

        else:
            # Fallback for other vendors
            cc = r["cnt_col"].strip()
            mask = df["Vendor_Upper"].str.contains(vk, na=False) & (df[cc].fillna(0) > 0)
            sub = df[mask]
            count_col = "BTS_IP_CLEAN" if "BTS_IP_CLEAN" in df.columns else "BTS Name"

        if sub.empty:
            continue

        # ── Count UNIQUE sites (not rows) ───────────────────────────
        if count_col in sub.columns:
            site_count = sub[count_col].dropna().nunique()
        else:
            site_count = len(sub)

        # ── Build row ───────────────────────────────────────────────
        rows.append({
            "Profile": profile,
            "Vendor": vk,
            "Sites": site_count,  # ✅ Now uses correct unique count
            "Avg Avail (%)": round(sub[ac].mean(), 3) if ac in sub and not sub[ac].isna().all() else np.nan,
            "Min Avail (%)": round(sub[ac].min(), 3) if ac in sub and not sub[ac].isna().all() else np.nan,
            "Sites <97%": int((sub[ac] < 97).sum()) if ac in sub else 0,
            "Sites <95%": int((sub[ac] < 95).sum()) if ac in sub else 0,
            "Data GB": round(sub["Data GB Total"].sum(), 2) if "Data GB Total" in sub else 0,
            "Erl Total": round(sub["Erl Total"].sum(), 2) if "Erl Total" in sub else 0,
            "Color": r["color"],
        })
    return pd.DataFrame(rows)



def get_degradation_report(df_curr, df_prev, threshold):
    rows = []
    prev_lookups = {}
    for r in TECH_RULES:
        ac = r["avail_col"]
        if ac in df_prev.columns:
            prev_lookups[r["profile"]] = df_prev.set_index("BTS_IP_CLEAN")[ac].to_dict()

    for _, row in df_curr.iterrows():
        bid = row["BTS_IP_CLEAN"]
        for r in TECH_RULES:
            vk = r["vendor_key"]
            cc = r["cnt_col"]
            ac = r["avail_col"]
            if vk not in row.get("Vendor_Upper", ""):
                continue
            if row.get(cc, 0) <= 0:
                continue
            lk = prev_lookups.get(r["profile"], {})
            if bid not in lk:
                continue
            curr_val = row.get(ac)
            prev_val = lk[bid]
            if pd.isna(curr_val) or pd.isna(prev_val):
                continue
            delta = curr_val - prev_val
            if delta < -threshold:
                rows.append({
                    "BTS IP ID":      bid,
                    "BTS Name":       row.get("BTS Name", ""),
                    "SDCA":           row.get("SDCA", ""),
                    "Incharge":       row.get("incharge", ""),
                    "Vendor":         vk,
                    "Technology":     r["profile"],
                    "Prev Month (%)": round(prev_val, 3),
                    "Curr Month (%)": round(curr_val, 3),
                    "Delta (%)":      round(delta, 3),
                    "Site Category":  row.get("Site Category", ""),
                })
    return pd.DataFrame(rows).sort_values("Delta (%)") if rows else pd.DataFrame()


def get_worst_performers(df, vendor, cnt_col, avail_col, top_n=10):
    mask = df["Vendor_Upper"].str.contains(vendor, na=False) & (df[cnt_col].fillna(0) > 0)
    sub = df[mask].copy()
    if sub.empty or avail_col not in sub.columns:
        return pd.DataFrame()
    cols = ["BTS IP ID", "BTS Name", "SDCA"]
    if "incharge" in sub.columns:
        cols.append("incharge")
    cols.append(avail_col)
    if "Site Category" in sub.columns:
        cols.append("Site Category")
    return sub.nsmallest(top_n, avail_col)[cols].reset_index(drop=True)


def get_sdca_summary(df):
    if "SDCA" not in df.columns:
        return pd.DataFrame()
    rows = []
    for sdca, sub in df.groupby("SDCA"):
        def smean(col):
            return round(sub[col].mean(), 3) if col in sub and sub[col].notna().sum() > 0 else np.nan
        rows.append({
            "SDCA":          sdca,
            "Sites":         len(sub),
            "Avg 2G (%)":    smean("Nw Avail (2G)"),
            "Avg 3G (%)":    smean("Nw Avail (3G)"),
            "Avg 4G (%)":    smean("4G_Avail_Final"),
            "Sites <97% 2G": int((sub.get("Nw Avail (2G)", pd.Series()) < 97).sum()),
            "Data GB":       round(sub["Data GB Total"].sum(), 1) if "Data GB Total" in sub else 0,
            "Erl":           round(sub["Erl Total"].sum(), 1)     if "Erl Total" in sub else 0,
        })
    return pd.DataFrame(rows).sort_values("Avg 2G (%)")


def get_incharge_summary(df):
    if "incharge" not in df.columns:
        return pd.DataFrame()
    rows = []
    for inc, sub in df.groupby("incharge"):
        def smean(col):
            return round(sub[col].mean(), 3) if col in sub and sub[col].notna().sum() > 0 else np.nan
        rows.append({
            "Incharge":      inc,
            "Sites":         len(sub),
            "Avg 2G (%)":    smean("Nw Avail (2G)"),
            "Avg 3G (%)":    smean("Nw Avail (3G)"),
            "Avg 4G (%)":    smean("4G_Avail_Final"),
            "Sites <97%":    int((sub.get("Nw Avail (2G)", pd.Series()) < 97).sum()),
        })
    return pd.DataFrame(rows).sort_values("Avg 2G (%)").reset_index(drop=True)


# ──────────────────────────────────────────────────────────────
# ALARM ANALYSIS
# ──────────────────────────────────────────────────────────────
def alarm_group_summary(df):
    grp = (
        df.groupby("fault_group")
        .agg(Events=("fault_group", "count"),
             Total_Hours=("down_hours", "sum"),
             Avg_Hours=("down_hours", "mean"),
             Sites=("bts_ip_id", "nunique"))
        .reset_index()
        .sort_values("Total_Hours", ascending=False)
    )
    grp["Total_Hours"] = grp["Total_Hours"].round(2)
    grp["Avg_Hours"]   = grp["Avg_Hours"].round(2)
    return grp


def alarm_sdca_pivot(df):
    if "sdca_name" not in df.columns:
        return pd.DataFrame()
    pivot = (
        df.pivot_table(index="sdca_name", columns="fault_group",
                       values="down_hours", aggfunc="sum", fill_value=0)
        .round(2)
        .reset_index()
    )
    pivot.columns.name = None
    pivot["Total Hours"] = pivot.drop(columns="sdca_name").sum(axis=1)
    return pivot.sort_values("Total Hours", ascending=False)


def alarm_site_summary(df):
    site_col = "bts_name" if "bts_name" in df.columns else "bts_ip_id"
    pivot = (
        df.pivot_table(index=site_col, columns="fault_group",
                       values="down_hours", aggfunc="sum", fill_value=0)
        .round(2)
        .reset_index()
    )
    pivot.columns.name = None
    pivot["Total Hours"] = pivot.drop(columns=site_col).sum(axis=1)
    event_count = df.groupby(site_col).size().reset_index(name="Events")
    pivot = pivot.merge(event_count, on=site_col, how="left")
    if "sdca_name" in df.columns:
        sdca_map = df.groupby(site_col)["sdca_name"].first().reset_index()
        pivot = pivot.merge(sdca_map, on=site_col, how="left")
    return pivot.sort_values("Total Hours", ascending=False).reset_index(drop=True)


def alarm_daily_trend(df):
    if "bts_down_dt" not in df.columns:
        return pd.DataFrame()
    tmp = df.copy()
    tmp["date"] = pd.to_datetime(tmp["bts_down_dt"], errors="coerce").dt.date
    return (
        tmp.groupby(["date", "fault_group"])
        .agg(Events=("fault_group", "count"), Hours=("down_hours", "sum"))
        .reset_index()
    )


# ──────────────────────────────────────────────────────────────
# HTML EXPORT
# ──────────────────────────────────────────────────────────────
def avail_td_html(v):
    try:
        fv = float(v)
        c = color_avail(fv)
        return "<td style='color:" + c + ";font-weight:700'>" + str(round(fv, 2)) + "%</td>"
    except Exception:
        return "<td style='color:#94a3b8'>N/A</td>"


def delta_td_html(v):
    try:
        fv = float(v)
        c = "#ef4444" if fv < 0 else "#10b981"
        sym = "▼" if fv < 0 else "▲"
        return "<td style='color:" + c + ";font-weight:700'>" + sym + " " + str(round(abs(fv), 2)) + "%</td>"
    except Exception:
        return "<td>-</td>"


def build_html_report(ssa, target_period, base_period, threshold,
                      df_vendor, df_deg, df_sdca, df_incharge,
                      df_alarm_grp, df_sdca_pivot, df_site_sum, worst_dict,
                      df_trend, df_alarm_ssa, df_curr,
                      total_sites=0, avg_2g=0, avg_3g=0, avg_4g=0,
                      sites_below_97=0, total_outage_hrs=0, power_eb_hrs=0,
                      overall_avail=0.0, total_nodes=0, band_700=0, band_2100=0, band_2500=0,
                      tech_nodes=None, df_avail_dist=None):
    import plotly.graph_objects as go
    import plotly.express as px
    from datetime import datetime
    import pandas as pd
    import numpy as np

    gen_time = datetime.now().strftime("%d-%b-%Y %H:%M")

    # ── Helper: Color code for availability values ─────────────────────
    def avail_bg(v):
        try:
            fv = float(v)
        except:
            return "#f8fafc", "#94a3b8"
        if fv >= 99: return "#d1fae5", "#065f46"
        if fv >= 97: return "#fef3c7", "#92400e"
        if fv >= 95: return "#ffedd5", "#9a3412"
        return "#fee2e2", "#991b1b"

    # ── Generate Plotly Charts (WHITE/LIGHT THEME) ───────────────────
    def plot_to_html(fig, height=350):
        if fig is None or len(fig.data) == 0:
            return "<p style='color:#64748b;padding:20px'>No data for chart.</p>"
        fig.update_layout(
            plot_bgcolor="white", paper_bgcolor="white",
            font_color="#1e293b", height=height,
            xaxis=dict(showgrid=True, gridcolor="#f1f5f9"),
            yaxis=dict(showgrid=True, gridcolor="#f1f5f9")
        )
        return fig.to_html(full_html=False, include_plotlyjs='cdn')

    # Chart 1: Vendor Availability Bar
    chart_vendor_html = ""
    if not df_vendor.empty and "Avg Avail (%)" in df_vendor.columns:
        fig_vendor = px.bar(df_vendor, x="Profile", y="Avg Avail (%)", color="Profile",
                            color_discrete_sequence=[r["color"] for r in TECH_RULES if
                                                     r["profile"] in df_vendor["Profile"].values],
                            title="Average Network Availability by Tech-Vendor", text="Avg Avail (%)")
        fig_vendor.update_traces(texttemplate="%{text:.2f}%", textposition="outside")
        fig_vendor.add_hline(y=97, line_dash="dash", line_color="#f59e0b", annotation_text="97% SLA")
        fig_vendor.add_hline(y=95, line_dash="dash", line_color="#ef4444", annotation_text="95% Critical")
        chart_vendor_html = plot_to_html(fig_vendor)
    else:
        chart_vendor_html = "<p style='color:#64748b;padding:20px'>Vendor data unavailable for chart.</p>"

    # Chart 2: Fault Hours by Group (Pie)
    chart_fault_html = ""
    if not df_alarm_grp.empty:
        fig_fault = px.pie(df_alarm_grp, names="fault_group", values="Total_Hours", color="fault_group",
                           color_discrete_map=FAULT_COLORS, title="Outage Hours Distribution by Fault Group", hole=0.4)
        chart_fault_html = plot_to_html(fig_fault, height=400)
    else:
        chart_fault_html = "<p style='color:#64748b;padding:20px'>No fault data available.</p>"

    # Chart 3: Multi-Month Trend
    chart_trend_html = ""
    if df_trend is not None and not df_trend.empty and "Period" in df_trend.columns:
        valid_profiles = [r["profile"] for r in TECH_RULES if r["profile"] in df_trend.columns]
        if valid_profiles:
            fig_tr = go.Figure()
            for prof in valid_profiles:
                color = next((r["color"] for r in TECH_RULES if r["profile"] == prof), "#fff")
                fig_tr.add_trace(go.Scatter(x=df_trend["Period"], y=df_trend[prof], mode="lines+markers+text",
                                            name=prof, line=dict(color=color, width=3),
                                            text=df_trend[prof].round(2).astype(str) + "%", textposition="top center"))
            fig_tr.add_hline(y=97, line_dash="dash", line_color="#f59e0b", annotation_text="97% SLA")
            chart_trend_html = plot_to_html(fig_tr, height=400)

    # Chart 4: Daily Fault Trend (Clustered & Fixed)
    chart_daily_html = ""
    if df_alarm_ssa is not None and not df_alarm_ssa.empty and "bts_down_dt" in df_alarm_ssa.columns:
        tmp = df_alarm_ssa.copy()
        tmp["datetime"] = pd.to_datetime(tmp["bts_down_dt"], errors="coerce")
        tmp["date"] = tmp["datetime"].dt.date
        tmp = tmp.sort_values(["date", "fault_group", "datetime"])

        site_col = "bts_name" if "bts_name" in tmp.columns else "bts_ip_id"
        sdca_col = "sdca_name" if "sdca_name" in tmp.columns else None
        type_col = "fault_type" if "fault_type" in tmp.columns else None

        tmp["time_block"] = tmp["datetime"].dt.floor("4h")

        def safe_join(series):
            vals = series.dropna().astype(str).unique()
            return ", ".join(vals[:5]) + ("..." if len(vals) > 5 else "") if len(vals) > 0 else "-"

        def safe_mode(series):
            m = series.mode()
            return m.iloc[0] if not m.empty else "N/A"

        agg_kwargs = {"Total_Hours": ("down_hours", "sum"), "Events": ("down_hours", "count"),
                      "Sites_Affected": (site_col, "nunique")}
        if sdca_col: agg_kwargs["Affected_SDCA"] = (sdca_col, safe_join)
        if type_col: agg_kwargs["Probable_Cause"] = (type_col, safe_mode)

        clustered = tmp.groupby(["date", "fault_group", "time_block"]).agg(**agg_kwargs).reset_index()
        clustered["Time_Window"] = clustered["time_block"].dt.strftime("%H:%M") + " - " + (
                    clustered["time_block"] + pd.Timedelta(hours=4)).dt.strftime("%H:%M")
        clustered = clustered.sort_values("Total_Hours", ascending=False)

        fig_dt = px.bar(clustered, x="date", y="Total_Hours", color="fault_group", color_discrete_map=FAULT_COLORS,
                        title="Daily Outage Hours (Clustered by 4-hr Windows)", barmode="stack",
                        hover_data=["Events", "Sites_Affected", "Time_Window", "Affected_SDCA", "Probable_Cause"])
        chart_daily_html = plot_to_html(fig_dt, height=450)

        tbl = """<div style='margin-top:20px; overflow-x:auto;'><h4 style='color:#1e5799;margin-bottom:10px'>Clustered Outages for Troubleshooting</h4>
        <table style='width:100%;font-size:13px; border-collapse: collapse;'><thead><tr style='background:#f8fafc; color:#1e293b; border-bottom: 2px solid #cbd5e1;'>
        <th style='padding:8px; text-align:left;'>Date</th><th style='padding:8px; text-align:left;'>Fault Group</th>
        <th style='padding:8px; text-align:left;'>Time Window</th><th style='padding:8px; text-align:center;'>Events</th>
        <th style='padding:8px; text-align:center;'>Sites</th><th style='padding:8px; text-align:center;'>Total Hours</th>
        <th style='padding:8px; text-align:left;'>Affected SDCA</th><th style='padding:8px; text-align:left;'>Probable Cause</th>
        </tr></thead><tbody>"""
        for _, row in clustered.head(15).iterrows():
            tbl += f"""<tr style='border-bottom: 1px solid #e2e8f0;'><td style='padding:8px;'>{row['date']}</td>
            <td style='padding:8px;'><span style='color:{FAULT_COLORS.get(row["fault_group"], "#94a3b8")};font-weight:600'>{row["fault_group"]}</span></td>
            <td style='padding:8px;'>{row["Time_Window"]}</td><td style='padding:8px; text-align:center;'>{row["Events"]}</td>
            <td style='padding:8px; text-align:center;'>{row["Sites_Affected"]}</td>
            <td style='padding:8px; text-align:center;font-weight:700'>{round(row["Total_Hours"], 1)}h</td>
            <td style='padding:8px; font-size:11px;'>{row.get("Affected_SDCA", "-")}</td>
            <td style='padding:8px;'>{row.get("Probable_Cause", "N/A")}</td></tr>"""
        tbl += "</tbody></table></div>"
        chart_daily_html += tbl
    else:
        chart_daily_html = "<p style='color:#64748b;padding:20px'>No alarm trend data available.</p>"

    # ── CSS (COMPLETELY LIGHT THEME) ─────────────────────────────────
    css = """
:root{--blue:#2563eb;--green:#10b981;--red:#ef4444;--orange:#f97316;}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Segoe UI',Arial,sans-serif;background:#ffffff;color:#1e293b;font-size:13px}
.header{background:linear-gradient(135deg,#2563eb,#1d4ed8);color:#fff;padding:28px 32px}
.header h1{font-size:22px;font-weight:700;margin-bottom:8px}
.header .meta{display:flex;gap:20px;font-size:12px;opacity:.9;flex-wrap:wrap;margin-top:10px}
.header .badge{background:rgba(255,255,255,.25);padding:3px 10px;border-radius:12px;font-size:11px;font-weight:700}
.tabs-wrapper{display:flex;flex-direction:column;padding:20px 24px}
.tab-radio{display:none}
.tab-nav{display:flex;background:#f1f5f9;padding:5px;border-radius:8px;margin-bottom:20px;gap:5px;flex-wrap:wrap}
.tab-label{flex:1;min-width:120px;text-align:center;padding:11px 8px;cursor:pointer;font-weight:600;font-size:12px;border-radius:6px;color:#475569;transition:all .2s}
.tab-label:hover{background:#e2e8f0}
.tab-view{display:none}
#t1:checked~.tab-nav .l1,#t2:checked~.tab-nav .l2,#t3:checked~.tab-nav .l3, 
#t4:checked~.tab-nav .l4,#t5:checked~.tab-nav .l5,#t6:checked~.tab-nav .l6,#t7:checked~.tab-nav .l7{background:#2563eb;color:#fff}
#t1:checked~.tabs-content .c1,#t2:checked~.tabs-content .c2,#t3:checked~.tabs-content .c3,
#t4:checked~.tabs-content .c4,#t5:checked~.tabs-content .c5,#t6:checked~.tabs-content .c6,#t7:checked~.tabs-content .c7{display:block}
.section{background:#ffffff;border:1px solid #e2e8f0;border-radius:10px;padding:20px;margin-bottom:20px;box-shadow: 0 1px 3px rgba(0,0,0,0.05);}
.section h3{font-size:14px;font-weight:700;color:var(--blue);margin-bottom:12px;padding-bottom:8px;border-bottom:1px solid #e2e8f0}
.flex-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:18px;margin-bottom:18px}
.vendor-stack{display:flex;flex-direction:column;gap:24px;width:100%}
.card{background:#ffffff;border:1px solid #e2e8f0;border-radius:10px;padding:16px;overflow-x:auto;width:100%;box-shadow: 0 1px 2px rgba(0,0,0,0.05);}
.card table{width:100%;min-width:400px;border-collapse:collapse}
table{width:100%;border-collapse:collapse}
th{background:#f8fafc;color:#1e293b;font-weight:700;text-transform:uppercase;font-size:10px;letter-spacing:.4px;padding:10px 12px;text-align:left;border-bottom:2px solid #e2e8f0;white-space:nowrap}
td{padding:9px 12px;border-bottom:1px solid #f1f5f9;vertical-align:middle}
tr:hover td{background:#f8fafc}
.chart-container{background:#ffffff;border-radius:8px;padding:10px;margin:10px 0; border: 1px solid #e2e8f0;}
.footer{text-align:center;padding:16px;color:#64748b;font-size:11px;border-top:1px solid #e2e8f0;margin-top:12px}
@media print{.tab-view{display:block!important}.tab-nav{display:none}.chart-container{page-break-inside:avoid}}
"""

    # ── KPI Summary Bar ──────────────────────────────────────────────
    kpi_bar = (
            "<div style='display:grid;grid-template-columns:repeat(7,1fr);gap:8px;padding:12px 24px;background:#ffffff;border-bottom:1px solid #e2e8f0'>"
            "<div style='text-align:center;padding:8px;background:#f8fafc;border-radius:8px'><div style='font-size:10px;color:#64748b;font-weight:600'>Total BTS Sites</div><div style='font-size:18px;font-weight:800;color:#2563eb'>" + str(
        total_sites) + "</div></div>"
                       "<div style='text-align:center;padding:8px;background:#f8fafc;border-radius:8px'><div style='font-size:10px;color:#64748b;font-weight:600'>Avg 2G Avail</div><div style='font-size:18px;font-weight:800;color:" + color_avail(
        avg_2g) + "'>" + str(round(avg_2g, 2)) + "%</div></div>"
                                                 "<div style='text-align:center;padding:8px;background:#f8fafc;border-radius:8px'><div style='font-size:10px;color:#64748b;font-weight:600'>Avg 3G Avail</div><div style='font-size:18px;font-weight:800;color:" + color_avail(
        avg_3g) + "'>" + str(round(avg_3g, 2)) + "%</div></div>"
                                                 "<div style='text-align:center;padding:8px;background:#f8fafc;border-radius:8px'><div style='font-size:10px;color:#64748b;font-weight:600'>Avg 4G Avail</div><div style='font-size:18px;font-weight:800;color:" + color_avail(
        avg_4g) + "'>" + str(round(avg_4g, 2)) + "%</div></div>"
                                                 "<div style='text-align:center;padding:8px;background:#f8fafc;border-radius:8px'><div style='font-size:10px;color:#64748b;font-weight:600'>Sites &lt;97% (2G)</div><div style='font-size:18px;font-weight:800;color:" + (
                "#ef4444" if sites_below_97 > 0 else "#10b981") + "'>" + str(sites_below_97) + "</div></div>"
                                                                                               "<div style='text-align:center;padding:8px;background:#f8fafc;border-radius:8px'><div style='font-size:10px;color:#64748b;font-weight:600'>Total Outage Hrs</div><div style='font-size:18px;font-weight:800;color:#64748b'>" + str(
        round(total_outage_hrs, 1)) + "h</div></div>"
                                      "<div style='text-align:center;padding:8px;background:#f8fafc;border-radius:8px'><div style='font-size:10px;color:#64748b;font-weight:600'>Power/EB Down Hrs</div><div style='font-size:18px;font-weight:800;color:" + (
                "#f97316" if power_eb_hrs > 10 else "#10b981") + "'>" + str(round(power_eb_hrs, 1)) + "h</div></div>"
                                                                                                      "</div>"
    )

    # ── GENERATE TABLE ROWS (This fixes the NameError) ────────────────

    # 1. Vendor Rows (vrows)
    vrows = ""
    for _, row in df_vendor.iterrows():
        vrows += (
                "<tr>"
                "<td><b>" + str(row.get("Profile", " ")) + "</b></td>"
                                                           "<td>" + str(row.get("Vendor", " ")) + "</td>"
                                                                                                  "<td style='text-align:center'>" + str(
            row.get("Sites", " ")) + "</td>"
                + avail_td_html(row.get("Avg Avail (%)", " "))
                + avail_td_html(row.get("Min Avail (%)", " "))
                + "<td style='text-align:center'>" + str(row.get("Sites <97%", " ")) + "</td>"
                                                                                       "<td style='text-align:center'>" + str(
            row.get("Sites <95%", " ")) + "</td>"
                                          "<td>" + str(round(float(row.get("Data GB", 0)), 1)) + "</td>"
                                                                                                 "<td>" + str(
            round(float(row.get("Erl Total", 0)), 1)) + "</td>"
                                                        "</tr>"
        )

    # 2. Degradation Rows (drows)
    drows = ""
    if df_deg.empty:
        drows = "<tr><td colspan='9' style='text-align:center;color:#10b981;padding:20px'>No degradation beyond " + str(
            threshold) + "% detected</td></tr>"
    else:
        degraded_ids = df_deg["BTS IP ID"].unique()
        alarm_deg = df_alarm_ssa[
            df_alarm_ssa["bts_ip_id"].isin(degraded_ids)] if not df_alarm_ssa.empty else pd.DataFrame()
        top_reason_map = {}
        if not alarm_deg.empty:
            top_reason = alarm_deg.groupby(["bts_ip_id", "fault_group"])["down_hours"].sum().reset_index().sort_values(
                "down_hours", ascending=False).drop_duplicates("bts_ip_id")
            top_reason_map = dict(zip(top_reason["bts_ip_id"], top_reason["fault_group"]))

        for _, row in df_deg.iterrows():
            sc = str(row.get("Site Category", " "))
            sc_html = (
                "<span style='background:#fee2e2;color:#991b1b;padding:2px 6px;border-radius:4px;font-size:10px'>" + sc + "</span>"
                if "CRITICAL" in sc.upper() or "IMPORTANT" in sc.upper() else "<span style='font-size:10px;color:#64748b'>" + sc + "</span>")
            primary = top_reason_map.get(row["BTS IP ID"], "-")
            pc_color = FAULT_COLORS.get(primary, "#94a3b8")
            drows += ("<tr><td><b>" + str(row.get("BTS Name", " ")) + "</b><br><small style='color:#64748b'>" + str(
                row.get("BTS IP ID", " ")) + "</small></td><td>" + str(row.get("SDCA", " ")) + "</td><td>" + str(
                row.get("Incharge", " ")) + "</td><td>" + str(row.get("Technology", " ")) + "</td>"
                      + avail_td_html(row.get("Prev Month (%)", " ")) + avail_td_html(
                        row.get("Curr Month (%)", " ")) + delta_td_html(row.get("Delta (%)", " "))
                      + "<td>" + sc_html + "</td><td><span style='background:" + pc_color + "20;color:" + pc_color + ";padding:3px 8px;border-radius:4px;font-size:11px;font-weight:600'>" + primary + "</span></td></tr>")

    # 3. SDCA Rows (srows)
    srows = ""
    for _, row in df_sdca.iterrows():
        ov = row.get("Overall Avail (%)", 0)
        srows += ("<tr><td><b>" + str(row.get("SDCA", " ")) + "</b></td><td style='text-align:center'>" + str(
            row.get("Sites", " ")) + "</td>"
                  + avail_td_html(row.get("Avg 2G (%)", " ")) + avail_td_html(
                    row.get("Avg 3G (%)", " ")) + avail_td_html(row.get("Avg 4G (%)", " "))
                  + avail_td_html(ov) + "<td style='text-align:center'>" + str(
                    row.get("Sites <97% 2G", 0)) + "</td><td>" + str(
                    round(float(row.get("Data GB", 0)), 1)) + "</td></tr>")

    # 4. Incharge Rows (irows)
    irows = ""
    for _, row in df_incharge.iterrows():
        irows += ("<tr><td><b>" + str(row.get("Incharge", " ")) + "</b></td><td style='text-align:center'>" + str(
            row.get("Sites", " ")) + "</td>"
                  + avail_td_html(row.get("Avg 2G (%)", " ")) + avail_td_html(
                    row.get("Avg 3G (%)", " ")) + avail_td_html(row.get("Avg 4G (%)", " "))
                  + "<td style='text-align:center'>" + str(row.get("Sites <97%", 0)) + "</td></tr>")

    # 5. Alarm Group Rows (arows)
    arows = ""
    for _, r in df_alarm_grp.iterrows():
        grp = str(r.get("fault_group", ""))
        arows += ("<tr><td><span style='background:" + FAULT_COLORS.get(grp,
                                                                        "#94a3b8") + "20;color:" + FAULT_COLORS.get(grp,
                                                                                                                    "#94a3b8") + ";padding:3px 8px;border-radius:4px;font-weight:700'>" + grp + "</span></td>"
                                                                                                                                                                                                "<td style='text-align:center'>" + str(
            r.get("Events", 0)) + "</td><td style='text-align:center'>" + str(r.get("Sites", 0)) + "</td>"
                                                                                                   "<td style='color:" + FAULT_COLORS.get(
            grp, "#64748b") + ";font-weight:700'>" + str(r.get("Total_Hours", 0)) + "h</td><td>" + str(
            r.get("Avg_Hours", 0)) + "h</td></tr>")

    # 6. Tab 4 SDCA Pivot (tab4_sdca_html)
    tab4_sdca_html = ""
    if not df_sdca_pivot.empty:
        tab4_sdca_html = "<div class='section'><h3> Fault Hours by SDCA</h3><table><thead><tr><th>SDCA</th>"
        for c in df_sdca_pivot.columns:
            if c not in ["sdca_name", "Total Hours"]:
                tab4_sdca_html += f"<th style='color:{FAULT_COLORS.get(c, '#64748b')}'>{c}</th>"
        tab4_sdca_html += "<th style='font-weight:800'>Total</th></tr></thead><tbody>"
        for _, r in df_sdca_pivot.iterrows():
            tab4_sdca_html += f"<tr><td><b>{str(r.get('sdca_name', ''))}</b></td>"
            for c in df_sdca_pivot.columns:
                if c not in ["sdca_name", "Total Hours"]:
                    val = r.get(c, 0)
                    cc = "#ef4444" if val > 100 else "#f97316" if val > 50 else "#10b981" if val > 0 else "#64748b"
                    tab4_sdca_html += f"<td style='color:{cc};font-weight:600;text-align:center'>{round(val, 1)}h</td>"
            tab4_sdca_html += f"<td style='font-weight:800;text-align:center'>{round(r.get('Total Hours', 0), 1)}h</td></tr>"
        tab4_sdca_html += "</tbody></table></div>"

    # 7. Tab 4 Detail Breakdown (tab4_detail_html)
    tab4_detail_html = ""
    if not df_alarm_ssa.empty and "fault_type" in df_alarm_ssa.columns:
        tab4_detail_html = "<div class='section'><h3>Detailed Fault Type Breakdown (within each Group)</h3>"
        for grp, sub_df in df_alarm_ssa.groupby("fault_group"):
            type_summary = sub_df.groupby("fault_type").agg(Events=("fault_type", "count"), Total_Hours=(
            "down_hours", "sum")).reset_index().sort_values("Total_Hours", ascending=False)
            tab4_detail_html += f"<h4 style='color:{FAULT_COLORS.get(grp, '#1e293b')}; margin-top:15px; border-bottom:1px solid #e2e8f0; padding-bottom:5px;'>{grp}</h4>"
            tab4_detail_html += "<table style='font-size:12px;'><thead><tr style='background:#f8fafc;'><th style='padding:8px;text-align:left;'>Fault Type</th><th style='padding:8px;text-align:center;'>Events</th><th style='padding:8px;text-align:center;'>Total Hours</th></tr></thead><tbody>"
            for _, row in type_summary.iterrows():
                tab4_detail_html += f"<tr style='border-bottom:1px solid #f1f5f9;'><td style='padding:8px;'>{row['fault_type']}</td><td style='padding:8px;text-align:center;'>{row['Events']}</td><td style='padding:8px;text-align:center;font-weight:700;'>{row['Total_Hours']:.1f}h</td></tr>"
            tab4_detail_html += "</tbody></table>"
        tab4_detail_html += "</div>"

    # 8. Tab 5 Site Ranking (tab5_html)
    tab5_html = "<div class='tab-view c5'><div class='section'><h3>Outage Ranking — All Sites (by Total Down Hours)</h3>"
    if not df_site_sum.empty:
        site_col = df_site_sum.columns[0]
        fg_cols = [c for c in df_site_sum.columns if c not in [site_col, "Total Hours", "Events", "sdca_name"]]
        tab5_html += "<table><thead><tr><th>Site</th><th>SDCA</th>"
        for c in fg_cols: tab5_html += f"<th style='color:{FAULT_COLORS.get(c, '#64748b')}'>{c}</th>"
        tab5_html += "<th>Events</th><th>Total Hours</th></tr></thead><tbody>"
        for _, r in df_site_sum.head(20).iterrows():
            tab5_html += f"<tr><td><b>{str(r.get(site_col, ''))}</b></td><td>{str(r.get('sdca_name', ''))}</td>"
            for c in fg_cols:
                val = r.get(c, 0)
                cc = "#ef4444" if val > 50 else "#f97316" if val > 20 else "#10b981" if val > 0 else "#64748b"
                tab5_html += f"<td style='color:{cc};text-align:center;font-weight:600'>{round(val, 1)}h</td>"
            tab5_html += f"<td style='text-align:center'>{int(r.get('Events', 0))}</td>"
            th = r.get("Total Hours", 0)
            thc = "#ef4444" if th > 20 else "#f97316" if th > 10 else "#10b981"
            tab5_html += f"<td style='color:{thc};font-weight:700'>{round(th, 2)}h</td></tr>"
        tab5_html += "</tbody></table></div></div>"
    else:
        tab5_html += "<p style='color:#64748b;padding:20px'>No outage data available.</p></div></div>"

    # 9. Tab 6 Heatmap (tab6_html)
    heatmap_headers = ""
    heatmap_rows = ""
    if df_trend is not None and not df_trend.empty:
        for p in df_trend["Period"]: heatmap_headers += "<th>" + str(p) + "</th>"
        for r in TECH_RULES:
            if r["profile"] in df_trend.columns:
                heatmap_rows += "<tr><td style='color:" + r["color"] + ";font-weight:700'>" + r["profile"] + "</td>"
                for p in df_trend["Period"]:
                    val = df_trend.loc[df_trend["Period"] == p, r["profile"]]
                    if val.empty or pd.isna(val.iloc[0]):
                        heatmap_rows += "<td>-</td>"
                    else:
                        bg, tc = avail_bg(val.iloc[0])
                        heatmap_rows += "<td style='background:" + bg + ";color:" + tc + ";text-align:center;font-weight:700'>" + str(
                            round(float(val.iloc[0]), 2)) + "</td>"
                heatmap_rows += "</tr>"

    tab6_html = "<div class='tab-view c6'>"
    tab6_html += "<div class='section'><h3>📈 Multi-Month Availability Trend</h3><div class='chart-container'>" + chart_trend_html + "</div></div>"
    tab6_html += "<div class='section'><h3>🗓️ Availability Heatmap — Period vs Tech</h3><table><thead><tr><th>Technology</th>" + heatmap_headers + "</tr></thead><tbody>" + heatmap_rows + "</tbody></table></div>"
    tab6_html += "<div class='section'><h3>⚡ Daily Fault Event Trend (Clustered for Troubleshooting)</h3><div class='chart-container'>" + chart_daily_html + "</div></div></div>"

    # 10. Tab 7 Summary (tab7_html)
    tab7_html = "<div class='tab-view c7'><div class='section'><h3> Network Summary & Node Distribution</h3>"
    tab7_html += "<div style='display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:20px;'>"
    tab7_html += f"<div style='background:#f8fafc;padding:14px;border-radius:8px;text-align:center;border:1px solid #e2e8f0'><div style='font-size:11px;color:#64748b;font-weight:600'>Total Network Nodes</div><div style='font-size:22px;font-weight:800;color:#2563eb'>{total_nodes}</div></div>"
    tab7_html += f"<div style='background:#f8fafc;padding:14px;border-radius:8px;text-align:center;border:1px solid #e2e8f0'><div style='font-size:11px;color:#64748b;font-weight:600'>Overall Weighted Availability</div><div style='font-size:22px;font-weight:800;color:{color_avail(overall_avail)}'>{overall_avail:.2f}%</div></div>"
    tab7_html += f"<div style='background:#f8fafc;padding:14px;border-radius:8px;text-align:center;border:1px solid #e2e8f0'><div style='font-size:11px;color:#64748b;font-weight:600'>4G Band Coverage (MHz)</div><div style='font-size:22px;font-weight:800;color:#7c3aed'>{band_700} / {band_2100} / {band_2500}</div></div>"
    tab7_html += "</div>"

    tab7_html += "<h4 style='margin:15px 0 10px;color:#1e293b;'>📡 Node Distribution by Technology & Vendor</h4>"
    tab7_html += "<table><thead><tr><th>Technology / Vendor</th><th>Node Count</th><th>Share (%)</th></tr></thead><tbody>"
    if tech_nodes is not None:
        for k, v in tech_nodes.items():
            share = round(v / total_nodes * 100, 2) if total_nodes > 0 else 0
            tab7_html += f"<tr><td style='font-weight:600'>{k}</td><td style='text-align:center'>{v}</td><td style='text-align:center'>{share}%</td></tr>"
    tab7_html += "</tbody></table>"

    tab7_html += "<h4 style='margin:15px 0 10px;color:#1e293b;'> Availability Distribution by Technology</h4>"
    tab7_html += "<table><thead><tr><th>Technology</th><th>Avg Availability (%)</th><th>Sites Count</th><th>Status</th></tr></thead><tbody>"
    if df_avail_dist is not None and not df_avail_dist.empty:
        for _, r in df_avail_dist.iterrows():
            bg, tc = avail_bg(r["Avg Avail (%)"])
            status = "✅ Excellent" if r["Avg Avail (%)"] >= 99 else "⚠️ Monitor" if r[
                                                                                        "Avg Avail (%)"] >= 97 else " Critical"
            tab7_html += f"<tr><td style='font-weight:600'>{r['Technology']}</td><td style='background:{bg};color:{tc};text-align:center;font-weight:700'>{r['Avg Avail (%)']:.2f}%</td><td style='text-align:center'>{r['Sites']}</td><td style='text-align:center;font-size:12px'>{status}</td></tr>"
    tab7_html += "</tbody></table></div></div>"

    # ── Degradation Driver HTML ─────────────────────────────────────
    deg_driver_html = ""
    if not df_deg.empty and 'alarm_deg' in locals() and not alarm_deg.empty:
        fault_contrib = alarm_deg.groupby("fault_group")["down_hours"].sum().reset_index().sort_values("down_hours",
                                                                                                       ascending=False)
        deg_driver_html = "<div class='section'><h3>🔍 Fault Groups Driving Degradation</h3><table><thead><tr><th>Fault Group</th><th>Total Hours Causing Drop</th></tr></thead><tbody>"
        for _, r in fault_contrib.iterrows():
            deg_driver_html += f"<tr><td style='color:{FAULT_COLORS.get(r['fault_group'], '#64748b')};font-weight:600'>{r['fault_group']}</td><td style='text-align:center;font-weight:700'>{round(r['down_hours'], 1)}h</td></tr>"
        deg_driver_html += "</tbody></table></div>"

    # ── Worst Performers HTML ───────────────────────────────────────
    worst_html_parts = ""
    for p in worst_dict:
        color = next((r["color"] for r in TECH_RULES if r["profile"] == p), "#64748b")
        ac = next((r["avail_col"] for r in TECH_RULES if r["profile"] == p), "")
        df_w = worst_dict.get(p, pd.DataFrame())
        worst_html_parts += "<div class='card'><h4 style='color:" + color + ";margin-top:0'>" + p + "</h4><table><thead><tr><th>Site</th><th>SDCA</th><th>Incharge</th><th>Avail</th></tr></thead><tbody>"
        for _, r in df_w.iterrows():
            worst_html_parts += "<tr><td>" + str(r.get("BTS Name", "")) + "</td><td>" + str(
                r.get("SDCA", "")) + "</td><td>" + str(r.get("incharge", "")) + "</td>" + avail_td_html(
                r.get(ac, "")) + "</tr>"
        worst_html_parts += "</tbody></table></div>"
    worst_html = "<div class='vendor-stack'>" + worst_html_parts + "</div>"

    # ── FINAL HTML ASSEMBLY (F-String Template) ───────────────────────
    html = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>BSNL Network Report - {ssa} - {target_period}</title>
        <style>{css}</style>
    </head>
    <body>
        <div class="header">
            <h1>BSNL Network Operations Intelligence Report</h1>
            <div class="meta">
                <span class="badge">SSA: {ssa}</span>
                <span>Report Period: <b>{target_period}</b> vs Baseline: <b>{base_period}</b></span>
                <span>Threshold: <b>{threshold}%</b></span>
                <span>Generated: {gen_time}</span>
            </div>
        </div>

        {kpi_bar}

        <div class="tabs-wrapper">
            <input type="radio" id="t1" name="tabs" class="tab-radio" checked>
            <input type="radio" id="t2" name="tabs" class="tab-radio">
            <input type="radio" id="t3" name="tabs" class="tab-radio">
            <input type="radio" id="t4" name="tabs" class="tab-radio">
            <input type="radio" id="t5" name="tabs" class="tab-radio">
            <input type="radio" id="t6" name="tabs" class="tab-radio">
            <input type="radio" id="t7" name="tabs" class="tab-radio">

            <div class="tab-nav">
                <label for="t1" class="tab-label l1"> Vendor</label>
                <label for="t2" class="tab-label l2"> Degradation</label>
                <label for="t3" class="tab-label l3"> SDCA</label>
                <label for="t4" class="tab-label l4"> Faults</label>
                <label for="t5" class="tab-label l5"> Sites</label>
                <label for="t6" class="tab-label l6"> Trends</label>
                <label for="t7" class="tab-label l7">📋 Summary</label>
            </div>

            <div class="tabs-content">
                <!-- Tab 1 -->
                <div class="tab-view c1">
                    <div class="section">
                        <h3>Technology & Vendor Availability — {target_period}</h3>
                        <div class="chart-container">{chart_vendor_html}</div>
                        <table>
                            <thead><tr><th>Profile</th><th>Vendor</th><th>Sites</th><th>Avg Avail</th><th>Min Avail</th><th>&lt;97%</th><th>&lt;95%</th><th>Data GB</th><th>Erlang</th></tr></thead>
                            <tbody>{vrows}</tbody>
                        </table>
                    </div>
                </div>

                <!-- Tab 2 -->
                <div class="tab-view c2">
                    <div class="section">
                        <h3>MoM Degradation — Sites dropped &gt;{threshold}%</h3>
                        <table>
                            <thead><tr><th>Site</th><th>SDCA</th><th>Incharge</th><th>Tech</th><th>Prev</th><th>Curr</th><th>Delta</th><th>Category</th><th>Primary Cause</th></tr></thead>
                            <tbody>{drows}</tbody>
                        </table>
                    </div>
                    {deg_driver_html}
                    <div class="section">
                        <h3>Worst Performing Sites by Vendor</h3>
                        {worst_html}
                    </div>
                </div>

                <!-- Tab 3 -->
                <div class="tab-view c3">
                    <div class="flex-grid">
                        <div class="card">
                            <h3 style="margin-top:0;font-size:14px;color:var(--blue)">SDCA Performance</h3>
                            <table>
                                <thead><tr><th>SDCA</th><th>Sites</th><th>Avg 2G</th><th>Avg 3G</th><th>Avg 4G</th><th>Overall Avail</th><th>&lt;97% 2G</th><th>Data GB</th></tr></thead>
                                <tbody>{srows}</tbody>
                            </table>
                        </div>
                        <div class="card">
                            <h3 style="margin-top:0;font-size:14px;color:var(--blue)">Incharge Accountability</h3>
                            <table>
                                <thead><tr><th>Incharge</th><th>Sites</th><th>Avg 2G</th><th>Avg 3G</th><th>Avg 4G</th><th>&lt;97%</th></tr></thead>
                                <tbody>{irows}</tbody>
                            </table>
                        </div>
                    </div>
                </div>

                <!-- Tab 4 -->
                <div class="tab-view c4">
                    <div class="section">
                        <h3>Outage Fault Group Summary</h3>
                        <div class="chart-container">{chart_fault_html}</div>
                        <table>
                            <thead><tr><th>Fault Group</th><th>Events</th><th>Sites</th><th>Total Hours</th><th>Avg hrs/Event</th></tr></thead>
                            <tbody>{arows}</tbody>
                        </table>
                    </div>
                    {tab4_sdca_html}
                    {tab4_detail_html}
                </div>

                <!-- Tab 5 -->
                <div class="tab-view c5">
                    <div class="section">
                        <h3>Outage Ranking — All Sites (by Total Down Hours)</h3>
                        {tab5_html}
                    </div>
                </div>

                <!-- Tab 6 -->
                <div class="tab-view c6">
                    <div class="section">
                        <h3>📈 Multi-Month Availability Trend</h3>
                        <div class="chart-container">{chart_trend_html}</div>
                    </div>
                    <div class="section">
                        <h3>🗓️ Availability Heatmap — Period vs Tech</h3>
                        <table>
                            <thead><tr><th>Technology</th>{heatmap_headers}</tr></thead>
                            <tbody>{heatmap_rows}</tbody>
                        </table>
                    </div>
                    <div class="section">
                        <h3>⚡ Daily Fault Event Trend (Clustered for Troubleshooting)</h3>
                        <div class="chart-container">{chart_daily_html}</div>
                    </div>
                </div>

                <!-- Tab 7 -->
                <div class="tab-view c7">
                    {tab7_html}
                </div>

            </div>
        </div>

        <div class="footer">BSNL Network Operations Intelligence &bull; {ssa} SSA &bull; Generated {gen_time} &bull; Internal Use Only</div>
    </body>
    </html>
    """
    return html
# ──────────────────────────────────────────────────────────────
# CUSTOM CSS
# ──────────────────────────────────────────────────────────────
st.markdown("""
<style>
[data-testid="stSidebar"] { background: #0f1b2d; }
[data-testid="stSidebar"] * { color: #e2e8f0 !important; }
.stTabs [data-baseweb="tab"] { font-size: 13px; font-weight: 600; }
</style>
""", unsafe_allow_html=True)


# ──────────────────────────────────────────────────────────────
# SIDEBAR
# ──────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 📡 BSNL Network Ops")
    st.markdown("---")
    st.markdown("### 📂 Upload Files")

    uploaded_nw = st.file_uploader(
        "Monthly NW Availability CSVs (multi-select for MoM)",
        type=["csv"],
        accept_multiple_files=True,
    )
    uploaded_inc = st.file_uploader(
        "Incharge Mapping — incharge_updated.xlsx",
        type=["xlsx", "csv"],
        accept_multiple_files=False,
    )
    uploaded_alarms = st.file_uploader(
        "Alarm / Fault Logs (csv / xls / xlsx)",
        type=["csv", "xls", "xlsx"],
        accept_multiple_files=True,
    )

    st.markdown("---")
    st.markdown("### 🎛️ Controls")

    # SSA selector — needs NW data to populate
    if uploaded_nw:
        try:
            _chunks = []
            for f in uploaded_nw:
                _chunks.append(pd.read_csv(io.BytesIO(f.read())))
                f.seek(0)
            _df_tmp = pd.concat(_chunks)
            _df_tmp.columns = _df_tmp.columns.str.strip()
            ssa_options = sorted(_df_tmp["SSA"].dropna().unique().tolist())
        except Exception:
            ssa_options = ["KARAIKUDI"]
        _default = ssa_options.index("KARAIKUDI") if "KARAIKUDI" in ssa_options else 0
        selected_ssa = st.selectbox("SSA", ssa_options, index=_default)
    else:
        selected_ssa = "KARAIKUDI"

    degradation_threshold = st.slider(
        "MoM Degradation Alert Threshold (%)",
        min_value=0.5, max_value=10.0, value=2.0, step=0.5,
    )
    top_n = st.slider("Worst Performers — Top N Sites", 5, 20, 10, 1)

    st.markdown("---")
    st.caption("BSNL Network Ops Intelligence v2.0")


# ──────────────────────────────────────────────────────────────
# LANDING PAGE
# ──────────────────────────────────────────────────────────────
if not uploaded_nw:
    st.title("📡 BSNL Network Operations Intelligence Dashboard")
    st.markdown("""
Upload your files in the sidebar to begin:

| File | Format | Notes |
|------|--------|-------|
| Monthly NW Availability | CSV | One per month; select multiple for MoM trend |
| Incharge Mapping | XLSX / CSV | `incharge_updated.xlsx` |
| Alarm / Fault Logs | CSV / XLS / XLSX | Daily logs; multiple files supported |

**Fault groups auto-classified:**
- 🔴 **EB Supply** — Mains failure, EB pole break, no mains, power cut
- 🟠 **Infra / Power** — Battery, Power plant, DG/Engine, Temperature
- 🔵 **Media / OFC** — OFC break, E1, SSA media, CPAN, CNTx-zone
- 🟣 **Hardware (BTS)** — Sector down, BTS hardware, reset issues
""")
    st.stop()


# ──────────────────────────────────────────────────────────────
# LOAD DATA
# ──────────────────────────────────────────────────────────────
with st.spinner("Loading network data…"):
    nw_bytes = [f.read() for f in uploaded_nw]
    for f in uploaded_nw:
        f.seek(0)
    nw_names = [f.name for f in uploaded_nw]
    df_nw_raw = load_network_data(nw_bytes, nw_names)

df_nw = df_nw_raw[
    df_nw_raw["SSA"].str.strip().str.upper() == selected_ssa.upper()
].copy()

# Incharge merge
if uploaded_inc:
    with st.spinner("Loading incharge mapping…"):
        inc_bytes = uploaded_inc.read()
        uploaded_inc.seek(0)
        df_inc = load_incharge(inc_bytes, uploaded_inc.name)
    df_nw = df_nw.merge(
        df_inc[["BTSIPID_CLEAN", "incharge", "SDCA"]].rename(columns={"SDCA": "SDCA_inc"}),
        left_on="BTS_IP_CLEAN",
        right_on="BTSIPID_CLEAN",
        how="left",
    )
    if "SDCA" not in df_nw.columns:
        df_nw["SDCA"] = df_nw["SDCA_inc"]
    elif "SDCA_inc" in df_nw.columns:
        df_nw["SDCA"] = df_nw["SDCA"].fillna(df_nw["SDCA_inc"])

# Alarm logs
df_alarm_ssa = pd.DataFrame()
if uploaded_alarms:
    with st.spinner("Loading alarm logs…"):
        al_bytes = [f.read() for f in uploaded_alarms]
        for f in uploaded_alarms:
            f.seek(0)
        al_names = [f.name for f in uploaded_alarms]
        df_alarm_all = load_alarm_logs(al_bytes, al_names)
    if not df_alarm_all.empty and "ssa_name" in df_alarm_all.columns:
        df_alarm_ssa = df_alarm_all[
            df_alarm_all["ssa_name"].str.strip().str.upper() == selected_ssa.upper()
        ].copy()
        if df_alarm_ssa.empty:
            df_alarm_ssa = df_alarm_all.copy()
    else:
        df_alarm_ssa = df_alarm_all.copy() if not df_alarm_all.empty else pd.DataFrame()

# Period resolution
periods = get_periods(df_nw_raw, selected_ssa)
if len(periods) == 0:
    st.error("No data found for selected SSA.")
    st.stop()

latest_period   = periods[-1]
previous_period = periods[-2] if len(periods) >= 2 else None

df_curr = df_nw[df_nw["Period"] == latest_period].copy()
# ── NEW: Overall Availability, Total Nodes & Band-wise Counts ──────────
band_cols_map = {
    "Band 700": "BTS Site ID (700)",
    "Band 2100": "BTS Site ID (2100)",
    "Band 41 (2500)": "BTS Site ID (2500)"
}
band_counts = {}
for label, col in band_cols_map.items():
    if col in df_curr.columns:
        valid = df_curr[col].dropna().astype(str).str.strip()
        band_counts[label] = len(valid[valid != ""])
    else:
        band_counts[label] = 0

total_nodes = df_curr["BTS_IP_CLEAN"].nunique() if "BTS_IP_CLEAN" in df_curr else len(df_curr)

# Weighted Overall Availability (2G/3G/4G)
tech_cols = {"2G": "Nw Avail (2G)", "3G": "Nw Avail (3G)", "4G": "4G_Avail_Final"}
overall_avail = 0.0
total_weight = 0
for tech, col in tech_cols.items():
    if col in df_curr.columns:
        s = df_curr[col].dropna()
        if len(s) > 0:
            overall_avail += s.mean() * len(s)
            total_weight += len(s)
overall_avail = (overall_avail / total_weight) if total_weight > 0 else 0.0

# SDCA-wise Overall Availability
sdca_overall_avail = {}
if "SDCA" in df_curr.columns:
    for sdca, sub in df_curr.groupby("SDCA"):
        w_a, w_t = 0.0, 0
        for tech, col in tech_cols.items():
            if col in sub.columns:
                s = sub[col].dropna()
                if len(s) > 0:
                    w_a += s.mean() * len(s)
                    w_t += len(s)
        sdca_overall_avail[sdca] = (w_a / w_t) if w_t > 0 else 0.0

df_prev = df_nw[df_nw["Period"] == previous_period].copy() if previous_period else pd.DataFrame()

# Compute analytics
df_vendor_sum  = get_vendor_summary(df_curr)
df_degradation = (
    get_degradation_report(df_curr, df_prev, degradation_threshold)
    if not df_prev.empty else pd.DataFrame()
)

# ── Add Top Reason (Primary Cause) to Degradation ────────────────
if not df_degradation.empty and not df_alarm_ssa.empty:
    degraded_ids = df_degradation["BTS IP ID"].unique()
    alarm_deg = df_alarm_ssa[df_alarm_ssa["bts_ip_id"].isin(degraded_ids)]
    if not alarm_deg.empty:
        # Top fault group by hours per site
        top_reason = (
            alarm_deg.groupby(["bts_ip_id", "fault_group"])["down_hours"]
            .sum().reset_index()
            .sort_values("down_hours", ascending=False)
            .drop_duplicates("bts_ip_id")
        )
        top_reason = top_reason[["bts_ip_id", "fault_group"]].rename(columns={"fault_group": "Primary Cause"})
        df_degradation = df_degradation.merge(top_reason, left_on="BTS IP ID", right_on="bts_ip_id", how="left").drop(columns=["bts_ip_id"])

df_sdca_sum = get_sdca_summary(df_curr)

# ── NEW: Network Summary Metrics ──────────────────────────────────
# 1. Node Counts by Tech/Vendor
tech_nodes = {}
masks = {
    "Nokia 2G":  df_curr["Vendor_Upper"].str.contains("NOKIA", na=False) & (df_curr["2G cnt"].fillna(0) > 0),
    "Nokia 3G":  df_curr["Vendor_Upper"].str.contains("NOKIA", na=False) & (df_curr["3G cnt"].fillna(0) > 0),
    "Nortel 2G": df_curr["Vendor_Upper"].str.contains("NORTEL", na=False) & (df_curr["2G cnt"].fillna(0) > 0),
    "ZTE 3G":    df_curr["Vendor_Upper"].str.contains("ZTE", na=False) & (df_curr["3G cnt"].fillna(0) > 0),
    "Tejas 4G":  df_curr["Vendor_Upper"].str.contains("TEJAS", na=False) & (df_curr["4G cnt"].fillna(0) > 0),
}
for label, mask in masks.items():
    tech_nodes[label] = df_curr[mask]["BTS_IP_CLEAN"].nunique() if "BTS_IP_CLEAN" in df_curr else len(df_curr[mask])

# 2. 4G Band-wise Counts
band_700  = len(df_curr[df_curr["BTS Site ID (700)"].notna() & (df_curr["BTS Site ID (700)"] != "")]) if "BTS Site ID (700)" in df_curr else 0
band_2100 = len(df_curr[df_curr["BTS Site ID (2100)"].notna() & (df_curr["BTS Site ID (2100)"] != "")]) if "BTS Site ID (2100)" in df_curr else 0
band_2500 = len(df_curr[df_curr["BTS Site ID (2500)"].notna() & (df_curr["BTS Site ID (2500)"] != "")]) if "BTS Site ID (2500)" in df_curr else 0

total_nodes = df_curr["BTS_IP_CLEAN"].nunique() if "BTS_IP_CLEAN" in df_curr else len(df_curr)

# 3. Weighted Overall Availability & Distribution
tech_avail_cols = {"2G": "Nw Avail (2G)", "3G": "Nw Avail (3G)", "4G": "4G_Avail_Final"}
weighted_avail = 0.0
total_weight = 0
avail_dist = []
for tech, col in tech_avail_cols.items():
    if col in df_curr.columns:
        s = df_curr[col].dropna()
        if len(s) > 0:
            avg = s.mean()
            weighted_avail += avg * len(s)
            total_weight += len(s)
            avail_dist.append({"Technology": tech, "Avg Avail (%)": round(avg, 3), "Sites": len(s)})
overall_avail = (weighted_avail / total_weight) if total_weight > 0 else 0.0
df_avail_dist = pd.DataFrame(avail_dist)

# ── NEW: Add SDCA-wise Overall Availability ─────────────────────
if not df_sdca_sum.empty and "SDCA" in df_sdca_sum.columns:
    sdca_overall_avail = {}
    tech_cols = {"2G": "Nw Avail (2G)", "3G": "Nw Avail (3G)", "4G": "4G_Avail_Final"}
    for sdca, sub in df_curr.groupby("SDCA"):
        w_a, w_t = 0.0, 0
        for tech, col in tech_cols.items():
            if col in sub.columns:
                s = sub[col].dropna()
                if len(s) > 0:
                    w_a += s.mean() * len(s)
                    w_t += len(s)
        sdca_overall_avail[sdca] = (w_a / w_t) if w_t > 0 else 0.0

    df_sdca_sum["Overall Avail (%)"] = df_sdca_sum["SDCA"].map(sdca_overall_avail).round(3)
    # Reorder columns to place Overall Avail right after Avg 4G
    cols = df_sdca_sum.columns.tolist()
    if "Overall Avail (%)" in cols and "Avg 4G (%)" in cols:
        cols.remove("Overall Avail (%)")
        cols.insert(cols.index("Avg 4G (%)") + 1, "Overall Avail (%)")
        df_sdca_sum = df_sdca_sum[cols]

df_inc_sum = get_incharge_summary(df_curr)

worst_dict = {}
for r in TECH_RULES:
    worst_dict[r["profile"]] = get_worst_performers(
        df_curr, r["vendor_key"], r["cnt_col"], r["avail_col"], top_n
    )

# Alarm analytics
df_alarm_grp   = alarm_group_summary(df_alarm_ssa)   if not df_alarm_ssa.empty else pd.DataFrame()
df_site_sum    = alarm_site_summary(df_alarm_ssa)    if not df_alarm_ssa.empty else pd.DataFrame()
df_sdca_pivot  = alarm_sdca_pivot(df_alarm_ssa)      if not df_alarm_ssa.empty else pd.DataFrame()
df_alarm_trend = alarm_daily_trend(df_alarm_ssa)     if not df_alarm_ssa.empty else pd.DataFrame()

# ── Compute Trend Data for HTML Report ────────────────────────
trend_rows = []
for p in periods:
    df_p = df_nw[df_nw["Period"] == p]
    row = {"Period": p}
    for r in TECH_RULES:
        vk = r["vendor_key"]
        cc = r["cnt_col"]
        ac = r["avail_col"]
        mask = df_p["Vendor_Upper"].str.contains(vk, na=False) & (df_p.get(cc, 0).fillna(0) > 0)
        sub = df_p[mask]
        if not sub.empty and ac in sub.columns:
            row[r["profile"]] = round(sub[ac].mean(), 3)
    trend_rows.append(row)
df_trend = pd.DataFrame(trend_rows)

# ──────────────────────────────────────────────────────────────
# PAGE HEADER
# ──────────────────────────────────────────────────────────────
col_hdr, col_btn = st.columns([5, 1])
with col_hdr:
    st.title("📡 BSNL Network Ops Intelligence — " + selected_ssa)
    period_info = "Period: **" + latest_period + "**"
    if previous_period:
        period_info += " vs **" + previous_period + "**"
    period_info += " | Threshold: **" + str(degradation_threshold) + "%**"
    st.caption(period_info)

with col_btn:
    if not df_vendor_sum.empty:
        # ── Calculate KPI Values ────────────────────────────────
        total_sites = len(df_curr)
        avg_2g = df_curr["Nw Avail (2G)"].mean() if "Nw Avail (2G)" in df_curr else 0.0
        avg_3g = df_curr["Nw Avail (3G)"].mean() if "Nw Avail (3G)" in df_curr else 0.0
        avg_4g = df_curr["4G_Avail_Final"].mean() if "4G_Avail_Final" in df_curr else 0.0
        sites_below_97 = int((df_curr.get("Nw Avail (2G)", pd.Series()) < 97).sum())
        total_outage_hrs = df_alarm_ssa["down_hours"].sum() if not df_alarm_ssa.empty else 0
        power_eb_hrs = (
            df_alarm_ssa[df_alarm_ssa["fault_group"].isin(["EB Supply", "Infra / Power"])]["down_hours"].sum()
            if not df_alarm_ssa.empty else 0
        )

        # ── Prepare Trend Data for HTML Export ────────────────────────────────
        df_trend_html = None
        if len(periods) >= 2:
            t_rows = []
            for p in periods:
                df_p = df_nw[df_nw["Period"] == p]
                row = {"Period": p}
                for r in TECH_RULES:
                    vk, cc, ac, prof = r["vendor_key"], r["cnt_col"], r["avail_col"], r["profile"]
                    mask = df_p["Vendor_Upper"].str.contains(vk, na=False) & (df_p.get(cc, 0).fillna(0) > 0)
                    sub = df_p[mask]
                    if not sub.empty and ac in sub.columns:
                        row[prof] = round(sub[ac].mean(), 3)
                t_rows.append(row)
            df_trend_html = pd.DataFrame(t_rows) if t_rows else None

        html_out = build_html_report(
            selected_ssa, latest_period, previous_period or "N/A",
            degradation_threshold, df_vendor_sum, df_degradation,
            df_sdca_sum, df_inc_sum, df_alarm_grp,
            df_sdca_pivot, df_site_sum, worst_dict,
            df_trend, df_alarm_ssa, df_curr,
            total_sites=total_sites, avg_2g=avg_2g, avg_3g=avg_3g, avg_4g=avg_4g,
            sites_below_97=sites_below_97, total_outage_hrs=total_outage_hrs, power_eb_hrs=power_eb_hrs,
            overall_avail=overall_avail, total_nodes=total_nodes,
            band_700=band_700, band_2100=band_2100, band_2500=band_2500,
            tech_nodes=tech_nodes, df_avail_dist=df_avail_dist
        )
        st.download_button(
            label="⬇️ Export HTML",
            data=html_out,
            file_name="BSNL_" + selected_ssa + "_" + latest_period.replace(" ", "_") + ".html",
            mime="text/html",
            use_container_width=True,
        )


# ──────────────────────────────────────────────────────────────
# KPI ROW
# ──────────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════
# KPI ROW — UPDATED WITH OVERALL & BAND-WISE METRICS
# ══════════════════════════════════════════════════════════════

# ── 1. Calculate Existing Metrics ────────────────────────────
total_sites    = len(df_curr)
avg_2g         = df_curr["Nw Avail (2G)"].mean()    if "Nw Avail (2G)"    in df_curr else 0.0
avg_3g         = df_curr["Nw Avail (3G)"].mean()    if "Nw Avail (3G)"    in df_curr else 0.0
avg_4g         = df_curr["4G_Avail_Final"].mean()   if "4G_Avail_Final"   in df_curr else 0.0
sites_below_97 = int((df_curr.get("Nw Avail (2G)", pd.Series()) < 97).sum())
total_alarm_h  = df_alarm_ssa["down_hours"].sum() if not df_alarm_ssa.empty else 0
power_h = (
    df_alarm_ssa[df_alarm_ssa["fault_group"].isin(["EB Supply", "Infra / Power"])]["down_hours"].sum()
    if not df_alarm_ssa.empty else 0
)

# ── 2. Calculate NEW Metrics (Overall Avail, Nodes, Bands) ───
band_cols_map = {
    "Band 700": "BTS Site ID (700)",
    "Band 2100": "BTS Site ID (2100)",
    "Band 41": "BTS Site ID (2500)"
}
band_counts = {}
for label, col in band_cols_map.items():
    if col in df_curr.columns:
        valid = df_curr[col].dropna().astype(str).str.strip()
        band_counts[label] = len(valid[valid != ""])
    else:
        band_counts[label] = 0

total_nodes = df_curr["BTS_IP_CLEAN"].nunique() if "BTS_IP_CLEAN" in df_curr else len(df_curr)

# Weighted Overall Availability (2G+3G+4G)
tech_cols = {"2G": "Nw Avail (2G)", "3G": "Nw Avail (3G)", "4G": "4G_Avail_Final"}
overall_avail = 0.0
total_weight = 0
for tech, col in tech_cols.items():
    if col in df_curr.columns:
        s = df_curr[col].dropna()
        if len(s) > 0:
            overall_avail += s.mean() * len(s)
            total_weight += len(s)
overall_avail = (overall_avail / total_weight) if total_weight > 0 else 0.0

# ── 3. Helper Function ───────────────────────────────────────
def kpi_card(col, label, value, color="#3b82f6", sub=" "):
    col.markdown(
        f"<div style='background:#1e293b;border:1px solid #334155;border-radius:10px;"
        f"padding:12px 14px;text-align:center'>"
        f"<div style='font-size:9px;color:#94a3b8;font-weight:600;text-transform:uppercase;"
        f"letter-spacing:.4px;margin-bottom:3px'>{label}</div>"
        f"<div style='font-size:22px;font-weight:800;color:{color}'>{value}</div>"
        f"<div style='font-size:9px;color:#64748b;margin-top:2px'>{sub}</div>"
        f"</div>", unsafe_allow_html=True)

# ── 4. Render Cards ──────────────────────────────────────────
# Row 1: Core Network KPIs
k1, k2, k3, k4, k5, k6 = st.columns(6)
kpi_card(k1, "Total Nodes", total_nodes, "#3b82f6", "Unique BTS Sites")
kpi_card(k2, "Overall Avail", f"{overall_avail:.2f}%", color_avail(overall_avail), "Weighted Avg")
kpi_card(k3, "Avg 2G", f"{avg_2g:.2f}%", color_avail(avg_2g))
kpi_card(k4, "Avg 3G", f"{avg_3g:.2f}%", color_avail(avg_3g))
kpi_card(k5, "Avg 4G", f"{avg_4g:.2f}%", color_avail(avg_4g))
kpi_card(k6, "Sites <97% (2G)", sites_below_97, "#ef4444" if sites_below_97 > 0 else "#10b981")

# Row 2: 4G Band-wise & Outage KPIs
b1, b2, b3, o1, o2 = st.columns(5)
kpi_card(b1, "4G Band 700", band_counts["Band 700"], "#6366f1", "Nodes")
kpi_card(b2, "4G Band 2100", band_counts["Band 2100"], "#8b5cf6", "Nodes")
kpi_card(b3, "4G Band 41", band_counts["Band 41"], "#06b6d4", "Nodes")
kpi_card(o1, "Total Outage Hrs", f"{total_alarm_h:.1f}h", "#94a3b8")
kpi_card(o2, "Power/EB Hrs", f"{power_h:.1f}h", "#f97316" if power_h > 10 else "#10b981")

st.markdown("<br>", unsafe_allow_html=True)

# ──────────────────────────────────────────────────────────────
# MAIN TABS
# ──────────────────────────────────────────────────────────────
tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs([
    "📊 Vendor Summary",
    "🚨 Degradation & Worst Sites",
    "🏢 SDCA / Incharge",
    "⚡ Fault Analysis",
    "🔎 Site Drill-Down",
    " Trends",
    "📋 Network Summary & Nodes"  # ← NEW TAB
])

# ══════════════════════════════════════════════════════════════
# TAB 1 — VENDOR SUMMARY
# ══════════════════════════════════════════════════════════════
with tab1:
    st.subheader("Technology & Vendor Availability — " + latest_period)
    if df_vendor_sum.empty:
        st.warning("No vendor data found for the selected SSA and period.")
    else:
        display_cols = [
            "Profile", "Vendor", "Sites",
            "Avg Avail (%)", "Min Avail (%)",
            "Sites <97%", "Sites <95%",
            "Data GB", "Erl Total",
        ]
        st.dataframe(
            styled_avail_df(df_vendor_sum[display_cols], ["Avg Avail (%)", "Min Avail (%)"]),
            use_container_width=True,
            height=260,
        )

        st.markdown("---")
        c1, c2 = st.columns(2)
        with c1:
            fig = px.bar(
                df_vendor_sum, x="Profile", y="Avg Avail (%)",
                color="Profile",
                color_discrete_sequence=[r["color"] for r in TECH_RULES if r["profile"] in df_vendor_sum["Profile"].values],
                title="Average Network Availability by Tech-Vendor",
                text="Avg Avail (%)",
            )
            fig.update_traces(texttemplate="%{text:.2f}%", textposition="outside")
            fig.add_hline(y=97, line_dash="dash", line_color="#f59e0b", annotation_text="97% SLA")
            fig.add_hline(y=95, line_dash="dash", line_color="#ef4444", annotation_text="95% Critical")
            fig.update_layout(
                plot_bgcolor="#0f172a", paper_bgcolor="#0f172a",
                font_color="#e2e8f0", yaxis_range=[88, 101], showlegend=False,
            )
            st.plotly_chart(fig, use_container_width=True)

        with c2:
            fig2 = px.bar(
                df_vendor_sum, x="Profile", y=["Sites <97%", "Sites <95%"],
                barmode="group", title="Sites Below Threshold",
                color_discrete_map={"Sites <97%": "#f59e0b", "Sites <95%": "#ef4444"},
            )
            fig2.update_layout(
                plot_bgcolor="#0f172a", paper_bgcolor="#0f172a", font_color="#e2e8f0"
            )
            st.plotly_chart(fig2, use_container_width=True)

        c3, c4 = st.columns(2)
        with c3:
            fig3 = px.pie(
                df_vendor_sum, names="Profile", values="Data GB",
                title="Data Traffic Share (GB)", hole=0.4,
            )
            fig3.update_layout(paper_bgcolor="#0f172a", font_color="#e2e8f0")
            st.plotly_chart(fig3, use_container_width=True)
        with c4:
            fig4 = px.pie(
                df_vendor_sum, names="Profile", values="Erl Total",
                title="Voice Traffic Share (Erlang)", hole=0.4,
            )
            fig4.update_layout(paper_bgcolor="#0f172a", font_color="#e2e8f0")
            st.plotly_chart(fig4, use_container_width=True)
    with st.expander("🔍 Cross-Check: Vendor Site Counts (Rows vs Unique Sites)"):
        import pandas as pd

        st.info("Comparing 'Row Count' (current) vs 'Unique BTS_IP' (true site count).")

        check_results = []
        for r in TECH_RULES:
            vk, cc = r["vendor_key"], r["cnt_col"]

            # 1. Replicate your current logic
            mask = df_curr["Vendor_Upper"].str.contains(vk, na=False) & (df_curr[cc].fillna(0) > 0)
            sub = df_curr[mask]

            row_count = len(sub)
            unique_count = sub["BTS_IP_CLEAN"].nunique() if "BTS_IP_CLEAN" in sub else 0

            check_results.append({
                "Profile": r["profile"],
                "Current (Rows)": row_count,
                "True Unique Sites": unique_count,
                "Over-count": row_count - unique_count
            })

            # 2. Specific Debug for Tejas 4G
            if r["profile"] == "Tejas 4G ":
                if row_count > unique_count:
                    st.warning(f"⚠️ **Tejas 4G**: Found {row_count - unique_count} duplicate rows inflating the count.")

                    # Show duplicate IP entries
                    dupes = sub[sub["BTS_IP_CLEAN"].duplicated(keep=False)]
                    if not dupes.empty:
                        st.markdown("**Sample Duplicates:**")
                        st.dataframe(
                            dupes.sort_values("BTS_IP_CLEAN")
                            .head(20)[["BTS_IP_CLEAN", "BTS Name", "SDCA", "4G cnt", "4G_Avail_Final"]],
                            use_container_width=True
                        )

        st.dataframe(pd.DataFrame(check_results), use_container_width=True)
    with st.expander("🔍 Verify: Dashboard vs Manual Count Logic"):
        st.write("Comparing `get_vendor_summary()` output with your manual cross-check formulas.")

        manual_results = []
        for _, row in df_vendor_sum.iterrows():
            profile = row["Profile"]
            dash_count = row["Sites"]

            # Replicate YOUR manual logic
            if profile == "Nokia 2G":
                manual_df = df_curr[
                    df_curr["Vendor"].str.contains("NOKIA", na=False) &
                    df_curr["BTS Site ID (2G)"].astype(str).str.contains("BCF", na=False)
                    ]
                manual_count = manual_df["BTS Site ID (2G)"].nunique() if "BTS Site ID (2G)" in manual_df else 0
            elif profile == "Nokia 3G":
                manual_df = df_curr[
                    df_curr["Vendor"].str.contains("NOKIA", na=False) &
                    df_curr["BTS Site ID (3G)"].astype(str).str.contains("WBTS", na=False)
                    ]
                manual_count = manual_df["BTS Site ID (3G)"].nunique() if "BTS Site ID (3G)" in manual_df else 0
            elif profile == "ZTE 3G":
                manual_df = df_curr[
                    df_curr["Vendor"].str.contains("ZTE", na=False) &
                    df_curr["BTS Site ID (3G)"].notna()
                    ]
                manual_count = manual_df["BTS Site ID (3G)"].nunique() if "BTS Site ID (3G)" in manual_df else 0
            elif profile == "Nortel 2G":
                manual_df = df_curr[df_curr["Vendor"].str.contains("NORTEL", na=False)]
                manual_count = manual_df["BTS Name"].nunique() if "BTS Name" in manual_df else 0
            elif profile == "Tejas 4G":
                manual_df = df_curr[df_curr["Vendor"].str.contains("TEJAS", na=False)]
                manual_count = manual_df["BTS Name"].nunique() if "BTS Name" in manual_df else 0
            else:
                manual_count = dash_count  # Fallback

            match = "✅" if dash_count == manual_count else "❌"
            manual_results.append({
                "Profile": profile,
                "Dashboard": dash_count,
                "Manual": manual_count,
                "Match": match,
                "Diff": dash_count - manual_count
            })

        st.dataframe(pd.DataFrame(manual_results), use_container_width=True)

        if any(r["Match"] == "❌" for r in manual_results):
            st.warning("⚠️ Counts still don't match! Check column names in your data.")
        else:
            st.success("✅ All counts now match your manual cross-check logic!")

# ══════════════════════════════════════════════════════════════
# TAB 2 — DEGRADATION & WORST SITES
# ══════════════════════════════════════════════════════════════
with tab2:
    st.subheader("MoM Degradation — Threshold: >" + str(degradation_threshold) + "%")

    if previous_period is None:
        st.info("Upload 2 or more monthly NW files to enable MoM analysis.")
    elif df_degradation.empty:
        st.success("No sites degraded beyond " + str(degradation_threshold) + "% this month.")
    else:
        st.error(
            str(len(df_degradation)) + " site-technology combinations dropped more than "
            + str(degradation_threshold) + "% from " + str(previous_period)
            + " to " + str(latest_period) + "."
        )
        st.dataframe(
            styled_avail_df(df_degradation, ["Prev Month (%)", "Curr Month (%)"]),
            use_container_width=True,
        )
        if "SDCA" in df_degradation.columns:
            deg_sdca = df_degradation.groupby("SDCA")["Delta (%)"].mean().reset_index()
            fig_d = px.bar(
                deg_sdca, x="SDCA", y="Delta (%)",
                title="Avg Availability Drop by SDCA",
                color="Delta (%)", color_continuous_scale="Reds_r",
            )
            fig_d.update_layout(
                plot_bgcolor="#0f172a", paper_bgcolor="#0f172a", font_color="#e2e8f0"
            )
            st.plotly_chart(fig_d, use_container_width=True)

    st.markdown("---")
    st.subheader("Worst Performing Sites — " + latest_period)

    for row_profiles in [["Nokia 2G", "Nortel 2G", "Nokia 3G"], ["Tejas 4G", "ZTE 3G"]]:
        valid = [p for p in row_profiles if p in worst_dict and not worst_dict[p].empty]
        if not valid:
            continue
        cols_ui = st.columns(len(valid))
        for col_ui, profile in zip(cols_ui, valid):
            rule = next((r for r in TECH_RULES if r["profile"] == profile), None)
            if rule is None:
                continue
            color = rule["color"]
            col_ui.markdown(
                "<div style='font-weight:700;font-size:13px;color:" + color + ";margin-bottom:6px'>"
                + profile + "</div>",
                unsafe_allow_html=True,
            )
            df_w = worst_dict[profile]
            ac = rule["avail_col"]
            col_ui.dataframe(
                styled_avail_df(df_w, [ac] if ac in df_w.columns else []),
                use_container_width=True,
                height=320,
            )


# ══════════════════════════════════════════════════════════════
# TAB 3 — SDCA / INCHARGE
# ══════════════════════════════════════════════════════════════
with tab3:
    c1, c2 = st.columns(2)

    with c1:
        st.subheader("SDCA Sub-Division Summary")
        if df_sdca_sum.empty:
            st.warning("No SDCA data. Check that the SDCA column is present.")
        else:
            acols = [c for c in ["Avg 2G (%)", "Avg 3G (%)", "Avg 4G (%)"] if c in df_sdca_sum.columns]
            st.dataframe(styled_avail_df(df_sdca_sum, acols), use_container_width=True)
            if "Avg 2G (%)" in df_sdca_sum.columns:
                fig_s = px.bar(
                    df_sdca_sum.sort_values("Avg 2G (%)"),
                    x="Avg 2G (%)", y="SDCA", orientation="h",
                    title="SDCA — Avg 2G Availability",
                    color="Avg 2G (%)", color_continuous_scale="RdYlGn",
                    range_color=[90, 100], text="Avg 2G (%)",
                )
                fig_s.update_traces(texttemplate="%{text:.2f}%")
                fig_s.update_layout(
                    plot_bgcolor="#0f172a", paper_bgcolor="#0f172a", font_color="#e2e8f0",
                    yaxis={"categoryorder": "total ascending"},
                )
                st.plotly_chart(fig_s, use_container_width=True)

    with c2:
        st.subheader("Incharge Accountability")
        if df_inc_sum.empty:
            st.info("Upload the incharge mapping file to see accountability data.")
        else:
            acols = [c for c in ["Avg 2G (%)", "Avg 3G (%)", "Avg 4G (%)"] if c in df_inc_sum.columns]
            st.dataframe(styled_avail_df(df_inc_sum, acols), use_container_width=True)
            if "Avg 2G (%)" in df_inc_sum.columns:
                fig_i = px.bar(
                    df_inc_sum.sort_values("Avg 2G (%)"),
                    x="Avg 2G (%)", y="Incharge", orientation="h",
                    title="Incharge — Avg 2G Availability",
                    color="Avg 2G (%)", color_continuous_scale="RdYlGn",
                    range_color=[90, 100], text="Avg 2G (%)",
                )
                fig_i.update_traces(texttemplate="%{text:.2f}%")
                fig_i.update_layout(
                    plot_bgcolor="#0f172a", paper_bgcolor="#0f172a", font_color="#e2e8f0",
                )
                st.plotly_chart(fig_i, use_container_width=True)

    # Multi-metric radar — SDCA
    if not df_sdca_sum.empty:
        radar_cols = [c for c in ["Avg 2G (%)", "Avg 3G (%)", "Avg 4G (%)"] if c in df_sdca_sum.columns]
        if len(radar_cols) >= 2:
            st.markdown("---")
            st.subheader("SDCA Multi-Technology Radar")
            df_radar = df_sdca_sum[["SDCA"] + radar_cols].dropna()
            fig_r = go.Figure()
            for _, row in df_radar.iterrows():
                fig_r.add_trace(go.Scatterpolar(
                    r=[row[c] for c in radar_cols],
                    theta=radar_cols,
                    fill="toself",
                    name=str(row["SDCA"]),
                ))
            fig_r.update_layout(
                polar=dict(radialaxis=dict(range=[85, 101], visible=True)),
                showlegend=True,
                paper_bgcolor="#0f172a",
                font_color="#e2e8f0",
                title="SDCA Availability Across Technologies",
            )
            st.plotly_chart(fig_r, use_container_width=True)


# ══════════════════════════════════════════════════════════════
# TAB 4 — FAULT ANALYSIS
# ══════════════════════════════════════════════════════════════
with tab4:
    if df_alarm_ssa.empty:
        st.info("Upload alarm/fault log files to enable fault analysis.")
    else:
        # KPIs
        total_ev = len(df_alarm_ssa)
        total_dh = df_alarm_ssa["down_hours"].sum()
        eb_ev    = len(df_alarm_ssa[df_alarm_ssa["fault_group"] == "EB Supply"])
        infra_ev = len(df_alarm_ssa[df_alarm_ssa["fault_group"] == "Infra / Power"])
        media_ev = len(df_alarm_ssa[df_alarm_ssa["fault_group"] == "Media / OFC"])
        hw_ev    = len(df_alarm_ssa[df_alarm_ssa["fault_group"] == "Hardware (BTS)"])

        fa1, fa2, fa3, fa4, fa5, fa6 = st.columns(6)
        kpi_card(fa1, "Total Events",    total_ev,                    "#3b82f6")
        kpi_card(fa2, "Total Down Hrs",  str(round(total_dh, 1)) + "h", "#ef4444")
        kpi_card(fa3, "EB Supply",       eb_ev,                       "#ef4444")
        kpi_card(fa4, "Infra / Power",   infra_ev,                    "#f97316")
        kpi_card(fa5, "Media / OFC",     media_ev,                    "#3b82f6")
        kpi_card(fa6, "Hardware",        hw_ev,                       "#a855f7")
        st.markdown("<br>", unsafe_allow_html=True)

        # ── Summary table + charts
        st.subheader("Fault Group Summary")
        ca, cb = st.columns([2, 3])
        with ca:
            disp_grp = df_alarm_grp.rename(columns={
                "fault_group": "Fault Group",
                "Total_Hours": "Total Hrs",
                "Avg_Hours":   "Avg Hrs/Event",
            })
            st.dataframe(disp_grp, use_container_width=True)
        with cb:
            fig_fg = px.bar(
                df_alarm_grp, x="fault_group", y="Total_Hours",
                color="fault_group",
                color_discrete_map=FAULT_COLORS,
                title="Total Outage Hours by Fault Group",
                text="Total_Hours",
            )
            fig_fg.update_traces(texttemplate="%{text:.1f}h", textposition="outside")
            fig_fg.update_layout(
                plot_bgcolor="#0f172a", paper_bgcolor="#0f172a",
                font_color="#e2e8f0", showlegend=False,
            )
            st.plotly_chart(fig_fg, use_container_width=True)

        cc, cd = st.columns(2)
        with cc:
            fig_p1 = px.pie(
                df_alarm_grp, names="fault_group", values="Total_Hours",
                color="fault_group", color_discrete_map=FAULT_COLORS,
                title="Hours Distribution", hole=0.4,
            )
            fig_p1.update_layout(paper_bgcolor="#0f172a", font_color="#e2e8f0")
            st.plotly_chart(fig_p1, use_container_width=True)
        with cd:
            fig_p2 = px.pie(
                df_alarm_grp, names="fault_group", values="Events",
                color="fault_group", color_discrete_map=FAULT_COLORS,
                title="Event Count Distribution", hole=0.4,
            )
            fig_p2.update_layout(paper_bgcolor="#0f172a", font_color="#e2e8f0")
            st.plotly_chart(fig_p2, use_container_width=True)

        # ── SDCA pivot
        if not df_sdca_pivot.empty:
            st.markdown("---")
            st.subheader("Fault Hours by SDCA")
            st.dataframe(df_sdca_pivot, use_container_width=True)
            sdca_col_name = "sdca_name"
            melt_cols = [c for c in df_sdca_pivot.columns if c not in [sdca_col_name, "Total Hours"]]
            df_melt = df_sdca_pivot.melt(
                id_vars=[sdca_col_name], value_vars=melt_cols,
                var_name="Fault Group", value_name="Hours",
            )
            fig_sp = px.bar(
                df_melt, x=sdca_col_name, y="Hours", color="Fault Group",
                color_discrete_map=FAULT_COLORS,
                title="Outage Hours by SDCA (Stacked)",
                barmode="stack",
            )
            fig_sp.update_layout(
                plot_bgcolor="#0f172a", paper_bgcolor="#0f172a", font_color="#e2e8f0"
            )
            st.plotly_chart(fig_sp, use_container_width=True)

        # ── Per-group detailed breakdown
        st.markdown("---")
        st.subheader("Detailed Fault Type Breakdown (within each Group)")
        groups_present = df_alarm_ssa["fault_group"].unique().tolist()
        for grp in groups_present:
            sub = df_alarm_ssa[df_alarm_ssa["fault_group"] == grp]
            raw_ft = (
                sub.groupby("fault_type")
                .agg(Events=("fault_type", "count"), Total_Hours=("down_hours", "sum"))
                .reset_index()
                .sort_values("Total_Hours", ascending=False)
            )
            raw_ft["Total_Hours"] = raw_ft["Total_Hours"].round(2)
            gc = FAULT_COLORS.get(grp, "#94a3b8")
            header = grp + " — " + str(len(sub)) + " events / " + str(round(sub["down_hours"].sum(), 2)) + "h"
            with st.expander(header, expanded=False):
                st.markdown("**Raw fault types in this group:**")
                st.dataframe(raw_ft, use_container_width=True)
                detail_cols = [
                    c for c in
                    ["bts_name", "bts_type", "vendor", "fault_type",
                     "bts_down_dt", "bts_up_dt", "down_hours", "sdca_name"]
                    if c in sub.columns
                ]
                st.markdown("**Alarm records:**")
                st.dataframe(
                    sub[detail_cols].sort_values("down_hours", ascending=False).reset_index(drop=True),
                    use_container_width=True,
                )


# ══════════════════════════════════════════════════════════════
# TAB 5 — SITE DRILL-DOWN
# ══════════════════════════════════════════════════════════════
with tab5:
    st.subheader("Site-Level Network Availability Search")
    search_site = st.text_input("Search by BTS Name or BTS IP ID", placeholder="e.g. Sathankulam")
    if search_site:
        mask = (
            df_curr["BTS Name"].str.lower().str.contains(search_site.lower(), na=False)
            | df_curr["BTS_IP_CLEAN"].str.lower().str.contains(search_site.lower(), na=False)
        )
        df_found = df_curr[mask].copy()
        if df_found.empty:
            st.warning("No sites matched.")
        else:
            disp = ["BTS IP ID", "BTS Name", "SDCA"]
            if "incharge" in df_found.columns:
                disp.append("incharge")
            for c in ["Nw Avail (2G)", "Nw Avail (3G)", "4G_Avail_Final",
                       "Erl Total", "Data GB Total", "Site Category"]:
                if c in df_found.columns:
                    disp.append(c)
            ac_cols = [c for c in ["Nw Avail (2G)", "Nw Avail (3G)", "4G_Avail_Final"] if c in df_found.columns]
            st.dataframe(
                styled_avail_df(df_found[disp].reset_index(drop=True), ac_cols),
                use_container_width=True,
            )

    st.markdown("---")
    st.subheader("Outage Ranking — All Sites (by Total Down Hours)")
    if df_alarm_ssa.empty:
        st.info("Upload alarm log files to see site outage ranking.")
    else:
        st.dataframe(df_site_sum.head(40), use_container_width=True)
        if not df_site_sum.empty:
            site_col_0 = df_site_sum.columns[0]
            fig_sr = px.bar(
                df_site_sum.head(20), x=site_col_0, y="Total Hours",
                color="Total Hours", color_continuous_scale="Reds",
                title="Top 20 Sites — Outage Hours",
            )
            fig_sr.update_layout(
                plot_bgcolor="#0f172a", paper_bgcolor="#0f172a",
                font_color="#e2e8f0", xaxis_tickangle=-40,
            )
            st.plotly_chart(fig_sr, use_container_width=True)

        st.markdown("---")
        st.subheader("Alarm Log Detail — Filter by Site")
        site_options = ["All"] + sorted(
            df_alarm_ssa.get("bts_name", pd.Series()).dropna().unique().tolist()
        )
        selected_site = st.selectbox("Select Site", site_options)
        df_filtered = (
            df_alarm_ssa if selected_site == "All"
            else df_alarm_ssa[df_alarm_ssa["bts_name"] == selected_site]
        )
        detail_c = [
            c for c in
            ["bts_name", "bts_type", "vendor", "fault_type", "fault_group",
             "bts_down_dt", "bts_up_dt", "down_hours", "sdca_name"]
            if c in df_filtered.columns
        ]
        st.dataframe(
            df_filtered[detail_c].sort_values("down_hours", ascending=False).reset_index(drop=True),
            use_container_width=True,
        )

# ══════════════════════════════════════════════════════════════
# TAB 6 — TRENDS
# ══════════════════════════════════════════════════════════════
# ══════════════════════════════════════════════════════════════
# TAB 6 — TRENDS
# ══════════════════════════════════════════════════════════════
with tab6:
    st.subheader("Multi-Month Availability Trend")
    if len(periods) < 2:
        st.info("Upload 2 or more monthly NW files to see trend charts.")
    else:
        trend_rows = []
        for p in periods:
            # Safe Period matching (handles with/without trailing spaces)
            df_p = df_nw[df_nw["Period"].str.strip() == p.strip()]
            row = {"Period": p.strip()}  # 🔽 Fixed: No trailing space

            for r in TECH_RULES:
                vk = r.get("vendor_key", "").strip()
                cc = r.get("cnt_col", "").strip()
                ac = r.get("avail_col", "").strip()
                profile = r.get("profile", "").strip()

                if cc not in df_p.columns or ac not in df_p.columns:
                    continue

                mask = df_p["Vendor_Upper"].str.contains(vk, na=False) & (df_p[cc].fillna(0) > 0)
                sub = df_p[mask]
                if not sub.empty:
                    row[profile] = round(sub[ac].mean(), 3)
            trend_rows.append(row)

        df_trend = pd.DataFrame(trend_rows)

        # Safe profile extraction
        valid_profiles = [
            r.get("profile", "").strip()
            for r in TECH_RULES
            if r.get("profile", "").strip() in df_trend.columns
        ]

        if valid_profiles:
            fig_tr = go.Figure()
            for prof in valid_profiles:
                rule = next((r for r in TECH_RULES if r.get("profile", "").strip() == prof), None)
                color = rule.get("color", "#fff") if rule else "#fff"

                fig_tr.add_trace(go.Scatter(
                    x=df_trend["Period"],
                    y=df_trend[prof],
                    mode="lines+markers+text",
                    name=prof,
                    line=dict(color=color, width=2),
                    text=df_trend[prof].round(2).astype(str) + "%",
                    textposition="top center",
                ))
            fig_tr.add_hline(y=97, line_dash="dash", line_color="#f59e0b", annotation_text="97% SLA")
            fig_tr.update_layout(
                title="MoM Network Availability Trend",
                plot_bgcolor="#0f172a", paper_bgcolor="#0f172a",
                font_color="#e2e8f0", yaxis_range=[88, 101],
                xaxis_title="Period", yaxis_title="Avg Availability (%)",
                legend=dict(bgcolor="#1e293b", bordercolor="#334155"),
            )
            st.plotly_chart(fig_tr, use_container_width=True)

            # 🔽 FIXED: Use "Period" (no trailing space) for heatmap index
            heat_data = df_trend.set_index("Period")[valid_profiles].T
            fig_hm = px.imshow(
                heat_data,
                color_continuous_scale="RdYlGn",
                zmin=90, zmax=100,
                title="Availability Heatmap — Period vs Tech",
                text_auto=".2f",
            )
            fig_hm.update_layout(paper_bgcolor="#0f172a", font_color="#e2e8f0")
            st.plotly_chart(fig_hm, use_container_width=True)

    # Daily alarm trend
    st.markdown("---")
    st.subheader("Daily Fault Event Trend")
    if df_alarm_trend.empty:
        st.info("Upload alarm log files to see daily fault trends.")
    else:
        fig_dt = px.bar(
            df_alarm_trend, x="date", y="Hours", color="fault_group",
            color_discrete_map=FAULT_COLORS,
            title="Daily Outage Hours by Fault Group",
            barmode="stack",
        )
        fig_dt.update_layout(
            plot_bgcolor="#0f172a", paper_bgcolor="#0f172a", font_color="#e2e8f0"
        )
        st.plotly_chart(fig_dt, use_container_width=True)

        fig_dt2 = px.bar(
            df_alarm_trend, x="date", y="Events", color="fault_group",
            color_discrete_map=FAULT_COLORS,
            title="Daily Alarm Event Count by Fault Group",
            barmode="stack",
        )
        fig_dt2.update_layout(
            plot_bgcolor="#0f172a", paper_bgcolor="#0f172a", font_color="#e2e8f0"
        )
        st.plotly_chart(fig_dt2, use_container_width=True)

# ══════════════════════════════════════════════════════════════
# TAB 7 — NETWORK SUMMARY & NODE DISTRIBUTION
# ══════════════════════════════════════════════════════════════
with tab7:
    st.subheader("📋 Network Summary & Node Distribution")
    c1, c2, c3 = st.columns(3)
    kpi_card(c1, "Total Network Nodes", total_nodes, "#3b82f6")
    kpi_card(c2, "Overall Weighted Availability", f"{overall_avail:.2f}%", color_avail(overall_avail))
    kpi_card(c3, "4G Band Coverage", f"{band_700}/{band_2100}/{band_2500}", "#8b5cf6", "MHz")
    st.markdown("---")

    st.subheader("📡 Node Distribution by Technology & Vendor")
    node_df = pd.DataFrame(list(tech_nodes.items()), columns=["Technology/Vendor", "Node Count"])
    node_df["Share (%)"] = (node_df["Node Count"] / total_nodes * 100).round(2)
    st.dataframe(node_df, use_container_width=True)

    st.markdown("---")
    st.subheader("📊 Availability Distribution")
    st.dataframe(styled_avail_df(df_avail_dist, ["Avg Avail (%)"]), use_container_width=True)

    c1, c2 = st.columns(2)
    with c1:
        fig_node = px.pie(node_df, names="Technology/Vendor", values="Node Count", title="Node Distribution Share", hole=0.4)
        fig_node.update_layout(paper_bgcolor="#0f172a", font_color="#e2e8f0")
        st.plotly_chart(fig_node, use_container_width=True)
    with c2:
        fig_avail = px.bar(df_avail_dist, x="Technology", y="Avg Avail (%)", color="Technology", text="Avg Avail (%)")
        fig_avail.update_traces(texttemplate="%{text:.2f}%")
        fig_avail.add_hline(y=97, line_dash="dash", line_color="#f59e0b")
        fig_avail.update_layout(paper_bgcolor="#0f172a", font_color="#e2e8f0", yaxis_range=[90, 100])
        st.plotly_chart(fig_avail, use_container_width=True)
