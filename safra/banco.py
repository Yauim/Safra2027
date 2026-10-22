"""Camada de dados: banco SQLite com duas tabelas.

produtores  uma linha por resposta, identificada só por código (P01, P02...)
safras      pés em produção e sacas colhidas por produtor e ano

Nenhum dado pessoal é guardado: nem nome, nem telefone, nem endereço.
"""
import sqlite3
from pathlib import Path

import pandas as pd

ESQUEMA = """
CREATE TABLE IF NOT EXISTS produtores (
    codigo           TEXT PRIMARY KEY,
    data_resposta    TEXT NOT NULL UNIQUE,
    pes_arabica      INTEGER,
    pes_conilon      INTEGER,
    irrigacao_pct    INTEGER,
    altitude         TEXT,
    florada_atual    TEXT,
    floradas_2027    TEXT,
    pegamento_2027   TEXT,
    floradas_2026    TEXT,
    graos_2026       TEXT,
    broca_2026       TEXT,
    expectativa_2027 INTEGER,
    origem_dado      TEXT
);
CREATE TABLE IF NOT EXISTS safras (
    codigo        TEXT NOT NULL REFERENCES produtores(codigo) ON DELETE CASCADE,
    ano           INTEGER NOT NULL,
    pes_producao  INTEGER,
    sacas         REAL,
    PRIMARY KEY (codigo, ano)
);
"""
CAMPOS = ["pes_arabica", "pes_conilon", "irrigacao_pct", "altitude", "florada_atual", "floradas_2027",
          "pegamento_2027", "floradas_2026", "graos_2026", "broca_2026", "expectativa_2027", "origem_dado"]


class Banco:
    def __init__(self, caminho: Path):
        caminho.parent.mkdir(parents=True, exist_ok=True)
        self.caminho = caminho
        with self._con() as con:
            con.executescript(ESQUEMA)

    def _con(self):
        con = sqlite3.connect(self.caminho)
        con.execute("PRAGMA foreign_keys = ON")
        return con

    def importar(self, produtores: pd.DataFrame, safras: pd.DataFrame) -> tuple[int, int]:
        """Grava as respostas. Respostas já importadas (mesmo carimbo) são atualizadas
        e mantêm o código; respostas novas recebem o próximo código livre.
        Devolve (novas, atualizadas)."""
        novas = atualizadas = 0
        with self._con() as con:
            existentes = dict(con.execute("SELECT data_resposta, codigo FROM produtores").fetchall())
            prox = 1 + max([int(c[1:]) for c in existentes.values()], default=0)
            codigos = {}
            for _, r in produtores.iterrows():
                valores = [None if pd.isna(r[c]) else (int(r[c]) if isinstance(r[c], float) else r[c]) for c in CAMPOS]
                if r["data_resposta"] in existentes:
                    codigo = existentes[r["data_resposta"]]
                    con.execute(f"UPDATE produtores SET {', '.join(c + '=?' for c in CAMPOS)} WHERE codigo=?",
                                valores + [codigo])
                    atualizadas += 1
                else:
                    codigo = f"P{prox:02d}"
                    prox += 1
                    con.execute(f"INSERT INTO produtores (codigo, data_resposta, {', '.join(CAMPOS)}) "
                                f"VALUES (?, ?, {', '.join('?' * len(CAMPOS))})", [codigo, r["data_resposta"]] + valores)
                    novas += 1
                codigos[r["data_resposta"]] = codigo
            for _, s in safras.iterrows():
                con.execute("INSERT OR REPLACE INTO safras (codigo, ano, pes_producao, sacas) VALUES (?, ?, ?, ?)",
                            [codigos[s["data_resposta"]], int(s["ano"]),
                             None if pd.isna(s["pes_producao"]) else int(s["pes_producao"]),
                             None if pd.isna(s["sacas"]) else float(s["sacas"])])
        return novas, atualizadas

    def sincronizar(self, produtores: pd.DataFrame, safras: pd.DataFrame) -> tuple[int, int, int]:
        """Deixa o banco igual à planilha: importa novas, atualiza as existentes e
        remove as que foram apagadas da planilha. Devolve (novas, atualizadas, removidas)."""
        novas, atualizadas = self.importar(produtores, safras)
        with self._con() as con:
            marcas = ",".join("?" * len(produtores)) or "''"
            removidas = con.execute(f"DELETE FROM produtores WHERE data_resposta NOT IN ({marcas})",
                                    list(produtores["data_resposta"])).rowcount
        return novas, atualizadas, removidas

    def produtores(self) -> pd.DataFrame:
        with self._con() as con:
            return pd.read_sql("SELECT * FROM produtores ORDER BY codigo", con)

    def safras(self) -> pd.DataFrame:
        with self._con() as con:
            return pd.read_sql("SELECT * FROM safras ORDER BY codigo, ano", con)

    def total(self) -> int:
        with self._con() as con:
            return con.execute("SELECT COUNT(*) FROM produtores").fetchone()[0]

    def apagar_tudo(self):
        with self._con() as con:
            con.execute("DELETE FROM safras")
            con.execute("DELETE FROM produtores")
