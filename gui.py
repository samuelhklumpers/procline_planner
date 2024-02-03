from abc import ABC, abstractmethod
import colorsys
import math
import tkinter as tk
import time
import json

from typing import Any, Dict, List, Optional, Union, Tuple
from enum import IntFlag, auto

from ttkwidgets.autocomplete import AutocompleteEntry
import tkinter.simpledialog

from recipes import Recipes
from throughput import Buffer, Recipe, Step, make_groups
from tscca import circuits


SAVE_FN = "procline.json"
MOUSE_EVENTS = ["<Button-1>", "<B1-Motion>", "<ButtonRelease-1>", "<Button-2>", "<B2-Motion>", "<ButtonRelease-2>", "<Button-3>", "<B3-Motion>", "<ButtonRelease-3>", "<MouseWheel>"]

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


class Gesture(IntFlag):
    PRESS = auto()
    CLICK = auto()
    DRAG  = auto()
    DRAG_END = auto()
    HOLD   = auto()
    SCROLL = auto()

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
        pos = Vec2(e.x_root, e.y_root)
        posi = Vec2(e.x, e.y)
        mod = Gesture(0)
        submod = 0

        # print(e, e.state, e.type)

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
        elif e.type == tk.EventType.MouseWheel:
            mod |= Gesture.SCROLL
            pos = Vec2(e.delta, 0)


        self.canvas.gesture(pos, posi, mod, source)


class CanvasMenu(tk.Menu):
    def __init__(self, master):
        tk.Menu.__init__(self, master, tearoff=False)

        self.coords = vzero

        self.add_command(label="New node", command=lambda: master.new_node(self.coords))
        self.add_command(label="New buffer", command=lambda: master.new_buffer(self.coords))


class NodeMenu(tk.Menu):
    def __init__(self, master: "NodeCanvas"):
        tk.Menu.__init__(self, master, tearoff=False)
        self.master: NodeCanvas

        self.node: Optional["StepFrame"] = None
        self.add_command(label="Propagate from here", command=lambda: self.master.propagate_flow(self.node))
        self.add_command(label="Delete", command=lambda: (self.node.delete() if self.node is not None else None))


class NodeToolbar(tk.Menu):
    def __init__(self, master: "NodeCanvas"):
        tk.Menu.__init__(self, master)
        self.master: NodeCanvas

        self.master.root.config(menu=self)

        calc_menu = tk.Menu(self)
        self.add_cascade(label="Calculate", menu=calc_menu)
        calc_menu.add_command(label="Find connected components", command=self.master.run_sccs)
        calc_menu.add_command(label="Force graph reconstruction", command=self.master.reconstruct)


class Vec2:
    def __init__(self, x, y):
        self.x = int(x)
        self.y = int(y)

    def __repr__(self):
        return f"Vec2({self.x}, {self.y})"

    def __add__(self, other: "Vec2"):
        return Vec2(self.x + other.x, self.y + other.y)

    def __sub__(self, other: "Vec2"):
        return Vec2(self.x - other.x, self.y - other.y)

    def __iter__(self):
        yield from (self.x, self.y)

    def __mul__(self, m: float):
        return Vec2(self.x * m, self.y * m)

    def __truediv__(self, m: float):
        return Vec2(self.x / m, self.y / m)

    def encode(self):
        return (self.x, self.y)


class State(Recipes):
    def __init__(self, master: "NodeCanvas"):
        super(State, self).__init__()

        self.master = master
        self.gesture_manager = self.master.gesture_manager
        self.scale  = 1.0
        self.center = self.screencenter = Vec2(0, 0)

    def init(self):
        self.center = self.screencenter = self.master.dimensions() / 2


class BetterWidget(tk.Widget):
    def __init__(self, globalstate: State, **kwargs):
        super(BetterWidget, self).__init__(**kwargs)
        
        self.globalstate = globalstate

    def position(self):
        """position"""
        return Vec2(self.winfo_x(), self.winfo_y())

    def dimensions(self):
        """dimensions"""
        return Vec2(self.winfo_width(), self.winfo_height())
    

class BetterFrame(tk.Frame):
    def __init__(self, **kwargs):
        super(BetterFrame, self).__init__(**kwargs)


