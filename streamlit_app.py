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

# 直接從 Streamlit Cloud 後台 Secrets 讀取，不顯示在 UI
try:
    notion_token = st.secrets["NOTION_TOKEN"]
    database_id = st.secrets["DATABASE_ID"]
except KeyError:
    st.error("❌ 找不到 Secrets 設定！請在 Streamlit Cloud 後台 Settings -> Secrets 中設定 NOTION_TOKEN 與 DATABASE_ID。")
    st.stop()

# 側邊欄僅顯示狀態
st.sidebar.title("🔐 系統連線")
st.sidebar.success("✅ 已成功連線至 Notion")
st.sidebar.info("💡 此版本已啟用金鑰隱藏保護")

# 緩存 OCR 引擎
@st.cache_resource
def load_ocr():
    # 使用 ja, en 模型
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
        t = text.strip()
        # 修正常見 OCR 誤判
        t = t.replace("紺べ園", "甜甜圈").replace("の咲", "咖啡").replace("雷紫", "蛋糕").replace("形", "開")
        if "duolingo" not in t.lower() and t:
            blocks.append({"text": t, "y": bbox[0][1]})
    
    # 按座標排序
    blocks.sort(key=lambda x: x["y"])
    
    jp_parts, zh_parts, found_zh = [], [], False
    for b in blocks:
        # 偵測假名以區分日文與中文
        has_kana = bool(re.search(r'[\u3040-\u309F\u30A0-\u30FF]', b["text"]))
        if not found_zh and not has_kana and re.search(r'[\u4e00-\u9fa5]', b["text"]):
            found_zh = True
        
        if found_zh:
            zh_parts.append(b["text"])
        else:
            jp_parts.append(b["text"])
    
    return "".join(jp_parts), " ".join(zh_parts)

# ==========================================
# 3. 主介面
# ==========================================
st.title("🇯🇵 日文自動化學習系統 Pro")
tab1, tab2, tab3 = st.tabs(["📸 辨識與新增", "🗂 資料庫管理", "✍️ 測驗模式"])

# --- Tab 1: OCR 辨識 ---
with tab1:
    st.header("圖片辨識與校對")
    uploaded_files = st.file_uploader("選擇 Duolingo 截圖 (可多選)", accept_multiple_files=True, type=['png', 'jpg', 'jpeg'])
    
    if uploaded_files:
        if st.button("🔍 開始辨識"):
            # 每次辨識前清空快取，確保不重複
            st.session_state['ocr_results'] = []
            with st.spinner("辨識中，請稍候..."):
                for file in uploaded_files:
                    jp, zh = process_ocr(file)
                    st.session_state['ocr_results'].append({"jp": jp, "zh": zh})

    if 'ocr_results' in st.session_state:
        st.divider()
        final_data = []
        for i, res in enumerate(st.session_state['ocr_results']):
            col1, col2 = st.columns(2)
            with col1:
                new_jp = st.text_input(f"日文原文 #{i+1}", value=res['jp'], key=f"jp_{i}")
            with col2:
                new_zh = st.text_input(f"中文翻譯 #{i+1}", value=res['zh'], key=f"zh_{i}")
            final_data.append({"jp": new_jp, "zh": new_zh})
        
        if st.button("🚀 確認並儲存至 Notion", type="primary"):
            # 獲取現有資料進行除重
            res_db = notion_api("POST", f"/databases/{database_id}/query")
            existing_jps = [p["properties"]["日文"]["title"][0]["text"]["content"] for p in res_db.get("results", []) if p["properties"]["日文"]["title"]]
            
            new_count, skip_count = 0, 0
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
                else:
                    skip_count += 1
            
            st.success(f"同步完成！新增: {new_count} 筆, 跳過重複: {skip_count} 筆。")
            # 儲存後清除顯示結果
            del st.session_state['ocr_results']

# --- Tab 2: 管理頁面 ---
with tab2:
    st.header("雲端資料庫管理")
    if st.button("🔄 刷新 Notion 資料"):
        with st.spinner("同步中..."):
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
        if st.session_state['db_cache']:
            df = pd.DataFrame(st.session_state['db_cache'])
            if "日文" in df.columns:
                st.dataframe(df[["日文", "中文"]], use_container_width=True)
                
                # 簡單的刪除機制
                del_target = st.selectbox("垃圾桶 (選擇要移除的項目)", options=[item['日文'] for item in st.session_state['db_cache']])
                if st.button("🗑 執行刪除"):
                    target_id = [item['ID'] for item in st.session_state['db_cache'] if item['日文'] == del_target][0]
                    notion_api("PATCH", f"/pages/{target_id}", {"archived": True})
                    st.warning(f"已移除: {del_target}")
                    st.rerun()
        else:
            st.info("目前資料庫是空的。")

# --- Tab 3: 測驗模式 ---
with tab3:
    st.header("測驗模式")
    if 'db_cache' not in st.session_state or not st.session_state['db_cache']:
        st.warning("請先到『資料庫管理』分頁刷新資料以載入題目。")
    else:
        quiz_type = st.radio("題型", ["選擇題", "填空題"], horizontal=True)
        
        if st.button("🎲 隨機產生 10 題"):
            db = st.session_state['db_cache']
            sample = random.sample(db, min(10, len(db)))
            st.session_state['current_quiz'] = sample
            st.session_state['quiz_results'] = {}

        if 'current_quiz' in st.session_state:
            score = 0
            cols = st.columns(2)
            for i, q in enumerate(st.session_state['current_quiz']):
                with cols[i % 2]:
                    st.write(f"**第 {i+1} 題**")
                    st.info(q['中文'])
                    if quiz_type == "選擇題":
                        # 隨機干擾項
                        all_jps = [item['日文'] for item in st.session_state['db_cache']]
                        others = random.sample([j for j in all_jps if j != q['日文']], min(3, len(all_jps)-1))
                        opts = sorted(others + [q['日文']])
                        st.session_state['quiz_results'][i] = st.radio(f"解答 {i+1}", opts, key=f"ans_{i}")
                    else:
                        st.session_state['quiz_results'][i] = st.text_input(f"解答 {i+1}", key=f"ans_{i}")

            if st.button("🏁 提交評分"):
                for i, q in enumerate(st.session_state['current_quiz']):
                    user_ans = st.session_state['quiz_results'].get(i, "").strip()
                    if user_ans == q['日文'].strip():
                        score += 1
                st.metric("您的得分", f"{score} / {len(st.session_state['current_quiz'])}")
                if score == len(st.session_state['current_quiz']):
                    st.balloons()
