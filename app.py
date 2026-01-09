import streamlit as st
import pandas as pd
from streamlit_image_coordinates import streamlit_image_coordinates
from PIL import Image
import os
import json
import datetime
import re

# --- 設定 ---
st.set_page_config(layout="wide", page_title="Volleyball Analyst Pro v15.2")

# --- 定数 ---
DATA_DIR = "data"
PLAYERS_FILE = os.path.join(DATA_DIR, "players.json")
HISTORY_FILE = os.path.join(DATA_DIR, "match_history.csv")

# --- 初期化 ---
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

def load_players():
    default_data = {
        "My Team": {"#1 田中": "OH", "#2 佐藤": "MB", "#3 鈴木": "OP", "#4 高橋": "OH", "#5 渡辺": "MB", "#6 山本": "L"},
        "Opponent A": {"#1 敵A": "OH", "#2 敵B": "MB", "#3 敵C": "OP", "#4 敵D": "OH", "#5 敵E": "MB", "#6 敵L": "L"}
    }
    if os.path.exists(PLAYERS_FILE):
        with open(PLAYERS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if data and isinstance(next(iter(data.values())), str):
                return {"My Team": data}
            return data
    return default_data

def save_players(players_dict):
    with open(PLAYERS_FILE, "w", encoding="utf-8") as f:
        json.dump(players_dict, f, ensure_ascii=False, indent=2)

def sort_players_by_number(player_names):
    def get_num(name):
        match = re.search(r'#(\d+)', name)
        return int(match.group(1)) if match else 999
    return sorted(player_names, key=get_num)

# --- ステート管理 ---
if 'players_db' not in st.session_state:
    st.session_state.players_db = load_players()
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
    st.session_state.game_state = {
        "my_score": 0, "op_score": 0,
        "serve_rights": "My Team",
        "my_rot": 1, "op_rot": 1
    }

# --- 関数 ---
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
#  サイドバー：メニュー切り替え
# ==========================================
with st.sidebar:
    st.title("🏐 Analyst Pro v15.2")
    
    app_mode = st.radio("メニュー選択", ["📊 試合入力・分析", "👤 選手名鑑 (チーム管理)"])
    
    st.markdown("---")
    
    team_list = list(st.session_state.players_db.keys())
    my_team_name = st.selectbox("自チーム", team_list, index=0)
    
    other_teams = [t for t in team_list if t != my_team_name]
    op_team_name = st.selectbox("相手チーム", other_teams, index=0) if other_teams else "未設定"

# ==========================================
#  モード1：選手名鑑 (チーム管理)
# ==========================================
if app_mode == "👤 選手名鑑 (チーム管理)":
    st.header("👤 選手名鑑・チーム管理")
    
    col_dir_1, col_dir_2 = st.columns([1, 2])
    
    with col_dir_1:
        st.subheader("チーム作成")
        new_team = st.text_input("新しいチーム名")
        if st.button("チームを追加"):
            if new_team and new_team not in st.session_state.players_db:
                st.session_state.players_db[new_team] = {}
                save_players(st.session_state.players_db)
                st.success(f"{new_team} を作成しました")
                st.rerun()
                
    with col_dir_2:
        st.subheader("選手リスト閲覧 & 編集")
        target_team = st.selectbox("表示するチーム", list(st.session_state.players_db.keys()))
        
        players_data = st.session_state.players_db[target_team]
        if players_data:
            p_list = []
            for name, pos in players_data.items():
                match = re.search(r'#(\d+)', name)
                num = int(match.group(1)) if match else 999
                p_list.append({"No.": num, "選手名": name, "ポジション": pos})
            
            df_players = pd.DataFrame(p_list).sort_values("No.")
            st.dataframe(df_players[["選手名", "ポジション"]], use_container_width=True, hide_index=True)
        else:
            st.info("選手がまだ登録されていません")
            
        st.markdown("---")
        st.write("▼ **選手の追加・修正**")
        
        tab_add, tab_edit = st.tabs(["➕ 新規登録", "✏️ 編集・削除"])
        
        with tab_add:
            c_num, c_name = st.columns([1, 2])
            with c_num: i_num = st.text_input("背番号", key="dir_num")
            with c_name: i_name = st.text_input("名前", key="dir_name")
            i_pos = st.selectbox("ポジション", ["OH", "MB", "OP", "S", "L"], key="dir_pos")
            
            if st.button("リストに追加"):
                if i_num and i_name:
                    key = f"#{i_num} {i_name}"
                    st.session_state.players_db[target_team][key] = i_pos
                    save_players(st.session_state.players_db)
                    st.success(f"{key} を追加しました")
                    st.rerun()

        with tab_edit:
            if players_data:
                sorted_keys = sort_players_by_number(list(players_data.keys()))
                edit_tgt = st.selectbox("選手を選択", sorted_keys, key="dir_edit_tgt")
                
                if st.button("この選手を削除"):
                    del st.session_state.players_db[target_team][edit_tgt]
                    save_players(st.session_state.players_db)
                    st.warning("削除しました")
                    st.rerun()
            else:
                st.write("選手がいません")


# ==========================================
#  モード2：試合入力・分析
# ==========================================
elif app_mode == "📊 試合入力・分析":
    
    try:
        image = Image.open("court.png")
    except FileNotFoundError:
        st.error("エラー：'court.png' が見つかりません。")
        st.stop()

    col_score, col_main, col_log = st.columns([0.8, 1.2, 0.8])

    # --- エリア1：スコアボード ---
    with col_score:
        st.header("1. Score")
        gs = st.session_state.game_state
        
        my_server = "-"
        if st.session_state.my_service_order:
            idx = (gs['my_rot'] - 1) % 6
            my_server = st.session_state.my_service_order[idx]

        op_server = "-"
        if st.session_state.op_service_order:
            idx = (gs['op_rot'] - 1) % 6
            op_server = st.session_state.op_service_order[idx]

        my_icon = "🏐 SERVE" if gs["serve_rights"] == "My Team" else ""
        op_icon = "🏐 SERVE" if gs["serve_rights"] == "Opponent" else ""

        st.markdown(f"""
        <div style="text-align: center; border: 2px solid #ddd; padding: 10px; border-radius: 10px; background-color: #f9f9f9;">
            <h1 style="font-size: 48px; margin: 0;">{gs['my_score']} - {gs['op_score']}</h1>
            <hr>
            <div style="display: flex; justify-content: space-between;">
                <div style="width:48%; text-align:center;">
                    <b style="color:blue;">{my_team_name}</b><br>
                    <span style="color:red; font-size:12px;">{my_icon}</span><br>
                    Rot: <b>{gs['my_rot']}</b><br>
                    Server: <b>{my_server.split(' ')[0]}</b>
                </div>
                <div style="width:48%; text-align:center;">
                    <b style="color:grey;">{op_team_name}</b><br>
                    <span style="color:red; font-size:12px;">{op_icon}</span><br>
                    Rot: <b>{gs['op_rot']}</b><br>
                    Server: <b>{op_server.split(' ')[0]}</b>
                </div>
            </div>
        </div>
        """, unsafe_allow_html=True)
        
        with st.expander("試合設定・修正"):
            match_name = st.text_input("大会/試合名", "練習試合")
            current_set = st.number_input("セット", 1, 5, 1)
            match_id = f"{datetime.date.today()}_{my_team_name}vs{op_team_name}"
            
            st.markdown("---")
            c_p1, c_p2 = st.columns(2)
            with c_p1:
                if st.button("自 +1"): add_point("My Team"); st.rerun()
                if st.button("自 Rot進"): rotate_team("my"); st.rerun()
            with c_p2:
                if st.button("敵 +1"): add_point("Opponent"); st.rerun()
                if st.button("敵 Rot進"): rotate_team("op"); st.rerun()

    # --- エリア2：入力 ---
    with col_main:
        st.header("2. Input")
        
        # --- スタメン未登録の場合 ---
        if not st.session_state.my_service_order:
            st.info("🏁 **スターティングメンバー設定**")
            
            my_p_list = sort_players_by_number(list(st.session_state.players_db[my_team_name].keys()))
            op_p_list = sort_players_by_number(list(st.session_state.players_db[op_team_name].keys())) if op_team_name != "未設定" else []

            c_my, c_op = st.columns(2)
            with c_my:
                st.caption(f"{my_team_name} (S1~S6)")
                ms = [st.selectbox(f"P{i+1}", my_p_list, key=f"m{i}") for i in range(6)]
                m_lib = st.selectbox("Libero", ["なし"] + my_p_list, key="mlib")
            with c_op:
                st.caption(f"{op_team_name}")
                if op_p_list:
                    os_ = [st.selectbox(f"P{i+1}", op_p_list, key=f"o{i}") for i in range(6)]
                    o_lib = st.selectbox("Libero", ["なし"] + op_p_list, key="olib")
                else:
                    st.warning("相手選手未登録")
                    os_ = []
                    o_lib = "なし"

            # ★ここを修正しました！ (チーム名で選択)
            st.markdown("---")
            st.caption("最初のサーブ権を選択")
            first_srv_label = st.radio("First Serve", [my_team_name, op_team_name], horizontal=True, label_visibility="collapsed")
            
            # 選択された名前を内部ロジック用のIDに変換
            first_srv_key = "My Team" if first_srv_label == my_team_name else "Opponent"
            
            if st.button("Start Match", type="primary"):
                st.session_state.my_service_order = ms
                st.session_state.op_service_order = os_
                st.session_state.my_libero = m_lib
                st.session_state.op_libero = o_lib
                st.session_state.game_state["serve_rights"] = first_srv_key
                st.rerun()

        # --- 試合進行中 ---
        else:
            active_players = list(st.session_state.my_service_order)
            if st.session_state.my_libero != "なし":
                active_players.append(st.session_state.my_libero)
            
            active_players_sorted = sort_players_by_number(active_players)

            is_setter_front = True if gs['my_rot'] in [4, 5, 6] else False
            s_pos_str = "S前衛" if is_setter_front else "S後衛"
            
            c1, c2 = st.columns([0.8, 1.2])
            with c1:
                st.info(f"**{s_pos_str}** (Rot {gs['my_rot']})")
                reception = st.radio("Reception", ["Aパス", "Bパス", "Cパス"], horizontal=True)
            
            with c2:
                player_key = st.selectbox("Player (出場中のみ)", active_players_sorted)
                result = st.selectbox("Result", ["得点 (Kill)", "効果", "継続", "失点 (Error)", "被ブロック"])

            st.write("👇 **コートをクリック**")
            
            coords = streamlit_image_coordinates(image, width=500, key="court_click")

            if coords is not None:
                last_x = st.session_state.match_data[-1]["X"] if st.session_state.match_data else -1
                if coords["x"] != last_x:
                    pos = st.session_state.players_db[my_team_name].get(player_key, "?")
                    new_record = {
                        "チーム": my_team_name,
                        "セット": current_set,
                        "自得点": gs['my_score'],
                        "敵得点": gs['op_score'],
                        "自ローテ": gs['my_rot'],
                        "選手": player_key,
                        "ポジション": pos,
                        "結果": result,
                        "パス": reception,
                        "X": coords["x"],
                        "Y": coords["y"],
                        "数": 1
                    }
                    st.session_state.match_data.append(new_record)
                    
                    if result == "得点 (Kill)":
                        add_point("My Team")
                        st.toast(f"Nice! {gs['my_score']}-{gs['op_score']}")
                    elif result in ["失点 (Error)", "被ブロック"]:
                        add_point("Opponent")
                        st.toast(f"Don't mind... {gs['my_score']}-{gs['op_score']}")
                    else:
                        st.toast("記録しました")
                    st.rerun()

            with st.expander("🔄 メンバーチェンジ / リセット"):
                if st.button("全リセット (スタメン選択に戻る)"):
                    st.session_state.my_service_order = []
                    st.rerun()
                
                st.caption("交代を行うと、入力候補リストも自動更新されます")
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

    # --- エリア3：ログ ---
    with col_log:
        st.header("3. Log")
        if st.session_state.match_data:
            df = pd.DataFrame(st.session_state.match_data)
            st.dataframe(df[["自得点", "選手", "結果"]].iloc[::-1], height=400, hide_index=True)
            
            if st.button("💾 CSV保存"):
                if os.path.exists(HISTORY_FILE):
                    df_h = pd.read_csv(HISTORY_FILE)
                    df_new = pd.concat([df_h, df], ignore_index=True)
                else:
                    df_new = df
                df_new.to_csv(HISTORY_FILE, index=False, encoding='utf-8-sig')
                st.success("保存しました")
                st.session_state.match_data = []