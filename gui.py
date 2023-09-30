from abc import ABC, abstractmethod
import os
import tkinter as tk
import time
import json
import pickle

from typing import Dict, Generic, List, Optional, Union, Tuple, TypeVar
from enum import IntFlag, auto

from ttkwidgets.autocomplete import AutocompleteEntry
import tkinter.simpledialog

from dictproxy import DictProxy, wrap
from throughput import Buffer, Recipe, Step, make_groups
from tscca import circuits


SAVE_FN = "procline.json"

class TkMods(IntFlag):
    SHIFT = 0x1
    CAPS  = 0x2
    CTRL  = 0x4
    NUMLCK = 0x8
    SCRLLCK = 0x20
    LEFT = 0x100
    MIDDLE = 0x200
    RIGHT = 0x400
    ALT = 0x20000

MOUSE_EVENTS = ["<Button-1>", "<B1-Motion>", "<ButtonRelease-1>", "<Button-2>", "<B2-Motion>", "<ButtonRelease-2>", "<Button-3>", "<B3-Motion>", "<ButtonRelease-3>"]


A = TypeVar("A")
class UnorderedPair(Generic[A]):
    def __init__(self, x: A, y: A):
        order = hash(x) < hash(y)

        self.x = x if order else y
        self.y = y if order else x

    def __eq__(self, other):
        return self.x == other.x and self.y == other.y

    def __hash__(self) -> int:
        return hash((self.x, self.y))


class Gesture(IntFlag):
    PRESS = auto()
    CLICK = auto()
    DRAG  = auto()
    DRAG_END = auto()
    HOLD  = auto()

    RIGHT  = auto()
    MIDDLE = auto()

    SHIFT = auto()
    CTRL = auto()


class GestureManager():
    HOLD_TIME = 0.5
    DRAG_MIN  = 10

    def __init__(self, canvas: "NodeCanvas"):
        self.canvas = canvas

        self.held: float  = 0
        self.drag: bool = False

        self.mod = 0

    def on_event(self, e: tk.Event, source: Union["NodeCanvas", "NodeFrame", "Hatch"]):
        x, y = e.x_root, e.y_root
        xint, yint = e.x, e.y
        mod = Gesture(0)
        submod = 0

        mod |= self.mod

        e.state = e.state if isinstance(e.state, int) else 0

        if e.state & TkMods.SHIFT:
            submod |= Gesture.SHIFT

        if e.state & TkMods.CTRL:
            submod |= Gesture.CTRL

        if e.num == 3 or e.state & TkMods.RIGHT:
            mod |= Gesture.RIGHT
        elif e.num == 2 or e.state & TkMods.MIDDLE:
            mod |= Gesture.MIDDLE

        if e.type == tk.EventType.ButtonPress:
            self.held = time.perf_counter()
            self.drag = False

            self.mod = submod
            mod |= Gesture.PRESS
            mod |= self.mod
        elif e.type == tk.EventType.Motion:
            self.drag = True
            mod |= Gesture.DRAG
        elif e.type == tk.EventType.ButtonRelease:
            if self.drag:
                mod |= Gesture.DRAG_END
            elif time.perf_counter() - self.held < 0.5:
                mod |= Gesture.CLICK
            else:
                mod |= Gesture.HOLD
            self.mod = 0

        self.canvas.gesture(x, y, xint, yint, mod, source)

class CanvasMenu(tk.Menu):
    def __init__(self, master):
        tk.Menu.__init__(self, master, tearoff=False)

        self.coords: Tuple[int, int] = 0, 0

        self.add_command(label="New node", command=lambda: master.new_node(*self.coords))
        self.add_command(label="New buffer", command=lambda: master.new_buffer(*self.coords))

class NodeMenu(tk.Menu):
    def __init__(self, master: "NodeCanvas"):
        tk.Menu.__init__(self, master, tearoff=False)
        self.master: NodeCanvas

        self.node: Optional["StepFrame"] = None
        self.add_command(label="Propagate from here", command=lambda: self.master.propagate_flow(self.node))
        self.add_command(label="Delete", command=lambda: (self.node.delete() if self.node is not None else None))

# class JSON(ABC):
#     @abstractmethod
#     def encode(self) -> dict: 
#         ...

#     @abstractmethod
#     def decode(self, d: dict): 
#         ...


def center(wid: tk.Misc) -> Tuple[int, int]:
    x = wid.winfo_rootx()
    y = wid.winfo_rooty()

    x += wid.winfo_width() // 2
    y += wid.winfo_height() // 2

    return (x, y)


