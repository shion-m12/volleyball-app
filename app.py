import streamlit as st
import pandas as pd
from streamlit_image_coordinates import streamlit_image_coordinates
from PIL import Image, ImageDraw
import datetime
import re
import os
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# --- 設定 ---
st.set_page_config(layout="wide", page_title="Volleyball Analyst Pro v44.1")

# 定数
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
    # IDは固定
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

def sort_players(plist):
    return sorted(plist, key=lambda x: int(re.search(r'#(\d+)', x).group(1)) if re.search(r'#(\d+)', x) else 999)

def get_court_img():
    if os.path.exists("court.png"): return Image.open("court.png")
    img = Image.new('RGB', (500, 500), '#FFCC99')
    draw = ImageDraw.Draw(img)
    draw.rectangle([0,0,499,499], outline='white', width=5)
    draw.line([0,250,500,250], fill='white', width=3) # Center
    draw.line([0,170,500,170], fill='white', width=2) # Attack line
    draw.line([0,330,500,330], fill='white', width=2)
    img.save("court.png")
    return img

# --- ステート ---
if 'players_db' not in st.session_state: st.session_state.players_db = load_players()
if 'match_data' not in st.session_state: st.session_state.match_data = []
if 'my_order' not in st.session_state: st.session_state.my_order = []
if 'op_order' not in st.session_state: st.session_state.op_order = []
if 'game_state' not in st.session_state: st.session_state.game_state = {"my_score": 0, "op_score": 0, "serve_rights": "My Team", "my_rot": 1, "op_rot": 1}
if 'temp_coords' not in st.session_state: st.session_state.temp_coords = None
if 'my_libero' not in st.session_state: st.session_state.my_libero = "なし"

# --- ルールロジック (自動ローテ) ---
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
    # P4, P3, P2, P5, P6, P1 の順に誰がいるか
    return {
        "FL": order[(3+idx)%6], "FC": order[(2+idx)%6], "FR": order[(1+idx)%6],
        "BL": order[(4+idx)%6], "BC": order[(5+idx)%6], "BR": order[(0+idx)%6]
    }

# ==========================================
#  UI
# ==========================================
with st.sidebar:
    st.title("🏐 Analyst Pro v44.1")
    app_mode = st.radio("Mode", ["📊 試合入力", "👤 チーム管理", "📝 履歴"])
    st.markdown("---")
    
    # チーム選択
    teams = list(st.session_state.players_db.keys())
    if teams:
        my_tm = st.selectbox("自チーム", teams, index=0)
        op_tm = st.selectbox("相手チーム", [t for t in teams if t!=my_tm], index=0) if len(teams)>1 else "Guest"
    else: my_tm="MyTeam"; op_tm="Guest"

    if app_mode == "📊 試合入力":
        st.markdown("### 💾 データ操作")
        
        # 1. 途中保存 (バックアップ)
        if st.session_state.match_data:
            df_now = pd.DataFrame(st.session_state.match_data)
            csv = df_now.to_csv(index=False).encode('utf-8')
            st.download_button(
                label="📥 途中経過を保存 (CSV)",
                data=csv,
                file_name=f"match_backup_{datetime.datetime.now().strftime('%H%M')}.csv",
                mime='text/csv',
                help="入力中のデータをスマホ/PCにダウンロードします。ブラウザを閉じる前に押してください。"
            )
        
        # 2. 試合終了 (クラウド保存)
        if st.button("🏁 試合終了 (クラウド保存)", type="primary"):
            if st.session_state.match_data:
                save_match_data(pd.DataFrame(st.session_state.match_data))
                st.toast("Google Sheetsに保存完了！")
                st.success("クラウドへの保存が完了しました。")
            
            # リセット
            st.session_state.game_state = {"my_score": 0, "op_score": 0, "serve_rights": "My Team", "my_rot": 1, "op_rot": 1}
            st.session_state.match_data = []
            st.session_state.my_order = []
            st.rerun()

