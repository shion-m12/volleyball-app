import streamlit as st
import pandas as pd
from streamlit_image_coordinates import streamlit_image_coordinates
from PIL import Image, ImageDraw
import datetime
import re
import os
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import matplotlib.pyplot as plt
import matplotlib.patches as patches

# --- 設定 ---
st.set_page_config(layout="wide", page_title="Volleyball Analyst Pro v45")

# 定数・設定
ZONE_COLORS = {
    "レフト(L)": ("red", "Left"), "センター(C)": ("green", "Center"), "ライト(R)": ("blue", "Right"),
    "ツーアタック": ("gold", "Dump"), "レフトバック(LB)": ("orange", "Back-L"),
    "センターバック(CB)": ("purple", "Back-C"), "ライトバック(RB)": ("cyan", "Back-R"), "なし": ("gray", "-")
}
PASS_ORDER = ["Aパス", "Bパス", "Cパス", "その他", "相手サーブミス", "失敗 (エース)"]
ZONE_ORDER = ["レフト(L)", "センター(C)", "ライト(R)", "ツーアタック", "レフトバック(LB)", "センターバック(CB)", "ライトバック(RB)", "なし"]
BLOCK_OPTIONS = ["0", "1", "1.5", "2", "2.5", "3"]

# --- Google API ---
def get_gcp_creds():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    try:
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
        return ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    except: st.stop()

def connect_to_gsheet():
    creds = get_gcp_creds()
    client = gspread.authorize(creds)
    return client.open_by_key("14o1wNqQIrJPy9IAuQ7PSCwP6NyA4O5dZrn_FmFoSqLQ")

# --- データ管理 ---
def load_players():
    try:
        ws = connect_to_gsheet().worksheet("players")
        data = ws.get_all_records()
        if not data: return {}
        db = {}
        for r in data:
            t, p, pos = str(r["Team"]), str(r["PlayerKey"]), str(r["Position"])
            if t not in db: db[t] = {}
            db[t][p] = pos
        return db
    except: return {}

def save_players(db):
    ws = connect_to_gsheet().worksheet("players")
    rows = [["Team", "PlayerKey", "Position"]]
    for t, ms in db.items():
        for p, pos in ms.items(): rows.append([t, p, pos])
    ws.clear(); ws.update(rows)

def save_match_data(df):
    try: ws = connect_to_gsheet().worksheet("history")
    except: ws = connect_to_gsheet().add_worksheet("history", 1000, 20)
    data = df.astype(str).values.tolist()
    if not ws.get_all_values(): ws.append_row(df.columns.tolist())
    ws.append_rows(data)

def load_match_history():
    try:
        ws = connect_to_gsheet().worksheet("history")
        data = ws.get_all_values()
        if len(data) < 2: return pd.DataFrame()
        return pd.DataFrame(data[1:], columns=data[0])
    except: return pd.DataFrame()

def sort_players(plist):
    return sorted(plist, key=lambda x: int(re.search(r'#(\d+)', x).group(1)) if re.search(r'#(\d+)', x) else 999)

# コート画像生成 (入力用)
def get_input_court_img():
    if os.path.exists("court.png"): return Image.open("court.png")
    img = Image.new('RGB', (500, 500), '#FFCC99')
    draw = ImageDraw.Draw(img)
    draw.rectangle([0,0,499,499], outline='white', width=5)
    draw.line([0,250,500,250], fill='white', width=3)
    draw.line([0,170,500,170], fill='white', width=2)
    draw.line([0,330,500,330], fill='white', width=2)
    img.save("court.png")
    return img

# 散布図用コート描画 (Matplotlib)
def plot_court_background(ax):
    ax.set_xlim(0, 500); ax.set_ylim(500, 0)
    ax.set_aspect('equal')
    # コート背景
    rect = patches.Rectangle((0, 0), 500, 500, linewidth=2, edgecolor='black', facecolor='#FFCC99')
    ax.add_patch(rect)
    # ライン
    ax.plot([0, 500], [250, 250], color='white', linewidth=3) # センター
    ax.plot([0, 500], [170, 170], color='white', linewidth=2) # アタックライン
    ax.plot([0, 500], [330, 330], color='white', linewidth=2)
    ax.axis('off')

