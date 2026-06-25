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
DATA_FILE = "ranking_data.json"
STOCK_MAP_FILE = "stock_map.json"

STOCK_MAP = {}
SEARCH_COUNT_KR = Counter()
SEARCH_COUNT_US = Counter()
TICKER_CACHE = {}

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
# 3. 데이터 복구 및 기본 랭킹 데이터 스택 장전
# ================================================================
# 덤프 기본 카운터 초기값 설정
SEARCH_COUNT_KR.update({"005930.KS": 15, "000660.KS": 12, "035420.KS": 8, "035720.KS": 7, "005380.KS": 6})
SEARCH_COUNT_US.update({"AAPL": 20, "TSLA": 18, "NVDA": 15, "MSFT": 12, "AMZN": 10})

if os.path.exists(DATA_FILE):
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        try:
            past_data = json.load(f)
            for k, v in past_data.get("KR", {}).items(): SEARCH_COUNT_KR[k] = v
            for k, v in past_data.get("US", {}).items(): SEARCH_COUNT_US[k] = v
        except Exception:
            pass

TICKER_CACHE = {
    "005930.KS": {"name": "삼성전자", "score": 62, "color": "hsl(55, 85%, 45%)"},
    "000660.KS": {"name": "SK하이닉스", "score": 65, "color": "hsl(60, 85%, 45%)"},
    "035420.KS": {"name": "NAVER", "score": 58, "color": "hsl(48, 85%, 45%)"},
    "AAPL": {"name": "Apple Inc.", "score": 68, "color": "hsl(65, 85%, 45%)"},
    "TSLA": {"name": "Tesla, Inc.", "score": 54, "color": "hsl(43, 85%, 45%)"}
}

SYSTEM_METRICS_GUIDE = [
    {"type": "plus", "keyword": "괴리율", "title": "목표가 괴리율 안전마진", "desc": "증권사 평균 목표가와 현재 주가의 차이가 벌어져 안전마진이 확보된 경우 가점을 부여합니다."},
    {"type": "plus", "keyword": "PER", "title": "선행 PER 가성비", "desc": "1년 뒤 예상 실적 대비 주가가 현저히 저렴한 구간입니다."},
    {"type": "plus", "keyword": "PBR", "title": "자산 가치 대비 저평가", "desc": "기업이 가진 순자산보다 주가가 싸게 거래되는 장부상 저평가 상태입니다."},
    {"type": "plus", "keyword": "배당", "title": "우수한 배당 수익률", "desc": "연 4% 이상의 배당으로 주가 하락 시 강력한 현금 흐름 방어선 역할을 합니다."},
    {"type": "plus", "keyword": "초성장", "title": "초성장 기술주 버프", "desc": "연 실적 성장률이 30%를 넘는 혁신 기업에 부여되는 프리미엄입니다."},
    {"type": "plus", "keyword": "선호", "title": "시장 선호주 인정", "desc": "최근 6개월간 우상향하며 자금이 지속 유입되는 대세 종목입니다."},
    {"type": "minus", "keyword": "증자", "title": "최근 유상증자 희석 리스크", "desc": "최근 6개월 내 유상증자 등 발행 주식 수가 증가하여 주주 가치가 희석된 횟수만큼 감점합니다."},
    {"type": "minus", "keyword": "고부채", "title": "부채비율 과다 부담", "desc": "부채비율이 업종 평균 대비 과도하게 높아 재무적 리스크가 있는 경우 감점합니다."},
    {"type": "minus", "keyword": "과열", "title": "목표가 대비 현재가 과열", "desc": "단기 과열 국면에 진입한 경우입니다."},
    {"type": "minus", "keyword": "적자", "title": "영업이익 적자 상태", "desc": "사업을 할수록 돈을 잃고 있는 구조적 위험 단계입니다."},
    {"type": "minus", "keyword": "가치함정", "title": "가치함정 주의보", "desc": "최근 6개월간 주가가 하락하거나 정체되어 시장에서 소외된 종목입니다."}
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

if not os.path.exists(DATA_FILE):
    for name, ticker in STOCK_MAP.items():
        if ticker not in TICKER_CACHE:
            TICKER_CACHE[ticker] = {"name": name, "score": 50, "color": "#64748b"}
        if ".KS" in ticker or ".KQ" in ticker:
            if SEARCH_COUNT_KR[ticker] == 0: SEARCH_COUNT_KR[ticker] = 1
        else:
            if "000000" not in ticker:
                if SEARCH_COUNT_US[ticker] == 0: SEARCH_COUNT_US[ticker] = 1
    try:
        save_ranking_to_file()
    except: pass

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
                score -= (dilution_count * 5)
                reasons.append(f"- 최근 6개월 내 유상증자 리스크 유발 ({dilution_count}회 진행)")
    except:
        if info.get("sharesOutstanding", 0) > 2000000000:
            score -= 5; reasons.append("- 유통 주식 물량 과다 부담")

    debt_eq = info.get("debtToEquity", 0)
    if debt_eq > 180: score -= 7; reasons.append("- 위험 수준의 고부채 재무 부담 리스크")

    per = info.get("forwardPE")
    if per:
        if is_kr and per < 8: score += 7; reasons.append("+ 선행 PER 기준 국장 저평가 메리트")
        elif not is_kr and per < 18: score += 7; reasons.append("+ 선행 PER 기준 미장 가성비 양호")
        elif per > 35: score -= 6; reasons.append("- 높은 멀티플 오버밸류 경계")

    pbr = info.get("priceToBook")
    if pbr:
        if is_kr and pbr < 0.5: score += 6; reasons.append("+ 장부상 청산가치 이하 저PBR 수혜")
        elif not is_kr and pbr < 3.0: score += 4; reasons.append("+ 적정 수준의 자산 가치 반영")
        elif pbr > 10.0: score -= 5; reasons.append("- 자산 가치 대비 멀티플 과열 위험")

    target, cur = info.get("targetMeanPrice"), info.get("currentPrice") or info.get("regularMarketPrice")
    if target and cur:
        gap = (target - cur) / target * 100
        if gap > 25: score += 8; reasons.append("+ 증권사 목표가 대비 안전마진")
        elif gap < 0: score -= 10; reasons.append("- 목표가 상회로 인한 단기 고평가 영역")
    
    if info.get("dividendYield", 0) * 100 >= 4.0: score += 4; reasons.append("+ 안정적인 배당 수익률 뒷받침")
    if info.get("operatingMargins", 0) < 0: score -= 12; reasons.append("- 영업이익 적자 구조 리스크")
    if info.get("earningsGrowth", 0) * 100 >= 25: score += 5; reasons.append("+ 고성장 기업 프리미엄 버프")

    try:
        import yfinance as yf
        hist = yf.Ticker(ticker).history(period="6mo")
        if len(hist) >= 2:
            change = (hist['Close'].iloc[-1] - hist['Close'].iloc[0]) / hist['Close'].iloc[0]
            if change <= -0.08: score -= 6; reasons.append("- 가치함정 주의 (6개월간 소외 우하향)")
            elif change >= 0.20: score += 4; reasons.append("+ 시장 선호 수급 유입")
    except: pass

    deviation = score - 60
    score = 60 + int(deviation * 0.85)
    score = max(0, min(100, int(score)))
    color = get_score_color(score)
    
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