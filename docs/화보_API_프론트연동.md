# 화보(Lookbook) API 명세 · 프론트 연동 가이드

기준: 2026-08-19 · 백엔드 `apps.lookbook` · 서버 `https://hello1423.site/api/v1`

이 문서는 **화보 기능 전체**와 **프론트가 어디를 어떻게 붙여야 하는지**를 담는다.
기존 명세(📸 화보 개요, 📷 업로드 URL 발급)에서 **바뀐 부분**은 ⚠️로 표시했다.

---

## 0. 한눈에 보는 흐름

```
P01  상품 선택   GET  /reports/{slug}/lookbook/candidates   → 후보 6개
P02  촬영·동의   POST /uploads/presign                      → 업로드 URL 2개
                PUT  {photo_upload_url}                     → 사진
                PUT  {mask_upload_url}                      → 인물 실루엣
P02c 로딩       POST /reports/{slug}/lookbook               → 202 + job_id
                GET  /lookbooks/jobs/{job_id}               → 폴링 (8~9회)
P03  화보       GET  /lookbooks/{share_slug}                → 완성 이미지
P04  공유       navigator.share / 이미지 저장
```

인증은 **`X-Visit-Token` 헤더** 하나다. 폴링(`/lookbooks/jobs/*`)만 예외로 인증이 없다 —
토큰이 만료된 뒤에도 로딩 화면이 살아 있어야 하기 때문이다.

---

## 1. 공통 규칙

### 에러 형식

모든 에러가 같은 모양이다. 엔드포인트마다 다르게 파싱할 필요가 없다.

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "입력값이 올바르지 않습니다.",
    "detail": { "consent": ["consent_required"] }
  }
}
```

| HTTP | code | 언제 |
| --- | --- | --- |
| 400 | `VALIDATION_ERROR` | 입력이 잘못됨 |
| 401 | `INVALID_VISIT_TOKEN` | 토큰 없음·만료 |
| 403 | `FORBIDDEN` | 남의 리포트 |
| 404 | `NOT_FOUND` | 없는 리소스 |
| 409 | `CONFLICT` | 아직 준비 안 됨 (재시도하면 됨) |
| 429 | `RATE_LIMITED` | 재생성 3회 소진 |

**409는 "없음"이 아니라 "아직"이다.** 404와 다르게 처리해야 한다.

### ⚠️ 이미지 URL은 모두 절대 주소로 내려간다

`image_url`·`cutout_url`·`thumbnail`은 **항상 `https://hello1423.site/...` 형태**로 나간다.
프론트가 앞에 도메인을 붙이면 안 된다. 그대로 `<img src>`에 넣으면 된다.

DB에는 상대 경로가 저장돼 있지만 응답을 만들 때 서버가 절대화한다. 나중에 이미지가
CDN으로 옮겨가도 프론트 코드는 그대로다.

---

## 2. P01 — 후보 6개

```
GET /api/v1/reports/{slug}/lookbook/candidates
X-Visit-Token: <token>
```

### 응답 200

```json
{
  "max_select": 1,
  "min_select": 1,
  "preselected": ["p_305"],
  "items": [
    {
      "product_id": "p_305",
      "name": "New Liz 비세토스 쇼퍼",
      "category": "토트백",
      "thumbnail": "https://images.mcmworldwide.com/i/mcmworldwide/MWPGSLR02BK001_01",
      "cutout_url": "https://hello1423.site/media/cutouts/23-Photoroom.png",
      "score": 12.5,
      "reason_code": "most_dwelled",
      "reason": "가장 오래 보신 상품이에요"
    }
  ]
}
```

### 프론트가 할 일

- `items`는 **항상 정확히 6개**다. 빈 칸 처리를 만들 필요 없다.
- `preselected`의 상품을 미리 선택 상태로 둔다. 6칸 중 뭘 눌러야 할지 헤매지 않게 하는 장치다.
- `max_select`가 1이라 **하나만 고를 수 있다.** 이 값을 하드코딩하지 말고 응답을 따르면,
  나중에 서버가 4로 바꿔도 프론트를 안 고쳐도 된다.
