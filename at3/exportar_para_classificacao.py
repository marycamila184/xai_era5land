#!/usr/bin/env python3
"""Export the AT3 table and a README for whoever builds the classifier.

Writes two files to at3/export/:

    curitiba_at3_p90.parquet  one row per day: date, train/test split, rain, heavy-day
                              flag and the 11 features the p90 regression uses
    LEIA-ME.md                how the regression was built (split, validation, tuning,
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
    reg = joblib.load(ROOT / "analysis" / "modelos" / "modelo_p90.joblib")
    F, limiar, corte = reg["features"], reg["limiar"], reg["treino_ate"]

    df = tabela()
    df["forte"] = (df.tp_mm >= limiar).astype(int)
    df["conjunto"] = (df.date.dt.year > corte).map({False: "treino", True: "teste"})
    saida = df[["date", "conjunto", "tp_mm", "forte"] + F]

    OUT.mkdir(exist_ok=True)
    saida.to_parquet(OUT / "curitiba_at3_p90.parquet", index=False)

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

**O que mudou em 07/10.** A regressão deixou de prever a chuva média do dia forte e passou a prever o p90, o valor que só 1 em cada 10 dias fortes com uma véspera parecida ultrapassa. O modelo agora é um gradient boosting quantílico e usa 11 variáveis, sem o vento a 850 hPa. O arquivo novo é o `curitiba_at3_p90.parquet`. O `curitiba_at3.parquet` antigo continua na pasta e é igual ao novo com a coluna `wind850_speed_mean` a mais.

## O arquivo `curitiba_at3_p90.parquet`

Uma linha por dia, de 01/04/1980 a 30/12/2025, {n} dias, na célula do ERA5-Land mais próxima do centro de Curitiba.

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

Todas as variáveis descrevem a véspera, exceto o dia do ano, então nenhuma traz informação que não estaria disponível na hora de prever. São as mesmas 11 variáveis da regressão. Usar as mesmas na classificação permite comparar os dois modelos variável por variável. Se a classificação já foi feita com as 12 do arquivo antigo, basta dizer isso no relatório, porque a diferença é só o vento a 850 hPa.

```python
import pandas as pd

df = pd.read_parquet("curitiba_at3_p90.parquet")
F = [c for c in df.columns if c not in ("date", "conjunto", "tp_mm", "forte")]   # as 11 variáveis
treino = df[df.conjunto == "treino"].reset_index(drop=True)
teste  = df[df.conjunto == "teste"].reset_index(drop=True)
```

## Como a regressão foi feita

A regressão estima até quanto pode chover num dia forte, então ela usa só as linhas com `forte == 1`. A classificação usa todas as linhas.

**1. O que a regressão prevê.** Para cada dia forte, o modelo devolve um número em mm, o p90. A leitura é "num dia forte com uma véspera como esta, a chuva fica abaixo deste valor em 90% dos casos". A troca aconteceu porque nenhum modelo conseguiu prever a chuva média melhor que a climatologia, enquanto o p90 tem sinal. As condições da véspera dizem pouco sobre quanto vai chover, mas dizem algo sobre quão longe a chuva pode ir.

**2. Treino e teste no tempo.** Treino de 1980 a 2014 e teste de 2015 a 2025. As variáveis e os hiperparâmetros foram escolhidos só pela validação cruzada, dentro do treino. A troca da árvore pelo boosting, porém, veio depois de ver uma árvore quantílica perder da climatologia no teste, então o teste não está totalmente limpo e o ganho final deve ser lido com essa ressalva.

| | Dias | Dias fortes |
|---|---|---|
| Treino (1980 a 2014) | {n_tr} | {n_ftr} ({f_tr_txt}%) |
| Teste (2015 a 2025) | {n_te} | {n_fte} ({f_te_txt}%) |

**3. Validação cruzada temporal.** Dentro do treino, cinco blocos de quatro anos (1995 a 1998, 1999 a 2002, 2003 a 2006, 2007 a 2010 e 2011 a 2014). Cada bloco é validado com um modelo treinado só nos anos anteriores a ele (janela expansiva). Os blocos são cortados pelo calendário, e não pelo número de linhas, porque na tabela filtrada um número fixo de linhas não corresponde a um número fixo de anos.

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

**4. Modelo e grade de hiperparâmetros.** O modelo é o `GradientBoostingRegressor(loss="quantile", alpha=0.9)` do scikit-learn, que soma muitas árvores pequenas, cada uma corrigindo um pouco as anteriores. A grade teve 120 combinações, com quatro conjuntos de variáveis, profundidade das árvores 1, 2 ou 3, de 25 a 400 árvores e mínimo de 20 ou 50 dias por folha, sempre com taxa de aprendizado 0,05 e 80% dos dias sorteados por árvore. Cada combinação foi treinada e avaliada nos cinco blocos, e a métrica é a média dos blocos.

**5. Métrica e escolha.** Para um p90, o RMSE não serve, porque ele mede a distância até a média. A métrica é a perda pinball, que cobra 0,9 por mm quando a chuva passa da previsão e 0,1 por mm quando fica abaixo. O mínimo dela é justamente o p90. O escolhido foi o de menor pinball média na validação, depois treinado em todo o treino e avaliado uma vez no teste. Também se confere a cobertura, a fração dos dias que ficaram abaixo da previsão, que num p90 calibrado fica perto de 90%.

**6. Referência: climatologia mensal.** Todo modelo é comparado com uma referência que só sabe o mês do ano. Ela é ajustada apenas no treino e avaliada nos mesmos blocos e no mesmo teste que o modelo. Na regressão, a climatologia prevê o p90 dos dias fortes daquele mês no treino.

```python
def climatologia(treino_df, alvo_df, coluna, quantil=None):
    \"\"\"Média (ou quantil) de `coluna` por mês no treino, aplicada ao mês de cada dia de alvo_df.\"\"\"
    por_mes = treino_df.groupby(treino_df.date.dt.month)[coluna]
    valor = por_mes.mean() if quantil is None else por_mes.quantile(quantil)
    geral = treino_df[coluna].mean() if quantil is None else treino_df[coluna].quantile(quantil)
    return alvo_df.date.dt.month.map(valor).fillna(geral).to_numpy()

# regressão: só dias fortes, coluna "tp_mm", quantil=0.9
# classificação: todos os dias, coluna "forte", sem quantil, o que dá a frequência de dias
# fortes de cada mês, ou seja, uma probabilidade
p_clim = climatologia(treino, teste, "forte")
```

Na validação, a climatologia é refeita em cada bloco, só com os anos de treino daquele bloco.

**7. Resultado da regressão.** Boosting com profundidade 2, 100 árvores e ao menos 20 dias por folha. Na validação, a pinball foi 2,453 contra 2,681 da climatologia, um ganho de 8,5% que aparece nos cinco blocos. No teste, foi 2,407 contra 2,486, um ganho de 3,2%, com 90,5% dos dias abaixo da previsão. O ganho é pequeno, mas real, e vem de o modelo baixar o teto nos dias calmos e subir nos dias de risco, enquanto a climatologia dá o mesmo valor para todo dia do mês. Uma árvore de decisão única perdia da climatologia tanto para a média quanto para o p90.

## Os quatro dias mudaram

Os quatro dias do teste que o relatório explica foram escolhidos de novo junto com o modelo. Dois continuam e dois são novos.

| Antes (árvore, média) | Dia | Agora (boosting, p90) | Dia |
|---|---|---|---|
| maior evento | 07/11/2024 | passou do teto | 07/11/2024 (o mesmo) |
| acerto | 16/10/2021 | teto alto | 06/06/2017 (novo) |
| superestimado | 28/06/2021 | dia calmo | 06/03/2018 (novo) |
| dia típico | 07/04/2019 | dia típico | 07/04/2019 (o mesmo) |

As regras antigas foram feitas para uma previsão da média. O "acerto" era o dia com a previsão mais perto da chuva observada e o "superestimado" era o dia em que a previsão ficou mais acima da chuva. Com o p90 essas ideias deixam de fazer sentido, porque a previsão é um teto. Ficar abaixo dele não é erro, é o esperado em 90% dos dias, e o modelo não tenta acertar o valor exato. Por isso as regras novas usam o próprio teto. O dia que "passou do teto" é aquele em que a chuva mais ultrapassou a previsão. O "teto alto" é o dia em que o modelo viu mais potencial, e o "dia calmo" é o de teto mais baixo. O "dia típico" tem teto perto do mediano e chuva perto da mediana observada.

O 07/11/2024 é o maior evento do teste e também o dia que mais passou do teto, então só o nome do papel mudou. É o evento que nenhum dos dois modelos viu chegando. O 07/04/2019 continuou como dia típico pelas duas regras, por coincidência. Se a classificação já explicou os dias antigos, os dois que continuam podem ser aproveitados e só os outros dois precisam ser refeitos.

## Sugestões para a classificação

- Para comparar com a regressão, explicar os mesmos quatro dias fortes do teste que o relatório usa. Eles mudaram junto com o modelo, como explica a seção anterior.

| Papel | Data | Chuva observada | p90 da regressão |
|---|---|---|---|
| passou do teto | 07/11/2024 | 79,9 mm | 24,1 mm |
| teto alto | 06/06/2017 | 20,2 mm | 54,0 mm |
| dia calmo | 06/03/2018 | 11,8 mm | 18,3 mm |
| dia típico | 07/04/2019 | 16,0 mm | 27,1 mm |

- Sugestão: ignorar a acurácia e focar em precisão, revocação, F1 e área sob a curva. Como só cerca de 15% dos dias são fortes, um modelo que chamasse todo dia de fraco teria acurácia alta sem acertar nenhum dia forte. A precisão diz quantos dos dias apontados como fortes foram fortes de fato, a revocação diz quantos dias fortes o modelo encontrou e o F1 combina as duas. Essas três dependem do limiar de probabilidade a partir do qual um dia é chamado de forte, então vale dizer qual limiar foi usado. A área sob a curva não depende de limiar; com a classe rara, a curva de precisão e revocação (PR-AUC) costuma ser mais informativa que a ROC.
- Sugestão: usar como referência a climatologia mensal da classificação, que é uma probabilidade (a frequência de dias fortes do mês no treino). Assim ela pode ser comparada com o modelo pela mesma métrica de probabilidade que for escolhida.
- Sugestão: as duas partes se completam. A classificação diz se o dia vai passar de 10 mm, e a regressão diz até quanto a chuva pode ir se passar.
- Sugestão: se quiser incluir um falso positivo, lembrar que ele é um dia que não chegou a 10 mm e, por isso, não tem explicação da regressão para comparar. Nesse caso, ele entra à parte, além dos quatro dias.
- Sugestão: o relatório tem caixas "[Classificação, a completar]" em cada seção, dizendo o que pode entrar ali, e sugere o Anchors como método adicional da classificação.
"""


if __name__ == "__main__":
    main()
