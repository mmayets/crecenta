from unittest import mock

from django.core.cache import cache

from apps.core.ratelimit import hit


def test_ventana_fija():
    limits = [(2, 60), (3, 3600)]
    assert hit("u1", limits, now=0)
    assert hit("u1", limits, now=1)
    assert not hit("u1", limits, now=2)  # 3 > 2 por minuto
    assert not hit("u1", limits, now=61)  # nueva ventana de minuto, pero 4 > 3 por hora
    assert hit("u2", limits, now=0)  # cada clave es independiente


def test_clave_expirada_entre_add_e_incr():
    with mock.patch.object(cache, "incr", side_effect=ValueError):
        assert hit("u3", [(1, 60)], now=0)
