import os
from io import StringIO
from unittest import mock

import pytest
from django.conf import settings
from django.core.management import CommandError, call_command

from apps.core.management.commands.importar_parametros import parse_env
from apps.core.models import Parameter
from config.parameters import load_parameters


def test_parse_env_ignora_comentarios_y_quita_comillas():
    text = "# nota\nA=1\n\nB = 'dos'\nexport C=\"tres=3\"\nVACIO=\nsin_igual\n"
    assert parse_env(text) == {"A": "1", "B": "dos", "C": "tres=3", "VACIO": ""}


@pytest.mark.django_db
def test_importar_parametros_omite_la_conexion_y_respeta_no_sobrescribir(tmp_path):
    archivo = tmp_path / "x.env"
    archivo.write_text("DATABASE_URL=postgres://a:b@h/x\nAI_PROVIDER=fake\n", encoding="utf-8")
    call_command("importar_parametros", str(archivo), stdout=StringIO())
    assert list(Parameter.objects.values_list("key", "value")) == [("AI_PROVIDER", "fake")]

    archivo.write_text("AI_PROVIDER=gemini\nTIME_ZONE=UTC\n", encoding="utf-8")
    call_command("importar_parametros", str(archivo), "--no-sobrescribir", stdout=StringIO())
    assert Parameter.objects.get(key="AI_PROVIDER").value == "fake"
    call_command("importar_parametros", str(archivo), stdout=StringIO())
    assert Parameter.objects.get(key="AI_PROVIDER").value == "gemini"
    assert Parameter.objects.get(key="TIME_ZONE").value == "UTC"


def test_importar_parametros_archivo_inexistente():
    with pytest.raises(CommandError, match="No encuentro"):
        call_command("importar_parametros", "no-existe.env", stdout=StringIO())


@pytest.mark.django_db(transaction=True)
def test_load_parameters_no_pisa_variables_de_entorno():
    Parameter.objects.create(key="CRECENTA_TEST_NUEVA", value="tabla")
    Parameter.objects.create(key="CRECENTA_TEST_EXISTENTE", value="tabla")
    with mock.patch.dict(os.environ, {"CRECENTA_TEST_EXISTENTE": "entorno"}):
        load_parameters(settings.DATABASES["default"])
        assert os.environ["CRECENTA_TEST_NUEVA"] == "tabla"
        assert os.environ["CRECENTA_TEST_EXISTENTE"] == "entorno"


def test_load_parameters_tolera_una_base_inaccesible():
    load_parameters({"NAME": "no_existe", "USER": "nadie", "HOST": "localhost", "PORT": "1"})