# TODO low prio: canvas in foreground -> put the nodes in canvas.create_window's
class NodeCanvas(BetterWidget, tk.Canvas):
    def __init__(self, master: tk.Tk, **kwargs):
        self.gesture_manager = GestureManager(self)
        super(NodeCanvas, self).__init__(globalstate=State(self), master=master, **kwargs)
        self.root = master

        self.menubar = NodeToolbar(self)

        self.autosave = SAVE_FN
        self.nodes: List[NodeFrame] = []


        self.selection: List[NodeFrame] = []
        self.hatch: Optional[Hatch] = None
        self.drag_start  = vzero
        self.drag_starti = vzero

        self.connections: Dict[Hatch, Dict[Hatch, Connection]] = {}

        # self.to_move: List[NodeFrame] = []
        # self.to_move_left: List[Connection] = []
        # self.to_move_right: List[Connection] = []

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
        self.globalstate.init()

        # TODO mid prio: colour groups and group lines

    def run_sccs(self):
        self.reconstruct()

        nodes = {node.model : node for node in self.nodes}

        groups = circuits(nodes)
        make_groups(groups)

        n = len(groups)

        for i, group in enumerate(groups):
            r, g, b = colorsys.hsv_to_rgb(i / n, 1.0, 1.0)
            r, g, b = int(255 * r), int(255 * g), int(255 * b)


            for node in group:
                col = f"#{r:02x}{g:02x}{b:02x}"
                nodes[node].set_background(col)

        # for node in self.nodes:
        #     if isinstance(node.model, Step):
        #         print(node, node.model.group, node.model.pull, node.model.push)

    def propagate_flow(self, node: Optional["StepFrame"]):
        self.run_sccs()

        print("Propagating")

        if node is None:
            raise RuntimeError("?")

        Buffer.global_reset()
        for node_ in self.nodes:
            if isinstance(node_, BufferFrame):
                if node_.model is None:
                    raise RuntimeError("Impossible")

                node_.model.reset()

        # TODO low: report total failure
        node.propagate_flow()

        summary = {}
        eut = 0
        surge_eut = 0
        for step in self.nodes:
            if isinstance(step, StepFrame):
                if step.model is None:
                    raise RuntimeError("Impossible")
                else:
                    step.set_rate(step.model.rate)
                    eut += step.eut
                    surge_eut += step.surge_eut
                    machine = step.machine.get()
                    summary[machine] = 1 + summary.get(machine, 0)
            if isinstance(step, BufferFrame):
                if step.model is None:
                    raise RuntimeError("Impossible")
                else:
                    step.display_flow()

        amps, tier = powerTier(eut)
        surge_amps, surge_tier = powerTier(surge_eut)
        print(f"Power usage: {eut:.1f} ({amps:.1f} {TIERS[tier]})")
        print(f"Surge usage: {surge_eut:.1f} ({surge_amps:.1f} {TIERS[surge_tier]})")

        flows = [(flow, item) for item, flow in Buffer.global_flow.items()]
        flows.sort()
        
        for flow, item in flows:
            if abs(flow) < 1e-10:
                print(f"{self.globalstate.item_name(item)}: Neutral?")
            else:
                print(f"{self.globalstate.item_name(item)}: {flow}")
        print("Summary:")
        for machine, num in summary.items():
            print(f"{num:>3}x {machine}")
        print()

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
    
    def _decode(self, canvas):
        for d_child in canvas:
            self.nodes.append(NodeFrame._decode(self.globalstate, self, **d_child))

    def decode(self, _=None):
        self.unbind("<Visibility>")

        try:
            with open(SAVE_FN, mode="r", encoding="utf-8") as fp:
                d = json.load(fp)
                
                self._decode(**d)
                self.update()

                for node in self.nodes:
                    node.tie(self.nodes)

                self.after_idle(self.drag_finish)
        except OSError:
            pass

    def on_closing(self):
        if self.autosave:
            with open(self.autosave, mode="w", encoding="utf-8") as fp:
                json.dump(self, fp, default=lambda x: x.encode())
        
        self.master.destroy()

    def gesture(self, pos: Vec2, posi: Vec2, mod: Gesture, source: Union["NodeCanvas", "NodeFrame", "Hatch"]):
        if mod == Gesture.PRESS:
            self.drag_start = pos

            source.focus_set()
            if isinstance(source, NodeFrame):
                if source not in self.selection:
                    self.deselect_all()
                    self.select(source)
            else:
                self.deselect_all()


            # self.drag_init(source != self)
        elif mod == Gesture.PRESS | Gesture.SHIFT:
            self.drag_starti = posi
            self.drag_start  = pos
            if source == self:
                xint, yint = posi
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
            x, y = pos
            if isinstance(source, StepFrame):
                self.node_menu.tk_popup(x, y, 0)
                self.node_menu.node = source
            else:
                self.canv_menu.tk_popup(x, y, 0)
                self.canv_menu.coords = posi
        elif mod == Gesture.CLICK | Gesture.SHIFT:
            self.delete(self.selection_rectangle)
            self.selection_rectangle = 0
            if isinstance(source, NodeFrame):
                self.select_toggle(source)
        elif mod == Gesture.CLICK | Gesture.CTRL:
            if isinstance(source, Hatch):
                source.item_menu()
        elif mod == Gesture.CLICK | Gesture.RIGHT | Gesture.CTRL:
            print(source)
        elif mod == Gesture.HOLD | Gesture.SHIFT:
            self.delete(self.selection_rectangle)
        elif mod == Gesture.DRAG:
            self.drag(pos)
        elif mod == Gesture.DRAG | Gesture.SHIFT:
            if self.selection_rectangle:
                self.change_region_selection(posi)
        elif mod & (~ Gesture.SHIFT) == Gesture.DRAG_END:
            self.drag_finish()

            if self.selection_rectangle:
                self.select_region(posi)
                self.delete(self.selection_rectangle)
                self.selection_rectangle = 0
        elif mod & Gesture.SCROLL:
            delta = pos.x / 120 / 10

            delta *= 3


            self.globalstate.scale = max(0.01, self.globalstate.scale * (1 + delta))
            self.update_positions()
            self.update_scales()

        if not isinstance(source, Hatch):
            self.hatch = None

        # self.configure(background="#DDDDDD")
        # less trails, but stupid
        
    # def drag_init(self, on_selection):
    #     self.to_move = self.selection
        
    #     to_move_left = set()
    #     to_move_right = set()

    #     for child in self.to_move:
    #         for hatch in child.input_hatches.hatches:
    #             for conn in hatch.connections:
    #                 to_move_right.add(self.connections[hatch][conn])

    #         for hatch in child.output_hatches.hatches:
    #             for conn in hatch.connections:
    #                 to_move_left.add(self.connections[hatch][conn])

    #     self.to_move_left = list(to_move_left)
    #     self.to_move_right = list(to_move_right)

    def update_positions(self):        
        for child in self.nodes:
            child.update_position()

    def update_scales(self):
        for child in self.nodes:
            child.update_scale()

    def drag(self, pos):
        dp = (pos - self.drag_start) / self.globalstate.scale
        
        self.drag_start = pos

    
        if self.selection:
            for child in self.selection:
                child.move(dp)
        else:
            self.globalstate.center -= dp
            self.update_positions()

    def drag_finish(self):
        # if not self.to_move:
        #     # just get all connections loaded
        #     self.drag_init(False)

        self.update_idletasks()

        # for child in self.to_move:
        #     child.drag_start = (child.winfo_x(), child.winfo_y())

        #     for conn in self.to_move_left:
        #         conn.drag_start = self.coords(conn.line)

        #     for conn in self.to_move_right:
        #         conn.drag_start = self.coords(conn.line)

        # self.to_move = []
        # self.to_move_left = []
        # self.to_move_right = []

    def select_region(self, pos):
        x0, y0 = self.drag_starti
        x1, y1 = pos

        x0, x1 = min(x0, x1), max(x0, x1)
        y0, y1 = min(y0, y1), max(y0, y1)
        
        for child in self.winfo_children():
            if not isinstance(child, NodeFrame):
                continue

            x = child.winfo_x()
            y = child.winfo_y()
            
            if x0 < x < x1 and y0 < y < y1 and child not in self.selection:
                self.select(child)    

    def change_region_selection(self, posi):
        xint, yint = posi
        self.coords(self.selection_rectangle, *self.drag_starti, xint, yint)

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

    def new_node(self, pos: Vec2):
        pos_ = pos + self.globalstate.center - self.globalstate.screencenter

        node = StepFrame(master=self, globalstate=self.globalstate, pos=pos_)
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
        while self.selection:
            self.selection[0].delete()

    def new_buffer(self, pos: Vec2):
        pos_ = pos + self.globalstate.center - self.globalstate.screencenter

        node = BufferFrame(master=self, globalstate=self.globalstate, pos=pos_)
        self.nodes.append(node)
        node.drag_init()

        return node

    def connect(self, a: "Hatch", b: "Hatch"):
        if a == b:
            return

        if a.is_input == b.is_input:
            return
        
        if self.connections.get(a, {}).get(b) is None:
            if a.is_input:
                a, b = b, a

            if not a.connect(b):
                return
            b.connect(a)

            x1, y1 = a.relative_position(self)
            x2, y2 = b.relative_position(self)

            x1, y1 = x1 + a.winfo_width() // 2, y1 + a.winfo_height()
            x2, y2 = x2 + b.winfo_width() // 2, y2 + b.winfo_height()

            dx = self.winfo_rootx()
            dy = self.winfo_rootx()

            conn = Connection(self, self.create_line(x1 - dx, y1 - dy, x2 - dx, y2 - dy, fill="#00FF00", width=3), a, b)

            self.connections.setdefault(a, {})[b] = conn
            self.connections.setdefault(b, {})[a] = conn
    
    def update_connection(self, a: "Hatch", b: "Hatch"):
        connection = self.connections[a][b] 

        x1, y1 = a.relative_position(self)
        x2, y2 = b.relative_position(self)

        x1, y1 = x1 + a.winfo_width() // 2, y1 + a.winfo_height()
        x2, y2 = x2 + b.winfo_width() // 2, y2 + b.winfo_height()

        dx = self.winfo_rootx()
        dy = self.winfo_rootx()

        self.coords(connection.line, x1 - dx, y1 - dy, x2 - dx, y2 - dy)

    def disconnect(self, a: "Hatch", b: "Hatch"):
        if self.connections.get(a, {}).get(b) is not None:
            self.delete(self.connections[a][b].line)
            del self.connections[a][b]
            del self.connections[b][a]
            
            a._disconnect(b)
            b._disconnect(a)

    def toggle_connect(self, a: "Hatch", b: "Hatch"):
        if self.connections.get(a, {}).get(b) is None:
            self.connect(a, b)
        else:
            self.disconnect(a, b)

