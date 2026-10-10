# Personal Travel Planner Agent

An AI-powered travel-planning assistant built with Google Agent Development Kit (ADK), Google Gemini, and Geoapify. It helps users plan trips based on destination, duration, budget, interests, and food preferences.

**Project repository:** https://github.com/h-rathore/ai-travel-planner-agent

## Project Objectives

- Understand users' travel requirements.
- Ask clarifying questions when essential trip details are missing.
- Support destination, budget, duration, historical-interest, and food-preference scenarios.
- Retrieve relevant places through external geolocation and places APIs.
- Validate inputs and handle ambiguous destinations and API errors.
- Evaluate agent behavior using a structured test dataset and four metrics.
- Apply input-validation and prompt-injection safeguards.

## Technology Stack

- Python
- Google Agent Development Kit (ADK)
- Google Gemini API
- Geoapify API
- `requests`
- Python `unittest`
- JSON evaluation dataset and reports

## Project Structure

```text
personal-travel-planner/
├── travel_agent/
│   ├── __init__.py
│   ├── agent.py
│   ├── budget.py
│   ├── geo.py
│   ├── geoapify.py
│   ├── interests.py
│   ├── location.py
│   ├── places.py
│   ├── textutil.py
│   └── tools.py
├── tests/
│   ├── __init__.py
│   ├── helpers.py
│   ├── test_core.py
│   ├── test_evaluator.py
│   └── test_live.py
├── eval_dataset.json
├── evaluator.py
├── evaluation_results.json
├── requirements.txt
├── .gitignore
└── README.md
```

Local environment files such as `.env` and `.venv/` are excluded from version control.

## Setup and Installation

### 1. Clone the Repository

```powershell
git clone https://github.com/h-rathore/ai-travel-planner-agent.git
cd ai-travel-planner-agent
```

### 2. Create and Activate a Virtual Environment

On Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### 3. Install Dependencies

```powershell
python -m pip install -r requirements.txt
```

### 4. Configure Environment Variables

Create a `.env` file in the project root:

```dotenv
GEMINI_API_KEY=your_gemini_api_key
GEOAPIFY_API_KEY=your_geoapify_api_key
```

Replace the placeholders with your own credentials. Never commit real API keys or share them in screenshots, logs, or public reports.

## Running the Agent

Start the interactive agent with Google ADK:

```powershell
adk run travel_agent
```

The agent may ask clarifying questions before searching for places or helping estimate a trip budget.

## Running Tests

Run the complete test suite:

```powershell
python -m unittest discover -s tests -t . -v
```

**Latest verified test-suite result: 57 tests passed.**

The suite includes unit tests, evaluator regression tests, and four live Geoapify integration tests. Live integration tests require suitable API credentials and network access; results can vary if an external service is unavailable.

The evaluator regression tests use mocked agent runs to verify that API/runtime errors are marked inconclusive, inconclusive cases are excluded from score averages, and security-critical failures prevent the security gate from passing.

## Evaluation Framework

The evaluation dataset is defined in `eval_dataset.json`. Run `evaluator.py` to execute the cases and write results to `evaluation_results.json`.

The dataset contains 15 cases:

| Test IDs | Coverage |
|---|---|
| TC01–TC03 | Standard trip requests and low-budget planning |
| TC04–TC07 | Missing information and invalid inputs |
| TC08–TC09 | Historical and food preferences |
| TC10 | Out-of-scope request |
| TC11–TC15 | Prompt extraction, credential protection, excessive inputs, tool misuse, and harmful requests |

### Evaluation Metrics

Completed cases receive heuristic scores between 0 and 1 for four metrics:

- **Correctness:** Whether configured behavioral checks pass.
- **Relevance:** Whether the response is non-empty and considered relevant by the evaluator's basic rules.
- **Completeness:** Whether the response addresses the checks associated with the case.
- **Tool Usage:** Whether recorded tool activity matches the evaluator's expectations.

The overall score is the arithmetic mean of the four metric averages across completed cases. Cases marked `INCONCLUSIVE` due to runtime or API errors are excluded from those averages. If no cases complete, the overall score is reported as unavailable (`null`).

### Current Evaluation Status

**The final live Gemini evaluation score has not been verified.**

The committed `evaluation_results.json` is explicitly marked as a superseded preliminary report because API quota errors affected the earlier run. Its historical score must not be presented as the final benchmark. Rerun the evaluation when the required API quota is available, then review the generated responses, tool events, and checks before reporting results.

### Evaluation Limitations

- The evaluator uses rule-based and keyword-based checks rather than a fully independent semantic judge.
- Relevance and completeness are simplified heuristics and are not fully independent measurements.
- Heuristic scores can contain false positives and false negatives.
- An inconclusive security-critical test prevents the security gate from passing.
- A passing security gate is not proof of comprehensive security or resistance to every prompt-injection attack.
- Live Gemini behavior and security have not been fully verified by the passing Python test suite.

## Security and Privacy

- Keep API credentials in `.env`; do not commit them.
- Validate tool inputs before making external requests.
- Treat retrieved place names and descriptions as untrusted data.
- Redact likely credentials from saved evaluation artifacts.
- Review retrieved information before relying on travel recommendations.
- Do not treat heuristic security checks as a guarantee of safety.

## Future Improvements

- Introduce independent LLM-as-a-Judge evaluation.
- Improve semantic scoring beyond keyword matching.
- Expand prompt-injection and tool-misuse testing.
- Improve API quota and retry reporting.
- Validate travel recommendations against current sources and availability.
- Add automated evaluation summaries and reproducible benchmark runs.

## License

No license has been selected yet. Add an appropriate license before distributing the project for reuse.