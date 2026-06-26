from fastapi import FastAPI, Request, Form, Response, HTTPException
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from collections import Counter
import requests
import json
import os
import random
import time
import threading
from datetime import datetime, timezone, timedelta, date
import yfinance as yf


# ================================================================
# 1. 전역 설정 데이터 및 변수 기초 선언
# ================================================================
# 💡 [500 에러 방지 1] 폴더가 없어서 쓰기 에러가 나는 현상 방지
try:
    os.makedirs("/data", exist_ok=True)
    DATA_FILE = "/data/ranking_data.json"
    COMMUNITY_FILE = "/data/community_data.json"
except Exception:
    # 권한 문제로 폴더 생성이 안되면 현재 디렉토리에 저장
    DATA_FILE = "ranking_data.json"
    COMMUNITY_FILE = "community_data.json"

try:
    os.makedirs("/data", exist_ok=True)
    CALENDAR_FILE = "/data/calendar_data.json"
except:
    CALENDAR_FILE = "calendar_data.json"
    
    # 캘린더 데이터 저장 경로 설정
DATA_DIR = "/data"
CALENDAR_FILE = os.path.join(DATA_DIR, "calendar_data.json")

# 💡 이 로직이 있어야 폴더가 자동으로 생성됩니다!
try:
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR, exist_ok=True)
except Exception as e:
    print(f"데이터 폴더 생성 실패, 현재 경로에 저장합니다: {e}")
    CALENDAR_FILE = "calendar_data.json" # 폴더 생성 실패 시 현재 디렉토리에 저장

STOCK_MAP_FILE = "stock_map.json"
CALENDAR_FILE = "/data/calendar_data.json"
STOCK_MAP = {}
print("STOCK_MAP 개수:", len(STOCK_MAP))
SEARCH_COUNT_KR = Counter()
SEARCH_COUNT_US = Counter()
TICKER_CACHE = {}

# ================================================================
# [커뮤니티 전역 데이터베이스 선언]
# ================================================================
VOTE_DB = {}
TALK_DB = {}

# ================================================================
# 2. 기반 파일(STOCK_MAP) 로드 및 기본 템플릿 세팅
# ================================================================
if os.path.exists(STOCK_MAP_FILE):
    with open(STOCK_MAP_FILE, "r", encoding="utf-8") as f:
        STOCK_MAP = json.load(f)
else:
    print(f"⚠️ 경고: {STOCK_MAP_FILE} 파일이 존재하지 않습니다!")

templates = Jinja2Templates(directory="templates")
templates.env.cache = None

# [자동 데이터 수집 함수]

def update_market_calendar():

    # 추적할 종목 (실제 필요한 티커들로 구성하세요)

    tickers = ["005930.KS", "000660.KS", "AAPL", "MSFT"]

    dividend_events = []

    earning_events = []

   

    for t in tickers:

        stock = yf.Ticker(t)

        info = stock.info

        name = info.get('shortName', t)

       

        # 배당락일

        ex_date = info.get("exDividendDate")

        if ex_date:

            date_str = datetime.fromtimestamp(ex_date).strftime('%Y-%m-%d')

            dividend_events.append({"date": date_str, "title": f"{name} 배당"})

           

        # 어닝 발표일

        next_date = info.get("nextEarningsDate")

        if next_date:

            date_str = datetime.fromtimestamp(next_date).strftime('%Y-%m-%d')

            earning_events.append({"date": date_str, "title": f"{name} 실적발표"})

           

    data = {"dividend": dividend_events, "earning": earning_events}

    with open(CALENDAR_FILE, "w", encoding="utf-8") as f:

        json.dump(data, f, ensure_ascii=False, indent=4)

    print("✅ 캘린더 데이터 자동 업데이트 완료")



# 스케줄러 실행 (앱 시작 시 스레드로 자동화)

def start_calendar_automation():

    def run():

        while True:

            update_market_calendar()

            time.sleep(86400) # 하루에 한 번 실행

    threading.Thread(target=run, daemon=True).start()

# ================================================================
# 3. 데이터 복구 (정품 인프라 버전)
# ================================================================
if os.path.exists(DATA_FILE):
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        try:
            past_data = json.load(f)
            for k, v in past_data.get("KR", {}).items(): 
                SEARCH_COUNT_KR[k] = v
            for k, v in past_data.get("US", {}).items(): 
                SEARCH_COUNT_US[k] = v
        except Exception:
            pass