# --- 1. チーム管理 ---
if app_mode == "👤 チーム管理":
    st.header("👤 チーム・選手登録")
    c1, c2 = st.columns([2,1])
    new_t = c1.text_input("チーム新規作成")
    if c2.button("追加") and new_t:
        st.session_state.players_db[new_t] = {}
        save_players(st.session_state.players_db)
        st.rerun()
    
    if teams:
        tgt = st.selectbox("編集チーム", teams)
        mems = st.session_state.players_db[tgt]
        rows = [{"No": re.search(r'#(\d+)',k).group(1) if re.search(r'#(\d+)',k) else "99", "Name":k, "Pos":v} for k,v in mems.items()]
        st.dataframe(pd.DataFrame(rows), hide_index=True)
        
        with st.form("add_p"):
            c_no, c_nm, c_ps = st.columns([1,2,1])
            no = c_no.text_input("No")
            nm = c_nm.text_input("Name")
            ps = c_ps.selectbox("Pos", ["OH","MB","OP","S","L"])
            if st.form_submit_button("登録"):
                st.session_state.players_db[tgt][f"#{no} {nm}"] = ps
                save_players(st.session_state.players_db)
                st.rerun()

# --- 2. 試合入力 (メイン) ---
elif app_mode == "📊 試合入力":
    
    # --- A. スタメン登録画面 (未登録時) ---
    if not st.session_state.my_order:
        st.header("🏁 スターティングメンバー登録")
        st.info("コート上の位置に合わせて選手を配置してください")
        
        mp = sort_players(list(st.session_state.players_db[my_tm].keys())) if my_tm in st.session_state.players_db else []
        op = sort_players(list(st.session_state.players_db[op_tm].keys())) if op_tm in st.session_state.players_db else []
        
        # 視覚的配置: 左(自) - ネット - 右(敵)
        c_my_b, c_my_f, c_net, c_op_f, c_op_b = st.columns([1.5, 1.5, 0.2, 1.5, 1.5])
        
        # NET表示
        with c_net:
            st.markdown("<div style='height:300px; border-left:4px double #333; margin-left:50%;'></div>", unsafe_allow_html=True)

        # 自チーム (左側)
        with c_my_f:
            st.caption(f"{my_tm} 前衛")
            m4 = st.selectbox("前・左 (FL)", mp, index=3 if len(mp)>3 else 0, key="m4")
            m3 = st.selectbox("前・中 (FC)", mp, index=2 if len(mp)>2 else 0, key="m3")
            m2 = st.selectbox("前・右 (FR)", mp, index=1 if len(mp)>1 else 0, key="m2")
        with c_my_b:
            st.caption("後衛")
            m5 = st.selectbox("後・左 (BL)", mp, index=4 if len(mp)>4 else 0, key="m5")
            m6 = st.selectbox("後・中 (BC)", mp, index=5 if len(mp)>5 else 0, key="m6")
            m1 = st.selectbox("後・右 (BR/Srv)", mp, index=0, key="m1")

        # 相手チーム (右側)
        with c_op_f:
            st.caption(f"{op_tm} 前衛")
            if op:
                o2 = st.selectbox("前・左 (FL)", op, index=1, key="o2")
                o3 = st.selectbox("前・中 (FC)", op, index=2, key="o3")
                o4 = st.selectbox("前・右 (FR)", op, index=3, key="o4")
            else: st.write("(未登録)"); o2=o3=o4="Op2"
        with c_op_b:
            st.caption("後衛")
            if op:
                o1 = st.selectbox("後・左 (BL)", op, index=0, key="o1")
                o6 = st.selectbox("後・中 (BC)", op, index=5, key="o6")
                o5 = st.selectbox("後・右 (BR)", op, index=4, key="o5")
            else: st.write("(未登録)"); o1=o6=o5="Op1"

        st.markdown("---")
        c_opt1, c_opt2, c_btn = st.columns([1,1,1])
        ml = c_opt1.selectbox("リベロ (自)", ["なし"]+mp)
        first = c_opt2.radio("First Serve", [my_tm, op_tm])
        
        if c_btn.button("試合開始 🚀", type="primary"):
            st.session_state.my_order = [m1, m2, m3, m4, m5, m6]
            st.session_state.op_order = [o1, o2, o3, o4, o5, o6] if op else ["Op1","Op2","Op3","Op4","Op5","Op6"]
            st.session_state.my_libero = ml
            st.session_state.game_state["serve_rights"] = "My Team" if first == my_tm else "Opponent"
            st.rerun()

    # --- B. 試合中画面 ---
    else:
        # 1. リアルタイム・コート図 & スコア
        gs = st.session_state.game_state
        my_p = get_pos(st.session_state.my_order, gs['my_rot'])
        
        # サーブ権表示
        s_my = "🏐 SERVER" if gs['serve_rights']=="My Team" else ""
        s_op = "SERVER 🏐" if gs['serve_rights']=="Opponent" else ""
        
        # スコアボード
        st.markdown(f"""
        <div style="background:#262730; color:white; padding:15px; border-radius:10px; text-align:center; margin-bottom:10px;">
            <div style="font-size:1.2em; color:#aaa;">SET 1 (Demo)</div>
            <div style="font-size:3em; font-weight:bold; line-height:1;">
                <span style="color:#4da6ff">{gs['my_score']}</span> - <span style="color:#ff4b4b">{gs['op_score']}</span>
            </div>
            <div style="display:flex; justify-content:space-between; padding:0 20px;">
                <div style="color:#4da6ff; font-weight:bold;">{my_tm}<br>{s_my}</div>
                <div style="color:#ff4b4b; font-weight:bold;">{op_tm}<br>{s_op}</div>
            </div>
        </div>
        """, unsafe_allow_html=True)

        # コート図 (CSS Grid)
        st.markdown(f"""
        <style>
            .c-container {{ display: grid; grid-template-columns: 1fr 1fr 0.1fr 1fr 1fr; gap:5px; margin-bottom:15px; text-align:center; font-size:0.85em; }}
            .c-cell {{ padding:8px; border-radius:5px; border:1px solid #444; display:flex; flex-direction:column; justify-content:center; min-height:60px; }}
            .my-front {{ background-color: #d1e7dd; color: #0f5132; border: 2px solid #198754; }}
            .my-back {{ background-color: #f8f9fa; color: #333; }}
            .op-area {{ background-color: #f8d7da; color: #842029; opacity: 0.7; }}
            .net {{ background: #333; width:100%; height:100%; }}
            .srv-tag {{ font-size:0.7em; background:gold; padding:2px; border-radius:3px; color:black; font-weight:bold; }}
        </style>
        <div class="c-container">
            <div class="c-cell my-back">
                <div>BL (5)</div><div style="font-weight:bold;">{my_p.get('BL','?')}</div>
            </div>
            <div class="c-cell my-front">
                <div>FL (4)</div><div style="font-weight:bold;">{my_p.get('FL','?')}</div>
            </div>
            <div class="net"></div>
            <div class="c-cell op-area">Op Right</div>
            <div class="c-cell op-area">Op Left</div>

            <div class="c-cell my-back">
                <div>BC (6)</div><div style="font-weight:bold;">{my_p.get('BC','?')}</div>
            </div>
            <div class="c-cell my-front">
                <div>FC (3)</div><div style="font-weight:bold;">{my_p.get('FC','?')}</div>
            </div>
            <div class="net"></div>
            <div class="c-cell op-area">Op Center</div>
            <div class="c-cell op-area">Op Center</div>

            <div class="c-cell my-back" style="border: 2px solid gold;">
                <div>BR (1) <span class="srv-tag">Srv</span></div>
                <div style="font-weight:bold;">{my_p.get('BR','?')}</div>
            </div>
            <div class="c-cell my-front">
                <div>FR (2)</div><div style="font-weight:bold;">{my_p.get('FR','?')}</div>
            </div>
            <div class="net"></div>
            <div class="c-cell op-area">Op Left</div>
            <div class="c-cell op-area">Op Right</div>
        </div>
        """, unsafe_allow_html=True)

        # 2. 入力エリア (2カラムレイアウト)
        c_input, c_tools = st.columns([1.8, 1])
        
        with c_input:
            st.subheader("🏐 プレー入力")
            
            active = list(st.session_state.my_order)
            if st.session_state.my_libero != "なし": active.append(st.session_state.my_libero)
            active_sorted = ["なし"] + sort_players(active)
            
            c_i1, c_i2 = st.columns(2)
            pas = c_i1.selectbox("1. Reception", PASS_ORDER)
            sett = c_i2.selectbox("2. Setter", active_sorted)
            
            c_i3, c_i4 = st.columns(2)
            zone = c_i3.selectbox("3. Zone", ZONE_ORDER)
            # ツーアタック連動
            def_h = active_sorted.index(sett) if zone=="ツーアタック" and sett in active_sorted else 0
            hit = c_i4.selectbox("4. Hitter", active_sorted, index=def_h)
            
            blk = st.select_slider("5. Opponent Block", BLOCK_OPTIONS, value="2")
            
            st.caption("6. Toss Origin (Click Court)")
            coords = streamlit_image_coordinates(get_court_img(), width=400, key="click")
            if coords: st.session_state.temp_coords = coords
            
            if st.session_state.temp_coords:
                st.success("📍 座標取得OK")
            else:
                st.info("👆 上のコート図をクリックしてトス位置を指定")

            st.write("---")
            st.write("7. Result (決定で自動加点)")
            c_r1, c_r2, c_r3 = st.columns(3)
            res = None
            if c_r1.button("🔥 決定 (Kill)", type="primary", use_container_width=True): res = "得点 (Kill)"
            if c_r2.button("🔄 継続", use_container_width=True): res = "継続"
            if c_r3.button("💀 失点/被ブロ", use_container_width=True): res = "失点"

            if res:
                if not st.session_state.temp_coords:
                    st.error("コートをクリックして位置を指定してください！")
                else:
                    rec = {
                        "Time": datetime.datetime.now().strftime("%H:%M:%S"),
                        "MyScore": gs['my_score'], "OpScore": gs['op_score'], "Rot": gs['my_rot'],
                        "Pass": pas, "Setter": sett, "Zone": zone, "Hitter": hit, "Block": blk, "Result": res,
                        "X": st.session_state.temp_coords["x"], "Y": st.session_state.temp_coords["y"]
                    }
                    st.session_state.match_data.append(rec)
                    
                    if res == "得点 (Kill)":
                        add_score("my")
                        st.toast("Nice Kill! (+1)")
                    elif res == "失点":
                        add_score("op")
                        st.toast("Don't mind... (Op +1)")
                    elif pas == "失敗 (エース)":
                        add_score("op")
                        st.toast("Service Ace... (Op +1)")
                    
                    st.session_state.temp_coords = None
                    st.rerun()

        # 3. 調整パネル (右側)
        with c_tools:
            with st.expander("⚙️ 手動修正・交代", expanded=True):
                st.write("**点数修正**")
                c_adj1, c_adj2 = st.columns(2)
                if c_adj1.button("自 +1"): add_score("my"); st.rerun()
                if c_adj1.button("自 -1"): gs["my_score"]-=1; st.rerun()
                if c_adj2.button("敵 +1"): add_score("op"); st.rerun()
                if c_adj2.button("敵 -1"): gs["op_score"]-=1; st.rerun()
                
                st.write("**ローテーション**")
                if st.button("ローテを回す (Rotate)"): rotate("my"); st.rerun()
                
                st.write("**メンバーチェンジ**")
                pos_idx = st.selectbox("位置", ["FL(4)","FC(3)","FR(2)","BL(5)","BC(6)","BR(1)"])
                p_idx = {"BR(1)":0, "FR(2)":1, "FC(3)":2, "FL(4)":3, "BL(5)":4, "BC(6)":5}[pos_idx]
                
                bench = [p for p in sort_players(list(st.session_state.players_db[my_tm].keys())) if p not in st.session_state.my_order]
                sub_in = st.selectbox("IN", bench) if bench else None
                if st.button("交代実行") and sub_in:
                    st.session_state.my_order[p_idx] = sub_in
                    st.success("交代しました")
                    st.rerun()

            st.write("---")
            st.write("📜 直近の履歴")
            if st.session_state.match_data:
                if st.button("Undo (1つ消す)"):
                    st.session_state.match_data.pop()
                    st.rerun()
                df = pd.DataFrame(st.session_state.match_data)
                st.dataframe(df[["Pass","Hitter","Result"]].iloc[::-1], height=200, hide_index=True)

# --- 3. 履歴モード ---
elif app_mode == "📝 履歴":
    st.title("Log")
    try:
        df = pd.DataFrame(connect_to_gsheet().worksheet("history").get_all_records())
        st.dataframe(df)
    except: st.info("データなし")
