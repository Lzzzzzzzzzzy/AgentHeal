from __future__ import annotations

import json
from pathlib import Path
import re
import time

from ..tools.backend import ToolBackend, enabled_tools
from .llm import LLM
from .prompts import system_context, user_message

ACTION_RE = re.compile(r"Action:[ \t]*([A-Za-z_]+)[ \t]*(?:\s*Action Input:[ \t]*(.*))?", re.S)
_DECODER = json.JSONDecoder()
WINDOW = 12  # most recent steps kept verbatim


def tool_catalog(be: ToolBackend) -> str:
    lines = []
    for name, desc, props, req, cond in enabled_tools(be.ctx):
        args = ", ".join(f"{k}{'' if k in req else '?'}: {v.get('type', 'any')}" for k, v in props.items())
        lines.append(f"- {name}({args}): {desc}")
    skills = be.list_skills()
    if skills:
        lines.append("\nAvailable skills (load with load_skill):")
        lines += [f"- {s['name']}: {s['description']}" for s in skills]
    return "\n".join(lines)


SYSTEM = """You solve tasks by interleaving reasoning and actions.
At every step write exactly:
Thought: <your reasoning>
Action: <tool name>
Action Input: <JSON object with the tool arguments>
Then stop and wait for the Observation. Use one action per step.

Tools:
{tools}
"""


# Some models emit their native tool-call markup instead of the ReAct text format. These are normalized to the
# same (tool, arguments) pair so that the H0 baseline measures recovery behaviour rather than format compliance.
_LONGCAT = re.compile(r"<longcat_tool_call>\s*([A-Za-z_]+)(.*?)(?:</longcat_tool_call>|$)", re.S)
_LONGCAT_ARG = re.compile(r"<longcat_arg_key>(.*?)</longcat_arg_key>\s*<longcat_arg_value>(.*?)</longcat_arg_value>", re.S)
_JSON_CALL = re.compile(r"<(?:tool_call|function_call)>\s*(\{.*?\})\s*</(?:tool_call|function_call)>", re.S)
# DeepSeek's native markup, e.g. <｜｜DSML｜｜ invoke name="fetch"><｜｜DSML｜｜ parameter name="url" string="true">...
_INVOKE = re.compile(r'<[^<>]*?\binvoke\s+name="([A-Za-z_]\w*)"[^<>]*>(.*?)'
                     r'(?=<[^<>]*?/[^<>]*?invoke\s*>|<[^<>]*?\binvoke\s+name=|\Z)', re.S)
_PARAM = re.compile(r'<[^<>]*?\bparameter\s+name="([^"]+)"([^<>]*)>(.*?)</[^<>]*?parameter\s*>', re.S)
# ReAct fields written as tags, e.g. <parameter name="Action">fetch\nAction Input: {...}
_TAGGED_FIELD = re.compile(r'<[^<>]*\bname="(action[ _]input|action)"[^<>]*>[ \t]*', re.I)
_CLOSING_TAG = re.compile(r'</[^<>]*>')
FORMAT_HINT = ('Reply in this format and nothing else:\nThought: <reasoning>\nAction: search\n'
               'Action Input: {"query": "example query"}')


def _value(v: str):
    v = v.strip()
    try:
        out = json.loads(v)
        return out if not isinstance(out, str) else v
    except json.JSONDecodeError:
        return v


def parse_native(text: str):
    """(name, args, dialect) for a native tool call, or None."""
    m = _INVOKE.search(text)
    if m:
        args = {}
        for key, attrs, val in _PARAM.findall(m.group(2)):
            val = val.strip()
            if 'string="true"' in attrs:
                args[key] = val
            else:
                try:
                    args[key] = json.loads(val)
                except json.JSONDecodeError:
                    args[key] = val
        return m.group(1), args, "dsml"
    m = _LONGCAT.search(text)
    if m:
        return m.group(1), {k.strip(): _value(v) for k, v in _LONGCAT_ARG.findall(m.group(2))}, "longcat"
    m = _JSON_CALL.search(text)
    if m:
        try:
            obj = json.loads(m.group(1))
        except json.JSONDecodeError:
            return None
        args = obj.get("arguments", obj.get("parameters", {}))
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                return None
        if isinstance(obj.get("name"), str) and isinstance(args, dict):
            return obj["name"], args, "json_tool_call"
    return None


def parse_action(text: str):
    """First text-format action in a reply: (name, args, thought, extra) or None when there is no Action line.

    args is None when the Action Input is not a JSON object. Only the first JSON value after "Action Input:" is
    read, so text that follows it on the same line (a new "Thought:", prose, a second action) is ignored; extra
    is True when the reply contained further actions, which are not executed."""
    m = ACTION_RE.search(text)
    if not m and _TAGGED_FIELD.search(text):
        text = _TAGGED_FIELD.sub(lambda t: ("Action: " if t.group(1).lower() == "action" else "Action Input: "), text)
        text = _CLOSING_TAG.sub("\n", text)
        m = ACTION_RE.search(text)
    if not m:
        return None
    name, thought = m.group(1).strip(), text[:m.start()].strip()
    raw = (m.group(2) or "").lstrip().lstrip("`")
    if raw[:4].lower() == "json":
        raw = raw[4:]
    raw = raw.lstrip()
    if not raw or not raw.startswith(("{", "[")):
        rest, args = raw, ({} if not raw or raw.startswith(("Thought:", "Action")) else None)
    else:
        try:
            args, end = _DECODER.raw_decode(raw)
            rest = raw[end:]
            if not isinstance(args, dict):
                args = {"value": args}
        except json.JSONDecodeError:
            args, rest = None, ""
    extra = bool(re.search(r"Action:[ \t]*[A-Za-z_]+", rest))
    return name, args, thought, extra


