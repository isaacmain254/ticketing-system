# Ticketing System API

## Purpose

A portfolio-grade Django REST Framework inventory API for published events and
ticket types. The API:

- uses PostgreSQL transactions and row locks to prevent overselling;
- separates customers and staff with JWT authentication and ownership-aware
  permissions;
- atomically creates, confirms, cancels, and expires reservations;
- records append-only inventory movements; and
- exposes filtering, pagination, Swagger UI, ReDoc, and OpenAPI schema.

This repository is intended for local development and demonstration. It does
not provide payment processing, email delivery, production deployment, or an
operational reconciliation service.

## Technology stack

- Python 3.15 and `uv`
- Django 6 and Django REST Framework
- PostgreSQL 17
- Docker Compose
- Simple JWT
- django-filter
- drf-spectacular

## Project layout

- `apps/accounts`: custom user model, customer registration, JWT authentication,
  and staff permissions.
- `apps/events`: published events, ticket types, staff event management, and
  staff inventory views.
- `apps/reservations`: reservations, inventory movements, lifecycle services,
  filters, pagination, management command, API views, and tests.
- `config`: Django settings and canonical API/documentation routes.

## Prerequisites

- Python 3.15 or compatible versions supported by the project
- `uv`
- Docker with Docker Compose

## Environment setup

Copy the example environment file and replace local development placeholders
before use:

```bash
cp .env.example .env
```

On Windows PowerShell, use:

```powershell
Copy-Item .env.example .env
```

`.env.example` defines the PostgreSQL database, host port, Django secret key,
debug mode, and allowed hosts. `.env` is ignored by Git; never commit real
credentials or production data. The Django secret and PostgreSQL password should
be rotated for any shared or deployed environment.

Start PostgreSQL:

```bash
docker compose up -d db
```

Confirm that the service is healthy:

```bash
docker compose ps
```

The database data is stored in the `postgres_data` named volume. Stop the
service with `docker compose stop db`; remove the local database and volume
only when an intentionally clean database is wanted.

## Install dependencies and migrate

Synchronize dependencies from the lockfile:

```bash
uv sync
```

Apply migrations:

```bash
uv run python manage.py migrate
```

Run the API development server:

```bash
uv run python manage.py runserver
```

The base local URL is `http://127.0.0.1:8000`.

## Staff accounts

Public registration always creates a customer and ignores staff-related fields.
Create an administrative staff account interactively:

```bash
uv run python manage.py createsuperuser
```

Staff API authorization uses the custom `role` field. After creating the user,
assign the staff role safely in Django shell:

```bash
uv run python manage.py shell -c "from django.contrib.auth import get_user_model; u=get_user_model().objects.get(username='STAFF_USERNAME'); u.role='STAFF'; u.save(update_fields=['role'])"
```

Keep staff credentials separate from customer registration credentials.

## API routes and documentation

Canonical API routes are under `/api/v1/`:

- `POST /api/v1/auth/register/`
- `POST /api/v1/auth/token/`
- `POST /api/v1/auth/token/refresh/`
- `GET /api/v1/events/`
- `POST /api/v1/events/`
- `POST /api/v1/events/{id}/ticket-types/`
- `GET /api/v1/ticket-types/{id}/`
- `GET /api/v1/ticket-types/{id}/inventory/`
- `GET|POST /api/v1/reservations/`
- `GET /api/v1/reservations/{id}/`
- `POST /api/v1/reservations/{id}/confirm/`
- `POST /api/v1/reservations/{id}/cancel/`
- `GET /api/v1/reservations/{id}/movements/`
- `GET /api/v1/inventory-movements/`

Compatibility routes remain available at `/api/auth/`,
`/api/reservations/`, and Swagger UI/ReDoc paths under `/api/`.

- Swagger UI: `http://127.0.0.1:8000/api/docs/`
- ReDoc: `http://127.0.0.1:8000/api/redoc/`
- OpenAPI schema: `http://127.0.0.1:8000/api/schema/`

Swagger's **Authorize** control accepts the Simple JWT access token.

## End-to-end workflow

Register a customer:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/auth/register/ \
  -H "Content-Type: application/json" \
  -d '{"username":"customer1","email":"customer1@example.com","password":"ExamplePassphrase!42","password_confirm":"ExamplePassphrase!42"}'
```

Obtain a JWT pair:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/auth/token/ \
  -H "Content-Type: application/json" \
  -d '{"username":"customer1","password":"ExamplePassphrase!42"}'
```

Create an event and ticket type as a staff user. Replace the event UUID and JWT
with values from the API responses:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/events/ \
  -H "Authorization: Bearer STAFF_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"Portfolio Concert","description":"Demo event","venue":"Main Hall","starts_at":"2026-12-01T19:00:00Z","status":"PUBLISHED"}'

curl -X POST http://127.0.0.1:8000/api/v1/events/EVENT_UUID/ticket-types/ \
  -H "Authorization: Bearer STAFF_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"General Admission","price":"75.00","capacity":100}'
