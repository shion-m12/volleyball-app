import streamlit as st
import pandas as pd
from streamlit_image_coordinates import streamlit_image_coordinates
from PIL import Image, ImageDraw
import datetime
import re
import os
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
import io
import matplotlib.pyplot as plt
import matplotlib.image as mpimg
import cv2
import tempfile
from ultralytics import YOLO
import numpy as np
import math

# --- 設定 ---
st.set_page_config(layout="wide", page_title="Volleyball Analyst Pro v37.1")

# ★★★ 設定済み: あなたのGoogleドライブ共有フォルダID ★★★
TARGET_FOLDER_ID = "1F1hTSQcYV3QRpz0PBrx5m4U-9TxE_bgE"

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

# キーポイントID (YOLOv8 Pose)
KP_NOSE = 0
KP_R_WRIST = 10
KP_L_WRIST = 9
KP_R_ANKLE = 16
KP_L_ANKLE = 15

KEYPOINT_NAMES = {
    0: "Nose", 1: "L-Eye", 2: "R-Eye", 3: "L-Ear", 4: "R-Ear",
    5: "L-Shoulder", 6: "R-Shoulder", 7: "L-Elbow", 8: "R-Elbow",
    9: "L-Wrist", 10: "R-Wrist", 11: "L-Hip", 12: "R-Hip",
    13: "L-Knee", 14: "R-Knee", 15: "L-Ankle", 16: "R-Ankle"
}

# --- AIモデルのロード ---
@st.cache_resource
def load_models():
    pose_model = YOLO('yolov8n-pose.pt')
    det_model = YOLO('yolov8n.pt') 
    return pose_model, det_model

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

# --- Google API 接続設定 (Sheets & Drive) ---
def get_gcp_creds():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    try:
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        return creds
    except Exception as e:
        st.error(f"認証エラー: Secretsの設定を確認してください。 {e}")
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

def connect_to_drive():
    creds = get_gcp_creds()
    service = build('drive', 'v3', credentials=creds)
    return service

# --- Drive 操作関数 (共有フォルダ対応版) ---
def list_drive_files(folder_id):
    service = connect_to_drive()
    query = f"'{folder_id}' in parents and mimeType contains 'video' and trashed=false"
    try:
        results = service.files().list(
            q=query,
            pageSize=20, fields="nextPageToken, files(id, name, createdTime)").execute()
        items = results.get('files', [])
        return items
    except Exception as e:
        if "404" in str(e) or "File not found" in str(e):
            st.error("🚨 エラー: 指定されたフォルダが見つかりません。")
            st.warning("サイドバーのメールアドレスをGoogleドライブで招待してください。")
        else:
            st.error(f"Driveアクセスエラー: {e}")
        return []

def download_file_from_drive(file_id):
    service = connect_to_drive()
    request = service.files().get_media(fileId=file_id)
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while done is False:
        status, done = downloader.next_chunk()
    fh.seek(0)
    return fh

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

# ★動画パス保存用のセッションステート
if 'analysis_video_path' not in st.session_state: st.session_state.analysis_video_path = None

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
    indices = {
        "P4(FL)": (3 + r_idx) % 6, "P3(FC)": (2 + r_idx) % 6, "P2(FR)": (1 + r_idx) % 6,
        "P5(BL)": (4 + r_idx) % 6, "P6(BC)": (5 + r_idx) % 6, "P1(BR)": (0 + r_idx) % 6,
    }
    return {k: service_order[v] for k, v in indices.items()}

# ==========================================
#  UI サイドバー
# ==========================================
with st.sidebar:
    st.title("🏐 Analyst Pro v37.1")
    app_mode = st.radio("メニュー", ["🎥 AI動作分析 (Drive)", "📊 試合入力", "📈 トス配給分析", "📝 履歴編集", "👤 チーム管理"])
    st.markdown("---")
    
    try:
        creds_info = dict(st.secrets["gcp_service_account"])
        sa_email = creds_info.get("client_email", "不明")
        st.caption("📧 このメアドをフォルダに招待してください:")
        st.code(sa_email, language=None)
    except:
        st.error("Secretsの設定エラー")

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

