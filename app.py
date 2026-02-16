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

# --- 設定 ---
st.set_page_config(layout="wide", page_title="Volleyball Analyst Pro v43 (Research)")

# 定数定義
ZONE_COLORS = {
    "レフト(L)": ("red", "Left"),
    "センター(C)": ("green", "Center"),
    "ライト(R)": ("blue", "Right"),
    "ツーアタック": ("gold", "Setter Dump"),
    "レフトバック(LB)": ("orange", "Back-Left"),
    "センターバック(CB)": ("purple", "Back-Center"),
    "ライトバック(RB)": ("cyan", "Back-Right"),
    "なし": ("gray", "None")
}
PASS_ORDER = ["Aパス", "Bパス", "Cパス", "その他", "相手サーブミス", "失敗 (エース)"]
ZONE_ORDER = ["レフト(L)", "センター(C)", "ライト(R)", "ツーアタック", "レフトバック(LB)", "センターバック(CB)", "ライトバック(RB)", "なし"]
BLOCK_OPTIONS = ["0", "1", "1.5", "2", "2.5", "3"]

# --- Google API 接続設定 ---
def get_gcp_creds():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    try:
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        return creds
    except Exception as e:
        st.error(f"認証エラー: {e}")
        st.stop()

def connect_to_gsheet():
    creds = get_gcp_creds()
    client = gspread.authorize(creds)
    SPREADSHEET_ID = "14o1wNqQIrJPy9IAuQ7PSCwP6NyA4O5dZrn_FmFoSqLQ"
    try:
        sheet = client.open_by_key(SPREADSHEET_ID)
        return sheet
    except gspread.exceptions.APIError:
        st.error("エラー：スプレッドシートが見つかりません。")
        st.stop()

# --- データ読み書き ---
def load_players_from_sheet():
    sheet = connect_to_gsheet()
    try:
        worksheet = sheet.worksheet("players")
        data = worksheet.get_all_records()
        if not data: return {}
        db = {}
        for row in data:
            team = str(row["Team"])
            p_key = str(row["PlayerKey"])
            pos = str(row["Position"])
            if team not in db: db[team] = {}
            db[team][p_key] = pos
        return db
    except:
        return {}

def save_players_to_sheet(players_dict):
    sheet = connect_to_gsheet()
    try: worksheet = sheet.worksheet("players")
    except: worksheet = sheet.add_worksheet(title="players", rows="100", cols="5")
    rows = [["Team", "PlayerKey", "Position"]]
    for team, members in players_dict.items():
        for k, v in members.items(): rows.append([team, k, v])
    worksheet.clear()
    worksheet.update(rows)

def save_match_data_to_sheet(df):
    sheet = connect_to_gsheet()
    try: worksheet = sheet.worksheet("history")
    except: worksheet = sheet.add_worksheet(title="history", rows="1000", cols="20")
    existing = worksheet.get_all_values()
    data = df.astype(str).values.tolist()
    if not existing:
        worksheet.append_row(df.columns.tolist())
        worksheet.append_rows(data)
    else:
        worksheet.append_rows(data)

def load_match_history():
    sheet = connect_to_gsheet()
    try:
        worksheet = sheet.worksheet("history")
        data = worksheet.get_all_values()
        if not data: return pd.DataFrame()
        return pd.DataFrame(data[1:], columns=data[0])
    except: return pd.DataFrame()

# --- ユーティリティ ---
def sort_players_by_number(player_names):
    def get_num(name):
        match = re.search(r'#(\d+)', name)
        return int(match.group(1)) if match else 999
    return sorted(player_names, key=get_num)

def get_court_image():
    if os.path.exists("court.png"): return Image.open("court.png")
    img = Image.new('RGB', (500, 500), color='#FFCC99')
    draw = ImageDraw.Draw(img)
    w, h = 500, 500
    draw.rectangle([0, 0, w-1, h-1], outline='white', width=5)
    draw.line([0, h/2, w, h/2], fill='white', width=3)
    img.save("court.png")
    return img

# --- ステート管理 ---
if 'players_db' not in st.session_state: st.session_state.players_db = load_players_from_sheet()
if 'match_data' not in st.session_state: st.session_state.match_data = []
if 'my_service_order' not in st.session_state: st.session_state.my_service_order = []
if 'game_state' not in st.session_state: st.session_state.game_state = {"my_score": 0, "op_score": 0, "serve_rights": "My Team", "my_rot": 1, "op_rot": 1}
if 'temp_coords' not in st.session_state: st.session_state.temp_coords = None
if 'my_libero' not in st.session_state: st.session_state.my_libero = "なし"

def rotate_team(team_side):
    cur = st.session_state.game_state[f"{team_side}_rot"]
    st.session_state.game_state[f"{team_side}_rot"] = cur + 1 if cur < 6 else 1

