from throughput import *

step1 = Step()
step2 = Step()
AE = Buffer("AE")

LCR = Machine("LCR")

H    = Item(1)
N    = Item(2)
O    = Item(3)
NH3  = Item(4)
HNO3 = Item(5)
H2O  = Item(6)

H_N_HN3  = Recipe({H : Qty(-3000), N : Qty(-1000),
                   NH3 : Qty(1000)},
                  duration = {LCR : 16},
                  power = {LCR : 384})

HN3_HNO3 = Recipe({NH3 : Qty(-1000), O : Qty(-4000),
                   HNO3 : Qty(1000), H2O : Qty(1000)},
                  duration = {LCR : 16},
                  power = {LCR : 30})

step1.machine = LCR
step1.recipe  = H_N_HN3

step2.machine = LCR
step2.recipe  = HN3_HNO3

step1.pull[H]   = [AE]
step1.pull[N]   = [AE]
step1.push[NH3] = [step2]

step2.pull[O]    = [AE]
step2.pull[NH3]  = [step1]
step2.push[HNO3] = [AE]
step2.push[H2O]  = [AE]

AE.push[H] = [step1]
AE.push[N] = [step1]
AE.push[O] = [step2]
AE.pull[HNO3] = [step2]
AE.pull[H2O]  = [step2]

step2.propagate_item(HNO3, None, 1000)
print("flows:", AE.flow)

from tscca import tarjan

nodes = [step1, step2, AE]
sccs = tarjan(nodes)

print(sccs)
