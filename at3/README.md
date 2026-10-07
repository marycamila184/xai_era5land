# AT3, explicações locais para chuva forte em Curitiba

Trabalho da disciplina de XAI (Atividade 03). Usa a mesma tabela da [AT2](../at2/README.md), uma célula do ERA5-Land sobre Curitiba e uma linha por dia UTC, agora voltada para os **dias de chuva forte** e explicada com métodos locais. Esta pasta tem a parte da regressão (Ceteris Paribus, ICE, LIME e SHAP; um teste de contrafactuais com o DiCE fica no notebook, fora do relatório). A classificação é feita à parte, sobre a mesma tabela e os mesmos quatro dias, a partir de [`export/`](#entrega-para-a-classificação).

## O problema

**Dia de chuva forte.** Precipitação de 10 mm ou mais, o índice `R10mm` do ETCCDI. São 2.395 dias (14,3% do registro, cerca de 52 por ano), que concentram 65% de toda a chuva. Eles são chamados de *fortes*, e não de *extremos*, porque o extremo para Curitiba é o percentil 99 dos dias chuvosos, 48,6 mm em 24 h (Goudard & Mendonça, 2020).

**A regressão.** Até quanto pode chover, sabendo que o dia é forte, então ela é treinada só com dias fortes. O modelo prevê o **p90** da chuva do dia, o valor que só 1 em cada 10 dias fortes com uma véspera parecida ultrapassa. É uma regressão quantílica com *gradient boosting* (`GradientBoostingRegressor(loss="quantile", alpha=0.9)`).

| | Regressão |
|---|---|
| Linhas | só dias fortes (1.857 no treino) |
| Modelo | *gradient boosting* quantílico, 100 árvores de profundidade 2, ao menos 20 dias por folha, taxa de aprendizado 0,05, 80% dos dias por árvore |
| Validação cruzada (1995–2014) | perda quantílica 2,453, contra 2,681 da climatologia (ganho de 8,5%, nos cinco blocos) |
| Teste (2015–2025) | perda quantílica 2,407, contra 2,486 da climatologia (ganho de 3,2%) |
| Cobertura no teste | 90,5% dos dias abaixo do teto previsto (alvo de 90%) |

**Por que o p90 e não a média.** Nenhum modelo superou a climatologia mensal ao prever a chuva média dos dias fortes, nem a árvore de decisão das versões anteriores nem o próprio *gradient boosting*. O p90 tem sinal. As condições da véspera dizem pouco sobre quanto vai chover, mas dizem algo sobre quão longe a chuva pode ir. Uma árvore quantílica única perdia da climatologia no teste, porque o p90 de cada folha sai de poucos dias, e o *boosting* reduz essa variância. Uma floresta de regressão quantílica chegou ao mesmo desempenho, o que indica que o limite está na informação disponível, e não no modelo.

**Métrica.** O RMSE mede a distância até a média e não serve para avaliar um p90. A métrica é a perda quantílica (*pinball loss*), que cobra 0,9 por mm quando a chuva passa da previsão e 0,1 por mm quando fica abaixo. O mínimo dela é justamente o p90. A cobertura, a fração dos dias abaixo da previsão, confere se o teto está calibrado. A referência é a climatologia mensal do p90, o p90 dos dias fortes de cada mês no treino.

**Validação.** 1980–2014 é o desenvolvimento e 2015–2025 é o teste. Dentro do desenvolvimento, cinco blocos de janela expansiva validam em blocos consecutivos de quatro anos (1995–1998 … 2011–2014). Os blocos são cortados pelo **calendário**, e não por linhas: na tabela de dias fortes, `TimeSeriesSplit(test_size=365*4)` daria 27 anos. O modelo é o melhor de 120 combinações (profundidade 1, 2 ou 3, de 25 a 400 árvores, 20 ou 50 dias por folha, sobre quatro conjuntos de variáveis), escolhido pela menor perda quantílica média na validação. As variáveis e os hiperparâmetros saíram só da validação. A troca da árvore pelo *boosting*, porém, veio depois de ver a árvore quantílica perder no teste, então o teste não está totalmente limpo e o ganho de 3,2% deve ser lido com essa ressalva.

**Variáveis.** Nove colunas da AT2 em t−1 (`ssrd_wm2`, `t2m`, `d2m`, `dpd`, `wind_speed`, `wind_const`, `wind_dir_sin`, `wind_dir_cos`, `tp_lag1`) mais o dia do ano (`day_sin`, `day_cos`, do próprio dia t, conhecido de antemão). Veja o [README da AT2](../at2/README.md#colunas). A árvore das versões anteriores usava também o `wind850_speed_mean`, o vento a 850 hPa do ERA5 ([`commons/synoptic.py`](../commons/synoptic.py)); com o *boosting*, o conjunto sem ele foi melhor na validação. Também não melhoraram a validação a seleção de variáveis refeita pela perda quantílica, nem tendências, anomalias de 30 dias, máximos móveis de 3 dias, o índice de chuva antecedente e a contagem de dias de chuva na semana anterior.

## Estrutura

```
at3/
├── analysis/
│   ├── atv3_extremos.ipynb         limiar, blocos de validação, referências, boosting quantílico
│   ├── atv3_explicabilidade.ipynb  CP, ICE, LIME, SHAP e DiCE sobre o boosting
│   ├── brdwgd_curitiba.ipynb       comparação do ERA5-Land com pluviômetros (BR-DWGD), fora do modelo
│   ├── modelos/                    os modelos salvos (.joblib, fora do versionamento)
│   └── figuras*/                   figuras de cada notebook
├── relatorio/                      o relatório em LaTeX no template da SBC (fora do versionamento, editado no Overleaf)
├── exportar_para_classificacao.py  escreve a tabela e um LEIA-ME para a parte da classificação
└── evaluation.py                   blocos por data e climatologia suavizada
```

Os dados e os scripts que os constroem são compartilhados com a AT2 e ficam em [`commons/`](../commons/).

## Como rodar

```bash
uv sync --group dev
uv run python -m commons.build_curitiba_daily   # commons/data/curitiba_daily.parquet
uv run python -m commons.synoptic               # vento a 850 hPa, CAPE, TCWV (ERA5)
uv run python -m commons.subdaily               # colunas subdiárias
```

Depois os notebooks, em ordem, a partir de `at3/analysis/`. O `atv3_extremos` salva o modelo em `modelos/modelo_p90.joblib`, e o `atv3_explicabilidade` o explica. O DiCE usa o `dice-ml`.

Tudo tem semente fixa. Rodar de novo reproduz o modelo salvo e as figuras das explicações.

## Entrega para a classificação

`uv run python -m at3.exportar_para_classificacao` escreve dois arquivos em `at3/export/` (fora do versionamento):

- `curitiba_at3_p90.parquet`: todos os dias com as 11 variáveis, a chuva, a marcação de dia forte (`forte`, o alvo da classificação) e a divisão entre treino e teste;
- `LEIA-ME.md`: como a regressão foi montada (divisão, blocos por calendário, grade, climatologia de referência), para a classificação seguir o mesmo processo, mais os quatro dias e algumas sugestões.

O `curitiba_at3.parquet` da versão anterior, com as 12 variáveis, continua na pasta.

## As quatro observações

Quatro dias fortes do teste, cada um escolhido por uma regra que usa só o teto previsto pela regressão:

| Papel | Data | Observado | Teto p90 | Regra |
|---|---|---|---|---|
| passou do teto | 2024-11-07 | 79,9 mm | 24,1 mm | maior excesso da chuva sobre o teto |
| teto alto | 2017-06-06 | 20,2 mm | 54,0 mm | maior teto previsto |
| dia calmo | 2018-03-06 | 11,8 mm | 18,3 mm | menor teto previsto |
| dia típico | 2019-04-07 | 16,0 mm | 27,1 mm | teto perto do mediano, chuva mais perto da mediana dos dias fortes |

Os quatro são dias fortes, então a classificação pode explicar os mesmos. Um falso positivo da classificação seria um dia fraco e não tem par na regressão.

## Métodos e configurações

- **Ceteris Paribus** com o `dalex`, uma variável de cada vez, sobre uma grade de 101 quantis dos dias fortes do teste.
- **ICE / PDP** com `sklearn.inspection.partial_dependence(kind="both")` na mesma grade; o gráfico desenha 300 curvas sorteadas.
- **LIME** (`lime` 0.2.0.1, `LimeTabularExplainer`), sorteando a partir dos dados de **treino**: discretização por quartis, 5.000 amostras, as 11 variáveis, largura do núcleo 0,75·√11 ≈ 2,5, regressão ridge como modelo substituto. A estabilidade é conferida em 10 sementes.
- **SHAP** com o `TreeExplainer`, exato para somas de árvores, em mm de teto. O notebook confere que o valor base mais as contribuições é igual à previsão em todos os dias explicados.
- **DiCE** (`dice-ml`, busca aleatória), testado no notebook e deixado fora do relatório: contrafactuais que levam o teto a 40–50 mm (ou a 18–25 mm no dia de teto alto), com a data fixa, cada um conferido no modelo e marcado quando é fisicamente impossível.

### Cuidados

Uma curva de CP ou de ICE mexe em uma coluna e mantém as outras, então visita combinações que nunca acontecem: um ponto de orvalho acima da temperatura, um par `(sin, cos)` fora do círculo unitário, dias de junho com quase o dobro da maior radiação já registrada em junho. O LIME e o DiCE sorteiam cada variável de forma independente e têm o mesmo problema. O SHAP é exato para o modelo, mas divide o crédito entre variáveis correlacionadas de um jeito discutível (Aas et al., 2021).

## Referências

- Muñoz-Sabater et al. (2021), ERA5-Land, *ESSD* 13, [doi:10.5194/essd-13-4349-2021](https://doi.org/10.5194/essd-13-4349-2021)
- Hersbach et al. (2020), ERA5, *QJRMS* 146, [doi:10.1002/qj.3803](https://doi.org/10.1002/qj.3803)
- ETCCDI, [definições dos índices](https://etccdi.pacificclimate.org/docs/ETCCDMIndicesComparison1.pdf); Zhang et al. (2011), *WIREs Clim. Change* 2, [doi:10.1002/wcc.147](https://doi.org/10.1002/wcc.147)
- Goudard & Mendonça (2020), *IdeAs* 15, [doi:10.4000/ideas.8082](https://doi.org/10.4000/ideas.8082)
- Koenker & Bassett (1978), regressão quantílica, *Econometrica* 46(1), 33–50
- Friedman (2001), *gradient boosting*, *Ann. Statist.* 29(5), 1189–1232
- Steinwart & Christmann (2011), perda quantílica, *Bernoulli* 17(1), [doi:10.3150/10-BEJ267](https://doi.org/10.3150/10-BEJ267)
- Gneiting, Balabdaoui & Raftery (2007), calibração e nitidez, *JRSS-B* 69(2), 243–268
- Bergmeir & Benítez (2012), validação cruzada para séries temporais, *Inf. Sci.* 191, [doi:10.1016/j.ins.2011.12.028](https://doi.org/10.1016/j.ins.2011.12.028)
- Biecek & Burzykowski (2021), *Explanatory Model Analysis*, CRC, [doi:10.1201/9781003025902](https://doi.org/10.1201/9781003025902)
- Goldstein et al. (2015), ICE, *JCGS* 24, [doi:10.1080/10618600.2014.907095](https://doi.org/10.1080/10618600.2014.907095)
- Ribeiro et al. (2016), LIME, KDD, [doi:10.1145/2939672.2939778](https://doi.org/10.1145/2939672.2939778)
- Mothilal et al. (2020), DiCE, FAT*, [doi:10.1145/3351095.3372850](https://doi.org/10.1145/3351095.3372850)
- Lundberg & Lee (2017), SHAP, NeurIPS; Lundberg et al. (2020), TreeSHAP, *Nat. Mach. Intell.* 2, [doi:10.1038/s42256-019-0138-9](https://doi.org/10.1038/s42256-019-0138-9)
- Aas et al. (2021), variáveis dependentes, *Artif. Intell.* 298, [doi:10.1016/j.artint.2021.103502](https://doi.org/10.1016/j.artint.2021.103502)
- Rudin (2019), *Nat. Mach. Intell.* 1, [doi:10.1038/s42256-019-0048-x](https://doi.org/10.1038/s42256-019-0048-x)
