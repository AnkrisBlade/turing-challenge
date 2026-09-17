"""La ingesta es el unico paso manual del despliegue: debe fallar con claridad."""

from __future__ import annotations

from pathlib import Path

import pytest

from mtg_assistant.rag.index import RulesIndex
from mtg_assistant.rag.ingest import build_index, main


def test_build_index_desde_txt(tmp_path: Path, rules_text: str) -> None:
    fuente = tmp_path / "reglamento.txt"
    fuente.write_text(rules_text, encoding="utf-8")
    destino = tmp_path / "rules.jsonl"

    index = build_index(fuente, destino)
    assert destino.exists()
    assert len(RulesIndex.load(destino)) == len(index)


def test_un_documento_vacio_aborta_con_mensaje(tmp_path: Path) -> None:
    fuente = tmp_path / "vacio.txt"
    fuente.write_text("", encoding="utf-8")
    with pytest.raises(SystemExit, match="No se extrajo"):
        build_index(fuente, tmp_path / "out.jsonl")


def test_cli_con_fichero_inexistente_devuelve_1(tmp_path: Path, capsys) -> None:
    assert main([str(tmp_path / "nope.pdf")]) == 1
    assert "No existe" in capsys.readouterr().err


def test_cli_feliz_imprime_el_recuento(tmp_path: Path, rules_text: str, capsys) -> None:
    fuente = tmp_path / "reglamento.txt"
    fuente.write_text(rules_text, encoding="utf-8")
    destino = tmp_path / "rules.jsonl"

    assert main([str(fuente), "-o", str(destino)]) == 0
    assert "con numero de regla" in capsys.readouterr().out
