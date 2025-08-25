# Teamsy

Teamsy is a simple app that records Microsoft Teams availability for every user in a tenant. The
backend polls the Microsoft Graph hourly and stores each user's presence in a PostgreSQL database.
Users sign in via Azure AD (OIDC) to view the historical data through a small frontend.

## Backend

The backend is built with [FastAPI](https://fastapi.tiangolo.com/). It requires Azure AD
application credentials to query the Microsoft Graph API and authenticate users.

### Environment variables

- `TENANT_ID`
- `CLIENT_ID`
- `CLIENT_SECRET`
- `SESSION_SECRET` (random string for session cookies)
- `DATABASE_URL` (optional, defaults to `postgresql+psycopg2://postgres:postgres@db:5432/presence`)

### Running

```bash
pip install -r backend/requirements.txt
uvicorn backend.app:app --reload
```

### Docker

The repo includes a Docker setup that runs the API and a PostgreSQL database:

```bash
docker compose up --build
```

The app will be available at http://localhost:8000.

## Frontend

Open `frontend/index.html` in a browser while the backend is running. Select an employee to see
their availability history.
