# Ticketing Inventory Reservation API --- Project Plan

> **Purpose:** Build a portfolio-quality backend API that demonstrates
> intermediate Django/DRF engineering, PostgreSQL transaction safety,
> concurrency control, domain modeling, authorization, testing, and API
> documentation.
>
> **Implementation rule:** Follow the phases in order. Complete each
> phase's acceptance criteria before moving on. Keep the project
> backend-only and avoid adding features outside the defined scope.

## 1. Project Overview

Build an API for a ticketing platform where staff publish events and
define ticket types with limited capacity. Customers can temporarily
reserve tickets, confirm reservations, or cancel them. Pending
reservations expire after a deadline and release their holds.

The system must **never oversell inventory**, even when many requests
attempt to reserve the last available tickets at the same time.

### Required stack

-   Python, managed with **uv**
-   Django
-   Django REST Framework
-   PostgreSQL, run locally with **Docker Compose**
-   Simple JWT for JWT authentication
-   `drf-spectacular` for OpenAPI schema, Swagger UI, and ReDoc
-   `pytest` and `pytest-django` for automated tests
-   PostgreSQL-backed tests for transaction and concurrency behavior

Use current compatible stable package versions and commit `uv.lock` so
the environment is reproducible.

### Project boundaries

**In scope** - User registration and JWT authentication - Customer and
staff roles - Events and ticket types - Inventory counters and
availability - Create, confirm, cancel, and expire reservations -
Inventory movement ledger - Reservation history, filtering, and
pagination - Atomic database operations and row locking - Automated
unit/API/integration/concurrency tests - Interactive API documentation -
Setup instructions and design decisions in README

**Out of scope for v1** - Frontend or client application - Real payment
processing, refunds, and payment webhooks - QR-code ticket generation -
Email/SMS notifications - Distributed microservices - Celery/Redis
unless the core project is complete and there is a clear reason to
extend it - Cancelling confirmed tickets or refunding sold tickets

Reservation confirmation represents conversion of a hold into a
confirmed ticket; it does **not** charge a payment method.

## 2. Business Rules --- Treat These as Requirements

1.  A ticket type belongs to one event and has a fixed capacity.
2.  A reservation belongs to one customer and one ticket type. Multiple
    ticket types require separate reservations in v1.
3.  Reservation quantity must be a positive integer.
4.  Available quantity is
    `capacity - reserved_quantity - sold_quantity`.
5.  Creating a reservation atomically increases `reserved_quantity`,
    creates a pending reservation, and writes a `HOLD` movement.
6.  The default reservation lifetime is 10 minutes. Store the deadline
    in `expires_at`; do not hard-code the duration in multiple places.
7.  Confirmation is allowed only for a pending reservation whose
    deadline has not passed.
8.  Confirmation atomically decreases `reserved_quantity`, increases
    `sold_quantity`, changes status to `confirmed`, records
    `confirmed_at`, and writes a `SALE` movement.
9.  Cancelling a pending reservation atomically decreases
    `reserved_quantity`, changes status to `cancelled`, and writes a
    `RELEASE` movement.
10. Expiring a pending reservation atomically decreases
    `reserved_quantity`, changes status to `expired`, and writes a
    `RELEASE` movement.
11. A reservation can reach only one terminal state: `confirmed`,
    `cancelled`, or `expired`.
12. Repeated confirmation/cancellation/expiry attempts must never alter
    counters or write duplicate movements. Return the existing state for
    a repeat of the same successful transition, or a documented
    `409 Conflict` for an invalid transition.
13. Customers can only read and modify their own reservations. Staff can
    manage events and inspect all reservations and inventory movements.
14. Role privileges are server-controlled. Registration must never allow
    a client to create a staff account or set protected fields.
15. Every inventory change must be performed through the domain service
    layer in a transaction and recorded in the ledger.
16. All code paths that lock both a reservation and a ticket type must
    use a consistent lock order to reduce deadlock risk.
17. Use timezone-aware datetimes and a consistent clock
    (`django.utils.timezone.now()`).
18. Event/ticket capacity cannot be reduced below the number of tickets
    already held or sold.
19. A failed operation must not leave partial database changes.
20. Use database constraints for invariants that can be enforced in
    PostgreSQL, not just serializer validation.

## 3. Architecture and Repository Layout

Use one Django project with small domain apps. Do not create
microservices.

