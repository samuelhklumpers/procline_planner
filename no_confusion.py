import pickle

from dictproxy import wrap
##
##print("Loading...")
##recipes = wrap({})
##with open("recipes.pickle", mode="rb") as fp:
##    recipes_by_machine = wrap(pickle.load(fp)).sources[0]["machines"]
##
##    for machine in recipes_by_machine:
##        recipes[machine.n] = machine.recs
##    
##recipes = recipes['Assembler']
##
##print("Sorting...")
##by_circuit = {}
##for r in recipes:
##    ingredients = r.iI
##    circuit = 0
##
##    non_circuits = []
##    
##    invalid = False
##    for item in ingredients:
##        if not item.uN:
##            invalid = True
##            break
##            
##        if item.uN == "gt.integrated_circuit":
##            circuit = item.cfg
##        elif item.uN == "item.BioRecipeSelector":
##            circuit = 100 # can't detect this circuit number :(
##        elif item.uN == "item.T3RecipeSelector":
##            circuit = 200
##        else:
##            non_circuits.append(item.uN)
##    
##    if r.fI.unwrap() and r.fI[0].uN:
##        non_circuits.append(r.fI[0].uN)
##    
##    if invalid:
##        continue
##        
##    by_circuit.setdefault(circuit, []).append(tuple(sorted(non_circuits)))
##
##    
##def trie(memo, path, previous):
##    if not path:
##        return {}, {}
##
##    if path in memo:
##        return memo, memo[path]
##    memo[path] = previous
##        
##    subtrie = {}
##    previous[path[0]] = subtrie
##    trie(memo, path[1:], subtrie)
##   
##
##print("Calculating tries...") 
##trie_by_circuit = {}
##for circuit, recipes in by_circuit.items():
##    memo     = {}
##    previous = {}
##    
##    for recipe in recipes:
##        trie(memo, recipe, previous)
##
##    trie_by_circuit[circuit] = previous
##
##
##def trie_contains(t, path):
##    if not path:
##        return True
##        
##    if path[0] in t:
##        return trie_contains(t[path[0]], path[1:])
##    
##    return False
##
##
##print("Finding overlaps...")
##confusion = {}
##for c1, ctrie in trie_by_circuit.items():
##    for c2, recipes in by_circuit.items():
##        if c1 == c2:
##            continue
##            
##        overlap = False
##        for recipe in recipes:
##            if trie_contains(ctrie, recipe):
##                overlap = recipe
##                print(c1, c2, recipe)
##                break
##        
##        confusion.setdefault(c1, {})[c2] = overlap
##
##with open("confusion.pickle", mode="wb") as fp:
##    pickle.dump(confusion, fp)
    
with open("confusion.pickle", mode="rb") as fp:
    confusion = pickle.load(fp)


##import networkx as nx
##import matplotlib.pyplot as plt
##
##G = nx.Graph()
##
##for c1, c2s in confusion.items():
##    for c2, reason in c2s.items():
##        if reason:
##            G.add_edge(c1, c2)
##        
##G_ = nx.complement(G)
##
##        
##nx.draw(G_, with_labels=True, pos=nx.drawing.kamada_kawai_layout(G_))
##plt.show()

for c1 in sorted(confusion):
    c2s = confusion[c1]

    print(c1, "cannot be used safely with:")
    for c2 in sorted(c2s):
        overlap = c2s[c2]
        if overlap:
            print(c1, c2, overlap)
    print()
print()

for c1 in confusion:
    c2s = confusion[c1]
    for c2, overlap in c2s.items():
        if overlap:
            confusion.setdefault(c2, {})[c1] = overlap

for c1 in sorted(confusion):
    c2s = confusion[c1]

    print(c1, "can be used safely with:")
    for c2 in sorted(c2s):
        overlap = c2s[c2]
        if not overlap:
            print("", c2)
    print()