vzero = Vec2(0, 0)

class Position(BetterWidget):
    def __init__(self, master: tk.Widget, parent: Optional["Position"], globalstate: State, pos=vzero, force=False, **kwargs):
        super(BetterWidget, self).__init__(master=master, **kwargs)

        self.parent = parent
        self.master: tk.Widget
        self.globalstate = globalstate

        self.pos = pos
        self.force = force

        self.init()

    def relative_position(self, relative_to) -> Vec2:
        if relative_to == self.master:
            return self.position()
        elif self.parent:
            return self.parent.relative_position(relative_to) + self.position()
        else:
            raise RuntimeError(f"{relative_to} is not above {self}")

    def move(self, dp):
        self.pos += dp
        self.update_position()



    def update_position(self):
        if self.force:
            p = (self.pos - self.globalstate.center) * self.globalstate.scale + self.globalstate.screencenter
            x, y = p
            self.place(x=x, y=y)

    def init(self):
        if self.force:
            x, y = self.pos
            self.place(x=x, y=y)

    def encode(self) -> Dict[str, Any]:
        return {"pos": self.pos.encode()}

    def decode(self, pos):
        self.pos = Vec2(*pos)
        self.init()


class Hatches(Position, BetterFrame, ABC):
    def __init__(self, globalstate: State, master: NodeCanvas
                , inputs: Optional["HatchBar"]=None, outputs: Optional["HatchBar"]=None, **kwargs):
        super(Hatches, self).__init__(globalstate=globalstate, master=master, **kwargs)
        self.master: NodeCanvas

        self.input_hatches  = inputs if inputs else \
            HatchBar(master=self, globalstate=globalstate, is_input=True)
        self.output_hatches = outputs if outputs else \
            HatchBar(master=self, globalstate=globalstate, is_input=False)

    @abstractmethod
    def set_background(self, colour):
        ...

    def update_scale(self):
        self.input_hatches.update_scale()
        self.output_hatches.update_scale()

    def update_connected_colour(self):
        good = True

        for hatch in self.input_hatches.hatches + self.output_hatches.hatches:
            if not hatch.connections:
                good = False
                break

        if good:
            self.set_background(Hatch.CONNECTED)
        else:
            self.set_background(Hatch.DISCONNECTED)

    def disconnect(self, a, b):
        self.master.disconnect(a, b)

    def encode(self, hatch_tl):
        d = super(Hatches, self).encode()
        d["inputs"]  = self.input_hatches.encode(hatch_tl)
        d["outputs"] = self.output_hatches.encode(hatch_tl)

        return d

    def decode(self, inputs, outputs, **kwargs):
        super(Hatches, self).decode(**kwargs)

        self.input_hatches.decode(*inputs)
        self.output_hatches.decode(*outputs)

    def update_position(self):
        super(Hatches, self).update_position()
        self.input_hatches.update_hatches()
        self.output_hatches.update_hatches()
        

    def move(self, dp):
        super(Hatches, self).move(dp)
        self.input_hatches.update_hatches()
        self.output_hatches.update_hatches()

        #     for c in h.connections:

        #     x1, y1, x2, y2 = conn.drag_start

        #     if conn in self.to_move_right:
        #         self.coords(conn.line, x1 + dx, y1 + dy, x2 + dx, y2 + dy)
        #     else:
        #         self.coords(conn.line, x1 + dx, y1 + dy, x2, y2)

        # for conn in self.to_move_right:
        #     x1, y1, x2, y2 = conn.drag_start

        #     if conn not in self.to_move_left:
        #         self.coords(conn.line, x1, y1, x2 + dx, y2 + dy)


