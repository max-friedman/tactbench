# Does the system turn reach each model? (Round 53)

Written by `experiments/system_turn_check.py` against llama-cpp-python's server. *Tokens* are prompt token counts of the same user turn under the preflight's system turn, under that turn with padding appended, and under no system turn. The preflight (`LLMPolicy.system_turn_reaches_the_model`) requires the padded count to exceed the short one; a template that drops the system turn gives two equal counts. The no-system count is shown because some templates insert a default system prompt, which made comparing against it refuse Granite. *Repeated* is how many of the seven preflight words the model repeated when the word was sent only in the system turn -- R51's check, which a small model can fail with the turn delivered. *Runs use* is how published runs deliver the system prompt.

| model | tokens, system turn | padded | no system turn | preflight passes | repeated | runs use |
|---|---|---|---|---|---|---|
| `qwen2.5-0.5b` | 37 | 67 | 35 | yes | 7/7 | system turn |
| `llama-3.2-1b` | 59 | 89 | 41 | yes | 3/7 | system turn |
| `qwen2.5-1.5b` | 37 | 67 | 35 | yes | 7/7 | system turn |
| `smollm2-1.7b` | 39 | 69 | 36 | yes | 7/7 | system turn |
| `gemma-2-2b` | — | — | — | error: HTTPError | — | user turn (`--no-system-role`) |
| `qwen2.5-3b` | 37 | 67 | 35 | yes | 7/7 | system turn |
| `llama-3.2-3b` | 59 | 89 | 41 | yes | 7/7 | system turn |
| `phi-3.5-mini` | 40 | 71 | 15 | yes | 7/7 | system turn |
| `gemma-3-4b` | 34 | 64 | 15 | yes | 7/7 | system turn |
| `qwen2.5-7b` | 37 | 67 | 35 | yes | 7/7 | system turn |
| `llama-3.1-8b` | 59 | 89 | 41 | yes | 7/7 | system turn |
| `granite-3.3-2b` | 37 | 70 | 64 | yes | 7/7 | system turn |
| `phi-4-mini` | 29 | 59 | 9 | yes | 7/7 | system turn |
| `mistral-7b` | 11 | 11 | 11 | **no** | 0/7 | user turn (`--no-system-role`) |
