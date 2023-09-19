from throughput import *

step0 = Step()
step1 = Step()
step2 = Step()
AE = Buffer("AE")

LCR = Machine("LCR")

Si    = Item(1)
Cl    = Item(2)
SiCl4 = Item(3)
Na    = Item(4)
SSi   = Item(5)
NaCl  = Item(6)

Si_SiCl4 = Recipe({Si : Qty(1), Cl : Qty(4000)},
                  {SiCl4 : Qty(-1000)},
                  duration = {LCR : 1},
                  power    = {LCR : 1})

SiCl4_SSi = Recipe({SiCl4 : Qty(1000), Na : Qty(4)},
                   {SSi : Qty(-1), NaCl : Qty(-8)},
                   duration = {LCR : 1},
                   power    = {LCR : 1})

NaCl_Cl = Recipe({NaCl : Qty(2)},
                 {Na : Qty(-1), Cl : Qty(-1000)},
                  duration = {LCR : 1},
                  power    = {LCR : 1})

step0.machine = LCR
step0.recipe  = Si_SiCl4

step1.machine = LCR
step1.recipe  = SiCl4_SSi

step2.machine = LCR
step2.recipe  = NaCl_Cl

step0.pull[Si]    = [AE]
step0.pull[Cl]    = [step2]
step0.push[SiCl4] = [step1]

step1.pull[SiCl4] = [step0]
step1.pull[Na]    = [step2]
step1.push[SSi]   = [AE]
step1.push[NaCl]  = [step2]

step2.pull[NaCl]  = [step1]
step2.push[Na]    = [step1]
step2.push[Cl]    = [step0]

AE.push[Si] = [step0]
AE.pull[SSi] = [step1]

from tscca import tarjan

nodes = [step0, step1, step2, AE]
sccs = tarjan(nodes)

make_groups(nodes, sccs)

step1.propagate_item(SSi, AE, 1)


#print(sccs)

#group1 = Group(sccs[0])
#mat, x, y, buffs = group1.matrix()

#print(mat)
#print(x)
#print(y)
#print(buffs)
