"""A config do Streamlit versionada (.streamlit/config.toml): excecao fora de try
nao pode mostrar tipo,
traceback nem caminho do servidor na tela (default do 1.58 = "full"): o detalhe
vai pro log do servico.
"""
import tomllib
from pathlib import Path

CONFIG = Path(__file__).parent.parent / ".streamlit" / "config.toml"


def _config() -> dict:
    return tomllib.loads(CONFIG.read_text(encoding="utf-8"))


def test_excecao_nao_capturada_nao_mostra_tipo_nem_traceback_na_tela():
    # chave ausente = default do Streamlit 1.58 = "full" (tipo + traceback + caminho)
    assert _config()["client"].get("showErrorDetails", "full") == "none"


def test_demais_opcoes_da_config_seguem_como_estavam():
    """CONTROLE: menu escondido e sem metrica de uso continuam."""
    config = _config()
    assert config["client"]["toolbarMode"] == "minimal"
    assert config["browser"]["gatherUsageStats"] is False
