# Sinergia — gestão de afastamentos com agentes de IA

Sistema multiagente que recebe, confere e registra atestados e, a partir do histórico, revela
tendências coletivas de adoecimento para a saúde ocupacional agir preventivamente. Quatro agentes
especializados trabalham em cadeia, orquestrados pelo **LangGraph**, e nenhuma decisão sobre
pessoas sai do sistema sem passar por um profissional.

| Agente | Tipo | Objetivo | Situação |
| --- | --- | --- | --- |
| A1 · Recepção | Baseado em objetivos | Obter um dossiê de entrada completo e válido | Implementado |
| A2 · Processamento | Reativo simples | Transformar o documento em registro estruturado | Planejado |
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

## Stack

Python 3.12 · LangGraph (com checkpoint em SQLite) · LangChain · Groq · Pydantic · FastAPI ·
SQLite · pypdf · Pillow · pytest · ruff

## Como executar

### 1. Ambiente

```bash
python -m venv .venv
source .venv/Scripts/activate      # Windows (Git Bash)
# source .venv/bin/activate        # Linux / macOS
pip install -r requirements.lock
pip install -e ".[dev]"
```

### 2. Configuração

```bash
cp .env.example .env
```

Preencha `GROQ_API_KEY` no `.env` (o arquivo não vai para o repositório). Para rodar sem LLM, use
`LLM_PROVIDER=none`. Teste a conexão:

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
imagem em branco, PDF escaneado, PDF corrompido e um arquivo de texto. Todos os dados são
fictícios.

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

# Consulta do protocolo, pendências e auditoria
sinergia status SNG-AAAAMMDD-XXXXXX
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
| GET | `/health` | Disponibilidade |

```bash
curl -X POST http://127.0.0.1:8000/reception/submissions \
  -F employee_id=1001 -F absence_start=2026-10-27 -F file=@samples/atestado_medico.pdf
```

## Estrutura

```text
├── config/rules.yaml              # parâmetros versionados das regras
├── src/sinergia/
│   ├── core/                      # configuração, domínio, estado do caso, LLM, relógio
│   ├── data/                      # SQLite, linhas de entrada, arquivos, auditoria
│   ├── agents/reception/          # Agente 1: inspeção, classificação, objetivo, grafo
│   ├── api/                       # FastAPI
│   ├── synthetic/                 # geradores de documentos fictícios
│   ├── bootstrap.py               # montagem das dependências
│   └── cli.py                     # comando `sinergia`
├── scripts/                       # utilitários de linha de comando
└── tests/                         # testes da fundação, do Agente 1 e da API
```

## Privacidade (LGPD)

- Atestado é dado de saúde, categoria sensível da LGPD. Este repositório trabalha **somente com
  dados sintéticos**; a pasta `data/` (banco, checkpoints e arquivos recebidos) fica fora do Git.
- O texto extraído do documento serve só para classificar o tipo e não é gravado no estado do
  grafo nem nos checkpoints.
- A trilha de auditoria registra ação, regras disparadas, versão das regras e responsável, sem
  conteúdo do documento.
- Com o Groq como provedor, ative o Zero Data Retention em *Data Controls* no console. Em
  produção, use contrato de operador ou um modelo local, trocando apenas o `LLM_PROVIDER`.