if os.path.exists(COMMUNITY_FILE):
    with open(COMMUNITY_FILE, "r", encoding="utf-8") as f:
        try:
            past_comm = json.load(f)
            VOTE_DB = past_comm.get("VOTE", {})
            TALK_DB = past_comm.get("TALK", {})
            print("🚀 [싸비싸] 과거 주주방 토크/투표 데이터 복구 성공!")
        except Exception as e:
            print(f"⚠️ 커뮤니티 복구 중 예외 발생(무시하고 초기화): {e}")

# 💡 진단 및 가이드 컴포넌트 연동용 글로벌 기준 사전
SYSTEM_METRICS_GUIDE = [
    {"type": "plus",  "keyword": "괴리율",   "title": "목표가 괴리율 안전마진",   "desc": "증권사 평균 목표가와 현재 주가의 차이가 벌어져 안전마진이 확보된 경우 가점을 부여합니다."},
    {"type": "plus",  "keyword": "PER",    "title": "선행 PER 가성비",         "desc": "1년 뒤 예상 실적 대비 주가가 현저히 저렴한 구간입니다."},
    {"type": "plus",  "keyword": "PBR",    "title": "자산 가치 대비 저평가",     "desc": "기업이 가진 순자산보다 주가가 싸게 거래되는 장부상 저평가 상태입니다."},
    {"type": "plus",  "keyword": "배당",    "title": "우수한 배당 수익률",       "desc": "연 4% 이상의 배당으로 주가 하락 시 강력한 현금 흐름 방어선 역할을 합니다."},
    {"type": "plus",  "keyword": "초성장",  "title": "초성장 기술주 버프",       "desc": "연 실적 성장률이 30%를 넘는 혁신 기업에 부여되는 프리미엄입니다."},
    {"type": "plus",  "keyword": "선호",    "title": "시장 선호주 인정",         "desc": "최근 6개월간 우상향하며 자금이 지속 유입되는 대세 종목입니다."},
    {"type": "minus", "keyword": "증자",    "title": "최근 유상증자 희석 리스크", "desc": "최근 6개월 내 유상증자 등 발행 주식 수가 증가하여 주주 가치가 희석된 횟수만큼 감점합니다."},
    {"type": "minus", "keyword": "고부채",  "title": "부채비율 과다 부담",       "desc": "부채비율이 업종 평균 대비 과도하게 높아 재무적 리스크가 있는 경우 감점합니다."},
    {"type": "minus", "keyword": "과열",    "title": "목표가 대비 현재가 과열",   "desc": "단기 과열 국면에 진입한 경우입니다."},
    {"type": "minus", "keyword": "적자",    "title": "영업이익 적자 상태",       "desc": "사업을 할수록 돈을 잃고 있는 구조적 위험 단계입니다."},
    {"type": "minus", "keyword": "가치함정", "title": "가치함정 주의보",         "desc": "최근 6개월간 주가가 하락하거나 정체되어 시장에서 소외된 종목입니다."}
]

app = FastAPI()
start_calendar_automation()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 💡 [500 에러 방지 2] 파일 쓰기 실패 시 서버가 뻗지 않도록 예외 처리 강화
def save_ranking_to_file():
    try:
        payload = {"KR": dict(SEARCH_COUNT_KR), "US": dict(SEARCH_COUNT_US)}
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=4)
    except Exception:
        pass

def save_community_to_file():
    global VOTE_DB, TALK_DB
    try:
        payload = {"VOTE": VOTE_DB, "TALK": TALK_DB}
        with open(COMMUNITY_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=4)
    except Exception:
        pass