def rotate_team_reverse(team_side):
    cur = st.session_state.game_state[f"{team_side}_rot"]
    st.session_state.game_state[f"{team_side}_rot"] = cur - 1 if cur > 1 else 6

def get_pos_map(order, rot):
    if not order or len(order)<6: return {}
    idx = rot - 1
    return {
        "P4(FL)": order[(3+idx)%6], "P3(FC)": order[(2+idx)%6], "P2(FR)": order[(1+idx)%6],
        "P5(BL)": order[(4+idx)%6], "P6(BC)": order[(5+idx)%6], "P1(BR)": order[(0+idx)%6]
    }

# ==========================================
#  UI サイドバー
# ==========================================
with st.sidebar:
    st.title("🏐 Analyst Pro v43")
    app_mode = st.radio("メニュー", ["📊 試合入力", "🎓 研究用分析(New)", "📈 トス配給分析(通常)", "👤 チーム管理", "📝 履歴データ"])
    st.markdown("---")
    
    # チーム設定
    team_list = list(st.session_state.players_db.keys())
    if team_list:
        my_team_name = st.selectbox("自チーム", team_list, index=0)
        other_teams = [t for t in team_list if t != my_team_name]
        op_team_name = st.selectbox("相手チーム", other_teams, index=0) if other_teams else "未設定"
    else:
        my_team_name = "未設定"; op_team_name = "未設定"

    if app_mode == "📊 試合入力":
        st.markdown("---")
        if st.button("🏁 試合終了 (保存してリセット)", type="primary"):
            if st.session_state.match_data:
                df = pd.DataFrame(st.session_state.match_data)
                save_match_data_to_sheet(df)
                st.toast("保存しました")
            st.session_state.game_state = {"my_score": 0, "op_score": 0, "serve_rights": "My Team", "my_rot": 1, "op_rot": 1}
            st.session_state.match_data = []
            st.session_state.my_service_order = []
            st.rerun()

# ==========================================
#  UI メイン
# ==========================================

# --- モード1: チーム管理 ---
if app_mode == "👤 チーム管理":
    st.header("👤 チーム・選手管理")
    with st.expander("➕ チーム追加"):
        c1, c2 = st.columns([2,1])
        nt = c1.text_input("チーム名")
        if c2.button("追加") and nt:
            st.session_state.players_db[nt] = {}
            save_players_to_sheet(st.session_state.players_db)
            st.rerun()
            
    if team_list:
        tgt = st.selectbox("編集チーム", team_list)
        mems = st.session_state.players_db[tgt]
        p_l = [{"No.": (int(re.search(r'#(\d+)', k).group(1)) if re.search(r'#(\d+)', k) else 999), "Name": k, "Pos": v} for k,v in mems.items()]
        st.dataframe(pd.DataFrame(p_l).sort_values("No.") if p_l else pd.DataFrame(), hide_index=True)
        
        t1, t2 = st.tabs(["登録", "削除"])
        with t1:
            c_n, c_nm, c_p = st.columns([1,2,1])
            num = c_n.text_input("No.", key="mk_n")
            nm = c_nm.text_input("Name", key="mk_nm")
            pos = c_p.selectbox("Pos", ["OH","MB","OP","S","L"], key="mk_p")
            if st.button("登録"):
                st.session_state.players_db[tgt][f"#{num} {nm}"] = pos
                save_players_to_sheet(st.session_state.players_db)
                st.rerun()
        with t2:
            if mems:
                d_tgt = st.selectbox("削除", list(mems.keys()))
                if st.button("削除実行"):
                    del st.session_state.players_db[tgt][d_tgt]
                    save_players_to_sheet(st.session_state.players_db)
                    st.rerun()

