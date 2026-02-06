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
import matplotlib.image as mpimg

# --- 設定 ---
st.set_page_config(layout="wide", page_title="Volleyball Analyst Pro v29")

# ゾーンと色の定義
ZONE_COLORS = {
    "レフト(L)": ("red", "Left"),
    "センター(C)": ("green", "Center"),
    "ライト(R)": ("blue", "Right"),
    "レフトバック(LB)": ("orange", "Back-Left"),
    "センターバック(CB)": ("purple", "Back-Center"),
    "ライトバック(RB)": ("cyan", "Back-Right"),
    "なし": ("gray", "None")
}

# 表示順序
PASS_ORDER = ["Aパス", "Bパス", "Cパス", "その他", "相手サーブミス", "失敗 (エース)"]
ZONE_ORDER = ["レフト(L)", "センター(C)", "ライト(R)", "レフトバック(LB)", "センターバック(CB)", "ライトバック(RB)", "なし"]

# --- コート画像を準備する関数 ---
def get_court_image():
    if os.path.exists("court.png"):
        try:
            img = Image.open("court.png")
            img.verify()
            return Image.open("court.png")
        except Exception:
            pass
    img = Image.new('RGB', (500, 500), color='#FFCC99')
    draw = ImageDraw.Draw(img)
    w, h = 500, 500
    draw.rectangle([0, 0, w-1, h-1], outline='white', width=5)
    draw.line([0, h/2, w, h/2], fill='white', width=3)
    draw.line([0, h/2 - 80, w, h/2 - 80], fill='white', width=2)
    draw.line([0, h/2 + 80, w, h/2 + 80], fill='white', width=2)
    img.save("court.png")
    return img

# --- Google Sheets 接続設定 ---
def connect_to_gsheet():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    try:
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
    except Exception as e:
        st.error(f"認証エラー: {e}")
        st.stop()
    
    SPREADSHEET_ID = "14o1wNqQIrJPy9IAuQ7PSCwP6NyA4O5dZrn_FmFoSqLQ"
    
    try:
        sheet = client.open_by_key(SPREADSHEET_ID)
        return sheet
    except gspread.exceptions.APIError:
        st.error("エラー：スプレッドシートが見つかりません。")
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
            team = str(row["Team"])
            p_key = str(row["PlayerKey"])
            pos = str(row["Position"])
            if team not in db: db[team] = {}
            db[team][p_key] = pos
        return db
    except gspread.exceptions.WorksheetNotFound:
        st.error("エラー：シート 'players' が見つかりません。")
        st.stop()

def save_players_to_sheet(players_dict):
    sheet = connect_to_gsheet()
    worksheet = sheet.worksheet("players")
    rows = [["Team", "PlayerKey", "Position"]]
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
    data_to_write = df.astype(str).values.tolist()
    if not existing_data:
        header = df.columns.tolist()
        worksheet.append_row(header)
        worksheet.append_rows(data_to_write)
    else:
        worksheet.append_rows(data_to_write)

def overwrite_history_sheet(df):
    sheet = connect_to_gsheet()
    try:
        worksheet = sheet.worksheet("history")
    except gspread.exceptions.WorksheetNotFound:
        worksheet = sheet.add_worksheet(title="history", rows="1000", cols="20")
    worksheet.clear()
    if not df.empty:
        data = [df.columns.tolist()] + df.astype(str).values.tolist()
        worksheet.update(data)

def load_match_history():
    sheet = connect_to_gsheet()
    try:
        worksheet = sheet.worksheet("history")
        data = worksheet.get_all_values()
        if not data: return pd.DataFrame()
        headers = data[0]
        if "Match" not in headers: return pd.DataFrame()
        rows = data[1:]
        if not rows: return pd.DataFrame(columns=headers)
        return pd.DataFrame(rows, columns=headers)
    except Exception as e:
        return pd.DataFrame()

def sort_players_by_number(player_names):
    def get_num(name):
        match = re.search(r'#(\d+)', name)
        return int(match.group(1)) if match else 999
    return sorted(player_names, key=get_num)

