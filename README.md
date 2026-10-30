# Ticketing System API

## Scheduled reservation expiry

Run the expiry worker every minute using cron or another scheduler:

```cron
* * * * * cd /path/to/ticketing-system-api && uv run python manage.py expire_reservations
```

The command processes at most 100 expired reservations by default. Use
`--batch-size` to change the bound:

```text
uv run python manage.py expire_reservations --batch-size 500
```