``` text
ticketing-api/
├── config/
│   ├── settings.py
│   ├── urls.py
│   ├── asgi.py
│   └── wsgi.py
├── apps/
│   ├── __init__.py
│   ├── accounts/
│   │   ├── models.py
│   │   ├── serializers.py
│   │   ├── views.py
│   │   ├── permissions.py
│   │   └── tests/
│   ├── events/
│   │   ├── models.py
│   │   ├── serializers.py
│   │   ├── views.py
│   │   └── tests/
│   └── reservations/
│       ├── models.py
│       ├── serializers.py
│       ├── views.py
│       ├── services.py
│       ├── selectors.py
│       ├── filters.py
│       ├── management/
│       │   └── commands/
│       │       └── expire_reservations.py
│       └── tests/
├── tests/
│   └── integration/
├── docker-compose.yml
├── Dockerfile                 # Add when containerizing the API, if desired
├── pyproject.toml
├── uv.lock
├── .env.example
├── .gitignore
├── README.md
└── manage.py
```

Responsibilities: - **Models:** persisted data, relationships, choices,
and database constraints. - **Serializers:** validate request input and
define response shapes. - **Views:** HTTP concerns, authentication,
permissions, status codes, and invoking services. - **Services:**
transactional business operations and inventory invariants. -
**Selectors/query helpers:** reusable read queries when useful. -
**Management command:** scheduled expiry worker. - **Tests:** prove
business behavior and database correctness.

Keep business logic out of serializers and views. Do not expose internal
model fields just because they exist.

## 4. Data Model

Use UUID primary keys for public-facing entities. Use Django's custom
user model from the start---before the first migration.

### 4.1 User

Use a custom Django user model extending `AbstractUser`, configured
through `AUTH_USER_MODEL` before creating initial migrations.

Fields: - Standard Django identity fields - `role`: `CUSTOMER` or
`STAFF`, with customer as the default - Timestamps if useful

Do not allow registration serializers to accept `role`, `is_staff`,
`is_superuser`, or other privilege fields. Use Django's permission/group
system or a controlled role field consistently. Only an authorized
operator can promote a user.

### 4.2 Event

Fields: - `id`: UUID - `name` - `description` - `venue` - `starts_at` -
`status`: `DRAFT`, `PUBLISHED`, or `CANCELLED` - `created_at`,
`updated_at`

Customers can browse published events only. Staff can create and update
events. Do not allow reservations for unpublished or cancelled events.

### 4.3 TicketType

Fields: - `id`: UUID - `event`: foreign key to Event - `name` - `price`:
decimal, never float - `capacity`: non-negative integer -
`reserved_quantity`: non-negative integer, default 0 - `sold_quantity`:
non-negative integer, default 0 - `created_at`, `updated_at`

Constraints and validation: - Price must be non-negative. - Capacity and
inventory counters cannot be negative. -
`reserved_quantity + sold_quantity <= capacity`. - Define whether
ticket-type names must be unique per event; prefer a database uniqueness
constraint on `(event, name)`. - Capacity edits must lock the ticket
type and reject values below held plus sold inventory. - Compute
availability as `capacity - reserved_quantity - sold_quantity`; do not
maintain a separate writable `available_quantity` counter.

### 4.4 Reservation

Fields: - `id`: UUID - `customer`: foreign key to the custom user
model - `ticket_type`: foreign key to TicketType - `quantity`: positive
integer - `unit_price`: decimal snapshot of the price at reservation
time - `status`: `PENDING`, `CONFIRMED`, `CANCELLED`, or `EXPIRED` -
`expires_at` - `created_at`, `updated_at` - `confirmed_at`: nullable
timestamp

Store the unit price snapshot so later price edits do not change an
existing reservation's price. `total_price` can be computed as
`unit_price * quantity`; avoid storing a redundant total unless a clear
requirement emerges.

### 4.5 InventoryMovement

Fields: - `id`: UUID - `ticket_type`: foreign key to TicketType -
`reservation`: foreign key to Reservation - `movement_type`: `HOLD`,
`RELEASE`, or `SALE` - `quantity`: positive integer - `created_at` -
Optional `metadata` JSON field for context

Movement semantics: - `HOLD`: tickets move from available capacity into
pending holds. - `RELEASE`: a pending hold is returned to available
capacity. - `SALE`: a hold is converted to sold inventory on
confirmation.