# --- ステート管理 ---
if 'players_db' not in st.session_state: st.session_state.players_db = load_players_from_sheet()
if 'match_data' not in st.session_state: st.session_state.match_data = []
if 'my_service_order' not in st.session_state: st.session_state.my_service_order = []
if 'op_service_order' not in st.session_state: st.session_state.op_service_order = []
if 'my_libero' not in st.session_state: st.session_state.my_libero = "なし"
if 'op_libero' not in st.session_state: st.session_state.op_libero = "なし"
if 'game_state' not in st.session_state: st.session_state.game_state = {"my_score": 0, "op_score": 0, "serve_rights": "My Team", "my_rot": 1, "op_rot": 1}
if 'temp_coords' not in st.session_state: st.session_state.temp_coords = None

def rotate_team(team_side):
    current = st.session_state.game_state[f"{team_side}_rot"]
    next_rot = current + 1 if current < 6 else 1
    st.session_state.game_state[f"{team_side}_rot"] = next_rot

def rotate_team_reverse(team_side):
    current = st.session_state.game_state[f"{team_side}_rot"]
    prev_rot = current - 1 if current > 1 else 6
    st.session_state.game_state[f"{team_side}_rot"] = prev_rot

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

def remove_point(winner):
    gs = st.session_state.game_state
    if winner == "My Team":
        if gs["my_score"] > 0: gs["my_score"] -= 1
    else:
        if gs["op_score"] > 0: gs["op_score"] -= 1

# ★現在のローテーション位置を取得する関数
def get_current_positions(service_order, rotation):
    # order: [p1, p2, p3, p4, p5, p6] のリスト
    # rotation: 1～6
    # コート上の位置 (FrontLeft, FrontCenter...) に誰がいるかを返す
    
    if not service_order or len(service_order) < 6:
        return {}
    
    # Pythonのリストは0始まり。Rot1の時、Pos1(サーブ)にいるのは order[0]
    # Rotが進むにつれて反時計回りにズレていく（インデックスはマイナスになる）
    
    # 各ポジションのインデックス計算: (定位置 - Rot) % 6
    # Pos1(BR): 0, Pos2(FR): 1, Pos3(FC): 2, Pos4(FL): 3, Pos5(BL): 4, Pos6(BC): 5
    
    # 修正ロジック:
    # Rot1: [0]がPos1
    # Rot2: [5]がPos1 ([0]はPos6に移動)
    # つまり Pos_i の選手 = order[(i - 1 - (rotation - 1)) % 6] ???
    # いや、もっと単純に。
    # Pos 1 (Srv) index = (1 - rot) % 6
    # Pos 2 (FR)  index = (2 - rot) % 6
    # ...
    
    indices = {
        "P4(FL)": (3 - (rotation - 1)) % 6,
        "P3(FC)": (2 - (rotation - 1)) % 6,
        "P2(FR)": (1 - (rotation - 1)) % 6,
        "P5(BL)": (4 - (rotation - 1)) % 6,
        "P6(BC)": (5 - (rotation - 1)) % 6,
        "P1(BR)": (0 - (rotation - 1)) % 6,
    }
    
    positions = {k: service_order[v] for k, v in indices.items()}
    return positions

# ==========================================
#  UI サイドバー
# ==========================================
with st.sidebar:
    st.title("🏐 Analyst Pro v29")
    app_mode = st.radio("メニュー", ["📊 試合入力", "📈 トス配給分析", "📝 履歴編集", "👤 チーム管理"])
    st.markdown("---")
    
    team_list = list(st.session_state.players_db.keys())
    if team_list:
        my_team_name = st.selectbox("自チーム", team_list, index=0)
        other_teams = [t for t in team_list if t != my_team_name]
        op_team_name = st.selectbox("相手チーム", other_teams, index=0) if other_teams else "未設定"
    else:
        my_team_name = "未設定"; op_team_name = "未設定"
    
    st.markdown("---")
    if app_mode == "📊 試合入力":
        if st.button("🏁 試合終了 (保存してリセット)"):
            if st.session_state.match_data:
                df = pd.DataFrame(st.session_state.match_data)
                save_match_data_to_sheet(df)
                st.toast("自動保存しました")
            st.session_state.game_state = {"my_score": 0, "op_score": 0, "serve_rights": "My Team", "my_rot": 1, "op_rot": 1}
            st.session_state.match_data = []
            st.session_state.my_service_order = []
            st.session_state.temp_coords = None
            st.success("リセット完了")
            st.rerun()

