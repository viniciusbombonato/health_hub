import pytest
from main import valid_phone_number
import phonenumbers

def test_phone_validation():
    phone = "(11) 99234-5678"

    assert valid_phone_number(phone) == "+5511992345678"
    assert valid_phone_number(phone, "BR") == "+5511992345678"

    # Erro
    assert valid_phone_number(phone, None) == None

    phone2 = "55 1234 1234"
    phone3 = "123 1234"

    assert valid_phone_number(phone2, None) == None
    assert valid_phone_number(phone3, "BR") == None
    