class NodeFrame(Hatches, ABC):
    def __init__(self, master: NodeCanvas, **kwargs):
        super(NodeFrame, self).__init__(master=master, parent=None, force=True, **kwargs)
        self.master: NodeCanvas

        self.model: Union[None, Step, Buffer] = None

        self.input_hatches.grid(row=0, column=0, sticky="nesw")
        self.output_hatches.grid(row=2, column=0, sticky="nesw")

        self.grid_rowconfigure(index=0, weight=1)
        self.grid_rowconfigure(index=2, weight=1)
        self.grid_columnconfigure(index=0, weight=1)

        self.drag_start: Tuple[int, int] = 0, 0

        self.nwidth = self.nheight = 200
        self.place(width=self.nwidth, height=self.nheight)
        self.configure(background="#FFFFFF", highlightbackground="#000000", highlightcolor="#0000FF", highlightthickness=1)
    
        self.bind("<Delete>", lambda e: self.master.delete_selection())

    # TODO low: disconnect all button
    def encode(self, hatch_tl):
        return super(NodeFrame, self).encode(hatch_tl)
    
    def update_scale(self):
        super(NodeFrame, self).update_scale()

        s = self.globalstate.scale
        self.place(width=s * self.nwidth, height=s * self.nheight)
        # self.input_hatches.update_scale()
        # self.output_hatches.update_scale()

    def decode(self, **d):
        super(NodeFrame, self).decode(**d)

    @classmethod
    def _decode(cls, globalstate, master, type, **d):
        if type == "step":
            x = StepFrame(globalstate=globalstate, master=master)
            x.decode(**d)
        elif type == "buffer":
            x = BufferFrame(globalstate=globalstate, master=master)
            x.decode(**d)
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