# --- ステート ---
if 'players_db' not in st.session_state: st.session_state.players_db = load_players()
if 'match_data' not in st.session_state: st.session_state.match_data = []
if 'my_order' not in st.session_state: st.session_state.my_order = []
if 'game_state' not in st.session_state: st.session_state.game_state = {"my_score": 0, "op_score": 0, "serve_rights": "My Team", "my_rot": 1, "op_rot": 1}
if 'temp_coords' not in st.session_state: st.session_state.temp_coords = None
if 'my_libero' not in st.session_state: st.session_state.my_libero = "なし"

# --- ルールロジック ---
def rotate(team):
    cur = st.session_state.game_state[f"{team}_rot"]
    st.session_state.game_state[f"{team}_rot"] = cur + 1 if cur < 6 else 1

def add_score(side):
    gs = st.session_state.game_state
    if side == "my":
        gs["my_score"] += 1
        if gs["serve_rights"] == "Opponent":
            rotate("my")
            gs["serve_rights"] = "My Team"
    else:
        gs["op_score"] += 1
        if gs["serve_rights"] == "My Team":
            rotate("op")
            gs["serve_rights"] = "Opponent"

def get_pos(order, rot):
    if len(order)<6: return {}
    idx = rot - 1
    return {
        "FL": order[(3+idx)%6], "FC": order[(2+idx)%6], "FR": order[(1+idx)%6],
        "BL": order[(4+idx)%6], "BC": order[(5+idx)%6], "BR": order[(0+idx)%6]
    }

# ==========================================
#  UI サイドバー
# ==========================================
with st.sidebar:
    st.title("🏐 Analyst Pro v45")
    app_mode = st.radio("機能メニュー", [
        "📊 試合入力", 
        "🎓 研究用分析", 
        "📈 配給チャート", 
        "👤 チーム管理", 
        "📝 履歴データ"
    ])
    st.markdown("---")
    
    # チーム選択
    teams = list(st.session_state.players_db.keys())
    if teams:
        my_tm = st.selectbox("自チーム", teams, index=0)
        op_tm = st.selectbox("相手チーム", [t for t in teams if t!=my_tm], index=0) if len(teams)>1 else "Guest"
    else: my_tm="MyTeam"; op_tm="Guest"

    # データ操作
    if app_mode == "📊 試合入力":
        st.markdown("### 💾 データ操作")
        if st.session_state.match_data:
            df_now = pd.DataFrame(st.session_state.match_data)
            csv = df_now.to_csv(index=False).encode('utf-8')
            st.download_button("📥 入力中データを保存(CSV)", csv, f"backup_{datetime.datetime.now().strftime('%H%M')}.csv", "text/csv")
        
        if st.button("🏁 試合終了 (クラウド保存)", type="primary"):
            if st.session_state.match_data:
                save_match_data(pd.DataFrame(st.session_state.match_data))
                st.toast("保存完了！")
            st.session_state.game_state = {"my_score": 0, "op_score": 0, "serve_rights": "My Team", "my_rot": 1, "op_rot": 1}
            st.session_state.match_data = []
            st.session_state.my_order = []
            st.rerun()

# ==========================================
#  UI メインコンテンツ
# ==========================================

