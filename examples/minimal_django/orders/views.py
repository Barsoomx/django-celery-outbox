import json

from django.db import transaction
from django.http import HttpRequest, JsonResponse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

from orders.models import Order
from orders.tasks import notify_warehouse, schedule_shipping_reminder, send_order_confirmation


@method_decorator(csrf_exempt, name='dispatch')
class OrderCreateView(View):
    def post(self, request: HttpRequest) -> JsonResponse:
        data = json.loads(request.body)

        with transaction.atomic():
            order = Order.objects.create(
                customer_email=data['email'],
                total=data['total'],
            )

            send_order_confirmation.delay(order.id, order.customer_email)

            notify_warehouse.apply_async(
                args=[order.id],
                link=schedule_shipping_reminder.s(order.id),
            )

            schedule_shipping_reminder.apply_async(
                args=[order.id],
                countdown=3600,
            )

        return JsonResponse(
            {
                'id': order.id,
                'status': order.status,
                'message': 'Order created, tasks queued via outbox',
            },
            status=201,
        )


class OrderListView(View):
    def get(self, request: HttpRequest) -> JsonResponse:
        orders = Order.objects.all().order_by('-created_at')[:20]

        return JsonResponse(
            {
                'orders': [
                    {
                        'id': o.id,
                        'email': o.customer_email,
                        'total': str(o.total),
                        'status': o.status,
                        'created_at': o.created_at.isoformat(),
                    }
                    for o in orders
                ]
            }
        )
