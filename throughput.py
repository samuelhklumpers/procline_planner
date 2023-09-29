from typing import Dict, Optional, Union
from numpy.linalg import lstsq
import numpy as np


class Machine:
    def __init__(self, name="Machine"):
        self.name = name
        # nothing else, the duration and power usage are in the recipes

    def __str__(self):
        return self.name

    def __repr__(self):
        return str(self)


class Item:
    def __init__(self, tag=0):
        self.tag = tag

    def __str__(self):
        return str(self.tag)

    def __repr__(self):
        return str(self)


NULL_ITEM = Item()


class Qty:
    def __init__(self, num=0):  # item=NULL_ITEM, prob=1):
        self.number = num
        #self.probability = prob
        #self.item        = item

    def __str__(self):
        return f"{self.number}"  # @ {self.probability}"

    def __repr__(self):
        return str(self)


class Recipe:
    def __init__(self, consume=None, produce=None, duration=None, power=None):
        # a recipe can eat something and return it again
        # self.signature = signature if signature else {}
        self.consume = consume if consume else {}
        self.produce = produce if produce else {}

        # duration maps a valid machine to the duration of this recipe in that machine
        self.duration = duration if duration else 1

        # the same for power
        self.power = power if power else 1

    def signature(self):
        x = {}
        x.update(self.consume)
        x.update(self.produce)

        return x

    def __str__(self):
        raise NotImplementedError()

    def __repr__(self):
        return str(self)


class Group:
    def __init__(self, steps=None):
        self.steps = steps if steps else []
        self.junctions = {}

    def __repr__(self):
        return str(self.steps)

    def propagate(self, item=None, cause=None, flow=1.0):
        if cause is None:
            raise RuntimeError(
                "How can a group propagate without knowing where its propagating to/from?")

        mat, x, border, causes, buffs, buffs_r = self.matrix()

        if isinstance(cause, Buffer):
            if item is None:
                raise RuntimeError("A buffer doesn't have a rate")

            push = flow < 0
            # print(buffs)
            # print(cause, push, item)
            cause_ = buffs[cause][push][item]
            cause_rate = 1.0
        else:
            cause_ = cause
            if item is None:
                cause_rate = 1.0
            else:
                if flow > 0:
                    cause_rate = cause.recipe.produce[item].number / \
                        cause.recipe.duration[cause.machine]
                else:
                    cause_rate = -flow / \
                        cause.recipe.consume[item].number / \
                        cause.recipe.duration[cause.machine]

        i = x.index(cause_)
        mat = np.pad(mat, ((0, 1), (0, 0)))
        mat[-1][i] = cause_rate

        vy = np.zeros(mat.shape[0])
        vy[-1] = flow

        # print(x)
        # print(y)
        # print(mat)
        # print(vy)

        # print(mat.shape)

        vx, res, _, _ = lstsq(mat, vy, rcond=None)

        if res.sum() > 1e-15:
            print("warning high residual in cycle solution, results might be wrong")

        # print(vx)
        for step, rateflow in zip(x, vx):
            # print(step, rateflow)
            if step in self.steps and isinstance(step, Step):
                step.rate = rateflow
            elif step != cause_:
                k = border[step]

                if isinstance(step, int):
                    step = buffs_r[step]

                step.propagate_item(k, causes[step], rateflow)

    def neighbourhood(self):
        neighs = set()

        for step in self.steps:
            for targets in step.pull.values():
                for target in targets:
                    neighs.add(target)

        return neighs.difference(self.steps)

    def junction(self, start, push, tag):
        # a junction identifies a cluster of nodes all sharing the resource `tag`
        junction = set([(start, push)])
        q = [(start, push)]

        while q:
            node, push = q.pop()

            opposites = node.push if push else node.pull

            for opp in opposites.get(tag, []):
                x = (opp, not push)
                if x not in junction:
                    q.append(x)
                    junction.add(x)

        return junction

    def matrix(self):
        # returns the matrix A representing this group in the sense
        # A: Step -> Junction -> Flow/Rate
        A: Dict[Union[Step, int], Dict[int, float]] = {}
        # where each Junction represents an intersection of multiple machine outputs of the same item type
        # junctions: Step -> Output? -> Item -> Junction Index
        junctions: Dict[Union[Step, Buffer, int],
                        Dict[bool, Dict[Item, int]]] = {}
        self.junctions = junctions

        # given a vector of rates x, the total flow is then A^T x (oops)

        # internal flows should add up to zero,
        # external flows can be varied.

        # note: we represent internal rates, but external flows
        # this works, because if an external node had two connections, requiring us to use rates, it would not be external, but in this cycle.

        # causes: Step -> Step, which associates a step x on the border with the node of this group that will cause the propagation to x
        causes: Dict[Step, Step] = {}
        # j is the next junction index
        j = 0

        for step in self.steps:
            duration = step.duration()

            # first we mark all incoming flow
            junct_step = junctions.setdefault(step, {})
            junct_step_pull = junct_step.setdefault(False, {})
            junct_step_push = junct_step.setdefault(True, {})

            for item, qty in step.recipe.consume.items():
                # get the junction the resource k comes from
                j_k = junct_step_pull.get(item)

                if j_k is None:
                    # if it doesn't exist yet, find the nodes connected to the junction
                    # declare a new junction
                    j_k = j
                    k_neighbours = self.junction(step, False, item)

                    for neighbour, push in k_neighbours:
                        # and mark the corresponding flow of k in each node accordingly
                        junct_neigh = junctions.setdefault(
                            neighbour, {}).setdefault(push, {})

                        if item in junct_neigh:
                            raise RuntimeError(
                                f"how did {item} get into {junct_neigh}?")

                        junct_neigh[item] = j

                        if neighbour not in self.steps:
                            causes[neighbour] = step

                    j += 1

                A_step = A.setdefault(step, {})
                if j_k in A_step:
                    raise RuntimeError(f"how did {j_k} get into {A_step}?")

                A_step[j_k] = qty.number / duration

            # then we mark all outgoing flow
            for item, qty in step.recipe.produce.items():
                # get the junction the resource k goes to
                j_k = junct_step_push.get(item)

                if j_k is None:
                    # if it doesn't exist yet, find the nodes connected to the junction
                    # declare a new junction
                    j_k = j
                    k_neighbours = self.junction(step, True, item)

                    for neighbour, push in k_neighbours:
                        # and mark the corresponding flow of k in each node accordingly
                        junct_neigh = junctions.setdefault(
                            neighbour, {}).setdefault(push, {})

                        if item in junct_neigh:
                            raise RuntimeError(
                                f"how did {item} get into {junct_neigh}?")

                        junct_neigh[item] = j

                        if neighbour not in self.steps:
                            causes[neighbour] = step

                    j += 1

                A_step = A.setdefault(step, {})
                if j_k in A_step:
                    raise RuntimeError(f"how did {j_k} get into {A_step}?")
                A_step[j_k] = qty.number / duration

        qty = 0
        buffs = {}
        buffs_r = []

        border = {}
        j_k = 0
        A_step = {}

        for step in self.neighbourhood():
            if isinstance(step, Step):
                junct_step = junctions.setdefault(step, {})
                junct_step_pull = junct_step.setdefault(False, {})
                junct_step_push = junct_step.setdefault(True, {})

                xs_pull = list(junct_step_pull.values())
                xs_push = list(junct_step_push.values())

                if xs_pull:
                    border[step] = list(junct_step_pull.keys())[0]
                elif xs_push:
                    border[step] = list(junct_step_push.keys())[0]

                xs = xs_pull + xs_push
                if len(xs) != 1:
                    raise RuntimeError(
                        f"{step} is not part of this cycle, but doubly connected!")
                A_step = A.setdefault(step, {})
                A_step[xs[0]] = 1  # TODO ?
            elif isinstance(step, Buffer):
                junct_step = junctions.setdefault(step, {})
                junct_step_pull = junct_step.setdefault(False, {})
                junct_step_push = junct_step.setdefault(True, {})

                for item, j_k in junct_step_pull.items():
                    A_step = A.setdefault(qty, {})
                    A_step[j_k] = 1
                    buffs.setdefault(step, {}).setdefault(
                        False, {}).setdefault(item, qty)
                    buffs_r.append(step)
                    border[qty] = item
                    qty += 1

                for item, j_k in junct_step_push.items():
                    A_step = A.setdefault(qty, {})
                    A_step[j_k] = 1
                    buffs.setdefault(step, {}).setdefault(
                        True, {}).setdefault(item, qty)
                    buffs_r.append(step)
                    border[qty] = item

                    qty += 1
            else:
                raise RuntimeError(f"how did {j_k} get into {A_step}?")

        variables = list(A.keys())
        B = np.zeros((j, len(variables)))

        for i, neighbour in enumerate(variables):
            A_step = A[neighbour]
            for item, f in A_step.items():
                B[item, i] = f

        return B, variables, border, causes, buffs, buffs_r


