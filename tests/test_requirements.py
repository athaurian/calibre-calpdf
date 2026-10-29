from __future__ import annotations

import pytest

from calpdf_plugin import requirements


def test_version_tuple_handles_suffixes():
    assert requirements.version_tuple("0.2.0") == (0, 2, 0)
    assert requirements.version_tuple("0.2.0rc1") == (0, 2, 0)
    assert requirements.version_tuple("1.10") == (1, 10, 0)
    assert requirements.version_tuple("nonsense") == (0, 0, 0)


def test_accepts_the_minimum_version(monkeypatch):
    monkeypatch.setattr(requirements, "version", lambda _: "0.2.0")

    assert requirements.calpdf_problem() is None


def test_reports_an_older_version(monkeypatch):
    monkeypatch.setattr(requirements, "version", lambda _: "0.1.0")

    problem = requirements.calpdf_problem()

    assert problem is not None
    assert "0.2.0 or newer" in problem
    assert "0.1.0 is installed" in problem


def test_reports_a_missing_metadata(monkeypatch):
    def missing(_):
        raise requirements.PackageNotFoundError

    monkeypatch.setattr(requirements, "version", missing)

    problem = requirements.calpdf_problem()

    assert problem is not None
    assert "metadata" in problem


def test_reports_an_import_failure(monkeypatch):
    def broken(_):
        raise ImportError("no pikepdf")

    monkeypatch.setattr(requirements.importlib, "import_module", broken)

    problem = requirements.calpdf_problem()

    assert problem is not None
    assert "no pikepdf" in problem


@pytest.fixture(autouse=True)
def _calpdf_importable(monkeypatch):
    monkeypatch.setattr(requirements.importlib, "import_module", lambda _: object())