def ask_multiple_choice_question(master, prompt, options):
    root = tk.Toplevel(master)

    # https://stackoverflow.com/a/42581226
    if prompt:
        tk.Label(root, text=prompt).pack()

    v = tk.IntVar()
    for i, option in enumerate(options):
        tk.Radiobutton(root, text=str(option), variable=v, value=i).pack(anchor="w")

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


TIERS = [ "LV", "MV", "HV", "EV"
        , "IV", "LuV", "ZPM", "UV"
        , "UHV", "UEV", "UIV", "UMV"]
def powerTier(eut):

    m = eut / 32
    e = min(math.ceil(math.log(max(m, 1), 4)), len(TIERS) - 1)

    m /= 4 ** e

    return (m, e)


class StepFrame(NodeFrame):
    def __init__(self, **kwargs):
        super(StepFrame, self).__init__(**kwargs)

        self.model: Optional[Step]

        self.settings = tk.Frame(self, background="#FFFFFF", highlightbackground="#000000", highlightthickness=1)
        self.settings.grid(row=1, column=0, sticky="nesw")
        self.settings.configure()
        self.grid_rowconfigure(index=1, weight=4)
        self.machine = tk.StringVar()
        self.recipe_name = tk.StringVar()
        self.recipe: Optional[Recipe] = None
        self.recipe_id: Optional[int] = None
        self.rate   = tk.DoubleVar()
        self.eut = self.surge_eut = 0

        invalidate_machine = self.register(self.invalidate_machine)
        validate_rate = self.register(self.validate_rate)

        # TODO high: list valid machines
        self.machinebox = AutocompleteEntry(self.settings, completevalues=list(self.globalstate.recipes_by_machine.keys()), textvariable=self.machine, validatecommand=(invalidate_machine,))
        self.recipebox  = tk.Label(self.settings, textvariable=self.recipe_name)
        self.recipebox.configure(background="white", borderwidth=2, relief="groove")
        self.ratebox    = tk.Entry(self.settings, textvariable=self.rate, validatecommand=(validate_rate,))
        self.powerlabel = tk.Label(self.settings)

        self.machinebox.grid(column=0, row=0)
        self.recipebox.grid(column=0, row=1)
        self.ratebox.grid(column=0, row=2)
        self.powerlabel.grid(column=0, row=3)
        self.settings.grid_rowconfigure(0, weight=1)
        self.settings.grid_rowconfigure(1, weight=1)
        self.settings.grid_rowconfigure(2, weight=1)
        self.settings.grid_rowconfigure(3, weight=1)
        self.settings.grid_columnconfigure(0, weight=1)
        
        self.bind("<Control-r>", lambda _: self.refine())
        self.bind("<Control-a>", lambda _: self.auto())
        self.recipebox.bind("<Button-1>", lambda _: self.select_recipe())

        for e in MOUSE_EVENTS:
            self.settings.bind(e, lambda e: self.master.gesture_manager.on_event(e, self))
        
        self.update_connected_colour()

    def update_scale(self):
        super(StepFrame, self).update_scale()
        self.machinebox.configure(font=("Segoe UI",  int(1 + 8 * self.globalstate.scale)))
        self.recipebox.configure(font=("Segoe UI",  int(1 + 8 * self.globalstate.scale)))
        self.ratebox.configure(font=("Segoe UI",  int(1 + 8 * self.globalstate.scale)))

    def set_background(self, colour):
        self.configure(background=colour)
        self.settings.configure(background=colour)

    def delete(self):
        self.invalidate_machine()
        super(StepFrame, self).delete()

    def auto(self):
        if self.recipe is not None:
            for hatch1 in self.input_hatches.hatches:
                if not hatch1.connections:
                    for node in self.master.nodes:
                        for hatch2 in node.output_hatches.hatches:
                            if hatch1.item_id == hatch2.item_id:
                                self.globalstate.master.connect(hatch1, hatch2)

            for hatch1 in self.output_hatches.hatches:
                if not hatch1.connections:
                    for node in self.master.nodes:
                        for hatch2 in node.input_hatches.hatches:
                            if hatch1.item_id == hatch2.item_id:
                                self.globalstate.master.connect(hatch1, hatch2)

    def refine(self):
        p = self.position()

        if self.recipe is not None:
            for n, hatch in enumerate(self.input_hatches.hatches):
                if not hatch.connections:
                    other = self.master.new_node(p + Vec2(-100 + 50 *  n, -300))
                    self.globalstate.master.connect(hatch, other.output_hatches.add_hatch())

            for n, hatch in enumerate(self.output_hatches.hatches):
                if not hatch.connections:
                    other = self.master.new_node(p + Vec2(-100 + 50 *  n, 300))
                    self.globalstate.master.connect(hatch, other.input_hatches.add_hatch())

    def invalidate_machine(self):
        # print("Invalidate!")

        self.recipe = None
        self.recipe_id = None
        self.recipe_name.set("")
        self.invalidate_recipe()

    def invalidate_recipe(self):
        # TODO high: keep valid hatches
        self.remove_all()

        if self.recipe is not None:
            # print(recipe)

            for item in self.recipe.consume:
                self.input_hatches.add_hatch(item)

            for item in self.recipe.produce:
                self.output_hatches.add_hatch(item)

    def disconnect_all(self):
        self.input_hatches.disconnect_all()
        self.output_hatches.disconnect_all()

    def remove_all(self):
        self.input_hatches.remove_all()
        self.output_hatches.remove_all()

    def set_recipe(self, recipe: Optional[Recipe]=None, recipe_id=None):
        if recipe is not None:
            self.recipe = recipe
            recipe_id = self.globalstate.recipe_id(self.machine.get(), recipe.raw)
            self.recipe_name.set(str(self.recipe))

            if True: # recipe_id != self.recipe_id:
                self.invalidate_recipe()

            self.recipe_id = recipe_id
        elif recipe_id is not None:
            self.recipe = self.globalstate.recipe_by_id(self.machine.get(), recipe_id)
            self.recipe_id = recipe_id
            self.recipe_name.set(str(self.recipe))

    def select_recipe(self):
        # TODO low: validate
        inputs  = [hatch.item_id for hatch in self.input_hatches.hatches if hatch.item_id]
        outputs = [hatch.item_id for hatch in self.output_hatches.hatches if hatch.item_id]
        
        if not self.machine.get() and not (inputs + outputs):
            print("Try setting some hatches or the machine type")
            return

        if self.machine.get():
            recipes = self.globalstate.search_recipe(self.machine.get(), inputs, outputs)

            if len(recipes) == 1:
                self.set_recipe(recipes[0])
            elif len(recipes) > 1:
                recipe = ask_multiple_choice_question(self, "Recipe?", recipes)
                # print(recipe)

                if recipe is not None:
                    self.set_recipe(recipe)
            else:
                print("No valid recipe found :(")
        else:
            recipes_by_machine = self.globalstate.search_machine_recipe(inputs, outputs)

            class MR:
                def __init__(self, m, r):
                    self.m = m
                    self.r = r

                def __str__(self):
                    return f"({self.m}) {self.r}"

            recipes = [MR(m, r) for m, rs in recipes_by_machine.items() for r in rs]

            if len(recipes) == 1:
                mr = recipes[0]
                machine, recipe = mr.m, mr.r
                self.machine.set(machine)
                self.set_recipe(recipe)
            elif len(recipes) > 1:
                mr = ask_multiple_choice_question(self, "Recipe?", recipes)

                if mr is not None:
                    machine, recipe = mr.m, mr.r
                    self.machine.set(machine)
                    self.set_recipe(recipe)
            else:
                print("No valid machine and recipe found :(")


    def propagate_flow(self):
        if self.model is not None:
            # TODO low: validate
            self.model.propagate(rate=self.rate.get())

    def encode(self, hatch_tl: Dict["Hatch", Tuple[int, bool, int]]):
        d = super(StepFrame, self).encode(hatch_tl)

        d.update({ "type": "step"
                 , "machine": self.machine.get()
                 , "recipe": self.recipe_id
                 , "rate": self.rate.get()})

        return d

    def decode(self, machine, recipe, rate, **d):
        super(StepFrame, self).decode(**d)

        self.machine.set(machine)
        self.recipe_id = recipe

        if self.recipe_id is not None:
            self.set_recipe(recipe_id=self.recipe_id)

        self.set_rate(rate)

    def validate_rate(self):
        rate = self.rate.get()

        if self.recipe is not None:
            self.eut = eut = self.recipe.power * rate
            amps, tier = powerTier(eut)

            _, minTier = powerTier(self.recipe.power)

            surgeTier = max(tier, minTier)
            self.surge_eut = 32 * (4 ** surgeTier)

            # print(tier, minTier, self.recipe, self.recipe.power)

            #if tier < minTier:
            text = f"{eut:.1f} ({amps:.1f} {TIERS[tier]}, min. {TIERS[minTier]})"
            #else:
            #    text = f"{eut:.1f} ({amps:.1f} {TIERS[tier]})"

            self.powerlabel.configure(text=text)

    def set_rate(self, rate):
        self.rate.set(rate)
        self.validate_rate()
    

    def reconstruct(self):
        if self.recipe is None:
            raise RuntimeError("Can't reconstruct when recipe is unspecified")
        else:
            self.model = Step(self.recipe)

            # print(self.model, self)


