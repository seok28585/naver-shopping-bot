import streamlit as st
import pandas as pd
import requests
import time
import urllib.parse
from io import BytesIO
from PIL import Image
import imagehash
import concurrent.futures # 병렬 처리를 위한 핵심 라이브러리

# ==============================================================================
# 1. [핵심 기능 모듈] 이미지 처리 및 API 로직
# ==============================================================================

def load_image_from_url(url):
    """
    URL에서 이미지를 다운로드하여 PIL 이미지 객체로 변환합니다.
    User-Agent 헤더를 추가하여 차단을 방지합니다.
    """
    if not isinstance(url, str) or not url.startswith('http'):
        return None
        
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        # 타임아웃을 짧게 설정하여 응답 없는 이미지는 빠르게 건너뜀
        response = requests.get(url, headers=headers, stream=True, timeout=3)
        response.raise_for_status()
        img = Image.open(response.raw)
        return img
    except Exception:
        return None

def calculate_similarity(img1, img2):
    """
    두 이미지의 Perceptual Hash(pHash)를 비교하여 Hamming Distance를 반환합니다.
    - 0: 완전 동일
    - 10 이하: 매우 유사
    - 20 이상: 다른 이미지일 가능성 높음
    """
    try:
        hash1 = imagehash.phash(img1)
        hash2 = imagehash.phash(img2)
        return hash1 - hash2 
    except:
        return 100 # 비교 불가 시 큰 값 반환

def find_best_match_optimized(client_id, client_secret, product_name, target_img_url):
    """
    [속도 최적화 버전]
    상품명으로 검색 후, 결과 이미지들을 '병렬(Parallel)'로 다운로드하여
    타겟 이미지와 가장 유사한 상품을 찾아냅니다.
    """
    api_url = "https://openapi.naver.com/v1/search/shop.json"
    headers = {
        "X-Naver-Client-Id": client_id,
        "X-Naver-Client-Secret": client_secret
    }
    # 정확도를 위해 상위 5개(display=5) 분석
    params = {"query": product_name, "display": 5, "sort": "sim"}

    try:
        # 1. 네이버 쇼핑 API 호출 (텍스트 검색)
        response = requests.get(api_url, headers=headers, params=params)
        if response.status_code != 200:
            return "API_Error", "", f"API오류({response.status_code})"
        
        items = response.json().get('items')
        if not items:
            return "검색결과없음", "", "검색결과 0건"

        # 2. 기준이 되는(엑셀의) 타겟 이미지 다운로드
        target_img = load_image_from_url(target_img_url)
        
        # 타겟 이미지가 없거나 로드 실패 시 -> 텍스트 검색 1순위 결과 반환
        if target_img is None:
            best_item = items[0]
            lprice = best_item.get('lprice')
            link = f"https://search.shopping.naver.com/search/all?query={urllib.parse.quote(product_name)}"
            return lprice, link, "원본이미지 로드실패(1순위대체)"

        # 3. [속도 최적화 구간] 후보 이미지들 병렬 다운로드
        # ThreadPoolExecutor를 사용하여 5장의 이미지를 동시에 요청합니다.
        candidate_images = [] # (item_data, image_object) 튜플을 담을 리스트
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            # {Future객체: item데이터} 형태의 딕셔너리 생성
            future_to_item = {
                executor.submit(load_image_from_url, item.get('image')): item 
                for item in items
            }
            
            # 완료되는 순서대로 처리
            for future in concurrent.futures.as_completed(future_to_item):
                item = future_to_item[future]
                try:
                    img = future.result()
                    if img:
                        candidate_images.append((item, img))
                except Exception:
                    continue # 이미지 다운 실패 시 건너뜀

        # 4. 이미지 유사도 비교 로직
        best_score = 100
        best_item = items[0] # 기본값은 1순위
        
        if candidate_images:
            for item, img in candidate_images:
                score = calculate_similarity(target_img, img)
                
                # 점수가 더 낮을수록(유사할수록) 갱신
                if score < best_score:
                    best_score = score
                    best_item = item
            
            # 결과 주석 작성
            if best_score <= 15:
                note = f"이미지매칭성공(오차:{best_score})"
            elif best_score <= 25:
                note = f"유사도보통(오차:{best_score})"
            else:
                note = f"유사이미지없음(1순위대체/오차:{best_score})"
        else:
            note = "후보이미지 다운실패(1순위대체)"

        # 5. 최종 결과 반환
        lprice = best_item.get('lprice')
        # 사용자가 보기 편한 검색 결과 페이지 링크 생성
        search_url = f"https://search.shopping.naver.com/search/all?query={urllib.parse.quote(product_name)}"
        
        return lprice, search_url, note

    except Exception as e:
        return f"Error", "", f"시스템오류:{str(e)}"

# ==============================================================================
# 2. [UI 모듈] Streamlit 웹 인터페이스
# ==============================================================================

