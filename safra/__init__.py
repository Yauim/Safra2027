"""Pacote do sistema de apoio à estimativa da safra 2027.

Camadas:
    formulario.py  leitura e padronização das respostas do Google Forms
    banco.py       persistência em SQLite (camada de dados)
    clima.py       clima (NASA POWER), ONI (NOAA) e base histórica (IBGE)
    calculo.py     regras de negócio: cenários, estimativas e checagens
A interface (app.py) só chama funções destes módulos.
"""
