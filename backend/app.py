import os

from authlib.integrations.starlette_client import OAuth, OAuthError
from fastapi import Depends, FastAPI, HTTPException, Request
from starlette.middleware.sessions import SessionMiddleware
from starlette.responses import RedirectResponse
from sqlalchemy.orm import Session
from fastapi.staticfiles import StaticFiles

from . import database, models, scheduler

models.Base.metadata.create_all(bind=database.engine)

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key=os.getenv("SESSION_SECRET", "change-me"))

oauth = OAuth()
TENANT_ID = os.getenv("TENANT_ID")
CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
oauth.register(
    name="azure",
    client_id=CLIENT_ID,
    client_secret=CLIENT_SECRET,
    server_metadata_url=f"https://login.microsoftonline.com/{TENANT_ID}/v2.0/.well-known/openid-configuration",
    client_kwargs={"scope": "openid profile email"},
)


@app.on_event("startup")
async def startup_event() -> None:
    scheduler.start_scheduler()


def get_current_user(
    request: Request, db: Session = Depends(database.get_db)
) -> models.User:
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401)
    user = db.get(models.User, user_id)
    if not user:
        raise HTTPException(status_code=401)
    return user


@app.get("/auth/login")
async def login(request: Request):
    redirect_uri = request.url_for("auth_callback")
    return await oauth.azure.authorize_redirect(request, redirect_uri)


@app.get("/auth/callback")
async def auth_callback(request: Request, db: Session = Depends(database.get_db)):
    try:
        token = await oauth.azure.authorize_access_token(request)
        user_info = await oauth.azure.parse_id_token(request, token)
    except OAuthError as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc))
    user = db.query(models.User).filter(models.User.oidc_sub == user_info["sub"]).first()
    if not user:
        user = models.User(
            oidc_sub=user_info["sub"],
            email=user_info.get("email"),
            name=user_info.get("name"),
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    request.session["user_id"] = user.id
    return RedirectResponse("/")


@app.get("/api/history")
def get_history(
    user_id: str | None = None,
    db: Session = Depends(database.get_db),
    _: models.User = Depends(get_current_user),
):
    query = db.query(models.PresenceRecord)
    if user_id:
        query = query.filter(models.PresenceRecord.user_id == user_id)
    records = query.order_by(models.PresenceRecord.collected_at.desc()).all()
    return [
        {
            "user_id": r.user_id,
            "display_name": r.display_name,
            "availability": r.availability,
            "activity": r.activity,
            "collected_at": r.collected_at.isoformat(),
        }
        for r in records
    ]


@app.get("/api/users")
def get_users(
    db: Session = Depends(database.get_db),
    _: models.User = Depends(get_current_user),
):
    users = db.query(models.PresenceRecord.user_id, models.PresenceRecord.display_name).distinct()
    return [
        {"user_id": user_id, "display_name": display_name}
        for user_id, display_name in users
    ]


app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")
