import re
import shutil
import subprocess
from pathlib import Path

import pytest

from bankapp import services
from bankapp.errors import AuthError

STATIC = Path(__file__).resolve().parent.parent / "bankapp" / "static"


def auth(token):
    return {"Authorization": f"Bearer {token}"}


# ------------------------------------------------------------- serving

def test_home_serves_the_page_with_security_headers(client):
    r = client.get("/")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert "<title>Python Bank</title>" in r.text
    csp = r.headers["content-security-policy"]
    assert "default-src 'self'" in csp and "frame-ancestors 'none'" in csp
    assert r.headers["x-content-type-options"] == "nosniff"


def test_assets_are_served(client):
    js = client.get("/static/app.js")
    css = client.get("/static/style.css")
    assert js.status_code == 200 and "javascript" in js.headers["content-type"]
    assert css.status_code == 200 and "text/css" in css.headers["content-type"]


def test_page_references_only_its_own_files():
    html = (STATIC / "index.html").read_text()
    refs = re.findall(r'(?:src|href)="([^"]+)"', html)
    assert refs and all(r.startswith("/static/") for r in refs)
    assert "<script>" not in html and "onclick=" not in html  # CSP forbids inline script


def test_every_element_id_the_script_uses_exists_in_the_page():
    html = (STATIC / "index.html").read_text()
    js = (STATIC / "app.js").read_text()
    page_ids = set(re.findall(r'id="([^"]+)"', html))
    used = set(re.findall(r'\$\("([^"]+)"\)', js)) | set(re.findall(r'"(view-[a-z-]+)"', js))
    # moneyForm("deposit-form", "deposit-amount", ...) passes ids as plain strings too
    for pair in re.findall(r'moneyForm\("([^"]+)", "([^"]+)"', js):
        used |= set(pair)
    assert used - page_ids == set()


def test_script_never_writes_server_text_as_html():
    js = (STATIC / "app.js").read_text()
    assert "innerHTML" not in js and "outerHTML" not in js
    assert "insertAdjacentHTML" not in js and "document.write" not in js


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_script_has_valid_syntax():
    subprocess.run(["node", "--check", str(STATIC / "app.js")], check=True)


# ------------------------------------------------------------- logout

def test_logout_ends_the_session(db, client):
    ann = services.open_account(db, "Ann", "1234")
    token = client.post("/login", json={"number": ann.number, "pin": "1234"}).json()["token"]
    assert client.get("/me", headers=auth(token)).status_code == 200

    assert client.post("/logout", headers=auth(token)).status_code == 204
    assert client.get("/me", headers=auth(token)).status_code == 401
    with pytest.raises(AuthError):
        services.account_for_token(db, token)


def test_logout_is_harmless_to_repeat_or_with_a_bad_token(client):
    assert client.post("/logout", headers=auth("nonsense")).status_code == 204


def test_logout_needs_a_token_header(client):
    assert client.post("/logout").status_code == 401


def test_admin_can_log_out_too(client, admin):
    token = client.post("/admin/login",
                        json={"username": "admin", "password": "admin123"}).json()["token"]
    assert client.post("/logout", headers=auth(token)).status_code == 204
    r = client.post("/admin/accounts/0000000000/unlock", headers=auth(token))
    assert r.status_code == 401


def test_logout_only_ends_that_session(db, client):
    ann = services.open_account(db, "Ann", "1234")
    login = lambda: client.post("/login", json={"number": ann.number, "pin": "1234"}).json()["token"]
    a, b = login(), login()
    client.post("/logout", headers=auth(a))
    assert client.get("/me", headers=auth(a)).status_code == 401
    assert client.get("/me", headers=auth(b)).status_code == 200
