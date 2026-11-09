def auth(token):
    return {"Authorization": f"Bearer {token}"}


def logged_in(client, owner="Ann", pin="1234"):
    number = client.post("/accounts", json={"owner": owner, "pin": pin}).json()["number"]
    token = client.post("/login", json={"number": number, "pin": pin}).json()["token"]
    return number, auth(token)


def test_balance_starts_at_zero(client):
    _, h = logged_in(client)
    r = client.get("/balance", headers=h)
    assert r.status_code == 200 and r.json() == {"balance": "0.00"}


def test_deposit_then_balance(client):
    _, h = logged_in(client)
    r = client.post("/deposit", json={"amount": "250.75"}, headers=h)
    assert r.status_code == 200 and r.json() == {"balance": "250.75"}
    assert client.get("/balance", headers=h).json() == {"balance": "250.75"}


def test_deposit_accepts_json_numbers(client):
    _, h = logged_in(client)
    assert client.post("/deposit", json={"amount": 10}, headers=h).json() == {"balance": "10.00"}
    assert client.post("/deposit", json={"amount": 0.1}, headers=h).json() == {"balance": "10.10"}


def test_bad_amounts_are_400(client):
    _, h = logged_in(client)
    for bad in ["0", "-5", "1.234"]:
        r = client.post("/deposit", json={"amount": bad}, headers=h)
        assert r.status_code == 400, bad
    assert client.get("/balance", headers=h).json() == {"balance": "0.00"}


def test_missing_or_garbage_amount_is_422(client):
    _, h = logged_in(client)
    assert client.post("/deposit", json={}, headers=h).status_code == 422
    assert client.post("/deposit", json={"amount": "abc"}, headers=h).status_code == 422


def test_money_endpoints_require_login(client):
    assert client.get("/balance").status_code == 401
    assert client.post("/deposit", json={"amount": "5"}).status_code == 401


def test_users_only_see_their_own_balance(client):
    _, ann = logged_in(client, "Ann")
    _, bob = logged_in(client, "Bob")
    client.post("/deposit", json={"amount": "100"}, headers=ann)
    assert client.get("/balance", headers=bob).json() == {"balance": "0.00"}


def fund(client, h, amount):
    client.post("/deposit", json={"amount": amount}, headers=h)


def test_withdraw(client):
    _, h = logged_in(client)
    fund(client, h, "500")
    r = client.post("/withdraw", json={"amount": "120.25"}, headers=h)
    assert r.status_code == 200 and r.json() == {"balance": "379.75"}
    assert client.get("/balance", headers=h).json() == {"balance": "379.75"}


def test_withdraw_more_than_balance_is_400(client):
    _, h = logged_in(client)
    fund(client, h, "50")
    r = client.post("/withdraw", json={"amount": "50.01"}, headers=h)
    assert r.status_code == 400 and "Insufficient funds" in r.json()["detail"]


def test_withdraw_over_daily_limit_is_400(client):
    _, h = logged_in(client)
    fund(client, h, "30000")
    assert client.post("/withdraw", json={"amount": "10000"}, headers=h).status_code == 200
    r = client.post("/withdraw", json={"amount": "0.01"}, headers=h)
    assert r.status_code == 400 and "Daily limit" in r.json()["detail"]
    assert client.get("/balance", headers=h).json() == {"balance": "20000.00"}


def test_withdraw_requires_login_and_valid_amount(client):
    assert client.post("/withdraw", json={"amount": "5"}).status_code == 401
    _, h = logged_in(client)
    assert client.post("/withdraw", json={"amount": "-5"}, headers=h).status_code == 400
    assert client.post("/withdraw", json={}, headers=h).status_code == 422


def test_transfer_api(client):
    _, ann = logged_in(client, "Ann", "1234")
    bob_no, bob = logged_in(client, "Bob", "4321")
    fund(client, ann, "500")
    r = client.post("/transfer", json={"to": bob_no, "amount": "125.25"}, headers=ann)
    assert r.status_code == 200 and r.json() == {"balance": "374.75"}
    assert client.get("/balance", headers=bob).json() == {"balance": "125.25"}


def test_transfer_api_errors(client):
    ann_no, ann = logged_in(client, "Ann", "1234")
    bob_no, _ = logged_in(client, "Bob", "4321")
    fund(client, ann, "100")
    post = lambda body: client.post("/transfer", json=body, headers=ann)
    assert post({"to": bob_no, "amount": "100.01"}).status_code == 400   # too much
    assert post({"to": "0000000000", "amount": "1"}).status_code == 400  # no such account
    assert post({"to": ann_no, "amount": "1"}).status_code == 400        # self
    assert post({"to": bob_no, "amount": "-1"}).status_code == 400
    assert post({"to": bob_no}).status_code == 422                       # missing amount
    assert client.get("/balance", headers=ann).json() == {"balance": "100.00"}


def test_transfer_requires_login(client):
    assert client.post("/transfer", json={"to": "1", "amount": "1"}).status_code == 401


def test_transfer_over_daily_limit_is_400(client):
    _, ann = logged_in(client, "Ann", "1234")
    bob_no, _ = logged_in(client, "Bob", "4321")
    fund(client, ann, "30000")
    assert client.post("/transfer", json={"to": bob_no, "amount": "10000"}, headers=ann).status_code == 200
    r = client.post("/withdraw", json={"amount": "0.01"}, headers=ann)  # shared limit
    assert r.status_code == 400 and "Daily limit" in r.json()["detail"]
