from fastapi import FastAPI, Request, Form, Response, HTTPException
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from collections import Counter
import requests
import json
import os

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
# 종목별 투표 데이터 저장 구조: {"AAPL": {"up": 15, "down": 4}}
VOTE_DB = {}

# 종목별 한 줄 주주방 댓글 저장 구조: {"AAPL": [{"nickname": "익명", "text": "화이팅", "time": "22:45"}]}
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
# 3. 데이터 복구 및 기본 랭킹 데이터 스택 장전 (정품 인프라 버전)
# ================================================================
# 💡 하드코딩 더미 데이터를 완전히 제거하고 파일 데이터 기반으로만 빌드합니다.
if os.path.exists(DATA_FILE):
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        try:
            past_data = json.load(f)
            # 파일에 저장되어 있던 진짜 유저들의 조회수 기록 복구
            for k, v in past_data.get("KR", {}).items(): 
                SEARCH_COUNT_KR[k] = v
            for k, v in past_data.get("US", {}).items(): 
                SEARCH_COUNT_US[k] = v
        except Exception:
            pass

# 💡 진단 및 가이드 컴포넌트 연동용 글로벌 기준 사전 (구조 칼정렬)
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

# ================================================================
# 4. 안전 공통 유틸 함수 및 객체 인스턴스 생성
# ================================================================
app = FastAPI()

def save_ranking_to_file():
    payload = {
        "KR": dict(SEARCH_COUNT_KR),
        "US": dict(SEARCH_COUNT_US)
    }
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=4)

# 💬 [신설] 투표 및 주주방 단톡방 데이터를 파일로 저장하는 백업 함수
def save_community_to_file():
    global VOTE_DB, TALK_DB
    payload = {
        "VOTE": VOTE_DB,
        "TALK": TALK_DB
    }
    with open(COMMUNITY_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=4)

# 🔄 [신설] 서버가 새로 켜질 때 외장하드(/data/)에 보존되어 있던 커뮤니티 데이터 자동 부활 로직
if os.path.exists(COMMUNITY_FILE):
    with open(COMMUNITY_FILE, "r", encoding="utf-8") as f:
        try:
            past_comm = json.load(f)
            VOTE_DB = past_comm.get("VOTE", {})
            TALK_DB = past_comm.get("TALK", {})
            print("🚀 [싸비싸] Render 디스크로부터 과거 주주방 토크/투표 데이터 복구 성공!")
        except Exception as e:
            print(f"⚠️ 커뮤니티 복구 중 예외 발생(무시하고 초기화): {e}")

# (이어서 기존의 import threading, import time 및 6시간 스케줄러 로직이 위치하게 됩니다)
import threading
import time
# ================================================================
# 4. [신설] 6시간 주기 자동 가치점수 동기화 백그라운드 엔진
# ================================================================
app = FastAPI()

