# LLM Structured Output Guide

## Why Structured Output
- Prevents JSON parse errors
- Enables automatic action execution
- Reduces hallucination via schema validation
- Makes agent behavior predictable

## OpenAI JSON Mode
```python
response = client.chat.completions.create(
    model="gpt-4o",
    response_format={"type": "json_object"},
    messages=[...]
)
```

## JSON Schema for Plan Output
```json
{
  "type": "object",
  "properties": {
    "status": {"type": "string", "enum": ["in_progress", "complete", "blocked"]},
    "reasoning": {"type": "string"},
    "actions": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "type": {"type": "string"},
          "parameters": {"type": "object"}
        },
        "required": ["type"]
      }
    }
  },
  "required": ["status", "actions"]
}
```

## Validation Pipeline
1. LLM generates JSON
2. Parse with json.loads
3. Validate against schema (pydantic/jsonschema)
4. Check action types against known actions
5. Check parameter types and ranges
6. Execute or reject with feedback
