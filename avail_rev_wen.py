#!/usr/bin/env python3
"""
TN Circle Mobile Network Intelligence Dashboard — v4 FINAL
===========================================================
• Vendor decode from RBC TECH codes (H2G/Z3G/TCS4G → Huawei/ZTE/TCS)
• Outage filtered per technology (correct site counts: 2G=239, 3G=151, 4G=246)
• Site Master List: vendor × technology × revenue × availability
• MoM revenue AND availability worst/best comparison with LOCATION
• Auto-Analytics (No API key required)
• HTML downloadable reports for every major section
• Data Quality: lists unmatched / unknown-SDCA sites
• Tolerant XLS 97-2003 reader with FAT-corruption patch
• Incharge performance scoring from failure data
• Failure-Availability correlation
"""
import io, base64, datetime, json, textwrap
import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
import plotly.io as pio

st.set_page_config(
    page_title="TN Circle Network Dashboard",
    layout="wide",  # This enables full-width layout
    page_icon="📡",
    initial_sidebar_state="expanded"
)

# ── Constants ────────────────────────────────────────────────────────────────
MONTH_ORDER = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
               "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}
SSAID_TO_CODE = {
    "TNCOI": "CBE", "TNCOO": "CON", "TNCUD": "CDL", "TNDHA": "DPI",
    "TNERO": "ERD", "TNKAR": "KKD", "TNKUM": "CRDA", "TNMAD": "MA",
    "TNNAG": "NGC", "TNPON": "PY", "TNSAL": "SLM", "TNTHA": "TNJ",
    "TNTIR": "TVL", "TNTRI": "TR", "TNTUT": "TT", "TNVEL": "VLR", "TNVIR": "VGR",
}
CODE_TO_SSAID = {v: k for k, v in SSAID_TO_CODE.items()}
SSA_DISPLAY = {
    "CBE": "Coimbatore", "CON": "Coonoor", "CDL": "Cuddalore", "DPI": "Dharmapuri",
    "ERD": "Erode", "KKD": "Karaikudi", "NGC": "Nagercoil", "MA": "Madurai",
    "PY": "Pondicherry", "SLM": "Salem", "TNJ": "Thanjavur", "TVL": "Tirunelveli",
    "TT": "Tuticorin", "VLR": "Vellore", "VGR": "Virudhunagar", "TR": "Trichy", "CRDA": "CRDA",
}
CAT_ORDER = ["VHT", "HT", "MT", "LT", "VLT"]
AVAIL_COLS = {"2G": "Nw Avail (2G)", "3G": "Nw Avail (3G)", "4G TCS": "Nw Avail (4G TCS)"}
REV_NUM_COLS = ["TOT_TRAFFIC", "TOT_DATA", "TRAFFIC_REV", "DATA_REV", "TOT_REV", "REV_LAKH",
                "2g_rev", "3g_rev", "4g_rev", "2G_Traffic", "2G_Data", "3G_Traffic", "3G_Data",
                "4G_Traffic", "4G_Data", "Perday_2G_Erl", "Perday_3G_GB", "Perday_4G_GB"]

VEND_COLORS = {
    "Huawei": "#CF0A2C", "Nokia/NSN": "#0057A8", "Nortel": "#7B2D8B",
    "Motorola": "#E377C2", "ZTE": "#F5A623", "TCS/Tejas": "#17BECF",
    "Nokia/NSN+TCS": "#00CC96", "Ericsson": "#BCBD22", "Unknown": "#aaaaaa",
}
TC_COLORS = {
    "2G":"#636EFA","3G":"#EF553B","4G Total":"#00CC96",
    "4G 700":"#19D3F3","4G 2100":"#FF6692","4G 2500":"#B6E880",
}
TECH2G_MAP = {"H2G": "Huawei", "NSN2G": "Nokia/NSN", "Z2G": "ZTE", "N2G": "Nortel", "M2G": "Motorola"}
TECH3G_MAP = {"Z3G": "ZTE", "NSN3G": "Nokia/NSN", "H3G": "Huawei", "N3G": "Nortel"}
TECH4G_MAP = {"TCS4G": "TCS/Tejas", "NSN4G": "Nokia/NSN", "NSN4G & TCS4G": "Nokia/NSN+TCS"}


# ── Small helpers ─────────────────────────────────────────────────────────────
def month_sort_key(lbl):
    try:
        m = lbl[:3].lower(); y = int(lbl[3:]); return y * 100 + MONTH_ORDER.get(m, 0)
    except:
        return 0


def make_month_label(month_str, year_val):
    try:
        m = str(month_str).strip()[:3].lower();
        y = str(int(year_val))[-2:]
        return f"{m}{y}"
    except:
        return str(month_str)


def _avail_color(val):
    try:
        v = float(val)
        if v < 90: return "background-color:#ffcccc"
        if v < 95: return "background-color:#fff3cd"
        return "background-color:#d4edda"
    except:
        return ""


def _rev_color(val):
    try:
        v = float(val)
        if v == 0:  return "background-color:#ffcccc"
        if v < 0.3: return "background-color:#fff3cd"
        if v >= 1:  return "background-color:#d4edda"
        return ""
    except:
        return ""


def safe_style(df, fn=_avail_color, subset=None):
    df2 = df.reset_index(drop=True).copy()
    df2 = df2.loc[:, ~df2.columns.duplicated()]
    if subset is not None:
        subset = [c for c in subset if c in df2.columns]
        if not subset: subset = None
    try:
        s = df2.style.map(fn, subset=subset);
        s._compute();
        return s
    except:
        return df2


def _avail_td(v):
    try:
        f = float(v)
        if f < 90: return "bad"
        if f < 95: return "warn"
        return "ok"
    except:
        return ""


def _rev_td(v):
    try:
        f = float(v)
        if f == 0: return "bad"
        if f < 0.3: return "warn"
        if f >= 1: return "ok"
        return ""
    except:
        return ""


# ── Vendor helpers ─────────────────────────────────────────────────────────────
def get_radio_vendor(v):
    if pd.isna(v) or str(v).strip() in ["", "nan", "None", "0"]: return "Unknown"
    parts = [p.strip().upper() for p in str(v).split(";")]
    for p in ["NORTEL", "MOTOROLA", "HUAWEI", "NOKIA", "ZTE"]:
        if any(p in x for x in parts): return "Nokia/NSN" if p == "NOKIA" else p.title()
    if any("TEJAS" in x for x in parts): return "TCS/Tejas"
    return parts[0].title()


def get_4g_vendor_from_str(v, has_4g):
    if not has_4g: return "—"
    if pd.isna(v): return "Unknown"
    parts = [p.strip().upper() for p in str(v).split(";")]
    if any("TEJAS" in x for x in parts): return "TCS/Tejas"
    return "Unknown"


def get_3g_vendor_from_str(v, has_3g):
    if not has_3g: return "—"
    if pd.isna(v): return "Unknown"
    parts = [p.strip().upper() for p in str(v).split(";")]
    if any("NOKIA" in x or "NSN" in x for x in parts): return "Nokia/NSN"
    if any("ZTE" in x for x in parts): return "ZTE"
    return "Unknown"


# ── Tolerant XLS Reader with Full Reset ─────────────────────────────────────
def _tolerant_read_file(uploaded_file):
    import io, warnings
    raw = uploaded_file.read()
    uploaded_file.seek(0)
    fname = uploaded_file.name.lower()

    if fname.endswith(".csv"):
        for enc in ["utf-8", "latin1", "cp1252"]:
            try:
                return pd.read_csv(io.BytesIO(raw), encoding=enc)
            except:
                pass

    if fname.endswith((".xlsx", ".xlsm")):
        try:
            return pd.read_excel(io.BytesIO(raw), engine="openpyxl")
        except Exception as e:
            raise ValueError(f"Cannot read XLSX: {e}")

    try:
        import xlrd, xlrd.compdoc as _cd
        _orig = _cd.CompDoc._locate_stream

        def _tolerant_locate(self, qname, seen_types, parent_sid, *a, **kw):
            max_retries, retries = 50, 0
            while retries < max_retries:
                try:
                    return _orig(self, qname, seen_types, parent_sid, *a, **kw)
                except _cd.CompDocError as e:
                    msg = str(e)
                    if "corruption: seen[" in msg:
                        try:
                            self.seen = [0] * len(self.seen)
                            retries += 1
                        except:
                            raise e
                    else:
                        raise
            raise _cd.CompDocError(f"Too many FAT corruptions in {qname}")

        _cd.CompDoc._locate_stream = _tolerant_locate
        try:
            warnings.filterwarnings("ignore")
            wb = xlrd.open_workbook(file_contents=raw)
            sh = wb.sheet_by_index(0)
            headers = [str(sh.cell_value(0, c)).strip() for c in range(sh.ncols)]
            data = []
            for r in range(1, sh.nrows):
                row = [sh.cell_value(r, c) for c in range(sh.ncols)]
                data.append(row)
            return pd.DataFrame(data, columns=headers)
        finally:
            _cd.CompDoc._locate_stream = _orig
    except ImportError:
        pass
    except Exception as xls_err:
        for sep in ["\t", ","]:
            for enc in ["utf-8", "latin1", "cp1252"]:
                try:
                    return pd.read_csv(io.BytesIO(raw), sep=sep, encoding=enc)
                except:
                    pass
        raise ValueError(f"Cannot read '{uploaded_file.name}'. Error: {xls_err}")

    try:
        return pd.read_excel(io.BytesIO(raw), engine="openpyxl")
    except Exception:
        pass
    raise ValueError(f"Cannot read '{uploaded_file.name}'. Try CSV or XLSX.")


# ── HTML Report Generators ──────────────────────────────────────────────────
def _html_head(title, ssa_label, month_label):
    ts = datetime.datetime.now().strftime("%d %b %Y %H:%M")
    return f"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<title>{title}</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:'Segoe UI',Tahoma,sans-serif;background:#f0f2f5;color:#222;padding:20px}}
