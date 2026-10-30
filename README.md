# Sinergia — gestão de afastamentos com agentes de IA

Sistema multiagente que recebe, confere e registra atestados e, a partir do histórico, revela
tendências coletivas de adoecimento para a saúde ocupacional agir preventivamente. Quatro agentes
especializados trabalham em cadeia, orquestrados pelo **LangGraph**, e nenhuma decisão sobre
pessoas sai do sistema sem passar por um profissional.

| Agente | Tipo | Objetivo | Situação |
| --- | --- | --- | --- |
| A1 · Recepção | Baseado em objetivos | Obter um dossiê de entrada completo e válido | Implementado |
| A2 · Processamento | Reativo simples | Transformar o documento em registro estruturado | Implementado |
| A3 · Monitoramento | Reativo baseado em modelo | Detectar padrões fora do esperado | Implementado |
| A4 · Escalonamento | Baseado em utilidade | Encaminhar cada caso ao responsável certo | Implementado |

Uma crew de insights em **CrewAI** gera, fora do fluxo principal, um relatório semanal para o
SESMT a partir só de dados agregados, e um **painel em Streamlit** mostra a cada perfil (colaborador,
RH/DP, gestor, SESMT e auditoria) só o que ele precisa ver.

## Agente 1 — Recepção

O agente segue o ciclo Percepção → Decisão → Ação, montado como subgrafo do LangGraph:

```text
perceive → decide ─┬─ completo ─────────────→ store_dossier → fim (protocolo)
                   ├─ falta algo ───────────→ ask_employee → wait_for_employee ─┐
                   │        (pausa com interrupt() até o colaborador responder) │
                   │                      perceive ←────────────────────────────┘
                   └─ tentativas esgotadas → hand_over_to_hr → fim (pendência para o RH)
```

- **Percepção:** identifica o formato pelo conteúdo do arquivo, confere tamanho, páginas,
  resolução, contraste e nitidez, e classifica o tipo do documento pela camada de texto.
- **Decisão:** compara o envio com o objetivo e lista o que falta — arquivo, legibilidade, tipo
  aceito, matrícula e data de início — aplicando as regras R01 a R03.
- **Ação:** pede ao colaborador só o que falta, ou arquiva o original com hash SHA-256, cria a
  linha de entrada com protocolo e registra tudo na trilha de auditoria.

| Regra | O que verifica | Se violada |
| --- | --- | --- |
| R01 | Tipo do documento na lista aceita | Pede o documento correto |
| R02 | Arquivo em formato aceito, legível e completo | Pede reenvio |
| R03 | Entrega dentro do prazo da política | Recebe, sinaliza e abre pendência para o RH |

Os limiares ficam em [`config/rules.yaml`](config/rules.yaml), versionados: alterá-los não exige
mudança de código, e cada decisão registra a versão das regras usada.

**Onde entra o LLM.** Só para reescrever o pedido ao colaborador em tom de conversa. O LLM recebe
apenas a lista do que falta, nunca o documento; protocolo e prazos são montados sem LLM; e
qualquer falha do provedor volta para a mensagem padrão. Todas as decisões são regras em Python.

## Agente 2 — Processamento

Quando o Agente 1 conclui o recebimento, o grafo do caso segue direto para o Agente 2. Os dois
agentes são subgrafos do mesmo grafo e compartilham o checkpoint do caso.

```text
read_document → verify_crm → validate ─┬─ válido ─→ register_valid → check_deadlines → fim
                                        └─ violou ─→ register_for_review → await_review
                                                                                │ interrupt()
                      validate ←── apply_review (aprovar, com correções) ←─────┤
                      fim      ←── apply_review (invalidar) ←────────────────────┘
```

- **Leitura:** usa a camada de texto do PDF; para fotos e PDFs escaneados, aplica OCR local
  com o EasyOCR e seu modelo de português, que reconhece acentos e cedilha. A imagem do
  atestado não sai da máquina. Os trechos lidos são remontados em linhas pela posição na
  imagem, o que mantém a ordem de leitura mesmo em fotos inclinadas.
- **Confiança da leitura:** se a confiança média do OCR ficar abaixo do limiar
  (`min_ocr_confidence` no `rules.yaml`), o caso vai para revisão pela R08, por exemplo com uma
  foto ruim que passou pela triagem do Agente 1.
