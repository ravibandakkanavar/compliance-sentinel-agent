from conftest import DEMO_REPO

from sentinel.agent import codebase


def test_load_repo_reads_source_and_skips_junk(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('hi')\n", encoding="utf-8")
    (tmp_path / "node_modules" / "lib").mkdir(parents=True)
    (tmp_path / "node_modules" / "lib" / "index.js").write_text("x", encoding="utf-8")
    (tmp_path / "package-lock.json").write_text("{}", encoding="utf-8")
    (tmp_path / "logo.png").write_bytes(b"\x89PNG\x00\xff")
    (tmp_path / "notes.md").write_text("# notes", encoding="utf-8")

    assert list(codebase.load_repo(tmp_path)) == ["src/main.py"]


def test_demo_repo_loads_with_posix_paths():
    files = codebase.load_repo(DEMO_REPO)
    assert {
        "app.py",
        "db.py",
        "config.py",
        "services/analytics.py",
        "templates/signup.html",
    } <= set(files)


def test_grep_ignores_invalid_patterns():
    files = {"a.py": ["password = 'x'", "ok = 1"], "b.py": ["nothing"]}
    assert codebase.grep(files, ["PASSWORD", "(unclosed"]) == {"a.py": [1]}


def test_locate_quote_ignores_indentation_and_wrong_line_hint():
    lines = ["def f():", "    log.info(", '        "ssn=%s", ssn', "    )", "    return 1"]
    quote = 'log.info(\n"ssn=%s", ssn'
    assert codebase.locate_quote(lines, quote, hint_line=40) == (2, 3)


def test_locate_quote_picks_occurrence_nearest_the_hint():
    lines = ["x = 1", "y = 2", "x = 1"]
    assert codebase.locate_quote(lines, "x = 1", hint_line=3) == (3, 3)
    assert codebase.locate_quote(lines, "x = 1", hint_line=1) == (1, 1)


def test_locate_quote_rejects_code_that_is_not_there():
    assert codebase.locate_quote(["x = 1"], "bcrypt.hashpw(password)", 1) is None
    assert codebase.locate_quote(["x = 1"], "   \n", 1) is None


def test_snippets_merge_nearby_hits_and_respect_the_budget():
    files = {"a.py": [f"line {n}" for n in range(1, 101)]}
    text = codebase.render_snippets(files, {"a.py": [10, 14, 80]}, context=3)

    assert text.count('<file path="a.py">') == 2
    assert "    7 | line 7" in text and "   17 | line 17" in text
    assert "line 40" not in text
    assert codebase.render_snippets(files, {"a.py": [10]}, context=3, char_budget=10) == ""
