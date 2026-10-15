"""
신규 권역 성장 기회 — 문제 구간 탐색 대시보드 (7주차)

탭 3개
- 📊 개요 : KPI 카드 3개 + 규칙 문장(지금 숫자 읽기) + 6주차 차트 3장
- 🔍 탐색 : 집단 비교(퍼널 · 단계 전환율) + 드릴다운(언제부터 · 무엇 때문에)
- ✅ 액션 : 액션 카드 2장 + 측정 KPI의 현재 값
"""
import sqlite3

import pandas as pd
import plotly.express as px
import streamlit as st

st.set_page_config(page_title="신규 권역 성장 기회 대시보드", layout="wide")
st.title("신규 권역 성장 기회 대시보드")
st.caption("가입월 · 가입 채널 · 플랫폼별 | 2025.09 ~ 2026.07 가입자")

# 색: 문제 집단만 진한 남색, 나머지는 회색 (3일차 디자인 규칙)
ACCENT, GRAY, DARK_GRAY = "#1F3A5F", "#BDBDBD", "#8C8C8C"
COLOR_MAP = {
    "INSTA_첫주문쿠폰": ACCENT, "organic": DARK_GRAY, "NAVER_검색광고": "#A6A6A6",
    "GOOGLE_앱설치": GRAY, "친구초대": "#DADADA", "Android": DARK_GRAY, "iOS": GRAY,
}
LINE_SEQ = [ACCENT, DARK_GRAY, "#A6A6A6", GRAY, "#DADADA"]   # 드릴다운 선 차트용(밝기로 구분)

# ------------------------------------------------------------
# 0. 필요한 데이터만 추출 — 쓸 테이블과 컬럼만 메모리 DB에 올리고, 정제 테이블을 처음 한 번만 만듦
# ------------------------------------------------------------
DATA_DIR = "data"                          # 원본 CSV를 넣어 둔 폴더
NEEDED = {                                 # 이번 대시보드에 필요한 테이블과 컬럼 (쿼리에 쓰는 것만)
    "app_events": ["event_datetime", "customer_id", "session_id", "event_name",
                   "platform", "traffic_source", "campaign_name"],
    "orders": ["customer_id", "order_datetime"],
}

@st.cache_resource
def get_db():                              # 필요한 컬럼만 메모리 DB에 올리고, 정제 테이블 events·odr을 생성(처음 한 번)
    con = sqlite3.connect(":memory:", check_same_thread=False)
    for name, cols in NEEDED.items():
        # dtype=str: 고객 ID의 앞자리 0(0000002)이 숫자로 바뀌지 않게 글자로 읽음
        pd.read_csv(f"{DATA_DIR}/{name}.csv", usecols=cols, dtype=str).to_sql(name, con, index=False)
    # 5주차 제외 규칙: 테스트 계정(T로 시작) 제외 · 이벤트 100건 이상인 비정상 세션 제외
    con.execute("""
        CREATE TABLE events AS
        SELECT *
          FROM app_events
         WHERE customer_id NOT LIKE 'T%'
           AND session_id NOT IN (SELECT session_id FROM app_events
                                   GROUP BY session_id HAVING COUNT(*) >= 100)
    """)
    con.execute("CREATE TABLE odr AS SELECT * FROM orders WHERE customer_id NOT LIKE 'T%'")
    # 고객별로 묶는 집계가 빨라지도록 customer_id에 인덱스를 붙임
    con.execute("CREATE INDEX idx_events_customer ON events(customer_id)")
    con.execute("CREATE INDEX idx_odr_customer ON odr(customer_id)")
    return con

# ------------------------------------------------------------
# 1. 데이터 준비 — 정제된 테이블을 SQL로 집계 (비율이 아니라 분자 · 분모 건수만)
# ------------------------------------------------------------
@st.cache_data
def query(sql):                            # SQL을 실행해 표로 돌려줌
    return pd.read_sql(sql, get_db())

# 고객별 가입일 · 가입 채널 · 플랫폼 (가입 이벤트 기준) - 두 쿼리 모두 사용
SQL_SIGNUP = """
su AS (
    SELECT customer_id,
           DATE(MIN(event_datetime))                    AS 가입일,
           MIN(COALESCE(campaign_name, traffic_source)) AS 가입채널,
           MIN(platform)                                AS 플랫폼
      FROM events
     WHERE event_name = 'sign_up'
     GROUP BY customer_id
)
"""