.hdr{{background:linear-gradient(135deg,#1a237e,#0d47a1);color:#fff;padding:26px 32px;
border-radius:12px;margin-bottom:22px;display:flex;justify-content:space-between;align-items:flex-end}}
.hdr h1{{font-size:1.6em;margin-bottom:5px}}.hdr .meta{{font-size:.82em;opacity:.8;line-height:1.8}}
.hdr .stamp{{font-size:.72em;opacity:.55;text-align:right}}
.krow{{display:flex;gap:14px;flex-wrap:wrap;margin-bottom:20px}}
.kpi{{background:#fff;border-radius:10px;padding:16px 20px;flex:1;min-width:130px;
box-shadow:0 2px 8px rgba(0,0,0,.08);border-left:5px solid #3949ab}}
.kpi.g{{border-color:#2e7d32}}.kpi.r{{border-color:#c62828}}.kpi.a{{border-color:#e65100}}
.kpi .v{{font-size:1.75em;font-weight:700;color:#1a237e;line-height:1.1}}
.kpi.g .v{{color:#2e7d32}}.kpi.r .v{{color:#c62828}}.kpi.a .v{{color:#e65100}}
.kpi .l{{font-size:.73em;color:#777;margin-top:4px}}
.sec{{background:#fff;border-radius:10px;padding:20px 24px;margin-bottom:18px;
box-shadow:0 2px 8px rgba(0,0,0,.07)}}
.sec h2{{font-size:1.05em;color:#1a237e;border-bottom:2px solid #e8eaf6;
padding-bottom:8px;margin-bottom:14px}}
table{{border-collapse:collapse;width:100%;font-size:.79em;table-layout:fixed;word-break:break-word}}
thead th{{background:#e8eaf6;color:#1a237e;padding:8px 11px;text-align:left;
font-weight:600;border-bottom:2px solid #c5cae9}}
tbody td{{padding:6px 11px;border-bottom:1px solid #f3f4f9;overflow-wrap:break-word}}
tbody tr:hover td{{background:#f5f6ff}}
.ok{{background:#e8f5e9!important}}.warn{{background:#fff8e1!important}}
.bad{{background:#ffebee!important}}.hi{{background:#e3f2fd!important}}
.two{{display:grid;grid-template-columns:1fr 1fr;gap:14px}}
.footer{{text-align:center;font-size:.7em;color:#aaa;margin-top:28px;
padding:12px 0;border-top:1px solid #e0e0e0}}
</style></head><body>
<div class="hdr"><div><div style="font-size:.8em;opacity:.65;margin-bottom:3px">📡 TN Circle</div>
<h1>{title}</h1><div class="meta">SSA: <b>{ssa_label}</b> | Period: <b>{month_label.upper()}</b></div></div>
<div class="stamp">Generated<br>{ts}</div></div>"""


def _kpi_h(val, label, cls=""):
    return f'<div class="kpi {cls}"><div class="v">{val}</div><div class="l">{label}</div></div>'


def _fig_html(fig, h=320):
    try:
        return pio.to_html(fig, full_html=False, include_plotlyjs="cdn",
                           config={"displayModeBar": False}, default_height=f"{h}px")
    except:
        return "<p><em>Chart unavailable</em></p>"


def _df_html(df, col_cls=None, maxr=300):
    if df is None or len(df) == 0: return "<p>No data.</p>"
    df2 = df.head(maxr).copy()
    ths = "".join(f"<th>{c}</th>" for c in df2.columns)
    rows = []
    for _, row in df2.iterrows():
        tds = []
        for c, val in row.items():
            css = col_cls[c](val) if col_cls and c in col_cls else ""
            s = f"{val:.2f}" if isinstance(val, float) and not np.isnan(val) else (
                "—" if (isinstance(val, float) and np.isnan(val)) else str(val))
            tds.append(f'<td class="{css}">{s}</td>')
        rows.append("<tr>" + "".join(tds) + "</tr>")
    return f"<table><thead><tr>{ths}</tr></thead><tbody>{''.join(rows)}</tbody></table>"


def _sec(title, body): return f'<div class="sec"><h2>{title}</h2>{body}</div>'


def _krow(kpis): return f'<div class="krow">{"".join(kpis)}</div>'


def _dl_btn(html_str, filename, label="⬇️ Download HTML Report"):
    st.download_button(label, data=html_str.encode(),
                       file_name=filename, mime="text/html", key=f"dl_{filename}")


def gen_exec_html(df_lat, rev_lat, avail_existing, sdca_sum, sdca_vendor,
                  ven_matrix, unmatched_sites, ssa_label, month_label, has_revenue):
    total = df_lat["BTS IP ID"].nunique()
    s2g = int(df_lat["_has2g"].sum()) if "_has2g" in df_lat.columns else 0
    s3g = int(df_lat["_has3g"].sum()) if "_has3g" in df_lat.columns else 0
    s4g = int(df_lat["Has_4G_Physical"].sum())
    kpis = [_kpi_h(f"{total:,}", "Total Sites"),
            _kpi_h(f"{s2g:,}", "2G Sites"),
            _kpi_h(f"{s3g:,}", "3G Sites"),
            _kpi_h(f"{s4g:,}", "4G Physical")]
    for tech, col in avail_existing.items():
        avg = df_lat[col].mean()
        n95 = int((df_lat[col] < 95).sum())
        cls = "g" if avg >= 97 else ("a" if avg >= 93 else "r")
        kpis += [_kpi_h(f"{avg:.2f}%", f"Avg {tech} Avail", cls),
                 _kpi_h(str(n95), f"{tech} <95%", "r" if n95 > 5 else "a")]
    if has_revenue and rev_lat is not None:
        tr = rev_lat["REV_LAKH"].sum()
        zr = int((rev_lat["REV_LAKH"] == 0).sum())
        kpis += [_kpi_h(f"₹{tr:.2f}L", "Total Revenue", "g"),
                 _kpi_h(str(zr), "Zero Rev Sites", "r")]
    # ── Total Traffic & Data Computation ──────────────────────────────────
    total_2g_erl = df_lat["Erl (2g)"].sum() if "Erl (2g)" in df_lat.columns else 0
    total_3g_erl = df_lat["Erl (3g)"].sum() if "Erl (3g)" in df_lat.columns else 0
    total_4g_erl = df_lat["Erl Total"].sum() if "Erl Total" in df_lat.columns else 0
    total_erl = total_2g_erl + total_3g_erl + total_4g_erl

    total_2g_gb = df_lat["Data GB (2g)"].sum() if "Data GB (2g)" in df_lat.columns else 0
    total_3g_gb = df_lat["Data GB (3g)"].sum() if "Data GB (3g)" in df_lat.columns else 0
    total_4g_gb = df_lat["Data GB Total"].sum() if "Data GB Total" in df_lat.columns else 0
    total_data_tb = (total_2g_gb + total_3g_gb + total_4g_gb) / 1024  # Convert GB to TB

    kpis += [
        _kpi_h(f"{total_erl:,.0f}", "Total Erlangs", "g"),
        _kpi_h(f"{total_data_tb:.2f} TB", "Total Data", "g"),
        _kpi_h(f"{total_2g_erl:,.0f}", "2G Erlangs"),
        _kpi_h(f"{total_3g_erl:,.0f}", "3G Erlangs"),
        _kpi_h(f"{total_4g_erl:,.0f}", "4G Erlangs"),
        _kpi_h(f"{total_2g_gb / 1024:.2f} TB", "2G Data"),
        _kpi_h(f"{total_3g_gb / 1024:.2f} TB", "3G Data"),
        _kpi_h(f"{total_4g_gb / 1024:.2f} TB", "4G Data"),
    ]

    # SDCA tables
    sdca_site_tbl = ""
    sdca_avail_tbl = ""
    sdca_rev_tbl = ""
    sdca_vendor_tbl = ""
    # ── SDCA-wise Traffic & Data Table ────────────────────────────────────
    sdca_traffic_tbl = ""
    if "SDCA" in df_lat.columns:
        traffic_rows = []
        for sdca_name, sdca_df_group in df_lat.groupby("SDCA"):
            row = {
                "SDCA": sdca_name,
                "2G Erl": round(sdca_df_group["Erl (2g)"].sum(), 1) if "Erl (2g)" in sdca_df_group.columns else 0,
                "3G Erl": round(sdca_df_group["Erl (3g)"].sum(), 1) if "Erl (3g)" in sdca_df_group.columns else 0,
                "4G Erl": round(sdca_df_group["Erl Total"].sum(), 1) if "Erl Total" in sdca_df_group.columns else 0,
                "2G Data (TB)": round(sdca_df_group["Data GB (2g)"].sum() / 1024,
                                      3) if "Data GB (2g)" in sdca_df_group.columns else 0,
                "3G Data (TB)": round(sdca_df_group["Data GB (3g)"].sum() / 1024,
                                      3) if "Data GB (3g)" in sdca_df_group.columns else 0,
                "4G Data (TB)": round(sdca_df_group["Data GB Total"].sum() / 1024,
                                      3) if "Data GB Total" in sdca_df_group.columns else 0,
            }
            traffic_rows.append(row)
        if traffic_rows:
            sdca_traffic_df = pd.DataFrame(traffic_rows).sort_values("4G Erl", ascending=False)
            sdca_traffic_tbl = _df_html(sdca_traffic_df.round(3))


    if sdca_sum is not None and len(sdca_sum):
        # Site counts table
        site_cols = ["SDCA", "Total Sites", "2G Sites", "3G Sites", "4G Sites"]
        site_cols = [c for c in site_cols if c in sdca_sum.columns]
        sdca_site_tbl = _df_html(sdca_sum[site_cols])

        # Availability table
        avail_cols = ["SDCA"] + [c for c in sdca_sum.columns if c.startswith("Avg") and "%" in c]
        sdca_avail_tbl = _df_html(sdca_sum[avail_cols].round(2),
                                  {c: _avail_td for c in avail_cols if "%" in c})

        # Revenue table
        rev_cols = ["SDCA", "Rev_Total", "Avg Rev/Site (L)", "Zero_Sites", "Sites_with_Rev"]
        rev_cols = [c for c in rev_cols if c in sdca_sum.columns]
        sdca_rev_tbl = _df_html(sdca_sum[rev_cols].round(3))

    if sdca_vendor is not None and len(sdca_vendor):
        sdca_vendor_tbl = _df_html(sdca_vendor)

    avail_chart = ""
    if "SDCA" in df_lat.columns:
        ac = [c for c in avail_existing.values() if c in df_lat.columns]
        av = df_lat.groupby("SDCA")[ac].mean().round(2).reset_index()
        av.columns = ["SDCA"] + [c.replace("Nw Avail (", "").replace(")", "") for c in ac]
        sc = [c for c in av.columns if c != "SDCA"]
        fig = go.Figure(go.Heatmap(z=av[sc].values, x=sc, y=av["SDCA"].tolist(),
                                   colorscale="RdYlGn", zmin=85, zmax=100,
                                   text=[[f"{v:.1f}%" for v in row] for row in av[sc].values],
                                   texttemplate="%{text}", textfont={"size": 11}))
        fig.update_layout(title="Availability % — SDCA × Technology", height=340, margin=dict(t=40, b=10))
        avail_chart = _fig_html(fig, 340)

    ven_chart = ""
    if ven_matrix is not None and len(ven_matrix):
        fig2 = px.bar(ven_matrix, x="Vendor",
                      y=[col for col in ["Sites_2G", "Sites_3G", "Sites_4G_Total"] if col in ven_matrix.columns],
                      barmode="group", text_auto=True,
                      labels={"value": "Sites", "variable": "Technology"},
                      color_discrete_map={"Sites_2G": "#636EFA", "Sites_3G": "#EF553B", "Sites_4G_Total": "#00CC96"})
        fig2.for_each_trace(lambda t: t.update(name=t.name.replace("Sites_", "")))
        fig2.update_layout(height=300, margin=dict(t=30, b=10))
        ven_chart = _fig_html(fig2, 300)

    ven_tbl = _df_html(ven_matrix.round(2)) if ven_matrix is not None and len(ven_matrix) else ""
    unm_tbl = _df_html(unmatched_sites) if unmatched_sites is not None and len(
        unmatched_sites) else "<p>None — all sites matched.</p>"

    body = (_krow(kpis) +
            _sec("📊 SDCA-wise Traffic & Data", sdca_traffic_tbl) +
            _sec("📍 SDCA-wise Sites & Technology",
                 f'<div class="two"><div>{avail_chart}</div><div>{sdca_site_tbl}</div></div>') +
            _sec("📡 SDCA-wise Availability", sdca_avail_tbl) +
            _sec("💰 SDCA-wise Revenue", sdca_rev_tbl) +
            _sec("🏭 SDCA × Vendor Breakdown", sdca_vendor_tbl) +
            _sec("🏭 Vendor × Technology", f'<div class="two"><div>{ven_chart}</div><div>{ven_tbl}</div></div>') +
            _sec("⚠️ Unmatched Sites (No Revenue Data)", unm_tbl) +
            f'<div class="footer">TN Circle Executive Summary — {month_label.upper()}</div>')
    return _html_head(f"Executive Summary — {ssa_label}", ssa_label, month_label) + body + "</body></html>"

def gen_revenue_html(rdf, ssa_label, month_label, prev_rdf=None, prev_month=""):
    tr = rdf["REV_LAKH"].sum();
    sites = rdf["BTSIPID"].nunique()
    zr = int((rdf["REV_LAKH"] == 0).sum());
    avg_r = rdf["REV_LAKH"].mean()
    kpis = [_kpi_h(f"₹{tr:.2f}L", "Total Revenue", "g"),
            _kpi_h(f"{sites:,}", "Total Sites"),
            _kpi_h(f"₹{avg_r:.3f}L", "Avg Rev/Site"),
            _kpi_h(str(zr), "Zero Rev Sites", "r")]

    tech_vals = {t: rdf[c].sum() for t, c in [("2G", "2g_rev"), ("3G", "3g_rev"), ("4G", "4g_rev")] if c in rdf.columns}
    tech_chart = ""
    if tech_vals:
        fig = px.pie(values=list(tech_vals.values()), names=list(tech_vals.keys()), hole=0.42,
                     color_discrete_map={"2G": "#636EFA", "3G": "#EF553B", "4G": "#00CC96"})
        fig.update_layout(height=260);
        tech_chart = _fig_html(fig, 260)

    sdca_chart = ""
    if "SDCA" in rdf.columns:
        sd = rdf.groupby("SDCA")["REV_LAKH"].sum().reset_index().sort_values("REV_LAKH", ascending=False)
        fig3 = px.bar(sd, x="SDCA", y="REV_LAKH", text="REV_LAKH", color="REV_LAKH",
                      color_continuous_scale="Blues", title="Revenue by SDCA")
        fig3.update_traces(texttemplate="₹%{text:.2f}L", textposition="outside")
        fig3.update_layout(coloraxis_showscale=False, height=300);
        sdca_chart = _fig_html(fig3, 300)

    mom_html = "<p class='note'>Load 2 months of RBC data for MoM comparison.</p>"
    if prev_rdf is not None and len(prev_rdf):
        mom = rdf[["BTSIPID", "REV_LAKH", "SDCA"]].merge(
            prev_rdf[["BTSIPID", "REV_LAKH"]].rename(columns={"REV_LAKH": "REV_PREV"}),
            on="BTSIPID", how="outer").fillna(0)
        mom["Δ Rev"] = (mom["REV_LAKH"] - mom["REV_PREV"]).round(3)
        gain = mom.nlargest(20, "Δ Rev")[["BTSIPID", "SDCA", "REV_PREV", "REV_LAKH", "Δ Rev"]].round(3)
        loss = mom.nsmallest(20, "Δ Rev")[["BTSIPID", "SDCA", "REV_PREV", "REV_LAKH", "Δ Rev"]].round(3)
        mom_html = (f'<div class="two">'
                    f'<div><h3>📈 Top 20 Gainers</h3>{_df_html(gain, {"Δ Rev": _rev_td})}</div>'
                    f'<div><h3>📉 Top 20 Losers</h3>{_df_html(loss)}</div></div>')

    show_rc = [c for c in ["BTSIPID", "SDCA", "REV_LAKH", "2g_rev", "3g_rev", "4g_rev", "4G_Cat"] if c in rdf.columns]
    top25 = rdf.nlargest(25, "REV_LAKH")[show_rc].reset_index(drop=True).round(3)

    body = (_krow(kpis) +
            _sec("Revenue by Technology", f'<div class="two"><div>{tech_chart}</div><div>{sdca_chart}</div></div>') +
            _sec("📈 MoM Comparison", mom_html) +
            _sec("🏆 Top 25 Sites", _df_html(top25, {"REV_LAKH": _rev_td})) +
            f'<div class="footer">TN Circle Revenue Intelligence — {month_label.upper()}</div>')
    return _html_head(f"Revenue Report — {ssa_label}", ssa_label, month_label) + body + "</body></html>"


def gen_avail_html(df_lat, avail_existing, ven_matrix, sdca_sum,
                   ssa_label, month_label, prev_df_lat=None, prev_month=""):
    kpis = []
    for tech, col in avail_existing.items():
        if col not in df_lat.columns: continue
        avg = df_lat[col].mean();
        n90 = int((df_lat[col] < 90).sum());
        n95 = int((df_lat[col] < 95).sum())
        cls = "g" if avg >= 97 else ("a" if avg >= 93 else "r")
        kpis += [_kpi_h(f"{avg:.2f}%", f"Avg {tech} Avail", cls),
                 _kpi_h(str(n90), f"{tech} <90% 🔴", "r"),
                 _kpi_h(str(n95 - n90), f"{tech} 90-95% 🟡", "a")]

    worst_tbls = ""
    for tech, col in avail_existing.items():
        if col not in df_lat.columns: continue
        w = df_lat.nsmallest(20, col)[["BTS IP ID", "BTS Name", "SDCA", "Radio_Vendor", col]].reset_index(
            drop=True).round(2)
        worst_tbls += f'<h3>📡 {tech} — Worst 20 Sites</h3>{_df_html(w, {col: _avail_td})}'

    body = (_krow(kpis) +
            _sec("📉 Worst Availability Sites", worst_tbls) +
            f'<div class="footer">TN Circle Availability Report — {month_label.upper()}</div>')
    return _html_head(f"Availability Report — {ssa_label}", ssa_label, month_label) + body + "</body></html>"


def gen_outage_html(outage_df, corr_df, tech_sum, sdca_tot, ssa_label, month_label):
    if outage_df is None or outage_df.empty:
        return _html_head(f"Outage — {ssa_label}", ssa_label, month_label) + "<p>No data.</p></body></html>"
    tot = outage_df["total_lost_rev"].sum()
    hi = int((outage_df.groupby("BTS IP ID")["outage_pct"].mean() > 5).sum())
    kpis = [_kpi_h(f"₹{tot / 100000:.3f}L", "Est. Total Lost Rev", "r"),
            _kpi_h(str(hi), "Sites >5% Outage", "r")]

    hi_df = outage_df[outage_df["outage_pct"] > 5].sort_values("total_lost_rev", ascending=False).head(30).copy()
    hi_df["Lost(L)"] = (hi_df["total_lost_rev"] / 100000).round(5)
    hi_cols = [c for c in ["BTS IP ID", "BTS Name", "SDCA", "Technology", "Radio_Vendor",
                           "avail_pct", "outage_pct", "lost_erl", "lost_gb", "Lost(L)"] if c in hi_df.columns]

    body = (_krow(kpis) +
            _sec("High-Impact Sites (>5% Outage)",
                 _df_html(hi_df[hi_cols].reset_index(drop=True).round(3), {"avail_pct": _avail_td})) +
            f'<div class="footer">TN Circle Outage Report — {month_label.upper()}</div>')
    return _html_head(f"Outage Impact — {ssa_label}", ssa_label, month_label) + body + "</body></html>"


def gen_site_master_html(master_df, ssa_label, month_label):
    if master_df is None or master_df.empty:
        return _html_head(f"Site Master — {ssa_label}", ssa_label, month_label) + "<p>No data.</p></body></html>"
    total = master_df["BTS IP ID"].nunique()
    tr = master_df["REV_LAKH"].sum() if "REV_LAKH" in master_df.columns else 0
    kpis = [_kpi_h(f"{total:,}", "Total Sites"),
            _kpi_h(f"₹{tr:.2f}L" if tr else "—", "Total Revenue", "g")]
    show = [c for c in ["BTS IP ID", "BTS Name", "SDCA", "Vendor_2G_RBC", "Vendor_3G_RBC", "Vendor_4G_RBC",
                        "Nw Avail (2G)", "Nw Avail (3G)", "Nw Avail (4G TCS)",
                        "REV_LAKH", "2g_rev", "3g_rev", "4g_rev", "2G_Cat", "3G_Cat", "4G_Cat"] if
            c in master_df.columns]
    tbl = _df_html(master_df[show].sort_values("REV_LAKH" if "REV_LAKH" in master_df.columns else show[0],
                                               ascending=False).reset_index(drop=True).round(3),
                   {"Nw Avail (2G)": _avail_td, "Nw Avail (3G)": _avail_td, "Nw Avail (4G TCS)": _avail_td,
                    "REV_LAKH": _rev_td})
    body = (_krow(kpis) + _sec("📋 All Sites", tbl) +
            f'<div class="footer">TN Circle Site Master List — {month_label.upper()}</div>')
    return _html_head(f"Site Master List — {ssa_label}", ssa_label, month_label) + body + "</body></html>"


def gen_incharge_html(incharge_scores, worst_sites, ssa_label, month_label):
    if incharge_scores is None or len(incharge_scores) == 0:
        return _html_head(f"Incharge Report — {ssa_label}", ssa_label, month_label) + "<p>No data.</p></body></html>"
    green = incharge_scores[incharge_scores["Score"] >= 70]
    amber = incharge_scores[(incharge_scores["Score"] >= 45) & (incharge_scores["Score"] < 70)]
    red = incharge_scores[incharge_scores["Score"] < 45]
    kpis = [
        _kpi_h(str(len(incharge_scores)), "Total Incharges"),
        _kpi_h(str(len(green)), "🟢 Good Contributors", "g"),
        _kpi_h(str(len(amber)), "🟡 Needs Attention", "a"),
        _kpi_h(str(len(red)), "🔴 Critical", "r"),
    ]
    tbl_cols = [c for c in ["incharge", "Sites", "Failures", "Total_Down_Hrs",
                            "Avg_Down_Hrs", "Top_Trouble", "Score", "Status", "Remedial"] if
                c in incharge_scores.columns]

    def _score_td(v):
        try:
            f = float(v)
            if f >= 70: return "ok"
            if f >= 45: return "warn"
            return "bad"
        except:
            return ""

    body = (_krow(kpis) +
            _sec("🟢 Good Contributors", _df_html(green[tbl_cols].reset_index(drop=True))) +
            _sec("🟡 Needs Attention", _df_html(amber[tbl_cols].reset_index(drop=True))) +
            _sec("🔴 Critical — Pulling Down", _df_html(red[tbl_cols].reset_index(drop=True), {"Score": _score_td})) +
            _sec("📍 Worst Sites (by downtime)", _df_html(worst_sites.head(30))) +
            f'<div class="footer">Incharge Performance Report — {ssa_label} — {month_label.upper()}</div>')
    return _html_head(f"Incharge Performance — {ssa_label}", ssa_label, month_label) + body + "</body></html>"


def gen_failure_html(fdf, ssa_label, period):
    if fdf is None or len(fdf) == 0:
        return _html_head(f"Failure Report — {ssa_label}", ssa_label, period) + "<p>No data.</p></body></html>"
    total_fail = len(fdf);
    sites = fdf["bts_ip_id"].nunique() if "bts_ip_id" in fdf.columns else "?"
    total_hrs = fdf["down_hours"].sum() if "down_hours" in fdf.columns else 0
    kpis = [
        _kpi_h(str(total_fail), "Total Failures", "r"),
        _kpi_h(str(sites), "Sites Affected", "a"),
        _kpi_h(f"{total_hrs:,.0f}", "Total Downtime (Hrs)", "r"),
        _kpi_h(f"{total_hrs / max(sites, 1):.1f}", "Avg Hrs/Site", "a"),
    ]
    tc_chart = ""
    if "trouble_category" in fdf.columns:
        tc = fdf["trouble_category"].value_counts().reset_index();
        tc.columns = ["Category", "Failures"]
        fig = px.bar(tc, x="Category", y="Failures", color="Category", text="Failures",
                     title="Failures by Root Cause")
        fig.update_traces(textposition="outside");
        fig.update_layout(showlegend=False, height=280)
        tc_chart = _fig_html(fig, 280)
    sdca_tbl = ""
    if "SDCA" in fdf.columns and "down_hours" in fdf.columns:
        sd = fdf.groupby("SDCA").agg(Failures=("bts_ip_id", "count"),
                                     Sites=("bts_ip_id", "nunique"), Total_Hrs=("down_hours", "sum"),
                                     Avg_Hrs=("down_hours", "mean")).round(2).sort_values("Total_Hrs",
                                                                                          ascending=False).reset_index()
        fig2 = px.bar(sd, x="SDCA", y="Total_Hrs", color="Total_Hrs",
                      color_continuous_scale="Reds", text="Total_Hrs", title="Downtime by SDCA")
        fig2.update_traces(texttemplate="%{text:.0f}h", textposition="outside")
        fig2.update_layout(coloraxis_showscale=False, height=280)
        sdca_tbl = _fig_html(fig2, 280) + _df_html(sd)
    worst_sites_tbl = ""
    if "bts_ip_id" in fdf.columns:
        ws = fdf.groupby(["bts_ip_id", "bts_name", "SDCA", "incharge", "vendor"]).agg(
            Failures=("down_hours", "count"), Total_Hrs=("down_hours", "sum"),
            Types=("trouble_category", lambda x: ", ".join(x.dropna().unique()))
        ).reset_index().sort_values("Total_Hrs", ascending=False).head(30).round(2)
        worst_sites_tbl = _df_html(ws)
    body = (_krow(kpis) +
            _sec("📊 Root Cause Analysis", f'<div class="two"><div>{tc_chart}</div></div>') +
            _sec("📍 SDCA-wise Downtime", sdca_tbl) +
            _sec("🔴 Worst 30 Sites", worst_sites_tbl) +
            f'<div class="footer">Failure Analysis Report — {ssa_label} — {period}</div>')
    return _html_head(f"Failure Analysis — {ssa_label}", ssa_label, period) + body + "</body></html>"


# Add these functions if missing
def standardize_perf(raw):
    df = raw.copy()
    if "BTS IP ID" in df.columns:
        df["BTS IP ID"] = df["BTS IP ID"].astype(str).str.strip()
    num_cols = ["Nw Avail (2G)", "Nw Avail (3G)", "Nw Avail (4G)", "Nw Avail (4G TCS)",
                "Erl (2g)", "Erl (3g)", "Erl (4g)", "Erl (2100)", "Erl (2500)", "Erl (700)",
                "Erl Total", "Data GB (2g)", "Data GB (3g)", "Data GB (4g)",
                "Data GB (2100)", "Data GB (2500)", "Data GB (700)", "Data GB Total",
                "2G cnt", "3G cnt", "4G cnt", "Latitude", "Longitude"]
    for c in num_cols:
        if c in df.columns: df[c] = pd.to_numeric(df[c], errors="coerce")
    if "MONTH" in df.columns and "YEAR" in df.columns:
        df["Month_Label"] = df.apply(lambda r: make_month_label(r["MONTH"], r["YEAR"]), axis=1)
    else:
        df["Month_Label"] = "unknown"
    if "SSAID" in df.columns:
        df["SSA_Code"] = df["SSAID"].map(SSAID_TO_CODE).fillna(df["SSAID"])
        df["SSA_Label"] = df["SSA_Code"].map(SSA_DISPLAY).fillna(df["SSA_Code"])

    # FIX: Create Has_4G_Physical safely
    has_4g = pd.Series(False, index=df.index)
    for bc in ["BTS Site ID (700)", "BTS Site ID (2100)", "BTS Site ID (2500)"]:
        if bc in df.columns:
            has_4g |= df[bc].notna()
    df["Has_4G_Physical"] = has_4g  # Always create this column even if False

    df["_has2g"] = pd.to_numeric(df.get("2G cnt", 0), errors="coerce").fillna(0) > 0
    df["_has3g"] = pd.to_numeric(df.get("3G cnt", 0), errors="coerce").fillna(0) > 0
    band_map = {"A": "700 only", "B": "700+2100", "C": "2100+2500", "D": "700+2100+2500", "Null": "No 4G"}
    if "Band category" in df.columns:
        df["Band_Cat_Label"] = df["Band category"].map(band_map).fillna(df["Band category"])
    if "Vendor" in df.columns:
        df["Radio_Vendor"] = df["Vendor"].apply(get_radio_vendor)
        df["Vendor_4G"] = df.apply(lambda r: get_4g_vendor_from_str(r["Vendor"], r["Has_4G_Physical"]), axis=1)
        df["Primary_Vendor"] = df["Radio_Vendor"]
    return df

def clean_rev_df(rdf_raw, m_lbl):
    rdf_raw = rdf_raw.copy()
    for c in REV_NUM_COLS:
        if c in rdf_raw.columns: rdf_raw[c] = pd.to_numeric(rdf_raw[c], errors="coerce")
    rdf_raw["BTSIPID"] = rdf_raw["BTSIPID"].astype(str).str.strip()
    rdf_raw = rdf_raw[~rdf_raw["BTSIPID"].isin(["0", "nan", "", "NaN", "None"])].copy()

    if "SDCANAME" in rdf_raw.columns:
        rdf_raw["SDCA"] = rdf_raw["SDCANAME"].str.strip().str.title()
    if "SDCA" not in rdf_raw.columns: rdf_raw["SDCA"] = "Unknown"
    rdf_raw["SDCA"] = rdf_raw["SDCA"].fillna("Unknown")
    rdf_raw["Rev_Month"] = m_lbl
    return rdf_raw.groupby("BTSIPID", sort=False).first().reset_index()

# ═══════════════════════════════════════════════════════════════════════════════
# SESSION STATE
# ═══════════════════════════════════════════════════════════════════════════════
for k, v in [("master_df", None), ("rev_store_full", {}), ("ref_df", None),
             ("failure_df", None), ("gainers_df", None), ("losers_df", None),
             ("sdca_df", None), ("locked_df", None)]:  # <--- Added these two
    if k not in st.session_state:
        st.session_state[k] = v
# ═══════════════════════════════════════════════════════════════════════════════
# SIDEBAR
# ═══════════════════════════════════════════════════════════════════════════════
with st.sidebar:
    st.markdown("## 📡 TN Circle Dashboard")
    st.caption("Upload files below to populate all tabs.")
    with st.expander("① Reference File (optional — Incharge data)"):
        ref_up = st.file_uploader("BTSIPID_PKEY1 file", type=["xlsx"], key="ref_up")
        if ref_up:
            try:
                xf = pd.ExcelFile(ref_up)
                rdf = pd.read_excel(ref_up, sheet_name=xf.sheet_names[0])
                keep = [c for c in ["BTSIPID", "SDCA", "SDCANAME", "SITENAME", "LOCATION",
                                    "incharge", "JTO INCHARGE"] if c in rdf.columns]
                rdf = rdf[keep].copy()
                rdf["BTSIPID"] = rdf["BTSIPID"].astype(str).str.strip()
                st.session_state.ref_df = rdf
                st.success(f"✅ {len(rdf)} sites loaded")
            except Exception as e:
                st.error(f"Error: {e}")

    st.markdown("**② Monthly Performance Files** (CSV/XLSX/XLS)")
    perf_ups = st.file_uploader("Perf files", type=["csv", "xlsx", "xls"],
                                accept_multiple_files=True, key="perf_up")
    if perf_ups:
        dfs = []
        for f in perf_ups:
            try:
                dfs.append(standardize_perf(_tolerant_read_file(f)))
            except Exception as e:
                st.error(f"{f.name}: {e}")
        if dfs:
            st.session_state.master_df = pd.concat(dfs, ignore_index=True)
            months = sorted(st.session_state.master_df["Month_Label"].unique(), key=month_sort_key)
            st.success(f"✅ {len(dfs)} file(s) · {len(st.session_state.master_df):,} rows")
            st.caption(f"Months: {', '.join(m.upper() for m in months)}")

    st.markdown("**③ Revenue Files (RBC — one per month)**")
    rev_ups = st.file_uploader("RBC files", type=["xlsx", "csv"],
                               accept_multiple_files=True, key="rev_up")
    if rev_ups:
        for rf in rev_ups:
            try:
                parts = rf.name.upper().replace("-", "_").replace(" ", "_")
                parts = parts.replace(".XLSX", "").replace(".XLS", "").replace(".CSV", "").split("_")
                abbrs = {"JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"}
                m_lbl = None
                for i, p in enumerate(parts):
                    if p in abbrs:
                        yr_part = [x for x in parts[i + 1:] if x.isdigit() and len(x) == 4]
                        yr = yr_part[0][-2:] if yr_part else "??"
                        m_lbl = f"{p.lower()}{yr}";
                        break
                if m_lbl is None:
                    m_lbl = rf.name.lower().replace(".xlsx", "").replace(".csv", "").replace(" ", "_")
                xf = pd.ExcelFile(rf)
                sheet = "RBC DATA" if "RBC DATA" in xf.sheet_names else xf.sheet_names[0]
                rdf_raw = pd.read_excel(rf, sheet_name=sheet)
                rdf_clean = clean_rev_df(rdf_raw, m_lbl)
                st.session_state.rev_store_full[m_lbl] = rdf_clean
                n_ssas = rdf_clean["SSACODE"].nunique() if "SSACODE" in rdf_clean.columns else "?"
                st.success(f"✅ {m_lbl.upper()}: {len(rdf_clean):,} sites · {n_ssas} SSAs")
            except Exception as e:
                st.error(f"{rf.name}: {e}")

    st.markdown("---")
    st.markdown("**④ Gainers / Losers CSV** (from Tech Shift tab export)")
    gl_up1 = st.file_uploader("Gainers CSV", type=["csv"], key="gl_gain")
    gl_up2 = st.file_uploader("Losers CSV", type=["csv"], key="gl_loss")
    if gl_up1:
        try:
            st.session_state["gainers_df"] = pd.read_csv(gl_up1)
            st.success(f"✅ Gainers: {len(st.session_state['gainers_df'])} sites")
        except Exception as e:
            st.error(str(e))
    if gl_up2:
        try:
            st.session_state["losers_df"] = pd.read_csv(gl_up2)
            st.success(f"✅ Losers: {len(st.session_state['losers_df'])} sites")
        except Exception as e:
            st.error(str(e))
    with st.expander("④ SDCA Mapping File"):
        sdca_up = st.file_uploader("SDCA file", type=["xlsx","csv"], key="sdca_up")
        if sdca_up:
            try:
                sdf = pd.read_excel(sdca_up) if sdca_up.name.endswith(".xlsx") else pd.read_csv(sdca_up)
                # Normalize columns
                col_map = {c.lower().replace(" ",""):c for c in sdf.columns}
                for k in ["btsipid","sdca","type"]:
                    if k in col_map: sdf.rename(columns={col_map[k]:k.upper()}, inplace=True)
                sdf["BTSIPID"] = sdf["BTSIPID"].astype(str).str.strip()
                st.session_state.sdca_df = sdf
                st.success(f"✅ {len(sdf)} sites mapped")
            except Exception as e: st.error(str(e))

    with st.expander("⑤ Locked Sites File"):
        lock_up = st.file_uploader("Locked sites", type=["xlsx","csv"], key="lock_up")
        if lock_up:
            try:
                ldf = pd.read_excel(lock_up) if lock_up.name.endswith(".xlsx") else pd.read_csv(lock_up)
                col_map = {c.lower().replace(" ",""):c for c in ldf.columns}
                for k in ["btsname","btssiteid"]:
                    if k in col_map: ldf.rename(columns={col_map[k]:k.upper()}, inplace=True)
                st.session_state.locked_df = ldf
                st.success(f"✅ {len(ldf)} locked sites")
            except Exception as e: st.error(str(e))

# AI Report uses Auto-Analytics only (no API key required)
if st.session_state.master_df is not None:
    mdf = st.session_state.master_df
    all_months = sorted(mdf["Month_Label"].unique(), key=month_sort_key)
    sel_months = st.multiselect("Months (trend tabs)", all_months, default=all_months, key="sel_months")
    perf_codes = set()
    if "SSAID" in mdf.columns:
        for s in mdf["SSAID"].dropna().unique():
            c = SSAID_TO_CODE.get(str(s).strip())
            if c: perf_codes.add(c)
    rev_codes = set()
    for rdf in st.session_state.rev_store_full.values():
        if "SSACODE" in rdf.columns:
            rev_codes.update(rdf["SSACODE"].dropna().astype(str).str.strip().unique())
    all_codes = sorted((perf_codes | rev_codes) or {"KKD"},
                       key=lambda c: SSA_DISPLAY.get(c, c))


    def _oa_lbl(c):
        return f"{SSA_DISPLAY.get(c, c)}  ({c})"


    default_code = "KKD" if "KKD" in all_codes else all_codes[0]
    sel_ssa_code = st.selectbox("🔍 Active SSA (all tabs)", all_codes,
                                index=all_codes.index(default_code),
                                format_func=_oa_lbl, key="sel_ssa")
    sel_ssaid = CODE_TO_SSAID.get(sel_ssa_code, sel_ssa_code)
else:
    sel_months = [];
    sel_ssa_code = "KKD";
    sel_ssaid = "TNKAR"

# ── Gate ─────────────────────────────────────────────────────────────────────
if st.session_state.master_df is None:
    st.markdown("""
    <div style='text-align:center;padding:60px'>
    <h1>📡 TN Circle Network Intelligence Dashboard v4</h1>
    <p style='font-size:1.15em;color:#555'>Upload files from the sidebar to get started</p>
    <br/><p>① Reference (optional) &nbsp;·&nbsp; ② Performance CSV/XLSX/XLS &nbsp;·&nbsp; ③ RBC Revenue XLSX</p>
    </div>""", unsafe_allow_html=True)
    st.stop()

# ═══════════════════════════════════════════════════════════════════════════════
# GLOBAL DATA PREP
# ═══════════════════════════════════════════════════════════════════════════════
mdf = st.session_state.master_df.copy()
rev_store_full = st.session_state.rev_store_full
ref_df = st.session_state.ref_df
if sel_months:
    mdf = mdf[mdf["Month_Label"].isin(sel_months)]
if "SSAID" in mdf.columns and mdf["SSAID"].nunique() > 1:
    mdf = mdf[mdf["SSAID"].astype(str).str.strip() == sel_ssaid].copy()
months_sorted = sorted(mdf["Month_Label"].unique(), key=month_sort_key)
latest_month = months_sorted[-1] if months_sorted else "unknown"
prev_month = months_sorted[-2] if len(months_sorted) >= 2 else None
df_lat = mdf[mdf["Month_Label"] == latest_month].copy()
df_prev = mdf[mdf["Month_Label"] == prev_month].copy() if prev_month else pd.DataFrame()

# Revenue store for selected SSA
rev_store = {}
if rev_store_full:
    for m, rdf in rev_store_full.items():
        f = rdf[rdf["SSACODE"].astype(str).str.strip() == sel_ssa_code].copy() \
            if "SSACODE" in rdf.columns else rdf.copy()
        if len(f): rev_store[m] = f
has_revenue = bool(rev_store)
rev_months_sorted = sorted(rev_store.keys(), key=month_sort_key) if has_revenue else []
latest_rev_month = rev_months_sorted[-1] if has_revenue else None
prev_rev_month = rev_months_sorted[-2] if len(rev_months_sorted) >= 2 else None
rev_lat = rev_store[latest_rev_month].copy() if has_revenue else None
rev_prev = rev_store[prev_rev_month].copy() if prev_rev_month else None

# SDCA from revenue
if has_revenue:
    _sdca_src = rev_store[rev_months_sorted[-1]]
    if "SDCANAME" in _sdca_src.columns and "BTSIPID" in _sdca_src.columns:
        _lkp = (_sdca_src[["BTSIPID", "SDCANAME"]].dropna().drop_duplicates("BTSIPID")
                .set_index("BTSIPID")["SDCANAME"]
                .str.strip().str.title()
                .str.replace("Tirupathur", "Tirupattur", regex=False))
        for _df in [mdf, df_lat, df_prev]:
            if len(_df):
                _df["SDCA"] = _df["BTS IP ID"].map(_lkp).fillna("Unknown")
else:
    for _df in [mdf, df_lat, df_prev]:
        if len(_df) and "SDCA" not in _df.columns:
            _df["SDCA"] = "Unknown"

# Incharge enrichment
has_incharge = has_jto = False
if ref_df is not None:
    has_incharge = "incharge" in ref_df.columns
    has_jto = "JTO INCHARGE" in ref_df.columns
    rc = [c for c in ["BTSIPID", "incharge", "JTO INCHARGE"] if c in ref_df.columns]
    if len(rc) > 1:
        for _df in [df_lat, mdf]:
            if len(_df):
                _df.update(_df.merge(ref_df[rc], left_on="BTS IP ID",
                                     right_on="BTSIPID", how="left",
                                     suffixes=("", "_ref")).drop(columns=["BTSIPID"], errors="ignore"))

avail_existing = {k: v for k, v in AVAIL_COLS.items() if v in df_lat.columns}

# ── REV JOIN COLS ─────────────────────────────────────────────────────────────
REV_JOIN_COLS = [c for c in ["BTSIPID", "REV_LAKH", "TOT_REV", "TRAFFIC_REV", "DATA_REV",
                             "2G_Traffic", "2G_Data", "3G_Traffic", "3G_Data", "4G_Traffic", "4G_Data",
                             "TOT_TRAFFIC", "TOT_DATA", "2g_rev", "3g_rev", "4g_rev",
                             "Perday_2G_Erl", "Perday_3G_GB", "Perday_4G_GB",
                             "2G_Cat", "3G_Cat", "4G_Cat", "2G TECH", "3G TECH", "4G TECH",
                             "Vendor_2G_RBC", "Vendor_3G_RBC", "Vendor_4G_RBC", "SDCA"]
                 if c in (rev_lat.columns if rev_lat is not None else [])]
df_lat_rev = None
if has_revenue and len(REV_JOIN_COLS) > 1:
    df_lat_rev = df_lat.merge(rev_lat[REV_JOIN_COLS], left_on="BTS IP ID",
                              right_on="BTSIPID", how="left",
                              suffixes=("", "_rbc")).copy()

# ── UNMATCHED SITES ───────────────────────────────────────────────────────────
unmatched_sites = pd.DataFrame()
if has_revenue:
    rev_ids = set(rev_lat["BTSIPID"].dropna().astype(str))
    unmatched_mask = ~df_lat["BTS IP ID"].isin(rev_ids)
    if unmatched_mask.any():
        um_cols = [c for c in ["BTS IP ID", "BTS Name", "SDCA", "Vendor",
                               "Nw Avail (2G)", "Nw Avail (3G)", "Nw Avail (4G TCS)",
                               "Erl Total", "Data GB Total"] if c in df_lat.columns]
        unmatched_sites = df_lat[unmatched_mask][um_cols].copy()
        unmatched_sites["Issue"] = "No Revenue Match"

# ── VENDOR MATRIX (2G/3G from Radio_Vendor; 4G from Vendor_4G) ───────────────
# ── VENDOR MATRIX (2G/3G from Radio_Vendor; 4G from Vendor_4G) ───────────────
ven_matrix = pd.DataFrame()
if "Radio_Vendor" in df_lat.columns:
    # Ensure boolean columns exist
    if "_has2g" not in df_lat.columns:
        df_lat["_has2g"] = pd.to_numeric(df_lat.get("2G cnt", 0), errors="coerce").fillna(0) > 0
    if "_has3g" not in df_lat.columns:
        df_lat["_has3g"] = pd.to_numeric(df_lat.get("3G cnt", 0), errors="coerce").fillna(0) > 0
    if "Has_4G_Physical" not in df_lat.columns:
        df_lat["Has_4G_Physical"] = False  # Default if not present

    if "Vendor" in mdf.columns:
        mdf["Radio_Vendor"] = mdf["Vendor"].apply(get_radio_vendor)
        mdf["Primary_Vendor"] = mdf["Radio_Vendor"]
        mdf["Vendor_4G"] = mdf.apply(lambda r: get_4g_vendor_from_str(r.get("Vendor", ""),
                                                                      r.get("Has_4G_Physical", False)), axis=1)
    df_lat["Vendor_3G_str"] = df_lat.apply(
        lambda r: get_3g_vendor_from_str(r.get("Vendor", ""), r.get("_has3g", False)), axis=1)
    if "Vendor" in mdf.columns:
        mdf["Vendor_3G_str"] = mdf.apply(
            lambda r: get_3g_vendor_from_str(r.get("Vendor", ""), r.get("_has3g", False)), axis=1)

    _v2 = df_lat[df_lat["_has2g"]].groupby("Radio_Vendor")["BTS IP ID"].nunique().rename("Sites_2G")
    _v3 = df_lat[df_lat["_has3g"]].groupby("Vendor_3G_str")["BTS IP ID"].nunique().rename("Sites_3G")
    _v4 = df_lat[df_lat["Has_4G_Physical"]].groupby("Vendor_4G")["BTS IP ID"].nunique().rename("Sites_4G_Total")
    _s700 = int(df_lat["BTS Site ID (700)"].notna().sum()) if "BTS Site ID (700)" in df_lat.columns else 0
    _s2100 = int(df_lat["BTS Site ID (2100)"].notna().sum()) if "BTS Site ID (2100)" in df_lat.columns else 0
    _s2500 = int(df_lat["BTS Site ID (2500)"].notna().sum()) if "BTS Site ID (2500)" in df_lat.columns else 0
    all_vens = sorted(set(_v2.index) | set(_v3.index) | set(_v4.index) - {"—", "Unknown"})
    ven_matrix = pd.DataFrame({"Vendor": all_vens})
    ven_matrix["Sites_2G"] = ven_matrix["Vendor"].map(_v2).fillna(0).astype(int)
    ven_matrix["Sites_3G"] = ven_matrix["Vendor"].map(_v3).fillna(0).astype(int)
    _v4_df = _v4.reset_index();
    _v4_df.columns = ["Vendor", "Sites_4G_Total"]
    ven_matrix = ven_matrix.merge(_v4_df, on="Vendor", how="outer").fillna(0)
    ven_matrix["Sites_4G_Total"] = ven_matrix["Sites_4G_Total"].astype(int)
    ven_matrix["Sites_4G_700"] = ven_matrix["Vendor"].apply(lambda v: _s700 if "TCS" in str(v) else 0)
    ven_matrix["Sites_4G_2100"] = ven_matrix["Vendor"].apply(lambda v: _s2100 if "TCS" in str(v) else 0)
    ven_matrix["Sites_4G_2500"] = ven_matrix["Vendor"].apply(lambda v: _s2500 if "TCS" in str(v) else 0)
    ven_matrix["Sites_2G"] = ven_matrix["Sites_2G"].astype(int)
    ven_matrix["Sites_3G"] = ven_matrix["Sites_3G"].astype(int)
    ven_matrix["Total_Sites"] = ven_matrix[["Sites_2G", "Sites_3G", "Sites_4G_Total"]].max(axis=1)
    for ac_name, ac_col in avail_existing.items():
        ven_matrix = ven_matrix.merge(
            df_lat.groupby("Radio_Vendor")[ac_col].mean().round(2)
            .rename(f"Avg {ac_name} %").reset_index()
            .rename(columns={"Radio_Vendor": "Vendor"}),
            on="Vendor", how="left")
    if has_revenue:
        _jv = df_lat.merge(rev_lat[["BTSIPID", "REV_LAKH"]],
                           left_on="BTS IP ID", right_on="BTSIPID", how="left")
        ven_matrix = ven_matrix.merge(
            _jv.groupby("Radio_Vendor")["REV_LAKH"].agg(
                Rev_Total="sum", Rev_Avg="mean").round(3).reset_index()
            .rename(columns={"Radio_Vendor": "Vendor"}),
            on="Vendor", how="left")
    ven_matrix = ven_matrix[ven_matrix["Vendor"].notna() &
                            (~ven_matrix["Vendor"].isin(["Unknown", "—"]))].sort_values("Total_Sites", ascending=False)
# --- SDCA Enrichment ---
sdca_df = st.session_state.get("sdca_df")
if sdca_df is not None and "BTSIPID" in sdca_df.columns:
    sdca_lkp = sdca_df.set_index("BTSIPID")[["SDCA", "TYPE"]].to_dict()
    for _df in [mdf, df_lat, df_prev]:
        if len(_df):
            _df["SDCA_Mapped"] = _df["BTS IP ID"].map(sdca_lkp.get("SDCA"))
            _df["TYPE"] = _df["BTS IP ID"].map(sdca_lkp.get("TYPE"))
            # Only overwrite if current SDCA is Unknown
            _df["SDCA"] = _df["SDCA_Mapped"].fillna(_df.get("SDCA", "Unknown"))

# --- Locked Sites Marking ---
locked_df = st.session_state.get("locked_df")
if locked_df is not None:
    locked_ids = set()
    if "BTSNAME" in locked_df.columns:
        locked_ids.update(locked_df["BTSNAME"].dropna().astype(str).str.strip())
    if "BTSSITEID" in locked_df.columns:
        locked_ids.update(locked_df["BTSSITEID"].dropna().astype(str).str.strip())

    for _df in [mdf, df_lat, df_prev]:
        if len(_df):
            _df["Is_Locked"] = _df["BTS IP ID"].isin(locked_ids) | _df["BTS Name"].isin(locked_ids)
else:
    for _df in [mdf, df_lat, df_prev]:
        if len(_df): _df["Is_Locked"] = False

# ── SDCA SUMMARY ──────────────────────────────────────────────────────────────
# ─ SDCA SUMMARY (ENHANCED) ──────────────────────────────────────────────────
sdca_sum = pd.DataFrame()
if "SDCA" in df_lat.columns:
    # Base: total sites per SDCA
    sdca_sum = df_lat.groupby("SDCA")["BTS IP ID"].nunique().reset_index()
    sdca_sum.columns = ["SDCA", "Total Sites"]

    # Technology-wise site counts
    if "_has2g" in df_lat.columns:
        s2g = df_lat[df_lat["_has2g"]].groupby("SDCA")["BTS IP ID"].nunique()
        sdca_sum = sdca_sum.merge(s2g.reset_index().rename(columns={"BTS IP ID": "2G Sites"}), on="SDCA", how="left")
    else:
        sdca_sum["2G Sites"] = 0
    if "_has3g" in df_lat.columns:
        s3g = df_lat[df_lat["_has3g"]].groupby("SDCA")["BTS IP ID"].nunique()
        sdca_sum = sdca_sum.merge(s3g.reset_index().rename(columns={"BTS IP ID": "3G Sites"}), on="SDCA", how="left")
    else:
        sdca_sum["3G Sites"] = 0
    if "Has_4G_Physical" in df_lat.columns:
        s4g = df_lat[df_lat["Has_4G_Physical"]].groupby("SDCA")["BTS IP ID"].nunique()
        sdca_sum = sdca_sum.merge(s4g.reset_index().rename(columns={"BTS IP ID": "4G Sites"}), on="SDCA", how="left")
    else:
        sdca_sum["4G Sites"] = 0

    # Fill NaN with 0 for site counts
    for c in ["2G Sites", "3G Sites", "4G Sites"]:
        if c in sdca_sum.columns:
            sdca_sum[c] = sdca_sum[c].fillna(0).astype(int)

    # Availability per technology
    for ac_name, ac_col in avail_existing.items():
        sdca_sum = sdca_sum.merge(
            df_lat.groupby("SDCA")[ac_col].mean().round(2).rename(f"Avg {ac_name} %").reset_index(),
            on="SDCA", how="left")

    # Revenue
    if has_revenue and "SDCA" in rev_lat.columns:
        rev_sdca = rev_lat.groupby("SDCA")["REV_LAKH"].agg(
            Rev_Total="sum",
            Zero_Sites=lambda x: (x == 0).sum(),
            Sites_with_Rev=lambda x: (x > 0).sum()
        ).round(3).reset_index()
        sdca_sum = sdca_sum.merge(rev_sdca, on="SDCA", how="left")
        # Per-site revenue
        sdca_sum["Avg Rev/Site (L)"] = (sdca_sum["Rev_Total"] / sdca_sum["Total Sites"]).round(3)

    sdca_sum = sdca_sum.sort_values("Total Sites", ascending=False).reset_index(drop=True)


# ── SDCA VENDOR BREAKDOWN ────────────────────────────────────────────────────
sdca_vendor = pd.DataFrame()
if "SDCA" in df_lat.columns and "Radio_Vendor" in df_lat.columns:
    # 2G vendor per SDCA
    if "_has2g" in df_lat.columns:
        v2g = df_lat[df_lat["_has2g"]].groupby(["SDCA", "Radio_Vendor"])["BTS IP ID"].nunique().reset_index()
        v2g.columns = ["SDCA", "Vendor", "2G Sites"]
        sdca_vendor = v2g.copy()

    # 3G vendor per SDCA
    if "_has3g" in df_lat.columns and "Vendor_3G_str" in df_lat.columns:
        v3g = df_lat[df_lat["_has3g"]].groupby(["SDCA", "Vendor_3G_str"])["BTS IP ID"].nunique().reset_index()
        v3g.columns = ["SDCA", "Vendor", "3G Sites"]
        if len(sdca_vendor):
            sdca_vendor = sdca_vendor.merge(v3g, on=["SDCA", "Vendor"], how="outer")
        else:
            sdca_vendor = v3g.copy()

    # 4G vendor per SDCA
    if "Has_4G_Physical" in df_lat.columns and "Vendor_4G" in df_lat.columns:
        v4g = df_lat[df_lat["Has_4G_Physical"]].groupby(["SDCA", "Vendor_4G"])["BTS IP ID"].nunique().reset_index()
        v4g.columns = ["SDCA", "Vendor", "4G Sites"]
        if len(sdca_vendor):
            sdca_vendor = sdca_vendor.merge(v4g, on=["SDCA", "Vendor"], how="outer")
        else:
            sdca_vendor = v4g.copy()

    sdca_vendor = sdca_vendor.fillna(0)
    for c in ["2G Sites", "3G Sites", "4G Sites"]:
        if c in sdca_vendor.columns:
            sdca_vendor[c] = sdca_vendor[c].astype(int)

# ── MASTER SITE TABLE (perf + revenue joined) ─────────────────────────────────
master_site_df = pd.DataFrame()
if has_revenue:
    join_cols = [c for c in ["BTSIPID", "SDCA", "REV_LAKH", "2g_rev", "3g_rev", "4g_rev",
                             "2G_Cat", "3G_Cat", "4G_Cat", "Vendor_2G_RBC", "Vendor_3G_RBC",
                             "Vendor_4G_RBC", "2G TECH", "3G TECH", "4G TECH"] if c in rev_lat.columns]
    master_site_df = df_lat.merge(rev_lat[join_cols], left_on="BTS IP ID",
                                  right_on="BTSIPID", how="left",
                                  suffixes=("", "_rbc"))
    if "SDCA_rbc" in master_site_df.columns:
        master_site_df["SDCA"] = master_site_df["SDCA"].fillna(master_site_df["SDCA_rbc"])
        master_site_df = master_site_df.drop(columns=["SDCA_rbc"], errors="ignore")
else:
    master_site_df = df_lat.copy()

# ── DISPLAY BANNER ────────────────────────────────────────────────────────────
_ssa_name = SSA_DISPLAY.get(sel_ssa_code, sel_ssa_code)
_rev_cnt = rev_lat["BTSIPID"].nunique() if has_revenue else 0
_perf_cnt = df_lat["BTS IP ID"].nunique()
st.info(
    f"🔍 **Active SSA: {_ssa_name} ({sel_ssa_code})**  |  "
    f"Perf: **{_perf_cnt:,}** sites  |  Revenue: **{_rev_cnt:,}** sites  |  "
    f"Latest Perf: **{latest_month.upper()}**" +
    (f"  |  Latest Revenue: **{latest_rev_month.upper()}**" if has_revenue else "  |  No revenue loaded") +
    (f"  |  Unmatched: **{len(unmatched_sites)}** sites ⚠️" if len(unmatched_sites) else "")
)

# ═══════════════════════════════════════════════════════════════════════════════
# TABS
# ═══════════════════════════════════════════════════════════════════════════════
TAB_LABELS = [
    "🏠 Executive",         # 0
    "💰 Revenue",           # 1
    "📋 Site Master",       # 2
    "🎯 Action Items",      # 3
    "📈 Trends",            # 4
    "📊 Traffic Analysis",  # 5 (NEW)
    "🌐 Circle & SDCA",     # 6 (was 5)
    "📉 Network Analysis",  # 7 (was 6)
    "🔧 Operations",        # 8 (was 7)
    "💸 Revenue Impact",    # 9 (was 8)
    "📊 Reports",           # 10 (was 9)
]
tabs = st.tabs(TAB_LABELS)

# ══════════════════════════════════════════════════════════════════════════════
# TAB 0 – EXECUTIVE SUMMARY
# ══════════════════════════════════════════════════════════════════════════════
with tabs[0]:
    st.header(f"🏠 Executive Summary — {_ssa_name} ({sel_ssa_code}) · {latest_month.upper()}")
    total_sites = df_lat["BTS IP ID"].nunique()
    s2g = int(df_lat["_has2g"].sum()) if "_has2g" in df_lat.columns else 0
    s3g = int(df_lat["_has3g"].sum()) if "_has3g" in df_lat.columns else 0
    s4g = int(df_lat["Has_4G_Physical"].sum())
    s700 = int(df_lat["BTS Site ID (700)"].notna().sum()) if "BTS Site ID (700)" in df_lat.columns else 0
    s2100 = int(df_lat["BTS Site ID (2100)"].notna().sum()) if "BTS Site ID (2100)" in df_lat.columns else 0
    s2500 = int(df_lat["BTS Site ID (2500)"].notna().sum()) if "BTS Site ID (2500)" in df_lat.columns else 0
    avg2g = df_lat["Nw Avail (2G)"].mean() if "Nw Avail (2G)" in df_lat.columns else np.nan
    avg3g = df_lat["Nw Avail (3G)"].mean() if "Nw Avail (3G)" in df_lat.columns else np.nan
    avg4g = df_lat[df_lat["Has_4G_Physical"]]["Nw Avail (4G TCS)"].mean() \
        if "Nw Avail (4G TCS)" in df_lat.columns else np.nan
    tot_rev = rev_lat["REV_LAKH"].sum() if has_revenue else np.nan
    zero_rev_n = int((rev_lat["REV_LAKH"] == 0).sum()) if has_revenue else 0

    c1, c2, c3, c4, c5, c6, c7, c8 = st.columns(8)
    c1.metric("Total Sites", f"{total_sites:,}")
    c2.metric("2G Sites", f"{s2g:,}")
    c3.metric("3G Sites", f"{s3g:,}")
    c4.metric("4G Physical", f"{s4g:,}")
    c5.metric("Avg 2G %", f"{avg2g:.2f}%" if not np.isnan(avg2g) else "N/A")
    c6.metric("Avg 3G %", f"{avg3g:.2f}%" if not np.isnan(avg3g) else "N/A")
    c7.metric("Avg 4G %", f"{avg4g:.2f}%" if not np.isnan(avg4g) else "N/A")
    c8.metric("Total Rev (L)", f"₹{tot_rev:.2f}" if not np.isnan(tot_rev) else "—")
    st.markdown("---")

    col_g, col_v = st.columns(2)
    with col_g:
        fig_gauge = go.Figure()
        colors = ["#636EFA", "#EF553B", "#00CC96"]
        avail_list = [(t, c) for t, c in avail_existing.items() if c in df_lat.columns]
        for i, (tech, col) in enumerate(avail_list):
            avg = df_lat[col].mean()
            fig_gauge.add_trace(go.Indicator(
                mode="gauge+number", value=round(avg, 2),
                title={"text": tech, "font": {"size": 13}},
                gauge={"axis": {"range": [80, 100]}, "bar": {"color": colors[i % 3]},
                       "steps": [{"range": [80, 90], "color": "#ffcccc"},
                                 {"range": [90, 95], "color": "#fff3cd"},
                                 {"range": [95, 100], "color": "#d4edda"}],
                       "threshold": {"line": {"color": "red", "width": 2}, "thickness": 0.75, "value": 95}},
                domain={"x": [i / len(avail_list), (i + 1) / len(avail_list)], "y": [0, 1]}))
        fig_gauge.update_layout(height=240, margin=dict(t=40, b=10, l=10, r=10))
        st.plotly_chart(fig_gauge, use_container_width=True)

    with col_v:
        if "Radio_Vendor" in df_lat.columns:
            v2g_c = df_lat[df_lat["_has2g"]].groupby("Radio_Vendor")["BTS IP ID"].nunique().reset_index()
            v2g_c.columns = ["Vendor", "Count"];
            v2g_c["Technology"] = "2G"
            v3g_c = \
            df_lat[df_lat["_has3g"]].groupby("Vendor_3G_str" if "Vendor_3G_str" in df_lat.columns else "Radio_Vendor")[
                "BTS IP ID"].nunique().reset_index()
            v3g_c.columns = ["Vendor", "Count"];
            v3g_c["Technology"] = "3G"
            v4g_c = df_lat[df_lat["Has_4G_Physical"]].groupby("Vendor_4G")["BTS IP ID"].nunique().reset_index()
            v4g_c.columns = ["Vendor", "Count"];
            v4g_c["Technology"] = "4G"
            vt_all = pd.concat([v2g_c, v3g_c, v4g_c]).query("Vendor not in ['—','Unknown']")
            _tech_order = ["2G", "3G", "4G"]
            vt_all["Technology"] = pd.Categorical(vt_all["Technology"], categories=_tech_order, ordered=True)
            vt_all = vt_all.sort_values("Technology")
            fig_vt = px.bar(vt_all, x="Technology", y="Count", color="Vendor",
                            text="Count", barmode="stack",
                            title="Site Count by Technology & Vendor",
                            category_orders={"Technology": _tech_order},
                            color_discrete_map=VEND_COLORS)
            _tot = vt_all.groupby("Technology")["Count"].sum().reindex(_tech_order).fillna(0)
            fig_vt.add_trace(go.Scatter(x=_tot.index.tolist(), y=_tot.values.tolist(),
                                        mode="text", text=[str(int(v)) for v in _tot.values],
                                        textposition="top center",
                                        textfont=dict(size=13, color="black", family="Arial Black"),
                                        showlegend=False, name="Total"))
            fig_vt.update_traces(textposition="inside", selector=dict(type="bar"))
            fig_vt.update_layout(height=240, margin=dict(t=40, b=10), legend_title="Vendor")
            st.plotly_chart(fig_vt, use_container_width=True)
        else:
            tech_bar = {"Category": ["2G", "3G", "4G", "700MHz", "2100MHz", "2500MHz"],
                        "Count": [s2g, s3g, s4g, s700, s2100, s2500],
                        "Group": ["Technology"] * 3 + ["4G Band"] * 3}
            fig_tb = px.bar(pd.DataFrame(tech_bar), x="Category", y="Count", color="Group",
                            text="Count", barmode="group", title="Site Count by Technology & Band")
            fig_tb.update_traces(textposition="outside")
            st.plotly_chart(fig_tb, use_container_width=True)

    st.markdown("---")
    col_h, col_r = st.columns(2)
    with col_h:
        st.subheader("🗺️ SDCA × Technology Availability")
        if "SDCA" in df_lat.columns and avail_existing:
            ac = [c for c in avail_existing.values() if c in df_lat.columns]
            av = df_lat.groupby("SDCA")[ac].mean().round(2).reset_index()
            short = [c.replace("Nw Avail (", "").replace(")", "") for c in ac]
            av.columns = ["SDCA"] + short
            fig_hm = go.Figure(go.Heatmap(
                z=av[short].values, x=short, y=av["SDCA"].tolist(),
                colorscale="RdYlGn", zmin=85, zmax=100,
                text=[[f"{v:.1f}%" if not np.isnan(v) else "—" for v in row] for row in av[short].values],
                texttemplate="%{text}", textfont={"size": 12}))
            fig_hm.update_layout(height=340, margin=dict(t=30, b=10))
            st.plotly_chart(fig_hm, use_container_width=True)

    with col_r:
        st.subheader("💰 Revenue Health")
        if has_revenue:
            rev_health = [{"Segment": "VHT (Top)",
                           "Sites": int((rev_lat["REV_LAKH"] >= rev_lat["REV_LAKH"].quantile(0.9)).sum())},
                          {"Segment": "HT", "Sites": int(((rev_lat["REV_LAKH"] >= rev_lat["REV_LAKH"].quantile(
                              0.75)) & (rev_lat["REV_LAKH"] < rev_lat["REV_LAKH"].quantile(0.9))).sum())},
                          {"Segment": "MT", "Sites": int(((rev_lat["REV_LAKH"] >= rev_lat["REV_LAKH"].quantile(0.5)) & (
                                      rev_lat["REV_LAKH"] < rev_lat["REV_LAKH"].quantile(0.75))).sum())},
                          {"Segment": "LT", "Sites": int(((rev_lat["REV_LAKH"] > 0) & (
                                      rev_lat["REV_LAKH"] < rev_lat["REV_LAKH"].quantile(0.5))).sum())},
                          {"Segment": "Zero", "Sites": zero_rev_n}]
            fig_rh = px.bar(pd.DataFrame(rev_health), x="Segment", y="Sites", color="Segment", text="Sites",
                            title="Revenue Segment Distribution",
                            color_discrete_map={"VHT (Top)": "#1a9641", "HT": "#a6d96a", "MT": "#ffffbf",
                                                "LT": "#fdae61", "Zero": "#d7191c"})
            fig_rh.update_traces(textposition="outside")
            fig_rh.update_layout(showlegend=False, height=300)
            st.plotly_chart(fig_rh, use_container_width=True)

            tech_revs = {t: rev_lat[c].sum() for t, c in [("2G", "2g_rev"), ("3G", "3g_rev"), ("4G", "4g_rev")] if
                         c in rev_lat.columns}
            if tech_revs:
                fig_tp = px.pie(values=list(tech_revs.values()), names=list(tech_revs.keys()), hole=0.45,
                                color_discrete_map={"2G": "#636EFA", "3G": "#EF553B", "4G": "#00CC96"})
                fig_tp.update_layout(height=220, margin=dict(t=20, b=10))
                st.plotly_chart(fig_tp, use_container_width=True)
        else:
            st.info("Load RBC revenue files to see revenue health.")

    st.markdown("---")
    st.subheader("🏭 Vendor × Technology Matrix")
    if len(ven_matrix):
        vm1, vm2 = st.columns([1.6, 1])
        with vm1:
            fig_vm = px.bar(ven_matrix, x="Vendor",
                            y=[col for col in
                               ["Sites_2G", "Sites_3G", "Sites_4G_Total", "Sites_4G_700", "Sites_4G_2100",
                                "Sites_4G_2500"] if col in ven_matrix.columns], barmode="group",
                            text_auto=True, title="Sites per Vendor by Technology",
                            labels={"value": "Sites", "variable": "Technology"},
                            color_discrete_map={"Sites_2G": "#636EFA", "Sites_3G": "#EF553B", "Sites_4G": "#00CC96"})
            fig_vm.for_each_trace(lambda t: t.update(name=t.name.replace("Sites_", "")))
            fig_vm.update_layout(height=320, legend_title="Technology")
            st.plotly_chart(fig_vm, use_container_width=True)
        with vm2:
            st.dataframe(ven_matrix.round(2).reset_index(drop=True),
                         use_container_width=True, hide_index=True, height=320)

    st.markdown("---")
    st.subheader("📍 SDCA-wise Detailed Summary")
    st.caption("Site counts tally with summary: Total=261, 2G=239, 3G=151, 4G=246")

    if len(sdca_sum):
        # Verification row
        verify_cols = ["Total Sites", "2G Sites", "3G Sites", "4G Sites"]
        verify = {c: int(sdca_sum[c].sum()) for c in verify_cols if c in sdca_sum.columns}
        v1, v2, v3, v4 = st.columns(4)
        v1.metric("Σ Total Sites", f"{verify.get('Total Sites', 0):,}")
        v2.metric("Σ 2G Sites", f"{verify.get('2G Sites', 0):,}")
        v3.metric("Σ 3G Sites", f"{verify.get('3G Sites', 0):,}")
        v4.metric("Σ 4G Sites", f"{verify.get('4G Sites', 0):,}")
        st.markdown("---")

        # Split into multiple tables for readability
        tab_sdca1, tab_sdca2, tab_sdca3 = st.tabs([
            "📊 Sites & Technology",
            "📡 Availability",
            "💰 Revenue"
        ])

        with tab_sdca1:
            site_cols = ["SDCA", "Total Sites", "2G Sites", "3G Sites", "4G Sites"]
            site_cols = [c for c in site_cols if c in sdca_sum.columns]
            st.dataframe(sdca_sum[site_cols], use_container_width=True, hide_index=True)

        with tab_sdca2:
            avail_cols = ["SDCA"] + [c for c in sdca_sum.columns if c.startswith("Avg") and "%" in c]
            st.dataframe(sdca_sum[avail_cols].round(2), use_container_width=True, hide_index=True)

        with tab_sdca3:
            rev_cols = ["SDCA", "Rev_Total", "Avg Rev/Site (L)", "Zero_Sites", "Sites_with_Rev"]
            rev_cols = [c for c in rev_cols if c in sdca_sum.columns]
            st.dataframe(sdca_sum[rev_cols].round(3), use_container_width=True, hide_index=True)

        # Vendor breakdown per SDCA
        if len(sdca_vendor):
            st.markdown("---")
            st.subheader("🏭 SDCA × Vendor Breakdown")
            st.dataframe(sdca_vendor, use_container_width=True, hide_index=True)

    if "Radio_Vendor" in df_lat.columns and avail_existing:
        ac = [c for c in avail_existing.values() if c in df_lat.columns]
        va = df_lat.groupby("Radio_Vendor")[ac].mean().round(2).reset_index()
        short = [c.replace("Nw Avail (", "").replace(")", "") for c in ac]
        va.columns = ["Vendor"] + short
        fig_vh = go.Figure(go.Heatmap(
            z=va[short].values.astype(float), x=short, y=va["Vendor"].tolist(),
            colorscale="RdYlGn", zmin=88, zmax=100,
            text=[[f"{v:.1f}%" if not np.isnan(v) else "—" for v in row] for row in va[short].values],
            texttemplate="%{text}", textfont={"size": 12}))
        fig_vh.update_layout(title="Avg Availability % — Vendor × Technology",
                             height=280, margin=dict(t=40, b=10))
        st.plotly_chart(fig_vh, use_container_width=True)

    st.markdown("---")
    st.subheader("⚠️ Data Quality — Unmatched Sites")
    if len(unmatched_sites):
        st.warning(f"{len(unmatched_sites)} sites in performance data have no revenue match.")
        st.dataframe(unmatched_sites.round(2).reset_index(drop=True),
                     use_container_width=True, hide_index=True)
    else:
        st.success("✅ All sites matched to revenue data.")

    st.markdown("---")
    exec_html = gen_exec_html(df_lat, rev_lat, avail_existing,
                              sdca_sum if len(sdca_sum) else None,
                              sdca_vendor if len(sdca_vendor) else None,  # <-- INSERT THIS LINE
                              ven_matrix if len(ven_matrix) else None,
                              unmatched_sites if len(unmatched_sites) else None,
                              _ssa_name, latest_month, has_revenue)
    _dl_btn(exec_html, f"executive_{sel_ssa_code}_{latest_month}.html", "️ Download Executive HTML Report")

# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 – REVENUE INTELLIGENCE
# ══════════════════════════════════════════════════════════════════════════════
with tabs[1]:
    st.header(f"💰 Revenue Intelligence — {_ssa_name} ({sel_ssa_code})")
    if not has_revenue:
        st.info("Upload RBC revenue files from the sidebar.")
    else:
        rev_m_sel = st.selectbox("Revenue Month", rev_months_sorted,
                                 index=len(rev_months_sorted) - 1,
                                 format_func=lambda x: x.upper(), key="ri_month")
        rdf = rev_store[rev_m_sel].copy()
        if "SDCANAME" in rdf.columns:
            rdf["SDCA"] = rdf["SDCANAME"].str.strip().str.title().str.replace("Tirupathur", "Tirupattur", regex=False)
        rdf["SDCA"] = rdf.get("SDCA", pd.Series("Unknown", index=rdf.index)).fillna("Unknown")
        tot_rev = rdf["REV_LAKH"].sum();
        sites = rdf["BTSIPID"].nunique()
        zero_r = int((rdf["REV_LAKH"] == 0).sum());
        avg_r = rdf["REV_LAKH"].mean()
        prev_rdf_sel = rev_store.get(prev_rev_month) if prev_rev_month and rev_m_sel == latest_rev_month else None

        k1, k2, k3, k4, k5 = st.columns(5)
        k1.metric("Total Revenue (L)", f"₹{tot_rev:.2f}")
        k2.metric("Total Sites", f"{sites:,}")
        k3.metric("Avg Rev/Site (L)", f"₹{avg_r:.3f}")
        k4.metric("Zero Revenue Sites", zero_r, delta_color="inverse")
        k5.metric("VLT Sites", int((rdf["4G_Cat"] == "VLT").sum()) if "4G_Cat" in rdf.columns else "—")
        st.markdown("---")

        st.subheader("🔗 Revenue — Availability Correlation")
        if df_lat_rev is not None and "REV_LAKH" in df_lat_rev.columns:
            corr_cols = st.columns(len(avail_existing))
            for ci, (tech, col) in enumerate(avail_existing.items()):
                if col not in df_lat_rev.columns: continue
                with corr_cols[ci]:
                    _sub = df_lat_rev[[col, "REV_LAKH"]].dropna()
                    if len(_sub) > 5:
                        corr_val = _sub[col].corr(_sub["REV_LAKH"])
                        st.metric(f"{tech} ↔ Revenue (r)", f"{corr_val:.3f}",
                                  help="Pearson correlation between availability and revenue")
            fig_corr_all = px.scatter(
                df_lat_rev.dropna(subset=list(avail_existing.values())[:1] + ["REV_LAKH"]),
                x=list(avail_existing.values())[0], y="REV_LAKH",
                color="SDCA" if "SDCA" in df_lat_rev.columns else None,
                trendline="ols", hover_name="BTS Name",
                title=f"Availability vs Revenue — {rev_m_sel.upper()}",
                labels={list(avail_existing.values())[0]: "Availability %", "REV_LAKH": "Revenue (Lakhs)"})
            st.plotly_chart(fig_corr_all, use_container_width=True)
            bucket_col = list(avail_existing.values())[0]
            if bucket_col in df_lat_rev.columns:
                _bc = df_lat_rev[[bucket_col, "REV_LAKH"]].dropna().copy()
                _bc["Avail Bucket"] = pd.cut(_bc[bucket_col],
                                             bins=[-0.01, 90, 95, 99, 100.01],
                                             labels=["<90% 🔴", "90-95% 🟡", "95-99% 🟢", "≥99% ✅"])
                bucket_rev = _bc.groupby("Avail Bucket", observed=True).agg(
                    Sites=("REV_LAKH", "count"), Avg_Rev=("REV_LAKH", "mean"),
                    Total_Rev=("REV_LAKH", "sum")).round(3).reset_index()
                st.subheader("📊 Availability Bucket → Revenue Impact")
                br1, br2 = st.columns(2)
                with br1:
                    fig_br = px.bar(bucket_rev, x="Avail Bucket", y="Avg_Rev",
                                    color="Avail Bucket", text="Avg_Rev",
                                    title="Avg Revenue by Availability Bucket",
                                    color_discrete_map={"<90% 🔴": "#d7191c", "90-95% 🟡": "#fdae61",
                                                        "95-99% 🟢": "#a6d96a", "≥99% ✅": "#1a9641"})
                    fig_br.update_traces(texttemplate="₹%{text:.3f}L", textposition="outside")
                    fig_br.update_layout(showlegend=False)
                    st.plotly_chart(fig_br, use_container_width=True)
                with br2:
                    st.dataframe(bucket_rev, use_container_width=True, hide_index=True)

        st.markdown("---")
        st.subheader("📈 MoM Revenue Gain / Loss")
        if prev_rdf_sel is not None and len(prev_rdf_sel):
            mom = rdf[["BTSIPID", "REV_LAKH", "SDCA"]].merge(
                prev_rdf_sel[["BTSIPID", "REV_LAKH"]].rename(columns={"REV_LAKH": "REV_PREV"}),
                on="BTSIPID", how="outer")
            mom["REV_LAKH"] = mom["REV_LAKH"].fillna(0)
            mom["REV_PREV"] = mom["REV_PREV"].fillna(0)
            mom["Δ Rev"] = (mom["REV_LAKH"] - mom["REV_PREV"]).round(3)
            mom["Δ %"] = np.where(mom["REV_PREV"] > 0, (mom["Δ Rev"] / mom["REV_PREV"] * 100).round(1), None)
            mom["Status"] = mom["Δ Rev"].apply(
                lambda x: "📈 Gain" if x > 0.01 else ("📉 Loss" if x < -0.01 else "➡ Flat"))
            n_gain = int((mom["Δ Rev"] > 0.01).sum());
            n_loss = int((mom["Δ Rev"] < -0.01).sum())
            tot_ch = rdf["REV_LAKH"].sum() - prev_rdf_sel["REV_LAKH"].sum()
            tot_pct = tot_ch / prev_rdf_sel["REV_LAKH"].sum() * 100 if prev_rdf_sel["REV_LAKH"].sum() > 0 else 0

            d1, d2, d3, d4 = st.columns(4)
            d1.metric("Total Δ Rev", f"₹{tot_ch:+.2f}L", f"{tot_pct:+.1f}%")
            d2.metric("Gain Sites", n_gain)
            d3.metric("Loss Sites", n_loss, delta_color="inverse")
            d4.metric("New Sites", int(((mom["REV_PREV"] == 0) & (mom["REV_LAKH"] > 0)).sum()))

            g_tab, l_tab = st.tabs([f"📈 Top 25 Gainers", "📉 Top 25 Losers"])
            show_mom = [c for c in ["BTSIPID", "SDCA", "REV_PREV", "REV_LAKH", "Δ Rev", "Δ %", "Status"] if
                        c in mom.columns]
            with g_tab:
                g25 = mom.nlargest(25, "Δ Rev")[show_mom].reset_index(drop=True)
                st.dataframe(safe_style(g25.round(3), _rev_color, ["REV_LAKH"]), use_container_width=True,
                             hide_index=True)
                fig_g = px.bar(g25, x="Δ Rev", y="BTSIPID", orientation="h", color="Δ Rev",
                               color_continuous_scale="Greens", title="Top 25 Gainers")
                fig_g.update_layout(yaxis={"categoryorder": "total ascending"}, height=600, coloraxis_showscale=False)
                st.plotly_chart(fig_g, use_container_width=True)
            with l_tab:
                l25 = mom.nsmallest(25, "Δ Rev")[show_mom].reset_index(drop=True)
                st.dataframe(l25.round(3), use_container_width=True, hide_index=True)
                fig_l = px.bar(l25, x="Δ Rev", y="BTSIPID", orientation="h", color="Δ Rev",
                               color_continuous_scale="Reds_r", title="Top 25 Losers")
                fig_l.update_layout(yaxis={"categoryorder": "total descending"}, height=600, coloraxis_showscale=False)
                st.plotly_chart(fig_l, use_container_width=True)
        else:
            st.info("Upload ≥2 months of RBC data for MoM analysis.")

        if len(rev_months_sorted) >= 2:
            trend = pd.DataFrame([{"Month": m.upper(), "Total Rev (L)": rev_store[m]["REV_LAKH"].sum().round(2),
                                   "Sites": rev_store[m]["BTSIPID"].nunique(),
                                   "Zero Sites": int((rev_store[m]["REV_LAKH"] == 0).sum())}
                                  for m in rev_months_sorted])
            fig_tr = px.line(trend, x="Month", y="Total Rev (L)", markers=True,
                             title="Total Revenue Trend (Lakhs)")
            st.plotly_chart(fig_tr, use_container_width=True)

        st.markdown("---")
        st.subheader("📊 Revenue by Traffic Category")
        cat_tabs = st.tabs(["2G Cat", "3G Cat", "4G Cat"])
        for ci, (cat_col, tech, rev_col) in enumerate(
                [("2G_Cat", "2G", "2g_rev"), ("3G_Cat", "3G", "3g_rev"), ("4G_Cat", "4G", "4g_rev")]):
            with cat_tabs[ci]:
                if cat_col not in rdf.columns: st.info(f"No {tech} category."); continue
                cg = rdf.groupby(cat_col).agg(Sites=("BTSIPID", "nunique"),
                                              Total_Rev=("REV_LAKH", "sum"), Avg_Rev=("REV_LAKH", "mean")
                                              ).reindex(
                    [c for c in CAT_ORDER if c in rdf[cat_col].dropna().unique()]).round(3).reset_index()
                cg.columns = [cat_col, "Sites", "Total Rev (L)", "Avg Rev/Site (L)"]
                cc1, cc2 = st.columns(2)
                with cc1:
                    fig_cg = px.bar(cg, x=cat_col, y="Total Rev (L)", color=cat_col, text="Total Rev (L)",
                                    color_discrete_map={"VHT": "#1a9641", "HT": "#a6d96a", "MT": "#ffffbf",
                                                        "LT": "#fdae61", "VLT": "#d7191c"})
                    fig_cg.update_traces(texttemplate="₹%{text:.2f}L", textposition="outside")
                    fig_cg.update_layout(showlegend=False)
                    st.plotly_chart(fig_cg, use_container_width=True)
                with cc2:
                    st.dataframe(cg, use_container_width=True, hide_index=True)

        st.markdown("---")
        rev_html = gen_revenue_html(rdf, _ssa_name, rev_m_sel, prev_rdf_sel, prev_rev_month or "")
        _dl_btn(rev_html, f"revenue_{sel_ssa_code}_{rev_m_sel}.html", "⬇️ Download Revenue HTML Report")

# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 – SITE MASTER LIST
# ══════════════════════════════════════════════════════════════════════════════
with tabs[2]:
    st.header(f"📋 Site Master List — {_ssa_name} ({sel_ssa_code}) · {latest_month.upper()}")
    st.caption("Complete site listing: Vendor × Technology × Revenue × Availability · Filter and download.")
    fc1, fc2, fc3, fc4, fc5 = st.columns(5)
    with fc1:
        sdca_opts_sm = ["All"] + sorted(master_site_df["SDCA"].dropna().unique().tolist()) \
            if "SDCA" in master_site_df.columns else ["All"]
        sel_sdca_sm = st.selectbox("SDCA", sdca_opts_sm, key="sm_sdca")
    with fc2:
        v2g_opts = ["All"] + sorted(master_site_df["Vendor_2G_RBC"].dropna().unique().tolist()) \
            if "Vendor_2G_RBC" in master_site_df.columns else ["All"]
        sel_v2g = st.selectbox("2G Vendor", v2g_opts, key="sm_v2g")
    with fc3:
        v3g_opts = ["All"] + sorted(master_site_df["Vendor_3G_RBC"].dropna().unique().tolist()) \
            if "Vendor_3G_RBC" in master_site_df.columns else ["All"]
        sel_v3g = st.selectbox("3G Vendor", v3g_opts, key="sm_v3g")
    with fc4:
        v4g_opts = ["All"] + sorted(master_site_df["Vendor_4G_RBC"].dropna().unique().tolist()) \
            if "Vendor_4G_RBC" in master_site_df.columns else ["All"]
        sel_v4g = st.selectbox("4G Vendor", v4g_opts, key="sm_v4g")
    with fc5:
        cat_opts = ["All"] + CAT_ORDER
        sel_cat_sm = st.selectbox("4G Category", cat_opts, key="sm_cat")

    sm = master_site_df.copy()
    if sel_sdca_sm != "All" and "SDCA" in sm.columns: sm = sm[sm["SDCA"] == sel_sdca_sm]
    if sel_v2g != "All" and "Vendor_2G_RBC" in sm.columns: sm = sm[sm["Vendor_2G_RBC"] == sel_v2g]
    if sel_v3g != "All" and "Vendor_3G_RBC" in sm.columns: sm = sm[sm["Vendor_3G_RBC"] == sel_v3g]
    if sel_v4g != "All" and "Vendor_4G_RBC" in sm.columns: sm = sm[sm["Vendor_4G_RBC"] == sel_v4g]
    if sel_cat_sm != "All" and "4G_Cat" in sm.columns: sm = sm[sm["4G_Cat"] == sel_cat_sm]
    st.caption(f"Showing {len(sm):,} sites")

    show_sm = [c for c in ["BTS IP ID", "BTS Name", "SDCA",
                           "Vendor_2G_RBC", "Vendor_3G_RBC", "Vendor_4G_RBC",
                           "Nw Avail (2G)", "Nw Avail (3G)", "Nw Avail (4G TCS)",
                           "Erl Total", "Data GB Total",
                           "REV_LAKH", "2g_rev", "3g_rev", "4g_rev",
                           "2G_Cat", "3G_Cat", "4G_Cat"] if c in sm.columns]
    sm_tabs = st.tabs(["📋 All Sites", "🏭 By Vendor", "📈 MoM Comparison", "🔗 Rev–Avail Correlation", "⚠️ Data Quality"])

    with sm_tabs[0]:
        avail_sc = [c for c in ["Nw Avail (2G)", "Nw Avail (3G)", "Nw Avail (4G TCS)"] if c in sm.columns]
        sm_disp = sm[show_sm].sort_values("REV_LAKH" if "REV_LAKH" in sm.columns else show_sm[0],
                                          ascending=False).reset_index(drop=True).round(2)
        st.dataframe(safe_style(sm_disp, _avail_color, avail_sc), use_container_width=True, hide_index=True)
        csv_sm = sm_disp.to_csv(index=False)
        st.download_button("⬇️ Download CSV", csv_sm, f"sites_{sel_ssa_code}_{latest_month}.csv", "text/csv",
                           key="sm_csv")

    with sm_tabs[1]:
        st.subheader("Sites grouped by Vendor — Technology-wise")
        st.caption("2G/3G vendor from Radio_Vendor (BTS string). "
                   "3G vendor uses Vendor_3G_str (Nokia/NSN or ZTE). "
                   "4G vendor always TCS/Tejas in BSNL TN.")
        if "Radio_Vendor" in sm.columns:
            _sm2 = sm[sm["_has2g"]].copy() if "_has2g" in sm.columns else sm.copy()
            _sm3 = sm[sm["_has3g"]].copy() if "_has3g" in sm.columns else pd.DataFrame()
            _sm4 = sm[sm["Has_4G_Physical"]].copy() if "Has_4G_Physical" in sm.columns else pd.DataFrame()
            v2g_cnt = _sm2.groupby("Radio_Vendor")["BTS IP ID"].nunique().rename("2G Sites")
            v3g_cnt = (_sm3.groupby("Vendor_3G_str")["BTS IP ID"].nunique().rename("3G Sites")
                       if not _sm3.empty and "Vendor_3G_str" in _sm3.columns
                       else pd.Series(dtype=int, name="3G Sites"))
            v4g_cnt = (_sm4.groupby("Vendor_4G")["BTS IP ID"].nunique().rename("4G Sites")
                       if not _sm4.empty and "Vendor_4G" in _sm4.columns
                       else pd.Series(dtype=int, name="4G Sites"))
            all_vens = sorted((set(v2g_cnt.index) | set(v3g_cnt.index) | set(v4g_cnt.index))
                              - {"—", "Unknown"})
            matrix_rows = []
            for ven in all_vens:
                row = {"Vendor": ven,
                       "2G Sites": int(v2g_cnt.get(ven, 0)),
                       "3G Sites": int(v3g_cnt.get(ven, 0)),
                       "4G Sites": int(v4g_cnt.get(ven, 0))}
                row["Total Sites"] = max(row["2G Sites"], row["3G Sites"], row["4G Sites"])
                for ac_name, ac_col in avail_existing.items():
                    sub_ac = sm[sm["Radio_Vendor"] == ven] if ven in sm["Radio_Vendor"].values else pd.DataFrame()
                    row[f"Avg {ac_name} %"] = round(sub_ac[ac_col].mean(), 2) if len(
                        sub_ac) and ac_col in sub_ac.columns else None
                if "REV_LAKH" in sm.columns:
                    sub_rv = sm[sm["Radio_Vendor"] == ven] if ven in sm["Radio_Vendor"].values else pd.DataFrame()
                    row["Rev (L)"] = round(sub_rv["REV_LAKH"].sum(), 3) if len(sub_rv) else 0
                matrix_rows.append(row)
            matrix_df = pd.DataFrame(matrix_rows).sort_values("Total Sites", ascending=False)
            vm1, vm2 = st.columns([1.6, 1])
            with vm1:
                fig_vm2 = px.bar(matrix_df, x="Vendor",
                                 y=["2G Sites", "3G Sites", "4G Sites"],
                                 barmode="group", text_auto=True,
                                 title="Sites by Vendor & Technology",
                                 color_discrete_map={"2G Sites": "#636EFA",
                                                     "3G Sites": "#EF553B",
                                                     "4G Sites": "#00CC96"})
                fig_vm2.update_layout(height=320, legend_title="Technology")
                st.plotly_chart(fig_vm2, use_container_width=True)
            with vm2:
                st.dataframe(matrix_df.round(2).reset_index(drop=True),
                             use_container_width=True, hide_index=True)
            st.markdown("---")
            for ven in all_vens:
                sub_v = sm[sm["Radio_Vendor"] == ven].copy() if ven in sm["Radio_Vendor"].values else pd.DataFrame()
                cnt_2g = int(sub_v["_has2g"].sum()) if "_has2g" in sub_v.columns else 0
                cnt_3g = int(sub_v["_has3g"].sum()) if "_has3g" in sub_v.columns else 0
                cnt_4g = int(sub_v["Has_4G_Physical"].sum()) if "Has_4G_Physical" in sub_v.columns else 0
                rev_tot = sub_v["REV_LAKH"].sum() if "REV_LAKH" in sub_v.columns else 0
                with st.expander(
                        f"🏭 {ven} — {len(sub_v)} total sites | "
                        f"2G:{cnt_2g} 3G:{cnt_3g} 4G:{cnt_4g} | "
                        f"Rev:₹{rev_tot:.2f}L"):
                    if len(sub_v):
                        sv_cols = [c for c in show_sm if c in sub_v.columns]
                        sv_disp = sub_v[sv_cols].sort_values(
                            "REV_LAKH" if "REV_LAKH" in sub_v.columns else sv_cols[0],
                            ascending=False).reset_index(drop=True).round(2)
                        vk1, vk2, vk3, vk4 = st.columns(4)
                        vk1.metric("Total Sites", len(sub_v))
                        vk2.metric("2G", cnt_2g);
                        vk3.metric("3G", cnt_3g);
                        vk4.metric("4G", cnt_4g)
                        avail_sc_v = [c for c in avail_sc if c in sub_v.columns]
                        for ac_name, ac_col in avail_existing.items():
                            if ac_col in sub_v.columns:
                                st.metric(f"Avg {ac_name} %", f"{sub_v[ac_col].mean():.2f}%")
                        if "REV_LAKH" in sub_v.columns:
                            st.metric("Total Rev (L)", f"₹{rev_tot:.2f}")
                        st.dataframe(safe_style(sv_disp, _avail_color, avail_sc_v),
                                     use_container_width=True, hide_index=True)
                    else:
                        st.info("No sites after current filter.")
        else:
            st.info("Vendor data not available. Load performance files.")

    with sm_tabs[2]:
        st.subheader("Month-on-Month Revenue & Availability Comparison")
        if prev_rev_month and prev_rdf_sel is not None:
            # Only select columns that actually exist in the revenue file
            rev_mom_cols = [c for c in
                            ["BTSIPID", "REV_LAKH", "SDCA", "Vendor_2G_RBC", "Vendor_3G_RBC", "Vendor_4G_RBC", "4G_Cat"]
                            if c in rev_lat.columns]
            rev_mom = rev_lat[rev_mom_cols].merge(
                prev_rdf_sel[["BTSIPID", "REV_LAKH"]].rename(columns={"REV_LAKH": "REV_PREV"}),
                on="BTSIPID", how="outer").fillna(0)
            rev_mom["Δ Rev"] = (rev_mom["REV_LAKH"] - rev_mom["REV_PREV"]).round(3)
            if len(df_prev) and avail_existing:
                for tech, col in avail_existing.items():
                    if col not in df_lat.columns or col not in df_prev.columns: continue
                    cur_av = df_lat.groupby("BTS IP ID")[col].mean().round(2).rename(f"curr_{tech}")
                    prv_av = df_prev.groupby("BTS IP ID")[col].mean().round(2).rename(f"prev_{tech}")
                    avail_mom = pd.concat([cur_av, prv_av], axis=1).reset_index()
                    avail_mom[f"Δ {tech}"] = ((avail_mom[f"curr_{tech}"] - avail_mom[f"prev_{tech}"]).round(2))
                    rev_mom = rev_mom.merge(
                        avail_mom[["BTS IP ID", f"Δ {tech}"]].rename(columns={"BTS IP ID": "BTSIPID"}),
                        on="BTSIPID", how="left")
            delta_cols = [c for c in rev_mom.columns if c.startswith("Δ")]
            worst_cols = ["BTSIPID", "SDCA", "REV_PREV", "REV_LAKH", "Δ Rev"] + [c for c in delta_cols if
                                                                                 "Rev" not in c]
            worst_cols = [c for c in worst_cols if c in rev_mom.columns]
            st.markdown("### 📉 Worst Sites — Revenue Dropped + Availability Degraded")
            worst_combined = rev_mom.nsmallest(25, "Δ Rev")[worst_cols].round(2).reset_index(drop=True)
            st.dataframe(safe_style(worst_combined, _avail_color,
                                    [c for c in delta_cols if c != "Δ Rev" and c in worst_combined.columns]),
                         use_container_width=True, hide_index=True)
            st.markdown("### 📈 Best Sites — Revenue Gained + Availability Improved")
            best_combined = rev_mom.nlargest(25, "Δ Rev")[worst_cols].round(2).reset_index(drop=True)
            st.dataframe(safe_style(best_combined, _avail_color,
                                    [c for c in delta_cols if c != "Δ Rev" and c in best_combined.columns]),
                         use_container_width=True, hide_index=True)
            if "Vendor_2G_RBC" in rev_mom.columns:
                st.markdown("### 🏭 Vendor-wise MoM Revenue")
                ven_mom = rev_mom.groupby("Vendor_2G_RBC")["Δ Rev"].agg(
                    Sites="count", Total_Δ="sum", Avg_Δ="mean").round(3).reset_index()
                st.dataframe(ven_mom.sort_values("Total_Δ").reset_index(drop=True),
                             use_container_width=True, hide_index=True)
        else:
            st.info("Upload ≥2 months of RBC data to enable MoM comparison.")

        if prev_month and len(df_prev) and avail_existing:
            st.markdown("---")
            st.markdown("### 📉 Worst Availability Degradation (Perf MoM)")
            for tech, col in avail_existing.items():
                if col not in df_lat.columns or col not in df_prev.columns: continue
                cur_av = df_lat.groupby("BTS IP ID")[col].mean().rename("curr")
                prv_av = df_prev.groupby("BTS IP ID")[col].mean().rename("prev")
                av_mm = pd.concat([cur_av, prv_av], axis=1).dropna()
                av_mm["Δ"] = av_mm["curr"] - av_mm["prev"]
                meta = df_lat[["BTS IP ID", "BTS Name", "SDCA", "Radio_Vendor"]].drop_duplicates("BTS IP ID").set_index(
                    "BTS IP ID")
                av_mm = av_mm.join(meta)
                with st.expander(f"📡 {tech} — MoM Availability"):
                    w20 = av_mm.nsmallest(20, "Δ")[["BTS Name", "SDCA", "Radio_Vendor", "prev", "curr", "Δ"]].round(
                        2).reset_index()
                    b20 = av_mm.nlargest(20, "Δ")[["BTS Name", "SDCA", "Radio_Vendor", "prev", "curr", "Δ"]].round(
                        2).reset_index()
                    wt, bt = st.tabs(["📉 Worst 20", "📈 Best 20"])
                    with wt: st.dataframe(safe_style(w20, _avail_color, ["curr", "prev"]), use_container_width=True,
                                          hide_index=True)
                    with bt: st.dataframe(safe_style(b20, _avail_color, ["curr", "prev"]), use_container_width=True,
                                          hide_index=True)

    with sm_tabs[3]:
        st.subheader("🔗 Revenue — Availability Correlation by Vendor")
        if has_revenue and avail_existing and len(master_site_df):
            ms_corr = master_site_df.copy()
            for tech, col in avail_existing.items():
                if col not in ms_corr.columns: continue
                fig_sc = px.scatter(ms_corr.dropna(subset=[col, "REV_LAKH"]),
                                    x=col, y="REV_LAKH",
                                    color="Vendor_2G_RBC" if "Vendor_2G_RBC" in ms_corr.columns else "SDCA",
                                    trendline="ols", size="REV_LAKH", size_max=14,
                                    title=f"{tech} Availability vs Revenue — {latest_month.upper()}",
                                    labels={col: "Avail %", "REV_LAKH": "Revenue (Lakhs)"},
                                    color_discrete_map=VEND_COLORS)
                st.plotly_chart(fig_sc, use_container_width=True)
                if "Vendor_2G_RBC" in ms_corr.columns:
                    corr_ven = ms_corr.dropna(subset=[col, "REV_LAKH"]).groupby("Vendor_2G_RBC").apply(
                        lambda g: g[col].corr(g["REV_LAKH"])).round(3).rename("Corr (Avail↔Rev)").reset_index()
                    corr_ven.columns = ["Vendor", "Corr (Avail↔Rev)"]
                    st.dataframe(corr_ven, use_container_width=True, hide_index=True)
        else:
            st.info("Load both performance and revenue data to see correlation.")

    with sm_tabs[4]:
        st.subheader("⚠️ Data Quality Issues")
        if len(unmatched_sites):
            st.warning(f"**{len(unmatched_sites)} sites** in performance data have no revenue match:")
            st.dataframe(unmatched_sites.round(2), use_container_width=True, hide_index=True)
        else:
            st.success("✅ All performance sites matched to revenue data.")
        if "SDCA" in master_site_df.columns:
            unknown_sdca = master_site_df[master_site_df["SDCA"].isin(["Unknown", ""])]
            if len(unknown_sdca):
                st.warning(f"**{len(unknown_sdca)} sites** have Unknown SDCA:")
                st.dataframe(unknown_sdca[show_sm].round(2).reset_index(drop=True),
                             use_container_width=True, hide_index=True)
            else:
                st.success("✅ All sites have a valid SDCA assignment.")
        st.markdown("---")
        site_html = gen_site_master_html(master_site_df if len(master_site_df) else None,
                                         _ssa_name, latest_month)
        _dl_btn(site_html, f"site_master_{sel_ssa_code}_{latest_month}.html", "⬇️ Download Site Master HTML")

# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 – ACTION ITEMS
# ══════════════════════════════════════════════════════════════════════════════
with tabs[3]:
    st.header(f"🎯 Action Items — {_ssa_name} · {latest_month.upper()}")
    st.subheader("🟡 A. Good Availability + Low Revenue")
    if df_lat_rev is not None and "REV_LAKH" in df_lat_rev.columns:
        ac1, ac2 = st.columns(2)
        with ac1:
            avail_th = st.slider("Min Avail %", 85, 100, 95, key="ai_avail")
        with ac2:
            rev_th = st.slider("Max Rev (L)", 0.05, 2.0, 0.5, 0.05, key="ai_rev")
        avail_col_ai = list(avail_existing.values())[0] if avail_existing else None
        if avail_col_ai and avail_col_ai in df_lat_rev.columns:
            good_mask = pd.to_numeric(df_lat_rev[avail_col_ai], errors="coerce") >= avail_th
            rev_mask = pd.to_numeric(df_lat_rev["REV_LAKH"], errors="coerce") <= rev_th
            gal = df_lat_rev[good_mask & rev_mask].copy()
            am1, am2, am3 = st.columns(3)
            am1.metric("Opportunity Sites", len(gal))
            am2.metric("Zero Rev in Set", int((gal["REV_LAKH"] == 0).sum()))
            am3.metric("Avg Rev (L)", f"₹{gal['REV_LAKH'].mean():.3f}" if len(gal) else "—")
            if len(gal):
                gal_show = [c for c in
                            ["BTS IP ID", "BTS Name", "SDCA", "Vendor_2G_RBC", avail_col_ai, "REV_LAKH", "4G_Cat"] if
                            c in gal.columns]
                st.dataframe(safe_style(gal[gal_show].sort_values("REV_LAKH").reset_index(drop=True).round(2),
                                        _avail_color, [avail_col_ai]), use_container_width=True, hide_index=True)
    else:
        st.info("Load both performance and revenue files.")

    st.markdown("---")
    st.subheader("🔴 B. Consistent Poor Availability (Multi-month)")
    if len(months_sorted) >= 2:
        poor_th = st.slider("Poor Avail threshold %", 80, 99, 95, key="ai_poor")
        for tech, col in avail_existing.items():
            poor_sets = [set(mdf[(mdf["Month_Label"] == m) & (mdf[col] < poor_th)]["BTS IP ID"].dropna().astype(str))
                         for m in months_sorted]
            from collections import Counter

            sc = Counter()
            for ps in poor_sets:
                for s in ps: sc[s] += 1
            poor_ids = {s for s, c in sc.items() if c >= 2}
            with st.expander(f"📡 {tech} — {len(poor_ids)} sites below {poor_th}% in ≥2 months"):
                if not poor_ids: st.success("No chronic poor sites!"); continue
                poor_rows = []
                for sid in sorted(poor_ids):
                    mr = df_lat[df_lat["BTS IP ID"].astype(str) == sid]
                    if len(mr) == 0: continue
                    r = mr.iloc[0]
                    row = {"BTS IP ID": sid, "BTS Name": r.get("BTS Name", ""), "SDCA": r.get("SDCA", ""),
                           "Months Below": sc[sid]}
                    for m in months_sorted:
                        dm = mdf[(mdf["BTS IP ID"].astype(str) == sid) & (mdf["Month_Label"] == m)]
                        row[m.upper()] = round(float(dm[col].mean()), 2) if len(dm) and dm[col].notna().any() else None
                    if has_revenue:
                        rv = rev_lat[rev_lat["BTSIPID"] == sid]["REV_LAKH"]
                        row["REV_LAKH"] = round(float(rv.iloc[0]), 3) if len(rv) else None
                    poor_rows.append(row)
                if poor_rows:
                    poor_df = pd.DataFrame(poor_rows).sort_values("Months Below", ascending=False).reset_index(
                        drop=True)
                    month_cols = [m.upper() for m in months_sorted if m.upper() in poor_df.columns]
                    st.dataframe(safe_style(poor_df.round(2), _avail_color, month_cols), use_container_width=True,
                                 hide_index=True)
    else:
        st.info("Upload ≥2 months for chronic poor availability detection.")

    # ══════════════════════════════════════════════════════════════════════════════
    # D. CHRONIC POOR PERFORMERS — LAST 5 MONTHS (with Traffic Details)
    # ══════════════════════════════════════════════════════════════════════════════
    st.markdown("---")
    st.subheader("📉 D. Chronic Poor Performers — Last 5 Months (with Traffic & Location)")
    st.caption("Sites with availability <95% in ≥3 out of last 5 months — with 2G/3G/4G Erlangs & Data (TB)")

    if len(months_sorted) >= 3:
        # Get last 5 months (or all if less than 5)
        last_5_months = months_sorted[-5:] if len(months_sorted) >= 5 else months_sorted

        # Threshold selector
        poor_th_5m = st.slider("Poor Availability Threshold %", 80, 99, 95, key="poor_5m")
        min_months_poor = st.slider("Minimum months below threshold", 2, len(last_5_months), 3, key="min_months_5m")

        st.markdown(f"**Analyzing last {len(last_5_months)} months:** {', '.join(m.upper() for m in last_5_months)}")

        # Build chronic poor performers list with traffic details
        chronic_rows = []

        for sid in df_lat["BTS IP ID"].unique():
            site_months = []

            for month in last_5_months:
                month_data = mdf[(mdf["BTS IP ID"] == sid) & (mdf["Month_Label"] == month)]
                if len(month_data) == 0:
                    continue

                row = month_data.iloc[0]
                month_info = {"Month": month.upper()}

                # Availability per technology
                for tech, col in avail_existing.items():
                    if col in row.index and pd.notna(row[col]):
                        month_info[f"Avail_{tech}"] = round(float(row[col]), 2)

                # Traffic - Erlangs (2G/3G/4G)
                if "Erl (2g)" in row.index and pd.notna(row["Erl (2g)"]):
                    month_info["2G_Erl"] = round(float(row["Erl (2g)"]), 1)
                if "Erl (3g)" in row.index and pd.notna(row["Erl (3g)"]):
                    month_info["3G_Erl"] = round(float(row["Erl (3g)"]), 1)
                if "Erl Total" in row.index and pd.notna(row["Erl Total"]):
                    month_info["4G_Erl"] = round(float(row["Erl Total"]), 1)

                # Traffic - Data GB → convert to TB
                if "Data GB (2g)" in row.index and pd.notna(row["Data GB (2g)"]):
                    month_info["2G_Data_TB"] = round(float(row["Data GB (2g)"]) / 1024, 3)
                if "Data GB (3g)" in row.index and pd.notna(row["Data GB (3g)"]):
                    month_info["3G_Data_TB"] = round(float(row["Data GB (3g)"]) / 1024, 3)
                if "Data GB Total" in row.index and pd.notna(row["Data GB Total"]):
                    month_info["4G_Data_TB"] = round(float(row["Data GB Total"]) / 1024, 3)

                site_months.append(month_info)

            if len(site_months) < len(last_5_months):
                continue  # Skip if not all months present

            # Count months below threshold
            months_below = 0
            for month_info in site_months:
                for tech in avail_existing.keys():
                    avail_key = f"Avail_{tech}"
                    if avail_key in month_info:
                        if month_info[avail_key] < poor_th_5m:
                            months_below += 1
                            break  # Count once per month

            if months_below >= min_months_poor:
                # Get site details from latest month
                latest_data = df_lat[df_lat["BTS IP ID"] == sid]
                if len(latest_data) > 0:
                    r = latest_data.iloc[0]

                    row_data = {
                        "BTS IP ID": sid,
                        "BTS Name": r.get("BTS Name", ""),
                        "SDCA": r.get("SDCA", ""),
                        "Vendor": r.get("Radio_Vendor", ""),
                        "Months Below": months_below,
                    }

                    # Add monthly availability
                    for month_info in site_months:
                        for tech in avail_existing.keys():
                            avail_key = f"Avail_{tech}"
                            if avail_key in month_info:
                                row_data[f"{month_info['Month']}_{tech}"] = month_info[avail_key]

                    # Add traffic averages across the period
                    all_2g_erl = [m.get("2G_Erl", 0) for m in site_months if "2G_Erl" in m]
                    all_3g_erl = [m.get("3G_Erl", 0) for m in site_months if "3G_Erl" in m]
                    all_4g_erl = [m.get("4G_Erl", 0) for m in site_months if "4G_Erl" in m]
                    all_2g_data = [m.get("2G_Data_TB", 0) for m in site_months if "2G_Data_TB" in m]
                    all_3g_data = [m.get("3G_Data_TB", 0) for m in site_months if "3G_Data_TB" in m]
                    all_4g_data = [m.get("4G_Data_TB", 0) for m in site_months if "4G_Data_TB" in m]

                    row_data["Avg 2G Erl"] = round(np.mean(all_2g_erl), 1) if all_2g_erl else 0
                    row_data["Avg 3G Erl"] = round(np.mean(all_3g_erl), 1) if all_3g_erl else 0
                    row_data["Avg 4G Erl"] = round(np.mean(all_4g_erl), 1) if all_4g_erl else 0
                    row_data["Avg 2G Data(TB)"] = round(np.mean(all_2g_data), 3) if all_2g_data else 0
                    row_data["Avg 3G Data(TB)"] = round(np.mean(all_3g_data), 3) if all_3g_data else 0
                    row_data["Avg 4G Data(TB)"] = round(np.mean(all_4g_data), 3) if all_4g_data else 0

                    # Revenue if available
                    if has_revenue and sid in rev_lat["BTSIPID"].values:
                        rev_val = rev_lat[rev_lat["BTSIPID"] == sid]["REV_LAKH"].values[0]
                        row_data["Revenue (L)"] = round(float(rev_val), 3)

                    chronic_rows.append(row_data)

        if chronic_rows:
            chronic_df = pd.DataFrame(chronic_rows)

            # Sort by months below (descending) then by revenue impact
            if "Revenue (L)" in chronic_df.columns:
                chronic_df = chronic_df.sort_values(["Months Below", "Revenue (L)"], ascending=[False, False])
            else:
                chronic_df = chronic_df.sort_values("Months Below", ascending=False)

            # Summary KPIs
            total_chronic = len(chronic_df)
            total_rev_impact = chronic_df["Revenue (L)"].sum() if "Revenue (L)" in chronic_df.columns else 0
            avg_months_poor = chronic_df["Months Below"].mean()

            ck1, ck2, ck3 = st.columns(3)
            ck1.metric("Chronic Poor Sites", f"{total_chronic}")
            ck2.metric("Revenue at Risk (L)", f"₹{total_rev_impact:.2f}")
            ck3.metric("Avg Months Poor", f"{avg_months_poor:.1f}")

            st.markdown("---")

            # Display tabs
            display_tabs = st.tabs(["📊 Summary Table", "📈 Detailed Monthly View", "📥 Export"])

            with display_tabs[0]:
                # Summary columns
                summary_cols = ["BTS IP ID", "BTS Name", "SDCA", "Vendor", "Months Below"]
                if "Revenue (L)" in chronic_df.columns:
                    summary_cols.append("Revenue (L)")
                summary_cols.extend(["Avg 2G Erl", "Avg 3G Erl", "Avg 4G Erl",
                                     "Avg 2G Data(TB)", "Avg 3G Data(TB)", "Avg 4G Data(TB)"])
                summary_cols = [c for c in summary_cols if c in chronic_df.columns]

                st.dataframe(chronic_df[summary_cols].round(2), use_container_width=True, hide_index=True)

            with display_tabs[1]:
                # Detailed monthly view - show all monthly availability columns
                monthly_cols = ["BTS IP ID", "BTS Name", "SDCA", "Vendor", "Months Below"]
                # Add all monthly availability columns
                for month in last_5_months:
                    for tech in avail_existing.keys():
                        col_name = f"{month.upper()}_{tech}"
                        if col_name in chronic_df.columns:
                            monthly_cols.append(col_name)

                st.dataframe(chronic_df[monthly_cols].round(2), use_container_width=True, hide_index=True)

                # Traffic trend chart for selected site
                st.markdown("---")
                st.subheader("Traffic Trend for Selected Site")
                selected_site = st.selectbox("Select Site", chronic_df["BTS IP ID"].tolist(), key="chronic_site_sel")

                if selected_site:
                    site_data = chronic_df[chronic_df["BTS IP ID"] == selected_site].iloc[0]

                    # Plot traffic trends
                    traffic_data = []
                    for month in last_5_months:
                        month_row = {"Month": month.upper()}
                        for tech in ["2G", "3G", "4G"]:
                            erl_col = f"{month.upper()}_{tech}"
                            if erl_col in site_data.index:
                                month_row[f"{tech}_Erl"] = site_data[erl_col]
                        traffic_data.append(month_row)

                    if traffic_data:
                        traffic_df = pd.DataFrame(traffic_data)

                        fig_traffic = px.line(traffic_df, x="Month",
                                              y=[c for c in ["2G_Erl", "3G_Erl", "4G_Erl"] if c in traffic_df.columns],
                                              markers=True, title=f"Traffic Trend - {selected_site}",
                                              labels={"value": "Erlangs", "variable": "Technology"},
                                              color_discrete_map={"2G_Erl": "#636EFA", "3G_Erl": "#EF553B",
                                                                  "4G_Erl": "#00CC96"})
                        fig_traffic.update_layout(height=300)
                        st.plotly_chart(fig_traffic, use_container_width=True)

            with display_tabs[2]:
                # Export options
                st.markdown("### Download Chronic Poor Performers Report")

                # CSV export
                csv_chronic = chronic_df.to_csv(index=False)
                st.download_button("Download CSV", csv_chronic,
                                   f"chronic_poor_performers_{sel_ssa_code}_{latest_month}.csv",
                                   "text/csv", key="dl_chronic_csv")

                # Excel export with multiple sheets
                excel_buffer = io.BytesIO()
                with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
                    # Summary sheet
                    summary_export = chronic_df[summary_cols].copy()
                    summary_export.to_excel(writer, sheet_name='Summary', index=False)

                    # Monthly detail sheet
                    monthly_export = chronic_df[monthly_cols].copy()
                    monthly_export.to_excel(writer, sheet_name='Monthly_Detail', index=False)

                    # Traffic averages sheet
                    traffic_cols = ["BTS IP ID", "BTS Name", "SDCA", "Vendor",
                                    "Avg 2G Erl", "Avg 3G Erl", "Avg 4G Erl",
                                    "Avg 2G Data(TB)", "Avg 3G Data(TB)", "Avg 4G Data(TB)"]
                    traffic_cols = [c for c in traffic_cols if c in chronic_df.columns]
                    traffic_export = chronic_df[traffic_cols].copy()
                    traffic_export.to_excel(writer, sheet_name='Traffic_Averages', index=False)

                st.download_button("Download Excel", excel_buffer.getvalue(),
                                   f"chronic_poor_performers_{sel_ssa_code}_{latest_month}.xlsx",
                                   "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                   key="dl_chronic_excel")
        else:
            st.success(f"No sites found with availability <{poor_th_5m}% in ≥{min_months_poor} months")
    else:
        st.info("Upload ≥3 months of performance data for chronic poor performer analysis.")


    if has_revenue:
        st.markdown("---")
        st.subheader("⚫ C. Zero Revenue Sites")
        zero_df = rev_lat[rev_lat["REV_LAKH"] == 0].copy()
        st.metric("Zero Revenue Sites", len(zero_df))
        if len(zero_df):
            zshow = [c for c in ["BTSIPID", "SDCA", "Vendor_2G_RBC", "Vendor_3G_RBC", "Vendor_4G_RBC",
                                 "2G_Cat", "3G_Cat", "4G_Cat", "Nw Avail (2G)", "Nw Avail (3G)", "Nw Avail (4G TCS)"] if
                     c in zero_df.columns]
            by_sdca = zero_df.groupby("SDCA")["BTSIPID"].count().reset_index();
            by_sdca.columns = ["SDCA", "Zero Rev Sites"]
            zc1, zc2 = st.columns([1.5, 1])
            with zc1:
                fig_z = px.bar(by_sdca.sort_values("Zero Rev Sites", ascending=False), x="SDCA", y="Zero Rev Sites",
                               text="Zero Rev Sites", color="Zero Rev Sites", color_continuous_scale="Reds")
                fig_z.update_traces(textposition="outside");
                st.plotly_chart(fig_z, use_container_width=True)
            with zc2:
                st.dataframe(by_sdca, use_container_width=True, hide_index=True)
                st.dataframe(zero_df[zshow].reset_index(drop=True), use_container_width=True, hide_index=True)
        action_html = _html_head(f"Action Items — {_ssa_name}", _ssa_name, latest_month)
        action_html += _sec("🟡 Good Avail + Low Rev", "<p>See dashboard for interactive filter</p>")
        action_html += _sec("🔴 Consistent Poor Avail", "<p>See dashboard for multi-month analysis</p>")
        action_html += _sec("⚫ Zero Rev Sites", "<p>See dashboard for zero revenue sites</p>")
        action_html += f'<div class="footer">Action Items — {_ssa_name} — {latest_month.upper()}</div></body></html>'
        _dl_btn(action_html, f"actions_{sel_ssa_code}_{latest_month}.html", "⬇️ Download Action Items HTML")

# ══════════════════════════════════════════════════════════════════════════════
# TAB 4 – TRENDS
# ══════════════════════════════════════════════════════════════════════════════
with tabs[4]:
    st.header(f"📊 Monthly Overview — {latest_month.upper()}")
    if "Site Type" in df_lat.columns:
        stc = df_lat["Site Type"].value_counts().reset_index();
        stc.columns = ["Site Type", "Count"]
        stc["% Share"] = (stc["Count"] / stc["Count"].sum() * 100).round(1)
        sc1, sc2 = st.columns(2)
        with sc1:
            fig_sp = px.pie(stc, names="Site Type", values="Count", hole=0.4, title="Site Type Distribution")
            st.plotly_chart(fig_sp, use_container_width=True)
        with sc2:
            st.dataframe(stc, use_container_width=True, hide_index=True)
    if "SDCA" in df_lat.columns and avail_existing:
        ac = [c for c in avail_existing.values() if c in df_lat.columns]
        av_df = df_lat.groupby("SDCA")[ac].mean().round(2).reset_index()
        short = [c.replace("Nw Avail (", "").replace(")", "") for c in ac]
        av_df.columns = ["SDCA"] + short
        fig_hm = go.Figure(go.Heatmap(z=av_df[short].values, x=short, y=av_df["SDCA"].tolist(),
                                      colorscale="RdYlGn", zmin=80, zmax=100,
                                      text=[[f"{v:.2f}%" if not np.isnan(v) else "—" for v in row] for row in
                                            av_df[short].values],
                                      texttemplate="%{text}", textfont={"size": 12}))
        fig_hm.update_layout(title="Avg Availability % — SDCA × Technology", height=400)
        st.plotly_chart(fig_hm, use_container_width=True)

    st.markdown("---")
    st.header("📈 Month-over-Month Trends")
    if len(months_sorted) < 2:
        st.warning("Need ≥2 months of data.")
    else:
        avail_list = [c for c in avail_existing.values() if c in mdf.columns]
        erl_cols = [c for c in ["Erl (2g)", "Erl (3g)", "Erl (2100)", "Erl (2500)", "Erl (700)", "Erl Total"] if
                    c in mdf.columns]
        data_cols = [c for c in ["Data GB (2g)", "Data GB (3g)", "Data GB (2100)", "Data GB (2500)", "Data GB (700)",
                                 "Data GB Total"] if c in mdf.columns]
        agg_d = {**{c: "sum" for c in erl_cols + data_cols}, **{c: "mean" for c in avail_list}}
        monthly = mdf.groupby("Month_Label")[erl_cols + data_cols + avail_list].agg(agg_d).reset_index()
        monthly["sk"] = monthly["Month_Label"].apply(month_sort_key)
        monthly = monthly.sort_values("sk").drop(columns="sk")
        if avail_list:
            mom_m = monthly.melt("Month_Label", value_vars=avail_list, var_name="Technology", value_name="Avg Avail %")
            mom_m["Technology"] = mom_m["Technology"].map({v: k for k, v in AVAIL_COLS.items()})
            st.plotly_chart(px.line(mom_m, x="Month_Label", y="Avg Avail %", color="Technology",
                                    markers=True, title="Availability Trend"), use_container_width=True)
        tc1, tc2 = st.columns(2)
        with tc1:
            if erl_cols:
                st.plotly_chart(
                    px.line(monthly.melt("Month_Label", value_vars=erl_cols, var_name="Band", value_name="Erl"),
                            x="Month_Label", y="Erl", color="Band", markers=True, title="Traffic (Erl) Trend"),
                    use_container_width=True)
        with tc2:
            if data_cols:
                st.plotly_chart(
                    px.line(monthly.melt("Month_Label", value_vars=data_cols, var_name="Band", value_name="GB"),
                            x="Month_Label", y="GB", color="Band", markers=True, title="Data Volume Trend (GB)"),
                    use_container_width=True)
        if has_revenue and len(rev_months_sorted) >= 2:
            trend = pd.DataFrame([{"Month": m.upper(), "Rev (L)": rev_store[m]["REV_LAKH"].sum().round(2),
                                   "Zero Sites": int((rev_store[m]["REV_LAKH"] == 0).sum())}
                                  for m in rev_months_sorted])
            st.plotly_chart(px.line(trend, x="Month", y="Rev (L)", markers=True, title="Revenue Trend"),
                            use_container_width=True)
        st.dataframe(monthly.round(2).reset_index(drop=True), use_container_width=True)

# ══════════════════════════════════════════════════════════════════════════════
# TAB 5 – TRAFFIC ANALYSIS (Erlangs & Data TB)
# ══════════════════════════════════════════════════════════════════════════════
with tabs[5]:
    st.header("📊 Technology-wise Traffic Analysis")
    st.caption("Voice Erlangs and Data Traffic (TB) by Technology — All Uploaded Months")

    # Define traffic columns
    erl_cols = {"2G": "Erl (2g)", "3G": "Erl (3g)", "4G": "Erl Total"}
    data_cols = {"2G": "Data GB (2g)", "3G": "Data GB (3g)", "4G": "Data GB Total"}

    # Filter available columns
    avail_erl = {k: v for k, v in erl_cols.items() if v in mdf.columns}
    avail_data = {k: v for k, v in data_cols.items() if v in mdf.columns}

    if not avail_erl and not avail_data:
        st.warning("No traffic data columns found in uploaded files.")
    else:
        # Month selector
        if len(months_sorted) > 1:
            sel_months_traffic = st.multiselect("Select Months", months_sorted,
                                                default=months_sorted, key="traffic_months")
        else:
            sel_months_traffic = months_sorted

        if not sel_months_traffic:
            st.warning("Please select at least one month.")
        else:
            # Filter data for selected months
            mdf_traffic = mdf[mdf["Month_Label"].isin(sel_months_traffic)].copy()

            # ── AGGREGATE BY MONTH ────────────────────────────────────────────
            st.subheader("📈 Monthly Traffic Summary")

            monthly_stats = []
            for month in sorted(sel_months_traffic, key=month_sort_key):
                month_df = mdf_traffic[mdf_traffic["Month_Label"] == month]
                if len(month_df) == 0:
                    continue

                row = {"Month": month.upper(), "Sites": month_df["BTS IP ID"].nunique()}

                # Erlangs
                for tech, col in avail_erl.items():
                    row[f"{tech}_Erl"] = month_df[col].sum() if col in month_df.columns else 0

                # Data (convert GB to TB)
                for tech, col in avail_data.items():
                    gb_sum = month_df[col].sum() if col in month_df.columns else 0
                    row[f"{tech}_Data_TB"] = gb_sum / 1024  # GB to TB

                monthly_stats.append(row)

            if monthly_stats:
                traffic_df = pd.DataFrame(monthly_stats)

                # Display KPIs for latest month
                if len(traffic_df) > 0:
                    latest = traffic_df.iloc[-1]
                    st.markdown(f"### 📊 Latest Month: {latest['Month']}")

                    kpi_cols = st.columns(6)

                    # Erlang KPIs
                    if "2G_Erl" in latest:
                        kpi_cols[0].metric("2G Erlangs", f"{latest['2G_Erl']:,.0f}")
                    if "3G_Erl" in latest:
                        kpi_cols[1].metric("3G Erlangs", f"{latest['3G_Erl']:,.0f}")
                    if "4G_Erl" in latest:
                        kpi_cols[2].metric("4G Erlangs", f"{latest['4G_Erl']:,.0f}")

                    # Data KPIs
                    if "2G_Data_TB" in latest:
                        kpi_cols[3].metric("2G Data (TB)", f"{latest['2G_Data_TB']:.2f}")
                    if "3G_Data_TB" in latest:
                        kpi_cols[4].metric("3G Data (TB)", f"{latest['3G_Data_TB']:.2f}")
                    if "4G_Data_TB" in latest:
                        kpi_cols[5].metric("4G Data (TB)", f"{latest['4G_Data_TB']:.2f}")

                st.markdown("---")

                # ── TRENDS ───────────────────────────────────────────────────
                st.subheader("📈 Traffic Trends Over Time")

                tab_erl, tab_data = st.tabs(["🔊 Voice Erlangs", "📶 Data (TB)"])

                with tab_erl:
                    if any(col in traffic_df.columns for col in ["2G_Erl", "3G_Erl", "4G_Erl"]):
                        erl_melt = traffic_df.melt(
                            id_vars=["Month", "Sites"],
                            value_vars=[c for c in ["2G_Erl", "3G_Erl", "4G_Erl"] if c in traffic_df.columns],
                            var_name="Technology",
                            value_name="Erlangs"
                        )
                        erl_melt["Technology"] = erl_melt["Technology"].str.replace("_Erl", "")

                        fig_erl = px.line(erl_melt, x="Month", y="Erlangs", color="Technology",
                                          markers=True, title="Voice Traffic (Erlangs) by Technology",
                                          labels={"Erlangs": "Erlangs", "Month": "Month"},
                                          color_discrete_map={"2G": "#636EFA", "3G": "#EF553B", "4G": "#00CC96"})
                        fig_erl.update_traces(line_width=3, marker_size=8)
                        st.plotly_chart(fig_erl, use_container_width=True)

                        # Show data table
                        st.markdown("#### Erlang Summary Table")
                        erl_display = traffic_df[
                            ["Month"] + [c for c in ["2G_Erl", "3G_Erl", "4G_Erl"] if c in traffic_df.columns]].copy()
                        erl_display.columns = ["Month"] + [c.replace("_Erl", " Erl") for c in erl_display.columns[1:]]
                        st.dataframe(erl_display.round(0), use_container_width=True, hide_index=True)

                with tab_data:
                    if any(col in traffic_df.columns for col in ["2G_Data_TB", "3G_Data_TB", "4G_Data_TB"]):
                        data_melt = traffic_df.melt(
                            id_vars=["Month", "Sites"],
                            value_vars=[c for c in ["2G_Data_TB", "3G_Data_TB", "4G_Data_TB"] if
                                        c in traffic_df.columns],
                            var_name="Technology",
                            value_name="Data_TB"
                        )
                        data_melt["Technology"] = data_melt["Technology"].str.replace("_Data_TB", "")

                        fig_data = px.line(data_melt, x="Month", y="Data_TB", color="Technology",
                                           markers=True, title="Data Traffic (TB) by Technology",
                                           labels={"Data_TB": "Terabytes (TB)", "Month": "Month"},
                                           color_discrete_map={"2G": "#636EFA", "3G": "#EF553B", "4G": "#00CC96"})
                        fig_data.update_traces(line_width=3, marker_size=8)
                        st.plotly_chart(fig_data, use_container_width=True)

                        # Show data table
                        st.markdown("#### Data Summary Table (TB)")
                        data_display = traffic_df[["Month"] + [c for c in ["2G_Data_TB", "3G_Data_TB", "4G_Data_TB"] if
                                                               c in traffic_df.columns]].copy()
                        data_display.columns = ["Month"] + [c.replace("_Data_TB", " TB") for c in
                                                            data_display.columns[1:]]
                        st.dataframe(data_display.round(3), use_container_width=True, hide_index=True)

                st.markdown("---")

                # ── TECHNOLOGY SHARE ─────────────────────────────────────────
                st.subheader("📊 Technology Share Analysis")

                if "4G_Erl" in traffic_df.columns or "4G_Data_TB" in traffic_df.columns:
                    share_tabs = st.tabs(["Voice Share", "Data Share"])

                    with share_tabs[0]:
                        if "4G_Erl" in traffic_df.columns:
                            # Calculate total Erlangs
                            traffic_df["Total_Erl"] = traffic_df.get("2G_Erl", 0) + traffic_df.get("3G_Erl",
                                                                                                   0) + traffic_df.get(
                                "4G_Erl", 0)

                            share_df = traffic_df[["Month", "2G_Erl", "3G_Erl", "4G_Erl", "Total_Erl"]].copy()
                            for col in ["2G_Erl", "3G_Erl", "4G_Erl"]:
                                share_df[f"{col}_Share"] = (share_df[col] / share_df["Total_Erl"] * 100).round(1)

                            share_melt = share_df.melt(
                                id_vars="Month",
                                value_vars=["2G_Erl_Share", "3G_Erl_Share", "4G_Erl_Share"],
                                var_name="Technology",
                                value_name="Share %"
                            )
                            share_melt["Technology"] = share_melt["Technology"].str.replace("_Erl_Share", "")

                            fig_share = px.line(share_melt, x="Month", y="Share %", color="Technology",
                                                markers=True, title="Voice Traffic Share by Technology (%)",
                                                color_discrete_map={"2G": "#636EFA", "3G": "#EF553B", "4G": "#00CC96"})
                            fig_share.update_traces(line_width=3, marker_size=8)
                            st.plotly_chart(fig_share, use_container_width=True)

                    with share_tabs[1]:
                        if "4G_Data_TB" in traffic_df.columns:
                            # Calculate total Data
                            traffic_df["Total_Data_TB"] = (traffic_df.get("2G_Data_TB", 0) +
                                                           traffic_df.get("3G_Data_TB", 0) +
                                                           traffic_df.get("4G_Data_TB", 0))

                            share_df = traffic_df[
                                ["Month", "2G_Data_TB", "3G_Data_TB", "4G_Data_TB", "Total_Data_TB"]].copy()
                            for col in ["2G_Data_TB", "3G_Data_TB", "4G_Data_TB"]:
                                share_df[f"{col}_Share"] = (share_df[col] / share_df["Total_Data_TB"] * 100).round(1)

                            share_melt = share_df.melt(
                                id_vars="Month",
                                value_vars=["2G_Data_TB_Share", "3G_Data_TB_Share", "4G_Data_TB_Share"],
                                var_name="Technology",
                                value_name="Share %"
                            )
                            share_melt["Technology"] = share_melt["Technology"].str.replace("_Data_TB_Share", "")

                            fig_share = px.line(share_melt, x="Month", y="Share %", color="Technology",
                                                markers=True, title="Data Traffic Share by Technology (%)",
                                                color_discrete_map={"2G": "#636EFA", "3G": "#EF553B", "4G": "#00CC96"})
                            fig_share.update_traces(line_width=3, marker_size=8)
                            st.plotly_chart(fig_share, use_container_width=True)

                st.markdown("---")

                # ── MoM CHANGE ───────────────────────────────────────────────
                if len(traffic_df) >= 2:
                    st.subheader("📈 Month-over-Month Change")

                    traffic_df_sorted = traffic_df.sort_values("Month", key=lambda x: x.map(month_sort_key))

                    # Calculate MoM change for latest month
                    if len(traffic_df_sorted) >= 2:
                        latest_month = traffic_df_sorted.iloc[-1]["Month"]
                        prev_month = traffic_df_sorted.iloc[-2]["Month"]

                        st.markdown(f"#### {prev_month} → {latest_month}")

                        mom_cols = st.columns(6)

                        # Erlang MoM
                        for i, (tech, col) in enumerate([("2G", "2G_Erl"), ("3G", "3G_Erl"), ("4G", "4G_Erl")]):
                            if col in traffic_df.columns:
                                curr = traffic_df_sorted[traffic_df_sorted["Month"] == latest_month][col].values[0]
                                prev = traffic_df_sorted[traffic_df_sorted["Month"] == prev_month][col].values[0]
                                change = ((curr - prev) / prev * 100) if prev > 0 else 0
                                mom_cols[i].metric(f"{tech} Erl Δ", f"{change:+.1f}%",
                                                   delta=f"{curr - prev:+,.0f} Erl")

                        # Data MoM
                        for i, (tech, col) in enumerate(
                                [("2G", "2G_Data_TB"), ("3G", "3G_Data_TB"), ("4G", "4G_Data_TB")]):
                            if col in traffic_df.columns:
                                curr = traffic_df_sorted[traffic_df_sorted["Month"] == latest_month][col].values[0]
                                prev = traffic_df_sorted[traffic_df_sorted["Month"] == prev_month][col].values[0]
                                change = ((curr - prev) / prev * 100) if prev > 0 else 0
                                mom_cols[i + 3].metric(f"{tech} Data Δ", f"{change:+.1f}%",
                                                       delta=f"{curr - prev:+.3f} TB")

# ══════════════════════════════════════════════════════════════════════════════
# TAB 5 – CIRCLE & SDCA
# ══════════════════════════════════════════════════════════════════════════════
with tabs[6]:
    st.header("🌐 OA / Circle View — TN Circle")
    if not rev_store_full:
        st.info("Upload RBC revenue files to enable Circle-level analysis.")
    else:
        oa_months = sorted(rev_store_full.keys(), key=month_sort_key)
        oa_m = st.selectbox("Revenue Month", oa_months, index=len(oa_months) - 1, format_func=lambda x: x.upper(),
                            key="oa_m")
        oa_df = rev_store_full[oa_m].copy()
        if "SDCANAME" in oa_df.columns:
            oa_df["SDCA"] = oa_df["SDCANAME"].str.strip().str.title().str.replace("Tirupathur", "Tirupattur",
                                                                                  regex=False)
        oa_df["SDCA"] = oa_df.get("SDCA", pd.Series("Unknown")).fillna("Unknown")
        if "SSACODE" in oa_df.columns:
            oa_df["SSA_Label"] = oa_df["SSACODE"].map(SSA_DISPLAY).fillna(oa_df["SSACODE"])
        oa_tot = oa_df["REV_LAKH"].sum();
        oa_sites = oa_df["BTSIPID"].nunique()
        ok1, ok2, ok3 = st.columns(3)
        ok1.metric("Circle Total Revenue (L)", f"₹{oa_tot:.2f}")
        ok2.metric("Total Sites", f"{oa_sites:,}")
        ok3.metric("Zero Rev Sites", int((oa_df["REV_LAKH"] == 0).sum()), delta_color="inverse")
        if "SSACODE" in oa_df.columns:
            ssa_rev = oa_df.groupby(["SSACODE", "SSA_Label"]).agg(
                Sites=("BTSIPID", "nunique"), Total_Rev=("REV_LAKH", "sum"),
                Zero_Sites=("REV_LAKH", lambda x: (x == 0).sum())
            ).round(3).reset_index().sort_values("Total_Rev", ascending=False)
            fig_ssa = px.bar(ssa_rev, x="SSA_Label", y="Total_Rev", color="Total_Rev", text="Total_Rev",
                             color_continuous_scale="Blues", title=f"Revenue by SSA — {oa_m.upper()}")
            fig_ssa.update_traces(texttemplate="₹%{text:.2f}L", textposition="outside")
            fig_ssa.update_layout(coloraxis_showscale=False, xaxis_tickangle=-30)
            st.plotly_chart(fig_ssa, use_container_width=True)
            st.dataframe(ssa_rev.reset_index(drop=True), use_container_width=True, hide_index=True)

    # ══════════════════════════════════════════════════════════════════════════════
    # SDCA-WISE TRAFFIC TECHNOLOGY-WISE MoM
    # ══════════════════════════════════════════════════════════════════════════════
    st.markdown("---")
    st.header("📊 SDCA-wise Traffic Technology-wise MoM")
    st.caption("Voice Erlangs and Data Traffic (TB) by SDCA — All Uploaded Months")

    if len(months_sorted) >= 1 and "SDCA" in mdf.columns:
        # Define traffic columns
        erl_cols_map = {"2G": "Erl (2g)", "3G": "Erl (3g)", "4G": "Erl Total"}
        data_cols_map = {"2G": "Data GB (2g)", "3G": "Data GB (3g)", "4G": "Data GB Total"}

        avail_erl = {k: v for k, v in erl_cols_map.items() if v in mdf.columns}
        avail_data = {k: v for k, v in data_cols_map.items() if v in mdf.columns}

        if not avail_erl and not avail_data:
            st.warning("No traffic data columns found in uploaded files.")
        else:
            # Build SDCA-wise traffic data for all months
            sdca_traffic_rows = []
            for month in sorted(months_sorted, key=month_sort_key):
                month_df = mdf[mdf["Month_Label"] == month]
                if len(month_df) == 0:
                    continue
                # Group by SDCA
                sdca_grp = month_df.groupby("SDCA")
                row_base = {"Month": month.upper()}

                # Erlangs per technology
                for tech, col in avail_erl.items():
                    row_base[f"{tech}_Erl"] = sdca_grp[col].sum()

                # Data GB → TB per technology
                for tech, col in avail_data.items():
                    row_base[f"{tech}_Data_TB"] = sdca_grp[col].sum() / 1024

                # Sites count
                row_base["Sites"] = sdca_grp["BTS IP ID"].nunique()

                # Convert to list of dicts (one per SDCA)
                for sdca_name in row_base["Sites"].index:
                    row = {"SDCA": sdca_name, "Month": month.upper(),
                           "Sites": int(row_base["Sites"].get(sdca_name, 0))}
                    for tech in avail_erl:
                        row[f"{tech}_Erl"] = round(row_base[f"{tech}_Erl"].get(sdca_name, 0), 1)
                    for tech in avail_data:
                        row[f"{tech}_Data_TB"] = round(row_base[f"{tech}_Data_TB"].get(sdca_name, 0), 3)
                    sdca_traffic_rows.append(row)

            if not sdca_traffic_rows:
                st.info("No SDCA-wise traffic data available.")
            else:
                sdca_traffic_df = pd.DataFrame(sdca_traffic_rows)

                # Sub-tabs for different views
                st_traffic_tabs = st.tabs(["📊 Latest Month Detail", "📈 MoM Trend", "🔄 Month Comparison"])

                # ── Sub-tab 1: Latest Month Detail ────────────────────────────
                with st_traffic_tabs[0]:
                    st.markdown(f"#### Latest Month: {latest_month.upper()}")
                    latest_traffic = sdca_traffic_df[sdca_traffic_df["Month"] == latest_month.upper()]

                    if len(latest_traffic) > 0:
                        show_cols = ["SDCA", "Sites"]
                        for tech in avail_erl:
                            show_cols.append(f"{tech}_Erl")
                        for tech in avail_data:
                            show_cols.append(f"{tech}_Data_TB")
                        show_cols = [c for c in show_cols if c in latest_traffic.columns]

                        display_df = latest_traffic[show_cols].copy()
                        col_renames = {"SDCA": "SDCA", "Sites": "Sites"}
                        for tech in avail_erl:
                            col_renames[f"{tech}_Erl"] = f"{tech} Erl"
                        for tech in avail_data:
                            col_renames[f"{tech}_Data_TB"] = f"{tech} Data (TB)"
                        display_df = display_df.rename(columns=col_renames)

                        st.dataframe(display_df.sort_values("Sites", ascending=False),
                                     use_container_width=True, hide_index=True)

                        # Summary KPIs
                        col1, col2, col3 = st.columns(3)
                        total_erl = sum(latest_traffic[f"{t}_Erl"].sum() for t in avail_erl)
                        total_tb = sum(latest_traffic[f"{t}_Data_TB"].sum() for t in avail_data)
                        col1.metric("Total Voice Erlangs", f"{total_erl:,.1f}")
                        col2.metric("Total Data (TB)", f"{total_tb:.3f}")
                        col3.metric("Active SDCAs", f"{latest_traffic['SDCA'].nunique()}")

                        # Download
                        csv_traffic = display_df.to_csv(index=False)
                        st.download_button("⬇️ Download SDCA Traffic CSV", csv_traffic,
                                           f"sdca_traffic_{latest_month}.csv", "text/csv", key="dl_sdca_traffic")

                # ── Sub-tab 2: MoM Trend ──────────────────────────────────────
                with st_traffic_tabs[1]:
                    if len(months_sorted) < 2:
                        st.info("Upload ≥2 months for MoM trend.")
                    else:
                        trend_tabs = st.tabs(["🔊 Voice Erlangs", "📶 Data (TB)"])

                        with trend_tabs[0]:
                            if avail_erl:
                                erl_melt = sdca_traffic_df.melt(
                                    id_vars=["SDCA", "Month"],
                                    value_vars=[f"{t}_Erl" for t in avail_erl],
                                    var_name="Technology", value_name="Erlangs")
                                erl_melt["Technology"] = erl_melt["Technology"].str.replace("_Erl", "")

                                fig_erl = px.line(erl_melt, x="Month", y="Erlangs", color="SDCA",
                                                  facet_col="Technology", markers=True,
                                                  title="Voice Traffic (Erl) by SDCA — MoM",
                                                  color_discrete_map=TC_COLORS)
                                fig_erl.update_layout(height=400)
                                st.plotly_chart(fig_erl, use_container_width=True)

                                # MoM change table
                                if len(months_sorted) >= 2:
                                    last_m = latest_month.upper()
                                    prev_m = months_sorted[-2].upper()
                                    last_df = sdca_traffic_df[sdca_traffic_df["Month"] == last_m].set_index("SDCA")
                                    prev_df = sdca_traffic_df[sdca_traffic_df["Month"] == prev_m].set_index("SDCA")

                                    mom_rows = []
                                    for sdca in last_df.index:
                                        if sdca not in prev_df.index:
                                            continue
                                        row = {"SDCA": sdca}
                                        for tech in avail_erl:
                                            col = f"{tech}_Erl"
                                            curr = last_df.loc[sdca, col] if col in last_df.columns else 0
                                            prev = prev_df.loc[sdca, col] if col in prev_df.columns else 0
                                            delta = curr - prev
                                            pct = (delta / prev * 100) if prev > 0 else None
                                            row[f"{tech} Δ Erl"] = round(delta, 1)
                                            row[f"{tech} Δ %"] = round(pct, 1) if pct is not None else None
                                        mom_rows.append(row)

                                    if mom_rows:
                                        mom_df = pd.DataFrame(mom_rows)
                                        st.dataframe(mom_df.sort_values(
                                            [f"{t} Δ Erl" for t in avail_erl][0], ascending=False),
                                            use_container_width=True, hide_index=True)

                        with trend_tabs[1]:
                            if avail_data:
                                data_melt = sdca_traffic_df.melt(
                                    id_vars=["SDCA", "Month"],
                                    value_vars=[f"{t}_Data_TB" for t in avail_data],
                                    var_name="Technology", value_name="Data_TB")
                                data_melt["Technology"] = data_melt["Technology"].str.replace("_Data_TB", "")

                                fig_data = px.line(data_melt, x="Month", y="Data_TB", color="SDCA",
                                                   facet_col="Technology", markers=True,
                                                   title="Data Traffic (TB) by SDCA — MoM",
                                                   color_discrete_map=TC_COLORS)
                                fig_data.update_layout(height=400)
                                st.plotly_chart(fig_data, use_container_width=True)

                # ── Sub-tab 3: Month Comparison ───────────────────────────────
                with st_traffic_tabs[2]:
                    if len(months_sorted) < 2:
                        st.info("Upload ≥2 months for comparison.")
                    else:
                        comp_c1, comp_c2 = st.columns(2)
                        with comp_c1:
                            m_from = st.selectbox("From", months_sorted[:-1],
                                                  index=len(months_sorted) - 2,
                                                  format_func=str.upper, key="sdca_comp_from")
                        with comp_c2:
                            m_to_opts = [m for m in months_sorted if month_sort_key(m) > month_sort_key(m_from)]
                            m_to = st.selectbox("To", m_to_opts, index=len(m_to_opts) - 1,
                                                format_func=str.upper, key="sdca_comp_to")

                        from_df = sdca_traffic_df[sdca_traffic_df["Month"] == m_from.upper()].set_index("SDCA")
                        to_df = sdca_traffic_df[sdca_traffic_df["Month"] == m_to.upper()].set_index("SDCA")

                        comp_rows = []
                        for sdca in to_df.index:
                            if sdca not in from_df.index:
                                continue
                            row = {"SDCA": sdca}
                            for tech in avail_erl:
                                col = f"{tech}_Erl"
                                curr = to_df.loc[sdca, col] if col in to_df.columns else 0
                                prev = from_df.loc[sdca, col] if col in from_df.columns else 0
                                row[f"{tech} Erl ({m_from.upper()})"] = round(prev, 1)
                                row[f"{tech} Erl ({m_to.upper()})"] = round(curr, 1)
                                row[f"{tech} Δ Erl"] = round(curr - prev, 1)
                            for tech in avail_data:
                                col = f"{tech}_Data_TB"
                                curr = to_df.loc[sdca, col] if col in to_df.columns else 0
                                prev = from_df.loc[sdca, col] if col in from_df.columns else 0
                                row[f"{tech} TB ({m_from.upper()})"] = round(prev, 3)
                                row[f"{tech} TB ({m_to.upper()})"] = round(curr, 3)
                                row[f"{tech} Δ TB"] = round(curr - prev, 3)
                            comp_rows.append(row)

                        if comp_rows:
                            comp_df = pd.DataFrame(comp_rows)
                            st.dataframe(comp_df.sort_values(
                                [f"{t} Δ Erl" for t in avail_erl][0] if avail_erl else comp_df.columns[1],
                                ascending=False),
                                use_container_width=True, hide_index=True)

                            # Download
                            csv_comp = comp_df.to_csv(index=False)
                            st.download_button("⬇️ Download Comparison CSV", csv_comp,
                                               f"sdca_traffic_comp_{m_from}_{m_to}.csv",
                                               "text/csv", key="dl_sdca_comp")
                        else:
                            st.info("No common SDCAs between selected months.")
    else:
        st.info("Upload performance files with SDCA data to see SDCA-wise traffic analysis.")

    st.header("🗺️ SDCA Drill-down")
    if "SDCA" not in mdf.columns:
        st.warning("SDCA data not available.")
    else:
        sdca_list = sorted([s for s in mdf["SDCA"].dropna().unique() if s != "Unknown"])
        sel_sdca = st.selectbox("Select SDCA", sdca_list, key="sdca_sel")
        df_sdca = mdf[mdf["SDCA"] == sel_sdca]
        avail_show = [c for c in avail_existing.values() if c in mdf.columns]
        if prev_month:
            df_p = df_sdca[df_sdca["Month_Label"] == prev_month]
            df_c = df_sdca[df_sdca["Month_Label"] == latest_month]
            col_p, col_c = st.columns(2)
            for cw, dm, lbl in [(col_p, df_p, f"⬅ {prev_month.upper()}"),
                                (col_c, df_c, f"➡ {latest_month.upper()} (Latest)")]:
                with cw:
                    st.markdown(f"### {lbl}");
                    st.metric("Sites", dm["BTS IP ID"].nunique())
                    for ac in avail_show:
                        tn = ac.replace("Nw Avail ", "").replace("(", "").replace(")", "")
                        st.metric(f"Avg {tn}%",
                                  f"{dm[ac].mean():.2f}%" if len(dm) and not dm[ac].isna().all() else "N/A")
                    if len(dm):
                        t = dm.groupby(["BTS IP ID", "BTS Name"])[avail_show].mean().round(2).reset_index()
                        t.columns = ["BTS IP ID", "BTS Name"] + [c.replace("Nw Avail ", "") for c in avail_show]
                        st.dataframe(t, use_container_width=True)

# ══════════════════════════════════════════════════════════════════════════════
# TAB 6 – NETWORK ANALYSIS
# ══════════════════════════════════════════════════════════════════════════════
with tabs[7]:
    st.header(f"📉 Availability Deep Dive — {latest_month.upper()}")
    st.subheader("📊 Availability Distribution")
    dist_rows = []
    for tech, col in avail_existing.items():
        if col not in df_lat.columns: continue
        v = df_lat[col].dropna()
        dist_rows += [{"Technology": tech, "Bucket": "<90%", "Sites": int((v < 90).sum())},
                      {"Technology": tech, "Bucket": "90-95%", "Sites": int(((v >= 90) & (v < 95)).sum())},
                      {"Technology": tech, "Bucket": "95-99%", "Sites": int(((v >= 95) & (v < 99)).sum())},
                      {"Technology": tech, "Bucket": "≥99%", "Sites": int((v >= 99).sum())}]
    if dist_rows:
        fig_dist = px.bar(pd.DataFrame(dist_rows), x="Technology", y="Sites", color="Bucket",
                          barmode="stack", text="Sites", title="Availability Distribution",
                          color_discrete_map={"<90%": "#d7191c", "90-95%": "#fdae61", "95-99%": "#ffffbf",
                                              "≥99%": "#1a9641"})
        fig_dist.update_traces(textposition="inside")
        st.plotly_chart(fig_dist, use_container_width=True)

    if "Radio_Vendor" in df_lat.columns and avail_existing:
        ac = [c for c in avail_existing.values() if c in df_lat.columns]
        va = df_lat.groupby("Radio_Vendor")[ac].mean().round(2).reset_index()
        short = [c.replace("Nw Avail (", "").replace(")", "") for c in ac]
        va.columns = ["Vendor"] + short
        fig_va = go.Figure(go.Heatmap(z=va[short].values.astype(float), x=short, y=va["Vendor"].tolist(),
                                      colorscale="RdYlGn", zmin=88, zmax=100,
                                      text=[[f"{v:.1f}%" for v in row] for row in va[short].values],
                                      texttemplate="%{text}", textfont={"size": 12}))
        fig_va.update_layout(title="Availability — Vendor × Technology", height=280)
        st.plotly_chart(fig_va, use_container_width=True)

    st.subheader("📉 Worst Availability Sites")
    for tech, col in avail_existing.items():
        if col not in df_lat.columns: continue
        n95 = int((df_lat[col] < 95).sum())
        with st.expander(f"📡 {tech} — {n95} sites <95%"):
            w = df_lat.nsmallest(25, col)[["BTS IP ID", "BTS Name", "SDCA", "Radio_Vendor", col]].reset_index(
                drop=True).round(2)
            fig_w = px.bar(w, x=col, y="BTS Name", orientation="h", color=col,
                           color_continuous_scale="RdYlGn", range_color=[80, 100], title=f"Worst 25 — {tech}")
            fig_w.update_layout(yaxis={"categoryorder": "total ascending"}, height=600, coloraxis_showscale=False)
            st.plotly_chart(fig_w, use_container_width=True)
            st.dataframe(safe_style(w, _avail_color, [col]), use_container_width=True, hide_index=True)

    if df_lat_rev is not None and "REV_LAKH" in df_lat_rev.columns and avail_existing:
        st.subheader("🔗 Availability vs Revenue Correlation")
        pc = st.selectbox("Avail metric", list(avail_existing.values()), key="avail_corr_x")
        fig_sc = px.scatter(df_lat_rev.dropna(subset=[pc, "REV_LAKH"]), x=pc, y="REV_LAKH",
                            color="SDCA" if "SDCA" in df_lat_rev.columns else None,
                            hover_name="BTS Name", trendline="ols",
                            title=f"{pc} vs Revenue",
                            labels={pc: "Availability %", "REV_LAKH": "Revenue (Lakhs)"})
        st.plotly_chart(fig_sc, use_container_width=True)

    avail_html = gen_avail_html(df_lat, avail_existing, ven_matrix if len(ven_matrix) else None,
                                sdca_sum if len(sdca_sum) else None, _ssa_name, latest_month,
                                df_prev if len(df_prev) else None, prev_month or "")
    _dl_btn(avail_html, f"availability_{sel_ssa_code}_{latest_month}.html", "⬇️ Download Availability HTML Report")

    st.markdown("---")
    st.header("🔄 Technology Traffic Shift & Leakage Analysis")
    ERL_COLS = {"2G": "Erl (2g)", "3G": "Erl (3g)", "4G 700": "Erl (700)", "4G 2100": "Erl (2100)",
                "4G Total": "Erl Total"}
    DATA_COLS = {"2G": "Data GB (2g)", "3G": "Data GB (3g)", "4G 700": "Data GB (700)", "4G 2100": "Data GB (2100)",
                 "4G Total": "Data GB Total"}
    avail_erl = {k: v for k, v in ERL_COLS.items() if v in mdf.columns}
    avail_data = {k: v for k, v in DATA_COLS.items() if v in mdf.columns}

    st.subheader(f"📋 Site Traffic Rankings — {latest_month.upper()}")
    rank_tabs = st.tabs(["🔊 Voice (Erl)", "📶 Data (GB)"])
    for rt_idx, (rt, col_map, unit) in enumerate([(rank_tabs[0], avail_erl, "Erl"), (rank_tabs[1], avail_data, "GB")]):
        with rt:
            if not col_map: st.info(f"No {unit} columns."); continue
            _rk = df_lat[["BTS IP ID", "BTS Name", "SDCA", "Radio_Vendor", "Has_4G_Physical"] +
                         [v for v in col_map.values() if v in df_lat.columns]].copy()
            _rk = _rk.rename(columns={v: k for k, v in col_map.items() if v in _rk.columns})
            tech_rank_cols = [k for k in col_map if k in _rk.columns]
            if not tech_rank_cols: st.info("No matching columns."); continue
            _rk[f"Total {unit}"] = _rk[tech_rank_cols].sum(axis=1)
            tech_totals = {k: _rk[k].sum() for k in tech_rank_cols}
            fig_tt = px.bar(x=list(tech_totals.keys()), y=list(tech_totals.values()),
                            color=list(tech_totals.keys()), text=[f"{v:,.0f}" for v in tech_totals.values()],
                            title=f"Total {unit} by Technology", color_discrete_map=TC_COLORS,
                            labels={"x": "Technology", "y": unit})
            fig_tt.update_traces(textposition="outside");
            fig_tt.update_layout(showlegend=False, height=300)
            st.plotly_chart(fig_tt, use_container_width=True)
            total_col = f"Total {unit}"
            b_tab, w_tab = st.tabs(["🏆 Best 20", "📉 Worst 20"])
            show_rk = ["BTS IP ID", "BTS Name", "SDCA", "Radio_Vendor"] + tech_rank_cols + [total_col]
            show_rk = [c for c in show_rk if c in _rk.columns]
            with b_tab:
                best20 = _rk.nlargest(20, total_col)[show_rk].reset_index(drop=True).round(2)
                st.dataframe(best20, use_container_width=True, hide_index=True)
                fig_b = px.bar(best20, x=total_col, y="BTS Name", orientation="h", color=total_col,
                               color_continuous_scale="Greens", title=f"Top 20 Sites — {unit}")
                fig_b.update_layout(yaxis={"categoryorder": "total ascending"}, height=550, coloraxis_showscale=False)
                st.plotly_chart(fig_b, use_container_width=True)
            with w_tab:
                worst20 = _rk[_rk[total_col] > 0].nsmallest(20, total_col)[show_rk].reset_index(drop=True).round(2)
                st.dataframe(worst20, use_container_width=True, hide_index=True)

    st.markdown("---")
    st.subheader("📈 Traffic Evolution — All Months (Line Trends)")
    if len(months_sorted) >= 2:
        se_rows = [];
        sd_rows = []
        for m in months_sorted:
            dm = mdf[mdf["Month_Label"] == m]
            re = {"Month": m.upper()};
            rd = {"Month": m.upper()}
            for lbl, col in avail_erl.items():  re[lbl] = dm[col].sum().round(1)
            for lbl, col in avail_data.items(): rd[lbl] = dm[col].sum().round(1)
            se_rows.append(re);
            sd_rows.append(rd)
        se_df = pd.DataFrame(se_rows);
        sd_df = pd.DataFrame(sd_rows)
        erl_techs = [c for c in se_df.columns if c != "Month"]
        data_techs = [c for c in sd_df.columns if c != "Month"]
        ev1, ev2 = st.columns(2)
        with ev1:
            if erl_techs:
                fig_el = px.line(se_df.melt("Month", var_name="Technology", value_name="Erl"),
                                 x="Month", y="Erl", color="Technology", markers=True,
                                 title="Voice Traffic (Erl) — MoM", color_discrete_map=TC_COLORS)
                fig_el.update_traces(line_width=2.5, marker_size=8)
                st.plotly_chart(fig_el, use_container_width=True)
        with ev2:
            if data_techs:
                fig_dl = px.line(sd_df.melt("Month", var_name="Technology", value_name="GB"),
                                 x="Month", y="GB", color="Technology", markers=True,
                                 title="Data Volume (GB) — MoM", color_discrete_map=TC_COLORS)
                fig_dl.update_traces(line_width=2.5, marker_size=8)
                st.plotly_chart(fig_dl, use_container_width=True)
        ev3, ev4 = st.columns(2)
        with ev3:
            if erl_techs:
                se_n = se_df.copy()
                rs = se_n[erl_techs].sum(axis=1).replace(0, np.nan)
                se_n[erl_techs] = se_n[erl_techs].div(rs, axis=0).multiply(100).round(1)
                fig_en = px.line(se_n.melt("Month", var_name="Technology", value_name="Share %"),
                                 x="Month", y="Share %", color="Technology", markers=True,
                                 title="Erl Share % — Migration Trend", color_discrete_map=TC_COLORS)
                st.plotly_chart(fig_en, use_container_width=True)
        with ev4:
            if data_techs:
                sd_n = sd_df.copy()
                rsd = sd_n[data_techs].sum(axis=1).replace(0, np.nan)
                sd_n[data_techs] = sd_n[data_techs].div(rsd, axis=0).multiply(100).round(1)
                fig_dn = px.line(sd_n.melt("Month", var_name="Technology", value_name="Share %"),
                                 x="Month", y="Share %", color="Technology", markers=True,
                                 title="Data Share % — Migration Trend", color_discrete_map=TC_COLORS)
                st.plotly_chart(fig_dn, use_container_width=True)

    st.markdown("---")
    st.subheader("🔍 Site-level Shift — Outage-driven vs Genuine Shift")
    ts1, ts2 = st.columns(2)
    with ts1:
        m_from = st.selectbox("From", months_sorted[:-1], index=len(months_sorted) - 2, format_func=str.upper,
                              key="ts_from")
    with ts2:
        m_to_o = [m for m in months_sorted if month_sort_key(m) > month_sort_key(m_from)]
        m_to = st.selectbox("To", m_to_o, index=len(m_to_o) - 1, format_func=str.upper, key="ts_to")
    df_from = mdf[mdf["Month_Label"] == m_from].groupby("BTS IP ID").first()
    df_to = mdf[mdf["Month_Label"] == m_to].groupby("BTS IP ID").first()
    common = df_from.index.intersection(df_to.index)
    shift_rows = []
    for sid in common:
        rf = df_from.loc[sid];
        rt = df_to.loc[sid]
        row = {"BTS IP ID": sid, "BTS Name": rt.get("BTS Name", ""), "SDCA": rt.get("SDCA", ""),
               "Radio_Vendor": rt.get("Radio_Vendor", "Unknown")}
        for lbl, col in avail_erl.items():
            vf = float(pd.to_numeric(rf.get(col, 0), errors="coerce") or 0)
            vt = float(pd.to_numeric(rt.get(col, 0), errors="coerce") or 0)
            row[f"Erl_{lbl}_FROM"] = round(vf, 2);
            row[f"Erl_{lbl}_TO"] = round(vt, 2);
            row[f"ΔErl_{lbl}"] = round(vt - vf, 2)
        for lbl, col in avail_data.items():
            vf = float(pd.to_numeric(rf.get(col, 0), errors="coerce") or 0)
            vt = float(pd.to_numeric(rt.get(col, 0), errors="coerce") or 0)
            row[f"GB_{lbl}_FROM"] = round(vf, 2);
            row[f"GB_{lbl}_TO"] = round(vt, 2);
            row[f"ΔGB_{lbl}"] = round(vt - vf, 2)
        for tech, col in avail_existing.items():
            if col in df_from.columns and col in df_to.columns:
                avf = float(pd.to_numeric(rf.get(col, 100), errors="coerce") or 100)
                avt = float(pd.to_numeric(rt.get(col, 100), errors="coerce") or 100)
                row[f"Avail_{tech}_FROM"] = round(avf, 2);
                row[f"Avail_{tech}_TO"] = round(avt, 2)
                row[f"ΔAvail_{tech}"] = round(avt - avf, 2)
        shift_rows.append(row)
    shift_df = pd.DataFrame(shift_rows) if shift_rows else pd.DataFrame()
    if not shift_df.empty:
        erl_delta = [c for c in shift_df.columns if c.startswith("ΔErl_")]
        data_delta = [c for c in shift_df.columns if c.startswith("ΔGB_")]
        avail_delta = [c for c in shift_df.columns if c.startswith("ΔAvail_")]
        sum_erl = [];
        sum_data = []
        for lbl in avail_erl:
            fc = f"Erl_{lbl}_FROM";
            tc = f"Erl_{lbl}_TO";
            dc = f"ΔErl_{lbl}"
            if dc not in shift_df.columns: continue
            prev = shift_df[fc].sum() if fc in shift_df.columns else 0
            curr = shift_df[tc].sum() if tc in shift_df.columns else 0
            delta = shift_df[dc].sum()
            sum_erl.append({"Technology": lbl, f"{m_from.upper()} Erl": round(prev, 1),
                            f"{m_to.upper()} Erl": round(curr, 1), "Δ Erl": round(delta, 1),
                            "Δ %": round(delta / prev * 100, 1) if prev else None})
        for lbl in avail_data:
            fc = f"GB_{lbl}_FROM";
            tc = f"GB_{lbl}_TO";
            dc = f"ΔGB_{lbl}"
            if dc not in shift_df.columns: continue
            prev = shift_df[fc].sum() if fc in shift_df.columns else 0
            curr = shift_df[tc].sum() if tc in shift_df.columns else 0
            delta = shift_df[dc].sum()
            sum_data.append({"Technology": lbl, f"{m_from.upper()} GB": round(prev, 1),
                             f"{m_to.upper()} GB": round(curr, 1), "Δ GB": round(delta, 1),
                             "Δ %": round(delta / prev * 100, 1) if prev else None})
        sv_erl = pd.DataFrame(sum_erl);
        sv_data = pd.DataFrame(sum_data)
        sc1, sc2 = st.columns(2)
        with sc1:
            st.markdown("**🔊 Voice (Erl) Summary**")
            if not sv_erl.empty:
                ecol = [c for c in sv_erl.columns if c.startswith("Δ")][0] if any(
                    c.startswith("Δ") for c in sv_erl.columns) else None
                if ecol:
                    fig_es = px.bar(sv_erl, x="Technology", y=ecol, color=ecol,
                                    color_continuous_scale=["#d7191c", "#ffffbf", "#1a9641"], text=ecol)
                    fig_es.update_traces(texttemplate="%{text:+.1f}", textposition="outside")
                    fig_es.update_layout(coloraxis_showscale=False, height=280)
                    st.plotly_chart(fig_es, use_container_width=True)
                st.dataframe(sv_erl, use_container_width=True, hide_index=True)
        with sc2:
            st.markdown("**📶 Data (GB) Summary**")
            if not sv_data.empty:
                dcol = [c for c in sv_data.columns if c.startswith("Δ")][0] if any(
                    c.startswith("Δ") for c in sv_data.columns) else None
                if dcol:
                    fig_ds = px.bar(sv_data, x="Technology", y=dcol, color=dcol,
                                    color_continuous_scale=["#d7191c", "#ffffbf", "#1a9641"], text=dcol)
                    fig_ds.update_traces(texttemplate="%{text:+.1f}", textposition="outside")
                    fig_ds.update_layout(coloraxis_showscale=False, height=280)
                    st.plotly_chart(fig_ds, use_container_width=True)
                st.dataframe(sv_data, use_container_width=True, hide_index=True)

        st.markdown("---")
        st.subheader("❓ Why Did Traffic Change? — Outage-driven vs Genuine Shift")
        total_dc = next((c for c in erl_delta if "Total" in c), erl_delta[0] if erl_delta else None)
        main_avail_dc = avail_delta[0] if avail_delta else None
        if total_dc and main_avail_dc:
            shift_df["Traffic_Change"] = shift_df[total_dc]
            shift_df["Avail_Change"] = shift_df[main_avail_dc]


            def classify_cause(row):
                tc = row["Traffic_Change"];
                ac = row["Avail_Change"]
                if tc < -1 and ac < -2: return "⚠️ Outage-Driven Loss"
                if tc < -1 and ac >= -2: return "🔄 Genuine Traffic Shift/Loss"
                if tc > 1 and ac < -2: return "💪 Growth Despite Outage"
                if tc > 1 and ac >= 0: return "📈 Healthy Growth"
                return "➡ Stable"


            shift_df["Root_Cause"] = shift_df.apply(classify_cause, axis=1)
            CAUSE_C = {"⚠️ Outage-Driven Loss": "#d7191c", "🔄 Genuine Traffic Shift/Loss": "#fdae61",
                       "💪 Growth Despite Outage": "#a6d96a", "📈 Healthy Growth": "#1a9641", "➡ Stable": "#aaaaaa"}
            rc_sum = shift_df["Root_Cause"].value_counts().reset_index()
            rc_sum.columns = ["Root Cause", "Sites"]
            ca1, ca2 = st.columns(2)
            with ca1:
                fig_rc = px.bar(rc_sum, x="Root Cause", y="Sites", color="Root Cause", text="Sites",
                                title="Traffic Change Root Cause", color_discrete_map=CAUSE_C)
                fig_rc.update_traces(textposition="outside");
                fig_rc.update_layout(showlegend=False, xaxis_tickangle=-15)
                st.plotly_chart(fig_rc, use_container_width=True)
            with ca2:
                st.dataframe(rc_sum, use_container_width=True, hide_index=True)
            _quad_df = shift_df.dropna(subset=["Traffic_Change", "Avail_Change"]).copy()
            _quad_df["_sz"] = _quad_df["Traffic_Change"].abs().clip(0.1) + 0.1
            fig_quad = px.scatter(_quad_df,
                                  x="Avail_Change", y="Traffic_Change", color="Root_Cause",
                                  hover_name="BTS Name", size="_sz",
                                  size_max=18,
                                  title=f"Δ Avail % vs Δ Traffic — {m_from.upper()}→{m_to.upper()}",
                                  color_discrete_map=CAUSE_C,
                                  labels={"Avail_Change": "Δ Availability %", "Traffic_Change": "Δ Erl (Total)"})
            fig_quad.add_hline(y=0, line_dash="dash", line_color="gray", annotation_text="No traffic change")
            fig_quad.add_vline(x=0, line_dash="dash", line_color="gray", annotation_text="No avail change")
            fig_quad.add_vline(x=-2, line_dash="dot", line_color="red", annotation_text="Avail degraded")
            st.plotly_chart(fig_quad, use_container_width=True)

            st.markdown("---")
            st.subheader("🚨 Sites with Biggest Traffic Change")
            th_val = max(0.5, shift_df[total_dc].abs().quantile(0.8))
            bm_cols = ["BTS IP ID", "BTS Name", "SDCA", "Radio_Vendor", "Root_Cause"] + erl_delta + avail_delta
            bm_cols = [c for c in bm_cols if c in shift_df.columns]
            g1, g2 = st.columns(2)
            with g1:
                st.markdown("**🟢 Top 20 Gainers**")
                tg = shift_df.nlargest(20, total_dc)[bm_cols].reset_index(drop=True).round(2)
                st.dataframe(safe_style(tg, lambda v: _delta_color(v, th_val), erl_delta), use_container_width=True,
                             hide_index=True)
                fig_gain = px.bar(tg, x=total_dc, y="BTS Name", orientation="h", color=total_dc,
                                  color_continuous_scale="Greens", hover_data=["SDCA", "Root_Cause"])
                fig_gain.update_layout(yaxis={"categoryorder": "total ascending"}, height=600,
                                       coloraxis_showscale=False)
                st.plotly_chart(fig_gain, use_container_width=True)
            with g2:
                st.markdown("**🔴 Top 20 Losers**")
                tl = shift_df.nsmallest(20, total_dc)[bm_cols].reset_index(drop=True).round(2)
                st.dataframe(safe_style(tl, lambda v: _delta_color(v, th_val), erl_delta), use_container_width=True,
                             hide_index=True)
                fig_loss = px.bar(tl, x=total_dc, y="BTS Name", orientation="h", color=total_dc,
                                  color_continuous_scale="Reds_r", hover_data=["SDCA", "Root_Cause"])
                fig_loss.update_layout(yaxis={"categoryorder": "total descending"}, height=600,
                                       coloraxis_showscale=False)
                st.plotly_chart(fig_loss, use_container_width=True)
        else:
            st.info("Upload ≥ 2 months of performance data for shift analysis.")

# ══════════════════════════════════════════════════════════════════════════════
# TAB 7 – OPERATIONS (Incharge + Failure Analysis)
# ══════════════════════════════════════════════════════════════════════════════
with tabs[8]:
    st.header("👷 Incharge Analysis")
    failure_df = st.session_state.failure_df
    has_failure = failure_df is not None and len(failure_df) > 0
    if has_failure and "ssa_id" in failure_df.columns:
        fdf = failure_df[failure_df["ssa_id"].astype(str).str.strip() == sel_ssaid].copy()
        if len(fdf) == 0:
            fdf = failure_df.copy()
    else:
        fdf = failure_df.copy() if has_failure else pd.DataFrame()

    if not has_failure or len(fdf) == 0:
        _fu = st.file_uploader("Upload Failure Report (CSV / XLSX / XLS 97-2003)",
                               type=["csv", "xlsx", "xls"], key="fail_up_inline")
        if _fu:
            try:
                _ff = _tolerant_read_file(_fu)
                _ff.columns = _ff.columns.str.strip()
                for _fc in ["down_hours", "down_minutes"]:
                    if _fc in _ff.columns:
                        _ff[_fc] = pd.to_numeric(_ff[_fc], errors="coerce").fillna(0)
                st.session_state.failure_df = _ff
                st.rerun()
            except Exception as _fe:
                st.error(f"Error: {_fe}")
        else:
            st.info("Upload Failure Report above (CSV / XLSX / XLS 97-2003).")
    else:
        period_str = (f"{fdf['log_date'].min()} → {fdf['log_date'].max()}"
                      if "log_date" in fdf.columns else latest_month)
        st.caption(f"Period: {period_str} | {len(fdf):,} events | "
                   f"{fdf['bts_ip_id'].nunique() if 'bts_ip_id' in fdf.columns else '?'} sites")
        total_hrs = fdf["down_hours"].sum()
        sites_aff = fdf["bts_ip_id"].nunique() if "bts_ip_id" in fdf.columns else 0
        long_events = int((fdf["down_hours"] > 24).sum())
        k1, k2, k3, k4, k5 = st.columns(5)
        k1.metric("Total Failures", f"{len(fdf):,}")
        k2.metric("Sites Affected", f"{sites_aff:,}")
        k3.metric("Total Downtime (Hrs)", f"{total_hrs:,.1f}")
        k4.metric("Avg Hrs/Failure", f"{fdf['down_hours'].mean():.2f}")
        k5.metric("Events >24 hrs", long_events, delta_color="inverse")
        st.markdown("---")

        st.subheader("📊 Root Cause Distribution")
        if "trouble_category" in fdf.columns:
            tc_cnt = fdf["trouble_category"].value_counts().reset_index()
            tc_cnt.columns = ["Category", "Failures"]
            tc_hrs = fdf.groupby("trouble_category")["down_hours"].sum().round(1).reset_index()
            tc_hrs.columns = ["Category", "Total_Hrs"]
            tc_all = tc_cnt.merge(tc_hrs, on="Category").sort_values("Failures", ascending=False)
            fa1, fa2, fa3 = st.columns(3)
            with fa1:
                fig_tc = px.pie(tc_cnt, names="Category", values="Failures", hole=0.42,
                                title="Failures by Root Cause",
                                color_discrete_map={"Power/Battery": "#d62728", "Transmission": "#ff7f0e",
                                                    "Hardware": "#9467bd",
                                                    "Unknown/Other": "#7f7f7f", "Environment": "#2ca02c",
                                                    "Software/Config": "#1f77b4"})
                fig_tc.update_traces(textinfo="label+percent+value")
                st.plotly_chart(fig_tc, use_container_width=True)
            with fa2:
                fig_th = px.bar(tc_all, x="Category", y="Total_Hrs", color="Category",
                                text="Total_Hrs", title="Downtime Hours by Root Cause",
                                color_discrete_map={"Power/Battery": "#d62728", "Transmission": "#ff7f0e",
                                                    "Hardware": "#9467bd",
                                                    "Unknown/Other": "#7f7f7f", "Environment": "#2ca02c",
                                                    "Software/Config": "#1f77b4"})
                fig_th.update_traces(texttemplate="%{text:.0f}h", textposition="outside")
                fig_th.update_layout(showlegend=False, height=320)
                st.plotly_chart(fig_th, use_container_width=True)
            with fa3:
                st.markdown("**🛠️ Remedial Actions**")
                REMEDIAL_ACTIONS = {
                    "Power/Battery": "✅ Check EB supply · Replace expired batteries · Test DG · Install solar backup",
                    "Transmission": "✅ Audit backhaul links · Check E1/STM-1 alarms · Coordinate with transmission team",
                    "Hardware": "✅ Schedule preventive maintenance · Raise hardware replacement request · Vendor site visit",
                    "Unknown/Other": "✅ Conduct detailed site visit · Check all alarms · Raise fault ticket with vendor",
                    "Environment": "✅ Check shelter AC/cooling · Inspect for water ingress · Secure site access",
                    "Software/Config": "✅ Push pending patches · Verify configuration · Coordinate with O&M team",
                }
                for _, row in tc_all.iterrows():
                    cat = row["Category"]
                    st.markdown(f"**{cat}** ({int(row['Failures'])} events)")
                    st.caption(REMEDIAL_ACTIONS.get(cat, REMEDIAL_ACTIONS["Unknown/Other"]))

        st.subheader("🔎 Fault Type Detail")
        if "fault_type" in fdf.columns:
            ft = fdf["fault_type"].value_counts().reset_index()
            ft.columns = ["Fault Type", "Count"]
            ft_hrs = fdf.groupby("fault_type")["down_hours"].sum().round(1).reset_index()
            ft_hrs.columns = ["Fault Type", "Total_Hrs"]
            ft_all = ft.merge(ft_hrs, on="Fault Type").sort_values("Count", ascending=False)
            fig_ft = px.bar(ft_all, x="Count", y="Fault Type", orientation="h",
                            color="Total_Hrs", color_continuous_scale="Reds",
                            text="Count", title="Top Fault Types")
            fig_ft.update_layout(yaxis={"categoryorder": "total ascending"}, height=600)
            st.plotly_chart(fig_ft, use_container_width=True)

        st.markdown("---")
        st.subheader("📡 Technology-wise Failure Analysis")
        if "bts_type" in fdf.columns:
            tech_f = fdf.groupby("bts_type").agg(
                Failures=("bts_ip_id", "count"), Sites=("bts_ip_id", "nunique"),
                Total_Hrs=("down_hours", "sum"), Avg_Hrs=("down_hours", "mean")
            ).round(2).reset_index()
            tf1, tf2 = st.columns(2)
            with tf1:
                fig_tf = px.pie(tech_f, names="bts_type", values="Failures", hole=0.42,
                                title="Failures by Technology",
                                color_discrete_map={"2G": "#636EFA", "3G": "#EF553B", "4G": "#00CC96"})
                st.plotly_chart(fig_tf, use_container_width=True)
            with tf2:
                fig_tf2 = px.bar(tech_f, x="bts_type", y="Total_Hrs", color="bts_type",
                                 text="Total_Hrs", title="Downtime by Technology",
                                 color_discrete_map={"2G": "#636EFA", "3G": "#EF553B", "4G": "#00CC96"})
                fig_tf2.update_traces(texttemplate="%{text:.0f}h", textposition="outside")
                fig_tf2.update_layout(showlegend=False)
                st.plotly_chart(fig_tf2, use_container_width=True)

        st.subheader("🏭 Vendor-wise Failure Analysis")
        if "vendor" in fdf.columns:
            ven_f = fdf.groupby("vendor").agg(
                Failures=("bts_ip_id", "count"), Sites=("bts_ip_id", "nunique"),
                Total_Hrs=("down_hours", "sum"), Avg_Hrs=("down_hours", "mean"),
                Long_Outages=("down_hours", lambda x: (x > 8).sum())
            ).round(2).reset_index().sort_values("Total_Hrs", ascending=False)
            vf1, vf2 = st.columns(2)
            with vf1:
                fig_ven = px.bar(ven_f, x="vendor", y="Total_Hrs", color="vendor",
                                 text="Total_Hrs", title="Total Downtime by Vendor",
                                 color_discrete_map=VEND_COLORS)
                fig_ven.update_traces(texttemplate="%{text:.0f}h", textposition="outside")
                fig_ven.update_layout(showlegend=False)
                st.plotly_chart(fig_ven, use_container_width=True)
            with vf2:
                st.dataframe(ven_f, use_container_width=True, hide_index=True)

        st.markdown("---")
        st.subheader("📍 SDCA-wise Failure Analysis")
        if "SDCA" in fdf.columns:
            sdca_f = fdf.groupby("SDCA").agg(
                Failures=("bts_ip_id", "count"), Sites=("bts_ip_id", "nunique"),
                Total_Hrs=("down_hours", "sum"), Avg_Hrs=("down_hours", "mean"),
                Long_Outages=("down_hours", lambda x: (x > 8).sum())
            ).round(2).reset_index().sort_values("Total_Hrs", ascending=False)
            if has_revenue and "SDCA" in rev_lat.columns:
                sdca_f = sdca_f.merge(
                    rev_lat.groupby("SDCA")["REV_LAKH"].sum().round(3).rename("Rev (L)").reset_index(),
                    on="SDCA", how="left")
            sf1, sf2 = st.columns([1.5, 1])
            with sf1:
                fig_sf = px.bar(sdca_f, x="SDCA", y="Total_Hrs", color="Total_Hrs",
                                color_continuous_scale="Reds", text="Total_Hrs",
                                title="Total Downtime by SDCA")
                fig_sf.update_traces(texttemplate="%{text:.0f}h", textposition="outside")
                fig_sf.update_layout(coloraxis_showscale=False, xaxis_tickangle=-30)
                st.plotly_chart(fig_sf, use_container_width=True)
            with sf2:
                st.dataframe(sdca_f, use_container_width=True, hide_index=True)

        st.markdown("---")
        st.subheader("⏱️ Outage Duration Analysis")
        if "duration_band" in fdf.columns:
            dur_f = fdf["duration_band"].value_counts().reset_index()
            dur_f.columns = ["Duration", "Count"]
            df1, df2 = st.columns(2)
            with df1:
                fig_dur = px.bar(dur_f, x="Duration", y="Count", color="Duration", text="Count",
                                 title="Failures by Duration Band",
                                 color_discrete_map={"1–4 hrs": "#1a9641", "4–8 hrs": "#fdae61",
                                                     "8–24 hrs": "#d7191c", "> 24 hrs": "#7b2d8b"})
                fig_dur.update_traces(textposition="outside")
                fig_dur.update_layout(showlegend=False)
                st.plotly_chart(fig_dur, use_container_width=True)
            with df2:
                long_out = fdf[fdf["down_hours"] > 24].sort_values("down_hours", ascending=False)
                lo_show = [c for c in ["bts_ip_id", "bts_name", "SDCA", "incharge", "vendor",
                                       "down_hours", "trouble_category", "fault_type"] if c in long_out.columns]
                st.markdown(f"**⚠️ {len(long_out)} events >24 hrs:**")
                st.dataframe(long_out[lo_show].head(20).round(2).reset_index(drop=True),
                             use_container_width=True, hide_index=True)

        st.markdown("---")
        st.subheader("🔴 Worst 30 Sites — Total Downtime")
        worst_f = fdf.groupby(["bts_ip_id", "bts_name", "SDCA", "incharge", "vendor"]).agg(
            Failures=("down_hours", "count"), Total_Hrs=("down_hours", "sum"),
            Types=("trouble_category", lambda x: ", ".join(x.dropna().unique()))
        ).reset_index().sort_values("Total_Hrs", ascending=False).head(30).round(2)
        if has_revenue:
            worst_f = worst_f.merge(
                rev_lat[["BTSIPID", "REV_LAKH"]].rename(columns={"BTSIPID": "bts_ip_id"}),
                on="bts_ip_id", how="left")
        st.dataframe(worst_f.reset_index(drop=True), use_container_width=True, hide_index=True)

        f_html = gen_failure_html(fdf, _ssa_name, period_str)
        _dl_btn(f_html, f"failure_{sel_ssa_code}_{latest_month}.html",
                "⬇️ Download Failure Analysis HTML")

# ══════════════════════════════════════════════════════════════════════════════
# TAB 8 – REVENUE IMPACT (Lost Revenue + Revenue Ideas)
# ══════════════════════════════════════════════════════════════════════════════
with tabs[9]:
    st.header(f"💸 Lost Revenue & Outage Impact — {_ssa_name} · {latest_month.upper()}")
    st.caption("Estimates revenue lost due to network unavailability. Filtered per technology for correct site counts.")
    st.subheader("⚙️ Revenue Rate Inputs")
    ri1, ri2, ri3, ri4, ri5 = st.columns(5)
    with ri1:
        rate_erl_2g = st.number_input("₹/Erl — 2G", 0.0, value=15.0, step=1.0, key="lr_2g",
                                      help="Monthly voice revenue per Erlang")
    with ri2:
        rate_erl_3g = st.number_input("₹/Erl — 3G", 0.0, value=12.0, step=1.0, key="lr_3g")
    with ri3:
        rate_gb_3g = st.number_input("₹/GB — 3G Data", 0.0, value=8.0, step=0.5, key="lr_3gd")
    with ri4:
        rate_gb_4g = st.number_input("₹/GB — 4G Data", 0.0, value=5.0, step=0.5, key="lr_4g")
    with ri5:
        days_month = st.number_input("Days in month", 28, 31, value=30, key="lr_days")
    st.markdown("---")

    df_lat["_has2g_lr"] = pd.to_numeric(df_lat.get("2G cnt", 0), errors="coerce").fillna(0) > 0
    df_lat["_has3g_lr"] = pd.to_numeric(df_lat.get("3G cnt", 0), errors="coerce").fillna(0) > 0
    AVAIL_TECH = [
        ("2G", "Nw Avail (2G)", "Erl (2g)", "Data GB (2g)", rate_erl_2g, 0.0, df_lat["_has2g_lr"]),
        ("3G", "Nw Avail (3G)", "Erl (3g)", "Data GB (3g)", rate_erl_3g, rate_gb_3g, df_lat["_has3g_lr"]),
        ("4G", "Nw Avail (4G TCS)", "Erl Total", "Data GB Total", 0.0, rate_gb_4g, df_lat["Has_4G_Physical"]),
    ]
    outage_rows = []
    for tech, avail_col, erl_col, gb_col, erl_rate, gb_rate, tech_mask in AVAIL_TECH:
        if avail_col not in df_lat.columns: continue
        sub = df_lat[tech_mask].copy()
        sub["avail_pct"] = pd.to_numeric(sub[avail_col], errors="coerce").clip(0, 100).fillna(100)
        sub["outage_pct"] = (100 - sub["avail_pct"]).clip(lower=0)
        sub["outage_hrs"] = sub["outage_pct"] / 100 * days_month * 24
        if erl_col and erl_col in sub.columns:
            sub["erl_month"] = pd.to_numeric(sub[erl_col], errors="coerce").fillna(0)
            sub["lost_erl"] = sub["erl_month"] * sub["outage_pct"] / 100
            sub["lost_erl_rev"] = sub["lost_erl"] * erl_rate
        else:
            sub["lost_erl"] = 0.0;
            sub["lost_erl_rev"] = 0.0
        if gb_col and gb_col in sub.columns:
            sub["gb_month"] = pd.to_numeric(sub[gb_col], errors="coerce").fillna(0)
            sub["lost_gb"] = sub["gb_month"] * sub["outage_pct"] / 100
            sub["lost_gb_rev"] = sub["lost_gb"] * gb_rate
        else:
            sub["lost_gb"] = 0.0;
            sub["lost_gb_rev"] = 0.0
        sub["total_lost_rev"] = sub["lost_erl_rev"] + sub["lost_gb_rev"]
        sub["Technology"] = tech
        kcols = [c for c in ["BTS IP ID", "BTS Name", "SDCA", "Radio_Vendor", "Technology",
                             "avail_pct", "outage_pct", "outage_hrs", "lost_erl", "lost_erl_rev",
                             "lost_gb", "lost_gb_rev", "total_lost_rev"] if c in sub.columns]
        outage_rows.append(sub[kcols])

    if not outage_rows:
        st.warning("No availability data found.")
    else:
        outage_df = pd.concat(outage_rows, ignore_index=True)
        tot_lost = outage_df["total_lost_rev"].sum()
        tot_erl_l = outage_df["lost_erl_rev"].sum()
        tot_gb_l = outage_df["lost_gb_rev"].sum()
        sites_any = int((outage_df.groupby("BTS IP ID")["outage_pct"].mean() > 0.1).sum())
        sites_high = int((outage_df.groupby("BTS IP ID")["outage_pct"].mean() > 5).sum())
        k1, k2, k3, k4, k5 = st.columns(5)
        k1.metric("💸 Est. Total Lost Rev", f"₹{tot_lost / 100000:.3f}L")
        k2.metric("🔊 Voice Rev Lost", f"₹{tot_erl_l / 100000:.3f}L")
        k3.metric("📶 Data Rev Lost", f"₹{tot_gb_l / 100000:.3f}L")
        k4.metric("Sites Impacted", f"{sites_any:,}")
        k5.metric("High-Impact >5%", f"{sites_high:,}", delta_color="inverse")
        st.markdown("---")

        st.subheader("📡 Technology-wise Outage & Revenue Impact")
        tech_sum = outage_df.groupby("Technology").agg(
            Sites=("BTS IP ID", "nunique"),
            Avg_Avail=("avail_pct", "mean"),
            Avg_Outage=("outage_pct", "mean"),
            Total_Lost_Erl=("lost_erl", "sum"),
            Lost_Erl_Rev=("lost_erl_rev", "sum"),
            Total_Lost_GB=("lost_gb", "sum"),
            Lost_GB_Rev=("lost_gb_rev", "sum"),
            Total_Lost_Rev=("total_lost_rev", "sum"),
        ).round(2).reset_index()
        tech_sum["Lost Rev (L)"] = (tech_sum["Total_Lost_Rev"] / 100000).round(4)
        ts1, ts2 = st.columns(2)
        with ts1:
            fig_ts = px.bar(tech_sum, x="Technology", y="Lost Rev (L)", color="Technology", text="Lost Rev (L)",
                            title="Est. Lost Revenue by Technology",
                            color_discrete_map={"2G": "#636EFA", "3G": "#EF553B", "4G": "#00CC96"})
            fig_ts.update_traces(texttemplate="₹%{text:.3f}L", textposition="outside")
            fig_ts.update_layout(showlegend=False)
            st.plotly_chart(fig_ts, use_container_width=True)
        with ts2:
            disp = [c for c in ["Technology", "Sites", "Avg_Avail", "Avg_Outage",
                                "Total_Lost_Erl", "Lost_Erl_Rev", "Total_Lost_GB", "Lost_GB_Rev", "Lost Rev (L)"] if
                    c in tech_sum.columns]
            st.dataframe(tech_sum[disp].reset_index(drop=True), use_container_width=True, hide_index=True)

        st.markdown("---")
        st.subheader("🚨 Immediate Revenue Loss — Priority Sites")
        st.caption("Sites ranked by: High actual revenue × High outage = Maximum revenue being lost RIGHT NOW")
        if has_revenue:
            priority_df = outage_df.groupby("BTS IP ID").agg(
                Avg_Avail=("avail_pct", "mean"),
                Avg_Outage=("outage_pct", "mean"),
                Total_Lost=("total_lost_rev", "sum"),
                SDCA=("SDCA", "first"),
                Radio_Vendor=("Radio_Vendor", "first"),
            ).reset_index()
            priority_df = priority_df.merge(
                rev_lat[["BTSIPID", "REV_LAKH", "4G_Cat"]].rename(columns={"BTSIPID": "BTS IP ID"}),
                on="BTS IP ID", how="inner")
            priority_df["Priority_Score"] = (priority_df["REV_LAKH"] * priority_df["Avg_Outage"]).round(4)
            priority_df["Lost Rev (L)"] = (priority_df["Total_Lost"] / 100000).round(5)
            top_priority = priority_df.nlargest(30, "Priority_Score")[
                ["BTS IP ID", "SDCA", "Radio_Vendor", "Avg_Avail", "Avg_Outage",
                 "REV_LAKH", "Lost Rev (L)", "4G_Cat", "Priority_Score"]].reset_index(drop=True).round(3)
            st.dataframe(safe_style(top_priority, _avail_color, ["Avg_Avail"]),
                         use_container_width=True, hide_index=True)

        st.markdown("---")
        st.subheader("🔗 Outage vs Actual Revenue Correlation")
        if has_revenue:
            fig_co = px.scatter(priority_df, x="Avg_Outage", y="REV_LAKH",
                                color="4G_Cat" if "4G_Cat" in priority_df.columns else "SDCA",
                                size="REV_LAKH", size_max=16, trendline="ols",
                                title="Outage % vs Actual Revenue (Site Level)",
                                labels={"Avg_Outage": "Avg Outage %", "REV_LAKH": "Revenue (Lakhs)"},
                                color_discrete_map={"VHT": "#1a9641", "HT": "#a6d96a", "MT": "#ffffbf", "LT": "#fdae61",
                                                    "VLT": "#d7191c"})
            fig_co.update_layout(height=420)
            st.plotly_chart(fig_co, use_container_width=True)
            pot = priority_df["Lost Rev (L)"].sum()
            pr1, pr2, pr3 = st.columns(3)
            pr1.metric("Current Revenue", f"₹{priority_df['REV_LAKH'].sum():.2f}L")
            pr2.metric("Est. Revenue if 100% Avail", f"₹{(priority_df['REV_LAKH'].sum() + pot):.2f}L")
            pr3.metric("💰 Recovery Potential", f"₹{pot:.4f}L")

        st.markdown("---")
        st.subheader("📍 SDCA-wise Outage Impact")
        if "SDCA" in outage_df.columns:
            sdca_lost = outage_df.groupby(["SDCA", "Technology"]).agg(
                Sites=("BTS IP ID", "nunique"), Avg_Outage=("outage_pct", "mean"),
                Total_Lost=("total_lost_rev", "sum")).reset_index()
            sdca_lost["Lost (L)"] = (sdca_lost["Total_Lost"] / 100000).round(4)
            fig_sl = px.bar(sdca_lost, x="SDCA", y="Lost (L)", color="Technology", barmode="stack",
                            text="Lost (L)", title="Est. Lost Revenue by SDCA & Technology",
                            color_discrete_map={"2G": "#636EFA", "3G": "#EF553B", "4G": "#00CC96"})
            fig_sl.update_traces(texttemplate="₹%{text:.3f}L", textposition="inside")
            st.plotly_chart(fig_sl, use_container_width=True)
            sdca_tot = sdca_lost.groupby("SDCA")["Lost (L)"].sum().reset_index()
            sdca_tot = sdca_tot.merge(
                outage_df.groupby("SDCA")["outage_pct"].mean().round(2).rename("Avg Outage %").reset_index(), on="SDCA",
                how="left")
            if has_revenue and "SDCA" in rev_lat.columns:
                sdca_tot = sdca_tot.merge(
                    rev_lat.groupby("SDCA")["REV_LAKH"].sum().round(3).rename("Actual Rev (L)").reset_index(),
                    on="SDCA", how="left")
            st.dataframe(sdca_tot.sort_values("Lost (L)", ascending=False).reset_index(drop=True),
                         use_container_width=True, hide_index=True)

        if "Radio_Vendor" in outage_df.columns:
            st.markdown("---")
            st.subheader("🏭 Vendor-wise Outage Impact")
            ven_lost = outage_df.groupby(["Radio_Vendor", "Technology"]).agg(
                Sites=("BTS IP ID", "nunique"), Avg_Avail=("avail_pct", "mean"),
                Avg_Outage=("outage_pct", "mean"), Total_Lost=("total_lost_rev", "sum")).reset_index()
            ven_lost["Lost (L)"] = (ven_lost["Total_Lost"] / 100000).round(4)
            fig_vl = px.bar(ven_lost, x="Radio_Vendor", y="Lost (L)", color="Technology", barmode="group",
                            title="Est. Lost Revenue by Vendor & Technology",
                            color_discrete_map={"2G": "#636EFA", "3G": "#EF553B", "4G": "#00CC96"})
            st.plotly_chart(fig_vl, use_container_width=True)

        st.markdown("---")
        st.subheader("📋 Site-level Detail")
        sl_c1, sl_c2, sl_c3 = st.columns(3)
        with sl_c1:
            min_out = st.slider("Min Outage %", 0.0, 20.0, 0.5, 0.1, key="lr_min")
        with sl_c2:
            sdca_opts_lr = ["All"] + sorted(
                outage_df["SDCA"].dropna().unique().tolist()) if "SDCA" in outage_df.columns else ["All"]
            sel_sdca_lr = st.selectbox("SDCA", sdca_opts_lr, key="lr_sdca")
        with sl_c3:
            sel_tech_lr = st.selectbox("Technology", ["All"] + sorted(outage_df["Technology"].unique().tolist()),
                                       key="lr_tech")
        site_d = outage_df[outage_df["outage_pct"] >= min_out].copy()
        if sel_sdca_lr != "All" and "SDCA" in site_d.columns: site_d = site_d[site_d["SDCA"] == sel_sdca_lr]
        if sel_tech_lr != "All": site_d = site_d[site_d["Technology"] == sel_tech_lr]
        site_d["Lost (L)"] = (site_d["total_lost_rev"] / 100000).round(5)
        sd_show = [c for c in ["BTS IP ID", "BTS Name", "SDCA", "Radio_Vendor", "Technology",
                               "avail_pct", "outage_pct", "outage_hrs", "lost_erl", "lost_gb", "Lost (L)"] if
                   c in site_d.columns]
        site_d_s = site_d[sd_show].sort_values("Lost (L)", ascending=False).reset_index(drop=True).round(3)
        st.caption(f"{len(site_d_s):,} site-tech rows | Min outage {min_out}%")
        st.dataframe(safe_style(site_d_s, _avail_color, ["avail_pct"]), use_container_width=True, hide_index=True)
        st.download_button("⬇️ Download Outage CSV", site_d_s.to_csv(index=False),
                           f"outage_{sel_ssa_code}_{latest_month}.csv", "text/csv", key="lr_csv")
        corr_df_out = priority_df if has_revenue and len(priority_df) else None
        outage_html = gen_outage_html(outage_df, corr_df_out, tech_sum,
                                      sdca_tot if "SDCA" in outage_df.columns else None,
                                      _ssa_name, latest_month)
        _dl_btn(outage_html, f"outage_{sel_ssa_code}_{latest_month}.html", "⬇️ Download Outage HTML Report")

        st.markdown("---")
        st.subheader("💡 Revenue Improvement Ideas")
        st.caption(
            "Data-driven recommendations to improve revenue based on availability, traffic, and failure analysis.")
        st.subheader("🎯 Priority 1 — Fix Outages to Recover Revenue Immediately")
        if has_failure and has_revenue and len(fdf):
            site_down = fdf.groupby("bts_ip_id").agg(
                Total_Down_Hrs=("down_hours", "sum"), Failures=("down_hours", "count"),
                Top_Trouble=("trouble_category", lambda x: x.value_counts().index[0] if len(x.dropna()) > 0 else "—"),
                Incharge=("incharge", "first"), SDCA=("SDCA", "first")
            ).reset_index().rename(columns={"bts_ip_id": "BTSIPID"})
            recovery = site_down.merge(rev_lat[["BTSIPID", "REV_LAKH", "4G_Cat"]] if "4G_Cat" in rev_lat.columns
                                       else rev_lat[["BTSIPID", "REV_LAKH"]], on="BTSIPID", how="left")
            if "REV_LAKH" in recovery.columns:
                recovery["Lost_Rev_Est"] = (recovery["REV_LAKH"] * recovery["Total_Down_Hrs"] / (30 * 24)).round(4)
                recovery["Priority_Score"] = (recovery["REV_LAKH"] * recovery["Total_Down_Hrs"]).round(2)
                top_rec = recovery.nlargest(20, "Priority_Score")[
                    ["BTSIPID", "SDCA", "Incharge", "REV_LAKH", "Total_Down_Hrs", "Failures",
                     "Top_Trouble", "Lost_Rev_Est", "Priority_Score"]].reset_index(drop=True).round(3)
                st.metric("💰 Total Recoverable Revenue (Est.)",
                          f"₹{recovery['Lost_Rev_Est'].sum():.3f}L")
                st.dataframe(safe_style(top_rec, _rev_color, ["REV_LAKH"]),
                             use_container_width=True, hide_index=True)
                fig_rec = px.bar(top_rec, x="Lost_Rev_Est", y="BTSIPID", orientation="h",
                                 color="Top_Trouble", text="Lost_Rev_Est",
                                 title="Estimated Lost Revenue by Site (Top 20)",
                                 color_discrete_map={"Power/Battery": "#d62728", "Transmission": "#ff7f0e",
                                                     "Hardware": "#9467bd",
                                                     "Unknown/Other": "#7f7f7f", "Environment": "#2ca02c",
                                                     "Software/Config": "#1f77b4"})
                fig_rec.update_traces(texttemplate="₹%{text:.4f}L", textposition="outside")
                fig_rec.update_layout(yaxis={"categoryorder": "total ascending"}, height=550)
                st.plotly_chart(fig_rec, use_container_width=True)
        else:
            st.info("Load both Failure Report and Revenue data to see recovery estimates.")

        st.markdown("---")
        st.subheader("🎯 Priority 2 — VLT Sites Ready for Revenue Uplift")
        st.caption("Sites classified as VLT with good availability = prime upgrade candidates")
        if has_revenue and avail_existing:
            avail_col_main = list(avail_existing.values())[0]
            if df_lat_rev is not None and "REV_LAKH" in df_lat_rev.columns and avail_col_main in df_lat_rev.columns:
                vlt_good = df_lat_rev[(df_lat_rev.get("4G_Cat", "") == "VLT") &
                                      (pd.to_numeric(df_lat_rev[avail_col_main], errors="coerce") >= 95)].copy()
                if len(vlt_good):
                    st.metric("VLT Sites with Good Availability", len(vlt_good))
                    vlt_show = [c for c in ["BTS IP ID", "BTS Name", "SDCA", "Radio_Vendor",
                                            avail_col_main, "REV_LAKH", "Erl Total", "Data GB Total"] if
                                c in vlt_good.columns]
                    st.dataframe(vlt_good[vlt_show].sort_values(avail_col_main, ascending=False)
                                 .reset_index(drop=True).round(2), use_container_width=True, hide_index=True)
                    with st.expander("💡 Actions for VLT Sites"):
                        st.markdown("""
                        **Revenue uplift actions:**
                        1. 📢 **Local marketing campaign** targeting VLT site coverage areas
                        2. 🎯 **JTO/incharge visit** — verify coverage, check interference
                        3. 📱 **Subscriber acquisition drive** — partner with local shops/CSPs
                        4. 🔧 **Antenna tilt optimisation** — improve coverage footprint
                        5. 📊 **Tariff awareness** — ensure competitive tariff is visible locally""")

        st.markdown("---")
        st.subheader("📋 Complete Revenue Improvement Roadmap")
        ideas = [
            {"Priority": "P1 — Immediate", "Action": "Fix power/battery issues at top outage sites",
             "Expected Impact": "High — directly recovers lost revenue", "Owner": "JE/JTO + O&M", "Timeline": "7 days"},
            {"Priority": "P1 — Immediate", "Action": "Resolve transmission failures at hub sites",
             "Expected Impact": "High — multiple dependent sites restored", "Owner": "Transmission Team",
             "Timeline": "7 days"},
            {"Priority": "P2 — Short Term", "Action": "Replace expired batteries at power-critical sites",
             "Expected Impact": "Medium — prevents future outages", "Owner": "Civil/Power Team", "Timeline": "30 days"},
            {"Priority": "P2 — Short Term", "Action": "Escalate Hardware sites to Vendor (TCS/Nokia/Nortel)",
             "Expected Impact": "Medium — reduces hardware-driven outages", "Owner": "Vendor Mgmt",
             "Timeline": "14 days"},
            {"Priority": "P3 — Medium Term", "Action": "Drive VoLTE adoption in low-VoLTE locations",
             "Expected Impact": "Medium — improves ARPU", "Owner": "Marketing + JTO", "Timeline": "30-60 days"},
            {"Priority": "P3 — Medium Term", "Action": "Optimise antenna tilt on low-throughput cells",
             "Expected Impact": "Medium — improves user experience", "Owner": "RF Team", "Timeline": "30-60 days"},
            {"Priority": "P4 — Long Term", "Action": "Add capacity at high-PRB locations",
             "Expected Impact": "High — unlocks congestion-limited revenue", "Owner": "Planning",
             "Timeline": "90+ days"},
            {"Priority": "P4 — Long Term", "Action": "Subscriber acquisition in VLT-site coverage areas",
             "Expected Impact": "High — direct revenue growth", "Owner": "Marketing + Local JTO",
             "Timeline": "60-90 days"},
        ]
        ideas_df = pd.DataFrame(ideas)
        st.dataframe(ideas_df, use_container_width=True, hide_index=True, height=320)
        ideas_html = (_html_head(f"Revenue Improvement Ideas — {_ssa_name}", _ssa_name, latest_month) +
                      _sec("📋 Revenue Improvement Roadmap", _df_html(ideas_df)) +
                      f'<div class="footer">Revenue Ideas — {_ssa_name} — {latest_month.upper()}</div></body></html>')
        _dl_btn(ideas_html, f"revenue_ideas_{sel_ssa_code}_{latest_month}.html",
                "⬇️ Download Revenue Ideas HTML")

# ══════════════════════════════════════════════════════════════════════════════
# TAB 9 – REPORTS & ANALYTICS (Auto Analytics + Executive Report)
# ══════════════════════════════════════════════════════════════════════════════
with tabs[10]:
    st.header("📊 Analytics & Insights Report")

    st.markdown("---")
    st.subheader("📊 SDCA-wise Traffic Technology-wise MoM")
    st.caption("Voice Erlangs and Data Traffic (TB) by SDCA across all uploaded months")

    # Prepare data for all months
    if len(months_sorted) >= 1:
        # Collect data for all months
        all_months_data = []

        for month in months_sorted:
            month_df = mdf[mdf["Month_Label"] == month].copy()
            if len(month_df) == 0:
                continue

            # Group by SDCA
            if "SDCA" in month_df.columns:
                sdca_traffic = month_df.groupby("SDCA").agg({
                    "Erl (2g)": "sum",
                    "Erl (3g)": "sum",
                    "Erl Total": "sum",
                    "Data GB (2g)": "sum",
                    "Data GB (3g)": "sum",
                    "Data GB Total": "sum",
                    "BTS IP ID": "count"
                }).reset_index()

                sdca_traffic.columns = ["SDCA", "2G_Erl", "3G_Erl", "Total_Erl",
                                        "2G_Data_GB", "3G_Data_GB", "Total_Data_GB", "Sites"]

                # Convert GB to TB
                sdca_traffic["2G_Data_TB"] = sdca_traffic["2G_Data_GB"] / 1024
                sdca_traffic["3G_Data_TB"] = sdca_traffic["3G_Data_GB"] / 1024
                sdca_traffic["Total_Data_TB"] = sdca_traffic["Total_Data_GB"] / 1024

                sdca_traffic["Month"] = month.upper()
                all_months_data.append(sdca_traffic)

        if all_months_data:
            # Combine all months
            combined_df = pd.concat(all_months_data, ignore_index=True)

            # Create tabs for different views
            mom_tabs = st.tabs(["📈 MoM Trend", "📊 Latest Month Detail", "🔄 Month Comparison"])

            with mom_tabs[0]:
                st.markdown("#### Voice Traffic (Erlangs) - MoM Trend")
                if "Total_Erl" in combined_df.columns:
                    erl_trend = combined_df.pivot_table(
                        index="SDCA",
                        columns="Month",
                        values="Total_Erl",
                        aggfunc="sum"
                    ).fillna(0)

                    # Calculate MoM change
                    if len(erl_trend.columns) >= 2:
                        months_list = sorted(erl_trend.columns,
                                             key=lambda x: month_sort_key(x.lower()) if isinstance(x, str) else 0)
                        erl_trend = erl_trend[months_list]

                        # Show last 2 months comparison
                        if len(months_list) >= 2:
                            last_month = months_list[-1]
                            prev_month = months_list[-2]
                            erl_mom = pd.DataFrame({
                                "SDCA": erl_trend.index,
                                f"{prev_month} Erl": erl_trend[prev_month].round(1),
                                f"{last_month} Erl": erl_trend[last_month].round(1),
                                "Δ Erl": (erl_trend[last_month] - erl_trend[prev_month]).round(1),
                                "Δ %": ((erl_trend[last_month] - erl_trend[prev_month]) /
                                        erl_trend[prev_month].replace(0, np.nan) * 100).round(1)
                            })


                            # Color coding
                            def erl_color(val):
                                if pd.isna(val):
                                    return ""
                                try:
                                    v = float(val)
                                    if v > 0:
                                        return "background-color:#d4edda"
                                    elif v < 0:
                                        return "background-color:#ffcccc"
                                except:
                                    pass
                                return ""


                            st.dataframe(erl_mom.style.map(erl_color, subset=["Δ Erl", "Δ %"]),
                                         use_container_width=True, hide_index=True)

                            # Chart
                            erl_trend_melted = erl_trend.reset_index().melt(
                                id_vars="SDCA",
                                var_name="Month",
                                value_name="Erlangs"
                            )

                            fig_erl = px.line(erl_trend_melted,
                                              x="Month", y="Erlangs", color="SDCA",
                                              title="Voice Traffic (Erl) by SDCA - Trend",
                                              markers=True)
                            fig_erl.update_layout(xaxis_title="Month", yaxis_title="Erlangs",
                                                  height=400, legend_title="SDCA")
                            st.plotly_chart(fig_erl, use_container_width=True)

                st.markdown("#### Data Traffic (TB) - MoM Trend")
                if "Total_Data_TB" in combined_df.columns:
                    data_trend = combined_df.pivot_table(
                        index="SDCA",
                        columns="Month",
                        values="Total_Data_TB",
                        aggfunc="sum"
                    ).fillna(0)

                    if len(data_trend.columns) >= 2:
                        months_list = sorted(data_trend.columns,
                                             key=lambda x: month_sort_key(x.lower()) if isinstance(x, str) else 0)
                        data_trend = data_trend[months_list]

                        if len(months_list) >= 2:
                            last_month = months_list[-1]
                            prev_month = months_list[-2]
                            data_mom = pd.DataFrame({
                                "SDCA": data_trend.index,
                                f"{prev_month} TB": data_trend[prev_month].round(3),
                                f"{last_month} TB": data_trend[last_month].round(3),
                                "Δ TB": (data_trend[last_month] - data_trend[prev_month]).round(3),
                                "Δ %": ((data_trend[last_month] - data_trend[prev_month]) /
                                        data_trend[prev_month].replace(0, np.nan) * 100).round(1)
                            })


                            def data_color(val):
                                if pd.isna(val):
                                    return ""
                                try:
                                    v = float(val)
                                    if v > 0:
                                        return "background-color:#d4edda"
                                    elif v < 0:
                                        return "background-color:#ffcccc"
                                except:
                                    pass
                                return ""


                            st.dataframe(data_mom.style.map(data_color, subset=["Δ TB", "Δ %"]),
                                         use_container_width=True, hide_index=True)

                            data_trend_melted = data_trend.reset_index().melt(
                                id_vars="SDCA",
                                var_name="Month",
                                value_name="Terabytes"
                            )

                            fig_data = px.line(data_trend_melted,
                                               x="Month", y="Terabytes", color="SDCA",
                                               title="Data Traffic (TB) by SDCA - Trend",
                                               markers=True)
                            fig_data.update_layout(xaxis_title="Month", yaxis_title="Terabytes (TB)",
                                                   height=400, legend_title="SDCA")
                            st.plotly_chart(fig_data, use_container_width=True)

            with mom_tabs[1]:
                st.markdown(f"#### Latest Month: {latest_month.upper()}")
                latest_data = combined_df[combined_df["Month"] == latest_month.upper()]

                if len(latest_data) > 0:
                    show_cols = ["SDCA", "Sites", "2G_Erl", "3G_Erl", "Total_Erl",
                                 "2G_Data_TB", "3G_Data_TB", "Total_Data_TB"]
                    show_cols = [c for c in show_cols if c in latest_data.columns]

                    display_df = latest_data[show_cols].copy()
                    display_df.columns = ["SDCA", "Sites", "2G Erl", "3G Erl", "Total Erl",
                                          "2G Data (TB)", "3G Data (TB)", "Total Data (TB)"]

                    st.dataframe(display_df.round(3), use_container_width=True, hide_index=True)

                    # Summary metrics
                    col1, col2, col3, col4 = st.columns(4)
                    col1.metric("Total Voice Erlangs", f"{latest_data['Total_Erl'].sum():,.1f}")
                    col2.metric("Total Data (TB)", f"{latest_data['Total_Data_TB'].sum():.3f}")
                    col3.metric("Total Sites", f"{latest_data['Sites'].sum():,}")
                    col4.metric("Active SDCAs", f"{latest_data['SDCA'].nunique()}")

            with mom_tabs[2]:
                if len(months_sorted) >= 2:
                    st.markdown("#### Technology-wise Traffic Comparison")

                    # Tech breakdown for each month
                    for month in months_sorted[-2:]:  # Last 2 months
                        month_data = combined_df[combined_df["Month"] == month.upper()]
                        if len(month_data) > 0:
                            st.markdown(f"**{month.upper()}**")

                            tech_summary = pd.DataFrame({
                                "Technology": ["2G Voice", "3G Voice", "2G Data", "3G Data"],
                                "Value": [
                                    f"{month_data['2G_Erl'].sum():,.1f} Erl",
                                    f"{month_data['3G_Erl'].sum():,.1f} Erl",
                                    f"{month_data['2G_Data_TB'].sum():.3f} TB",
                                    f"{month_data['3G_Data_TB'].sum():.3f} TB"
                                ]
                            })

                            st.table(tech_summary)
                            st.markdown("---")
                else:
                    st.info("Upload at least 2 months to see comparison")
        else:
            st.warning("No SDCA data available in uploaded files")
    else:
        st.info("Upload performance files to see SDCA-wise traffic analysis")

    st.caption("Automated data-driven analysis — no external API or key required.")
    st.markdown("---")
    st.subheader("📊 Auto Analytics — No API Key Required")
    st.caption("Data-driven insights computed directly from loaded data.")
    if st.button("▶️ Generate Auto Analytics", key="auto_analytics"):
        insights = []
        if avail_existing and len(df_lat):
            for tech, col in avail_existing.items():
                if col in df_lat.columns:
                    avg = df_lat[col].mean()
                    n95 = int((df_lat[col] < 95).sum())
                    worst = df_lat.nsmallest(5, col)[["BTS Name", "SDCA", col]].reset_index(drop=True)
                    worst_sites_str = ", ".join(
                        [f"{row['BTS Name']} ({row['SDCA']}) at {row[col]:.1f}%" for _, row in worst.iterrows()])
                    insights.append(f"📡 **{tech} Availability**: Avg **{avg:.2f}%** — "
                                    f"**{n95}** sites below 95% threshold. "
                                    f"Worst sites: {worst_sites_str}.")
        if has_revenue:
            tot = rev_lat["REV_LAKH"].sum();
            zero = int((rev_lat["REV_LAKH"] == 0).sum())
            avg_r = rev_lat["REV_LAKH"].mean()
            top_site = rev_lat.nlargest(1, "REV_LAKH").iloc[0]
            bot_site = rev_lat[rev_lat["REV_LAKH"] > 0].nsmallest(1, "REV_LAKH").iloc[0]
            insights.append(f"💰 **Revenue**: Total ₹**{tot:.2f}L** across "
                            f"**{rev_lat['BTSIPID'].nunique()}** sites. Avg ₹{avg_r:.3f}L/site. "
                            f"**{zero}** zero-revenue sites need urgent action.")
            insights.append(f"🏆 **Best site**: {top_site['BTSIPID']} "
                            f"({top_site.get('SDCA', '—')}) → ₹{top_site['REV_LAKH']:.2f}L")
            insights.append(f"⚠️ **Lowest active site**: {bot_site['BTSIPID']} "
                            f"({bot_site.get('SDCA', '—')}) → ₹{bot_site['REV_LAKH']:.3f}L")
            if "4G_Cat" in rev_lat.columns:
                vlt = int((rev_lat["4G_Cat"] == "VLT").sum())
                vht = int((rev_lat["4G_Cat"] == "VHT").sum())
                insights.append(f"📊 **Revenue tiers**: VHT={vht} | VLT={vlt} sites. "
                                f"{'⚠️ High VLT count — revenue uplift opportunity' if vlt > 20 else '✅ Good tier distribution'}")
        if has_failure and len(fdf):
            tot_f = len(fdf);
            tot_h = fdf["down_hours"].sum()
            top_cat = fdf["trouble_category"].value_counts().index[
                0] if "trouble_category" in fdf.columns else "Unknown"
            worst_ic = fdf.groupby("incharge")["down_hours"].sum().idxmax() if "incharge" in fdf.columns else "—"
            insights.append(f"🔧 **Failures**: **{tot_f}** events, **{tot_h:.0f}** total downtime hours. "
                            f"Top cause: **{top_cat}**. "
                            f"Incharge needing most attention: **{worst_ic}**.")
        if len(ven_matrix):
            avail_vc = [c2 for c2 in ven_matrix.columns if c2.startswith("Avg")]
            if avail_vc:
                worst_v = ven_matrix.sort_values(avail_vc[0]).iloc[0]
                insights.append(f"🏭 **Vendor watch**: **{worst_v['Vendor']}** has lowest "
                                f"avg availability ({worst_v[avail_vc[0]]:.1f}%). "
                                f"Review maintenance SLA with this vendor.")
        if len(unmatched_sites):
            insights.append(f"⚠️ **Data Quality**: **{len(unmatched_sites)}** performance sites "
                            "have no revenue match — verify BTS IP ID alignment between systems.")
        insights.append("---")
        insights.append("**🎯 Top 3 Recommended Actions:**")
        actions = []
        if has_revenue and int((rev_lat["REV_LAKH"] == 0).sum()) > 0:
            actions.append(
                f"1. Fix **{int((rev_lat['REV_LAKH'] == 0).sum())} zero-revenue sites** immediately — check alarms and connectivity.")
        for tech, col in avail_existing.items():
            n90 = int((df_lat[col] < 90).sum()) if col in df_lat.columns else 0
            if n90 > 0:
                actions.append(f"2. Resolve **{n90} {tech} sites below 90%** — critical availability issue.")
                break
        if has_failure and len(fdf):
            top_cat2 = fdf["trouble_category"].value_counts().index[0] if "trouble_category" in fdf.columns else None
            if top_cat2:
                actions.append(
                    f"3. Address **{top_cat2}** failures ({fdf['trouble_category'].value_counts().iloc[0]} events) — highest failure category.")
        for a in actions: insights.append(a)
        for ins in insights:
            st.markdown(ins)
        st.success("✅ Auto analytics complete — no API key required.")

    st.markdown("---")
    st.header(f"🏆 Executive Report — {_ssa_name} ({sel_ssa_code}) · {latest_month.upper()}")
    exec_total = df_lat["BTS IP ID"].nunique()
    s4g_er = int(df_lat["Has_4G_Physical"].sum())
    avg_avails = {tech: df_lat[col].mean() for tech, col in avail_existing.items() if col in df_lat.columns}
    ek_cols = st.columns(6)
    ek_cols[0].metric("Total Sites", exec_total)
    ek_cols[1].metric("4G Physical", s4g_er)
    for i, (tech, avg) in enumerate(avg_avails.items()):
        if i + 2 < 6: ek_cols[i + 2].metric(f"Avg {tech}%", f"{avg:.2f}%")
    if has_revenue: ek_cols[5].metric("Total Rev (L)", f"₹{rev_lat['REV_LAKH'].sum():.2f}")
    st.markdown("---")
    kpis_dict = {
        "Total Sites": exec_total,
        "2G Active": int(df_lat["_has2g"].sum()) if "_has2g" in df_lat.columns else "N/A",
        "3G Active": int(df_lat["_has3g"].sum()) if "_has3g" in df_lat.columns else "N/A",
        "4G Physical": s4g_er,
        "4G 700 MHz": int(
            df_lat["BTS Site ID (700)"].notna().sum()) if "BTS Site ID (700)" in df_lat.columns else "N/A",
        "4G 2100 MHz": int(
            df_lat["BTS Site ID (2100)"].notna().sum()) if "BTS Site ID (2100)" in df_lat.columns else "N/A",
        "4G 2500 MHz": int(
            df_lat["BTS Site ID (2500)"].notna().sum()) if "BTS Site ID (2500)" in df_lat.columns else "N/A",
    }
    for tech, avg in avg_avails.items():
        n90 = int((df_lat[avail_existing[tech]] < 90).sum())
        n95 = int((df_lat[avail_existing[tech]] < 95).sum())
        kpis_dict[f"Avg {tech} Avail %"] = f"{avg:.2f}%"
        kpis_dict[f"{tech} Sites <95%"] = n95
        kpis_dict[f"{tech} Sites <90% (Critical)"] = n90
    if has_revenue:
        kpis_dict["Total Revenue (Lakhs)"] = f"₹{rev_lat['REV_LAKH'].sum():.2f}"
        kpis_dict["Zero Revenue Sites"] = int((rev_lat["REV_LAKH"] == 0).sum())
        kpis_dict["Avg Rev/Site (Lakhs)"] = f"₹{rev_lat['REV_LAKH'].mean():.3f}"
    if has_failure and len(fdf):
        kpis_dict["Total Failures"] = len(fdf)
        kpis_dict["Sites with Failures"] = int(fdf["bts_ip_id"].nunique() if "bts_ip_id" in fdf.columns else 0)
        kpis_dict["Total Downtime (Hrs)"] = f"{fdf['down_hours'].sum():,.1f}"
    if len(unmatched_sites): kpis_dict["Unmatched Sites"] = len(unmatched_sites)
    st.table(pd.DataFrame(list(kpis_dict.items()), columns=["KPI", "Value"]))
    if len(ven_matrix):
        st.markdown("---")
        st.subheader("🏭 Vendor Summary")
        st.dataframe(ven_matrix.round(2).reset_index(drop=True),
                     use_container_width=True, hide_index=True)
    st.markdown("---")
    st.subheader("📉 Worst Availability Sites")
    for tech, col in avail_existing.items():
        if col not in df_lat.columns: continue
        n95 = int((df_lat[col] < 95).sum())
        with st.expander(f"📡 {tech} — {n95} sites <95%"):
            cols_s = [c for c in ["BTS IP ID", "BTS Name", "SDCA", "Radio_Vendor", col] if c in df_lat.columns]
            worst = df_lat[df_lat[col].notna()].nsmallest(15, col)[cols_s].reset_index(drop=True).round(2)
            st.dataframe(safe_style(worst, _avail_color, [col]), use_container_width=True, hide_index=True)
    st.markdown("---")
    ec_html = gen_exec_html(df_lat, rev_lat, avail_existing,
                            sdca_sum if len(sdca_sum) else None,
                            sdca_vendor if len(sdca_vendor) else None,  # <-- INSERT THIS LINE
                            ven_matrix if len(ven_matrix) else None,
                            unmatched_sites if len(unmatched_sites) else None,
                            _ssa_name, latest_month, has_revenue)
    _dl_btn(ec_html, f"exec_report_{sel_ssa_code}_{latest_month}.html",
            "⬇️ Download Full Executive HTML Report")

# ══════════════════════════════════════════════════════════════════════════════
# TAB 10 – SDCA DISTRIBUTION DETAILS
# ══════════════════════════════════════════════════════════════════════════════
with tabs[10]:
    st.header("📍 SDCA-wise Network Distribution Details")
    st.caption("Complete SDCA breakdown by technology and vendor · Unknown sites shown separately")

    # Filter out Unknown SDCA for main distribution
    df_known = df_lat[df_lat["SDCA"] != "Unknown"].copy() if "SDCA" in df_lat.columns else df_lat.copy()
    df_unknown = df_lat[df_lat["SDCA"] == "Unknown"].copy() if "SDCA" in df_lat.columns else pd.DataFrame()

    # ── SDCA Distribution Table ─────────────────────────────────────────────
    st.subheader("📊 SDCA-wise Site Distribution")

    if len(df_known) > 0 and "SDCA" in df_known.columns:
        sdca_dist = df_known.groupby("SDCA").agg(
            Total_Sites=("BTS IP ID", "nunique"),
            Sites_2G=("_has2g", "sum"),
            Sites_3G=("_has3g", "sum"),
            Sites_4G=("Has_4G_Physical", "sum"),
            Avg_Avail_2G=("Nw Avail (2G)", "mean") if "Nw Avail (2G)" in df_known.columns else ("BTS IP ID", "count"),
            Avg_Avail_3G=("Nw Avail (3G)", "mean") if "Nw Avail (3G)" in df_known.columns else ("BTS IP ID", "count"),
            Avg_Avail_4G=("Nw Avail (4G TCS)", "mean") if "Nw Avail (4G TCS)" in df_known.columns else (
            "BTS IP ID", "count"),
        ).round(2).reset_index()

        # Vendor-wise breakdown per SDCA
        if "Radio_Vendor" in df_known.columns:
            vendor_dist = df_known.groupby(["SDCA", "Radio_Vendor"])["BTS IP ID"].nunique().reset_index()
            vendor_pivot = vendor_dist.pivot(index="SDCA", columns="Radio_Vendor", values="BTS IP ID").fillna(
                0).reset_index()
            sdca_dist = sdca_dist.merge(vendor_pivot, on="SDCA", how="left")

        # Technology-wise vendor breakdown
        st.markdown("### 🏭 2G BTS Distribution by Vendor")
        if "Vendor_2G_RBC" in df_known.columns or "Radio_Vendor" in df_known.columns:
            vendor_col = "Vendor_2G_RBC" if "Vendor_2G_RBC" in df_known.columns else "Radio_Vendor"
            s2g_dist = df_known[df_known["_has2g"]].groupby(["SDCA", vendor_col])["BTS IP ID"].nunique().reset_index()
            s2g_pivot = s2g_dist.pivot(index="SDCA", columns=vendor_col, values="BTS IP ID").fillna(0).reset_index()
            s2g_pivot.columns = ["SDCA"] + [f"2G_{col}" for col in s2g_pivot.columns[1:]]
            s2g_pivot["2G_Total"] = s2g_pivot.iloc[:, 1:].sum(axis=1)
            st.dataframe(s2g_pivot.sort_values("2G_Total", ascending=False), use_container_width=True, hide_index=True)

        st.markdown("### 📡 3G Node B Distribution by Vendor")
        if "Vendor_3G_RBC" in df_known.columns or "Vendor_3G_str" in df_known.columns:
            vendor_col = "Vendor_3G_RBC" if "Vendor_3G_RBC" in df_known.columns else "Vendor_3G_str"
            s3g_dist = df_known[df_known["_has3g"]].groupby(["SDCA", vendor_col])["BTS IP ID"].nunique().reset_index()
            s3g_pivot = s3g_dist.pivot(index="SDCA", columns=vendor_col, values="BTS IP ID").fillna(0).reset_index()
            s3g_pivot.columns = ["SDCA"] + [f"3G_{col}" for col in s3g_pivot.columns[1:]]
            s3g_pivot["3G_Total"] = s3g_pivot.iloc[:, 1:].sum(axis=1)
            st.dataframe(s3g_pivot.sort_values("3G_Total", ascending=False), use_container_width=True, hide_index=True)

        st.markdown("### 🌐 4G eNode B Distribution")
        if "Vendor_4G_RBC" in df_known.columns or "Vendor_4G" in df_known.columns:
            vendor_col = "Vendor_4G_RBC" if "Vendor_4G_RBC" in df_known.columns else "Vendor_4G"
            s4g_dist = df_known[df_known["Has_4G_Physical"]].groupby(["SDCA", vendor_col])[
                "BTS IP ID"].nunique().reset_index()
            s4g_pivot = s4g_dist.pivot(index="SDCA", columns=vendor_col, values="BTS IP ID").fillna(0).reset_index()
            s4g_pivot.columns = ["SDCA"] + [f"4G_{col}" for col in s4g_pivot.columns[1:]]
            s4g_pivot["4G_Total"] = s4g_pivot.iloc[:, 1:].sum(axis=1)
            st.dataframe(s4g_pivot.sort_values("4G_Total", ascending=False), use_container_width=True, hide_index=True)

        # Summary table
        st.markdown("### 📋 SDCA Summary")
        summary_cols = ["SDCA", "Total_Sites", "Sites_2G", "Sites_3G", "Sites_4G"]
        if "Nokia/NSN" in sdca_dist.columns: summary_cols.extend(["Nokia/NSN", "Nortel", "ZTE", "TCS/Tejas"])
        safe_summary_cols = [c for c in summary_cols if c in sdca_dist.columns]
        st.dataframe(sdca_dist[safe_summary_cols].sort_values("Total_Sites", ascending=False),
                     use_container_width=True, hide_index=True)

        # Towers count (if available in data)
        if "Towers" in df_known.columns:
            towers_by_sdca = df_known.groupby("SDCA")["Towers"].first().reset_index()
            st.markdown("### 🗼 Towers by SDCA")
            st.dataframe(towers_by_sdca.sort_values("Towers", ascending=False),
                         use_container_width=True, hide_index=True)

    # ── Unknown Sites Section ─────────────────────────────────────────────
    st.markdown("---")
    st.subheader("⚠️ Sites with Unknown SDCA (To be removed from database)")

    if len(df_unknown) > 0:
        st.warning(f"**{len(df_unknown)} sites** have Unknown SDCA and should be removed from the database.")

        unknown_details = df_unknown[["BTS IP ID", "BTS Name", "Vendor",
                                      "Nw Avail (2G)", "Nw Avail (3G)", "Nw Avail (4G TCS)",
                                      "Erl Total", "Data GB Total"]].copy()

        if has_revenue:
            # Check if these sites exist in revenue data
            if "BTSIPID" in rev_lat.columns:
                unknown_details["In_Revenue"] = unknown_details["BTS IP ID"].isin(rev_lat["BTSIPID"])

        st.dataframe(unknown_details.round(2), use_container_width=True, hide_index=True)

        # Download button for unknown sites
        unknown_csv = unknown_details.to_csv(index=False)
        st.download_button("⬇️ Download Unknown Sites CSV", unknown_csv,
                           f"unknown_sdca_sites_{latest_month}.csv", "text/csv", key="dl_unknown")
    else:
        st.success("✅ All sites have valid SDCA assignments.")

    st.markdown("---")
    st.caption("Note: Sites with Unknown SDCA are excluded from the main distribution statistics above.")

# ── Footer ─────────────────────────────────────────────────────────────────────
st.markdown("---")
st.caption(
    f"📡 TN Circle Network Intelligence Dashboard v4 Final  |  "
    f"SSA: {_ssa_name} ({sel_ssa_code})  |  "
    f"Month: {latest_month.upper()}  |  "
    f"Vendor decode: RBC TECH codes  |  "
    f"Outage: filtered per technology  |  "
    f"Corr: Revenue ↔ Availability"
)
