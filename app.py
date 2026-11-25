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
AZUL = "#3D6F8E"
COR_FASE = alt.Scale(domain=["El Niño", "Neutro", "La Niña"], range=[CEREJA, CINZA, AZUL])


def estilo(grafico, fonte=15):
    """Fontes maiores e visual limpo, pensado para o gráfico continuar legível em print."""
    return (
        grafico.configure_axis(labelFontSize=fonte, titleFontSize=fonte, labelColor="#333", titleColor="#333",
                               titleFontWeight="normal", domainColor="#999", tickColor="#999", gridColor="#eee")
        .configure_legend(labelFontSize=fonte, titleFontSize=fonte, symbolSize=180)
        .configure_title(fontSize=fonte + 2, anchor="start", color="#222", offset=8)
        .configure_text(fontSize=fonte - 3)
        .configure_view(stroke=None)
    )


def legenda_fases() -> str:
    """Legenda única (HTML) para os dois gráficos lado a lado."""
    itens = [("El Niño", CEREJA), ("Neutro", CINZA), ("La Niña", AZUL)]
    return " &nbsp;&nbsp; ".join(
        f'<span style="font-size:1.05rem"><span style="display:inline-block;width:14px;height:14px;'
        f'background:{cor};border-radius:2px;vertical-align:-1px"></span> {nome}</span>'
        for nome, cor in itens
    )


def fmt(n, casas=0) -> str:
    if pd.isna(n):
        return "—"
    if abs(n) >= 1e6:
        return f"{n / 1e6:.2f} milhão".replace(".", ",") if abs(n) < 2e6 else f"{n / 1e6:.2f} milhões".replace(".", ",")
    return f"{n:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")


st.set_page_config(page_title="Safra 2027 · Espírito Santo", page_icon="☕", layout="wide")
# Legendas (st.caption) mais escuras e um pouco maiores, para lerem bem no print
st.markdown("""<style>
[data-testid="stCaptionContainer"] { opacity: 1 !important; }
[data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] * { color: #3a3a3a !important; font-size: 0.95rem !important; }
[data-testid="stCaptionContainer"] strong { color: #111 !important; }
</style>""", unsafe_allow_html=True)


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
        st.sidebar.success(f"Clima atualizado até {clima_df.dropna(subset=['chuva_mm'])['data'].max():%d/%m/%Y}")
    except Exception:
        clima_df = carregar_clima_local(PASTA)
        st.sidebar.warning("API indisponível; usando a cópia local.")
else:
    clima_df = carregar_clima_local(PASTA)
clima = clima_df

sem_respostas = db.total() == 0
if not sem_respostas:
    larga = calculo.tabela_larga(db.produtores(), db.safras())
    todos = calculo.estimar(larga, fatores, metodo)
    alertas = calculo.checagens(todos)
    graves = set(alertas.loc[alertas["gravidade"] == "Grave", "produtor"])
    est = todos[~todos["codigo"].isin(graves)] if excluir_graves else todos

st.sidebar.divider()
if sem_respostas:
    st.sidebar.caption("Banco SQLite: nenhuma resposta ainda.")
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