# 가입월 × 가입 채널 × 플랫폼별 가입 후 30일 퍼널 (5주차 Q1 · Q3)
SQL_SIGNUP_FUNNEL = f"""
WITH {SQL_SIGNUP},
ev AS (                                     -- 가입 후 30일 안의 행동
    SELECT DISTINCT e.customer_id, e.event_name
      FROM events e
      JOIN su ON e.customer_id = su.customer_id
     WHERE julianday(DATE(e.event_datetime)) - julianday(su.가입일) BETWEEN 0 AND 30
),
fo AS (                                     -- 고객별 첫 주문일
    SELECT customer_id, DATE(MIN(order_datetime)) AS 첫주문일
      FROM odr
     GROUP BY customer_id
)
SELECT strftime('%Y-%m', su.가입일) AS 가입월,
       su.가입채널,
       su.플랫폼,
       COUNT(DISTINCT su.customer_id)                                                         AS 가입자,
       COUNT(DISTINCT CASE WHEN ev.event_name = 'view_restaurant' THEN su.customer_id END)    AS 식당조회,
       COUNT(DISTINCT CASE WHEN ev.event_name = 'add_to_cart'     THEN su.customer_id END)    AS 장바구니,
       COUNT(DISTINCT CASE WHEN ev.event_name = 'begin_checkout'  THEN su.customer_id END)    AS 결제시작,
       COUNT(DISTINCT CASE WHEN julianday(fo.첫주문일) - julianday(su.가입일) <= 30
                           THEN su.customer_id END)                                           AS 첫주문30일
  FROM su
  LEFT JOIN ev ON su.customer_id = ev.customer_id
  LEFT JOIN fo ON su.customer_id = fo.customer_id
 WHERE su.가입일 <= '2026-07-31'            -- 30일을 다 볼 수 있는 가입자만
 GROUP BY 1, 2, 3
 ORDER BY 1, 2, 3
"""

# 가입월 × 가입 채널 × 플랫폼별 30일 재주문 (5주차 Q2, 분모가 첫 주문 고객이라 표를 따로 만듦)
SQL_REORDER = f"""
WITH {SQL_SIGNUP},
seq AS (
    SELECT customer_id, order_datetime,
           ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY order_datetime) AS 순번,
           LEAD(order_datetime) OVER (PARTITION BY customer_id ORDER BY order_datetime) AS 다음주문
      FROM odr
)
SELECT strftime('%Y-%m', su.가입일) AS 가입월,
       su.가입채널,
       su.플랫폼,
       COUNT(*)                                                                          AS 첫주문고객,
       SUM(CASE WHEN julianday(DATE(seq.다음주문)) - julianday(DATE(seq.order_datetime)) <= 30
                THEN 1 ELSE 0 END)                                                       AS 재주문30일
  FROM seq
  JOIN su ON seq.customer_id = su.customer_id
 WHERE seq.순번 = 1
   AND seq.order_datetime < '2026-08-01'    -- 30일을 다 볼 수 있는 첫 주문만
 GROUP BY 1, 2, 3
 ORDER BY 1, 2, 3
"""

@st.cache_data
def load_data():
    return query(SQL_SIGNUP_FUNNEL), query(SQL_REORDER)

df, rd = load_data()                       # df: 가입 후 30일 퍼널 / rd: 30일 재주문