For a reservation of 3 tickets that is confirmed, record `HOLD(3)` and
`SALE(3)`. Do not increase the held counter during confirmation. For a
reservation cancelled or expired, record `HOLD(3)` and `RELEASE(3)`.

Treat ledger rows as append-only in application code. Never edit or
delete past movements to correct a mistake; any future correction should
be a new, explicit compensating movement with documented semantics. In
v1, do not provide an API that edits or deletes ledger entries.

The inventory counters are optimized current state; the movement ledger
is the audit trail. Tests should ensure both agree with reservation
transitions.

## 5. Setup Phase --- uv and Docker Compose

### Step 1: Create the project

``` bash
mkdir ticketing-api
cd ticketing-api
uv init
uv add django djangorestframework "psycopg[binary]" \
  djangorestframework-simplejwt drf-spectacular \
  django-filter
uv add --dev pytest pytest-django
uv run django-admin startproject config .
```

Create the `apps` package and Django apps. If needed, create each app
from the `apps/` directory and then set its full Python import path
correctly. Ensure every app is importable.

Pin compatible dependency versions through `uv.lock` and commit both
`pyproject.toml` and `uv.lock`. Use `uv run` for project commands so the
environment is reproducible.

### Step 2: Configure PostgreSQL in Docker Compose

Create `docker-compose.yml` with a PostgreSQL service: - A supported
PostgreSQL image version - Environment variables for database name,
username, and password - A host port mapping such as `5432:5432` for a
Django process running on the host - A named volume for persistence - A
health check using `pg_isready`

Use values from `.env` locally and provide only placeholders in
`.env.example`. Add `.env` to `.gitignore`. Never commit real
credentials.

When Django runs on the host, use `localhost` as the database host. If
Django is later run as a Compose service on the same network, use the
Compose service name (for example, `db`) as the host.

Start the database:

``` bash
docker compose up -d db
docker compose ps
```

Wait until PostgreSQL is healthy before running migrations. Use the
actual service name from your Compose file.

### Step 3: Configure Django

-   Add `rest_framework`, `drf_spectacular`, `django_filters`, and the
    three local apps to `INSTALLED_APPS`.
-   Configure PostgreSQL through environment variables.
-   Set `AUTH_USER_MODEL` before the first migration.
-   Enable timezone support.
-   Configure DRF authentication, permissions, pagination, and the
    OpenAPI schema class.
-   Configure Simple JWT with sensible access-token lifetime and refresh
    settings.
-   Keep `DEBUG`, `SECRET_KEY`, allowed hosts, and database credentials
    out of source-controlled production settings.
-   Provide safe defaults for local development only.

Run:

``` bash
uv run python manage.py check
uv run python manage.py makemigrations
uv run python manage.py migrate
uv run python manage.py createsuperuser
uv run python manage.py runserver
```

**Acceptance criteria** - PostgreSQL is running in Compose with
persistent storage. - Django connects successfully. - Custom user model
is in the initial migration history. - `manage.py check` passes. -
Migrations apply without errors. - No secrets are committed.

## 6. Implementation Phases

### Phase 1 --- Domain models and constraints

Implement Event, TicketType, Reservation, and InventoryMovement models
and their constraints. Register useful models in Django admin for local
inspection. Add migrations and minimal test fixtures/factories.

**Do not implement the complete API yet.**

Acceptance criteria: - Relationships and deletion behavior are
deliberate. - Status and movement choices are defined. - Database
constraints prevent negative quantities/counters and over-capacity
counters. - Event/ticket capacity rules are validated. - Price snapshots
are persisted. - Tests cover model constraints where practical.

### Phase 2 --- Authentication and permissions

Implement: - Customer registration - JWT obtain and refresh endpoints -
Authentication configuration - Reusable staff permission - Reservation
ownership enforcement - Staff-only management permissions

Use DRF permissions and scoped querysets together. Do not rely only on a
detail-view permission check: list endpoints must also be scoped to the
current customer.

Acceptance criteria: - Anonymous users cannot access protected
reservation operations. - Registration always creates a customer. -
Customers cannot elevate privileges by submitting extra JSON fields. -
Customers cannot read or alter other customers' reservations. - Staff
can access authorized staff endpoints. - Permission failures do not leak
another user's reservation details.

### Phase 3 --- Reservation creation service

Implement `create_reservation(customer, ticket_type_id, quantity)` in
`reservations/services.py`.

