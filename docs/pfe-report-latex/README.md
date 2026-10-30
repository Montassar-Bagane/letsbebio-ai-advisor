# Final Project Report — LaTeX source (EPI DIGITAL SCHOOL Standard)

## Compiling

```bash
latexmk -pdf main.tex        # recommended, handles the three passes
```

or, without latexmk:

```bash
pdflatex main.tex
pdflatex main.tex            # second pass for table of contents & list of figures
pdflatex main.tex            # third pass for cross-references
```

Output: `main.pdf`.

## Conformity with EPI DIGITAL SCHOOL Guidelines

This report strictly conforms to the official EPI graduation internship guidelines (Année Universitaire 2025/2026), harmonized with the reference report structure of fellow students at EPI Digital School:
- **4 numbered chapters**:
  - Chapter 1: General Context and Environment of the Project
  - Chapter 2: Market Study and State of the Art (featuring CRISP-DM, Information Extraction, and Tool-Augmented ReAct LLM agents)
  - Chapter 3: Methodology, Data Collection, and Analytical Framework (schema auditing, EDA, preprocessing, and scoring formulation)
  - Chapter 4: Implementation, Deployment, and Agent Evaluation (FastAPI, WordPress, Docker, and comprehensive 22-profile empirical evaluation)
- **Cover Page** strictly formatted according to the official EPI layout (Ministère de l'Enseignement Supérieur, EPI Digital School, Spécialité IA, 3-column metadata block).
- **CRISP-DM lifecycle** thoroughly articulated across business understanding, data understanding, preparation, modeling, evaluation, and deployment.
- **Figures and Tables parity**: The report now balances comprehensive data tables with **19 figures and screenshots**.

## Figures & Screenshot Placeholders in `figures/`

All 19 figures are pre-generated as clean placeholder PNGs in `docs/pfe-report-latex/figures/`. You can compile the document immediately without any missing-file errors. To add your real screenshots, simply overwrite the respective PNG file:

| File in `figures/` | Caption / Screenshot Purpose | Chapter |
|---|---|---|
| `company_workflow.png` | Host Organisation & Project Operational Workflow | Chapter 1 |
| `gantt_schedule.png` | Project Temporal Organisation & Gantt Chart | Chapter 1 |
| `rag_vs_tool_agent.png` | Comparison: Ungrounded LLM Chatbot vs Tool-Grounded ReAct Agent | Chapter 2 |
| `crisp_dm_cycle.png` | The CRISP-DM Methodology Lifecycle | Chapter 2 |
| `project_workflow.png` | End-to-End Data Transformation Workflow | Chapter 3 |
| `woocommerce_erd.png` | WooCommerce Database Entity-Relationship Diagram (ERD) | Chapter 3 |
| `category_distribution.png` | Distribution of Products Across Primary Catalogue Categories | Chapter 3 |
| `description_lengths.png` | Histogram of Product Description Character Lengths | Chapter 3 |
| `data_model_schema.png` | Derived Multi-Dimensional Product Data Model Schema | Chapter 3 |
| `system_architecture.png` | System Multi-Layer Architecture & Data Flow Diagram | Chapter 4 |
| `extraction_pipeline_flow.png` | Extraction, Normalisation & Pack Resolution Flowchart | Chapter 4 |
| `screenshot_fastapi_swagger.png` | Interactive API Documentation via FastAPI Swagger UI | Chapter 4 |
| `screenshot_wordpress_plugin.png` | WordPress Administration & Shortcode Storefront View | Chapter 4 |
| `screenshot_demo_questionnaire.png` | Interactive Web Demo Interface --- Guided Questionnaire | Chapter 4 |
| `screenshot_demo_routine.png` | Interactive Web Demo Interface --- Generated Skincare Routine | Chapter 4 |
| `screenshot_agent_chat.png` | Conversational Shopping Adviser Chat Interface | Chapter 4 |
| `agent_react_cycle.png` | Conversational Agent ReAct Loop & Tool Execution Cycle | Chapter 4 |
| `screenshot_docker_deployment.png` | Docker Compose Multi-Container Deployment Status | Chapter 4 |
| `evaluation_benchmark_chart.png` | Evaluation Benchmark Across 22 Customer Scenarios | Chapter 4 |

## Before Submission --- Quick Checklist

| Where | Status |
|---|---|
| `main.tex`, macro `\supervisor` | Configured to **Sawssen Guerbej** |
| `chapters/00-cover.tex` | Integrated official EPI template (`official_cover_template.pdf`) with TikZ overlay |
| `chapters/00-dedication.tex` | Personalise dedication text if desired |
| `figures/` | Drop in your actual captured PNG screenshots over the placeholders |