- `reason`은 카드 뱃지에 **그대로 노출**하는 문구다. 프론트가 문장을 만들지 않는다.
- 분기가 필요하면 `reason` 문자열이 아니라 `reason_code`로 한다.

### 에러

| HTTP | detail | 뜻 |
| --- | --- | --- |
| 409 | `report_pending` | 리포트 분석이 아직 안 끝남 → 잠시 후 재시도 |
| 403 | — | 내 방문의 리포트가 아님 |

---

## 3. P02 — 업로드 URL 발급

```
POST /api/v1/uploads/presign
X-Visit-Token: <token>
Content-Type: application/json
```

```json
{ "content_type": "image/jpeg", "byte_size": 412000 }
```

### 응답 200

```json
{
  "photo_key": "photos/2026/08/19/9c1f4a2b3d4e5f60.jpg",
  "photo_upload_url": "https://hello1423.site/api/v1/uploads/photos/2026/08/19/9c1f4a2b3d4e5f60.jpg",
  "mask_key": "photos/2026/08/19/9c1f4a2b3d4e5f60_mask.png",
  "mask_upload_url": "https://hello1423.site/api/v1/uploads/photos/2026/08/19/9c1f4a2b3d4e5f60_mask.png",
  "headers": {
    "photo": { "Content-Type": "image/jpeg" },
    "mask":  { "Content-Type": "image/png" }
  },
  "expires_in": 600
}
```

### ⚠️ 지금은 업로드 URL이 우리 서버를 가리킨다

기존 명세는 "브라우저가 스토리지로 직행"이었지만, 버킷이 아직 없어서 **Django가 직접
PUT을 받는다.** 프론트 입장에서 달라지는 것은 없다 — 응답 형식이 동일하고, 나중에 R2로
옮겨도 URL만 바뀐다.

### 프론트가 할 일

```js
const { photo_upload_url, mask_upload_url, headers, photo_key, mask_key } = presign;

await fetch(photo_upload_url, {
  method: "PUT",
  headers: headers.photo,   // { "Content-Type": "image/jpeg" }
  body: photoBlob,
});

await fetch(mask_upload_url, {
  method: "PUT",
  headers: headers.mask,
  body: maskBlob,
});
```

- **`X-Visit-Token`을 붙이지 않는다.** presign URL은 그 자체로 업로드 허가다.
  버킷으로 옮기면 실제로 인증 헤더를 받지 않는다.
- `headers`를 그대로 실어야 한다. 값을 직접 만들지 말고 응답을 쓴다.
- `photo_key`·`mask_key`는 **생성 요청에 그대로 넘긴다.** 프론트가 가공하지 않는다.
- 파일명은 보내지 않는다. 키는 서버가 만든다.

### 마스크는 왜 필요한가

MediaPipe Selfie Segmentation으로 만든 **인물 실루엣**이다. 흰색이 인물이다.

| | 마스크 있음 | 마스크 없음 |
| --- | --- | --- |
| 얼굴·체형 | **원본 그대로 보존** | AI가 유사하게 재생성 |
| 생성 시간 | 1초 미만 | 약 40초 |

마스크가 오면 서버는 AI를 부르지 않고 실루엣으로 인물을 오려 배경판에 얹는다.
**마스크를 보내주는 것이 화보 품질과 속도 양쪽에 가장 큰 영향을 준다.**

MediaPipe가 실패하면 `mask_key`를 빼고 생성 요청을 보내면 된다. 서버가 자동으로
AI 경로로 넘어간다. 실패를 숨기려고 빈 마스크를 만들어 보내면 안 된다.

### 에러

| HTTP | detail | 뜻 |
| --- | --- | --- |
| 400 | `unsupported_type` | jpeg/png/webp만 허용 |
| 400 | `file_too_large` | 5MB 초과 |
| 401 | — | 토큰 없음·만료 |

PUT 자체의 에러: `empty_body` / `file_too_large` / `not_an_image` / `invalid_key`

---

## 4. P02-c — 화보 생성 요청

```
POST /api/v1/reports/{slug}/lookbook
X-Visit-Token: <token>
```

