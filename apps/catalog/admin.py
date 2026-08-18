"""상품 30개를 사람이 직접 넣고 검수하는 화면. 크롤링 결과 확인용이다."""

from django.contrib import admin

from apps.catalog.models import Product, Scene, Store


class ProductInline(admin.TabularInline):
    model = Product
    extra = 0
    fields = ("no", "name", "price", "category", "color", "material", "is_new")
    show_change_link = True


@admin.register(Store)
class StoreAdmin(admin.ModelAdmin):
    list_display = ("id", "name")


@admin.register(Scene)
class SceneAdmin(admin.ModelAdmin):
    list_display = ("no", "name", "store", "product_count")
    inlines = [ProductInline]

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("store").prefetch_related("products")

    @admin.display(description="상품 수")
    def product_count(self, scene: Scene) -> int:
        return scene.products.count()


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("name", "scene", "no", "price", "price_band", "color", "material", "mood", "is_new")
    list_filter = (
        "scene",
        "category",
        "color",
        "material",
        "pattern",
        "silhouette",
        "mood",
        "price_band",
        "use_case",
        "is_new",
    )
    search_fields = ("name", "story")
    list_select_related = ("scene",)