# --- 1. 試合入力 (v44仕様) ---
if app_mode == "📊 試合入力":
    
    # A. スタメン登録
    if not st.session_state.my_order:
        st.header("🏁 スターティングメンバー登録")
        mp = sort_players(list(st.session_state.players_db[my_tm].keys())) if my_tm in st.session_state.players_db else []
        op = sort_players(list(st.session_state.players_db[op_tm].keys())) if op_tm in st.session_state.players_db else []
        
        c_my_b, c_my_f, c_net, c_op_f, c_op_b = st.columns([1.5, 1.5, 0.2, 1.5, 1.5])
        with c_net: st.markdown("<div style='height:300px; border-left:4px double #333; margin-left:50%;'></div>", unsafe_allow_html=True)

        with c_my_f:
            st.caption(f"{my_tm} 前衛")
            m4 = st.selectbox("前・左 (FL)", mp, index=3 if len(mp)>3 else 0)
            m3 = st.selectbox("前・中 (FC)", mp, index=2 if len(mp)>2 else 0)
            m2 = st.selectbox("前・右 (FR)", mp, index=1 if len(mp)>1 else 0)
        with c_my_b:
            st.caption("後衛")
            m5 = st.selectbox("後・左 (BL)", mp, index=4 if len(mp)>4 else 0)
            m6 = st.selectbox("後・中 (BC)", mp, index=5 if len(mp)>5 else 0)
            m1 = st.selectbox("後・右 (BR/Srv)", mp, index=0)

        st.markdown("---")
        ml = st.selectbox("リベロ (自)", ["なし"]+mp)
        first = st.radio("First Serve", [my_tm, op_tm], horizontal=True)
        
        if st.button("試合開始 🚀", type="primary"):
            st.session_state.my_order = [m1, m2, m3, m4, m5, m6]
            st.session_state.op_order = ["Op1","Op2","Op3","Op4","Op5","Op6"] # 相手は簡易
            st.session_state.my_libero = ml
            st.session_state.game_state["serve_rights"] = "My Team" if first == my_tm else "Opponent"
            st.rerun()

    # B. 試合中画面
    else:
        gs = st.session_state.game_state
        my_p = get_pos(st.session_state.my_order, gs['my_rot'])
        s_my = "🏐 SERVER" if gs['serve_rights']=="My Team" else ""
        s_op = "SERVER 🏐" if gs['serve_rights']=="Opponent" else ""
        
        # スコアボード
        st.markdown(f"""
        <div style="background:#262730; color:white; padding:10px; border-radius:10px; text-align:center; margin-bottom:10px;">
            <div style="font-size:2.5em; font-weight:bold;">
                <span style="color:#4da6ff">{gs['my_score']}</span> - <span style="color:#ff4b4b">{gs['op_score']}</span>
            </div>
            <div style="display:flex; justify-content:space-between; font-weight:bold;">
                <div style="color:#4da6ff;">{my_tm} {s_my}</div>
                <div style="color:#ff4b4b;">{op_tm} {s_op}</div>
            </div>
        </div>
        """, unsafe_allow_html=True)

        # ビジュアルコート図
        st.markdown(f"""
        <style>
            .c-container {{ display: grid; grid-template-columns: 1fr 1fr 0.1fr 1fr 1fr; gap:3px; margin-bottom:10px; text-align:center; font-size:0.8em; }}
            .c-cell {{ padding:5px; border-radius:4px; border:1px solid #555; }}
            .my-front {{ background: #d1e7dd; color: #0f5132; border: 2px solid #198754; }}
            .my-back {{ background: #f8f9fa; color: #333; }}
            .net {{ background: #fff; width:100%; }}
        </style>
        <div class="c-container">
            <div class="c-cell my-back">BL: {my_p.get('BL','?')}</div>
            <div class="c-cell my-front">FL: {my_p.get('FL','?')}</div>
            <div class="net"></div><div class="c-cell">Op</div><div class="c-cell">Op</div>

            <div class="c-cell my-back">BC: {my_p.get('BC','?')}</div>
            <div class="c-cell my-front">FC: {my_p.get('FC','?')}</div>
            <div class="net"></div><div class="c-cell">Op</div><div class="c-cell">Op</div>

            <div class="c-cell my-back" style="border:2px solid gold;">BR: {my_p.get('BR','?')}</div>
            <div class="c-cell my-front">FR: {my_p.get('FR','?')}</div>
            <div class="net"></div><div class="c-cell">Op</div><div class="c-cell">Op</div>
        </div>
        """, unsafe_allow_html=True)

        # 入力エリア
        c_in, c_ctrl = st.columns([1.8, 1])
        with c_in:
            st.subheader("🏐 プレー入力")
            active = list(st.session_state.my_order)
            if st.session_state.my_libero != "なし": active.append(st.session_state.my_libero)
            active_sorted = ["なし"] + sort_players(active)
            
            c1, c2 = st.columns(2)
            pas = c1.selectbox("1. Reception", PASS_ORDER)
            sett = c2.selectbox("2. Setter", active_sorted)
            
            c3, c4 = st.columns(2)
            zone = c3.selectbox("3. Zone", ZONE_ORDER)
            def_h = active_sorted.index(sett) if zone=="ツーアタック" and sett in active_sorted else 0
            hit = c4.selectbox("4. Hitter", active_sorted, index=def_h)
            
            blk = st.select_slider("5. Opponent Block", BLOCK_OPTIONS, value="2")
            
            st.caption("6. Toss Origin (Click!)")
            coords = streamlit_image_coordinates(get_input_court_img(), width=400, key="click")
            if coords: st.session_state.temp_coords = coords
            if st.session_state.temp_coords: st.success("📍 座標OK")
            
            st.write("7. Result")
            c_r1, c_r2, c_r3 = st.columns(3)
            res = None
            if c_r1.button("🔥 決定 (Kill)", type="primary", use_container_width=True): res = "得点 (Kill)"
            if c_r2.button("🔄 継続", use_container_width=True): res = "継続"
            if c_r3.button("💀 失点/被ブロ", use_container_width=True): res = "失点"

            if res:
                if not st.session_state.temp_coords:
                    st.error("コート位置を指定してください")
                else:
                    rec = {
                        "Time": datetime.datetime.now().strftime("%H:%M:%S"),
                        "MyScore": gs['my_score'], "OpScore": gs['op_score'], "Rot": gs['my_rot'],
                        "Pass": pas, "Setter": sett, "Zone": zone, "Hitter": hit, "Block": blk, "Result": res,
                        "X": st.session_state.temp_coords["x"], "Y": st.session_state.temp_coords["y"]
                    }
                    st.session_state.match_data.append(rec)
                    if res == "得点 (Kill)": add_score("my"); st.toast("Nice Kill!")
                    elif res == "失点": add_score("op"); st.toast("Don't mind...")
                    elif pas == "失敗 (エース)": add_score("op"); st.toast("Ace...")
                    st.session_state.temp_coords = None
                    st.rerun()

        with c_ctrl:
            with st.expander("⚙️ 修正・交代", expanded=True):
                if st.button("ローテ回す"): rotate("my"); st.rerun()
                if st.button("点数修正: 自+1"): add_score("my"); st.rerun()
                if st.button("点数修正: 敵+1"): add_score("op"); st.rerun()
                
                st.write("**交代**")
                pos_idx = st.selectbox("Out", ["FL(4)","FC(3)","FR(2)","BL(5)","BC(6)","BR(1)"])
                idx_map = {"BR(1)":0, "FR(2)":1, "FC(3)":2, "FL(4)":3, "BL(5)":4, "BC(6)":5}
                bench = [p for p in sort_players(list(st.session_state.players_db[my_tm].keys())) if p not in st.session_state.my_order]
                sub = st.selectbox("In", bench) if bench else None
                if st.button("交代実行") and sub:
                    st.session_state.my_order[idx_map[pos_idx]] = sub
                    st.rerun()
            
            if st.session_state.match_data:
                if st.button("Undo"): st.session_state.match_data.pop(); st.rerun()
                st.dataframe(pd.DataFrame(st.session_state.match_data)[["Pass","Zone","Result"]].iloc[::-1], height=200, hide_index=True)

