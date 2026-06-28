from fastapi import FastAPI, Request, Form, Response, HTTPException
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List
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
try:
    os.makedirs("/data", exist_ok=True)
    DATA_FILE = "/data/ranking_data.json"
    COMMUNITY_FILE = "/data/community_data.json"
    CALENDAR_FILE = "/data/calendar_data.json"
    HISTORY_FILE = "/data/history_data.json"
except Exception:
    DATA_FILE = "ranking_data.json"
    COMMUNITY_FILE = "community_data.json"
    CALENDAR_FILE = "calendar_data.json"
    HISTORY_FILE = "history_data.json"

STOCK_MAP_FILE = "stock_map.json"
STOCK_MAP = {}
if os.path.exists(STOCK_MAP_FILE):
    with open(STOCK_MAP_FILE, "r", encoding="utf-8") as f:
        STOCK_MAP = json.load(f)

print("STOCK_MAP 개수:", len(STOCK_MAP))
SEARCH_COUNT_KR = Counter()
SEARCH_COUNT_US = Counter()
TICKER_CACHE = {}

# [커뮤니티 전역 데이터베이스 선언]
VOTE_DB = {}
TALK_DB = {}

# [추천 종목 캐시 선언]
RECOMMENDATION_CACHE = []

# ================================================================
# 2. 기본 템플릿 세팅
# ================================================================
templates = Jinja2Templates(directory="templates")
templates.env.cache = None

# ================================================================
# 🚀 배당률 오류 원천 차단 전용 함수
# ================================================================
def get_dividend_percent(info):
    div_rate = info.get("dividendRate")
    price = info.get("currentPrice") or info.get("regularMarketPrice")
    
    if div_rate and price and price > 0:
        return (div_rate / price) * 100
        
    dy = info.get("dividendYield") or 0
    if dy == 0:
        return 0
        
    if dy > 0.2:
        return dy
    return dy * 100

# ================================================================
# 3. 데이터 복구 및 히스토리 관리 엔진
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
        except Exception:
            pass

def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_history(data):
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
    except Exception:
        pass

def update_and_get_history(ticker, current_score, info):
    history = load_history()
    kst = timezone(timedelta(hours=9))
    today_str = datetime.now(kst).strftime("%Y-%m-%d")
    
    if ticker not in history:
        history[ticker] = {"dates": [], "scores": [], "virtual_return": 0.0}
    
    if not history[ticker]["dates"] or history[ticker]["dates"][-1] != today_str:
        history[ticker]["dates"].append(today_str)
        history[ticker]["scores"].append(current_score)
        
        if len(history[ticker]["dates"]) > 180:
            history[ticker]["dates"].pop(0)
            history[ticker]["scores"].pop(0)
            
        if len(history[ticker]["scores"]) > 1:
            prev_score = history[ticker]["scores"][-2]
            diff = (current_score - prev_score) * 0.15 
            history[ticker]["virtual_return"] += diff
            history[ticker]["virtual_return"] = round(history[ticker]["virtual_return"], 2)
            
        save_history(history)
    else:
        history[ticker]["scores"][-1] = current_score
        save_history(history)
    
    dates = history[ticker]["dates"]
    scores = history[ticker]["scores"]
    v_return = history[ticker].get("virtual_return", 0.0)
    
    score_change = 0
    if len(scores) > 1:
        score_change = scores[-1] - scores[-2]
        
    curations = []
    cur_price = info.get("currentPrice") or info.get("regularMarketPrice", 0)
    target = info.get("targetMeanPrice", 0)
    high_52 = info.get("fiftyTwoWeekHigh", 0)
    
    if target and cur_price and target > cur_price * 1.1:
        curations.append("📈 증권사 평균 목표가 대비 현재가가 낮아 상승 여력이 포착됩니다.")
    elif target and cur_price and cur_price > target:
        curations.append("⚠️ 현재가가 증권사 평균 목표가를 상회하여 단기 과열 구간일 수 있습니다.")
        
    if cur_price and high_52 and cur_price >= high_52 * 0.95:
        curations.append("🔥 52주 신고가 부근입니다. 강력한 모멘텀 혹은 고점 리스크가 공존합니다.")
        
    actual_div_percent = get_dividend_percent(info)
    if actual_div_percent >= 4.0:
        curations.append(f"💰 연 {round(actual_div_percent, 2)}% 수준의 고배당이 기대되어 하방 경직성이 튼튼합니다.")
        
    if not curations:
        if current_score >= 60:
            curations.append("💡 안정적인 펀더멘탈을 유지하고 있으며, 특별한 악재는 발견되지 않았습니다.")
        else:
            curations.append("💡 뚜렷한 호재나 특이 공시는 포착되지 않고 있어 관망이 필요합니다.")
            
    curation_reason = " ".join(curations)

    display_dates = dates[-6:] if len(dates) >= 6 else dates
    display_scores = scores[-6:] if len(scores) >= 6 else scores
    formatted_dates = [d[5:].replace("-", "/") for d in display_dates]
    
    if len(formatted_dates) == 1:
        formatted_dates = ["어제", "오늘"]
        display_scores = [current_score, current_score]
    
    return score_change, curation_reason, v_return, formatted_dates, display_scores

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ================================================================
# 4. 백그라운드 태스크 엔진 (캘린더, 랭킹, 추천 등)
# ================================================================
def save_ranking_to_file():
    try:
        payload = {"KR": dict(SEARCH_COUNT_KR), "US": dict(SEARCH_COUNT_US)}
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=4)
    except Exception: pass

