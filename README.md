# Ticketing System API

A Django REST Framework ticket inventory API with PostgreSQL transactions, JWT
authentication, reservation lifecycle management, staff permissions, filtering,
pagination, and OpenAPI documentation.

## Stack

- Python 3.15 and `uv`
- Django 6 and Django REST Framework
- PostgreSQL 17 with Docker Compose
- Simple JWT
- django-filter
- drf-spectacular

## Project structure

- `apps/accounts` - custom users, registration, JWT authentication, staff
  permissions
- `apps/events` - events, ticket types, and inventory
- `apps/reservations` - reservations, movements, services, filters, workers,
  pagination, and tests
- `config` - Django settings and URLs

## Requirements

- `uv`
- Docker with Docker Compose

## Setup

```bash
cp .env.example .env
docker compose up -d db
uv sync
uv run python manage.py migrate
uv run python manage.py runserver
```

PowerShell:

```powershell
Copy-Item .env.example .env
```

The API runs at `http://127.0.0.1:8000`.

PostgreSQL data is persisted in the `postgres_data` Docker volume. Keep `.env`
out of Git and replace example credentials before sharing the project.

## Staff account

Public registration creates customer accounts only.

```bash
uv run python manage.py createsuperuser
```

Assign the staff role:

```bash
uv run python manage.py shell -c "from django.contrib.auth import get_user_model; u=get_user_model().objects.get(username='STAFF_USERNAME'); u.role='STAFF'; u.save(update_fields=['role'])"
```

## API documentation

- Swagger UI: `http://127.0.0.1:8000/api/docs/`
- ReDoc: `http://127.0.0.1:8000/api/redoc/`
- OpenAPI schema: `http://127.0.0.1:8000/api/schema/`

Use Swagger's **Authorize** control to send requests with a JWT access token.

## Inventory lifecycle

```text
availability = capacity - reserved_quantity - sold_quantity
```

- Creation: reserved inventory increases and creates `HOLD`.
- Confirmation: reserved inventory becomes sold and creates `SALE`.
- Cancellation: reserved inventory is released and creates `RELEASE`.
- Expiry: reserved inventory is released and creates `RELEASE`.

Pending reservations expire after ten minutes. Confirmation also checks the
deadline before converting a hold to a sale.

## Transactions and locking

Reservation changes run in database transactions. When a booking is created,
the API locks its ticket type row with `select_for_update()` before checking
availability and increasing the reserved count. Concurrent requests for the
same ticket type wait their turn, so each sees the updated count and cannot
reserve the same remaining tickets.

Confirmation, cancellation, and expiry lock the reservation and ticket type
before changing state or inventory. The reservation update, inventory counters,
and movement record commit together, preventing partial changes if an operation
fails.

## Reservation expiry

Run the bounded expiry worker manually:

```bash
uv run python manage.py expire_reservations
```

Recommended cron schedule:

```cron
* * * * * cd /path/to/ticketing-system-api && uv run python manage.py expire_reservations
```

Batch size can be changed:

```bash
uv run python manage.py expire_reservations --batch-size 500
```

## Tests

Start PostgreSQL first, then run:

```bash
docker compose up -d db
uv run pytest
```

The suite includes inventory rules, lifecycle transitions, permissions,
transaction rollback, schema documentation, and a PostgreSQL 100-request
concurrency proof.

## Verification

```bash
uv run python manage.py check
uv run python manage.py makemigrations --check --dry-run
uv run python manage.py migrate --check
uv run python manage.py spectacular --file ticketing-openapi.yml --validate
uv run pytest
```

## Limitations

- Local development project, not a production deployment setup.
- No payments, refunds, email, notifications, ticket delivery, or reconciliation
  service.
- Public registration cannot create staff users.
- The expiry command needs an external scheduler.