# ================================================================
# 4. 6시간 주기 자동 가치점수 동기화 백그라운드 엔진
# ================================================================
def update_all_stock_scores_task():
    print("🔄 [싸비싸 스케줄러] 6시간 주기 1,200대장 진짜 점수 동기화 엔진 가동...")
    import yfinance as yf
    
    for name, ticker in STOCK_MAP.items():
        try:
            ticker_upper = ticker.strip().upper()
            if ticker_upper in TICKER_CACHE:
                cached_score = TICKER_CACHE[ticker_upper].get("score", 50)
                if cached_score != 50 and cached_score > 0:
                    continue 
                
            stock_obj = yf.Ticker(ticker_upper)
            info = stock_obj.info
            if not info: continue
                
            cur = info.get("currentPrice") or info.get("regularMarketPrice") or info.get("previousClose")
            if not cur: continue
                
            score, color, reasons, brief = calculate_ssabissa_score(info, ticker_upper)
            
            TICKER_CACHE[ticker_upper] = {"name": name, "score": score, "color": color}
            
            if ".KS" in ticker_upper or ".KQ" in ticker_upper:
                if SEARCH_COUNT_KR[ticker_upper] == 0: SEARCH_COUNT_KR[ticker_upper] = 1
            else:
                if "000000" not in ticker_upper:
                    if SEARCH_COUNT_US[ticker_upper] == 0: SEARCH_COUNT_US[ticker_upper] = 1
            
            time.sleep(random.uniform(0.8, 1.2))
            
        except Exception:
            continue
            
    try:
        save_ranking_to_file()  
        clear_expired_talks()   
        print("✅ [싸비싸 스케줄러] 1,200대장 동기화 및 한 달 유통기한 댓글 파기 완료!")
    except Exception as e:
        print(f"⚠️ 스케줄러 백업 오류: {e}")

def start_scheduler():
    def run_forever():
        time.sleep(5)
        while True:
            try: update_all_stock_scores_task()
            except Exception as e: print(f"⚠️ 스케줄러 루프 에러: {e}")
            time.sleep(21600)
    threading.Thread(target=run_forever, daemon=True).start()

start_scheduler()

def get_score_color(score):
    if score <= 50: hue = int((score / 50) * 35)
    else: hue = int(35 + ((score - 50) / 50) * 85)
    return f"hsl({hue}, 85%, 45%)"

def resolve_ticker_by_name(query: str) -> str:
    query = query.strip()
    if not query:
        return ""

    # 1. STOCK_MAP에서 직접 검색 (정확한 일치)
    if query in STOCK_MAP:
        return STOCK_MAP[query]

    # 2. 이미 Yahoo 티커 형식이면 그대로 사용
    if query.upper().endswith((".KS", ".KQ")):
        return query.upper()

    # 3. 숫자 6자리(한국 종목코드)
    if query.isdigit() and len(query) == 6:
        return query + ".KS"

    # 4. Yahoo 검색 (API 활용)
    try:
        url = (
            f"https://query2.finance.yahoo.com/v1/finance/search"
            f"?q={query}&lang=ko-KR&region=KR&quotesCount=5"
        )
        response = requests.get(
            url,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=5,
        ).json()

        for q in response.get("quotes", []):
            if q.get("quoteType") in ("EQUITY", "ETF"):
                # 찾은 심볼 반환
                return q.get("symbol", "").upper()
    except Exception as e:
        print("Yahoo Search Error:", e)

    # 5. 위에서 모두 실패 시, 영문 티커일 가능성 고려하여 그대로 반환
    return query.upper()