# --- モード3：AI動作分析 (Drive連携・修正版) ---
elif app_mode == "🎥 AI動作分析 (Drive)":
    st.header("🎥 AIによる自動動作判定 (Back View)")
    
    with st.expander("🛠 エンドラインの設定 (判定基準)", expanded=True):
        end_line_percent_y = st.slider("エンドライン位置 (上端=0, 下端=100)", 0, 100, 80)
        st.caption(f"上から {end_line_percent_y}% の位置より下側を「サーブエリア」とみなします。")

    # ソース選択
    source_type = st.radio("動画ソース", ["📤 PCからアップロード", "📂 クラウド(Drive)から選択"], horizontal=True)
    
    # 1. PCアップロード
    if source_type == "📤 PCからアップロード":
        video_file = st.file_uploader("動画ファイルを選択 (mp4, mov)", type=['mp4', 'mov'])
        if video_file:
            tfile = tempfile.NamedTemporaryFile(delete=False)
            tfile.write(video_file.read())
            st.session_state.analysis_video_path = tfile.name # パスを保存
            st.success("アップロード完了")

    # 2. Driveロード
    elif source_type == "📂 クラウド(Drive)から選択":
        if len(TARGET_FOLDER_ID) < 10:
            st.error("【設定未完了】コード内の `TARGET_FOLDER_ID` に、Googleドライブの共有フォルダIDを入力してください。")
        else:
            if st.button("フォルダ内のリストを更新"):
                pass 
            
            try:
                files = list_drive_files(TARGET_FOLDER_ID)
                if files:
                    file_options = {f['name']: f['id'] for f in files}
                    selected_filename = st.selectbox("解析する動画を選択", list(file_options.keys()))
                    
                    if selected_filename:
                        if st.button("動画をロードして解析準備"):
                            with st.spinner("クラウドからダウンロード中..."):
                                file_id = file_options[selected_filename]
                                fh = download_file_from_drive(file_id)
                                tfile = tempfile.NamedTemporaryFile(delete=False)
                                tfile.write(fh.read())
                                st.session_state.analysis_video_path = tfile.name # パスを保存
                                st.success(f"「{selected_filename}」をロードしました！解析ボタンを押してください。")
                else:
                    st.warning("フォルダに動画が見つかりません。")
            except Exception as e:
                st.error(f"Driveエラー: {e}")

    # 解析実行部分 (パスがある場合のみ表示)
    if st.session_state.analysis_video_path:
        st.write("---")
        st.video(st.session_state.analysis_video_path) # 動画プレビュー
        
        if st.button("🚀 解析・自動判定開始", type="primary"):
            st.text("モデルをロード中... (これには数分かかる場合があります)")
            try:
                pose_model, det_model = load_models()
                # セッションステートからパスを取得
                cap = cv2.VideoCapture(st.session_state.analysis_video_path)
                st_frame = st.empty()
                
                width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                progress_bar = st.progress(0)
                
                detected_events = []
                raw_pose_data = []
                frame_count = 0
                skip_frames = 2
                cooldown = 0
                
                while cap.isOpened():
                    ret, frame = cap.read()
                    if not ret: break
                    
                    frame_count += 1
                    if cooldown > 0: cooldown -= 1
                    if frame_count % skip_frames != 0: continue
                    
                    ball_results = det_model(frame, classes=[32], conf=0.3, verbose=False)
                    ball_box = None
                    if len(ball_results[0].boxes) > 0:
                        box = ball_results[0].boxes[0]
                        bx1, by1, bx2, by2 = box.xyxy[0].cpu().numpy()
                        ball_cx, ball_cy = (bx1+bx2)/2, (by1+by2)/2
                        ball_box = (ball_cx, ball_cy)
                        cv2.circle(frame, (int(ball_cx), int(ball_cy)), 10, (0, 255, 255), -1)

                    pose_results = pose_model(frame, conf=0.5, verbose=False)
                    annotated_frame = pose_results[0].plot()
                    action_text = ""
                    
                    if pose_results[0].keypoints is not None:
                        keypoints_tensor = pose_results[0].keypoints.xy.cpu().numpy()
                        
                        for person_id, kpts in enumerate(keypoints_tensor):
                            row_data = {"Frame": frame_count, "PersonID": person_id}
                            if ball_box:
                                row_data["Ball_X"] = ball_box[0]; row_data["Ball_Y"] = ball_box[1]
                            else:
                                row_data["Ball_X"] = 0; row_data["Ball_Y"] = 0
                            for kp_idx, (x, y) in enumerate(kpts):
                                part_name = KEYPOINT_NAMES.get(kp_idx, f"kp{kp_idx}")
                                row_data[f"{part_name}_X"] = x; row_data[f"{part_name}_Y"] = y
                            raw_pose_data.append(row_data)
                            
                            if ball_box is None: continue
                            nose = kpts[KP_NOSE]
                            r_wrist = kpts[KP_R_WRIST]
                            l_wrist = kpts[KP_L_WRIST]
                            r_ankle = kpts[KP_R_ANKLE]
                            
                            if nose[0]==0 or r_wrist[0]==0: continue
                            
                            dist_r = math.hypot(ball_box[0] - r_wrist[0], ball_box[1] - r_wrist[1])
                            dist_l = math.hypot(ball_box[0] - l_wrist[0], ball_box[1] - l_wrist[1])
                            
                            impact_threshold = 80
                            is_hit = (dist_r < impact_threshold) or (dist_l < impact_threshold)
                            is_overhand = (r_wrist[1] < nose[1]) or (l_wrist[1] < nose[1])
                            
                            if is_hit and is_overhand and cooldown == 0:
                                line_y = height * (end_line_percent_y / 100)
                                if r_ankle[1] > line_y:
                                    action_text = "SERVE 🏐"
                                    detected_events.append({"Frame": frame_count, "Time": f"{frame_count/30:.1f}s", "Action": "Serve"})
                                else:
                                    action_text = "SPIKE 💥"
                                    detected_events.append({"Frame": frame_count, "Time": f"{frame_count/30:.1f}s", "Action": "Spike"})
                                cooldown = 15
                                break 
                    
                    if action_text:
                        cv2.putText(annotated_frame, action_text, (50, 100), cv2.FONT_HERSHEY_SIMPLEX, 2, (0, 0, 255), 5)
                    
                    line_y_int = int(height * (end_line_percent_y / 100))
                    cv2.line(annotated_frame, (0, line_y_int), (width, line_y_int), (255, 0, 0), 2)

                    annotated_frame = cv2.cvtColor(annotated_frame, cv2.COLOR_BGR2RGB)
                    st_frame.image(annotated_frame, caption=f"Frame: {frame_count}", use_container_width=True)
                    
                    if total_frames > 0:
                        progress_bar.progress(min(frame_count / total_frames, 1.0))
                
                cap.release()
                st.success("解析完了！")
                
                c_dl1, c_dl2 = st.columns(2)
                with c_dl1:
                    if detected_events:
                        st.write("##### 📊 検出イベント")
                        df_events = pd.DataFrame(detected_events)
                        st.dataframe(df_events, height=150)
                        csv_events = df_events.to_csv(index=False).encode('utf-8')
                        st.download_button("📥 イベントリストを保存 (CSV)", csv_events, "events.csv", "text/csv")
                    else:
                        st.warning("イベントは検出されませんでした。")
                with c_dl2:
                    if raw_pose_data:
                        st.write("##### 🦴 生座標データ (全フレーム)")
                        df_pose = pd.DataFrame(raw_pose_data)
                        st.dataframe(df_pose.head(3), height=150)
                        csv_pose = df_pose.to_csv(index=False).encode('utf-8')
                        st.download_button("📥 骨格座標データを保存 (CSV)", csv_pose, "pose_raw.csv", "text/csv")
                    else:
                        st.warning("骨格データが取得できませんでした。")
                
            except Exception as e:
                st.error(f"解析エラー: {e}")

