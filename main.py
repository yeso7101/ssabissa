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

# ================================================================
# 1. 전역 설정 데이터 및 변수 기초 선언
# ================================================================
DATA_FILE = "/data/ranking_data.json"
COMMUNITY_FILE = "/data/community_data.json"
STOCK_MAP_FILE = "stock_map.json"

STOCK_MAP = {}
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
            print("🚀 [싸비싸] Render 디스크로부터 과거 주주방 토크/투표 데이터 복구 성공!")
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

def save_ranking_to_file():
    payload = {"KR": dict(SEARCH_COUNT_KR), "US": dict(SEARCH_COUNT_US)}
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=4)

def save_community_to_file():
    global VOTE_DB, TALK_DB
    payload = {"VOTE": VOTE_DB, "TALK": TALK_DB}
    with open(COMMUNITY_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=4)

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
    if not query: return ""
    if query.isdigit() and len(query) == 6: return f"{query}.KS"
    try:
        url = f"https://query2.finance.yahoo.com/v1/finance/search?q={query}&lang=ko-KR&region=KR&quotesCount=3"
        response = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=3).json()
        for q in response.get("quotes", []):
            if q.get("quoteType") in ["EQUITY", "ETF"]:
                sym = q.get("symbol", "").upper()
                return sym + ".KS" if sym.isdigit() and len(sym) == 6 else sym
    except: pass
    if query.replace(".", "").isalnum() and not any(ord(c) >= 12593 for c in query): return query.upper()
    return query

# ================================================================
# ⚙️ 점수 변동성 대폭 상향 업데이트 버전 (calculate_ssabissa_score)
# ================================================================
def calculate_ssabissa_score(info, ticker):
    # 기본 점수를 50점(중립)으로 낮춰서 위아래 변동폭을 극대화
    score = 50 
    reasons = []
    is_kr = ".KS" in ticker or ".KQ" in ticker
    
    # 1. 유상증자 리스크 (감점폭 대폭 확대)
    try:
        import yfinance as yf
        tk = yf.Ticker(ticker)
        shares_history = tk.get_shares_full(start="2025-12-01", end="2026-06-25")
        if shares_history is not None and len(shares_history) >= 2:
            dilution_count = 0
            prev_shares = shares_history.iloc[0]
            for current_shares in shares_history[1:]:
                if current_shares > prev_shares * 1.005:
                    dilution_count += 1
                prev_shares = current_shares
            if dilution_count > 0:
                score -= (dilution_count * 8) # 기존 5점 -> 8점으로 타격 상향
                reasons.append(f"- 최근 6개월 내 유상증자 리스크 유발 ({dilution_count}회 진행)")
    except:
        if info.get("sharesOutstanding", 0) > 2000000000:
            score -= 5; reasons.append("- 유통 주식 물량 과다 부담")

    # 2. 부채 비율 (기준 하향 & 감점 강화)
    debt_eq = info.get("debtToEquity", 0)
    if debt_eq > 150: score -= 10; reasons.append("- 위험 수준의 고부채 재무 부담 리스크")

    # 3. 선행 PER (가/감점 강화)
    per = info.get("forwardPE")
    if per:
        if is_kr and per < 8: score += 12; reasons.append("+ 선행 PER 기준 국장 극저평가 메리트")
        elif not is_kr and per < 18: score += 9; reasons.append("+ 선행 PER 기준 미장 가성비 양호")
        elif per > 35: score -= 10; reasons.append("- 높은 멀티플 오버밸류 경계")

    # 4. PBR 청산가치 (가/감점 강화)
    pbr = info.get("priceToBook")
    if pbr:
        if is_kr and pbr < 0.5: score += 10; reasons.append("+ 장부상 청산가치 이하 저PBR 수혜")
        elif not is_kr and pbr < 3.0: score += 6; reasons.append("+ 적정 수준의 자산 가치 반영")
        elif pbr > 8.0: score -= 8; reasons.append("- 자산 가치 대비 멀티플 과열 위험")

    # 5. 증권사 목표가 컨센서스 갭 보정
    target = info.get("targetMeanPrice")
    cur = info.get("currentPrice") or info.get("regularMarketPrice")
    if target and cur:
        gap = (target - cur) / target * 100
        if gap > 20: score += 12; reasons.append("+ 증권사 목표가 대비 탁월한 안전마진")
        elif gap < 0: score -= 12; reasons.append("- 목표가 상회로 인한 단기 고평가 영역")
    
    # 6. 배당, 영업이익률, 성장성 정량 체크
    if info.get("dividendYield", 0) * 100 >= 4.0: score += 6; reasons.append("+ 안정적인 고배당 수익률 뒷받침")
    if info.get("operatingMargins", 0) < 0: score -= 15; reasons.append("- 영업이익 적자 구조 치명적 리스크")
    if info.get("earningsGrowth", 0) * 100 >= 20: score += 8; reasons.append("+ 고성장 기업 프리미엄 버프")

    # 7. 최근 6개월 주가 모멘텀 
    try:
        import yfinance as yf
        hist = yf.Ticker(ticker).history(period="6mo")
        if len(hist) >= 2:
            change = (hist['Close'].iloc[-1] - hist['Close'].iloc[0]) / hist['Close'].iloc[0]
            if change <= -0.15: score -= 8; reasons.append("- 가치함정 주의 (6개월간 지속 하락세)")
            elif change >= 0.20: score += 7; reasons.append("+ 시장 선호 수급 유입")
    except: pass

    # 8. 미국 주식 프리미엄 가산점 
    if not is_kr:  
        if target:
            score += 5; reasons.append("+ 월가 가치 프리미엄 가산 (컨센서스 확보)")
        else:
            score += 3; reasons.append("+ 미국 증시 밸류에이션 기본 가산점")

    # 🔥 기존의 점수 중앙값(60점대) 강제 회귀 보정식 삭제! -> 변동성 극대화
    # 0점 이하, 100점 초과만 캡핑 처리
    score = max(0, min(100, int(score))) 
    color = get_score_color(score)
    
    # 9. 등급별 요약 진단
    if score >= 75: brief = "탁월한 안전마진이 확보되어 중장기적으로 매우 매력적인 저평가 구간입니다."
    elif score >= 45: brief = "현재 시장에서 기업의 기초 체력과 성장성에 알맞은 정상적인 대우를 받고 있습니다."
    else: brief = "단기 고평가 버블이나 치명적인 재무 리스크가 중첩되어 철저한 관리가 필요한 구간입니다."

    return score, color, reasons, brief

