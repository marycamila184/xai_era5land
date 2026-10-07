# AT2, tabela diária de precipitação para Curitiba (ERA5-Land)

Trabalho da disciplina de XAI. Uma linha por dia, uma célula da grade, montada para prever a chuva de amanhã em Curitiba e depois explicar o modelo.

As estatísticas de vento vêm de [`scripts/utils/wind_stats.py`](../scripts/utils/wind_stats.py), na raiz do repositório, o mesmo código que o pipeline principal usa.

## O problema

**Ponto.** A célula do ERA5-Land mais próxima da Praça Tiradentes (−25,4284, −49,2733), que cai em **−25,4, −49,3**. Uma célula tem cerca de 9 km de lado, então já é uma média do modelo sobre cerca de 81 km², centrada na cidade. Seis células cobrem Curitiba, e fazer a média delas suavizaria os extremos, que são justamente os casos para os quais um modelo de chuva existe. A série representa o centro e é um pouco mais seca que o município como um todo.

**Dia.** O dia UTC. Em Curitiba (UTC−3), o dia D começa às 21:00 locais de D−1. Uma tempestade no fim da tarde cai no dia certo; a chuva depois da meia-noite cai no dia anterior. Vale lembrar disso ao comparar com as estações do INMET, que usam o dia civil local.

**Tempo das variáveis.** `tp_mm` é a única coluna do dia t. Todo o resto descreve **t−1 ou antes**, então a tabela é uma previsão honesta de t+1: nada em uma linha seria desconhecido no momento em que a previsão seria feita. `_lagk` quer dizer o dia t−k.

## Como construir

```bash
uv sync --group dev
uv run python -m commons.build_curitiba_daily   # commons/data/curitiba_daily.parquet
uv run python -m at2.plot.plot_month 2025-01     # ../figures/curitiba_2025_01.png
uv run python -m at2.plot.animate_month 2025-01  # ../figures/curitiba_map_2025_01.gif
```