- **Extração:** com LLM configurado, o Groq devolve os campos em saída estruturada (Pydantic) e
  as regras por padrão completam o que faltar. Sem LLM, ou se o provedor falhar, só as regras.
- **Ancoragem:** cada valor extraído precisa aparecer no texto do documento. Valor que não
  aparece fica com confiança baixa (R08), e CID que não consta é descartado (R09). A
  comparação tolera um acento que o OCR não tenha lido, mas nenhuma outra letra pode mudar.
- **Decisão:** regras fixas em Python. Qualquer violação manda o caso para a fila de revisão
  humana, com a regra e os campos destacados. O agente nunca rejeita um atestado sozinho.
- **Revisão humana:** o profissional aprova (com correções) ou invalida. A aprovação substitui
  as checagens de CRM (R06) e de confiança (R08), mas não as de campos obrigatórios, datas e
  sobreposição. Cada correção fica guardada como exemplo para melhorar a extração.
- **Prazos legais:** afastamento acima de 15 dias (R10) e mesma doença somando mais de 15 dias
  em 60 (R11) abrem pendência para o RH/DP, que o Agente 4 vai acompanhar.

| Regra | O que verifica | Se violada |
| --- | --- | --- |
| R04 | Campos obrigatórios por tipo de documento | Status pendente + revisão humana |
| R05 | Fim ≥ início; emissão até 1 dia após o início; dias coerentes com o período | Revisão humana |
| R06 | CRM regular na consulta configurada | Revisão humana |
| R07 | Sem sobreposição com outro afastamento ou com férias registradas | Revisão humana |
| R08 | Confiança de cada campo ≥ 0,8 e da leitura por OCR ≥ 0,6 | Revisão humana, com o campo destacado |
| R09 | CID só se constar no documento | Campo CID fica vazio |
| R10 | Afastamento acima de 15 dias | Pendência para o RH/DP (INSS) |
| R11 | Mesma categoria de CID somando mais de 15 dias em 60 | Pendência para RH/DP e médico do trabalho |

### Verificação do CRM (R06)

| `CRM_VERIFIER` | Fonte | Uso |
| --- | --- | --- |
| `cfm` | Webservice oficial do CFM (SOAP), com `CFM_ACCESS_KEY` | Produção |
| `local` | `config/crm_registry.yaml`, com CRMs fictícios | Validação local e testes |
| `none` | Nenhuma | Todo caso vai para conferência humana |

A chave do webservice do CFM é emitida para a instituição que adotar o sistema (Res. CFM
2.129/2015). Falha ou indisponibilidade da consulta nunca bloqueia o fluxo: o caso vai para
revisão humana como "não verificado". O comando `sinergia check-cfm` mostra as operações do
WSDL vigente, e `sinergia check-cfm --crm NUMERO --uf UF` faz uma consulta.

### Férias (R07)

As férias vêm do sistema de RH/folha. Enquanto não há integração, entram por cadastro ou por
importação de um CSV exportado da folha, com as colunas `employee_id`, `start_date` e
`end_date` (datas em DD/MM/AAAA ou AAAA-MM-DD; separador vírgula ou ponto e vírgula). Um
atestado que caia dentro das férias vai para revisão humana pela R07. Importar o mesmo período
de novo não o duplica.

```bash
sinergia vacation import samples/ferias.csv
sinergia vacation add --employee-id 1001 --start 01/12/2026 --end 20/12/2026
sinergia vacation list --employee-id 7007
```

## Agente 3 — Monitoramento

Reativo baseado em modelo: mantém uma visão da base (o "modelo do mundo") e a compara com a
linha de base de cada grupo. Roda de dois jeitos: no grafo do caso, logo depois de um
afastamento válido, e sozinho, no ciclo agendado (`sinergia monitor run` ou
`POST /monitoring/run`).

```text
detect   percepção: cadastro + afastamentos válidos → visão pseudonimizada
         decisão: regras A01–A05, todas estatísticas e explicáveis
publish  ação: grava os alertas novos com explicação, versão das regras e auditoria
```

