import asyncio

from dedup_tui.app import DedupApp
from dedup_tui.core import Group


def groups(tree):
    a, b, c = tree("a", b"same"), tree("b", b"same"), tree("c", b"same")
    return [Group("file", [a, b, c], 4)], (a, b, c)


def drive(app, keys):
    async def go():
        async with app.run_test() as pilot:
            for k in keys:
                await pilot.press(k)
            await pilot.pause()
    asyncio.run(go())


def test_default_keeps_only_first(tree):
    gs, _ = groups(tree)
    app = DedupApp([], groups=gs)
    drive(app, ["x"])
    (keeper, victims, kind), = app.result
    assert keeper == gs[0].members[0] and victims == gs[0].members[1:] and kind == "file"


def test_cannot_drop_last_keeper(tree):
    gs, _ = groups(tree)
    app = DedupApp([], groups=gs)
    drive(app, ["space", "x"])     # try to drop the only kept copy
    assert app.keep_flags[0] == [True, False, False]
    assert len(app.result[0][1]) == 2


def test_multi_keep(tree):
    gs, _ = groups(tree)
    app = DedupApp([], groups=gs)
    drive(app, ["right", "down", "space", "x"])   # focus members, move to #2, keep it too
    assert app.keep_flags[0] == [True, True, False]
    assert app.result[0][1] == [gs[0].members[2]]


def test_excluded_victims_not_removed(tree):
    a, b = tree("a", b"s"), tree("node_modules/b", b"s")
    app = DedupApp(["node_modules"], groups=[Group("file", [a, b], 1)])
    drive(app, ["x"])
    assert app.result == []


def test_reset_restores_default(tree):
    gs, _ = groups(tree)
    app = DedupApp([], groups=gs)
    drive(app, ["right", "down", "space", "left", "r"])
    assert app.keep_flags[0] == [True, False, False]
