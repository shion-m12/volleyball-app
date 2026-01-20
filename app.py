import streamlit as st
import pandas as pd
from streamlit_image_coordinates import streamlit_image_coordinates
from PIL import Image
import datetime
import re
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# --- 設定 ---
st.set_page_config(layout="wide", page_title="Volleyball Analyst Pro v16.1")

# --- Google Sheets 接続設定 ---
def connect_to_gsheet():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    
    # Secretsから認証情報を取得
    creds_dict = dict(st.secrets["gcp_service_account"])
    creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")

    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    
    # ここはあなたのIDのままでOKです！
    SPREADSHEET_ID = "14o1wNqQIrJPy9IAuQ7PSCwP6NyA4O5dZrn_FmFoSqLQ"
    
    try:
        # エラーチェック（if文）を削除して、すぐに開くようにしました
        sheet = client.open_by_key(SPREADSHEET_ID)
        return sheet
    except gspread.exceptions.APIError:
        st.error("エラー：スプレッドシートが見つかりません。IDが正しいか、共有設定（ロボットの招待）ができているか確認してください。")
        st.stop()
# --- データ読み書き関数 ---
def load_players_from_sheet():
    sheet = connect_to_gsheet()
    try:
        worksheet = sheet.worksheet("players")
        data = worksheet.get_all_records()
        
        if not data:
             return {
                "My Team": {"#1 田中": "OH", "#2 佐藤": "MB", "#3 鈴木": "OP", "#4 高橋": "OH", "#5 渡辺": "MB", "#6 山本": "L"},
                "Opponent A": {"#1 敵A": "OH", "#2 敵B": "MB", "#3 敵C": "OP", "#4 敵D": "OH", "#5 敵E": "MB", "#6 敵L": "L"}
            }
        
        db = {}
        for row in data:
            team = str(row["Team"]) # 数値として扱われないよう文字列化
            p_key = str(row["PlayerKey"])
            pos = str(row["Position"])
            
            if team not in db:
                db[team] = {}
            db[team][p_key] = pos
        return db

    except gspread.exceptions.WorksheetNotFound:
        st.error("エラー：シート 'players' が見つかりません。")
        st.stop()

def save_players_to_sheet(players_dict):
    sheet = connect_to_gsheet()
    worksheet = sheet.worksheet("players")
    
    rows = []
    rows.append(["Team", "PlayerKey", "Position"])
    for team, members in players_dict.items():
        for p_key, pos in members.items():
            rows.append([team, p_key, pos])
    
    worksheet.clear()
    worksheet.update(rows)

def save_match_data_to_sheet(df):
    sheet = connect_to_gsheet()
    try:
        worksheet = sheet.worksheet("history")
    except gspread.exceptions.WorksheetNotFound:
        worksheet = sheet.add_worksheet(title="history", rows="1000", cols="20")
    
    existing_data = worksheet.get_all_values()
    # DataFrameの値をすべて文字列に変換してからリスト化（エラー防止）
    data_to_write = df.astype(str).values.tolist()
    
    if not existing_data:
        header = df.columns.tolist()
        worksheet.append_row(header)
        worksheet.append_rows(data_to_write)
    else:
        worksheet.append_rows(data_to_write)

def sort_players_by_number(player_names):
    def get_num(name):
        match = re.search(r'#(\d+)', name)
        return int(match.group(1)) if match else 999
    return sorted(player_names, key=get_num)

# --- ステート管理 ---
if 'players_db' not in st.session_state:
    st.session_state.players_db = load_players_from_sheet()
if 'match_data' not in st.session_state:
    st.session_state.match_data = []
if 'my_service_order' not in st.session_state:
    st.session_state.my_service_order = []
if 'op_service_order' not in st.session_state:
    st.session_state.op_service_order = []
if 'my_libero' not in st.session_state:
    st.session_state.my_libero = "なし"
if 'op_libero' not in st.session_state:
    st.session_state.op_libero = "なし"
if 'game_state' not in st.session_state:
    st.session_state.game_state = {"my_score": 0, "op_score": 0, "serve_rights": "My Team", "my_rot": 1, "op_rot": 1}

def rotate_team(team_side):
    current = st.session_state.game_state[f"{team_side}_rot"]
    next_rot = current + 1 if current < 6 else 1
    st.session_state.game_state[f"{team_side}_rot"] = next_rot