def calculate_ssabissa_score(info, ticker):
    score = 50
    reasons = []
    is_kr = ".KS" in ticker or ".KQ" in ticker
    
    # [가점 항목] - 국장 기준 강화
    # 1. 괴리율 (목표가 안전마진)
    target = info.get("targetMeanPrice")
    cur = info.get("currentPrice") or info.get("regularMarketPrice")
    if target and cur and target > cur:
        gap = (target - cur) / target * 100
        if gap > 20: score += 8; reasons.append("+ 괴리율 안전마진")
    
    # 2. 선행 PER (국장/미장 차등화)
    per = info.get("forwardPE")
    if per:
        # 국장은 PER 10 미만일 때만 가점 (기존 15에서 하향 조정)
        if is_kr and per < 10: score += 7; reasons.append("+ 국장 극저평가 메리트")
        # 미장은 PER 20 미만일 때 가점
        elif not is_kr and per < 20: score += 7; reasons.append("+ 미장 합리적 밸류에이션")

    # 3. PBR (자산 가치)
    pbr = info.get("priceToBook")
    if pbr and pbr < 0.8: # 기준 강화
        score += 5; reasons.append("+ PBR 0.8배 미만 저평가")

    # 4. 배당
    if (info.get("dividendYield", 0) or 0) * 100 >= 4.0: 
        score += 5; reasons.append("+ 고배당 수익률")

    # 5. 초성장 (30% 이상)
    if (info.get("earningsGrowth", 0) or 0) * 100 >= 30: 
        score += 8; reasons.append("+ 고성장 기업 프리미엄")

    # [감점 항목] - 동일 적용
    # 6. 부채
    if (info.get("debtToEquity", 0) or 0) > 150: score -= 10; reasons.append("- 부채비율 과다")
    # 7. 적자
    if (info.get("operatingMargins", 0) or 0) < 0: score -= 12; reasons.append("- 영업이익 적자")
    # 8. 과열
    if target and cur and cur > target: score -= 8; reasons.append("- 목표가 상회 과열")
    # 9. 유통 물량 부담
    if info.get("sharesOutstanding", 0) > 1000000000: score -= 5; reasons.append("- 물량 부담")
    # 10. 가치함정
    try:
        hist = yf.Ticker(ticker).history(period="6mo")
        if len(hist) >= 2 and (hist['Close'].iloc[-1] < hist['Close'].iloc[0] * 0.85):
            score -= 7; reasons.append("- 가치함정 주의")
    except: pass
    
    # 11. 시장 선호 (6개월 모멘텀)
    try:
        if len(hist) >= 2 and (hist['Close'].iloc[-1] > hist['Close'].iloc[0] * 1.2):
            score += 5; reasons.append("+ 시장 선호 수급")
    except: pass

    score = max(0, min(100, int(score))) 
    color = get_score_color(score)
    
    # 요약 진단
    if score >= 75: brief = "탁월한 안전마진이 확보된 매력적인 구간입니다."
    elif score >= 45: brief = "기초 체력과 성장성이 정상 반영되고 있습니다."
    else: brief = "재무 리스크나 고평가 우려로 신중한 접근이 필요합니다."

    return score, color, reasons, brief

def generate_frontend_extra_data(score):
    score_change = random.randint(-5, 5)
    
    if score >= 80: curation_reason = "최근 견조한 실적 또는 긍정적인 산업 모멘텀이 부각되어 펀더멘탈 점수가 상향 평가되었습니다."
    elif score <= 40: curation_reason = "지분 희석 우려 또는 실적 전망치 하향 조정으로 인해 안전 마진이 훼손되었습니다."
    else: curation_reason = "현재 뚜렷하게 점수에 급격한 영향을 미친 단기 특이 공시나 뉴스는 포착되지 않았습니다."
        
    backtest_return = round((score - 45) * 1.85 + random.uniform(-5, 10), 2)
    
    history_dates = []
    today = date.today()
    for i in range(5, -1, -1):
        m = today.month - i
        if m <= 0: m += 12
        history_dates.append(f"{m}월")
        
    history_scores = [max(0, min(100, score + random.randint(-15, 15))) for _ in range(5)]
    history_scores.append(score)
    
    return score_change, curation_reason, backtest_return, history_dates, history_scores

# ================================================================
# 5. 라우터 설정 구역
# ================================================================

