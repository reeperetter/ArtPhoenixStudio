from paint_by_numbers.gui.history import UndoStack


def test_undo_redo_basic_and_redo_cleared():
    h = UndoStack("A")
    assert not h.can_undo and not h.can_redo and h.undo() is None and h.redo() is None
    h.push("B", "b")
    h.push("C", "c")
    assert h.undo_label == "c" and h.undo() == "B" and h.undo() == "A" and h.undo() is None
    assert h.redo_label == "b" and h.redo() == "B" and h.redo() == "C" and h.redo() is None
    h.undo()
    h.push("D", "d")                               # нова дія скасовує «повторити»
    assert not h.can_redo and h.undo() == "B"


def test_snapshots_are_copies():
    h = UndoStack([])
    z = [{"w": 1}]
    h.push(z, "add")
    z[0]["w"] = 99                                  # зміна оригіналу не псує історію
    z.append({"w": 2})
    assert h.undo() == [] and h.redo() == [{"w": 1}]


def test_merge_rapid_edits_and_limit():
    h = UndoStack(0)
    h.push(1, "edit", key=("e", 0), now=10.0)
    h.push(2, "edit", key=("e", 0), now=10.4)      # в межах вікна: той самий крок
    h.push(3, "edit", key=("e", 0), now=10.9)
    assert h.undo() == 0 and not h.can_undo
    h.redo()
    h.push(4, "edit", key=("e", 0), now=20.0)      # пізніше: новий крок
    h.push(5, "edit", key=("e", 1), now=20.1)      # інший ключ: новий крок
    assert h.undo() == 4 and h.undo() == 3
    s = UndoStack(0, limit=3)
    for i in range(1, 10):
        s.push(i, str(i))
    steps = 0
    while s.undo() is not None:
        steps += 1
    assert steps == 3
    # після відміни редагування не зливається зі старим записом
    m = UndoStack(0)
    m.push(1, "e", key="k", now=1.0)
    m.undo()
    m.push(2, "e", key="k", now=1.1)
    assert m.undo() == 0 and m.redo() == 2
