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
    def __init__(self, num=0, #item=NULL_ITEM,
                 prob=1):
        self.number      = num
        #self.probability = prob
        #self.item        = item

    def __str__(self):
        return f"{self.number}" # @ {self.probability}"

    def __repr__(self):
        return str(self)
        
class Recipe:
    def __init__(self, consume=None, produce=None, duration=None, power=None):
        # oops actually a recipe can eat something and return it again
        # self.signature = signature if signature else {}
        self.consume = consume if consume else {}
        self.produce = produce if produce else {}

        # duration maps a valid machine to the duration of this recipe in that machine 
        self.duration = duration if duration else {}

        # the same for power
        self.power    = power if power else {}

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
        return str(self)

    def propagate(self, start, item, cause, flow):
        mat, x, border, causes, buffs, buffs_r = self.matrix()

        if isinstance(cause, Buffer):
            push = flow < 0
            # print(buffs)
            # print(cause, push, item)
            cause_ = buffs[cause][push][item]
        else:
            cause_ = cause


        i = x.index(cause_)
        mat = np.pad(mat, ((0, 1), (0, 0)))
        mat[-1][i] = 1

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
            if step in self.steps:
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
        # the matrix of a group represents the total flow of a group
        # given an input vector of rates.
        # internal flows should add up to zero,
        # external flows can be varied.

        # note: we represent internal rates, but external flows
        # this works, because if an external node had two connections, requiring us to use rates, it would not be external, but in this cycle.
        
        A = {}
        
        junctions = {}
        self.junctions = junctions
        j = 0

        causes = {}

        for step in self.steps:
            duration = step.duration()
            
            # first we mark all incoming flow
            step_junct = junctions.setdefault(step, {})
            pull_junct = step_junct.setdefault(False, {})
            push_junct = step_junct.setdefault(True, {})
            
            for k, v in step.recipe.consume.items():
                # get the junction the resource k comes from
                j_k = pull_junct.get(k)

                if j_k is None:
                    # if it doesn't exist yet, find the nodes connected to the junction
                    # declare a new junction
                    j_k = j
                    junct = self.junction(step, False, k)
                    # print(k, junct)
                
                    for s, p in junct:
                        # and mark the corresponding flow of k in each node accordingly
                        x = junctions.setdefault(s, {}).setdefault(p, {})

                        # print(s, p, k, j)
                        if k in x:
                            raise RuntimeError(f"how did {k} get into {x}?")

                        x[k] = j

                        if s not in self.steps:
                            causes[s] = step
                            
                        # print(junctions)
                        # print("p", push_junct)
            
                    j += 1

                R = A.setdefault(step, {})
                if j_k in R:
                    raise RuntimeError(f"how did {j_k} get into {R}?")
                R[j_k] = v.number / duration
            
            # then we mark all outgoing flow
            for k, v in step.recipe.produce.items():
                # get the junction the resource k goes to
                j_k = push_junct.get(k)
                # print("p", push_junct)
                # print(j_k)

                if j_k is None:
                    # if it doesn't exist yet, find the nodes connected to the junction
                    # declare a new junction
                    j_k = j
                    junct = self.junction(step, True, k)
                    # print(k, junct)

                    for s, p in junct:
                        # and mark the corresponding flow of k in each node accordingly
                        x = junctions.setdefault(s, {}).setdefault(p, {})
                        
                        # print(s, p, k, j)
                        if k in x:
                            raise RuntimeError(f"how did {k} get into {x}?")

                        x[k] = j

                        if s not in self.steps:
                            causes[s] = step
                        # print(junctions)
            
                    j += 1


                R = A.setdefault(step, {})
                if j_k in R:
                    raise RuntimeError(f"how did {j_k} get into {R}?")
                R[j_k] = v.number / duration

        v = 0
        buffs = {}
        buffs_r = []
        
        border = {}
        for step in self.neighbourhood():
            if isinstance(step, Step):
                step_junct = junctions.setdefault(step, {})
                pull_junct = step_junct.setdefault(False, {})
                push_junct = step_junct.setdefault(True, {})

                xs_pull = list(pull_junct.values())
                xs_push = list(push_junct.items())

                if xs_pull:
                    border[step] = list(pull_junct.keys())[0]
                elif xs_push:
                    border[step] = list(push_junct.keys())[0]

                xs = xs_pull + xs_push
                if len(xs) != 1:
                    raise RuntimeError(f"{step} is not part of this cycle, but doubly connected!")
                R[xs[0]] = 1

                
            elif isinstance(step, Buffer):
                step_junct = junctions.setdefault(step, {})
                pull_junct = step_junct.setdefault(False, {})
                push_junct = step_junct.setdefault(True, {})

                for k, j_k in pull_junct.items():
                    R = A.setdefault(v, {})
                    R[j_k] = 1
                    buffs.setdefault(step, {}).setdefault(False, {}).setdefault(k, v)
                    buffs_r.append(step)
                    border[v] = k
                    v += 1

                for k, j_k in push_junct.items():
                    R = A.setdefault(v, {})
                    R[j_k] = 1
                    buffs.setdefault(step, {}).setdefault(True, {}).setdefault(k, v)
                    buffs_r.append(step)
                    border[v] = k

                    v += 1
            else:
                raise RuntimeError(f"how did {j_k} get into {R}?")

        variables = list(A.keys())
        B = np.zeros((j, len(variables)))

        for i, s in enumerate(variables):
            R = A[s]
            for k, f in R.items():
                B[k, i] = f

        return B, variables, border, causes, buffs, buffs_r
                
class Step:
    index = 0
    
    def __init__(self, machine=None, recipe=None):
        self.index = Step.index
        Step.index = self.index + 1
        
        self.machine = machine if machine else Machine()
        self.recipe  = recipe if recipe else Recipe()

        # push maps inputs to producers, in order of priority?
        self.pull = {}
        # push maps outputs to consumers, in order of priority?
        self.push = {}

        # group points to the cycle this step is part of, if any
        self.group = None

        # rate is the fraction of active machines in this step
        self.rate = 0

    def __str__(self):
        return f"Step {self.index}"

    def __repr__(self):
        return str(self)

    def duration(self):
        return self.recipe.duration[self.machine]

    def propagate(self, cause=None, rate=1):
        if self.group:
            raise NotImplementedError("cycles are hard")

        self.rate = rate
        duration = self.duration()

        for x, q in self.recipe.signature().items():
            flow = rate * q.number / duration

            # self.pull[x][0], because we don't handle splitting yet
            target = self.pull[x][0] if q.number < 0 else self.push[x][0]
            if target is not cause:
                target.propagate_item(x, self, -flow)

    def propagate_item(self, item, cause, flow):
        if self.group:
            self.group.propagate(self, item, cause, flow)
        else:
            rate = flow / self.recipe.signature()[item].number * self.recipe.duration[self.machine]
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
