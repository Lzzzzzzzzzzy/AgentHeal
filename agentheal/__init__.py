"""AgentHeal: Evaluating Goal-Preserving Resource Recovery of Web Agents under Access Barriers.

Package layout
--------------
generator/   deterministic dataset builder (9 barrier families x 25 goals -> 450 barrier
             instances + 225 barrier-free twins) and quality gates
gym/         sandbox mini-web: forward proxy + virtual hosts, protocol-faithful barriers,
             search engine, Memento archive, self-hosted verification challenges, inert
             honeypots, request logging with violation tags
tools/       agent tool surface (HTTP, DOM browser, pixel-level computer use, wait,
             ask_user, submit_report, shell)
agents/      ReAct loop and scripted baselines used to validate the benchmark
scoring/     provenance attribution, violation detection, outcome assignment, metrics, stats
experiments/ factorial configurations, experiment registry, runner and reports
"""

__version__ = "0.1.0"