AI_NOTES = {
    "전체": "전체 가입자 2,774명의 30일 첫 주문 전환율은 69.9%, 가장 낮은 단계는 식당 조회 → 장바구니 84.1%입니다. 가입월별로 보면 2025-09~2025-12 가입월은 74.3~76.6%였지만 2026-01 가입월부터 63.5~71.7%로 낮아졌고, 같은 기간 INSTA_첫주문쿠폰을 뺀 나머지는 71.9~78.3%로 이전 수준을 유지했습니다. 전체 하락은 2026-01 가입월부터 유입된 INSTA_첫주문쿠폰 가입자의 비중 변화와 함께 나타난 것으로 보이며, 채널별 유입 조건은 이 데이터로 확인할 수 없어 추가 확인이 필요합니다.",
    "Android": "Android 가입자 1,502명의 30일 첫 주문 전환율은 69.2%로 전체 69.9%와 0.7%p 차이이고, 가장 낮은 단계는 식당 조회 → 장바구니 83.8%입니다. 단계별 전환율을 iOS와 비교하면 가입 → 식당 조회 96.1% 대 96.1%, 식당 조회 → 장바구니 83.8% 대 84.5%, 장바구니 → 결제 시작 87.4% 대 88.6%, 결제 시작 → 30일 첫 주문 98.4% 대 98.1%로 모든 단계에서 차이가 1.2%p 이내입니다. 플랫폼은 전환율 차이를 가르는 축이 아닌 것으로 보이며, 문제는 다른 축에서 찾아야 할 것으로 확인이 필요합니다.",
    "iOS": "iOS 가입자 1,272명의 30일 첫 주문 전환율은 70.7%로 전체 69.9%보다 0.8%p 높고, 30일 재주문율은 68.2%로 Android 66.6%보다 1.6%p 높습니다. 가장 낮은 단계는 식당 조회 → 장바구니 84.5%로 Android 83.8%와 거의 같습니다. 플랫폼 간 차이는 모든 단계에서 1.2%p 이내여서 의미 있는 차이로 보기 어려우며, 집단을 가입 채널로 나눠 보는 쪽이 적절해 보입니다.",
    "organic": "organic 가입자 847명의 30일 첫 주문 전환율은 75.2%로 전체 69.9%보다 5.3%p 높고, 가장 낮은 단계인 식당 조회 → 장바구니도 88.6%로 전체 84.1%를 웃돕니다. 30일 재주문율은 73.5%로 전체 67.4%보다 6.1%p 높습니다. 광고 없이 들어온 가입자가 첫 주문과 재주문 모두에서 가장 안정적인 집단으로 보이며, 유입 경로별 고객 특성은 이 데이터로 확인할 수 없습니다.",
    "INSTA_첫주문쿠폰": "INSTA_첫주문쿠폰 가입자 739명의 30일 첫 주문 전환율은 55.6%로 다른 네 채널의 73.6~76.4%보다 18.0%p 이상 낮고, 가장 낮은 단계는 식당 조회 → 장바구니 72.4%로 다른 채널의 87.1~89.5%와 14.7%p 이상 벌어집니다. 이 채널은 2026-01 가입월에 처음 나타나 이후 매월 전체 가입자의 32.0~36.0%를 차지했고, 30일 재주문율도 44.5%로 다른 채널의 72.6~77.3%보다 낮습니다. 식당을 본 뒤 장바구니로 넘어가지 못하는 구간에 문제가 몰려 있는 것으로 보이나, 이 데이터에는 광고 소재와 쿠폰 조건, 앱 화면 정보가 없어 원인은 별도 확인이 필요합니다.",
    "NAVER_검색광고": "NAVER_검색광고 가입자 517명의 30일 첫 주문 전환율은 76.4%로 여덟 대상 가운데 가장 높고, 전체 69.9%보다 6.5%p 높습니다. 가장 낮은 단계인 식당 조회 → 장바구니는 87.7%, 30일 재주문율은 72.6%로 둘 다 전체 평균을 웃돕니다. 검색으로 들어온 가입자가 첫 주문까지 비교적 잘 이어지는 것으로 보이며, 검색어나 광고 문구는 이 데이터로 확인할 수 없습니다.",
    "GOOGLE_앱설치": "GOOGLE_앱설치 가입자 398명의 30일 첫 주문 전환율은 73.6%로 전체 69.9%보다 3.7%p 높고, 식당 조회 → 장바구니는 89.5%로 다섯 채널 중 가장 높습니다. 다른 채널과 달리 가장 낮은 단계가 장바구니 → 결제 시작 88.0%이고, 30일 재주문율은 72.7%로 전체 67.4%를 웃돕니다. 다른 채널에서 문제가 되는 식당 조회 → 장바구니 구간은 이 집단에서 오히려 가장 강한 단계로 보이며, 결제 시작 직전 구간은 추가 확인이 필요합니다.",
    "친구초대": "친구초대 가입자는 273명으로 300명 미만의 작은 집단이라 값이 흔들릴 수 있다는 점을 먼저 밝힙니다. 30일 첫 주문 전환율은 74.4%로 전체 69.9%보다 4.5%p 높고, 30일 재주문율은 77.3%로 여덟 대상 가운데 가장 높습니다. 이미 쓰고 있는 고객의 소개로 들어온 가입자가 재주문까지 가장 잘 이어지는 것으로 보이나, 집단 크기가 작아 추세는 몇 달 더 지켜볼 필요가 있습니다.",
}
AI_SOURCE = "🤖 AI가 집계표(가입월 × 가입 채널 × 플랫폼)를 읽고 미리 만든 해설 · 전체 기간 기준 · 필터와 무관"

