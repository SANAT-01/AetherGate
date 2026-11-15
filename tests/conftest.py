import pytest


@pytest.fixture
def client():
    from django.test import AsyncClient

    return AsyncClient()