class NodeToolbar(tk.Menu):
    def __init__(self, master: "NodeCanvas"):
        tk.Menu.__init__(self, master)
        self.master: NodeCanvas

        self.master.root.config(menu=self)

        calc_menu = tk.Menu(self)
        self.add_cascade(label="Calculate", menu=calc_menu)
        calc_menu.add_command(label="Find connected components", command=self.master.run_sccs)
        calc_menu.add_command(label="Force graph reconstruction", command=self.master.reconstruct)


class NodeCanvas(tk.Canvas):
    # TODO low prio: canvas in foreground -> put the nodes in canvas.create_window's
    def __init__(self, master: tk.Tk):
        tk.Canvas.__init__(self, master)

        self.root = master
        self.menubar = NodeToolbar(self)

        self.autosave = SAVE_FN
        self.recipes_by_machine = {}
        self.nodes: List[NodeFrame] = []
        # self.sccs: List[Group] = []
        self.load()

        self.gesture_manager = GestureManager(self)

        self.selection: List[NodeFrame] = []
        self.hatch: Optional[Hatch] = None
        self.drag_start: Tuple[int, int] = 0, 0
        self.drag_starti: Tuple[int, int] = 0, 0

        self.connections: Dict[Hatch, Dict[Hatch, Connection]] = {}

        self.to_move: List[NodeFrame] = []
        self.to_move_left: List[Connection] = []
        self.to_move_right: List[Connection] = []

        self.selection_rectangle = 0

        self.pack(expand=1, fill="both")
        self.configure(background="#DDDDDD")

        self.canv_menu = CanvasMenu(self)
        self.node_menu = NodeMenu(self)

        for e in MOUSE_EVENTS:
            self.bind(e, lambda e: self.gesture_manager.on_event(e, self))

        self.bind("<Delete>", lambda e: self.delete_selection())
        self.after(500, self.decode)

        self.focus_set()

        # TODO mid prio: colour groups and group lines

    def run_sccs(self):
        self.reconstruct()

        nodes = [node.model for node in self.nodes]

        make_groups(nodes, circuits(nodes))

        # for node in self.nodes:
        #     if isinstance(node.model, Step):
        #         print(node, node.model.group, node.model.pull, node.model.push)

    def propagate_flow(self, node: Optional["StepFrame"]):
        self.reconstruct()
        self.run_sccs()

        if node is None:
            raise RuntimeError("?")

        # TODO low: report total failure
        
        node.propagate_flow()

        for step in self.nodes:
            if isinstance(step, StepFrame):
                if step.model is None:
                    raise RuntimeError("Impossible")
                else:
                    step.rate.set(step.model.rate)

    def reconstruct(self):
        for node in self.nodes:
            node.reconstruct()

        for node in self.nodes:
            node.reconstruct_reconnect()

    def encode(self):
        hatch_tl = {}
        for i, node in enumerate(self.nodes):
            for j, hatch in enumerate(node.input_hatches.hatches):
                hatch_tl[hatch] = [i, False, j]

            for j, hatch in enumerate(node.output_hatches.hatches):
                hatch_tl[hatch] = [i, True, j]

        d = []
        for node in self.nodes:
            d.append(node.encode(hatch_tl))

        return {"canvas": d}

    def decode(self, _=None):
        self.unbind("<Visibility>")

        try:
            with open(SAVE_FN, mode="r", encoding="utf-8") as fp:
                d = json.load(fp) 
                d = d["canvas"]

                for d_child in d:
                    self.nodes.append(NodeFrame._decode(self, d_child))

                self.update()

                for node in self.nodes:
                    node.tie(self.nodes)

                self.after_idle(self.drag_finish)
        except OSError:
            pass
            # the_canvas.autosave = ""

    def load(self):
        if os.path.exists("recipes.pickle"):
            with open("recipes.pickle", mode="rb") as fp:
                recipes = pickle.load(fp)
        else:
            with open("recipes.json", mode="r", encoding="utf-8") as fp:
                recipes = json.load(fp)
            
            with open("recipes.pickle", mode="wb") as fp:
                pickle.dump(recipes, fp)
            
        recipes = wrap(recipes)
        recipes_by_machine = recipes.sources[0]["machines"]

        for machine in recipes_by_machine:
            self.recipes_by_machine[machine.n] = machine.recs

        self.recipes_by_machine["None"] = []

        self.recipes_by_machine_by_input  = {}
        self.recipes_by_machine_by_output = {}
        for machine, recipes in self.recipes_by_machine.items():
            by_input = self.recipes_by_machine_by_input[machine] = {}
            by_output = self.recipes_by_machine_by_output[machine] = {}

            for recipe in recipes:
                for item in recipe.iI:
                    by_input.setdefault(item.uN, []).append(recipe)
                for item in recipe.fI:
                    by_input.setdefault(item.uN, []).append(recipe)
                for item in recipe.iO:
                    by_output.setdefault(item.uN, []).append(recipe)
                for item in recipe.fO:
                    by_output.setdefault(item.uN, []).append(recipe)

        try:
            with open("items.pickle", mode="rb") as fp:
                self.itemlist, self.id_to_item = wrap(pickle.load(fp))
        except (OSError, KeyError, ValueError, TypeError):
            items = {}
            id_to_item = {}

            for _, recipes in self.recipes_by_machine.items():
                for recipe in recipes:
                    for item in recipe.iI:
                        ids = items.setdefault(item.lN, [])
                        id_to_item.setdefault(item.uN, item.lN)
                        if item.uN not in ids:
                            ids.append(item.uN)

                    for item in recipe.iO:
                        ids = items.setdefault(item.lN, [])
                        id_to_item.setdefault(item.uN, item.lN)
                        if item.uN not in ids:
                            ids.append(item.uN)

                    for item in recipe.fI:
                        ids = items.setdefault(item.lN, [])
                        id_to_item.setdefault(item.uN, item.lN)
                        if item.uN not in ids:
                            ids.append(item.uN)

                    for item in recipe.fO:
                        ids = items.setdefault(item.lN, [])
                        id_to_item.setdefault(item.uN, item.lN)
                        if item.uN not in ids:
                            ids.append(item.uN)

            self.id_to_item = id_to_item
            self.itemlist   = wrap(items)

            with open("items.pickle", mode="wb") as fp:
                pickle.dump((items, id_to_item), fp)

        self.itemlist[""]   = "null"
        self.id_to_item[""] = ""
    
    def item_name(self, item_id):
        return self.id_to_item[item_id]

    def recipe_id(self, machine, recipe):
        return self.recipes_by_machine[machine].index(recipe)
    
    def recipe_by_id(self, machine, recipe_id):
        return self.recipes_by_machine[machine][recipe_id]

    def search_recipe(self, machine: str, inputs: List[str], outputs: List[str]):
        # TODO low: fast(er?) recipe search
        if inputs:
            candidates = self.recipes_by_machine_by_input[machine][inputs[0]]
            inputs = inputs[1:]
        elif outputs:
            candidates = self.recipes_by_machine_by_output[machine][outputs[0]]
            outputs = outputs[1:]
        else:
            candidates = self.recipes_by_machine[machine]

        def match(is_input, item):
            key = "I" if is_input else "O"
            keyi = "i" + key
            keyf = "f" + key
            def match_(candidate):
                for qty in candidate[keyi]:
                    if item == qty.uN:
                        return True
                for qty in candidate[keyf]:
                    if item == qty.uN:
                        return True
                return False
            return match_

        for item in inputs:
            candidates = filter(match(True, item), candidates)

        for item in outputs:
            candidates = filter(match(False, item), candidates)

        return list(candidates)

    def on_closing(self):
        if self.autosave:
            with open(self.autosave, mode="w", encoding="utf-8") as fp:
                json.dump(self, fp, default=lambda x: x.encode())
        
        self.master.destroy()

    def gesture(self, x: int, y: int, xint: int, yint: int, mod: Gesture, source: Union["NodeCanvas", "NodeFrame", "Hatch"]):
        if mod == Gesture.PRESS:
            self.drag_start = (x, y)

            source.focus_set()
            if isinstance(source, NodeFrame) and source not in self.selection:
                self.deselect_all()
                self.select(source)

            self.drag_init(source != self)
        elif mod == Gesture.PRESS | Gesture.SHIFT:
            self.drag_starti = (xint, yint)
            self.drag_start = (x, y)
            if source == self:
                self.selection_rectangle = self.create_rectangle(xint, yint, xint, yint, width=1, outline="#0000FF")
        elif mod == Gesture.CLICK:
            if source == self:
                self.deselect_all()
                self.focus_set()
            elif source in self.selection:
                self.deselect_all()
                self.select(source)
                source.focus_set()
            elif isinstance(source, Hatch):
                if self.hatch is None:
                    self.hatch = source
                else:
                    self.toggle_connect(self.hatch, source)
                    self.hatch = None
        elif mod == Gesture.CLICK | Gesture.RIGHT:
            if isinstance(source, StepFrame):
                self.node_menu.tk_popup(x, y, 0)
                self.node_menu.node = source
            else:
                self.canv_menu.tk_popup(x, y, 0)
                self.canv_menu.coords = (xint, yint)
        elif mod == Gesture.CLICK | Gesture.SHIFT:
            self.delete(self.selection_rectangle)
            self.selection_rectangle = 0
            if isinstance(source, NodeFrame):
                self.select_toggle(source)
        elif mod == Gesture.CLICK | Gesture.CTRL:
            if isinstance(source, Hatch):
                source.item_menu()
        elif mod == Gesture.HOLD | Gesture.SHIFT:
            self.delete(self.selection_rectangle)
        elif mod == Gesture.DRAG:
            self.drag(x, y)
        elif mod == Gesture.DRAG | Gesture.SHIFT:
            if self.selection_rectangle:
                self.change_region_selection(xint, yint)
        elif mod & (~ Gesture.SHIFT) == Gesture.DRAG_END:
            self.drag_finish()

            if self.selection_rectangle:
                self.select_region(xint, yint)
                self.delete(self.selection_rectangle)
                self.selection_rectangle = 0

        if not isinstance(source, Hatch):
            self.hatch = None

        # self.configure(background="#DDDDDD")
        # less trails, but stupid
        
    def drag_init(self, on_selection):
        self.to_move = self.selection if on_selection else self.nodes
        
        to_move_left = set()
        to_move_right = set()

        for child in self.to_move:
            for hatch in child.input_hatches.hatches:
                for conn in hatch.connections:
                    to_move_right.add(self.connections[hatch][conn])

            for hatch in child.output_hatches.hatches:
                for conn in hatch.connections:
                    to_move_left.add(self.connections[hatch][conn])

        self.to_move_left = list(to_move_left)
        self.to_move_right = list(to_move_right)

    def drag(self, x, y):
        dx = x - self.drag_start[0]
        dy = y - self.drag_start[1]
    
        for child in self.to_move:
            child.place(x=child.drag_start[0] + dx, y=child.drag_start[1] + dy)

        for conn in self.to_move_left:
            x1, y1, x2, y2 = conn.drag_start

            if conn in self.to_move_right:
                self.coords(conn.line, x1 + dx, y1 + dy, x2 + dx, y2 + dy)
            else:
                self.coords(conn.line, x1 + dx, y1 + dy, x2, y2)

        for conn in self.to_move_right:
            x1, y1, x2, y2 = conn.drag_start

            if conn not in self.to_move_left:
                self.coords(conn.line, x1, y1, x2 + dx, y2 + dy)

    def drag_finish(self):
        if not self.to_move:
            # just get all connections loaded
            self.drag_init(False)

        self.update_idletasks()

        for child in self.to_move:
            child.drag_start = (child.winfo_x(), child.winfo_y())

            for conn in self.to_move_left:
                conn.drag_start = self.coords(conn.line)

            for conn in self.to_move_right:
                conn.drag_start = self.coords(conn.line)

        self.to_move = []
        self.to_move_left = []
        self.to_move_right = []

    def select_region(self, x1, y1):
        x0, y0 = self.drag_starti

        x0, x1 = min(x0, x1), max(x0, x1)
        y0, y1 = min(y0, y1), max(y0, y1)
        
        for child in self.winfo_children():
            if not isinstance(child, NodeFrame):
                continue

            x = child.winfo_x()
            y = child.winfo_y()
            
            if x0 < x < x1 and y0 < y < y1 and child not in self.selection:
                self.select(child)    

    def change_region_selection(self, xi, yi):
        self.coords(self.selection_rectangle, *self.drag_starti, xi, yi)

    def deselect_all(self):
        for child in self.selection:
            child.deselect()
        
        self.selection = []

    def select(self, child: "NodeFrame"):
        self.selection.append(child)
        child.select()

    def deselect(self, child: "NodeFrame"):
        self.selection.remove(child)
        child.deselect()

    def select_toggle(self, child: "NodeFrame"):
        if child in self.selection:
            self.deselect(child)
            self.focus_set()
        else:
            self.select(child)
            child.focus_set()

    def new_node(self, x, y):
        node = StepFrame(self, x, y)
        self.nodes.append(node)
        node.drag_init()

        return node

    def delete_node(self, child):
        if child in self.selection:
            self.selection.remove(child)

        for hatch in child.input_hatches.hatches:
            for conn in hatch.connections:
                self.disconnect(hatch, conn)

        for hatch in child.output_hatches.hatches:
            for conn in hatch.connections:
                self.disconnect(hatch, conn)

        self.nodes.remove(child)
        child.destroy()

    def delete_selection(self):
        for child in self.selection.copy():
            self.delete_node(child)

    def new_buffer(self, x, y):
        node = BufferFrame(self, x, y)
        self.nodes.append(node)
        node.drag_init()

        return node

    def connect(self, a: "Hatch", b: "Hatch"):
        if self.connections.get(a, {}).get(b) is None:
            if a.is_input:
                a, b = b, a

            a.connect(b)
            b.connect(a)

            x1, y1 = center(a)
            x2, y2 = center(b)

            dx = self.winfo_rootx()
            dy = self.winfo_rootx()

            # print(dx, dy)

            conn = Connection(self, self.create_line(x1 - dx, y1 - dy, x2 - dx, y2 - dy, fill="#00FF00", width=3))

            self.connections.setdefault(a, {})[b] = conn
            self.connections.setdefault(b, {})[a] = conn

    def disconnect(self, a: "Hatch", b: "Hatch"):
        if self.connections.get(a, {}).get(b) is not None:
            self.delete(self.connections[a][b].line)
            del self.connections[a][b]
            del self.connections[b][a]
            
            a._disconnect(b)
            b._disconnect(a)

    def toggle_connect(self, a: "Hatch", b: "Hatch"):
        if a.is_input != b.is_input:
            if self.connections.get(a, {}).get(b) is None:
                self.connect(a, b)
            else:
                self.disconnect(a, b)