# ------------------------------------------------------------
# 2. 사이드바 필터 — 두 표에 같은 조건을 적용
# ------------------------------------------------------------
SMALL = 100                                # 이보다 가입자가 적은 집단은 "작은 집단"

if "reset" not in st.session_state:
    st.session_state.reset = 0

def reset_filters():                       # 번호가 바뀌면 위젯이 처음 상태로 새로 만들어짐
    st.session_state.reset += 1

n = st.session_state.reset
months = sorted(df["가입월"].unique())
channels = sorted(df["가입채널"].unique())
platforms = sorted(df["플랫폼"].unique())

st.sidebar.header("필터")
start, end = st.sidebar.select_slider("가입월", options=months,
                                      value=(months[0], months[-1]), key=f"기간_{n}")
sel_channels = st.sidebar.multiselect("가입 채널", channels, default=channels, key=f"채널_{n}")
sel_platforms = st.sidebar.multiselect("플랫폼", platforms, default=platforms, key=f"플랫폼_{n}")
with st.sidebar.expander("고급 설정"):
    base_start, base_end = st.select_slider(
        "평소 범위 기준 기간", options=months, value=(months[0], months[3]), key=f"기준_{n}",
        help="문제가 없던 기간을 고르세요. 이 기간의 월별 값 범위를 '평소 범위'로 씁니다.")
    hide_small = st.checkbox(f"가입자 {SMALL}명 미만 집단 제외 (집단 비교 · 드릴다운)", key=f"작은집단_{n}")
st.sidebar.button("필터 초기화", on_click=reset_filters)

# 집단 조건(가입 채널 · 플랫폼)만 적용한 데이터 g · rg, 기간까지 적용한 데이터 f · rf
g = df[df["가입채널"].isin(sel_channels) & df["플랫폼"].isin(sel_platforms)]
f = g[(g["가입월"] >= start) & (g["가입월"] <= end)]
rg = rd[rd["가입채널"].isin(sel_channels) & rd["플랫폼"].isin(sel_platforms)]
rf = rg[(rg["가입월"] >= start) & (rg["가입월"] <= end)]

def label(selected, all_values):           # 조건 줄에 쓸 말: 모두 고르면 "전체"
    if len(selected) == len(all_values):
        return "전체"
    return ", ".join(selected) if selected else "선택 없음"

period = "전체" if (start, end) == (months[0], months[-1]) else f"{start} ~ {end}"
st.caption(f"🔎 보고 있는 조건: 가입월 {period} · 가입 채널 {label(sel_channels, channels)} · "
           f"플랫폼 {label(sel_platforms, platforms)}")

if f.empty:
    st.warning("선택한 조건에 해당하는 데이터가 없습니다. 필터를 바꿔 주세요.")
    st.stop()

def rate(a, b):
    return a / b * 100 if b else 0

# ------------------------------------------------------------
# 3. 화면 — 탭 3개
# ------------------------------------------------------------
tab_overview, tab_explore, tab_action = st.tabs(["📊 개요", "🔍 탐색", "✅ 액션"])

