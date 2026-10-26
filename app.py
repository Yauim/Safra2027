"""
Sistema de apoio à decisão para estimativa da safra cafeeira do Espírito Santo
sob influência do El Niño 2026/2027.

Esta é a camada de interface. Ela não faz cálculo nem acessa o banco
diretamente: chama o pacote `safra` (formulario, banco, clima, calculo).

Rodar:  streamlit run app.py
"""
import hashlib
from pathlib import Path

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

from safra import banco, calculo, formulario
from safra import clima as fontes

RAIZ = Path(__file__).parent
PASTA = RAIZ / "dados"
VERDE, CEREJA, GRAO, CINZA, PALHA = "#2F5D3A", "#A3292E", "#6B4A2B", "#A7AFA5", "#D9C27A"
COR_FASE = alt.Scale(domain=["El Niño", "Neutro", "La Niña"], range=[CEREJA, CINZA, "#3D6F8E"])


def fmt(n, casas=0) -> str:
    if pd.isna(n):
        return "—"
    if abs(n) >= 1e6:
        return f"{n / 1e6:.2f} milhão".replace(".", ",") if abs(n) < 2e6 else f"{n / 1e6:.2f} milhões".replace(".", ",")
    return f"{n:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")


st.set_page_config(page_title="Safra 2027 · Espírito Santo", page_icon="☕", layout="wide")


# ----------------------------------------------------------------------------
# Dados
# ----------------------------------------------------------------------------
@st.cache_resource
def abrir_banco() -> banco.Banco:
    db = banco.Banco(RAIZ / "banco" / "safra.db")
    # Na primeira execução (ou após reinício do servidor) carrega o CSV oficial, se existir
    if db.total() == 0 and (PASTA / "respostas.csv").exists():
        db.importar(*formulario.ler_respostas(PASTA / "respostas.csv"))
    return db


@st.cache_resource
def banco_exemplo() -> banco.Banco:
    db = banco.Banco(RAIZ / "banco" / "exemplo.db")
    db.apagar_tudo()
    db.importar(*formulario.ler_respostas(PASTA / "produtores_EXEMPLO_ficticio.csv"))
    return db


carregar_clima_local = st.cache_data(fontes.clima_local)
baixar_clima_nasa = st.cache_data(ttl=60 * 60 * 24)(fontes.clima_nasa)
oni = st.cache_data(fontes.oni)(PASTA)
base = st.cache_data(fontes.base_historica)(PASTA)
fatores = calculo.fatores_cenario(base)
CENARIOS = list(fatores)
db = abrir_banco()


# ----------------------------------------------------------------------------
# Barra lateral
# ----------------------------------------------------------------------------
st.sidebar.title("☕ Safra 2027")
st.sidebar.caption("Espírito Santo · El Niño 2026/2027")
pagina = st.sidebar.radio("Tela", ["Clima e El Niño", "Histórico do Espírito Santo", "Estimativa por produtor",
                                   "Resumo do grupo", "Qualidade dos dados"])

st.sidebar.divider()
@st.cache_data(ttl=300, show_spinner="Lendo a planilha de respostas...")
def ler_planilha(url: str):
    return formulario.ler_respostas(url)


def endereco_planilha() -> str | None:
    try:
        return st.secrets.get("PLANILHA_CSV_URL")
    except Exception:
        return None


url_planilha = endereco_planilha()
if url_planilha:
    # Sincronização automática: a planilha do Google Forms é a fonte; o SQLite guarda a cópia de trabalho
    try:
        novas, atualizadas, removidas = db.sincronizar(*ler_planilha(url_planilha))
        st.sidebar.caption(f"Planilha sincronizada às {pd.Timestamp.now(tz='America/Sao_Paulo'):%H:%M} "
                           "(atualiza a cada 5 minutos).")
        if st.sidebar.button("Atualizar agora"):
            ler_planilha.clear()
            st.rerun()
    except Exception:
        st.sidebar.warning("Não foi possível ler a planilha agora; usando os dados já gravados no banco.")
