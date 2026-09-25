"""The gate between the job that reads third-party pages and the repository.

The collect job holds no write access; what it produced reaches the
repository only through steward.publish. These pin what that gate refuses:
anything the pipeline does not write, anything that is not the shape the
pipeline writes it in, and links out of the output directory.
"""

from __future__ import annotations

from tests import offline  # noqa: F401 — no test may use the network
import json
import os
import tempfile
import unittest

from steward import publish


class Gate(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = os.path.join(self.tmp.name, "out")
        self.repo = os.path.join(self.tmp.name, "repo")
        os.makedirs(self.repo)
        self.write("hashes.json", json.dumps({"Set": {"hash": "abc"}}))
        self.write("runs.jsonl", '{"run_id": "r1"}\n{"run_id": "r2"}\n')
        self.write("analysis/Set.json", json.dumps({"verdict": "no_material_change"}))
        self.write("transparency/snapshots/ip-australia.txt", "Statement text")

    def write(self, relative, text, root=None):
        path = os.path.join(root or self.out, relative)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)

    def assertRejected(self, fragment):
        with self.assertRaises(publish.RejectedOutput) as caught:
            publish.check(self.out)
        self.assertIn(fragment, str(caught.exception))

    def test_the_pipelines_own_output_passes(self):
        self.assertEqual(len(publish.check(self.out)), 4)

    def test_a_workflow_file_is_refused(self):
        self.write(".github/workflows/evil.yml", "on: push")
        self.assertRejected(".github/workflows/evil.yml")

    def test_site_code_is_refused(self):
        self.write("src/App.js", "export default () => null;")
        self.assertRejected("src/App.js")

    def test_config_is_refused(self):
        self.write("policy_sets.json", "[]")
        self.assertRejected("policy_sets.json: not a file the pipeline writes")

    def test_an_unexpected_file_type_is_refused(self):
        self.write("logs/payload.js", "alert(1)")
        self.assertRejected("logs/payload.js: unexpected file type")

    def test_broken_json_is_refused(self):
        self.write("news/feed.json", "{not json")
        self.assertRejected("news/feed.json: not valid JSON")

    def test_a_symbolic_link_is_refused(self):
        os.symlink("/etc/passwd", os.path.join(self.out, "analysis", "passwd.json"))
        self.assertRejected("symbolic links")

    def test_a_linked_directory_is_refused(self):
        os.symlink("/etc", os.path.join(self.out, "logs"))
        self.assertRejected("logs: symbolic links")

    def test_an_oversized_file_is_refused(self):
        self.write("logs/big_snapshot.txt", "x" * (publish.MAX_FILE_BYTES + 1))
        self.assertRejected("over the")

    def test_output_without_state_files_is_refused(self):
        os.remove(os.path.join(self.out, "hashes.json"))
        os.remove(os.path.join(self.out, "runs.jsonl"))
        self.assertRejected("did not run")

    def test_copying_mirrors_deletions_and_leaves_absent_paths_alone(self):
        self.write("analysis/Removed.json", "{}", root=self.repo)
        self.write("news/feed.json", '{"items": []}', root=self.repo)
        self.write("policy_sets.json", "[]", root=self.repo)
        publish.copy_into(self.out, self.repo)

        self.assertTrue(os.path.exists(os.path.join(self.repo, "analysis", "Set.json")))
        self.assertFalse(os.path.exists(os.path.join(self.repo, "analysis", "Removed.json")), "the pipeline deleted it")
        self.assertTrue(os.path.exists(os.path.join(self.repo, "news", "feed.json")), "news was not in this output")
        self.assertTrue(os.path.exists(os.path.join(self.repo, "policy_sets.json")))

    def test_nothing_is_copied_when_anything_is_refused(self):
        self.write("src/App.js", "x")
        with self.assertRaises(publish.RejectedOutput):
            publish.copy_into(self.out, self.repo)
        self.assertEqual(os.listdir(self.repo), [])


if __name__ == "__main__":
    unittest.main()