| Regra | O que detecta | Como decide | Dado de saúde? |
| --- | --- | --- | --- |
| A01 | Pico de afastamentos no setor | Taxa da semana (dias ÷ pessoas × 7) acima de média + máx(2 desvios, 2 p.p.) das até 8 semanas anteriores (mínimo de 4) | Não |
| A02 | Mesmo grupo de CID concentrado | ≥ 3 pessoas do mesmo setor ou turno com a mesma categoria de CID em 30 dias | Sim |
| A03 | Cobertura baixa em função crítica | Menos de 70% da equipe da função disponível na data | Não |
| A04 | Mesma causa perto do limite do INSS | Um colaborador soma 12 a 15 dias pelo mesmo grupo de CID em 60 dias (antecipa a R11) | Sim, por pseudônimo |
| A05 | Grupo pequeno demais | Setores e turnos com menos de 5 pessoas são agregados em "Demais grupos" ou suprimidos nas regras de saúde | — |

Os parâmetros ficam em `config/rules.yaml` (seção `monitoring`) e a versão vai junto com cada
alerta. A mesma regra, grupo e período nunca gera dois alertas, e um padrão que continua nos
dias seguintes não gera outro enquanto o alerta anterior estiver aberto. O LLM, quando configurado, só
reescreve a explicação: recebe marcadores no lugar do grupo de CID e do pseudônimo, e o texto
reescrito só é aceito se mantiver todos os números e marcadores; senão vale o texto padrão.

O agente usa um cadastro mínimo de colaboradores (sem nomes), importado de um CSV da folha
com as colunas `employee_id`, `sector`, `role`, `shift` e `critical_role` (sim/não).

```bash
# Histórico fictício com um padrão plantado para cada regra; --avaliar mede precisão e cobertura
python scripts/generate_synthetic_history.py --date 2026-10-28 --avaliar
sinergia monitor run --date 2026-10-28
sinergia alerts list
sinergia employees import samples/colaboradores.csv
```

## Agente 4 — Escalonamento

Baseado em utilidade: para cada demanda, pontua as alternativas de destino, urgência e nível
de detalhe e fica com as de maior utilidade. Não usa LLM. Nenhum encaminhamento vale antes de
uma pessoa confirmar, e o prazo de cada tarefa é acompanhado.

```text
collect             percepção: R10/R11 do Agente 2, R12/R13 do próprio agente, alertas novos do Agente 3
decide              decisão: função de utilidade; grava as propostas
await_confirmation  pausa (interrupt): uma pessoa confirma, cancela ou redireciona
dispatch            ação: abre as tarefas com prazo e registra na auditoria
```

Roda no fim do grafo do caso (depois do Agente 3) e no ciclo agendado (`sinergia monitor run`),
que agora é monitoramento → escalonamento. Cada execução do ciclo é uma sessão própria.

| Demanda | Origem | Destino principal (e outros acima do mínimo) |
| --- | --- | --- |
| R10 · afastamento acima de 15 dias | Agente 2 | RH/DP; prazo no 16º dia |
| R11 · mesma doença acima de 15 dias em 60 | Agente 2 | RH/DP e médico do trabalho |
| R12 · ausência de 30 dias ou mais (NR-7, item 7.5.9) | Agente 4 | SESMT, médico do trabalho e gestor; prazo no dia da volta |
| R13 · CID de lesão ou exposição ocupacional (S, T, Z57) | Agente 4 | SESMT e médico do trabalho; CAT até o 1º dia útil seguinte (Lei 8.213/1991, art. 22) |
| A01 · pico no setor | Agente 3 | SESMT e gestor |
| A02 · mesmo grupo de CID (indício coletivo, R13) | Agente 3 | SESMT e médico do trabalho |
| A03 · cobertura baixa em função crítica | Agente 3 | Gestor, urgência crítica |
| A04 · mesma causa perto do limite | Agente 3 | Médico do trabalho e RH/DP (sem CID) |

A utilidade de cada alternativa é:

```text
U = competência do destino − custo do nível de detalhe − custo da urgência
    − gravidade × atraso previsto em relação ao prazo
```

Os pesos, os SLAs de cada urgência (baixa 10 dias, média 5, alta 2, crítica 1), a competência
de cada destino por demanda e a cadeia de reescalonamento ficam em `config/rules.yaml` (seção
`escalation`). A pontuação nunca passa por cima de duas restrições: o gestor não recebe
demanda com dado de saúde, e o detalhe fica entre o mínimo para agir e o máximo que a origem
permite (alertas nunca reidentificam pessoas). O CID só aparece no texto para o SESMT e o
médico do trabalho.

