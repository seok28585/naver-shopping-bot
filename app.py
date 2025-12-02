import streamlit as st
import pandas as pd
import requests
import time
import urllib.parse
from io import BytesIO
from PIL import Image
import imagehash
import concurrent.futures

# ==============================================================================
# 1. [기능 모듈] 이미지 처리 및 API 로직 (변동 없음)
# ==============================================================================

def load_image_from_url(url):
    """URL에서 이미지를 다운로드하여 PIL 이미지 객체로 변환"""
    if not isinstance(url, str) or not url.startswith('http'):
        return None  
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers, stream=True, timeout=3)
        response.raise_for_status()
        img = Image.open(response.raw)
        return img
    except Exception:
        return None

def calculate_similarity(img1, img2):
    """두 이미지의 Perceptual Hash(pHash) 비교"""
    try:
        hash1 = imagehash.phash(img1)
        hash2 = imagehash.phash(img2)
        return hash1 - hash2 
    except:
        return 100

def find_best_match_optimized(client_id, client_secret, product_name, target_img_url):
    """텍스트 검색 + 이미지 병렬 다운로드 + 유사도 분석"""
    api_url = "https://openapi.naver.com/v1/search/shop.json"
    headers = {
        "X-Naver-Client-Id": client_id,
        "X-Naver-Client-Secret": client_secret
    }
    params = {"query": product_name, "display": 5, "sort": "sim"}

    try:
        response = requests.get(api_url, headers=headers, params=params)
        if response.status_code != 200:
            return "API_Error", "", f"API오류({response.status_code})"
        
        items = response.json().get('items')
        if not items:
            return "검색결과없음", "", "검색결과 0건"

        target_img = load_image_from_url(target_img_url)
        
        if target_img is None:
            best_item = items[0]
            lprice = best_item.get('lprice')
            link = f"https://search.shopping.naver.com/search/all?query={urllib.parse.quote(product_name)}"
            return lprice, link, "원본이미지 로드실패(1순위대체)"

        # 병렬 이미지 다운로드
        candidate_images = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            future_to_item = {
                executor.submit(load_image_from_url, item.get('image')): item 
                for item in items
            }
            for future in concurrent.futures.as_completed(future_to_item):
                item = future_to_item[future]
                try:
                    img = future.result()
                    if img:
                        candidate_images.append((item, img))
                except Exception:
                    continue

        best_score = 100
        best_item = items[0]
        
        if candidate_images:
            for item, img in candidate_images:
                score = calculate_similarity(target_img, img)
                if score < best_score:
                    best_score = score
                    best_item = item
            
            if best_score <= 15:
                note = f"이미지매칭성공(오차:{best_score})"
            elif best_score <= 25:
                note = f"유사도보통(오차:{best_score})"
            else:
                note = f"유사이미지없음(1순위대체/오차:{best_score})"
        else:
            note = "후보이미지 다운실패(1순위대체)"

        lprice = best_item.get('lprice')
        search_url = f"https://search.shopping.naver.com/search/all?query={urllib.parse.quote(product_name)}"
        
        return lprice, search_url, note

    except Exception as e:
        return f"Error", "", f"시스템오류:{str(e)}"

# ==============================================================================
# 2. [UI 모듈] Streamlit 웹 인터페이스 (수정됨: Secrets 적용)
# ==============================================================================

st.set_page_config(page_title="High-Speed 최저가 검색기", layout="wide")

st.title("⚡ 네이버 최저가 검색기")
st.markdown("병렬 처리와 자동 로그인 기능이 적용된 전문가용 버전입니다.")

# --- 사이드바 설정 (Secrets 로직 적용) ---
with st.sidebar:
    st.header("⚙️ API 설정")
    
    # 1. Secrets 확인 (자동 로그인 시도)
    # Streamlit Cloud나 로컬 secrets.toml에 키가 있는지 확인
    if "NAVER_CLIENT_ID" in st.secrets and "NAVER_CLIENT_SECRET" in st.secrets:
        client_id = st.secrets["NAVER_CLIENT_ID"]
        client_secret = st.secrets["NAVER_CLIENT_SECRET"]
        st.success("✅ API Key가 보안 저장소에서 자동 로드되었습니다.")
    
    # 2. Secrets가 없으면 수동 입력창 표시 (Fallback)
    else:
        st.info("Secrets가 설정되지 않았습니다. 키를 직접 입력하세요.")
        client_id = st.text_input("Client ID", type="password")
        client_secret = st.text_input("Client Secret", type="password")

    st.divider()
    st.markdown("Developed by **WebProgramming Expert**")

# --- 메인 로직 (이전과 동일) ---
uploaded_file = st.file_uploader("엑셀 파일 업로드 (.xlsx)", type=['xlsx'])

if uploaded_file is not None:
    try:
        df = pd.read_excel(uploaded_file)
        st.success("✅ 파일 로드 완료")
        st.dataframe(df.head(3))

        col1, col2 = st.columns(2)
        all_columns = df.columns.tolist()

        with col1:
            st.info("입력 데이터")
            idx_img = next((i for i, c in enumerate(all_columns) if '이미지' in str(c)), 0)
            idx_name = next((i for i, c in enumerate(all_columns) if '상품명' in str(c)), 1)
            img_col = st.selectbox("📷 대표 이미지 URL (A열)", all_columns, index=idx_img)
            name_col = st.selectbox("📦 상품명 (B열)", all_columns, index=idx_name)

        with col2:
            st.warning("출력 데이터")
            idx_price = next((i for i, c in enumerate(all_columns) if '최저가' in str(c)), 2)
            idx_ship = next((i for i, c in enumerate(all_columns) if '배송비' in str(c) or '비고' in str(c)), 3)
            idx_url = next((i for i, c in enumerate(all_columns) if 'URL' in str(c) or '링크' in str(c)), 4)
            price_dest = st.selectbox("💰 최저가 저장 위치", all_columns, index=idx_price)
            ship_dest = st.selectbox("🚚 비고/상태 저장 위치", all_columns, index=idx_ship)
            url_dest = st.selectbox("🔗 검색 URL 저장 위치", all_columns, index=idx_url)

        st.markdown("---")
        if st.button("🚀 고속 검색 시작"):
            if not client_id or not client_secret:
                st.error("⚠️ API Key가 없습니다. 사이드바 설정을 확인하세요.")
            else:
                progress_bar = st.progress(0)
                status_text = st.empty()
                
                total_rows = len(df)
                start_time = time.time()

                for i, row in df.iterrows():
                    p_name = str(row[name_col])
                    p_img_url = str(row[img_col])

                    status_text.markdown(f"**진행 중 ({i+1}/{total_rows})** : `{p_name}`")

                    if p_name and p_name != 'nan':
                        price, url, note = find_best_match_optimized(
                            client_id, client_secret, p_name, p_img_url
                        )
                        df.at[i, price_dest] = price
                        df.at[i, url_dest] = url
                        df.at[i, ship_dest] = note
                    
                    progress_bar.progress((i + 1) / total_rows)

            
                elapsed_time = time.time() - start_time
                status_text.empty()
                st.success(f"🎉 작업 완료! (소요 시간: {elapsed_time:.1f}초)")
                
                st.subheader("📊 결과 미리보기")
                st.dataframe(df.head())

                output = BytesIO()
                with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                    df.to_excel(writer, index=False)
                
                st.download_button(
                    label="📥 결과 엑셀 다운로드",
                    data=output.getvalue(),
                    file_name=f"최저가조사_{int(time.time())}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )

    except Exception as e:
        st.error(f"❌ 오류 발생: {str(e)}")

