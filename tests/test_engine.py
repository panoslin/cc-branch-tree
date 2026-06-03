"""Unit tests for the cc-branch-tree engine (stdlib unittest, zero deps)."""
import os
import sys
import io
import contextlib
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))

# Point the engine at fixtures + a throwaway data dir BEFORE importing it.
FIX = os.path.join(HERE, "fixtures", "projects")
os.environ["CC_PROJECTS_DIR"] = FIX
os.environ["CLAUDE_PLUGIN_DATA"] = tempfile.mkdtemp(prefix="ccbt-test-")

import cc_tree  # noqa: E402


def fpath(proj, sid):
    return os.path.join(FIX, proj, sid + ".jsonl")


class TestParse(unittest.TestCase):
    def test_root(self):
        s = cc_tree.parse_transcript(fpath("proj1", "root"))
        self.assertIsNone(s.forked_from_sid)
        self.assertEqual(s.label, "Root Session")
        self.assertEqual(s.msgs, 2)
        self.assertEqual(s.cwd, "/work/proj1")
        self.assertEqual(s.git_branch, "main")

    def test_child(self):
        s = cc_tree.parse_transcript(fpath("proj1", "child"))
        self.assertEqual(s.forked_from_sid, "root")
        self.assertTrue({"a1", "a2"} <= s.inherited_uuids)
        self.assertEqual(s.msgs, 3)
        self.assertEqual(s.label, "Child Branch")
        self.assertEqual(s.inherited_in_order[-1], "a2")

    def test_latest_title_wins(self):
        s = cc_tree.parse_transcript(fpath("proj1", "renamed"))
        self.assertEqual(s.label, "New Name")

    def test_caveat_stripped_from_preview(self):
        s = cc_tree.parse_transcript(fpath("proj2", "caveat"))
        self.assertEqual(s.label, "Real user question about X")


class TestForest(unittest.TestCase):
    def setUp(self):
        self.sessions = cc_tree.load_sessions()
        self.owner = cc_tree.build_owner_index(self.sessions)
        self.children, self.roots = cc_tree.build_forest(self.sessions, self.owner)

    def test_nesting(self):
        self.assertEqual(set(self.children.get("root", [])), {"child", "sib"})
        self.assertEqual(set(self.children.get("child", [])), {"grand"})
        for r in ("root", "solo", "orphan"):
            self.assertIn(r, self.roots)

    def test_sibling_not_nested_containment_trap(self):
        # sib's inherited set is a subset of grand's uuids, but the parent must be root.
        self.assertTrue(self.sessions["sib"].inherited_uuids <= self.sessions["grand"].all_uuids)
        self.assertEqual(
            cc_tree.immediate_parent(self.sessions["sib"], self.sessions, self.owner), "root"
        )

    def test_authorship_invariant(self):
        # F5 (forkedFrom.sessionId) must equal F6 (author of last inherited msg) when parent exists.
        for sid, s in self.sessions.items():
            if s.forked_from_sid in self.sessions and s.inherited_in_order:
                self.assertEqual(
                    self.owner.get(s.inherited_in_order[-1]),
                    s.forked_from_sid,
                    f"{sid}: authorship != forkedFrom",
                )

    def test_orphan_is_root(self):
        self.assertIsNone(
            cc_tree.immediate_parent(self.sessions["orphan"], self.sessions, self.owner)
        )


class TestRenderResolve(unittest.TestCase):
    def setUp(self):
        self.sessions = cc_tree.load_sessions()
        self.children, self.roots = cc_tree.build_forest(
            self.sessions, cc_tree.build_owner_index(self.sessions)
        )
        self.text, self.ordered = cc_tree.render(self.sessions, self.children, self.roots)
        cc_tree.write_last_tree(self.ordered, self.sessions)

    def test_depth_first_order(self):
        i = self.ordered.index
        self.assertLess(i("root"), i("child"))
        self.assertLess(i("child"), i("grand"))
        self.assertLess(i("grand"), i("sib"))

    def test_indent_grand_under_child(self):
        def indent(sid):
            tag = "[%d]" % self.ordered.index(sid)
            line = next(l for l in self.text.splitlines() if tag in l)
            return line.index(tag)
        self.assertGreater(indent("grand"), indent("child"))

    def test_resolve(self):
        ri = self.ordered.index("root")
        self.assertEqual(cc_tree.resolve(str(ri), self.sessions)[0], "root")
        self.assertEqual(cc_tree.resolve("chi", self.sessions)[0], "child")
        self.assertEqual(cc_tree.resolve("Branch", self.sessions)[0], "child")
        self.assertIsNone(cc_tree.resolve("zzz-nomatch", self.sessions))

    def test_connectors(self):
        def line(sid):
            tag = "[%d]" % self.ordered.index(sid)
            return next(l for l in self.text.splitlines() if tag in l)
        # root's children: child (not last) -> ├─ ; sib (last) -> └─
        self.assertIn("├─", line("child"))
        self.assertIn("└─", line("sib"))
        # grand is nested deeper than child
        self.assertGreater(line("grand").index("["), line("child").index("["))


class TestCLI(unittest.TestCase):
    def test_resume_prints_command(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = cc_tree.main(["cc_tree.py", "resume", "root"])
        out = buf.getvalue()
        self.assertEqual(rc, 0)
        self.assertIn("claude --resume root", out)
        self.assertIn('cd "/work/proj1"', out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