class Connection:
    def __init__(self, canvas: NodeCanvas, line: int):
        self.line = line
        self.drag_start = canvas.coords(line)


# class SearchMenu(tk.Frame):
#    def __init__(self, master, values):
#        tk.Frame.__init__(self, master)




class Hatch(tk.Frame):
    def __init__(self, master: "HatchBar", is_input: bool, item_id=None, *args, **kwargs):
        tk.Frame.__init__(self, master, *args, **kwargs)
        self.master: "HatchBar"

        self.description = tk.StringVar()
        self.label = tk.Label(self, textvariable=self.description)
        self.label.configure(background="white")
        self.label.pack(expand=1, fill="both")

        self.node: NodeFrame = master.master
        self.item_name = ""
        self.item_id   = ""

        if item_id is not None:
            self.set_item(item_id)

        self.is_input = is_input
        self.connections: List[Hatch] = []

        self.d_connections = {}

        self.configure(highlightcolor="#00AAFF")

    
        for e in MOUSE_EVENTS:
            self.bind(e, lambda e: self.master.master.master.gesture_manager.on_event(e, self))
            self.label.bind(e, lambda e: self.master.master.master.gesture_manager.on_event(e, self))

        self.bind("<Delete>", lambda e: self.master.remove_hatch(self))

    def remove(self):
        self.disconnect_all()
        self.destroy()

    def encode(self, hatch_tl: Dict["Hatch", Tuple[int, bool, int]]):
        return { "connections": [hatch_tl[x] for x in self.connections]
               , "id": self.item_id
               , "name": self.item_name }

    def decode(self, d):
        self.d_connections = d["connections"]
        self.set_item(d["id"])
    
    def set_item(self, item_id):
        # , item_name):
        self.item_id = item_id
        self.item_name = self.master.master.master.item_name(item_id)
        self.description.set(self.item_name)

    def tie(self, canvas: "NodeCanvas", nodes: List["NodeFrame"]):
        for [i, x, j] in self.d_connections:
            i: int
            x: bool
            j: int

            node = nodes[i]
            hatchbar = node.output_hatches if x else node.input_hatches
            canvas.connect(self, hatchbar.hatches[j])

    # TODO low: def revalidate(self): invalid hatches get marked red

    def connect(self, target: "Hatch"):
        # TODO low: prevent mismatched hatch connections
        
        if bool(self.item_name) > bool(target.item_name):
            target.set_item(self.item_id)

        if bool(self.item_name) < bool(target.item_name):
            self.set_item(target.item_id)

        if target not in self.connections:
            self.connections.append(target)

    def _disconnect(self, target: "Hatch"):
        if target in self.connections:
            self.connections.remove(target)

    def disconnect_all(self):
        for conn in self.connections:
            self.master.master.master.disconnect(self, conn)

    def item_menu(self):
        item_name = tkinter.simpledialog.askstring("Item name?", "Item name?", initialvalue=self.item_name)
        item_id = ""

        if item_name is None:
            return

        try:
            item_id = self.master.master.master.itemlist[item_name][0] # TODO low: lol
            self.set_item(item_id) # bit inefficient but ok
        except:
            print("Warning:", item_name, "is an invalid item name")

        if item_id != self.item_id:
            self.disconnect_all()