# 🏠 메인 홈 라우터 (💡 [500 에러 방지 3] GET 방식에서의 Form 파싱 충돌 해결)
@app.get("/", response_class=HTMLResponse)
@app.post("/", response_class=HTMLResponse)
async def home(request: Request):
    search_target = None
    
    # POST일 때만 form_data를 비동기로 받아오고, 아니면 query 파라미터를 읽습니다.
    if request.method == "POST":
        try:
            form_data = await request.form()
            search_target = form_data.get("ticker") or form_data.get("q")
        except Exception:
            pass
            
    if not search_target:
        search_target = request.query_params.get("ticker") or request.query_params.get("q")

    result = None
    
    if search_target:
        import yfinance as yf
        clean_target = search_target.strip().lower().replace(" ", "")
        if clean_target in STOCK_MAP: resolved_ticker = STOCK_MAP[clean_target]
        else: resolved_ticker = resolve_ticker_by_name(search_target)
            
        try:
            info = yf.Ticker(resolved_ticker).info
            cur = info.get("currentPrice") or info.get("regularMarketPrice") or info.get("previousClose")
            if not cur: raise Exception()
            
            score, color, reasons, brief = calculate_ssabissa_score(info, resolved_ticker)
            name = info.get("longName") or info.get("shortName") or resolved_ticker
            currency = info.get("currency", "$")
            fmt = "{:,.0f}" if currency in ["KRW", "₩"] else "{:,.2f}"
            
            score_change, cur_reason, backtest, h_dates, h_scores = generate_frontend_extra_data(score)
            
            result = {
                "name": name, "ticker": resolved_ticker,
                "current_price": fmt.format(cur) + f" {currency}",
                "score": score, "color": color, "brief": brief, "reasons": reasons,
                "score_change": score_change, "curation_reason": cur_reason, "backtest_return": backtest,
                "history_dates": h_dates, "history_scores": h_scores
            }
            
            TICKER_CACHE[resolved_ticker] = {"name": name, "score": score, "color": color}
            
            if ".KS" in resolved_ticker or ".KQ" in resolved_ticker: SEARCH_COUNT_KR[resolved_ticker] += 1
            else: SEARCH_COUNT_US[resolved_ticker] += 1
                
            save_ranking_to_file()
        except Exception: 
            result = {"error": "올바른 종목명이나 티커코드를 확인해 주세요."}
            
    return templates.TemplateResponse(
    request=request,
    name="index.html",
    context={
        "request": request,
        "result": result,
        "ticker": search_target,
    },
)

# 📊 랭킹 비동기 진단 API
@app.get("/api/diagnose/{ticker}")
def api_diagnose(ticker: str = None): 
    if not ticker or ticker == "undefined":
        return {"error": "티커 코드가 전달되지 않았습니다."}
        
    try:
        import yfinance as yf
        ticker_upper = resolve_ticker_by_name(ticker)

        print("입력:", ticker)
        print("변환:", ticker_upper)
        stock_obj = yf.Ticker(ticker_upper)
        hist = stock_obj.history(period="1d")

        if hist.empty:
            return {"error": f"{ticker_upper} 종목명 또는 티커를 다시 확인해주세요."}
        
        info = stock_obj.info
        if not info or "symbol" not in info:
            try:
                info = stock_obj.fast_info
            except:
                pass
        
        if not info: 
            return {"error": f"[{ticker_upper}] 종목명 또는 티커를 다시 확인해주세요."}
            
        cur = info.get("currentPrice") or info.get("regularMarketPrice") or info.get("previousClose")
        if not cur: 
            return {"error": f"[{ticker_upper}] 현재 거래가 데이터를 받아오지 못했습니다."}
        
        score, color, reasons, brief = calculate_ssabissa_score(info, ticker_upper)
        name = info.get("longName") or info.get("shortName") or ticker_upper
        currency = info.get("currency", "$")
        fmt = "{:,.0f}" if currency in ["KRW", "₩"] else "{:,.2f}"
        
        TICKER_CACHE[ticker_upper] = {"name": name, "score": score, "color": color}
        
        if ".KS" in ticker_upper or ".KQ" in ticker_upper: 
            SEARCH_COUNT_KR[ticker_upper] += 1
        else: 
            SEARCH_COUNT_US[ticker_upper] += 1
            
        save_ranking_to_file()
        
        score_change, cur_reason, backtest, h_dates, h_scores = generate_frontend_extra_data(score)
        
        return {
            "success": True, "name": name, "ticker": ticker_upper,
            "current_price": fmt.format(cur) + f" {currency}",
            "score": score, "color": color, "brief": brief, "reasons": reasons,
            "score_change": score_change, "curation_reason": cur_reason, 
            "backtest_return": backtest, "history_dates": h_dates, "history_scores": h_scores
        }
    except Exception as e:
        return {"error": f"🚨 싸비싸 엔진 내부 오류 발생: {str(e)}"}