def save_community_to_file():
    global VOTE_DB, TALK_DB
    try:
        payload = {"VOTE": VOTE_DB, "TALK": TALK_DB}
        with open(COMMUNITY_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=4)
    except Exception: pass

# 🚀 추천 종목 생성기
def fetch_recommendations():
    global RECOMMENDATION_CACHE
    large_caps = ["005930.KS", "000660.KS", "005380.KS", "AAPL", "MSFT", "NVDA", "TSLA", "GOOGL", "005490.KS", "105560.KS"]
    temp_cache = []
    for ticker in large_caps:
        try:
            info = yf.Ticker(ticker).info
            cur = info.get("currentPrice") or info.get("regularMarketPrice") or info.get("previousClose")
            if cur:
                score, color, reasons, brief = calculate_ssabissa_score(info, ticker)
                name = info.get("longName") or info.get("shortName") or ticker
                currency = info.get("currency", "$")
                fmt = "{:,.0f}" if currency in ["KRW", "₩"] else "{:,.2f}"
                score_change, cur_reason, backtest, h_dates, h_scores = update_and_get_history(ticker, score, info)
                
                temp_cache.append({
                    "name": name, "ticker": ticker,
                    "current_price": fmt.format(cur) + f" {currency}",
                    "score": score, "color": color, "brief": brief, "reasons": reasons,
                    "score_change": score_change, "curation_reason": cur_reason, "backtest_return": backtest,
                    "history_dates": h_dates, "history_scores": h_scores
                })
        except Exception:
            continue
    if temp_cache:
        RECOMMENDATION_CACHE = temp_cache

def update_all_stock_scores_task():
    for name, ticker in STOCK_MAP.items():
        try:
            ticker_upper = ticker.strip().upper()
            if ticker_upper in TICKER_CACHE:
                cached_score = TICKER_CACHE[ticker_upper].get("score", 50)
                if cached_score != 50 and cached_score > 0: continue 
                
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
    except Exception as e: pass

def start_scheduler():
    def run_forever():
        fetch_recommendations() # 서버 부팅 시 추천 종목 초기화
        time.sleep(5)
        while True:
            try: 
                update_all_stock_scores_task()
                fetch_recommendations() # 점수 업데이트 시 추천 종목도 갱신
            except Exception as e: pass
            time.sleep(21600)
    threading.Thread(target=run_forever, daemon=True).start()

