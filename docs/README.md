# Documentation

| File | Language | Contents |
|---|---|---|
| `01-catalogue-audit.md` | EN | What the catalogue actually contains. Answers the six questions asked at the start of the project. |
| `02-data-model.md` | EN | The product data model: fields, controlled vocabularies, the rules that protect recommendation quality. |
| `03-architecture.md` | EN | Deployment options, API contract, where AI belongs, evaluation plan, risks. |
| `04-validation-fr.md` | FR | Validation protocol, stated limitations, defects found and corrected. |
| `05-agent-fr.md` | FR | The conversational agent: architecture, safety rule, difficulties encountered. |
| `pfe-report-latex/` | EN | Full academic report (59 pages), LaTeX source. |

## Building the report

```bash
make report        # from the project root
```

or upload `pfe-report-latex/` to Overleaf, which needs no local installation.

Before submitting, fill in the placeholders listed in
`pfe-report-latex/README.md`: the supervisor's name, the official cover page,
and the screenshots.