else:
    arquivo = st.sidebar.file_uploader("Respostas dos produtores (CSV do Google Forms)", type="csv")
    if arquivo is not None:
        assinatura = hashlib.md5(arquivo.getvalue()).hexdigest()
        if st.session_state.get("ultimo_arquivo") != assinatura:
            try:
                novas, atualizadas = db.importar(*formulario.ler_respostas(arquivo))
                st.session_state["ultimo_arquivo"] = assinatura
                st.sidebar.success(f"{novas} respostas novas e {atualizadas} atualizadas no banco.")
            except ValueError as erro:
                st.sidebar.error(str(erro))

metodo = st.sidebar.selectbox("Produção base de cada produtor", list(calculo.METODOS),
                              format_func=calculo.METODOS.get)
excluir_graves = st.sidebar.toggle("Deixar de fora respostas com problema grave", value=True)
usar_api = st.sidebar.toggle("Atualizar clima pela API da NASA POWER", value=False)

if usar_api:
    try:
        clima_df = baixar_clima_nasa()
        st.sidebar.success(f"Clima atualizado até {clima_df['data'].max():%d/%m/%Y}")
    except Exception:
        clima_df = carregar_clima_local(PASTA)
        st.sidebar.warning("API indisponível; usando a cópia local.")
else:
    clima_df = carregar_clima_local(PASTA)
clima = clima_df

exemplo = db.total() == 0
fonte = banco_exemplo() if exemplo else db
larga = calculo.tabela_larga(fonte.produtores(), fonte.safras())
todos = calculo.estimar(larga, fatores, metodo)
alertas = calculo.checagens(todos)
graves = set(alertas.loc[alertas["gravidade"] == "Grave", "produtor"])
est = todos[~todos["codigo"].isin(graves)] if excluir_graves else todos

st.sidebar.divider()
if exemplo:
    st.sidebar.caption("Banco vazio: exibindo o exemplo fictício.")
else:
    st.sidebar.caption(f"Banco SQLite: {db.total()} respostas.")
    with st.sidebar.expander("Apagar respostas do banco"):
        if st.checkbox("Confirmo que quero apagar todas as respostas"):
            if st.button("Apagar respostas"):
                db.apagar_tudo()
                st.session_state.pop("ultimo_arquivo", None)
                st.rerun()

with st.sidebar.expander("Como a estimativa é calculada"):
    st.markdown(f"""
Para cada produtor: **sacas por mil pés na base × pés em produção em 2026 × (1 + fator do cenário)**.

Os fatores vêm do histórico do café no Espírito Santo (IBGE, 2003–2025), comparando a produtividade
de cada safra com a tendência de longo prazo:

- Sem efeito: 0%
- El Niño médio: {fatores['El Niño médio']:+.0%}
- El Niño forte (ONI ≥ 1,5): {fatores['El Niño forte']:+.0%}

Safra com 0 saca e pés em produção (lavoura recepada, por exemplo) fica fora da média.
""")

if exemplo:
    st.info("Os produtores exibidos são **fictícios**, gerados só para demonstrar o sistema. "
            "Configure o endereço da planilha ou envie o CSV das respostas na barra lateral para substituí-los.", icon="🧪")


