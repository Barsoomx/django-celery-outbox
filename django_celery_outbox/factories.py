import factory
from django.utils import timezone

from django_celery_outbox.models import CeleryOutbox, CeleryOutboxDeadLetter


class CeleryOutboxFactory(factory.django.DjangoModelFactory):
    task_id = factory.Sequence(lambda n: f'task-{n}')
    task_name = factory.Sequence(lambda n: f'app.tasks.task_{n}')
    schema_version = 1

    class Meta:
        model = CeleryOutbox


class CeleryOutboxDeadLetterFactory(factory.django.DjangoModelFactory):
    task_id = factory.Sequence(lambda n: f'dead-task-{n}')
    task_name = factory.Sequence(lambda n: f'app.tasks.dead_task_{n}')
    created_at = factory.LazyFunction(timezone.now)
    schema_version = 1

    class Meta:
        model = CeleryOutboxDeadLetter