class HatchBar(tk.Frame):
    def __init__(self, master: "NodeFrame", is_input: bool, *args, **kwargs):
        tk.Frame.__init__(self, master, *args, **kwargs)
        self.master: "NodeFrame"
        
        self.is_input = is_input
        self.plus = tk.Button(self, text="+", command=self.add_hatch)
        self.hatches: List[Hatch] = []

        self.space()

    def encode(self, hatch_tl: Dict[Hatch, Tuple[int, bool, int]]):
        d = []

        for hatch in self.hatches:
            d.append(hatch.encode(hatch_tl))

        return d

    def decode(self, d):
        for d_hatch in d:
            # print(self, d_hatch)
            hatch = Hatch(self, self.is_input, background="#FFFFFF", highlightbackground="#000000", highlightthickness=1)
            hatch.decode(d_hatch)
            self.insert_hatch(len(self.hatches), hatch)
            # print(self.hatches)

        return self

    def disconnect_all(self):
        for hatch in self.hatches:
            hatch.disconnect_all()

    def remove_all(self):
        for hatch in list(self.hatches):
            self.remove_hatch(hatch)

    def tie(self, canvas: "NodeCanvas", nodes: List["NodeFrame"]):
        for hatch in self.hatches:
            hatch.tie(canvas, nodes)

    def add_hatch(self, item_id=None):
        # TODO low: adding hatches should move connections on the canvas
        self.hatches.append(Hatch(self, self.is_input, item_id=item_id, background="#FFFFFF", highlightbackground="#000000", highlightthickness=1))
        self.space()

    def insert_hatch(self, i, hatch):
        self.hatches.insert(i, hatch)
        self.space()

    def remove_hatch(self, hatch):
        self.master.master.hatch = None # just in case
        self.hatches.remove(hatch)
        hatch.remove()
        self.space()

    def space(self):
        xs = [self.plus] + self.hatches
        n = len(xs)

        for i, x in enumerate(xs):
            x.place(relx=i / n, rely=0, relwidth=1 / n, relheight=1)