def update_all_stock_scores_task():
    """1,200대장 종목의 실제 싸비싸 스코어를 백그라운드에서 주기적으로 수집하는 엔진 (차단 방어막 탑재)"""
    print("🔄 [싸비싸 스케줄러] 6시간 주기 1,200대장 진짜 점수 동기화 엔진 가동...")
    import yfinance as yf
    import random  # ⏰ 인간형 랜덤 휴식을 위해 난수 라이브러리 추가
    import time
    
    # 1. 1,200대장 종목 순회 연산
    for name, ticker in STOCK_MAP.items():
        try:
            ticker_upper = ticker.strip().upper()
            
            # 🛡️ [철벽 방어선 업그레이드] 
            # 이미 캐시에 점수가 제대로 들어가 있다면(기본값 50점이 아닌 경우), 
            # 야후 서버를 절대 다시 찌르지 않고 패스하여 Rate Limit을 완벽하게 봉쇄합니다.
            if ticker_upper in TICKER_CACHE:
                cached_score = TICKER_CACHE[ticker_upper].get("score", 50)
                if cached_score != 50 and cached_score > 0:
                    continue  # 👈 이미 진짜 점수가 장전된 종목은 야후 패스!
                
            stock_obj = yf.Ticker(ticker_upper)
            info = stock_obj.info
            if not info: continue
                
            cur = info.get("currentPrice") or info.get("regularMarketPrice") or info.get("previousClose")
            if not cur: continue
                
            # 진짜 싸비싸 연산 엔진 통과
            score, color, reasons, brief = calculate_ssabissa_score(info, ticker_upper)
            
            # 캐시 사전 최신화
            TICKER_CACHE[ticker_upper] = {
                "name": name,
                "score": score,
                "color": color
            }
            
            # 초기 조회수 기본 방어벽
            if ".KS" in ticker_upper or ".KQ" in ticker_upper:
                if SEARCH_COUNT_KR[ticker_upper] == 0: SEARCH_COUNT_KR[ticker_upper] = 1
            else:
                if "000000" not in ticker_upper:
                    if SEARCH_COUNT_US[ticker_upper] == 0: SEARCH_COUNT_US[ticker_upper] = 1
            
            # ⏰ [인간형 디레이팅 적용] 
            # 고정 0.2초 대신 0.8초~1.2초 사이의 무작위 휴식을 주어 야후 디펜스 시스템을 속입니다.
            time.sleep(random.uniform(0.8, 1.2))
            
        except Exception as e:
            # 특정 종목 오류 나도 멈추지 않고 다음 종목으로 패스
            continue
            
    # 2. 1,200대장 순회가 완벽히 끝난 후 디스크 백업 및 한 달 경과 댓글 청소기 가동
    try:
        save_ranking_to_file()  # 랭킹 점수 디스크 백업
        clear_expired_talks()   # 30일 지난 묵은 댓글 정화 
        print("✅ [싸비싸 스케줄러] 1,200대장 동기화 및 한 달 유통기한 댓글 자동 파기 프로세스 완전 성공!")
    except Exception as sched_err:
        print(f"⚠️ 스케줄러 후처리 백업 중 오류 발생: {sched_err}")

def start_scheduler():
    """서버가 켜진 후 5초 뒤에 최초 1회 전체 동기화를 돌리고, 이후 6시간마다 무한 반복합니다."""
    def run_forever():
        # 서버 초기 구동 안정화를 위해 5초 대기
        time.sleep(5)
        while True:
            try:
                update_all_stock_scores_task()
            except Exception as e:
                print(f"⚠️ 스케줄러 루프 에러: {e}")
            
            # 6시간 대기 (6시간 = 6 * 60 * 60 초 = 21600초)
            # 테스트해 보고 싶으시다면 이 숫자를 60(1분)이나 300(5분)으로 바꿔서 확인해 보세요!
            time.sleep(21600)

    # 서버 메인 스레드가 멈추지 않도록 백그라운드 스레드로 격리하여 가동
    threading.Thread(target=run_forever, daemon=True).start()

# 🚀 서버 기동과 동시에 백그라운드 타이머 시동!
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