# --- モード2: 研究用分析 (NEW) ---
elif app_mode == "🎓 研究用分析(New)":
    st.header("🎓 トス配給傾向の研究分析")
    st.caption("研究計画に基づき、セッターの前衛・後衛別、Cパス時の傾向、ブロック枚数との関係を分析します。")
    
    # データロード
    df_hist = load_match_history()
    df_sess = pd.DataFrame(st.session_state.match_data)
    df = pd.concat([df_hist, df_sess], ignore_index=True)
    
    if df.empty:
        st.info("データがありません。")
    else:
        # 数値変換
        df["Block"] = pd.to_numeric(df["Block"], errors='coerce')
        
        # フィルタリング
        teams = df["Team"].unique()
        sel_team = st.selectbox("分析対象チーム", teams, index=0)
        df = df[df["Team"] == sel_team]
        
        # セッター前衛/後衛の定義
        st.markdown("##### ⚙️ 分析条件設定")
        setter_front_rot = st.multiselect("セッターが「前衛」のローテーションを選択", [1,2,3,4,5,6], default=[4,5,6])
        
        # データ分割
        df["SetterPos"] = df["Rot"].astype(int).apply(lambda x: "前衛 (攻撃2枚)" if x in setter_front_rot else "後衛 (攻撃3枚)")
        
        # タブ切り替え
        tab_front, tab_back, tab_cpass = st.tabs(["① セッター前衛時", "② セッター後衛時", "③ Cパス詳細分析"])
        
        # 共通分析関数
        def analyze_situation(data, title):
            st.subheader(f"📊 {title} の配給傾向")
            if data.empty:
                st.write("データなし")
                return

            # 1. 配給率クロス集計
            st.markdown("**1. レセプション別 配給率 (%)**")
            pivot_count = pd.crosstab(data["Pass"], data["Zone"])
            pivot_pct = pd.crosstab(data["Pass"], data["Zone"], normalize='index') * 100
            st.dataframe(pivot_pct.style.format("{:.1f}%").background_gradient(cmap="Oranges", axis=1))
            
            # 2. ブロック枚数の質的評価
            st.markdown("**2. ブロック枚数と数的優位性**")
            # 数的優位定義: ブロック1.5枚以下
            data["NumericalAdvantage"] = data["Block"] <= 1.5
            
            c1, c2 = st.columns(2)
            with c1:
                st.write("▼ ゾーン別 平均被ブロック枚数")
                block_stats = data.groupby("Zone")["Block"].mean().reset_index()
                st.bar_chart(block_stats.set_index("Zone"))
                
            with c2:
                st.write("▼ 数的優位を作れた割合 (Block <= 1.5)")
                adv_rate = data.groupby("Zone")["NumericalAdvantage"].mean() * 100
                st.dataframe(adv_rate.to_frame("優位率(%)").style.format("{:.1f}%"))

            # 3. ツーアタック評価 (前衛時のみ)
            if "前衛" in title:
                dump_count = len(data[data["Zone"] == "ツーアタック"])
                dump_rate = dump_count / len(data) * 100
                st.metric("ツーアタック実施率", f"{dump_rate:.1f}%", f"{dump_count}本")

        with tab_front:
            df_f = df[df["SetterPos"] == "前衛 (攻撃2枚)"]
            analyze_situation(df_f, "セッター前衛 (攻撃2枚)")
            
        with tab_back:
            df_b = df[df["SetterPos"] == "後衛 (攻撃3枚)"]
            analyze_situation(df_b, "セッター後衛 (攻撃3枚)")
            
        with tab_cpass:
            st.subheader("⚠️ Cパス（乱された場面）の傾向分析")
            df_c = df[df["Pass"] == "Cパス"]
            
            if df_c.empty:
                st.info("Cパスのデータがありません")
            else:
                c1, c2 = st.columns(2)
                with c1:
                    st.markdown("**配給先内訳 (誰に託したか)**")
                    dist = df_c["Zone"].value_counts()
                    fig, ax = plt.subplots()
                    ax.pie(dist, labels=dist.index, autopct='%1.1f%%', startangle=90)
                    st.pyplot(fig)
                
                with c2:
                    st.markdown("**その時の被ブロック枚数分布**")
                    blk_dist = df_c["Block"].value_counts().sort_index()
                    st.bar_chart(blk_dist)
                    avg_blk = df_c["Block"].mean()
                    st.metric("Cパス時の平均被ブロック枚数", f"{avg_blk:.2f}枚")
                    if avg_blk > 2.0:
                        st.error("評価: 多くの場面で数的不利（2枚以上）を強いられています。")
                    else:
                        st.success("評価: 乱されてもブロックを分散できています。")