class NodeFrame(tk.Frame, ABC):
    def __init__(self, master: NodeCanvas, x=None, y=None, inputs=None, outputs=None):
        tk.Frame.__init__(self, master)
        self.master: NodeCanvas

        self.model: Union[None, Step, Buffer] = None

        self.input_hatches  = inputs if inputs else \
                              HatchBar(self, True, background="#FFFFFF", highlightbackground="#000000", highlightthickness=1)
        self.output_hatches = outputs if outputs else \
                              HatchBar(self, False, background="#FFFFFF", highlightbackground="#000000", highlightthickness=1)

        self.input_hatches.grid(row=0, column=0, sticky="nesw")
        self.output_hatches.grid(row=2, column=0, sticky="nesw")

        self.grid_rowconfigure(index=0, weight=1)
        self.grid_rowconfigure(index=2, weight=1)
        self.grid_columnconfigure(index=0, weight=1)

        x = x if x else 40
        y = y if y else 40

        # True iff the last mouse interaction (in this widget) was a motion event (as opposed to a single click)
        self.drag_start: Tuple[int, int] = 0, 0

        self.place(x=x, y=y, width=200, height=200)
        self.configure(background="#FFFFFF", highlightbackground="#000000", highlightcolor="#0000FF", highlightthickness=1)
    
        self.bind("<Delete>", lambda e: self.master.delete_selection())
        # self.bind("x", lambda e: print(self.winfo_rootx(), self.winfo_rooty(), self.master.winfo_rootx(), self.master.winfo_rooty()))

    # TODO low: disconnect all button

    @abstractmethod
    def encode(self, hatch_tl: Dict[Hatch, Tuple[int, bool, int]]):
        ...

    @abstractmethod
    def decode(self, d):
        ...

    @classmethod
    def _decode(cls, master, d):
        if d.get("type", "step") == "step":
            x = StepFrame(master)
            x.decode(d)
        elif d["type"] == "buffer":
            x = BufferFrame(master)
            x.decode(d)
        else:
            raise RuntimeError()

        return x


    @abstractmethod
    def reconstruct(self):
        ...

    def drag_init(self):
        self.update_idletasks()
        self.drag_start = (self.winfo_x(), self.winfo_y())

    def reconstruct_reconnect(self):
        if self.model is None:
            raise RuntimeError("?")

        # TODO low: validate
        for hatch in self.input_hatches.hatches:
            for conn in hatch.connections:
                self.model.pull.setdefault(hatch.item_id, []).append(conn.node.model) # type: ignore

        for hatch in self.output_hatches.hatches:
            for conn in hatch.connections:
                self.model.push.setdefault(hatch.item_id, []).append(conn.node.model) # type: ignore

    def tie(self, nodes: List["NodeFrame"]):
        self.input_hatches.tie(self.master, nodes)
        self.output_hatches.tie(self.master, nodes)

    def select(self):
        self.configure(highlightbackground="#0000FF")

    def deselect(self):
        self.configure(highlightbackground="#000000")

    def delete(self):
        self.master.delete_node(self)


