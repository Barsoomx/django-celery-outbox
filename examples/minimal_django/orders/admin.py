from django.contrib import admin

from orders.models import Order


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ['id', 'customer_email', 'total', 'status', 'created_at']
    list_filter = ['status']
    search_fields = ['customer_email']