# 🚀 일일/주간 리셋 자동화 스케줄러 (조회수 & 투표 데이터)
def start_reset_scheduler():
    def run_reset():
        global SEARCH_COUNT_KR, SEARCH_COUNT_US, VOTE_DB
        kst = timezone(timedelta(hours=9))
        last_daily_reset = datetime.now(kst).date()
        last_weekly_reset = datetime.now(kst).date()
        
        while True:
            time.sleep(60) # 1분마다 자정 통과 여부 체크
            now_date = datetime.now(kst).date()
            
            # 1. 랭킹페이지 조회수 매일 자정 리셋
            if now_date > last_daily_reset:
                SEARCH_COUNT_KR.clear()
                SEARCH_COUNT_US.clear()
                last_daily_reset = now_date
                save_ranking_to_file()
                
            # 2. 커뮤니티 응원바 매주 일요일 자정 리셋 (weekday() == 6)
            if now_date.weekday() == 6 and now_date > last_weekly_reset:
                for ticker in list(VOTE_DB.keys()):
                    VOTE_DB[ticker] = {"up": 0, "down": 0}
                last_weekly_reset = now_date
                save_community_to_file()
                
    threading.Thread(target=run_reset, daemon=True).start()

def update_market_calendar():
    sample_tickers = [
        "005930.KS", "000660.KS", "005380.KS", "373220.KS", "035420.KS", 
        "035720.KS", "000270.KS", "068270.KS", "105560.KS", "055550.KS",
        "051910.KS", "006400.KS", "005490.KS", "012330.KS", "028260.KS",
        "AAPL", "MSFT", "NVDA", "TSLA", "GOOGL", "AMZN", "META", "TSM", 
        "AVGO", "LLY", "V", "JPM", "WMT", "MA", "PG", "NFLX", "AMD", 
        "COST", "ADBE", "CRM", "INTC", "CSCO", "PEP", "KO", "DIS"
    ]
    
    dividend_events = []
    earning_events = []
    kst = timezone(timedelta(hours=9))
    today_date = datetime.now(kst).date()
    # 수정: 30일 이전 과거 데이터부터 수집하도록 범위 확장
    past_date_limit = today_date - timedelta(days=30) 

    for t in sample_tickers:
        try:
            stock = yf.Ticker(t)
            info = stock.info
            if not info: continue
            
            name = info.get('shortName') or info.get('longName') or t
            
            ex_date = info.get("exDividendDate")
            if ex_date:
                dt = datetime.fromtimestamp(ex_date, tz=kst).date()
                if dt >= past_date_limit: # 수정된 날짜 제한 적용
                    dividend_events.append({"date": dt.strftime('%y.%m.%d'), "title": f"[{t.replace('.KS','')}] {name}"})
            
            earning_date = info.get("earningsTimestamp") or info.get("earningsTimestampStart")
            if earning_date:
                edt = datetime.fromtimestamp(earning_date, tz=kst).date()
                if edt >= past_date_limit: # 수정된 날짜 제한 적용
                    earning_events.append({"date": edt.strftime('%y.%m.%d'), "title": f"[{t.replace('.KS','')}] {name}"})
        except Exception:
            continue

    dividend_events.sort(key=lambda x: x["date"])
    earning_events.sort(key=lambda x: x["date"])

    data = {"dividend": dividend_events, "earning": earning_events}
    try:
        with open(CALENDAR_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
    except Exception as e:
        print(f"⚠️ 캘린더 업데이트 실패: {e}")

def start_calendar_automation():
    def run():
        update_market_calendar()
        while True:
            time.sleep(86400)
            try: update_market_calendar()
            except Exception as e: print(f"Calendar Update Error: {e}")
            
    threading.Thread(target=run, daemon=True).start()

# 스케줄러 일괄 실행
start_calendar_automation()
start_scheduler()
start_reset_scheduler()

# ================================================================
# 5. 유틸리티 엔진 
# ================================================================
def get_score_color(score):
    if score <= 50: hue = int((score / 50) * 35)
    else: hue = int(35 + ((score - 50) / 50) * 85)
    return f"hsl({hue}, 85%, 45%)"

def resolve_ticker_by_name(query: str) -> str:
    query = query.strip()
    if not query: return ""
    if query in STOCK_MAP: return STOCK_MAP[query]
    if query.upper().endswith((".KS", ".KQ")): return query.upper()
    if query.isdigit() and len(query) == 6: return query + ".KS"

    try:
        url = f"https://query2.finance.yahoo.com/v1/finance/search?q={query}&lang=ko-KR&region=KR&quotesCount=5"
        res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=5).json()
        for q in res.get("quotes", []):
            if q.get("quoteType") in ("EQUITY", "ETF"):
                return q.get("symbol", "").upper()
    except Exception: pass
    return query.upper()