class BufferFrame(NodeFrame):
    def __init__(self, **kwargs):
        super(BufferFrame, self).__init__(**kwargs)

        self.model: Optional[Buffer]
        self.label = tk.Label(self, text="AE")
       
        self.label.grid(row=1, column=0, sticky="nesw")
        self.label.configure(background="white")
        self.grid_rowconfigure(index=1, weight=1)
        
        for e in MOUSE_EVENTS:
            self.label.bind(e, lambda e: self.master.gesture_manager.on_event(e, self))

    def update_scale(self):
        super(BufferFrame, self).update_scale()
        self.label.configure(font=("Segoe UI", int(1 + 8 * self.globalstate.scale)))

    def display_flow(self):
        if self.model is None:
            ...
        else:
            text = "\n".join(f"{self.globalstate.item_name(item)}: {flow}" for item, flow in self.model.flow.items())
            self.label.config(text=text)

    def encode(self, hatch_tl: Dict["Hatch", Tuple[int, bool, int]]):
        d = super(BufferFrame, self).encode(hatch_tl)
        d["type"] = "buffer"

        return d
 
    def decode(self, **d):
        super(BufferFrame, self).decode(**d)

    def reconstruct(self):
        self.model = Buffer("AE")

    def set_background(self, colour):
        self.configure(background=colour)


