"""Non-regression tests for the leak scanners (offline, no Fabric, no network).

Every fixture value is assembled at runtime: writing a real-looking GUID, a real
Fabric endpoint or a personal path as a literal here would make this very file
trip the scanner it is testing.

Run:  python -m pytest tests/test_leak_scanner.py -v
"""
import hashlib
import pathlib
import re
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import check_no_client_leak as canonical  # noqa: E402
import check_repo_leaks as wrapper  # noqa: E402

# Published contract of the canonical scanner (Statyx/Fab-Analyze-Data-Agent,
# 6e4a65e704128894175a822825b6bdaddf345650, scripts/check_no_client_leak.py).
CANONICAL_SHA256 = (
    "33312e7e678c09663a7da51151359f8244ea0cadd10e811fc2a31ccf38328cd3"
)
CANONICAL_SIZE = 4023

# Opaque sentinels for the deny-list probes: they collide with nothing that
# exists, so a reviewer can never mistake them for real data. Microsoft's
# fictional companies are kept for the value-independence test alone.
PROBE = "zzsecretname"
PROBE_PAIR = "zzalpha zzbeta"


def _guid(seed: str) -> str:
    """Build a plausible, non-null GUID without writing one down."""
    digest = hashlib.sha256(seed.encode()).hexdigest()
    return "-".join([digest[:8], digest[8:12], digest[12:16],
                     digest[16:20], digest[20:32]])


def _fabric_endpoint() -> str:
    return "a" * 24 + ".data" + "warehouse.fabric.microsoft.com"


def _personal_path() -> str:
    sep = chr(92)
    return f"C:{sep}Users{sep}jdoe{sep}secrets"


@pytest.fixture
def probe():
    """A throwaway file inside the repo — scan_file() resolves against REPO_ROOT.

    `_tmp_*` is git-ignored, so an aborted run can never leave a committable file.
    """
    rel = "_tmp_leak_probe.txt"
    path = ROOT / rel

    def write(text: str) -> list:
        path.write_text(text, encoding="utf-8")
        return canonical.scan_file(rel)

    yield write
    path.unlink(missing_ok=True)


@pytest.fixture
def denylist_probe(monkeypatch):
    """Write a line into a repo file and run only the denylist rule over it."""
    rel = "_tmp_denylist_probe.txt"
    path = ROOT / rel
    monkeypatch.setattr(canonical, "tracked_files", lambda: [rel])

    def run(denylist: str, line: str) -> list:
        path.write_text(line, encoding="utf-8")
        return wrapper.scan_denylist(wrapper.parse_denylist(denylist))

    yield run
    path.unlink(missing_ok=True)


@pytest.fixture(autouse=True)
def structural_guids_allowed():
    """The wrapper reconfigures the canonical module in place — restore after."""
    saved = list(canonical.CHECKS)
    wrapper.allow_structural_placeholders()
    yield
    canonical.CHECKS[:] = saved


# ── The canonical file is a verbatim copy ───────────────────────
def test_canonical_scanner_is_byte_identical():
    """Copied, never merged, never improved. Line endings normalised for Windows."""
    data = (SCRIPTS / "check_no_client_leak.py").read_bytes().replace(b"\r\n", b"\n")
    assert len(data) == CANONICAL_SIZE
    assert hashlib.sha256(data).hexdigest() == CANONICAL_SHA256


def test_no_hardcoded_customer_list_survives():
    """The whole point: the guard must not spell out what it guards against."""
    assert not (ROOT / ".github" / "scripts" / "check_client_leak.py").exists()
    for name in ("check_no_client_leak.py", "check_repo_leaks.py"):
        text = (SCRIPTS / name).read_text(encoding="utf-8")
        assert "CLIENT_PATTERNS" not in text


# ── Detection by shape ──────────────────────────────────────────
def test_real_guid_is_flagged(probe):
    findings = probe(f"tenant_id: {_guid('tenant')}\n")
    assert any("real GUID" in f for f in findings), findings