def calculate_ssabissa_score(info, ticker):
    score = 50
    reasons = []
    is_kr = ".KS" in ticker or ".KQ" in ticker
    
    target = info.get("targetMeanPrice")
    cur = info.get("currentPrice") or info.get("regularMarketPrice")
    if target and cur and target > cur:
        gap = (target - cur) / target * 100
        if gap > 20: score += 8; reasons.append("+ 괴리율 안전마진")
    
    per = info.get("forwardPE")
    if per:
        if is_kr and per < 10: score += 7; reasons.append("+ 국장 극저평가 메리트")
        elif not is_kr and per < 20: score += 7; reasons.append("+ 미장 합리적 밸류에이션")

    pbr = info.get("priceToBook")
    if pbr and pbr < 0.8: score += 5; reasons.append("+ PBR 0.8배 미만 저평가")

    actual_div = get_dividend_percent(info)
    if actual_div >= 4.0: 
        score += 5
        reasons.append(f"+ 고배당 수익률")
    
    if (info.get("earningsGrowth", 0) or 0) * 100 >= 30: score += 8; reasons.append("+ 고성장 기업 프리미엄")

    if (info.get("debtToEquity", 0) or 0) > 150: score -= 10; reasons.append("- 부채비율 과다")
    if (info.get("operatingMargins", 0) or 0) < 0: score -= 12; reasons.append("- 영업이익 적자")
    if target and cur and cur > target: score -= 8; reasons.append("- 목표가 상회 과열")
    if info.get("sharesOutstanding", 0) > 1000000000: score -= 5; reasons.append("- 물량 부담")
    
    try:
        hist = yf.Ticker(ticker).history(period="6mo")
        if len(hist) >= 2 and (hist['Close'].iloc[-1] < hist['Close'].iloc[0] * 0.85):
            score -= 7; reasons.append("- 가치함정 주의")
        elif len(hist) >= 2 and (hist['Close'].iloc[-1] > hist['Close'].iloc[0] * 1.2):
            score += 5; reasons.append("+ 시장 선호 수급")
    except: pass

    score = max(0, min(100, int(score))) 
    color = get_score_color(score)
    
    if score >= 75: brief = "탁월한 안전마진이 확보된 매력적인 구간입니다."
    elif score >= 45: brief = "기초 체력과 성장성이 정상 반영되고 있습니다."
    else: brief = "재무 리스크나 고평가 우려로 신중한 접근이 필요합니다."

    return score, color, reasons, brief