Required algorithm: 1. Validate quantity. 2. Begin
`transaction.atomic()`. 3. Lock the TicketType row using
`select_for_update()`. 4. Recheck that its event is published and
eligible for reservation. 5. Calculate availability after obtaining the
lock. 6. Raise a domain-specific insufficient-inventory exception if
there is not enough capacity. 7. Increment `reserved_quantity`. 8.
Create a PENDING reservation with unit price snapshot and `expires_at`.
9. Create a matching HOLD movement. 10. Commit all changes together.

All code that changes a ticket type's counters must follow the same
locking discipline. Use domain exceptions, not generic `ValueError`, to
distinguish expected business errors from unexpected bugs. Translate
domain exceptions into HTTP responses in the API layer.

Acceptance criteria: - A successful reservation changes counters and
creates one reservation and one HOLD movement. - Insufficient capacity
creates no reservation or movement and changes no counters. - Invalid
quantity is rejected. - Exceptions after any write roll the entire
operation back. - Tests run against PostgreSQL for locking-related
behavior.

### Phase 4 --- Confirmation and cancellation services

Implement: - `confirm_reservation(customer, reservation_id)` -
`cancel_reservation(customer, reservation_id)`

For operations involving both rows, use the same lock order everywhere:
**lock Reservation first, then TicketType**. Recheck status and deadline
only after obtaining locks. Reservation creation only needs to lock
TicketType because the Reservation row does not yet exist.

Confirmation transaction: 1. Lock reservation. 2. Verify ownership or
staff authorization at the API boundary; the service must still enforce
the business-state rules. 3. Lock ticket type. 4. If the reservation
deadline has passed, expire it and release its hold safely instead of
confirming it. 5. If it is no longer pending, return the documented
idempotent result or conflict. 6. Decrease `reserved_quantity` and
increase `sold_quantity`. 7. Set status to CONFIRMED and `confirmed_at`.
8. Create one SALE movement. 9. Commit.

Cancellation transaction: 1. Lock reservation. 2. Lock ticket type. 3.
If PENDING, decrease `reserved_quantity`, set CANCELLED, and create one
RELEASE movement. 4. If already CANCELLED, do not change inventory or
create another movement. 5. Reject cancellation of CONFIRMED or EXPIRED
reservations in v1 unless it is a repeat of the same documented
transition. 6. Commit.

Important rollback detail: do not update a reservation to EXPIRED and
then raise an exception inside the same atomic block if the expiry
update must persist---the exception will roll back the update. Persist
the expiry/release transaction successfully, then return a conflict
response from the API layer.

Acceptance criteria: - State transitions update counters and ledger
atomically. - Repeated requests cannot double-release inventory. -
Invalid transitions have predictable errors. - A confirmed reservation
moves inventory from held to sold without increasing availability. -
Expired reservations cannot be confirmed.

### Phase 5 --- Expiry worker

Create a Django management command:

``` text
uv run python manage.py expire_reservations
```

It should process batches of PENDING reservations whose deadline has
passed.

Requirements: - Use timezone-aware comparisons. - Lock rows and recheck
status/deadline before expiring. - Reuse the same domain transition
logic as other operations where practical. - Release inventory, change
status, and create RELEASE movement in the same transaction. - Be safe
to run repeatedly and concurrently. - Avoid holding locks for a long
batch; process a bounded number of reservations at a time. - Establish
and document a scheduler interval, such as every minute, using cron or
another simple scheduler.

Confirmation must independently enforce the deadline. Correctness must
not depend on the scheduler having run.

Acceptance criteria: - Expiry releases held inventory exactly once. -
Re-running the command creates no duplicate movements. - A confirmation
racing with expiry produces one valid terminal state and consistent
counters. - Tests cover a past deadline and a future deadline.

### Phase 6 --- API endpoints and serializers

Use `/api/v1/` for all application endpoints.

#### Authentication

-   `POST /api/v1/auth/register/`
-   `POST /api/v1/auth/token/`
-   `POST /api/v1/auth/token/refresh/`

#### Events and ticket types

-   `GET /api/v1/events/` --- public, published events only
-   `GET /api/v1/events/{id}/` --- public, published events only
-   `POST /api/v1/events/` --- staff
-   `PATCH /api/v1/events/{id}/` --- staff
-   `POST /api/v1/events/{id}/ticket-types/` --- staff
-   `GET /api/v1/ticket-types/{id}/` --- public if associated event is
    published
