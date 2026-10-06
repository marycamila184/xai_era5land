#!/usr/bin/env python3
"""Export the AT3 table and a README for whoever builds the classifier.

Writes two files to at3/export/:

    curitiba_at3.parquet   one row per day: date, train/test split, rain, heavy-day
                           flag and the 12 features the regression uses
    LEIA-ME.md             how the regression was built (split, validation, tuning,
                           climatology baseline) and how to set up the same for the
                           classification

Run from the repository root:  uv run python -m at3.exportar_para_classificacao
"""

from pathlib import Path

import joblib
import pandas as pd

ROOT = Path(__file__).resolve().parent
DATA = ROOT.parent / "commons" / "data"
OUT = ROOT / "export"


def tabela():
    """The daily table with the synoptic and sub-daily columns, as the notebooks build it."""
    df = pd.read_parquet(DATA / "curitiba_daily.parquet").sort_values("date").reset_index(drop=True)
    extras = []
    for nome in ["curitiba_synoptic.parquet", "curitiba_subdaily.parquet"]:
        extra = pd.read_parquet(DATA / nome)
        df = df.join(extra, on="date")
        extras += list(extra.columns)
    # same rows as the notebooks: days missing any extra column are dropped
    return df.dropna(subset=extras).reset_index(drop=True)


def main():
    reg = joblib.load(ROOT / "analysis" / "modelos" / "modelo_r10mm.joblib")
    F, limiar, corte = reg["features"], reg["limiar"], reg["treino_ate"]

    df = tabela()
    df["forte"] = (df.tp_mm >= limiar).astype(int)
    df["conjunto"] = (df.date.dt.year > corte).map({False: "treino", True: "teste"})
    saida = df[["date", "conjunto", "tp_mm", "forte"] + F]

    OUT.mkdir(exist_ok=True)
    saida.to_parquet(OUT / "curitiba_at3.parquet", index=False)

    treino, teste = saida[saida.conjunto == "treino"], saida[saida.conjunto == "teste"]
    f_tr = 100 * treino.forte.mean()
    (OUT / "LEIA-ME.md").write_text(LEIA_ME.format(
        n=len(saida), n_tr=len(treino), n_te=len(teste), f_tr=f_tr, f_te=100 * teste.forte.mean(),
        n_ftr=int(treino.forte.sum()), n_fte=int(teste.forte.sum()),
        f_tr_txt=f"{f_tr:.1f}".replace(".", ","), f_te_txt=f"{100 * teste.forte.mean():.1f}".replace(".", ",")))

    print(f"{len(saida)} dias | treino {len(treino)} ({f_tr:.1f}% fortes) | "
          f"teste {len(teste)} ({100 * teste.forte.mean():.1f}% fortes)")
    print(f"escrito em {OUT}")


