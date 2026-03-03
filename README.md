# tender-intelligence-agent

Production-ready Python MCP server for an AI Tender Qualification Agent.

## What it does

This MCP server exposes tools for a ChatGPT App frontend to decide whether to bid on a tender:

1. `ingest_tender_documents` — ingest a tender package (multi-doc) and return structured, typed documents.
2. `sculpt_find_and_enrich_company` — proxy call to Sculpt_Hack `find-and-enrich-company`.
3. `sculpt_find_and_enrich_contacts_at_company` — proxy call to Sculpt_Hack `find-and-enrich-contacts-at-company`.
4. `validate_buyer_identity` — canonicalize buyer name/domain using Sculpt_Hack enrichment payloads (or direct inputs).
5. `analyse_tender` — use OpenAI to extract requirements, criteria, risks, complexity, and delivery scope.
6. `sync_tender_to_clay` — upsert Buyer by domain then create Tender row in Clay.
7. `competitor_review` — normalize competitor context payloads into deterministic competitor structures.
8. `capability_assessment` — merge US capability context (inline JSON or file) with buyer/competitor domains.
9. `qualify_bid` — apply transparent scoring logic to produce Bid / No Bid / Conditional recommendation.
10. `generate_briefing` — create an executive summary for decision makers.
11. `run_tender_workflow` — deterministic orchestration across ingestion, buyer validation, analysis, competitor review, capability assessment, qualification, and briefing.

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
│           ├── clay_client.py
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

### `validate_buyer_identity`

**Input**
- `buyer_name: string | null`
- `buyer_domain: string | null`
- `buyer_enrichment: object | null` (Sculpt_Hack `find-and-enrich-company` payload)

**Output**
```json
{
  "buyer_name": "...",
  "buyer_domain": "acme.com",
  "company_profile": "...",
  "strategic_signals": ["..."],
  "relationship_signals": ["..."],
  "source": "sculpt_hack|manual"
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


### `sync_tender_to_clay`

**Input**
- `buyer_name: string`
- `buyer_domain: string`
- `tender_analysis: object` (schema from `analyse_tender`)

**Output**
```json
{
  "buyer": {"id": "row_x", "domain": "acme.com", "company_name": "Acme"},
  "tender": {"id": "row_y", "buyer_domain": "acme.com", "tender_title": "..."}
}
```

Flow:
1) normalize `buyer_domain`
2) upsert Buyer in Buyer Intelligence table (`domain` unique key)
3) create Tender row in Tender Pipeline table with `buyer_domain`

`buyer_ref` is optional and intentionally skipped for hackathon simplicity; Clay lookup/waterfall can link by domain.

### `competitor_review`

**Input**
- `buyer_domain: string`
- `competitor_context: object | null` (Sculpt_Hack competitor payload)

**Output**
```json
{
  "buyer_domain": "acme.com",
  "competitors": [{"name": "OtherCo", "domain": "otherco.com"}],
  "competitor_domains": ["otherco.com"],
  "competitive_context": ["OtherCo active in buyer market."],
  "source": "sculpt_hack|empty"
}
```

### `capability_assessment`

**Input**
- `buyer_domain: string`
- `competitor_review: object | null`
- `us_context: object | null`
- `us_table_path: string | null`

**Output**
```json
{
  "buyer_domain": "acme.com",
  "buyer_summary": "...",
  "buyer_capability": {},
  "competitor_capabilities": [],
  "relationship_signals": ["..."],
  "strategic_signals": ["..."],
  "coverage_gaps": ["..."],
  "source": "us_context|json_file|empty"
}
```


### `run_tender_workflow`

**Input**
- `files: string[] | null`
- `text: string | null`
- `buyer_name: string | null`
- `buyer_domain: string | null`
- `buyer_enrichment: object | null`
- `us_context: object | null`
- `competitor_context: object | null`
- `us_table_path: string | null`
- `correlation_id: string | null`

**Output**
- `WorkflowResult` with either full successful payloads or structured failure:
```json
{
  "ok": false,
  "correlation_id": "...",
  "error": {
    "step": "validate_buyer_identity",
    "error_type": "ValueError",
    "message": "buyer_domain is required",
    "debug_context": {}
  }
}
```

Execution order (fail-fast): ingest -> validate buyer identity -> analyse -> competitor review -> capability assessment -> qualify -> briefing.

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


## Response style controller

`StyleConfig` supports:
- `mode`: `INTERMEDIATE | FINAL`
- `audience`: `BID_MANAGER` (default)

Behavior:
- **INTERMEDIATE**: <=120 words, <=5 bullets, no tender text restatement, ends with one forward question.
- **FINAL**: detailed structured briefing sections.

Threading through tools:
- `analyse_tender(..., style_config={"mode":"INTERMEDIATE","audience":"BID_MANAGER"})`
- `qualify_bid(..., style_config={"mode":"INTERMEDIATE","audience":"BID_MANAGER"})`
- `generate_briefing(..., style_config={"mode":"FINAL","audience":"BID_MANAGER"})`

Prompt templates:
- Analyse (INTERMEDIATE): `Mode: INTERMEDIATE. Respond concisely for a BID_MANAGER. Do not repeat source tender text. Max 120 words, up to 5 bullets, and end with one forward question.`
- Qualify (INTERMEDIATE): `Mode: INTERMEDIATE. Provide short bid/no-bid rationale with key deltas only. Max 120 words, max 5 bullets, no tender-text restatement, and end with one decision-driving question.`
- Briefing (FINAL): `Mode: FINAL for BID_MANAGER. Produce a detailed briefing with sections: Executive Summary, Recommendation, Win Themes, Key Risks, Next Actions. Include quantified values when available (win_probability, risk_level, strategic_value).`

Example 4-turn transcript:
1. `analyse_tender` (INTERMEDIATE) → concise status + one question.
2. `qualify_bid` (INTERMEDIATE) → concise recommendation + one question.
3. `sync_tender_to_clay` → persistence confirmation.
4. `generate_briefing` (FINAL) → full detailed sections with quantified metrics.


## Architecture notes

- **Modular services**: ingestion, document typing, OpenAI analysis, Clay adapter, qualification, briefing are separated.
- **Replaceable Clay layer**: `ClayAdapter` abstraction + `MockClayAdapter` default implementation.
- **Chunking for large docs**: each tender document is chunked by `MAX_CHUNK_CHARS`.
- **Environment-driven config**: API keys/models and chunk size controlled via env vars.
- **Safe large-set handling**: ingestion limits per-call file processing to first 200 file paths.

---


## Clay.com REST API integration notes

> ⚠️ Clay's REST API documentation and endpoint naming may differ across accounts/workspaces.
> The examples below reflect the safest commonly used REST patterns and are implemented in a configurable client (`ClayComClient`).
> Validate exact paths/params against your Clay workspace docs before production use.

### Authentication with API key

Use an API key header (Bearer token pattern):

```bash
curl -X GET "https://api.clay.com/api/v1/tables" \
  -H "Authorization: Bearer $CLAY_API_KEY" \
  -H "Accept: application/json"