# ----------------------------------------------------------------------------
# Tela 1 · Clima e El Niño
# ----------------------------------------------------------------------------
if pagina == "Clima e El Niño":
    st.title("O El Niño está passando pela florada")
    ultimo = oni.iloc[-1]
    ultimo_dia = clima.dropna(subset=["chuva_mm"])["data"].max()
    ano_atual = ultimo_dia.year

    # Mesma janela em todos os anos: de 1º de setembro até o dia/mês do último dado
    md = clima["data"].dt.month * 100 + clima["data"].dt.day
    limite = ultimo_dia.month * 100 + ultimo_dia.day
    janela = clima[(md >= 901) & (md <= limite)]
    por_ano = (
        janela.groupby(janela["data"].dt.year)
        .agg(chuva=("chuva_mm", "sum"), dias_35=("tmax_c", lambda s: (s >= 35).sum()))
        .reset_index(names="ano")
    )
    por_ano["oni"] = por_ano["ano"].map(oni[oni["trimestre"] == "SON"].set_index("ano")["oni"])
    por_ano.loc[por_ano["ano"] == ano_atual, "oni"] = ultimo["oni"]
    por_ano["fase"] = por_ano["oni"].map(calculo.fase_enos)
    atual = por_ano[por_ano["ano"] == ano_atual].iloc[0]
    hist = por_ano[por_ano["ano"] < ano_atual]

    c1, c2, c3 = st.columns(3)
    c1.metric(
        f"ONI ({ultimo['trimestre']} {ultimo['ano']})",
        f"{ultimo['oni']:+.2f} °C",
        f"El Niño {calculo.intensidade(ultimo['oni'])}",
        delta_color="off",
    )
    c2.metric(
        f"Chuva desde 1º/set ({ano_atual})",
        f"{atual['chuva']:.0f} mm",
        f"{atual['chuva'] - hist['chuva'].median():+.0f} mm vs. mediana",
    )
    c3.metric(
        "Dias acima de 35 °C",
        f"{atual['dias_35']:.0f}",
        f"{atual['dias_35'] - hist['dias_35'].median():+.0f} vs. mediana",
        delta_color="inverse",
    )
    st.caption(
        f"Comparação na mesma janela de todos os anos: 1º de setembro a {ultimo_dia:%d/%m}. "
        "Clima da região dos produtores participantes (Noroeste do ES). Fonte: NASA POWER (chuva corrigida) e NOAA/CPC."
    )

    st.subheader("Chuva e calor na florada, ano a ano")
    base_graf = alt.Chart(por_ano).encode(
        x=alt.X("ano:O", title=None),
        color=alt.Color("fase:N", scale=COR_FASE, title="Fase do ENOS"),
        tooltip=["ano", alt.Tooltip("chuva:Q", format=".0f"), "dias_35", alt.Tooltip("oni:Q", format="+.2f")],
    )
    g1 = base_graf.mark_bar().encode(y=alt.Y("chuva:Q", title="Chuva (mm)"))
    g2 = base_graf.mark_bar().encode(y=alt.Y("dias_35:Q", title="Dias ≥ 35 °C"))
    st.altair_chart(g1.properties(height=220), width="stretch")
    st.altair_chart(g2.properties(height=220), width="stretch")

    st.subheader("Índice ONI desde 2002")
    o = oni[oni["ano"] >= 2002].copy()
    o["mes"] = pd.to_datetime(o["ano"].astype(str) + "-" + (o.groupby("ano").cumcount() + 1).astype(str) + "-15")
    linha = alt.Chart(o).mark_area(line={"color": GRAO}, color=alt.Gradient(
        gradient="linear", stops=[alt.GradientStop(color=CEREJA, offset=0), alt.GradientStop(color="#3D6F8E", offset=1)],
        x1=1, x2=1, y1=0, y2=1), opacity=0.35).encode(
        x=alt.X("mes:T", title=None), y=alt.Y("oni:Q", title="Anomalia (°C)"),
        tooltip=["trimestre", "ano", alt.Tooltip("oni:Q", format="+.2f")],
    )
    limites = alt.Chart(pd.DataFrame({"y": [0.5, -0.5]})).mark_rule(strokeDash=[4, 4], color=CINZA).encode(y="y:Q")
    st.altair_chart((linha + limites).properties(height=240), width="stretch")
    st.caption("Acima de +0,5 °C: El Niño. Abaixo de −0,5 °C: La Niña.")


