from typing import Dict, List, Optional, Set, Tuple, Union
from numpy.linalg import lstsq
import numpy as np

from dictproxy import DictProxy


Item = str
Push = bool

PULL: Push = False
PUSH: Push = True

Node = Union["Step", "Buffer"]

class Recipe:
    def __init__(self, recipe: DictProxy):
        self.duration = recipe["dur"]
        self.power    = recipe["eut"]

        self.consume: Dict[Item, int] = {}
        self.produce: Dict[Item, int] = {}

        self.table = {}

        for item in recipe.iI:
            if item.a != 0:
                self.consume[item.uN] = item.a
                self.table[item.uN] = item.lN

        for item in recipe.fI:
            if item.a != 0:
                self.consume[item.uN] = item.a
                self.table[item.uN] = item.lN

        for item in recipe.iO:
            if item.a != 0:
                self.produce[item.uN] = item.a
                self.table[item.uN] = item.lN

        for item in recipe.fO:
            if item.a != 0:
                self.produce[item.uN] = item.a
                self.table[item.uN] = item.lN

    def inrate(self, item: Item):
        # print(self.consume)
        return self.consume[item] / self.duration

    def outrate(self, item: Item):
        # print(self.produce)
        return self.produce[item] / self.duration
    
    def __repr__(self):
        # TODO low: maybe scientific
        x = " + ".join(str(v) + " * " + self.table[u] for u, v in self.consume.items())
        x += " -> " 
        x += " + ".join(str(v) + " * " + self.table[u] for u, v in self.produce.items())

        return x

IBuffer  = Tuple["Buffer", Push, Item]
IStep    = Tuple["Step", Push, Item]
IHatch    = Tuple[Node, Push, Item]
IVar     = Union["Step", IHatch]
Junction = int

ITEM_NONE = "None"