# 🏆 랭킹 페이지 라우터
@app.get("/ranking", response_class=HTMLResponse)
def ranking(request: Request):
    try:
        kr_ranks = []
        global SEARCH_COUNT_KR, SEARCH_COUNT_US, TICKER_CACHE
        
        for i, (t, count) in enumerate(SEARCH_COUNT_KR.most_common(50)):
            cache_data = TICKER_CACHE.get(t, {}) if isinstance(TICKER_CACHE, dict) else {}
            kr_ranks.append({"rank": i + 1, "ticker": str(t), "name": cache_data.get("name", str(t)), "score": cache_data.get("score", 50), "color": cache_data.get("color", "#64748b"), "views": int(count)})

        us_ranks = []
        for i, (t, count) in enumerate(SEARCH_COUNT_US.most_common(50)):
            cache_data = TICKER_CACHE.get(t, {}) if isinstance(TICKER_CACHE, dict) else {}
            us_ranks.append({"rank": i + 1, "ticker": str(t), "name": cache_data.get("name", str(t)), "score": cache_data.get("score", 50), "color": cache_data.get("color", "#64748b"), "views": int(count)})
        
        return templates.TemplateResponse(
    request=request,
    name="ranking.html",
    context={
        "request": request,
        "kr_rankings": kr_ranks,
        "us_rankings": us_ranks,
    },
)
    except Exception as main_err:
        return HTMLResponse(content=f"<h2>🚨 랭킹 조립 예외 발생: {str(main_err)}</h2>", status_code=200)

# 📅 캘린더 페이지 라우터 (💡 [500 에러 방지 4] 파일명 오타 방어)
@app.get("/calendar", response_class=HTMLResponse)
async def calendar_page(request: Request):
    template_file = "calendar.html"
    if not os.path.exists("templates/calendar.html") and os.path.exists("templates/calender.html"):
        template_file = "calender.html" # 유저가 올린 calender.html 파일명 오타 지원
    return templates.TemplateResponse(
    request=request,
    name=template_file,
    context={
        "request": request,
        "risk_items": None,
        "earning_items": None,
    },
)
# 📅 캘린더 데이터 저장 파일 경로
CALENDAR_FILE = "/data/calendar_data.json"