# ----------------------------------------------------------------------------
# Tela 2 · Histórico do Espírito Santo
# ----------------------------------------------------------------------------
elif pagina == "Histórico do Espírito Santo":
    st.title("Safras sob El Niño forte ficaram abaixo da tendência")
    h = base[base["sacas_ha_total"].notna()].copy()

    pontos = alt.Chart(h).mark_point(size=90, filled=True).encode(
        x=alt.X("safra:O", title="Safra"),
        y=alt.Y("sacas_ha_total:Q", title="Sacas por hectare"),
        color=alt.Color("fase_enos:N", scale=COR_FASE, title="ENOS na florada"),
        tooltip=["safra", "sacas_ha_total", "fase_enos", alt.Tooltip("oni_florada:Q", format="+.2f"),
                 alt.Tooltip("desvio_tendencia_pct:Q", format="+.1f")],
    )
    tend = alt.Chart(h).mark_line(color=GRAO, strokeDash=[6, 4]).encode(x="safra:O", y="tendencia_sacas_ha:Q")
    serie = alt.Chart(h).mark_line(color=CINZA, opacity=0.6).encode(x="safra:O", y="sacas_ha_total:Q")
    st.altair_chart((serie + tend + pontos).properties(height=320), width="stretch")
    st.caption("Produtividade do café no Espírito Santo (IBGE, Produção Agrícola Municipal). "
               "Linha tracejada: tendência de longo prazo (tecnologia, renovação de lavouras).")

    st.subheader("Desvio médio em relação à tendência")
    v = h[~h["dado_repetido_ibge"]]
    resumo = v.groupby("fase_enos")["desvio_tendencia_pct"].agg(["mean", "count"]).reset_index()
    graf = alt.Chart(resumo).mark_bar().encode(
        y=alt.Y("fase_enos:N", title=None, sort=["El Niño", "La Niña", "Neutro"]),
        x=alt.X("mean:Q", title="Desvio médio (%)"),
        color=alt.Color("fase_enos:N", scale=COR_FASE, legend=None),
        tooltip=[alt.Tooltip("mean:Q", format="+.1f"), alt.Tooltip("count:Q", title="safras")],
    )
    st.altair_chart(graf.properties(height=150), width="stretch")

    st.subheader("Safras sob El Niño")
    en = h[h["fase_enos"] == "El Niño"][["safra", "oni_florada", "intensidade_el_nino", "chuva_florada_set_nov_mm",
                                          "dias_acima_35c_florada", "sacas_ha_total", "desvio_tendencia_pct"]]
    st.dataframe(en.round(1).rename(columns={
        "oni_florada": "ONI", "intensidade_el_nino": "intensidade", "chuva_florada_set_nov_mm": "chuva florada (mm)",
        "dias_acima_35c_florada": "dias ≥35 °C", "sacas_ha_total": "sc/ha", "desvio_tendencia_pct": "desvio (%)"}),
        hide_index=True, width="stretch")

    st.subheader("Estimativa para o Espírito Santo em 2027")
    tend27, area, mun = calculo.cenarios_estado(base, fatores)
    cols = st.columns(len(fatores))
    for col, (nome, f) in zip(cols, fatores.items()):
        col.metric(nome, f"{mun[nome] / 1e6:.1f} mi sacas".replace(".", ","),
                   f"{tend27 * (1 + f):.1f} sc/ha", delta_color="off")
    st.caption(f"Tendência 2027: {tend27:.1f} sc/ha × {area:,.0f} ha colhidos em 2025.".replace(",", "."))




# ----------------------------------------------------------------------------
# Tela 3 · Estimativa por produtor
# ----------------------------------------------------------------------------
elif pagina == "Estimativa por produtor":
    st.title("Estimativa por produtor")
    rotulos = todos["codigo"] + " · " + todos["tipo_cafe"]
    escolha = st.selectbox("Produtor", rotulos)
    p = todos[rotulos == escolha].iloc[0]
    meus = alertas[alertas["produtor"] == p["codigo"]]
    for _, a in meus.iterrows():
        (st.error if a["gravidade"] == "Grave" else st.warning)(a["problema"])

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Pés de arábica", fmt(p["pes_arabica"]))
    c2.metric("Pés de conilon", fmt(p["pes_conilon"]))
    c3.metric("Irrigado", f"{fmt(p['irrigacao_pct'])}%")
    c4.metric("Altitude", str(p["altitude"] or "—").replace("De ", "").replace(" a ", "–"))

    anos = [str(a) for a in calculo.ANOS]
    barras = pd.DataFrame({
        "safra": anos + [f"2027 {c.replace('El Niño ', '').lower()}" for c in CENARIOS],
        "sacas": [p[f"sacas_{a}"] for a in calculo.ANOS] + [p[f"est_2027_{c}"] for c in CENARIOS],
        "tipo": ["Informado", "Informado (El Niño)", "Informado", "Informado"] + ["Estimado"] * len(CENARIOS),
    }).dropna(subset=["sacas"])
    g = alt.Chart(barras).mark_bar().encode(
        x=alt.X("safra:N", title=None, sort=None, axis=alt.Axis(labelAngle=0, labelOverlap=False, labelLimit=130)),
        y=alt.Y("sacas:Q", title="Sacas"),
        color=alt.Color("tipo:N", scale=alt.Scale(domain=["Informado (El Niño)", "Informado", "Estimado"],
                                                   range=[CEREJA, VERDE, PALHA]), title=None),
        tooltip=["safra", alt.Tooltip("sacas:Q", format=",.0f")])
    st.altair_chart(g.properties(height=280), width="stretch")

    prod = pd.DataFrame({"safra": anos, "sacas por mil pés": [p[f"prod_{a}"] for a in calculo.ANOS]}).dropna()
    st.altair_chart(alt.Chart(prod).mark_line(point=True, color=GRAO).encode(
        x=alt.X("safra:O", title=None, axis=alt.Axis(labelAngle=0)), y="sacas por mil pés:Q",
        tooltip=["safra", alt.Tooltip("sacas por mil pés:Q", format=".1f")]).properties(height=180),
        width="stretch")

    a, b = st.columns(2)
    a.metric("El Niño 2023/24: safra 2024 contra 2026", f"{fmt(p['efeito_2024_pct'])}%",
             help="Sacas por mil pés em 2024 comparadas com 2026, que está no mesmo ciclo bienal.")
    if pd.notna(p["expectativa_2027"]):
        b.metric("Expectativa do próprio produtor para 2027", f"{fmt(p['expectativa_2027'])} sacas",
                 f"{fmt(p['expectativa_2027'] - p['est_2027_Sem efeito'])} vs. cenário sem efeito", delta_color="off")
    st.caption(f"Safra 2026: {p['floradas_2026'] or '—'} florada(s), grãos {str(p['graos_2026'] or '—').lower()}, "
               f"broca {str(p['broca_2026'] or '—').lower()}. Safra 2027: florada {str(p['florada_atual'] or '—').lower()}, "
               f"{p['floradas_2027'] or '—'} florada(s) até agora, pegamento {str(p['pegamento_2027'] or '—').lower()}. "
               f"Origem dos números: {str(p['origem_dado'] or '—').lower()}.")