LEIA_ME = """# AT3, dados para a parte da classificação

Este arquivo descreve os dados e como a regressão foi montada, para a classificação seguir o mesmo processo e as duas partes poderem ser comparadas no relatório.

## O arquivo `curitiba_at3.parquet`

Uma linha por dia, de 01/04/1980 a 30/12/2025, {n} dias, na célula do ERA5-Land mais próxima do centro de Curitiba (o vento a 850 hPa vem do ERA5).

| Coluna | O que é |
|---|---|
| `date` | o dia previsto (dia UTC) |
| `conjunto` | `treino` (1980 a 2014) ou `teste` (2015 a 2025) |
| `tp_mm` | chuva do dia, em mm. É o **target** (alvo) da regressão |
| `forte` | 1 se `tp_mm` ≥ 10 mm (índice R10mm do ETCCDI). É o **target** (alvo) da classificação |
| `ssrd_wm2` | radiação solar média da véspera (W/m²), indica nebulosidade |
| `t2m`, `d2m` | temperatura e ponto de orvalho médios da véspera (°C) |
| `dpd` | `t2m − d2m`, quão longe o ar estava de saturar |
| `wind_speed` | velocidade média do vento a 10 m na véspera (m/s) |
| `wind_const` | constância da direção do vento na véspera, de 0 a 1 |
| `wind_dir_sin`, `wind_dir_cos` | seno e cosseno da direção de onde veio o vento (cosseno 1 é norte, −1 é sul) |
| `day_sin`, `day_cos` | o dia do ano em seno e cosseno (é do próprio dia, já conhecido de antemão) |
| `tp_lag1` | chuva da véspera (mm) |
| `wind850_speed_mean` | velocidade média do vento a 850 hPa (cerca de 1,5 km de altitude) no dia anterior, média das 4 horas do ERA5 (00, 06, 12 e 18 UTC), em m/s |

Todas as variáveis descrevem a véspera, exceto o dia do ano, então nenhuma traz informação que não estaria disponível na hora de prever. São as mesmas 12 variáveis da regressão; usar as mesmas na classificação permite comparar os dois modelos variável por variável.

```python
import pandas as pd

df = pd.read_parquet("curitiba_at3.parquet")
F = [c for c in df.columns if c not in ("date", "conjunto", "tp_mm", "forte")]   # as 12 variáveis
treino = df[df.conjunto == "treino"].reset_index(drop=True)
teste  = df[df.conjunto == "teste"].reset_index(drop=True)
```

## Como a regressão foi feita

A regressão estima quanto chove num dia forte, então ela usa só as linhas com `forte == 1`. A classificação usa todas as linhas.

**1. Treino e teste no tempo.** Treino de 1980 a 2014 e teste de 2015 a 2025. O teste foi usado uma única vez, no fim, depois de tudo escolhido. Nada foi escolhido olhando o teste.

| | Dias | Dias fortes |
|---|---|---|
| Treino (1980 a 2014) | {n_tr} | {n_ftr} ({f_tr_txt}%) |
| Teste (2015 a 2025) | {n_te} | {n_fte} ({f_te_txt}%) |

**2. Validação cruzada temporal.** Dentro do treino, cinco blocos de quatro anos (1995 a 1998, 1999 a 2002, 2003 a 2006, 2007 a 2010 e 2011 a 2014). Cada bloco é validado com um modelo treinado só nos anos anteriores a ele (janela expansiva). Os blocos são cortados pelo calendário, e não pelo número de linhas, porque na tabela filtrada um número fixo de linhas não corresponde a um número fixo de anos.

```python
import numpy as np

def date_folds(dates, n_splits=5, val_years=4, end="2015-01-01"):
    \"\"\"Blocos de calendário com janela expansiva; devolve pares (índices de treino, índices de validação).\"\"\"
    dates = pd.to_datetime(pd.Series(dates)).reset_index(drop=True)
    bordas = [pd.Timestamp(end) - pd.DateOffset(years=val_years * k) for k in range(n_splits + 1)][::-1]
    return [(np.where(dates < ini)[0], np.where((dates >= ini) & (dates < fim))[0])
            for ini, fim in zip(bordas[:-1], bordas[1:])]

folds = date_folds(treino.date)
```

**3. Grade de hiperparâmetros.** Cada configuração foi treinada e avaliada nos cinco blocos, e a métrica é a média dos blocos. Na regressão foram 192 árvores de decisão: critério Poisson ou erro quadrático, profundidade 3, 4, 5 ou 8, mínimo de 20, 50, 100 ou 200 dias por folha, e duas formas de poda (`ccp_alpha` e `min_impurity_decrease`). O modelo final usa as 12 variáveis deste arquivo; os outros conjuntos testados, menores ou com outras variáveis, não melhoraram a validação.

**4. Métrica e escolha.** Na regressão, a métrica é o RMSE, e o escolhido foi o de menor RMSE médio na validação. Depois ele foi treinado em todo o treino e avaliado uma vez no teste.

**5. Referência: climatologia mensal.** Todo modelo é comparado com uma referência que só sabe o mês do ano. Ela é ajustada apenas no treino e avaliada nos mesmos blocos e no mesmo teste que o modelo. Na regressão, a climatologia prevê a chuva média dos dias fortes daquele mês no treino.

```python
def climatologia(treino_df, alvo_df, coluna):
    \"\"\"Média de `coluna` por mês no treino, aplicada ao mês de cada dia de alvo_df.\"\"\"
    media_mes = treino_df.groupby(treino_df.date.dt.month)[coluna].mean()
    return alvo_df.date.dt.month.map(media_mes).fillna(treino_df[coluna].mean()).to_numpy()

# regressão: só dias fortes, coluna "tp_mm"
# classificação: todos os dias, coluna "forte", o que dá a frequência de dias fortes de cada mês,
# ou seja, uma probabilidade
p_clim = climatologia(treino, teste, "forte")
```

Na validação, a climatologia é refeita em cada bloco, só com os anos de treino daquele bloco.

**6. Resultado da regressão.** Árvore com critério Poisson, profundidade 4, ao menos 50 dias por folha e 11 folhas. RMSE de 11,49 mm na validação e 10,42 mm no teste, contra 10,29 mm da climatologia no teste. A árvore empata com a climatologia, então as explicações da regressão descrevem como o modelo decide, e não as causas físicas da quantidade de chuva.

## Sugestões para a classificação

- Para comparar com a regressão, explicar os mesmos quatro dias fortes do teste que o relatório usa:

| Papel | Data | Chuva observada | Regressão |
|---|---|---|---|
| maior evento | 07/11/2024 | 79,9 mm | 17,6 mm |
| acerto | 16/10/2021 | 20,6 mm | 20,6 mm |
| superestimado | 28/06/2021 | 13,0 mm | 35,1 mm |
| dia típico | 07/04/2019 | 16,0 mm | 17,6 mm |

- Sugestão: ignorar a acurácia e focar em precisão, revocação, F1 e área sob a curva. Como só cerca de {f_tr:.0f}% dos dias são fortes, um modelo que chamasse todo dia de fraco teria acurácia alta sem acertar nenhum dia forte. A precisão diz quantos dos dias apontados como fortes foram fortes de fato, a revocação diz quantos dias fortes o modelo encontrou e o F1 combina as duas. Essas três dependem do limiar de probabilidade a partir do qual um dia é chamado de forte, então vale dizer qual limiar foi usado. A área sob a curva não depende de limiar; com a classe rara, a curva de precisão e revocação (PR-AUC) costuma ser mais informativa que a ROC.
- Sugestão: usar como referência a climatologia mensal da classificação, que é uma probabilidade (a frequência de dias fortes do mês no treino). Assim ela pode ser comparada com o modelo pela mesma métrica de probabilidade que for escolhida.
- Sugestão: se quiser incluir um falso positivo, lembrar que ele é um dia que não chegou a 10 mm e, por isso, não tem explicação da regressão para comparar. Nesse caso, ele entra à parte, além dos quatro dias.
- Sugestão: o relatório tem caixas "[Classificação, a completar]" em cada seção, dizendo o que pode entrar ali, e sugere o Anchors como método adicional da classificação.
"""


if __name__ == "__main__":
    main()
