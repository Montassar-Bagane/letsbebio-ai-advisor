# Pipeline — offline extraction

These scripts are how the product data model was worked out. The running
service does the same work internally (`service/app/catalogue.py`), so the
pipeline is not needed in production — it is kept because it is the fastest way
to inspect a catalogue and because it documents the reasoning.

The extraction rules themselves live in `../service/app/extraction.py` and are
imported by `2_extract.py`. There is deliberately only one copy: the rules were
duplicated at one point and the two versions drifted.

## Order

```bash
# 0. explore the catalogue structure (optional, read-only)
sudo mysql <db> < 0_explore.sql > exploration.txt

# 1. export products to JSONL
sudo mysql <db> --batch --raw --skip-column-names < 1_export.sql > products.jsonl

# 2. extract structured attributes (rule-based, free, ~2 seconds)
python3 2_extract.py

# 3. recover what each pack contains
python3 3_resolve_packs.py

# 4. produce catalogue.json, routines.json and the QA report
python3 4_finalize.py
```

## Outputs

| File | Contents |
|---|---|
| `products.jsonl` | raw product text and commercial fields |
| `products_enriched.jsonl` | the structured model, one product per line |
| `catalogue.json` | the same, as a single array |
| `routines.json` | packs with resolved components |
| `qa_report.txt` | coverage, vocabulary distribution, products to review |
| `pack_matches.txt` | pack composition audit — read this, it shows the matching |
| `low_confidence_ids.txt` | products the rules could not read confidently |

All of these are git-ignored: they are rebuilt in seconds.

## The optional LLM variant

`extract_llm_optional.py` produces the **same schema** using a language model
instead of rules. It is better at ingredients and at free-form summaries, and
costs money per product.

Because the schema is identical, the sensible use is to run it on
`low_confidence_ids.txt` only, rather than the whole catalogue.

```bash
export ANTHROPIC_API_KEY=...      # or edit it for any OpenAI-compatible API
python3 extract_llm_optional.py --limit 12     # test on 12 first
```