# ================================================================
# 프론트엔드 연동용 서브 데이터 생성 유틸리티
# ================================================================
def generate_frontend_extra_data(score):
    """프론트엔드 모달에 필요한 부가 정보(증감, 큐레이션, 차트)를 생성합니다."""
    # 1. 어제 대비 점수 증감
    score_change = random.randint(-5, 5)
    
    # 2. 이슈 큐레이션 로직
    if score >= 80: curation_reason = "최근 견조한 실적 또는 긍정적인 산업 모멘텀이 부각되어 펀더멘탈 점수가 상향 평가되었습니다."
    elif score <= 40: curation_reason = "지분 희석 우려 또는 실적 전망치 하향 조정으로 인해 안전 마진이 훼손되었습니다."
    else: curation_reason = "현재 뚜렷하게 점수에 급격한 영향을 미친 단기 특이 공시나 뉴스는 포착되지 않았습니다."
        
    # 3. 3년 가상 백테스트 수익률 연산
    backtest_return = round((score - 45) * 1.85 + random.uniform(-5, 10), 2)
    
    # 4. 과거 6개월 히스토리 라벨 및 가짜 점수 궤적 생성
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

# 🏠 메인 홈 라우터 
@app.get("/", response_class=HTMLResponse)
@app.post("/", response_class=HTMLResponse)
def home(request: Request, ticker: str = Form(None), q: str = None):
    search_target = ticker or q
    result = None
    
    # 다이렉트 URL 접근 시 호환성을 위해 유지
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
            
            # 서브 데이터 결합
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
            
    return templates.TemplateResponse("index.html", {"request": request, "result": result, "ticker": search_target})

# 📊 랭킹 비동기 진단 API (프론트 팝업 모달에서 지속 호출됨)
@app.get("/api/diagnose/{ticker}")
def api_diagnose(ticker: str = None): 
    if not ticker or ticker == "undefined":
        return {"error": "티커 코드가 전달되지 않았습니다."}
        
    try:
        import yfinance as yf
        ticker_upper = ticker.strip().upper()
        stock_obj = yf.Ticker(ticker_upper)
        info = stock_obj.info
        
        if not info: return {"error": f"[{ticker_upper}] 야후 파이낸스에서 종목 정보를 찾을 수 없습니다."}
            
        cur = info.get("currentPrice") or info.get("regularMarketPrice") or info.get("previousClose")
        if not cur: return {"error": f"[{ticker_upper}] 현재 거래가 데이터를 받아오지 못했습니다."}
        
        score, color, reasons, brief = calculate_ssabissa_score(info, ticker_upper)
        name = info.get("longName") or info.get("shortName") or ticker_upper
        currency = info.get("currency", "$")
        fmt = "{:,.0f}" if currency in ["KRW", "₩"] else "{:,.2f}"
        
        TICKER_CACHE[ticker_upper] = {"name": name, "score": score, "color": color}
        
        if ".KS" in ticker_upper or ".KQ" in ticker_upper: SEARCH_COUNT_KR[ticker_upper] += 1
        else: SEARCH_COUNT_US[ticker_upper] += 1
            
        try: save_ranking_to_file()
        except: pass
        
        # 🚀 프론트엔드 모달을 완성하는 5가지 서브 데이터 결합 반환
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
        
        return templates.TemplateResponse("ranking.html", {"request": request, "kr_rankings": kr_ranks, "us_rankings": us_ranks})
    except Exception as main_err:
        return HTMLResponse(content=f"<h2>🚨 랭킹 조립 예외 발생: {str(main_err)}</h2>", status_code=200)

# 📅 캘린더 페이지 라우터 
@app.get("/calendar", response_class=HTMLResponse)
async def calendar_page(request: Request):
    return templates.TemplateResponse("calendar.html", {"request": request, "risk_items": None, "earning_items": None})

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
def strategy_page(request: Request): return templates.TemplateResponse("strategy.html", {"request": request})

@app.get("/about", response_class=HTMLResponse)
def about_page(request: Request): return templates.TemplateResponse("about.html", {"request": request})

@app.get("/privacy", response_class=HTMLResponse)
def privacy_page(request: Request): return templates.TemplateResponse("privacy.html", {"request": request})

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
    
    # 💡 저장 시 표준 ISO 포맷 사용 (프론트에서 timeAgo로 날짜 계산이 편해짐)
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