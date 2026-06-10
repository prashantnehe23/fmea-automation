from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel
from typing import Dict
import time

app = FastAPI()

# 🚨 Hardcoded secret (VULNERABILITY #2)
API_KEY = "sk_live_123456789"

# In-memory "database"
wallets: Dict[str, float] = {
    "alice": 1000.0,
    "bob": 500.0
}


class TransferRequest(BaseModel):
    sender: str
    receiver: str
    amount: float


def authenticate(x_api_key: str):
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")


@app.get("/balance/{user}")
def get_balance(user: str, x_api_key: str = Header(...)):
    authenticate(x_api_key)

    if user not in wallets:
        raise HTTPException(status_code=404, detail="User not found")

    return {"user": user, "balance": wallets[user]}


@app.post("/transfer")
def transfer_funds(req: TransferRequest, x_api_key: str = Header(...)):
    authenticate(x_api_key)

    # 🚨 Missing input validation (VULNERABILITY #3)
    # No check for negative amounts, zero, or sender == receiver

    if req.sender not in wallets or req.receiver not in wallets:
        raise HTTPException(status_code=404, detail="Invalid users")

    # 🚨 Race condition starts here (VULNERABILITY #1)
    sender_balance = wallets[req.sender]

    # Simulate processing delay (makes race condition easier to exploit)
    time.sleep(0.5)

    if sender_balance < req.amount:
        raise HTTPException(status_code=400, detail="Insufficient funds")

    wallets[req.sender] -= req.amount
    wallets[req.receiver] += req.amount

    return {
        "status": "success",
        "from": req.sender,
        "to": req.receiver,
        "amount": req.amount
    }


@app.get("/health")
def health_check():
    return {"status": "ok"}
