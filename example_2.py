from throughput import *

step1 = Step()
step2 = Step()
step3 = Step()
AE = Buffer("AE")

LCR = Machine("LCR")

Si    = Item(1)
Cl    = Item(2)
SiCl4 = Item(3)
Na    = Item(4)
SSi   = Item(5)
NaCl  = Item(6)

Si_SiCl4 = Recipe({Si : Qty(1), Cl : Qty(4000),
                   SiCl4 : Qty(-1000)},
                  duration = {LCR : 1},
                  power    = {LCR : 1})

SiCl4_SSi = Recipe({SiCl4 : Qty(1000), Na : Qty(4),
                    SSi : Qty(-1), NaCl : Qty(-8)},
                   duration = {LCR : 1},
                   power    = {LCR : 1})

NaCl_Cl = Recipe({NaCl : Qty(2),
                  Na : Qty(-1), Cl : Qty(-1000)},
                   duration = {LCR : 1},
                   power    = {LCR : 1})

step1.machine = LCR
step1.recipe  = Si_SiCl4

step2.machine = LCR
step2.recipe  = SiCl4_SSi

step3.machine = LCR
step3.recipe  = NaCl_Cl

step1.pull[Si]    = [AE]
step1.pull[Cl]    = [step3]
step1.push[SiCl4] = [step2]

step2.pull[SiCl4] = [step1]
step2.pull[Na]    = [step3]
step2.push[SSi]   = [AE]
step2.push[NaCl]  = [step3]

step3.pull[NaCl]  = [step2]
step3.push[Na]    = [step2]
step3.push[Cl]    = [step1]

AE.push[Si] = [step1]
AE.pull[Cl] = [step3]

from tscca import tarjan

nodes = [step1, step2, step3, AE]
sccs = tarjan(nodes)

print(sccs)
