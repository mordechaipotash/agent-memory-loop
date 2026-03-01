"""Tests for README updater."""

from pathlib import Path

import pytest

from agent_memory_loop.readme_updater import (
    STATUS_START,
    STATUS_END,
    generate_status_table,
    update_readme,
    CronJob,
    DEFAULT_JOBS,
)


@pytest.fixture
def readme_file(tmp_path):
    """Create a README with status markers."""
    readme = tmp_path / "README.md"
    readme.write_text(
        f"# Test README\n\n"
        f"Some content above.\n\n"
        f"{STATUS_START}\n"
        f"Old status here\n"
        f"{STATUS_END}\n\n"
        f"Some content below.\n"
    )
    return readme


class TestGenerateStatusTable:
    def test_generates_table(self):
        jobs = [
            CronJob("test-job", "*/15 * * * *", "Test purpose"),
        ]
        table = generate_status_table(jobs)
        assert "test-job" in table
        assert "Test purpose" in table
        assert "*/15 * * * *" in table

    def test_default_jobs(self):
        table = generate_status_table()
        assert "context-windows" in table
        assert "nightly-consolidation" in table

    def test_table_has_headers(self):
        table = generate_status_table([])
        assert "Status" in table
        assert "Job" in table
        assert "Schedule" in table


class TestUpdateReadme:
    def test_updates_between_markers(self, readme_file):
        changed = update_readme(readme_file)
        assert changed is True

        content = readme_file.read_text()
        assert "Old status here" not in content
        assert "context-windows" in content
        assert "Some content above." in content
        assert "Some content below." in content

    def test_preserves_surrounding_content(self, readme_file):
        update_readme(readme_file)
        content = readme_file.read_text()
        assert content.startswith("# Test README")
        assert "Some content below." in content

    def test_no_markers_returns_false(self, tmp_path):
        readme = tmp_path / "README.md"
        readme.write_text("# No markers here\n")
        assert update_readme(readme) is False

    def test_nonexistent_file_returns_false(self, tmp_path):
        assert update_readme(tmp_path / "nope.md") is False