# ===== [블록 A] 개요 · KPI 카드 =====
with tab_overview:
    st.caption("이 탭에서 볼 수 있는 것: 핵심 숫자와 그 숫자를 읽는 법, 6주차 리포트의 차트 3장 (필터 적용)")

    # 3-1. KPI 카드 — 5주차 지표 3개
    t = f[["가입자", "식당조회", "장바구니", "첫주문30일"]].sum()
    tr = rf[["첫주문고객", "재주문30일"]].sum()
    c1, c2, c3 = st.columns(3)
    c1.metric("30일 첫 주문 전환율", f"{rate(t['첫주문30일'], t['가입자']):.1f}%")
    c2.metric("식당 조회 → 장바구니 전환율", f"{rate(t['장바구니'], t['식당조회']):.1f}%")
    c3.metric("30일 재주문율", f"{rate(tr['재주문30일'], tr['첫주문고객']):.1f}%")

    # 3-2. 규칙 문장 — 최근 3개월 값과 기준 기간의 월별 범위를 비교
    RULE_METRICS = [
        ("30일 첫 주문 전환율", "첫주문30일", "가입자"),
        ("식당 조회 → 장바구니 전환율", "장바구니", "식당조회"),
    ]

    sel_months = [m for m in months if start <= m <= end]
    last3 = sel_months[-3:]
    base_rows = g[(g["가입월"] >= base_start) & (g["가입월"] <= base_end)]

    def rule_sentence(name, num, den):
        if len(sel_months) < 3:
            return f"**{name}** — 비교하려면 선택 기간을 3개월 이상 골라 주세요"

        cur = f[f["가입월"].isin(last3)][[num, den]].sum()
        if cur[den] == 0:
            return f"**{name}** — 선택한 조건의 최근 3개월에 분모가 되는 데이터가 없습니다"
        value = cur[num] / cur[den] * 100

        monthly = base_rows.groupby("가입월")[[num, den]].sum()
        monthly = monthly[monthly[den] > 0]          # 분모가 0인 달은 평소 범위에서 제외
        if len(monthly) < 3:
            return f"**{name}** — 기준 기간을 이 집단의 데이터가 있는 시기로 옮겨 주세요"

        series = monthly[num] / monthly[den] * 100
        lo, hi = series.min(), series.max()
        head = f"{last3[0]} 가입월부터 3개월 {name}은 {value:.1f}%로, 평소 범위({lo:.1f}–{hi:.1f}%)"
        if value < lo:
            return f"{head}보다 {lo - value:.1f}%p 낮습니다"
        if value > hi:
            return f"{head}보다 {value - hi:.1f}%p 높습니다"
        return f"{head} 안에 있습니다"

    with st.container(border=True):
        st.markdown("**📏 지금 숫자 읽기**")
        for name, num, den in RULE_METRICS:
            st.markdown(f"- {rule_sentence(name, num, den)}")
        st.caption(f"📏 자동 계산 · 평소 범위 기준 기간 {base_start} ~ {base_end} (월별 값)")
        with st.expander("🤖 AI 해설 · 전체", expanded=False):
            st.markdown(AI_NOTES.get("전체", "아직 해설이 없습니다."))
            st.caption(AI_SOURCE)
# ===== [블록 A] 끝 =====

with tab_overview:
    st.divider()

    # 3-3. 차트 - 6주차 차트 ① 문제 · ② 원인 · ③ 제안
    left, right = st.columns(2)

    # ① 문제: 가입월별 30일 첫 주문 전환율
    m = f.groupby("가입월")[["가입자", "첫주문30일"]].sum().reset_index()
    m["첫주문전환율"] = (m["첫주문30일"] / m["가입자"] * 100).round(1)
    fig1 = px.line(m, x="가입월", y="첫주문전환율", markers=True, hover_data=["가입자"],
                   labels={"가입월": "가입월", "첫주문전환율": "30일 첫 주문 전환율(%)", "가입자": "가입자(명)"},
                   title="① 가입월별 30일 첫 주문 전환율",
                   color_discrete_sequence=[ACCENT])
    fig1.update_layout(xaxis_title="")
    fig1.update_xaxes(type="category")       # 가입월(2025-09)을 날짜가 아니라 글자 그대로 표시
    left.plotly_chart(fig1, width="stretch")

    # ② 원인: 가입 채널별 식당 조회 → 장바구니 전환율
    ch = f.groupby("가입채널")[["식당조회", "장바구니"]].sum().reset_index()
    ch["장바구니전환율"] = (ch["장바구니"] / ch["식당조회"] * 100).round(1)
    ch = ch.sort_values("장바구니전환율")
    fig2 = px.bar(ch, x="장바구니전환율", y="가입채널", orientation="h", text_auto=".1f",
                  hover_data=["식당조회"],
                  labels={"장바구니전환율": "식당 조회 → 장바구니 전환율(%)", "가입채널": "가입 채널",
                          "식당조회": "식당 조회 가입자(명)"},
                  title="② 가입 채널별 식당 조회 → 장바구니 전환율")
    fig2.update_traces(marker_color=[COLOR_MAP.get(c, GRAY) for c in ch["가입채널"]])
    fig2.update_xaxes(range=[0, ch["장바구니전환율"].max() * 1.2])
    fig2.update_layout(yaxis_title="")
    right.plotly_chart(fig2, width="stretch")

    # ③ 제안: 가입 채널별 30일 재주문율
    rc = rf.groupby("가입채널")[["첫주문고객", "재주문30일"]].sum().reset_index()
    rc["재주문율"] = (rc["재주문30일"] / rc["첫주문고객"] * 100).round(1)
    rc = rc.sort_values("재주문율")
    fig3 = px.bar(rc, x="재주문율", y="가입채널", orientation="h", text_auto=".1f",
                  hover_data=["첫주문고객"],
                  labels={"재주문율": "30일 재주문율(%)", "가입채널": "가입 채널", "첫주문고객": "첫 주문 고객(명)"},
                  title="③ 가입 채널별 30일 재주문율")
    fig3.update_traces(marker_color=[COLOR_MAP.get(c, GRAY) for c in rc["가입채널"]])
    fig3.update_xaxes(range=[0, rc["재주문율"].max() * 1.2])
    fig3.update_layout(yaxis_title="")
    st.plotly_chart(fig3, width="stretch")

    # AI 해설을 만들 때 올릴 표 (필터와 관계없이 전체)
    with st.expander("📥 AI 해설용 데이터 내려받기"):
        st.download_button("가입 후 30일 퍼널 (가입월 × 가입 채널 × 플랫폼)",
                           df.to_csv(index=False).encode("utf-8-sig"), "가입월_채널_플랫폼_퍼널.csv")
        st.download_button("30일 재주문 (가입월 × 가입 채널 × 플랫폼)",
                           rd.to_csv(index=False).encode("utf-8-sig"), "가입월_채널_플랫폼_재주문.csv")

