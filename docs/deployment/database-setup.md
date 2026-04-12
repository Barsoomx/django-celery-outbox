# Database Setup

## Supported Databases

| Database | Minimum Version | Notes |
|----------|-----------------|-------|
| PostgreSQL | 9.5 | Recommended |
| MySQL | 8.0.1 | Supported |
| SQLite | - | Not supported |

## PostgreSQL Setup

```sql
CREATE DATABASE myapp;
CREATE USER myapp WITH PASSWORD 'secret';
GRANT ALL PRIVILEGES ON DATABASE myapp TO myapp;
```

```python
# settings.py
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': 'myapp',
        'USER': 'myapp',
        'PASSWORD': 'secret',
        'HOST': 'localhost',
        'PORT': '5432',
    }
}
```

## MySQL Setup

```sql
CREATE DATABASE myapp CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'myapp'@'%' IDENTIFIED BY 'secret';
GRANT ALL PRIVILEGES ON myapp.* TO 'myapp'@'%';
```

```python
# settings.py
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': 'myapp',
        'USER': 'myapp',
        'PASSWORD': 'secret',
        'HOST': 'localhost',
        'PORT': '3306',
        'OPTIONS': {
            'charset': 'utf8mb4',
        }
    }
}
```

## Multi-Database Setup

If using a separate database for the outbox:

```python
DATABASE_ROUTERS = ['myapp.routers.OutboxRouter']
```

```python
# myapp/routers.py
class OutboxRouter:
    def db_for_read(self, model, **hints):
        if model._meta.app_label == 'django_celery_outbox':
            return 'outbox'
        return None

    def db_for_write(self, model, **hints):
        if model._meta.app_label == 'django_celery_outbox':
            return 'outbox'
        return None
```

## Migrations

```bash
python manage.py migrate django_celery_outbox
```

Creates two tables:

- `celery_outbox` — Pending messages
- `celery_outbox_dead_letter` — Failed messages