# ==========================================
#  UI メイン
# ==========================================

# --- モード1：チーム管理 ---
if app_mode == "👤 チーム管理":
    st.header("👤 チーム・選手管理")
    c1, c2 = st.columns([1, 2])
    with c1:
        new_team = st.text_input("チーム新規作成")
        if st.button("追加"):
            if new_team and new_team not in st.session_state.players_db:
                st.session_state.players_db[new_team] = {}
                save_players_to_sheet(st.session_state.players_db)
                st.success(f"{new_team} 追加")
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
                        st.success("保存")
                        st.rerun()
            with tab_del:
                if members:
                    del_tgt = st.selectbox("削除対象", sort_players_by_number(list(members.keys())))
                    if st.button("削除実行"):
                        del st.session_state.players_db[tgt_team][del_tgt]
                        save_players_to_sheet(st.session_state.players_db)
                        st.warning("削除完了")
                        st.rerun()

# --- モード2：データ分析 ---
elif app_mode == "📈 トス配給分析":
    st.header("📈 セッター配給分析 (Setter Distribution)")
    
    df_session = pd.DataFrame(st.session_state.match_data)
    df_history = load_match_history()
    df_all = pd.concat([df_history, df_session], ignore_index=True)
    
    if df_all.empty:
        st.info("データがありません。")
    else:
        if "X" not in df_all.columns or "Y" not in df_all.columns:
            st.warning("データの列構造が古い可能性があります。")
        else:
            df_all["X"] = pd.to_numeric(df_all["X"], errors='coerce')
            df_all["Y"] = pd.to_numeric(df_all["Y"], errors='coerce')
            df_all = df_all.dropna(subset=["X", "Y"])
            
            with st.expander("🔍 フィルタリング設定", expanded=True):
                c_f1, c_f2 = st.columns(2)
                teams = df_all["Team"].unique()
                default_idx = 0
                if my_team_name in teams:
                    temp_list = list(teams)
                    default_idx = temp_list.index(my_team_name)
                    
                sel_team = c_f1.selectbox("チーム", teams, index=default_idx)
                df_filtered = df_all[df_all["Team"] == sel_team]
                
                if "Setter" in df_filtered.columns:
                    setters_raw = [s for s in list(df_filtered["Setter"].unique()) if s != "なし"]
                    setters = ["全員"] + setters_raw
                    sel_setter = c_f2.selectbox("分析対象セッター", setters)
                    if sel_setter != "全員":
                        df_filtered = df_filtered[df_filtered["Setter"] == sel_setter]
            
            # マトリクス表
            if not df_filtered.empty and "Pass" in df_filtered.columns and "Zone" in df_filtered.columns:
                st.markdown(f"### 📊 レセプション別 配給・決定率一覧 - {sel_setter}")
                st.caption("配: 配給率 (本数シェア%) / 決: 決定率 (得点確率%)")
                
                pass_counts = df_filtered["Pass"].value_counts()
                stats = df_filtered.groupby(['Pass', 'Zone']).agg(
                    attempts=('Result', 'count'),
                    kills=('Result', lambda x: (x == '得点 (Kill)').sum())
                ).reset_index()
                
                table_data = []
                valid_passes = [p for p in PASS_ORDER if p in df_filtered["Pass"].unique()]
                
                for p_label in valid_passes:
                    row = {"Pass": p_label}
                    total_sets_in_pass = pass_counts.get(p_label, 0)
                    for z_label in ZONE_ORDER:
                        target = stats[(stats['Pass'] == p_label) & (stats['Zone'] == z_label)]
                        if not target.empty:
                            att = target.iloc[0]['attempts']
                            kill = target.iloc[0]['kills']
                            dist_rate = (att / total_sets_in_pass * 100) if total_sets_in_pass > 0 else 0
                            kill_rate = (kill / att * 100) if att > 0 else 0
                            row[f"{z_label} (配)"] = dist_rate
                            row[f"{z_label} (決)"] = kill_rate
                        else:
                            row[f"{z_label} (配)"] = 0.0
                            row[f"{z_label} (決)"] = 0.0
                    table_data.append(row)
                
                if table_data:
                    df_matrix = pd.DataFrame(table_data).set_index("Pass")
                    dist_cols = [c for c in df_matrix.columns if "(配)" in c]
                    kill_cols = [c for c in df_matrix.columns if "(決)" in c]
                    st.dataframe(
                        df_matrix.style
                        .format("{:.1f}%")
                        .background_gradient(cmap="Oranges", subset=dist_cols, vmin=0, vmax=100)
                        .background_gradient(cmap="Blues", subset=kill_cols, vmin=0, vmax=100),
                        use_container_width=True
                    )

            st.markdown("---")
            st.markdown(f"### 🎯 セットアップ位置の散布図")
            try:
                pil_img = get_court_image()
                fig, ax = plt.subplots(figsize=(10, 6))
                ax.imshow(pil_img, extent=[0, 500, 500, 0])
                zones_in_data = df_filtered["Zone"].unique()
                for zone in zones_in_data:
                    if zone == "なし": continue
                    subset = df_filtered[df_filtered["Zone"] == zone]
                    color_info = ZONE_COLORS.get(zone, ("gray", zone))
                    ax.scatter(subset["X"], subset["Y"], label=color_info[1], color=color_info[0], s=120, alpha=0.8, edgecolors='white')
                ax.legend(loc='upper right', title="Toss Direction")
                ax.axis('off')
                st.pyplot(fig)
            except Exception as e:
                st.error(f"画像描画エラー: {e}")

