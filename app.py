import streamlit as st
import pandas as pd
from streamlit_image_coordinates import streamlit_image_coordinates
from PIL import Image, ImageDraw
import datetime
import re
import os
import io
import tempfile
import numpy as np
import math

# Google関連
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

# 画像処理系
import cv2

# --- 設定 ---
st.set_page_config(layout="wide", page_title="Volleyball Analyst Pro v40")

# ★★★ Googleドライブ共有フォルダID ★★★
TARGET_FOLDER_ID = "1F1hTSQcYV3QRpz0PBrx5m4U-9TxE_bgE"

# 定数
KP_NOSE = 0
KP_R_WRIST = 10
KP_L_WRIST = 9
KP_R_ANKLE = 16
KP_L_ANKLE = 15

# --- AIモデルのロード ---
@st.cache_resource
def load_models():
    from ultralytics import YOLO
    pose_model = YOLO('yolov8n-pose.pt')
    det_model = YOLO('yolov8n.pt') 
    return pose_model, det_model

# --- Google API 接続 ---
def get_gcp_creds():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    try:
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        return creds
    except Exception as e:
        st.error(f"認証設定エラー: secrets.tomlを確認してください。 {e}")
        st.stop()

def connect_to_drive():
    creds = get_gcp_creds()
    service = build('drive', 'v3', credentials=creds)
    return service

def connect_to_gsheet():
    creds = get_gcp_creds()
    client = gspread.authorize(creds)
    return client

# --- Drive 操作 ---
def list_drive_files(folder_id):
    try:
        service = connect_to_drive()
        query = f"'{folder_id}' in parents and mimeType contains 'video' and trashed=false"
        results = service.files().list(
            q=query,
            pageSize=20, fields="nextPageToken, files(id, name, createdTime)").execute()
        return results.get('files', [])
    except Exception as e:
        if "404" in str(e) or "File not found" in str(e):
            st.error("🚨 エラー: フォルダが見つかりません。")
        else:
            st.error(f"Driveエラー: {e}")
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

# --- データ管理関数 ---
def save_match_data_to_sheet(df):
    client = connect_to_gsheet()
    try:
        # シートIDは固定または設定から取得
        SPREADSHEET_ID = "14o1wNqQIrJPy9IAuQ7PSCwP6NyA4O5dZrn_FmFoSqLQ"
        sheet = client.open_by_key(SPREADSHEET_ID)
        try:
            worksheet = sheet.worksheet("history")
        except:
            worksheet = sheet.add_worksheet(title="history", rows="1000", cols="20")
        
        # 既存データ取得
        existing = worksheet.get_all_values()
        data_to_write = df.astype(str).values.tolist()
        
        if not existing:
            header = df.columns.tolist()
            worksheet.append_row(header)
            worksheet.append_rows(data_to_write)
        else:
            worksheet.append_rows(data_to_write)
        st.toast("Google Sheetsにも保存しました")
    except Exception as e:
        st.error(f"Sheet保存エラー: {e}")

# --- ステート管理 ---
if 'analysis_video_path' not in st.session_state: st.session_state.analysis_video_path = None
if 'analysis_results' not in st.session_state: st.session_state.analysis_results = None

# ==========================================
#  UI サイドバー
# ==========================================
with st.sidebar:
    st.title("🏐 Analyst Pro v40")
    app_mode = st.radio("メニュー", ["🎥 AI動作分析 (Drive)", "📊 試合入力(手動)", "👤 設定"])
    st.markdown("---")
    try:
        creds_info = dict(st.secrets["gcp_service_account"])
        sa_email = creds_info.get("client_email", "不明")
        st.caption("📧 招待用メールアドレス:")
        st.code(sa_email, language=None)
    except:
        st.error("Secrets未設定")

# ==========================================
#  UI メイン
# ==========================================

