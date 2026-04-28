import streamlit as st
import easyocr
import pandas as pd
import requests
import random
import re
from PIL import Image
import numpy as np

# ==========================================
# 1. 基礎設定與金鑰管理 (安全私有化版)
# ==========================================
st.set_page_config(page_title="日文學習助手 Pro", layout="wide")

try:
    notion_token = st.secrets["NOTION_TOKEN"]
    database_id = st.secrets["DATABASE_ID"]
except KeyError:
    st.error("❌ 找不到 Secrets 設定！請在 Streamlit Cloud 後台設定 NOTION_TOKEN 與 DATABASE_ID。")
    st.stop()

st.sidebar.title("🔐 系統連線")
st.sidebar.success("✅ 已連線至 Notion")

@st.cache_resource
def load_ocr():
    return easyocr.Reader(['ja', 'en'], gpu=False)

reader = load_ocr()

# ==========================================
# 2. 工具函式
# ==========================================
def notion_api(method, endpoint, payload=None):
    headers = {
        "Authorization": f"Bearer {notion_token}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28"
    }
    url = f"https://api.notion.com/v1{endpoint}"
    try:
        if method == "POST":
            res = requests.post(url, headers=headers, json=payload)
        elif method == "PATCH":
            res = requests.patch(url, headers=headers, json=payload)
        return res.json()
    except Exception as e:
        st.error(f"Notion 連線失敗: {e}")
        return {}

def process_ocr(uploaded_file):
    image = Image.open(uploaded_file)
    img_array = np.array(image)
    results = reader.readtext(img_array, detail=1)
    blocks = []
    for (bbox, text, prob) in results:
        t = text.strip().replace("紺べ園", "甜甜圈").replace("の咲", "咖啡").replace("雷紫", "蛋糕").replace("形", "開")
        if "duolingo" not in t.lower() and t:
            blocks.append({"text": t, "y": bbox[0][1]})
    blocks.sort(key=lambda x: x["y"])
    jp_parts, zh_parts, found_zh = [], [], False
    for b in blocks:
        has_kana = bool(re.search(r'[\u3040-\u309F\u30A0-\u30FF]', b["text"]))
        if not found_zh and not has_kana and re.search(r'[\u4e00-\u9fa5]', b["text"]):
            found_zh = True
        if found_zh: zh_parts.append(b["text"])
        else: jp_parts.append(b["text"])
    return "".join(jp_parts), " ".join(zh_parts)

# ==========================================
# 3. 主介面
# ==========================================
st.title("🇯🇵 日文自動化學習系統 Pro")
tab1, tab2, tab3 = st.tabs(["📸 辨識與新增", "🗂 資料庫管理", "✍️ 測驗模式"])

# --- Tab 1: OCR 辨識 ---
with tab1:
    st.header("圖片辨識與校對")
    uploaded_files = st.file_uploader("選擇 Duolingo 截圖", accept_multiple_files=True, type=['png', 'jpg', 'jpeg'])
    if uploaded_files:
        if st.button("🔍 開始辨識"):
            st.session_state['ocr_results'] = []
            with st.spinner("辨識中..."):
                for file in uploaded_files:
                    jp, zh = process_ocr(file)
                    st.session_state['ocr_results'].append({"jp": jp, "zh": zh})

    if 'ocr_results' in st.session_state:
        st.divider()
        final_data = []
        for i, res in enumerate(st.session_state['ocr_results']):
            c1, c2 = st.columns(2)
            new_jp = c1.text_input(f"日文 #{i+1}", value=res['jp'], key=f"jp_{i}")
            new_zh = c2.text_input(f"中文 #{i+1}", value=res['zh'], key=f"zh_{i}")
            final_data.append({"jp": new_jp, "zh": new_zh})
        
        if st.button("🚀 確認並儲存至 Notion", type="primary"):
            res_db = notion_api("POST", f"/databases/{database_id}/query")
            existing_jps = [p["properties"]["日文"]["title"][0]["text"]["content"] for p in res_db.get("results", []) if p["properties"]["日文"]["title"]]
            new_count = 0
            for item in final_data:
                if item['jp'] not in existing_jps:
                    payload = {"parent": {"database_id": database_id}, "properties": {"日文": {"title": [{"text": {"content": item['jp']}}]}, "中文": {"rich_text": [{"text": {"content": item['zh']}}]}}}
                    notion_api("POST", "/pages", payload)
                    new_count += 1
            st.success(f"同步完成！新增: {new_count} 筆。")
            del st.session_state['ocr_results']

