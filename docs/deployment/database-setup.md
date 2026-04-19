# Database Setup

## Supported Databases

| Database | Minimum Version | Notes |
|----------|-----------------|-------|
| PostgreSQL | 9.5 | Recommended |
| MySQL | 8.0.1 | Supported |
| SQLite | - | Not supported |

## PostgreSQL Setup

Use separate credentials for schema migrations and for the runtime app/relay processes. The runtime role should not own the schema.

```sql
CREATE DATABASE myapp;
CREATE ROLE myapp_deploy LOGIN PASSWORD 'deploy-secret';
ALTER DATABASE myapp OWNER TO myapp_deploy;

CREATE ROLE myapp_runtime LOGIN PASSWORD 'runtime-secret' NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
GRANT CONNECT ON DATABASE myapp TO myapp_runtime;
```

Run `python manage.py migrate` with the deploy role, then grant the runtime DML needed by enqueue, relay, replay, and purge flows:

```sql
\c myapp
GRANT USAGE ON SCHEMA public TO myapp_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE celery_outbox, celery_outbox_dead_letter TO myapp_runtime;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO myapp_runtime;
ALTER DEFAULT PRIVILEGES FOR ROLE myapp_deploy IN SCHEMA public
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO myapp_runtime;
ALTER DEFAULT PRIVILEGES FOR ROLE myapp_deploy IN SCHEMA public
GRANT USAGE, SELECT ON SEQUENCES TO myapp_runtime;
```

```python
# settings.py
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': 'myapp',
        'USER': 'myapp_runtime',
        'PASSWORD': 'runtime-secret',
        'HOST': 'localhost',
        'PORT': '5432',
    }
}
```

## MySQL Setup

Use one role for migrations and a separate least-privilege role for runtime traffic.

```sql
CREATE DATABASE myapp CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'myapp_deploy'@'%' IDENTIFIED BY 'deploy-secret';
CREATE USER 'myapp_runtime'@'%' IDENTIFIED BY 'runtime-secret';

GRANT ALTER, CREATE, CREATE TEMPORARY TABLES, DELETE, DROP, INDEX, INSERT, REFERENCES, SELECT, UPDATE
ON myapp.* TO 'myapp_deploy'@'%';

GRANT SELECT, INSERT, UPDATE, DELETE
ON myapp.* TO 'myapp_runtime'@'%';
```

```python
# settings.py
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': 'myapp',
        'USER': 'myapp_runtime',
        'PASSWORD': 'runtime-secret',
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

Run migrations with the deploy role, not the runtime role. Production runtime credentials should not own the schema or grant rights onward.

Creates two tables:

- `celery_outbox` — Pending messages
- `celery_outbox_dead_letter` — Failed messages
