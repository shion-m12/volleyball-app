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
st.set_page_config(layout="wide", page_title="Volleyball Analyst Pro v42 (Manual)")

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
PASS_ORDER = ["Aパス", "Bパス", "Cパス", "その他", "相手サーブミス", "失敗 (エース)"]
ZONE_ORDER = ["レフト(L)", "センター(C)", "ライト(R)", "レフトバック(LB)", "センターバック(CB)", "ライトバック(RB)", "なし"]

# --- Google API 接続設定 ---
def get_gcp_creds():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    try:
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        return creds
    except Exception as e:
        st.error(f"認証エラー: secrets.tomlを確認してください。 {e}")
        st.stop()

def connect_to_gsheet():
    creds = get_gcp_creds()
    client = gspread.authorize(creds)
    # スプレッドシートID (固定)
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
        # シートがない場合は作成して初期データを返す
        worksheet = sheet.add_worksheet(title="players", rows="100", cols="5")
        worksheet.append_row(["Team", "PlayerKey", "Position"])
        return {}

def save_players_to_sheet(players_dict):
    sheet = connect_to_gsheet()
    try:
        worksheet = sheet.worksheet("players")
    except:
        worksheet = sheet.add_worksheet(title="players", rows="100", cols="5")
        
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

def load_match_history():
    sheet = connect_to_gsheet()
    try:
        worksheet = sheet.worksheet("history")
        data = worksheet.get_all_values()
        if not data: return pd.DataFrame()
        headers = data[0]
        rows = data[1:]
        if not rows: return pd.DataFrame(columns=headers)
        return pd.DataFrame(rows, columns=headers)
    except Exception:
        return pd.DataFrame()

# --- ユーティリティ関数 ---
def sort_players_by_number(player_names):
    def get_num(name):
        match = re.search(r'#(\d+)', name)
        return int(match.group(1)) if match else 999
    return sorted(player_names, key=get_num)

def get_court_image():
    if os.path.exists("court.png"):
        try:
            img = Image.open("court.png")
            return img
        except: pass
    img = Image.new('RGB', (500, 500), color='#FFCC99')
    draw = ImageDraw.Draw(img)
    w, h = 500, 500
    draw.rectangle([0, 0, w-1, h-1], outline='white', width=5)
    draw.line([0, h/2, w, h/2], fill='white', width=3)
    draw.line([0, h/2 - 80, w, h/2 - 80], fill='white', width=2)
    draw.line([0, h/2 + 80, w, h/2 + 80], fill='white', width=2)
    img.save("court.png")
    return img

# --- ステート管理 ---
if 'players_db' not in st.session_state: st.session_state.players_db = load_players_from_sheet()
if 'match_data' not in st.session_state: st.session_state.match_data = []
if 'my_service_order' not in st.session_state: st.session_state.my_service_order = []
if 'op_service_order' not in st.session_state: st.session_state.op_service_order = []
if 'my_libero' not in st.session_state: st.session_state.my_libero = "なし"
if 'op_libero' not in st.session_state: st.session_state.op_libero = "なし"
if 'game_state' not in st.session_state: st.session_state.game_state = {"my_score": 0, "op_score": 0, "serve_rights": "My Team", "my_rot": 1, "op_rot": 1}
if 'temp_coords' not in st.session_state: st.session_state.temp_coords = None

# ローテーション管理
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

def get_current_positions(service_order, rotation):
    if not service_order or len(service_order) < 6: return {}
    r_idx = rotation - 1
    # ローテーションによる位置の計算 (配列インデックスとの対応)
    indices = {
        "P4(FL)": (3 + r_idx) % 6, "P3(FC)": (2 + r_idx) % 6, "P2(FR)": (1 + r_idx) % 6,
        "P5(BL)": (4 + r_idx) % 6, "P6(BC)": (5 + r_idx) % 6, "P1(BR)": (0 + r_idx) % 6,
    }
    return {k: service_order[v] for k, v in indices.items()}

