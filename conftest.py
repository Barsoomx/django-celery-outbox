import pytest
from django.contrib.auth.models import User


@pytest.fixture
def f_user() -> User:
    return User.objects.create_user(username='testuser', password='testpass')
