# Token Cost Analysis

## Cost Per Task Type (estimated tokens)
| Task | Planning | Execution | Reflection | Total | Cost @GPT-4o |
|------|----------|-----------|------------|-------|-------------|
| Chop 3 logs | 500 | 300 | 0 | 800 | $0.002 |
| Craft workbench | 400 | 200 | 0 | 600 | $0.0015 |
| Craft pickaxe | 600 | 300 | 0 | 900 | $0.002 |
| Mine cobblestone | 800 | 500 | 100 | 1400 | $0.004 |
| Build shelter | 1500 | 1000 | 200 | 2700 | $0.007 |
| Survive night | 2000 | 1500 | 500 | 4000 | $0.01 |
| Iron tools | 3000 | 2000 | 500 | 5500 | $0.014 |
| Diamond hunt | 5000 | 4000 | 1000 | 10000 | $0.025 |

## Cost Optimization Strategies
1. Use GPT-4o-mini for routine actions ($0.15/1M vs $5/1M)
2. Cache common planning patterns
3. Summarize observations before sending to LLM
4. Batch similar actions without re-planning
5. Use skill library instead of re-planning known tasks

## Model Cost Comparison
| Model | Input $/1M | Output $/1M | Quality |
|-------|-----------|-------------|---------|
| GPT-4o | $2.50 | $10 | Best |
| GPT-4o-mini | $0.15 | $0.60 | Good |
| Claude 3.5 Sonnet | $3 | $15 | Best |
| DeepSeek V3 | $0.14 | $0.28 | Good |
| Qwen 2.5 72B | $0.30 | $0.60 | Good |
| Llama 3.1 8B (local) | $0 | $0 | OK |
