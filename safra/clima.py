"""Fontes externas: clima (NASA POWER), índice ONI (NOAA) e base histórica (IBGE)."""
from pathlib import Path

import numpy as np
import pandas as pd
import requests

LAT, LON = -18.86, -41.12


def clima_local(pasta: Path) -> pd.DataFrame:
    return pd.read_csv(pasta / "clima_diario.csv", parse_dates=["data"])


def clima_nasa(inicio: str = "20020101") -> pd.DataFrame:
    """Busca a série diária na API da NASA POWER e valida a escala da chuva."""
    url = ("https://power.larc.nasa.gov/api/temporal/daily/point"
           f"?parameters=PRECTOTCORR,T2M_MAX,T2M_MIN&community=AG&latitude={LAT}&longitude={LON}"
           f"&start={inicio}&end={pd.Timestamp.today():%Y%m%d}&format=JSON")
    p = requests.get(url, timeout=60).json()["properties"]["parameter"]
    df = pd.DataFrame(p).replace(-999, np.nan)
    df.index = pd.to_datetime(df.index, format="%Y%m%d")
    df = df.rename(columns={"PRECTOTCORR": "chuva_mm", "T2M_MAX": "tmax_c", "T2M_MIN": "tmin_c"})
    # Chuva anual acima de 3.000 mm é impossível na região: os arquivos diários
    # vieram 24 vezes maiores (validado contra o produto mensal da própria NASA).
    if df["chuva_mm"].groupby(df.index.year).sum().median() > 3000:
        df["chuva_mm"] = df["chuva_mm"] / 24
    return df.reset_index(names="data")


def oni(pasta: Path) -> pd.DataFrame:
    o = pd.read_csv(pasta / "oni.txt", sep=r"\s+")
    return o.rename(columns={"SEAS": "trimestre", "YR": "ano", "ANOM": "oni"})


def base_historica(pasta: Path) -> pd.DataFrame:
    return pd.read_csv(pasta / "base_safras_mantenopolis_2003_2027.csv")
