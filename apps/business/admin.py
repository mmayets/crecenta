from django.contrib import admin

from .models import BusinessProfile, Product

admin.site.register(BusinessProfile)


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("name", "price", "unit_cost", "workspace")