# --- Tab 2: 資料庫管理 (強化編輯功能) ---
with tab2:
    st.header("資料庫管理")
    col_a, col_b = st.columns([1, 4])
    refresh = col_a.button("🔄 刷新資料")
    
    if refresh or 'db_cache' not in st.session_state:
        with st.spinner("載入中..."):
            data_res = notion_api("POST", f"/databases/{database_id}/query")
            pages = data_res.get("results", [])
            st.session_state['db_cache'] = [{"ID": p["id"], "日文": p["properties"]["日文"]["title"][0]["text"]["content"], "中文": p["properties"]["中文"]["rich_text"][0]["text"]["content"]} for p in pages if p["properties"]["日文"]["title"]]

    if st.session_state.get('db_cache'):
        df = pd.DataFrame(st.session_state['db_cache'])
        
        st.write("💡 **直接點擊單格即可編輯內容，完成後請點擊下方儲存按鈕。**")
        # 使用 st.data_editor 讓表格可編輯
        edited_df = st.data_editor(
            df, 
            column_config={
                "ID": None, # 隱藏 ID 欄位
                "日文": st.column_config.TextColumn("日文原文", width="medium"),
                "中文": st.column_config.TextColumn("中文翻譯", width="medium"),
            },
            use_container_width=True,
            num_rows="dynamic", # 允許在表格內刪除列
            key="db_editor"
        )

        c1, c2, _ = st.columns([1, 1, 3])
        if c1.button("💾 儲存修改", type="primary"):
            # 找出有變動的部分進行更新
            with st.spinner("同步至 Notion..."):
                for index, row in edited_df.iterrows():
                    # 比對原始資料是否有變
                    orig = df.iloc[index] if index < len(df) else None
                    if orig is None or row['日文'] != orig['日文'] or row['中文'] != orig['中文']:
                        payload = {
                            "properties": {
                                "日文": {"title": [{"text": {"content": row['日文']}}]},
                                "中文": {"rich_text": [{"text": {"content": row['中文']}}]}
                            }
                        }
                        notion_api("PATCH", f"/pages/{row['ID']}", payload)
            st.success("✅ 修改已同步至雲端！")
            st.rerun()

        if c2.button("🗑 刪除勾選列"):
            st.info("請直接在表格中點擊左側序號並按鍵盤 Delete，再點擊『儲存修改』即可。")

# --- Tab 3: 測驗模式 ---
with tab3:
    st.header("測驗模式")
    if 'db_cache' not in st.session_state or not st.session_state['db_cache']:
        st.warning("請先到『資料庫管理』刷新資料。")
    else:
        quiz_type = st.radio("題型", ["選擇題", "填空題"], horizontal=True)
        if st.button("🎲 產生題目"):
            st.session_state['current_quiz'] = random.sample(st.session_state['db_cache'], min(10, len(st.session_state['db_cache'])))
        
        if 'current_quiz' in st.session_state:
            score = 0
            user_ans = {}
            for i, q in enumerate(st.session_state['current_quiz']):
                st.write(f"**Q{i+1}: {q['中文']}**")
                if quiz_type == "選擇題":
                    opts = sorted([item['日文'] for item in random.sample(st.session_state['db_cache'], min(4, len(st.session_state['db_cache']))) if item['日文'] != q['日文']] + [q['日文']])
                    user_ans[i] = st.radio(f"選擇解答 {i+1}", opts, key=f"q_{i}")
                else:
                    user_ans[i] = st.text_input(f"輸入日文 {i+1}", key=f"q_{i}")
            
            if st.button("🏁 提交"):
                for i, q in enumerate(st.session_state['current_quiz']):
                    if user_ans[i].strip() == q['日文'].strip(): score += 1
                st.balloons()
                st.metric("得分", f"{score} / {len(st.session_state['current_quiz'])}")
