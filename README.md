# AgentHeal

This is the code repo for **AgentHeal: Evaluating Goal-Preserving Resource Recovery of Web Agent under Access Barriers**.

---

## 1. Setup

```bash
bash setup.sh
```
`setup.sh` creates `.venv/` inside the repository. 

## 2. Run one model

`scripts/02_main_react.sh` is the run script. Set the model name in the script, and pass the endpoint and key through
the environment.

```bash
# edit MODEL_NAME / MODEL_TAG / API_PROVIDER at the top of scripts/02_main_react.sh
export AGENTHEAL_API_URL="https://your-endpoint.example/v1"   # openai: include /v1; anthropic: no /v1
export AGENTHEAL_API_KEY="your-key"
bash scripts/00_smoke_test.sh          # one goal per family
bash scripts/02_main_react.sh          # full sandbox + real-web replay
```


Each model script sends one short request first (`PING OK ...`) and stops if the model name or endpoint is wrong.
Set `SKIP_PING=1` to skip that check. 

## 3. Experiments

| Script | What it runs | API |
|---|---|---|
| `scripts/00_smoke_test.sh` | API check, one goal per barrier family | yes |
| `scripts/02_main_react.sh` | ReAct, sandbox and real-web replay | yes |
| `scripts/07_report.sh` | tables from finished runs | no |
| `scripts/browse.sh` | open one episode in a local browser | no |

Finished episodes are skipped on restart. `RERUN=1` runs them again.


## 4. Outputs

```
runs/<sandbox|real>/<MODEL_TAG>__react__S0__C0/
    <episode_id>/s<seed>/
        report.json          the agent's final structured report
        trace.jsonl          every action and observation
        gym_log.json         every request the agent made, with violation tags
        result.json          the scored outcome
```

`bash scripts/07_report.sh` writes `reports/<sandbox|real>/paper_results.{csv,md,tex}` and `summary.json`.