# ==========================================
#  UI サイドバー
# ==========================================
with st.sidebar:
    st.title("🏐 Analyst Pro v42 (Manual)")
    app_mode = st.radio("メニュー", ["📊 試合入力", "👤 チーム・選手管理", "📝 履歴データ確認"])
    st.markdown("---")
    
    # チーム選択
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
                st.toast("データ保存しました！")
            # リセット処理
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
if app_mode == "👤 チーム・選手管理":
    st.header("👤 チーム・選手管理")
    
    # チーム追加
    with st.expander("➕ 新しいチームを追加"):
        c1, c2 = st.columns([2, 1])
        new_team = c1.text_input("チーム名")
        if c2.button("追加"):
            if new_team and new_team not in st.session_state.players_db:
                st.session_state.players_db[new_team] = {}
                save_players_to_sheet(st.session_state.players_db)
                st.success(f"{new_team} 追加しました")
                st.rerun()

    # 選手編集
    if team_list:
        tgt_team = st.selectbox("編集するチームを選択", team_list)
        members = st.session_state.players_db[tgt_team]
        
        # 一覧表示
        p_list = [{"No.": (int(re.search(r'#(\d+)', k).group(1)) if re.search(r'#(\d+)', k) else 999), "Name": k, "Pos": v} for k,v in members.items()]
        df_p = pd.DataFrame(p_list).sort_values("No.") if p_list else pd.DataFrame()
        st.write(f"▼ {tgt_team} の選手一覧")
        st.dataframe(df_p, hide_index=True, use_container_width=True)
        
        tab_add, tab_del = st.tabs(["選手登録", "選手削除"])
        
        with tab_add:
            c_n, c_nm, c_pos = st.columns([1, 2, 1])
            num = c_n.text_input("背番号 (数字のみ)", key="a_no")
            nm = c_nm.text_input("名前", key="a_nm")
            pos = c_pos.selectbox("ポジション", ["OH","MB","OP","S","L","R"], key="a_pos")
            
            if st.button("登録"):
                if num and nm:
                    key = f"#{num} {nm}"
                    st.session_state.players_db[tgt_team][key] = pos
                    save_players_to_sheet(st.session_state.players_db)
                    st.success(f"{key} を登録しました")
                    st.rerun()
                else:
                    st.error("背番号と名前を入力してください")
                    
        with tab_del:
            if members:
                del_tgt = st.selectbox("削除する選手", sort_players_by_number(list(members.keys())))
                if st.button("削除実行"):
                    del st.session_state.players_db[tgt_team][del_tgt]
                    save_players_to_sheet(st.session_state.players_db)
                    st.warning("削除しました")
                    st.rerun()
            else:
                st.info("選手が登録されていません")

