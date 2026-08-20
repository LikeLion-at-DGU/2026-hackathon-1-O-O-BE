# tools

백엔드 앱이 아니라 **상품 데이터를 만들 때 쓰는 도구**다. 서버 실행에는 관여하지 않는다.

| 파일 | 언제 쓰나 |
| --- | --- |
| `mcm_crawler.py` | MCM 상품 정보를 긁어 CSV로 만든다 |
| `check_mcm_access.py` | 크롤러가 403을 맞을 때 어떤 접근 방식이 통하는지 진단한다 |

## 데이터가 서버로 들어오는 경로

```
tools/mcm_crawler.py   →  mcm_60.csv
                          ↓  python manage.py import_products_csv --csv <경로>
                       apps/catalog/fixtures/demo.json
                          ↓  python manage.py seed_demo
                       DB
```

`demo.json`은 생성기의 출력이므로 **직접 고치지 말고 CSV를 고친 뒤 다시 돌린다.**

**CSV는 저장소에 없다.** 서버를 띄우는 데 필요한 것은 `demo.json`뿐이고, 그건 커밋돼
있다. 원본 CSV는 크롤링을 다시 돌릴 때만 필요하므로 작업자가 로컬에 둔다.

## 의존성

이 도구들은 `requirements.txt`에 없는 패키지를 쓴다. 서버에는 필요 없어서 뺐다.

```bash
pip install requests beautifulsoup4 lxml
pip install curl_cffi          # 403이 계속되면
```

## 이름에 `test_`를 붙이지 않는다

예전에 `test_crawler.py`·`test_access.py`였는데, `manage.py test`가 이 패턴을 테스트
모듈로 수집한다. `check_mcm_access.py`는 `__main__` 가드가 없어서 **임포트만으로
스크립트 전체가 실행됐고**, 테스트를 돌릴 때마다 MCM 접속 진단이 찍혔다.
