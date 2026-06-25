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
# 2. [필수 순서 1] 변수 선언을 위해 기반 파일(STOCK_MAP)을 최우선으로 로드
# ================================================================
if os.path.exists(STOCK_MAP_FILE):
    with open(STOCK_MAP_FILE, "r", encoding="utf-8") as f:
        STOCK_MAP = json.load(f)
else:
    print(f"⚠️ 경고: {STOCK_MAP_FILE} 파일이 존재하지 않습니다!")

# ================================================================
# 3. [필수 순서 2] 하위 로직에서 안전하게 호출할 유틸 함수 정의
# ================================================================
def save_ranking_to_file():
    # 현재 메모리에 있는 카운트 데이터를 통합해서 JSON 파일로 저장합니다.
    payload = {
        "KR": dict(SEARCH_COUNT_KR),
        "US": dict(SEARCH_COUNT_US)
    }
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=4)

# ================================================================
# 4. FastAPI 객체 생성 및 랭킹 초기화 데이터 주입 (조회수 1 세팅)
# ================================================================
app = FastAPI()

# 데이터 파일(ranking_data.json)이 없는 최초 실행 시에만 1로 초기화합니다.
if not os.path.exists(DATA_FILE):
    for name, ticker in STOCK_MAP.items():
        # 캐시(TICKER_CACHE)에 종목 이름과 기본 스코어 정보를 미리 연동해 둡니다.
        if ticker not in TICKER_CACHE:
            TICKER_CACHE[ticker] = {
                "name": name, 
                "score": 50,       # 초기 기본 가치 점수 (유저가 검색하면 실시간 갱신됨)
                "color": "#64748b" # 초기 기본 색상 (회색)
            }
        
        # 한국 주식과 미국 주식을 티커 형태로 구분하여 초기 조회수 1 주입
        if ".KS" in ticker or ".KQ" in ticker:
            if SEARCH_COUNT_KR[ticker] == 0:
                SEARCH_COUNT_KR[ticker] = 1
        else:
            if "000000" not in ticker:  # 미상장 임시 데이터 제외
                if SEARCH_COUNT_US[ticker] == 0:
                    SEARCH_COUNT_US[ticker] = 1
                    
    # 초기 세팅된 조회수 1짜리 더미 데이터를 json 파일로 즉시 저장합니다.
    try:
        save_ranking_to_file()
        print("🚀 [가치 스캐너] 1,200대장 종목 랭킹 초기화 완료! (기본 조회수 1 세팅)")
    except Exception as e:
        print(f"⚠️ 랭킹 초기화 파일 저장 중 오류 발생: {e}")

# ================================================================
# 5. 비즈니스 로직 라우터 시작 (이 아래로 기존 home 함수가 이어집니다)
# ================================================================
@app.get("/")
@app.post("/")
def home(request: Request, ticker: str = Form(None), q: str = None):
    import yfinance as yf
    search_target = ticker or q
    result = None
    
    if search_target:
        # 400대장 딕셔너리 매핑 및 공백 제거
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
                
            # 검색할 때마다 실시간으로 파일 보존
            save_ranking_to_file()
            
        except Exception: 
            result = {"error": "올바른 종목명이나 티커코드를 다시 한번 확인해 주세요."}
            
    # 첫 메인 주소("/")로 들어오면 무조건 index.html을 보여줍니다!
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

@app.get("/sitemap.xml")
def get_sitemap():
    xml_content = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
    <url>
        <loc>https://www.ssabissa.com/</loc>
        <priority>1.0</priority>
    </url>
    <url>
        <loc>https://www.ssabissa.com/ranking</loc>
        <priority>0.8</priority>
    </url>
    <url>
        <loc>https://www.ssabissa.com/strategy</loc>
        <priority>0.8</priority>
    </url>
    <url>
        <loc>https://www.ssabissa.com/about</loc>
        <priority>0.5</priority>
    </url>
