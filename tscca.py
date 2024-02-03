
from throughput import Step

class Wrap:
    def __init__(self, value):
        self.value = value

def circuits(nodes):
    nodes = [v for v in nodes if isinstance(v, Step)]

    edge = 0
    for v in nodes:
        v.suc = {} # type: ignore

    for v in nodes:
        for ws in list(v.pull.values()) + list(v.push.values()):
            for w in ws:
                if isinstance(w, Step):
                    if v in w.suc: # type: ignore
                        v.suc[w] = w.suc[v] # type: ignore
                    else:
                        v.suc.setdefault(w, []).append(edge) # type: ignore
                        edge += 1

    index = Wrap(0)
    S     = []
    sccs  = []

    def strongconnect(v):
        # Set the depth index for v to the smallest unused index
        indices[v] = index.value
        lowlink[v] = index.value
        
        index.value = index.value + 1
        S.append(v)
        onStack[v] = True
      
        # Consider successors of v
        def step(w):
            if w not in indices:
                # Successor w has not yet been visited; recurse on it
                strongconnect(w)
                lowlink[v] = min(lowlink[v], lowlink[w])
            elif onStack[w]:
                # Successor w is in stack S and hence in the current SCC
                # If w is not on stack, then (v, w) is an edge pointing to an SCC already found and must be ignored
                # Note: The next line may look odd - but is correct.
                # It says w.index not w.lowlink; that is deliberate and from the original paper
                lowlink[v] = min(lowlink[v], indices[w])
        
        for w, edges in v.suc.items(): # type: ignore
            e = None
            for e_ in edges:
                if e_ not in path:
                    e = e_
                    break
            
            if e is not None:
                path.append(e)
                step(w)
                path.pop()

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
    path    = []
    
    for v in nodes:
        if v not in indices:
            strongconnect(v)

    return sccs

# https://en.wikipedia.org/wiki/Tarjan's_strongly_connected_components_algorithm#The_algorithm_in_pseudocode