def recipe_str(recipe):
    return str(Recipe(recipe))

def ask_multiple_choice_question(master, prompt, options):
    root = tk.Toplevel(master)

    # https://stackoverflow.com/a/42581226
    if prompt:
        tk.Label(root, text=prompt).pack()

    v = tk.IntVar()
    for i, option in enumerate(options):
        tk.Radiobutton(root, text=recipe_str(option), variable=v, value=i).pack(anchor="w")

    is_ok = [False]
    def ok():
        is_ok[0] = True
        root.destroy()

    tk.Button(root, text="Ok?", command=ok).pack()

    root.update_idletasks()
    root.geometry("")

    root.focus()
    root.grab_set()
    root.wait_window()

    if is_ok[0]:
        return options[v.get()]


class StepFrame(NodeFrame):
    def __init__(self, master, x=0, y=0):
        NodeFrame.__init__(self, master, x, y)

        self.model: Optional[Step]

        self.settings = tk.Frame(self, background="#FFFFFF", highlightbackground="#000000", highlightthickness=1)
        self.settings.grid(row=1, column=0, sticky="nesw")
        self.settings.configure()
        self.grid_rowconfigure(index=1, weight=4)
        self.machine = tk.StringVar()
        self.recipe_name = tk.StringVar()
        self.recipe: Optional[DictProxy] = None
        self.recipe_id: Optional[int] = None
        self.rate   = tk.DoubleVar()

        invalidate_machine = self.register(self.invalidate_machine)

        self.machinebox = AutocompleteEntry(self.settings, completevalues=list(master.recipes_by_machine.keys()), textvariable=self.machine, validatecommand=(invalidate_machine,))
        self.recipebox  = tk.Label(self.settings, textvariable=self.recipe_name)
        self.recipebox.configure(background="white", borderwidth=2, relief="groove")
        self.ratebox    = tk.Entry(self.settings, textvariable=self.rate)

        self.machinebox.grid(column=0, row=0)
        self.recipebox.grid(column=0, row=1)
        self.ratebox.grid(column=0, row=2)
        self.settings.grid_rowconfigure(0, weight=1)
        self.settings.grid_rowconfigure(1, weight=1)
        self.settings.grid_rowconfigure(2, weight=1)
        self.settings.grid_columnconfigure(0, weight=1)
        
        self.bind("<Control-r>", lambda _: self.refine())
        self.recipebox.bind("<Button-1>", lambda _: self.select_recipe())

        for e in MOUSE_EVENTS:
            self.settings.bind(e, lambda e: self.master.gesture_manager.on_event(e, self))

    def refine(self):
        x, y = self.winfo_x(), self.winfo_y()

        if self.recipe is not None:
            for n, hatch in enumerate(self.input_hatches.hatches):
                if not hatch.connections:
                    self.master.new_node(x - 100 + 50 * n, y - 300)

            for n, hatch in enumerate(self.output_hatches.hatches):
                if not hatch.connections:
                    self.master.new_node(x - 100 + 50 * n, y + 300)

    def invalidate_machine(self):
        # print("Invalidate!")

        self.recipe = None
        self.recipe_id = None
        self.recipe_name.set("")
        self.invalidate_recipe()

    def invalidate_recipe(self):
        self.remove_all()

        if self.recipe is not None:
            recipe = Recipe(self.recipe)

            # print(recipe)

            for item in recipe.consume:
                self.input_hatches.add_hatch(item)

            for item in recipe.produce:
                self.output_hatches.add_hatch(item)

    def disconnect_all(self):
        self.input_hatches.disconnect_all()
        self.output_hatches.disconnect_all()

    def remove_all(self):
        self.input_hatches.remove_all()
        self.output_hatches.remove_all()

    def set_recipe(self, recipe=None, recipe_id=None):
        if recipe:
            self.recipe = recipe
            recipe_id = self.master.recipe_id(self.machine.get(), recipe.unwrap())
            self.recipe_name.set(recipe_str(self.recipe))

            if True: # recipe_id != self.recipe_id:
                self.invalidate_recipe()

            self.recipe_id = recipe_id
        elif recipe_id:
            self.recipe = self.master.recipe_by_id(self.machine.get(), recipe_id)
            self.recipe_id = recipe_id
            self.recipe_name.set(recipe_str(self.recipe))

    def select_recipe(self):
        # TODO low: validate
        if self.machine.get():
            inputs  = [hatch.item_id for hatch in self.input_hatches.hatches if hatch.item_id]
            outputs = [hatch.item_id for hatch in self.output_hatches.hatches if hatch.item_id]

            recipes = self.master.search_recipe(self.machine.get(), inputs, outputs)

            if len(recipes) == 1:
                self.set_recipe(recipes[0])
            elif len(recipes) > 1:
                recipe = ask_multiple_choice_question(self, "Recipe?", recipes)
                # print(recipe)

                if recipe is not None:
                    self.set_recipe(recipe)
            else:
                print("No valid recipe found :(")

    def propagate_flow(self):
        if self.model is not None:
            # TODO low: validate
            self.model.propagate(rate=self.rate.get())

    def encode(self, hatch_tl: Dict[Hatch, Tuple[int, bool, int]]):
        return { "type": "step"
               , "pos": (self.winfo_x(), self.winfo_y())
               , "machine": self.machine.get()
               , "recipe": self.recipe_id
               , "rate": self.rate.get()
               , "inputs": self.input_hatches.encode(hatch_tl)
               , "outputs": self.output_hatches.encode(hatch_tl)}
    
    def decode(self, d):
        x, y = d["pos"]
        self.place(x=x, y=y)

        self.machine.set(d.get("machine", ""))
        self.recipe_id = d.get("recipe")

        if self.recipe_id is not None:
            self.set_recipe(recipe_id=self.recipe_id)

        self.rate.set(d.get("rate", ""))

        self.input_hatches.decode(d.get("inputs", []))
        self.output_hatches.decode(d.get("outputs", []))

    def reconstruct(self):
        if self.recipe is None:
            raise RuntimeError("Can't reconstruct when recipe is unspecified")
        else:
            self.model = Step(self.recipe)


