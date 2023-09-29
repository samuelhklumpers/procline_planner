from throughput import *
from tscca import tarjan

step0 = Step()
step1 = Step()
step2 = Step()
step3 = Step()

LCR = Machine("LCR")

Si    = Item(1)
Cl    = Item(2)


step0.push[Si]    = [step1]
step0.push[Cl]    = [step2]

step1.pull[Si] = [step0]
step1.push[Si]  = [step3]

step2.pull[Cl]  = [step0]
step2.push[Cl]    = [step3]

step3.pull[Si]    = [step1]
step3.pull[Cl]    = [step2]

from tscca import tarjan

nodes = [step0, step1, step2, step3]
sccs = tarjan(nodes)

make_groups(nodes, sccs)

print(sccs)