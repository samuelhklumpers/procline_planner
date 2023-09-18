from numpy.linalg import lstsq


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
        return f"{self.number} x {self.item} @ {self.probability}"

    def __repr__(self):
        return str(self)
        
class Recipe:
    def __init__(self, signature=None, duration=None, power=None):
        self.signature = signature if signature else {}

        # duration maps a valid machine to the duration of this recipe in that machine 
        self.duration = duration if duration else {}

        # the same for power
        self.power    = power if power else {}

    def __str__(self):
        raise NotImplementedError()

    def __repr__(self):
        return str(self)

class Group:
    def __init__(self, steps=None):
        self.steps = steps if steps else []

    def __repr__(self):
        return str(self)

    """def neighbourhood(self):
        neighs = set()

        for step in self.steps:
            for targets in step.pull.values():
                for target in targets:
                    neighs.add(target)

        return neighs.difference(self.steps)"""

    def junction(self, start, push, tag):
        # a junction identifies a cluster of nodes all sharing the resource `tag`
        junction = set([start])
        q = [(start, push)]
        
        while q:
            node, push = q.pop()

            opposites = node.push if push else node.pull

            for opp in opposites[tag]:
                if opp not in junction:
                    q.append((opp, not push))
                    junction.add(opp)
        
    def matrix(self):
        # the matrix of a group represents the total flow of a group
        # given an input vector of rates.
        # internal flows should add up to zero,
        # external flows can be varied.
        
        A = {}

        variables = []
        results   = []

        junctions = {}
        j = 0

        for step in self.steps:
            variables.append(step)
            ...
            
            

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

    def propagate(self, cause=None, rate=1):
        if self.group:
            raise NotImplementedError("cycles are hard")

        self.rate = rate
        duration = self.recipe.duration[self.machine]

        for x, q in self.recipe.signature.items():
            flow = rate * q.number / duration

            # self.pull[x][0], because we don't handle splitting yet
            target = self.pull[x][0] if q.number < 0 else self.push[x][0]
            if target is not cause:
                target.propagate_item(x, self, -flow)

    def propagate_item(self, item, cause, flow):
        rate = flow / self.recipe.signature[item].number * self.recipe.duration[self.machine]
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