class Group:
    def __init__(self, steps: List["Step"]):
        self.steps     = steps
        self.junctions: Dict[IHatch, Junction] = {}

    def __repr__(self):
        return str(self.steps)

    # def propagate_nice():

        # cause_, push, item = cause
        # if isinstance(cause_, Step):
        #     if item == ITEM_NONE:
        #         cause_rate = 1.0
        #     else:
        #         if push:
        #             cause_rate = rateflow / cause_.recipe.outrate(item)
        #         else:
        #             cause_rate = -rateflow / cause_.recipe.inrate(item)
        # else:
        #     if item == ITEM_NONE:
        #         raise RuntimeError("A buffer cannot have a rate")
            
        #     if isinstance(cause, int):
        #         cause_ = buffs[cause][push][item]
        #     else:
        #         cause_ = cause
            

        #     cause_rate = 1.0


    def propagate(self, cause: IVar, flow=1.0):
        rate_flow, variables, outbound = self.matrix()

        
        # fix the rate of cause_ by adding the corresponding equation (row)
        rate_flow = np.pad(rate_flow, ((0, 1), (0, 0)))
        flows = np.zeros(rate_flow.shape[0])

        i = variables.index(cause)
        rate_flow[-1][i] = 1
        flows[-1]        = flow

        # print(variables)
        # print(rate_flow)

        # solve the system for vx (the rates) given vy (the flows)
        rates, res, _, _ = lstsq(rate_flow, flows, rcond=None)

        if res.sum() > 1e-15:
            print("warning high residual in cycle solution, results might be wrong")

        # print(rates)
        for v, rate_ in zip(variables, rates):
            # print(step, rateflow)

            if isinstance(v, Step):
                v.rate = rate_
            else:
                node, push, item = v

                if v != cause:
                    node.propagate_item(item, outbound[v], push, rate_ if push else -rate_)

    def neighbourhood(self) -> Set[Node]:
        # returns all nodes outside of this group with connections to this group
        neighs = set()

        for step in self.steps:
            for targets in step.pull.values():
                for target in targets:
                    neighs.add(target)

            for targets in step.push.values():
                for target in targets:
                    neighs.add(target)

        return neighs.difference(self.steps)

    def junction(self, start: Node, push: bool, item: Item) -> Set[Tuple[Node, bool]]:
        # a junction is a set of connected hatches of the same type
        seen  = set([(start, push)])
        queue = [(start, push)]

        while queue:
            node, push = queue.pop()

            connections = node.push if push else node.pull

            for target in connections.get(item, []):
                curr = (target, not push)

                if curr not in seen:
                    queue.append(curr)
                    seen.add(curr)

        return seen
    
    def matrix(self) -> Tuple[np.ndarray, List[IVar], Dict[IHatch, "Step"]]:
        # returns (A, x, o)
        # A: the matrix representing the flows as a response of the rates in and around this group
        # x: maps the column index to the associated internal step, or external IHatch
        # o: maps an external IHatch to the cause (internal step) of its propagation

        rate_flow: Dict[Junction, Dict[IVar, float]] = {}
        hatch_junction_ix: Dict[IHatch, Junction]    = {}
        outbound: Dict[IHatch, Step] = {}
        curr_junction_ix = 0

        for step in self.steps:
            # print(step)
            for item in step.recipe.consume.keys():
                # print(item)
                # look up if this hatch already has a junction associated to it
                hatch         = step, PULL, item
                junction_ix   = hatch_junction_ix.get(hatch, curr_junction_ix)
                junction_flow = rate_flow.setdefault(junction_ix, {})

                if junction_ix == curr_junction_ix:
                    curr_junction_ix += 1
                    # if not, create this junction
                    junction = self.junction(step, PULL, item)

                    # and associate this junction to all hatches connected to it
                    for neighbour, push in junction:
                        hatch_ = neighbour, push, item

                        # print("add", hatch_, "to", junction_ix)
                        if hatch_ in hatch_junction_ix:
                            raise RuntimeError(f"Impossible {hatch_} in junction {junction_ix}")
                        
                        hatch_junction_ix[hatch_] = junction_ix

                        if neighbour not in self.steps:
                            # if the hatch is external, remember where in this group it is connected to
                            outbound[hatch_]      = step
                            junction_flow[hatch_] = 1.0

                if step in junction_flow:
                    raise RuntimeError(f"Impossible {step} in junction {junction_ix}")

                junction_flow[step] = -step.recipe.inrate(item)

            for item in step.recipe.produce.keys():
                # print(item)

                hatch         = step, PUSH, item
                junction_ix   = hatch_junction_ix.get(hatch, curr_junction_ix)
                junction_flow = rate_flow.setdefault(junction_ix, {})

                if junction_ix == curr_junction_ix:
                    curr_junction_ix += 1

                    junction = self.junction(step, PUSH, item)
                    
                    for neighbour, push in junction:
                        hatch_ = neighbour, push, item

                        # print("add", hatch_, "to", junction_ix)
                        if hatch_ in hatch_junction_ix:
                            raise RuntimeError(f"Impossible {hatch_} in junction {junction_ix}")
                        
                        hatch_junction_ix[hatch_] = junction_ix

                        if neighbour not in self.steps:
                            outbound[hatch_]      = step
                            junction_flow[hatch_] = 1.0

                if step in junction_flow:
                    raise RuntimeError(f"Impossible {step} in junction {junction_ix}")

                junction_flow[step] = step.recipe.outrate(item)

        # extract the variables into a nice list
        variables: List[IVar] = []
        for junction_ix, junction_flow in rate_flow.items():
            for step in junction_flow.keys():
                if step not in variables:
                    variables.append(step)

        # extract the flows to a nice matrix
        rate_flow_ = np.zeros((len(rate_flow), len(variables)))
        for junction_ix, junction_flow in rate_flow.items():
            for step, flow in junction_flow.items():
                rate_flow_[junction_ix, variables.index(step)] = flow

        return rate_flow_, variables, outbound


