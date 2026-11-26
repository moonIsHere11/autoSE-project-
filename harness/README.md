# harness: the vanilla agent harness

Domain-agnostic. It knows nothing about COBOL, Java or any particular verifier; everything specific
is plugged in through three interfaces in `types.py` and named in `config.yaml`.

```
harness/
  types.py      Task, Candidate, Verdict + the plug-in Protocols: LLM, Verifier, Profile, ToolPack
  registry.py   ToolRegistry (schema + handler, arg filtering, error wrapping, output clipping), load_adapter()
  context.py    ContextManager (elide old tool output past a budget, never drop a tool_call/result pair),
                Scratchpad (agent notes re-pinned into the system prompt every turn)
  agent.py      Agent + AgentSpec: the configurable loop every agent uses (hooks, budgets, finish, sub-agents)
  policy.py     ToolPolicy: which tools an agent is offered and whether a call may run
  prompt.py     PromptBuilder: the system prompt as named sections, re-rendered every turn
  loop.py       AgentLoop: the old interface, kept for Runner, implemented on Agent
  runner.py     Runner: per task, loop until the verifier says green or the attempt budget is spent;
                owns the built-in tools `notes` and `submit` (snapshot staging -> verify -> feedback)
  workspace.py  workspace layout + submit semantics (staging/, submissions/S-NNNN/, reports/, runs/)
  feedback.py   Verdict -> the text the agent reads (findings, counterexamples, reproduce commands)
  events.py     append-only runs/<id>/events.jsonl
  llm/          LLMError + the default adapter (groq.py)
  config.py     build_runner(): compose everything from config.yaml
  cli.py        `bin/harness run|tasks --workspace W`
```

## The agent template (`agent.py`, `policy.py`, `prompt.py`)
Every agent (translator, planner, explorer, ...) is an `Agent(llm, registry, spec)`. The registry holds what tools
exist (`registry.tool(..., tags=("read",))`); the `AgentSpec` holds what makes this agent this agent:
```python
spec = AgentSpec("planner", prompt, policy=ToolPolicy(allow_tags={"read", "plan_edit"}, limits={"explore": 5}),
                 max_steps=25, max_tokens=200_000, result_schema=RESULT)   # result_schema adds a `finish` tool
agent = Agent(llm, registry, spec, events=ws.events, approve=None)        # approve: callback for ToolPolicy.ask
agent.add_prompt_section("notes", pad.read, after="role")                 # str or callable, rendered every turn
agent.deny_tools("write_file"); agent.set_budget(max_steps=10)
agent.add_stop_condition("green", lambda state: state.get("green"))
agent.on("before_tool", hook)          # also before_model, after_model, after_tool, on_text_reply, on_stop
registry.replace(agent.as_tool("explore", "...", params, make_message, spec=explorer_spec))  # sub-agent as a tool
result = agent.run("task message")     # AgentResult(stop_reason, output, steps, usage, messages, state)
```
The policy is checked when tools are offered and again on every call, so a model cannot run a tool it was not
given. `loop.AgentLoop` is the old interface, kept for `Runner`, implemented on `Agent`.

## Plugging things in (config.yaml)
```yaml
harness:
  llm:      {adapter: harness.llm.groq:GroqLLM, model: openai/gpt-oss-20b}
  verifier: {adapter: adapters.verifiers.nan:NanVerifier}      # or adapters.verifiers.contract:ContractVerifier
  profile:  {adapter: extras.cobol_java:Profile}
  context:  {budget: 36000, keep_last: 8, max_tool_output: 5000}
  toolset:  [read_file, write_file, build]                     # optional allow-list (notes + submit always on)
```
An adapter is any `package.module:Class`; extra keys under it become constructor kwargs.
- **LLM:** `model` + `chat(messages, tools) -> (message, usage)`; raise `LLMError(recoverable=True)` for unusable output.
- **Verifier:** `verify(Candidate) -> Verdict`. A `status` of `error` is a free retry (checker infra failure).
- **Profile:** `tasks()`, `system_prompt()`, `first_message()`, `toolpacks()`. A tool pack's `register(registry, env)` adds tools.

## How to call me
```
export GROQ_API_KEY=...
bin/harness tasks --workspace W                    # list the tasks the profile finds (no LLM)
bin/harness run   --workspace W [--tasks A,B]      # agent loop + verification
python3 -m unittest discover -s tests/harness -t . # unit tests (no LLM, no Docker)
```