# --- モード3: 試合入力 ---
elif app_mode == "📊 試合入力":
    image = get_court_image()
    c_sc, c_mn, c_lg = st.columns([0.8, 1.2, 0.8])
    
    with c_sc:
        gs = st.session_state.game_state
        st.markdown(f"""
        <div style="text-align: center; border: 2px solid #333; padding: 10px; border-radius: 10px; background: #f9f9f9;">
            <h3>{gs['my_score']} - {gs['op_score']}</h3>
            <div>{my_team_name} (Rot:{gs['my_rot']}) vs {op_team_name}</div>
        </div>
        """, unsafe_allow_html=True)
        
        # コート表示
        if st.session_state.my_service_order:
            pos_map = get_pos_map(st.session_state.my_service_order, gs['my_rot'])
            # (簡易表示)
            st.info(f"前衛: {pos_map.get('P4(FL)')}, {pos_map.get('P3(FC)')}, {pos_map.get('P2(FR)')}")
            
        with st.expander("点数・ローテ操作", expanded=True):
            c1, c2, c3, c4 = st.columns(4)
            if c1.button("自+1"): add_point("My Team"); st.rerun()
            if c2.button("自-1"): remove_point("My Team"); st.rerun()
            if c3.button("敵+1"): add_point("Opponent"); st.rerun()
            if c4.button("敵-1"): remove_point("Opponent"); st.rerun()
            if st.button("ローテ回す"): rotate_team("my"); st.rerun()

    with c_mn:
        if not st.session_state.my_service_order:
            st.warning("スタメン未設定")
            mp = sort_players_by_number(list(st.session_state.players_db[my_team_name].keys())) if my_team_name!="未設定" else []
            if mp:
                s_order = st.multiselect("スタメン6人 (P1から順に)", mp)
                if len(s_order)==6 and st.button("開始"):
                    st.session_state.my_service_order = s_order
                    st.rerun()
        else:
            # 入力フォーム
            st.write("##### プレー記録")
            active = ["なし"] + st.session_state.my_service_order
            
            c_p, c_s = st.columns(2)
            pas = c_p.selectbox("Pass", PASS_ORDER)
            sett = c_s.selectbox("Setter", active)
            
            c_z, c_h = st.columns(2)
            zone = c_z.selectbox("Zone", ZONE_ORDER)
            # ツーアタック連動
            def_h = 0
            if zone == "ツーアタック" and sett in active: def_h = active.index(sett)
            hit = c_h.selectbox("Hitter", active, index=def_h)
            
            # ★ブロック枚数スライダー (New)
            st.write("🧱 相手ブロック枚数")
            block_val = st.select_slider("Block Count", options=BLOCK_OPTIONS, value="2")
            
            res = st.radio("Result", ["得点 (Kill)", "継続", "失点", "被ブロック"], horizontal=True)
            
            st.caption("👇 トス位置をタップ")
            coords = streamlit_image_coordinates(image, width=500, key="click")
            if coords: st.session_state.temp_coords = coords
            
            if st.button("記録する", type="primary", use_container_width=True):
                if st.session_state.temp_coords:
                    rec = {
                        "Match": f"{datetime.date.today()}_{op_team_name}",
                        "Team": my_team_name,
                        "Rot": gs['my_rot'],
                        "Pass": pas,
                        "Setter": sett,
                        "Zone": zone,
                        "Hitter": hit,
                        "Block": block_val, # 保存
                        "Result": res,
                        "X": st.session_state.temp_coords["x"],
                        "Y": st.session_state.temp_coords["y"]
                    }
                    st.session_state.match_data.append(rec)
                    
                    if res == "得点 (Kill)": add_point("My Team")
                    elif res in ["失点", "被ブロック"]: add_point("Opponent")
                    st.toast("記録しました")
                    st.session_state.temp_coords = None
                    st.rerun()
                else:
                    st.error("位置を指定してください")

            # メンバーチェンジ
            with st.expander("選手交代"):
                pos_idx = st.number_input("位置 (1-6)", 1, 6, 1) - 1
                bench = [p for p in list(st.session_state.players_db[my_team_name].keys()) if p not in st.session_state.my_service_order]
                sub = st.selectbox("IN", bench) if bench else None
                if st.button("交代"):
                    st.session_state.my_service_order[pos_idx] = sub
                    st.rerun()

    with c_lg:
        st.header("Log")
        if st.session_state.match_data:
            if st.button("Undo"):
                st.session_state.match_data.pop()
                st.rerun()
            df = pd.DataFrame(st.session_state.match_data)
            st.dataframe(df[["Pass","Zone","Block","Result"]].iloc[::-1], height=300, hide_index=True)

# --- モード4: 履歴 & 通常分析 ---
elif app_mode == "📝 履歴データ":
    st.header("📝 データ確認")
    df = load_match_history()
    st.dataframe(df)

elif app_mode == "📈 トス配給分析(通常)":
    # 既存の散布図などを表示
    st.header("📈 通常分析")
    df = load_match_history()
    df_cur = pd.DataFrame(st.session_state.match_data)
    df_all = pd.concat([df, df_cur], ignore_index=True)
    
    if not df_all.empty and "X" in df_all.columns:
        df_all["X"] = pd.to_numeric(df_all["X"], errors='coerce')
        df_all["Y"] = pd.to_numeric(df_all["Y"], errors='coerce')
        df_all = df_all.dropna(subset=["X", "Y"])
        
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(10, 6))
        img = get_court_image()
        ax.imshow(img, extent=[0, 500, 500, 0])
        
        for z in ZONE_ORDER:
            d = df_all[df_all["Zone"]==z]
            if not d.empty:
                ax.scatter(d["X"], d["Y"], label=z, color=ZONE_COLORS.get(z,("gray",""))[0], s=100, edgecolors="white")
        ax.legend()
        st.pyplot(fig)
