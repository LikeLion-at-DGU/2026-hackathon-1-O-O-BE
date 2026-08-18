"""완성 화보 응답 조립. 화보 흐름에서 DB를 읽는 곳은 여기뿐이다.

이미지는 이 응답을 지나가지 않는다. URL 문자열만 넘기고 브라우저가 CDN에서 직접
받는다 — 올릴 때와 마찬가지로 내려받을 때도 서버를 우회한다.
"""

from apps.catalog.models import Product
from apps.lookbook import snapshot
from apps.lookbook.models import Lookbook


def build(lookbook: Lookbook) -> dict:
    """P03 화보 화면과 P04 공유 화면이 함께 쓰는 본문."""
    stored = lookbook.mood_payload if isinstance(lookbook.mood_payload, dict) else {}

    return {
        "share_slug": lookbook.share_slug,
        "attempt": lookbook.attempt,
        "image_url": lookbook.image_url,
        "width": lookbook.width,
        "height": lookbook.height,
        "muse_no": stored.get("muse_no"),
        "muse_label": stored.get("muse_label"),
        "venue": stored.get("venue"),
        "season": stored.get("season"),
        "mood": snapshot.mood_of(stored),
        # label까지 서버가 내려주므로 프론트는 순회만 하면 된다.
        # 항목이 늘어도 API를 고칠 필요가 없다.
        "stats": snapshot.stats_of(stored),
        "products": _products(lookbook.product_ids),
        "report_slug": lookbook.report_id,
        "created_at": lookbook.created_at,
    }


def _products(product_ids: list) -> list[dict]:
    """화보에 담긴 상품. 상세로 넘어갈 링크가 있어야 구매로 이어진다."""
    products = Product.objects.filter(id__in=product_ids or [])
    return [
        {
            "product_id": product.id,
            "name": product.name,
            "image_url": product.thumbnail,
            "price": product.price,
            "detail_url": product.external_url,
        }
        for product in products
    ]