O `plot_month` desenha um mês da própria tabela. O `animate_month` percorre o mesmo mês na **grade completa** em volta da cidade, lendo os arquivos em grade e não a tabela, com o limite do município e das divisas estaduais do [IBGE](https://servicodados.ibge.gov.br/api/docs/malhas?versao=3), guardados em `commons/data/boundaries/`. Um segundo argumento define a meia-largura da janela do mapa em graus, 2 por padrão:

```bash
uv run python -m at2.plot.animate_month 2025-01 0.6   # zoom na região metropolitana
```

A grade é de 0,1° e Curitiba ocupa cerca de 0,2° × 0,3°, então abaixo de uns 0,5° não sobra variação espacial para ver.

O vento é lido dos arquivos horários brutos, o que é lento, então ele fica guardado em `commons/data/wind_daily.parquet`. Apague esse arquivo para refazer. Todo o resto vem de `processed_daily/`.

```python
import pandas as pd
df = pd.read_parquet("commons/data/curitiba_daily.parquet")
```

## Colunas

Alvo: **`tp_mm`**, a chuva do dia t em mm. São 22 variáveis, sem valores faltando; o registro vai de 01/04/1980 a 30/12/2025, 16.710 linhas.

| Coluna | Unidade | De quando | Como é calculada |
|---|---|---|---|
| `date` | | t | o dia UTC previsto; não entra no modelo |
| **`tp_mm`** | mm | **t** | `tp` do ERA5 × 1000, **o alvo** |
| `tp_lag1..3` | mm | t−1..3 | `tp_mm` deslocado 1, 2 e 3 dias |
| `tp_sum7/30/90` | mm | t−k..t−1 | `tp_mm.shift(1).rolling(k).sum()` |
| `t2m`, `t2m_min`, `t2m_max` | °C | t−1 | `t2m` do ERA5 − 273,15 (média, mínima e máxima do dia) |
| `d2m`, `d2m_lag2`, `d2m_lag3` | °C | t−1..3 | `d2m` do ERA5 − 273,15, o ponto de orvalho |
| `dpd`, `dpd_lag2`, `dpd_lag3` | °C | t−1..3 | `t2m − d2m` |
| `ssrd_wm2` | W m⁻² | t−1 | `ssrd` do ERA5 ÷ 86400 |
| `wind_speed` | m s⁻¹ | t−1 | `mean(√(u²+v²))` nos 24 passos horários |
| `wind_const` | 0–1 | t−1 | `√(ū²+v̄²) / wind_speed` |
| `wind_dir_sin` | | t−1 | `sin(θ)`, `θ = (270° − atan2(v̄, ū)) mod 360°` |
| `wind_dir_cos` | | t−1 | `cos(θ)`, mesmo `θ` |
| `day_sin`, `day_cos` | | t | `sin` e `cos` de `2π × (dia_do_ano − 1) / n`, com `n` = 366 em ano bissexto e 365 nos outros. Assim 1º de janeiro fica no ângulo 0 e todo ano fecha o círculo exatamente; um 365,25 fixo deslocaria a fase ao longo do ciclo bissexto |

### Umidade

`d2m` é o ponto de orvalho, a temperatura em que o ar saturaria, então mede o vapor de fato presente. `dpd` é quantos graus faltam para o ar saturar.

### Nebulosidade

`ssrd` é guardado como energia acumulada (J m⁻²). Dividir pela janela de acumulação em segundos transforma em potência média, W m⁻²; um dia UTC tem 86400 s. Isso deixa valores diários e semanais comparáveis e permite ler o número contra a constante solar, cerca de 1361 W m⁻². Dividir por um 3600 fixo é o erro comum e dá cerca de cinco vezes esse valor.

### Vento

Uma média diária de `u10`/`v10` é uma média **vetorial**, e ela engana exatamente nos dias interessantes. Doze horas de vento oeste a 4 m s⁻¹ seguidas de doze horas de vento leste a 4 m s⁻¹ dão média zero, e o modelo lê "sem vento" quando o vento soprou o dia todo e mudou de direção, que é como uma frente se parece. Por isso a tabela traz a média **escalar** ao lado da vetorial, e a razão entre elas:

- **`wind_speed`**, quão forte soprou.
- **`wind_const`**, quão constante foi a direção. 1 quer dizer uma direção só o dia todo, transporte real de umidade; perto de 0 quer dizer que o vento se anulou. A média escalar nunca fica abaixo da vetorial, então a razão fica em [0, 1].
- **`wind_dir_sin` / `wind_dir_cos`**, de onde veio. Em graus, a direção salta de 359 para 0 e coloca dois ventos quase iguais em pontas opostas da escala; o par seno e cosseno não tem essa emenda. A convenção é a meteorológica, a direção **de onde** o vento sopra.

Num dia de constância baixa, a direção é mal definida. É exatamente esse o ponto: `wind_const` diz ao modelo quanto a direção vale.

## O que a tabela deixa de fora, e por quê

- **Qualquer coisa do dia t.** Nebulosidade e temperatura do mesmo dia seriam em parte *consequência* da chuva.
- **`u10` e `v10`.** São uma função exata das colunas de vento acima.
- **`temp_range`**, `t2m_max − t2m_min`, já que as duas colunas de origem estão na tabela.
- **`pev`.** A evaporação potencial acompanha de perto o `ssrd_wm2` e sozinha diz pouco sobre o alvo.
- **Os primeiros 91 dias**, o aquecimento que o `tp_sum90` precisa mais o deslocamento de um dia.

## Parece Curitiba?

Climatologia do registro: **1556 mm por ano**, mais chuvoso em janeiro (220 mm), mais seco em agosto (82 mm), sem estação seca de verdade, o regime Cfb da cidade. Vale conferir com as normais publicadas pelo INMET antes de citar os números.

## Referências

- **EPA-454/R-99-005**, *Meteorological Monitoring Guidance for Regulatory Modeling Applications* (2000). [PDF](https://www.epa.gov/sites/default/files/2020-10/documents/mmgrma_0.pdf). §6.2.1 para a velocidade média escalar, §6.2.2 (eqs. 6.2.13–6.2.16) para as componentes médias e a velocidade e direção resultantes.
- *Circular mean.* [Wikipedia](https://en.wikipedia.org/wiki/Circular_mean), por que uma direção é guardada como seno e cosseno e não em graus.
- *Antecedent moisture.* [Wikipedia](https://en.wikipedia.org/wiki/Antecedent_moisture), a chuva passada como indicador de quão úmido o solo já está, o papel de `tp_sum7` … `tp_sum90`.
- **Normais climatológicas do INMET.** [portal.inmet.gov.br/normais](https://portal.inmet.gov.br/normais), os totais mensais de Curitiba, para conferir a climatologia acima.
- **API de malhas do IBGE.** [Documentação](https://servicodados.ibge.gov.br/api/docs/malhas?versao=3), os endpoints `municipios` e `estados` que o `animate_month` desenha.

Fonte do ERA5-Land e convenções de acumulação: veja o [README principal](../README.md#source-and-citation).
