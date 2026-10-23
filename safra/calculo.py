"""Regras de negócio: cenários do El Niño, estimativa por produtor e checagens."""
import numpy as np
import pandas as pd

ANOS = [2023, 2024, 2025, 2026]
METODOS = {
    "impares": "Anos ímpares, 2023 e 2025 (mesmo ciclo bienal de 2027)",
    "recentes": "Média de 2025 e 2026 (neutraliza a bienalidade)",
    "s2025": "Só a safra 2025",
}


# --- cenários a partir do histórico do município -------------------------------
def fase_enos(v: float) -> str:
    if pd.isna(v):
        return "—"
    return "El Niño" if v >= 0.5 else ("La Niña" if v <= -0.5 else "Neutro")


def intensidade(v: float) -> str:
    if v < 0.5:
        return ""
    return "fraco" if v < 1 else "moderado" if v < 1.5 else "forte" if v < 2 else "muito forte"


def fatores_cenario(base: pd.DataFrame) -> dict:
    """Desvio médio da produtividade em relação à tendência, por cenário."""
    validas = base[base["desvio_tendencia_pct"].notna()]
    sem_rep = validas[~validas["dado_repetido_ibge"]]
    medio = sem_rep.loc[sem_rep["fase_enos"] == "El Niño", "desvio_tendencia_pct"].mean()
    forte = validas.loc[validas["oni_florada"] >= 1.5, "desvio_tendencia_pct"].mean()
    return {"Sem efeito": 0.0, "El Niño médio": round(medio / 100, 3), "El Niño forte": round(forte / 100, 3)}


def cenarios_municipio(base: pd.DataFrame, fatores: dict) -> tuple[float, float, dict]:
    h = base[base["sacas_ha_total"].notna()]
    t = h.dropna(subset=["tendencia_sacas_ha"])
    tend27 = float(np.polyval(np.polyfit(t["safra"], t["tendencia_sacas_ha"], 1), 2027))
    area = float(h.loc[h["safra"] == h["safra"].max(), "area_colhida_total_ha"].iloc[0])
    return tend27, area, {n: tend27 * (1 + f) * area for n, f in fatores.items()}


# --- produtores -------------------------------------------------------------------
def tabela_larga(produtores: pd.DataFrame, safras: pd.DataFrame) -> pd.DataFrame:
    """Uma linha por produtor com pés, sacas e sacas por mil pés de cada ano."""
    p = produtores.copy()
    for campo in ["pes_producao", "sacas"]:
        larga = safras.pivot(index="codigo", columns="ano", values=campo)
        for ano in ANOS:
            nome = ("pes_" if campo == "pes_producao" else "sacas_") + str(ano)
            p[nome] = p["codigo"].map(larga[ano]) if ano in larga else np.nan
    for ano in ANOS:
        pes = p[f"pes_{ano}"]
        # 0 saca com pés em produção costuma ser lavoura recepada: fica fora da média
        p[f"prod_{ano}"] = np.where((pes > 0) & (p[f"sacas_{ano}"] > 0), p[f"sacas_{ano}"] / pes * 1000, np.nan)
    tot = p["pes_arabica"].fillna(0) + p["pes_conilon"].fillna(0)
    parte_arab = np.where(tot > 0, p["pes_arabica"].fillna(0) / tot.replace(0, np.nan), np.nan)
    p["tipo_cafe"] = np.select([tot == 0, parte_arab >= 0.8, parte_arab <= 0.2],
                               ["Não informado", "Arábica", "Conilon"], "Misto")
    p["irrigacao_faixa"] = pd.cut(p["irrigacao_pct"], [-1, 0, 49, 100],
                                  labels=["Sequeiro", "Menos da metade", "Metade ou mais"]).astype(str)
    return p


def estimar(p: pd.DataFrame, fatores: dict, metodo: str) -> pd.DataFrame:
    e = p.copy()
    if metodo == "impares":
        e["prod_base"] = e[["prod_2023", "prod_2025"]].mean(axis=1)       # usa 2023 só se existir
    elif metodo == "recentes":
        e["prod_base"] = e[["prod_2025", "prod_2026"]].mean(axis=1)
    else:
        e["prod_base"] = e["prod_2025"]
    pes_ref = e["pes_2026"].fillna(e["pes_arabica"].fillna(0) + e["pes_conilon"].fillna(0))
    e["base_sacas"] = e["prod_base"] * pes_ref / 1000
    for nome, f in fatores.items():
        e[f"est_2027_{nome}"] = (e["base_sacas"] * (1 + f)).round()
    # El Niño 2023/24: compara 2024 com 2026, que está no mesmo ciclo bienal
    e["efeito_2024_pct"] = np.where((e["prod_2024"] > 0) & (e["prod_2026"] > 0),
                                    (e["prod_2024"] / e["prod_2026"] - 1) * 100, np.nan)
    return e


def bienalidade_grupo(e: pd.DataFrame) -> dict:
    """Sacas por mil pés do grupo em cada ano: mostra qual ciclo (par ou ímpar) é o de alta."""
    r = {}
    for ano in ANOS:
        ok = e[(e[f"pes_{ano}"] > 0) & e[f"sacas_{ano}"].notna()]
        r[ano] = ok[f"sacas_{ano}"].sum() / ok[f"pes_{ano}"].sum() * 1000 if len(ok) else np.nan
    return r


def checagens(e: pd.DataFrame) -> pd.DataFrame:
    """Lista problemas de preenchimento. 'Grave' tira o produtor das somas."""
    achados = []

    def add(c, grav, msg):
        achados.append({"produtor": c, "gravidade": grav, "problema": msg})

    for _, r in e.iterrows():
        c = r["codigo"]
        soma = (r["pes_arabica"] or 0) + (r["pes_conilon"] or 0)
        p26 = r["pes_2026"]
        if soma > 0 and pd.notna(p26) and p26 > 0:
            if p26 > soma * 1.5:
                add(c, "Grave", f"Pés em 2026 ({p26:,.0f}) muito acima de arábica + conilon ({soma:,.0f}): possível erro de digitação.")
            elif soma > p26 * 1.1:
                add(c, "Atenção", f"Arábica + conilon ({soma:,.0f}) acima dos pés em produção em 2026 ({p26:,.0f}): pode incluir pés novos ainda sem produção.")
            elif p26 > soma * 1.1:
                add(c, "Atenção", f"Pés em 2026 ({p26:,.0f}) acima de arábica + conilon ({soma:,.0f}).")
        for a, b in zip(ANOS[:-1], ANOS[1:]):
            pa, pb = r[f"pes_{a}"], r[f"pes_{b}"]
            if pd.notna(pa) and pd.notna(pb) and pa > 0 and pb > 0 and (pb / pa > 3 or pa / pb > 3):
                add(c, "Grave", f"Pés saltam de {pa:,.0f} em {a} para {pb:,.0f} em {b}: possível erro de digitação.")
        for ano in ANOS:
            if r[f"pes_{ano}"] > 0 and r[f"sacas_{ano}"] == 0:
                add(c, "Atenção", f"{ano}: {r[f'pes_{ano}']:,.0f} pés em produção e 0 sacas colhidas.")
            if r[f"prod_{ano}"] > 60:
                add(c, "Atenção", f"{ano}: {r[f'prod_{ano}']:.0f} sacas por mil pés, acima do esperado.")
        if not (r["base_sacas"] > 0):
            add(c, "Grave", "Sem produção nos anos usados como base: não é possível estimar 2027.")
    df = pd.DataFrame(achados, columns=["produtor", "gravidade", "problema"])
    df["problema"] = df["problema"].str.replace(",", ".")
    return df
