from django.dispatch import Signal

outbox_message_created = Signal()
outbox_message_sent = Signal()
outbox_message_failed = Signal()
outbox_message_dead_lettered = Signal()