if sem_respostas and pagina in ("Estimativa por produtor", "Resumo do grupo", "Qualidade dos dados"):
    st.title(pagina)
    st.info("Ainda não há respostas de produtores no banco. Configure o endereço da planilha do "
            "Google Forms ou envie o CSV das respostas na barra lateral.", icon="📋")
    st.stop()


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
        f"Comparação na **mesma janela de todos os anos: 1º de setembro a {ultimo_dia:%d/%m}**. "
        "Clima da região dos produtores participantes (**Noroeste do ES**). "
        "Fonte: **NASA POWER** (chuva corrigida) e **NOAA/CPC**."
    )

    st.subheader("Chuva e calor na florada, ano a ano")
    st.markdown(legenda_fases(), unsafe_allow_html=True)
    # Anos curtos ('02, '03...) na horizontal: cabem lado a lado sem girar o texto
    eixo_ano = alt.X("ano:O", title=None, axis=alt.Axis(labelAngle=0, labelExpr="\"'\" + slice(datum.label, 2)",
                                                         ticks=False, labelPadding=6))
    base_graf = alt.Chart(por_ano).encode(
        x=eixo_ano,
        color=alt.Color("fase:N", scale=COR_FASE, legend=None),
        tooltip=["ano", alt.Tooltip("chuva:Q", format=".0f"), "dias_35", alt.Tooltip("oni:Q", format="+.2f")],
    )

    def barras(campo, titulo, formato):
        y = alt.Y(f"{campo}:Q", title=None, axis=alt.Axis(tickCount=4, domain=False, ticks=False))
        b = base_graf.mark_bar(cornerRadiusTopLeft=2, cornerRadiusTopRight=2).encode(y=y)
        # Valor só no ano atual, em destaque
        rotulo = base_graf.transform_filter(alt.datum.ano == ano_atual).mark_text(
            dy=-8, fontWeight="bold", color="#222").encode(y=y, text=alt.Text(f"{campo}:Q", format=formato))
        return estilo((b + rotulo).properties(height=210, title=titulo))

    g1, g2 = st.columns(2)
    g1.altair_chart(barras("chuva", "Chuva (mm)", ".0f"), width="stretch")
    g2.altair_chart(barras("dias_35", "Dias com máxima ≥ 35 °C", ".0f"), width="stretch")

    st.subheader("Índice ONI desde 2002")
    o = oni[oni["ano"] >= 2002].copy()
    o["mes"] = pd.to_datetime(o["ano"].astype(str) + "-" + (o.groupby("ano").cumcount() + 1).astype(str) + "-15")
    linha = alt.Chart(o).mark_area(line={"color": GRAO, "strokeWidth": 2}, color=alt.Gradient(
        gradient="linear", stops=[alt.GradientStop(color=CEREJA, offset=0), alt.GradientStop(color=AZUL, offset=1)],
        x1=1, x2=1, y1=0, y2=1), opacity=0.35).encode(
        x=alt.X("mes:T", title=None, axis=alt.Axis(format="%Y", tickCount={"interval": "year", "step": 2},
                                                   labelAngle=0, grid=False)),
        y=alt.Y("oni:Q", title="ONI (°C)", axis=alt.Axis(values=[-2, -1, 0, 1, 2, 3], labelOverlap=False, domain=False, ticks=False)),
        tooltip=["trimestre", "ano", alt.Tooltip("oni:Q", format="+.2f")],
    )
    faixas = pd.DataFrame({"y": [0.5, -0.5], "nome": ["El Niño", "La Niña"]})
    limites = alt.Chart(faixas).mark_rule(strokeDash=[4, 4], color=CINZA).encode(y="y:Q")
    nomes_faixa = sum((alt.Chart(faixas.iloc[[i]]).mark_text(align="left", x=4, dy=dy, color="#666").encode(
        y="y:Q", text="nome:N") for i, dy in [(0, -9), (1, 11)]), alt.LayerChart())
    agora = alt.Chart(o.tail(1)).encode(x="mes:T", y="oni:Q")
    ponto = agora.mark_point(filled=True, size=90, color=CEREJA) + agora.mark_text(
        align="right", dx=-10, dy=-4, fontWeight="bold", color=CEREJA).encode(text=alt.Text("oni:Q", format="+.2f"))
    st.altair_chart(estilo((linha + limites + nomes_faixa + ponto).properties(height=200)), width="stretch")
    st.caption("Acima de **+0,5 °C: El Niño**. Abaixo de **−0,5 °C: La Niña**.")