Tarefa aberta que vence sem resposta sobe para o próximo da cadeia (por exemplo, SESMT →
coordenação do SESMT, gestor → RH/DP), um nível de urgência acima; depois de 2 tentativas fica
como vencida. O acompanhamento roda com `sinergia escalation sweep` (diariamente).

```bash
sinergia escalation list                         # sessões aguardando confirmação
sinergia escalation show <sessão>                # propostas, com a conta da utilidade
sinergia escalation decide <sessão> --reviewer "Ana (SESMT)" --cancel 4 --redirect 2=rh_dp
sinergia tasks list --destination gestor         # o que cada área tem para fazer
sinergia tasks done 7 --by "Carlos (gestor)" --note "escala refeita"
sinergia escalation sweep                        # reescala o que venceu
```

## Crew de insights (CrewAI)

Três agentes trabalham em sequência sobre um texto de fatos calculado em Python: o analista de
tendências aponta o que mudou, o redator de saúde ocupacional escreve o relatório com sugestões
de ação preventiva, e o revisor de privacidade aprova ou devolve. A crew nunca decide sobre um
caso e não vê matrícula, pseudônimo, nome, CID, alerta individual (A04) nem grupo com menos de 5
pessoas.

Depois da crew, uma conferência em Python (regra I01) barra o texto que tiver matrícula,
pseudônimo, código de CID, nome de grupo pequeno, termo estigmatizante ou qualquer número que não
esteja nos fatos. Se a crew for barrada, falhar ou não estiver configurada, entra o relatório
padrão, montado só com os fatos, e o motivo fica registrado. Todo relatório é rascunho até o
médico do trabalho aprovar.

A CrewAI usa o mesmo modelo do Groq pelo caminho compatível com a OpenAI (sem LiteLLM). Ela e o
Streamlit ficam no extra `insights`: sem ele, o sistema funciona e o relatório sai pelo modelo
padrão.

```bash
sinergia insights run --date 2026-10-28       # gera o rascunho (crew ou modelo padrão)
sinergia insights show 1
sinergia insights approve 1 --by "Dra. Ana (médica do trabalho)"
```

## Painel por perfil (Streamlit)

```bash
sinergia dashboard
```

| Perfil | O que vê |
| --- | --- |
| Colaborador | Situação do próprio protocolo, pendências e encaminhamentos, sem texto clínico |
| RH/DP | Documentos recebidos, % processado sem revisão, fila de revisão e tarefas com prazo |
| Gestor | Quem está ausente e até quando, cobertura das funções críticas e suas tarefas, sem saúde |
| SESMT / médico do trabalho | Tendência semanal por setor, alertas completos, tarefas da saúde e o relatório da crew (gerar e aprovar) |
| Auditoria | Trilha de auditoria, filtrável por ator |

O perfil é escolhido na tela: o controle de acesso por login fica para a integração com a
autenticação da empresa.

## Stack

Python 3.12 · LangGraph (com checkpoint em SQLite) · LangChain · Groq · Pydantic · FastAPI ·
SQLite · pypdf · Pillow · EasyOCR (PyTorch em CPU) · zeep · CrewAI · Streamlit · pytest · ruff

## Como executar

### 1. Ambiente

```bash
python -m venv .venv
source .venv/Scripts/activate      # Windows (Git Bash)
# source .venv/bin/activate        # Linux / macOS
pip install -r requirements.lock
pip install -e ".[dev,insights]"
```

O EasyOCR instala o PyTorch para CPU (cerca de 1 GB no disco). No primeiro uso, ele baixa os
modelos de detecção e de português (cerca de 95 MB) do GitHub para `data/ocr_models`; depois
disso o OCR funciona sem internet. Cada página leva alguns segundos em CPU.

### 2. Configuração

```bash
cp .env.example .env
```

Preencha `GROQ_API_KEY` no `.env` (o arquivo não vai para o repositório). Para rodar sem LLM, use
`LLM_PROVIDER=none`. Para validar localmente a regra do CRM, mantenha `CRM_VERIFIER=local`.
Troque o `PSEUDONYM_SALT` por um valor longo e aleatório (por exemplo, a saída de
`python -c "import secrets; print(secrets.token_hex(32))"`). Teste a conexão:

