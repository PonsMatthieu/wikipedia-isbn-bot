import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "deploy/toolforge/start-build.sh"


class ToolforgeStartTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        bin_dir = self.root / "bin"
        bin_dir.mkdir()
        (bin_dir / "id").write_text('#!/bin/sh\nprintf "%s\\n" "$TEST_TOOL_USER"\n')
        (bin_dir / "toolforge").write_text(
            "#!/usr/bin/env python3\n"
            "import json, os, sys\n"
            "args = sys.argv[1:]\n"
            "with open(os.environ['TEST_CALLS'], 'a') as out:\n"
            "    out.write(json.dumps(args) + '\\n')\n"
            "if ' '.join(args).startswith(os.environ.get('TEST_FAIL', '\\0')):\n"
            "    sys.exit(1)\n"
            "if args == ['jobs', 'list']:\n"
            "    print(os.environ.get('TEST_JOBS', 'No jobs'))\n"
        )
        for file in bin_dir.iterdir():
            file.chmod(0o755)
        self.bin_dir = bin_dir

    def launch(self, url="https://github.com/example/wikipedia-isbn-bot", **settings):
        log = self.root / "calls.jsonl"
        log.unlink(missing_ok=True)
        env = dict(os.environ, PATH=f"{self.bin_dir}:{os.environ['PATH']}",
                   TEST_TOOL_USER="tools.mesange-isbn-bot", TEST_CALLS=str(log))
        env.update(settings)
        result = subprocess.run(["bash", str(SCRIPT), url], env=env,
                                capture_output=True, text=True)
        calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
        return result, calls

    def test_launch_keeps_writes_disabled_and_mounts_storage(self):
        result, calls = self.launch()
        self.assertEqual(result.returncode, 0, result.stderr)
        for name, value in [("BOT_MODE", "DRY_RUN"), ("BOT_WRITE_ENABLED", "false"),
                            ("BOT_COMMUNITY_APPROVED", "false")]:
            self.assertIn(["envvars", "create", name, value], calls)
        jobs = [call for call in calls if call[:2] == ["jobs", "run"]]
        self.assertEqual(len(jobs), 3)
        for job in jobs:
            self.assertEqual(job[job.index("--mount") + 1], "all")
            self.assertNotIn("apply", job[job.index("--command") + 1])
        self.assertEqual(jobs[-1][jobs[-1].index("--schedule") + 1], "@hourly")

    def test_invalid_repository_never_calls_toolforge(self):
        for url in ["https://example.com/bot", "https://secret@github.com/example/bot",
                    "https://github.com/example/bot;echo unsafe", "-bad"]:
            with self.subTest(url=url):
                result, calls = self.launch(url)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(calls, [])

    def test_wrong_tool_account_never_calls_toolforge(self):
        result, calls = self.launch(TEST_TOOL_USER="mesangefutee")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(calls, [])

    def test_existing_jobs_are_preserved(self):
        for name in ["isbn-init", "isbn-first", "isbn-hourly"]:
            with self.subTest(job=name):
                result, calls = self.launch(TEST_JOBS=f"| {name} | Scheduled |")
                self.assertEqual(result.returncode, 2)
                self.assertEqual(calls, [["jobs", "list"]])

    def test_failed_step_prevents_hourly_schedule(self):
        for failed in ["jobs list", "build start", "envvars create BOT_MODE",
                       "jobs run isbn-init", "jobs run isbn-first"]:
            with self.subTest(step=failed):
                result, calls = self.launch(TEST_FAIL=failed)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(any(call[:3] == ["jobs", "run", "isbn-hourly"] for call in calls))
                self.assertTrue(" ".join(calls[-1]).startswith(failed))
