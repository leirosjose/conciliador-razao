"""ZIP em memoria: n PDFs -> n entradas, nomes corretos, colisao com
sufixo _2/_3 — nunca sobrescrita silenciosa (regra de ouro no pacote)."""
import io
import zipfile

from relatorio.pacote import zip_relatorios


def _abre(zip_bytes: bytes) -> zipfile.ZipFile:
    return zipfile.ZipFile(io.BytesIO(zip_bytes))


def test_n_arquivos_viram_n_entradas_com_conteudo_identico():
    pares = [("a.pdf", b"%PDF-a"), ("b.pdf", b"%PDF-b"), ("c.pdf", b"%PDF-c")]
    z = _abre(zip_relatorios(pares))
    assert z.namelist() == ["a.pdf", "b.pdf", "c.pdf"]
    for nome, conteudo in pares:
        assert z.read(nome) == conteudo


def test_colisao_de_nome_no_zip_ganha_sufixo():
    z = _abre(zip_relatorios([("golden_sintetico.pdf", b"%PDF-1"),
                              ("golden_sintetico.pdf", b"%PDF-2")]))
    assert z.namelist() == ["golden_sintetico.pdf", "golden_sintetico_2.pdf"]
    assert z.read("golden_sintetico.pdf") == b"%PDF-1"      # ordem de chegada preservada
    assert z.read("golden_sintetico_2.pdf") == b"%PDF-2"