# --- モード4：履歴編集 ---
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

# --- モード5：試合入力 ---
elif app_mode == "📊 試合入力":
    image = get_court_image()
    col_sc, col_mn, col_lg = st.columns([0.8, 1.2, 0.8])
    with col_sc:
        gs = st.session_state.game_state
        st.markdown(f"""
        <div style="text-align: center; border: 2px solid #ccc; padding: 10px; border-radius: 10px; margin-bottom: 10px;">
            <h1 style="margin:0;">{gs['my_score']} - {gs['op_score']}</h1>
            <div style="display:flex; justify-content:space-between;">
                <div style="color:blue; font-weight:bold;">{my_team_name}<br>Rot:{gs['my_rot']}</div>
                <div style="color:grey;">{op_team_name}<br>Rot:{gs['op_rot']}</div>
            </div>
        </div>
        """, unsafe_allow_html=True)
        if st.session_state.my_service_order:
            pos_map = get_current_positions(st.session_state.my_service_order, gs['my_rot'])
            st.markdown("""
            <style>
                .court-grid { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 5px; border: 1px solid #ccc; padding: 5px; background: #f9f9f9; text-align: center; font-size: 0.8em; }
                .court-cell { padding: 5px; border-radius: 5px; background: white; border: 1px solid #ddd; }
                .court-net { grid-column: 1 / 4; border-bottom: 3px double #333; margin-bottom: 5px; font-weight: bold; }
                .pos-label { font-size: 0.7em; color: #888; display: block; }
                .player-name { font-weight: bold; color: #000; }
            </style>
            """, unsafe_allow_html=True)
            grid_html = f"""
            <div class="court-grid">
                <div class="court-net">NET (Front)</div>
                <div class="court-cell"><span class="pos-label">P4 (FL)</span><span class="player-name">{pos_map.get("P4(FL)", "?")}</span></div>
                <div class="court-cell"><span class="pos-label">P3 (FC)</span><span class="player-name">{pos_map.get("P3(FC)", "?")}</span></div>
                <div class="court-cell"><span class="pos-label">P2 (FR)</span><span class="player-name">{pos_map.get("P2(FR)", "?")}</span></div>
                <div class="court-cell"><span class="pos-label">P5 (BL)</span><span class="player-name">{pos_map.get("P5(BL)", "?")}</span></div>
                <div class="court-cell"><span class="pos-label">P6 (BC)</span><span class="player-name">{pos_map.get("P6(BC)", "?")}</span></div>
                <div class="court-cell" style="background:#e6f3ff;"><span class="pos-label">P1 (Srv)</span><span class="player-name">{pos_map.get("P1(BR)", "?")}</span></div>
            </div>
            """
            st.markdown(grid_html, unsafe_allow_html=True)
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
        if st.session_state.match_data:
            if st.button("↩️ 1つ戻る (Undo)"):
                st.session_state.match_data.pop()
                st.warning("直前の記録を削除")
                st.rerun()
        if st.session_state.match_data:
            df = pd.DataFrame(st.session_state.match_data)
            cols_to_show = ["MyScore", "Pass", "Setter", "Zone", "Result"]
            valid_cols = [c for c in cols_to_show if c in df.columns]
            st.dataframe(df[valid_cols].iloc[::-1], height=300, hide_index=True)
            if st.button("💾 データ送信 (保存してリストをクリア)", type="primary"):
                save_match_data_to_sheet(df)
                st.success("クラウド保存完了")
                st.session_state.match_data = []
                st.rerun()
        else:
            st.info("記録待ち...")
            st.button("💾 データ送信 (保存してリストをクリア)", disabled=True)