def calculate_ssabissa_score(info, ticker):
    score = 65
    reasons = []
    is_kr = ".KS" in ticker or ".KQ" in ticker
    
    # 1. 최근 6개월 내 발행주식수 변동(유상증자) 리스크 연산 구역
    try:
        import yfinance as yf
        tk = yf.Ticker(ticker)
        shares_history = tk.get_shares_full(start="2025-12-01", end="2026-06-25")
        if shares_history is not None and len(shares_history) >= 2:
            dilation_count = 0
            prev_shares = shares_history.iloc[0]
            for current_shares in shares_history[1:]:
                if current_shares > prev_shares * 1.005:
                    dilution_count += 1
                prev_shares = current_shares
            if dilution_count > 0:
                score -= (dilution_count * 5)
                reasons.append(f"- 최근 6개월 내 유상증자 리스크 유발 ({dilution_count}회 진행)")
    except:
        if info.get("sharesOutstanding", 0) > 2000000000:
            score -= 5; reasons.append("- 유통 주식 물량 과다 부담")

    # 2. 부채 비율 리스크 검증
    debt_eq = info.get("debtToEquity", 0)
    if debt_eq > 180: score -= 7; reasons.append("- 위험 수준의 고부채 재무 부담 리스크")

    # 3. 선행 PER 밸류에이션 지표 비교
    per = info.get("forwardPE")
    if per:
        if is_kr and per < 8: score += 7; reasons.append("+ 선행 PER 기준 국장 저평가 메리트")
        elif not is_kr and per < 18: score += 7; reasons.append("+ 선행 PER 기준 미장 가성비 양호")
        elif per > 35: score -= 6; reasons.append("- 높은 멀티플 오버밸류 경계")

    # 4. PBR 청산가치 지표 비교
    pbr = info.get("priceToBook")
    if pbr:
        if is_kr and pbr < 0.5: score += 6; reasons.append("+ 장부상 청산가치 이하 저PBR 수혜")
        elif not is_kr and pbr < 3.0: score += 4; reasons.append("+ 적정 수준의 자산 가치 반영")
        elif pbr > 10.0: score -= 5; reasons.append("- 자산 가치 대비 멀티플 과열 위험")

    # 5. 증권사 목표가 컨센서스 갭 보정
    target = info.get("targetMeanPrice")
    cur = info.get("currentPrice") or info.get("regularMarketPrice")
    if target and cur:
        gap = (target - cur) / target * 100
        if gap > 25: score += 8; reasons.append("+ 증권사 목표가 대비 안전마진")
        elif gap < 0: score -= 10; reasons.append("- 목표가 상회로 인한 단기 고평가 영역")
    
    # 6. 배당률, 영업이익률, 성장성 정량 체크
    if info.get("dividendYield", 0) * 100 >= 4.0: score += 4; reasons.append("+ 안정적인 배당 수익률 뒷받침")
    if info.get("operatingMargins", 0) < 0: score -= 12; reasons.append("- 영업이익 적자 구조 리스크")
    if info.get("earningsGrowth", 0) * 100 >= 25: score += 5; reasons.append("+ 고성장 기업 프리미엄 버프")

    # 7. 최근 6개월 주가 모멘텀 트랙 추적
    try:
        import yfinance as yf
        hist = yf.Ticker(ticker).history(period="6mo")
        if len(hist) >= 2:
            change = (hist['Close'].iloc[-1] - hist['Close'].iloc[0]) / hist['Close'].iloc[0]
            if change <= -0.08: score -= 6; reasons.append("- 가치함정 주의 (6개월간 소외 우하향)")
            elif change >= 0.20: score += 4; reasons.append("+ 시장 선호 수급 유입")
    except: pass

    # ================================================================
    # 📈 [조립 지점] 미국 주식 프리미엄 가산점 시스템 (컨센서스 연동)
    # ================================================================
    if not is_kr:  # 미국 주식(미장)일 때만 발동
        if target:
            # S&P500급 우량주 등 월가 기관들의 목표 주가(컨센서스) 데이터가 풍부한 주식
            score += 5
            reasons.append("+ 월가 가치 프리미엄 가산 (컨센서스 확보)")
        else:
            # 컨센서스가 잡히지 않는 중소형주나 성장 초입 주식
            score += 3
            reasons.append("+ 미국 증시 밸류에이션 기본 가산점")

    # 8. 평균값 조정 및 최종 100점 마지노선 캡핑
    deviation = score - 60
    score = 60 + int(deviation * 0.85)
    score = max(0, min(100, int(score))) # 100점 초과 완전 방어
    color = get_score_color(score)
    
    # 9. 등급별 한 줄 요약 진단 셔터
    if score >= 68: brief = "보수적인 기준에서도 안전마진이 비교적 안정적으로 확보된 진입 매력 구간입니다."
    elif score >= 48: brief = "현재 시장에서 기업의 기초 체력과 성장성에 알맞은 정상적인 대우를 받고 있습니다."
    else: brief = "단기 주가 거품이나 재무적 페널티가 중첩되어 있어 리스크 관리가 필요한 구간입니다."

    return score, color, reasons, brief

# ================================================================
# 5. 비즈니스 로직 라우터 (주소 분할 완벽화)
# ================================================================