if app_mode == "🎥 AI動作分析 (Drive)":
    st.header("🎥 AI 自動スタッツ集計 (Back View)")
    
    # 1. エンドライン設定
    with st.expander("🛠 エンドラインの設定", expanded=True):
        end_line_percent_y = st.slider("エンドライン位置 (上端=0, 下端=100)", 0, 100, 80)
        st.caption(f"画面の上から {end_line_percent_y}% のラインを基準に、手前をサーブ、奥をスパイクと判定します。")

    # 2. 動画選択
    st.subheader("1. 動画選択")
    col_r, col_l = st.columns([1, 4])
    if col_r.button("🔄 更新"): pass
    
    files = list_drive_files(TARGET_FOLDER_ID)
    
    if files:
        file_options = {f['name']: f['id'] for f in files}
        selected_filename = st.selectbox("解析する動画を選択", list(file_options.keys()))
        
        if st.button("📥 動画をロード (解析準備)", type="primary"):
            with st.spinner("クラウドからダウンロード中..."):
                file_id = file_options[selected_filename]
                fh = download_file_from_drive(file_id)
                tfile = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4")
                tfile.write(fh.read())
                st.session_state.analysis_video_path = tfile.name
                st.session_state.analysis_results = None # 結果リセット
                st.success(f"ロード完了: {selected_filename}")
    else:
        st.warning("動画が見つかりません。")

    # 3. 解析実行 & 結果表示
    if st.session_state.analysis_video_path:
        st.markdown("---")
        st.subheader("2. 解析実行")
        st.video(st.session_state.analysis_video_path)
        
        if st.button("🚀 AI解析スタート", type="primary"):
            st.text("AIが映像を見ています... (100%になるまでお待ちください)")
            try:
                pose_model, det_model = load_models()
                cap = cv2.VideoCapture(st.session_state.analysis_video_path)
                st_frame = st.empty()
                
                width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                progress_bar = st.progress(0)
                
                detected_events = []
                frame_count = 0
                cooldown = 0
                
                while cap.isOpened():
                    ret, frame = cap.read()
                    if not ret: break
                    frame_count += 1
                    if cooldown > 0: cooldown -= 1
                    
                    # 高速化のため3フレームに1回処理
                    if frame_count % 3 != 0: continue
                    
                    # 1. ボール検出
                    ball_results = det_model(frame, classes=[32], conf=0.3, verbose=False)
                    ball_box = None
                    if len(ball_results[0].boxes) > 0:
                        box = ball_results[0].boxes[0]
                        bx1, by1, bx2, by2 = box.xyxy[0].cpu().numpy()
                        ball_cx, ball_cy = (bx1+bx2)/2, (by1+by2)/2
                        ball_box = (ball_cx, ball_cy)
                        cv2.circle(frame, (int(ball_cx), int(ball_cy)), 10, (0, 255, 255), -1)

                    # 2. 骨格検知
                    pose_results = pose_model(frame, conf=0.5, verbose=False)
                    annotated_frame = pose_results[0].plot()
                    action_text = ""
                    
                    if pose_results[0].keypoints is not None:
                        keypoints = pose_results[0].keypoints.xy.cpu().numpy()
                        for kpts in keypoints:
                            if ball_box is None: continue
                            nose = kpts[KP_NOSE]; r_wrist = kpts[KP_R_WRIST]; r_ankle = kpts[KP_R_ANKLE]
                            if nose[0]==0 or r_wrist[0]==0: continue
                            
                            dist = math.hypot(ball_box[0] - r_wrist[0], ball_box[1] - r_wrist[1])
                            
                            # 判定 (インパクト & オーバーハンド)
                            if dist < 100 and r_wrist[1] < nose[1] and cooldown == 0:
                                line_y = height * (end_line_percent_y / 100)
                                timestamp = frame_count / 30.0 # 仮の30fps
                                if r_ankle[1] > line_y:
                                    action = "SERVE"
                                else:
                                    action = "SPIKE"
                                
                                detected_events.append({
                                    "Time(s)": round(timestamp, 2),
                                    "Action": action,
                                    "Frame": frame_count
                                })
                                action_text = f"{action}!"
                                cooldown = 20 # 連打防止
                                break
                    
                    # 描画
                    if action_text:
                        cv2.putText(annotated_frame, action_text, (50, 150), cv2.FONT_HERSHEY_SIMPLEX, 3, (0, 0, 255), 5)
                    
                    line_y_int = int(height * (end_line_percent_y / 100))
                    cv2.line(annotated_frame, (0, line_y_int), (width, line_y_int), (255, 0, 0), 3)
                    st_frame.image(cv2.cvtColor(annotated_frame, cv2.COLOR_BGR2RGB), use_container_width=True)
                    if total_frames > 0:
                        progress_bar.progress(min(frame_count / total_frames, 1.0))
                
                cap.release()
                # 結果を保存
                if detected_events:
                    st.session_state.analysis_results = pd.DataFrame(detected_events)
                else:
                    st.session_state.analysis_results = pd.DataFrame(columns=["Time(s)", "Action", "Frame"])
                st.success("解析完了！下に結果を表示します 👇")
                    
            except Exception as e:
                st.error(f"解析エラー: {e}")

        # 4. 結果ダッシュボード (解析完了後に表示)
        if st.session_state.analysis_results is not None:
            st.markdown("---")
            st.subheader("📊 解析結果ダッシュボード")
            
            df = st.session_state.analysis_results
            if not df.empty:
                # 集計
                counts = df["Action"].value_counts()
                c1, c2, c3 = st.columns(3)
                c1.metric("総アクション数", len(df))
                c2.metric("🏐 サーブ", counts.get("SERVE", 0))
                c3.metric("💥 スパイク", counts.get("SPIKE", 0))
                
                # 詳細データとダウンロード
                st.write("▼ 検出イベント一覧")
                st.dataframe(df, use_container_width=True)
                
                # CSVダウンロードボタン
                csv = df.to_csv(index=False).encode('utf-8')
                st.download_button(
                    label="📥 解析データをCSVで保存",
                    data=csv,
                    file_name=f"volleyball_stats_{datetime.date.today()}.csv",
                    mime='text/csv',
                )
                
                # クラウド保存ボタン
                if st.button("☁️ Google Sheetsにも履歴として保存"):
                    save_match_data_to_sheet(df)
            else:
                st.info("アクションは検出されませんでした。")

# (手動入力モードが必要ならここに残す)
elif app_mode == "📊 試合入力(手動)":
    st.write("手動入力モードは現在メンテナンス中です。")