# ================================================================
# 6. 라우터 설정 구역
# ================================================================
@app.get("/", response_class=HTMLResponse)
@app.post("/", response_class=HTMLResponse)
async def home(request: Request):
    search_target = None
    if request.method == "POST":
        try:
            form_data = await request.form()
            search_target = form_data.get("ticker") or form_data.get("q")
        except Exception: pass
            
    if not search_target:
        search_target = request.query_params.get("ticker") or request.query_params.get("q")

    result = None
    recommendation = None
    
    if search_target:
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
            
            score_change, cur_reason, backtest, h_dates, h_scores = update_and_get_history(resolved_ticker, score, info)
            
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
    else:
        if RECOMMENDATION_CACHE:
            recommendation = random.choice(RECOMMENDATION_CACHE)
            
    return templates.TemplateResponse(request=request, name="index.html", context={"request": request, "result": result, "ticker": search_target, "recommendation": recommendation})

@app.get("/api/diagnose/{ticker}")
def api_diagnose(ticker: str = None): 
    if not ticker or ticker == "undefined": return {"error": "티커 코드가 전달되지 않았습니다."}
    try:
        ticker_upper = resolve_ticker_by_name(ticker)
        stock_obj = yf.Ticker(ticker_upper)
        hist = stock_obj.history(period="1d")

        if hist.empty: return {"error": f"{ticker_upper} 종목명 또는 티커를 다시 확인해주세요."}
        info = stock_obj.info
        if not info or "symbol" not in info:
            try: info = stock_obj.fast_info
            except: pass
        if not info: return {"error": f"[{ticker_upper}] 종목명 또는 티커를 다시 확인해주세요."}
            
        cur = info.get("currentPrice") or info.get("regularMarketPrice") or info.get("previousClose")
        if not cur: return {"error": f"[{ticker_upper}] 현재 거래가 데이터를 받아오지 못했습니다."}
        
        score, color, reasons, brief = calculate_ssabissa_score(info, ticker_upper)
        name = info.get("longName") or info.get("shortName") or ticker_upper
        currency = info.get("currency", "$")
        fmt = "{:,.0f}" if currency in ["KRW", "₩"] else "{:,.2f}"
        
        TICKER_CACHE[ticker_upper] = {"name": name, "score": score, "color": color}
        if ".KS" in ticker_upper or ".KQ" in ticker_upper: SEARCH_COUNT_KR[ticker_upper] += 1
        else: SEARCH_COUNT_US[ticker_upper] += 1
        save_ranking_to_file()
        
        score_change, cur_reason, backtest, h_dates, h_scores = update_and_get_history(ticker_upper, score, info)
        
        return {
            "success": True, "name": name, "ticker": ticker_upper,
            "current_price": fmt.format(cur) + f" {currency}",
            "score": score, "color": color, "brief": brief, "reasons": reasons,
            "score_change": score_change, "curation_reason": cur_reason, 
            "backtest_return": backtest, "history_dates": h_dates, "history_scores": h_scores
        }
    except Exception as e: return {"error": f"🚨 싸비싸 엔진 내부 오류 발생: {str(e)}"}

@app.get("/ranking", response_class=HTMLResponse)
def ranking(request: Request):
    try:
        kr_ranks, us_ranks = [], []
        for i, (t, count) in enumerate(SEARCH_COUNT_KR.most_common(50)):
            cache = TICKER_CACHE.get(t, {}) if isinstance(TICKER_CACHE, dict) else {}
            kr_ranks.append({"rank": i + 1, "ticker": str(t), "name": cache.get("name", str(t)), "score": cache.get("score", 50), "color": cache.get("color", "#64748b"), "views": int(count)})
        for i, (t, count) in enumerate(SEARCH_COUNT_US.most_common(50)):
            cache = TICKER_CACHE.get(t, {}) if isinstance(TICKER_CACHE, dict) else {}
            us_ranks.append({"rank": i + 1, "ticker": str(t), "name": cache.get("name", str(t)), "score": cache.get("score", 50), "color": cache.get("color", "#64748b"), "views": int(count)})
        return templates.TemplateResponse(request=request, name="ranking.html", context={"request": request, "kr_rankings": kr_ranks, "us_rankings": us_ranks})
    except Exception as main_err:
        return HTMLResponse(content=f"<h2>🚨 랭킹 조립 예외 발생: {str(main_err)}</h2>", status_code=200)

