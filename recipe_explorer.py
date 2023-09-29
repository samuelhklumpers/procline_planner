import pickle

from dictproxy import wrap


recipes = wrap({})
with open("recipes.pickle", mode="rb") as fp:
    recipes_by_machine = wrap(pickle.load(fp)).sources[0]["machines"]

    for machine in recipes_by_machine:
        recipes[machine.n] = machine.recs

items = wrap({})
with open("items.pickle", mode="rb") as fp:
    items = wrap(pickle.load(fp))