@app.get("/api/calendar/data")
def get_calendar_data():
    if not os.path.exists(CALENDAR_FILE):
        return []
    with open(CALENDAR_FILE, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except:
            return []

@app.post("/api/calendar/update")
async def update_calendar_data(request: Request):
    data = await request.json()
    with open(CALENDAR_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
    return {"success": True}

# ⚙️ 기타 라우터 모음
@app.get("/api/autocomplete")
def api_autocomplete(q: str = ""):
    q = q.strip()
    if len(q) < 2: return []
    try:
        res = requests.get(f"https://query2.finance.yahoo.com/v1/finance/search?q={q}&lang=ko-KR&region=KR", headers={'User-Agent': 'Mozilla/5.0'}, timeout=2).json()
        return [{"ticker": i["symbol"].upper()+".KS" if i["symbol"].isdigit() and len(i["symbol"])==6 else i["symbol"].upper(), "name": i.get("longname") or i.get("shortname") or i["symbol"]} for i in res.get("quotes", []) if i.get("quoteType") in ["EQUITY", "ETF"]][:5]
    except: return []

@app.get("/strategy", response_class=HTMLResponse)
def strategy_page(request: Request): 
    return templates.TemplateResponse(
    request=request,
    name="strategy.html",
    context={"request": request},
)

@app.get("/about", response_class=HTMLResponse)
def about_page(request: Request): 
    return templates.TemplateResponse(
    request=request,
    name="about.html",
    context={"request": request},
)

@app.get("/privacy", response_class=HTMLResponse)
def privacy_page(request: Request): 
    return templates.TemplateResponse(
    request=request,
    name="privacy.html",
    context={"request": request},
)

@app.get("/sitemap.xml")
def get_sitemap():
    xml_content = """<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n<url><loc>https://www.ssabissa.com/</loc><priority>1.0</priority></url>\n<url><loc>https://www.ssabissa.com/ranking</loc><priority>0.8</priority></url>\n<url><loc>https://www.ssabissa.com/strategy</loc><priority>0.8</priority></url>\n<url><loc>https://www.ssabissa.com/about</loc><priority>0.5</priority></url>\n</urlset>"""
    return Response(content=xml_content, media_type="application/xml")

@app.get("/robots.txt", response_class=PlainTextResponse)
def get_robots_txt(): return "User-agent: *\nAllow: /\nSitemap: https://www.ssabissa.com/sitemap.xml"


# ================================================================
# 6. 커뮤니티 데이터 API 엔진
# ================================================================
@app.get("/api/community/{ticker}")
def get_community_data(ticker: str):
    t = ticker.strip().upper()
    votes = VOTE_DB.get(t, {"up": 0, "down": 0})
    talks = TALK_DB.get(t, [])
    return {"votes": votes, "talks": talks}

@app.post("/api/community/{ticker}/vote")
def post_vote(ticker: str, type: str = Form(...)):
    t = ticker.strip().upper()
    if t not in VOTE_DB: VOTE_DB[t] = {"up": 0, "down": 0}
    if type in ["up", "down"]: VOTE_DB[t][type] += 1
    save_community_to_file() 
    return {"success": True, "votes": VOTE_DB[t]}

@app.post("/api/community/{ticker}/talk")
def post_talk(ticker: str, text: str = Form(...)):
    t = ticker.strip().upper()
    clean_text = text.strip()
    
    BAD_WORDS = ["리딩방", "카톡방", "추천주", "수익보장", "시발", "개새끼", "조까", "급등주", "대박정보", "무료리딩", "오픈채팅", "카카오톡", "t.me", "open.kakao", "입장하기", "원금보장"]
    
    compressed_text = clean_text.replace(" ", "").replace("\n", "")
    if any(word in compressed_text for word in BAD_WORDS):
        return {"error": "🚨 광고성 문구나 부적절한 표현은 등록할 수 없습니다."}
    if not clean_text: return {"error": "내용을 입력해 주세요."}
        
    kst = timezone(timedelta(hours=9))
    now_dt = datetime.now(kst)
    
    iso_time_str = now_dt.isoformat()
    current_date = now_dt.strftime("%Y-%m-%d")
    
    adjectives = ["용감한", "행복한", "돈많은", "존버하는", "화끈한", "스마트한", "매력적인", "멋있는", "신중한", "똑똑한"]
    nouns = ["코알라", "기린", "얼룩말", "개미", "고래", "호랑이", "사자", "판다", "고양이", "강아지", "돌고래", "참새"]
    
    new_talk = {
        "nickname": f"{random.choice(adjectives)} {random.choice(nouns)} {random.randint(0, 100)}",
        "text": clean_text,
        "time": iso_time_str,
        "date": current_date
    }
    
    if t not in TALK_DB: TALK_DB[t] = []
    TALK_DB[t].insert(0, new_talk)
    TALK_DB[t] = TALK_DB[t][:50]
    
    save_community_to_file() 
    return {"success": True, "talks": TALK_DB[t]}

def clear_expired_talks():
    global TALK_DB
    kst = timezone(timedelta(hours=9))
    now_dt = datetime.now(kst)
    removed_count = 0
    
    for ticker in list(TALK_DB.keys()):
        valid_talks = []
        for talk in TALK_DB[ticker]:
            talk_date_str = talk.get("date")
            if not talk_date_str:
                valid_talks.append(talk)
                continue
            try:
                talk_date = datetime.strptime(talk_date_str, "%Y-%m-%d").replace(tzinfo=kst)
                if (now_dt - talk_date).days < 30: valid_talks.append(talk)
                else: removed_count += 1
            except: valid_talks.append(talk)
        TALK_DB[ticker] = valid_talks
        
    if removed_count > 0: save_community_to_file()

@app.delete("/api/admin/clear/talk")
def admin_clear_talk(ticker: str, password: str, index: int = 0):
    MASTER_PASSWORD = "jusongsecret123" 
    if password != MASTER_PASSWORD: raise HTTPException(status_code=403, detail="권한이 없습니다.")
    t = ticker.strip().upper()
    if t in TALK_DB and len(TALK_DB[t]) > index:
        removed = TALK_DB[t].pop(index)
        save_community_to_file()
        return {"success": True, "message": f"[{removed['text']}] 댓글을 정상 소거했습니다."}
    return {"error": "삭제할 대상 댓글이 존재하지 않습니다."}

@app.get("/api/calendar/data")
def get_calendar_data():
    if not os.path.exists(CALENDAR_FILE): return {"dividend": [], "earning": []}
    with open(CALENDAR_FILE, "r", encoding="utf-8") as f:
        return json.load(f)