# ----------------------------------------------------------------------------
# Tela 4 · Resumo do grupo
# ----------------------------------------------------------------------------
elif pagina == "Resumo do grupo":
    st.title(f"{len(est)} produtores, {fmt(est['pes_2026'].sum())} de pés em produção")
    if excluir_graves and graves:
        st.caption(f"{len(graves)} resposta(s) com problema grave ficaram fora das somas. Veja a tela Qualidade dos dados.")

    cols = st.columns(len(CENARIOS))
    total_base = est["base_sacas"].sum()
    for col, c in zip(cols, CENARIOS):
        tot = est[f"est_2027_{c}"].sum()
        col.metric(f"2027 · {c}", f"{fmt(tot)} sacas",
                   f"{tot / total_base - 1:+.0%} vs. base" if fatores[c] else "base", delta_color="off")

    st.subheader("Produtividade do grupo ano a ano")
    bien = calculo.bienalidade_grupo(est)
    serie = pd.DataFrame({"safra": [str(a) for a in bien], "sacas por mil pés": list(bien.values())})
    serie["ciclo"] = np.where(serie["safra"].astype(int) % 2 == 1, "Ano ímpar (como 2027)", "Ano par")
    st.altair_chart(alt.Chart(serie).mark_bar().encode(
        x=alt.X("safra:N", title=None, axis=alt.Axis(labelAngle=0)), y="sacas por mil pés:Q",
        color=alt.Color("ciclo:N", scale=alt.Scale(range=[CINZA, VERDE]), title=None),
        tooltip=["safra", alt.Tooltip("sacas por mil pés:Q", format=".1f")]).properties(height=200),
        width="stretch")
    if pd.notna(bien[2025]) and pd.notna(bien[2026]):
        dif = bien[2026] / bien[2025] - 1
        st.caption(f"Em 2026 o grupo colheu {abs(dif):.0%} {'mais' if dif > 0 else 'menos'} por mil pés que em 2025. "
                   "Se os anos ímpares forem os de alta, a bienalidade favorece 2027; se forem os pares, pesa contra.")
    ef = est["efeito_2024_pct"].dropna()
    if len(ef):
        st.metric("El Niño 2023/24: safra 2024 contra 2026 (mediana do grupo)", f"{fmt(ef.median())}%",
                  f"{len(ef)} produtores com as duas safras", delta_color="off")

    st.subheader("Onde o impacto pesa mais")
    nomes = {"tipo_cafe": "Tipo de café", "irrigacao_faixa": "Irrigação", "altitude": "Altitude",
             "origem_dado": "Origem do dado"}
    recorte = st.radio("Agrupar por", list(nomes), horizontal=True, format_func=nomes.get)
    grp = est.groupby(recorte).agg(
        produtores=("codigo", "count"), pes=("pes_2026", "sum"),
        efeito_2024=("efeito_2024_pct", "median"), sacas_mil_pes=("prod_base", "median"),
        **{c: (f"est_2027_{c}", "sum") for c in CENARIOS}).reset_index()
    st.dataframe(grp.rename(columns={recorte: nomes[recorte], "pes": "pés", "efeito_2024": "2024 vs 2026 (%)",
                                     "sacas_mil_pes": "sacas por mil pés"}).round(1),
                 hide_index=True, width="stretch")

    st.subheader("O que os produtores viram no campo")
    campos = {"floradas_2026": "Floradas da safra 2026", "graos_2026": "Grãos no pé na colheita de 2026",
              "broca_2026": "Broca em 2026", "floradas_2027": "Floradas da safra 2027 até agora",
              "pegamento_2027": "Pegamento da florada atual", "florada_atual": "Florada atual"}
    c1, c2 = st.columns(2)
    for i, (campo, titulo) in enumerate(campos.items()):
        cont = est[campo].fillna("Sem resposta").value_counts().reset_index()
        cont.columns = ["resposta", "produtores"]
        (c1 if i % 2 == 0 else c2).altair_chart(alt.Chart(cont, title=titulo).mark_bar(color=GRAO).encode(
            y=alt.Y("resposta:N", title=None, sort="-x", axis=alt.Axis(labelLimit=260, labelOverlap=False)),
            x=alt.X("produtores:Q", title=None, axis=alt.Axis(tickMinStep=1)),
            tooltip=["resposta", "produtores"]).properties(height=34 * len(cont) + 90), width="stretch")
    st.caption("Desigualdade dos grãos contra broca na safra 2026 (número de produtores):")
    cruz = pd.crosstab(est["graos_2026"], est["broca_2026"])
    cruz.index.name, cruz.columns.name = "Grãos no pé", "Broca"
    st.dataframe(cruz, width="stretch")

    st.subheader("Todos os produtores")
    colunas = ["codigo", "tipo_cafe", "pes_2026", "irrigacao_pct", "prod_base", "base_sacas"] \
        + [f"est_2027_{c}" for c in CENARIOS] + ["expectativa_2027"]
    tabela = est[colunas].round(1)
    renomear = {"codigo": "produtor", "tipo_cafe": "tipo", "pes_2026": "pés 2026", "irrigacao_pct": "irrigado (%)",
                "prod_base": "sacas por mil pés", "base_sacas": "base (sacas)", "expectativa_2027": "expectativa",
                **{f"est_2027_{c}": f"2027 · {c}" for c in CENARIOS}}
    st.dataframe(tabela.rename(columns=renomear), hide_index=True, width="stretch")
    st.download_button("Baixar estimativas (CSV)", tabela.rename(columns=renomear).to_csv(index=False).encode("utf-8"),
                       "estimativas_2027.csv", "text/csv")


