from bankapp import services


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def open_ann(client):
    return client.post("/accounts", json={"owner": "Ann", "pin": "1234"}).json()["number"]


def login(client, number, pin):
    return client.post("/login", json={"number": number, "pin": pin})


def test_login_then_me(client):
    number = open_ann(client)
    r = login(client, number, "1234")
    assert r.status_code == 200
    me = client.get("/me", headers=auth(r.json()["token"]))
    assert me.status_code == 200 and me.json() == {"number": number, "owner": "Ann"}


def test_wrong_pin_is_401(client):
    number = open_ann(client)
    r = login(client, number, "0000")
    assert r.status_code == 401


def test_third_wrong_pin_is_403_and_stays_locked(client):
    number = open_ann(client)
    assert login(client, number, "0000").status_code == 401
    assert login(client, number, "0000").status_code == 401
    assert login(client, number, "0000").status_code == 403
    assert login(client, number, "1234").status_code == 403


def test_me_requires_a_token(client):
    assert client.get("/me").status_code == 401
    assert client.get("/me", headers=auth("garbage")).status_code == 401


def test_admin_unlocks_via_api(client, admin):
    number = open_ann(client)
    for _ in range(3):
        login(client, number, "0000")
    assert login(client, number, "1234").status_code == 403

    token = client.post("/admin/login",
                        json={"username": "admin", "password": "admin123"}).json()["token"]
    r = client.post(f"/admin/accounts/{number}/unlock", headers=auth(token))
    assert r.status_code == 200 and r.json() == {"number": number, "locked": False}
    assert login(client, number, "1234").status_code == 200


def test_admin_login_wrong_password_is_401(client, admin):
    r = client.post("/admin/login", json={"username": "admin", "password": "x"})
    assert r.status_code == 401


def test_unlock_requires_admin_token(client, admin):
    number = open_ann(client)
    assert client.post(f"/admin/accounts/{number}/unlock").status_code == 401
    user_token = login(client, number, "1234").json()["token"]
    r = client.post(f"/admin/accounts/{number}/unlock", headers=auth(user_token))
    assert r.status_code == 401


def test_unlock_unknown_account_is_404(client, admin):
    token = client.post("/admin/login",
                        json={"username": "admin", "password": "admin123"}).json()["token"]
    r = client.post("/admin/accounts/0000000000/unlock", headers=auth(token))
    assert r.status_code == 404