-   `GET /api/v1/ticket-types/{id}/inventory/` --- staff-only inventory
    details

#### Reservations

-   `POST /api/v1/reservations/` --- authenticated customer
-   `GET /api/v1/reservations/` --- customer's own history; staff can
    inspect all
-   `GET /api/v1/reservations/{id}/` --- owner or staff
-   `POST /api/v1/reservations/{id}/confirm/` --- owner or authorized
    staff
-   `POST /api/v1/reservations/{id}/cancel/` --- owner or authorized
    staff
-   `GET /api/v1/reservations/{id}/movements/` --- owner or staff

#### Inventory ledger

-   `GET /api/v1/inventory-movements/` --- staff only

Do not add an endpoint that lets clients directly modify inventory
counters or write arbitrary ledger movements.

Request to create a reservation:

``` json
{
  "ticket_type": "TICKET-TYPE-UUID",
  "quantity": 2
}
```

The server derives the customer from the authenticated user and sets
status, price snapshot, and expiry. Never trust client-supplied
`customer`, `status`, `expires_at`, `unit_price`, or inventory counters.

Example response shape:

``` json
{
  "id": "RESERVATION-UUID",
  "ticket_type": "TICKET-TYPE-UUID",
  "quantity": 2,
  "unit_price": "1500.00",
  "total_price": "3000.00",
  "status": "pending",
  "expires_at": "2026-10-22T12:10:00Z"
}
```

This is illustrative; the actual API returns persisted UUIDs and
timestamps. Use decimal strings for money.

Document and test response status codes consistently: - `200 OK`:
successful reads or state actions returning a representation -
`201 Created`: successful reservation/event/ticket-type creation -
`400 Bad Request`: malformed or invalid input - `401 Unauthorized`:
missing/invalid authentication - `403 Forbidden` or `404 Not Found`:
unauthorized access, according to a deliberate non-disclosure policy -
`404 Not Found`: resource does not exist - `409 Conflict`: insufficient
inventory or an invalid state transition - `500 Internal Server Error`:
unexpected failures, without exposing stack traces or secrets

Use DRF serializers for validation and responses; views should call
services rather than reimplementing inventory logic.

Acceptance criteria: - Endpoints follow the API contract. - Customers
cannot set protected fields or access other customers' data. - No
endpoint bypasses transactional services. - Error shapes and status
codes are consistent. - Tests cover successful and failed API requests.

### Phase 7 --- Filtering and pagination

Support query parameters such as: - `status=pending` -
`event_id=<uuid>` - `ticket_type=<uuid>` -
`created_after=<ISO-8601 datetime>` -
`created_before=<ISO-8601 datetime>` - `page=2` - `page_size=20`

Staff may filter by `customer_id`; customers must never use this to view
another customer's records.

Requirements: - Use DRF pagination and `django-filter` or explicit
validated query filters. - Apply ownership scoping before filters. - Set
a maximum page size. - Use stable ordering, for example `-created_at`
plus a unique tie-breaker. - Validate date ranges and allowed ordering
fields. - Use appropriate `select_related()`/`prefetch_related()` to
avoid unnecessary queries.

Acceptance criteria: - Filters combine predictably. - Pagination
metadata is documented. - Customer queries remain scoped to their own
reservations. - Invalid filters return a documented response.

### Phase 8 --- OpenAPI and interactive documentation

Use `drf-spectacular` to generate the schema and serve: -
`GET /api/schema/` --- OpenAPI schema - `GET /api/docs/` --- Swagger
UI - `GET /api/redoc/` --- ReDoc

Annotate operations with summaries, descriptions, request/response
serializers, authentication requirements, examples, and error responses.
Explain the reservation lifecycle, expiry behavior, and inventory
concurrency guarantees. Add examples for registration, authentication,
event browsing, creating a reservation, confirmation, cancellation, and
error cases.

Use the Swagger UI **Authorize** feature to paste a JWT and try
protected endpoints. The API documentation is an interface for testing
the backend, not a substitute for a frontend.

Acceptance criteria: - Schema generation succeeds without unresolved
serializer/view warnings that affect the contract. - Swagger UI loads
and requests can be sent to the running API. - JWT authorization works
from Swagger. - ReDoc renders the endpoint reference. - Request and
response schemas match actual behavior. - No real credentials or
personal data appear in examples.

