import tkinter as tk
import time

from enum import IntFlag, auto
from typing import List, Optional, Tuple
# from abc import ABC, abstractmethod


SHIFT = 0x1
CAPS  = 0x2
CTRL  = 0x4
NUMLCK = 0x8
SCRLLCK = 0x20
ALT = 0x20000

MOUSE_EVENTS = ["<Button-1>", "<B1-Motion>", "<ButtonRelease-1>", "<Button-2>", "<B2-Motion>", "<ButtonRelease-2>", "<Button-3>", "<B3-Motion>", "<ButtonRelease-3>"]


class Gesture(IntFlag):
    PRESS = auto()
    CLICK = auto()
    DRAG  = auto()
    DRAG_END = auto()
    HOLD  = auto()

    RIGHT  = auto()
    MIDDLE = auto()

    SHIFT = auto()


class GestureManager():
    HOLD_TIME = 0.5

    def __init__(self, canvas: "NodeCanvas"):
        self.canvas = canvas

        self.held: int  = 0
        self.drag: bool = False

        self.mod = 0

    def on_event(self, e: tk.Event, source: tk.Misc):
        x, y = e.x_root, e.y_root
        xint, yint = e.x, e.y
        mod = 0
        submod = 0

        mod |= self.mod
        
        if e.state & SHIFT:
            submod |= Gesture.SHIFT

        if e.num == 2:
            mod |= Gesture.RIGHT
        elif e.num == 3:
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


class NodeCanvas(tk.Canvas):
    def __init__(self, master: tk.Misc):
        tk.Canvas.__init__(self, master)

        self.gesture_manager = GestureManager(self)

        self.selection: List[NodeFrame] = []
        self.drag_start = None
        self.to_move = []
        self.selection_rectangle = None

        self.pack(expand=1, fill="both")
        self.configure(background="#DDDDDD")

        for e in MOUSE_EVENTS:
            self.bind(e, lambda e: self.gesture_manager.on_event(e, self))

    def gesture(self, x: int, y: int, xint: int, yint: int, mod: Gesture, source: tk.Misc):
        # print(mod, x, y)

        if mod == Gesture.PRESS:
            self.drag_start = (x, y)

            if source != self and source not in self.selection:
                self.deselect_all()
                self.select(source)

            on_selection = source != self
            self.to_move = self.selection if on_selection else self.winfo_children()

            # or only self.selection if source in self.selection
            for child in self.winfo_children():
                child.drag_start = (child.winfo_x(), child.winfo_y())
        elif mod == Gesture.PRESS | Gesture.SHIFT:
            self.drag_starti = (xint, yint)
            self.drag_start = (x, y)
            if source == self:
                self.selection_rectangle = self.create_rectangle(xint, yint, xint, yint, width=1, outline="#0000FF")
        elif mod == Gesture.CLICK:
            if source in self.selection:
                self.deselect_all()
                self.select(source)
            elif source == self:
                self.deselect_all()
        elif mod == Gesture.CLICK | Gesture.SHIFT:
            self.delete(self.selection_rectangle)
            self.selection_rectangle = None
            if source != self:
                self.select_toggle(source)
        elif mod == Gesture.HOLD | Gesture.SHIFT:
            self.delete(self.selection_rectangle)
        elif mod == Gesture.DRAG:
            self.drag(x, y)
        elif mod == Gesture.DRAG | Gesture.SHIFT:
            if self.selection_rectangle is not None:
                self.change_region_selection(xint, yint)
        elif mod & (~ Gesture.SHIFT) == Gesture.DRAG_END:
            if self.selection_rectangle is not None:
                self.select_region(xint, yint)
                self.delete(self.selection_rectangle)
                self.selection_rectangle = None

        # self.configure(background="#DDDDDD")
        # less trails, but stupid
        
    def drag(self, x, y):
        dx = x - self.drag_start[0]
        dy = y - self.drag_start[1]
    
        for child in self.to_move:
            child.place(x=child.drag_start[0] + dx, y=child.drag_start[1] + dy)

    def select_region(self, x1, y1):
        x0, y0 = self.drag_starti

        x0, x1 = min(x0, x1), max(x0, x1)
        y0, y1 = min(y0, y1), max(y0, y1)
        
        for child in self.winfo_children():
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
        else:
            self.select(child)


class NodeFrame(tk.Frame):
    def __init__(self, master: NodeCanvas):
        tk.Frame.__init__(self, master)

        # True iff the last mouse interaction (in this widget) was a motion event (as opposed to a single click)
        self.drag_start = None

        self.place(x=40, y=40, width=40, height=40)
        self.configure(background="#FFFFFF", highlightbackground="#000000", highlightthickness=1)
        
        for e in MOUSE_EVENTS:
            self.bind(e, lambda e: master.gesture_manager.on_event(e, self))
    
    def select(self):
        self.configure(highlightbackground="#0000FF")

    def deselect(self):
        self.configure(highlightbackground="#000000")


root = tk.Tk()

canvas = NodeCanvas(root)

box = NodeFrame(canvas)
box1 = NodeFrame(canvas)
box2 = NodeFrame(canvas)

#box.configure(background="#FFFFFF", highlightbackground="red", highlightthickness=1)
#box.place(x=40, y=40, width=40, height=40)

root.mainloop()

# def log(pref):
#     def f(e):
#         print(pref, e)

#     return f


# class Responsive(ABC):
#     @abstractmethod
#     def gesture(self, gesture: Gesture):
#         ...