def add_point(winner):
    gs = st.session_state.game_state
    if winner == "My Team":
        gs["my_score"] += 1
        if gs["serve_rights"] == "Opponent":
            rotate_team("my")
            gs["serve_rights"] = "My Team"
    else:
        gs["op_score"] += 1
        if gs["serve_rights"] == "My Team":
            rotate_team("op")
            gs["serve_rights"] = "Opponent"

# ==========================================
#  UI
# ==========================================
with st.sidebar:
    st.title("🏐 Analyst Pro v16.1")
    app_mode = st.radio("メニュー", ["📊 試合入力", "👤 チーム管理"])
    st.markdown("---")
    
    team_list = list(st.session_state.players_db.keys())
    if team_list:
        my_team_name = st.selectbox("自チーム", team_list, index=0)
        other_teams = [t for t in team_list if t != my_team_name]
        op_team_name = st.selectbox("相手チーム", other_teams, index=0) if other_teams else "未設定"
    else:
        my_team_name = "未設定"; op_team_name = "未設定"

# --- モード1：チーム管理 ---
if app_mode == "👤 チーム管理":
    st.header("👤 チーム・選手管理 (Google Sheets連動)")
    
    c1, c2 = st.columns([1, 2])
    with c1:
        new_team = st.text_input("チーム新規作成")
        if st.button("追加"):
            if new_team and new_team not in st.session_state.players_db:
                st.session_state.players_db[new_team] = {}
                save_players_to_sheet(st.session_state.players_db)
                st.success(f"{new_team} 追加保存完了")
                st.rerun()
    with c2:
        if team_list:
            tgt_team = st.selectbox("編集チーム", team_list)
            members = st.session_state.players_db[tgt_team]
            p_list = [{"No.": (int(re.search(r'#(\d+)', k).group(1)) if re.search(r'#(\d+)', k) else 999), "Name": k, "Pos": v} for k,v in members.items()]
            df_p = pd.DataFrame(p_list).sort_values("No.") if p_list else pd.DataFrame()
            st.dataframe(df_p, hide_index=True, use_container_width=True)
            
            tab_add, tab_del = st.tabs(["追加", "削除"])
            with tab_add:
                c_n, c_nm = st.columns([1,2])
                num = c_n.text_input("No.", key="a_no")
                nm = c_nm.text_input("Name", key="a_nm")
                pos = st.selectbox("Pos", ["OH","MB","OP","S","L"], key="a_pos")
                if st.button("登録"):
                    if num and nm:
                        key = f"#{num} {nm}"
                        st.session_state.players_db[tgt_team][key] = pos
                        save_players_to_sheet(st.session_state.players_db)
                        st.success("保存しました")
                        st.rerun()
            with tab_del:
                if members:
                    del_tgt = st.selectbox("削除対象", sort_players_by_number(list(members.keys())))
                    if st.button("削除実行"):
                        del st.session_state.players_db[tgt_team][del_tgt]
                        save_players_to_sheet(st.session_state.players_db)
                        st.warning("削除完了")
                        st.rerun()