@app.get("/calendar", response_class=HTMLResponse)
async def calendar_page(request: Request):
    template_file = "calender.html" if os.path.exists("templates/calender.html") else "calendar.html"
    
    # [수정됨] 캘린더 실제 데이터를 수집하여 템플릿(jinja)로 넘겨줍니다.
    events = {}
    if os.path.exists(CALENDAR_FILE):
        try:
            with open(CALENDAR_FILE, "r", encoding="utf-8") as f:
                cal_data = json.load(f)
                
                # 배당락일 가공
                for item in cal_data.get("dividend", []):
                    date_str = item["date"]
                    if date_str not in events: events[date_str] = []
                    
                    # 괄호 사이의 티커 기호 추출 (ex. "[AAPL] 애플" -> "AAPL")
                    ticker = item["title"].split("]")[0].replace("[", "").strip() if "[" in item["title"] else ""
                    
                    events[date_str].append({
                        "time": "종일",
                        "title": item["title"],
                        "description": "배당락일 (해당일 전까지 매수 필요)",
                        "type": "dividend",
                        "type_name": "배당락일",
                        "ticker": ticker
                    })
                    
                # 실적발표 가공
                for item in cal_data.get("earning", []):
                    date_str = item["date"]
                    if date_str not in events: events[date_str] = []
                    
                    ticker = item["title"].split("]")[0].replace("[", "").strip() if "[" in item["title"] else ""
                    
                    events[date_str].append({
                        "time": "발표일",
                        "title": item["title"],
                        "description": "기업 실적 발표 (예정)",
                        "type": "earnings",
                        "type_name": "실적발표",
                        "ticker": ticker
                    })
                    
            # 날짜순(오름차순) 정렬
            events = dict(sorted(events.items()))
        except Exception as e:
            print(f"Calendar Fetch Error: {e}")
            
    return templates.TemplateResponse(request=request, name=template_file, context={"request": request, "events": events})