```bash
sinergia check-llm
```

### 3. Testes

```bash
pytest
ruff check . && ruff format --check .
```

### 4. Documentos sintéticos

```bash
python scripts/generate_synthetic_documents.py samples
```

Gera atestados, declarações, uma receita (tipo não aceito), fotos nítida, desfocada e pequena,
imagem em branco, PDF escaneado, PDF corrompido, um arquivo de texto e casos para cada regra do
Agente 2 (afastamento longo com CID, datas incoerentes, CRM aposentado, atestado sem assinatura,
dois atestados com o mesmo CID, uma foto com nomes acentuados, a mesma foto simulando celular —
inclinada, com fundo e compressão JPEG — e um CSV de férias) e do Agente 4 (afastamento de 35
dias, para R10 e R12, e lesão de punho com CID S62, para R13). Todos os dados são fictícios.

### 5. Validação pela linha de comando

```bash
# Envio completo: recebe na hora e devolve o protocolo
sinergia submit --file samples/atestado_medico.pdf --employee-id 1001 --start 2026-10-27

# PDF escaneado sem informações: o agente pergunta tipo, matrícula e data
sinergia submit --file samples/atestado_escaneado.pdf

# Foto desfocada: o agente pede um novo arquivo (responda com samples/atestado_foto.png)
sinergia submit --file samples/atestado_foto_desfocada.png --employee-id 1001 \
  --type atestado_medico --start 2026-10-27

# Entrega fora do prazo: recebe e abre pendência para o RH
sinergia submit --file samples/atestado_medico.pdf --employee-id 1001 --start 2026-10-01

# Consulta do protocolo: entrada, afastamento, pendências e auditoria
sinergia status SNG-AAAAMMDD-XXXXXX

# Agente 2: afastamento de 20 dias abre pendência R10 para o RH/DP
sinergia submit --file samples/atestado_longo_cid.pdf --employee-id 2002 --start 2026-10-27

# Agente 2: data de emissão incoerente (R05) vai para a fila de revisão
sinergia submit --file samples/atestado_datas_incoerentes.pdf --employee-id 3003 --start 2026-10-27
sinergia review list
sinergia review show SNG-AAAAMMDD-XXXXXX
sinergia review decide SNG-AAAAMMDD-XXXXXX --approve --reviewer "Ana (RH)" \
  --set issue_date=27/10/2026 --note "conferido no original"

# Agente 2: atestado durante as férias (R07)
sinergia vacation import samples/ferias.csv
sinergia submit --file samples/atestado_medico.pdf --employee-id 7007 --start 2026-10-27

# Agente 2: sem assinatura nem CRM (R04) só fica válido depois de corrigido
sinergia submit --file samples/atestado_sem_assinatura.pdf --employee-id 4004 --start 2026-10-27
sinergia review decide SNG-AAAAMMDD-XXXXXX --approve --reviewer "Ana (RH)" \
  --set crm_number=900123 --set crm_uf=SP --set signed=sim
```

### 6. API

```bash
uvicorn sinergia.api.app:create_default_app --factory --reload
```

A documentação interativa fica em `http://127.0.0.1:8000/docs`.

