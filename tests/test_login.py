import pytest

from bankapp import services
from bankapp.errors import AuthError, LockedError


@pytest.fixture
def ann(db):
    return services.open_account(db, "Ann", "1234")


def wrong(db, number, times):
    for _ in range(times):
        with pytest.raises((AuthError, LockedError)):
            services.login(db, number, "0000")


def test_login_returns_token_for_the_account(db, ann):
    token = services.login(db, ann.number, "1234")
    assert services.account_for_token(db, token).id == ann.id


def test_wrong_pin_rejected_and_counted(db, ann):
    with pytest.raises(AuthError):
        services.login(db, ann.number, "0000")
    db.refresh(ann)
    assert ann.failed_attempts == 1 and not ann.locked


def test_unknown_account_gives_same_message_as_wrong_pin(db, ann):
    with pytest.raises(AuthError) as unknown:
        services.login(db, "9999999999", "1234")
    with pytest.raises(AuthError) as bad_pin:
        services.login(db, ann.number, "0000")
    assert str(unknown.value) == str(bad_pin.value)


def test_two_failures_do_not_lock(db, ann):
    wrong(db, ann.number, 2)
    db.refresh(ann)
    assert not ann.locked
    services.login(db, ann.number, "1234")  # still works


def test_third_failure_locks_the_account(db, ann):
    wrong(db, ann.number, 2)
    with pytest.raises(LockedError):
        services.login(db, ann.number, "0000")
    db.refresh(ann)
    assert ann.locked and ann.failed_attempts == 3


def test_locked_account_rejects_the_correct_pin(db, ann):
    wrong(db, ann.number, 3)
    with pytest.raises(LockedError):
        services.login(db, ann.number, "1234")


def test_success_resets_the_counter(db, ann):
    wrong(db, ann.number, 2)
    services.login(db, ann.number, "1234")
    db.refresh(ann)
    assert ann.failed_attempts == 0
    # Two more failures after a success must not lock: 3 in a row, not 3 in total.
    wrong(db, ann.number, 2)
    db.refresh(ann)
    assert not ann.locked


def test_failures_are_per_account(db, ann):
    bob = services.open_account(db, "Bob", "4321")
    wrong(db, ann.number, 3)
    services.login(db, bob.number, "4321")  # Bob unaffected


def test_unlock_restores_access(db, ann):
    wrong(db, ann.number, 3)
    services.unlock_account(db, ann.number)
    db.refresh(ann)
    assert not ann.locked and ann.failed_attempts == 0
    services.login(db, ann.number, "1234")