### Phase 9 --- Automated testing and concurrency proof

Use pytest/pytest-django or Django's test framework consistently. Use
PostgreSQL for integration tests that rely on locks and transactions.
SQLite is not an acceptable substitute for proving PostgreSQL row-lock
behavior.

Cover at least:

**Inventory and business rules** - Valid reservation succeeds. -
Zero/negative quantity fails. - Insufficient inventory fails without
partial writes. - Availability equals capacity minus held minus sold. -
Capacity cannot be lowered below held plus sold. - Price snapshot is
unchanged after ticket price changes.

**Lifecycle** - Pending reservation can be confirmed. - Pending
reservation can be cancelled. - Expired reservation releases
inventory. - Confirmation after expiry is rejected and the hold is
released. - Repeated cancel/confirm/expiry does not double-adjust
counters or duplicate movements. - Competing confirm and expiry
operations leave one terminal state.

**Transactions** - Force an exception after a counter update and prove
the counter, reservation, and ledger changes all roll back. - Force a
failure during ledger creation and prove the inventory update is rolled
back too.

**Authorization** - Anonymous access is rejected where required. -
Customer cannot read, confirm, or cancel another customer's
reservation. - Customer cannot access staff-only inventory or ledger
endpoints. - Registration cannot create staff users. - Staff can perform
permitted operations.

**Filtering/docs** - Pagination and filters return the correct
results. - Staff-only filters cannot leak data to customers. - OpenAPI
schema generation passes.

#### Concurrency test: the defining test

Given only five tickets remain, run 100 simultaneous attempts to reserve
one ticket using separate threads/workers and separate database
connections.

Expected: - Exactly five reservations succeed. - Ninety-five requests
fail with insufficient inventory. - `reserved_quantity + sold_quantity`
never exceeds capacity. - The number of successful reservations and
total held quantity agree. - No orphaned reservations or
duplicate/partial movements exist.

Use a transaction-capable test setup (`TransactionTestCase` or
transaction-enabled pytest-django tests), real PostgreSQL, separate
connections, and synchronization barriers where useful. Do not wrap all
workers in one shared transaction. Make the test repeatable and avoid
relying on arbitrary sleeps.

Acceptance criteria: - The full test suite passes against PostgreSQL. -
Concurrency test proves no overselling. - Rollback tests prove
atomicity. - Tests do not depend on production data or network services.

### Phase 10 --- README, reproducibility, and final review

The README must include: 1. Project purpose and scope 2. Tech stack 3.
Architecture and app responsibilities 4. Prerequisites (`uv`, Docker,
Docker Compose) 5. Environment setup and `.env.example` instructions 6.
How to start PostgreSQL 7. How to install/sync dependencies and run
migrations 8. How to create a staff account safely 9. How to run the API
and expiry command 10. Swagger, ReDoc, and schema URLs 11. Example
end-to-end API workflow 12. How to run tests, including PostgreSQL
concurrency tests 13. Inventory formula and state-transition diagram or
explanation 14. Explanation of `transaction.atomic()` and
`select_for_update()` 15. Trade-offs, known limitations, and
out-of-scope features

Final checks:

``` bash
uv run python manage.py check
uv run python manage.py makemigrations --check
uv run python manage.py migrate --check
uv run pytest
```

Run the concurrency/integration suite against the Compose PostgreSQL
database. Confirm the instructions work from a clean checkout. Verify
`.env`, database volumes, and credentials are handled safely.

## 7. Inventory and Concurrency Design Notes

### Why a normal check-then-update fails

Unsafe pattern: 1. Read available inventory without a lock. 2. Check
that requested quantity is available. 3. Update the counter.

Two transactions can read the same availability and both pass the check.
The total allocation can exceed capacity.

Correct pattern: - Start a database transaction with
`transaction.atomic()`. - Lock the relevant TicketType row with
`select_for_update()`. - Read current counters after the lock is
acquired. - Validate availability and update counters while holding the
lock. - Write reservation and ledger rows within the same transaction. -
Commit all changes together.

PostgreSQL row locks serialize competing modifications to the same
ticket type. A transaction waiting for the lock must re-evaluate
availability against the current committed state after obtaining the
lock.

Use the same locking discipline in confirmation, cancellation, expiry,
and capacity changes. Add database constraints as a second line of
defense.

### Expiry and transition races

