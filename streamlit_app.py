import streamlit as st
import easyocr
import pandas as pd
import requests
import random
import re
from PIL import Image
import numpy as np

# ==========================================
# 1. 基礎設定與金鑰管理
# ==========================================
st.set_page_config(page_title="日文學習助手 Pro (Web)", layout="wide")

st.sidebar.title("🔑 連線設定")
# 修改為：優先讀取後台設定，若無則顯示空白讓使用者輸入
default_token = st.secrets.get("NOTION_TOKEN", "")
default_db_id = st.secrets.get("DATABASE_ID", "")

st.sidebar.title("🔑 連線設定")
notion_token = st.sidebar.text_input("Notion Token", value=default_token, type="password")
database_id = st.sidebar.text_input("Database ID", value=default_db_id)

# 緩存 OCR 引擎，避免重複加載
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
    if method == "POST":
        res = requests.post(url, headers=headers, json=payload)
    elif method == "GET":
        res = requests.get(url, headers=headers)
    elif method == "PATCH":
        res = requests.patch(url, headers=headers, json=payload)
    return res.json()

def process_ocr(uploaded_file):
    # 將上傳的檔案轉為 numpy 陣列供 EasyOCR 使用
    image = Image.open(uploaded_file)
    img_array = np.array(image)
    results = reader.readtext(img_array, detail=1)
    
    blocks = []
    for (bbox, text, prob) in results:
        t = text.strip().replace("紺べ園", "甜甜圈").replace("の咲", "咖啡").replace("雷紫", "蛋糕").replace("形", "開")
        if "duolingo" not in t.lower():
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
# 3. 主介面分頁
# ==========================================
st.title("🇯🇵 日文自動化學習系統 Pro")
tab1, tab2, tab3 = st.tabs(["📸 辨識與新增", "🗂 資料庫管理", "✍️ 測驗模式"])

# --- Tab 1: OCR 辨識 ---
with tab1:
    st.header("圖片辨識與校對")
    uploaded_files = st.file_uploader("選擇 Duolingo 截圖", accept_multiple_files=True, type=['png', 'jpg', 'jpeg'])
    
    if uploaded_files:
        if st.button("開始辨識"):
            st.session_state['ocr_results'] = []
            for file in uploaded_files:
                jp, zh = process_ocr(file)
                st.session_state['ocr_results'].append({"jp": jp, "zh": zh})

    if 'ocr_results' in st.session_state:
        st.write("---")
        final_data = []
        for i, res in enumerate(st.session_state['ocr_results']):
            col1, col2 = st.columns(2)
            with col1:
                new_jp = st.text_input(f"日文 #{i+1}", value=res['jp'], key=f"jp_{i}")
            with col2:
                new_zh = st.text_input(f"中文 #{i+1}", value=res['zh'], key=f"zh_{i}")
            final_data.append({"jp": new_jp, "zh": new_zh})
        
        if st.button("🚀 確認並儲存至 Notion", type="primary"):
            # 獲取現有資料以除重
            res = notion_api("POST", f"/databases/{database_id}/query")
            existing_jps = [p["properties"]["日文"]["title"][0]["text"]["content"] for p in res.get("results", []) if p["properties"]["日文"]["title"]]
            
            new_count = 0
            for item in final_data:
                if item['jp'] not in existing_jps:
                    payload = {
                        "parent": {"database_id": database_id},
                        "properties": {
                            "日文": {"title": [{"text": {"content": item['jp']}}]},
                            "中文": {"rich_text": [{"text": {"content": item['zh']}}]}
                        }
                    }
                    notion_api("POST", "/pages", payload)
                    new_count += 1
            st.success(f"同步完成！新增了 {new_count} 筆資料。")
            del st.session_state['ocr_results']

# --- Tab 2: 資料庫管理 ---
with tab2:
    st.header("雲端資料庫內容")
    if st.button("🔄 刷新資料"):
        data_res = notion_api("POST", f"/databases/{database_id}/query")
        pages = data_res.get("results", [])
        table_data = []
        for p in pages:
            try:
                table_data.append({
                    "ID": p["id"],
                    "日文": p["properties"]["日文"]["title"][0]["text"]["content"],
                    "中文": p["properties"]["中文"]["rich_text"][0]["text"]["content"]
                })
            except: pass
        st.session_state['db_cache'] = table_data

    if 'db_cache' in st.session_state:
        df = pd.DataFrame(st.session_state['db_cache'])
        st.dataframe(df[["日文", "中文"]], use_container_width=True)
        
        # 刪除功能
        del_target = st.selectbox("選取要刪除的日文單字", options=[item['日文'] for item in st.session_state['db_cache']])
        if st.button("🗑 刪除"):
            target_id = [item['ID'] for item in st.session_state['db_cache'] if item['日文'] == del_target][0]
            notion_api("PATCH", f"/pages/{target_id}", {"archived": True})
            st.warning(f"已刪除：{del_target}")
            st.rerun()

# --- Tab 3: 測驗模式 ---
with tab3:
    st.header("智慧測驗模式")
    quiz_type = st.radio("題型選擇", ["選擇題", "填空題"], horizontal=True)
    
    if st.button("✨ 產生隨機 10 題"):
        data_res = notion_api("POST", f"/databases/{database_id}/query")
        pages = data_res.get("results", [])
        if len(pages) < 4:
            st.error("資料庫內容不足，無法進行測驗。")
        else:
            sample = random.sample(pages, min(10, len(pages)))
            st.session_state['current_quiz'] = []
            for p in sample:
                st.session_state['current_quiz'].append({
                    "jp": p["properties"]["日文"]["title"][0]["text"]["content"],
                    "zh": p["properties"]["中文"]["rich_text"][0]["text"]["content"]
                })
            st.session_state['all_jps'] = [p["properties"]["日文"]["title"][0]["text"]["content"] for p in pages]

    if 'current_quiz' in st.session_state:
        score = 0
        user_answers = {}
        
        # 雙欄佈局顯示題目
        cols = st.columns(2)
        for i, q in enumerate(st.session_state['current_quiz']):
            with cols[i % 2]:
                st.subheader(f"Q{i+1}: {q['zh']}")
                if quiz_type == "選擇題":
                    others = random.sample([j for j in st.session_state['all_jps'] if j != q['jp']], 3)
                    opts = [q['jp']] + others
                    random.shuffle(opts)
                    user_answers[i] = st.radio(f"請選擇答案 (Q{i+1})", opts, key=f"q_{i}")
                else:
                    user_answers[i] = st.text_input(f"請輸入日文 (Q{i+1})", key=f"q_{i}")

        if st.button("✅ 提交答案"):
            for i, q in enumerate(st.session_state['current_quiz']):
                if user_answers[i].strip() == q['jp'].strip():
                    score += 1
            st.balloons()
            st.success(f"測驗結束！您的得分：{score} / {len(st.session_state['current_quiz'])}")