# tender-intelligence-agent

Production-ready Python MCP server for an AI Tender Qualification Agent.

## What it does

This MCP server exposes tools for a ChatGPT App frontend to decide whether to bid on a tender:

1. `ingest_tender_documents` — ingest a tender package (multi-doc) and return structured, typed documents.
2. `analyse_tender` — use OpenAI to extract requirements, criteria, risks, complexity, and delivery scope.
3. `get_clay_intelligence` — fetch buyer intelligence via a replaceable Clay integration layer (mock included).
4. `qualify_bid` — apply transparent scoring logic to produce Bid / No Bid / Conditional recommendation.
5. `generate_briefing` — create an executive summary for decision makers.

---

## Folder structure

```text
.
├── .env.example
├── examples/
│   └── tool_calls.json
├── pyproject.toml
├── README.md
├── src/
│   └── tender_intelligence_agent/
│       ├── __init__.py
│       ├── config.py
│       ├── models.py
│       ├── server.py
│       └── services/
│           ├── briefing.py
│           ├── clay_adapter.py
│           ├── document_ingestion.py
│           ├── document_typing.py
│           ├── openai_tender_analysis.py
│           └── qualification.py
└── tests/
    ├── test_document_ingestion.py
    └── test_qualification.py
```

---

## Tool schemas

### `ingest_tender_documents`

**Input**
- `file_paths: string[] | null`
- `file_path: string | null` (backward compatible single-file input)
- `text: string | null` (backward compatible inline single-doc input)

**Output (TenderPackage)**
```json
{
  "documents": [
    {
      "filename": "rfp-main.pdf",
      "type": "main_rfp",
      "text": "...cleaned text...",
      "chunk_count": 3
    }
  ],
  "combined_text": "...",
  "primary_document_type": "main_rfp",
  "primary_document_filename": "rfp-main.pdf"
}
```

Document `type` is one of:
- `main_rfp`
- `requirements`
- `pricing`
- `terms`
- `appendix`
- `unknown`

### `analyse_tender`

**Input**
- `tender_package: object | null` (preferred; schema from `ingest_tender_documents`)
- `cleaned_tender_text: string | null` (backward compatibility)

**Output**
```json
{
  "requirements": ["..."],
  "evaluation_criteria": ["..."],
  "risks": ["..."],
  "complexity": "low|medium|high",
  "delivery_scope": "...",
  "cross_document_insights": ["..."],
  "document_contributions": {
    "main_rfp": "...",
    "requirements": "...",
    "terms": "...",
    "pricing": "..."
  }
}
```

Analysis behavior:
- Uses primary document (main_rfp/requirements preferred, otherwise longest doc) as base context.
- Uses all other documents as supporting context.

Analysis strategy:
- Step A: analyse primary document first for core requirements/criteria/risks/complexity/scope.
- Step B: analyse each supporting document for extra requirements, legal/commercial constraints, pricing/resource implications, and new risks.
- Step C: run cross-document reasoning for conflicts, hidden obligations, unscored requirements, and commercial feasibility constraints.
- Step D: aggregate into one unified `TenderAnalysis` response.

### `get_clay_intelligence`

**Input**
- `organisation: string`

**Output**
```json
{
  "organisation": "...",
  "company_profile": "...",
  "strategic_signals": ["..."],
  "market_activity": ["..."],
  "relationships": ["..."],
  "competitive_context": ["..."],
  "source": "clay|mock_clay_adapter"
}
```

### `qualify_bid`

**Input**
- `tender_analysis: object` (schema from `analyse_tender`)
- `clay_intelligence: object` (schema from `get_clay_intelligence`)

**Output**
```json
{
  "recommendation": "Bid|No Bid|Conditional",
  "win_probability": 0.67,
  "strategic_value": "Low|Medium|High",
  "risk_level": "Low|Medium|High",
  "key_risks": ["..."],
  "required_resources": ["..."],
  "scoring_breakdown": {
    "strategic_fit": 74.0,
    "capability_fit": 68.0,
    "commercial_viability": 61.0,
    "risk_score": 42.0,
    "relationship_advantage": 70.0,
    "conflict_penalty_count": 1.0
  },
  "rationale": "..."
}
```

### `generate_briefing`

**Input**
- `tender_analysis: object`
- `clay_intelligence: object`
- `qualification: object`

**Output**
```json
{
  "title": "...",
  "summary": "...",
  "recommendation": "...",
  "win_probability": 0.67,
  "top_considerations": ["..."],
  "immediate_actions": ["..."]
}
```

---

## Architecture notes

- **Modular services**: ingestion, document typing, OpenAI analysis, Clay adapter, qualification, briefing are separated.
- **Replaceable Clay layer**: `ClayAdapter` abstraction + `MockClayAdapter` default implementation.
- **Chunking for large docs**: each tender document is chunked by `MAX_CHUNK_CHARS`.
- **Environment-driven config**: API keys/models and chunk size controlled via env vars.
- **Safe large-set handling**: ingestion limits per-call file processing to first 200 file paths.

---

## Local run instructions

### 1) Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

### 2) Configure

```bash
cp .env.example .env
# set OPENAI_API_KEY in .env or export in shell
```

### 3) Run MCP server (stdio)

```bash
python -m tender_intelligence_agent.server
```

---

## Railway deployment notes

Use this project as a Python service and set env vars in Railway:

- `OPENAI_API_KEY`
- `OPENAI_MODEL` (optional)
- `CLAY_ADAPTER_MODE` (currently `mock`)
- `MAX_CHUNK_CHARS` (optional)

Start command:

```bash
python -m tender_intelligence_agent.server
```

---

## Example tool calls

See: `examples/tool_calls.json`.