```json
{
  "product_ids": ["p_305"],
  "photo_key": "photos/2026/08/19/9c1f4a2b3d4e5f60.jpg",
  "mask_key": "photos/2026/08/19/9c1f4a2b3d4e5f60_mask.png",
  "consent": true,
  "photo_meta": { "face_count": 1, "face_ratio": 0.22, "face_center": [0.5, 0.4] }
}
```

- `mask_key`는 **선택**이다. 없으면 생략하거나 `""`를 보낸다.
- `consent`가 `false`면 400이다. 얼굴 사진이라 동의 없이 시작하지 않는다.
- `photo_meta`도 선택이다. `face_ratio`로 사진에 맞는 구도를 고른다 —
  정면 상반신인데 전신 와이드를 쓰면 없는 몸을 만들어내야 해서 결과가 왜곡된다.

### 응답 202

```json
{
  "job_id": "job_7Kd2mQ",
  "share_slug": "look_J4C9nS40l3E",
  "attempt": 1,
  "remaining_regenerations": 2,
  "poll_after_ms": 3000
}
```

### 프론트가 할 일

- **즉시 202가 온다.** 생성이 끝난 게 아니다. 바로 폴링으로 넘어간다.
- `share_slug`를 받는 즉시 **URL을 `/lookbook/{share_slug}`로 바꿔둔다.**
  로딩 중 앱을 닫았다 켜도 복구된다.
- `remaining_regenerations`로 [다시 돌리기] 버튼의 남은 횟수를 표시한다.

### 재생성

**같은 엔드포인트를 같은 값으로 다시 호출**하면 된다. 매번 새 `share_slug`가 발급된다 —
이미 공유한 링크의 이미지가 나중에 바뀌면 남이 열었을 때 다른 화보가 보이기 때문이다.

### 에러

| HTTP | detail | 뜻 |
| --- | --- | --- |
| 400 | `consent_required` | 동의 안 함 |
| 400 | `upload_not_found` | presign만 받고 PUT을 안 함 |
| 400 | `not_an_image` | 올린 바이트가 이미지가 아님 |
| 400 | `too_many_products` / `unknown_product` | 상품 선택 오류 |
| 409 | `report_pending` | 리포트 분석 미완료 |
| 429 | `regeneration_limit` | 재생성 3회 소진 |

---

## 5. P02-c — 폴링

```
GET /api/v1/lookbooks/jobs/{job_id}
```

**인증 헤더가 필요 없다.**

### 응답 200

```json
{
  "job_id": "job_7Kd2mQ",
  "status": "processing",
  "progress": 0.62,
  "stage": "render",
  "step": "패디가 셔터를 누르는 중",
  "share_slug": "look_J4C9nS40l3E",
  "attempt": 1,
  "error_code": null,
  "retryable": false,
  "poll_after_ms": 3000
}
```

### 프론트가 할 일

- **다음 폴링 간격은 `poll_after_ms`를 따른다.** 프론트가 3초/1.2초를 하드코딩하지 않는다.
  서버가 부하에 따라 조절하므로, 데모 당일 사람이 몰려도 배포 없이 대응할 수 있다.
- **애니메이션 분기는 `stage` 코드로 한다.** `step`은 화면에 그대로 띄우는 문구라
  카피가 바뀌면 분기가 깨진다.

| stage | 의미 |
| --- | --- |
| `compose` | 준비 중 |
| `render` | 생성 중 |
| `finalize` | 마무리 |

- `progress`는 **완료 전에는 0.9를 넘지 않는다.** 99%에서 멈춰 있는 것보다 90%에서
  기다리다 100%로 점프하는 편이 덜 답답하다는 판단이다.
- `status`가 `ready`가 되면 폴링을 멈추고 `share_slug`로 상세를 부른다.

| status | 다음 행동 |
| --- | --- |
| `queued` / `processing` | 계속 폴링 |
| `ready` | `GET /lookbooks/{share_slug}` |
| `failed` | `retryable`을 본다 |

### 실패 처리

```json
{ "status": "failed", "error_code": "GEN_CONTENT_BLOCKED", "retryable": false }
```

| error_code | retryable | 화면 |
| --- | --- | --- |
| `GEN_TIMEOUT` | true | [다시 시도] — **재생성 횟수 차감 없음** |
| `GEN_RATE_LIMITED` | true | 위와 같음 |
| `GEN_UPSTREAM` | true | 위와 같음 |
| `GEN_CONTENT_BLOCKED` | **false** | 다시 촬영 안내 |

