import os

from dedup_tui import core


def scan(root, excludes=core.DEFAULT_EXCLUDES):
    return core.scan_builtin(root, excludes)


def test_finds_identical_files(tree):
    a, b = tree("a.txt", b"hello"), tree("sub/b.txt", b"hello")
    (g,) = scan(tree.root)
    assert sorted(g.members) == sorted([a, b]) and g.kind == "file" and g.size == 5 and g.waste == 5


def test_same_size_different_content_is_not_duplicate(tree):
    tree("a", b"aaaa"); tree("b", b"bbbb")
    assert scan(tree.root) == []


def test_same_prefix_different_tail_is_not_duplicate(tree):
    head = b"P" * 5000
    tree("a", head + b"1"); tree("b", head + b"2")
    assert scan(tree.root) == []


def test_empty_files_ignored(tree):
    tree("a", b""); tree("b", b"")
    assert scan(tree.root) == []


def test_symlinks_ignored(tree):
    a = tree("a", b"data")
    os.symlink(a, os.path.join(tree.root, "link"))
    assert scan(tree.root) == []


def test_excluded_dirs_skipped(tree):
    tree("a", b"data"); tree("node_modules/b", b"data"); tree("pkg-1.0.dist-info/c", b"data")
    assert scan(tree.root) == []


def test_three_way_group(tree):
    for n in "abc":
        tree(n, b"same")
    (g,) = scan(tree.root)
    assert len(g.members) == 3 and g.waste == 8


def test_members_sorted_most_original_first(tree):
    tree("new", b"same", mtime=2_000_000_000); tree("old", b"same", mtime=1_000_000_000)
    (g,) = scan(tree.root)
    assert g.members == sorted(g.members, key=core.originality_key)


def test_excluded_helper():
    assert core.excluded("/x/node_modules/y", core.DEFAULT_EXCLUDES)
    assert core.excluded("/x/foo-1.0.dist-info/y", core.DEFAULT_EXCLUDES)
    assert not core.excluded("/x/src/y", core.DEFAULT_EXCLUDES)
