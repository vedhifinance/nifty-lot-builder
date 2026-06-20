import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import json, base64, requests
from datetime import date, datetime

st.set_page_config(page_title="Nifty Lot Builder", layout="wide", page_icon="🎯",
                   initial_sidebar_state="collapsed")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Playfair+Display:ital,wght@1,700&family=Inter:wght@300;400;500;600&display=swap');
html,body,[class*="css"]{font-family:'Inter',sans-serif!important}
.brand{font-family:'Playfair Display',Georgia,serif!important;font-style:italic;
       font-size:38px;font-weight:700;color:#1A1A18;letter-spacing:-1px;line-height:1.1}
.brand .hi{color:#1D9E75}
.sub{font-size:11px;color:#999;letter-spacing:0.1em;text-transform:uppercase;margin-top:4px}
.live-badge{display:inline-flex;align-items:center;gap:5px;background:#EAF3DE;
            color:#27500A;font-size:10px;font-weight:600;padding:3px 10px;
            border-radius:20px;letter-spacing:.06em;text-transform:uppercase;margin-top:6px}
.dot{width:6px;height:6px;border-radius:50%;background:#1D9E75;
     display:inline-block;animation:blink 1.5s infinite}
@keyframes blink{0%,100%{opacity:1}50%{opacity:.2}}
</style>
""", unsafe_allow_html=True)

NIFTY50 = [
    "ADANIENT","ADANIPORTS","APOLLOHOSP","ASIANPAINT","AXISBANK",
    "BAJAJ-AUTO","BAJFINANCE","BAJAJFINSV","BEL","BPCL",
    "BHARTIARTL","BRITANNIA","CIPLA","COALINDIA","DIVISLAB",
    "DRREDDY","EICHERMOT","GRASIM","HCLTECH","HDFCBANK",
    "HDFCLIFE","HEROMOTOCO","HINDALCO","HINDUNILVR","ICICIBANK",
    "ITC","INDUSINDBK","INFY","JSWSTEEL","KOTAKBANK",
    "LT","M&M","MARUTI","NTPC","NESTLEIND",
    "ONGC","POWERGRID","RELIANCE","SBILIFE","SHRIRAMFIN",
    "SBIN","SUNPHARMA","TCS","TATACONSUM","TATAMOTORS",
    "TATASTEEL","TECHM","TITAN","ULTRACEMCO","WIPRO",
]

TOTAL_CAPITAL = 500000
DATA_FILE     = "lot_builder_data.json"

def gh_headers():
    return {"Authorization": f"token {st.secrets.get('GITHUB_TOKEN','')}",
            "Accept": "application/vnd.github.v3+json"}

def gh_repo():
    return st.secrets.get("GITHUB_REPO_LB", st.secrets.get("GITHUB_REPO",""))

def load_data():
    try:
        url = f"https://api.github.com/repos/{gh_repo()}/contents/{DATA_FILE}"
        r   = requests.get(url, headers=gh_headers(), timeout=10)
        if r.status_code == 200:
            j    = r.json()
            data = json.loads(base64.b64decode(j["content"]).decode())
            data["_sha"] = j["sha"]
            return data
        return {"trades":[], "sold":[], "_sha":None}
    except:
        return {"trades":[], "sold":[], "_sha":None}

def save_data(data):
    try:
        # Always fetch latest SHA before saving to avoid 409 conflicts
        url = f"https://api.github.com/repos/{gh_repo()}/contents/{DATA_FILE}"
        r_get = requests.get(url, headers=gh_headers(), timeout=10)
        sha = r_get.json()["sha"] if r_get.status_code == 200 else data.pop("_sha", None)
        data.pop("_sha", None)  # remove sha from data before saving
        encoded = base64.b64encode(json.dumps(data, indent=2).encode()).decode()
        payload = {"message":"Update Lot Builder data","content":encoded}
        if sha: payload["sha"] = sha
        r = requests.put(url, headers=gh_headers(), json=payload, timeout=10)
        if r.status_code in [200,201]:
            data["_sha"] = r.json()["content"]["sha"]
            return True
        st.error(f"Save failed: {r.status_code}")
        return False
    except Exception as e:
        st.error(f"Save error: {e}")
        return False

def calc_rsi(close, period=14):
    close = close.dropna()
    close = close[~close.index.duplicated(keep='last')].sort_index()
    delta = close.diff().dropna()
    gain  = delta.clip(lower=0)
    loss  = (-delta).clip(lower=0)
    ag    = gain.ewm(alpha=1/period, adjust=False, min_periods=period).mean()
    al    = loss.ewm(alpha=1/period, adjust=False, min_periods=period).mean()
    val   = float((100-(100/(1+ag/al.replace(0,1e-10)))).iloc[-1])
    return round(val,1) if 1<=val<=99 else None

@st.cache_data(ttl=1800)
def fetch_stock_data(symbol):
    try:
        df  = yf.download(f"{symbol}.NS", period="1y", interval="1d",
                          progress=False, auto_adjust=True)
        if df.empty or len(df)<55: return None
        c   = df["Close"].squeeze().dropna()
        c   = c[~c.index.duplicated(keep='last')].sort_index()
        vol = df["Volume"].squeeze().dropna()
        vol = vol[~vol.index.duplicated(keep='last')].sort_index()
        ltp = float(c.iloc[-1]); prev=float(c.iloc[-2])
        e20 = float(c.ewm(span=20,adjust=False).mean().iloc[-1])
        e50 = float(c.ewm(span=50,adjust=False).mean().iloc[-1])
        e200= float(c.ewm(span=200,adjust=False).mean().iloc[-1])
        rsi = calc_rsi(c)
        tv  = float(vol.iloc[-1])
        av  = float(vol.iloc[-21:-1].mean()) if len(vol)>=21 else float(vol.mean())
        vr  = round(tv/av,2) if av>0 else 0
        above_200 = ltp > e200
        pct_above = round((ltp-e200)/e200*100,1)
        at_20  = abs(ltp-e20)/e20 < 0.02
        at_50  = abs(ltp-e50)/e50 < 0.02
        at_200 = abs(ltp-e200)/e200 < 0.03
        vol_dry= vr < 0.8
        rsi_t1 = rsi is not None and 35<=rsi<=45
        rsi_t2 = rsi is not None and 30<=rsi<35
        rsi_t3 = rsi is not None and rsi<30

        if not above_200:
            signal="⛔ Below EMA 200 — Disqualified"; tranche=None
        elif rsi_t1 and (at_20 or at_50) and vol_dry:
            signal="🟢 T1 Entry — Pullback + RSI cooling + Volume drying"; tranche="T1"
        elif rsi_t1 and (at_20 or at_50):
            signal="🟡 T1 Watch — Pullback zone, await volume drying"; tranche="T1_watch"
        elif rsi_t2 and ltp < min(e20,e50):
            signal="🔵 T2 Entry — Below EMA support, RSI oversold"; tranche="T2"
        elif rsi_t3 and (at_200 or ltp < min(e20,e50)):
            signal="🟣 T3/T4 Entry — Deep oversold, near EMA 200"; tranche="T3"
        else:
            signal="⚪ Monitoring — No entry signal yet"; tranche=None

        return {"ltp":ltp,"chg":ltp-prev,"chgp":(ltp-prev)/prev*100,
                "ema20":round(e20,2),"ema50":round(e50,2),"ema200":round(e200,2),
                "rsi":rsi,"vol_ratio":vr,"above_200":above_200,
                "pct_above_200":pct_above,"signal":signal,"tranche":tranche}
    except: return None

@st.cache_data(ttl=300)
def get_ltp(symbol):
    try:
        df = yf.download(f"{symbol}.NS", period="5d", interval="1d",
                         progress=False, auto_adjust=True)
        if df.empty: return None
        return float(df["Close"].squeeze().dropna().iloc[-1])
    except: return None

# Load data
if "lb_data" not in st.session_state or st.session_state.get("lb_reload", True):
    st.session_state["lb_data"]   = load_data()
    st.session_state["lb_reload"] = False

db     = st.session_state["lb_data"]
trades = db.get("trades", [])
sold_h = db.get("sold", [])

# Header
st.markdown("""
<div style="padding:4px 0 10px">
  <div class="brand">Nifty Lot <span class="hi">Builder</span></div>
  <div class="sub">₹5 Lakh Capital · 3–4 Tranche Strategy · Nifty 50 Stocks</div>
  <div class="live-badge"><span class="dot"></span>&nbsp;Live</div>
</div>
""", unsafe_allow_html=True)

# Capital summary
total_deployed = sum(
    sum(t["qty"]*t["price"] for t in tr["tranches"])
    for tr in trades
)
capital_remaining = TOTAL_CAPITAL - total_deployed
deployed_pct      = round(total_deployed/TOTAL_CAPITAL*100,1)

c1,c2,c3,c4 = st.columns(4)
c1.metric("Total Capital",    f"₹{TOTAL_CAPITAL:,.0f}")
c2.metric("Deployed",         f"₹{total_deployed:,.0f}", f"{deployed_pct}%")
c3.metric("Available",        f"₹{capital_remaining:,.0f}")
c4.metric("Open positions",   len(trades))

st.divider()

# Navigation
nav = st.selectbox("", ["📡 Signal Scanner","📂 Open Positions","💸 Sell Stock","📋 Trade History"],
                   key="nav_sel", label_visibility="collapsed")

# ══════════════════════════════════════════════════════
# SIGNAL SCANNER
# ══════════════════════════════════════════════════════
if nav == "📡 Signal Scanner":
    st.markdown("#### 📡 Tranche Entry Signal Scanner")
    st.caption("Shows T1/T2/T3/T4 entry signals for all Nifty 50 stocks based on EMA + RSI + Volume strategy")

    sc1,sc2,sc3 = st.columns([2,1,1])
    with sc1:
        scan_stocks = st.multiselect("Select stocks to scan (or leave empty for all 50)",
                                      NIFTY50, key="scan_sel")
    with sc2:
        show_all   = st.checkbox("Show all (including no signal)", key="show_all_chk")
    with sc3:
        st.markdown("<br>", unsafe_allow_html=True)
        run_scan   = st.button("▶ Run Scanner", type="primary", use_container_width=True, key="run_scan_btn")

    if run_scan:
        stocks_to_scan = scan_stocks if scan_stocks else NIFTY50
        results = []
        prog = st.progress(0, text="Scanning…")
        for i,sym in enumerate(stocks_to_scan):
            prog.progress((i+1)/len(stocks_to_scan), text=f"Scanning {sym}…")
            d = fetch_stock_data(sym)
            if d:
                if not show_all and d["tranche"] is None: continue
                results.append({
                    "Stock":sym, "LTP ₹":d["ltp"],
                    "Chg%":round(d["chgp"],2),
                    "RSI":d["rsi"],"EMA 20":d["ema20"],
                    "EMA 50":d["ema50"],"EMA 200":d["ema200"],
                    "% above 200":d["pct_above_200"],
                    "Vol Ratio":d["vol_ratio"],
                    "Signal":d["signal"],
                    "_tranche":d["tranche"],
                })
        prog.empty()

        failed = [s for s in stocks_to_scan if s not in [r["Stock"] for r in results] and s not in [r["Stock"] for r in results]]
        # Recalculate failed stocks
        scanned_syms = [r["Stock"] for r in results]
        failed_syms  = [s for s in stocks_to_scan if s not in scanned_syms]
        if failed_syms:
            st.warning(f"⚠ Could not fetch data for: {', '.join(failed_syms)} — Yahoo Finance temporarily unavailable for these stocks. Try again later.")

        if not results:
            st.info("No entry signals found. Try 'Show all' to see all stocks.")
        else:
            st.success(f"Found {len(results)} stocks with signals")
            cols = ["Stock","LTP ₹","Chg%","RSI","EMA 20","EMA 50","EMA 200","% above 200","Vol Ratio","Signal"]

            def sig_style(val):
                if "T1 Entry" in str(val):   return "background:#D6F5E3;color:#1A5C35;font-weight:600"
                if "T1 Watch" in str(val):   return "background:#FFF9DB;color:#7A5C00;font-weight:600"
                if "T2 Entry" in str(val):   return "background:#DBF0FF;color:#0C447C;font-weight:600"
                if "T3/T4" in str(val):      return "background:#EDE0FF;color:#4A0C7C;font-weight:600"
                if "Disqualified" in str(val): return "background:#FDDCDC;color:#7A1A1A;font-weight:600"
                return "color:#888"

            hdr = "".join(f'<th style="background:#1A1A18;color:white;font-size:11px;font-weight:600;padding:9px 12px;text-align:left;white-space:nowrap;border-right:0.5px solid #444">{c}</th>' for c in cols)
            bdy = ""
            for i,r in enumerate(results):
                bg = "#fff" if i%2==0 else "#FAFAF8"
                bdy += f'<tr style="background:{bg}">'
                for col in cols:
                    v = r[col]
                    s = "padding:9px 12px;font-size:13px;border-right:0.5px solid #E0DED8;border-bottom:0.5px solid #E0DED8;white-space:nowrap;"
                    if col=="Stock": s+="background:#1A1A18;color:white;font-weight:600;"
                    elif col=="Chg%": s+=f"color:{'#1D9E75' if v>=0 else '#E24B4A'};font-weight:500;"
                    elif col=="Signal": s+=sig_style(v)
                    elif col=="RSI" and v is not None:
                        if v<30: s+="color:#185FA5;font-weight:600;"
                        elif v<40: s+="color:#1D9E75;font-weight:600;"
                        elif v>70: s+="color:#E24B4A;font-weight:600;"
                    fv = f"₹{v:.2f}" if col in ["LTP ₹","EMA 20","EMA 50","EMA 200"] else \
                         f"{v:+.2f}%" if col=="Chg%" else \
                         f"{v:.1f}" if col=="RSI" and v else \
                         f"{v:.2f}x" if col=="Vol Ratio" else \
                         f"{v:+.1f}%" if col=="% above 200" else str(v)
                    bdy += f'<td style="{s}">{fv}</td>'
                bdy += "</tr>"

            st.markdown(f'<div style="overflow-x:auto;border:0.5px solid #E0DED8;border-radius:8px;overflow:hidden"><table style="width:100%;border-collapse:collapse;font-family:system-ui,sans-serif"><thead><tr>{hdr}</tr></thead><tbody>{bdy}</tbody></table></div>', unsafe_allow_html=True)
            st.caption("T1=Pullback entry · T2=Below EMA support · T3/T4=Near EMA 200 · Not financial advice")

    # Strategy explanation
    with st.expander("📖 Strategy Rules — click to read"):
        st.markdown("""
**Pre-requisite:** Stock must be above EMA 200 — non-negotiable. Below EMA 200 = disqualified.

| Tranche | Trigger | Size | RSI | Volume |
|---|---|---|---|---|
| **T1** | Pullback to EMA 20 or EMA 50 | 25% of target qty | 35–45 | Drying up (<0.8x avg) |
| **T2** | Breaks below EMA 20/50 support | 25% of target qty | 30–35 | Any |
| **T3** | Near EMA 200 or deep oversold | 25% of target qty | <30 | Any |
| **T4** | Right on EMA 200 — last defense | 25% of target qty | <30 | Any |

**Stop Loss:** Close below EMA 200 on any candle → exit full position immediately.

**Exit:** Price recovers to target % above your average cost → sell full position.
        """)

# ══════════════════════════════════════════════════════
# OPEN POSITIONS
# ══════════════════════════════════════════════════════
elif nav == "📂 Open Positions":
    st.markdown("#### 📂 Open Positions")

    # Add tranche form
    st.markdown("**➕ Add a tranche buy**")
    with st.form("add_tranche_form", clear_on_submit=True):
        f1,f2,f3,f4,f5 = st.columns(5)
        with f1: t_sym    = st.selectbox("Stock", NIFTY50, key="t_sym")
        with f2: t_tranche= st.selectbox("Tranche", ["T1","T2","T3","T4"], key="t_tr")
        with f3: t_qty    = st.number_input("Quantity", min_value=1, step=1, key="t_qty")
        with f4: t_price  = st.number_input("Buy price (₹)", min_value=0.01, step=0.05, format="%.2f", key="t_bp")
        with f5: t_date   = st.date_input("Buy date", key="t_bd")
        t_target = st.number_input("Target % (profit target)", min_value=0.1, step=0.5,
                                    value=8.0, format="%.1f", key="t_tgt",
                                    help="e.g. 8 means sell when +8% above avg cost")
        t_notes  = st.text_input("Notes (optional)", key="t_notes")

        if st.form_submit_button("➕ Add tranche", type="primary", use_container_width=True):
            if t_qty > 0 and t_price > 0:
                existing = next((tr for tr in trades if tr["symbol"]==t_sym), None)
                new_t = {"tranche":t_tranche,"qty":int(t_qty),"price":float(t_price),
                         "date":str(t_date),"notes":t_notes}
                if existing:
                    existing["tranches"].append(new_t)
                    existing["target_pct"] = float(t_target)
                else:
                    trades.append({"id":len(trades)+1,"symbol":t_sym,
                                   "tranches":[new_t],"target_pct":float(t_target)})
                db["trades"] = trades
                if save_data(db):
                    st.success(f"✓ {t_tranche} added: {int(t_qty)} {t_sym} @ ₹{t_price:.2f}")
                    st.session_state["lb_reload"]=True
                    st.session_state["lb_data"] = load_data()
                    st.rerun()

    st.divider()

    if not trades:
        st.info("No open positions. Use the scanner to find entry signals, then add tranches above.")
    else:
        for tr in trades:
            sym       = tr["symbol"]
            tranches  = tr["tranches"]
            target_pct= tr.get("target_pct", 8.0)
            total_qty = sum(t["qty"] for t in tranches)
            avg_cost  = sum(t["qty"]*t["price"] for t in tranches)/total_qty if total_qty else 0
            invested  = round(avg_cost*total_qty,2)
            ltp       = get_ltp(sym) or avg_cost
            curr_val  = round(ltp*total_qty,2)
            pnl       = round(curr_val-invested,2)
            pnl_pct   = round(pnl/invested*100,2) if invested else 0
            target_px = round(avg_cost*(1+target_pct/100),2)
            sl_data   = fetch_stock_data(sym)
            ema200    = sl_data["ema200"] if sl_data else 0
            sl_breach = ltp < ema200 if ema200 else False

            pnl_col = "#1D9E75" if pnl>=0 else "#E24B4A"
            border_col = "#E24B4A" if sl_breach else "#1D9E75"

            st.markdown(f"""
            <div style="background:#fff;border:0.5px solid #E0DED8;border-radius:10px;
                        padding:14px 18px;margin-bottom:10px;border-left:4px solid {border_col}">
              <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px">
                <div style="display:flex;align-items:center;gap:10px">
                  <span style="background:#1A1A18;color:white;font-weight:600;font-size:14px;
                               padding:4px 12px;border-radius:6px">{sym}</span>
                  <span style="font-size:12px;color:#888">{len(tranches)} tranches · {total_qty:,} shares</span>
                  {f'<span style="background:#FDDCDC;color:#7A1A1A;font-size:11px;font-weight:600;padding:2px 8px;border-radius:10px">⚠ BELOW EMA 200 — Consider Exit</span>' if sl_breach else ''}
                </div>
                <div style="text-align:right">
                  <span style="font-size:18px;font-weight:600">₹{ltp:.2f}</span>
                  <span style="font-size:12px;color:{pnl_col};margin-left:8px">₹{pnl:+,.0f} ({pnl_pct:+.1f}%)</span>
                </div>
              </div>
            </div>
            """, unsafe_allow_html=True)

            m1,m2,m3,m4,m5,m6 = st.columns(6)
            m1.metric("Avg cost",     f"₹{avg_cost:.2f}")
            m2.metric("Invested",     f"₹{invested:,.0f}")
            m3.metric("Curr value",   f"₹{curr_val:,.0f}")
            m4.metric("Unreal P&L",   f"₹{pnl:+,.0f}", f"{pnl_pct:+.1f}%")
            m5.metric("Target",       f"₹{target_px:.2f}", f"+{target_pct}%")
            m6.metric("EMA 200 SL",   f"₹{ema200:.0f}" if ema200 else "—",
                      "⚠ Breached!" if sl_breach else "Safe ✓")

            # Tranche breakdown
            with st.expander(f"📋 {sym} — tranche details"):
                t_rows = [{"Tranche":t["tranche"],"Date":t["date"],"Qty":t["qty"],
                           "Price ₹":f"₹{t['price']:.2f}",
                           "Value ₹":f"₹{t['qty']*t['price']:,.0f}",
                           "Notes":t.get("notes","—")} for t in tranches]
                st.dataframe(pd.DataFrame(t_rows), use_container_width=True, hide_index=True)

            st.divider()

# ══════════════════════════════════════════════════════
# SELL STOCK
# ══════════════════════════════════════════════════════
elif nav == "💸 Sell Stock":
    st.markdown("#### 💸 Sell Stock")

    open_syms = [tr["symbol"] for tr in trades]
    if not open_syms:
        st.info("No open positions to sell.")
    else:
        with st.form("sell_lb_form", clear_on_submit=True):
            s1,s2,s3,s4 = st.columns(4)
            with s1: s_sym    = st.selectbox("Stock", open_syms, key="s_sym")
            with s2: s_qty    = st.number_input("Qty to sell", min_value=1, step=1, key="s_qty")
            with s3: s_price  = st.number_input("Sell price (₹)", min_value=0.01,
                                                 step=0.05, format="%.2f", key="s_price")
            with s4: s_date   = st.date_input("Sell date", key="s_date")

            s5,s6 = st.columns(2)
            with s5: s_brok   = st.number_input("Total brokerage (₹)", min_value=0.0,
                                                  step=1.0, format="%.2f", key="s_brok",
                                                  help="Total brokerage for buy+sell orders")
            with s6: s_notes  = st.text_input("Notes (optional)", key="s_notes")
            s_reason = st.selectbox("Reason for selling", [
                "Target reached","Stop loss — below EMA 200","Partial profit booking","Other"
            ], key="s_reason")

            if st.form_submit_button("💸 Confirm sell", type="primary", use_container_width=True):
                pos = next((tr for tr in trades if tr["symbol"]==s_sym), None)
                if pos:
                    total_qty = sum(t["qty"] for t in pos["tranches"])
                    avg_cost  = sum(t["qty"]*t["price"] for t in pos["tranches"])/total_qty
                    if int(s_qty) > total_qty:
                        st.error(f"You only hold {total_qty} shares of {s_sym}.")
                    else:
                        invested  = round(avg_cost*int(s_qty),2)
                        proceeds  = round(float(s_price)*int(s_qty),2)
                        brok      = float(s_brok)
                        gross_pnl = round(proceeds-invested,2)
                        net_pnl   = round(gross_pnl-brok,2)
                        net_pct   = round(net_pnl/invested*100,2) if invested else 0
                        first_date= min(t["date"] for t in pos["tranches"])
                        hold_days = (date.fromisoformat(str(s_date))-date.fromisoformat(first_date)).days

                        sold_h.append({
                            "id":len(sold_h)+1,"symbol":s_sym,
                            "qty":int(s_qty),"avg_cost":round(avg_cost,2),
                            "sell_price":float(s_price),
                            "buy_date":first_date,"sell_date":str(s_date),
                            "hold_days":hold_days,"tranches":len(pos["tranches"]),
                            "invested":invested,"proceeds":proceeds,
                            "brokerage":brok,"gross_pnl":gross_pnl,
                            "net_pnl":net_pnl,"net_pct":net_pct,
                            "reason":s_reason,"notes":s_notes,
                        })

                        if int(s_qty) == total_qty:
                            db["trades"] = [tr for tr in trades if tr["symbol"]!=s_sym]
                        else:
                            rem = int(s_qty)
                            for t in pos["tranches"]:
                                if rem<=0: break
                                ded=min(t["qty"],rem); t["qty"]-=ded; rem-=ded
                            pos["tranches"] = [t for t in pos["tranches"] if t["qty"]>0]

                        db["sold"] = sold_h
                        if save_data(db):
                            emoji = "🟢" if net_pnl>=0 else "🔴"
                            st.success(f"""
{emoji} Sold {int(s_qty)} {s_sym} @ ₹{s_price:.2f}
Gross P&L: ₹{gross_pnl:+,.0f} | Brokerage: ₹{brok:,.0f} | **Net P&L: ₹{net_pnl:+,.0f} ({net_pct:+.1f}%)**
                            """)
                            st.session_state["lb_reload"]=True; st.rerun()

# ══════════════════════════════════════════════════════
# TRADE HISTORY
# ══════════════════════════════════════════════════════
elif nav == "📋 Trade History":
    st.markdown("#### 📋 Trade History")

    if not sold_h:
        st.info("No closed trades yet.")
    else:
        rows = [{"#":s["id"],"Stock":s["symbol"],"Qty":s["qty"],
                 "Avg Cost ₹":f"₹{s['avg_cost']:.2f}",
                 "Sell Price ₹":f"₹{s['sell_price']:.2f}",
                 "Tranches":s["tranches"],
                 "Hold Days":s["hold_days"],
                 "Invested ₹":f"₹{s['invested']:,.0f}",
                 "Proceeds ₹":f"₹{s['proceeds']:,.0f}",
                 "Brokerage ₹":f"₹{s['brokerage']:,.0f}",
                 "Gross P&L":f"₹{s['gross_pnl']:+,.0f}",
                 "Net P&L":f"₹{s['net_pnl']:+,.0f}",
                 "Net %":f"{s['net_pct']:+.1f}%",
                 "Reason":s["reason"],
                 "Sell Date":s["sell_date"]} for s in sorted(sold_h,key=lambda x:x["sell_date"],reverse=True)]

        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

        # Summary
        total_net  = sum(s["net_pnl"] for s in sold_h)
        total_brok = sum(s["brokerage"] for s in sold_h)
        winners    = [s for s in sold_h if s["net_pnl"]>0]
        best       = max(sold_h, key=lambda x:x["net_pnl"])
        worst      = min(sold_h, key=lambda x:x["net_pnl"])

        st.divider()
        r1,r2,r3,r4,r5,r6 = st.columns(6)
        r1.metric("Total trades",    len(sold_h))
        r2.metric("Total net P&L",   f"₹{total_net:+,.0f}")
        r3.metric("Win rate",        f"{len(winners)/len(sold_h)*100:.0f}%")
        r4.metric("Total brokerage", f"₹{total_brok:,.0f}")
        r5.metric("Best trade",      f"₹{best['net_pnl']:+,.0f}", best["symbol"])
        r6.metric("Worst trade",     f"₹{worst['net_pnl']:+,.0f}", worst["symbol"])

        st.download_button("⬇ Download history",
                           pd.DataFrame(rows).to_csv(index=False),
                           "lot_builder_history.csv","text/csv")