# 🏠 메인 홈 라우터 (GET, POST만 완벽하게 바인딩)
@app.get("/", response_class=HTMLResponse)
@app.post("/", response_class=HTMLResponse)
def home(request: Request, ticker: str = Form(None), q: str = None):
    import yfinance as yf
    search_target = ticker or q
    result = None
    
    if search_target:
        clean_target = search_target.strip().lower().replace(" ", "")
        if clean_target in STOCK_MAP:
            resolved_ticker = STOCK_MAP[clean_target]
        else:
            resolved_ticker = resolve_ticker_by_name(search_target)
            
        try:
            info = yf.Ticker(resolved_ticker).info
            cur = info.get("currentPrice") or info.get("regularMarketPrice") or info.get("previousClose")
            if not cur: raise Exception()
            
            score, color, reasons, brief = calculate_ssabissa_score(info, resolved_ticker)
            name = info.get("longName") or info.get("shortName") or resolved_ticker
            currency = info.get("currency", "$")
            fmt = "{:,.0f}" if currency in ["KRW", "₩"] else "{:,.2f}"
            
            result = {
                "name": name, "ticker": resolved_ticker,
                "current_price": fmt.format(cur) + f" {currency}",
                "score": score, "color": color, "brief": brief, "reasons": reasons
            }
            
            TICKER_CACHE[resolved_ticker] = {"name": name, "score": score, "color": color}
            
            if ".KS" in resolved_ticker or ".KQ" in resolved_ticker: 
                SEARCH_COUNT_KR[resolved_ticker] += 1
            else: 
                SEARCH_COUNT_US[resolved_ticker] += 1
                
            save_ranking_to_file()
            
        except Exception: 
            result = {"error": "올바른 종목명이나 티커코드를 다시 한번 확인해 주세요."}
            
    return templates.TemplateResponse(
        request=request, 
        name="index.html", 
        context={
            "request": request, 
            "result": result, 
            "ticker": search_target, 
            "metrics_guide": SYSTEM_METRICS_GUIDE
        }
    )

# 📊 랭킹 비동기 진단용 전용 API 라우터 (독립 확보)
@app.get("/api/diagnose/{ticker}")
def api_diagnose(ticker: str = None): 
    if not ticker or ticker == "undefined":
        return {"error": "티커 코드가 올바르게 전달되지 않았습니다."}
        
    try:
        import yfinance as yf
        ticker_upper = ticker.strip().upper()
        stock_obj = yf.Ticker(ticker_upper)
        info = stock_obj.info
        
        if not info:
            return {"error": f"[{ticker_upper}] 야후 파이낸스에서 종목 정보를 찾을 수 없습니다."}
            
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
            
        try:
            save_ranking_to_file()
        except: pass
        
        return {
            "success": True,
            "name": name,
            "ticker": ticker_upper,
            "current_price": fmt.format(cur) + f" {currency}",
            "score": score,
            "color": color,
            "brief": brief,
            "reasons": reasons
        }
    except Exception as e:
        return {"error": f"🚨 싸비싸 엔진 내부 오류 발생: {str(e)}"}

# 📊 랭킹 페이지 HTML 반환 라우터 (독립 확보)
@app.get("/ranking", response_class=HTMLResponse)
def ranking(request: Request):
    try:
        kr_ranks = []
        global SEARCH_COUNT_KR, SEARCH_COUNT_US, TICKER_CACHE
        
        for i, (t, count) in enumerate(SEARCH_COUNT_KR.most_common(50)):
            cache_data = TICKER_CACHE.get(t, {}) if isinstance(TICKER_CACHE, dict) else {}
            kr_ranks.append({
                "rank": i + 1,
                "ticker": str(t),
                "name": cache_data.get("name", str(t)),
                "score": cache_data.get("score", 50),
                "color": cache_data.get("color", "#64748b"),
                "views": int(count)
            })

        us_ranks = []
        for i, (t, count) in enumerate(SEARCH_COUNT_US.most_common(50)):
            cache_data = TICKER_CACHE.get(t, {}) if isinstance(TICKER_CACHE, dict) else {}
            us_ranks.append({
                "rank": i + 1,
                "ticker": str(t),
                "name": cache_data.get("name", str(t)),
                "score": cache_data.get("score", 50),
                "color": cache_data.get("color", "#64748b"),
                "views": int(count)
            })
        
        return templates.TemplateResponse(
            request=request, 
            name="ranking.html", 
            context={"request": request, "kr_rankings": kr_ranks, "us_rankings": us_ranks}
        )
    except Exception as main_err:
        return HTMLResponse(content=f"<h2>🚨 랭킹 조립 예외 발생: {str(main_err)}</h2>", status_code=200)

