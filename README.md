\# Personal Travel Planner Agent



An AI-powered travel planning assistant built using Google Agent Development Kit (ADK). The project is designed to help users plan trips based on destinations, travel duration, budgets, interests, and food preferences.



\## Project Objectives



\- Understand a user's travel requirements.

\- Ask clarifying questions when important trip details are missing.

\- Support destination, budget, duration, historical-interest, and food-preference scenarios.

\- Use tools to retrieve relevant travel information where appropriate.

\- Handle invalid inputs and out-of-scope requests.

\- Evaluate responses using a structured test dataset and measurable metrics.



\## Technology Stack



\- Python

\- Google Agent Development Kit (ADK)

\- Google Gemini API

\- Geoapify API

\- Python `unittest` for project tests

\- JSON for evaluation datasets and reports



\## Project Structure



```text

personal-travel-planner/

├── travel\_agent/

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

├── eval\_dataset.json

├── evaluator.py

├── evaluation\_results.json

├── requirements.txt

├── .env

└── README.md

```



The `.env` file contains local API credentials and must not be committed to Git.



\## Setup and Installation



\### 1. Clone the repository



```bash

git clone <YOUR\_GITHUB\_REPOSITORY\_URL>

cd personal-travel-planner

```



Replace the placeholder with the actual repository URL.



\### 2. Create and activate a virtual environment



On Windows PowerShell:



```powershell

python -m venv .venv

.\\.venv\\Scripts\\Activate.ps1

```



\### 3. Install dependencies



```powershell

pip install -r requirements.txt

```



\### 4. Configure environment variables



Create a `.env` file in the project root:



```dotenv

GEMINI\_API\_KEY=your\_gemini\_api\_key

GEOAPIFY\_API\_KEY=your\_geoapify\_api\_key

```



Use your own credentials. Never commit real API keys or publish them in logs or screenshots.



\## Running the Agent



Start the interactive agent using ADK:



```powershell

adk run travel\_agent

```



Follow the agent's prompts to provide travel details and clarify missing information.



\## Running Tests



Run the project's unit and integration tests:



```powershell

python -m unittest discover -s tests -t . -v

```



Some integration tests may require valid API credentials and network access.



\## Evaluation Framework



The evaluation suite is defined in `eval\_dataset.json` and executed by `evaluator.py`. Results are written to `evaluation\_results.json`.



The dataset contains 15 test cases, covering standard travel requests, missing information, invalid inputs, user preferences, out-of-scope requests, and security-related scenarios.



\### Test Case Coverage



| Test ID | Scenario |

|---|---|

| TC01 | Valid 3-day Jaipur trip |

| TC02 | Valid 5-day Delhi trip |

| TC03 | Low-budget trip |

| TC04 | Missing destination |

| TC05 | Missing budget |

| TC06 | Invalid duration |

| TC07 | Negative budget |

| TC08 | Historical-place preference |

| TC09 | Food preference |

| TC10 | Non-travel question |

| TC11 | System prompt extraction |

| TC12 | API key extraction |

| TC13 | Excessive duration and search |

| TC14 | Credential exfiltration through tool request |

| TC15 | Harmful non-travel request |



\### Evaluation Metrics



Each completed test receives heuristic scores between 0 and 1 for the following metrics:



\- \*\*Correctness:\*\* Whether the response satisfies the configured checks.

\- \*\*Relevance:\*\* Whether the agent returns a usable, relevant response.

\- \*\*Completeness:\*\* Whether the response addresses the expected aspects of the test.

\- \*\*Tool Usage:\*\* Whether captured tool activity is appropriate for the request.



The overall score is calculated as the average of these four metrics. Metric averages exclude tests marked `INCONCLUSIVE` because of runtime or API errors.



\### Evaluation Limitations



The current evaluator uses rule-based and keyword-based checks. These are preliminary indicators, not proof of correctness. They can produce false positives and false negatives.



Security checks are limited heuristics and do not constitute a comprehensive security audit. A security-critical test that could not execute is marked inconclusive and prevents the security gate from passing.



\*\*Evaluation status:\*\* The evaluation framework has passed an offline test of its error-handling logic. A final live evaluation score has not yet been verified. The committed evaluation report must be regenerated after a successful live run before its scores can be reported as final.



\## Security and Privacy



\- Keep API credentials in `.env`.

\- Exclude `.env` and virtual-environment files from version control.

\- Redact likely credentials from saved evaluation artifacts.

\- Review tool calls and returned data before trusting generated travel recommendations.

\- Do not treat heuristic security checks as a guarantee that the agent is secure.



\## Future Improvements



\- Introduce an independent LLM-as-a-Judge evaluation.

\- Improve semantic scoring beyond keyword matching.

\- Add stronger security and prompt-injection tests.

\- Improve handling and reporting of API quota limits.

\- Validate travel recommendations against retrieved sources and current availability.



\## License



Add an appropriate license before distributing this project publicly.