| Método | Rota | Uso |
| --- | --- | --- |
| POST | `/reception/submissions` | Primeiro envio (multipart: `file`, `employee_id`, `declared_type`, `absence_start`, `channel`) |
| POST | `/reception/submissions/{session_id}/reply` | Resposta ao que o agente pediu (mesmos campos) |
| GET | `/reception/intakes/{protocol}` | Linha de entrada e pendências do protocolo |
| GET | `/absences/{protocol}` | Registro do Agente 2 (indica se há CID, sem mostrar o código) |
| GET | `/review/cases` | Fila de revisão humana |
| GET | `/review/cases/{protocol}` | O que o revisor precisa conferir |
| POST | `/review/cases/{protocol}/decision` | `{"decision": "aprovar" ou "invalidar", "reviewer", "corrections", "note"}` |
| POST | `/vacations` | Cadastra férias (`employee_id`, `start_date`, `end_date`) |
| POST | `/vacations/import` | Importa o CSV de férias (multipart: `file`) |
| GET | `/vacations/{employee_id}` | Férias do colaborador |
| POST | `/employees/import` | Importa o cadastro de colaboradores (multipart: `file`) |
| POST | `/monitoring/run` | Roda o Agente 3 (`reference_date` opcional) |
| GET | `/alerts` | Alertas; `audience=gestao` (padrão, sem CID) ou `audience=sesmt` |
| GET | `/escalation/pending` | Sessões com encaminhamentos aguardando confirmação |
| GET | `/escalation/pending/{session_id}` | Propostas de uma sessão, com a conta da utilidade |
| POST | `/escalation/pending/{session_id}/decision` | `{"reviewer", "cancel": [ids], "redirect": {"id": "destino"}, "note"}` |
| POST | `/escalation/sweep` | Reescala as tarefas vencidas |
| GET | `/tasks` | Tarefas por `destination` e `status` |
| POST | `/tasks/{task_id}/complete` | `{"by", "note"}` |
| POST | `/insights/run` | Gera o rascunho do relatório (`reference_date` opcional) |
| GET | `/insights` | Relatórios recentes |
| GET | `/insights/{report_id}` | Um relatório, com os fatos que o embasam |
| POST | `/insights/{report_id}/decision` | `{"approve": true ou false, "by", "note"}` |
| GET | `/health` | Disponibilidade |

```bash
curl -X POST http://127.0.0.1:8000/reception/submissions \
  -F employee_id=1001 -F absence_start=2026-10-27 -F file=@samples/atestado_medico.pdf
```

## Estrutura

```text
├── config/rules.yaml              # parâmetros versionados das regras
├── config/crm_registry.yaml       # CRMs fictícios para CRM_VERIFIER=local
├── src/sinergia/
│   ├── core/                      # configuração, domínio, estado do caso, LLM, relógio
│   ├── data/                      # SQLite, entradas, afastamentos, férias, cadastro, alertas, tarefas, relatórios
│   ├── agents/reception/          # Agente 1: inspeção, classificação, objetivo, grafo
│   ├── agents/processing/         # Agente 2: leitura/OCR, extração, CRM, regras, revisão
│   ├── agents/monitoring/         # Agente 3: visão pseudonimizada, regras A01–A05, alertas
│   ├── agents/escalation/         # Agente 4: demandas, função de utilidade, confirmação, prazos
│   ├── insights/                  # crew de insights (CrewAI): fatos, crew, conferência, relatório padrão
│   ├── dashboard/                 # painel por perfil (Streamlit)
│   ├── graph.py                   # grafos do caso e do ciclo, com os agentes como subgrafos
│   ├── api/                       # FastAPI
│   ├── synthetic/                 # documentos e histórico fictícios
│   ├── bootstrap.py               # montagem das dependências
│   └── cli/                       # comando `sinergia` (envio, revisão, férias, monitoramento, escalonamento, insights, painel)
├── scripts/                       # utilitários de linha de comando
└── tests/                         # testes da fundação, dos quatro agentes, da crew, do painel e da API
```

## Privacidade (LGPD)

- Atestado é dado de saúde, categoria sensível da LGPD. Este repositório trabalha **somente com
  dados sintéticos**; a pasta `data/` (banco, checkpoints e arquivos recebidos) fica fora do Git.
- O texto extraído do documento (camada do PDF ou OCR) é usado só durante a extração e não é
  gravado no estado do grafo nem nos checkpoints.
- O CID só é registrado quando consta no documento, e a fila de revisão e a API mostram apenas
  se ele existe, nunca o código.
- O Agente 3 só vê pseudônimos (HMAC-SHA256 da matrícula com o `PSEUDONYM_SALT` do `.env`) e
  a categoria do CID (3 caracteres). Alertas de saúde coletiva valem só para grupos com pelo
  menos 5 pessoas (A05); a visão da gestão na API não mostra o grupo de CID.
- A crew de insights só recebe agregados de grupos com 5 pessoas ou mais, sem CID; o texto dela
  passa por uma conferência em Python antes de virar rascunho, e o painel mostra a cada perfil só
  o que ele precisa (o gestor nunca vê saúde).
- A trilha de auditoria registra ação, regras disparadas, versão das regras e responsável, sem
  conteúdo do documento.
- Com o Groq como provedor, ative o Zero Data Retention em *Data Controls* no console. Em
  produção, use contrato de operador ou um modelo local, trocando apenas o `LLM_PROVIDER`.
