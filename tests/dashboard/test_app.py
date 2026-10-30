"""Cada perfil do painel abre sem erro (Streamlit em modo de teste, sem navegador)."""

from pathlib import Path

import pytest

from sinergia.dashboard import views

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

APP = str(Path(views.__file__).with_name("app.py"))


@pytest.fixture
def env(make_app, monkeypatch) -> None:
    app = make_app()
    for key, value in {
        "DATA_DIR": str(app.settings.data_dir),
        "LLM_PROVIDER": "none",
        "CRM_VERIFIER": "local",
    }.items():
        monkeypatch.setenv(key, value)


@pytest.mark.parametrize("profile", views.PROFILES)
def test_every_profile_renders(env, profile: str) -> None:
    at = AppTest.from_file(APP, default_timeout=60).run()
    at.sidebar.radio[0].set_value(profile).run()
    assert not at.exception
    assert at.header[0].value


def test_sesmt_generates_a_report_from_the_screen(env) -> None:
    at = AppTest.from_file(APP, default_timeout=60).run()
    at.sidebar.radio[0].set_value("SESMT / médico do trabalho").run()
    at.button[0].click().run()
    assert not at.exception
    assert any("feito por: modelo" in caption.value for caption in at.caption)