# --- モード2：試合入力 ---
elif app_mode == "📊 試合入力":
    try: image = Image.open("court.png")
    except: st.error("画像エラー"); st.stop()
        
    col_sc, col_mn, col_lg = st.columns([0.8, 1.2, 0.8])
    with col_sc:
        gs = st.session_state.game_state
        st.markdown(f"""
        <div style="text-align: center; border: 2px solid #ccc; padding: 10px; border-radius: 10px;">
            <h1 style="margin:0;">{gs['my_score']} - {gs['op_score']}</h1>
            <div style="display:flex; justify-content:space-between;">
                <div style="color:blue;">{my_team_name}<br>Rot:{gs['my_rot']}</div>
                <div style="color:grey;">{op_team_name}<br>Rot:{gs['op_rot']}</div>
            </div>
        </div>
        """, unsafe_allow_html=True)
        with st.expander("設定"):
            match_name = st.text_input("試合名", "練習試合")
            set_no = st.number_input("Set", 1, 5, 1)
            c_a, c_b = st.columns(2)
            if c_a.button("自+1"): add_point("My Team"); st.rerun()
            if c_a.button("自Rot"): rotate_team("my"); st.rerun()
            if c_b.button("敵+1"): add_point("Opponent"); st.rerun()
            if c_b.button("敵Rot"): rotate_team("op"); st.rerun()

    with col_mn:
        if not st.session_state.my_service_order:
            st.info("Lineup設定")
            mp = sort_players_by_number(list(st.session_state.players_db[my_team_name].keys())) if my_team_name!="未設定" else []
            op = sort_players_by_number(list(st.session_state.players_db[op_team_name].keys())) if op_team_name!="未設定" else []
            c1, c2 = st.columns(2)
            with c1:
                st.caption("自チーム")
                ms = [st.selectbox(f"P{i+1}", mp, key=f"m{i}") for i in range(6)]
                ml = st.selectbox("L", ["なし"]+mp, key="ml")
            with c2:
                st.caption("相手チーム")
                if op: os_ = [st.selectbox(f"P{i+1}", op, key=f"o{i}") for i in range(6)]; ol = st.selectbox("L", ["なし"]+op, key="ol")
                else: os_=[]; ol="なし"
            
            st.markdown("---")
            st.caption("最初のサーブ権を選択")
            first_srv_label = st.radio("First Serve", [my_team_name, op_team_name], horizontal=True, label_visibility="collapsed")
            first_srv_key = "My Team" if first_srv_label == my_team_name else "Opponent"
            
            if st.button("Start Match", type="primary"):
                st.session_state.my_service_order = ms; st.session_state.op_service_order = os_
                st.session_state.my_libero = ml; st.session_state.op_libero = ol
                st.session_state.game_state["serve_rights"] = first_srv_key
                st.rerun()
        else:
            active = list(st.session_state.my_service_order)
            if st.session_state.my_libero!="なし": active.append(st.session_state.my_libero)
            active_sorted = sort_players_by_number(active)
            c_p, c_r = st.columns([0.8, 1.2])
            recep = c_p.radio("Pass", ["Aパス","Bパス","Cパス"], horizontal=True)
            p_key = c_r.selectbox("Player", active_sorted)
            res = c_r.selectbox("Result", ["得点 (Kill)", "効果", "継続", "失点 (Error)", "被ブロック"])
            st.write("Click Court 👇")
            coords = streamlit_image_coordinates(image, width=500, key="click")
            if coords and coords["x"] != (st.session_state.match_data[-1]["X"] if st.session_state.match_data else -1):
                pos = st.session_state.players_db[my_team_name].get(p_key, "?")
                rec = {"Match": f"{datetime.date.today()}_{match_name}", "Set": set_no, "Team": my_team_name, "MyScore": gs['my_score'], "OpScore": gs['op_score'], "Rot": gs['my_rot'], "Player": p_key, "Pos": pos, "Result": res, "Pass": recep, "X": coords["x"], "Y": coords["y"]}
                st.session_state.match_data.append(rec)
                if res == "得点 (Kill)": add_point("My Team"); st.toast("Nice!")
                elif res in ["失点 (Error)", "被ブロック"]: add_point("Opponent"); st.toast("Don't mind")
                else: st.toast("Saved")
                st.rerun()
            with st.expander("Reset / Sub"):
                if st.button("Reset Lineup"): st.session_state.my_service_order=[]; st.rerun()
                c_s1, c_s2 = st.columns(2)
                sub_pos = c_s1.selectbox("位置", ["P1","P2","P3","P4","P5","P6"])
                all_p = sort_players_by_number(list(st.session_state.players_db[my_team_name].keys()))
                bench = [p for p in all_p if p not in st.session_state.my_service_order]
                sub_in = c_s2.selectbox("IN", bench) if bench else None
                if st.button("交代実行"):
                    if sub_in: st.session_state.my_service_order[int(sub_pos[1])-1] = sub_in; st.rerun()

    with col_lg:
        if st.session_state.match_data:
            df = pd.DataFrame(st.session_state.match_data)
            st.dataframe(df[["MyScore", "Player", "Result"]].iloc[::-1], height=300, hide_index=True)
            if st.button("☁️ Google Sheetsに保存"):
                save_match_data_to_sheet(df)
                st.success("クラウド保存完了！")
                st.session_state.match_data = []