`GEN_CONTENT_BLOCKED`는 얼굴 사진이 벤더 정책에 걸린 경우라 다시 눌러도 계속 막힌다.
이걸 재시도 가능으로 다루면 사용자가 3회를 헛되이 쓰고 비용도 그만큼 나간다.

### 404가 나오면

```json
{ "error": { "code": "NOT_FOUND", "message": "진행 상태를 찾을 수 없습니다." } }
```

작업 상태는 캐시에 있고 TTL이 있다. 만료됐거나 서버가 재시작된 경우다.
**`share_slug`로 상세를 직접 불러보면** 완성돼 있을 수 있다.

### 목(mock)으로 먼저 만들기

`job_id`를 `job_mock`으로 시작하는 값으로 주면 워커 없이 로딩 화면을 눌러볼 수 있다.

| job_id | 결과 |
| --- | --- |
| `job_mock1` | 정상 완료 |
| `job_mock_failed` | 재시도 가능 실패 |
| `job_mock_blocked` | 재시도 불가 실패 |

**개발 서버에서만 동작한다.** 운영에서는 그냥 404다.

---

## 6. P03 — 완성 화보

```
GET /api/v1/lookbooks/{share_slug}
X-Visit-Token: <token>
```

### 응답 200

```json
{
  "share_slug": "look_J4C9nS40l3E",
  "attempt": 1,
  "image_url": "https://hello1423.site/media/lookbooks/look_J4C9nS40l3E.png",
  "width": 1080,
  "height": 1350,
  "muse_no": 11,
  "muse_label": "N.011",
  "venue": "MCM HAUS SEOUL",
  "season": "2026 F/W",
  "mood": {},
  "stats": [],
  "products": [
    {
      "product_id": "p_305",
      "name": "New Liz 비세토스 쇼퍼",
      "image_url": "https://images.mcmworldwide.com/i/mcmworldwide/MWPGSLR02BK001_01",
      "price": 1090000,
      "detail_url": "https://kr.mcmworldwide.com/..."
    }
  ],
  "report_slug": "rep_abc123",
  "created_at": "2026-08-19T12:34:56Z"
}
```

### 프론트가 할 일

- **`width`·`height`로 자리를 먼저 잡는다.** 이미지가 뜰 때 화면이 튀지 않는다.
- `image_url`은 **완성된 화보 한 장**이다. 타이포·프레임·캡션이 이미 그려져 있다.
  프론트가 캔버스로 덧그릴 필요가 없다.
- `stats`는 `key`·`label`·`value`를 가진 배열이라 **순회만 하면 된다.**
  항목이 늘어도 API를 고칠 필요가 없다. 지금은 비어 있을 수 있다.
- `mood`는 현재 `{}`로 내려간다(분석 워커가 아직 무드를 만들지 않는다).
  **빈 값을 견디게** 만들어야 한다.
- 409 `not_ready`가 오면 아직 생성 중이다. 404와 다르게 처리한다.

### ⚠️ CORS — 화보를 fetch로 받는 경우

`<img src={image_url}>`로 보여주기만 하면 아무 설정도 필요 없다.

`fetch`로 받아 `navigator.share`나 저장에 쓰려면 **서버에 CORS 헤더가 필요하다.**
`/media/`는 nginx가 직접 서빙해서 Django의 CORS 설정이 적용되지 않는다.
필요하면 백엔드에 알려주면 nginx에 한 줄 추가한다.

```js
// 이 코드를 쓸 거면 백엔드에 CORS 요청 필요
const blob = await (await fetch(image_url)).blob();
await navigator.share({ files: [new File([blob], "lookbook.png", { type: "image/png" })] });
```

---

## 7. 상품 상세 — ⚠️ `cutout_url` 추가됨

```
GET /api/v1/products/{product_id}
X-Visit-Token: <token>
```

### 응답 200

