import streamlit as st
import sys

st.set_page_config(page_title="診断モード")

st.title("🏥 アプリ健康診断")
st.write("ライブラリが正しく読み込めるかテストします。")

# 1. 基本ライブラリのテスト
st.subheader("1. 基本機能")
try:
    import pandas as pd
    import numpy as np
    from PIL import Image
    st.success("✅ Pandas / Numpy / Pillow: OK")
except Exception as e:
    st.error(f"❌ 基本機能エラー: {e}")

# 2. Google機能のテスト
st.subheader("2. Google連携")
try:
    import gspread
    from oauth2client.service_account import ServiceAccountCredentials
    from googleapiclient.discovery import build
    st.success("✅ Google API: OK")
except Exception as e:
    st.error(f"❌ Google APIエラー: {e}")

# 3. OpenCV (画像処理) のテスト
st.subheader("3. OpenCV (画像処理)")
try:
    import cv2
    st.success(f"✅ OpenCV: OK (Version {cv2.__version__})")
except ImportError as e:
    st.error(f"❌ OpenCV エラー: {e}")
    st.info("💡 ヒント: packages.txt に 'libgl1' が書かれているか確認してください。")
except Exception as e:
    st.error(f"❌ OpenCV その他エラー: {e}")

# 4. AI (YOLO) のテスト
st.subheader("4. AI (Ultralytics)")
if st.button("AIライブラリをテストする (重いので注意)"):
    try:
        with st.spinner("読み込み中..."):
            from ultralytics import YOLO
            st.success("✅ Ultralytics Import: OK")
            
            # モデルロードテスト
            model = YOLO('yolov8n-pose.pt')
            st.success("✅ モデルロード: OK")
    except Exception as e:
        st.error(f"❌ AIエラー: {e}")
        st.warning("メモリ不足の可能性があります。")

st.write("---")
st.caption("この画面が表示されていれば、Streamlit自体は動いています。")
