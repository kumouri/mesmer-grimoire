"""Zethus asks with the harness's question tool, never for an exact phrase
(``zethus/docs/ask-with-the-question-tool.md``).

Ceryce's report, 2026-11-04 (paraphrased): the agent asked her to reply with one of two exact phrases.
These tests pin the shared rule in every copy of the agent and the working agreement, keep the
safety wording on the converted confirm gates, and fail when any Zethus prompt or skill asks for an
exact reply.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
KIT = REPO / "zethus"
AGENTS = (KIT / "com.github.copilot" / "agents" / "zethus.agent.md", KIT / "agents" / "zethus.agent.md")
AGREEMENT = KIT / "copilot-instructions.md"
GATED_SKILLS = ("confluence-cli", "datadog-cli", "jenkins-cli", "jira-cli", "sonarqube-cli")

RULE_PHRASES = ("question tool", "AskUserQuestion", "ask_user", "request_user_input", "vscode/askQuestions",
                "numbered list", "any clear wording", "exact phrase", "(Recommended)", "preselected",
                "means don't")

# A prompt telling the person to type, reply with or say a quoted or backticked literal, or to wait
# for a literal "yes".
EXACT_REPLY = re.compile(
    r"(?:reply|respond|answer|type)\s+(?:with\s+)?(?:exactly|only|one of)\b[^.\n]{0,40}[\"`“]"
    r"|(?:reply|respond|answer)\s+with\s+[\"`“][^\"`”]{2,40}[\"`”]"
    r"|\btype\s+`[^`]{2,40}`"
    r"|wait(?:s)? for (?:a|the) \"?yes\b",
    re.IGNORECASE)


def flat(text: str) -> str:
    return re.sub(r"\s+", " ", text)


def zethus_prompts() -> dict[str, str]:
    return {str(p.relative_to(REPO)): p.read_text(encoding="utf-8")
            for p in (*AGENTS, AGREEMENT, *KIT.glob("skills/*/SKILL.md"))}


class RulePresent(unittest.TestCase):
    def test_every_harness_copy_carries_the_rule(self):
        for path in (*AGENTS, AGREEMENT):
            text = flat(path.read_text(encoding="utf-8"))
            for phrase in RULE_PHRASES:
                self.assertIn(phrase, text, f"{path.relative_to(REPO)}: {phrase}")

    def test_converted_gates_keep_their_safety(self):
        for name in GATED_SKILLS:
            text = flat((KIT / "skills" / name / "SKILL.md").read_text(encoding="utf-8"))
            for phrase in ("Run it", "Don't run it", "neither preselected", "means don't", "never an exact phrase"):
                self.assertIn(phrase, text, f"{name}: {phrase}")

    def test_doc_is_linked_from_the_readme(self):
        self.assertIn("docs/ask-with-the-question-tool.md", (KIT / "README.md").read_text(encoding="utf-8"))


class NoExactPhrase(unittest.TestCase):
    def test_no_prompt_asks_for_an_exact_reply(self):
        for name, text in zethus_prompts().items():
            m = EXACT_REPLY.search(flat(text))
            self.assertIsNone(m, f"{name} asks for an exact reply: ...{m.group(0) if m else ''}...")

    def test_the_check_catches_the_original_failure(self):
        for bad in ('Reply with "approve spec" or "revise spec".', "Type `CONFIRM DELETE` to continue.",
                    "Show the exact command, then wait for a yes.", "Reply with exactly one of: `a`, `b`."):
            self.assertTrue(EXACT_REPLY.search(bad), bad)
        for fine in ("Never ask the person to type an exact phrase.", 'A picked "Run it", or any clear "yes".'):
            self.assertFalse(EXACT_REPLY.search(fine), fine)


if __name__ == "__main__":
    unittest.main()