```

Create a reservation:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/reservations/ \
  -H "Authorization: Bearer CUSTOMER_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"ticket_type":"TICKET_TYPE_UUID","quantity":2}'
```

Confirm or cancel it before expiry:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/reservations/RESERVATION_UUID/confirm/ \
  -H "Authorization: Bearer CUSTOMER_ACCESS_TOKEN"

curl -X POST http://127.0.0.1:8000/api/v1/reservations/RESERVATION_UUID/cancel/ \
  -H "Authorization: Bearer CUSTOMER_ACCESS_TOKEN"
```

Customers can list only their own reservations. Staff can list all reservations,
filter by customer, inspect inventory, and review inventory movements.

## Inventory and lifecycle

For each ticket type:

```text
availability = capacity - reserved_quantity - sold_quantity
```

A quantity hold changes the inventory counters atomically:

```text
PENDING creation: reserved += quantity; HOLD movement
CONFIRM: reserved -= quantity; sold += quantity; SALE movement
CANCEL: reserved -= quantity; RELEASE movement
EXPIRY: reserved -= quantity; RELEASE movement
```

Pending reservations have a ten-minute deadline. The expiry management command
marks expired holds and releases them; confirmation also performs deadline
checking so a late confirmation cannot turn an expired hold into a sale.

Database constraints and service logic prevent negative counters and counter
totals above capacity. Repeated confirmation, cancellation, and expiry are
designed to be idempotent and do not duplicate terminal movements.

## Transactions and locking

Reservation creation and lifecycle transitions run inside
`transaction.atomic()`, so inventory counters, reservation state, and the
inventory ledger commit together. A forced exception rolls all of those changes
back.

Creation locks the relevant `TicketType` row with `select_for_update()` before
checking and changing availability. Confirmation, cancellation, and expiry lock
the reservation and its ticket type before applying transitions. PostgreSQL
serializes competing changes to the locked rows, and each waiting transaction
re-evaluates availability from the latest committed state.

Database constraints provide a second line of defense, while the row locks
provide the transaction-level behavior needed for accurate inventory decisions.

## Reservation expiry worker

Run the expiry worker every minute using cron or another scheduler:

```cron
* * * * * cd /path/to/ticketing-system-api && uv run python manage.py expire_reservations
```

The command processes at most 100 expired reservations per invocation by
default:

```bash
uv run python manage.py expire_reservations
```

Change the bounded batch:

```bash
uv run python manage.py expire_reservations --batch-size 500
```

The command is safe to repeat and locks only the bounded reservation and ticket
type rows required for each transition.

## Filtering and pagination

Reservation and inventory-movement lists use DRF pagination with default page
size 20 and maximum page size 100:

```text
GET /api/v1/reservations/?page=2&page_size=50
```

Paginated responses contain `count`, `next`, `previous`, and `results`.

Reservation filters include status, event, ticket type, customer ID for staff,
created/expiry date ranges, UUIDs, and validated stable ordering. Customer
requests cannot override ownership or use staff-only customer filters.

## Automated tests

PostgreSQL must be healthy before running integration and concurrency tests.
The project keeps the pytest configuration in `pyproject.toml` and discovers
existing Django `tests.py` modules.

Run the complete suite:

```bash
uv run pytest
```

Coverage includes inventory constraints, lifecycle transitions, ownership
authorization, filtering, pagination, OpenAPI routes, transaction rollback,
competing expiry/confirmation, and concurrency.

The defining concurrency test uses PostgreSQL `TransactionTestCase`, separate
threads and database connections, and 100 simultaneous attempts to reserve one
ticket when only five tickets remain. It requires exactly five successes and
95 insufficient-inventory failures.

The Compose PostgreSQL service raises `max_connections` to 300 so the complete
100-worker proof and Django setup connections can coexist. This is a test/local
development setting, not a production sizing recommendation.

Use focused test paths while debugging:

```bash
uv run pytest apps/reservations/tests.py -q
```

## Final verification

Run these checks from a clean checkout after configuring `.env` and starting
PostgreSQL:

```bash
uv run python manage.py check
uv run python manage.py makemigrations --check --dry-run
uv run python manage.py migrate --check
uv run python manage.py spectacular --file ticketing-openapi.yml --validate
uv run pytest
```

These tests must run against Docker Compose PostgreSQL. The same locking design
should not be described as proven by SQLite tests.

## Trade-offs and limitations

- Access tokens are not revoked on logout in the demonstrated API configuration.
- The project does not implement payments, refunds, refunds ledgers, email,
  notifications, waitlists, or ticket delivery.
- Registration deliberately cannot create staff users.
- The expiry command requires external scheduling; this repository does not
  run a production worker supervisor.
- Inventory is reconciled through constraints, services, and ledger tests; no
  asynchronous reconciliation or audit command is included.
- The development secret and credentials in `.env.example` are placeholders,
  not production secrets.
- Pagination, filtering, and ordering are validation-focused; they are not a
  caching or search optimization layer.
