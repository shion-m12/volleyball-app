import streamlit as st
import pandas as pd
from streamlit_image_coordinates import streamlit_image_coordinates
from PIL import Image
import datetime
import re
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import matplotlib.pyplot as plt
import matplotlib.image as mpimg

# --- 設定 ---
st.set_page_config(layout="wide", page_title="Volleyball Analyst Pro v26")

# 凡例用の色設定
ZONE_COLORS = {
    "レフト(L)": ("red", "Left"),
    "センター(C)": ("green", "Center"),
    "ライト(R)": ("blue", "Right"),
    "レフトバック(LB)": ("orange", "Back-Left"),
    "センターバック(CB)": ("purple", "Back-Center"),
    "ライトバック(RB)": ("cyan", "Back-Right"),
    "なし": ("gray", "None")
}

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
        worksheet = sheet.worksheet("