class BufferFrame(NodeFrame):
    def __init__(self, master, x=0, y=0):
        NodeFrame.__init__(self, master, x, y)

        self.model: Optional[Buffer]
        self.label = tk.Label(self, text="AE")
       
        self.label.grid(row=1, column=0, sticky="nesw")
        self.label.configure(background="white")
        self.grid_rowconfigure(index=1, weight=1)
        
        for e in MOUSE_EVENTS:
            self.label.bind(e, lambda e: self.master.gesture_manager.on_event(e, self))

    def encode(self, hatch_tl: Dict[Hatch, Tuple[int, bool, int]]):
        return { "type": "buffer"
               , "pos": (self.winfo_x(), self.winfo_y())
               , "inputs": self.input_hatches.encode(hatch_tl)
               , "outputs": self.output_hatches.encode(hatch_tl)}
    
    def decode(self, d):
        x, y = d["pos"]
        self.place(x=x, y=y)

        self.input_hatches.decode(d.get("inputs", []))
        self.output_hatches.decode(d.get("outputs", []))

    def reconstruct(self):
        self.model = Buffer("AE")



def main():
    root = tk.Tk()

    the_canvas = NodeCanvas(root)

    root.protocol("WM_DELETE_WINDOW", the_canvas.on_closing)
    root.geometry("1080x1080+0+0")
    
    root.mainloop()


if __name__ == "__main__":
    main()