```

### List available tables

```bash
curl -X GET "https://api.clay.com/api/v1/tables" \
  -H "Authorization: Bearer $CLAY_API_KEY" \
  -H "Accept: application/json"
```

Typical response shape:

```json
{
  "tables": [
    {
      "id": "tbl_123",
      "name": "company_enrichment",
      "workspace_id": "ws_456"
    }
  ]
}
```

### Query a table row by field value (domain)

```bash
curl -G "https://api.clay.com/api/v1/tables/tbl_123/rows" \
  -H "Authorization: Bearer $CLAY_API_KEY" \
  --data-urlencode "field=domain" \
  --data-urlencode "value=acme.com" \
  --data-urlencode "limit=1"
```

Typical enriched row response shape:

```json
{
  "rows": [
    {
      "id": "row_001",
      "domain": "acme.com",
      "company_name": "Acme Inc",
      "firmographics_summary": "Enterprise B2B software provider in North America",
      "strategic_signals": [
        "Announced AI-led cost transformation program",
        "Expanded EMEA partner ecosystem"
      ],
      "leadership_changes": [
        "New CIO appointed in Q2"
      ],
      "market_activity": [
        "Opened two new procurement-led initiatives"
      ],
      "relationships": [
        "Existing advisory relationship with major SI"
      ],
      "competitive_context": [
        "Incumbent supplier under performance review"
      ],
      "tech_stack": ["Salesforce", "Snowflake", "Azure"],
      "funding": {
        "last_round": "Series D",
        "amount": 120000000
      },
      "hiring_trends": {
        "engineering_90d": 14,
        "procurement_90d": 4
      }
    }
  ]
}
```



### Create a row

```bash
curl -X POST "https://api.clay.com/api/v1/tables/tbl_123/rows" \
  -H "Authorization: Bearer $CLAY_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "fields": {
      "domain": "acme.com",
      "company_name": "Acme Inc"
    }
  }'
```

### Python async client

See `src/tender_intelligence_agent/services/clay_client.py` for `ClayComClient`.

Safest fallback approach if API docs/endpoints are uncertain:
- Keep `CLAY_ADAPTER_MODE=mock` in production until endpoint contract is confirmed.
- Validate `list_tables` first, then run a single-domain lookup on a non-critical table.
- Map Clay fields defensively (accept both top-level and nested `fields` keys).
- Log raw payload samples in staging before tightening strict parsing.


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
# edit .env with your real keys (do not commit secrets)
```

We keep `.env.example` in git as a template, and use `.env` locally for actual values.
The included `.gitignore` excludes `.env` so credentials are not committed.

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
