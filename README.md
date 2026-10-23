# korea-career-pack

[career-ops](https://github.com/santifer/career-ops)에 넣어 쓰는 **한국 시장 오퍼 단계 확장팩**입니다.
career-ops에 이미 있는 한국어 모드(`modes/ko`: 공고 평가·지원서·파이프라인·면접)가 다루지 않는
**오퍼 비교, 처우협의, 계약서 읽기**를 채웁니다. 국내 기업과 외국계를 모두 다룹니다.

> **Works with career-ops. Not affiliated with or endorsed by the career-ops project.**
> career-ops 원본 메인테이너와 관계없는 독립 확장팩입니다. "career-ops" 이름과 브랜드는 원본 소유입니다([TRADEMARK.md](https://github.com/santifer/career-ops/blob/main/TRADEMARK.md)).

## 무엇이 들어 있나

| 파일 (설치 위치) | 역할 |
|------------------|------|
| `modes/ko/offer-compare.md` | **새 모드.** 받은 오퍼 2개 이상(현직 포함)을 같은 기준으로 비교하고, 처우협의 질문과 회신 초안(요청 시)까지. 결정은 하지 않음 |
| `modes/ko/offer-prep.md` | 원본 `offer-prep`(계약서 읽기) 위에 얹는 **한국 레이어.** 처우협의서·근로계약서·연봉계약서·외국계 영문 오퍼 구분, 한국 조항 분류, 노무사/변호사 질문 분리 |
| `scripts/kr_offer.py` | 오퍼 계산기 (표준 라이브러리만). 퇴직금 포함 연봉 12/13 환산, 성과급(보장/비보장), 사이닝(반환 조건), **외국계 RSU 연환산(환율 기준일)**, 수습 감액, 고정OT 초과 여부, 월 실수령 추정, 실효 시급 |
| `templates/kr-labor-facts.yml` | 모드가 인용하는 **검증된 노동법·제도 사실표** (출처·시행일·확인일 포함). 원본 `restrictive-covenants.yml`과 같은 규칙 |
| `templates/offers.example.json` | 오퍼 입력 예시 (가상 숫자) |
| `templates/portals-kr.example.yml` | 서울/한국 근무 공고만 거르는 `location_filter`와, **서울 공고가 실제로 있는 것을 확인한** 외국계·글로벌 기업 Greenhouse 보드 5곳 |

## 설치

```bash
git clone https://github.com/santifer/career-ops        # 이미 있다면 생략
git clone https://github.com/ryuuusm/korea-career-pack
python korea-career-pack/install.py career-ops --dry-run   # 무엇이 복사되는지 먼저 확인
python korea-career-pack/install.py career-ops
```

- 이미 있는 파일과 내용이 다르면 **덮어쓰지 않고 건너뜁니다**(`--force`로만 덮어씀).
- `config/profile.yml`에 한국어 모드를 켭니다(원본 `modes/ko/README.md` 참고):
  ```yaml
  language:
    output: ko
    modes_dir: modes/ko
  ```
- 외국계 공고 스캔: `templates/portals-kr.example.yml`의 블록을 `portals.yml`에 합칩니다.

삭제는 위 표의 파일 6개를 지우면 됩니다(설치 스크립트는 아무것도 지우지 않습니다).

## 사용 예

- "오퍼 두 개 받았어. `modes/ko/offer-compare.md`로 비교해줘" → 항목을 물어본 뒤 `data/offers.json` 작성 → `python scripts/kr_offer.py data/offers.json`
- "이 오퍼레터 같이 읽어줘" (`modes_dir: modes/ko`일 때 `/career-ops offer-prep`) → 원본 절차 + 한국 레이어
- 계산기만 따로: `python scripts/kr_offer.py templates/offers.example.json`

예시 출력(일부, 가상 숫자):

| 항목 (원) | 현직 | 국내 A사 | 외국계 B사 |
|---|---:|---:|---:|
| 세전 연봉(퇴직금 제외) | 72,000,000 | 78,461,538 | 80,000,000 |
| 1년차 보장 총보상 | 78,000,000 | 83,038,462 | 96,666,667 |
| 2년차~ 기대 총보상 | 85,200,000 | 90,000,000 | 119,516,667 |
| 월실수령 | 4,950,940 | 5,316,832 | 5,403,707 |

## 원칙 (원본 career-ops와 같음)

- **결정하지 않는다.** 비교·질문·초안까지. 수락 여부는 사용자가 정한다.
- **법을 기억으로 말하지 않는다.** 법·제도 사실은 `kr-labor-facts.yml`의 검증된 행만 인용하고, 나머지는 노무사·변호사 질문으로 넘긴다. 계류 중인 법안(예: 포괄임금 금지 법안)은 법으로 말하지 않는다.
- **오퍼 내용을 외부로 보내지 않는다.** 회사명·금액이 들어간 검색을 하지 않는다.
- **없는 경쟁 오퍼를 지어내지 않는다.**

## 숫자의 근거 (2026-10-23 확인)

| 항목 | 값 | 출처 |
|------|----|------|
| 국민연금 | 근로자 4.75% (총 9.5%), 기준소득월액 41만~659만 원 (2026-07~2027-06) | [세계일보 2026-01-11](https://www.segye.com/newsView/20260111508142) |
| 건강보험 / 장기요양 | 3.595% (총 7.19%) / 0.9448% (= 건강보험료의 13.14%) | [국민건강보험공단](https://www.nhis.or.kr/renewal_popup/poster/20260204_poster_longdesc_1.html) |
| 고용보험 | 근로자 0.9% | [비즈폼 2026 급여계산 가이드](https://www.bizforms.co.kr/365guide/view.asp?number=309) |
| 소득세율·식대 비과세 | 6~45% 8단계, 식대 월 20만 원 | 같은 자료, 소득세법 제55조 |
| 포괄임금 지침 | 2026-04-09 시행 지도지침 (법률 아님) | [고용노동부](https://www.moel.go.kr/news/enews/report/enewsView.do?news_seq=19208) |
| 포괄임금 금지 법안 | 계류 중 (2026-10-13 기준) | [머니투데이](https://www.mt.co.kr/economy/2026/10/13/2026101311553174749) |

월 실수령액은 국세청 간이세액표와 월 수천~수만 원 차이가 날 수 있는 **추정치**입니다. 요율은 매년 1월·7월에 바뀌므로 `scripts/kr_offer.py`의 `RATES`와 `kr-labor-facts.yml`을 함께 갱신하세요.

## 개발

```bash
pip install pytest
pytest tests -q
```

`tests/reference_salary.py`는 [ai-job-search-kr](https://github.com/wing0828/ai-job-search-kr)의 `salary.py`(MIT) 원본입니다. 계산 로직이 원본과 같은지 확인하는 기준으로만 씁니다. 원본의 부동소수점 때문에 생기는 10원 단위 절사 오차(예: 5,800,000 × 0.9%가 52,190원이 되는 문제)는 이 팩에서 고쳤습니다.

## 라이선스

MIT. career-ops(Santiago Fernández de Valderrama), ai-job-search-kr(wing0828), ai-job-search(Mads Lorentzen)의 저작권 표시를 [LICENSE](LICENSE)에 함께 둡니다.

---

### English summary

An offer-stage extension pack for [career-ops](https://github.com/santifer/career-ops) targeting the Korean market (domestic and multinational employers). It adds a multi-offer comparison mode, a Korea layer for `offer-prep` (contract reading), a stdlib-only calculator that normalises Korean offers (severance-inclusive salaries, guaranteed vs. target bonus, sign-on clawbacks, RSU annualisation with an FX date, probation pay, fixed-OT checks, estimated take-home pay), a cited table of Korean labor facts, and a Seoul location filter with five verified Greenhouse boards. Works with career-ops; not affiliated with or endorsed by it. MIT.