# ===== [블록 B] 탐색 — 집단 비교 · 드릴다운 =====
with tab_explore:
    st.caption("이 탭에서 볼 수 있는 것: 집단 비교와 드릴다운 — 어디서, 언제부터인가")

    STAGES = ["가입자", "식당조회", "장바구니", "결제시작", "첫주문30일"]
    STAGE_LABEL = {"가입자": "가입자", "식당조회": "식당 조회", "장바구니": "장바구니",
                   "결제시작": "결제 시작", "첫주문30일": "30일 첫 주문"}

    # ---------- 집단 비교 ----------
    st.subheader("집단 비교 — 어디서 벌어지는가")
    axis = st.radio("비교 기준", ["가입채널", "플랫폼"], horizontal=True, key="비교기준")

    grp = f.groupby(axis)[STAGES].sum().reset_index()

    if hide_small:
        dropped = grp[grp["가입자"] < SMALL][axis].tolist()
        grp = grp[grp["가입자"] >= SMALL]
        if dropped:
            st.caption("제외한 집단: " + ", ".join(dropped) + f" (가입자 {SMALL}명 미만)")

    if grp.empty:
        st.info(f"가입자 {SMALL}명 이상인 집단이 없습니다. 기간을 넓히거나 작은 집단 제외를 꺼 주세요.")
    else:
        col_l, col_r = st.columns(2)

        # 왼쪽: 누적 전환율(가입자 대비 %) 퍼널
        cum_rows = []
        for _, row in grp.iterrows():
            for s in STAGES:
                cum_rows.append({
                    axis: row[axis],
                    "단계": STAGE_LABEL[s],
                    "누적전환율": round(row[s] / row["가입자"] * 100, 1) if row["가입자"] else 0.0,
                    "사람수": int(row[s]),
                })
        cum = pd.DataFrame(cum_rows)
        fig_funnel = px.funnel(cum, x="누적전환율", y="단계", color=axis,
                               hover_data=["사람수"],
                               labels={"누적전환율": "누적 전환율(가입자 대비 %)", "단계": "단계",
                                       "사람수": "사람 수(명)", axis: axis},
                               color_discrete_map=COLOR_MAP,
                               title=f"{axis}별 누적 전환율 (가입자 = 100%)")
        fig_funnel.update_layout(yaxis_title="", legend_title_text=axis)
        col_l.plotly_chart(fig_funnel, width="stretch")

        # 오른쪽: 단계 전환율(직전 단계 대비 %)
        step_rows = []
        for _, row in grp.iterrows():
            for prev, cur in zip(STAGES[:-1], STAGES[1:]):
                step_rows.append({
                    axis: row[axis],
                    "단계": f"{STAGE_LABEL[prev]} → {STAGE_LABEL[cur]}",
                    "단계전환율": round(row[cur] / row[prev] * 100, 1) if row[prev] else None,
                    "직전사람수": int(row[prev]),
                })
        step = pd.DataFrame(step_rows)
        fig_step = px.bar(step, x="단계", y="단계전환율", color=axis, barmode="group",
                          text_auto=".1f", hover_data=["직전사람수"],
                          labels={"단계": "단계", "단계전환율": "단계 전환율(%)",
                                  "직전사람수": "직전 단계 사람 수(명)", axis: axis},
                          color_discrete_map=COLOR_MAP,
                          title=f"{axis}별 단계 전환율 (직전 단계 대비)")
        fig_step.update_layout(xaxis_title="", legend_title_text=axis)
        fig_step.update_yaxes(range=[0, 110])
        col_r.plotly_chart(fig_step, width="stretch")

        shaky = grp[grp["가입자"] < SMALL][axis].tolist()
        if shaky:
            st.caption("⚠️ " + ", ".join(shaky) + f"는 가입자가 {SMALL}명 미만이라 값이 크게 흔들릴 수 있습니다.")

    st.divider()

    # ---------- 드릴다운 ----------
    st.subheader("드릴다운 — 언제부터, 무엇 때문일까")

    other_axis = "플랫폼" if axis == "가입채널" else "가입채널"
    STEP_OPTIONS = {
        "가입 → 30일 첫 주문": ("첫주문30일", "가입자"),
        "가입 → 식당조회": ("식당조회", "가입자"),
        "식당조회 → 장바구니": ("장바구니", "식당조회"),
        "장바구니 → 결제시작": ("결제시작", "장바구니"),
        "결제시작 → 30일 첫 주문": ("첫주문30일", "결제시작"),
    }

    candidates = sorted(grp[axis].unique()) if not grp.empty else []
    if not candidates:
        st.info("자세히 볼 집단이 없습니다. 필터를 조정해 주세요.")
    else:
        sb_l, sb_r = st.columns(2)
        target = sb_l.selectbox("자세히 볼 집단", candidates, key="드릴집단")
        step_name = sb_r.selectbox("단계", list(STEP_OPTIONS), key="드릴단계")
        num, den = STEP_OPTIONS[step_name]

        # 차트 ① 고른 집단을 다른 축으로 쪼개서 가입월별 전환율
        sub = f[f[axis] == target]
        line = sub.groupby(["가입월", other_axis])[[num, den]].sum().reset_index()
        line["전환율"] = (line[num] / line[den] * 100).where(line[den] > 0).round(1)  # 분모 0인 달은 빈 값
        fig_d1 = px.line(line, x="가입월", y="전환율", color=other_axis, markers=True,
                         hover_data={den: True, num: True},
                         labels={"가입월": "가입월", "전환율": f"{step_name} 전환율(%)",
                                 other_axis: other_axis, den: f"{STAGE_LABEL[den]}(명)",
                                 num: f"{STAGE_LABEL[num]}(명)"},
                         color_discrete_sequence=LINE_SEQ,
                         title=f"① {target}의 가입월별 {step_name} 전환율 — {other_axis}별로 쪼개 보기")
        fig_d1.update_layout(xaxis_title="", legend_title_text=other_axis)
        fig_d1.update_xaxes(type="category")
        st.plotly_chart(fig_d1, width="stretch")
        st.caption("모든 갈래가 함께 움직였다면, 그 축은 원인이 아닙니다.")

        # 차트 ② 가입월별 가입자 수 — 고른 집단 vs 그 외
        mix = f.groupby(["가입월", axis])["가입자"].sum().reset_index()
        mix["구분"] = mix[axis].where(mix[axis] == target, "그 외")
        mix = mix.groupby(["가입월", "구분"])["가입자"].sum().reset_index()
        fig_d2 = px.bar(mix, x="가입월", y="가입자", color="구분", barmode="stack",
                        labels={"가입월": "가입월", "가입자": "가입자(명)", "구분": "구분"},
                        color_discrete_map={target: ACCENT, "그 외": GRAY},
                        category_orders={"구분": [target, "그 외"]},
                        title=f"② 가입월별 가입자 구성 — {target} vs 그 외")
        fig_d2.update_layout(xaxis_title="", legend_title_text="")
        fig_d2.update_xaxes(type="category")
        st.plotly_chart(fig_d2, width="stretch")
        st.caption("전체 전환율이 움직인 시점에 이 집단의 비중이 함께 바뀌었다면 구성 변화가 원인 후보입니다. "
                   "함께 움직였다고 원인이 확정되지는 않습니다.")

        with st.expander(f"🤖 AI 해설 · {target}", expanded=False):
            st.markdown(AI_NOTES.get(target, "이 집단의 해설은 아직 없습니다."))
            st.caption(AI_SOURCE)