class HatchBar(Position, BetterFrame):
    def __init__(self, master: Hatches, is_input: bool, **kwargs):
        super(HatchBar, self).__init__(master=master, parent=master, force=False, **kwargs)
        self.master: Hatches

        self.configure(background="#FFFFFF", highlightbackground="#000000", highlightthickness=1)

        self.is_input = is_input
        self.plus = tk.Button(self, text="+", command=self.add_hatch)
        self.hatches: List[Hatch] = []

        self.space()

    def update_scale(self):
        self.plus.configure(font=("Segoe UI",  int(1 + 8 * self.globalstate.scale)))

        for h in self.hatches:
            h.update_scale()

    def encode(self, hatch_tl: Dict["Hatch", Tuple[int, bool, int]]):
        d = []
        for hatch in self.hatches:
            d.append(hatch.encode(hatch_tl))

        return d

    def decode(self, *d):
        for d_hatch in d:
            hatch = Hatch(master=self, item_id="", globalstate=self.globalstate, is_input=self.is_input)
            hatch.decode(**d_hatch)
            self.insert_hatch(len(self.hatches), hatch)

        return self

    def update_colour(self):
        self.master.update_connected_colour()

    def disconnect(self, a, b):
        self.master.disconnect(a, b)

    def disconnect_all(self):
        for hatch in self.hatches:
            hatch.disconnect_all()

    def remove_all(self):
        while self.hatches:
            self.remove_hatch(self.hatches[0])

    def tie(self, canvas: "NodeCanvas", nodes: List["NodeFrame"]):
        for hatch in self.hatches:
            hatch.tie(canvas, nodes)

    def update_hatches(self):
        for hatch in self.hatches:
            hatch.update_connections()

    def add_hatch(self, item_id=None):
        # TODO low: adding hatches should move connections on the canvas
        x = Hatch(master=self, globalstate=self.globalstate, is_input=self.is_input, item_id=item_id)
        self.hatches.append(x)
        self.update_colour()
        self.space()

        return x

    def insert_hatch(self, i, hatch):
        self.hatches.insert(i, hatch)
        self.space()
        self.update_colour()

    def remove_hatch(self, hatch):
        self.hatches.remove(hatch)
        hatch.remove()
        self.space()

    def space(self):
        xs = [self.plus] + self.hatches
        n = len(xs)

        for i, x in enumerate(xs):
            x.place(relx=i / n, rely=0, relwidth=1 / n, relheight=1)

        self.update_hatches()


