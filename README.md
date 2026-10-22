# Safra 2027 · Mantenópolis-ES

Sistema de apoio à estimativa da safra cafeeira 2027 sob influência do El Niño 2026/2027.

## Organização em camadas

| Camada | Arquivo | O que faz |
|---|---|---|
| Interface | `app.py` | Telas em Streamlit; não calcula nem acessa o banco diretamente |
| Regras de negócio | `safra/calculo.py` | Cenários do El Niño, estimativa por produtor, bienalidade e checagens |
| Dados | `safra/banco.py` | Banco SQLite (tabelas `produtores` e `safras`), sem dados pessoais |
| Dados | `safra/formulario.py` | Lê o CSV do Google Forms reconhecendo as colunas pelo texto da pergunta |
| Dados | `safra/clima.py` | NASA POWER (API), índice ONI da NOAA e base histórica do IBGE |

## Rodar no computador

    pip install -r requirements.txt
    streamlit run app.py

## Carregar as respostas

**Automático (recomendado).** O sistema lê a planilha do Google Forms sozinho a cada 5 minutos
e grava no banco `banco/safra.db`: respostas novas entram, correções feitas na planilha são
aplicadas e respostas apagadas da planilha saem do banco.

1. Na planilha: Arquivo > Compartilhar > Publicar na Web. Escolha a aba de respostas e o formato
   "Valores separados por vírgula (.csv)" e clique em Publicar. Copie o link gerado.
2. No Streamlit Community Cloud: abra o app > Settings > Secrets e cole:

       PLANILHA_CSV_URL = "cole-aqui-o-link-copiado"

   Para rodar no computador, crie o arquivo `.streamlit/secrets.toml` com a mesma linha.

**Manual.** Sem o link configurado, a barra lateral mostra um campo para enviar o CSV baixado da
planilha (Arquivo > Fazer download > .csv).

Sem respostas no banco, o sistema mostra 50 produtores **fictícios** (`dados/produtores_EXEMPLO_ficticio.csv`).

## Publicar com link

1. Crie um repositório **privado** no GitHub e envie esta pasta inteira.
2. Entre em share.streamlit.io com a conta do GitHub, clique em "Create app",
   escolha o repositório e o arquivo `app.py`.
3. Em poucos minutos sai o link do sistema.

O banco SQLite do servidor gratuito é apagado quando o app reinicia; com a sincronização
automática ele é reconstruído a partir da planilha na primeira visita.