st.set_page_config(page_title="High-Speed 최저가 검색기", layout="wide")

st.title("⚡ AI 이미지 매칭 & 고속 최저가 검색기")
st.markdown("""
**기능:** 상품명과 이미지 URL을 분석하여 동일 상품의 최저가를 찾아냅니다.
**특징:** 병렬 처리(Multi-threading) 기술이 적용되어 속도가 매우 빠릅니다.
""")

# --- 사이드바 설정 ---
with st.sidebar:
    st.header("⚙️ API 설정")
    st.info("네이버 개발자 센터 Client ID/Secret 필요")
    client_id = st.text_input("Client ID", type="password")
    client_secret = st.text_input("Client Secret", type="password")
    st.divider()
    st.markdown("Developed by **WebProgramming Expert**")

# --- 메인 화면: 파일 업로드 ---
uploaded_file = st.file_uploader("엑셀 파일 업로드 (.xlsx)", type=['xlsx'])

if uploaded_file is not None:
    try:
        df = pd.read_excel(uploaded_file)
        st.success("✅ 파일이 정상적으로 로드되었습니다.")
        
        st.markdown("### 1. 데이터 미리보기")
        st.dataframe(df.head(3))

        st.markdown("### 2. 컬럼 매핑 (데이터 위치 지정)")
        col1, col2 = st.columns(2)
        all_columns = df.columns.tolist()

        with col1:
            st.info("입력 데이터 (읽어올 열)")
            # 스마트한 기본값 선택 (header 이름에 '이미지', '상품명'이 있으면 자동 선택 시도)
            idx_img = next((i for i, c in enumerate(all_columns) if '이미지' in str(c)), 0)
            idx_name = next((i for i, c in enumerate(all_columns) if '상품명' in str(c)), 1)
            
            img_col = st.selectbox("📷 대표 이미지 URL (A열)", all_columns, index=idx_img)
            name_col = st.selectbox("📦 상품명 (B열)", all_columns, index=idx_name)

        with col2:
            st.warning("출력 데이터 (저장할 열 - 덮어씌워짐)")
            idx_price = next((i for i, c in enumerate(all_columns) if '최저가' in str(c)), 2)
            idx_ship = next((i for i, c in enumerate(all_columns) if '배송비' in str(c) or '비고' in str(c)), 3)
            idx_url = next((i for i, c in enumerate(all_columns) if 'URL' in str(c) or '링크' in str(c)), 4)

            price_dest = st.selectbox("💰 최저가 저장 위치", all_columns, index=idx_price)
            ship_dest = st.selectbox("🚚 비고/상태 저장 위치", all_columns, index=idx_ship)
            url_dest = st.selectbox("🔗 검색 URL 저장 위치", all_columns, index=idx_url)

        # --- 실행 버튼 ---
        st.markdown("---")
        if st.button("🚀 고속 검색 시작 (Start)"):
            if not client_id or not client_secret:
                st.error("⚠️ 사이드바에 API Key를 먼저 입력해주세요.")
            else:
                # 진행 상태 표시를 위한 UI 요소들
                progress_bar = st.progress(0)
                status_text = st.empty()
                result_area = st.empty()
                
                total_rows = len(df)
                start_time = time.time() # 시간 측정 시작

                # 데이터 순회
                for i, row in df.iterrows():
                    p_name = str(row[name_col])
                    p_img_url = str(row[img_col])

                    # UI 업데이트
                    status_text.markdown(f"""
                    **진행 중 ({i+1}/{total_rows})** 현재 검색 상품: `{p_name}`
                    """)

                    if p_name and p_name != 'nan':
                        # 최적화된 함수 호출
                        price, url, note = find_best_match_optimized(
                            client_id, client_secret, p_name, p_img_url
                        )
                        
                        # 결과 기록
                        df.at[i, price_dest] = price
                        df.at[i, url_dest] = url
                        df.at[i, ship_dest] = note
                    
                    # 진행률 업데이트
                    progress_bar.progress((i + 1) / total_rows)

                # 완료 처리
                end_time = time.time()
                elapsed_time = end_time - start_time
                
                status_text.empty() # 진행 텍스트 제거
                st.success(f"🎉 모든 작업이 완료되었습니다! (총 소요 시간: {elapsed_time:.1f}초)")
                
                # 결과 미리보기 업데이트
                st.subheader("📊 최종 결과 미리보기")
                st.dataframe(df.head())

                # 다운로드 버튼 생성
                output = BytesIO()
                with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                    df.to_excel(writer, index=False)
                
                st.download_button(
                    label="📥 결과 엑셀 파일 다운로드",
                    data=output.getvalue(),
                    file_name=f"최저가조사_완료_{int(time.time())}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )

    except Exception as e:
        st.error(f"❌ 파일을 처리하는 중 오류가 발생했습니다: {str(e)}")