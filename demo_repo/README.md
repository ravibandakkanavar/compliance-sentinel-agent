# ShopLite (audit target)

A small Flask shop backend used as the audit target for Compliance Sentinel.

**This code is deliberately non-compliant.** It contains seeded privacy and
security violations so the agent's findings can be scored against a known
answer key in `evals/ground_truth.json`. Do not deploy it or copy from it.

```
pip install flask requests
flask --app app run
```
