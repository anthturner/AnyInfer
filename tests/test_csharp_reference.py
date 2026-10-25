"""Controls for the generated C# API reference and its documentation-coverage checker.

The fixture under tests/fixtures/csharp-reference/ is a small project whose declarations
exercise shapes the real assembly may not currently expose. Its compiler XML documentation,
documentation inventory and DocFX metadata are committed, so these controls run without the
.NET SDK; the slow freshness test re-extracts them when the SDK and pinned DocFX are present.
"""

from __future__ import annotations

import copy
import json
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path, PurePosixPath

import pytest
from scripts import generate_csharp_reference as reference
from scripts.check_csharp_docs import (
    comment_findings,
    load_comments,
    load_inventory,
    reference_findings,
)

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = ROOT / "tests" / "fixtures" / "csharp-reference" / "expected"
DOCFX_ROOT = PurePosixPath("tests/fixtures/csharp-reference")

# The fixture's deliberate documentation gaps: an implicit public constructor nothing can
# document, and a positional record parameter the compiler never warns about.
PLANTED_COMMENT_FINDINGS = [
    "M:ReferenceFixture.Box`1.Nested.#ctor: no XML documentation",
    "M:ReferenceFixture.Meters.#ctor(System.Double): missing param documentation for 'Value'",
    "P:ReferenceFixture.Meters.Value: no XML documentation",
    "T:ReferenceFixture.Meters: missing param documentation for 'Value'",
]


@pytest.fixture(scope="module")
def documents() -> list[dict[str, object]]:
    return reference.load_metadata(EXPECTED / "metadata")


@pytest.fixture(scope="module")
def rendered(documents: list[dict[str, object]]) -> reference.Reference:
    return _render(documents)


def _render(documents: list[dict[str, object]]) -> reference.Reference:
    return reference.render(
        documents, version="9.9.9-test", assembly="ReferenceFixture", docfx_root=DOCFX_ROOT
    )


def _page(rendered: reference.Reference, uid: str) -> str:
    return next(page.content for page in rendered.pages if page.uid == uid)


def test_type_slugs_are_readable_and_distinguish_arity_and_nesting() -> None:
    assert reference.type_slug("AnyInfer.Capabilities.ContextBudget") == (
        "anyinfer.capabilities.contextbudget"
    )
    assert reference.type_slug("ReferenceFixture.Box`1") == "referencefixture.box-1"
    assert reference.type_slug("ReferenceFixture.Box`1.Nested.Depth") == (
        "referencefixture.box-1.nested.depth"
    )
    assert reference.type_slug("N.Box") != reference.type_slug("N.Box`1")
    with pytest.raises(reference.ReferenceError):
        reference.type_slug("N.Box{System.Int32}")


def test_slug_collisions_are_hard_errors(documents: list[dict[str, object]]) -> None:
    mutated = copy.deepcopy(documents)
    clone = copy.deepcopy(
        next(doc for doc in mutated if doc["items"][0]["uid"] == "ReferenceFixture.Constants")
    )
    item = clone["items"][0]
    item["uid"], item["commentId"], item["children"] = (
        "ReferenceFixture.CONSTANTS",
        "T:ReferenceFixture.CONSTANTS",
        [],
    )
    clone["items"] = [item]
    mutated.append(clone)
    with pytest.raises(reference.ReferenceError, match="share the route segment"):
        _render(mutated)