# --- モード3：履歴編集 ---
elif app_mode == "📝 履歴編集":
    st.header("📝 履歴データの閲覧・編集")
    df_all = load_match_history()
    if df_all.empty:
        st.info("保存されたデータがまだありません。")
    else:
        if "Match" in df_all.columns:
            match_list = sorted(df_all["Match"].unique(), reverse=True)
            selected_match = st.selectbox("編集する試合を選択してください", match_list)
            df_match = df_all[df_all["Match"] == selected_match].copy()
            st.write(f"▼ {selected_match} のデータ ({len(df_match)}件)")
            edited_df = st.data_editor(df_match, num_rows="dynamic", use_container_width=True, height=400, key="editor")
            c_s, c_d = st.columns([1, 1])
            with c_s:
                if st.button("💾 変更を保存する", type="primary"):
                    df_others = df_all[df_all["Match"] != selected_match]
                    df_new_all = pd.concat([df_others, edited_df], ignore_index=True)
                    overwrite_history_sheet(df_new_all)
                    st.success("保存しました！")
                    st.rerun()
            with c_d:
                with st.expander("🗑 削除"):
                    if st.button("削除実行"):
                        df_rem = df_all[df_all["Match"] != selected_match]
                        overwrite_history_sheet(df_rem)
                        st.success("削除しました")
                        st.rerun()
        else: st.error("Match列なし")