```json
{
  "product_id": "p_305",
  "name": "New Liz 비세토스 쇼퍼",
  "images": ["https://images.mcmworldwide.com/i/mcmworldwide/MWPGSLR02BK001_01"],
  "cutout_url": "https://hello1423.site/media/cutouts/23-Photoroom.png",
  "price": 1090000,
  "attributes": { "color": "black", "material": "비세토스 모노그램 캔버스", "size": "M (약 17 x 30 x 35 센티미터)" },
  "story": "뮌헨 아이콘의 재 탄생",
  "scene_id": "sc_03",
  "external_url": "https://kr.mcmworldwide.com/...",
  "preset_answers": { "price": "...", "material": "...", "design_intent": "..." }
}
```

### 프론트가 할 일

- **상품 id로 이미지 경로를 직접 조합하지 않는다.** `/images/{id}-Photoroom.png` 같은
  방식은 백엔드가 파일 위치를 바꾸면 조용히 404가 된다.
- 배경이 제거된 이미지가 필요하면 `cutout_url`, 원본 사진이 필요하면 `images[0]`을 쓴다.
- `attributes`는 **사람이 물어보는 구체적인 값**이다("무슨 색이야?" → `lotus pink`).
  분석용 축(`color: pink`)과 값이 다르며, 화면에는 `attributes`를 쓴다.
- `preset_answers`는 가격·재질·디자인 의도 버튼의 답변이다. 미리 작성된 문구라
  LLM 호출이 필요 없다.

---

## 8. 진열대 목록 (참고)

`POST /api/v1/enter` 응답의 `scenes[].products[]`는 목록용 축약형이다.

```json
{ "product_id": "p_305", "no": 5, "name": "New Liz 비세토스 쇼퍼", "thumbnail": "https://...", "price": 1090000 }
```

**`cutout_url`은 목록에 없다.** 필요하면 상세를 부르거나 화보 후보(P01)를 쓴다.

### ⚠️ 상품 데이터가 60개로 교체됨

| 진열대 | 개수 |
| --- | --- |
| 1 토트백 / 2 백팩 / 3 쇼퍼백 | 9 / 9 / 9 |
| 4 악세서리 | 18 |
| 5 여성의류 / 6 남성의류 | 6 / 6 |
| 7 F/W 신상 | 3 |

6번이 9개에서 **6개로 줄었다.**

`/enter` 응답을 `sessionStorage("scenes")`에 캐시하고 있다면, **이미 열린 세션은 옛
데이터를 계속 본다.** 확인할 때는 `sessionStorage.clear()` 하거나 시크릿 창으로 새로
들어가야 한다.

---

## 9. 연동 체크리스트

- [ ] 모든 요청에 `X-Visit-Token` (폴링만 예외)
- [ ] presign의 PUT 2개에는 **토큰을 붙이지 않는다**
- [ ] MediaPipe 성공 시 **마스크를 반드시 올린다** (품질·속도 차이가 가장 크다)
- [ ] MediaPipe 실패 시 `mask_key`를 빼고 생성 요청 (빈 마스크를 만들지 않는다)
- [ ] 폴링 간격은 `poll_after_ms`를 따른다
- [ ] 로딩 애니메이션 분기는 `step`이 아니라 `stage`
- [ ] 실패 시 `retryable`로 [다시 시도]와 [다시 촬영]을 가른다
- [ ] `share_slug`를 받는 즉시 URL에 반영 (새로고침 복구)
- [ ] 이미지 URL 앞에 도메인을 붙이지 않는다 (이미 절대 주소)
- [ ] `width`/`height`로 자리를 미리 잡는다
- [ ] `mood`·`stats`가 비어 있어도 화면이 깨지지 않는다
- [ ] 상품 이미지는 `cutout_url` / `images`를 쓰고 경로를 조합하지 않는다

---

## 10. 아직 남은 것

| 항목 | 상태 |
| --- | --- |
| `mood` 4종 | 분석 워커가 아직 만들지 않아 `{}`로 내려감 |
| `stats` 3항목 | 무엇을 세는 값인지 기획 미확정 |
| 이미지 저장소 | 서버 디스크. 버킷(R2)으로 옮겨도 프론트 코드는 그대로 |
| 동시 생성 상한 | 미구현. 동시 요청이 몰리면 일부가 `GEN_RATE_LIMITED` |
