import os
import json
import time
import requests
import pandas as pd
from datetime import timedelta

SOURCE_URL = (
    "https://raw.githubusercontent.com/greatsong/"
    "my-data-log/refs/heads/main/data/kobis_daily_log.csv"
)

OUTPUT_FILE = "kobis_movie_summary.csv"
CACHE_FILE = "movie_metadata.json"

API_URL = (
    "https://www.kobis.or.kr/kobisopenapi/"
    "webservice/rest/movie/searchMovieInfo.json"
)

API_KEY = os.environ.get("KOBIS_API_KEY", "")

COLUMNS = [
    "movieCd", "movieNm", "openDt", "genre", "nation",
    "first_scrn", "first_show", "first_date", "peak",
    "first_week_audi", "total_audi", "days_in_top10"
]


def load_cache():
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def get_movie_info(movie_cd, cache):
    movie_cd = str(movie_cd)

    if movie_cd in cache:
        return cache[movie_cd]

    if not API_KEY:
        raise ValueError(
            "GitHub Secrets에 KOBIS_API_KEY를 등록해야 합니다."
        )

    response = requests.get(
        API_URL,
        params={"key": API_KEY, "movieCd": movie_cd},
        timeout=30
    )
    response.raise_for_status()
    result = response.json()

    if "faultInfo" in result:
        raise RuntimeError(
            f"KOBIS API 오류: {result['faultInfo']}"
        )

    info = result.get("movieInfoResult", {}).get("movieInfo")

    if not info:
        return {}

    metadata = {
        "openDt": info.get("openDt", ""),
        "genre": ", ".join(
            x["genreNm"] for x in info.get("genres", [])
            if x.get("genreNm")
        ),
        "nation": ", ".join(
            x["nationNm"] for x in info.get("nations", [])
            if x.get("nationNm")
        )
    }

    cache[movie_cd] = metadata
    time.sleep(0.1)
    return metadata


def main():
    print("원본 CSV 다운로드 중...")

    df = pd.read_csv(SOURCE_URL, dtype={"영화코드": str})
    df.columns = df.columns.str.strip()

    required = [
        "날짜", "순위", "영화코드", "영화명",
        "일관객", "누적관객", "스크린수", "상영횟수"
    ]

    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"원본 CSV에 필요한 열이 없습니다: {missing}")

    df["날짜"] = pd.to_datetime(
        df["날짜"].astype(str), format="%Y%m%d", errors="coerce"
    )

    for col in ["순위", "일관객", "누적관객", "스크린수", "상영횟수"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=["날짜", "영화코드"])
    df["영화코드"] = df["영화코드"].astype(str).str.strip()
    df = df.sort_values(["영화코드", "날짜"])

    cache = load_cache()
    rows = []

    for movie_cd, group in df.groupby("영화코드", sort=False):
        group = group.sort_values("날짜")
        first = group.iloc[0]
        last = group.iloc[-1]

        # 영화 상세정보: 개봉일, 장르, 국가
        try:
            meta = get_movie_info(movie_cd, cache)
        except Exception as e:
            # API 오류가 발생하면 전체 실행을 중단해
            # 잘못된 결과가 최신 CSV를 덮어쓰지 않도록 함
            raise RuntimeError(
                f"{movie_cd} 영화정보 조회 실패: {e}"
            ) from e

        open_dt = meta.get("openDt", "")
        open_date = pd.to_datetime(
            open_dt, format="%Y%m%d", errors="coerce"
        )

        # 개봉일 기준 7일 동안 원본 TOP 10에 기록된 일관객 합계.
        # TOP 10 밖의 관객은 원본에 없으므로 실제 첫 주 관객과
        # 다를 수 있음.
        if pd.notna(open_date):
            week_end = open_date + timedelta(days=7)
            week_rows = group[
                (group["날짜"] >= open_date)
                & (group["날짜"] < week_end)
            ]
            first_week_audi = int(week_rows["일관객"].sum())
            peak = int(open_date.month in [12, 1, 7, 8])
        else:
            first_week_audi = ""
            peak = ""

        # 누적관객 수의 마지막 유효값
        valid_audi = group["누적관객"].dropna()
        total_audi = (
            int(valid_audi.iloc[-1]) if not valid_audi.empty else ""
        )

        rows.append({
            "movieCd": movie_cd,
            "movieNm": first["영화명"],
            "openDt": open_dt,
            "genre": meta.get("genre", ""),
            "nation": meta.get("nation", ""),
            "first_scrn": (
                int(first["스크린수"])
                if pd.notna(first["스크린수"]) else ""
            ),
            "first_show": (
                int(first["상영횟수"])
                if pd.notna(first["상영횟수"]) else ""
            ),
            "first_date": first["날짜"].strftime("%Y%m%d"),
            "peak": peak,
            "first_week_audi": first_week_audi,
            "total_audi": total_audi,
            "days_in_top10": int(group["날짜"].nunique())
        })

    result = pd.DataFrame(rows, columns=COLUMNS)
    result.to_csv(OUTPUT_FILE, index=False, encoding="utf-8-sig")

    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)

    print(f"완료: {len(result)}개 영화")
    print(f"CSV 저장: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
