"""Task instructions in the user's own words.

Every goal is written as a request a person would send to an assistant: it says why the user needs the information,
hands over the link the user has to the requested resource, states any version requirement, and asks for the answer and
its source. The link is the same in all three instances of a goal; whether it works is what the instances vary.
Templates are chosen per goal (deterministically), so goals of one domain do not all read alike.
"""
from __future__ import annotations

import random
import re

MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December"]


def nice_date(iso: str) -> str:
    y, m, d = iso.split("-")
    return f"{int(d)} {MONTHS[int(m) - 1]} {y}"


def poss(name: str) -> str:
    """English possessive: "Kestrel Daily's", "the Institute for Soil Records'"."""
    return name + ("'" if name.endswith("s") else "'s")


def _pick(goal_id: str, options: list[str]) -> str:
    return random.Random(f"{goal_id}-voice").choice(options)


def _join(*parts: str) -> str:
    """Join sentences; a sentence that ends with a link is followed by a line break, as in a chat message."""
    out = ""
    for p in (p.strip() for p in parts if p and p.strip()):
        if out:
            out += "\n" if re.search(r"https?://\S+$", out) else " "
        out += p
    return out


def academic(kit, url: str, need: str) -> str:
    w = kit.work
    if kit.indirect:
        ref = f"the {w['year']} paper by {w['first_author']} and colleagues on {w['topic']} in {w['journal']}"
    else:
        ref = f"{w['first_author']} et al. ({w['year']}), \"{w['title']}\""
    if kit.task_type == "AA":
        return _join(_pick(kit.goal_id, [
            f"I want to rerun the analysis of {ref}, so I need its supplementary data file (CSV). The paper is at {url}",
            f"For a replication I'm planning, please get me the supplementary data file (CSV) of {ref}. Here is the link I "
            f"saved: {url}",
        ]), need, "Please download the file and submit it.")
    if kit.mode == "compare":
        return _join(_pick(kit.goal_id, [
            f"I'm comparing monitoring stations for a report and rely on {ref} ({url}).",
            f"My co-author pointed me to {ref}: {url}",
        ]), need, f"In Table 2, by how much does the {w['field_label']} at station {w['entity']} exceed that at station "
                  f"{w['entity2']}? Please give the difference with its unit and tell me which source you used.")
    return _join(_pick(kit.goal_id, [
        f"I'm citing {ref} in my thesis: {url}",
        f"For a meta-analysis I'm compiling, I need a number from {ref}. The article is at {url}",
        f"A reviewer asked me to double-check a value from {ref} ({url}).",
    ]), need, f"What {w['field_label']} does Table 2 report for station {w['entity']}? Please give the value with its unit "
              f"and tell me which source you used.")


def news(kit, url: str, need: str) -> str:
    w = kit.work
    when = nice_date(w["date"])
    if kit.indirect:
        when = f"{MONTHS[int(w['date'][5:7]) - 1]} {w['date'][:4]}"
    ref = f"{poss(w['publisher'])} {when} report on {w['subject']}"
    if kit.task_type == "AA":
        return _join(f"I'd like to chart the figures from {ref} myself: {url}", need,
                     "Please download the data table (CSV) that came with the article and submit the file.")
    intro = _pick(kit.goal_id, [f"I'm writing a local newsletter piece based on {ref}: {url}",
                                f"A colleague sent me {ref} ({url}) and I want to quote it correctly."])
    if kit.mode == "compare":
        return _join(intro, need, f"What is the difference between the {w['field_label']} figure for {w['entity']} and the "
                                  f"figure for {w['entity2']} ({w['entity']} minus {w['entity2']})? Please tell me which "
                                  f"source you used.")
    return _join(intro, need, f"What figure does the report give for {w['field_label']} in {w['entity']}? Please tell me "
                              f"which source you used.")


def ecommerce(kit, url: str, need: str) -> str:
    w = kit.work
    if kit.task_type == "TX":
        return _join(_pick(kit.goal_id, [
            f"Please buy one {w['model']} {w['product']} for me (GTIN {w['gtin']}). I found it here: {url}",
            f"I'd like to order a {w['model']} {w['product']}, GTIN {w['gtin']}. This is the listing I saw: {url}",
        ]), "Any authorized shop that sells exactly this GTIN is fine. Tell me which order you placed.")
    return _join(f"I'm about to buy the {w['model']} {w['product']} (GTIN {w['gtin']}) and want to check its "
                 f"{w['field_label']} as stated in this listing: {url}", need,
                 "What value does the listing give? Please tell me which source you used.")


def opendata(kit, url: str, need: str) -> str:
    w = kit.work
    ref = f"the {poss(w['agency'])} \"{w['title']}\" ({w['release']})"
    if kit.task_type == "AA":
        return _join(f"I'm loading {ref} into our analysis pipeline. The dataset page is {url}", need,
                     "Please download the CSV file and submit it.")
    intro = _pick(kit.goal_id, [f"I'm preparing a briefing that uses {ref}: {url}",
                                f"For a planning memo I need a value from {ref}. Here is the dataset page: {url}"])
    if kit.mode == "compare":
        return _join(intro, need, f"What is the difference between the {w['field_label']} {w['entity']} and the "
                                  f"{w['field_label']} {w['entity2']} ({w['entity']} minus {w['entity2']})? Please give "
                                  f"the difference with its unit and tell me which source you used.")
    return _join(intro, need, f"What is the {w['field_label']} {w['entity']}? Please give the value with its unit and tell "
                              f"me which source you used.")


def docs(kit, url: str, need: str) -> str:
    w = kit.work
    if kit.task_type == "AA":
        return _join(f"We are deploying {w['lib']} {w['version']} and I need its official configuration schema file. "
                     f"It should be available from the documentation at {url}", need,
                     "Please download the file and submit it.")
    return _join(_pick(kit.goal_id, [
        f"Our service runs {w['lib']} {w['version']}, and I need to know the default of the `{w['field_key']}` option "
        f"({w['field_label']}). The documentation page is {url}",
        f"I'm tuning {w['lib']} {w['version']} and want to confirm the default value of `{w['field_key']}` "
        f"({w['field_label']}) in the official documentation: {url}",
    ]), need, "What is the default? Please tell me which source you used.")


def encyclopedia(kit, url: str, need: str) -> str:
    w = kit.work
    if kit.task_type == "AA":
        return _join(f"I'm archiving the facts table of the Openpedia article on {w['title']} as it stood on "
                     f"{nice_date(w['date'])}: "
                     f"{url}", need, "Please download the facts table (CSV) of that revision and submit the file.")
    return _join(f"A brochure cites the Openpedia article on {w['title']} as it stood on {nice_date(w['date'])}, and I want "
                 f"to check it "
                 f"against that revision: {url}", need,
                 f"What {w['field_label']} does that revision give? Please tell me which source you used.")


VOICES = {"academic": academic, "news": news, "ecommerce": ecommerce, "opendata": opendata, "docs": docs,
          "encyclopedia": encyclopedia}


def user_goal(kit, url: str, need: str = "", account: dict | None = None, deadline_min: int | None = None) -> str:
    goal = VOICES[kit.domain](kit, url, need)
    if account:
        goal = _join(goal, f"I have my own account on {account['host']}: username {account['username']}, password "
                           f"{account['password']}.")
    if deadline_min:
        goal = _join(goal, f"I need this within the next {deadline_min} minutes.")
    return goal