class Step:
    index = 0

    def __init__(self, recipe: DictProxy):
        self.index = Step.index
        Step.index = self.index + 1

        # self.machine = machine if machine else Machine()
        self.recipe = Recipe(recipe)

        # push maps inputs to producers (in order of priority?)
        self.pull: Dict[Item, List[Union["Step", "Buffer"]]] = {}
        # push maps outputs to consumers (in order of priority?)
        self.push: Dict[Item, List[Union["Step", "Buffer"]]]  = {}

        # group points to the cycle this step is part of, if any
        self.group: Optional[Group] = None

        # rate is the fraction of active machines in this step
        self.rate: float = 0.0

    def __str__(self):
        return f"Step {self.index}"

    def __repr__(self):
        return str(self)
    
    def push_to(self, target, item):
        x = self.push.setdefault(item, [])
        if target not in x:
            x.append(target)

    def propagate(self, cause: Union[None, "Step", "Buffer"]=None, rate=1.0):
        if self.group:
            if not cause or cause == self:
                self.group.propagate(self, rate)
                return
            else:
                raise RuntimeError("That's bad...")

        self.rate = rate

        for item in self.recipe.consume:
            flow = rate * self.recipe.inrate(item)

            try:
                target = self.pull[item][0] # default to the first because what else
            except Exception as exc:
                raise RuntimeError(f"{self} is missing a source of {item}") from exc

            if target is not cause:
                target.propagate_item(item, self, PUSH, flow)

        for item in self.recipe.produce:
            flow = rate * self.recipe.outrate(item)

            try:
                target = self.push[item][0] # default to the first because what else
            except Exception as exc:
                raise RuntimeError(f"{self} is missing a destination for {item}") from exc
            
            if target is not cause:
                target.propagate_item(item, self, PULL, flow)

    def propagate_item(self, item, cause: Union[None, "Step", "Buffer"]=None, push=PULL, flow=1.0):
        # note, push refers to whether self is pushing
        # so not push indicates whether cause is pushing

        # print("propagate_item:", self, item, cause, push, flow)

        if not cause:
            cause = self

        if self.group:
            x = cause , not push , item
            self.group.propagate(x, -flow if push else flow)
        else:
            if push:
                rate = flow / self.recipe.outrate(item)
            else:
                rate = flow / self.recipe.inrate(item)

            self.propagate(cause=cause, rate=rate)


class Buffer:
    def __init__(self, name="Buffer"):
        self.name = name
        self.flow = {}
        self.pull = {}
        self.push = {}

    def __str__(self):
        return self.name

    def __repr__(self):
        return str(self)

    def propagate_item(self, item, _, push, flow):
        self.flow[item] = -flow if push else flow


def make_groups(nodes, sccs):
    for group in sccs:
        g = Group(group)

        if len(group) > 1:
            for step in group:
                step.group = g





# class Qty:
#     def __init__(self, num=0):  # item=NULL_ITEM, prob=1):
#         self.number = num
#         #self.probability = prob
#         #self.item        = item

#     def __str__(self):
#         return f"{self.number}"  # @ {self.probability}"

#     def __repr__(self):
#         return str(self)



# class Recipe:
#     def __init__(self, consume=None, produce=None, duration=None, power=None):
#         # a recipe can eat something and return it again
#         # self.signature = signature if signature else {}
#         self.consume: Dict[Item, int] = consume if consume else {}
#         self.produce: Dict[Item, int] = produce if produce else {}

#         # duration maps a valid machine to the duration of this recipe in that machine
#         self.duration = duration if duration else 1

#         # the same for power
#         self.power = power if power else 1

#     def signature(self):
#         x = {}
#         x.update(self.consume)
#         x.update(self.produce)

#         return x

#     def __str__(self):
#         raise NotImplementedError()

#     def __repr__(self):
#         return str(self)