def test_overload_anchors_are_stable_distinct_and_collisions_fail(
    rendered: reference.Reference,
    documents: list[dict[str, object]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    single = "M:ReferenceFixture.Box`1.Map``1(System.Func{`0,``0})"
    pair = "M:ReferenceFixture.Box`1.Map``1(System.Func{`0,``0},``0)"
    assert reference.member_anchor(single) == reference.member_anchor(single)
    assert reference.member_anchor(single) != reference.member_anchor(pair)
    assert rendered.symbols[single].endswith("#" + reference.member_anchor(single))
    assert rendered.symbols[pair].endswith("#" + reference.member_anchor(pair))
    page = _page(rendered, "T:ReferenceFixture.Box`1")
    assert f'<a id="{reference.member_anchor(single)}"></a>' in page
    assert f'<a id="{reference.member_anchor(pair)}"></a>' in page

    monkeypatch.setattr(reference, "member_anchor", lambda _comment_id: "member-same")
    with pytest.raises(reference.ReferenceError, match="share member-same"):
        _render(documents)


def test_rendered_symbols_cover_the_inventory_except_the_undeclared_constructor(
    rendered: reference.Reference,
) -> None:
    inventory = load_inventory(EXPECTED / "inventory.json")
    assert reference_findings(inventory, rendered.symbols) == [
        "M:ReferenceFixture.Box`1.Nested.#ctor: not rendered in the generated C# reference"
    ]


def test_missing_constructor_overload_or_member_fails_coverage(
    rendered: reference.Reference,
) -> None:
    inventory = load_inventory(EXPECTED / "inventory.json")
    for dropped in (
        "M:ReferenceFixture.Box`1.#ctor(`0)",
        "M:ReferenceFixture.Box`1.Map``1(System.Func{`0,``0},``0)",
        "E:ReferenceFixture.IShape.Changed",
        "M:ReferenceFixture.Meters.op_Implicit(System.Double)~ReferenceFixture.Meters",
    ):
        symbols = {key: value for key, value in rendered.symbols.items() if key != dropped}
        assert f"{dropped}: not rendered in the generated C# reference" in reference_findings(
            inventory, symbols
        )


def test_broken_uid_mapping_fails_coverage(rendered: reference.Reference) -> None:
    inventory = load_inventory(EXPECTED / "inventory.json")
    symbols = dict(rendered.symbols)
    url = symbols.pop("M:ReferenceFixture.Signatures.TryParse(System.String,System.Int32@)")
    symbols["M:ReferenceFixture.Signatures.TryParse(System.String,System.Int32)"] = url
    findings = reference_findings(inventory, symbols)
    assert (
        "M:ReferenceFixture.Signatures.TryParse(System.String,System.Int32@): "
        "not rendered in the generated C# reference"
    ) in findings
    assert (
        "M:ReferenceFixture.Signatures.TryParse(System.String,System.Int32): "
        "rendered but absent from the documentation inventory"
    ) in findings


def test_xml_links_resolve_to_site_pages_or_framework_documentation(
    rendered: reference.Reference,
) -> None:
    box = _page(rendered, "T:ReferenceFixture.Box`1")
    assert "[`Pair<TLeft, TRight>`](/csharp/api/referencefixture.pair-2/)" in box
    assert (
        "[InvalidOperationException](https://learn.microsoft.com/dotnet/api/system.invalidoperationexception)"
        in box
    )
    assert "or `null` when empty" in box
    signatures = _page(rendered, "T:ReferenceFixture.Signatures")
    # A constructed nested generic links to its generic definition's page.
    assert "[Box](/csharp/api/referencefixture.box-1/)" in signatures
    assert "](/csharp/api/referencefixture.box-1.nested/)" in signatures


def test_unresolved_reference_into_the_documented_assembly_fails(
    documents: list[dict[str, object]],
) -> None:
    mutated = copy.deepcopy(documents)
    item = next(doc for doc in mutated if doc["items"][0]["uid"] == "ReferenceFixture.Constants")[
        "items"
    ][0]
    item["summary"] = (
        'See <xref href="ReferenceFixture.Internal.Hidden" data-throw-if-not-resolved="false"></xref>.'
    )
    with pytest.raises(
        reference.ReferenceError, match=r"unresolved reference to ReferenceFixture\.Internal\.Hidden"
    ):
        _render(mutated)


def test_unknown_markup_and_foreign_assemblies_fail(documents: list[dict[str, object]]) -> None:
    mutated = copy.deepcopy(documents)
    item = next(doc for doc in mutated if doc["items"][0]["uid"] == "ReferenceFixture.Constants")[
        "items"
    ][0]
    item["summary"] = "A <blink>new</blink> tag."
    with pytest.raises(reference.ReferenceError, match=r"unsupported documentation markup <blink>"):
        _render(mutated)
    mutated = copy.deepcopy(documents)
    mutated[0]["items"][0]["assemblies"] = ["SomethingElse"]
    with pytest.raises(reference.ReferenceError, match="not ReferenceFixture"):
        _render(mutated)


def test_prose_is_escaped_while_code_and_signatures_stay_literal(
    rendered: reference.Reference,
) -> None:
    box = _page(rendered, "T:ReferenceFixture.Box`1")
    assert "# Box\\<T\\> class" in box
    assert "`a < b && c > d` and braces \\{literal\\}" in box
    assert "```csharp\npublic class Box<T> where T : notnull\n```" in box
    assert 'title: "Box<T> class"' in box


def test_long_signatures_are_complete_and_wrapped_one_parameter_per_line(
    rendered: reference.Reference,
) -> None:
    signatures = _page(rendered, "T:ReferenceFixture.Signatures")
    assert (
        "Long(\n"
        "    IReadOnlyDictionary<string, IReadOnlyList<KeyValuePair<string, Box<string>?>>>? first = null,\n"
        '    string? second = "default",\n'
    ) in signatures
    assert "    Box<Pair<int, string>>? sixth = null)\n```" in signatures
    assert "public static bool TryParse(string? text, out int value)" in signatures
    assert "public static void Swap(ref int left, ref int right)" in signatures
    assert "public static int Read(in int value)" in signatures
    assert "IAsyncEnumerable<int> CountAsync(" in signatures


def test_records_operators_obsolete_and_enums_render(rendered: reference.Reference) -> None:
    pair = _page(rendered, "T:ReferenceFixture.Pair`2")
    assert "# Pair\\<TLeft, TRight\\> record" in pair
    assert ":::note Record type" in pair
    meters = _page(rendered, "T:ReferenceFixture.Meters")
    assert "# Meters record struct" in meters
    assert "## Operators" in meters and "operator +(" in meters
    signatures = _page(rendered, "T:ReferenceFixture.Signatures")
    assert ":::caution Obsolete\n\nUse Sum instead." in signatures
    depth = _page(rendered, "T:ReferenceFixture.Box`1.Nested.Depth")
    assert "## Values" in depth and "`One` | `1` | The first level. |" in depth


def test_source_links_are_repository_relative(rendered: reference.Reference) -> None:
    for page in rendered.pages:
        assert "/home/" not in page.content and "C:\\" not in page.content
        if page.kind == "index":
            continue
        assert page.origin == "tests/fixtures/csharp-reference/ReferenceFixture/Shapes.cs"
    box = _page(rendered, "T:ReferenceFixture.Box`1")
    # DocFX records 0-based lines; GitHub anchors are 1-based.
    line = next(
        number
        for number, text in enumerate(
            (ROOT / "tests/fixtures/csharp-reference/ReferenceFixture/Shapes.cs")
            .read_text(encoding="utf-8")
            .splitlines(),
            1,
        )
        if text.startswith("public class Box<T>")
    )
    assert f"ReferenceFixture/Shapes.cs#L{line})" in box


def test_index_and_sidebar_list_every_type_page(rendered: reference.Reference) -> None:
    index = _page(rendered, "index")
    types = [page for page in rendered.pages if page.kind != "index"]
    for page in types:
        assert f"]({page.url})" in index
    sidebar = rendered.sidebar()
    listed = [item["id"] for namespace in sidebar["namespaces"] for item in namespace["items"]]
    assert sorted(listed) == sorted(page.path.removesuffix(".md") for page in types)
    assert sidebar["index"] == "api/index"


def test_fixture_comment_check_reports_exactly_the_planted_gaps() -> None:
    inventory = load_inventory(EXPECTED / "inventory.json")
    comments = load_comments(EXPECTED / "ReferenceFixture.xml")
    assert comment_findings(inventory, comments) == PLANTED_COMMENT_FINDINGS


def _mutated_comments(mutate: object) -> list[str]:
    inventory = load_inventory(EXPECTED / "inventory.json")
    comments = copy.deepcopy(load_comments(EXPECTED / "ReferenceFixture.xml"))
    mutate(comments)  # type: ignore[operator]
    return [
        finding
        for finding in comment_findings(inventory, comments)
        if finding not in PLANTED_COMMENT_FINDINGS
    ]


def test_comment_check_rejects_missing_params_returns_and_placeholders() -> None:
    def drop_param(comments: dict[str, ET.Element]) -> None:
        member = comments["M:ReferenceFixture.Signatures.Swap(System.Int32@,System.Int32@)"]
        member.remove(member.findall("param")[1])

    assert _mutated_comments(drop_param) == [
        "M:ReferenceFixture.Signatures.Swap(System.Int32@,System.Int32@): "
        "missing param documentation for 'right'"
    ]

    def drop_returns(comments: dict[str, ET.Element]) -> None:
        member = comments["M:ReferenceFixture.Signatures.Sum(System.Int32[])"]
        member.remove(member.find("returns"))  # type: ignore[arg-type]

    assert _mutated_comments(drop_returns) == [
        "M:ReferenceFixture.Signatures.Sum(System.Int32[]): missing returns documentation"
    ]

    def placeholder(comments: dict[str, ET.Element]) -> None:
        comments["T:ReferenceFixture.Constants"].find("summary").text = "TODO"  # type: ignore[union-attr]

    assert "T:ReferenceFixture.Constants: placeholder summary 'TODO'" in _mutated_comments(
        placeholder
    )


def test_comment_check_rejects_decision_ids_private_crefs_and_unearned_inheritdoc() -> None:
    def leak(comments: dict[str, ET.Element]) -> None:
        summary = comments["T:ReferenceFixture.Constants"].find("summary")
        summary.text = "Follows ADR-012."  # type: ignore[union-attr]
        reference_element = ET.SubElement(summary, "see")  # type: ignore[arg-type]
        reference_element.set("cref", "T:ReferenceFixture.Internal.Hidden")
        comments["F:ReferenceFixture.Constants.Answer"] = ET.fromstring(
            '<member name="F:ReferenceFixture.Constants.Answer"><inheritdoc/></member>'
        )

    findings = _mutated_comments(leak)
    assert (
        "T:ReferenceFixture.Constants: documentation contains an internal decision identifier"
        in findings
    )
    assert (
        "T:ReferenceFixture.Constants: cref 'T:ReferenceFixture.Internal.Hidden' "
        "names a declaration outside the public surface"
    ) in findings
    assert (
        "F:ReferenceFixture.Constants.Answer: inheritdoc on a declaration that neither "
        "overrides nor implements a member"
    ) in findings


@pytest.mark.slow
def test_committed_fixture_matches_a_fresh_extraction(tmp_path: Path) -> None:
    if shutil.which("dotnet") is None:
        pytest.skip("the .NET SDK is not installed")
    tools = subprocess.run(
        ["dotnet", "tool", "list", "--local"],
        cwd=ROOT / "src" / "csharp",
        capture_output=True,
        text=True,
    )
    if "docfx" not in tools.stdout:
        pytest.skip("the pinned DocFX tool is not restored (run `dotnet tool restore`)")
    fresh = tmp_path / "expected"
    reference.refresh_fixture(ROOT, fresh)
    committed = sorted(
        path.relative_to(EXPECTED) for path in EXPECTED.rglob("*") if path.is_file()
    )
    assert (
        sorted(path.relative_to(fresh) for path in fresh.rglob("*") if path.is_file()) == committed
    )
    for relative in committed:
        assert (fresh / relative).read_text(encoding="utf-8") == (EXPECTED / relative).read_text(
            encoding="utf-8"
        ), (
            f"{relative} is stale; run `python scripts/generate_csharp_reference.py --refresh-fixture`"
        )
    json.loads((fresh / "inventory.json").read_text(encoding="utf-8"))
