"""Leitura das respostas do Google Forms.

As colunas são reconhecidas pelo texto da pergunta (sem acento e sem diferença
entre maiúsculas e minúsculas), então mudar a ordem das perguntas ou corrigir
pequenos detalhes do título não quebra a leitura.
"""
import re
import unicodedata

import numpy as np
import pandas as pd

ANOS = [2023, 2024, 2025, 2026]


def _norm(txt: str) -> str:
    txt = unicodedata.normalize("NFKD", str(txt)).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", txt.lower()).strip()


def numero(valor) -> float:
    """Converte '9.000', '12000', '1.400.000' ou '12,5' em número."""
    if valor is None or (isinstance(valor, float) and np.isnan(valor)):
        return np.nan
    s = str(valor).strip().replace(" ", "")
    if s == "":
        return np.nan
    if re.fullmatch(r"\d{1,3}(\.\d{3})+", s):          # 9.000 / 1.400.000
        s = s.replace(".", "")
    elif "," in s:                                     # 12,5 / 1.200,5
        s = s.replace(".", "").replace(",", ".")
    s = re.sub(r"[^\d.]", "", s)
    try:
        return float(s)
    except ValueError:
        return np.nan


def _irrigacao(valor) -> float:
    t = _norm(valor)
    if not t or t == "nan":
        return np.nan
    m = re.search(r"(\d+)\s*%", t)
    if m:
        return float(m.group(1))
    for chave, pct in [("nenhuma", 0), ("menos", 25), ("mais ou menos", 50), ("mais da metade", 75),
                       ("toda", 100), ("so uma parte", 50), ("sim", 100), ("nao", 0)]:
        if chave in t:
            return float(pct)
    return np.nan


def _categoria(valor, regras: list[tuple[str, str]]) -> str | None:
    t = _norm(valor)
    if not t or t == "nan":
        return None
    for chave, rotulo in regras:
        if chave in t:
            return rotulo
    return str(valor).strip().capitalize()


FLORADAS = [("mais de 3", "Mais de 3"), ("3 ou mais", "3 ou mais"), ("ainda nao", "Ainda não floresceu"),
            ("nao sei", "Não sei"), ("1", "1"), ("2", "2"), ("3", "3")]
GRAOS = [("quase todos", "Quase todos maduros juntos"), ("mistura", "Mistura de verde e maduro"),
         ("muito desigual", "Muito desigual (flor, verde e maduro)"), ("nao sei", "Não sei")]
BROCA = [("menor", "Menor"), ("igual", "Igual"), ("maior", "Maior"), ("nao sei", "Não sei")]
PEGAMENTO = [("bom", "Bom"), ("regular", "Regular"), ("ruim", "Ruim"), ("ainda nao", "Ainda não dá para ver")]
FLORADA_ATUAL = [("boa", "Boa"), ("regular", "Regular"), ("fraca", "Fraca"), ("ainda nao", "Ainda não sei")]
ORIGEM = [("parte", "Parte anotação, parte memória"), ("anotacao", "Anotação ou registro"),
          ("registro", "Anotação ou registro"), ("memoria", "Memória")]


def _mapear_colunas(colunas) -> dict:
    """Associa cada coluna da planilha a um nome interno."""
    mapa = {}
    for col in colunas:
        n = _norm(col)
        m_pes = re.search(r"pes em producao em (\d{4})", n)
        m_sac = re.search(r"sacas colhidas em (\d{4})", n)
        if "carimbo" in n:
            mapa[col] = "data_resposta"
        elif "concorda" in n:
            mapa[col] = "consentimento"
        elif m_pes:
            mapa[col] = f"pes_{m_pes.group(1)}"
        elif m_sac:
            mapa[col] = f"sacas_{m_sac.group(1)}"
        elif "arabica" in n and "pes" in n:
            mapa[col] = "pes_arabica"
        elif "conilon" in n and "pes" in n:
            mapa[col] = "pes_conilon"
        elif "irrigad" in n:
            mapa[col] = "irrigacao_txt"
        elif "altitude" in n:
            mapa[col] = "altitude"
        elif "espera colher" in n:
            mapa[col] = "expectativa_2027"
        elif "de onde vieram" in n:
            mapa[col] = "origem_dado"
        elif "broca" in n:
            mapa[col] = "broca_2026"
        elif "graos no pe" in n:
            mapa[col] = "graos_2026"
        elif "pegamento" in n or "chumbinho" in n:
            mapa[col] = "pegamento_2027"
        elif "floradas" in n and "2027" in n:
            mapa[col] = "floradas_2027"
        elif "floradas" in n and "2026" in n:
            mapa[col] = "floradas_2026"
        elif "florada" in n and "como foi" in n:
            mapa[col] = "florada_atual"
    return mapa


def ler_respostas(arquivo) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Lê o CSV do Forms e devolve (produtores, safras) já padronizados.

    produtores: uma linha por resposta, com código P01, P02... pela ordem de envio.
    safras:     uma linha por produtor e ano (pés em produção e sacas colhidas).
    """
    bruto = pd.read_csv(arquivo, dtype=str)
    bruto = bruto.rename(columns=_mapear_colunas(bruto.columns))
    if "data_resposta" not in bruto:
        raise ValueError("A planilha não tem a coluna 'Carimbo de data/hora' do Google Forms.")
    if "consentimento" in bruto:
        bruto = bruto[bruto["consentimento"].fillna("").str.lower().str.startswith("sim")]

    bruto["data_resposta"] = pd.to_datetime(bruto["data_resposta"], dayfirst=True, errors="coerce")
    bruto = bruto.dropna(subset=["data_resposta"]).sort_values("data_resposta").reset_index(drop=True)

    def col(nome):
        return bruto[nome] if nome in bruto else pd.Series([None] * len(bruto))

    prod = pd.DataFrame({
        "data_resposta": bruto["data_resposta"].dt.strftime("%Y-%m-%d %H:%M:%S"),
        "pes_arabica": col("pes_arabica").map(numero),
        "pes_conilon": col("pes_conilon").map(numero),
        "irrigacao_pct": col("irrigacao_txt").map(_irrigacao),
        "altitude": col("altitude"),
        "florada_atual": col("florada_atual").map(lambda v: _categoria(v, FLORADA_ATUAL)),
        "floradas_2027": col("floradas_2027").map(lambda v: _categoria(v, FLORADAS)),
        "pegamento_2027": col("pegamento_2027").map(lambda v: _categoria(v, PEGAMENTO)),
        "floradas_2026": col("floradas_2026").map(lambda v: _categoria(v, FLORADAS)),
        "graos_2026": col("graos_2026").map(lambda v: _categoria(v, GRAOS)),
        "broca_2026": col("broca_2026").map(lambda v: _categoria(v, BROCA)),
        "expectativa_2027": col("expectativa_2027").map(numero),
        "origem_dado": col("origem_dado").map(lambda v: _categoria(v, ORIGEM)),
    })
    linhas = []
    for i, r in bruto.iterrows():
        for ano in ANOS:
            linhas.append({
                "data_resposta": prod.at[i, "data_resposta"], "ano": ano,
                "pes_producao": numero(r.get(f"pes_{ano}")), "sacas": numero(r.get(f"sacas_{ano}")),
            })
    safras = pd.DataFrame(linhas)
    safras = safras[~(safras["pes_producao"].isna() & safras["sacas"].isna())]
    return prod, safras
