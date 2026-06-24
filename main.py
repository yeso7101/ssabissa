import yfinance as yf
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from collections import Counter
import requests
from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi import FastAPI, HTTPException
import json
import os



DATA_FILE = "ranking_data.json"
app = FastAPI()
# [파일 저장용 유틸 함수]
def save_ranking_to_file():
    # 현재 메모리에 있는 카운트 데이터를 통합해서 JSON 파일로 저장합니다.
    payload = {
        "KR": dict(SEARCH_COUNT_KR),
        "US": dict(SEARCH_COUNT_US)
    }
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=4)

@app.get("/")
@app.post("/")
def home(request: Request, ticker: str = Form(None), q: str = None):
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

STOCK_MAP = {
    # ================================================================
    # 🇰🇷 대한민국 주식 (국장 핵심 200종목 - 야후 파이낸스 .KS/.KQ 규격)
    # ================================================================
    "삼성전자": "005930.KS", "삼성": "005930.KS", "삼전": "005930.KS",
    "sk하이닉스": "000660.KS", "하이닉스": "000660.KS", "에스케이하이닉스": "000660.KS", "국전": "000660.KS",
    "lg에너지솔루션": "373220.KS", "lg엔솔": "373220.KS", "엔솔": "373220.KS",
    "삼성바이오로직스": "207940.KS", "삼바": "207940.KS",
    "현대자동차": "005380.KS", "현대차": "005380.KS",
    "기아": "000270.KS", "기아차": "000270.KS",
    "셀트리온": "068270.KS",
    "포스코홀딩스": "005490.KS", "포스코": "005490.KS", "posco홀딩스": "005490.KS",
    "네이버": "035420.KS", "naver": "035420.KS",
    "신한지주": "055550.KS", "신한은행": "055550.KS", "신한금융지주": "055550.KS",
    "kb금융": "105560.KS", "국민은행": "105560.KS", "kb금융지주": "105560.KS",
    "삼성물산": "028260.KS",
    "삼성sdi": "006400.KS", "삼성에스디아이": "006400.KS", "sdi": "006400.KS",
    "lg화학": "051910.KS", "엘지화학": "051910.KS",
    "카카오": "035720.KS",
    "현대모비스": "012330.KS", "모비스": "012330.KS",
    "포스코퓨처엠": "003670.KS", "퓨처엠": "003670.KS",
    "하나금융지주": "086790.KS", "하나금융": "086790.KS", "하나은행": "086790.KS",
    "메리츠금융지주": "138040.KS", "메리츠": "138040.KS",
    "삼성생명": "032830.KS",
    "에코프로비엠": "247540.KQ", "에코프로bm": "247540.KQ", "비엠": "247540.KQ",
    "에코프로": "086520.KQ",
    "알테오젠": "196170.KQ",
    "hlb": "028300.KQ", "에이치엘비": "028300.KQ",
    "kt&g": "033780.KS", "케이티앤지": "033780.KS", "담배": "033780.KS",
    "카카오뱅크": "323410.KS", "카뱅": "323410.KS",
    "삼성화재": "000810.KS",
    "기업은행": "024110.KS",
    "한국전력": "015760.KS", "한전": "015760.KS",
    "크래프톤": "259960.KS", "배그": "259960.KS",
    "sk이노베이션": "096770.KS", "sk이노": "096770.KS",
    "두산에너빌리티": "034020.KS", "두산중공업": "034020.KS", "에너빌리티": "034020.KS",
    "h運": "011200.KS", "hmm": "011200.KS", "흠": "011200.KS",
    "s-oil": "010950.KS", "에쓰오일": "010950.KS", "쌍용정유": "010950.KS",
    "lg전자": "066570.KS", "엘지전자": "066570.KS",
    "대한항공": "003490.KS", "땅콩": "003490.KS",
    "삼성에스디에스": "018260.KS", "삼성sds": "018260.KS", "sds": "018260.KS",
    "우리금융지주": "316140.KS", "우리금융": "316140.KS", "우리은행": "316140.KS",
    "포스코인터내셔널": "047050.KS", "포인": "047050.KS",
    "한화오션": "042660.KS", "대우조선해양": "042660.KS",
    "삼성전기": "009150.KS", "전기": "009150.KS",
    "한화솔루션": "009830.KS",
    "kt": "030200.KS", "케이티": "030200.KS",
    "고려아연": "010130.KS",
    "엔씨소프트": "036570.KS", "nc소프트": "036570.KS", "린저씨": "036570.KS",
    "한미반도체": "042700.KS", "한미": "042700.KS",
    "sk": "034730.KS", "에스케이": "034730.KS",
    "하이브": "352820.KS", "bts": "352820.KS",
    "한국항공우주": "047810.KS", "kai": "047810.KS",
    "아모레퍼시픽": "090430.KS", "아모레": "090430.KS",
    "hd현대중공업": "329180.KS", "현중": "329180.KS",
    "sk스퀘어": "402340.KS",
    "금호석유": "011780.KS",
    "현대글로비스": "086280.KS", "글로비스": "086280.KS",
    "lgu+": "032640.KS", "lg유플러스": "032640.KS", "유플러스": "032640.KS",
    "코웨이": "021240.KS", "웅진코웨이": "021240.KS",
    "cj제일제당": "097950.KS", "제일제당": "097950.KS",
    "한화에어로스페이스": "012450.KS", "한화에어로": "012450.KS",
    "포스코디엑스": "022100.KS", "포스코dx": "022100.KS", "dx": "022100.KS",
    "엔켐": "348370.KQ",
    "유한양행": "000100.KS",
    "hd현대일렉트릭": "267260.KS", "현대일렉": "267260.KS",
    "셀트리온제약": "068760.KQ",
    "현대건설": "000720.KS",
    "f&f": "383220.KS", "에프앤에프": "383220.KS",
    "넷마블": "251270.KS",
    "리노공업": "058470.KQ",
    "한진칼": "180640.KS",
    "두산밥캣": "241560.KS", "밥캣": "241560.KS",
    "쌍용C&E": "003410.KS", "쌍용시멘트": "003410.KS",
    "이마트": "139480.KS",
    "오리온": "271560.KS",
    "gs": "078930.KS", "지에스": "078930.KS",
    "한미약품": "128940.KS",
    "신세계": "004170.KS",
    "호텔신라": "008770.KS", "신라호텔": "008770.KS",
    "현대위아": "011210.KS",
    "제일기획": "030000.KS",
    "hd현대": "267250.KS",
    "롯데지주": "004990.KS",
    "롯데케미칼": "011170.KS",
    "한국금융지주": "071050.KS", "한국투자증권": "071050.KS", "한투": "071050.KS",
    "lg디스플레이": "034220.KS", "lg디플": "034220.KS", "디플": "034220.KS",
    "현대백화점": "069960.KS", "현백": "069960.KS",
    "cj": "001040.KS", "씨제이": "001040.KS",
    "ls": "006260.KS", "엘에스": "006260.KS",
    "대우건설": "047040.KS",
    "hd현대인프라코어": "042670.KS", "두산인프라코어": "042670.KS",
    "skc": "011790.KS", "에스케이씨": "011790.KS",
    "sk바이오팜": "326030.KS", "sk바팜": "326030.KS",
    "bgh": "282330.KS", "bgf리테일": "282330.KS", "cu": "282330.KS",
    "씨젠": "096530.KQ",
    "솔브레인": "352820.KQ",
    "에스엠": "041510.KQ", "sm": "041510.KQ",
    "jyp": "035900.KQ", "jypent": "035900.KQ", "박진영": "035900.KQ",
    "와이지엔터테인먼트": "122870.KQ", "yg": "122870.KQ", "와이지": "122870.KQ",
    "펄어비스": "263750.KQ", "검은사막": "263750.KQ",
    "컴투스": "078340.KQ",
    "동진쎄미켐": "005290.KQ",
    "원익ips": "240810.KQ",
    "천보": "278280.KQ",
    "파라다이스": "034230.KQ",
    "스튜디오드래곤": "253450.KQ", "드래곤": "253450.KQ",
    "hpsp": "403870.KQ",
    "이오테크닉스": "039030.KQ",
    "클래시스": "214150.KQ",
    "두산": "000150.KS",
    "한화": "000880.KS",
    "코오롱인더": "120110.KS",
    "효성티앤씨": "298020.KS",
    "효성중공업": "298040.KS",
    "풍산": "103140.KS",
    "영원무역": "111770.KS",
    "노스페이스": "111770.KS",
    "태광산업": "003240.KS",
    "대한유화": "006650.KS",
    "롯데쇼핑": "023530.KS", "롯데백화점": "023530.KS",
    "gs리테일": "007070.KS", "gs25": "007070.KS",
    "신세계인터내셔날": "031430.KS",
    "현대홈쇼핑": "057050.KS",
    "오뚜기": "007310.KS", "갓뚜기": "007310.KS",
    "농심": "004370.KS", "신라면": "004370.KS",
    "삼양식품": "003230.KS", "불닭볶음면": "003230.KS", "삼양": "003230.KS",
    "대상": "001680.KS", "미원": "001680.KS",
    "풀무원": "017810.KS",
    "동원f&b": "016800.KS", "동원참치": "016800.KS",
    "매일유업": "267980.KQ",
    "빙그레": "005180.KS", "바나나맛우유": "005180.KS",
    "하이트진로": "000080.KS", "테라": "000080.KS", "참이슬": "000080.KS",
    "오리온홀딩스": "001800.KS",
    "보령": "003850.KS", "보령제약": "003850.KS",
    "한미사이언스": "008930.KS",
    "대웅제약": "069620.KS",
    "종근당": "185750.KS",
    "동아에스티": "170900.KS", "동아제약": "170900.KS",
    "광동제약": "009290.KS", "비타500": "009290.KS",
    "일양약품": "007570.KS",
    "부광약품": "003000.KS",
    "신풍제약": "019170.KS",
    "메디톡스": "086900.KQ",
    "휴젤": "145020.KQ",
    "젬백스": "082270.KQ",
    "에스티팜": "237690.KQ",
    "레고켐바이오": "141080.KQ",
    "지씨셀": "144510.KQ",
    "케어젠": "214370.KQ",
    "코미팜": "041960.KQ",
    "안랩": "053800.KQ", "안철수": "053800.KQ",
    "더존비즈온": "012510.KS",
    "카카오페이": "377300.KS",
    "다우데이타": "032190.KQ",
    "케이피엠테크": "042040.KQ",
    "카페24": "042000.KQ",
    "kg이니시스": "035600.KQ",
    "나이스정보통신": "03680s.KQ",
    "다날": "064260.KQ", "페이코인": "064260.KQ",
    "한국정보인증": "053300.KQ",
    "보안": "053300.KQ",
    "이수페타시스": "007660.KS", "이수": "007660.KS",
    "심텍": "222800.KQ",
    "대덕전자": "353200.KS",
    "해성디에스": "195870.KS",
    "패키지": "195870.KS",
    "네패스": "033640.KQ",
    "sfa반도체": "036540.KQ",
    "하나마이크론": "067310.KQ",
    "제우스": "079370.KQ",
    "주성엔지니어링": "036930.KQ",
    "아이에스동서": "010780.KS",
    "태영건설": "009410.KS",
    "gs건설": "006360.KS", "자이": "006360.KS",
    "dl이앤씨": "375500.KS", "대림산업": "375500.KS",
    "hdc현대산업개발": "294870.KS", "아이파크": "294870.KS",
    "계룡건설": "013580.KS",
    "금호건설": "002990.KS",
    "쌍용건설": "012650.KS",
    "한전KPS": "051600.KS",
    "한전기술": "052690.KS",
    "한국가스공사": "036460.KS", "가스공사": "036460.KS",
    "지역난방공사": "071320.KS",
    "강원랜드": "035250.KS", "카지노": "035250.KS",
    "gkl": "114090.KS",
    "파라": "034230.KQ",
    "한진": "005430.KS",
    "현대엘리베이터": "017800.KS", "엘리베이터": "017800.KS",
    "경동나비엔": "009450.KS", "보일러": "009450.KS",
    "신성이엔지": "011930.KS",
    "에스원": "012750.KS", "세콤": "012750.KS",
    "한샘": "009240.KS",
    "현대리바트": "079430.KS", "리바트": "079430.KS",
    "퍼시스": "016800.KS",
    "에이스침대": "003800.KQ",
    "지누스": "013890.KS",

    # ================================================================
    # 🇺🇸 미국 주식 (미장 핵심 200종목 - 야후 파이낸스 티커 규격)
    # ================================================================
    "애플": "AAPL", "apple": "AAPL",
    "테슬라": "TSLA", "tesla": "TSLA",
    "엔비디아": "NVDA", "nvidia": "NVDA", "엔비": "NVDA",
    "마이크로소프트": "MSFT", "microsoft": "MSFT", "마소": "MSFT",
    "구글": "GOOGL", "google": "GOOGL", "알파벳": "GOOGL",
    "아마존": "AMZN", "amazon": "AMZN",
    "메타": "META", "meta": "META", "페이스북": "META", "페북": "META",
    "버크셔서웨이": "BRK-B", "버크셔": "BRK-B", "워렌버핏": "BRK-B", "워런버핏": "BRK-B",
    "일라이릴리": "LLY", "릴리": "LLY", "비만치료제": "LLY",
    "브로드컴": "AVGO", "broadcom": "AVGO",
    "노보노디스크": "NVO", "노보": "NVO",
    "jp모건": "JPM", "제이피모간": "JPM", "jp모간": "JPM",
    "비자": "V", "visa": "V",
    "마스터카드": "MA", "mastercard": "MA",
    "엑손모빌": "XOM", "exxon": "XOM",
    "유나이티드헬스": "UNH", "unh": "UNH",
    "존슨앤드존슨": "JNJ", "존슨앤존슨": "JNJ", "jnj": "JNJ",
    "월마트": "WMT", "walmart": "WMT",
    "asml": "ASML", "에이디에스엠엘": "ASML",
    "오라클": "ORCL", "oracle": "ORCL",
    "코스트코": "COST", "costco": "COST",
    "p&g": "PG", "프록터앤갬블": "PG", "피앤지": "PG",
    "뱅크오브아메리카": "BAC", "boa": "BAC", "보아": "BAC",
    "넷플릭스": "NFLX", "netflix": "NFLX",
    "넷플": "NFLX",
    "amd": "AMD", "에이엠디": "AMD",
    "셰브론": "CVX", "chevron": "CVX",
    "넷앱": "NTAP",
    "시스코": "CSCO", "cisco": "CSCO",
    "어도비": "ADBE", "adobe": "ADBE",
    "세일즈포스": "CRM", "salesforce": "CRM",
    "티모바일": "TMUS", "tmobile": "TMUS",
    "나이키": "NKE", "nike": "NKE",
    "퀄컴": "QCOM", "qualcomm": "QCOM",
    "맥도날드": "MCD", "mcdonalds": "MCD", "맥날": "MCD",
    "코카콜라": "KO", "coke": "KO", "코카": "KO",
    "펩시": "PEP", "pepsico": "PEP", "펩시코": "PEP",
    "린데": "LIN",
    "웰스파고": "WFC",
    "인텔": "INTC", "intel": "INTC",
    "텍사스인스트루먼트": "TXN", "ti": "TXN",
    "버라이즌": "VZ", "verizon": "VZ",
    "암젠": "AMGN", "amgen": "AMGN",
    "디즈니": "DIS", "disney": "DIS",
    "씨티그룹": "C", "citigroup": "C", "씨티": "C",
    "필립모리스": "PM", "아이코스": "PM",
    "레이시온": "RTX", "rtx": "RTX",
    "ibm": "IBM", "아이비엠": "IBM",
    "모건스탠리": "MS",
    "골드만삭스": "GS", "goldmansachs": "GS",
    "허니웰": "HON",
    "보잉": "BA", "boeing": "BA",
    "스타벅스": "SBUX", "starbucks": "SBUX", "스벅": "SBUX",
    "인튜이트": "INTU",
    "블랙록": "BLK", "blackrock": "BLK",
    "캐터필러": "CAT", "caterpillar": "CAT",
    "화이자": "PFE", "pfizer": "PFE",
    "모더나": "MRNA", "moderna": "MRNA",
    "유니온퍼시픽": "UNP",
    "amc": "AMC",
    "지이": "GE", "제너럴일렉트릭": "GE", "ge": "GE",
    "at&t": "T", "에이티앤티": "T",
    "우버": "UBER", "uber": "UBER",
    "에어비앤비": "ABNB", "airbnb": "ABNB",
    "부킹홀딩스": "BKNG", "부킹닷컴": "BKNG",
    "스포티파이": "SPOT", "spotify": "SPOT",
    "팔란티어": "PLTR", "palantir": "PLTR", "반지의제왕": "PLTR",
    "쇼피파이": "SHOP", "shopify": "SHOP",
    "스퀘어": "SQ", "블록": "SQ", "block": "SQ",
    "코인베이스": "COIN", "coinbase": "COIN", "코인": "COIN",
    "로블록스": "RBLX", "roblox": "RBLX",
    "유니티": "U", "unity": "U",
    "스냅": "SNAP", "스냅챗": "SNAP",
    "핀터레스트": "PINS", "pinterest": "PINS",
    "이베이": "EBAY", "ebay": "EBAY",
    "이치": "ETSY",
    "치폴레": "CMG", "chipotle": "CMG",
    "줌": "ZM", "zoom": "ZM",
    "도큐사인": "DOCU",
    "트윌리오": "TWLO",
    "클라우드플레어": "NET", "cloudflare": "NET",
    "크라우드스트라이크": "CRWD", "crowdstrike": "CRWD",
    "데이터독": "DDOG", "datadog": "DDOG",
    "스노우플레이크": "SNOW", "snowflake": "SNOW",
    "몽고db": "MDB", "mongodb": "MDB",
    "지스케일러": "ZS",
    "옥타": "OKTA",
    "시놉시스": "SNPS",
    "케이던스": "CDNS",
    "암": "ARM", "arm홀딩스": "ARM",
    "마이크론": "MU", "micron": "MU", "마이크론테크놀로지": "MU",
    "어플라이드머티어리얼즈": "AMAT", "amat": "AMAT",
    "램리서치": "LRCX", "lamresearch": "LRCX",
    "asml홀딩": "ASML",
    "도쿄일렉트론": "TOELY",
    "엔페이즈": "ENPH", "엔페이즈에너지": "ENPH",
    "솔라에지": "SEDG",
    "퍼스트솔라": "FSLR",
    "넥스트에라": "NEE", "nextera": "NEE",
    "듀크에너지": "DUK",
    "남부전력": "SO",
    "델타항공": "DAL", "delta": "DAL",
    "아메리칸항공": "AAL",
    "유나이티드항공": "UAL",
    "사우스웨스트": "LUV",
    "카니발": "CCL", "크루즈": "CCL",
    "로얄캐리비안": "RCL",
    "노르웨이전크루즈": "NCLH",
    "헤르츠": "HTZ",
    "에이비스": "CAR",
    "페덱스": "FDX", "fedex": "FDX",
    "ups": "UPS", "유피에스": "UPS",
    "포드": "F", "ford": "F",
    "gm": "GM", "제너럴모터스": "GM", "지엠": "GM",
    "루시드": "LCID", "lucid": "LCID",
    "리비안": "RIVN", "rivian": "RIVN",
    "니오": "NIO", "nio": "NIO",
    "샤오펑": "XPEV",
    "리오토": "LI",
    "비야디": "BYDDY", "byd": "BYDDY",
    "토요타": "TM", "toyota": "TM",
    "혼다": "HMC",
    "페라리": "RACE", "ferrari": "RACE",
    "스텔란티스": "STLA",
    "모빌아이": "MBLY",
    "질로우": "Z",
    "레드핀": "RDFN",
    "위워크": "WEWKQ",
    "리얼티인컴": "O", "realtyincome": "O", "월배당": "O",
    "아메리칸타워": "AMT",
    "프롤로지스": "PLD",
    "디지털리얼티": "DLR",
    "에퀴닉스": "EQIX",
    "사이먼프로퍼티": "SPG",
    "웰타워": "WELL",
    "비치프로퍼티": "VICI",
    "에어비앤": "ABNB",
    "힐튼": "HLT",
    "메리어트": "MAR",
    "하얏트": "H",
    "윈리조트": "WYNN",
    "라스베이거스샌즈": "LVS", "샌즈": "LVS",
    " MGM리조트": "MGM",
    "3m": "MMM", "쓰리엠": "MMM",
    "제너럴일렉": "GE",
    "로크웰": "ROK",
    "이튼": "ETN",
    "에머슨": "EMR",
    "파카하니핀": "PH",
    "디어앤컴퍼니": "DE", "존디어": "DE",
    "쿠팡": "CPNG", "coupang": "CPNG",
    "알리바바": "BABA", "alibaba": "BABA",
    "징둥닷컴": "JD",
    "피두오두오": "PDD", "템구": "PDD", "temu": "PDD",
    "바이두": "BIDU",
    "텐센트": "TCEHY",
    "넷이즈": "NTES",
    "tsmc": "TSM", "대만반도체": "TSM",
    "ase홀딩": "ASX",
    "유나이티드마이크로": "UMC",
    "소니": "SONY", "sony": "SONY",
    "파나소닉": "PCRFY",
    "닌텐도": "NTDOY", "nintendo": "NTDOY",
    "스위치": "NTDOY",
    "머크": "MRK", "merck": "MRK",
    "애브비": "ABBV", "abbvie": "ABBV",
    "브리스톨마이어스": "BMY", "bms": "BMY",
    "아스트라제네카": "AZN", "az": "AZN",
    "사노피": "SNY",
    "글락소스미스크라인": "GSK", "gsk": "GSK",
    "다케다": "TAK",
    "길리어드": "GILD",
    "리제네론": "REGN",
    "바이오젠": "BIIB",
    "버텍스": "VRTX",
    "일루미나": "ILMN",
    "덱스콤": "DXCM",
    "인튜이티브서지컬": "ISRG", "다빈치": "ISRG",
    "메드트로닉": "MDT",
    "스트라이커": "SYK",
    "보스턴사이언티픽": "BSX",
    "에보트": "ABT", "애보트랩스": "ABT",
    "다나허": "DHR",
    "써모피셔": "TMO",
    "애질런트": "A",
    "워터스": "WAT",
    "몬스터베버리지": "MNST", "몬스터에너지": "MNST",
    "셀시우스": "CELH",
    "코노코필립스": "COP",
    "옥시덴탈": "OXY", "버핏형픽": "OXY",
    "슐럼버거": "SLB",
    "할리버튼": "HAL",
    "베이커휴즈": "BKR",
    "필립스66": "PSX",
    "마라톤페트롤리엄": "MPC",
    "발레로": "VLO"
}

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
def ranking(request: Request):
    # 주송이님이 깎아두신 1등~10등 추출 알고리즘 원본 그대로 가동!
    kr_ranks = [{"rank": i+1, "ticker": t, "name": TICKER_CACHE[t]["name"], "score": TICKER_CACHE[t]["score"], "color": TICKER_CACHE[t]["color"]} for i, (t, _) in enumerate(SEARCH_COUNT_KR.most_common(10)) if t in TICKER_CACHE]
    us_ranks = [{"rank": i+1, "ticker": t, "name": TICKER_CACHE[t]["name"], "score": TICKER_CACHE[t]["score"], "color": TICKER_CACHE[t]["color"]} for i, (t, _) in enumerate(SEARCH_COUNT_US.most_common(10)) if t in TICKER_CACHE]
    
    # /ranking 주소로 들어오면 무조건 ranking.html을 보여줍니다!
    return templates.TemplateResponse(
        request=request, 
        name="ranking.html", 
        context={
            "request": request, 
            "kr_rankings": kr_ranks, 
            "us_rankings": us_ranks
        }
    )

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