# --- 2. 研究用分析 (v43機能) ---
elif app_mode == "🎓 研究用分析":
    st.header("🎓 トス配給傾向の研究分析")
    
    # データ統合
    df_h = load_match_history()
    df_s = pd.DataFrame(st.session_state.match_data)
    df = pd.concat([df_h, df_s], ignore_index=True)
    
    if df.empty:
        st.info("データがありません")
    else:
        # 型変換
        df["Block"] = pd.to_numeric(df["Block"], errors='coerce')
        df["Rot"] = pd.to_numeric(df["Rot"], errors='coerce')
        
        # チームフィルタ
        if "Team" not in df.columns: df["Team"] = my_tm # カラムがない場合の補完
        
        # セッター位置の定義
        st.write("##### 条件設定")
        setter_front_rot = st.multiselect("セッター前衛のローテ", [1,2,3,4,5,6], default=[4,5,6])
        df["SetterPos"] = df["Rot"].apply(lambda x: "前衛 (攻撃2枚)" if x in setter_front_rot else "後衛 (攻撃3枚)")
        
        t1, t2, t3 = st.tabs(["セッター前衛", "セッター後衛", "Cパス分析"])
        
        def analyze_tab(data):
            if data.empty: st.write("データなし"); return
            st.markdown("**配給率 (%)**")
            piv = pd.crosstab(data["Pass"], data["Zone"], normalize='index') * 100
            st.dataframe(piv.style.format("{:.1f}%").background_gradient(cmap="Oranges", axis=1))
            
            st.markdown("**ブロック枚数 & 数的優位率**")
            data["Advantage"] = data["Block"] <= 1.5
            adv = data.groupby("Zone")["Advantage"].mean() * 100
            st.bar_chart(adv)
            st.caption("※ 縦軸: 相手ブロックが1.5枚以下だった割合(%)")

        with t1: analyze_tab(df[df["SetterPos"]=="前衛 (攻撃2枚)"])
        with t2: analyze_tab(df[df["SetterPos"]=="後衛 (攻撃3枚)"])
        with t3:
            st.subheader("⚠️ Cパス時の傾向")
            df_c = df[df["Pass"]=="Cパス"]
            if not df_c.empty:
                c1, c2 = st.columns(2)
                with c1:
                    st.write("配給先")
                    st.dataframe(df_c["Zone"].value_counts())
                with c2:
                    avg_blk = df_c["Block"].mean()
                    st.metric("平均被ブロック枚数", f"{avg_blk:.2f}枚")
            else: st.info("データなし")