# --- モード4：試合入力 ---
elif app_mode == "📊 試合入力":
    image = get_court_image()
    col_sc, col_mn, col_lg = st.columns([0.8, 1.2, 0.8])
    with col_sc:
        gs = st.session_state.game_state
        
        # スコアボード
        st.markdown(f"""
        <div style="text-align: center; border: 2px solid #ccc; padding: 10px; border-radius: 10px; margin-bottom: 10px;">
            <h1 style="margin:0;">{gs['my_score']} - {gs['op_score']}</h1>
            <div style="display:flex; justify-content:space-between;">
                <div style="color:blue; font-weight:bold;">{my_team_name}<br>Rot:{gs['my_rot']}</div>
                <div style="color:grey;">{op_team_name}<br>Rot:{gs['op_rot']}</div>
            </div>
        </div>
        """, unsafe_allow_html=True)
        
        # ★現在のローテーション表示 (Visual)
        if st.session_state.my_service_order:
            pos_map = get_current_positions(st.session_state.my_service_order, gs['my_rot'])
            
            # HTMLで簡易的なコート表示を作る
            st.markdown("""
            <style>
                .court-grid { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 5px; border: 1px solid #ccc; padding: 5px; background: #f9f9f9; text-align: center; font-size: 0.8em; }
                .court-cell { padding: 5px; border-radius: 5px; background: white; border: 1px solid #ddd; }
                .court-net { grid-column: 1 / 4; border-bottom: 3px double #333; margin-bottom: 5px; font-weight: bold; }
                .pos-label { font-size: 0.7em; color: #888; display: block; }
                .player-name { font-weight: bold; color: #000; }
            </style>
            <div class="court-grid">
                <div class="court-net">NET (Front)</div>
                <div class="court-cell"><span class="pos-label">P4 (FL)</span><span class="player-name">{}</span></div>
                <div class="court-cell"><span class="pos-label">P3 (FC)</span><span class="player-name">{}</span></div>
                <div class="court-cell"><span class="pos-label">P2 (FR)</span><span class="player-name">{}</span></div>
                
                <div class="court-cell"><span class="pos-label">P5 (BL)</span><span class="player-name">{}</span></div>
                <div class="court-cell"><span class="pos-label">P6 (BC)</span><span class="player-name">{}</span></div>
                <div class="court-cell" style="background:#e6f3ff;"><span class="pos-label">P1 (Srv)</span><span class="player-name">{}</span></div>
            </div>
            """.format(
                pos_map.get("P4(FL)", "?"), pos_map.get("P3(FC)", "?"), pos_map.get("P2(FR)", "?"),
                pos_map.get("P5(BL)", "?"), pos_map.get("P6(BC)", "?"), pos_map.get("P1(BR)", "?")
            ), unsafe_allow_html=True)
        
        with st.expander("試合設定", expanded=False):
            match_name = st.text_input("試合名", "練習試合")
            set_no = st.number_input("Set", 1, 5, 1)

    with col_mn:
        if not st.session_state.my_service_order:
            st.info("🏁 スターティングメンバー (Lineup) 設定")
            mp = sort_players_by_number(list(st.session_state.players_db[my_team_name].keys())) if my_team_name!="未設定" else []
            op = sort_players_by_number(list(st.session_state.players_db[op_team_name].keys())) if op_team_name!="未設定" else []
            c_m_bk, c_m_fr, c_net, c_o_fr, c_o_bk = st.columns([1.5, 1.5, 0.2, 1.5, 1.5])
            with c_net: st.markdown("<div style='height:300px; border-left: 3px dashed #888; margin-left: 50%;'></div>", unsafe_allow_html=True)
            with c_m_bk:
                st.caption(f"{my_team_name} 後衛")
                m5 = st.selectbox("P5 (BL)", mp, key="m5", index=4 if len(mp)>4 else 0)
                m6 = st.selectbox("P6 (BC)", mp, key="m6", index=5 if len(mp)>5 else 0)
                m1 = st.selectbox("P1 (BR/Serve)", mp, key="m1", index=0)
            with c_m_fr:
                st.caption("前衛 (Net)")
                m4 = st.selectbox("P4 (FL)", mp, key="m4", index=3 if len(mp)>3 else 0)
                m3 = st.selectbox("P3 (FC)", mp, key="m3", index=2 if len(mp)>2 else 0)
                m2 = st.selectbox("P2 (FR)", mp, key="m2", index=1 if len(mp)>1 else 0)
            with c_o_fr:
                st.caption(f"前衛 (Net)")
                if op:
                    o2 = st.selectbox("P2 (FR)", op, key="o2", index=1 if len(op)>1 else 0)
                    o3 = st.selectbox("P3 (FC)", op, key="o3", index=2 if len(op)>2 else 0)
                    o4 = st.selectbox("P4 (FL)", op, key="o4", index=3 if len(op)>3 else 0)
                else: o2=o3=o4=None; st.write("未登録")
            with c_o_bk:
                st.caption(f"{op_team_name} 後衛")
                if op:
                    o1 = st.selectbox("P1 (BR/Serve)", op, key="o1", index=0)
                    o6 = st.selectbox("P6 (BC)", op, key="o6", index=5 if len(op)>5 else 0)
                    o5 = st.selectbox("P5 (BL)", op, key="o5", index=4 if len(op)>4 else 0)
                else: o1=o6=o5=None; st.write("未登録")
            st.markdown("---")
            c_lib1, c_lib2 = st.columns(2)
            with c_lib1: ml = st.selectbox(f"リベロ ({my_team_name})", ["なし"]+mp, key="ml")
            with c_lib2: ol = st.selectbox(f"リベロ ({op_team_name})", ["なし"]+op, key="ol") if op else "なし"
            st.markdown("<br>", unsafe_allow_html=True)
            st.caption("最初のサーブ権")
            first_srv_label = st.radio("First Serve", [my_team_name, op_team_name], horizontal=True, label_visibility="collapsed")
            first_srv_key = "My Team" if first_srv_label == my_team_name else "Opponent"
            if st.button("試合開始 (Lineup確定)", type="primary"):
                st.session_state.my_service_order = [m1, m2, m3, m4, m5, m6]
                st.session_state.op_service_order = [o1, o2, o3, o4, o5, o6] if op else []
                st.session_state.my_libero = ml; st.session_state.op_libero = ol
                st.session_state.game_state["serve_rights"] = first_srv_key
                st.rerun()
        else:
            with st.expander("🛠 点数・ローテ手動修正", expanded=False):
                c_m_all, c_o_all = st.columns(2)
                with c_m_all:
                    st.caption(f"▼ {my_team_name}")
                    c_m1, c_m2, c_m3, c_m4 = st.columns(4)
                    if c_m1.button("＋1", key="m_p1"): add_point("My Team"); st.rerun()
                    if c_m2.button("－1", key="m_m1"): remove_point("My Team"); st.rerun()
                    if c_m3.button("次R", key="m_r_next"): rotate_team("my"); st.rerun()
                    if c_m4.button("前R", key="m_r_prev"): rotate_team_reverse("my"); st.rerun()
                with c_o_all:
                    st.caption(f"▼ {op_team_name}")
                    c_o1, c_o2, c_o3, c_o4 = st.columns(4)
                    if c_o1.button("＋1", key="o_p1"): add_point("Opponent"); st.rerun()
                    if c_o2.button("－1", key="o_m1"): remove_point("Opponent"); st.rerun()
                    if c_o3.button("次R", key="o_r_next"): rotate_team("op"); st.rerun()
                    if c_o4.button("前R", key="o_r_prev"): rotate_team_reverse("op"); st.rerun()

            active = list(st.session_state.my_service_order)
            if st.session_state.my_libero!="なし": active.append(st.session_state.my_libero)
            active_sorted = ["なし"] + sort_players_by_number(active)
            attack_zones = ["なし", "レフト(L)", "センター(C)", "ライト(R)", "レフトバック(LB)", "センターバック(CB)", "ライトバック(RB)"]
            
            st.markdown("##### 1. Reception")
            recep = st.radio("Pass", ["Aパス","Bパス","Cパス", "失敗 (エース)", "相手サーブミス", "その他"], horizontal=True, label_visibility="collapsed")
            
            is_input_needed = True
            if recep == "相手サーブミス":
                is_input_needed = False
                st.info("💡 相手サーブミスが選択されました。")
            else:
                st.markdown("##### 2. Attack Detail")
                c_set, c_zone = st.columns(2)
                setter_key = c_set.selectbox("Setter (トス)", active_sorted, key="setter")
                zone_key = c_zone.selectbox("Zone (トスを上げた場所)", attack_zones, key="zone")
                
                c_hitter, c_res = st.columns([1, 1])
                p_key = c_hitter.selectbox("Hitter (打った人)", active_sorted, key="hitter")
                res = c_res.selectbox("Result", ["なし", "得点 (Kill)", "効果", "継続", "失点 (Error)", "被ブロック"], key="res")

                st.write("👇 **トスを上げた位置（セットアップ位置）** をタップしてください")
                coords = streamlit_image_coordinates(image, width=500, key="click")
                if coords: st.session_state.temp_coords = coords
                if st.session_state.temp_coords: st.write(f"📍 座標選択済み: {st.session_state.temp_coords}")

            st.markdown("---")
            if st.button("📝 この内容で記録する", type="primary", use_container_width=True):
                if is_input_needed and not st.session_state.temp_coords:
                    st.error("⚠️ コートをクリックしてセットアップ位置を指定してください！")
                else:
                    final_coords = st.session_state.temp_coords if st.session_state.temp_coords else {"x":0, "y":0}
                    final_setter = setter_key if is_input_needed else "なし"
                    final_zone = zone_key if is_input_needed else "なし"
                    final_player = p_key if is_input_needed else "なし"
                    final_res = res if is_input_needed else "Opp Service Error"
                    
                    if recep == "失敗 (エース)": final_res = "Rec Error"
                    elif recep == "相手サーブミス": final_res = "Opp Service Error"

                    pos = st.session_state.players_db[my_team_name].get(final_player, "?")
                    
                    rec = {
                        "Match": f"{datetime.date.today()}_{match_name}",
                        "Set": set_no,
                        "Team": my_team_name,
                        "MyScore": gs['my_score'],
                        "OpScore": gs['op_score'],
                        "Rot": gs['my_rot'],
                        "Pass": recep,
                        "Setter": final_setter,
                        "Zone": final_zone,
                        "Player": final_player,
                        "Pos": pos,
                        "Result": final_res,
                        "X": final_coords["x"], "Y": final_coords["y"]
                    }
                    st.session_state.match_data.append(rec)
                    if recep == "失敗 (エース)": add_point("Opponent"); st.toast("Ace!")
                    elif recep == "相手サーブミス": add_point("My Team"); st.toast("Lucky!")
                    elif final_res == "得点 (Kill)": add_point("My Team"); st.toast("Nice Kill!")
                    elif final_res in ["失点 (Error)", "被ブロック"]: add_point("Opponent"); st.toast("Error...")
                    else: st.toast("記録しました")
                    st.session_state.temp_coords = None
                    st.rerun()

            with st.expander("🔄 メンバーチェンジ / リセット"):
                if st.button("全リセット (スタメン選択に戻る)"):
                    st.session_state.my_service_order = []
                    st.rerun()
                c_sub1, c_sub2 = st.columns(2)
                sub_pos = c_sub1.selectbox("位置", ["P1","P2","P3","P4","P5","P6"])
                all_p = sort_players_by_number(list(st.session_state.players_db[my_team_name].keys()))
                bench = [p for p in all_p if p not in st.session_state.my_service_order]
                sub_in = c_sub2.selectbox("IN", bench) if bench else None
                if st.button("交代実行"):
                    if sub_in:
                        idx = int(sub_pos[1]) - 1
                        old = st.session_state.my_service_order[idx]
                        st.session_state.my_service_order[idx] = sub_in
                        st.success(f"交代: {old} ➔ {sub_in}")
                        st.rerun()

    with col_lg:
        st.header("3. Log")
        
        # ★Undoボタン
        if st.session_state.match_data:
            if st.button("↩️ 1つ戻る (Undo)"):
                st.session_state.match_data.pop()
                st.warning("直前の記録を削除")
                st.rerun()
        
        # ★リストと送信ボタン (常に表示し、データがないときはdisabledにする)
        if st.session_state.match_data:
            df = pd.DataFrame(st.session_state.match_data)
            cols_to_show = ["MyScore", "Pass", "Setter", "Zone", "Result"]
            valid_cols = [c for c in cols_to_show if c in df.columns]
            st.dataframe(df[valid_cols].iloc[::-1], height=300, hide_index=True)
            
            # データがある時
            if st.button("💾 データ送信 (保存してリストをクリア)", type="primary"):
                save_match_data_to_sheet(df)
                st.success("クラウド保存完了")
                st.session_state.match_data = []
                st.rerun()
        else:
            st.info("記録待ち...")
            # データがない時は押せないボタンを表示しておく
            st.button("💾 データ送信 (保存してリストをクリア)", disabled=True)