@app.get("/api/calendar/data")
def get_calendar_data():
    if not os.path.exists(CALENDAR_FILE): return {"dividend": [], "earning": []}
    try:
        with open(CALENDAR_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except: return {"dividend": [], "earning": []}

@app.get("/api/autocomplete")
def api_autocomplete(q: str = ""):
    q = q.strip()
    if len(q) < 2: return []
    try:
        res = requests.get(f"https://query2.finance.yahoo.com/v1/finance/search?q={q}&lang=ko-KR&region=KR", headers={'User-Agent': 'Mozilla/5.0'}, timeout=2).json()
        return [{"ticker": i["symbol"].upper()+".KS" if i["symbol"].isdigit() and len(i["symbol"])==6 else i["symbol"].upper(), "name": i.get("longname") or i.get("shortname") or i["symbol"]} for i in res.get("quotes", []) if i.get("quoteType") in ["EQUITY", "ETF"]][:5]
    except: return []

@app.get("/favorites", response_class=HTMLResponse)
def favorites_page(request: Request):
    return templates.TemplateResponse(request=request, name="favorites.html", context={"request": request})

class TickerList(BaseModel):
    tickers: List[str]

@app.post("/api/favorites/details")
def get_favorites_details(req: TickerList):
    results = []
    for t in req.tickers:
        ticker_upper = resolve_ticker_by_name(t)
        
        cache = TICKER_CACHE.get(ticker_upper)
        if cache and cache.get("score") != 50:
            results.append({
                "ticker": ticker_upper,
                "name": cache.get("name", ticker_upper),
                "score": cache.get("score", 50),
                "color": cache.get("color", "#64748b")
            })
            continue
            
        try:
            info = yf.Ticker(ticker_upper).info
            score, color, _, _ = calculate_ssabissa_score(info, ticker_upper)
            name = info.get("longName") or info.get("shortName") or ticker_upper
            results.append({
                "ticker": ticker_upper,
                "name": name,
                "score": score,
                "color": color
            })
            TICKER_CACHE[ticker_upper] = {"name": name, "score": score, "color": color}
        except Exception:
            pass
            
    return {"data": results}

@app.get("/strategy", response_class=HTMLResponse)
def strategy_page(request: Request): return templates.TemplateResponse(request=request, name="strategy.html", context={"request": request})

@app.get("/about", response_class=HTMLResponse)
def about_page(request: Request): return templates.TemplateResponse(request=request, name="about.html", context={"request": request})

@app.get("/privacy", response_class=HTMLResponse)
def privacy_page(request: Request): return templates.TemplateResponse(request=request, name="privacy.html", context={"request": request})

@app.get("/faq", response_class=HTMLResponse)
def faq_page(request: Request): return templates.TemplateResponse(request=request, name="faq.html", context={"request": request})

@app.get("/sitemap.xml")
def get_sitemap():
    xml_content = """<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n<url><loc>https://www.ssabissa.com/</loc><priority>1.0</priority></url>\n<url><loc>https://www.ssabissa.com/ranking</loc><priority>0.8</priority></url>\n<url><loc>https://www.ssabissa.com/strategy</loc><priority>0.8</priority></url>\n<url><loc>https://www.ssabissa.com/faq</loc><priority>0.7</priority></url>\n<url><loc>https://www.ssabissa.com/about</loc><priority>0.5</priority></url>\n</urlset>"""
    return Response(content=xml_content, media_type="application/xml")

@app.get("/robots.txt", response_class=PlainTextResponse)
def get_robots_txt(): return "User-agent: *\nAllow: /\nSitemap: https://www.ssabissa.com/sitemap.xml"

# ================================================================
# 7. 커뮤니티 데이터 API 엔진
# ================================================================
@app.get("/api/community/{ticker}")
def get_community_data(ticker: str):
    t = ticker.strip().upper()
    return {"votes": VOTE_DB.get(t, {"up": 0, "down": 0}), "talks": TALK_DB.get(t, [])}

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
    BAD_WORDS = ["리딩방", "카톡방", "추천주", "수익보장", "시발", "개새끼", "조까", "급등주", "대박정보", "무료리딩", "오픈채팅"]
    
    if any(word in clean_text.replace(" ", "") for word in BAD_WORDS):
        return {"error": "🚨 광고성 문구나 부적절한 표현은 등록할 수 없습니다."}
    if not clean_text: return {"error": "내용을 입력해 주세요."}
        
    kst = timezone(timedelta(hours=9))
    now_dt = datetime.now(kst)
    
    new_talk = {
        "nickname": f"{random.choice(['용감한', '행복한', '스마트한', '존버하는'])} {random.choice(['개미', '고래', '호랑이', '판다'])} {random.randint(0, 100)}",
        "text": clean_text,
        "time": now_dt.isoformat(),
        "date": now_dt.strftime("%Y-%m-%d")
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
            try:
                if (now_dt - datetime.strptime(talk["date"], "%Y-%m-%d").replace(tzinfo=kst)).days < 30: 
                    valid_talks.append(talk)
                else: removed_count += 1
            except: valid_talks.append(talk)
        TALK_DB[ticker] = valid_talks
        
    if removed_count > 0: save_community_to_file()

@app.delete("/api/admin/clear/talk")
def admin_clear_talk(ticker: str, password: str, index: int = 0):
    if password != "jusongsecret123": raise HTTPException(status_code=403, detail="권한이 없습니다.")
    t = ticker.strip().upper()
    if t in TALK_DB and len(TALK_DB[t]) > index:
        TALK_DB[t].pop(index)
        save_community_to_file()
        return {"success": True}
    return {"error": "삭제할 대상 댓글이 존재하지 않습니다."}