class Connection:
    def __init__(self, canvas: NodeCanvas, line: int, start: "Hatch", end: "Hatch"):
        self.line = line
        self.drag_start = canvas.coords(line)
        self.start = start
        self.end = end


class Hatch(Position, BetterFrame):
    DISCONNECTED = "#FF8888"
    CONNECTED    = "#FFFFFF"

    def __init__(self, master: "HatchBar", is_input=False, item_id=None, **kwargs):
        super(Hatch, self).__init__(master=master, parent=master, force=False, **kwargs)
        self.configure(background="#FFFFFF", highlightbackground="#000000", highlightthickness=1)
        self.master: "HatchBar"

        self.description = tk.StringVar()
        self.label = tk.Label(self, textvariable=self.description)

        self.label.configure(background=Hatch.DISCONNECTED)
        self.configure(background=Hatch.DISCONNECTED)
        
        self.label.pack(expand=1, fill="both")

        self.node: Hatches = master.master
        self.item_name = ""
        self.item_id   = ""

        if item_id is not None:
            self.set_item(item_id)

        self.is_input = is_input
        self.connections: List[Hatch] = []

        self.d_connections = {}

        self.configure(highlightcolor="#00AAFF")

    
        for e in MOUSE_EVENTS:
            self.bind(e, lambda e: self.globalstate.gesture_manager.on_event(e, self))
            self.label.bind(e, lambda e: self.globalstate.gesture_manager.on_event(e, self))

        self.bind("<Delete>", lambda e: self.master.remove_hatch(self))

    def update_scale(self):
        self.label.configure(font=("Segoe UI",  int(1 + 8 * self.globalstate.scale)))

    def remove(self):
        self.disconnect_all()
        self.destroy()

    def encode(self, hatch_tl: Dict["Hatch", Tuple[int, bool, int]]):
        return { "connections": [hatch_tl[x] for x in self.connections if x in hatch_tl] # start screaming if it isn't
               , "item_id": self.item_id
               , "item_name": self.item_name }

    def decode(self, connections, item_id, item_name):
        self.d_connections = connections
        self.set_item(item_id)
    
    def set_item(self, item_id):
        # , item_name):
        self.item_id = item_id
        self.item_name = self.globalstate.item_name(item_id)
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
        if bool(self.item_name) > bool(target.item_name):
            target.set_item(self.item_id)
        elif bool(self.item_name) < bool(target.item_name):
            self.set_item(target.item_id)
        elif self.item_name != target.item_name:
            print(f"Mismatched hatches {self.item_name} - {target.item_name}")
            return False

        if target not in self.connections:
            self.connections.append(target)

            self.label.configure(background=Hatch.CONNECTED)
            self.configure(background=Hatch.CONNECTED)
            self.master.update_colour()

        return True

    def _disconnect(self, target: "Hatch"):
        if target in self.connections:
            self.connections.remove(target)

            if not self.connections:    
                self.label.configure(background=Hatch.DISCONNECTED)
                self.configure(background=Hatch.DISCONNECTED)
                self.master.update_colour()

    def disconnect_all(self):
        while self.connections:
            self.master.disconnect(self, self.connections[0])

    def item_menu(self):
        item_name = tkinter.simpledialog.askstring("Item name?", "Item name?", initialvalue=self.item_name)
        item_id = ""

        if item_name is None:
            return

        try:
            item_id = self.globalstate.itemlist[item_name][0] # TODO low: lol
            self.set_item(item_id) # bit inefficient but ok
        except:
            print("Warning:", item_name, "is an invalid item name")

        if item_id != self.item_id:
            self.disconnect_all()

    def update_connections(self):
        for c in self.connections:
            self.globalstate.master.update_connection(self, c)


def main():
    root = tk.Tk()

    the_canvas = NodeCanvas(root)

    root.protocol("WM_DELETE_WINDOW", the_canvas.on_closing)
    root.geometry("1080x1080+0+0")
    
    root.mainloop()

    return root, the_canvas


if __name__ == "__main__":
    root, canvas = main()