# ================================================================
# 6. 기타 부속 페이지 및 서비스 라우터 
# ================================================================
@app.get("/api/autocomplete")
def api_autocomplete(q: str = ""):
    q = q.strip()
    if len(q) < 2: return []
    try:
        res = requests.get(f"https://query2.finance.yahoo.com/v1/finance/search?q={q}&lang=ko-KR&region=KR", headers={'User-Agent': 'Mozilla/5.0'}, timeout=2).json()
        return [{"ticker": i["symbol"].upper()+".KS" if i["symbol"].isdigit() and len(i["symbol"])==6 else i["symbol"].upper(), "name": i.get("longname") or i.get("shortname") or i["symbol"]} for i in res.get("quotes", []) if i.get("quoteType") in ["EQUITY", "ETF"]][:5]
    except: return []

@app.get("/strategy", response_class=HTMLResponse)
def strategy_page(request: Request): return templates.TemplateResponse(request=request, name="strategy.html", context={"request": request})

@app.get("/about", response_class=HTMLResponse)
def about_page(request: Request): return templates.TemplateResponse(request=request, name="about.html", context={"request": request})

@app.get("/privacy", response_class=HTMLResponse)
def privacy_page(request: Request): return templates.TemplateResponse(request=request, name="privacy.html", context={"request": request})

@app.get("/sitemap.xml")
def get_sitemap():
    xml_content = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
    <url><loc>https://www.ssabissa.com/</loc><priority>1.0</priority></url>
    <url><loc>https://www.ssabissa.com/ranking</loc><priority>0.8</priority></url>
    <url><loc>https://www.ssabissa.com/strategy</loc><priority>0.8</priority></url>
    <url><loc>https://www.ssabissa.com/about</loc><priority>0.5</priority></url>
</urlset>""".strip()
    return Response(content=xml_content, media_type="application/xml")

@app.get("/robots.txt", response_class=PlainTextResponse)
def get_robots_txt():
    return """User-agent: *
Allow: /
Allow: /ranking
Allow: /strategy
Allow: /about
Sitemap: https://www.ssabissa.com/sitemap.xml""".strip()

# ================================================================
# 6. 정품 가치 보존 및 초정밀 필터링 기반 커뮤니티 API 엔진 구역
# ================================================================

# 1. 특정 종목의 커뮤니티 데이터(투표수 + 댓글목록) 가져오기 API
@app.get("/api/community/{ticker}")
def get_community_data(ticker: str):
    t = ticker.strip().upper()
    votes = VOTE_DB.get(t, {"up": 0, "down": 0})
    talks = TALK_DB.get(t, [])
    return {"votes": votes, "talks": talks}

# 2. 상승/하락 투표하기 API
@app.post("/api/community/{ticker}/vote")
def post_vote(ticker: str, type: str = Form(...)):
    t = ticker.strip().upper()
    if t not in VOTE_DB:
        VOTE_DB[t] = {"up": 0, "down": 0}
        
    if type in ["up", "down"]:
        VOTE_DB[t][type] += 1
        
    save_community_to_file() 
    return {"success": True, "votes": VOTE_DB[t]}