# ----------------------------------------------------------------------------
# Tela 2 · Histórico do Espírito Santo
# ----------------------------------------------------------------------------
elif pagina == "Histórico do Espírito Santo":
    st.title("Safras sob El Niño forte ficaram abaixo da tendência")
    h = base[base["desvio_tendencia_pct"].notna()]
    v = h[~h["dado_repetido_ibge"]]
    grupos = [
        ("El Niño", v[v["fase_enos"] == "El Niño"], CEREJA),
        ("Neutro", v[v["fase_enos"] == "Neutro"], CINZA),
        ("La Niña", v[v["fase_enos"] == "La Niña"], AZUL),
    ]
    resumo = pd.DataFrame([{"grupo": g, "desvio": d["desvio_tendencia_pct"].mean(), "n": len(d), "cor": cor,
                            "anos": ", ".join(d["safra"].astype(int).astype(str))} for g, d, cor in grupos])
    resumo["rotulo"] = resumo.apply(lambda r: f"{r['desvio']:+.1f}%".replace(".", ",") + f" ({r['n']})", axis=1)

    # --- Produtividade ano a ano (esquerda) e desvio médio por fase (direita) ---
    col_prod, col_desv = st.columns([1.15, 1], gap="large")
    hp = base[base["sacas_ha_total"].notna()].copy()
    hp["forte"] = hp["oni_florada"] >= 1.5
    x_safra = alt.X("safra:O", title=None, axis=alt.Axis(labelAngle=0, labelExpr="\"'\" + slice(datum.label, 2)",
                                                          ticks=False, labelPadding=6, grid=False))
    y_prod = alt.Y("sacas_ha_total:Q", title=None, scale=alt.Scale(zero=False), axis=alt.Axis(tickCount=5, domain=False))
    serie = alt.Chart(hp).mark_line(color=CINZA, strokeWidth=2).encode(x=x_safra, y=y_prod)
    tend = alt.Chart(hp).mark_line(color=GRAO, strokeDash=[6, 4], strokeWidth=2).encode(
        x=x_safra, y="tendencia_sacas_ha:Q")
    pontos = alt.Chart(hp).mark_point(filled=True, opacity=1).encode(
        x=x_safra, y=y_prod, color=alt.Color("fase_enos:N", scale=COR_FASE, legend=None),
        size=alt.condition("datum.forte", alt.value(220), alt.value(80)),
        stroke=alt.condition("datum.forte", alt.value("#222"), alt.value(None)),
        tooltip=["safra", "sacas_ha_total", "tendencia_sacas_ha", "fase_enos",
                 alt.Tooltip("oni_florada:Q", format="+.2f"), alt.Tooltip("desvio_tendencia_pct:Q", format="+.1f")])
    nota = alt.Chart(hp[hp["forte"]]).mark_text(dy=24, fontWeight="bold", fontSize=14, color="#6E1A1E").transform_calculate(
        rotulo="format(datum.desvio_tendencia_pct, '.0f') + '%'").encode(x=x_safra, y=y_prod, text="rotulo:N")
    with col_prod:
        st.subheader("Produtividade do café no ES (sacas/ha)")
        st.markdown(legenda_fases() + ' &nbsp;&nbsp; <span style="font-size:1.05rem">'
                    f'<span style="color:{GRAO};font-weight:700">- - -</span> tendência</span>',
                    unsafe_allow_html=True)
        st.altair_chart(estilo((serie + tend + pontos + nota).properties(height=250), fonte=15), width="stretch")
        st.caption("Pontos grandes com contorno: **El Niño forte**, com o desvio (%) logo abaixo. "
                   "Linha tracejada: tendência de longo prazo (tecnologia, renovação de lavouras).")

    col_desv.subheader("Desvio médio em relação à tendência")
    y = alt.Y("grupo:N", title=None, sort=list(resumo["grupo"]), axis=alt.Axis(labelFontWeight="bold", labelPadding=8, labelLimit=220))
    x = alt.X("desvio:Q", title=None, scale=alt.Scale(domain=[-9, 9]),
              axis=alt.Axis(values=[-5, 0, 5], labelExpr="datum.value + '%'"))
    barras_desvio = alt.Chart(resumo).mark_bar(height=36, cornerRadius=2).encode(
        y=y, x=x, color=alt.Color("cor:N", scale=None),
        tooltip=["grupo", alt.Tooltip("desvio:Q", format="+.1f"), alt.Tooltip("n:Q", title="safras"), "anos"])
    rot_neg = alt.Chart(resumo[resumo["desvio"] < 0]).mark_text(align="right", dx=-8, fontWeight="bold", fontSize=16).encode(
        y=y, x=x, text="rotulo:N")
    rot_pos = alt.Chart(resumo[resumo["desvio"] >= 0]).mark_text(align="left", dx=8, fontWeight="bold", fontSize=16).encode(
        y=y, x=x, text="rotulo:N")
    zero = alt.Chart(pd.DataFrame({"x": [0]})).mark_rule(color="#333", strokeWidth=1.5).encode(x="x:Q")
    col_desv.markdown("&nbsp;", unsafe_allow_html=True)
    col_desv.altair_chart(estilo((barras_desvio + zero + rot_neg + rot_pos).properties(height=230), fonte=15),
                          width="stretch")
    col_desv.caption("Média por fase do ENOS na florada; entre parênteses, o número de safras. "
               "Desvio de cada safra em relação à tendência de longo prazo da produtividade (sacas/ha) do café no "
               "Espírito Santo. Fonte: **IBGE**, Produção Agrícola Municipal, 2003–2025; ONI: **NOAA/CPC**.")

    st.subheader("Estimativa para o Espírito Santo em 2027")
    tend27, area, mun = calculo.cenarios_estado(base, fatores)
    cols = st.columns(len(fatores))
    for col, (nome, f) in zip(cols, fatores.items()):
        with col.container(border=True):
            st.metric(nome, f"{mun[nome] / 1e6:.1f} mi sacas".replace(".", ","),
                      f"{tend27 * (1 + f):.1f} sc/ha · {f:+.1%}".replace(".", ","), delta_color="off",
                      delta_arrow="off")
    st.caption(f"**Tendência 2027: {fmt(tend27, 1)} sc/ha** × **{fmt(area)} ha** colhidos em 2025. "
               "Cada cenário aplica à tendência o desvio médio do histórico.")
    # Números das estimativas maiores, para o print
    st.markdown("<style>[data-testid='stMetricValue']{font-size:2.6rem}"
                "[data-testid='stMetricLabel'] p{font-size:1.15rem;font-weight:600}</style>",
                unsafe_allow_html=True)


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

    # --- Ficha do produtor ---
    ficha = [("Pés de arábica", fmt(p["pes_arabica"])), ("Pés de conilon", fmt(p["pes_conilon"])),
             ("Irrigado", f"{fmt(p['irrigacao_pct'])}%"),
             ("Altitude", str(p["altitude"] or "—").replace("De ", "").replace(" a ", "–"))]
    for col, (rotulo, valor) in zip(st.columns(4), ficha):
        col.container(border=True).metric(rotulo, valor)

    # --- Gráficos: sacas (esquerda) e sacas por mil pés (direita) ---
    anos = [str(a) for a in calculo.ANOS]
    nomes_cen = [c.replace("El Niño ", "").lower() for c in CENARIOS]
    barras = pd.DataFrame({
        "safra": anos + [f"2027 {n}" for n in nomes_cen],
        "eixo": anos + [f"2027|{n}" for n in nomes_cen],
        "sacas": [p[f"sacas_{a}"] for a in calculo.ANOS] + [p[f"est_2027_{c}"] for c in CENARIOS],
        "tipo": ["Informado", "Informado (El Niño)", "Informado", "Informado"] + ["Estimado"] * len(CENARIOS),
    }).dropna(subset=["sacas"])
    cores_tipo = [("Informado", VERDE), ("Informado (safra 2024, El Niño)", CEREJA), ("Estimado para 2027", PALHA)]
    legenda_tipo = " &nbsp;&nbsp; ".join(
        f'<span style="font-size:1.05rem"><span style="display:inline-block;width:14px;height:14px;'
        f'background:{cor};border-radius:2px;vertical-align:-1px"></span> {nome}</span>' for nome, cor in cores_tipo)

    g_sacas, g_prod = st.columns([1.6, 1], gap="large")
    with g_sacas:
        st.subheader("Sacas colhidas e estimativa para 2027")
        st.markdown(legenda_tipo, unsafe_allow_html=True)
        x_b = alt.X("eixo:N", title=None, sort=None,
                    axis=alt.Axis(labelAngle=0, labelExpr="split(datum.label, '|')", ticks=False, labelPadding=8,
                                  labelOverlap=False, labelLimit=130))
        y_b = alt.Y("sacas:Q", title=None, axis=alt.Axis(tickCount=4, domain=False, ticks=False),
                    scale=alt.Scale(domainMax=float(barras["sacas"].max()) * 1.15))
        base_b = alt.Chart(barras).encode(x=x_b, y=y_b)
        colunas = base_b.mark_bar(cornerRadiusTopLeft=2, cornerRadiusTopRight=2, width={"band": 0.7}).encode(
            color=alt.Color("tipo:N", legend=None, scale=alt.Scale(
                domain=["Informado (El Niño)", "Informado", "Estimado"], range=[CEREJA, VERDE, PALHA])),
            tooltip=["safra", "tipo", alt.Tooltip("sacas:Q", format=",.0f")])
        valores = base_b.mark_text(dy=-10, fontSize=16, fontWeight="bold", color="#222").encode(
            text=alt.Text("sacas:Q", format=",.0f"))
        st.altair_chart(estilo((colunas + valores).properties(height=270), fonte=15), width="stretch")

    with g_prod:
        st.subheader("Sacas por mil pés")
        st.markdown('<span style="font-size:1.05rem">Produtividade informada em cada safra</span>',
                    unsafe_allow_html=True)
        prod = pd.DataFrame({"safra": anos, "sacas por mil pés": [p[f"prod_{a}"] for a in calculo.ANOS]}).dropna()
        x_p = alt.X("safra:O", title=None, axis=alt.Axis(labelAngle=0, ticks=False, labelPadding=8, grid=False))
        y_p = alt.Y("sacas por mil pés:Q", title=None, axis=alt.Axis(tickCount=4, domain=False, ticks=False),
                    scale=alt.Scale(domainMax=float(prod["sacas por mil pés"].max()) * 1.2 if len(prod) else None))
        base_p = alt.Chart(prod).encode(x=x_p, y=y_p)
        linha_p = base_p.mark_line(color=GRAO, strokeWidth=3) + base_p.mark_point(
            filled=True, size=110, color=GRAO, opacity=1).encode(
            tooltip=["safra", alt.Tooltip("sacas por mil pés:Q", format=".1f")])
        rot_p = base_p.mark_text(dy=-16, fontSize=16, fontWeight="bold", color="#222").transform_calculate(
            rot="replace(format(datum['sacas por mil pés'], '.1f'), '.', ',')").encode(text="rot:N")
        st.altair_chart(estilo((linha_p + rot_p).properties(height=270), fonte=15), width="stretch")

    # --- Indicadores ---
    a, b = st.columns(2)
    a.container(border=True).metric(
        "El Niño 2023/24: safra 2024 contra 2026", f"{fmt(p['efeito_2024_pct'])}%",
        help="Sacas por mil pés em 2024 comparadas com 2026, que está no mesmo ciclo bienal.")
    if pd.notna(p["expectativa_2027"]):
        dif = p["expectativa_2027"] - p["est_2027_Sem efeito"]
        b.container(border=True).metric(
            "Expectativa do próprio produtor para 2027", f"{fmt(p['expectativa_2027'])} sacas",
            f"{'+' if dif > 0 else ''}{fmt(dif)} vs. cenário sem efeito", delta_color="off", delta_arrow="off")


# ----------------------------------------------------------------------------
# Tela 4 · Resumo do grupo
# ----------------------------------------------------------------------------
elif pagina == "Resumo do grupo":
    total_pes = est["pes_2026"].sum()
    st.title(f"{len(est)} produtores, {fmt(total_pes)} {'de pés' if total_pes >= 1e6 else 'pés'} em produção")
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
                                     "sacas_mil_pes": "sacas por mil pés"}).round(1)
                 .assign(**{"2024 vs 2026 (%)": lambda d: d["2024 vs 2026 (%)"].map(
                     lambda v: "—" if pd.isna(v) else f"{v:+.1f}")}),
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
