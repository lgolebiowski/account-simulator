from contextlib import asynccontextmanager
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from sqlalchemy.orm import Session

from bankapp import config, services, statements
from bankapp.db import SessionLocal, init_db
from bankapp.errors import AuthError, BankError
from bankapp.models import Account, Admin


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    with SessionLocal() as db:
        services.ensure_admin(db)
    yield


app = FastAPI(title="Bank App", lifespan=lifespan)


@app.exception_handler(BankError)
async def bank_error_handler(request: Request, exc: BankError):
    return JSONResponse(status_code=exc.status_code, content={"detail": str(exc)})


STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def get_db():
    with SessionLocal() as db:
        yield db


# auto_error=False so a missing header gives our 401 instead of FastAPI's default 403.
bearer = HTTPBearer(auto_error=False)


def _token(creds: HTTPAuthorizationCredentials | None) -> str:
    if creds is None:
        raise AuthError("Not logged in.")
    return creds.credentials


def current_account(creds: HTTPAuthorizationCredentials | None = Depends(bearer),
                    db: Session = Depends(get_db)) -> Account:
    return services.account_for_token(db, _token(creds))


def current_admin(creds: HTTPAuthorizationCredentials | None = Depends(bearer),
                  db: Session = Depends(get_db)) -> Admin:
    return services.admin_for_token(db, _token(creds))


# ----------------------------------------------------------------- schemas

class OpenAccountRequest(BaseModel):
    owner: str
    pin: str


class AccountOut(BaseModel):
    number: str
    owner: str


class LoginRequest(BaseModel):
    number: str
    pin: str


class AdminLoginRequest(BaseModel):
    username: str
    password: str


class TokenOut(BaseModel):
    token: str


class AmountRequest(BaseModel):
    amount: Decimal


class TransferRequest(BaseModel):
    to: str
    amount: Decimal


class BalanceOut(BaseModel):
    balance: Decimal


class StatementLineOut(BaseModel):
    time: datetime
    type: str
    amount: Decimal          # signed: money out is negative
    other_account: str | None
    balance: Decimal


class StatementOut(BaseModel):
    start: date
    end: date
    timezone: str
    transactions: list[StatementLineOut]   # oldest first


class UnlockedOut(BaseModel):
    number: str
    locked: bool


# ------------------------------------------------------------------ routes

@app.post("/accounts", response_model=AccountOut, status_code=201)
def open_account(body: OpenAccountRequest, db: Session = Depends(get_db)):
    return services.open_account(db, body.owner, body.pin)


@app.post("/login", response_model=TokenOut)
def login(body: LoginRequest, db: Session = Depends(get_db)):
    return {"token": services.login(db, body.number, body.pin)}


@app.get("/me", response_model=AccountOut)
def me(account: Account = Depends(current_account)):
    return account


@app.post("/admin/login", response_model=TokenOut)
def admin_login(body: AdminLoginRequest, db: Session = Depends(get_db)):
    return {"token": services.admin_login(db, body.username, body.password)}


@app.post("/admin/accounts/{number}/unlock", response_model=UnlockedOut)
def unlock(number: str, _: Admin = Depends(current_admin),
           db: Session = Depends(get_db)):
    return services.unlock_account(db, number)


@app.get("/balance", response_model=BalanceOut)
def balance(account: Account = Depends(current_account),
            db: Session = Depends(get_db)):
    return {"balance": services.get_balance(db, account)}


@app.post("/deposit", response_model=BalanceOut)
def deposit(body: AmountRequest, account: Account = Depends(current_account),
            db: Session = Depends(get_db)):
    txn = services.deposit(db, account, body.amount)
    return {"balance": txn.balance_after}


@app.post("/withdraw", response_model=BalanceOut)
def withdraw(body: AmountRequest, account: Account = Depends(current_account),
             db: Session = Depends(get_db)):
    txn = services.withdraw(db, account, body.amount)
    return {"balance": txn.balance_after}


@app.post("/transfer", response_model=BalanceOut)
def transfer(body: TransferRequest, account: Account = Depends(current_account),
             db: Session = Depends(get_db)):
    txn = services.transfer(db, account, body.to, body.amount)
    return {"balance": txn.balance_after}


@app.get("/statement", response_model=StatementOut)
def statement(start: date | None = None, end: date | None = None,
              account: Account = Depends(current_account), db: Session = Depends(get_db)):
    st = statements.get_statement(db, account, start, end)
    return {"start": st.start, "end": st.end, "timezone": config.TIMEZONE,
            "transactions": st.lines}


@app.get("/statement.csv")
def statement_csv(start: date | None = None, end: date | None = None,
                  account: Account = Depends(current_account), db: Session = Depends(get_db)):
    st = statements.get_statement(db, account, start, end)
    filename = f"statement-{account.number}-{st.start}-to-{st.end}.csv"
    return Response(statements.to_csv(st), media_type="text/csv", headers={
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Cache-Control": "no-store",
    })


# ---------------------------------------------------------------- web page

@app.get("/", include_in_schema=False)
def home():
    # The page loads only its own files, so scripts and styles from anywhere else are refused.
    return FileResponse(STATIC_DIR / "index.html", headers={
        "Content-Security-Policy":
            "default-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "no-store",
    })


@app.post("/logout", status_code=204)
def logout(creds: HTTPAuthorizationCredentials | None = Depends(bearer),
           db: Session = Depends(get_db)):
    services.logout(db, _token(creds))
    return Response(status_code=204)