</urlset>
""".strip()
    return Response(content=xml_content, media_type="application/xml")
templates = Jinja2Templates(directory="templates")
templates.env.cache = None

# 실시간 랭킹 캐시 디렉토리
SEARCH_COUNT_KR = Counter({"005930.KS": 15, "000660.KS": 12, "035420.KS": 8, "035720.KS": 7, "005380.KS": 6})
SEARCH_COUNT_US = Counter({"AAPL": 20, "TSLA": 18, "NVDA": 15, "MSFT": 12, "AMZN": 10})
if os.path.exists(DATA_FILE):
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        try:
            past_data = json.load(f)
            # 옛날 기록이 있으면 불러와서 복구합니다.
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
    # 🎯 요청사항 반영: 기본 시작 점수 65점으로 세팅
    score = 65
    reasons = []
    is_kr = ".KS" in ticker or ".KQ" in ticker
    
    # 1. 🚨 [독립 분리 1] 최근 6개월 내 유상증자(발행주식 수 증가) 횟수 추적 로직
    try:
        tk = yf.Ticker(ticker)
        # 분기별 주식 수 추적 (최근 2분기 = 약 6개월 데이터 비교)
        shares_history = tk.get_shares_full(start="2025-12-01", end="2026-06-25")
        if shares_history is not None and len(shares_history) >= 2:
            dilution_count = 0
            prev_shares = shares_history.iloc[0]
            for current_shares in shares_history[1:]:
                # 이전 분기보다 주식 수가 늘어났다면 유상증자 혹은 주식 희석 행위로 판단
                if current_shares > prev_shares * 1.005:  # 0.5% 이상 유의미한 증가만 카운트
                    dilution_count += 1
                prev_shares = current_shares
            
            if dilution_count > 0:
                dilution_penalty = dilution_count * 5  # ⚡ 회당 5점 감점
                score -= dilution_penalty
                reasons.append(f"- 최근 6개월 내 유상증자 리스크 유발 ({dilution_count}회 진행)")
    except:
        # 혹시 히스토리 데이터가 안 잡히는 신생 기업 등은 outstanding 기준으로 보수적 방어 체계만 가동
        if info.get("sharesOutstanding", 0) > 2000000000:
            score -= 5; reasons.append("- 유통 주식 물량 과다 부담")

    # 2. 🚨 [독립 분리 2] 부채비율 부담 리스크 분리
    debt_eq = info.get("debtToEquity", 0)
    if debt_eq > 180:  
        score -= 7; reasons.append("- 위험 수준의 고부채 재무 부담 리스크")

    # 3. PER 가성비 검증
    per = info.get("forwardPE")
    if per:
        if is_kr and per < 8: score += 7; reasons.append("+ 선행 PER 기준 국장 저평가 메리트")
        elif not is_kr and per < 18: score += 7; reasons.append("+ 선행 PER 기준 미장 가성비 양호")
        elif per > 35: score -= 6; reasons.append("- 높은 멀티플 오버밸류 경계")

    # 4. PBR 자산가치 검증
    pbr = info.get("priceToBook")
    if pbr:
        if is_kr and pbr < 0.5: score += 6; reasons.append("+ 장부상 청산가치 이하 저PBR 수혜")
        elif not is_kr and pbr < 3.0: score += 4; reasons.append("+ 적정 수준의 자산 가치 반영")
        elif pbr > 10.0: score -= 5; reasons.append("- 자산 가치 대비 멀티플 과열 위험")

    # 5. 목표가 괴리율 안전마진
    target, cur = info.get("targetMeanPrice"), info.get("currentPrice") or info.get("regularMarketPrice")
    if target and cur:
        gap = (target - cur) / target * 100
        if gap > 25: score += 8; reasons.append("+ 증권사 목표가 대비 안전마진")
        elif gap < 0: score -= 10; reasons.append("- 목표가 상회로 인한 단기 고평가 영역")
    
    # 6. 기타 펀더멘탈
    if info.get("dividendYield", 0) * 100 >= 4.0: score += 4; reasons.append("+ 안정적인 배당 수익률 뒷받침")
    if info.get("operatingMargins", 0) < 0: score -= 12; reasons.append("- 영업이익 적자 구조 리스크")
    if info.get("earningsGrowth", 0) * 100 >= 25: score += 5; reasons.append("+ 고성장 기업 프리미엄 버프")

    # 7. 6개월 주가 추세 모멘텀
    try:
        hist = yf.Ticker(ticker).history(period="6mo")
        if len(hist) >= 2:
            change = (hist['Close'].iloc[-1] - hist['Close'].iloc[0]) / hist['Close'].iloc[0]
            if change <= -0.08: score -= 6; reasons.append("- 가치함정 주의 (6개월간 소외 우하향)")
            elif change >= 0.20: score += 4; reasons.append("+ 시장 선호 수급 유입")
    except: pass

    # 극단치 압축 완충 마진율 적용
    deviation = score - 60
    score = 60 + int(deviation * 0.85)

    score = max(0, min(100, int(score)))
    color = get_score_color(score)
    
    if score >= 68: verdict, brief = "[저평가 매력 구간]", "보수적인 기준에서도 안전마진이 비교적 안정적으로 확보된 진입 매력 구간입니다."
    elif score >= 48: verdict, brief = "[적정 가치 구간]", "현재 시장에서 기업의 기초 체력과 성장성에 알맞은 정상적인 대우를 받고 있습니다."
    else: verdict, brief = "[고평가 경계 구간]", "단기 주가 거품이나 재무적 페널티가 중첩되어 있어 리스크 관리가 필요한 구간입니다."

    return score, color, reasons, brief

@app.get("/", response_class=HTMLResponse)
@app.post("/", response_class=HTMLResponse)
@app.get("/ranking", response_class=HTMLResponse)
@app.get("/api/diagnose/{ticker}")
def api_diagnose(ticker: str = None): 
    """랭킹 페이지에서 종목 클릭 시 화면 전환 없이 결과를 반환하는 API (서버에러 완벽 디버깅 버전)"""
    if not ticker or ticker == "undefined":
        return {"error": "티커 코드가 올바르게 전달되지 않았습니다."}
        
    try:
        # 💡 [리스크 방어 1] 상단 전역 임포트가 꼬였을 수 있으므로 함수 내부에서 yfinance 명시적 가동
        import yfinance as yf
        
        # 소문자 및 공백 완벽 제거
        ticker_upper = ticker.strip().upper()
        
        # 💡 [리스크 방어 2] yf.Ticker 호출 시 네트워크 지연 및 데이터 누락 방어
        stock_obj = yf.Ticker(ticker_upper)
        info = stock_obj.info
        
        if not info:
            return {"error": f"[{ticker_upper}] 야후 파이낸스에서 종목 정보를 찾을 수 없습니다."}
            
        cur = info.get("currentPrice") or info.get("regularMarketPrice") or info.get("previousClose")
        if not cur: 
            return {"error": f"[{ticker_upper}] 현재 거래가 데이터를 받아오지 못했습니다. 잠시 후 다시 시도해 주세요."}
        
        # 💡 [주의] 혹시 주송이님 원래 분석 함수 이름이 'calculate_score'라면 이 부분을 고치셔야 합니다!
        score, color, reasons, brief = calculate_ssabissa_score(info, ticker_upper)
        
        name = info.get("longName") or info.get("shortName") or ticker_upper
        currency = info.get("currency", "$")
        fmt = "{:,.0f}" if currency in ["KRW", "₩"] else "{:,.2f}"
        
        # 💡 [리스크 방어 3] 캐시 및 카운터 사전에 안전하게 데이터 등록 (KeyError 방지)
        TICKER_CACHE[ticker_upper] = {"name": name, "score": score, "color": color}
        
        if ".KS" in ticker_upper or ".KQ" in ticker_upper: 
            SEARCH_COUNT_KR[ticker_upper] += 1
        else: 
            SEARCH_COUNT_US[ticker_upper] += 1
            
        # 실시간 랭킹 디스크 저장
        try:
            save_ranking_to_file()
        except Exception as file_err:
            print(f"⚠️ 랭킹 파일 저장 실패(무시하고 진행): {file_err}")
        
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
        # 💡 500 Internal Server Error를 뱉지 않고, 뭐가 문제인지 팝업창에 에러를 솔직하게 뱉어줍니다.
        return {"error": f"🚨 싸비싸 엔진 내부 오류 발생: {str(e)}"}

# ================================================================
# 2. 📊 랭킹 템플릿 반환 라우터 (안전장치 추가)
# ================================================================
@app.get("/ranking", response_class=HTMLResponse)
def ranking(request: Request):
    """Internal Server Error를 원천 차단하는 안전망이 탑재된 랭킹 라우터"""
    try:
        # 🇰🇷 한국 주식 랭킹 빌드
        kr_ranks = []
        # 혹시 전역 변수가 바인딩 안 되었을 리스크 방어
        global SEARCH_COUNT_KR, SEARCH_COUNT_US, TICKER_CACHE
        
        for i, (t, count) in enumerate(SEARCH_COUNT_KR.most_common(50)):
            try:
                # TICKER_CACHE가 사전이 아니거나 에러가 날 상황을 완전 방어
                if isinstance(TICKER_CACHE, dict) and t in TICKER_CACHE:
                    cache_data = TICKER_CACHE[t]
                else:
                    cache_data = {}
            except Exception:
                cache_data = {}

            kr_ranks.append({
                "rank": i + 1,
                "ticker": str(t),
                "name": cache_data.get("name", str(t)) if isinstance(cache_data, dict) else str(t),
                "score": cache_data.get("score", 50) if isinstance(cache_data, dict) else 50,
                "color": cache_data.get("color", "#64748b") if isinstance(cache_data, dict) else "#64748b",
                "views": int(count)
            })

        # 🇺🇸 미국 주식 랭킹 빌드
        us_ranks = []
        for i, (t, count) in enumerate(SEARCH_COUNT_US.most_common(50)):
            try:
                if isinstance(TICKER_CACHE, dict) and t in TICKER_CACHE:
                    cache_data = TICKER_CACHE[t]
                else:
                    cache_data = {}
            except Exception:
                cache_data = {}

            us_ranks.append({
                "rank": i + 1,
                "ticker": str(t),
                "name": cache_data.get("name", str(t)) if isinstance(cache_data, dict) else str(t),
                "score": cache_data.get("score", 50) if isinstance(cache_data, dict) else 50,
                "color": cache_data.get("color", "#64748b") if isinstance(cache_data, dict) else "#64748b",
                "views": int(count)
            })
        
        # 템플릿 엔진 정상 송출
        return templates.TemplateResponse(
            request=request, 
            name="ranking.html", 
            context={
                "request": request, 
                "kr_rankings": kr_ranks, 
                "us_rankings": us_ranks
            }
        )
        
    except Exception as main_err:
        # 💡 [치트키] 만약 이 안에서조차 에러가 나면 500화면을 띄우지 않고 무엇이 범인인지 화면에 텍스트로 찍어줍니다.
        from fastapi.responses import HTMLResponse
        error_html = f"""
        <html>
            <body style="font-family:sans-serif; padding:50px; line-height:1.6;">
                <h2>🚨 싸비싸 백엔드 렌더링 긴급 정지</h2>
                <p>랭킹 데이터를 조립하던 중 파이썬 예외가 발생했습니다.</p>
                <pre style="background:#eee; padding:15px; border-radius:8px; color:red;">{str(main_err)}</pre>
                <p>위 에러 문구를 AI 동료에게 전달해 주시면 바로 고쳐드릴게요!</p>
                <a href="/">🏠 메인 홈으로 돌아가기</a>
            </body>
        </html>
        """
        return HTMLResponse(content=error_html, status_code=200)
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
from fastapi.responses import PlainTextResponse

# 로봇이 www.ssabissa.com/robots.txt 로 들어오면 이 함수가 실행됩니다.
@app.get("/robots.txt", response_class=PlainTextResponse)
def get_robots_txt():
    return """User-agent: *
Allow: /
Allow: /ranking
Allow: /strategy
Allow: /about
Sitemap: https://www.ssabissa.com/sitemap.xml
"""