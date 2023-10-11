"""recipes.py"""

import json
import os
import pickle

from typing import List, Dict

from dictproxy import DictProxy, wrap
from throughput import Recipe, Machine


class Recipes:
    """Recipes"""

    def __init__(self):
        self.recipes_by_input = {}
        self.recipes_by_output = {}
        self.recipes_by_machine = {}
        self.recipes_by_machine_by_input = {}
        self.recipes_by_machine_by_output = {}
        self.itemlist = {}
        self.id_to_item = {}
        self.load()

    def load(self):
        """load"""
        if os.path.exists("recipes.pickle"):
            with open("recipes.pickle", mode="rb") as fp:
                recipes = pickle.load(fp)
        else:
            with open("recipes.json", mode="r", encoding="utf-8") as fp:
                recipes = json.load(fp)

            with open("recipes.pickle", mode="wb") as fp:
                pickle.dump(recipes, fp)

        recipes = wrap(recipes)
        recipes_by_machine = recipes.sources[0]["machines"]

        for machine in recipes_by_machine:
            self.recipes_by_machine[machine.n] = machine.recs

        self.recipes_by_machine["None"] = []

        self.recipes_by_machine_by_input = {}
        self.recipes_by_machine_by_output = {}

        self.recipes_by_input = {}
        self.recipes_by_output = {}

        for machine, recipes in self.recipes_by_machine.items():
            by_input = self.recipes_by_machine_by_input[machine] = {}
            by_output = self.recipes_by_machine_by_output[machine] = {}

            for recipe in recipes:
                for item in recipe.iI:
                    by_input.setdefault(item.uN, []).append(recipe)
                for item in recipe.fI:
                    by_input.setdefault(item.uN, []).append(recipe)
                for item in recipe.iO:
                    by_output.setdefault(item.uN, []).append(recipe)
                for item in recipe.fO:
                    by_output.setdefault(item.uN, []).append(recipe)

        try:
            with open("items.pickle", mode="rb") as fp:
                self.itemlist, self.id_to_item = wrap(pickle.load(fp))
        except (OSError, KeyError, ValueError, TypeError):
            items = {}
            id_to_item = {}

            for _, recipes in self.recipes_by_machine.items():
                for recipe in recipes:
                    for item in recipe.iI:
                        ids = items.setdefault(item.lN, [])
                        id_to_item.setdefault(item.uN, item.lN)
                        if item.uN not in ids:
                            ids.append(item.uN)

                    for item in recipe.iO:
                        ids = items.setdefault(item.lN, [])
                        id_to_item.setdefault(item.uN, item.lN)
                        if item.uN not in ids:
                            ids.append(item.uN)

                    for item in recipe.fI:
                        ids = items.setdefault(item.lN, [])
                        id_to_item.setdefault(item.uN, item.lN)
                        if item.uN not in ids:
                            ids.append(item.uN)

                    for item in recipe.fO:
                        ids = items.setdefault(item.lN, [])
                        id_to_item.setdefault(item.uN, item.lN)
                        if item.uN not in ids:
                            ids.append(item.uN)

            self.id_to_item = id_to_item
            self.itemlist = wrap(items)

            with open("items.pickle", mode="wb") as fp:
                pickle.dump((items, id_to_item), fp)

        self.itemlist[""] = "null"
        self.id_to_item[""] = ""

    def item_name(self, item_id):
        """load"""
        return self.id_to_item[item_id]

    def recipe_id(self, machine, recipe: DictProxy):
        """load"""
        return self.recipes_by_machine[machine].index(recipe)

    def recipe_by_id(self, machine, recipe_id) -> Recipe:
        """load"""
        return Recipe(self.recipes_by_machine[machine][recipe_id])

    def search_machine_recipe(self, inputs: List[str], outputs: List[str]) \
          -> Dict[Machine, List[Recipe]]:
        """load"""
        recipes = {}
        for machine in self.recipes_by_machine:
            results = self.search_recipe(machine, inputs, outputs)

            if results:
                recipes[machine] = results

        return recipes

    def search_recipe(self, machine: str, inputs: List[str], outputs: List[str]) -> List[Recipe]:
        """load"""
        # TODO low: fast(er?) recipe search

        try:
            if inputs:
                candidates = self.recipes_by_machine_by_input[machine][inputs[0]]
                inputs = inputs[1:]
            elif outputs:
                candidates = self.recipes_by_machine_by_output[machine][outputs[0]]
                outputs = outputs[1:]
            else:
                candidates = self.recipes_by_machine[machine]
        except KeyError:
            return []

        def match(is_input, item):
            key = "I" if is_input else "O"
            keyi = "i" + key
            keyf = "f" + key

            def match_(candidate):
                for qty in candidate[keyi]:
                    if item == qty.uN:
                        return True
                for qty in candidate[keyf]:
                    if item == qty.uN:
                        return True
                return False
            return match_

        for item in inputs:
            candidates = filter(match(True, item), candidates)

        for item in outputs:
            candidates = filter(match(False, item), candidates)

        return [Recipe(r) for r in candidates]
