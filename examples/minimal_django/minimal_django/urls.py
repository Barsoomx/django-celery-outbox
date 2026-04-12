from django.contrib import admin
from django.urls import path
from orders.views import HealthView, OrderCreateView, OrderListView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('orders/', OrderListView.as_view(), name='order-list'),
    path('orders/create/', OrderCreateView.as_view(), name='order-create'),
    path('orders/health/', HealthView.as_view(), name='health'),
]