# ----------------------------------------------------------------------------
# Tela 5 · Qualidade dos dados
# ----------------------------------------------------------------------------
else:
    st.title("Qualidade dos dados")
    c1, c2, c3 = st.columns(3)
    c1.metric("Respostas", len(todos))
    c2.metric("Com problema grave", len(graves))
    c3.metric("Com ponto de atenção", alertas.loc[alertas["gravidade"] == "Atenção", "produtor"].nunique())
    if alertas.empty:
        st.success("Nenhum problema encontrado nas respostas.")
    else:
        st.dataframe(alertas, hide_index=True, width="stretch")
    st.markdown("""
**O que o sistema confere em cada resposta**

- Se os pés em produção em 2026 batem com a soma de pés de arábica e de conilon.
- Se o número de pés não salta mais de três vezes de um ano para outro, sinal de erro de digitação.
- Safras com pés em produção e nenhuma saca colhida, que costumam indicar lavoura recepada.
- Produtividade acima de 60 sacas por mil pés.
- Se há produção nos anos usados como base para estimar 2027.

Respostas com problema **grave** ficam fora das somas do grupo (pode ser desligado na barra lateral).
Para corrigir, ajuste o valor na planilha do Google Forms, baixe o CSV de novo e envie na barra lateral:
a resposta é atualizada no banco e mantém o mesmo código.
""")
