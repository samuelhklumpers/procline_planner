# https://en.wikipedia.org/wiki/Tarjan's_strongly_connected_components_algorithm#The_algorithm_in_pseudocode

from throughput import Step

class Wrap:
    def __init__(self, value):
        self.value = value

def tarjan(nodes):
    index = Wrap(0)
    S     = []
    sccs  = []

    def strongconnect(v, cause=None, push=False):
        # print("s", v, cause, push)
        # cause: the node v is being strongconnected from
        # push: true if v is being strongconnected from cause.push,
        # false if from cause.pull
        
        # Set the depth index for v to the smallest unused index
        indices[v] = index.value
        lowlink[v] = index.value
        
        index.value = index.value + 1
        S.append(v)
        onStack[v] = True
      
        # Consider successors of v

        # This is different from the usual algorithm!
        # We have a directed graph,
        # but we can also go backwards,
        # provided we don't use the same edge twice
        suc_pull = list(v.pull.values())
        suc_push = list(v.push.values())

        suc_pull = [x for y in suc_pull for x in y if isinstance(x, Step)]
        suc_push = [x for y in suc_push for x in y if isinstance(x, Step)]

        if cause:
            if push:
                suc_pull.remove(cause)
            else:
                suc_push.remove(cause)

        # print(suc_pull)
        # print(suc_push)

        def step(w, push):
            # print("step", w, push)
            if w not in indices:
                # Successor w has not yet been visited; recurse on it
                strongconnect(w, v, push)
                lowlink[v] = min(lowlink[v], lowlink[w])
            elif onStack[w]:
                # Successor w is in stack S and hence in the current SCC
                # If w is not on stack, then (v, w) is an edge pointing to an SCC already found and must be ignored
                # Note: The next line may look odd - but is correct.
                # It says w.index not w.lowlink; that is deliberate and from the original paper
                lowlink[v] = min(lowlink[v], indices[w])
        
        for w in suc_pull:
            step(w, False)

        for w in suc_push:
            step(w, True)

        # If v is a root node, pop the stack and generate an SCC
        if lowlink[v] == indices[v]:
            # start a new strongly connected component
            scc = []
            
            w = S.pop()
            onStack[w] = False
            scc.append(w) # add w to current strongly connected component
            
            while w != v:
                w = S.pop()
                onStack[w] = False
                scc.append(w) # add w to current strongly connected component

            sccs.append(scc)

    indices = {}
    lowlink = {}
    onStack = {}
    
    for v in nodes:
        if v not in indices:
            strongconnect(v)

    return sccs