# --- 3. 配給チャート (v42散布図) ---
elif app_mode == "📈 配給チャート":
    st.header("📈 トス配給散布図")
    
    df_h = load_match_history()
    df_s = pd.DataFrame(st.session_state.match_data)
    df = pd.concat([df_h, df_s], ignore_index=True)
    
    if not df.empty and "X" in df.columns:
        df["X"] = pd.to_numeric(df["X"], errors='coerce')
        df["Y"] = pd.to_numeric(df["Y"], errors='coerce')
        df = df.dropna(subset=["X", "Y"])
        
        sel_setter = st.selectbox("セッター絞り込み", ["全員"] + sorted(list(df["Setter"].unique())))
        if sel_setter != "全員": df = df[df["Setter"]==sel_setter]
        
        fig, ax = plt.subplots(figsize=(8, 5))
        plot_court_background(ax)
        
        for z in ZONE_ORDER:
            d = df[df["Zone"]==z]
            if not d.empty:
                col = ZONE_COLORS.get(z, ("gray",""))[0]
                ax.scatter(d["X"], d["Y"], label=z, color=col, s=100, edgecolors="white", alpha=0.8)
        
        ax.legend(bbox_to_anchor=(1.05, 1), loc='upper left')
        st.pyplot(fig)
    else:
        st.info("データがありません")

# --- 4. チーム管理 ---
elif app_mode == "👤 チーム管理":
    st.header("👤 チーム・選手管理")
    if teams:
        tgt = st.selectbox("チーム", teams)
        mems = st.session_state.players_db[tgt]
        rows = [{"No":k, "Pos":v} for k,v in mems.items()]
        st.dataframe(pd.DataFrame(rows), hide_index=True)
        
        with st.form("reg"):
            c1,c2,c3 = st.columns([1,2,1])
            n = c1.text_input("No")
            nm = c2.text_input("Name")
            p = c3.selectbox("Pos", ["OH","MB","OP","S","L"])
            if st.form_submit_button("登録"):
                st.session_state.players_db[tgt][f"#{n} {nm}"] = p
                save_players(st.session_state.players_db)
                st.rerun()
    
    with st.expander("チーム追加"):
        nt = st.text_input("チーム名")
        if st.button("追加"):
            st.session_state.players_db[nt] = {}
            save_players(st.session_state.players_db)
            st.rerun()

# --- 5. 履歴データ ---
elif app_mode == "📝 履歴データ":
    st.header("📝 履歴データ")
    df = load_match_history()
    st.dataframe(df)