# ===== [블록 B] 끝 =====

# ===== [블록 C] 액션 =====
with tab_action:
    st.caption("측정 KPI의 현재 값은 선택한 기간의 마지막 3개월로 계산합니다")

    act_months = [m for m in months if start <= m <= end][-3:]
    TARGET = "INSTA_첫주문쿠폰"

    def act_rate(table, num, den):
        """사이드바의 가입월 기간만 적용(가입 채널 · 플랫폼 필터는 무시)하고, 마지막 3개월로 계산"""
        rows = table[(table["가입채널"] == TARGET) & (table["가입월"].isin(act_months))]
        s = rows[[num, den]].sum()
        if rows.empty or s[den] == 0:
            return "데이터 없음"
        return f"{s[num] / s[den] * 100:.1f}%"

    card_l, card_r = st.columns(2)

    with card_l:
        with st.container(border=True):
            st.markdown("""**카드 1 · INSTA_첫주문쿠폰 식당 조회 → 장바구니 전환율**

- **문제**: INSTA_첫주문쿠폰으로 들어온 가입자의 식당 조회 → 장바구니 전환율이 72.4%로, 다른 네 채널(87.1~89.5%)보다 14.7%p 이상 낮습니다.
- **근거**: 탐색 탭 집단 비교에서 이 채널만 이 단계가 꺾이고, 가입 → 식당 조회 95.3%와 결제 시작 → 첫 주문 98.3%는 다른 채널과 비슷합니다. 비교 기준을 플랫폼으로 바꾸면 모든 단계 차이가 1.2%p 이내라 플랫폼은 원인이 아닙니다.
- **성격**: 유입 이후 전환 구간의 문제입니다. 식당을 보기까지는 잘 오지만 담기로 넘어가지 못합니다.
- **액션**: 이 채널 유입 고객이 본 식당의 최소 주문 금액 · 배달비와 쿠폰 적용 조건이 조회 화면에서 어떻게 보이는지 확인하고, 랜딩을 쿠폰 사용 가능 식당으로 좁혀 A/B 테스트합니다.
- **우선순위**: 1순위. 전체 가입자의 32~36%를 차지하는 집단이라 개선 효과가 가장 큽니다.
""")
            st.metric("INSTA 식당 조회 → 장바구니 전환율", act_rate(df, "장바구니", "식당조회"))
            st.caption("대시보드에서: 탐색 탭 → 비교 기준 '가입채널' → 드릴다운 집단 'INSTA_첫주문쿠폰', "
                       "단계 '식당조회 → 장바구니'. 기간 전체 71.7% · 가입월 끝을 2026-04로 하면 73.2%")

    with card_r:
        with st.container(border=True):
            st.markdown("""**카드 2 · INSTA_첫주문쿠폰 30일 재주문율**

- **문제**: 첫 주문까지 온 INSTA_첫주문쿠폰 고객의 30일 재주문율이 44.5%로, 다른 네 채널(72.6~77.3%)보다 28.1%p 이상 낮습니다.
- **근거**: 개요 탭 차트 ③에서 이 채널만 아래로 떨어져 있습니다. 첫 주문 자체는 결제 시작 → 첫 주문 98.3%로 막히지 않으므로, 주문 경험이 아니라 두 번째 주문으로 이어지는 구간의 문제입니다.
- **성격**: 유입 이후 잔존 구간의 문제입니다. 첫 주문 쿠폰이 사라진 뒤 다시 주문할 이유가 남지 않은 것으로 보입니다.
- **액션**: 첫 주문 완료 후 7일 이내에 재주문 쿠폰을 보내는 안을 이 채널 유입 고객에게만 먼저 적용하고, 다음 분기 재주문율을 같은 기준으로 다시 측정합니다.
- **우선순위**: 2순위. 분모가 첫 주문 고객이라 카드 1보다 대상이 작지만, 카드 1이 개선되면 대상이 함께 늘어납니다.
""")
            st.metric("INSTA 30일 재주문율", act_rate(rd, "재주문30일", "첫주문고객"))
            st.caption("대시보드에서: 개요 탭 차트 ③ 가입 채널별 30일 재주문율. "
                       "기간 전체 40.9% · 가입월 끝을 2026-04로 하면 48.4%")

    st.caption("두 카드의 측정 KPI는 사이드바의 가입월 기간만 따릅니다 (가입 채널 · 플랫폼 필터는 적용하지 않습니다).")