def canonical_step(thought: str, name: str, args: dict) -> str:
    """The assistant turn as kept in the context: the reasoning and the one action that was executed, so the
    model never sees continuations it wrote for steps that did not happen."""
    head = thought if thought.startswith("Thought:") else f"Thought: {thought}" if thought else "Thought:"
    return f"{head}\nAction: {name}\nAction Input: {json.dumps(args, ensure_ascii=False)}"


def call_tool(be: ToolBackend, name: str, args: dict):
    msg = be.over_budget(name)
    if msg:
        return msg
    fn = getattr(be, name, None)
    allowed = {t[0] for t in enabled_tools(be.ctx)}
    if fn is None or name not in allowed:
        return f"Unknown tool {name}."
    try:
        return fn(**args)
    except TypeError as e:
        return f"Bad arguments for {name}: {e}"
    except Exception as e:
        return f"Tool error: {type(e).__name__}: {e}"


def run_react(be: ToolBackend, llm: LLM, policy: str = "explicit", max_wall: float = 1200) -> dict:
    system = system_context(be.episode) + "\n\n" + SYSTEM.format(tools=tool_catalog(be))
    task = user_message(be.episode)
    steps: list[tuple[str, object]] = []  # (assistant text, observation)
    turns: list[dict] = []                 # complete dialogue, written to traj.json
    t0 = time.time()
    parse_errors = 0
    consecutive_errors = 0
    native_calls = 0
    multi_action_replies = 0
    iterations = 0
    end_reason = "budget"
    llm_log = open(Path(be.run_dir) / "llm.jsonl", "a", encoding="utf-8")
    try:
        while (not be.reported and time.time() - t0 < max_wall and be.calls < be.max_actions + 2
               and iterations < 2 * be.max_actions):
            iterations += 1
            msgs = [{"role": "user", "content": task}]
            older = len(steps) - WINDOW
            if older > 0:
                msgs[0]["content"] += f"\n\n[{older} earlier steps omitted]"
            for a, obs in steps[-WINDOW:]:
                msgs.append({"role": "assistant", "content": a})
                if isinstance(obs, dict) and obs.get("type") == "image":
                    msgs.append({"role": "user", "content": [{"type": "text", "text": "Observation: screenshot"},
                                                             {"type": "image", "data": obs["data"]}]})
                else:
                    msgs.append({"role": "user", "content": f"Observation: {obs}"})
            text = llm.complete(system, msgs, stop=["\nObservation:"])
            llm_log.write(json.dumps({"i": iterations, "t": round(time.time() - t0, 2), "text": text,
                                      "finish": getattr(llm, "last_finish", None),
                                      "reasoning_chars": getattr(llm, "last_reasoning_chars", None)}) + "\n")
            llm_log.flush()
            parsed = parse_action(text)
            native = None if parsed else parse_native(text)
            if not parsed and not native:
                parse_errors += 1
                consecutive_errors += 1
                hint = "Your reply was empty." if not text.strip() else "No action was taken: the reply had no Action line."
                observation = f"{hint} {FORMAT_HINT}"
                steps.append((text, observation))
                turns.append({"assistant": text, "observation": observation})
                if consecutive_errors >= 5:
                    end_reason = "parse_errors"
                    break
                continue
            note = ""
            if native:
                native_calls += 1
                name, args, _ = native
                shown = canonical_step(text.split("<", 1)[0].strip(), name, args)   # keep the context in ReAct format
            else:
                name, args, thought, extra = parsed
                if args is None:
                    parse_errors += 1
                    consecutive_errors += 1
                    observation = ("The Action Input was not a valid JSON object, so the action was not executed. "
                                   + FORMAT_HINT)
                    steps.append((text, observation))
                    turns.append({"assistant": text, "observation": observation})
                    if consecutive_errors >= 5:
                        end_reason = "parse_errors"
                        break
                    continue
                shown = canonical_step(thought, name, args)
                if extra:
                    multi_action_replies += 1
                    note = "\n[Only the first action of your reply was executed. Write one action per reply.]"
            consecutive_errors = 0
            obs = call_tool(be, name, args)
            steps.append((shown, obs if isinstance(obs, dict) else str(obs)[:6000] + note))
            turn = {"assistant": text, "action": name, "args": args,
                    "observation": obs if isinstance(obs, dict) else str(obs)}
            if note:
                turn["note"] = note
            turns.append(turn)
    finally:
        llm_log.close()
        be.trajectory = {"system": system, "task": task, "turns": turns}
    if be.reported:
        end_reason = "reported"
    elif time.time() - t0 >= max_wall:
        end_reason = "wall_clock"
    return {"end_reason": end_reason, "steps": be.calls, "llm_calls": llm.usage.calls, "input_tokens": llm.usage.input_tokens,
            "output_tokens": llm.usage.output_tokens, "llm_seconds": round(llm.usage.seconds, 2),
            "wall_seconds": round(time.time() - t0, 2), "parse_errors": parse_errors, "native_calls": native_calls,
            "multi_action_replies": multi_action_replies,
            "reported": be.reported}