class Step:
    index = 0

    def __init__(self, machine=None, recipe=None):
        self.index = Step.index
        Step.index = self.index + 1

        self.machine = machine if machine else Machine()
        self.recipe = recipe if recipe else Recipe()

        # push maps inputs to producers, in order of priority?
        self.pull = {}
        # push maps outputs to consumers, in order of priority?
        self.push = {}

        # group points to the cycle this step is part of, if any
        self.group: Optional[Group] = None

        # rate is the fraction of active machines in this step
        self.rate = 0

    def __str__(self):
        return f"Step {self.index}"

    def __repr__(self):
        return str(self)

    def duration(self):
        return self.recipe.duration

    def propagate(self, cause=None, rate=1.0):
        if not cause:
            cause = self

        if self.group:
            self.group.propagate(None, cause, rate)

        self.rate = rate
        duration = self.duration()

        for x, q in self.recipe.consume.items():
            flow = rate * q.number / duration

            target = self.pull[x][0]
            if target is not cause:
                target.propagate_item(x, self, flow)

        for x, q in self.recipe.produce.items():
            flow = rate * q.number / duration

            target = self.push[x][0]
            if target is not cause:
                target.propagate_item(x, self, -flow)

    def propagate_item(self, item, cause=None, flow=1.0):
        if not cause:
            cause = self

        if self.group:
            self.group.propagate(item, cause, flow)
        else:
            if flow > 0:
                rate = flow / \
                    self.recipe.produce[item].number * self.recipe.duration
            else:
                rate = -flow / \
                    self.recipe.consume[item].number * self.recipe.duration

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

    def propagate_item(self, item, cause, flow):
        self.flow[item] = flow


def make_groups(nodes, sccs):
    for group in sccs:
        g = Group(group)

        if len(group) > 1:
            for step in group:
                step.group = g
