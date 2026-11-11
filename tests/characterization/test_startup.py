"""Characterization tests for account selection and webhook URL generation."""

import re

import pytest

import main_without_ssl as bot
from libs.URLgenerator import generate_random_url


class _RecordingTLAPI:
    instances = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        _RecordingTLAPI.instances.append(self)


@pytest.fixture
def recorded(monkeypatch):
    _RecordingTLAPI.instances = []
    monkeypatch.setattr(bot, "TLAPI", _RecordingTLAPI)
    return _RecordingTLAPI.instances


CREDENTIALS = {"env": "https://demo.tradelocker.com", "username": "u", "password": "p", "server": "s"}


def test_account_number_selects_account_by_number(recorded):
    bot.create_tl_instance(**CREDENTIALS, acc_num=2, acc_id=0)

    assert recorded[0].kwargs["acc_num"] == 2
    assert "account_id" not in recorded[0].kwargs


def test_account_id_selects_account_by_id(recorded):
    bot.create_tl_instance(**CREDENTIALS, acc_num=0, acc_id=77)

    assert recorded[0].kwargs["account_id"] == 77
    assert "acc_num" not in recorded[0].kwargs


def test_no_account_selector_uses_broker_default(recorded):
    bot.create_tl_instance(**CREDENTIALS, acc_num=0, acc_id=0)

    assert recorded[0].kwargs == {
        "environment": "https://demo.tradelocker.com",
        "username": "u",
        "password": "p",
        "server": "s",
    }


def test_both_account_selectors_are_rejected_without_logging_in(recorded):
    with pytest.raises(ValueError, match="only the account number or ID"):
        bot.create_tl_instance(**CREDENTIALS, acc_num=2, acc_id=77)

    assert recorded == []


def test_generated_webhook_url_has_two_lowercase_alphanumeric_segments():
    for _ in range(50):
        assert re.fullmatch(r"/[a-z0-9]{10,20}/[a-z0-9]{10,20}", generate_random_url())
