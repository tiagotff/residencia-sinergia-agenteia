# Sinergia — gestão de afastamentos com agentes de IA

Sistema multiagente que recebe, confere e registra atestados e, a partir do histórico, revela
tendências coletivas de adoecimento para a saúde ocupacional agir preventivamente. Quatro agentes
especializados trabalham em cadeia, orquestrados pelo **LangGraph**, e nenhuma decisão sobre
pessoas sai do sistema sem passar por um profissional.

| Agente | Tipo | Objetivo | Situação |
| --- | --- | --- | --- |
| A1 · Recepção | Baseado em objetivos | Obter um dossiê de entrada completo e válido | Implementado |
| A2 · Processamento | Reativo simples | Transformar o documento em registro estruturado | Implementado |
| A3 · Monitoramento | Reativo baseado em modelo | Detectar padrões fora do esperado | Planejado |
| A4 · Escalonamento | Baseado em utilidade | Encaminhar cada caso ao responsável certo | Planejado |

Uma crew de insights em **CrewAI** gera, fora do fluxo principal, relatórios para o SESMT a
partir de dados agregados e pseudonimizados.

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

## Stack

Python 3.12 · LangGraph (com checkpoint em SQLite) · LangChain · Groq · Pydantic · FastAPI ·
SQLite · pypdf · Pillow · EasyOCR (PyTorch em CPU) · zeep · pytest · ruff

## Como executar

### 1. Ambiente

```bash
python -m venv .venv
source .venv/Scripts/activate      # Windows (Git Bash)
# source .venv/bin/activate        # Linux / macOS
pip install -r requirements.lock
pip install -e ".[dev]"
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
Teste a conexão:

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
inclinada, com fundo e compressão JPEG — e um CSV de férias). Todos os dados são fictícios.

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
│   ├── data/                      # SQLite, entradas, afastamentos, férias, arquivos, auditoria
│   ├── agents/reception/          # Agente 1: inspeção, classificação, objetivo, grafo
│   ├── agents/processing/         # Agente 2: leitura/OCR, extração, CRM, regras, revisão
│   ├── graph.py                   # grafo do caso, com os agentes como subgrafos
│   ├── api/                       # FastAPI
│   ├── synthetic/                 # geradores de documentos fictícios
│   ├── bootstrap.py               # montagem das dependências
│   └── cli/                       # comando `sinergia` (colaborador, revisão, férias, checagens)
├── scripts/                       # utilitários de linha de comando
└── tests/                         # testes da fundação, do Agente 1 e da API
```

## Privacidade (LGPD)

- Atestado é dado de saúde, categoria sensível da LGPD. Este repositório trabalha **somente com
  dados sintéticos**; a pasta `data/` (banco, checkpoints e arquivos recebidos) fica fora do Git.
- O texto extraído do documento (camada do PDF ou OCR) é usado só durante a extração e não é
  gravado no estado do grafo nem nos checkpoints.
- O CID só é registrado quando consta no documento, e a fila de revisão e a API mostram apenas
  se ele existe, nunca o código.
- A trilha de auditoria registra ação, regras disparadas, versão das regras e responsável, sem
  conteúdo do documento.
- Com o Groq como provedor, ative o Zero Data Retention em *Data Controls* no console. Em
  produção, use contrato de operador ou um modelo local, trocando apenas o `LLM_PROVIDER`.