# --- モード2：試合入力 ---
elif app_mode == "📊 試合入力":
    image = get_court_image()
    col_sc, col_mn, col_lg = st.columns([0.8, 1.2, 0.8])
    
    # 1. スコアボード & コート図
    with col_sc:
        gs = st.session_state.game_state
        
        # サーブ権の表示
        srv_my = "🏐" if gs['serve_rights'] == "My Team" else ""
        srv_op = "🏐" if gs['serve_rights'] == "Opponent" else ""
        
        st.markdown(f"""
        <div style="text-align: center; border: 2px solid #333; padding: 10px; border-radius: 10px; margin-bottom: 10px; background-color: #f0f2f6;">
            <div style="font-size: 1.5em; font-weight: bold;">{srv_my} {gs['my_score']} - {gs['op_score']} {srv_op}</div>
            <div style="display:flex; justify-content:space-between; margin-top: 5px;">
                <div style="color:blue; font-weight:bold;">{my_team_name}<br>Rot: {gs['my_rot']}</div>
                <div style="color:red; font-weight:bold;">{op_team_name}<br>Rot: {gs['op_rot']}</div>
            </div>
        </div>
        """, unsafe_allow_html=True)

        if st.session_state.my_service_order:
            pos_map = get_current_positions(st.session_state.my_service_order, gs['my_rot'])
            # コート上の配置を表示 (簡易グリッド)
            st.markdown(f"""
            <style>
                .court-grid {{ display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 4px; border: 2px solid #333; padding: 5px; background: #fff; text-align: center; font-size: 0.8em; }}
                .court-cell {{ padding: 8px 2px; border-radius: 4px; background: #eef; border: 1px solid #ccc; min-height: 50px; display: flex; flex-direction: column; justify-content: center; }}
                .pos-label {{ font-size: 0.7em; color: #666; }}
                .p-name {{ font-weight: bold; color: #000; font-size: 0.9em; }}
            </style>
            <div class="court-grid">
                <div style="grid-column: 1/4; border-bottom: 3px double #333; margin-bottom: 5px; font-weight:bold;">NET (Front)</div>
                <div class="court-cell"><span class="pos-label">P4(FL)</span><span class="p-name">{pos_map.get("P4(FL)","?")}</span></div>
                <div class="court-cell"><span class="pos-label">P3(FC)</span><span class="p-name">{pos_map.get("P3(FC)","?")}</span></div>
                <div class="court-cell"><span class="pos-label">P2(FR)</span><span class="p-name">{pos_map.get("P2(FR)","?")}</span></div>
                <div class="court-cell"><span class="pos-label">P5(BL)</span><span class="p-name">{pos_map.get("P5(BL)","?")}</span></div>
                <div class="court-cell"><span class="pos-label">P6(BC)</span><span class="p-name">{pos_map.get("P6(BC)","?")}</span></div>
                <div class="court-cell" style="background:#ffe;"><span class="pos-label">P1(Srv)</span><span class="p-name">{pos_map.get("P1(BR)","?")}</span></div>
            </div>
            """, unsafe_allow_html=True)
            
        with st.expander("試合設定", expanded=False):
            match_name = st.text_input("試合名", "練習試合")
            set_no = st.number_input("セット", 1, 5, 1)

    # 2. メイン操作パネル
    with col_mn:
        # スタメン未設定の場合
        if not st.session_state.my_service_order:
            st.info("🏁 スターティングメンバー (Lineup) を設定してください")
            
            # 自チームメンバーリスト
            mp = sort_players_by_number(list(st.session_state.players_db[my_team_name].keys())) if my_team_name!="未設定" else []
            if not mp: st.warning("「チーム管理」で選手を登録してください"); st.stop()
            
            c_f, c_b = st.columns(2)
            with c_f:
                st.caption("前衛")
                m4 = st.selectbox("P4 (FL)", mp, index=3 if len(mp)>3 else 0)
                m3 = st.selectbox("P3 (FC)", mp, index=2 if len(mp)>2 else 0)
                m2 = st.selectbox("P2 (FR)", mp, index=1 if len(mp)>1 else 0)
            with c_b:
                st.caption("後衛")
                m5 = st.selectbox("P5 (BL)", mp, index=4 if len(mp)>4 else 0)
                m6 = st.selectbox("P6 (BC)", mp, index=5 if len(mp)>5 else 0)
                m1 = st.selectbox("P1 (BR/Srv)", mp, index=0)
            
            st.markdown("---")
            ml = st.selectbox("リベロ", ["なし"]+mp)
            
            # 相手チーム (簡易)
            st.caption("相手チーム設定 (任意)")
            op = sort_players_by_number(list(st.session_state.players_db[op_team_name].keys())) if op_team_name!="未設定" else []
            
            first_srv = st.radio("最初のサーブ権", [my_team_name, op_team_name], horizontal=True)
            
            if st.button("試合開始 (確定)", type="primary"):
                st.session_state.my_service_order = [m1, m2, m3, m4, m5, m6]
                st.session_state.op_service_order = [p for p in op[:6]] if len(op)>=6 else []
                st.session_state.my_libero = ml
                st.session_state.game_state["serve_rights"] = "My Team" if first_srv == my_team_name else "Opponent"
                st.rerun()
        
        # 試合中画面
        else:
            # 点数操作パネル
            with st.expander("🛠 点数・ローテ手動修正", expanded=False):
                c1, c2, c3, c4 = st.columns(4)
                if c1.button("＋1 (自)"): add_point("My Team"); st.rerun()
                if c2.button("－1 (自)"): remove_point("My Team"); st.rerun()
                if c3.button("＋1 (敵)"): add_point("Opponent"); st.rerun()
                if c4.button("－1 (敵)"): remove_point("Opponent"); st.rerun()
                c5, c6 = st.columns(2)
                if c5.button("ローテ回す (自)"): rotate_team("my"); st.rerun()
                if c6.button("ローテ戻す (自)"): rotate_team_reverse("my"); st.rerun()

            # データ入力フォーム
            st.write("##### プレー記録")
            
            # 選択肢の準備
            active_players = list(st.session_state.my_service_order)
            if st.session_state.my_libero != "なし":
                active_players.append(st.session_state.my_libero)
            active_sorted = ["なし"] + sort_players_by_number(active_players)
            
            # 入力項目
            col_in1, col_in2 = st.columns(2)
            pass_val = col_in1.selectbox("レセプション (Pass)", PASS_ORDER)
            setter_val = col_in2.selectbox("セッター (Setter)", active_sorted)
            
            col_in3, col_in4 = st.columns(2)
            zone_val = col_in3.selectbox("トス配給 (Zone)", ZONE_ORDER)
            hitter_val = col_in4.selectbox("アタッカー (Hitter)", active_sorted)
            
            res_val = st.radio("結果 (Result)", ["得点 (Kill)", "継続 (Cont)", "失点 (Err)", "被ブロック (Blk)"], horizontal=True)

            # トス位置のクリック入力
            st.caption("👇 トスを上げた位置（セットアップ位置）をタップ")
            coords = streamlit_image_coordinates(image, width=500, key="click")
            if coords: st.session_state.temp_coords = coords
            
            if st.session_state.temp_coords:
                st.success(f"📍 位置を選択済み: {st.session_state.temp_coords}")
            
            # 登録ボタン
            if st.button("📝 記録する", type="primary", use_container_width=True):
                if not st.session_state.temp_coords:
                    st.error("コート図をタップして位置を指定してください")
                else:
                    # データの保存
                    final_pos = st.session_state.players_db[my_team_name].get(hitter_val, "?")
                    
                    rec = {
                        "Time": datetime.datetime.now().strftime("%H:%M:%S"),
                        "Set": set_no,
                        "MyScore": gs['my_score'],
                        "OpScore": gs['op_score'],
                        "Rot": gs['my_rot'],
                        "Pass": pass_val,
                        "Setter": setter_val,
                        "Zone": zone_val,
                        "Hitter": hitter_val,
                        "Pos": final_pos,
                        "Result": res_val,
                        "X": st.session_state.temp_coords["x"],
                        "Y": st.session_state.temp_coords["y"]
                    }
                    st.session_state.match_data.append(rec)
                    
                    # 自動点数加算
                    if res_val == "得点 (Kill)":
                        add_point("My Team")
                        st.toast("Nice Kill! (+1点)")
                    elif res_val in ["失点 (Err)", "被ブロック (Blk)"]:
                        add_point("Opponent")
                        st.toast("Don't mind... (相手+1点)")
                    elif pass_val == "失敗 (エース)":
                        add_point("Opponent")
                        st.toast("Service Ace... (相手+1点)")
                    elif pass_val == "相手サーブミス":
                        add_point("My Team")
                        st.toast("Lucky! (+1点)")
                    else:
                        st.toast("記録しました")
                        
                    st.session_state.temp_coords = None
                    st.rerun()

            # メンバーチェンジ機能
            with st.expander("🔄 メンバーチェンジ (交代)"):
                c_sub1, c_sub2 = st.columns(2)
                sub_pos_idx = c_sub1.selectbox("交代するポジション", 
                    options=[0,1,2,3,4,5], 
                    format_func=lambda x: f"P{pos_map.get(f'P{x+1}({["BR","FR","FC","FL","BL","BC"][x]})', '?')[:2]} ({st.session_state.my_service_order[x]})"
                )
                
                # ベンチメンバー（コートにいない選手）
                all_p = sort_players_by_number(list(st.session_state.players_db[my_team_name].keys()))
                bench = [p for p in all_p if p not in st.session_state.my_service_order and p != st.session_state.my_libero]
                
                sub_in = c_sub2.selectbox("IN (入る選手)", bench) if bench else None
                
                if st.button("交代実行"):
                    if sub_in:
                        out_player = st.session_state.my_service_order[sub_pos_idx]
                        st.session_state.my_service_order[sub_pos_idx] = sub_in
                        st.success(f"交代: {out_player} ➔ {sub_in}")
                        st.rerun()
                    else:
                        st.error("交代できる選手がいません")

    # 3. 履歴ログ
    with col_lg:
        st.header("Log")
        if st.session_state.match_data:
            # 1つ戻るボタン
            if st.button("↩️ 1つ戻る (Undo)"):
                st.session_state.match_data.pop()
                # 点数も戻す処理を入れると完璧だが複雑になるため今回はデータ削除のみ
                st.warning("直前の記録を削除しました（点数は手動で戻してください）")
                st.rerun()
                
            df = pd.DataFrame(st.session_state.match_data)
            # 表示するカラム
            cols = ["MyScore", "Pass", "Setter", "Zone", "Result"]
            st.dataframe(df[cols].iloc[::-1], height=400, hide_index=True)
            
            # CSVダウンロード
            csv = df.to_csv(index=False).encode('utf-8')
            st.download_button("📥 CSVダウンロード", csv, "match_log.csv", "text/csv")

# --- モード3：履歴データ確認 ---
elif app_mode == "📝 履歴データ確認":
    st.header("📝 保存済みデータの確認")
    df_history = load_match_history()
    
    if not df_history.empty:
        st.dataframe(df_history, use_container_width=True)
        st.info("※ ここは閲覧専用です。編集はGoogle Sheetsで行ってください。")
    else:
        st.info("保存されたデータはまだありません。")