The background expiry command is not the authority for whether a
reservation can be confirmed. The service must check the deadline under
lock.

If confirmation discovers that the reservation is expired: - Release the
hold and mark the reservation EXPIRED in a transaction. - Commit that
state change. - Return a conflict response after the transaction
completes.

Do not raise an exception inside the same atomic block after marking the
reservation expired if that exception would roll back the state change.

### Ledger invariants

For every reservation: - Creation creates exactly one HOLD movement. -
Successful confirmation creates exactly one SALE movement. - Successful
cancellation or expiry creates exactly one RELEASE movement. - A
reservation cannot have both SALE and RELEASE terminal movements. -
Repeated requests cannot create duplicate transition movements.

For each ticket type, the current counters must agree with the
reservation states: - `reserved_quantity` equals the sum of quantities
for PENDING reservations that have not been released or confirmed. -
`sold_quantity` equals the sum of quantities for CONFIRMED reservations
in v1. - Neither counter can be negative. - Their sum cannot exceed
capacity.

A future reconciliation management command could compare counters with
reservation/ledger history, but it is optional for v1.

## 8. Suggested Work Order and Time Budget

This is a target, not a reason to skip tests:

**Day 1** 1. Project, uv, Compose PostgreSQL, settings, custom user,
migrations 2. Domain models and constraints 3. Reservation creation
service and tests 4. Confirmation/cancellation services and tests 5.
Authentication and first API endpoints

**Day 2** 6. Expiry command and race handling 7. Remaining endpoints,
permissions, filtering, pagination 8. PostgreSQL transaction and
concurrency tests 9. OpenAPI/Swagger/ReDoc 10. README, clean-checkout
verification, and final review

If time runs short, prioritize correct inventory services, security, and
concurrency tests over extra endpoints or deployment polish.

## 9. Definition of Done

The project is complete when all of the following are true:

-   [ ] `uv sync` installs the locked environment.
-   [ ] Docker Compose starts PostgreSQL with persistent storage and a
    health check.
-   [ ] A fresh database can be migrated successfully.
-   [ ] Custom user model, events, ticket types, reservations, and
    movement ledger are implemented.
-   [ ] Reservation creation uses a transaction and PostgreSQL row
    locking.
-   [ ] Confirmation, cancellation, expiry, and capacity updates
    preserve inventory invariants.
-   [ ] Expiry works both through the scheduled command and when a late
    confirmation is attempted.
-   [ ] Customer/staff permissions and ownership checks are tested.
-   [ ] Reservation history filtering and pagination work.
-   [ ] Transaction rollback tests pass.
-   [ ] The 100-request/5-ticket PostgreSQL concurrency test proves no
    overselling.
-   [ ] Ledger records are append-only through the API.
-   [ ] Swagger UI and ReDoc load, and Swagger can send authenticated
    requests.
-   [ ] OpenAPI schemas and examples match actual responses.
-   [ ] README contains complete local setup and test instructions.
-   [ ] No secrets, tokens, or production customer data are committed.
-   [ ] All required tests pass.

## 10. Instructions for an AI Coding Agent

If an AI agent implements this plan, it must:

1.  Inspect the repository and existing files before making changes.
2.  Summarize the current state and propose a short phase-by-phase
    execution plan.
3.  Implement one phase at a time; do not perform a large, unreviewable
    rewrite.
4.  Preserve the scope and stack in this document: uv, Django REST
    Framework, PostgreSQL in Docker Compose, JWT, and drf-spectacular.
5.  Before changing the data model, confirm the custom user model is
    configured before initial migrations.
6.  Put inventory business logic in service functions, not duplicated
    across views or serializers.
7.  Use real PostgreSQL integration tests for row locking and
    concurrency; do not claim SQLite tests prove PostgreSQL concurrency
    correctness.
8.  Never weaken tests, remove constraints, or bypass locking merely to
    make a test pass.
9.  Run relevant tests after each phase and report the actual commands
    and results. Never claim a test passed if it was not run.
10. Explain important design choices and any deviation from this plan
    before proceeding.
11. Avoid adding payments, frontend code, Celery, Redis, microservices,
    or other out-of-scope features unless explicitly requested.
12. Finish with setup instructions, API docs URLs, test results, known
    limitations, and a list of files changed.

**Start by completing Phase 1 setup and configuration, then proceed
sequentially. Do not implement all phases in a single unreviewed pass.**