# 3. 🚨 익명 한 줄 응원방 글쓰기 API (서울시간 고정 + 닉네임 숫자 조합 + 초강력 필터)
@app.post("/api/community/{ticker}/talk")
def post_talk(ticker: str, text: str = Form(...)):
    t = ticker.strip().upper()
    clean_text = text.strip()
    
    # ❌ [주송이 초강력 블랙리스트] 교묘한 특수문자나 유도 문구를 필터링할 정밀 단어장
    BAD_WORDS = [
        "리딩방", "카톡방", "추천주", "수익보장", "시발", "개새끼", "조까", "급등주", 
        "대박 정보", "대박정보", "무료리딩", "오픈채팅", "카카오톡", "방입장", "선착순",
        "비밀방", "t.me", "open.kakao", "입장하기", "목표수익", "원금보장"
    ]
    
    # 공백이나 엔터를 다 걷어내고 글자만 순수 비교해서 숨겨둔 광고 단어까지 탐지
    compressed_text = clean_text.replace(" ", "").replace("\n", "").replace("\r", "")
    if any(word in compressed_text for word in BAD_WORDS):
        return {"error": "🚨 싸비싸 운영 정책에 따라 광고성 문구나 부적절한 표현은 등록할 수 없습니다."}
        
    if not clean_text:
        return {"error": "내용을 입력해 주세요."}
        
    # ⏰ [서울 시간 완전 보정] 싱가포르 등 클라우드 해외 서버 시차 무조건 교정
    from datetime import datetime, timezone, timedelta
    kst = timezone(timedelta(hours=9)) # KST 대한민국 표준시 강제 주입
    now_dt = datetime.now(kst)
    
    current_time = now_dt.strftime("%H:%M")
    current_date = now_dt.strftime("%Y-%m-%d") # 30일 만료 체크용 타임스탬프
    
    # 🎰 [주송이 초이스] 기분 좋은 형용사 + 동물 + 0~100 숫자 완벽 크래프트
    import random
    adjectives = ["용감한", "행복한", "돈많은", "존버하는", "화끈한", "스마트한", "아름다운", "매력적인", "멋있는", "신중한", "똑똑한"]
    nouns = ["코알라", "기린", "얼룩말", "개미", "고래", "호랑이", "사자", "판다", "고양이", "강아지", "돌고래", "기러기", "참새", "베짱이"]
    random_num = random.randint(0, 100) # 0~100 무작위 숫자 스택
    
    # 👤 최종 완성형 유니크 닉네임 (예시: '돈많은 판다 77')
    random_nickname = f"{random.choice(adjectives)} {random.choice(nouns)} {random_num}"
    
    new_talk = {
        "nickname": random_nickname,
        "text": clean_text,
        "time": current_time,
        "date": current_date
    }
    
    if t not in TALK_DB:
        TALK_DB[t] = []
        
    TALK_DB[t].insert(0, new_talk)
    TALK_DB[t] = TALK_DB[t][:50] # 스크롤 구현을 위해 최대 저장선을 50개로 넉넉히 상향 조정
    
    save_community_to_file() 
    return {"success": True, "talks": TALK_DB[t]}


# 🧹 4. 30일(한 달) 경과 묵은 데이터 영구 자동 폭파 정화 엔진
def clear_expired_talks():
    """6시간마다 스케줄러 루프가 동기화할 때 작동하여, 한 달이 지난 옛날 데이터를 외장하드에서 제거합니다."""
    global TALK_DB
    from datetime import datetime, timezone, timedelta
    
    kst = timezone(timedelta(hours=9))
    now_dt = datetime.now(kst)
    
    print("🧹 [싸비싸 디스크 정화기] 유통기한(30일)이 지난 익명 댓글 파기 프로세스를 작동합니다...")
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
                # 현재 시점과 대조하여 30일 미만으로 남은 쌩쌩한 글만 필터링해서 생존
                if (now_dt - talk_date).days < 30:
                    valid_talks.append(talk)
                else:
                    removed_count += 1
            except:
                valid_talks.append(talk)
                
        TALK_DB[ticker] = valid_talks
        
    if removed_count > 0:
        save_community_to_file()
        print(f"✅ [싸비싸 디스크 정화기] 기한 만료된 오래된 익명 댓글 총 {removed_count}개 영구 소멸 완료!")


# 🧹 5. 마스터 암행어사 댓글 강제 즉시 삭제 API
@app.delete("/api/admin/clear/talk")
def admin_clear_talk(ticker: str, password: str, index: int = 0):
    """주송이님만 아는 마스터 비밀번호로 특정 종목의 N번째 댓글을 브라우저에서 즉시 지웁니다."""
    # 🤫 노출 방지를 위해 마음에 드는 패스워드로 고치셔도 됩니다!
    MASTER_PASSWORD = "jusongsecret123" 
    
    if password != MASTER_PASSWORD:
        raise HTTPException(status_code=403, detail="권한이 없습니다.")
        
    t = ticker.strip().upper()
    if t in TALK_DB and len(TALK_DB[t]) > index:
        removed = TALK_DB[t].pop(index)
        save_community_to_file() # 삭제 즉시 Render 외장하드 동기화 구워버리기
        return {"success": True, "message": f"[{removed['text']}] 댓글을 정상 소거했습니다."}
        
    return {"error": "삭제할 대상 댓글이 존재하지 않습니다."}
# 기존 코드들...

@app.get("/calendar")
async def calendar(request: Request):
    # 추후 DB 연동 시 risk_items와 earning_items에 데이터를 담아 보냅니다.
    return templates.TemplateResponse(
        "calendar.html", 
        {
            "request": request, 
            "risk_items": None, 
            "earning_items": None
        }
    )