def test_null_guid_is_allowed(probe):
    assert probe("logicalId: 00000000-0000-0000-0000-000000000000\n") == []


def test_structural_placeholder_guid_is_allowed(probe):
    """Structural placeholder IDs of this shape are committed on purpose in sibling repos."""
    assert probe('{"id": "a1000000-0000-4000-a000-000000000001"}\n') == []


def test_structural_tolerance_is_not_a_blanket_pass(probe):
    findings = probe(f'{{"id": "{_guid("taskflow")}"}}\n')
    assert any("real GUID" in f for f in findings), findings


def test_fabric_endpoint_is_flagged(probe):
    findings = probe(f"server: {_fabric_endpoint()}\n")
    assert any("Fabric SQL endpoint" in f for f in findings), findings


def test_personal_path_is_flagged(probe):
    findings = probe(f"path = {_personal_path()}\n")
    assert any("personal filesystem path" in f for f in findings), findings


def test_placeholder_home_path_is_allowed(probe):
    sep = chr(92)
    assert probe(f"path = C:{sep}Users{sep}<you>{sep}repo\n") == []


def test_reconfiguration_fails_loudly_if_upstream_renames_the_rule():
    canonical.CHECKS[:] = [("renamed", canonical.GUID_RE, lambda m: True)]
    with pytest.raises(SystemExit):
        wrapper.allow_structural_placeholders()


# ── Denylist fed by a secret, never by the repo ─────────────────
def test_denylist_absent_degrades_without_failing(monkeypatch):
    monkeypatch.delenv(wrapper.DENYLIST_ENV, raising=False)
    monkeypatch.setattr(wrapper, "DENYLIST_FILE", ROOT / "_tmp_absent_denylist")
    patterns, _source = wrapper.load_denylist()
    assert patterns == []


def test_denylist_reads_one_entry_per_line_and_skips_comments(monkeypatch):
    monkeypatch.setenv(wrapper.DENYLIST_ENV, f"# comment\n{PROBE}\n\n  zzbeta  \n")
    patterns, source = wrapper.load_denylist()
    assert len(patterns) == 2
    assert source.endswith(wrapper.DENYLIST_ENV)


def test_denylist_entry_tolerates_separators():
    pattern = wrapper.compile_entry(PROBE_PAIR)
    for variant in ("zzalpha zzbeta", "ZZalpha-ZZbeta", "zzalpha_zzbeta",
                    "zzalpha.zzbeta", "zzalphazzbeta"):
        assert pattern.search(f"see {variant} here"), variant


def test_denylist_entry_respects_word_boundaries():
    pattern = wrapper.compile_entry(PROBE)
    assert pattern.search(f"the {PROBE} device")
    assert not pattern.search(f"supra{PROBE}meter")


def test_denylist_match_never_echoes_the_term_or_the_line(denylist_probe):
    """Actions logs are public: a chatty scanner recreates the leak it fights."""
    findings = denylist_probe(PROBE, f"the {PROBE} account id is 4471\n")
    assert findings, "the denylist rule must still catch a name"
    for finding in findings:
        assert re.fullmatch(r"[^:]+:\d+: entree de denylist no \d+", finding), finding


def test_colour_context_is_tolerated(denylist_probe):
    """Recognised by shape — a CSS declaration, a hex code, a badge URL."""
    for line in (f"--accent-color: {PROBE};\n",
                 f"background: #ff8800; /* {PROBE} */\n",
                 f"![b](https://img.shields.io/badge/{PROBE}-blue)\n"):
        assert denylist_probe(PROBE, line) == [], line


def test_denylist_rule_is_morphological_not_value_bound():
    """Any entry must work: the rule is tested on its mechanism, not on real data."""
    for entry in (PROBE, "Contoso", "Fabrikam", "Northwind Traders", "zz-9"):
        assert wrapper.compile_entry(entry).search(f"x {entry} y"), entry
